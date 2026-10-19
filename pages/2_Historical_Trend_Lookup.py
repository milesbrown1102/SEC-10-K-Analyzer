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
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("**Evidence by year:**")
        for _, row in df.sort_values("fiscal_year_end", ascending=False).iterrows():
            with st.expander(f"{row['fiscal_year_end']} — {row['category']} ({row['confidence']:.0%})"):
                st.write(f"“{row['evidence']}”")

    if result.get("capex_trend"):
        st.markdown("**CapEx trend (same company, from SEC XBRL):**")
        capex_df = pd.DataFrame(result["capex_trend"])
        capex_df["CapEx ($B)"] = capex_df["capex_usd"] / 1_000_000_000
        fig2 = px.bar(capex_df, x="fiscal_year_end", y="CapEx ($B)")
        st.plotly_chart(fig2, use_container_width=True)
elif run_clicked and not ticker_input:
    st.warning("Enter a ticker first.")
