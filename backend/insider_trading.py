# backend/insider_trading.py
"""
Insider buying from SEC Form 4: officers and directors buying their own
company's stock on the open market, with their own money.

Why purchases only: insiders sell for many reasons (taxes, diversification,
pre-scheduled plans), but they buy for essentially one — they think the
stock is cheap. Open-market purchases (transaction code "P") are the part
of insider data with the most consistent research support; clusters of
several insiders buying at once more so. Sales, option exercises, grants
and gifts are ignored.

Data:
- History: SEC's quarterly "Insider Transactions Data Sets" — every Form
  3/4/5 transaction for every company, ~9 MB per quarter. Only open-market
  purchases are kept, in the `insider_purchases` table.
- The weeks since the latest quarterly file: individual Form 4 XMLs read
  directly for the tickers being scored (recent_purchases_live).

Counted as an insider: anyone reporting as Director or Officer. Pure 10%
owners (usually funds) are kept in the table but excluded from counts.
Purchases under a pre-arranged Rule 10b5-1 plan are flagged; they carry
less information than a discretionary purchase.

Not yet scored: the buy score shows insider buying as info only until the
backtest (which records it as a factor) supports a weight.
"""

import csv
import io
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import requests

from . import db, sec_utils

DATA_SETS_PAGE = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
DEFAULT_LOOKBACK_DAYS = 90
FIRST_QUARTER = "2017q1"  # backtest starts 2017-12-31; 90-day lookback needs Q4 2017


def _init_table() -> None:
    with db._connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS insider_purchases (
            accession TEXT NOT NULL,
            trans_sk TEXT NOT NULL,
            issuer_cik TEXT NOT NULL,
            ticker TEXT,
            issuer_name TEXT,
            filing_date TEXT NOT NULL,
            trans_date TEXT,
            owner_cik TEXT,
            owner_name TEXT,
            relationship TEXT,
            title TEXT,
            shares REAL,
            price REAL,
            value REAL,
            plan_10b5_1 INTEGER,
            PRIMARY KEY (accession, trans_sk)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_issuer ON insider_purchases (issuer_cik, filing_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_date ON insider_purchases (filing_date)")
        conn.execute("""CREATE TABLE IF NOT EXISTS insider_quarters_loaded (
            quarter TEXT PRIMARY KEY, loaded_at REAL, purchases INTEGER)""")


_init_table()


def _sec_date(s: str) -> Optional[str]:
    """'31-JUL-2026' -> '2026-07-31'."""
    try:
        return datetime.strptime(s.strip(), "%d-%b-%Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def _is_insider(relationship: str) -> bool:
    rel = relationship or ""
    return "Director" in rel or "Officer" in rel


# =============================================================================
# Bulk quarterly data sets
# =============================================================================

def available_quarters(session: requests.Session) -> Dict[str, str]:
    """{'2026q3': url, ...} from SEC's index page (paths changed over the years)."""
    cached = db.cache_get("form345_index", "all", ttl_seconds=24 * 3600)
    if cached:
        return cached
    resp = sec_utils._polite_get(session, DATA_SETS_PAGE)
    resp.raise_for_status()
    links = re.findall(r'href="([^"]*?(\d{4}q[1-4])_form345\.zip)"', resp.text)
    out = {q: ("https://www.sec.gov" + href if href.startswith("/") else href) for href, q in links}
    db.cache_set("form345_index", "all", out)
    return out


def parse_data_set(zip_bytes: bytes) -> List[Dict]:
    """
    Pure function. One quarterly zip -> open-market purchases (code P,
    acquired), joined with filing date, issuer, and reporting owner.
    """
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))

    def rows(name):
        with z.open(name) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, "utf-8", errors="replace"), delimiter="\t")

    purchases = [r for r in rows("NONDERIV_TRANS.tsv")
                 if r.get("TRANS_CODE") == "P" and r.get("TRANS_ACQUIRED_DISP_CD") == "A"]
    if not purchases:
        return []
    wanted = {r["ACCESSION_NUMBER"] for r in purchases}
    subs = {r["ACCESSION_NUMBER"]: r for r in rows("SUBMISSION.tsv") if r["ACCESSION_NUMBER"] in wanted}
    owners: Dict[str, Dict] = {}
    for r in rows("REPORTINGOWNER.tsv"):
        # A filing can list several owners (e.g. a fund and its manager);
        # keep the first — the relationship is what matters here.
        if r["ACCESSION_NUMBER"] in wanted and r["ACCESSION_NUMBER"] not in owners:
            owners[r["ACCESSION_NUMBER"]] = r

    out = []
    for t in purchases:
        sub = subs.get(t["ACCESSION_NUMBER"])
        if not sub or not sub.get("DOCUMENT_TYPE", "").startswith("4"):
            continue
        own = owners.get(t["ACCESSION_NUMBER"], {})
        try:
            shares = float(t.get("TRANS_SHARES") or 0)
            price = float(t.get("TRANS_PRICEPERSHARE") or 0)
        except ValueError:
            continue
        out.append({
            "accession": t["ACCESSION_NUMBER"],
            "trans_sk": t.get("NONDERIV_TRANS_SK") or str(len(out)),
            "issuer_cik": sub["ISSUERCIK"].zfill(10),
            "ticker": (sub.get("ISSUERTRADINGSYMBOL") or "").strip().upper() or None,
            "issuer_name": sub.get("ISSUERNAME"),
            "filing_date": _sec_date(sub["FILING_DATE"]),
            "trans_date": _sec_date(t.get("TRANS_DATE", "")),
            "owner_cik": own.get("RPTOWNERCIK"),
            "owner_name": own.get("RPTOWNERNAME"),
            "relationship": own.get("RPTOWNER_RELATIONSHIP"),
            "title": own.get("RPTOWNER_TITLE"),
            "shares": shares,
            "price": price,
            "value": shares * price,
            "plan_10b5_1": 1 if str(sub.get("AFF10B5ONE", "")).lower() in ("1", "true") else 0,
        })
    return [p for p in out if p["filing_date"]]


