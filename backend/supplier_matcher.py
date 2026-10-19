# backend/supplier_matcher.py
"""
Tier 3 of the playbook: match a detected bottleneck to pure-play suppliers,
plus a spin-off catalyst monitor.

Important honesty note: "which mid-cap company controls >15% of a specific
sub-component niche" is not data that's available anywhere for free, and
isn't something that can be derived mechanically from SEC filings alone —
the playbook's own Historical Strategy Validation Matrix is three
hand-researched examples, not a formula. So this module does NOT try to
discover suppliers from scratch. It ships a small, hand-seeded taxonomy
(deliberately starting from the playbook's own three examples — NVDA,
VST, SNDK — plus a few adjacent "pick-and-shovel" categories that follow
the same logic) and matches a signal's evidence text against it by
keyword, with an LLM-assisted fallback that can only ever pick among the
existing taxonomy's categories — never invent a new ticker. Treat this as
a seeded starting point you'll keep extending by hand, exactly like the
playbook itself does.

Pass 3 adds a third, further fallback: when neither the keyword taxonomy
nor the constrained-label LLM step finds anything, industry_classifier.py
is asked to freely name the industry/problem and real public companies in
it. Every ticker it returns is still checked against SEC's official
ticker list, but which companies are relevant is now the LLM's open
judgment rather than a fixed vetted list — see industry_classifier.py's
own docstring for what that trade-off means in practice.

The spin-off monitor (Strategic Filter C) is different: SEC EDGAR's
"current filings" feed for Form 10-12B (the form used for corporate
separations) IS real, mechanically-checkable data, so that part fetches
live results rather than a curated list. Because this sandbox has no
network access to verify the exact response shape, the parsing is
deliberately lenient (regex over the raw Atom XML rather than a strict
parser) and fails soft to an empty list rather than raising — spot-check
it once you have it running for real, and treat every result as a lead to
verify on EDGAR directly, not a confirmed spin-off.
"""

import re
import time
from typing import Dict, List, Optional, Tuple

import requests

from . import db, industry_classifier, llm_client

SPINOFF_MONITOR_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
    "&type=10-12B&company=&dateb=&owner=include&count=40&output=atom"
)

# Starter taxonomy. `keywords` are matched (case-insensitive substring)
# against a signal's evidence text; `suppliers` maps ticker -> one-line
# reason. Extend this as you find more "pick-and-shovel" categories worth
# tracking.
SUPPLIER_TAXONOMY: List[Dict] = [
    {
        "category_label": "AI / GPU compute",
        "keywords": [
            "gpu", "graphics processing", "accelerat", "cuda", "ai chip",
            "parallel processing", "ai compute", "ai accelerator",
            "specialized chips", "compute capacity",
        ],
        "suppliers": {
            "NVDA": "Dominant AI/GPU accelerator supplier with the CUDA software moat",
            "AMD": "Secondary GPU/AI accelerator supplier",
        },
    },
    {
        "category_label": "Enterprise flash / NAND storage",
        "keywords": [
            "nand", "flash storage", "enterprise ssd", "solid state",
            "storage array", "flash memory", "high-bandwidth memory", "hbm",
            "dram",
        ],
        "suppliers": {
            "SNDK": "Pure-play enterprise flash/NAND supplier since the Western Digital spin-off",
            "WDC": "Legacy storage manufacturer with enterprise HDD + storage exposure",
            "MU": "Memory/NAND manufacturer with enterprise SSD exposure",
        },
    },
    {
        "category_label": "Clean baseload power generation",
        "keywords": [
            "baseload", "24/7 power", "around-the-clock", "nuclear",
            "clean power", "electrical capacity", "grid capacity", "grid interconnection",
            "power availability", "availability of power", "energy supply",
            "power resources", "power connections", "electricity generation",
        ],
        "suppliers": {
            "VST": "Baseload power generator serving ERCOT/PJM data center demand",
            "CEG": "Nuclear baseload power generator",
            "NRG": "Independent power producer with data-center-adjacent capacity",
        },
    },
    {
        "category_label": "Grid & electrical equipment",
        "keywords": [
            "transmission", "power connections", "interconnection", "transformer",
            "switchgear", "electrical equipment", "distribution infrastructure",
        ],
        "suppliers": {
            "GEV": "Gas turbines and grid equipment for new generation and transmission",
            "ETN": "Electrical distribution equipment (switchgear, transformers) for data centers",
            "PWR": "Utility and grid construction contractor building transmission capacity",
        },
    },
    {
        "category_label": "Data center networking / interconnect",
        "keywords": [
            "networking", "interconnect", "network switch", "optical networking",
            "data center fabric", "high-speed networking", "network equipment",
            "networking equipment", "optical",
        ],
        "suppliers": {
            "ANET": "Cloud/AI data center networking supplier",
            "CIEN": "Optical networking / interconnect supplier",
        },
    },
    {
        "category_label": "Data center thermal management",
        "keywords": [
            "cooling", "thermal management", "liquid cooling", "immersion cooling",
            "water",
        ],
        "suppliers": {
            "VRT": "Data center power and thermal management supplier",
        },
    },
    {
        "category_label": "Semiconductor manufacturing equipment",
        "keywords": [
            "semiconductor equipment", "fabrication capacity", "foundry capacity",
            "wafer", "lithography", "foundry", "advanced packaging",
        ],
        "suppliers": {
            "ASML": "Dominant EUV lithography equipment supplier",
            "AMAT": "Semiconductor fabrication equipment supplier",
            "LRCX": "Wafer fabrication equipment supplier",
        },
    },
]


