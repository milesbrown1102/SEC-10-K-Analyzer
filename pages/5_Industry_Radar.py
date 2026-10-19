# pages/5_Industry_Radar.py
"""
Which industries are newly reporting tight supply — across every SEC
filer, not a hand-picked list. Computation lives in
backend/industry_radar.py; this page starts runs, renders the report,
drills into single companies, and manages the scored universe.
"""

import time
from typing import Dict, Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Industry Radar", layout="wide", page_icon="📡")

if "api_base" not in st.session_state:
    st.session_state["api_base"] = "http://127.0.0.1:8000"
api_base = st.session_state["api_base"]

st.title("📡 Industry Radar")
st.caption("Which industries are newly saying their products, or their inputs, are scarce. "
           "Searches every 10-K and 10-Q filed with the SEC.")

with st.expander("How this works, and its limits", expanded=False):
    st.markdown("""
- The radar searches **all 10-K and 10-Q filings** from the last 12 months for tightness
  phrases, and does the same for the 12 months before. It then compares the two by industry
  (SEC's SIC code).
- **The change is the signal.** Risk-factor boilerplate appears in both years and mostly
  cancels out. An industry where *more companies than last year* write "demand exceeds supply"
  is worth a look.
- **Seller-side** phrases ("demand exceeds supply", "pricing power", "record backlog") mean the
  company's **own product** is scarce, so it may have pricing power.
- **Buyer-side** phrases ("extended lead times", "supply shortages", "power availability") mean
  the company **can't get its inputs**, so the bottleneck sits with its *suppliers*.

**Limits:**
- This is exact-phrase matching. "We do not expect demand to exceed supply" also matches.
  The **drill-down** tab runs the full sentence-level detector on one company's latest filing.
- **Not backtested.** It's a tool for finding where to look, not a trading signal. The related
  supplier-tightness factor showed only a weak, unproven edge (see Score Validation).
- SIC codes are coarse and self-reported.
    """)


def _get(path: str, timeout: int = 20) -> Optional[Dict]:
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

status = _get("/radar/status") or {}
c1, c2 = st.columns([1, 3])
with c1:
    run = st.button("📡 Run radar", type="primary", disabled=status.get("in_progress"))
with c2:
    st.caption("About a minute. Completed 12-month windows are cached; the current window refreshes daily.")
if run:
    requests.post(f"{api_base}/radar/run", timeout=10)
    status["in_progress"] = True
if status.get("in_progress"):
    with st.spinner("Searching every 10-K and 10-Q filed in the last two years…"):
        while (_get("/radar/status") or {}).get("in_progress"):
            time.sleep(2)
    st.rerun()
if status.get("error"):
    st.error(f"Last radar run failed: {status['error']}")

report = _get("/radar/latest", timeout=60)

tabs = st.tabs(["🔥 Scarce products (seller-side)", "⛓️ Scarce inputs (buyer-side)",
                "📈 Phrase trends", "🔍 Company drill-down", "🎯 Scored universe"])


def _is_financial(sic: str) -> bool:
    return bool(sic) and sic.isdigit() and 6000 <= int(sic) <= 6799


def _side_tab(side: str, explainer: str):
    if not report:
        st.info("No radar yet. Click **Run radar**.")
        return
    data = report[side]
    w = report["windows"]
    st.caption(f"{explainer} Last 12 months ({w['now']['start']} → {w['now']['end']}) vs the 12 months "
               f"before. {data['total_companies_now']} companies now vs {data['total_companies_prior']} before.")
    hide_fin = st.toggle("Hide finance & real estate (SIC 6000–6799)", value=True, key=f"fin_{side}",
                         help="REITs and asset managers use 'pricing power' as boilerplate. "
                              "Bitcoin miners also file under finance codes.")
    rows = [r for r in data["industries"] if not (hide_fin and _is_financial(r["sic"]))]
    if not rows:
        st.info("No industries with enough companies.")
        return

    top = sorted(rows, key=lambda r: -r["change"])[:15]
    chart = pd.DataFrame({"Industry": [f"{r['industry'][:40]} ({r['sic']})" for r in top],
                          "Now": [r["companies_now"] for r in top],
                          "Year before": [r["companies_prior"] for r in top]})
    fig = px.bar(chart.iloc[::-1], y="Industry", x=["Year before", "Now"], orientation="h",
                 barmode="group", height=max(320, 30 * len(top)),
                 labels={"value": "Companies using these phrases", "variable": ""})
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")

    st.dataframe(pd.DataFrame([{
        "Industry": r["industry"], "SIC": r["sic"], "Companies now": r["companies_now"],
        "Year before": r["companies_prior"], "Change": r["change"], "New this year": r["new_companies"],
        "Tickers": ", ".join(r["tickers"][:12]) + (" …" if len(r["tickers"]) > 12 else ""),
    } for r in rows]), width="stretch", hide_index=True)

    st.markdown("**Companies**")
    industries = ["All"] + [f"{r['industry']} ({r['sic']})" for r in rows]
    pick = st.selectbox("Industry", industries, key=f"ind_{side}")
    only_new = st.toggle("Only companies new this year", value=True, key=f"new_{side}")
    comps = [c for c in data["companies"]
             if (not hide_fin or not _is_financial(c["sic"] or ""))
             and (pick == "All" or pick.endswith(f"({c['sic']})"))
             and (c["new"] or not only_new)]
    st.dataframe(pd.DataFrame([{
        "Ticker": c["ticker"] or "—", "Company": c["name"], "Industry": c["industry"],
        "Phrases (now)": ", ".join(c["phrases"]),
        "Phrases (year before)": ", ".join(c["phrases_prior"]) or "—",
        "Latest": f"{c['latest_form']} {c['latest_date']}", "Filing": c["url"],
    } for c in comps[:300]]), width="stretch", hide_index=True,
        column_config={"Filing": st.column_config.LinkColumn("Filing", display_text="open")})
    st.caption("Look up any ticker in the **Company drill-down** tab to run the full detector, "
               "check valuation, and add it to the scored universe.")


