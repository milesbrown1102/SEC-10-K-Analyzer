# backend/deal_monitor.py
"""
Deal / partnership monitor — Pass 3's answer to "monitor new deals in the
media or in filings as soon as they're done."

Two sources, deliberately not treated as equally trustworthy, per your
own framing that filings should take precedence since they're legally
binding:

1. SEC 8-Ks, Item 1.01 ("Entry into a Material Definitive Agreement") —
   source='sec_8k'. Public companies are legally required to file one
   within 4 business days of signing a material agreement (this is
   exactly the kind of filing that would have disclosed something like
   the Meta/SanDisk deal). Real, structured, mechanically checkable —
   same trust level as the CapEx/XBRL data elsewhere in this app. Not
   instant (up to a 4-business-day lag by law), and only catches deals
   material enough to require disclosure.

2. A best-effort news/headline scan — source='news_search'. Reuses this
   project's existing enhanced_web_search.py DuckDuckGo scraper (the same
   one already used for the main app's Web Intelligence tab), so it
   carries the exact same, already-documented fragility: unofficial,
   rate-limit-prone, no guarantee of completeness or recency. Every hit
   from this source is an UNVERIFIED LEAD, not a confirmed deal — always
   shown as secondary to any 8-K hit, and only worth acting on after
   checking the actual company disclosure yourself.
"""

import re
import time
from typing import Dict, List, Optional

import requests

from enhanced_web_search import EnhancedWebSearch
from . import db, sec_utils

# Generalized deal/partnership language — deliberately broad since 8-K
# Item 1.01 covers everything from supply agreements to joint ventures,
# not just the "strategic partnership" framing a press release might use.
DEAL_KEYWORDS = [
    r"definitive agreement",
    r"supply agreement",
    r"collaboration agreement",
    r"strategic partnership",
    r"multi-?year agreement",
    r"master (?:supply|purchase) agreement",
    r"joint venture",
    r"licensing agreement",
    r"manufacturing agreement",
]
DEAL_KEYWORD_RE = re.compile("|".join(DEAL_KEYWORDS), re.IGNORECASE)
ITEM_101_RE = re.compile(r"item\s*1\.01", re.IGNORECASE)

# Item 1.01 covers ANY material agreement — most are debt (credit facility
# amendments, notes offerings, indentures), which say nothing about demand.
# These are told apart by what the Item 1.01 body actually describes.
ITEM_101_HEADING_RE = re.compile(
    r"item\s*1\.01[\s.:\-–—]*entry\s+into\s+a\s+material\s+definitive\s+agreement\.?",
    re.IGNORECASE,
)
NEXT_ITEM_RE = re.compile(r"\bitem\s*\d\.\d\d\b", re.IGNORECASE)
COMMERCIAL_RE = re.compile(
    r"\b(?:partnership|supply|purchase\s+(?:of|commitment)|offtake|power\s+purchase"
    r"|capacity|collaboration|licens(?:e|ing)|joint\s+venture|acquisition|acquire"
    r"|merger|customer|strategic|data\s*cent(?:er|re)|lease\s+of|manufactur)\w*",
    re.IGNORECASE,
)
FINANCING_RE = re.compile(
    r"\b(?:credit\s+agreement|credit\s+facility|revolving|term\s+loan|indenture"
    r"|(?:senior|subordinated|junior)[\w\s]{0,40}notes|notes\s+due|debentures"
    r"|underwriting\s+agreement|underwritten\s+public\s+offering|aggregate\s+principal"
    r"|receivables\s+(?:purchase|financing|facility)|commercial\s+paper|loan\s+agreement)\b",
    re.IGNORECASE,
)


def _extract_deal_snippet(text: str) -> Optional[str]:
    """First deal-keyword hit, trimmed to word boundaries, ~250 chars of context."""
    m = DEAL_KEYWORD_RE.search(text)
    if not m:
        return None

    start = max(0, m.start() - 120)
    end = min(len(text), m.end() + 150)
    if start > 0:
        space_idx = text.find(" ", start)
        if space_idx != -1 and space_idx < end:
            start = space_idx + 1
    if end < len(text):
        space_idx = text.rfind(" ", start, end)
        if space_idx != -1:
            end = space_idx

    return re.sub(r"\s+", " ", text[start:end]).strip()