def _store(purchases: List[Dict]) -> None:
    cols = ["accession", "trans_sk", "issuer_cik", "ticker", "issuer_name", "filing_date",
            "trans_date", "owner_cik", "owner_name", "relationship", "title", "shares",
            "price", "value", "plan_10b5_1"]
    with db._connect() as conn:
        conn.executemany(
            f"INSERT OR REPLACE INTO insider_purchases ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})",
            [tuple(p[c] for c in cols) for p in purchases])


def loaded_quarters() -> Dict[str, Dict]:
    with db._connect() as conn:
        return {r["quarter"]: dict(r) for r in conn.execute("SELECT * FROM insider_quarters_loaded")}


def load_data_sets(session: Optional[requests.Session] = None, first: str = FIRST_QUARTER,
                   progress=None) -> Dict:
    """
    Downloads every quarterly data set from `first` on that isn't loaded
    yet. Completed quarters never change; the newest is reloaded if it was
    loaded within the quarter's 45-day filing tail (SEC can re-post it).
    """
    session = session or sec_utils.make_sec_session()
    quarters = {q: u for q, u in available_quarters(session).items() if q >= first}
    done = loaded_quarters()
    newest = max(quarters) if quarters else None
    todo = [q for q in sorted(quarters)
            if q not in done or (q == newest and time.time() - done[q]["loaded_at"] > 7 * 86400)]
    added = 0
    for i, q in enumerate(todo):
        resp = session.get(quarters[q], timeout=180)
        resp.raise_for_status()
        purchases = parse_data_set(resp.content)
        _store(purchases)
        with db._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO insider_quarters_loaded VALUES (?, ?, ?)",
                         (q, time.time(), len(purchases)))
        added += len(purchases)
        if progress:
            progress(i + 1, len(todo), q)
        time.sleep(0.5)
    return {"quarters_loaded": len(todo), "purchases_added": added, "newest": newest}


def bulk_covers_through() -> Optional[str]:
    """Last calendar day covered by the newest loaded quarterly data set."""
    qs = loaded_quarters()
    if not qs:
        return None
    q = max(qs)
    year, n = int(q[:4]), int(q[-1])
    return (date(year + (n == 4), (n * 3) % 12 + 1, 1) - timedelta(days=1)).isoformat()


# =============================================================================
# Recent Form 4s (since the newest data set) — read individually
# =============================================================================

