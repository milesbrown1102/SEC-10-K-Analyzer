# pages/4_Score_Validation.py
"""
Is the buy score worth anything? Two independent checks:

1. Backtest — the score rebuilt at every quarter end since 2017 from
   point-in-time data, against what happened next (backend/backtest.py).
2. Track record — every live scan's scores and prices, followed forward.
   Small today; the only evidence free of backtest hindsight.
"""

import time
from typing import Dict, Optional

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(page_title="Score Validation", layout="wide", page_icon="🧪")

if "api_base" not in st.session_state:
    st.session_state["api_base"] = "http://127.0.0.1:8000"
api_base = st.session_state["api_base"]

st.title("🧪 Score Validation")
st.caption("Does a higher buy score actually come before better returns? "
           "Tested on history, and tracked going forward.")

with st.expander("How to read this, and what it can't tell you", expanded=False):
    st.markdown("""
**IC (information coefficient)** is the rank correlation, each quarter, between a factor and the
next 3 months' return *relative to the other names in the universe*, averaged over all quarters.
- Around **0.05–0.10** is useful in practice. **0** means no predictive value. **Below 0** means
  the factor points the wrong way.
- **t-stat** shows whether the average is distinguishable from luck. Under about **2** in size,
  treat it as noise. This sample is small: about 30 quarters × about 15 stocks.

**Biases the backtest can't remove:**
- **The stock universe was chosen in 2026, with hindsight.** NVDA and VST are in it partly
  *because* they won. So "the universe beat the S&P 500" means little. What matters is whether
  the score **ranks stocks within the universe** well, which is what IC measures.
- **The bottleneck detector's patterns were written in 2026**, after reading 2026 filings.
- **Fundamentals are point-in-time; the universe isn't.** Data only counts from its SEC filing
  date (no peeking at restatements), but the stock list itself still has the hindsight above.

The **track record** at the bottom has none of these biases, but it needs months of live
scans before it says anything.
    """)


