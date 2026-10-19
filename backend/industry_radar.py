# backend/industry_radar.py
"""
Industry Radar: which industries are newly reporting tight supply, across
ALL SEC filers rather than a hand-picked list.

Uses SEC EDGAR full-text search (efts.sec.gov) to find every 10-K / 10-Q
filed in the last 12 months containing a tightness phrase, and the same
for the 12 months before, then compares by industry (SIC code). Generic
risk-factor boilerplate appears in both windows and roughly cancels; the
CHANGE is the signal ("power availability": 32 filings -> 94).

Two kinds of phrases, kept apart because they point different ways:
- seller-side ("demand exceeds supply", "pricing power"): the company's
  OWN product is scarce — a candidate for pricing power itself;
- buyer-side ("extended lead times", "supply shortages"): the company
  can't get its INPUTS — the bottleneck is upstream, at its suppliers.

Honesty notes:
- Phrase matching, not the sentence-level detector: a filing that says
  "we do not expect demand to exceed supply" still matches. Industry
  counts are robust to that; for a single company, use the drill-down,
  which runs the full detector on its latest filing.
- Not backtested. The supplier-tightness factor this is modeled on showed
  a weak, unproven edge (Score Validation page); this is a discovery tool
  for finding where to look, not a signal to trade on.
- SIC codes are coarse and self-reported (Micron and a solar-cell maker
  share 3674 "Semiconductors & Related Devices").
"""

import re
import time
import urllib.parse
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

import requests

from . import db, sec_utils

FTS_URL = "https://efts.sec.gov/LATEST/search-index"
PAGE_SIZE = 100
MAX_PAGES_PER_PHRASE = 20  # 2,000 filings — far above any phrase below

SELLER_PHRASES = [
    "demand exceeds supply", "demand exceeded supply", "demand outpacing supply",
    "demand outpaced supply", "constrained supply", "tight supply", "supply-constrained",
    "capacity constrained", "record backlog", "pricing power",
    "higher average selling prices", "sold out", "fully booked",
]
BUYER_PHRASES = [
    "extended lead times", "longer lead times", "supply shortages", "power availability",
]
MIN_COMPANIES = 3  # industries with fewer companies hitting now are too thin to read


def _window(days_back_end: int, length: int = 365) -> Dict[str, str]:
    end = date.today() - timedelta(days=days_back_end)
    return {"start": (end - timedelta(days=length - 1)).isoformat(), "end": end.isoformat()}


def _fts_page(session: requests.Session, phrase: str, start: str, end: str, offset: int) -> Optional[Dict]:
    params = {"q": f'"{phrase}"', "forms": "10-K,10-Q", "dateRange": "custom",
              "startdt": start, "enddt": end, "from": offset}
    url = f"{FTS_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(3):
        try:
            resp = sec_utils._polite_get(session, url, timeout=30)
            data = resp.json()
            if "hits" in data:
                return data
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 + 3 * attempt)  # full-text search throttles bursts
    return None


_TICKER_RE = re.compile(r"\(([A-Z0-9.\-]{1,6})(?:,\s*[A-Z0-9.\-]+)*\)\s*\(CIK")


def search_phrase(phrase: str, start: str, end: str,
                  session: requests.Session) -> List[Dict]:
    """
    Every 10-K/10-Q main document (not exhibits) filed in [start, end]
    containing the exact phrase. Cached: a window that ended over a week
    ago can't change, so it's kept forever; recent windows for a day.
    """
    cache_key = f"{phrase}|{start}|{end}"
    settled = end < (date.today() - timedelta(days=7)).isoformat()
    cached = db.cache_get("fts_phrase", cache_key, ttl_seconds=None if settled else 24 * 3600)
    if cached is not None:
        return cached

    hits: List[Dict] = []
    for page in range(MAX_PAGES_PER_PHRASE):
        data = _fts_page(session, phrase, start, end, page * PAGE_SIZE)
        if data is None:
            break
        batch = data["hits"]["hits"]
        for h in batch:
            src = h["_source"]
            if src.get("file_type") not in ("10-K", "10-Q"):
                continue  # exhibits, press releases attached to the filing
            name = (src.get("display_names") or [""])[0]
            m = _TICKER_RE.search(name)
            adsh, _, filename = h["_id"].partition(":")
            cik = (src.get("ciks") or [""])[0]
            hits.append({
                "cik": cik,
                "ticker": m.group(1) if m else None,
                "name": re.sub(r"\s*\(.*$", "", name).strip(),
                "sic": (src.get("sics") or [None])[0],
                "form": src.get("file_type"),
                "file_date": src.get("file_date"),
                "url": (f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
                        f"{adsh.replace('-', '')}/{filename}") if cik else None,
            })
        if len(batch) < PAGE_SIZE:
            break
    db.cache_set("fts_phrase", cache_key, hits)
    return hits


def sic_descriptions(session: requests.Session) -> Dict[str, str]:
    """SEC's SIC code -> industry title table, cached for 30 days."""
    cached = db.cache_get("sic_titles", "all", ttl_seconds=30 * 86400)
    if cached:
        return cached
    try:
        import pandas as pd
        from io import StringIO
        resp = sec_utils._polite_get(
            session, "https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list")
        tables = pd.read_html(StringIO(resp.text))
    except Exception:
        return {}
    out = {}
    for t in tables:
        # SEC's table carries its headers in the first row, not the header.
        first = [str(v).strip().lower() for v in t.iloc[0].tolist()] if len(t) else []
        if any("sic" in v for v in first):
            t = t.iloc[1:].set_axis(first, axis=1)
        cols = {str(c).lower(): c for c in t.columns}
        code_col = next((cols[c] for c in cols if "sic" in c and "code" in c), None)
        title_col = next((cols[c] for c in cols if "industry" in c or "title" in c), None)
        if code_col is None or title_col is None:
            continue
        for _, row in t.iterrows():
            code = str(row[code_col]).strip().split(".")[0].zfill(4)
            if code.isdigit():
                out[code] = str(row[title_col]).strip().title()
    if out:
        db.cache_set("sic_titles", "all", out)
    return out


