# backend/opportunities.py
"""
"Which industry is next?" — industries ranked on four independent kinds
of evidence, then the companies inside each that the most sources point to.

Sources (each scored 0-25 by its rank among industries with any signal):
1. Giants' money — investments by the mega-caps in the last 12 months:
   other companies' 8-Ks naming them as investor, plus new stakes in their
   own 13Fs. Investments only: "agreements" announced by small companies
   mostly faded in the follow-up data (Historical Trend Lookup), so they're
   listed but not scored.
2. Scarcity rising — the Industry Radar's change in companies newly saying
   their own product is scarce.
3. Funds buying — net buyers among tracked 13F managers last quarter.
4. Insiders buying — officer/director open-market purchase clusters, 90 days.

NOT BACKTESTED as a combination. Its parts were tested separately with
mixed results (Score Validation page). Treat it as a ranked research list.
"""

import math
import time
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional

import requests

from . import (
    aftermath, db, industry_radar, insider_trading, institutional_holdings,
    point_in_time as pit, sec_utils,
)

GIANTS = ["NVDA", "MSFT", "GOOGL", "AMZN", "META", "AAPL"]
POINTS_PER_SOURCE = 25
SOURCES = ("giants", "scarcity", "funds", "insiders")
SOURCE_LABELS = {
    "giants": "Giants investing",
    "scarcity": "Scarcity rising",
    "funds": "Top funds buying",
    "insiders": "Insiders buying",
}


def _profile_for_ticker(ticker: Optional[str], session: requests.Session) -> Dict:
    if not ticker:
        return {}
    cik = sec_utils.get_cik_for_ticker(ticker, session)
    return {**aftermath.company_profile(cik, session), "cik": cik} if cik else {}


def _rank_points(values: Dict[str, float]) -> Dict[str, float]:
    """Industry -> 0..25 points by rank among industries with a positive value."""
    pos = sorted((v, k) for k, v in values.items() if v > 0)
    n = len(pos)
    return {k: round(POINTS_PER_SOURCE * (i + 1) / n, 1) for i, (v, k) in enumerate(pos)} if n else {}


