# backend/institutional_holdings.py
"""
"What are well-known investors buying?" — from SEC Form 13F.

Every institutional manager with >$100M in US equities must file a 13F
within 45 days of each quarter end, listing its long US equity positions.
Comparing a manager's two most recent 13Fs shows what it opened, added to,
trimmed, and exited. This module does that for a curated list of
managers, then aggregates across them into a "consensus" view: which
stocks the most managers bought last quarter.

Honesty notes — what 13Fs can and can't tell you:
- STALE BY DESIGN: a 13F shows holdings as of quarter end, filed up to 45
  days later. By the time you see it, the position may already be gone.
- LONG US EQUITIES ONLY: no shorts, no cash, no bonds, no non-US listings.
  A "new position" may be one leg of a hedged trade you can't see.
- OPTIONS are reported as the underlying share count (puts and calls are
  separate rows). They're kept separate here and excluded from consensus,
  since a large put position is a bearish bet, not a purchase.
- SIZE MATTERS: a "new position" at 0.1% of a portfolio is a toe in the
  water; check the weight column before reading conviction into it.
- The manager list below is "well-known", not "proven top performers" —
  13Fs don't report returns, and past performance isn't predictive anyway.

CUSIP -> ticker mapping uses OpenFIGI (Bloomberg's free public identifier
API; no key, ~25 requests/minute). Results are cached permanently since a
CUSIP's ticker almost never changes, so only a manager's first refresh
is slow.
"""

import math
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import requests

from . import db, sec_utils

# Every CIK here was checked against SEC's submissions API (name matches,
# files 13F-HR, filed within the last year). `default` = included in the
# standard refresh. Quant / macro shops with thousands of positions are
# opt-in: they make the first refresh much slower and their quarterly
# churn is mostly systematic rebalancing, not conviction buying.
MANAGERS: List[Dict] = [
    {"cik": "0001067983", "name": "Berkshire Hathaway", "manager": "Warren Buffett / Greg Abel", "style": "Value", "default": True},
    {"cik": "0001336528", "name": "Pershing Square", "manager": "Bill Ackman", "style": "Concentrated activist", "default": True},
    {"cik": "0001656456", "name": "Appaloosa", "manager": "David Tepper", "style": "Opportunistic", "default": True},
    {"cik": "0001536411", "name": "Duquesne Family Office", "manager": "Stanley Druckenmiller", "style": "Macro / growth", "default": True},
    {"cik": "0001061768", "name": "Baupost Group", "manager": "Seth Klarman", "style": "Deep value", "default": True},
    {"cik": "0001040273", "name": "Third Point", "manager": "Dan Loeb", "style": "Event-driven", "default": True},
    {"cik": "0001167483", "name": "Tiger Global", "manager": "Chase Coleman", "style": "Tech growth", "default": True},
    {"cik": "0001135730", "name": "Coatue", "manager": "Philippe Laffont", "style": "Tech growth", "default": True},
    {"cik": "0001061165", "name": "Lone Pine Capital", "manager": "Stephen Mandel (founder)", "style": "Growth", "default": True},
    {"cik": "0001103804", "name": "Viking Global", "manager": "Andreas Halvorsen", "style": "Long/short equity", "default": True},
    {"cik": "0001029160", "name": "Soros Fund Management", "manager": "Soros family office", "style": "Macro", "default": True},
    {"cik": "0001541617", "name": "Altimeter Capital", "manager": "Brad Gerstner", "style": "Tech growth", "default": True},
    {"cik": "0001791786", "name": "Elliott Investment Mgmt", "manager": "Paul Singer", "style": "Activist", "default": True},
    {"cik": "0001747057", "name": "D1 Capital Partners", "manager": "Dan Sundheim", "style": "Growth", "default": True},
    {"cik": "0000934639", "name": "Maverick Capital", "manager": "Lee Ainslie", "style": "Long/short equity", "default": True},
    {"cik": "0001709323", "name": "Himalaya Capital", "manager": "Li Lu", "style": "Concentrated value", "default": True},
    {"cik": "0001112520", "name": "Akre Capital", "manager": "Akre / Neff / Saler", "style": "Quality compounders", "default": True},
    {"cik": "0002045724", "name": "Situational Awareness LP", "manager": "Leopold Aschenbrenner", "style": "AI-focused", "default": True},
    {"cik": "0001697748", "name": "ARK Investment Mgmt", "manager": "Cathie Wood", "style": "Disruptive innovation", "default": False},
    {"cik": "0001350694", "name": "Bridgewater Associates", "manager": "Ray Dalio (founder)", "style": "Systematic macro", "default": False},
    {"cik": "0001037389", "name": "Renaissance Technologies", "manager": "Jim Simons (founder)", "style": "Quant", "default": False},
]
MANAGERS_BY_CIK = {m["cik"]: m for m in MANAGERS}

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH = 10            # max jobs per request without an API key
OPENFIGI_MIN_INTERVAL = 2.6    # seconds; keeps under 25 requests/minute