with tabs[0]:
    _side_tab("seller", "Companies saying their *own* product is scarce.")
with tabs[1]:
    _side_tab("buyer", "Companies saying they *can't get inputs*. The bottleneck is with their suppliers.")

with tabs[2]:
    if report:
        for side, label in (("seller", "Seller-side"), ("buyer", "Buyer-side")):
            st.markdown(f"**{label} phrases**: companies using each one, now vs a year before")
            st.dataframe(pd.DataFrame([{
                "Phrase": f"“{p['phrase']}”", "Companies now": p["companies_now"],
                "Year before": p["companies_prior"], "Change": p["companies_now"] - p["companies_prior"],
                "Filings now": p["filings_now"],
            } for p in report[side]["phrases"]]), width="stretch", hide_index=True)
    else:
        st.info("No radar yet.")

with tabs[3]:
    ticker = st.text_input("Ticker", placeholder="e.g. BE, MU, SMR").strip().upper()
    if ticker:
        with st.spinner(f"Reading {ticker}'s latest 10-K / 10-Q…"):
            d = _get(f"/radar/company/{ticker}", timeout=180)
        if not d:
            st.error(f"Couldn't load {ticker}. It may not be an SEC filer (foreign issuers file 20-F).")
        else:
            v, t, s = d["valuation"], d.get("tightness") or {}, d["score"]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Standalone buy score", f"{s['score']}/100",
                      help="Scored without mega-cap context (those factors are 0).")
            m2.metric("Tightness sentences", t.get("mentions", "—"),
                      help=f"In the MD&A of its {t.get('form', '')} filed {t.get('filing_date', '')}")
            m3.metric("Price / sales", f"{1 / v['sales_yield']:.1f}x" if v.get("sales_yield") else "—")
            m4.metric("Revenue growth (FY)", f"{v['revenue_growth_annual']:+.0f}%"
                      if v.get("revenue_growth_annual") is not None else "—")
            if t.get("evidence"):
                st.markdown("**From its own MD&A:**")
                for e in t["evidence"]:
                    st.write(f"> {e}")
            elif t:
                st.caption("No tight-supply, pricing-power or allocation sentences in its latest MD&A. "
                           "If the radar listed it, the phrase was probably in a risk factor or negated.")
            for flag in s.get("caution_flags", []):
                st.warning(flag)
            if d.get("fund_holders"):
                st.markdown("**Tracked funds (latest 13F):** " + ", ".join(
                    f"{h['manager']} ({h['change_type']}, {h['weight_curr_pct']:.1f}% of portfolio)"
                    for h in d["fund_holders"]))
            with st.expander("Score breakdown"):
                for b in s["breakdown"]:
                    pts = f"+{b['points']}/{b['max']}" if b["max"] else "info"
                    st.write(f"- **{pts}** {b['factor']} — {b['why']}")
            if d["in_universe"]:
                st.success(f"{ticker} is in the scored universe. The Scanner scores it on every run.")
            else:
                note = st.text_input("Note (optional)", key="note", placeholder="why you're watching it")
                if st.button(f"➕ Add {ticker} to the scored universe"):
                    r = requests.post(f"{api_base}/universe", json={"ticker": ticker, "note": note}, timeout=20)
                    if r.ok:
                        st.success(f"Added. {ticker} will be scored on the next Scanner run.")
                    else:
                        st.error(r.text)

with tabs[4]:
    u = _get("/universe") or {"taxonomy": [], "custom": []}
    st.markdown(f"**Hand-picked supplier taxonomy ({len(u['taxonomy'])}):** {', '.join(u['taxonomy'])}")
    st.markdown(f"**Added by you ({len(u['custom'])}):**")
    if not u["custom"]:
        st.caption("Nothing yet. Add companies from the drill-down tab.")
    for item in u["custom"]:
        a, b = st.columns([5, 1])
        a.write(f"**{item['ticker']}** · added {item['added']}" + (f" · {item['note']}" if item.get("note") else ""))
        if b.button("Remove", key=f"rm_{item['ticker']}"):
            requests.delete(f"{api_base}/universe/{item['ticker']}", timeout=10)
            st.rerun()
    st.caption("The Bottleneck Scanner scores every name here on each run, and the live track record "
               "follows them. They aren't in the backtest, whose universe is fixed so results stay comparable.")
