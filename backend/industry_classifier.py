# backend/industry_classifier.py
"""
Open-ended industry/problem discovery — Pass 3.

The Tier 3 supplier match (supplier_matcher.py) only ever recognizes an
industry if it's one of the ~6 hand-seeded categories in
SUPPLIER_TAXONOMY. That's precise but narrow: it can't tell you "this
bottleneck is about GPU compute" unless someone already wrote "GPU
compute" into the taxonomy by hand. This module is the fallback for
everything else — it asks the local LLM to read a signal's evidence text
and name the actual industry/problem plus the real, currently-public
companies that compete in it, the same way an analyst reading that
passage would reason "oh, this is the GPU/AI-accelerator industry — NVDA
and AMD are the players."

Two honesty notes, worth keeping in mind everywhere this module's output
shows up in the UI:

1. This is LLM judgment drawing on its own training data, not a verified
   database — unlike the curated taxonomy (deterministic keywords) or the
   ticker validation step below (checked against SEC's real ticker list),
   "which companies are in this industry" is not something that gets
   independently confirmed here. Every ticker IS checked against SEC's
   official company_tickers.json before being shown, so this can never
   surface a ticker that doesn't exist — but it can still surface a real
   company that isn't actually a meaningful competitor, or miss one that
   is. Treat this the same way you'd treat a knowledgeable friend's
   off-the-cuff answer: a good starting point, not a citation.

2. "Market control" has no free, structured data source anywhere (this is
   the same point supplier_matcher.py's docstring makes about "who
   controls >15% of a niche" — it isn't derivable from SEC filings or any
   free API). rank_by_market_control() below is a deliberate PROXY, not
   real market-share data: it ranks a group of tickers by their own
   reported revenue (and revenue growth) from SEC XBRL, on the reasoning
   that within the same specific industry, the biggest/fastest-growing
   revenue is often a reasonable stand-in for "who has the most control of
   it" — but it is not the same claim, and can be wrong (e.g. a company
   selling into many industries will look "biggest" here even in a niche
   where it's a minor player).
"""

import json
import re
from typing import Dict, List, Optional

import requests

from . import db, llm_client, sec_utils
from sec_financial_data import get_xbrl_financial_data

MAX_DISCOVERED_TICKERS = 5


def _validate_tickers(candidates: List[Dict], session: requests.Session) -> List[Dict]:
    """
    Keeps only candidates whose ticker resolves in SEC's official
    company_tickers.json — mirrors the same validation peer_analysis.py
    already does, so this module can never show a fabricated ticker.
    """
    try:
        lookup = sec_utils.get_ticker_lookup(session)
    except requests.RequestException:
        return []

    valid_tickers = {row["ticker"].upper() for row in lookup}
    validated = []
    for c in candidates:
        ticker = str(c.get("ticker", "")).strip().upper()
        if ticker and ticker in valid_tickers:
            validated.append({"ticker": ticker, "reason": str(c.get("reason", "")).strip()})
    return validated


def discover_industry_and_players(
    evidence_text: str,
    session: requests.Session,
    model: str = "llama3.2",
) -> Optional[Dict]:
    """
    Returns {'industry_label': str, 'problem': str, 'companies': [{'ticker','reason'}, ...]}
    or None if the LLM is unavailable, returns nothing usable, or nothing
    it named survives ticker validation.
    """
    if not evidence_text or not llm_client.is_available():
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "You are a financial analyst specializing in supply chains. "
                "Respond with ONLY valid JSON, no prose, no markdown fences."
            ),
        },
        {
            "role": "user",
            "content": f"""A large company's SEC filing contains this passage describing an
operational bottleneck or constraint:

"{evidence_text[:1200]}"

1. Name the specific industry or technical problem this describes (e.g.
   "AI/GPU compute accelerators", "enterprise flash storage", "grid-scale
   baseload power generation") — be specific, not generic ("technology").
2. Name up to {MAX_DISCOVERED_TICKERS} real, currently publicly-traded
   companies that are pure-play or major suppliers/competitors solving
   this specific problem (not the company the passage is from).

Respond with ONLY JSON in this exact shape:
{{"industry_label": "...", "problem": "one sentence", "companies": [{{"ticker": "XXXX", "reason": "one short sentence"}}]}}

If you cannot confidently identify a specific industry or any real public
companies in it, respond with {{"industry_label": null, "problem": null, "companies": []}}.""",
        },
    ]

    response = llm_client.chat(messages, model=model, max_tokens=500)
    if not response:
        return None

    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None

    if not parsed.get("industry_label") or not parsed.get("companies"):
        return None

    validated = _validate_tickers(parsed["companies"], session)
    if not validated:
        return None

    return {
        "industry_label": str(parsed["industry_label"]).strip(),
        "problem": str(parsed.get("problem", "")).strip(),
        "companies": validated,
    }


def rank_by_market_control(tickers: List[str], session: requests.Session) -> List[Dict]:
    """
    Ranks a group of tickers by reported revenue (SEC XBRL — real data),
    descending, as an approximate "who's biggest in this group" proxy for
    market control. See the module docstring: this is a proxy, not real
    market-share data.
    """
    ranked = []
    for ticker in tickers:
        cik = sec_utils.get_cik_for_ticker(ticker, session)
        if not cik:
            ranked.append({"ticker": ticker, "revenue": None, "revenue_formatted": None,
                            "note": "Could not resolve a CIK for this ticker"})
            continue

        cached = db.cache_get("xbrl_financials", cik, ttl_seconds=24 * 3600)
        if cached is None:
            cached = get_xbrl_financial_data(cik, session)
            db.cache_set("xbrl_financials", cik, cached)

        ranked.append({
            "ticker": ticker,
            "revenue": cached.get("revenue"),
            "revenue_formatted": cached.get("revenue_formatted"),
            "fiscal_year_end": cached.get("fiscal_year_end"),
            "note": None if cached.get("revenue") is not None else "No SEC XBRL revenue data found",
        })

    ranked.sort(key=lambda r: (r["revenue"] is None, -(r["revenue"] or 0)))
    for i, r in enumerate(ranked):
        r["market_control_rank"] = i + 1 if r["revenue"] is not None else None
    return ranked
