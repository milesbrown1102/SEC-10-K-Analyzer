# backend/main.py
"""
FastAPI backend for the Bottleneck Monopoly Scanner.

Run with (from the project root, same folder as app_beautiful_final.py):

    uvicorn backend.main:app --reload --port 8000

This is also the intended foundation for the eventual React frontend —
these endpoints are what React will call once that migration happens,
instead of talking to Streamlit. For now, the new
pages/1_Bottleneck_Scanner.py Streamlit page is the only consumer.

A scan can take a while (fetching + parsing several mega-caps' 10-Ks, plus
market data for every matched supplier), so /scanner/run kicks it off as a
background task and returns immediately; poll /scanner/status or
/scanner/results/{run_id} for progress and results.
"""

import os
import threading
import time
from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import (
    aftermath, backtest, bottleneck_detector, company_profile, db, historical_pipeline, industry_radar, insider_trading,
    opportunities,
    institutional_holdings, point_in_time, radar_backtest, scanner_pipeline, scoring, sec_utils,
)

app = FastAPI(title="SEC 10-K Analyzer — Bottleneck Scanner API", version="0.1.0")

# Permissive CORS since this is a local dev tool today; tighten this once
# it's actually deployed somewhere React will be served from a real origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialized at import time rather than only in an on_event("startup")
# handler: FastAPI's startup event only fires under a real ASGI lifespan
# (uvicorn does this correctly, but a bare TestClient() call without using
# it as a context manager won't), and init_db() is cheap and idempotent
# (CREATE TABLE IF NOT EXISTS), so there's no real cost to just doing it
# unconditionally on import instead of depending on lifespan timing.
db.init_db()

_scan_lock = threading.Lock()
_scan_in_progress = False


class ScanRequest(BaseModel):
    watchlist: Optional[List[str]] = None


def _run_scan_background(watchlist: Optional[List[str]]):
    global _scan_in_progress
    try:
        scanner_pipeline.run_full_scan(watchlist)
    except Exception:
        # Already recorded on the scan_runs row by run_full_scan; swallow
        # here so a background task exception doesn't just vanish into
        # uvicorn's logs without the in-progress flag being cleared.
        pass
    finally:
        with _scan_lock:
            _scan_in_progress = False


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scanner/run")
def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    global _scan_in_progress
    with _scan_lock:
        if _scan_in_progress:
            raise HTTPException(status_code=409, detail="A scan is already running.")
        _scan_in_progress = True

    background_tasks.add_task(_run_scan_background, req.watchlist)
    return {"status": "started"}


@app.get("/scanner/status")
def scan_status():
    return {"in_progress": _scan_in_progress, "latest_run": db.get_latest_scan_run()}


@app.get("/scanner/runs")
def list_runs(limit: int = 20):
    return db.list_scan_runs(limit)


@app.get("/scanner/results/{run_id}")
def scan_results(run_id: int):
    results = scanner_pipeline.get_scan_results(run_id)
    if not results:
        raise HTTPException(status_code=404, detail=f"No scan run with id {run_id}")
    return results


@app.get("/scanner/track-record")
def track_record():
    return scanner_pipeline.get_track_record()


@app.get("/scanner/latest")
def latest_results():
    run = db.get_latest_scan_run()
    if not run:
        raise HTTPException(status_code=404, detail="No scans have been run yet")
    return scanner_pipeline.get_scan_results(run["id"])


# =============================================================================
# Historical trend lookup — Pass 3: "check filings current and past to
# trends", for ANY ticker, not just the watchlist. Synchronous (unlike
# /scanner/run) since it's just one company's filings — typically a few to
# ~20 seconds depending on how many years of 10-Ks it fetches.
# =============================================================================

class HistoricalRequest(BaseModel):
    ticker: str
    max_years: int = 6


