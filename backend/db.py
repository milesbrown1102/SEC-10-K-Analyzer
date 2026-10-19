# backend/db.py
"""
Shared SQLite cache + Bottleneck Scanner storage.

Two things live here, both on purpose in one small file rather than a
heavier ORM: a generic namespaced key/value cache with a TTL (used for
"don't re-scrape SEC/yfinance every time" — filings, XBRL facts, market
data snapshots), and a handful of purpose-built tables for the Scanner
pipeline's own results (scan runs, detected bottleneck signals, matched
suppliers, CapEx history) so a completed scan survives a restart and can
be browsed without re-running the pipeline.

This is intentionally plain sqlite3 + JSON blobs, not SQLAlchemy — the
data model is simple enough that an ORM would be more ceremony than help,
and it keeps this dependency-free (stdlib only).
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "sec_analyzer_cache.db"


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they don't exist yet. Safe to call repeatedly."""
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS kv_cache (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                cached_at REAL NOT NULL,
                PRIMARY KEY (namespace, key)
            )"""
        )

        conn.execute(
            """CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at REAL NOT NULL,
                finished_at REAL,
                status TEXT NOT NULL,
                watchlist TEXT NOT NULL,
                error TEXT
            )"""
        )

        conn.execute(
            """CREATE TABLE IF NOT EXISTS bottleneck_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                mega_cap_ticker TEXT NOT NULL,
                category TEXT NOT NULL,
                evidence TEXT NOT NULL,
                confidence REAL NOT NULL,
                detected_at REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES scan_runs (id)
            )"""
        )

        conn.execute(
            """CREATE TABLE IF NOT EXISTS supplier_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                supplier_ticker TEXT NOT NULL,
                match_reason TEXT NOT NULL,
                match_method TEXT NOT NULL,
                FOREIGN KEY (signal_id) REFERENCES bottleneck_signals (id)
            )"""
        )

        conn.execute(
            """CREATE TABLE IF NOT EXISTS capex_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                fiscal_year_end TEXT NOT NULL,
                capex_usd REAL NOT NULL,
                yoy_growth_pct REAL,
                run_id INTEGER,
                UNIQUE (ticker, fiscal_year_end)
            )"""
        )

        conn.execute(
            """CREATE TABLE IF NOT EXISTS spinoff_filings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                cik TEXT,
                filed_at TEXT NOT NULL,
                form_type TEXT NOT NULL,
                source_url TEXT,
                run_id INTEGER,
                UNIQUE (company_name, filed_at, form_type)
            )"""
        )

        # Multi-year bottleneck-signal trend per ticker (Pass 3: "check
        # filings current and past to trends"). Upserted per (ticker,
        # fiscal_year_end, category) so re-running a lookup just refreshes
        # the same rows instead of accumulating duplicates.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS historical_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                fiscal_year_end TEXT NOT NULL,
                category TEXT NOT NULL,
                evidence TEXT NOT NULL,
                confidence REAL NOT NULL,
                computed_at REAL NOT NULL,
                UNIQUE (ticker, fiscal_year_end, category)
            )"""
        )

        # Deal/partnership events — SEC 8-K hits (source='sec_8k', confirmed,
        # legally-required disclosure) and best-effort news leads
        # (source='news_search', unverified — see deal_monitor.py). Filings
        # are the trustworthy half of this table; news rows exist only to
        # surface something worth checking by hand, never to be treated as
        # confirmed on their own.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS deal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                source TEXT NOT NULL,
                headline TEXT NOT NULL,
                evidence TEXT,
                event_date TEXT,
                source_url TEXT,
                run_id INTEGER,
                UNIQUE (ticker, source, headline)
            )"""
        )


# =============================================================================
# Generic namespaced KV cache with TTL
# =============================================================================

def cache_get(namespace: str, key: str, ttl_seconds: Optional[float]) -> Optional[Any]:
    """
    Returns the cached value for (namespace, key), or None if there's no
    entry or it's older than ttl_seconds. Pass ttl_seconds=None to accept
    any age (e.g. for data that basically never changes, like a closed
    fiscal year's XBRL figures).
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT value, cached_at FROM kv_cache WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()

    if not row:
        return None
    if ttl_seconds is not None and (time.time() - row["cached_at"]) > ttl_seconds:
        return None

    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return None


def cache_set(namespace: str, key: str, value: Any) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO kv_cache (namespace, key, value, cached_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(namespace, key) DO UPDATE SET
                 value = excluded.value, cached_at = excluded.cached_at""",
            (namespace, key, json.dumps(value), time.time()),
        )


def cache_clear(namespace: Optional[str] = None) -> None:
    with _connect() as conn:
        if namespace:
            conn.execute("DELETE FROM kv_cache WHERE namespace = ?", (namespace,))
        else:
            conn.execute("DELETE FROM kv_cache")


# =============================================================================
# Scan runs
# =============================================================================

def create_scan_run(watchlist: List[str]) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (started_at, status, watchlist) VALUES (?, ?, ?)",
            (time.time(), "running", json.dumps(watchlist)),
        )
        return cur.lastrowid


def finish_scan_run(run_id: int, status: str, error: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE scan_runs SET finished_at = ?, status = ?, error = ? WHERE id = ?",
            (time.time(), status, error, run_id),
        )


def get_scan_run(run_id: int) -> Optional[Dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM scan_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def get_latest_scan_run() -> Optional[Dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def list_scan_runs(limit: int = 20) -> List[Dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# =============================================================================
# Bottleneck signals + supplier matches
# =============================================================================

def add_signal(run_id: int, mega_cap_ticker: str, category: str, evidence: str,
                confidence: float) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO bottleneck_signals
               (run_id, mega_cap_ticker, category, evidence, confidence, detected_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, mega_cap_ticker, category, evidence, confidence, time.time()),
        )
        return cur.lastrowid


def add_supplier_match(signal_id: int, supplier_ticker: str, match_reason: str,
                        match_method: str) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO supplier_matches
               (signal_id, supplier_ticker, match_reason, match_method)
               VALUES (?, ?, ?, ?)""",
            (signal_id, supplier_ticker, match_reason, match_method),
        )


def get_signals_for_run(run_id: int) -> List[Dict]:
    with _connect() as conn:
        signal_rows = conn.execute(
            "SELECT * FROM bottleneck_signals WHERE run_id = ? ORDER BY confidence DESC",
            (run_id,),
        ).fetchall()

        signals = []
        for row in signal_rows:
            signal = dict(row)
            match_rows = conn.execute(
                "SELECT supplier_ticker, match_reason, match_method "
                "FROM supplier_matches WHERE signal_id = ?",
                (row["id"],),
            ).fetchall()
            signal["suppliers"] = [dict(m) for m in match_rows]
            signals.append(signal)

    return signals


# =============================================================================
# CapEx history
# =============================================================================

def upsert_capex(ticker: str, fiscal_year_end: str, capex_usd: float,
                  yoy_growth_pct: Optional[float], run_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO capex_history
               (ticker, fiscal_year_end, capex_usd, yoy_growth_pct, run_id)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(ticker, fiscal_year_end) DO UPDATE SET
                 capex_usd = excluded.capex_usd,
                 yoy_growth_pct = excluded.yoy_growth_pct,
                 run_id = excluded.run_id""",
            (ticker, fiscal_year_end, capex_usd, yoy_growth_pct, run_id),
        )


def get_capex_history(ticker: str, limit: int = 8) -> List[Dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM capex_history WHERE ticker = ?
               ORDER BY fiscal_year_end DESC LIMIT ?""",
            (ticker, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_capex_history(tickers: List[str]) -> Dict[str, List[Dict]]:
    return {t: get_capex_history(t) for t in tickers}


# =============================================================================
# Spin-off catalyst monitor
# =============================================================================

def add_spinoff_filing(company_name: str, cik: Optional[str], filed_at: str,
                        form_type: str, source_url: Optional[str], run_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO spinoff_filings
               (company_name, cik, filed_at, form_type, source_url, run_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (company_name, cik, filed_at, form_type, source_url, run_id),
        )


def get_recent_spinoff_filings(limit: int = 25) -> List[Dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM spinoff_filings ORDER BY filed_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# =============================================================================
# Historical (multi-year) bottleneck-signal trend
# =============================================================================

def upsert_historical_signal(ticker: str, fiscal_year_end: str, category: str,
                              evidence: str, confidence: float) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO historical_signals
               (ticker, fiscal_year_end, category, evidence, confidence, computed_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(ticker, fiscal_year_end, category) DO UPDATE SET
                 evidence = excluded.evidence,
                 confidence = excluded.confidence,
                 computed_at = excluded.computed_at""",
            (ticker, fiscal_year_end, category, evidence, confidence, time.time()),
        )


def get_historical_signals(ticker: str) -> List[Dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM historical_signals WHERE ticker = ?
               ORDER BY fiscal_year_end ASC""",
            (ticker,),
        ).fetchall()
    return [dict(r) for r in rows]


# =============================================================================
# Deal / partnership monitor
# =============================================================================

def add_deal_event(ticker: str, source: str, headline: str, evidence: Optional[str],
                    event_date: Optional[str], source_url: Optional[str],
                    run_id: Optional[int]) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO deal_events
               (ticker, source, headline, evidence, event_date, source_url, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ticker, source, headline, evidence, event_date, source_url, run_id),
        )


def delete_deal_events_for_url(ticker: str, source_url: Optional[str]) -> None:
    if not source_url:
        return
    with _connect() as conn:
        conn.execute(
            "DELETE FROM deal_events WHERE ticker = ? AND source_url = ? AND source LIKE 'sec_8k%'",
            (ticker, source_url),
        )


def get_deal_events(tickers: Optional[List[str]] = None, limit: int = 50) -> List[Dict]:
    with _connect() as conn:
        if tickers:
            placeholders = ",".join("?" for _ in tickers)
            rows = conn.execute(
                f"""SELECT * FROM deal_events WHERE ticker IN ({placeholders})
                    ORDER BY source ASC, event_date DESC LIMIT ?""",
                (*tickers, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM deal_events ORDER BY event_date DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]