def giants_money(session: requests.Session, progress=None) -> List[Dict]:
    """Every investment / agreement involving a giant in the last 12 months."""
    end = pit.today()
    start = (pit.datetime.fromisoformat(end) - timedelta(days=365)).date().isoformat()
    rows = []
    for i, giant in enumerate(GIANTS):
        cik = sec_utils.get_cik_for_ticker(giant, session)
        if not cik:
            continue
        for d in aftermath.counterparty_deals(giant, cik, start, end, session, explain=False):
            rows.append({"giant": giant, "source": "8-K", **{k: d[k] for k in (
                "date", "relationship", "company", "ticker", "sic", "industry", "amount_usd", "url",
                "return_to_today_pct")}})
        tf = aftermath.thirteen_f_changes(cik, start, end, session)
        for p in (tf or {}).get("positions", []):
            if p["change"] != "new" or not p["ticker"]:
                continue
            prof = _profile_for_ticker(p["ticker"], session)
            rows.append({"giant": giant, "source": "13F", "date": tf["to_filing"], "relationship": "invested",
                         "company": p["company"], "ticker": p["ticker"], "sic": prof.get("sic"),
                         "industry": prof.get("industry"), "amount_usd": p["value"], "url": None,
                         "return_to_today_pct": p["return_to_today_pct"]})
        if progress:
            progress(i + 1, len(GIANTS), giant, "following the giants' money")
    # An 8-K and the 13F often describe the same stake; keep one per giant+ticker.
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r["source"] != "8-K", r["date"] or ""), reverse=False):
        key = (r["giant"], r["ticker"] or r["company"], r["relationship"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def fund_buying(session: requests.Session) -> List[Dict]:
    report = institutional_holdings.get_latest_report()
    if not report:
        return []
    rows = []
    for c in report["consensus"]:
        if c["net_buyers"] < 1 or not c.get("ticker"):
            continue
        prof = _profile_for_ticker(c["ticker"], session)
        rows.append({"ticker": c["ticker"], "company": c["name"], "net_buyers": c["net_buyers"],
                     "buyers": [b["manager"] for b in c["buyers"]], "sic": prof.get("sic"),
                     "industry": prof.get("industry")})
    return rows


def insider_buying(session: requests.Session) -> List[Dict]:
    rows = []
    for c in insider_trading.cluster_buys(90, 2):
        if c["avg_per_buyer"] < 50_000:
            continue
        prof = aftermath.company_profile(c["issuer_cik"], session)
        rows.append({"ticker": c["ticker"], "company": c["issuer_name"], "buyers": c["buyers"],
                     "total_value": c["total_value"], "sic": prof.get("sic"), "industry": prof.get("industry")})
    return rows


def scarcity_rising() -> List[Dict]:
    report = industry_radar.get_latest_report()
    if not report:
        return []
    new_by_sic = defaultdict(list)
    for c in report["seller"]["companies"]:
        if c["new"] and c["ticker"]:
            new_by_sic[c["sic"]].append(c)
    rows = []
    for ind in report["seller"]["industries"]:
        rows.append({"sic": ind["sic"], "industry": ind["industry"], "change": ind["change"],
                     "companies_now": ind["companies_now"], "new_companies": new_by_sic.get(ind["sic"], [])})
    return rows


def build_rankings(giants: List[Dict], scarcity: List[Dict], funds: List[Dict], insiders: List[Dict],
                   titles: Dict[str, str]) -> List[Dict]:
    """Pure function: per-industry points from each source, plus companies cross-referenced."""
    def is_fin(sic):
        return bool(sic) and str(sic).isdigit() and 6000 <= int(sic) <= 6799 and int(sic) != 6199

    raw = {s: defaultdict(float) for s in SOURCES}
    companies: Dict[str, Dict[str, Dict]] = defaultdict(dict)

    def touch(sic, ticker, name, source, note):
        c = companies[sic].setdefault(ticker or name, {"ticker": ticker, "company": name, "sources": {}})
        c["sources"].setdefault(source, []).append(note)

    for g in giants:
        if not g["sic"] or is_fin(g["sic"]):
            continue
        if g["relationship"] == "invested":
            # Count + log of dollars, so one $5B stake doesn't swamp everything.
            raw["giants"][g["sic"]] += 1 + math.log10(1 + (g["amount_usd"] or 0) / 1e8)
        amt = f" (${g['amount_usd'] / 1e9:,.2f}B)" if g.get("amount_usd") else ""
        touch(g["sic"], g["ticker"], g["company"], "giants",
              f"{g['giant']} {'invested' if g['relationship'] == 'invested' else 'agreement'}{amt}, {g['date']}")
    for s in scarcity:
        if is_fin(s["sic"]):
            continue
        raw["scarcity"][s["sic"]] += max(0, s["change"])
        for c in s["new_companies"]:
            touch(s["sic"], c["ticker"], c["name"], "scarcity", "newly says: " + ", ".join(c["phrases"][:2]))
    for f in funds:
        if not f["sic"] or is_fin(f["sic"]):
            continue
        raw["funds"][f["sic"]] += f["net_buyers"]
        touch(f["sic"], f["ticker"], f["company"], "funds", f"{f['net_buyers']} net fund buyer(s): "
              + ", ".join(f["buyers"][:3]))
    for i in insiders:
        if not i["sic"] or is_fin(i["sic"]):
            continue
        raw["insiders"][i["sic"]] += 1
        touch(i["sic"], i["ticker"], i["company"], "insiders",
              f"{i['buyers']} insiders bought ${i['total_value'] / 1e6:,.1f}M")

    points = {s: _rank_points(raw[s]) for s in SOURCES}
    sics = set().union(*(points[s].keys() for s in SOURCES))
    out = []
    for sic in sics:
        breakdown = {s: points[s].get(sic, 0.0) for s in SOURCES}
        comps = sorted(companies[sic].values(),
                       key=lambda c: (-len(c["sources"]), -sum(len(v) for v in c["sources"].values())))
        out.append({
            "sic": sic, "industry": titles.get(sic, f"SIC {sic}"),
            "score": round(sum(breakdown.values()), 1), "breakdown": breakdown,
            "sources_present": sum(1 for v in breakdown.values() if v > 0),
            "raw": {s: round(raw[s].get(sic, 0.0), 2) for s in SOURCES},
            "companies": [{**c, "source_count": len(c["sources"])} for c in comps[:25]],
        })
    out.sort(key=lambda r: (-r["sources_present"], -r["score"]))
    return out


def run_opportunities(session: Optional[requests.Session] = None, progress=None) -> Dict:
    session = session or sec_utils.make_sec_session()
    titles = industry_radar.sic_descriptions(session)
    giants = giants_money(session, progress)
    if progress:
        progress(0, 1, "", "matching fund and insider buying to industries")
    funds = fund_buying(session)
    insiders = insider_buying(session)
    scarcity = scarcity_rising()
    report = {
        "generated_at": time.time(),
        "industries": build_rankings(giants, scarcity, funds, insiders, titles),
        "giants_money": sorted(giants, key=lambda r: r["date"] or "", reverse=True),
        "inputs": {"giants": len(giants), "funds": len(funds), "insiders": len(insiders),
                   "scarcity_industries": len(scarcity),
                   "radar_generated_at": (industry_radar.get_latest_report() or {}).get("generated_at"),
                   "funds_generated_at": (institutional_holdings.get_latest_report() or {}).get("generated_at")},
        "source_labels": SOURCE_LABELS,
    }
    db.cache_set("opportunities", "latest", report)
    return report


def get_latest_report() -> Optional[Dict]:
    return db.cache_get("opportunities", "latest", ttl_seconds=None)
