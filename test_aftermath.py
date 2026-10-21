# test_aftermath.py
"""
Offline tests for backend/aftermath.py pure logic — how another company's
8-K mentions a big company (invested in them / agreement / just a product).
Run with: python test_aftermath.py
"""

import tempfile
from pathlib import Path

import backend.db as db

db.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
db.init_db()

from backend import aftermath as am  # noqa: E402

NV = ["NVIDIA"]


def test_investment_detected():
    text = ("On September 15, 2025, Intel Corporation (the “Company”) entered into a Securities Purchase "
            "Agreement with NVIDIA Corporation, pursuant to which NVIDIA agreed to purchase 214,776,632 "
            "shares of the Company’s common stock.")
    r = am.classify_counterparty(text, NV)
    assert r and r["relationship"] == "invested", r
    print("PASS test_investment_detected")


def test_sold_to_detected():
    text = "The Company completed the issuance and sale of 1,000,000 shares of common stock to NVIDIA Corporation."
    assert am.classify_counterparty(text, NV)["relationship"] == "invested"
    print("PASS test_sold_to_detected")


def test_agreement_detected():
    text = ("The Company entered into a capacity agreement with NVIDIA Corporation under which NVIDIA will "
            "purchase unused datacenter capacity.")
    r = am.classify_counterparty(text, NV)
    assert r and r["relationship"] in ("agreement", "invested"), r
    print(f"PASS test_agreement_detected ({r['relationship']})")


def test_product_mention_ignored():
    text = ("The Company entered into an equipment purchase order for 2,000 NVIDIA GPUs to be deployed "
            "in its data center.")
    assert am.classify_counterparty(text, NV) is None
    text2 = "Proceeds will fund NVIDIA H200 servers and related hardware."
    assert am.classify_counterparty(text2, NV) is None
    print("PASS test_product_mention_ignored")


def test_absent_alias():
    assert am.classify_counterparty("The Company entered into a credit agreement with JPMorgan.", NV) is None
    print("PASS test_absent_alias")


def test_item_sections_extracted():
    text = ("Item 1.01 Entry into a Material Definitive Agreement. Deal with NVIDIA here. "
            "Item 5.02 Departure of Directors. NVIDIA unrelated. Item 3.02 Unregistered Sales. Shares to NVIDIA.")
    sec = am._item_sections(text)
    assert "Deal with NVIDIA here" in sec and "Shares to NVIDIA" in sec and "unrelated" not in sec, sec
    print("PASS test_item_sections_extracted")


META = ["Meta Platforms", "Meta"]


def test_party_rules():
    assert am.classify_counterparty("Prior to Meta, Arabia was Vice President, Product Operations.", META) is None
    assert am.classify_counterparty(
        "The sale of the Company’s interest in Hupecol Meta closed upon execution of the agreement.", META) is None
    assert am.classify_counterparty("Meta-PURE is part of the program under Cooperative Agreement No. 24.", META) is None
    r = am.classify_counterparty(
        "Constellation and Meta signed a 20-year power purchase agreement for the Clinton Clean Energy Center.", META)
    assert r and r["relationship"] == "agreement", r
    print("PASS test_party_rules")


def test_amount_ignores_market_size():
    text = "Meta is a leader in a $275 billion market for immersive devices and partnerships."
    assert am.extract_amount(text, META) is None
    print("PASS test_amount_ignores_market_size")


def test_case_for_and_against():
    from backend import company_profile as cp
    case = cp.build_case({
        "valuation": {"earnings_yield": -0.02, "market_cap": 1e9},
        "quarterly_revenue_growth_pct": 74.0,
        "stock": {"above_200sma": False, "return_1y_pct": 20.0},
        "funds": [{"manager": "Fund A", "change": "new", "window_start": "2026-03-31",
                   "window_end": "2026-06-30", "since_avg_pct": -50.0,
                   "price_range": {"low": 169, "high": 311, "avg": 235, "first_trading_day": "2026-05-14"}}],
    })
    assert any("+74%" in x for x in case["for"]), case
    assert any("-50%" in x and "IPO" in x for x in case["against"]), case
    assert any("Not profitable" in x for x in case["against"])
    assert any("Small company" in x for x in case["against"])
    print("PASS test_case_for_and_against")


if __name__ == "__main__":
    test_investment_detected()
    test_sold_to_detected()
    test_agreement_detected()
    test_product_mention_ignored()
    test_absent_alias()
    test_item_sections_extracted()
    test_party_rules()
    test_amount_ignores_market_size()
    test_case_for_and_against()
    print("\nAll aftermath tests passed.")
