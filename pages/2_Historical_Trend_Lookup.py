# pages/2_Historical_Trend_Lookup.py
"""
Historical bottleneck-signal trend lookup for ANY ticker — not just the
Scanner's mega-cap watchlist.

This exists to let you test the "would this have caught it early" idea
directly, on any company and any years SEC has filings for, rather than
take it on faith. Read the caveat box below before drawing conclusions
from a quiet or noisy result — see backend/historical_pipeline.py for the
full reasoning.
"""

from typing import Dict, Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Historical Trend Lookup", layout="wide", page_icon="🕰️")

if "api_base" not in st.session_state:
    st.session_state["api_base"] = "http://127.0.0.1:8000"
api_base = st.session_state["api_base"]

st.title("🕰️ Historical Trend Lookup")
st.caption(
    "Runs the same bottleneck-language detection used by the Scanner against "
    "a single company's own past 10-Ks, year by year — for any ticker."
)

with st.expander("Read this before drawing conclusions", expanded=False):
    st.markdown("""
This is **not** a backtest that proves the system would have "caught" anything in
real time. It runs today's detection patterns — generalized from a
present-day playbook — against old filings. A company's old filings
describe their business the way *it looked at the time*, not with the
benefit of hindsight. NVIDIA's own 2013 10-K reads as a gaming-GPU
company; the "AI compute bottleneck" framing wasn't legible in filing
language until roughly 2015-2016, once CUDA and deep learning adoption
took off.

What this **does** give you honestly: an unfiltered, year-by-year look at
exactly what language did or didn't appear in a company's own risk
factors and MD&A, so you can judge for yourself how early a pattern
became visible in the text — without me overselling what pattern-matching
old documents can prove.
    """)

st.divider()

ticker_input = st.text_input("Ticker", value="", placeholder="e.g. NVDA").strip().upper()
max_years = st.slider("How many years of 10-Ks to check", min_value=2, max_value=10, value=6)
run_clicked = st.button("🔍 Run Historical Trend", type="primary")


