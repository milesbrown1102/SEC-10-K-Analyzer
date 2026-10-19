# test_industry_radar.py
"""
Offline tests for backend/industry_radar.py pure logic — no SEC calls.
Run with: python test_industry_radar.py
"""

import tempfile
from pathlib import Path

import backend.db as db

db.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
db.init_db()

from backend import industry_radar as ir  # noqa: E402


def _co(cik, sic, ticker=None, phrases=("constrained supply",)):
    return {"cik": cik, "ticker": ticker, "name": f"Co {cik}", "sic": sic,
            "phrases": set(phrases),
            "latest_filing": {"form": "10-Q", "file_date": "2026-08-01", "url": None}}


def test_industry_table_compares_years_and_counts_new_companies():
    now = {c: _co(c, "3674", ticker=f"T{c}") for c in ("1", "2", "3", "4")}
    now["9"] = _co("9", "4911")  # thin industry: one company
    prior = {"1": _co("1", "3674"), "8": _co("8", "3674")}
    rows = ir.build_industry_table(now, prior, {"3674": "Semiconductors"}, min_companies=3)
    assert [r["sic"] for r in rows] == ["3674"], rows  # 4911 below threshold
    r = rows[0]
    assert r["industry"] == "Semiconductors"
    assert (r["companies_now"], r["companies_prior"], r["change"], r["new_companies"]) == (4, 2, 2, 3), r
    assert r["tickers"] == ["T1", "T2", "T3", "T4"]
    print("PASS test_industry_table_compares_years_and_counts_new_companies")


def test_industry_table_sorts_by_change():
    now = {**{f"a{i}": _co(f"a{i}", "1000") for i in range(5)},
           **{f"b{i}": _co(f"b{i}", "2000") for i in range(3)}}
    prior = {f"a{i}": _co(f"a{i}", "1000") for i in range(5)}
    rows = ir.build_industry_table(now, prior, {}, min_companies=3)
    assert [r["sic"] for r in rows] == ["2000", "1000"], rows  # +3 beats +0
    assert rows[1]["industry"] == "SIC 1000"
    print("PASS test_industry_table_sorts_by_change")


def test_ticker_parsing_from_display_names():
    for name, want in [
        ("MICRON TECHNOLOGY INC  (MU)  (CIK 0000723125)", "MU"),
        ("Alphabet Inc.  (GOOGL, GOOG)  (CIK 0001652044)", "GOOGL"),
        ("Berkshire Hathaway Inc  (BRK-B, BRK-A)  (CIK 0001067983)", "BRK-B"),
        ("Some Private Filer LLC  (CIK 0009999999)", None),
    ]:
        m = ir._TICKER_RE.search(name)
        assert (m.group(1) if m else None) == want, (name, m and m.group(1))
    print("PASS test_ticker_parsing_from_display_names")


def test_custom_universe_add_dedupes_and_removes():
    ir.add_to_universe("smr", "first")
    ir.add_to_universe("SMR", "second")
    items = ir.get_custom_universe()
    assert len(items) == 1 and items[0]["note"] == "second", items
    ir.remove_from_universe("smr")
    assert ir.get_custom_universe() == []
    print("PASS test_custom_universe_add_dedupes_and_removes")


if __name__ == "__main__":
    test_industry_table_compares_years_and_counts_new_companies()
    test_industry_table_sorts_by_change()
    test_ticker_parsing_from_display_names()
    test_custom_universe_add_dedupes_and_removes()
    print("\nAll industry radar tests passed.")
