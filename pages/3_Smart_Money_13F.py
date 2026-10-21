# pages/3_Smart_Money_13F.py
"""
What well-known investors bought and sold last quarter, from SEC Form 13F
filings — plus how that lines up with the Bottleneck Scanner's picks.

All computation happens in backend/institutional_holdings.py; this page
only starts refreshes and renders the stored report. See that module's
docstring for what 13F data can and can't tell you.
"""

import time
from datetime import date
from typing import Dict, List, Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Smart Money (13F)", layout="wide", page_icon="🏦")

if "api_base" not in st.session_state:
    st.session_state["api_base"] = "http://127.0.0.1:8000"
api_base = st.session_state["api_base"]

st.title("🏦 Smart Money (13F)")
st.caption(
    "Quarter-over-quarter position changes for well-known investment managers, "
    "from the 13F holdings reports they're legally required to file with the SEC."
)

with st.expander("Read this before acting on anything here", expanded=False):
    st.markdown("""
- **It's delayed.** A 13F shows holdings at quarter end and is filed up to **45 days later**.
  By the time you see a purchase, the manager may already have sold.
- **It only shows long US stock positions.** No shorts, cash, bonds or non-US listings. A
  "new position" may be one half of a hedged trade you can't see.
- **Options are separate.** Puts and calls are reported as the number of underlying shares.
  They're labelled here and **left out of the consensus**, because a big put position is a bet
  the stock falls, not a purchase.
- **Check the position size.** A new position at 0.1% of a portfolio is a small trial, not
  conviction. Look at the *weight* column.
- **"Well-known" is not "proven".** 13Fs don't report returns. The list is a starting point
  for research, not a performance ranking.
    """)


# -----------------------------------------------------------------------------
# API helpers
# -----------------------------------------------------------------------------