def _fetch_stored(ticker: str) -> Optional[Dict]:
    try:
        resp = requests.get(f"{api_base}/historical/{ticker}", timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def _fetch_aftermath(ticker: str, filing_date: str) -> Optional[Dict]:
    try:
        resp = requests.get(f"{api_base}/historical/{ticker}/aftermath",
                            params={"filing_date": filing_date}, timeout=600)
        return resp.json() if resp.ok else None
    except requests.RequestException:
        return None


def _pct(v) -> str:
    return f"{v:+.1f}%" if v is not None else "—"


def _render_aftermath(am: Dict):
    if not am["window_complete"]:
        st.caption(f"Less than 12 months have passed; showing what's happened up to {am['window_end']}.")

    # 1. Stock
    st.markdown("**How the stock did after this filing**")
    cols = st.columns(4)
    for col, h in zip(cols, ("3m", "6m", "12m")):
        r = am["stock"].get(h)
        if r and r["return_pct"] is not None:
            col.metric(f"{h[:-1]} months later", _pct(r["return_pct"]),
                       delta=f"{r['vs_spy_pct']:+.1f} pts vs S&P 500" if r["vs_spy_pct"] is not None else None)
        else:
            col.metric(f"{h[:-1]} months later", "—", help="Not enough time has passed")
    t = am["stock"]["to_today"]
    cols[3].metric("Filing → today", _pct(t["return_pct"]), help=f"S&P 500 over the same period: {_pct(t['spy_pct'])}")

    # 2. Money into other companies
    st.markdown("**Did it put money into, or sign with, other companies?**")
    deals = am["counterparty_deals"]
    if deals:
        st.caption("From the *other* company's 8-K. A deal that's small for a giant is material for the "
                   "smaller company, which must disclose it.")
        st.dataframe(pd.DataFrame([{
            "Date": d["date"],
            "What": "💰 Invested in them" if d["relationship"] == "invested" else "🤝 Agreement",
            "Company": d["company"], "Ticker": d["ticker"] or "—", "Industry": d["industry"] or "—",
            "Their stock, next 12m": _pct(d["return_12m_pct"]),
            "S&P 500, same 12m": _pct(d["spy_12m_pct"]),
            "Their stock, to today": _pct(d["return_to_today_pct"]),
            "Filing": d["url"],
        } for d in deals]), width="stretch", hide_index=True,
            column_config={"Filing": st.column_config.LinkColumn("Filing", display_text="8-K")})
        with st.expander("What each filing says"):
            for d in deals:
                st.markdown(f"**{d['date']} · {d['company']}**: “{d['evidence']}”")
    else:
        st.caption("No other company's 8-K named it as an investor or counterparty in this period.")

    tf = am.get("thirteen_f")
    if tf and tf["positions"]:
        st.markdown(f"**New or bigger stakes in public companies** (its own 13F: "
                    f"{tf['from_filing'] or 'first filing'} → {tf['to_filing']})")
        st.dataframe(pd.DataFrame([{
            "Ticker": p["ticker"] or "—", "Company": p["company"], "Industry": p["industry"] or "—",
            "New / added": p["change"], "Position value": f"${(p['value'] or 0) / 1e6:,.0f}M",
            "Stock, next 12m": _pct(p["return_12m_pct"]), "Stock, to today": _pct(p["return_to_today_pct"]),
        } for p in tf["positions"]]), width="stretch", hide_index=True)

    if am["own_deals"]:
        st.markdown("**Its own 8-K agreements** (commercial and M&A; debt excluded)")
        for d in am["own_deals"]:
            st.markdown(f"- {d['date']} · {d['type'].replace('_', ' ')}"
                        + (f" with **{d['counterparty']}**" if d.get("counterparty") else "")
                        + f": “{d['evidence'][:300]}…” [filing]({d['url']})")

    # 3. In-house
    st.markdown("**Did it fix it in-house, and say so?**")
    cap = am.get("capex")
    if cap and cap["change_pct"] is not None:
        st.write(f"CapEx: ${cap['before_usd'] / 1e9:,.1f}B (FY ending {cap['before_fy']}) → "
                 f"${cap['after_usd'] / 1e9:,.1f}B (FY ending {cap['after_fy']}), **{cap['change_pct']:+.0f}%**.")
    disc = am["disclosed"]
    if disc["in_house"]:
        st.markdown("*Building or doing it itself:*")
        for x in disc["in_house"]:
            st.write(f"> {x['sentence']}  \n— {x['form']} filed {x['date']}")
    if disc["secured_supply"]:
        st.markdown("*Securing supply by contract (prepayments, long-term supply / power agreements):*")
        for x in disc["secured_supply"]:
            st.write(f"> {x['sentence']}  \n— {x['form']} filed {x['date']}")
    if not disc["in_house"] and not disc["secured_supply"]:
        st.caption("No in-house or secured-supply statements found in its filings from this period.")


result = None
if run_clicked and ticker_input:
    with st.spinner(f"Fetching and scanning up to {max_years} years of {ticker_input}'s 10-Ks..."):
        try:
            resp = requests.post(
                f"{api_base}/historical/run",
                json={"ticker": ticker_input, "max_years": max_years},
                timeout=120,
            )
            if resp.ok:
                result = resp.json()
            else:
                st.error(f"Could not run this lookup: {resp.text}")
        except requests.RequestException as e:
            st.error(f"Could not reach the backend: {e}")
elif ticker_input:
    stored = _fetch_stored(ticker_input)
    if stored:
        st.caption(f"Showing previously computed results for {ticker_input}. Click the button above to refresh.")
        result = {"ticker": ticker_input, "signal_trend": stored["signal_trend"], "capex_trend": []}

if result and result.get("signal_trend") is not None:
    trend = result["signal_trend"]
    if not trend:
        st.info(
            f"No bottleneck-style language was detected in any of {ticker_input}'s "
            f"checked filings. That can mean the company genuinely never used this "
            f"kind of language — or that the detection patterns (generalized from the "
            f"playbook's own examples) just don't match how this particular company "
            f"writes about its business. Worth reading a filing or two yourself before "
            f"concluding either way."
        )
    else:
        df = pd.DataFrame(trend).sort_values("fiscal_year_end")
        fig = px.scatter(
            df, x="fiscal_year_end", y="confidence", color="category",
            size="confidence", hover_data=["evidence"],
            title=f"{ticker_input} — bottleneck-language signals by filing year",
        )
        fig.update_layout(yaxis_range=[0, 1.05])
        st.plotly_chart(fig, width="stretch")

        st.markdown("### Each filing, and what happened next")
        st.caption(
            "For every 10-K: what it said, then over the following 12 months, how the stock did, "
            "which companies it put money into or signed with (and how *their* stocks did), and "
            "what it disclosed doing in-house. The link between a deal and the bottleneck is "
            "inferred from timing and wording; companies rarely say \"we invested in X to fix Y\"."
        )
        filing_dates = sorted(df["fiscal_year_end"].unique(), reverse=True)
        if st.button("Load “what happened next” for every year",
                     help="About 10–60 seconds per year on first load; cached afterwards."):
            for fd in filing_dates:
                st.session_state[f"aftermath_{ticker_input}_{fd}"] = True

        for fd in filing_dates:
            year_rows = df[df["fiscal_year_end"] == fd].sort_values("confidence", ascending=False)
            st.markdown(f"#### 10-K filed {fd}")
            st.caption(" · ".join(f"{r['category']} ({r['confidence']:.0%})" for _, r in year_rows.iterrows()))
            with st.expander("What the filing said"):
                for _, row in year_rows.iterrows():
                    st.markdown(f"**{row['category']}** ({row['confidence']:.0%}): “{row['evidence']}”")
            key = f"aftermath_{ticker_input}_{fd}"
            if not st.session_state.get(key):
                if st.button("📈 What happened next?", key=f"btn_{key}"):
                    st.session_state[key] = True
                    st.rerun()
                continue
            with st.spinner(f"Reading the 12 months after {fd}…"):
                am = _fetch_aftermath(ticker_input, fd)
            if not am:
                st.error("Couldn't load what happened next for this filing.")
                continue
            _render_aftermath(am)
            st.divider()

    if result.get("capex_trend"):
        st.markdown("**CapEx trend (same company, from SEC XBRL):**")
        capex_df = pd.DataFrame(result["capex_trend"])
        capex_df["CapEx ($B)"] = capex_df["capex_usd"] / 1_000_000_000
        fig2 = px.bar(capex_df, x="fiscal_year_end", y="CapEx ($B)")
        st.plotly_chart(fig2, width="stretch")
elif run_clicked and not ticker_input:
    st.warning("Enter a ticker first.")