def parse_form4_xml(xml_text: str) -> List[Dict]:
    """Pure function. Open-market purchases in one Form 4 XML document."""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)

    def text(node, path):
        el = node.find(path)
        return el.text.strip() if el is not None and el.text else ""

    rel = root.find("reportingOwner/reportingOwnerRelationship")
    roles = []
    if rel is not None:
        for tag, label in (("isDirector", "Director"), ("isOfficer", "Officer"),
                           ("isTenPercentOwner", "TenPercentOwner"), ("isOther", "Other")):
            if text(rel, tag).lower() in ("1", "true"):
                roles.append(label)
    plan = text(root, "aff10b5One").lower() in ("1", "true")
    out = []
    for i, tx in enumerate(root.findall("nonDerivativeTable/nonDerivativeTransaction")):
        if text(tx, "transactionCoding/transactionCode") != "P":
            continue
        if text(tx, "transactionAmounts/transactionAcquiredDisposedCode/value") != "A":
            continue
        try:
            shares = float(text(tx, "transactionAmounts/transactionShares/value") or 0)
            price = float(text(tx, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        out.append({
            "trans_sk": f"x{i}",
            "issuer_cik": text(root, "issuer/issuerCik").zfill(10),
            "ticker": text(root, "issuer/issuerTradingSymbol").upper() or None,
            "issuer_name": text(root, "issuer/issuerName"),
            "trans_date": text(tx, "transactionDate/value")[:10] or None,
            "owner_cik": text(root, "reportingOwner/reportingOwnerId/rptOwnerCik"),
            "owner_name": text(root, "reportingOwner/reportingOwnerId/rptOwnerName"),
            "relationship": ",".join(roles),
            "title": text(root, "reportingOwner/reportingOwnerRelationship/officerTitle"),
            "shares": shares, "price": price, "value": shares * price,
            "plan_10b5_1": 1 if plan else 0,
        })
    return out


def refresh_recent(tickers: List[str], session: Optional[requests.Session] = None) -> int:
    """
    Reads Form 4s filed after the newest quarterly data set for `tickers`
    (each document fetched once — the table key makes reloads idempotent).
    """
    from . import point_in_time as pit
    session = session or sec_utils.make_sec_session()
    since = bulk_covers_through() or (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()
    stored = 0
    for ticker in tickers:
        cik = sec_utils.get_cik_for_ticker(ticker, session)
        if not cik:
            continue
        for f in pit.all_filings(cik, session):
            if f["filing_date"] <= since:
                break  # newest first
            if f["form"] != "4":
                continue
            key = f"{cik}_{f['accession_number']}"
            if db.cache_get("form4_seen", key, ttl_seconds=None):
                continue
            # primaryDocument points at the XSL-rendered view; the raw XML
            # is the same file name without the "xslF345X0n/" prefix.
            doc = f["primary_document"].split("/")[-1]
            url = (f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
                   f"{f['accession_number']}/{doc}")
            try:
                resp = sec_utils._polite_get(session, url)
                resp.raise_for_status()
                rows = parse_form4_xml(resp.text)
            except (requests.RequestException, ET.ParseError):
                continue
            acc = f["accession_number"]
            accession = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"
            for r in rows:
                r["accession"] = accession
                r["filing_date"] = f["filing_date"]
            _store(rows)
            stored += len(rows)
            db.cache_set("form4_seen", key, True)
    return stored


# =============================================================================
# Queries
# =============================================================================

def purchases(issuer_cik: Optional[str] = None, start: str = "0000", end: str = "9999",
              insiders_only: bool = True) -> List[Dict]:
    sql = "SELECT * FROM insider_purchases WHERE filing_date > ? AND filing_date <= ?"
    args: List = [start, end]
    if issuer_cik:
        sql += " AND issuer_cik = ?"
        args.append(issuer_cik.zfill(10))
    with db._connect() as conn:
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY filing_date DESC", args)]
    return [r for r in rows if not insiders_only or _is_insider(r["relationship"])]


def summarize(rows: List[Dict]) -> Dict:
    """Pure function. Distinct buyers, $ total, discretionary (non-10b5-1) buyers."""
    buyers = {r["owner_cik"] or r["owner_name"] for r in rows}
    discretionary = {r["owner_cik"] or r["owner_name"] for r in rows if not r["plan_10b5_1"]}
    return {
        "buyers": len(buyers),
        "discretionary_buyers": len(discretionary),
        "transactions": len(rows),
        "total_value": round(sum(r["value"] or 0 for r in rows), 2),
        "largest": max(rows, key=lambda r: r["value"] or 0) if rows else None,
    }


def insider_activity(cik: str, as_of: str, days: int = DEFAULT_LOOKBACK_DAYS) -> Dict:
    """Insider (officer/director) open-market buying filed in the `days` before as_of."""
    start = (datetime.fromisoformat(as_of) - timedelta(days=days)).date().isoformat()
    rows = purchases(cik, start, as_of)
    out = summarize(rows)
    out["rows"] = rows[:20]
    out["window_days"] = days
    return out


def cluster_buys(days: int = DEFAULT_LOOKBACK_DAYS, min_buyers: int = 2,
                 as_of: Optional[str] = None, min_total_value: float = 100_000) -> List[Dict]:
    """
    Market-wide: companies where at least `min_buyers` different officers or
    directors bought on the open market in the window, largest first.
    Skips issuers with no exchange ticker (private funds, unlisted
    companies) and totals under `min_total_value` — foreign issuers whose
    insiders began filing Form 4s in 2026 report many small plan-style
    purchases (TSMC: 31 insiders, ~$48K each).
    """
    as_of = as_of or date.today().isoformat()
    start = (datetime.fromisoformat(as_of) - timedelta(days=days)).date().isoformat()
    by_issuer: Dict[str, List[Dict]] = {}
    for r in purchases(None, start, as_of):
        if not r["ticker"] or r["ticker"] in ("NONE", "N/A", "NA"):
            continue
        by_issuer.setdefault(r["issuer_cik"], []).append(r)
    out = []
    for cik, rows in by_issuer.items():
        s = summarize(rows)
        if s["buyers"] < min_buyers or s["total_value"] < min_total_value:
            continue
        out.append({
            "issuer_cik": cik, "ticker": rows[0]["ticker"], "issuer_name": rows[0]["issuer_name"],
            **{k: v for k, v in s.items() if k != "largest"},
            "avg_per_buyer": round(s["total_value"] / s["buyers"], 2),
            "latest_filing": max(r["filing_date"] for r in rows),
            "titles": sorted({(r["title"] or r["relationship"] or "").strip() for r in rows} - {""})[:6],
        })
    out.sort(key=lambda r: (-r["discretionary_buyers"], -r["total_value"]))
    return out