def _collect(phrases: List[str], window: Dict[str, str], session: requests.Session) -> Dict[str, Dict]:
    """{cik: {ticker, name, sic, phrases: set, latest_filing}} for one window."""
    companies: Dict[str, Dict] = {}
    for phrase in phrases:
        for h in search_phrase(phrase, window["start"], window["end"], session):
            c = companies.setdefault(h["cik"], {
                "cik": h["cik"], "ticker": h["ticker"], "name": h["name"], "sic": h["sic"],
                "phrases": set(), "latest_filing": h,
            })
            c["phrases"].add(phrase)
            if h["file_date"] > c["latest_filing"]["file_date"]:
                c["latest_filing"] = h
            c["ticker"] = c["ticker"] or h["ticker"]
    return companies


def build_industry_table(now: Dict[str, Dict], prior: Dict[str, Dict],
                         titles: Dict[str, str], min_companies: int = MIN_COMPANIES) -> List[Dict]:
    """
    Pure function. One row per SIC code: distinct companies using the
    phrases now vs in the prior 12 months, and how many are new.
    """
    by_sic_now, by_sic_prior = defaultdict(set), defaultdict(set)
    for cik, c in now.items():
        by_sic_now[c["sic"]].add(cik)
    for cik, c in prior.items():
        by_sic_prior[c["sic"]].add(cik)
    rows = []
    for sic, ciks in by_sic_now.items():
        if not sic or len(ciks) < min_companies:
            continue
        before = by_sic_prior.get(sic, set())
        rows.append({
            "sic": sic,
            "industry": titles.get(sic, f"SIC {sic}"),
            "companies_now": len(ciks),
            "companies_prior": len(before),
            "change": len(ciks) - len(before),
            "new_companies": len(ciks - before),
            "tickers": sorted({now[c]["ticker"] for c in ciks if now[c]["ticker"]}),
        })
    rows.sort(key=lambda r: (-r["change"], -r["companies_now"]))
    return rows


def phrase_trends(phrases: List[str], windows: Dict[str, Dict], session: requests.Session) -> List[Dict]:
    out = []
    for p in phrases:
        now = search_phrase(p, windows["now"]["start"], windows["now"]["end"], session)
        prior = search_phrase(p, windows["prior"]["start"], windows["prior"]["end"], session)
        out.append({"phrase": p, "filings_now": len(now), "filings_prior": len(prior),
                    "companies_now": len({h["cik"] for h in now}),
                    "companies_prior": len({h["cik"] for h in prior})})
    out.sort(key=lambda r: -(r["companies_now"] - r["companies_prior"]))
    return out


def _company_rows(now: Dict[str, Dict], prior: Dict[str, Dict], titles: Dict[str, str]) -> List[Dict]:
    rows = []
    for cik, c in now.items():
        before = prior.get(cik)
        rows.append({
            "cik": cik, "ticker": c["ticker"], "name": c["name"], "sic": c["sic"],
            "industry": titles.get(c["sic"] or "", f"SIC {c['sic']}"),
            "phrases": sorted(c["phrases"]),
            "phrases_prior": sorted(before["phrases"]) if before else [],
            "new": before is None,
            "latest_form": c["latest_filing"]["form"],
            "latest_date": c["latest_filing"]["file_date"],
            "url": c["latest_filing"]["url"],
        })
    rows.sort(key=lambda r: (not r["new"], -len(r["phrases"]), r["name"]))
    return rows


def run_radar(session: Optional[requests.Session] = None) -> Dict:
    session = session or sec_utils.make_sec_session()
    windows = {"now": _window(0), "prior": _window(365)}
    titles = sic_descriptions(session)

    report = {"generated_at": time.time(), "windows": windows,
              "seller_phrases": SELLER_PHRASES, "buyer_phrases": BUYER_PHRASES}
    for side, phrases in (("seller", SELLER_PHRASES), ("buyer", BUYER_PHRASES)):
        now = _collect(phrases, windows["now"], session)
        prior = _collect(phrases, windows["prior"], session)
        report[side] = {
            "industries": build_industry_table(now, prior, titles),
            "companies": _company_rows(now, prior, titles),
            "phrases": phrase_trends(phrases, windows, session),
            "total_companies_now": len(now),
            "total_companies_prior": len(prior),
        }
    db.cache_set("industry_radar", "latest", report)
    return report


def get_latest_report() -> Optional[Dict]:
    return db.cache_get("industry_radar", "latest", ttl_seconds=None)


# =============================================================================
# Custom scored universe — radar finds go into the live buy score
# =============================================================================

def get_custom_universe() -> List[Dict]:
    return db.cache_get("scored_universe", "custom", ttl_seconds=None) or []


def add_to_universe(ticker: str, note: str = "") -> List[Dict]:
    ticker = ticker.strip().upper()
    items = [i for i in get_custom_universe() if i["ticker"] != ticker]
    items.append({"ticker": ticker, "note": note, "added": date.today().isoformat()})
    db.cache_set("scored_universe", "custom", items)
    return items


def remove_from_universe(ticker: str) -> List[Dict]:
    items = [i for i in get_custom_universe() if i["ticker"] != ticker.strip().upper()]
    db.cache_set("scored_universe", "custom", items)
    return items
