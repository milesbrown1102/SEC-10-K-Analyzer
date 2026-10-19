# pages/1_Bottleneck_Scanner.py
"""
Bottleneck Monopoly Scanner — a Streamlit page implementing the
Institutional Supply-Chain Investing Playbook's 3-tier pipeline.

This is a native Streamlit "multipage app" page (anything under pages/
becomes its own nav entry automatically), which is why it doesn't touch
app_beautiful_final.py at all — that file and its working single-company
flow are untouched.

It talks to the FastAPI backend (backend/main.py) over HTTP rather than
importing the pipeline directly, since that backend is also meant to be
the foundation for the eventual React frontend — this page is effectively
a reference implementation of an API client for it.

Run both processes from the project root:
    uvicorn backend.main:app --reload --port 8000
    streamlit run app_beautiful_final.py
"""

import time
from datetime import datetime
from typing import Dict, Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Bottleneck Scanner", layout="wide", page_icon="🔍")

if "api_base" not in st.session_state:
    st.session_state["api_base"] = "http://127.0.0.1:8000"
if "scan_polling" not in st.session_state:
    st.session_state["scan_polling"] = False

with st.sidebar:
    st.title("🔍 Scanner Settings")
    st.session_state["api_base"] = st.text_input(
        "Backend URL", value=st.session_state["api_base"],
        help="Where the FastAPI backend (uvicorn backend.main:app) is running."
    )
    api_base = st.session_state["api_base"]

    try:
        health = requests.get(f"{api_base}/health", timeout=3)
        if health.ok:
            st.success("Backend connected")
        else:
            st.error(f"Backend returned {health.status_code}")
    except requests.RequestException:
        st.error(
            "Can't reach the backend. Start it with:\n\n"
            "`uvicorn backend.main:app --reload --port 8000`"
        )

st.title("🔍 Bottleneck Monopoly Scanner")
st.caption(
    "Institutional Supply-Chain Investing Playbook, automated: mega-cap CapEx "
    "trends → bottleneck language in their own filings → matched pure-play "
    "suppliers → a market-data screen on those suppliers."
)

with st.expander("How this works (and its limits) — read this once"):
    st.markdown("""
**Tier 1 — CapEx trend.** Pulls each mega-cap's Capital Expenditures straight
from SEC XBRL data (not text-mined) and flags year-over-year growth above 25%.

**Tier 2 — Bottleneck language.** Scans each mega-cap's own MD&A and Risk
Factors sections for supply-constraint / backlog / power-infrastructure
language — generalized from the playbook's example phrases, not exact
string matches.

**Tier 3 — Supplier matching.** Matches a detected signal's evidence text
against a **small, hand-seeded taxonomy** (starting from the playbook's own
NVDA / VST / SNDK examples) by keyword, with an LLM fallback that can only
pick among that fixed list — it can't invent a ticker that isn't already in
the taxonomy. **This is not a market-share database** — "who controls >15%
of a niche" isn't freely available data anywhere, so treat matches as a
starting point to research further, the same way the playbook's own
validation matrix was hand-researched.

**Market screener.** Relative volume, 200-day moving average, and quarterly
revenue growth for matched suppliers, via yfinance (free, unofficial, can
be flaky — a screener error for one ticker doesn't block the others).

**Spin-off monitor.** Recent SEC Form 10-12B filings (the form used for
corporate separations) — a real, live feed, but parsed leniently since it
couldn't be tested against SEC's live response in the environment this was
built in. Treat every result as a lead to verify on EDGAR yourself, not a
confirmed spin-off.

**Industry discovery (Tier 3, step 3).** When the taxonomy above finds
nothing, the local LLM is asked to freely name the industry/problem and
real public companies in it — every ticker it names is still checked
against SEC's official ticker list, but *which* companies are relevant is
now the LLM's own judgment, not a vetted list. Shown in the UI as method
`llm_discovery` so you know it's less certain than a keyword match.

**Market control.** There's no free database of real market share
anywhere, so "market control" here is a proxy: matched suppliers are
ranked by their own reported SEC revenue. Biggest revenue ≠ biggest share
of this specific niche — treat it as a rough signal, not a citation.

**Deal monitor.** SEC 8-Ks (Item 1.01, "Entry into a Material Definitive
Agreement") are checked for the watchlist and every matched supplier —
this is a real, legally-required disclosure, so a hit here is confirmed,
though it can lag the actual signing by up to 4 business days. A
best-effort news search runs alongside it for leads 8-Ks might miss or
be too slow for — those are always unverified, always secondary.

**Buy score.** A fully transparent, itemized point total (not a
prediction) built from the signals already on this page: CapEx growth,
signal confidence, the market screener, a confirmed 8-K deal, and the
market-control proxy. Caution flags are separate plain-language notes,
not a mirrored "sell score" — see the Buy Scores tab for the full
breakdown behind every number.
    """)

