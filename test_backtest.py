# test_backtest.py
"""
Offline tests for backend/point_in_time.py and backend/backtest.py pure
logic — no SEC / yfinance calls. Run with: python test_backtest.py
"""

import tempfile
from pathlib import Path

import backend.db as db

db.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
db.init_db()

from backend import backtest as bt, point_in_time as pit  # noqa: E402


def test_known_facts_hide_future_filings_and_restatements():
    facts = [
        {"start": "2022-01-01", "end": "2022-12-31", "val": 100, "filed": "2023-02-01"},
        # Same period restated a year later — invisible before it was filed.
        {"start": "2022-01-01", "end": "2022-12-31", "val": 90, "filed": "2024-02-01"},
        {"start": "2023-01-01", "end": "2023-12-31", "val": 150, "filed": "2024-02-01"},
    ]
    known = pit._known_facts(facts, "2023-06-30")
    assert list(known.values())[0]["val"] == 100 and len(known) == 1, known
    later = pit._known_facts(facts, "2024-06-30")
    assert later[("2022-01-01", "2022-12-31")]["val"] == 90, later
    print("PASS test_known_facts_hide_future_filings_and_restatements")


def test_quarter_ends():
    q = bt.quarter_ends("2017-12-31", "2018-12-31")
    assert q == ["2017-12-31", "2018-03-31", "2018-06-30", "2018-09-30", "2018-12-31"], q
    print("PASS test_quarter_ends")


def test_split_factor_only_counts_later_splits():
    original = pit._price_data
    pit._price_data = lambda t: {"bars": {}, "splits": [["2021-07-20", 4.0], ["2024-06-10", 10.0]]}
    try:
        assert pit.split_factor_after("NVDA", "2020-04-26") == 40.0
        assert pit.split_factor_after("NVDA", "2022-01-30") == 10.0
        assert pit.split_factor_after("NVDA", "2025-01-26") == 1.0
    finally:
        pit._price_data = original
    print("PASS test_split_factor_only_counts_later_splits")


def _rows(dates=8):
    """Synthetic universe where factor 'good' predicts excess return and 'bad' doesn't."""
    rows = []
    for d in range(dates):
        for i in range(6):
            excess = (i - 2.5) / 100
            rows.append({
                "date": f"2020-{d + 1:02d}-28", "ticker": f"T{i}", "matched": i >= 3,
                "score": i * 10, "good": i, "bad": (i * 7 + d) % 6,
                "flag": i >= 3, "excess_3m": excess, "fwd_3m": 0.02 + excess,
                "universe_3m": 0.02, "spy_3m": 0.01,
            })
    return rows


def test_factor_ic_detects_a_working_factor():
    good = bt.factor_ic(_rows(), "good")
    assert good["mean_ic"] == 1.0 and good["n_dates"] == 8, good
    bad = bt.factor_ic(_rows(), "bad")
    assert abs(bad["mean_ic"]) < 0.5, bad
    print(f"PASS test_factor_ic_detects_a_working_factor (bad IC={bad['mean_ic']})")


def test_binary_split():
    out = bt.binary_split(_rows(), "flag")
    assert out["mean_excess_true"] > 0 > out["mean_excess_false"], out
    assert out["p_value"] is not None and out["p_value"] < 0.01, out
    print("PASS test_binary_split")


def test_top_n_strategy_compounds_quarterly():
    out = bt.top_n_strategy(_rows(dates=4), n=2)
    # Top 2 by score (T5, T4): mean fwd = 0.02 + (2.5 + 1.5)/2/100 = 0.04
    assert abs(out["curve"][-1]["strategy"] - 1.04 ** 4) < 1e-3, out["curve"][-1]
    assert abs(out["curve"][-1]["universe"] - 1.02 ** 4) < 1e-3
    assert out["curve"][0]["picks"] == ["T5", "T4"]
    print("PASS test_top_n_strategy_compounds_quarterly")


if __name__ == "__main__":
    test_known_facts_hide_future_filings_and_restatements()
    test_quarter_ends()
    test_split_factor_only_counts_later_splits()
    test_factor_ic_detects_a_working_factor()
    test_binary_split()
    test_top_n_strategy_compounds_quarterly()
    print("\nAll backtest tests passed.")
