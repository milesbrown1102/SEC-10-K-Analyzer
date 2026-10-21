# backend/scoring.py
"""
Transparent buy score (and caution flags) for a candidate supplier.

Deliberately NOT a black-box number: compute_buy_score returns an itemized
breakdown alongside the total, so every point is traceable to a specific
piece of data shown elsewhere in the app. Nothing here is a prediction or
a recommendation.

Weights (v2, set 2026-10-19). The first backtest (backtest.py, 2017-2026)
found the v1 score had no predictive power — its rank correlation with
next-quarter relative returns was slightly negative (IC -0.07, t -1.4) —
and that it missed the 2025-26 memory shortage entirely, because only the
mega-caps' filings were read. v2 weights were fixed from economic
reasoning BEFORE re-running the backtest, so that run is a test of them,
not a fit:
- NEW supplier's own tightness (25): the supplier's own MD&A reporting
  constrained supply, rising prices, allocation — the most direct
  evidence of a bottleneck. (Caveat: this idea came from looking at the
  memory miss in the same data, so its backtest isn't fully independent.)
- NEW growth-adjusted valuation (15): sales yield x revenue growth. The
  only factor positive in both halves of the first backtest.
- Mega-cap signal 20->15, CapEx thesis 15->10, deal 20->10: no support.
- Relative volume and revenue-leader proxy 15/5 -> 0: noise / negative.
  Still shown as info so nothing disappears silently.

There's no mirror "sell score" — compute_caution_flags returns plain
reasons for doubt instead.
"""

from typing import Dict, List, Optional

POINTS_OWN_TIGHTNESS = 25
POINTS_VALUATION = 15
POINTS_SIGNAL_CONFIDENCE_MAX = 15
POINTS_REVENUE_GROWTH = 15
POINTS_THESIS_INTACT = 10
POINTS_ABOVE_200SMA = 10
POINTS_CONFIRMED_DEAL = 10
POINTS_RELATIVE_VOLUME = 0
POINTS_MARKET_CONTROL_LEADER = 0
# Insider open-market buying (Form 4): recorded by the backtest, shown as
# info until the evidence supports a weight.
POINTS_INSIDER_BUYING = 0

# Growth-adjusted sales yield = (revenue / market cap) x revenue growth %.
# Cut-offs are the top and middle thirds of the 2017-2026 backtest
# universe's values (set from the distribution of values, not returns).
VALUATION_FULL_AT = 6.75
VALUATION_HALF_AT = 2.24

# Supplier tightness: distinct sentences in its latest 10-K/10-Q MD&A.
TIGHTNESS_FULL_AT = 2


def current_weights() -> Dict[str, int]:
    return {
        "own_tightness": POINTS_OWN_TIGHTNESS,
        "valuation": POINTS_VALUATION,
        "signal_confidence": POINTS_SIGNAL_CONFIDENCE_MAX,
        "revenue_growth": POINTS_REVENUE_GROWTH,
        "thesis_intact": POINTS_THESIS_INTACT,
        "above_200sma": POINTS_ABOVE_200SMA,
        "confirmed_deal": POINTS_CONFIRMED_DEAL,
        "relative_volume": POINTS_RELATIVE_VOLUME,
        "market_control_leader": POINTS_MARKET_CONTROL_LEADER,
        "insider_buying": POINTS_INSIDER_BUYING,
    }


def _valuation_points(gasy: Optional[float]) -> int:
    if gasy is None:
        return 0
    if gasy >= VALUATION_FULL_AT:
        return POINTS_VALUATION
    if gasy >= VALUATION_HALF_AT:
        return round(POINTS_VALUATION / 2)
    return 0