st.divider()

default_watchlist = "MSFT, META, GOOGL, AMZN, AAPL"
watchlist_input = st.text_input(
    "Mega-cap watchlist (comma-separated tickers)", value=default_watchlist
)
watchlist = [t.strip().upper() for t in watchlist_input.split(",") if t.strip()]

col_run, col_status = st.columns([1, 3])
with col_run:
    run_clicked = st.button("🚀 Run Full Scan", type="primary", use_container_width=True)

if run_clicked:
    try:
        resp = requests.post(f"{api_base}/scanner/run", json={"watchlist": watchlist}, timeout=10)
        if resp.status_code == 409:
            st.warning("A scan is already running — wait for it to finish.")
        elif resp.ok:
            st.session_state["scan_polling"] = True
        else:
            st.error(f"Could not start scan: {resp.text}")
    except requests.RequestException as e:
        st.error(f"Could not reach the backend: {e}")

if st.session_state["scan_polling"]:
    status_placeholder = st.empty()
    with st.spinner("Scanning — fetching mega-cap 10-Ks and market data, this can take a couple minutes..."):
        max_wait_seconds = 600
        waited = 0
        while waited < max_wait_seconds:
            try:
                status = requests.get(f"{api_base}/scanner/status", timeout=10).json()
            except requests.RequestException as e:
                status_placeholder.error(f"Lost connection to the backend: {e}")
                st.session_state["scan_polling"] = False
                break

            if not status.get("in_progress"):
                st.session_state["scan_polling"] = False
                latest = status.get("latest_run") or {}
                if latest.get("status") == "failed":
                    st.error(f"Scan failed: {latest.get('error', 'unknown error')}")
                else:
                    st.success("Scan complete!")
                break

            status_placeholder.caption(f"Still running... ({waited}s elapsed, checking every 3s)")
            time.sleep(3)
            waited += 3
        else:
            status_placeholder.warning("Scan is taking longer than expected — check back and refresh.")
            st.session_state["scan_polling"] = False

st.divider()