def _get(path: str, timeout: int = 15) -> Optional[Dict]:
    try:
        resp = requests.get(f"{api_base}{path}", timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


if not _get("/health", timeout=3):
    st.error("Can't reach the backend. Start it with "
             "`uvicorn backend.main:app --reload --reload-dir backend --port 8000`.")
    st.stop()

FACTOR_LABELS = {
    "score": "⭐ Total buy score",
    "matched": "Matched to a bottleneck",
    "signal_confidence": "Bottleneck-signal confidence",
    "thesis_intact": "Mega-cap CapEx growth > 25%",
    "relative_volume": "Relative volume",
    "rel_volume_gt_2": "Relative volume > 2x",
    "above_200sma": "Price above 200-day average",
    "quarterly_revenue_growth_pct": "Revenue growth (YoY)",
    "revenue_growth_gt_25": "Revenue growth > 25%",
    "confirmed_deal": "Commercial 8-K deal (90 days)",
    "market_control_leader": "Revenue leader in group",
    "earnings_yield": "Earnings yield (E/P)",
    "sales_yield": "Sales yield (S/P)",
    "fcf_yield": "Free-cash-flow yield",
    "growth_adjusted_sales_yield": "Growth-adjusted sales yield",
}

# -----------------------------------------------------------------------------
# Backtest
# -----------------------------------------------------------------------------

st.header("Backtest")
status = _get("/backtest/status") or {}
c1, c2 = st.columns([1, 3])
with c1:
    run = st.button("▶️ Run backtest", type="primary", disabled=status.get("in_progress"))
with c2:
    st.caption("The first run downloads about 8 years of filings and prices, which takes 10–20 minutes. "
               "Later runs reuse the cache.")
if run:
    requests.post(f"{api_base}/backtest/run", timeout=10)
    status["in_progress"] = True

if status.get("in_progress"):
    bar = st.progress(0.0, text="Starting…")
    while True:
        status = _get("/backtest/status") or {}
        if status.get("total"):
            bar.progress(status["done"] / status["total"],
                         text=f"Quarter {status['done']} of {status['total']} ({status.get('current')})")
        if not status.get("in_progress"):
            break
        time.sleep(3)
    st.rerun()
if status.get("error"):
    st.error(f"Last backtest failed: {status['error']}")

report = _get("/backtest/latest", timeout=60)
if not report:
    st.info("No backtest yet. Click **Run backtest**.")
else:
    a = report["analysis"]
    st.caption(
        f"{report['start']} → {report['end']} · {len(report['universe'])} stocks in the universe · "
        f"run {time.strftime('%Y-%m-%d %H:%M', time.localtime(report['generated_at']))} · "
        f"weights: {', '.join(f'{k} {v}' for k, v in report['weights'].items())}"
    )

    horizon = st.radio("Return horizon", ["3", "6", "12"], horizontal=True,
                       format_func=lambda h: f"{h} months",
                       help="3 months is the most reliable: quarters don't overlap. "
                            "6- and 12-month windows overlap, which overstates t-stats.")
    ic_rows = a["ic"][horizon]
    df = pd.DataFrame([{
        "Factor": FACTOR_LABELS.get(r["factor"], r["factor"]),
        "Mean IC": r["mean_ic"],
        "t-stat": r["t_stat"],
        "Quarters IC > 0": f"{r['pct_positive']}%" if r["pct_positive"] is not None else "—",
        "Quarters": r["n_dates"],
        "Verdict": ("—" if r["mean_ic"] is None or r["t_stat"] is None else
                    "✅ predictive" if r["mean_ic"] > 0 and r["t_stat"] >= 2 else
                    "❌ points the wrong way" if r["mean_ic"] < 0 and r["t_stat"] <= -2 else
                    "➖ not distinguishable from noise"),
    } for r in ic_rows])
    st.subheader("Which factors predicted relative returns?")
    st.dataframe(df, width="stretch", hide_index=True)

    st.subheader("Yes/no factors: average 3-month return vs the universe")
    bdf = pd.DataFrame([{
        "Factor": FACTOR_LABELS.get(r["factor"], r["factor"]),
        "When true": f"{r['mean_excess_true']:+.2f}%" if r["mean_excess_true"] is not None else "—",
        "When false": f"{r['mean_excess_false']:+.2f}%" if r["mean_excess_false"] is not None else "—",
        "Cases (true / false)": f"{r['n_true']} / {r['n_false']}",
        "p-value": r["p_value"] if r["p_value"] is not None else "—",
    } for r in a["binary"]])
    st.dataframe(bdf, width="stretch", hide_index=True)
    st.caption("p-value under 0.05: the difference is unlikely to be chance. These are pooled across "
               "quarters, which treats every stock-quarter as independent, so they're somewhat optimistic.")

    st.subheader("Strategy: hold the top 5 scored stocks, rebalanced quarterly")
    which = st.radio("Pick from", ["all", "matched"], horizontal=True,
                     format_func=lambda x: "Whole universe" if x == "all"
                     else "Only stocks matched to a bottleneck that quarter")
    strat = a["strategy_all" if which == "all" else "strategy_matched"]
    if strat["curve"]:
        cdf = pd.DataFrame(strat["curve"])
        fig = go.Figure()
        for col, name in [("strategy", "Top-5 by score"), ("universe", "Equal-weight universe"),
                          ("spy", "S&P 500 (SPY)")]:
            fig.add_trace(go.Scatter(x=cdf["date"], y=cdf[col], name=name, mode="lines"))
        fig.update_layout(yaxis_type="log", yaxis_title="Growth of $1 (log scale)", height=380,
                          margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Top-5 annual return", f"{strat['cagr_strategy']}%")
        m2.metric("Universe annual return", f"{strat['cagr_universe']}%")
        m3.metric("SPY annual return", f"{strat['cagr_spy']}%")
        m4.metric("Quarters top-5 beat universe", f"{strat['quarters_beating_universe']} / {strat['quarters']}")
        st.caption("The fair comparison is **top-5 vs the equal-weight universe**. The universe beating "
                   "SPY mostly reflects the hindsight in how it was chosen.")
        with st.expander("Picks each quarter"):
            st.dataframe(pd.DataFrame([{"Quarter end": c["date"], "Top 5": ", ".join(c["picks"])}
                                       for c in strat["curve"]]), width="stretch", hide_index=True)

    with st.expander("Raw backtest rows (every stock, every quarter)"):
        rows = pd.DataFrame(report["rows"]).drop(columns=["breakdown"], errors="ignore")
        st.dataframe(rows, width="stretch", hide_index=True)

# -----------------------------------------------------------------------------
# Live track record
# -----------------------------------------------------------------------------

st.header("Live track record")
st.caption("Every scan's buy scores and prices, recorded when the scan ran and followed forward. "
           "No hindsight. Meaningful once there are a few months of scans.")
track = _get("/scanner/track-record", timeout=60)
if not track or not track.get("picks"):
    st.info("No recorded scans yet. Scans run from now on are recorded automatically.")
else:
    tdf = pd.DataFrame([{
        "Scan date": p["scan_date"], "Ticker": p["ticker"], "Score": p["score"],
        "Price then": round(p["price_at_scan"], 2),
        "Price now": round(p["price_now"], 2) if p.get("price_now") else None,
        "Return": f"{p['return_pct']:+.1f}%" if p.get("return_pct") is not None else "—",
        "SPY same period": f"{p['spy_return_pct']:+.1f}%" if p.get("spy_return_pct") is not None else "—",
    } for p in track["picks"]])
    st.dataframe(tdf, width="stretch", hide_index=True)
    s = track.get("summary") or {}
    if s.get("n"):
        st.caption(f"{s['n']} recorded picks · scores ≥ {s['split']} averaged {s['high_avg']:+.1f}% vs "
                   f"{s['low_avg']:+.1f}% for lower scores · SPY {s['spy_avg']:+.1f}% over the same periods.")
