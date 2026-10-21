# backend/backtest.py
"""
Does a higher buy score actually precede better returns?

At each quarter end since START_DATE this rebuilds, from point-in-time
data only (see point_in_time.py), exactly what the Scanner would have
seen that day — mega-cap CapEx growth as filed by then, bottleneck
signals from the 10-Ks already filed, supplier matching, technicals,
year-over-year revenue growth, Item 1.01 deals in the prior 90 days, the
market-control rank and valuation — scores every company in the supplier
universe with the same scoring.compute_buy_score the live app uses, and
records the forward 3/6/12-month total returns.

Then, per factor and for the total score, it measures:
- information coefficient (IC): rank correlation between the factor and
  the next quarter's return relative to the universe average, per date,
  then averaged — with a t-stat and the share of quarters it was positive;
- for yes/no factors, the average excess return when true vs false;
- a simple strategy: hold the top-N scored names each quarter, equal
  weight, against the equal-weight universe and SPY.

Biases this CAN'T remove — read before trusting a good result:
- The supplier universe was hand-picked in 2026, with hindsight. Names
  like NVDA and VST are in it partly because they went on to win, so
  "universe beat SPY" says little. The useful question is whether the
  score ranks names WITHIN the universe — that's what IC measures.
- The detector's patterns were written in 2026 by reading 2026 filings.
- ~30 quarters x ~15 names is a small sample: a t-stat under ~2 is noise.
"""

import math
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import requests
from scipy import stats

from . import (
    bottleneck_detector, db, deal_monitor, insider_trading, point_in_time as pit, scoring, sec_utils,
)
from .scanner_pipeline import DEFAULT_WATCHLIST
from .supplier_matcher import SUPPLIER_TAXONOMY, match_suppliers_for_signal
from sec_financial_data import REVENUE_TAGS

START_DATE = "2017-12-31"
HORIZONS = (3, 6, 12)
BENCHMARK = "SPY"
TOP_N = 5
DEAL_LOOKBACK_DAYS = 90
CAPEX_THRESHOLD_PCT = 25.0
# Bump when detector or matching logic changes, so cached per-filing
# signals are recomputed rather than silently reused.
SIGNAL_CACHE_VERSION = "v1"

UNIVERSE = sorted({t for entry in SUPPLIER_TAXONOMY for t in entry["suppliers"]})

# Raw factor values recorded per (date, ticker). Direction: higher = better
# for all of them, so a positive IC means "the factor works as intended".
NUMERIC_FACTORS = [
    "score", "own_tightness", "signal_confidence", "relative_volume", "quarterly_revenue_growth_pct",
    "earnings_yield", "sales_yield", "fcf_yield", "growth_adjusted_sales_yield",
    "insider_buyers",
]
BINARY_FACTORS = [
    "own_tightness_any", "matched", "thesis_intact", "rel_volume_gt_2", "above_200sma",
    "revenue_growth_gt_25", "confirmed_deal", "market_control_leader",
    "insider_buy_any", "insider_cluster",
]