def _fetch_latest_results() -> Optional[Dict]:
    try:
        resp = requests.get(f"{api_base}/scanner/latest", timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


results = _fetch_latest_results()

if not results:
    st.info("No scan has completed yet. Click **Run Full Scan** above to get started.")
else:
    run = results["run"]
    started = datetime.fromtimestamp(run["started_at"]).strftime("%Y-%m-%d %H:%M")
    st.caption(f"Showing results from run #{run['id']} — started {started}, status: {run['status']}")

    tabs = st.tabs([
        "📈 CapEx Trends", "🚨 Bottleneck Signals", "🏭 Candidate Suppliers",
        "🔀 Spin-Off Monitor", "🤝 Deal Monitor", "🎯 Buy Scores",
    ])

    # --- Tier 1: CapEx trends ------------------------------------------------
    with tabs[0]:
        st.subheader("Mega-Cap CapEx Trajectories")
        capex_data = results.get("capex", {})

        rows = []
        for ticker, points in capex_data.items():
            for p in points:
                rows.append({
                    "Ticker": ticker,
                    "Fiscal Year End": p["fiscal_year_end"],
                    "CapEx ($B)": round(p["capex_usd"] / 1_000_000_000, 2),
                    "YoY Growth %": p["yoy_growth_pct"],
                })

        if rows:
            df = pd.DataFrame(rows).sort_values(["Ticker", "Fiscal Year End"])
            fig = px.bar(
                df, x="Fiscal Year End", y="CapEx ($B)", color="Ticker", barmode="group",
                title="CapEx by fiscal year end ($B)"
            )
            st.plotly_chart(fig, use_container_width=True)

            latest_growth = (
                df.sort_values("Fiscal Year End").groupby("Ticker").tail(1)
                [["Ticker", "Fiscal Year End", "YoY Growth %"]]
            )
            st.markdown("**Most recent year-over-year CapEx growth:**")
            for _, row in latest_growth.iterrows():
                growth = row["YoY Growth %"]
                if growth is None:
                    continue
                if growth >= 25:
                    st.success(f"🚀 {row['Ticker']}: +{growth}% ({row['Fiscal Year End']}) — clears the 25% threshold")
                else:
                    st.info(f"{row['Ticker']}: {growth:+.1f}% ({row['Fiscal Year End']})")

            st.dataframe(df, use_container_width=True)
        else:
            st.info("No CapEx data was extracted — check that the watchlist tickers resolved correctly.")

    # --- Tier 2: Bottleneck signals -------------------------------------------
    with tabs[1]:
        st.subheader("Detected Bottleneck Signals")
        signals = results.get("signals", [])

        if not signals:
            st.info("No bottleneck language was detected in this run's filings.")
        else:
            for sig in sorted(signals, key=lambda s: s["confidence"], reverse=True):
                title = f"{sig['mega_cap_ticker']} — {sig['category']} (confidence {sig['confidence']:.0%})"
                with st.expander(title):
                    st.write(f"**Evidence:** “{sig['evidence']}”")
                    if sig.get("suppliers"):
                        industry = sig["suppliers"][0].get("industry_label")
                        if industry:
                            st.markdown(f"**Industry:** {industry}")
                        st.markdown("**Matched candidate suppliers:**")
                        for s in sorted(
                            sig["suppliers"],
                            key=lambda x: x.get("market_control_rank") or 999,
                        ):
                            method_note = (
                                " ⚠️ *open LLM discovery — not a vetted list, verify independently*"
                                if s["match_method"] == "llm_discovery" else
                                " *(LLM-assisted category match)*" if s["match_method"] == "llm"
                                else ""
                            )
                            rank_note = (
                                f" — revenue rank #{s['market_control_rank']} "
                                f"({s.get('revenue_formatted', 'n/a')}) among matches"
                                if s.get("market_control_rank") else ""
                            )
                            st.write(
                                f"- **{s['supplier_ticker']}**{method_note}: "
                                f"{s['match_reason']}{rank_note}"
                            )
                    else:
                        st.caption("No suppliers matched this signal in the current taxonomy or via open discovery.")

    # --- Tier 3: Candidate suppliers + market screener -----------------------
    with tabs[2]:
        st.subheader("Candidate Suppliers — Market Screen")
        st.caption(
            "Passes = relative volume > 2.0, price above 200-day moving average, "
            "and year-over-year quarterly revenue growth > 25% (all three, per the playbook)."
        )

        market_data = results.get("market_data", {})
        if not market_data:
            st.info("No suppliers were matched in this run, so there's nothing to screen yet.")
        else:
            rows = []
            for ticker, md in market_data.items():
                if not md:
                    continue
                rows.append({
                    "Ticker": ticker,
                    "Price": md.get("price"),
                    "Rel. Volume": md.get("relative_volume"),
                    "Above 200D MA": md.get("above_200sma"),
                    "Qtrly Rev Growth % (YoY)": md.get("quarterly_revenue_growth_pct"),
                    "Passes All Filters": "✅" if md.get("passes_all_filters") else "—",
                    "Error": md.get("error") or "",
                })
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True)
                passing = df[df["Passes All Filters"] == "✅"]
                if not passing.empty:
                    st.success(
                        "Clearing every filter right now: " + ", ".join(passing["Ticker"].tolist())
                    )

    # --- Spin-off monitor ------------------------------------------------------
    with tabs[3]:
        st.subheader("Spin-Off Catalyst Monitor")
        st.caption(
            "Recent Form 10-12B filings (used for corporate separations) from SEC "
            "EDGAR's live feed — verify each one on EDGAR before acting on it."
        )
        spinoffs = results.get("spinoffs", [])
        if not spinoffs:
            st.info("No recent Form 10-12B filings found.")
        else:
            for f in spinoffs[:25]:
                link = f.get("source_url")
                label = f["company_name"]
                if link:
                    st.markdown(f"- [{label}]({link}) — filed {f.get('filed_at', 'unknown date')}")
                else:
                    st.markdown(f"- {label} — filed {f.get('filed_at', 'unknown date')}")

    # --- Deal monitor ------------------------------------------------------
    with tabs[4]:
        st.subheader("Deal / Partnership Monitor")
        st.caption(
            "Checked for the watchlist and every matched supplier. SEC 8-K hits are "
            "confirmed, legally-required disclosures. News hits are unverified leads — "
            "always check the actual filing or press release before acting on one."
        )
        deals = results.get("deals", [])
        if not deals:
            st.info("No deal-shaped 8-Ks or news leads found this run.")
        else:
            confirmed = [d for d in deals if d["source"] == "sec_8k"]
            financing = [d for d in deals
                         if d["source"].startswith("sec_8k") and d["source"] != "sec_8k"]
            leads = [d for d in deals if not d["source"].startswith("sec_8k")]

            st.markdown(f"**✅ Commercial agreements confirmed via SEC 8-K ({len(confirmed)})**")
            if confirmed:
                for d in confirmed:
                    with st.expander(f"{d['ticker']} — {d['headline']}"):
                        if d.get("evidence"):
                            st.write(f"**Evidence:** “{d['evidence']}”")
                        if d.get("source_url"):
                            st.markdown(f"[View filing]({d['source_url']})")
            else:
                st.caption("None this run.")

            if financing:
                with st.expander(
                    f"🏦 Financing & other Item 1.01 agreements ({len(financing)}) — "
                    "debt, credit facilities, note offerings; not counted as deals"
                ):
                    for d in financing:
                        st.markdown(f"**{d['ticker']} — {d['headline']}**")
                        if d.get("evidence"):
                            st.caption(d["evidence"])
                        if d.get("source_url"):
                            st.markdown(f"[View filing]({d['source_url']})")

            st.markdown(f"**🔎 Unverified news leads ({len(leads)})**")
            if leads:
                for d in leads:
                    with st.expander(f"{d['ticker']} — {d['headline']}"):
                        if d.get("evidence"):
                            st.write(d["evidence"])
                        if d.get("source_url"):
                            st.markdown(f"[View source]({d['source_url']})")
            else:
                st.caption("None this run.")

    # --- Buy scores ----------------------------------------------------------
    with tabs[5]:
        st.subheader("Buy Scores")
        st.caption(
            "A transparent, itemized point total (0-100) built from signals already "
            "shown elsewhere on this page — not a prediction or a recommendation. "
            "Click a row's ticker below to see exactly where its points came from."
        )
        buy_scores = results.get("buy_scores", [])
        if not buy_scores:
            st.info("No candidate suppliers were matched this run, so there's nothing to score yet.")
        else:
            score_rows = [
                {
                    "Ticker": s["ticker"],
                    "Score": s["score"],
                    "Mega-Cap Signal": s.get("mega_cap_ticker"),
                    "Industry": s.get("industry_label") or "—",
                    "Caution Flags": len(s.get("caution_flags", [])),
                }
                for s in sorted(buy_scores, key=lambda x: x["score"], reverse=True)
            ]
            st.dataframe(pd.DataFrame(score_rows), use_container_width=True)

            for s in sorted(buy_scores, key=lambda x: x["score"], reverse=True):
                with st.expander(f"{s['ticker']} — score {s['score']}/100 breakdown"):
                    for b in s["breakdown"]:
                        st.write(f"- **+{b['points']}/{b['max']}** {b['factor']} — {b['why']}")
                    if s.get("caution_flags"):
                        st.markdown("**⚠️ Caution flags:**")
                        for flag in s["caution_flags"]:
                            st.write(f"- {flag}")
