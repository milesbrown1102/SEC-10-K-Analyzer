"""
Offline integration test for the Bottleneck Scanner pipeline.

No network access is available in this sandbox (data.sec.gov, sec.gov, and
general internet are all blocked by org egress policy here), so every
network-touching function is monkeypatched with a fixture that mirrors the
real APIs' documented shapes. This exercises the full run_full_scan() ->
get_scan_results() path end-to-end against a temp SQLite db: CapEx series
math, bottleneck keyword detection, taxonomy-based supplier matching, and
market screener wiring, all the way through to what the FastAPI endpoint
would return. Miles should still run a real scan once this is on his
machine (network there is unrestricted) — this only proves the plumbing.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/tmp/sec10k_improve")

import backend.db as db

db.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
db.init_db()

from backend import (
    capex_pipeline, bottleneck_detector, supplier_matcher, market_screener,
    deal_monitor, scanner_pipeline,
)


# ---------------------------------------------------------------------------
# Fixtures mirroring real API shapes
# ---------------------------------------------------------------------------

FAKE_CIKS = {"NVDA_PARENT": "0000000001"}  # not used directly; see monkeypatch below

FAKE_COMPANYFACTS = {
    "facts": {
        "us-gaap": {
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {
                    "USD": [
                        {"start": "2022-07-01", "end": "2023-06-30", "val": 28_107_000_000, "form": "10-K"},
                        {"start": "2023-07-01", "end": "2024-06-30", "val": 44_477_000_000, "form": "10-K"},
                    ]
                }
            }
        }
    }
}

FAKE_FILING_TEXT = """
Item 7. Management's Discussion and Analysis

We have experienced unprecedented supply constraints regarding critical
AI accelerator components, and material backlogs for critical deployment
components including high-density enterprise flash storage arrays.
Extended lead times for hardware integration are pacing deployment of our
data center capacity. We are also focused on securing baseload power for
our facilities.

Item 1A. Risk Factors

Our business depends on uninterrupted, high-density energy resources being
available for our data centers.
"""


def _fake_get_cik_for_ticker(ticker, session):
    return {"MSFT": "0000789019", "META": "0001326801"}.get(ticker)


def _fake_get_recent_10k_filing(cik, session):
    return {
        "form": "10-K",
        "filing_date": "2024-08-01",
        "accession_number": "000000000024000001",
        "primary_document": "fake-10k.htm",
    }


def _fake_fetch_filing_text(cik, filing, session):
    return FAKE_FILING_TEXT


def _fake_companyfacts(cik, session):
    return FAKE_COMPANYFACTS


class _FakeYfHistory:
    """Mimics a pandas DataFrame-ish object just enough for market_screener."""


def _install_monkeypatches(monkeypatch_module):
    import backend.sec_utils as sec_utils

    monkeypatch_module.setattr(sec_utils, "get_cik_for_ticker", _fake_get_cik_for_ticker)
    monkeypatch_module.setattr(sec_utils, "get_recent_10k_filing", _fake_get_recent_10k_filing)
    monkeypatch_module.setattr(sec_utils, "fetch_filing_text", _fake_fetch_filing_text)
    # capex_pipeline did `from sec_financial_data import fetch_companyfacts_raw`,
    # which binds its own local name — patching sec_financial_data's copy
    # wouldn't affect that already-bound reference, so patch capex_pipeline's
    # own module-level name instead.
    monkeypatch_module.setattr(capex_pipeline, "fetch_companyfacts_raw", _fake_companyfacts)
    monkeypatch_module.setattr(supplier_matcher, "check_for_spinoff_filings", lambda session: [
        {"company_name": "10-12B - Fake Spinoff Co (0001234567)",
         "filed_at": "2025-01-01T00:00:00-05:00",
         "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"},
    ])
    # Skip real yfinance entirely for this test — just prove the wiring
    # calls screen_many with the right tickers and stores results the same
    # way the real screen_ticker() would (via db.cache_set), since
    # get_scan_results() reads market data back out of that cache.
    def _fake_screen_many(tickers, force_refresh=False):
        out = {}
        for t in tickers:
            result = {"ticker": t, "price": 123.45, "relative_volume": 2.5, "sma_200": 100.0,
                      "above_200sma": True, "quarterly_revenue_growth_pct": 30.0,
                      "passes_all_filters": True, "error": None}
            db.cache_set("market_screen", t, result)
            out[t] = result
        return out

    monkeypatch_module.setattr(market_screener, "screen_many", _fake_screen_many)

    # Deal monitor (Pass 3): keep it fully offline here too. An empty 8-K
    # list and no news leads means run_full_scan's deal-monitor step still
    # runs (proving the wiring doesn't blow up) without asserting on its
    # content — deal_monitor.py's own tests cover the detection logic.
    monkeypatch_module.setattr(sec_utils, "get_recent_8k_filings", lambda cik, s, max_filings=5: [])
    monkeypatch_module.setattr(deal_monitor, "check_news_leads_for_ticker", lambda *a, **kw: [])


class _SimpleMonkeypatch:
    """Tiny stand-in for pytest's monkeypatch fixture (no pytest in this sandbox)."""

    def __init__(self):
        self._restores = []

    def setattr(self, obj, name, value):
        self._restores.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._restores):
            setattr(obj, name, old)


