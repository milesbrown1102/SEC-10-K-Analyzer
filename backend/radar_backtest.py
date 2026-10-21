# backend/radar_backtest.py
"""
Does a company NEWLY reporting tight supply go on to outperform?

The Industry Radar's company-level question, tested on history. Each
quarter since 2016, SEC full-text search finds every company whose 10-K /
10-Q filed that quarter used a seller-side tightness phrase
(industry_radar.SELLER_PHRASES). Each such company is either:
- "new": no such phrase in its filings over the prior four quarters, or
- "persistent": it was already saying it.
Forward 3/6/12-month total returns are compared with SPY and with IWM
(small caps — most radar companies are small).

Statistics are computed across QUARTERS, not stocks: each quarter's
average excess return is one observation, so a single hot quarter where
everything moved together counts once. With ~40 quarters, |t| < 2 is noise.

Biases to keep in mind:
- Survivorship: yfinance has no prices for most delisted companies, so
  they drop out — which flatters results. Coverage is reported.
- The phrase list was written in 2026.
- Tickers come from SEC's current company names, so a company that has
  since changed ticker may be priced under the new one (fine) or missing.
"""

import math
import time
from datetime import date, timedelta
from typing import Dict, List, Optional

import requests
from scipy import stats

from . import db, industry_radar, insider_trading, sec_utils

START = "2016-03-31"
HORIZONS = (3, 6, 12)
BENCHMARKS = ("SPY", "IWM")
PRICE_BATCH = 80


def _quarter_ends(start: str, end: str) -> List[str]:
    from .backtest import quarter_ends
    return quarter_ends(start, end)


def _qwindow(q_end: str) -> Dict[str, str]:
    """The 3 calendar months ending on q_end."""
    y, m = int(q_end[:4]), int(q_end[5:7])
    sm, sy = m - 2, y
    if sm <= 0:
        sm += 12
        sy -= 1
    return {"start": f"{sy:04d}-{sm:02d}-01", "end": q_end}


def companies_by_quarter(quarters: List[str], session: requests.Session,
                         progress=None) -> Dict[str, Dict[str, Dict]]:
    """{quarter_end: {cik: {ticker, name, sic, phrases}}} for seller-side phrases."""
    out: Dict[str, Dict[str, Dict]] = {}
    for i, q in enumerate(quarters):
        w = _qwindow(q)
        found: Dict[str, Dict] = {}
        for phrase in industry_radar.SELLER_PHRASES:
            for h in industry_radar.search_phrase(phrase, w["start"], w["end"], session):
                c = found.setdefault(h["cik"], {"ticker": h["ticker"], "name": h["name"],
                                                "sic": h["sic"], "phrases": []})
                if phrase not in c["phrases"]:
                    c["phrases"].append(phrase)
                c["ticker"] = c["ticker"] or h["ticker"]
        out[q] = found
        if progress:
            progress(i + 1, len(quarters), q, "searching filings")
    return out


# =============================================================================
# Monthly prices for many tickers
# =============================================================================

def monthly_closes(tickers: List[str], progress=None) -> Dict[str, Dict[str, float]]:
    """
    {ticker: {'YYYY-MM': adjusted month-end close}} via yfinance batch
    downloads; cached per ticker for a week (empty = no data, also cached).
    """
    out: Dict[str, Dict[str, float]] = {}
    todo = []
    for t in sorted(set(tickers)):
        cached = db.cache_get("monthly_close", t, ttl_seconds=7 * 86400)
        if cached is not None:
            out[t] = cached
        else:
            todo.append(t)
    import yfinance as yf
    for i in range(0, len(todo), PRICE_BATCH):
        batch = todo[i:i + PRICE_BATCH]
        try:
            df = yf.download(batch, start="2015-12-01", interval="1mo", auto_adjust=True,
                             progress=False, group_by="ticker", threads=True)
        except Exception:
            df = None
        for t in batch:
            series: Dict[str, float] = {}
            try:
                col = df[t]["Close"] if len(batch) > 1 else df["Close"]
                for idx, v in col.dropna().items():
                    series[idx.strftime("%Y-%m")] = float(v)
            except Exception:
                pass
            out[t] = series
            db.cache_set("monthly_close", t, series)
        if progress:
            progress(min(i + PRICE_BATCH, len(todo)), len(todo), batch[-1], "downloading prices")
    return out


