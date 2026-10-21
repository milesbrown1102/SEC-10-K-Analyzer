# test_radar_backtest_and_insiders.py
"""
Offline tests for backend/radar_backtest.py and backend/insider_trading.py
pure logic — no SEC / yfinance calls.
Run with: python test_radar_backtest_and_insiders.py
"""

import tempfile
from pathlib import Path

import backend.db as db

db.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
db.init_db()

from backend import insider_trading as it, radar_backtest as rb  # noqa: E402

it._init_table()  # the import-time init ran against the real DB path


def test_events_label_new_vs_persistent():
    qs = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31"]
    by_q = {q: {} for q in qs}
    by_q["2020-06-30"]["A"] = {"ticker": "AAA", "name": "A", "sic": "1", "phrases": ["tight supply"]}
    by_q["2021-03-31"]["A"] = {"ticker": "AAA", "name": "A", "sic": "1", "phrases": ["tight supply"]}
    by_q["2021-03-31"]["B"] = {"ticker": "BBB", "name": "B", "sic": "1", "phrases": ["pricing power"]}
    by_q["2021-03-31"]["C"] = {"ticker": None, "name": "C", "sic": "1", "phrases": ["sold out"]}
    events = {e["cik"]: e for e in rb.build_events(by_q)}
    assert set(events) == {"A", "B"}, events  # no-ticker C dropped; earlier quarters lack history
    assert events["A"]["kind"] == "persistent" and events["B"]["kind"] == "new"
    print("PASS test_events_label_new_vs_persistent")


def test_forward_return_month_arithmetic():
    closes = {"2020-12": 100.0, "2021-03": 110.0, "2021-12": 150.0}
    assert abs(rb.forward_return(closes, "2020-12-31", 3) - 0.10) < 1e-9
    assert abs(rb.forward_return(closes, "2020-12-31", 12) - 0.50) < 1e-9
    assert rb.forward_return(closes, "2020-12-31", 6) is None  # missing month
    assert rb._month_add("2020-11", 3) == "2021-02"
    print("PASS test_forward_return_month_arithmetic")


def test_quarter_stats_weights_quarters_not_stocks():
    # Quarter 1: ten stocks at +10%; quarter 2: one stock at -10%.
    events = ([{"quarter": "q1", "excess_IWM_3m": 0.10}] * 10
              + [{"quarter": "q2", "excess_IWM_3m": -0.10}])
    s = rb.quarter_stats(events, 3, "IWM")
    assert s["mean_excess_pct"] == 0.0, s  # pooled mean would be +8.2%
    assert s["events"] == 11 and s["quarters"] == 2
    print("PASS test_quarter_stats_weights_quarters_not_stocks")


def test_difference_test():
    a = [{"quarter": f"q{i}", "excess_SPY_3m": 0.05 + 0.01 * (i % 2)} for i in range(6)]
    b = [{"quarter": f"q{i}", "excess_SPY_3m": 0.0} for i in range(6)]
    d = rb.difference_test(a, b, 3, "SPY")
    assert d["quarters"] == 6 and d["mean_diff_pct"] == 5.5 and d["t_stat"] > 5, d
    print("PASS test_difference_test")


FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0000723125</issuerCik><issuerName>MICRON</issuerName>
    <issuerTradingSymbol>mu</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0001</rptOwnerCik><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer></reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>0</aff10b5One>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-02</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>900.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-03</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>910</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_form4_keeps_only_open_market_purchases():
    rows = it.parse_form4_xml(FORM4)
    assert len(rows) == 1, rows
    r = rows[0]
    assert (r["ticker"], r["relationship"], r["value"], r["plan_10b5_1"]) == ("MU", "Director", 900500.0, 0), r
    print("PASS test_form4_keeps_only_open_market_purchases")


def test_insider_summary_and_ten_percent_owner_excluded():
    base = {"issuer_cik": "0000000001", "ticker": "XYZ", "issuer_name": "XYZ",
            "trans_date": "2026-01-02", "title": "", "price": 10.0}
    it._store([
        {**base, "accession": "a1", "trans_sk": "1", "filing_date": "2026-01-05", "owner_cik": "o1",
         "owner_name": "CEO", "relationship": "Officer", "shares": 100, "value": 1000, "plan_10b5_1": 0},
        {**base, "accession": "a2", "trans_sk": "1", "filing_date": "2026-01-06", "owner_cik": "o2",
         "owner_name": "Dir", "relationship": "Director", "shares": 50, "value": 500, "plan_10b5_1": 1},
        {**base, "accession": "a3", "trans_sk": "1", "filing_date": "2026-01-07", "owner_cik": "f1",
         "owner_name": "Big Fund", "relationship": "TenPercentOwner", "shares": 1e6, "value": 1e7, "plan_10b5_1": 0},
        {**base, "accession": "a4", "trans_sk": "1", "filing_date": "2025-06-01", "owner_cik": "o3",
         "owner_name": "Old", "relationship": "Officer", "shares": 1, "value": 10, "plan_10b5_1": 0},
    ])
    a = it.insider_activity("0000000001", "2026-01-31", days=90)
    assert (a["buyers"], a["discretionary_buyers"], a["total_value"]) == (2, 1, 1500), a
    # As of before the filings, nothing is visible (point-in-time by filing date).
    assert it.insider_activity("0000000001", "2026-01-04", days=90)["buyers"] == 0
    print("PASS test_insider_summary_and_ten_percent_owner_excluded")


if __name__ == "__main__":
    test_events_label_new_vs_persistent()
    test_forward_return_month_arithmetic()
    test_quarter_stats_weights_quarters_not_stocks()
    test_difference_test()
    test_form4_keeps_only_open_market_purchases()
    test_insider_summary_and_ten_percent_owner_excluded()
    print("\nAll radar backtest and insider tests passed.")