# bottleneck_detector category_key -> taxonomy labels it routes to directly.
# Categories without an entry (data center capacity, capacity buildout) are
# broad enough that the evidence text decides, via the steps below.
CATEGORY_TO_TAXONOMY: Dict[str, List[str]] = {
    "ai_compute": ["AI / GPU compute"],
    "power_energy": ["Clean baseload power generation", "Grid & electrical equipment"],
    "networking_servers": ["Data center networking / interconnect"],
    "memory_storage": ["Enterprise flash / NAND storage"],
    "cooling_thermal": ["Data center thermal management"],
    "fab_capacity": ["Semiconductor manufacturing equipment"],
}


def match_suppliers_for_signal(
    evidence_text: str,
    use_llm: bool = True,
    session: Optional[requests.Session] = None,
    category_key: Optional[str] = None,
) -> Tuple[List[Dict], str]:
    """
    Returns (matched_entries, method) where method is 'category',
    'keyword', 'llm', 'llm_discovery', or 'none'.

    Step 0: if the detector's `category_key` maps directly to taxonomy
    entries (CATEGORY_TO_TAXONOMY), those are returned as 'category' — the
    detector already established what is constrained, so no guessing.

    Three steps, tried in order, each only reached if the previous one
    found nothing:
    1. Keyword match against the curated SUPPLIER_TAXONOMY — fully
       deterministic, preferred whenever it fires.
    2. LLM picks among the *existing* taxonomy's category labels only
       (llm_client.classify_into_categories is constrained to that list —
       it cannot invent a category).
    3. Open discovery (industry_classifier.discover_industry_and_players):
       the LLM freely names the industry/problem and real public
       companies in it, every ticker validated against SEC's official
       ticker list before being returned. This is the step that lets the
       system recognize an industry nobody hand-seeded into the taxonomy
       — see industry_classifier.py's docstring for the honesty notes on
       what this can and can't be trusted for. Only attempted if a
       `session` is supplied (it needs one to validate tickers).

    Returns a LIST of entries, not just one: real evidence text often
    spans more than one category at once. Every taxonomy entry with at
    least one keyword hit is returned, ranked by hit count, capped at the
    top 3 so a vague passage with many weak matches doesn't flood the
    results.
    """
    mapped = CATEGORY_TO_TAXONOMY.get(category_key or "")
    if mapped:
        entries = [e for e in SUPPLIER_TAXONOMY if e["category_label"] in mapped]
        if entries:
            return entries, "category"

    text_lower = evidence_text.lower()

    scored = []
    for entry in SUPPLIER_TAXONOMY:
        hits = sum(1 for kw in entry["keywords"] if kw in text_lower)
        if hits > 0:
            scored.append((hits, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    if scored:
        return [entry for _, entry in scored[:3]], "keyword"

    if use_llm:
        labels = [entry["category_label"] for entry in SUPPLIER_TAXONOMY]
        chosen_label = llm_client.classify_into_categories(evidence_text, labels)
        if chosen_label:
            for entry in SUPPLIER_TAXONOMY:
                if entry["category_label"] == chosen_label:
                    return [entry], "llm"

    if use_llm and session is not None:
        discovered = industry_classifier.discover_industry_and_players(
            evidence_text, session
        )
        if discovered:
            entry = {
                "category_label": discovered["industry_label"],
                "problem": discovered["problem"],
                "suppliers": {c["ticker"]: c["reason"] for c in discovered["companies"]},
            }
            return [entry], "llm_discovery"

    return [], "none"


def run_supplier_tier(
    signals: List[Dict],
    run_id: int,
    use_llm: bool = True,
    session: Optional[requests.Session] = None,
) -> List[Dict]:
    """
    Mutates and returns `signals` (as produced by bottleneck_detector) with
    a 'suppliers' list attached to each, and persists the matches. When a
    `session` is given, also attaches a revenue-based "market control"
    rank to each signal's suppliers (see industry_classifier.py for what
    that proxy does and doesn't mean).
    """
    llm_available = use_llm and llm_client.is_available()

    for sig in signals:
        entries, method = match_suppliers_for_signal(
            " ".join(sig.get("all_evidence") or [sig["evidence"]]),
            use_llm=llm_available, session=session,
            category_key=sig.get("category_key"),
        )

        seen_tickers = set()
        for entry in entries:
            for ticker, reason in entry["suppliers"].items():
                if ticker in seen_tickers:
                    continue
                seen_tickers.add(ticker)
                db.add_supplier_match(sig["id"], ticker, reason, method)
                sig["suppliers"].append({
                    "supplier_ticker": ticker,
                    "match_reason": reason,
                    "match_method": method,
                    "industry_label": entry.get("category_label"),
                })

        if seen_tickers and session is not None:
            ranked = industry_classifier.rank_by_market_control(sorted(seen_tickers), session)
            rank_by_ticker = {r["ticker"]: r for r in ranked}
            for s in sig["suppliers"]:
                r = rank_by_ticker.get(s["supplier_ticker"])
                if r:
                    s["market_control_rank"] = r["market_control_rank"]
                    s["revenue_formatted"] = r["revenue_formatted"]

    return signals


def check_for_spinoff_filings(session: requests.Session) -> List[Dict]:
    """
    Best-effort fetch of recent Form 10-12B filings from SEC EDGAR's
    "current filings" feed. See the module docstring for why this is
    parsed leniently and should be treated as leads to verify, not
    confirmed results.
    """
    try:
        resp = session.get(SPINOFF_MONITOR_URL, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    finally:
        time.sleep(0.1)

    entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL)
    results = []
    for entry in entries:
        title_m = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
        updated_m = re.search(r"<updated>(.*?)</updated>", entry)
        link_m = re.search(r'<link[^>]*href="([^"]+)"', entry)
        if not title_m:
            continue

        title = re.sub(r"\s+", " ", title_m.group(1)).strip()
        results.append({
            "company_name": title,
            "filed_at": updated_m.group(1).strip() if updated_m else "",
            "source_url": link_m.group(1).strip() if link_m else "",
        })

    return results


def run_spinoff_monitor(session: requests.Session, run_id: int) -> List[Dict]:
    filings = check_for_spinoff_filings(session)
    for f in filings:
        db.add_spinoff_filing(
            f["company_name"], None, f["filed_at"], "10-12B", f["source_url"], run_id
        )
    return filings
