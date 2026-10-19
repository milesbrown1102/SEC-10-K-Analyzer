# backend/scoring.py
"""
Transparent buy score (and caution flags) for a candidate supplier —
Pass 3's answer to "give me a buy score or even a sell score."

Deliberately NOT a black-box number: compute_buy_score returns an
itemized breakdown alongside the total, so every point is traceable to a
specific, already-visible piece of data elsewhere in the app (CapEx
growth, bottleneck-signal confidence, the market screener, a confirmed
8-K deal, the revenue-based market-control proxy). Nothing here is a
prediction or a recommendation — it's a weighted summary of signals you
could just as easily add up yourself by reading the other tabs; the
score just saves you doing that arithmetic by hand.

There's no mirror "sell score" — a single number implying "how much to
sell" would overstate what this data can actually tell you. Instead,
compute_caution_flags returns a plain list of specific reasons for doubt
(decelerating revenue, price below trend, thesis going stale), which is a
more honest shape for "here's what would make me cautious" than a
fabricated score would be.
"""

from typing import Dict, List, Optional

# Max points per factor — sums to 100. Weights reflect how directly each
# factor is grounded in real data: the market screener (real price/volume
# data) and a confirmed 8-K deal (a real legal disclosure) carry the most
# weight; the market-control proxy (see industry_classifier.py) carries
# the least, since it's the most approximate of the inputs.
POINTS_THESIS_INTACT = 15
POINTS_SIGNAL_CONFIDENCE_MAX = 20
POINTS_RELATIVE_VOLUME = 15
POINTS_ABOVE_200SMA = 10
POINTS_REVENUE_GROWTH = 15
POINTS_CONFIRMED_DEAL = 20
POINTS_MARKET_CONTROL_LEADER = 5


def compute_buy_score(
    ticker: str,
    thesis_intact: bool,
    signal_confidence: float,
    market_data: Optional[Dict],
    confirmed_deal: bool,
    market_control_rank: Optional[int] = None,
) -> Dict:
    """
    Returns {'ticker', 'score' (0-100), 'breakdown': [{'factor','points','max','why'}, ...]}.
    """
    breakdown = []
    market_data = market_data or {}

    points = POINTS_THESIS_INTACT if thesis_intact else 0
    breakdown.append({
        "factor": "Mega-cap customer's CapEx growth clears the 25% threshold",
        "points": points, "max": POINTS_THESIS_INTACT,
        "why": "The underlying demand thesis (Tier 1) is still supported by real spending data"
               if thesis_intact else "No confirmed CapEx acceleration from the mega-cap customer this run",
    })

    conf_points = round(POINTS_SIGNAL_CONFIDENCE_MAX * max(0.0, min(1.0, signal_confidence)))
    breakdown.append({
        "factor": "Bottleneck-signal confidence (Tier 2)",
        "points": conf_points, "max": POINTS_SIGNAL_CONFIDENCE_MAX,
        "why": f"Detected at {signal_confidence:.0%} confidence in the mega-cap's own filing language",
    })

    rel_vol = market_data.get("relative_volume")
    rel_vol_points = POINTS_RELATIVE_VOLUME if (rel_vol is not None and rel_vol > 2.0) else 0
    breakdown.append({
        "factor": "Relative volume > 2.0x (unusual trading interest)",
        "points": rel_vol_points, "max": POINTS_RELATIVE_VOLUME,
        "why": f"Current relative volume: {rel_vol}" if rel_vol is not None else "No market data available",
    })

    above_sma = market_data.get("above_200sma")
    sma_points = POINTS_ABOVE_200SMA if above_sma else 0
    breakdown.append({
        "factor": "Price above 200-day moving average",
        "points": sma_points, "max": POINTS_ABOVE_200SMA,
        "why": "Trading above its own long-term trend" if above_sma
               else "At or below its 200-day average, or data unavailable",
    })

    rev_growth = market_data.get("quarterly_revenue_growth_pct")
    rev_points = POINTS_REVENUE_GROWTH if (rev_growth is not None and rev_growth > 25.0) else 0
    breakdown.append({
        "factor": "Quarterly revenue growth > 25% (YoY)",
        "points": rev_points, "max": POINTS_REVENUE_GROWTH,
        "why": f"Latest quarter vs same quarter last year: {rev_growth}%" if rev_growth is not None
               else "No revenue growth data available",
    })

    deal_points = POINTS_CONFIRMED_DEAL if confirmed_deal else 0
    breakdown.append({
        "factor": "Confirmed deal disclosed via SEC 8-K",
        "points": deal_points, "max": POINTS_CONFIRMED_DEAL,
        "why": "A real, legally-required disclosure of a material agreement was found this run"
               if confirmed_deal else "No 8-K deal disclosure found this run (absence isn't evidence of no deal)",
    })

    rank_points = POINTS_MARKET_CONTROL_LEADER if market_control_rank == 1 else 0
    breakdown.append({
        "factor": "Largest revenue among matched suppliers (market-control proxy)",
        "points": rank_points, "max": POINTS_MARKET_CONTROL_LEADER,
        "why": "Ranked #1 by reported revenue in its matched group — a proxy for scale, not verified market share"
               if market_control_rank == 1
               else f"Ranked #{market_control_rank} by revenue in its matched group" if market_control_rank
               else "No market-control ranking available",
    })

    total = sum(b["points"] for b in breakdown)
    return {"ticker": ticker, "score": total, "breakdown": breakdown}


def compute_caution_flags(
    signal_confidence: float,
    market_data: Optional[Dict],
    confirmed_deal: bool,
) -> List[str]:
    """Plain-language reasons for doubt — see module docstring for why this isn't a score."""
    flags = []
    market_data = market_data or {}

    rev_growth = market_data.get("quarterly_revenue_growth_pct")
    if rev_growth is not None and rev_growth < 0:
        flags.append(f"Quarterly revenue growth is negative year-over-year ({rev_growth}%)")

    if market_data.get("above_200sma") is False:
        flags.append("Price is currently below its 200-day moving average")

    if signal_confidence < 0.5 and not confirmed_deal:
        flags.append(
            "Low-confidence bottleneck signal and no confirmed deal this run — "
            "the thesis for this name may be weak or aging"
        )

    if market_data.get("error"):
        flags.append(f"Market data was incomplete: {market_data['error']}")

    return flags
