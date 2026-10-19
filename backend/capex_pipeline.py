# backend/capex_pipeline.py
"""
Tier 1 of the playbook: aggregate mega-cap CapEx trajectories.

Pulls a multi-year CapEx series straight from SEC XBRL (same data source as
sec_financial_data.py, reusing its raw fetch) for each mega-cap in the
watchlist, computes year-over-year growth, and flags names whose most
recent annual CapEx grew faster than CAPEX_GROWTH_THRESHOLD_PCT — the
playbook's own signal that a structural demand shift is underway.
"""

import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

from sec_financial_data import fetch_companyfacts_raw
from . import db, sec_utils

CAPEX_GROWTH_THRESHOLD_PCT = 25.0

# Priority order — companies don't all tag CapEx the same way.
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForCapitalImprovements",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquireMachineryAndEquipment",
]


def _annual_series_for_tags(us_gaap: Dict, tag_names: List[str],
                             min_points: int = 2) -> Tuple[List[Dict], Optional[str]]:
    """
    Returns (annual facts sorted ascending by end date, tag used) for the
    tag in `tag_names` with the most recent fiscal-year data, among those
    with at least `min_points` distinct full-fiscal-year 10-K values.
    `tag_names` order only breaks ties — companies switch tags over time
    (Amazon stopped using PaymentsToAcquirePropertyPlantAndEquipment after
    FY2016), so taking the first tag with any data can return a stale series.
    """
    best, best_tag = [], None
    for tag in tag_names:
        tag_data = us_gaap.get(tag)
        if not tag_data:
            continue

        usd_facts = tag_data.get("units", {}).get("USD", [])
        annual, seen_ends = [], set()

        for f in usd_facts:
            if f.get("form") not in ("10-K", "10-K/A"):
                continue
            start, end = f.get("start"), f.get("end")
            if not start or not end or end in seen_ends:
                continue
            try:
                duration_days = (
                    datetime.fromisoformat(end) - datetime.fromisoformat(start)
                ).days
            except ValueError:
                continue
            if not (300 <= duration_days <= 400):
                continue
            seen_ends.add(end)
            annual.append(f)

        annual.sort(key=lambda f: f["end"])
        if len(annual) >= min_points and (
            not best or annual[-1]["end"] > best[-1]["end"]
        ):
            best, best_tag = annual, tag

    return best, best_tag


def _cached_companyfacts(cik: str, session: requests.Session) -> Dict:
    """
    sec_financial_data.fetch_companyfacts_raw talks straight to SEC with no
    caching of its own (it's used standalone by the Streamlit app too, so
    it doesn't know about backend.db). Wrap it here so the Scanner doesn't
    re-download a mega-cap's entire XBRL facts file on every run.
    """
    cached = db.cache_get("companyfacts", cik, ttl_seconds=24 * 3600)
    if cached is not None:
        return cached

    data = fetch_companyfacts_raw(cik, session)
    if data:
        db.cache_set("companyfacts", cik, data)
    return data


def get_capex_series(cik: str, session: requests.Session) -> List[Dict]:
    """
    Returns a list of {'fiscal_year_end', 'capex_usd', 'yoy_growth_pct',
    'tag'} sorted oldest to newest, from SEC's structured XBRL data
    (cached — see _cached_companyfacts).
    """
    data = _cached_companyfacts(cik, session)
    us_gaap = data.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return []

    annual, tag_used = _annual_series_for_tags(us_gaap, CAPEX_TAGS)
    if not annual:
        return []

    series = []
    prev_val = None
    for f in annual:
        val = f["val"]
        yoy = None
        if prev_val:
            yoy = round((val - prev_val) / prev_val * 100, 1)
        series.append({
            "fiscal_year_end": f["end"],
            "capex_usd": val,
            "yoy_growth_pct": yoy,
            "tag": tag_used,
        })
        prev_val = val

    return series


def run_capex_tier(watchlist: List[str], session: requests.Session, run_id: int) -> Dict[str, Dict]:
    """
    Runs Tier 1 across the whole watchlist, persists each point to
    backend.db.capex_history, and returns a per-ticker summary including
    whether the most recent year cleared the growth threshold.
    """
    results: Dict[str, Dict] = {}

    for ticker in watchlist:
        cik = sec_utils.get_cik_for_ticker(ticker, session)
        if not cik:
            results[ticker] = {"error": f"Could not resolve a CIK for '{ticker}'", "series": []}
            continue

        series = get_capex_series(cik, session)
        for point in series:
            db.upsert_capex(
                ticker, point["fiscal_year_end"], point["capex_usd"],
                point["yoy_growth_pct"], run_id,
            )

        flagged = bool(
            series and series[-1]["yoy_growth_pct"] is not None
            and series[-1]["yoy_growth_pct"] >= CAPEX_GROWTH_THRESHOLD_PCT
        )

        results[ticker] = {
            "series": series,
            "flagged_high_growth": flagged,
            "latest_yoy_growth_pct": series[-1]["yoy_growth_pct"] if series else None,
        }
        time.sleep(0.1)

    return results
