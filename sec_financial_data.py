# sec_financial_data.py
"""
Real financial figures straight from SEC's structured XBRL data.

Why this module exists: the previous approach searched the raw filing HTML
text for phrases like "revenue of $X billion" using regex. That's fragile —
it can grab the wrong number, misjudge million vs. billion, or match a
sentence that isn't even about the company's own revenue. SEC already
publishes every filer's tagged financial facts as XBRL at a stable JSON
endpoint:

    https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json

That's the same underlying data XBRL viewers and financial data platforms
use, so pulling from it directly is strictly more reliable than pattern
matching prose. This module fetches it, picks the most recent full fiscal
year figure reported on a 10-K, and returns clean values. It intentionally
returns {} (never raises) when a company has no usable XBRL data — callers
should treat that as "fall back to something else," not as an error.

Note: employee headcount has no standard XBRL tag, so it still needs to
come from the filing text elsewhere in the app.
"""

from datetime import datetime
from typing import Dict, List, Optional

import requests

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Tags to try, in priority order — companies don't all use the same tag for
# the same concept (older filings especially use legacy tags).
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]
NET_INCOME_TAGS = ["NetIncomeLoss", "ProfitLoss"]
GROSS_PROFIT_TAGS = ["GrossProfit"]
COST_OF_REVENUE_TAGS = [
    "CostOfRevenue",
    "CostOfGoodsAndServicesSold",
    "CostOfGoodsAndServicesSoldExcludingDepreciationDepletionAndAmortization",
]


def _format_usd(value: float) -> str:
    """Match the app's existing $X.XB / $X.XM formatting convention."""
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,.0f}"


def _best_annual_fact(facts: List[Dict]) -> Optional[Dict]:
    """
    From a list of XBRL fact entries for one tag, pick the most recent
    FULL fiscal year value reported on a 10-K — not a 10-Q quarter, and not
    a half-year or nine-month cumulative figure that happens to share the
    same tag.
    """
    annual = []
    for f in facts:
        if f.get("form") not in ("10-K", "10-K/A"):
            continue
        start, end = f.get("start"), f.get("end")
        if not end:
            continue
        if start:
            try:
                duration_days = (
                    datetime.fromisoformat(end) - datetime.fromisoformat(start)
                ).days
            except ValueError:
                continue
            # Keep only durations that look like a full fiscal year.
            if not (300 <= duration_days <= 400):
                continue
        annual.append(f)

    if not annual:
        return None

    annual.sort(key=lambda f: f["end"], reverse=True)
    return annual[0]


def _get_tagged_value(us_gaap: Dict, tag_names: List[str]) -> Optional[Dict]:
    """
    Most recent annual fact across `tag_names`. Companies switch tags over
    time (e.g. Revenues -> RevenueFromContractWithCustomer... after ASC 606),
    so the first tag with data can be years stale; list order only breaks
    ties on the same fiscal year end.
    """
    newest = None
    for tag in tag_names:
        tag_data = us_gaap.get(tag)
        if not tag_data:
            continue
        usd_facts = tag_data.get("units", {}).get("USD", [])
        best = _best_annual_fact(usd_facts)
        if best and (newest is None or best["end"] > newest["end"]):
            newest = best
    return newest


def parse_companyfacts(data: Dict) -> Dict:
    """
    Pure parsing logic, split out from the network call so it can be unit
    tested against a saved/synthetic JSON fixture without hitting SEC.
    """
    us_gaap = data.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return {}

    result: Dict = {"source": "SEC XBRL"}

    revenue_fact = _get_tagged_value(us_gaap, REVENUE_TAGS)
    net_income_fact = _get_tagged_value(us_gaap, NET_INCOME_TAGS)
    gross_profit_fact = _get_tagged_value(us_gaap, GROSS_PROFIT_TAGS)
    cost_of_revenue_fact = _get_tagged_value(us_gaap, COST_OF_REVENUE_TAGS)

    # Only combine figures from the same fiscal year as revenue — a stale tag
    # (Amazon's last GrossProfit fact is FY2009) would otherwise be mixed
    # with current revenue and produce a nonsense margin.
    if revenue_fact:
        def _same_year(fact):
            return fact if fact and fact["end"] == revenue_fact["end"] else None
        net_income_fact = _same_year(net_income_fact)
        gross_profit_fact = _same_year(gross_profit_fact)
        cost_of_revenue_fact = _same_year(cost_of_revenue_fact)

    if revenue_fact:
        result["revenue"] = revenue_fact["val"]
        result["revenue_formatted"] = _format_usd(revenue_fact["val"])
        result["fiscal_year_end"] = revenue_fact["end"]

    if net_income_fact:
        result["net_income"] = net_income_fact["val"]
        result["net_income_formatted"] = _format_usd(net_income_fact["val"])

    gross_profit_val = gross_profit_fact["val"] if gross_profit_fact else None
    if gross_profit_val is None and revenue_fact and cost_of_revenue_fact:
        gross_profit_val = revenue_fact["val"] - cost_of_revenue_fact["val"]

    if gross_profit_val is not None and revenue_fact and revenue_fact["val"]:
        result["gross_margin_pct"] = round(
            (gross_profit_val / revenue_fact["val"]) * 100, 1
        )
        result["gross_margin_formatted"] = f"{result['gross_margin_pct']}%"

    return result


def get_xbrl_financial_data(cik: str, session: requests.Session) -> Dict:
    """
    Fetch structured financial data for a company from SEC XBRL.

    Returns {} if the company has no XBRL data (rare — e.g. some very small
    filers) or the request fails for any reason. This never raises; callers
    should fall back to something else (e.g. text-pattern extraction) when
    they get an empty dict back.
    """
    data = fetch_companyfacts_raw(cik, session)
    if not data:
        return {}
    return parse_companyfacts(data)


def fetch_companyfacts_raw(cik: str, session: requests.Session) -> Dict:
    """
    Raw XBRL companyfacts fetch, split out from get_xbrl_financial_data so
    other callers (e.g. the CapEx pipeline, which needs tags this module
    doesn't parse by default) can reuse the same fetch without duplicating
    the request/error-handling logic. Returns {} on any failure — never
    raises.
    """
    cik_padded = str(cik).zfill(10)
    url = COMPANYFACTS_URL.format(cik=cik_padded)

    try:
        response = session.get(url, timeout=20)
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return {}