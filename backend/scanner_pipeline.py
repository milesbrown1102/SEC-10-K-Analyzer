# backend/scanner_pipeline.py
"""
Orchestrates the full 3-tier Bottleneck Monopoly Scanner and persists
everything to backend.db so results survive a restart and don't require
re-running the pipeline just to look at them again.
"""

import json
from typing import Dict, List, Optional

from . import (
    capex_pipeline, bottleneck_detector, supplier_matcher, market_screener,
    deal_monitor, scoring, db, sec_utils, point_in_time,
)

DEFAULT_WATCHLIST = ["MSFT", "META", "GOOGL", "AMZN", "AAPL"]


def run_full_scan(watchlist: Optional[List[str]] = None, include_news_leads: bool = True) -> int:
    """
    Runs Tier 1 (CapEx) -> Tier 2 (bottleneck keywords) -> Tier 3 (supplier
    matching, now with an open-industry-discovery fallback + a revenue-based
    market-control ranking) -> market screener -> deal monitor (SEC 8-Ks,
    plus optional best-effort news leads) -> transparent buy scores, in that
    order, against the given watchlist (defaults to the playbook's own
    mega-cap set). Returns the run_id; raises on failure after marking the
    run 'failed' in the db so the caller/UI can see why.
    """
    watchlist = [t.strip().upper() for t in (watchlist or DEFAULT_WATCHLIST) if t.strip()]
    run_id = db.create_scan_run(watchlist)

    try:
        session = sec_utils.make_sec_session()

        capex_results = capex_pipeline.run_capex_tier(watchlist, session, run_id)

        signals = bottleneck_detector.run_bottleneck_tier(watchlist, session, run_id)
        signals = supplier_matcher.run_supplier_tier(signals, run_id, session=session)

        supplier_matcher.run_spinoff_monitor(session, run_id)

        # Score the whole supplier universe, not only names a mega-cap
        # filing pointed to: in the backtest, gating on that match was the
        # weakest part of the pipeline, while the supplier's own filings
        # caught what the mega-caps never mentioned (memory, 2025-26).
        supplier_tickers = sorted({
            match["supplier_ticker"]
            for sig in signals
            for match in sig.get("suppliers", [])
        } | set(supplier_universe()))
        if supplier_tickers:
            market_screener.screen_many(supplier_tickers)

            # Deal monitor runs against the mega-cap watchlist (e.g. did
            # Meta itself disclose the SanDisk deal) AND the discovered
            # suppliers (did SanDisk disclose it too) — a deal usually
            # shows up in both companies' filings.
            deal_pool = sorted(set(watchlist) | set(supplier_tickers))
            deal_monitor.run_deal_monitor(
                deal_pool, session, run_id, include_news=include_news_leads
            )

            _compute_and_store_buy_scores(signals, capex_results, watchlist, run_id)

        db.finish_scan_run(run_id, "completed")

    except Exception as e:
        db.finish_scan_run(run_id, "failed", error=f"{type(e).__name__}: {e}")
        raise

    return run_id


def supplier_universe() -> List[str]:
    """Hand-picked taxonomy suppliers plus anything added from the Industry Radar."""
    from . import industry_radar  # local import keeps module load order simple
    taxonomy = {t for entry in supplier_matcher.SUPPLIER_TAXONOMY for t in entry["suppliers"]}
    return sorted(taxonomy | {i["ticker"] for i in industry_radar.get_custom_universe()})