def compute_buy_score(
    ticker: str,
    thesis_intact: bool,
    signal_confidence: float,
    market_data: Optional[Dict],
    confirmed_deal: bool,
    market_control_rank: Optional[int] = None,
    valuation: Optional[Dict] = None,
    own_tightness: Optional[Dict] = None,
    insider: Optional[Dict] = None,
) -> Dict:
    """
    Returns {'ticker', 'score' (0-100), 'breakdown': [{'key','factor','points','max','why'}, ...]}.
    Factors with max 0 are informational (kept visible, not scored).
    """
    breakdown = []
    market_data = market_data or {}
    valuation = valuation or {}
    own_tightness = own_tightness or {}

    def add(key, factor, points, max_points, why):
        breakdown.append({"key": key, "factor": factor, "points": points,
                          "max": max_points, "why": why})

    mentions = own_tightness.get("mentions")
    pts = (POINTS_OWN_TIGHTNESS if mentions and mentions >= TIGHTNESS_FULL_AT
           else round(POINTS_OWN_TIGHTNESS / 2) if mentions else 0)
    add("own_tightness", "Supplier's own filing reports tight supply / pricing power", pts,
        POINTS_OWN_TIGHTNESS,
        f"{mentions} sentence(s) in its latest {own_tightness.get('form', 'filing')} MD&A, e.g. "
        f"“{own_tightness['evidence'][0][:160]}…”" if mentions
        else "No tight-supply, pricing-power or allocation language in its latest MD&A"
        if mentions == 0 else "Supplier's own filing not checked")

    gasy = valuation.get("growth_adjusted_sales_yield")
    growth = valuation.get("revenue_growth_annual")
    sy = valuation.get("sales_yield")
    add("valuation", "Valuation vs growth (sales yield × revenue growth)", _valuation_points(gasy),
        POINTS_VALUATION,
        f"Price/sales {1 / sy:.1f}x with {growth:+.0f}% revenue growth → {gasy:.2f} "
        f"(full points ≥ {VALUATION_FULL_AT}, half ≥ {VALUATION_HALF_AT})"
        if gasy is not None and sy else
        f"Revenue shrank {growth:.0f}% last fiscal year — no growth to pay for"
        if growth is not None and growth <= 0 else "Valuation data unavailable")

    conf_points = round(POINTS_SIGNAL_CONFIDENCE_MAX * max(0.0, min(1.0, signal_confidence)))
    add("signal_confidence", "Bottleneck-signal confidence in mega-cap filings", conf_points,
        POINTS_SIGNAL_CONFIDENCE_MAX,
        f"Detected at {signal_confidence:.0%} confidence in a mega-cap customer's 10-K"
        if signal_confidence else "Not matched to any mega-cap bottleneck signal")

    rev_growth = market_data.get("quarterly_revenue_growth_pct")
    add("revenue_growth", "Quarterly revenue growth > 25% (YoY)",
        POINTS_REVENUE_GROWTH if (rev_growth is not None and rev_growth > 25.0) else 0,
        POINTS_REVENUE_GROWTH,
        f"Latest quarter vs same quarter last year: {rev_growth}%" if rev_growth is not None
        else "No revenue growth data available")

    add("thesis_intact", "Mega-cap customer's CapEx growth clears 25%",
        POINTS_THESIS_INTACT if thesis_intact else 0, POINTS_THESIS_INTACT,
        "A mega-cap customer that flagged this bottleneck grew CapEx > 25%"
        if thesis_intact else "No matched mega-cap customer grew CapEx > 25%")

    above_sma = market_data.get("above_200sma")
    add("above_200sma", "Price above 200-day moving average",
        POINTS_ABOVE_200SMA if above_sma else 0, POINTS_ABOVE_200SMA,
        "Trading above its own long-term trend" if above_sma
        else "At or below its 200-day average, or data unavailable")

    add("confirmed_deal", "Commercial agreement disclosed via SEC 8-K",
        POINTS_CONFIRMED_DEAL if confirmed_deal else 0, POINTS_CONFIRMED_DEAL,
        "A commercial (not financing / M&A) Item 1.01 agreement was filed recently"
        if confirmed_deal else "No recent commercial 8-K agreement (absence isn't evidence of no deal)")

    rel_vol = market_data.get("relative_volume")
    add("relative_volume", "Relative volume > 2.0x (info only)",
        0, POINTS_RELATIVE_VOLUME,
        f"Relative volume {rel_vol}. Not scored: no predictive value in the backtest"
        if rel_vol is not None else "No volume data")

    add("market_control_leader", "Largest revenue in matched group (info only)",
        0, POINTS_MARKET_CONTROL_LEADER,
        (f"Ranked #{market_control_rank} by revenue in its matched group. " if market_control_rank
         else "") + "Not scored: negative in the backtest")

    if insider is not None:
        n, disc, val = insider.get("buyers", 0), insider.get("discretionary_buyers", 0), insider.get("total_value", 0)
        add("insider_buying", "Insiders buying on the open market, last 90 days (info only)", 0,
            POINTS_INSIDER_BUYING,
            (f"{n} officer/director buyer(s), ${val:,.0f} total"
             + (f", {n - disc} under pre-set 10b5-1 plans" if n > disc else "")
             + ". Not scored until the backtest supports it")
            if n else "No officer or director open-market purchases filed in the last 90 days")

    total = sum(b["points"] for b in breakdown)
    return {"ticker": ticker, "score": total, "breakdown": breakdown}


def compute_caution_flags(
    signal_confidence: float,
    market_data: Optional[Dict],
    confirmed_deal: bool,
    valuation: Optional[Dict] = None,
) -> List[str]:
    """Plain-language reasons for doubt — see module docstring for why this isn't a score."""
    flags = []
    market_data = market_data or {}
    valuation = valuation or {}

    rev_growth = market_data.get("quarterly_revenue_growth_pct")
    if rev_growth is not None and rev_growth < 0:
        flags.append(f"Quarterly revenue growth is negative year-over-year ({rev_growth}%)")

    if market_data.get("above_200sma") is False:
        flags.append("Price is currently below its 200-day moving average")

    gasy = valuation.get("growth_adjusted_sales_yield")
    if gasy is not None and gasy < VALUATION_HALF_AT:
        flags.append("Expensive relative to its growth (bottom third on sales yield × growth)")

    if valuation.get("earnings_yield") is not None and valuation["earnings_yield"] < 0:
        flags.append("Unprofitable in its last fiscal year")

    if signal_confidence < 0.5 and not confirmed_deal:
        flags.append(
            "Low-confidence bottleneck signal and no confirmed deal this run — "
            "the thesis for this name may be weak or aging"
        )

    if market_data.get("error"):
        flags.append(f"Market data was incomplete: {market_data['error']}")

    return flags