@app.post("/historical/run")
def run_historical(req: HistoricalRequest):
    session = sec_utils.make_sec_session()
    result = historical_pipeline.run_historical_trend(
        req.ticker, session, max_years=req.max_years
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/historical/{ticker}/aftermath")
def historical_aftermath(ticker: str, filing_date: str):
    """What happened in the 12 months after one of this company's 10-Ks."""
    result = aftermath.filing_aftermath(ticker, filing_date)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/historical/{ticker}")
def get_historical(ticker: str):
    trend = historical_pipeline.get_stored_historical_trend(ticker)
    if not trend:
        raise HTTPException(
            status_code=404,
            detail=f"No historical trend computed for '{ticker}' yet — POST /historical/run first",
        )
    return {"ticker": ticker.strip().upper(), "signal_trend": trend,
            "filings": historical_pipeline.get_stored_filings(ticker)}


# =============================================================================
# Institutional holdings (13F) — "what are well-known investors buying".
# Background task like /scanner/run: the first refresh maps every CUSIP to
# a ticker through OpenFIGI's rate-limited free API, which can take a few
# minutes; later refreshes hit the permanent cache and take seconds.
# =============================================================================

_inst_lock = threading.Lock()
_inst_in_progress = False
_inst_last_error: Optional[str] = None


class InstitutionsRequest(BaseModel):
    ciks: Optional[List[str]] = None


def _run_institutions_background(ciks: Optional[List[str]]):
    global _inst_in_progress, _inst_last_error
    try:
        institutional_holdings.run_institutional_report(ciks)
        _inst_last_error = None
    except Exception as e:
        _inst_last_error = f"{type(e).__name__}: {e}"
    finally:
        with _inst_lock:
            _inst_in_progress = False


@app.get("/institutions/managers")
def list_managers():
    return institutional_holdings.MANAGERS


@app.post("/institutions/refresh")
def refresh_institutions(req: InstitutionsRequest, background_tasks: BackgroundTasks):
    global _inst_in_progress
    with _inst_lock:
        if _inst_in_progress:
            raise HTTPException(status_code=409, detail="A 13F refresh is already running.")
        _inst_in_progress = True
    background_tasks.add_task(_run_institutions_background, req.ciks)
    return {"status": "started"}


@app.get("/institutions/status")
def institutions_status():
    report = institutional_holdings.get_latest_report()
    return {
        "in_progress": _inst_in_progress,
        "last_error": _inst_last_error,
        "generated_at": report["generated_at"] if report else None,
    }


@app.get("/institutions/latest")
def latest_institutions():
    report = institutional_holdings.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No 13F report yet — POST /institutions/refresh first")
    return report


@app.get("/institutions/scanner-overlap")
def institutions_scanner_overlap():
    """Which of the latest scan's buy-scored suppliers tracked managers hold or traded."""
    report = institutional_holdings.get_latest_report()
    run = db.get_latest_scan_run()
    if not report or not run:
        raise HTTPException(status_code=404, detail="Need both a 13F report and a scanner run")
    scores = scanner_pipeline.get_scan_results(run["id"]).get("buy_scores", [])
    tickers = [b["ticker"] for b in scores]
    return {
        "scan_run_id": run["id"],
        "buy_scores": {b["ticker"]: b["score"] for b in scores},
        "holders": institutional_holdings.holdings_for_tickers(report, tickers),
    }


# =============================================================================
# Backtest — does the buy score predict anything? Background task; the
# first run downloads ~8 years of filings and prices (several minutes),
# later runs reuse the cache.
# =============================================================================

_bt_lock = threading.Lock()
_bt_state = {"in_progress": False, "done": 0, "total": 0, "current": None, "error": None}


def _run_backtest_background():
    def progress(done, total, current):
        _bt_state.update(done=done, total=total, current=current)
    try:
        backtest.run_backtest(progress=progress)
        _bt_state["error"] = None
    except Exception as e:
        _bt_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        with _bt_lock:
            _bt_state["in_progress"] = False


@app.post("/backtest/run")
def start_backtest(background_tasks: BackgroundTasks):
    with _bt_lock:
        if _bt_state["in_progress"]:
            raise HTTPException(status_code=409, detail="A backtest is already running.")
        _bt_state.update(in_progress=True, done=0, total=0, current=None, error=None)
    background_tasks.add_task(_run_backtest_background)
    return {"status": "started"}


@app.get("/backtest/status")
def backtest_status():
    report = backtest.get_latest_report()
    return {**_bt_state, "generated_at": report["generated_at"] if report else None}


@app.get("/backtest/latest")
def latest_backtest():
    report = backtest.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No backtest yet — POST /backtest/run first")
    return report


# =============================================================================
# Industry Radar — tightness language across ALL SEC filers, by industry.
# =============================================================================

_radar_lock = threading.Lock()
_radar_state = {"in_progress": False, "error": None}


def _run_radar_background():
    try:
        industry_radar.run_radar()
        _radar_state["error"] = None
    except Exception as e:
        _radar_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        with _radar_lock:
            _radar_state["in_progress"] = False


@app.post("/radar/run")
def start_radar(background_tasks: BackgroundTasks):
    with _radar_lock:
        if _radar_state["in_progress"]:
            raise HTTPException(status_code=409, detail="The radar is already running.")
        _radar_state.update(in_progress=True, error=None)
    background_tasks.add_task(_run_radar_background)
    return {"status": "started"}


@app.get("/radar/status")
def radar_status():
    report = industry_radar.get_latest_report()
    return {**_radar_state, "generated_at": report["generated_at"] if report else None}


@app.get("/radar/latest")
def latest_radar():
    report = industry_radar.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No radar yet — POST /radar/run first")
    return report


@app.get("/radar/company/{ticker}")
def radar_company(ticker: str):
    """
    Drill-down for any ticker: the full tightness detector on its latest
    10-K/10-Q, valuation, growth, trend, a standalone buy score (no
    mega-cap context), and which tracked funds hold it.
    """
    ticker = ticker.strip().upper()
    session = sec_utils.make_sec_session()
    cik = sec_utils.get_cik_for_ticker(ticker, session)
    if not cik:
        raise HTTPException(status_code=404, detail=f"No SEC filer found for '{ticker}'")
    today = point_in_time.today()
    tightness = bottleneck_detector.supplier_tightness(ticker, today, session)
    valuation = point_in_time.valuation(ticker, today, session)
    tech = point_in_time.technicals(ticker, today)
    rev = point_in_time.quarterly_revenue_yoy(cik, today, session)
    market = {"relative_volume": tech["relative_volume"], "above_200sma": tech["above_200sma"],
              "quarterly_revenue_growth_pct": rev}
    score = scoring.compute_buy_score(
        ticker=ticker, thesis_intact=False, signal_confidence=0.0, market_data=market,
        confirmed_deal=False, valuation=valuation, own_tightness=tightness)
    # The mega-cap "low-confidence signal" flag doesn't apply to a standalone lookup.
    score["caution_flags"] = [f for f in scoring.compute_caution_flags(0.0, market, False, valuation)
                              if not f.startswith("Low-confidence bottleneck signal")]
    report = institutional_holdings.get_latest_report()
    holders = institutional_holdings.holdings_for_tickers(report, [ticker])[ticker] if report else []
    try:
        insider_trading.refresh_recent([ticker], session)
    except Exception:
        pass
    insider = insider_trading.insider_activity(cik, today)
    return {"ticker": ticker, "cik": cik, "tightness": tightness, "valuation": valuation,
            "insider": insider,
            "technicals": tech, "quarterly_revenue_growth_pct": rev, "score": score,
            "fund_holders": holders,
            "in_universe": ticker in scanner_pipeline.supplier_universe()}


class UniverseItem(BaseModel):
    ticker: str
    note: str = ""


@app.get("/universe")
def get_universe():
    return {"taxonomy": sorted({t for e in scanner_pipeline.supplier_matcher.SUPPLIER_TAXONOMY
                                for t in e["suppliers"]}),
            "custom": industry_radar.get_custom_universe()}


@app.post("/universe")
def add_universe(item: UniverseItem):
    session = sec_utils.make_sec_session()
    if not sec_utils.get_cik_for_ticker(item.ticker, session):
        raise HTTPException(status_code=404, detail=f"No SEC filer found for '{item.ticker}'")
    return {"custom": industry_radar.add_to_universe(item.ticker, item.note)}


@app.delete("/universe/{ticker}")
def remove_universe(ticker: str):
    return {"custom": industry_radar.remove_from_universe(ticker)}


# =============================================================================
# Insider buying (Form 4) — quarterly SEC data sets + recent filings.
# =============================================================================

_ins_lock = threading.Lock()
_ins_state = {"in_progress": False, "error": None, "done": 0, "total": 0}


def _run_insiders_background():
    def progress(done, total, q):
        _ins_state.update(done=done, total=total)
    try:
        insider_trading.load_data_sets(progress=progress)
        insider_trading.refresh_recent(scanner_pipeline.supplier_universe())
        _ins_state["error"] = None
    except Exception as e:
        _ins_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        with _ins_lock:
            _ins_state["in_progress"] = False


@app.post("/insiders/refresh")
def refresh_insiders(background_tasks: BackgroundTasks):
    with _ins_lock:
        if _ins_state["in_progress"]:
            raise HTTPException(status_code=409, detail="An insider refresh is already running.")
        _ins_state.update(in_progress=True, error=None, done=0, total=0)
    background_tasks.add_task(_run_insiders_background)
    return {"status": "started"}


@app.get("/insiders/status")
def insiders_status():
    loaded = insider_trading.loaded_quarters()
    return {**_ins_state, "quarters_loaded": len(loaded),
            "covers_through": insider_trading.bulk_covers_through(),
            "purchases": sum(q["purchases"] for q in loaded.values())}


@app.get("/insiders/clusters")
def insider_clusters(days: int = 90, min_buyers: int = 2, min_total_value: float = 100_000):
    return {"days": days, "covers_through": insider_trading.bulk_covers_through(),
            "clusters": insider_trading.cluster_buys(days, min_buyers, min_total_value=min_total_value)}


@app.get("/insiders/{ticker}")
def insider_ticker(ticker: str, days: int = 365):
    session = sec_utils.make_sec_session()
    cik = sec_utils.get_cik_for_ticker(ticker, session)
    if not cik:
        raise HTTPException(status_code=404, detail=f"No SEC filer found for '{ticker}'")
    try:
        insider_trading.refresh_recent([ticker], session)
    except Exception:
        pass
    return insider_trading.insider_activity(cik, point_in_time.today(), days)


# =============================================================================
# Radar backtest — does newly appearing tightness language precede
# outperformance? Background task: first run searches ~45 quarters of
# filings and downloads monthly prices for ~1-2k tickers.
# =============================================================================

_rbt_lock = threading.Lock()
_rbt_state = {"in_progress": False, "error": None, "done": 0, "total": 0, "stage": None}


def _run_radar_backtest_background():
    def progress(done, total, current, stage):
        _rbt_state.update(done=done, total=total, stage=stage)
    try:
        radar_backtest.run_radar_backtest(progress=progress)
        _rbt_state["error"] = None
    except Exception as e:
        _rbt_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        with _rbt_lock:
            _rbt_state["in_progress"] = False


@app.post("/radar-backtest/run")
def start_radar_backtest(background_tasks: BackgroundTasks):
    with _rbt_lock:
        if _rbt_state["in_progress"]:
            raise HTTPException(status_code=409, detail="A radar backtest is already running.")
        _rbt_state.update(in_progress=True, error=None, done=0, total=0, stage=None)
    background_tasks.add_task(_run_radar_backtest_background)
    return {"status": "started"}


@app.get("/radar-backtest/status")
def radar_backtest_status():
    report = radar_backtest.get_latest_report()
    return {**_rbt_state, "generated_at": report["generated_at"] if report else None}


@app.get("/radar-backtest/latest")
def latest_radar_backtest():
    report = radar_backtest.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No radar backtest yet")
    return report


# =============================================================================
# Opportunities — industries ranked on giants' money, scarcity, funds,
# insiders. Background task (first run follows six giants' deals: ~3 min).
# =============================================================================

_opp_lock = threading.Lock()
_opp_state = {"in_progress": False, "error": None, "done": 0, "total": 0, "stage": None}


def _run_opportunities_background():
    def progress(done, total, current, stage):
        _opp_state.update(done=done, total=total, stage=stage)
    try:
        opportunities.run_opportunities(progress=progress)
        _opp_state["error"] = None
    except Exception as e:
        _opp_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        with _opp_lock:
            _opp_state["in_progress"] = False


@app.post("/opportunities/run")
def start_opportunities(background_tasks: BackgroundTasks):
    with _opp_lock:
        if _opp_state["in_progress"]:
            raise HTTPException(status_code=409, detail="Already running.")
        _opp_state.update(in_progress=True, error=None, done=0, total=0, stage=None)
    background_tasks.add_task(_run_opportunities_background)
    return {"status": "started"}


@app.get("/opportunities/status")
def opportunities_status():
    report = opportunities.get_latest_report()
    return {**_opp_state, "generated_at": report["generated_at"] if report else None}


@app.get("/opportunities/latest")
def latest_opportunities():
    report = opportunities.get_latest_report()
    if not report:
        raise HTTPException(status_code=404, detail="No opportunities report yet")
    return report


@app.get("/company/{ticker}/profile")
def company_profile_endpoint(ticker: str):
    """Everything about one company: what it does, funds and when they bought, insiders,
    connections, buy score, and a case for / against built from the evidence."""
    result = company_profile.build_profile(ticker)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/prices/{ticker}")
def prices(ticker: str, years: float = 3.0):
    """Daily adjusted closes (weekly when the range is over 2 years), plus SPY over the same range."""
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=int(365 * years))).isoformat()

    def series(t):
        hist = point_in_time.price_history(t.upper())
        rows = [(d, v["adj_close"]) for d, v in sorted(hist.items()) if d >= start]
        if years > 2:
            rows = rows[::5]
        return [{"date": d, "close": round(c, 4)} for d, c in rows]

    data = series(ticker)
    if not data:
        raise HTTPException(status_code=404, detail=f"No price history for '{ticker}'")
    return {"ticker": ticker.upper(), "prices": data, "spy": series("SPY")}


