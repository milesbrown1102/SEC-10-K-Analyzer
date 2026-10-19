# backend/historical_pipeline.py
"""
Multi-year bottleneck-signal trend for a single ticker — Pass 3's answer to
"check filings current and past to trends."

The original Tier 2 (bottleneck_detector.py) only ever looked at a
company's LATEST 10-K. This module runs the exact same detection logic
against several years of that company's own past 10-Ks, so you can see
when (if ever) bottleneck-style language started showing up, instead of
only a single point-in-time snapshot.

Important honesty note, since this is the module that answers "would this
have caught NVIDIA in 2013": running today's detection logic against old
filings is NOT the same as proving the system would have flagged it in
real time back then — the language it looks for (drawn from a 2025-era
playbook, i.e. hindsight) may not be the language a company used to
describe an emerging bottleneck years before it was obviously one. NVIDIA
itself is a good example: its 2013 10-K describes a gaming-GPU company,
not an "AI compute bottleneck" — that framing only became legible once
CUDA + deep learning took off around 2015-2016. What this DOES give you
honestly: a real, unfiltered look at exactly what language did or didn't
appear in a company's own filings, year by year, so you can judge for
yourself how early a pattern became visible — not a guarantee the system
would have acted on it before the rest of the market did.
"""

import time
from typing import Dict, List

import requests

from . import bottleneck_detector, capex_pipeline, db, sec_utils


def run_historical_trend(ticker: str, session: requests.Session,
                          max_years: int = 6) -> Dict:
    """
    Fetches up to `max_years` of this ticker's own past 10-Ks, runs the
    bottleneck detector against each one, and persists + returns a
    year-by-year trend alongside the CapEx series (which capex_pipeline.py
    already computes across every available year, not just the latest).
    """
    ticker = ticker.strip().upper()
    cik = sec_utils.get_cik_for_ticker(ticker, session)
    if not cik:
        return {"ticker": ticker, "error": f"Could not resolve a CIK for '{ticker}'",
                "signal_trend": [], "capex_trend": []}

    filings = sec_utils.get_historical_10k_filings(cik, session, max_filings=max_years)
    if not filings:
        return {"ticker": ticker, "error": "No 10-K filings found for this ticker",
                "signal_trend": [], "capex_trend": []}

    signal_trend = []
    for filing in filings:
        content = sec_utils.fetch_filing_text(cik, filing, session)
        if not content:
            continue

        signals = bottleneck_detector.scan_filing_text(content)

        for sig in signals:
            db.upsert_historical_signal(
                ticker, filing["filing_date"], sig["category"],
                sig["evidence"], sig["confidence"],
            )
            signal_trend.append({
                "fiscal_year_end": filing["filing_date"],
                "category": sig["category"],
                "confidence": sig["confidence"],
                "evidence": sig["evidence"],
            })

        time.sleep(0.1)

    capex_trend = capex_pipeline.get_capex_series(cik, session)

    return {"ticker": ticker, "error": None, "signal_trend": signal_trend,
            "capex_trend": capex_trend}


def get_stored_historical_trend(ticker: str) -> List[Dict]:
    """Reads back whatever's already been computed for this ticker, without re-fetching."""
    return db.get_historical_signals(ticker.strip().upper())