def _compute_and_store_buy_scores(signals: List[Dict], capex_results: Dict,
                                   watchlist: List[str], run_id: int) -> None:
    """
    One buy score per UNIQUE supplier ticker, persisted as a cache entry
    keyed by run_id so get_scan_results can read it back without
    recomputing. Kept in the kv_cache table rather than a new schema
    table since this is derived/summary data, not a primary record.

    A supplier can be matched from more than one signal (e.g. flagged for
    both MSFT's and META's filings) — rather than emit one duplicate-ish
    score row per signal, this aggregates across every signal a ticker
    was matched from and scores it on its single BEST-supported context:
    the highest-confidence signal, and "thesis intact" true if any
    contributing mega-cap cleared the CapEx threshold. The mega-cap
    tickers and industry labels behind the score are kept as a list so
    the UI can still show everything that contributed.
    """
    by_ticker: Dict[str, Dict] = {}
    for sig in signals:
        mega_cap = sig["mega_cap_ticker"]
        thesis_intact = bool(capex_results.get(mega_cap, {}).get("flagged_high_growth"))

        for supplier in sig.get("suppliers", []):
            ticker = supplier["supplier_ticker"]
            entry = by_ticker.setdefault(ticker, {
                "best_confidence": 0.0, "thesis_intact": False,
                "mega_caps": set(), "industries": set(), "market_control_rank": None,
            })
            entry["best_confidence"] = max(entry["best_confidence"], sig["confidence"])
            entry["thesis_intact"] = entry["thesis_intact"] or thesis_intact
            entry["mega_caps"].add(mega_cap)
            if supplier.get("industry_label"):
                entry["industries"].add(supplier["industry_label"])
            if supplier.get("market_control_rank") and entry["market_control_rank"] is None:
                entry["market_control_rank"] = supplier["market_control_rank"]

    # Universe names no mega-cap filing pointed to are still scored — on
    # their own filings, valuation and price — with 0 for the mega-cap factors.
    for entry in supplier_matcher.SUPPLIER_TAXONOMY:
        for ticker in entry["suppliers"]:
            if ticker not in by_ticker:
                by_ticker[ticker] = {
                    "best_confidence": 0.0, "thesis_intact": False, "mega_caps": set(),
                    "industries": {entry["category_label"]}, "market_control_rank": None,
                    "unmatched": True,
                }
            elif by_ticker[ticker].get("unmatched"):
                by_ticker[ticker]["industries"].add(entry["category_label"])
    from . import industry_radar
    for item in industry_radar.get_custom_universe():
        by_ticker.setdefault(item["ticker"], {
            "best_confidence": 0.0, "thesis_intact": False, "mega_caps": set(),
            "industries": {"Added from radar" + (f": {item['note']}" if item.get("note") else "")},
            "market_control_rank": None, "unmatched": True,
        })

    deal_events = db.get_deal_events(tickers=list(by_ticker.keys())) if by_ticker else []
    deal_tickers_confirmed = {e["ticker"] for e in deal_events if e["source"] == "sec_8k"}

    # Same point-in-time code the backtest validates, with as_of = today.
    session = sec_utils.make_sec_session()
    today = point_in_time.today()

    scores = []
    for ticker, ctx in by_ticker.items():
        market_data = db.cache_get("market_screen", ticker, ttl_seconds=None)
        confirmed_deal = ticker in deal_tickers_confirmed
        try:
            valuation = point_in_time.valuation(ticker, today, session)
        except Exception:
            valuation = None
        try:
            tightness = bottleneck_detector.supplier_tightness(ticker, today, session)
        except Exception:
            tightness = None

        score = scoring.compute_buy_score(
            ticker=ticker,
            thesis_intact=ctx["thesis_intact"],
            signal_confidence=ctx["best_confidence"],
            market_data=market_data,
            confirmed_deal=confirmed_deal,
            market_control_rank=ctx["market_control_rank"],
            valuation=valuation,
            own_tightness=tightness,
        )
        score["caution_flags"] = scoring.compute_caution_flags(
            signal_confidence=ctx["best_confidence"],
            market_data=market_data,
            confirmed_deal=confirmed_deal,
            valuation=valuation,
        )
        score["valuation"] = valuation
        score["own_tightness"] = tightness
        # Recorded for the live track record (Score Validation page).
        score["scan_date"] = today
        score["price_at_scan"] = point_in_time.price_on(ticker, today)
        score["matched"] = not ctx.get("unmatched", False)
        score["mega_cap_ticker"] = ", ".join(sorted(ctx["mega_caps"])) or "—"
        score["industry_label"] = ", ".join(sorted(ctx["industries"])) or None
        scores.append(score)

    db.cache_set(f"buy_scores_{run_id}", "all", scores)