def _month_add(ym: str, months: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def forward_return(closes: Dict[str, float], q_end: str, months: int) -> Optional[float]:
    start = q_end[:7]
    end = _month_add(start, months)
    if start not in closes or end not in closes or end >= date.today().isoformat()[:7]:
        return None
    return closes[end] / closes[start] - 1 if closes[start] else None


# =============================================================================
# Events + statistics
# =============================================================================

def build_events(by_q: Dict[str, Dict[str, Dict]]) -> List[Dict]:
    """Pure function. One event per (quarter, company with a seller-side hit), labelled new/persistent."""
    quarters = sorted(by_q)
    events = []
    for i, q in enumerate(quarters):
        if i < 4:
            continue  # need four prior quarters to tell new from persistent
        prior = set().union(*(by_q[p].keys() for p in quarters[i - 4:i]))
        for cik, c in by_q[q].items():
            if not c["ticker"]:
                continue
            events.append({"quarter": q, "cik": cik, "ticker": c["ticker"], "name": c["name"],
                           "sic": c["sic"], "phrases": c["phrases"],
                           "kind": "persistent" if cik in prior else "new"})
    return events


def quarter_stats(events: List[Dict], horizon: int, bench: str) -> Dict:
    """
    Pure function over events carrying f'excess_{bench}_{horizon}m'.
    Mean of per-quarter average excess returns, t-stat across quarters,
    plus the pooled median and share of events that beat the benchmark.
    """
    key = f"excess_{bench}_{horizon}m"
    by_q: Dict[str, List[float]] = {}
    pooled = []
    for e in events:
        v = e.get(key)
        if v is None:
            continue
        by_q.setdefault(e["quarter"], []).append(v)
        pooled.append(v)
    qmeans = [sum(v) / len(v) for v in by_q.values()]
    out = {"events": len(pooled), "quarters": len(qmeans), "mean_excess_pct": None,
           "t_stat": None, "median_excess_pct": None, "pct_beating": None}
    if not qmeans:
        return out
    mean = sum(qmeans) / len(qmeans)
    out["mean_excess_pct"] = round(mean * 100, 2)
    if len(qmeans) > 2:
        sd = (sum((x - mean) ** 2 for x in qmeans) / (len(qmeans) - 1)) ** 0.5
        out["t_stat"] = round(mean / (sd / math.sqrt(len(qmeans))), 2) if sd else None
    s = sorted(pooled)
    out["median_excess_pct"] = round(s[len(s) // 2] * 100, 2)
    out["pct_beating"] = round(sum(1 for x in pooled if x > 0) / len(pooled) * 100)
    return out


def difference_test(a: List[Dict], b: List[Dict], horizon: int, bench: str) -> Dict:
    """Pure function. Per-quarter mean of group a minus group b, t-stat across quarters."""
    key = f"excess_{bench}_{horizon}m"

    def by_q(events):
        d: Dict[str, List[float]] = {}
        for e in events:
            if e.get(key) is not None:
                d.setdefault(e["quarter"], []).append(e[key])
        return {q: sum(v) / len(v) for q, v in d.items()}

    qa, qb = by_q(a), by_q(b)
    diffs = [qa[q] - qb[q] for q in qa if q in qb]
    if len(diffs) < 3:
        return {"quarters": len(diffs), "mean_diff_pct": None, "t_stat": None}
    t = stats.ttest_1samp(diffs, 0.0)
    return {"quarters": len(diffs), "mean_diff_pct": round(sum(diffs) / len(diffs) * 100, 2),
            "t_stat": round(float(t.statistic), 2)}


def run_radar_backtest(session: Optional[requests.Session] = None, progress=None) -> Dict:
    session = session or sec_utils.make_sec_session()
    # One extra year before START so the first quarters can be labelled.
    first = (date.fromisoformat(START) - timedelta(days=365)).isoformat()
    quarters = _quarter_ends(first, (date.today() - timedelta(days=95)).isoformat())
    by_q = companies_by_quarter(quarters, session, progress)
    events = build_events(by_q)

    closes = monthly_closes([e["ticker"] for e in events] + list(BENCHMARKS), progress)
    for e in events:
        c = closes.get(e["ticker"]) or {}
        e["has_prices"] = bool(c)
        for h in HORIZONS:
            r = forward_return(c, e["quarter"], h)
            e[f"fwd_{h}m"] = r
            for b in BENCHMARKS:
                br = forward_return(closes.get(b) or {}, e["quarter"], h)
                e[f"excess_{b}_{h}m"] = (r - br) if (r is not None and br is not None) else None
        # Insider overlay: officer/director open-market purchase filed in
        # the 90 days to the quarter end (data starts 2017).
        if e["quarter"] >= "2017-06-30":
            ins = insider_trading.insider_activity(e["cik"], e["quarter"])
            e["insider_buy"] = ins["discretionary_buyers"] >= 1
        else:
            e["insider_buy"] = None

    groups = {
        "new": [e for e in events if e["kind"] == "new"],
        "persistent": [e for e in events if e["kind"] == "persistent"],
        "new_with_insider_buying": [e for e in events if e["kind"] == "new" and e["insider_buy"]],
        "all": events,
    }
    results = {name: {f"{b}_{h}m": quarter_stats(evs, h, b) for b in BENCHMARKS for h in HORIZONS}
               for name, evs in groups.items()}
    report = {
        "generated_at": time.time(),
        "quarters": [q for q in quarters if q >= START],
        "events": len(events),
        "coverage_pct": round(sum(1 for e in events if e["has_prices"]) / len(events) * 100) if events else 0,
        "counts": {k: len(v) for k, v in groups.items()},
        "results": results,
        "new_vs_persistent": {f"{b}_{h}m": difference_test(groups["new"], groups["persistent"], h, b)
                              for b in BENCHMARKS for h in HORIZONS},
        "recent_new": sorted([{k: e[k] for k in ("quarter", "ticker", "name", "phrases", "fwd_3m",
                                                 "excess_SPY_3m", "insider_buy")}
                              for e in groups["new"] if e["quarter"] >= quarters[-4]],
                             key=lambda e: (e["quarter"], e["ticker"]), reverse=True),
    }
    db.cache_set("radar_backtest", "latest", report)
    return report


def get_latest_report() -> Optional[Dict]:
    return db.cache_get("radar_backtest", "latest", ttl_seconds=None)
