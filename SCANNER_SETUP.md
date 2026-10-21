# Bottleneck Monopoly Scanner — setup

Current file layout, all under your existing project root (Pass 3 added
`industry_classifier.py`, `historical_pipeline.py`, `deal_monitor.py`,
`scoring.py`, and a second Streamlit page — see CHANGES.md for exactly
what changed vs. Pass 2):

```
backend/
  __init__.py
  db.py                    shared SQLite cache + scanner storage
  sec_utils.py             SEC EDGAR fetch helpers (no Ollama dependency)
  llm_client.py            crash-proof Ollama client (never sys.exit()s)
  capex_pipeline.py        Tier 1 — mega-cap CapEx trajectories
  bottleneck_detector.py   Tier 2 — bottleneck keyword scanning
  supplier_matcher.py      Tier 3 — taxonomy + open discovery + spin-off monitor
  industry_classifier.py   open industry/company discovery + market-control proxy
  historical_pipeline.py   multi-year bottleneck-signal trend for any ticker
  deal_monitor.py          SEC 8-K deal detection + best-effort news leads
  scoring.py               transparent buy score + caution flags
  institutional_holdings.py  13F "smart money" tracker (Pass 4)
  point_in_time.py         "what was known on date X" data layer (Pass 5)
  backtest.py              quarterly backtest of the buy score (Pass 5)
  industry_radar.py        SEC full-text-search industry radar (Pass 6)
  radar_backtest.py        does new tightness language precede returns? (Pass 7)
  insider_trading.py       Form 4 open-market insider purchases (Pass 7)
  aftermath.py             what happened in the 12 months after a 10-K (Pass 7)
  market_screener.py       yfinance technical screener
  scanner_pipeline.py      orchestrates everything above
  main.py                  FastAPI app
pages/
  1_Bottleneck_Scanner.py       main scanner page (auto-appears in the sidebar nav)
  2_Historical_Trend_Lookup.py  standalone multi-year lookup for any ticker
  3_Smart_Money_13F.py          what well-known investors bought/sold last quarter
  4_Score_Validation.py         backtest of the buy score + live track record
  5_Industry_Radar.py           tightness language across every SEC filer, by industry
requirements-scanner.txt   (unchanged this pass — no new dependencies)
```

Nothing in `app_beautiful_final.py`'s existing single-company flow was
restructured to use the backend — that stays exactly as it worked before,
plus the one additive change described in CHANGES.md (persistent SQLite
caching alongside the existing in-memory `st.cache_data`).

## Quick start

```bash
./start.sh        # starts backend + app if needed, opens http://localhost:8501
./start.sh stop   # stops both
```

The backend refreshes the scan, 13F, radar and insider data weekly on its
own while it's running.

## Install

```powershell
pip install -r requirements-scanner.txt
```

(Everything else — streamlit, pandas, plotly, bs4, requests — you already have.
No new packages this pass.)

## Run

Two processes, both from the project root, in two terminals:

```powershell
# Terminal 1 — backend
uvicorn backend.main:app --reload --reload-dir backend --port 8000

# Terminal 2 — frontend (same command as always)
streamlit run app_beautiful_final.py
```

Streamlit will show **"Bottleneck Scanner"** and **"Historical Trend
Lookup"** as pages in the left sidebar automatically (that's what the
`pages/` folder does — no extra wiring needed). Open Bottleneck Scanner,
confirm the sidebar says "Backend connected", set your watchlist (defaults
to MSFT, META, GOOGL, AMZN, AAPL), and click **Run Full Scan** — it now
also runs the deal monitor and computes buy scores, so it'll take a bit
longer than before. Open Historical Trend Lookup separately, any time, to
run a multi-year check on any single ticker.

Every network call is cached in `sec_analyzer_cache.db` (in your project
root), so repeat runs are much faster until the cache TTLs expire (24h for
filings/CapEx/historical data, 6h for 8-K checks, 15 min for market data).

`--reload-dir backend` matters: without it, saving any `.py` file in the
project (a Streamlit page, a test) restarts the backend, and a restart
waits for any running scan or 13F refresh to finish first — so the API
looks hung for minutes.

**Smart Money (13F)** is a third sidebar page. Click **Refresh 13F data**
once: the first refresh maps every holding's CUSIP to a ticker through
OpenFIGI's free, rate-limited API (a few minutes for the default 18
managers); after that it's cached and refreshes take seconds. Quant /
systematic funds (Renaissance, Bridgewater, ARK) are opt-in in the
sidebar because they hold thousands of positions.

## Things to sanity-check on your machine

Same situation as Pass 2 — no live network access in the sandbox this was
built in, so everything was verified with `py_compile`, `pyflakes`, a
FastAPI `TestClient` smoke test, and fully offline/mocked integration
tests (`test_scanner_integration.py`, `test_pass3_integration.py` — 18
tests total, all passing). Nothing here has touched real SEC, yfinance,
DuckDuckGo, or Ollama data yet. Specifically worth checking once you have
it running for real:

- **Open industry discovery** (`industry_classifier.discover_industry_and_players`)
  needs Ollama running to do anything — without it, Tier 3 just falls back
  to "no match", same as before this pass. With Ollama running, check that
  the JSON it returns actually parses; local models sometimes wrap JSON in
  markdown fences or extra prose despite being asked not to, and while the
  regex extraction here is meant to handle that, a specific model's output
  style might need a small prompt tweak.
- **The deal monitor's 8-K check** fetches each ticker's own recent 8-Ks
  and regex-scans for "Item 1.01" plus deal language — spot check a name
  you know recently signed a real agreement (SanDisk itself, or Meta) and
  see if it actually surfaces. If it's coming back empty when you'd expect
  a hit, the keyword list in `deal_monitor.DEAL_KEYWORDS` is the first
  place to look — it's deliberately broad but can't cover every phrasing.
- **The historical trend lookup** depends on `get_historical_10k_filings`
  reading enough years out of SEC's `submissions.json` "recent" window —
  for a long-lived company this should comfortably cover 6+ years, but if
  a lookup comes back thinner than expected, that's the function to check
  first (see its docstring in `sec_utils.py` for why it doesn't walk SEC's
  older paginated filing index).
- **The spin-off monitor** (`supplier_matcher.check_for_spinoff_filings`)
  parses SEC EDGAR's "current filings" Atom feed with a lenient regex
  rather than a strict XML parser, since I couldn't verify the live
  response shape. If it comes back empty when you'd expect results, that's
  the first place to look.
- **yfinance's quarterly revenue growth** — `market_screener.py` tries both
  `quarterly_income_stmt` and the older `quarterly_financials` attribute,
  since this has changed across yfinance versions before. If your installed
  version uses something else, that's an isolated, easy fix in
  `_quarterly_revenue_growth()`.
- **The supplier taxonomy is deliberately small** (6 categories, seeded
  from the playbook's own 3 examples plus a few adjacent ones). Extending
  it is just adding entries to `SUPPLIER_TAXONOMY` in
  `backend/supplier_matcher.py` — keywords + a ticker/reason dict, no other
  code changes needed. The open-discovery fallback (this pass) only kicks
  in when the taxonomy finds nothing, so a well-maintained taxonomy still
  gives you the most deterministic, trustworthy results.