def get_scan_results(run_id: int) -> Dict:
    """Assembles everything the UI needs to render one completed (or in-progress) run."""
    run = db.get_scan_run(run_id)
    if not run:
        return {}

    watchlist = json.loads(run["watchlist"])
    signals = db.get_signals_for_run(run_id)

    capex = db.get_all_capex_history(watchlist)

    supplier_tickers = sorted({
        match["supplier_ticker"]
        for sig in signals
        for match in sig.get("suppliers", [])
    } | {s["ticker"] for s in db.cache_get(f"buy_scores_{run_id}", "all", ttl_seconds=None) or []})
    market_data = {
        t: db.cache_get("market_screen", t, ttl_seconds=None) for t in supplier_tickers
    }

    spinoffs = db.get_recent_spinoff_filings()

    deal_pool = sorted(set(watchlist) | set(supplier_tickers))
    deals = db.get_deal_events(tickers=deal_pool) if deal_pool else []

    buy_scores = db.cache_get(f"buy_scores_{run_id}", "all", ttl_seconds=None) or []

    return {
        "run": run,
        "watchlist": watchlist,
        "capex": capex,
        "signals": signals,
        "market_data": market_data,
        "spinoffs": spinoffs,
        "deals": deals,
        "buy_scores": buy_scores,
        "score_evidence": _score_evidence(),
    }


def _score_evidence() -> Optional[Dict]:
    from . import backtest  # local import: backtest imports this module
    try:
        return backtest.factor_evidence()
    except Exception:
        return None


def get_track_record(limit_runs: int = 200) -> Dict:
    """
    Every scored pick from past scans that recorded a price, with its return
    since the scan and SPY's over the same period. This is the evidence
    with no backtest hindsight in it — it only accumulates going forward.
    """
    today = point_in_time.today()
    picks = []
    for run in db.list_scan_runs(limit_runs):
        if run.get("status") != "completed":
            continue
        for s in db.cache_get(f"buy_scores_{run['id']}", "all", ttl_seconds=None) or []:
            if not s.get("price_at_scan") or not s.get("scan_date"):
                continue  # scans before track recording existed
            now = point_in_time.price_on(s["ticker"], today)
            spy_then = point_in_time.price_on("SPY", s["scan_date"])
            spy_now = point_in_time.price_on("SPY", today)
            picks.append({
                "run_id": run["id"], "scan_date": s["scan_date"], "ticker": s["ticker"],
                "score": s["score"], "price_at_scan": s["price_at_scan"], "price_now": now,
                "return_pct": round((now / s["price_at_scan"] - 1) * 100, 2) if now else None,
                "spy_return_pct": round((spy_now / spy_then - 1) * 100, 2)
                if spy_now and spy_then else None,
            })

    # Several scans on one day would count the same pick repeatedly; keep
    # the latest scan per (day, ticker).
    dedup = {}
    for p in sorted(picks, key=lambda p: p["run_id"]):
        dedup[(p["scan_date"], p["ticker"])] = p
    picks = sorted(dedup.values(), key=lambda p: (p["scan_date"], -p["score"]), reverse=True)

    with_returns = [p for p in picks if p["return_pct"] is not None]
    summary = None
    if with_returns:
        scores = sorted(p["score"] for p in with_returns)
        split = scores[len(scores) // 2]
        high = [p["return_pct"] for p in with_returns if p["score"] >= split]
        low = [p["return_pct"] for p in with_returns if p["score"] < split]
        spy = [p["spy_return_pct"] for p in with_returns if p["spy_return_pct"] is not None]
        summary = {
            "n": len(with_returns), "split": split,
            "high_avg": round(sum(high) / len(high), 2) if high else 0.0,
            "low_avg": round(sum(low) / len(low), 2) if low else 0.0,
            "spy_avg": round(sum(spy) / len(spy), 2) if spy else 0.0,
        }
    return {"picks": picks, "summary": summary}