def classify_item_101(text: str) -> Optional[Dict]:
    """
    Pure function. Returns {'deal_type': 'commercial'|'financing'|'other',
    'evidence': <start of the Item 1.01 body>} or None if this 8-K has no
    Item 1.01 section. Classification reads the opening of the body: a
    commercial partnership that mentions credit support further down (as
    NVIDIA's SB Energy 8-K does) is still commercial.
    """
    flat = re.sub(r"\s+", " ", text)
    heading = ITEM_101_HEADING_RE.search(flat)
    if not heading:
        return None
    body = flat[heading.end():heading.end() + 4000]
    nxt = NEXT_ITEM_RE.search(body)
    if nxt:
        body = body[:nxt.start()]
    body = body.strip()
    opening = body[:700]

    commercial = len(COMMERCIAL_RE.findall(opening))
    financing = len(FINANCING_RE.findall(opening))
    if commercial and commercial >= financing:
        deal_type = "commercial"
    elif financing:
        deal_type = "financing"
    else:
        deal_type = "other"

    evidence = body[:450]
    if len(body) > 450:
        evidence = evidence[:evidence.rfind(" ")] + "…"
    return {"deal_type": deal_type, "evidence": evidence}


def check_8k_deals_for_ticker(ticker: str, session: requests.Session,
                               max_filings: int = 5) -> List[Dict]:
    """
    Fetches this ticker's most recent 8-Ks and returns one event per
    Item 1.01 filing. Commercial agreements get source='sec_8k' (the only
    kind that earns buy-score points); debt/financing agreements get
    'sec_8k_financing' and anything unclassifiable 'sec_8k_other' — still
    real disclosures, kept visible, just not counted as a deal.
    """
    cik = sec_utils.get_cik_for_ticker(ticker, session)
    if not cik:
        return []

    filings = sec_utils.get_recent_8k_filings(cik, session, max_filings=max_filings)
    hits = []
    for filing in filings:
        text = sec_utils.fetch_filing_text(cik, filing, session)
        if not text:
            continue

        classified = classify_item_101(text)
        if classified is None and ITEM_101_RE.search(text) and DEAL_KEYWORD_RE.search(text):
            # Non-standard heading wording — fall back to the keyword snippet.
            classified = {"deal_type": "other", "evidence": _extract_deal_snippet(text)}
        if classified:
            source = {"commercial": "sec_8k", "financing": "sec_8k_financing"}.get(
                classified["deal_type"], "sec_8k_other")
            label = {"sec_8k": "commercial agreement", "sec_8k_financing": "financing",
                     "sec_8k_other": "other agreement"}[source]
            hits.append({
                "ticker": ticker,
                "source": source,
                "deal_type": classified["deal_type"],
                "headline": f"{ticker} 8-K (Item 1.01, {label}) — {filing['filing_date']}",
                "evidence": classified["evidence"],
                "event_date": filing["filing_date"],
                "source_url": sec_utils.get_filing_document_url(cik, filing),
            })
        time.sleep(0.05)

    return hits


def check_news_leads_for_ticker(ticker: str, company_name: Optional[str] = None) -> List[Dict]:
    """
    Best-effort news scan — see module docstring. Always source='news_search',
    always an unverified lead.
    """
    searcher = EnhancedWebSearch()
    query = f"{company_name or ticker} partnership OR agreement OR deal announcement"
    try:
        results = searcher._search_duckduckgo(query)
    except Exception:
        return []

    leads = []
    for r in results[:5]:
        title = (r.get("title") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        if not title:
            continue
        leads.append({
            "ticker": ticker,
            "source": "news_search",
            "headline": title,
            "evidence": snippet,
            "event_date": None,
            "source_url": r.get("url"),
        })
    return leads


def run_deal_monitor(tickers: List[str], session: requests.Session, run_id: int,
                      include_news: bool = True,
                      ticker_names: Optional[Dict[str, str]] = None) -> List[Dict]:
    """
    Runs both sources for each ticker in `tickers` and persists every hit.
    `ticker_names` (ticker -> company display name) improves the news
    query if you have it handy; falls back to the bare ticker otherwise.
    """
    all_events = []
    for ticker in tickers:
        try:
            filings_hits = check_8k_deals_for_ticker(ticker, session)
        except Exception:
            filings_hits = []

        news_hits = []
        if include_news:
            company_name = (ticker_names or {}).get(ticker)
            try:
                news_hits = check_news_leads_for_ticker(ticker, company_name)
            except Exception:
                news_hits = []

        for event in filings_hits:
            # Re-checking a filing replaces its earlier row, so filings
            # stored before classification existed get corrected.
            db.delete_deal_events_for_url(event["ticker"], event.get("source_url"))
        for event in filings_hits + news_hits:
            db.add_deal_event(
                event["ticker"], event["source"], event["headline"],
                event.get("evidence"), event.get("event_date"),
                event.get("source_url"), run_id,
            )
            all_events.append(event)

    return all_events