# Share-count change thresholds for classifying a continuing position.
CHANGE_THRESHOLD = 0.10
SPLIT_RATIOS = (2, 3, 4, 5, 8, 10, 15, 20, 25, 50)


# =============================================================================
# Fetching
# =============================================================================

def get_13f_filings(cik: str, session: requests.Session, count: int = 2) -> List[Dict]:
    """
    The `count` most recent ORIGINAL 13F-HRs, one per report period, newest
    first. Amendments are skipped — most are "new holdings" add-ons that
    aren't a full portfolio, which would distort the quarter comparison.
    """
    cache_key = f"{cik}_{count}"
    cached = db.cache_get("13f_filings", cache_key, ttl_seconds=12 * 3600)
    if cached is not None:
        return cached

    try:
        resp = sec_utils._polite_get(session, sec_utils.SUBMISSIONS_URL.format(cik=cik))
        resp.raise_for_status()
        recent = resp.json().get("filings", {}).get("recent", {})
    except (requests.RequestException, ValueError):
        return []

    filings, periods = [], set()
    for i, form in enumerate(recent.get("form", [])):
        if form != "13F-HR":
            continue
        period = recent["reportDate"][i]
        if period in periods:
            continue
        periods.add(period)
        filings.append({
            "accession_number": recent["accessionNumber"][i].replace("-", ""),
            "filing_date": recent["filingDate"][i],
            "report_date": period,
        })
        if len(filings) >= count:
            break

    db.cache_set("13f_filings", cache_key, filings)
    return filings


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_information_table(xml_text: str) -> Dict[str, Dict]:
    """
    Pure function. 13F information-table XML -> positions keyed by
    "CUSIP" (common/shares) or "CUSIP|PUT" / "CUSIP|CALL" (options).
    Rows for the same security are summed: large filers split one holding
    across several rows by sub-manager (Berkshire lists Ally on 3+ rows).
    """
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    positions: Dict[str, Dict] = {}
    for row in root.iter():
        if _strip_ns(row.tag) != "infoTable":
            continue
        fields: Dict[str, str] = {}
        for el in row.iter():
            name = _strip_ns(el.tag)
            if el.text and el.text.strip() and name not in fields:
                fields[name] = el.text.strip()

        cusip = fields.get("cusip", "").upper()
        if not cusip:
            continue
        put_call = (fields.get("putCall") or "").upper() or None
        key = f"{cusip}|{put_call}" if put_call else cusip
        try:
            value = float(fields.get("value", 0))
            shares = float(fields.get("sshPrnamt", 0))
        except ValueError:
            continue

        pos = positions.setdefault(key, {
            "cusip": cusip,
            "name": fields.get("nameOfIssuer", ""),
            "title_of_class": fields.get("titleOfClass", ""),
            "put_call": put_call,
            "shares_type": fields.get("sshPrnamtType", "SH"),
            "value": 0.0,
            "shares": 0.0,
        })
        pos["value"] += value
        pos["shares"] += shares
    return positions