def quarter_ends(start: str, end: str) -> List[str]:
    out = []
    y, m = int(start[:4]), int(start[5:7])
    while True:
        last_day = (date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()
        if last_day > end:
            return out
        if last_day >= start:
            out.append(last_day)
        m += 3
        if m > 12:
            m -= 12
            y += 1


# =============================================================================
# Point-in-time scanner state
# =============================================================================

def _signals_for_filing(cik: str, filing: Dict, session: requests.Session) -> List[Dict]:
    key = f"{SIGNAL_CACHE_VERSION}_{cik}_{filing['accession_number']}"
    cached = db.cache_get("backtest_signals", key, ttl_seconds=None)
    if cached is not None:
        return cached
    text = sec_utils.fetch_filing_text(cik, filing, session)
    signals = bottleneck_detector.scan_filing_text(text) if text else []
    slim = [{k: s[k] for k in ("category_key", "category", "confidence", "all_evidence")}
            for s in signals]
    db.cache_set("backtest_signals", key, slim)
    return slim


def mega_cap_state(as_of: str, session: requests.Session) -> Dict[str, Dict]:
    state = {}
    for ticker in DEFAULT_WATCHLIST:
        cik = sec_utils.get_cik_for_ticker(ticker, session)
        if not cik:
            continue
        growth = pit.capex_yoy_growth(cik, as_of, session)
        filing = pit.latest_10k(cik, as_of, session)
        state[ticker] = {
            "capex_growth": growth,
            "thesis_intact": growth is not None and growth > CAPEX_THRESHOLD_PCT,
            "filing_date": filing["filing_date"] if filing else None,
            "signals": _signals_for_filing(cik, filing, session) if filing else [],
        }
    return state


def supplier_context(state: Dict[str, Dict]) -> Dict[str, Dict]:
    """Same aggregation as scanner_pipeline._compute_and_store_buy_scores, minus the LLM steps."""
    ctx: Dict[str, Dict] = {}
    for mega, st in state.items():
        for sig in st["signals"]:
            entries, _ = match_suppliers_for_signal(
                " ".join(sig["all_evidence"]), use_llm=False, category_key=sig["category_key"])
            for entry in entries:
                for ticker in entry["suppliers"]:
                    c = ctx.setdefault(ticker, {"best_confidence": 0.0, "thesis_intact": False,
                                                "groups": set(), "mega_caps": set()})
                    c["best_confidence"] = max(c["best_confidence"], sig["confidence"])
                    c["thesis_intact"] = c["thesis_intact"] or st["thesis_intact"]
                    c["groups"].add(entry["category_label"])
                    c["mega_caps"].add(mega)
    return ctx


def _market_control_leaders(ctx: Dict[str, Dict], as_of: str,
                            session: requests.Session) -> Dict[str, int]:
    """Best revenue rank of each matched ticker within the taxonomy groups it matched."""
    revenue: Dict[str, Optional[float]] = {}
    ranks: Dict[str, int] = {}
    for entry in SUPPLIER_TAXONOMY:
        members = [t for t in entry["suppliers"]
                   if t in ctx and entry["category_label"] in ctx[t]["groups"]]
        for t in members:
            if t not in revenue:
                cik = sec_utils.get_cik_for_ticker(t, session)
                v = pit.annual_value(cik, REVENUE_TAGS, as_of, session) if cik else None
                revenue[t] = v["val"] if v else None
        ordered = sorted((t for t in members if revenue.get(t)), key=lambda t: -revenue[t])
        for i, t in enumerate(ordered):
            ranks[t] = min(ranks.get(t, 99), i + 1)
    return ranks


def _commercial_deal(ticker: str, as_of: str, session: requests.Session) -> bool:
    cik = sec_utils.get_cik_for_ticker(ticker, session)
    if not cik:
        return False
    start = (datetime.fromisoformat(as_of) - timedelta(days=DEAL_LOOKBACK_DAYS)).date().isoformat()
    for filing in pit.item_101_8ks(cik, start, as_of, session):
        text = sec_utils.fetch_filing_text(cik, filing, session)
        result = deal_monitor.classify_item_101(text) if text else None
        if result and result["deal_type"] == "commercial":
            return True
    return False


def snapshot(as_of: str, session: requests.Session) -> List[Dict]:
    """One row per universe ticker with a price on as_of: raw factors, score, forward returns."""
    state = mega_cap_state(as_of, session)
    ctx = supplier_context(state)
    ranks = _market_control_leaders(ctx, as_of, session)

    rows = []
    for ticker in UNIVERSE:
        tech = pit.technicals(ticker, as_of)
        if tech["price"] is None:
            continue  # not listed yet (GEV, SNDK, ...) or no data
        cik = sec_utils.get_cik_for_ticker(ticker, session)
        c = ctx.get(ticker)
        rev_growth = pit.quarterly_revenue_yoy(cik, as_of, session) if cik else None
        val = pit.valuation(ticker, as_of, session)
        deal = _commercial_deal(ticker, as_of, session)
        rank = ranks.get(ticker)
        tight = bottleneck_detector.supplier_tightness(ticker, as_of, session)
        insider = insider_trading.insider_activity(cik, as_of) if cik else None
        market_data = {"relative_volume": tech["relative_volume"],
                       "above_200sma": tech["above_200sma"],
                       "quarterly_revenue_growth_pct": rev_growth}
        score = scoring.compute_buy_score(
            ticker=ticker,
            thesis_intact=bool(c and c["thesis_intact"]),
            signal_confidence=c["best_confidence"] if c else 0.0,
            market_data=market_data,
            confirmed_deal=deal,
            market_control_rank=rank,
            valuation=val,
            own_tightness=tight,
            insider=insider,
        )
        row = {
            "date": as_of, "ticker": ticker, "score": score["score"],
            "breakdown": {b["factor"]: b["points"] for b in score["breakdown"]},
            "matched": c is not None,
            "own_tightness": tight["mentions"] if tight else None,
            "own_tightness_any": bool(tight and tight["mentions"]),
            "insider_buyers": insider["discretionary_buyers"] if insider else None,
            "insider_buy_any": bool(insider and insider["discretionary_buyers"] >= 1),
            "insider_cluster": bool(insider and insider["discretionary_buyers"] >= 2),
            "signal_confidence": c["best_confidence"] if c else 0.0,
            "thesis_intact": bool(c and c["thesis_intact"]),
            "relative_volume": tech["relative_volume"],
            "rel_volume_gt_2": bool(tech["relative_volume"] and tech["relative_volume"] > 2.0),
            "above_200sma": tech["above_200sma"],
            "quarterly_revenue_growth_pct": rev_growth,
            "revenue_growth_gt_25": bool(rev_growth is not None and rev_growth > 25.0),
            "confirmed_deal": deal,
            "market_control_leader": rank == 1,
            "earnings_yield": val["earnings_yield"],
            "sales_yield": val["sales_yield"],
            "fcf_yield": val["fcf_yield"],
            "growth_adjusted_sales_yield": val["growth_adjusted_sales_yield"],
        }
        for h in HORIZONS:
            row[f"fwd_{h}m"] = pit.forward_return(ticker, as_of, h)
        rows.append(row)

    # Excess return vs the universe's equal-weight average that quarter —
    # isolates "did the score rank names well" from "did the sector rally".
    for h in HORIZONS:
        vals = [r[f"fwd_{h}m"] for r in rows if r[f"fwd_{h}m"] is not None]
        mean = sum(vals) / len(vals) if vals else None
        bench = pit.forward_return(BENCHMARK, as_of, h)
        for r in rows:
            r[f"excess_{h}m"] = (r[f"fwd_{h}m"] - mean) if (mean is not None and r[f"fwd_{h}m"] is not None) else None
            r[f"universe_{h}m"] = mean
            r[f"spy_{h}m"] = bench
    return rows


# =============================================================================
# Analysis (pure functions over snapshot rows)
# =============================================================================

def factor_ic(rows: List[Dict], factor: str, horizon: int = 3, min_names: int = 5) -> Dict:
    """Mean per-date Spearman IC between factor and excess return, with t-stat."""
    by_date: Dict[str, List[Dict]] = {}
    for r in rows:
        if r.get(factor) is not None and r.get(f"excess_{horizon}m") is not None:
            by_date.setdefault(r["date"], []).append(r)
    ics = []
    for d, rs in sorted(by_date.items()):
        xs = [float(r[factor]) for r in rs]
        if len(rs) < min_names or len(set(xs)) < 2:
            continue
        ic = stats.spearmanr(xs, [r[f"excess_{horizon}m"] for r in rs]).correlation
        if ic == ic:  # not NaN
            ics.append(ic)
    if not ics:
        return {"factor": factor, "mean_ic": None, "t_stat": None, "n_dates": 0, "pct_positive": None}
    mean = sum(ics) / len(ics)
    sd = (sum((x - mean) ** 2 for x in ics) / (len(ics) - 1)) ** 0.5 if len(ics) > 1 else 0.0
    t = mean / (sd / math.sqrt(len(ics))) if sd > 0 else None
    return {"factor": factor, "mean_ic": round(mean, 3), "t_stat": round(t, 2) if t is not None else None,
            "n_dates": len(ics), "pct_positive": round(sum(1 for x in ics if x > 0) / len(ics) * 100)}


def binary_split(rows: List[Dict], factor: str, horizon: int = 3) -> Dict:
    """Average excess return when the factor is true vs false (pooled)."""
    yes = [r[f"excess_{horizon}m"] for r in rows if r.get(factor) is True and r.get(f"excess_{horizon}m") is not None]
    no = [r[f"excess_{horizon}m"] for r in rows if r.get(factor) is False and r.get(f"excess_{horizon}m") is not None]
    out = {"factor": factor, "n_true": len(yes), "n_false": len(no),
           "mean_excess_true": round(sum(yes) / len(yes) * 100, 2) if yes else None,
           "mean_excess_false": round(sum(no) / len(no) * 100, 2) if no else None,
           "p_value": None}
    if len(yes) >= 5 and len(no) >= 5:
        out["p_value"] = round(stats.ttest_ind(yes, no, equal_var=False).pvalue, 3)
    return out


def top_n_strategy(rows: List[Dict], n: int = TOP_N, matched_only: bool = False) -> Dict:
    """Hold the top-n scored names each quarter (3-month, non-overlapping), equal weight."""
    by_date: Dict[str, List[Dict]] = {}
    for r in rows:
        if r.get("fwd_3m") is not None and (r["matched"] or not matched_only):
            by_date.setdefault(r["date"], []).append(r)
    curve = []
    strat = univ = spy = 1.0
    for d in sorted(by_date):
        rs = sorted(by_date[d], key=lambda r: (-r["score"], r["ticker"]))
        picks = rs[:n]
        if not picks:
            continue
        strat *= 1 + sum(r["fwd_3m"] for r in picks) / len(picks)
        univ *= 1 + rs[0]["universe_3m"]
        spy *= 1 + (rs[0]["spy_3m"] or 0.0)
        curve.append({"date": d, "strategy": round(strat, 4), "universe": round(univ, 4),
                      "spy": round(spy, 4), "picks": [r["ticker"] for r in picks]})
    years = len(curve) / 4
    def cagr(x):
        return round((x ** (1 / years) - 1) * 100, 1) if years and x > 0 else None
    return {"curve": curve, "quarters": len(curve),
            "cagr_strategy": cagr(strat), "cagr_universe": cagr(univ), "cagr_spy": cagr(spy),
            "quarters_beating_universe": sum(
                1 for i, c in enumerate(curve)
                if (c["strategy"] / (curve[i - 1]["strategy"] if i else 1.0))
                > (c["universe"] / (curve[i - 1]["universe"] if i else 1.0)))}


def analyze(rows: List[Dict]) -> Dict:
    return {
        "ic": {h: [factor_ic(rows, f, h) for f in NUMERIC_FACTORS + BINARY_FACTORS] for h in HORIZONS},
        "binary": [binary_split(rows, f) for f in BINARY_FACTORS],
        "strategy_all": top_n_strategy(rows),
        "strategy_matched": top_n_strategy(rows, matched_only=True),
    }


# =============================================================================
# Runner
# =============================================================================

def run_backtest(start: str = START_DATE, session: Optional[requests.Session] = None,
                 progress: Optional[callable] = None) -> Dict:
    session = session or sec_utils.make_sec_session()
    end = (date.today() - timedelta(days=95)).isoformat()  # need >= 3 months forward
    dates = quarter_ends(start, end)
    rows: List[Dict] = []
    for i, d in enumerate(dates):
        rows.extend(snapshot(d, session))
        if progress:
            progress(i + 1, len(dates), d)
    report = {
        "generated_at": time.time(),
        "start": dates[0] if dates else None,
        "end": dates[-1] if dates else None,
        "universe": UNIVERSE,
        "mega_caps": DEFAULT_WATCHLIST,
        "weights": scoring.current_weights(),
        "rows": rows,
        "analysis": analyze(rows),
    }
    db.cache_set("backtest_report", "latest", report)
    return report


def get_latest_report() -> Optional[Dict]:
    return db.cache_get("backtest_report", "latest", ttl_seconds=None)


# Score breakdown keys -> the backtest factor that measures them.
_EVIDENCE_FACTOR = {
    "own_tightness": "own_tightness",
    "valuation": "growth_adjusted_sales_yield",
    "signal_confidence": "signal_confidence",
    "revenue_growth": "revenue_growth_gt_25",
    "thesis_intact": "thesis_intact",
    "above_200sma": "above_200sma",
    "confirmed_deal": "confirmed_deal",
    "relative_volume": "rel_volume_gt_2",
    "market_control_leader": "market_control_leader",
    "insider_buying": "insider_buy_any",
}


def factor_evidence() -> Optional[Dict]:
    """
    {'score': {...}, 'factors': {breakdown_key: {...}}} — 3-month IC and
    t-stat from the latest backtest, for showing next to a live score.
    """
    report = get_latest_report()
    if not report:
        return None
    ic = {r["factor"]: r for r in report["analysis"]["ic"]["3"]}
    return {
        "generated_at": report["generated_at"],
        "period": f"{report['start']} to {report['end']}",
        "weights": report.get("weights"),
        "score": ic.get("score"),
        "factors": {k: ic.get(f) for k, f in _EVIDENCE_FACTOR.items()},
    }
