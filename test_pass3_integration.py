"""
Offline integration tests for Pass 3: industry discovery, market-control
proxy, historical trend lookup, deal monitor, and buy scoring.

Same approach as test_scanner_integration.py — no network access in this
sandbox, so every network/LLM call is monkeypatched with a fixture
mirroring the real API's documented shape. Miles should still run these
for real once this is on his machine.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/tmp/sec10k_improve")

import backend.db as db

db.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
db.init_db()

from backend import (
    scoring, industry_classifier, supplier_matcher, historical_pipeline,
    deal_monitor, sec_utils, llm_client,
)


class _SimpleMonkeypatch:
    def __init__(self):
        self._restores = []

    def setattr(self, obj, name, value):
        self._restores.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._restores):
            setattr(obj, name, old)


# ---------------------------------------------------------------------------
# scoring.py — pure functions, no mocking needed
# ---------------------------------------------------------------------------

def test_buy_score_breakdown_sums_to_total():
    result = scoring.compute_buy_score(
        ticker="SNDK",
        thesis_intact=True,
        signal_confidence=1.0,
        market_data={"relative_volume": 2.5, "above_200sma": True,
                     "quarterly_revenue_growth_pct": 30.0},
        confirmed_deal=True,
        market_control_rank=1,
        valuation={"growth_adjusted_sales_yield": 10.0, "sales_yield": 0.2,
                   "revenue_growth_annual": 50.0},
        own_tightness={"mentions": 3, "form": "10-Q",
                       "evidence": ["Demand continues to exceed supply."]},
    )
    assert result["score"] == sum(b["points"] for b in result["breakdown"])
    assert result["score"] == 100, result  # every scored factor maxed out
    assert sum(b["max"] for b in result["breakdown"]) == 100
    print(f"PASS test_buy_score_breakdown_sums_to_total (score={result['score']})")


def test_buy_score_all_zero_when_nothing_supports_it():
    result = scoring.compute_buy_score(
        ticker="XYZ",
        thesis_intact=False,
        signal_confidence=0.0,
        market_data=None,
        confirmed_deal=False,
        market_control_rank=None,
    )
    assert result["score"] == 0, result
    print("PASS test_buy_score_all_zero_when_nothing_supports_it")


def test_caution_flags_catch_negative_growth_and_below_sma():
    flags = scoring.compute_caution_flags(
        signal_confidence=0.9,
        market_data={"quarterly_revenue_growth_pct": -5.0, "above_200sma": False},
        confirmed_deal=True,
    )
    assert any("negative" in f for f in flags), flags
    assert any("below its 200-day" in f for f in flags), flags
    print(f"PASS test_caution_flags_catch_negative_growth_and_below_sma ({len(flags)} flags)")


def test_caution_flags_low_confidence_no_deal():
    flags = scoring.compute_caution_flags(
        signal_confidence=0.3, market_data={}, confirmed_deal=False,
    )
    assert any("thesis for this name may be weak" in f for f in flags), flags
    print("PASS test_caution_flags_low_confidence_no_deal")


# ---------------------------------------------------------------------------
# industry_classifier.py
# ---------------------------------------------------------------------------

FAKE_TICKER_LOOKUP = [
    {"ticker": "NVDA", "title": "NVIDIA CORP", "cik_str": 1045810},
    {"ticker": "AMD", "title": "ADVANCED MICRO DEVICES INC", "cik_str": 2488},
    {"ticker": "SNDK", "title": "SANDISK CORP", "cik_str": 1698530},
]


def test_discover_industry_filters_invalid_tickers():
    mp = _SimpleMonkeypatch()
    mp.setattr(llm_client, "is_available", lambda *a, **kw: True)
    mp.setattr(llm_client, "chat", lambda *a, **kw: (
        '{"industry_label": "AI/GPU compute", "problem": "GPU shortage", '
        '"companies": [{"ticker": "NVDA", "reason": "leader"}, '
        '{"ticker": "FAKETICKER", "reason": "made up"}]}'
    ))
    mp.setattr(sec_utils, "get_ticker_lookup", lambda session: FAKE_TICKER_LOOKUP)

    try:
        result = industry_classifier.discover_industry_and_players("some evidence", session=object())
    finally:
        mp.undo()

    assert result is not None
    tickers = {c["ticker"] for c in result["companies"]}
    assert tickers == {"NVDA"}, tickers  # FAKETICKER must be dropped
    print("PASS test_discover_industry_filters_invalid_tickers")


def test_discover_industry_returns_none_when_llm_unavailable():
    mp = _SimpleMonkeypatch()
    mp.setattr(llm_client, "is_available", lambda *a, **kw: False)
    try:
        result = industry_classifier.discover_industry_and_players("evidence", session=object())
    finally:
        mp.undo()
    assert result is None
    print("PASS test_discover_industry_returns_none_when_llm_unavailable")


def test_rank_by_market_control_orders_by_revenue():
    mp = _SimpleMonkeypatch()
    mp.setattr(sec_utils, "get_cik_for_ticker", lambda t, s: {"NVDA": "1", "AMD": "2"}.get(t))

    fake_financials = {
        "1": {"revenue": 60_000_000_000, "revenue_formatted": "$60.0B", "fiscal_year_end": "2025-12-31"},
        "2": {"revenue": 25_000_000_000, "revenue_formatted": "$25.0B", "fiscal_year_end": "2025-12-31"},
    }
    mp.setattr(industry_classifier, "get_xbrl_financial_data", lambda cik, s: fake_financials[cik])

    try:
        ranked = industry_classifier.rank_by_market_control(["AMD", "NVDA"], session=object())
    finally:
        mp.undo()

    assert ranked[0]["ticker"] == "NVDA" and ranked[0]["market_control_rank"] == 1, ranked
    assert ranked[1]["ticker"] == "AMD" and ranked[1]["market_control_rank"] == 2, ranked
    print("PASS test_rank_by_market_control_orders_by_revenue")


# ---------------------------------------------------------------------------
# supplier_matcher.py — the new open-discovery fallback step
# ---------------------------------------------------------------------------

def test_supplier_match_falls_through_to_open_discovery():
    mp = _SimpleMonkeypatch()
    mp.setattr(llm_client, "is_available", lambda *a, **kw: True)
    # classify_into_categories (step 2, constrained to existing taxonomy)
    # returns None since nothing in the fixed list fits this evidence.
    mp.setattr(llm_client, "classify_into_categories", lambda *a, **kw: None)
    mp.setattr(supplier_matcher.industry_classifier, "discover_industry_and_players",
               lambda evidence, session, **kw: {
                   "industry_label": "Quantum-safe encryption hardware",
                   "problem": "made up for this test",
                   "companies": [{"ticker": "IBM", "reason": "test reason"}],
               })

    try:
        entries, method = supplier_matcher.match_suppliers_for_signal(
            "completely novel language matching nothing in the taxonomy",
            use_llm=True, session=object(),
        )
    finally:
        mp.undo()

    assert method == "llm_discovery", method
    assert entries[0]["category_label"] == "Quantum-safe encryption hardware", entries
    assert "IBM" in entries[0]["suppliers"], entries
    print("PASS test_supplier_match_falls_through_to_open_discovery")


# ---------------------------------------------------------------------------
# historical_pipeline.py
# ---------------------------------------------------------------------------

FAKE_HISTORICAL_TEXT_OLD = "Item 1. Business\nWe design graphics cards for gaming enthusiasts."
FAKE_HISTORICAL_TEXT_NEW = (
    "Item 7. MD&A\nWe have experienced unprecedented supply constraints regarding "
    "critical AI accelerator components amid surging demand."
)


def test_historical_trend_shows_signal_only_in_recent_year():
    mp = _SimpleMonkeypatch()
    mp.setattr(sec_utils, "get_cik_for_ticker", lambda t, s: "0001045810")
    mp.setattr(sec_utils, "get_historical_10k_filings", lambda cik, s, max_filings=6: [
        {"form": "10-K", "filing_date": "2013-01-27", "accession_number": "a1", "primary_document": "d1.htm"},
        {"form": "10-K", "filing_date": "2024-01-26", "accession_number": "a2", "primary_document": "d2.htm"},
    ])

    def _fake_fetch(cik, filing, session):
        return FAKE_HISTORICAL_TEXT_OLD if filing["filing_date"] == "2013-01-27" else FAKE_HISTORICAL_TEXT_NEW

    mp.setattr(sec_utils, "fetch_filing_text", _fake_fetch)
    mp.setattr(historical_pipeline.capex_pipeline, "get_capex_series", lambda cik, s: [])

    try:
        result = historical_pipeline.run_historical_trend("NVDA", session=object(), max_years=6)
    finally:
        mp.undo()

    years_with_signals = {pt["fiscal_year_end"] for pt in result["signal_trend"]}
    assert "2024-01-26" in years_with_signals, result
    assert "2013-01-27" not in years_with_signals, result
    print(f"PASS test_historical_trend_shows_signal_only_in_recent_year ({years_with_signals})")


# ---------------------------------------------------------------------------
# deal_monitor.py
# ---------------------------------------------------------------------------

FAKE_8K_WITH_DEAL = (
    "Item 1.01 Entry into a Material Definitive Agreement\n\n"
    "On September 3, 2026, the Company entered into a multi-year supply agreement "
    "with a strategic partner for enterprise flash storage components."
)
FAKE_8K_WITHOUT_DEAL = "Item 5.02 Departure of Directors or Certain Officers."


def test_8k_deal_detection_finds_item_101_and_keyword():
    mp = _SimpleMonkeypatch()
    mp.setattr(sec_utils, "get_cik_for_ticker", lambda t, s: "0001326801")
    mp.setattr(sec_utils, "get_recent_8k_filings", lambda cik, s, max_filings=5: [
        {"form": "8-K", "filing_date": "2026-09-03", "accession_number": "b1", "primary_document": "e1.htm"},
        {"form": "8-K", "filing_date": "2026-08-01", "accession_number": "b2", "primary_document": "e2.htm"},
    ])
    mp.setattr(sec_utils, "fetch_filing_text", lambda cik, filing, s: (
        FAKE_8K_WITH_DEAL if filing["accession_number"] == "b1" else FAKE_8K_WITHOUT_DEAL
    ))
    mp.setattr(sec_utils, "get_filing_document_url", lambda cik, filing: f"https://example.com/{filing['accession_number']}")

    try:
        hits = deal_monitor.check_8k_deals_for_ticker("META", session=object())
    finally:
        mp.undo()

    assert len(hits) == 1, hits
    assert hits[0]["source"] == "sec_8k"
    assert "supply agreement" in hits[0]["evidence"].lower(), hits
    print(f"PASS test_8k_deal_detection_finds_item_101_and_keyword (evidence: {hits[0]['evidence'][:60]}...)")


def test_news_leads_are_tagged_unverified():
    mp = _SimpleMonkeypatch()
    mp.setattr(deal_monitor.EnhancedWebSearch, "_search_duckduckgo", lambda self, query: [
        {"title": "Meta announces flash storage partnership", "snippet": "...", "url": "https://example.com/news"},
    ])

    try:
        leads = deal_monitor.check_news_leads_for_ticker("META", company_name="Meta Platforms")
    finally:
        mp.undo()

    assert leads and leads[0]["source"] == "news_search", leads
    print("PASS test_news_leads_are_tagged_unverified")


if __name__ == "__main__":
    test_buy_score_breakdown_sums_to_total()
    test_buy_score_all_zero_when_nothing_supports_it()
    test_caution_flags_catch_negative_growth_and_below_sma()
    test_caution_flags_low_confidence_no_deal()
    test_discover_industry_filters_invalid_tickers()
    test_discover_industry_returns_none_when_llm_unavailable()
    test_rank_by_market_control_orders_by_revenue()
    test_supplier_match_falls_through_to_open_discovery()
    test_historical_trend_shows_signal_only_in_recent_year()
    test_8k_deal_detection_finds_item_101_and_keyword()
    test_news_leads_are_tagged_unverified()
    print("\nAll Pass 3 integration tests passed.")