def _get(path: str, timeout: int = 15) -> Optional[Dict]:
    try:
        resp = requests.get(f"{api_base}{path}", timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def _fmt_usd(v: Optional[float]) -> str:
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e9:
        return f"{sign}${v / 1e9:,.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:,.0f}M"
    return f"{sign}${v / 1e3:,.0f}K"


def _label(ch: Dict) -> str:
    return ch.get("ticker") or ch.get("name", "")[:28]


def _change_text(h: Dict) -> str:
    if h["change_type"] in ("new", "exited"):
        return h["change_type"]
    return f"{h['shares_change_pct']:+.0f}%"


def _largest_weight(holders: List[Dict]) -> str:
    held = [h for h in holders if h["change_type"] != "exited"]
    if not held:
        return "—"
    top = max(held, key=lambda h: h["weight_curr_pct"])
    return f"{top['weight_curr_pct']:.1f}% ({top['manager']})"


health = _get("/health", timeout=3)
if not health:
    st.error(
        "Can't reach the backend. Start it from the project root with "
        "`uvicorn backend.main:app --reload --port 8000`."
    )
    st.stop()

managers: List[Dict] = _get("/institutions/managers") or []
status = _get("/institutions/status") or {}

# -----------------------------------------------------------------------------
# Refresh controls
# -----------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Managers")
    options = {f"{m['name']} — {m['manager']}": m["cik"] for m in managers}
    defaults = [k for k, cik in options.items()
                if next(m for m in managers if m["cik"] == cik)["default"]]
    chosen = st.multiselect("Include in refresh", list(options), default=defaults)
    st.caption(
        "Quant and systematic funds (Renaissance, Bridgewater, ARK) are off by default. "
        "They hold thousands of positions, which slows the first refresh, and most of "
        "their quarterly changes are rebalancing rather than conviction buys."
    )
    refresh = st.button("🔄 Refresh 13F data", type="primary", disabled=status.get("in_progress"))

if refresh:
    resp = requests.post(f"{api_base}/institutions/refresh",
                         json={"ciks": [options[k] for k in chosen]}, timeout=10)
    if resp.status_code not in (200, 409):
        st.error(f"Could not start refresh: {resp.text}")
    status["in_progress"] = True

if status.get("in_progress"):
    with st.status("Refreshing 13F data… the first run maps every holding to a ticker "
                   "(a few minutes); later runs take seconds.", expanded=False) as box:
        for _ in range(600):
            time.sleep(2)
            status = _get("/institutions/status") or {}
            if not status.get("in_progress"):
                break
        box.update(label="Refresh complete", state="complete")
    st.rerun()

if status.get("last_error"):
    st.error(f"Last refresh failed: {status['last_error']}")

report = _get("/institutions/latest", timeout=30)
if not report:
    st.info("No 13F data yet. Click **Refresh 13F data** in the sidebar to build the first report.")
    st.stop()

ok_managers = [m for m in report["managers"] if not m.get("error")]
failed = [m for m in report["managers"] if m.get("error")]
periods = sorted({m["report_date"] for m in ok_managers}, reverse=True)
st.caption(
    f"{len(ok_managers)} managers · latest quarter-end in data: **{periods[0] if periods else '—'}** · "
    f"report built {time.strftime('%Y-%m-%d %H:%M', time.localtime(report['generated_at']))}"
)
if failed:
    with st.expander(f"⚠️ {len(failed)} manager(s) couldn't be loaded"):
        for m in failed:
            st.write(f"**{m['name']}**: {m['error']}")

tabs = st.tabs(["📈 Consensus buys", "👤 By manager", "🔗 Overlap with Scanner picks",
                "🧑‍💼 Insider buying (Form 4)"])

# -----------------------------------------------------------------------------
# Consensus
# -----------------------------------------------------------------------------

with tabs[0]:
    st.subheader("What the most managers bought last quarter")
    st.caption(
        "Common stock only. A *buyer* opened a new position or grew one by 10%+ in shares; "
        "a *seller* cut one by 10%+ or exited. Sorted by net buyers."
    )
    min_buyers = st.slider("Minimum number of buyers", 1, 6, 2)
    rows = [r for r in report["consensus"] if r["buyer_count"] >= min_buyers]
    if not rows:
        st.info("Nothing meets that threshold. Try lowering it.")
    else:
        df = pd.DataFrame([{
            "Ticker": r.get("ticker") or "—",
            "Company": r["name"],
            "Buyers": r["buyer_count"],
            "New positions": r["new_position_count"],
            "Sellers": r["seller_count"],
            "Net": r["net_buyers"],
            "Est. net $ flow": _fmt_usd(r["est_net_value_change"]),
            "Bought by": ", ".join(b["manager"] for b in r["buyers"]),
            "Sold by": ", ".join(s["manager"] for s in r["sellers"]),
        } for r in rows])
        top = df.head(15)
        fig = px.bar(top[::-1], x="Net", y=top[::-1]["Ticker"].where(top[::-1]["Ticker"] != "—",
                                                                     top[::-1]["Company"]),
                     orientation="h", labels={"y": "", "Net": "Net buyers (buyers − sellers)"},
                     height=max(260, 28 * len(top)))
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(df, width="stretch", hide_index=True)
        st.caption("Est. net $ flow = sum over managers of (share change × quarter-end price). "
                   "Approximate: managers traded at various prices during the quarter.")

# -----------------------------------------------------------------------------
# Per manager
# -----------------------------------------------------------------------------

with tabs[1]:
    if not ok_managers:
        st.info("No managers loaded.")
    else:
        names = [f"{m['name']} — {m.get('manager', '')}" for m in ok_managers]
        pick = st.selectbox("Manager", names)
        m = ok_managers[names.index(pick)]

        age_days = (date.today() - date.fromisoformat(m["report_date"])).days
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Reported 13F value", _fmt_usd(m.get("total_value")))
        c2.metric("Positions", m.get("position_count"))
        c3.metric("Quarter ending", m["report_date"], help=f"Compared with {m['prior_report_date']}")
        c4.metric("Filed", m.get("filing_date", "—"))
        if age_days > 150:
            st.warning(f"This manager's latest 13F is for a quarter that ended {age_days} days ago. "
                       "They may have filed late, stopped filing, or fallen below the threshold.")
        st.caption(f"Style: {m.get('style', '—')} · [View filing on EDGAR]({m.get('source_url')})")

        show_options = st.toggle("Include options (puts and calls)", value=False)
        changes = [c for c in m["changes"] if show_options or not c["put_call"]]

        def _table(kind: List[str]) -> pd.DataFrame:
            sel = [c for c in changes if c["change_type"] in kind]
            return pd.DataFrame([{
                "Ticker": _label(c) + (f" ({c['put_call']})" if c["put_call"] else ""),
                "Company": c["name"],
                "Share change": "new" if c["shares_change_pct"] is None
                                else f"{c['shares_change_pct']:+.0f}%",
                "Weight now": f"{c['weight_curr_pct']:.2f}%",
                "Weight before": f"{c['weight_prev_pct']:.2f}%",
                "Est. $ change": _fmt_usd(c["est_value_change"]),
                "Note": (f"adjusted for {c['split_adjusted']}:1 split"
                         + (" (unverified)" if c.get("split_verified") is False else ""))
                        if c["split_adjusted"] > 1 else "",
            } for c in sel])

        left, right = st.columns(2)
        with left:
            st.markdown("**🟢 New positions & adds**")
            t = _table(["new", "added"])
            st.dataframe(t, width="stretch", hide_index=True) if len(t) else st.caption("None")
        with right:
            st.markdown("**🔴 Trims & exits**")
            t = _table(["trimmed", "exited"])
            st.dataframe(t, width="stretch", hide_index=True) if len(t) else st.caption("None")

        st.markdown("**Top holdings by weight**")
        holdings = sorted([c for c in changes if c["change_type"] != "exited"],
                          key=lambda c: -c["weight_curr_pct"])[:15]
        if holdings:
            hdf = pd.DataFrame({"Holding": [_label(c) + (f" ({c['put_call']})" if c["put_call"] else "")
                                            for c in holdings],
                                "Weight %": [c["weight_curr_pct"] for c in holdings]})
            fig = px.bar(hdf[::-1], x="Weight %", y="Holding", orientation="h",
                         height=max(260, 26 * len(hdf)))
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis_title="")
            st.plotly_chart(fig, width="stretch")