# =============================================================================
# Weekly auto-refresh. Runs inside the backend (a WSL cron job would only
# fire while WSL happens to be open): every 30 minutes, anything older than
# REFRESH_AFTER_DAYS is refreshed, one job at a time, in the background.
# The live track record depends on scans happening regularly.
# Disable with SEC_ANALYZER_SCHEDULER=off.
# =============================================================================


REFRESH_AFTER_DAYS = 7
SCHEDULER_INTERVAL_SECONDS = 30 * 60
_schedule_state = {"enabled": os.environ.get("SEC_ANALYZER_SCHEDULER", "on") != "off",
                   "last_check": None, "last_started": {}}


def _age_days(ts: Optional[float]) -> float:
    return float("inf") if not ts else (time.time() - ts) / 86400


def _latest_completed_scan_ts() -> Optional[float]:
    for run in db.list_scan_runs(20):
        if run["status"] == "completed":
            return run["finished_at"]
    return None


def _scheduled_jobs():
    """(name, last_refreshed_ts, start_fn) — start_fn returns False if busy."""
    def start_scan():
        global _scan_in_progress
        with _scan_lock:
            if _scan_in_progress:
                return False
            _scan_in_progress = True
        threading.Thread(target=_run_scan_background, args=(None,), daemon=True).start()
        return True

    def start_13f():
        global _inst_in_progress
        with _inst_lock:
            if _inst_in_progress:
                return False
            _inst_in_progress = True
        threading.Thread(target=_run_institutions_background, args=(None,), daemon=True).start()
        return True

    def start_radar():
        with _radar_lock:
            if _radar_state["in_progress"]:
                return False
            _radar_state.update(in_progress=True, error=None)
        threading.Thread(target=_run_radar_background, daemon=True).start()
        return True

    def start_insiders():
        with _ins_lock:
            if _ins_state["in_progress"]:
                return False
            _ins_state.update(in_progress=True, error=None)
        threading.Thread(target=_run_insiders_background, daemon=True).start()
        return True

    def start_opportunities_job():
        with _opp_lock:
            if _opp_state["in_progress"]:
                return False
            _opp_state.update(in_progress=True, error=None)
        threading.Thread(target=_run_opportunities_background, daemon=True).start()
        return True

    inst = institutional_holdings.get_latest_report()
    radar = industry_radar.get_latest_report()
    opp = opportunities.get_latest_report()
    loaded = insider_trading.loaded_quarters()
    return [
        ("scan", _latest_completed_scan_ts(), start_scan),
        ("13f", inst["generated_at"] if inst else None, start_13f),
        ("radar", radar["generated_at"] if radar else None, start_radar),
        ("insiders", max((q["loaded_at"] for q in loaded.values()), default=None), start_insiders),
        # Last, so it runs on fresh radar / 13F / insider inputs.
        ("opportunities", opp["generated_at"] if opp else None, start_opportunities_job),
    ]


def _scheduler_loop():
    while True:
        time.sleep(SCHEDULER_INTERVAL_SECONDS)
        _schedule_state["last_check"] = time.time()
        try:
            for name, ts, start in _scheduled_jobs():
                if _age_days(ts) >= REFRESH_AFTER_DAYS and start():
                    _schedule_state["last_started"][name] = time.time()
                    break  # one job per check, so SEC isn't hit by three at once
        except Exception:
            pass  # never let the scheduler thread die


if _schedule_state["enabled"]:
    threading.Thread(target=_scheduler_loop, daemon=True, name="auto-refresh").start()


@app.get("/schedule")
def schedule_status():
    return {
        **_schedule_state,
        "refresh_after_days": REFRESH_AFTER_DAYS,
        "jobs": [{"name": n, "last_refreshed": ts, "age_days": round(_age_days(ts), 2)
                  if ts else None, "due": _age_days(ts) >= REFRESH_AFTER_DAYS}
                 for n, ts, _ in _scheduled_jobs()],
    }
