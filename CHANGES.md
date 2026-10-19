# SEC 10-K Analyzer — Changes

## Pass 5: is the buy score worth anything? (backtest + v2 weights)

**Short answer: v1 wasn't; v2 points the right way but isn't proven.**

- **Point-in-time data layer (`backend/point_in_time.py`)** — every
  accessor takes an `as_of` date and only uses SEC facts *filed* by then
  (restatements can't leak back), filings filed by then, and prices up to
  then. Market cap lines filing share counts up with split-adjusted prices
  (NVIDIA mid-2020: $234B, not $6B); falls back to balance-sheet shares
  when a company (Alphabet) reports no cover-page count. The live score's
  new factors call the same functions with `as_of = today`.
- **Backtest (`backend/backtest.py`, `pages/4_Score_Validation.py`)** —
  rebuilds the scanner at 35 quarter ends (2017-2026) over the 17-name
  supplier universe and scores it with the live `compute_buy_score`.
  Reports per-factor rank IC with t-stats, true/false splits, and a top-5
  quarterly strategy vs the equal-weight universe and SPY.
- **v1 result:** score IC -0.065 (t -1.4); top-5 46%/yr vs universe 51%.
  Stocks matched via mega-cap filings did *worse* than unmatched ones,
  driven by 2025-26, when the memory names (MU, WDC, SNDK) the scanner
  never matched beat the universe by 29-82% per quarter.
- **v2 weights, fixed before re-testing** (see `scoring.py` docstring):
  new *supplier's own tightness* factor (25) reads the supplier's latest
  10-K/10-Q MD&A for constrained supply / rising prices / allocation; new
  *growth-adjusted valuation* (15), the only factor positive in both
  halves of the sample; volume spike and revenue-leader proxy dropped to
  info-only. M&A agreements no longer count as deals.
- **v2 result:** score IC +0.044 (t 1.0); top-5 67%/yr vs universe 51%,
  beating it in 21 of 35 quarters (~13% chance by luck). Better, not
  statistically proven. The tightness factor idea came from looking at
  the memory miss in this same data, so this isn't a clean test.
- **Live scanner now scores the whole supplier universe**, not only names
  a mega-cap filing pointed to — the matched-only version still trails the
  universe (43% vs 53%/yr), and that gate is what hid MU and SNDK.
- **Track record** — each scan now records scores and prices; the Score
  Validation page follows them forward. The only evidence with no
  backtest hindsight; it needs months to mean anything.
- The Buy Scores tab shows the score's backtest IC up front and each
  factor's IC next to it.

Known gap: ASML files a 20-F (foreign issuer, IFRS), so it has no
valuation or tightness data and scores near zero for lack of data.

Tests: `test_backtest.py` (6 offline tests) is new; 31 tests pass.

## Pass 4: first run against real data — detection fixes + 13F smart money

First time the whole pipeline ran against live SEC / yfinance data (Passes
2-3 were built offline). A scan of MSFT, META, GOOGL, AMZN, AAPL found
**1** bottleneck signal and scored **0-2** suppliers. After this pass the
same scan finds **16** signals and scores **11** suppliers, with evidence
quoted from the filings ("Our ability to scale our technical infrastructure
is increasingly constrained by the availability of power, water, and land"
— Alphabet). Root causes, in pipeline order:

- **Section extraction (`universal_section_extractor.py`)** — when "Item 7"
  appeared more than once (table of contents, cross-references, Microsoft's
  per-page "PART II / Item 7" headers) the last occurrence overwrote the
  real section, and Alphabet's headings put the title on the next line,
  which the regex required on the same line. MD&A came out as 259-1,961
  chars instead of 50-100K. Rewritten: line-start headings only, a section
  ends at the next *later* item, the longest candidate span wins. This also
  fixes the main app's Risk Factors / MD&A analysis, which shares the
  extractor (NVIDIA MD&A: 221 -> 34K chars). New optional `max_chars`
  (default 50,000, unchanged for the main app).
- **Filing text (`sec_utils.html_to_text`)** — inline-XBRL filings split
  words across `<span>`s, and `get_text("\n")` broke them ("i nvestment"),
  silently defeating regexes. Line breaks are now only added at block
  elements. Cached text is re-fetched (`filing_text_v2`).
- **10-K selection** — the "latest 10-K" could be a Part-III-only 10-K/A
  (Tesla files one every April). Originals are now preferred; historical
  lookups skip amendments.
- **Bottleneck detector (rewritten)** — the old patterns were exact phrases
  from the playbook's hypothetical examples and matched almost nothing in
  real filings. A sentence now counts when it has a *constraint cue*
  (shortage, constrained, limited number of suppliers, lead times, unable to
  secure, ...) AND a *subject* from a supply category (GPUs/accelerators,
  power/grid, servers/networking, memory/storage, cooling/water, fab
  capacity, data center sites). Boilerplate (internal controls, catastrophe
  lists, climate-change risk) is filtered. Scans Business + Risk Factors +
  MD&A, falling back to the full document when extraction comes back thin
  (banks put MD&A in an exhibit). Category keys changed — see
  `BOTTLENECK_CATEGORIES`.
- **Supplier routing** — each detector category maps straight to its
  taxonomy entries (`CATEGORY_TO_TAXONOMY`, method `"category"`); keyword /
  LLM / open discovery remain the fallback. New taxonomy entry "Grid &
  electrical equipment" (GEV, ETN, PWR). Fixed every supplier being
  labelled with the first matched industry.
- **CapEx & financials** — the first XBRL tag with any data won, so
  Amazon's CapEx stopped at FY2016 ($6.7B instead of $131.8B) after it
  changed tags. Now the tag with the newest data wins, in both
  `capex_pipeline.py` and `sec_financial_data.py`; gross margin / net
  income are only combined with revenue from the same fiscal year
  (Amazon's last `GrossProfit` fact is from 2009 -> margin showed 0.8%).
- **Revenue growth** — compared the latest quarter with the *previous*
  quarter, which mostly measured seasonality (VST -28.8% / CEG -32.5%
  instead of -5.5% / +23%). Now year-over-year, by date.
- **Deal monitor** — 7 of 10 "confirmed deals" were debt (credit facility
  amendments, notes offerings, underwriting agreements), and the evidence
  quoted the 8-K cover page. Item 1.01 bodies are now classified
  commercial / financing; only commercial ones (e.g. NVIDIA's SB Energy
  AI-campus partnership) earn buy-score points. Financing ones are shown
  separately. Re-checked filings replace their old rows.
- **Pages** point at `127.0.0.1:8000` rather than `localhost`, which can
  resolve to IPv6 and reach a different local server on port 8000.

**New: Smart Money (13F)** — `backend/institutional_holdings.py`,
`pages/3_Smart_Money_13F.py`, `/institutions/*` endpoints. Compares each
tracked manager's last two 13F filings (new / added / trimmed / exited,
portfolio weight, estimated $ flow), aggregates a cross-manager consensus,
and cross-references the Scanner's buy-scored suppliers. 21 managers with
CIKs verified against SEC (18 on by default). Handles rows split across
sub-managers, options kept out of consensus, filers still reporting in
thousands, stock splits (detected from price, then verified against the
stock's recorded split history), and non-US CINS codes. CUSIP -> ticker
via OpenFIGI, cached permanently (1,460 of 1,468 positions mapped). Read
the page's caveats: 13F data is up to 45 days stale and long-only.

Tests: `test_institutional_holdings.py` is new (8 offline tests); the
detector test in `test_scanner_integration.py` asserts the new category
keys. All 25 tests pass.

## Pass 3: industry discovery, historical trends, deal monitor, buy scores

Direct answer to: "I want it to identify industries, check filings current
and past for trends, monitor new deals as soon as they happen, and give me
a buy/sell score." Five additions on top of Pass 2's pipeline, all wired
into the existing `Run Full Scan` flow (plus one standalone lookup tool):

- **Open industry discovery (`backend/industry_classifier.py`)** — Tier 3's
  supplier match now has a third fallback step. Before: only the 6
  hand-seeded taxonomy categories (or an LLM picking among those same 6)
  could ever be recognized. Now: when neither of those find anything, the
  local LLM is asked to freely name the actual industry/problem plus real
  public companies in it — every ticker still validated against SEC's
  official ticker list before being shown (same validation `peer_analysis.py`
  already uses), so it can never surface a fabricated ticker. It CAN still
  surface a real company that isn't actually a meaningful competitor, or
  miss a better one — this is LLM judgment, not a verified database, and
  the UI marks it `llm_discovery` so you know it's less certain than a
  keyword match. Read the module's docstring for the full honesty notes.
- **Market-control proxy (`rank_by_market_control` in the same file)** —
  there is no free database of real market share anywhere (same point the
  Pass 2 docstring already made). This ranks a group of matched suppliers
  by their own reported SEC revenue as an approximate "who's biggest in
  this group" stand-in — labeled a proxy everywhere it shows up, not real
  share data. Shown per-supplier in the Candidate Suppliers tab and folded
  into the buy score below.
- **Historical trend lookup (`backend/historical_pipeline.py` +
  `pages/2_Historical_Trend_Lookup.py`)** — direct answer to "check filings
  current and past for trends." Type any ticker (not just the watchlist)
  and it runs the same bottleneck-language detection against several years
  of that company's own past 10-Ks, so you can see when the language
  started showing up. Important honesty note (also in the page and module
  docstrings): this is NOT a backtest proving the system would have caught
  anything in real time — it's today's detection patterns run against old
  filings, which describe the business the way it looked at the time, not
  with hindsight. NVIDIA's own 2013 10-K reads as a gaming-GPU company; the
  "AI compute bottleneck" framing wasn't legible in filing language until
  roughly 2015-2016. This tool shows you exactly what language did or
  didn't appear, year by year — a real, honest look, not a guarantee.
- **Deal monitor (`backend/deal_monitor.py`)** — checks the watchlist and
  every matched supplier for two kinds of evidence, deliberately NOT
  treated as equally trustworthy: (1) SEC 8-Ks, Item 1.01 ("Entry into a
  Material Definitive Agreement") — a real, legally-required disclosure
  (companies must file within 4 business days of a material agreement),
  same trust level as the CapEx/XBRL data elsewhere in the app; (2) a
  best-effort news/headline scan reusing this project's existing
  `enhanced_web_search.py` DuckDuckGo scraper — same already-documented
  fragility as the main app's Web Intelligence tab, always shown as an
  unverified lead, never as confirmed. This is what would have surfaced
  something like the Meta/SanDisk deal.
- **Transparent buy score (`backend/scoring.py`)** — a 0-100 point total
  for each matched supplier, fully itemized (never a black-box number):
  points for the mega-cap customer's CapEx growth clearing 25%, the
  bottleneck-signal confidence, the market screener (relative volume,
  200-day MA, revenue growth), a confirmed 8-K deal, and the market-control
  proxy — click any row in the new Buy Scores tab to see exactly where
  every point came from. There's deliberately no mirrored "sell score" —
  see `caution_flags` instead: plain-language reasons for doubt (negative
  revenue growth, price below trend, a stale/low-confidence thesis), which
  is a more honest shape than fabricating a second score would be.

New/changed files this pass: `backend/industry_classifier.py`,
`backend/historical_pipeline.py`, `backend/deal_monitor.py`,
`backend/scoring.py`, and `pages/2_Historical_Trend_Lookup.py` are new;
`backend/db.py`, `backend/sec_utils.py`, `backend/supplier_matcher.py`,
`backend/scanner_pipeline.py`, `backend/main.py`, `backend/bottleneck_detector.py`,
and `pages/1_Bottleneck_Scanner.py` are updated (`bottleneck_detector.py`
also got the evidence-snippet word-boundary fix sent separately after the
first scan run — this zip includes that fix too, so if you already applied
it by hand, overwriting with this version is safe and just reconfirms it).
No new dependencies — everything reuses what `requirements-scanner.txt`
already installed. `test_pass3_integration.py` is a new offline test file
(11 tests, all passing); `test_scanner_integration.py` was extended with 2
more assertions covering the new pipeline steps rather than replaced.

Sandbox note (unchanged): still no live network access here, so this was
verified with `py_compile`, `pyflakes`, a FastAPI `TestClient` smoke test,
and fully offline/mocked integration tests — nothing has touched real SEC,
yfinance, DuckDuckGo, or Ollama data yet. Please run it for real before
trusting it, especially the deal monitor and open industry discovery,
which are the newest and least-tested pieces.

## Pass 2: Bottleneck Monopoly Scanner + persistent cache

New feature implementing the Institutional Supply-Chain Investing Playbook
(`investment_playbook.md`) as an automated 3-tier pipeline, plus a shared
SQLite cache so results (and the existing single-company analysis) survive
a restart instead of only living in Streamlit's in-memory cache. Full
details and setup steps are in `SCANNER_SETUP.md`; the short version:

- **`backend/`** — a new FastAPI service (`uvicorn backend.main:app`) that
  runs the pipeline and is the intended foundation for the React frontend
  discussed for the next pass. It never touches `SEC10K.OllamaInterface`
  (which can call `sys.exit(1)` if Ollama isn't running — fine for a CLI
  script, would kill a backend process) — `backend/llm_client.py` is a
  separate, crash-proof Ollama client that just returns `None` on failure.
- **Tier 1 (`capex_pipeline.py`)** — mega-cap CapEx trends straight from
  SEC XBRL, flags >25% YoY growth.
- **Tier 2 (`bottleneck_detector.py`)** — scans each mega-cap's own MD&A /
  Risk Factors text for supply-constraint / backlog / power-infrastructure
  language generalized from the playbook's example phrases.
- **Tier 3 (`supplier_matcher.py`)** — matches a signal to pure-play
  suppliers via a small hand-seeded taxonomy (starting from the playbook's
  own NVDA/VST/SNDK examples), with an LLM fallback that can only pick
  among the existing taxonomy — never invents a ticker. **This is not a
  market-share database**; treat it as a starting point, the same way the
  playbook's own validation matrix was hand-researched. Also includes a
  best-effort SEC Form 10-12B (spin-off) filing monitor.
- **Market screener (`market_screener.py`)** — relative volume, 200-day
  moving average, quarterly revenue growth via yfinance, degrading
  gracefully per-ticker on failure since yfinance is unofficial/fragile.
- **`pages/1_Bottleneck_Scanner.py`** — new Streamlit page (native
  multipage app support, so `app_beautiful_final.py` itself is untouched
  structurally) that runs/polls scans and renders all of the above.
- **Persistent cache wired into the existing app** — `cached_get_cik`,
  `cached_get_filings`, `cached_fetch_content`, and `cached_xbrl_data` in
  `app_beautiful_final.py` now check/write the same SQLite store the
  Scanner uses (best-effort — falls back to the old in-memory-only
  behavior if `backend/` isn't importable for any reason). A filing fetched
  in the main analyzer is reused by the Scanner and vice versa, since they
  share the same cache keys for a company's CIK and filing text.

Bugs caught and fixed while building/testing this (see
`test_scanner_integration.py` for the regression tests):
- `backend/main.py` initialized the database only in a FastAPI
  `on_event("startup")` handler, which doesn't fire under every ASGI
  runner/test harness — moved to run unconditionally (and cheaply,
  `CREATE TABLE IF NOT EXISTS`) at import time instead.
- `supplier_matcher.match_suppliers_for_signal` originally returned only
  the single top-scoring taxonomy category, so a tie between two equally
  relevant categories (e.g. a passage mentioning both GPUs and flash
  storage) silently dropped one of them. It now returns every category
  that matched, capped at the top 3.

Sandbox note (original, still applies): this environment has no outbound network access to SEC or
general internet (blocked by org policy), so nothing here could be run
against live SEC data or a real Ollama instance. Syntax was verified with
`py_compile` and `pyflakes` (both clean), and every pure function was
exercised with offline unit tests against fixtures that mirror the real
SEC XBRL / ticker-file schemas (`test_offline.py`, all passing). Please
still run it for real on your machine before trusting it — per your usual
workflow of testing locally before committing.

## New files

**`sec_financial_data.py`** — pulls Revenue, Net Income, and Gross Margin
straight from SEC's structured XBRL data
(`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`) instead of
regex-scraping the filing's prose. This is the same underlying data XBRL
viewers use, so it's inherently more reliable than pattern-matching
sentences like "revenue of $X billion" — no more picking up the wrong
number or misjudging million vs. billion. Falls back to `{}` (never
raises) if a company has no usable XBRL data, so the app can fall back to
something else.

**`peer_analysis.py`** — replaces the 3-ticker hardcoded `peer_mappings`
dict (only NVDA/AAPL/MSFT ever got real competitor data; everyone else got
nothing) with dynamic discovery that works for any company:
1. Curated fast-path kept for those same 3 tickers (a hand-written reason
   reads better than a generated one for names this common).
2. Otherwise, asks the local Ollama model to read the filing's own
   Business/Risk Factors text and name real competitors — 10-Ks often
   state this directly ("we compete with X, Y and Z").
3. Falls back to a regex scan for the same kind of sentence if the LLM
   step is unavailable or returns nothing usable.
Every candidate name is checked against SEC's official
`company_tickers.json` before being shown, so the UI never displays a
ticker that doesn't exist.

## Bugs fixed

- **Fabricated "Impact" data presented as real analysis.** The Dashboard's
  Risk Assessment Matrix plotted `np.random.uniform(0.3, 0.9)` as the
  "Impact" axis — literally random numbers shown next to real model
  confidence scores in a tool meant to inform investment decisions. Removed
  entirely; the Dashboard now shows a horizontal bar chart of insights
  ranked by actual model confidence, nothing invented.

- **PDF report generation crashed whenever peer data was present.**
  `pdf_report_generator._create_peer_section` read
  `peer_comparison.competitive_position` and `.insights`, but
  `st.session_state.peer_data` is a plain `{'peers': [...], 'reasons': {...}}`
  dict — nothing in the app ever provided those attributes. Since the dict
  is always truthy (even with an empty peers list, it still has two keys),
  `if peer_comparison:` was true on essentially every "Generate PDF Report"
  click, so this would `AttributeError` in production. Fixed to read the
  actual dict shape, and to skip the section cleanly when there's nothing
  to show.

- **Employee count extraction was a no-op.**
  `financial_data['employees'] = matches[0].replace(',', ',')` replaces a
  comma with a comma — it does nothing. It happened to look fine whenever
  the filing text itself used comma formatting ("164,000 employees"), but
  produced an unformatted, non-numeric string ("164000") whenever it didn't,
  and would break any downstream code that tried to treat it as a number.
  Fixed to actually parse and reformat: `f"{count:,}"`.

- **"Investigate further" buttons in the AI Insights tab did nothing.**
  Clicking one appended `{'question': q, 'answer': 'Processing...'}` to the
  conversation history and never called anything to resolve it — a dead
  end that looked like it was working. Now it actually calls the answer
  engine and reports back.

- **Web Intelligence tab ran ~16-20 external searches on every rerun**,
  not just when you opened that tab — Streamlit reruns the whole script on
  *any* button click anywhere in the app, so clicking "Ask" in the Q&A tab
  or expanding a risk card also silently fired off a full batch of
  DuckDuckGo searches in the background. That's slow, invites getting
  rate-limited, and wastes the SEC's/DuckDuckGo's goodwill. It's now gated
  behind an explicit "Scan for Recent Risk Events & News" button, results
  are cached, and the scan stops checking more keywords for a risk category
  as soon as it finds a hit (it used to keep querying every keyword
  regardless).

- **Bare `except:` blocks swallowed errors silently** in the Web
  Intelligence tab. Replaced with `except Exception:` at minimum, so a bug
  surfaces instead of vanishing.

- **No caching on any SEC/network calls.** CIK lookup, filing list, filing
  content, XBRL data, and peer discovery are now wrapped in
  `st.cache_data(ttl=3600)`. A "🔄 Clear Cache" button was added to the
  sidebar for when you want to force a refresh.

- **Crash risk on edge cases**: no company resolved from natural-language
  input, no CIK found, or no 10-K filings returned would previously hit an
  `IndexError` (`filings[0]` on an empty list) or otherwise fail deep
  inside the pipeline with a raw traceback. These are now checked
  explicitly and raise a clear `ValueError` with a message `st.error`
  displays.

- **Progress bar could get stuck on screen** if an exception happened
  mid-analysis, because `progress.empty()` / `status_text.empty()` were
  only reached on the success path. Moved into a `finally` block.

## Structural changes

- The giant inline financial-regex block and the hardcoded peer-mapping
  dict were pulled out of `app_beautiful_final.py` into named functions
  (`build_financial_snapshot`, `_regex_extract_*`) and the new
  `peer_analysis` module, so the Streamlit file is closer to being just UI
  orchestration.
- `enhanced_web_search.py`'s `IntelligentAnswerEngine` and
  `EnhancedWebSearch.search_competitor_info` had their own separate
  hardcoded competitor dict (`NVDA`/`AAPL`/`TSLA`) — a second, inconsistent
  copy of the same idea in `app.py`. Removed; they now accept the peers
  already discovered by `peer_analysis.get_peer_companies` as a parameter.
- Financial metrics in the UI now show *where the number came from* via
  `st.metric(..., help=...)` — "SEC XBRL" vs. "Estimated from filing text —
  verify independently" — instead of presenting a text-mined guess with
  the same visual confidence as an audited figure.

## Not touched (flagged for later, out of scope for this pass)

- `SEC10K.py`, `universal_section_extractor.py`,
  `intelligent_inference_engine.py`, and `validation_module.py` are
  unchanged. `intelligent_inference_engine.py`'s `web_augmentation()` is a
  documented placeholder that returns search *queries* only, never actual
  results — it's not currently called in a way that surfaces this, so it
  was left alone.
- `universal_section_extractor.extract_by_headers` does a nested loop over
  header patterns for every header pattern, which is fine for the current
  pattern count but worth flattening if you add many more.
- The web search integration (`_search_duckduckgo`) scrapes DuckDuckGo's
  HTML with regex rather than an API — it works today but is inherently
  brittle if DuckDuckGo changes their markup. Worth a real search API key
  (the Google CSE / SerpAPI stubs are already sitting there unused) if this
  becomes a reliability problem in practice.