# -----------------------------------------------------------------------------
# Overlap with Scanner
# -----------------------------------------------------------------------------

with tabs[2]:
    st.subheader("Are tracked managers in the Scanner's picks?")
    st.caption(
        "For each supplier the latest Bottleneck Scanner run scored, this lists which tracked "
        "managers hold it and what they did with it last quarter. The two views are independent: "
        "one is based on bottleneck language in filings, the other on investors' actual positions."
    )
    overlap = _get("/institutions/scanner-overlap", timeout=30)
    if not overlap:
        st.info("Run the Bottleneck Scanner at least once to see the overlap.")
    else:
        rows = []
        for ticker, score in sorted(overlap["buy_scores"].items(), key=lambda kv: -kv[1]):
            holders = overlap["holders"].get(ticker, [])
            buying = [h for h in holders if h["change_type"] in ("new", "added")]
            selling = [h for h in holders if h["change_type"] in ("trimmed", "exited")]
            rows.append({
                "Ticker": ticker,
                "Scanner score": score,
                "Managers holding": sum(1 for h in holders if h["change_type"] != "exited"),
                "Buying": ", ".join(f"{h['manager']} ({_change_text(h)})" for h in buying) or "—",
                "Selling": ", ".join(f"{h['manager']} ({_change_text(h)})" for h in selling) or "—",
                "Largest weight": _largest_weight(holders),
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption(f"Scanner run #{overlap['scan_run_id']}.")


# -----------------------------------------------------------------------------
# Insider buying (Form 4)
# -----------------------------------------------------------------------------

with tabs[3]:
    st.subheader("Companies whose own executives are buying")
    st.caption(
        "Open-market purchases by officers and directors with their own money, from Form 4 filings. "
        "Insiders sell for many reasons but buy for essentially one. Several insiders buying at once "
        "(a *cluster*) is the pattern with the most research support. Grants, option exercises and "
        "sales are excluded."
    )
    ins = _get("/insiders/status") or {}
    if not ins.get("quarters_loaded"):
        st.info("Insider data isn't loaded yet.")
        if st.button("Load insider data (about 2 minutes)"):
            requests.post(f"{api_base}/insiders/refresh", timeout=10)
            st.rerun()
    else:
        st.caption(f"{ins['purchases']:,} purchases since 2017 · quarterly SEC data through "
                   f"{ins['covers_through']}; later filings are read individually for scored companies.")
        c1, c2, c3 = st.columns(3)
        days = c1.select_slider("Window", [30, 60, 90, 180, 365], value=90,
                                format_func=lambda d: f"last {d} days")
        min_buyers = c2.slider("Minimum different insiders", 1, 6, 2)
        min_avg = c3.select_slider("Minimum average purchase per insider",
                                   [0, 10_000, 25_000, 50_000, 100_000, 250_000], value=50_000,
                                   format_func=lambda v: f"${v:,}",
                                   help="Filters out small, plan-style buying, e.g. foreign companies "
                                        "whose insiders began filing Form 4s in 2026.")
        data = _get(f"/insiders/clusters?days={days}&min_buyers={min_buyers}", timeout=60) or {}
        clusters = [c for c in data.get("clusters", []) if c["avg_per_buyer"] >= min_avg]
        if not clusters:
            st.info("No companies match. Try a longer window or fewer insiders.")
        else:
            st.dataframe(pd.DataFrame([{
                "Ticker": c["ticker"], "Company": c["issuer_name"],
                "Insiders buying": c["buyers"],
                "Not on a pre-set plan": c["discretionary_buyers"],
                "Total bought": _fmt_usd(c["total_value"]),
                "Avg per insider": _fmt_usd(c["avg_per_buyer"]),
                "Latest filing": c["latest_filing"],
                "Who": ", ".join(c["titles"]),
            } for c in clusters]), width="stretch", hide_index=True)
            st.caption("Not scored or backtested on its own here; the Score Validation page measures it as a "
                       "factor. Look up any ticker on the Industry Radar's drill-down for the full picture.")