def fetch_holdings(cik: str, filing: Dict, session: requests.Session) -> Optional[Dict[str, Dict]]:
    """Positions for one 13F filing; cached forever (a filed 13F never changes)."""
    cache_key = f"{cik}_{filing['accession_number']}"
    cached = db.cache_get("13f_holdings", cache_key, ttl_seconds=None)
    if cached is not None:
        return cached

    base = (f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
            f"{filing['accession_number']}/")
    try:
        resp = sec_utils._polite_get(session, base + "index.json")
        resp.raise_for_status()
        items = resp.json().get("directory", {}).get("item", [])
    except (requests.RequestException, ValueError):
        return None

    # The information table is the XML that isn't the cover page; its file
    # name varies by filing agent ("56757.xml", "infotable.xml", ...).
    xml_names = [it["name"] for it in items
                 if it.get("name", "").lower().endswith(".xml")
                 and it["name"].lower() != "primary_doc.xml"]
    for name in xml_names:
        try:
            r = sec_utils._polite_get(session, base + name, timeout=30)
            r.raise_for_status()
        except requests.RequestException:
            continue
        if "infoTable" not in r.text:
            continue
        try:
            positions = parse_information_table(r.text)
        except ET.ParseError:
            continue
        db.cache_set("13f_holdings", cache_key, positions)
        return positions
    return None


# =============================================================================
# Quarter-over-quarter changes
# =============================================================================

def _split_factor(prev: Dict, curr: Dict) -> int:
    """
    Detects a stock split between quarters: shares jumped by ~k while the
    implied price fell by ~1/k. Without this, NVIDIA's 10-for-1 split reads
    as "added 900%". Returns k (1 = no split).
    """
    if not (prev["shares"] and curr["shares"] and prev["value"] and curr["value"]):
        return 1
    share_ratio = curr["shares"] / prev["shares"]
    price_ratio = (curr["value"] / curr["shares"]) / (prev["value"] / prev["shares"])
    # A split is a property of the stock's price, so k is chosen from the
    # price: price_ratio * k is the stock's own quarterly move, accepted
    # within -55%..+60%, and the k that puts it closest to flat wins. Any
    # remaining share change is real trading (Carvana's 2026 5:1 split
    # with Viking's shares up only 4x = a 20% trim, not a 4:1 split).
    # Shares must also have grown materially, so a crash alone isn't read
    # as a split. The +60% bound is what separates a 2:1 split from a
    # manager doubling a flat-priced position (2.0); a doubling during a
    # quarter the stock fell >20% is genuinely indistinguishable from a
    # 2:1 split using 13F data alone.
    if share_ratio < 1.5:
        return 1
    candidates = [k for k in SPLIT_RATIOS if 0.45 < price_ratio * k < 1.6]
    if not candidates:
        return 1
    return min(candidates, key=lambda k: abs(math.log(price_ratio * k)))