def test_capex_series_math():
    session = object()

    mp = _SimpleMonkeypatch()
    mp.setattr(capex_pipeline, "fetch_companyfacts_raw", _fake_companyfacts)
    try:
        series = capex_pipeline.get_capex_series("0000789019", session)
    finally:
        mp.undo()

    assert len(series) == 2, series
    assert series[0]["yoy_growth_pct"] is None
    expected_growth = round((44_477_000_000 - 28_107_000_000) / 28_107_000_000 * 100, 1)
    assert series[1]["yoy_growth_pct"] == expected_growth, series
    print(f"PASS test_capex_series_math (YoY growth = {expected_growth}%)")


def test_bottleneck_detection_finds_expected_categories():
    sections = {
        "mda": FAKE_FILING_TEXT,
        "risk_factors": FAKE_FILING_TEXT,
    }
    signals = bottleneck_detector.detect_bottleneck_signals(sections)
    categories = {s["category_key"] for s in signals}

    # "supply constraints regarding critical AI accelerator components"
    assert "ai_compute" in categories, categories
    # "material backlogs ... enterprise flash storage arrays"
    assert "memory_storage" in categories, categories
    # "lead times ... pacing deployment of our data center capacity"
    assert "datacenter_capacity" in categories, categories
    # "securing baseload power" / "depends on ... energy resources being available"
    assert "power_energy" in categories, categories
    print(f"PASS test_bottleneck_detection_finds_expected_categories ({categories})")


def test_supplier_matching_finds_flash_storage_and_power():
    entries, method = supplier_matcher.match_suppliers_for_signal(
        "material backlogs for critical deployment components including high-density "
        "enterprise flash storage arrays", use_llm=False
    )
    assert entries, "expected at least one taxonomy match"
    assert method == "keyword"
    all_suppliers = {t for e in entries for t in e["suppliers"]}
    assert "SNDK" in all_suppliers, entries
    print("PASS test_supplier_matching_finds_flash_storage_and_power")


def test_supplier_matching_ties_return_multiple_categories():
    # Regression test: this evidence ties between "AI / GPU compute" (2 hits:
    # 'accelerat', 'ai accelerator') and "Enterprise flash / NAND storage"
    # (2 hits: 'flash storage', 'storage array') — both should come back,
    # not just whichever is listed first in SUPPLIER_TAXONOMY.
    entries, method = supplier_matcher.match_suppliers_for_signal(
        "unprecedented supply constraints regarding critical AI accelerator "
        "components, and material backlogs for critical deployment components "
        "including high-density enterprise flash storage arrays",
        use_llm=False,
    )
    labels = {e["category_label"] for e in entries}
    assert "AI / GPU compute" in labels, labels
    assert "Enterprise flash / NAND storage" in labels, labels
    print(f"PASS test_supplier_matching_ties_return_multiple_categories ({labels})")


def test_supplier_matching_no_match_returns_empty():
    entries, method = supplier_matcher.match_suppliers_for_signal(
        "completely unrelated text about employee benefits and vacation policy",
        use_llm=False,
    )
    assert entries == []
    assert method == "none"
    print("PASS test_supplier_matching_no_match_returns_empty")


def test_full_pipeline_end_to_end():
    mp = _SimpleMonkeypatch()
    _install_monkeypatches(mp)

    import backend.sec_utils as sec_utils
    mp.setattr(sec_utils, "make_sec_session", lambda: object())

    try:
        run_id = scanner_pipeline.run_full_scan(["MSFT", "META"])
        results = scanner_pipeline.get_scan_results(run_id)
    finally:
        mp.undo()

    assert results["run"]["status"] == "completed", results["run"]
    assert set(results["watchlist"]) == {"MSFT", "META"}

    assert "MSFT" in results["capex"] and len(results["capex"]["MSFT"]) == 2, results["capex"]

    assert len(results["signals"]) >= 3, results["signals"]
    all_suppliers = {
        s["supplier_ticker"] for sig in results["signals"] for s in sig["suppliers"]
    }
    assert "SNDK" in all_suppliers, all_suppliers
    assert "VST" in all_suppliers, all_suppliers

    assert all_suppliers, "expected at least one matched supplier"
    for ticker in all_suppliers:
        assert ticker in results["market_data"], (ticker, results["market_data"])
        assert results["market_data"][ticker]["passes_all_filters"] is True

    assert len(results["spinoffs"]) == 1
    assert "Fake Spinoff Co" in results["spinoffs"][0]["company_name"]

    # Pass 3: deal monitor + buy scores are now part of the pipeline.
    assert "deals" in results and results["deals"] == [], results["deals"]  # mocked to empty
    assert "buy_scores" in results and results["buy_scores"], "expected a buy score per matched supplier"
    scored_tickers = {s["ticker"] for s in results["buy_scores"]}
    assert all_suppliers <= scored_tickers, (all_suppliers, scored_tickers)
    for s in results["buy_scores"]:
        assert 0 <= s["score"] <= 100, s
        assert s["score"] == sum(b["points"] for b in s["breakdown"]), s

    print("PASS test_full_pipeline_end_to_end "
          f"(run_id={run_id}, signals={len(results['signals'])}, suppliers={sorted(all_suppliers)}, "
          f"buy_scores={[(s['ticker'], s['score']) for s in results['buy_scores']]})")


if __name__ == "__main__":
    test_capex_series_math()
    test_bottleneck_detection_finds_expected_categories()
    test_supplier_matching_finds_flash_storage_and_power()
    test_supplier_matching_ties_return_multiple_categories()
    test_supplier_matching_no_match_returns_empty()
    test_full_pipeline_end_to_end()
    print("\nAll scanner integration tests passed.")