def normalize_value_units(positions: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Pure function. Since 2023 13F values must be in dollars, but some
    filers still report in thousands (Duquesne and Baupost did in 2026),
    which would understate their portfolios 1000x. Detected per filing: if
    the median implied share price is under $1, values are in thousands.
    """
    prices = sorted(p["value"] / p["shares"] for p in positions.values()
                    if p["shares"] and p["value"] and not p["put_call"])
    if prices and prices[len(prices) // 2] < 1.0:
        return {k: {**p, "value": p["value"] * 1000} for k, p in positions.items()}
    return positions


def _apply_split(row: Dict, k: int) -> None:
    """(Re)classify a continuing position, treating prior shares as split k:1."""
    prev_shares = row["raw_shares_prev"] * k
    row["split_adjusted"] = k
    row["shares_prev"] = prev_shares
    delta = row["shares_curr"] - prev_shares
    pct = delta / prev_shares if prev_shares else 0.0
    price = row["value_curr"] / row["shares_curr"] if row["shares_curr"] else 0.0
    row["shares_change_pct"] = round(pct * 100, 1)
    row["est_value_change"] = delta * price
    if pct >= CHANGE_THRESHOLD:
        row["change_type"] = "added"
    elif pct <= -CHANGE_THRESHOLD:
        row["change_type"] = "trimmed"
    else:
        row["change_type"] = "held"


def _actual_split_ratio(ticker: str, start: str, end: str) -> Optional[float]:
    """
    Split ratio yfinance records for `ticker` between two quarter ends
    (1.0 = no split), or None if it couldn't be checked. Cached per window.
    """
    cache_key = f"{ticker}_{start}_{end}"
    cached = db.cache_get("split_check", cache_key, ttl_seconds=None)
    if cached is not None:
        return cached.get("ratio")
    try:
        import yfinance as yf
        splits = yf.Ticker(ticker).splits
    except Exception:
        return None
    ratio = 1.0
    for when, r in splits.items():
        if start < when.strftime("%Y-%m-%d") <= end:
            ratio *= float(r)
    db.cache_set("split_check", cache_key, {"ratio": ratio})
    return ratio


def verify_splits(activity: Dict) -> None:
    """
    The share/price heuristic can't tell a 2:1 split from a manager
    doubling a position while the stock fell 20%+ (Himalaya and PDD,
    Q2 2026), so every suspected split is checked against the stock's
    recorded split history. No split on record -> reclassified as real
    trading; unverifiable (no ticker / yfinance down) -> kept, flagged.
    """
    for row in activity.get("changes", []):
        if row.get("split_adjusted", 1) <= 1:
            continue
        ratio = None
        if row.get("ticker"):
            ratio = _actual_split_ratio(row["ticker"], activity["prior_report_date"],
                                        activity["report_date"])
        if ratio is None:
            row["split_verified"] = False
        elif ratio > 1.0:
            _apply_split(row, int(round(ratio)))
            row["split_verified"] = True
        else:
            _apply_split(row, 1)


def compute_changes(prev: Dict[str, Dict], curr: Dict[str, Dict]) -> List[Dict]:
    """
    Pure function. Classifies every position as new / added / trimmed /
    exited / held, with portfolio weight and an estimated dollar value of
    the change (share change x current implied price).
    """
    total_curr = sum(p["value"] for p in curr.values()) or 1.0
    total_prev = sum(p["value"] for p in prev.values()) or 1.0
    changes = []

    for key in set(prev) | set(curr):
        p, c = prev.get(key), curr.get(key)
        base = c or p
        row = {
            "key": key,
            "cusip": base["cusip"],
            "name": base["name"],
            "put_call": base["put_call"],
            "shares_prev": p["shares"] if p else 0.0,
            "shares_curr": c["shares"] if c else 0.0,
            "value_prev": p["value"] if p else 0.0,
            "value_curr": c["value"] if c else 0.0,
            "weight_curr_pct": round((c["value"] if c else 0.0) / total_curr * 100, 2),
            "weight_prev_pct": round((p["value"] if p else 0.0) / total_prev * 100, 2),
            "split_adjusted": 1,
        }

        if c and not p:
            row["change_type"] = "new"
            row["shares_change_pct"] = None
            row["est_value_change"] = c["value"]
        elif p and not c:
            row["change_type"] = "exited"
            row["shares_change_pct"] = -100.0
            row["est_value_change"] = -p["value"]
        else:
            row["raw_shares_prev"] = p["shares"]
            _apply_split(row, _split_factor(p, c))
        changes.append(row)

    changes.sort(key=lambda r: -abs(r["est_value_change"]))
    return changes


# =============================================================================
# CUSIP -> ticker
# =============================================================================

_last_figi_call = 0.0


def _id_type(cusip: str) -> str:
    # Non-US issuers get CINS codes (a CUSIP variant starting with a letter,
    # e.g. Seagate G7997R103); OpenFIGI only resolves them as ID_CINS.
    return "ID_CINS" if cusip[:1].isalpha() else "ID_CUSIP"


def map_cusips(cusips: List[str], session: Optional[requests.Session] = None) -> Dict[str, Optional[str]]:
    """
    {cusip: ticker or None}. Cached permanently per CUSIP (misses for 30
    days, in case OpenFIGI was briefly unavailable). Fails soft: anything
    that couldn't be mapped comes back None and the UI shows the issuer
    name instead.
    """
    global _last_figi_call
    session = session or requests.Session()
    result: Dict[str, Optional[str]] = {}
    todo = []
    for cusip in dict.fromkeys(cusips):
        cached = db.cache_get("cusip_ticker", cusip, ttl_seconds=None)
        if cached is not None and (cached.get("ticker") or (
                cached.get("id_type") == _id_type(cusip)
                and time.time() - cached.get("checked_at", 0) < 30 * 86400)):
            result[cusip] = cached.get("ticker")
        else:
            todo.append(cusip)

    for i in range(0, len(todo), OPENFIGI_BATCH):
        batch = todo[i:i + OPENFIGI_BATCH]
        wait = OPENFIGI_MIN_INTERVAL - (time.time() - _last_figi_call)
        if wait > 0:
            time.sleep(wait)
        jobs = [{"idType": _id_type(c), "idValue": c} for c in batch]
        data = None
        for _attempt in range(2):
            try:
                _last_figi_call = time.time()
                resp = session.post(OPENFIGI_URL, json=jobs, timeout=20)
                if resp.status_code == 429:
                    time.sleep(60)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except (requests.RequestException, ValueError):
                break
        if data is None:
            for c in batch:
                result[c] = None
            continue

        for cusip, answer in zip(batch, data):
            listings = answer.get("data") or []
            # Prefer the US composite listing; fall back to any listing.
            pick = next((x for x in listings if x.get("exchCode") == "US"), None) \
                or (listings[0] if listings else None)
            ticker = pick.get("ticker") if pick else None
            result[cusip] = ticker
            db.cache_set("cusip_ticker", cusip, {"ticker": ticker, "checked_at": time.time(),
                                                 "id_type": _id_type(cusip)})

    return result


# =============================================================================
# Per-manager report + consensus
# =============================================================================

def manager_activity(cik: str, session: requests.Session) -> Dict:
    meta = MANAGERS_BY_CIK.get(cik, {"cik": cik, "name": cik, "manager": "", "style": ""})
    out = {**{k: v for k, v in meta.items() if k != "default"}, "error": None,
           "changes": [], "report_date": None, "prior_report_date": None}

    filings = get_13f_filings(cik, session, count=2)
    if len(filings) < 2:
        out["error"] = "Fewer than two 13F-HR filings available to compare"
        return out

    curr = fetch_holdings(cik, filings[0], session)
    prev = fetch_holdings(cik, filings[1], session)
    if curr is None or prev is None:
        out["error"] = "Could not read the 13F information table"
        return out
    curr, prev = normalize_value_units(curr), normalize_value_units(prev)

    out.update({
        "report_date": filings[0]["report_date"],
        "filing_date": filings[0]["filing_date"],
        "prior_report_date": filings[1]["report_date"],
        "total_value": sum(p["value"] for p in curr.values()),
        "position_count": len(curr),
        "source_url": (f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
                       f"{filings[0]['accession_number']}/"),
        "changes": compute_changes(prev, curr),
    })
    return out


def build_consensus(activities: List[Dict]) -> List[Dict]:
    """
    Pure function. One row per stock (common shares only — options are
    excluded, see module docstring), counting how many managers bought
    (new or added) vs sold (trimmed or exited) it last quarter.
    """
    rows: Dict[str, Dict] = {}
    for act in activities:
        if act.get("error"):
            continue
        for ch in act["changes"]:
            if ch["put_call"] or ch["change_type"] == "held":
                continue
            r = rows.setdefault(ch["cusip"], {
                "cusip": ch["cusip"], "name": ch["name"], "ticker": ch.get("ticker"),
                "buyers": [], "sellers": [], "est_net_value_change": 0.0,
            })
            entry = {
                "manager": act["name"],
                "change_type": ch["change_type"],
                "shares_change_pct": ch["shares_change_pct"],
                "weight_curr_pct": ch["weight_curr_pct"],
                "est_value_change": ch["est_value_change"],
            }
            (r["buyers"] if ch["change_type"] in ("new", "added") else r["sellers"]).append(entry)
            r["est_net_value_change"] += ch["est_value_change"]

    out = []
    for r in rows.values():
        r["buyer_count"] = len(r["buyers"])
        r["seller_count"] = len(r["sellers"])
        r["net_buyers"] = r["buyer_count"] - r["seller_count"]
        r["new_position_count"] = sum(1 for b in r["buyers"] if b["change_type"] == "new")
        out.append(r)
    out.sort(key=lambda r: (-r["net_buyers"], -r["buyer_count"], -r["est_net_value_change"]))
    return out


def run_institutional_report(ciks: Optional[List[str]] = None,
                             session: Optional[requests.Session] = None) -> Dict:
    """
    Full refresh: every manager's quarter-over-quarter changes, tickers
    attached, plus the cross-manager consensus. Stored as the latest report
    so the UI can read it back instantly.
    """
    session = session or sec_utils.make_sec_session()
    ciks = ciks or [m["cik"] for m in MANAGERS if m["default"]]

    activities = []
    for cik in ciks:
        try:
            activities.append(manager_activity(cik, session))
        except Exception as e:  # one bad filing shouldn't sink the report
            meta = MANAGERS_BY_CIK.get(cik, {"name": cik})
            activities.append({"cik": cik, "name": meta["name"], "changes": [],
                               "error": f"{type(e).__name__}: {e}"})

    # Map every common-stock CUSIP that changed or is held.
    cusips = sorted({ch["cusip"] for a in activities for ch in a.get("changes", [])})
    tickers = map_cusips(cusips)
    for a in activities:
        for ch in a.get("changes", []):
            ch["ticker"] = tickers.get(ch["cusip"])
        if not a.get("error"):
            verify_splits(a)
            a["changes"].sort(key=lambda r: -abs(r["est_value_change"]))

    report = {
        "generated_at": time.time(),
        "managers": activities,
        "consensus": build_consensus(activities),
    }
    db.cache_set("institutional_report", "latest", report)
    return report


def get_latest_report() -> Optional[Dict]:
    return db.cache_get("institutional_report", "latest", ttl_seconds=None)


def holdings_for_tickers(report: Dict, tickers: List[str]) -> Dict[str, List[Dict]]:
    """
    Pure function. {ticker: [{manager, change_type, weight, ...}]} for each
    ticker any tracked manager holds or traded — used to cross-reference
    the Scanner's supplier picks.
    """
    wanted = {t.upper() for t in tickers}
    out: Dict[str, List[Dict]] = {t: [] for t in wanted}
    for act in report.get("managers", []):
        for ch in act.get("changes", []):
            t = (ch.get("ticker") or "").upper()
            if t in wanted and not ch["put_call"]:
                out[t].append({
                    "manager": act["name"],
                    "change_type": ch["change_type"],
                    "shares_change_pct": ch["shares_change_pct"],
                    "weight_curr_pct": ch["weight_curr_pct"],
                    "value_curr": ch["value_curr"],
                })
    return out
