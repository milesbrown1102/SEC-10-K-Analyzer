# backend/aftermath.py
"""
"What happened after this filing?" — for one company's 10-K, the 12
months that followed:

1. Its stock: total return 3 / 6 / 12 months after the filing, vs SPY.
2. Money it put into other companies, and agreements it signed:
   a. Other companies' 8-Ks naming it as investor or counterparty
      (Items 1.01 agreement / 2.01 acquisition / 3.02 sale of shares).
      Big companies rarely file these themselves — a $5B deal is
      immaterial to NVIDIA but material to the company receiving it,
      which must disclose it. Each comes with the counterparty's ticker,
      industry, and stock return from the disclosure date.
   b. Its own 8-K agreements (commercial / M&A — financing excluded).
   c. If it files a 13F (NVIDIA, Alphabet, Amazon do): public companies
      it newly bought stakes in, or added to, over the year.
3. Fixing it in-house, as disclosed in its own filings over the year:
   sentences about building its own capacity / custom silicon / on-site
   power, and about securing supply (prepaid capacity, long-term supply
   agreements) — plus the change in CapEx.

The link between a deal and the bottleneck is INFERRED from timing and
wording. Companies almost never write "we invested in X to relieve
shortage Y"; the page shows the evidence so you can judge.
"""

import re
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

from . import bottleneck_detector, db, deal_monitor, institutional_holdings, point_in_time as pit, sec_utils
from .capex_pipeline import CAPEX_TAGS

AFTERMATH_VERSION = "v2"
WINDOW_DAYS = 365
DEAL_ITEMS = {"1.01", "2.01", "3.02"}
MAX_FTS_PAGES = 10
MAX_COUNTERPARTY_DOCS = 120

# Names other filers use for the big companies. Everything else falls back
# to the company's SEC name without its legal suffix ("Vistra Corp." ->
# "Vistra"). Short or generic names ("Apple", "Meta") need the long form.
ALIASES = {
    "NVDA": ["NVIDIA"],
    "MSFT": ["Microsoft"],
    "GOOGL": ["Alphabet", "Google"],
    "GOOG": ["Alphabet", "Google"],
    "AMZN": ["Amazon.com", "Amazon Web Services"],
    "META": ["Meta Platforms"],
    "AAPL": ["Apple Inc"],
    "ORCL": ["Oracle"],
    "TSLA": ["Tesla"],
}
_LEGAL_SUFFIX = re.compile(
    r"[,.]?\s+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|llc|plc|lp|l\.p|"
    r"holdings?|group|n\.v|s\.a|ag|se|/\w+/)\.?$", re.IGNORECASE)

# A mention that's just about buying the company's products, not a deal with it.
_PRODUCT_CONTEXT = re.compile(
    r"\b(?:gpus?|chips?|graphics|accelerators?|h100|h200|b200|gb200|gb300|blackwell|hopper|rubin|"
    r"servers?|hardware|cloud\s+(?:credits|services)|instances?|azure|aws\s+marketplace|"
    r"powered|based|certified|inception|partner\s+network|marketplace|app\s+store)\b",
    re.IGNORECASE)
_INVEST_VERBS = re.compile(
    r"\b(?:purchas\w*|acquir\w*|invest\w*|subscri\w*|bought|backed|led\s+by|anchor\w*)\b", re.IGNORECASE)
_SECURITIES = re.compile(
    r"\b(?:shares|stock|securities|notes|warrants?|equity|stake|interest|units|preferred)\b", re.IGNORECASE)
_SOLD_TO = re.compile(r"\b(?:sold|sell|sale\s+of|issue[ds]?|issuance)\b[^.;]{0,120}?\bto\b", re.IGNORECASE)

IN_HOUSE_CUES = re.compile(
    r"\b(?:in-house|internally\s+(?:developed|designed|built)"
    r"|our\s+own\s+(?:custom\s+)?(?:chips?|silicon|data\s*cent\w+|power|generation|fabs?|manufacturing|"
    r"infrastructure|supply|accelerators?|processors?)"
    r"|custom(?:-built|-designed|\s+designed|\s+built)?\s+(?:silicon|chips?|accelerators?|processors?|asics?)"
    r"|vertical(?:ly)?\s+integrat\w+"
    r"|(?:are\s+building|are\s+constructing|have\s+built|will\s+build|plan\s+to\s+build)\s+(?:our\s+own|new|additional)"
    r"|on-site\s+(?:power|generation)|self-generat\w+|behind-the-meter)\b",
    re.IGNORECASE)
SECURED_SUPPLY_CUES = re.compile(
    r"\b(?:prepa(?:id|yments?)\s+(?:supply|capacity|for\s+(?:supply|capacity))"
    r"|long-term\s+(?:supply|capacity|purchase)\s+(?:agreements?|commitments?|contracts?)"
    r"|capacity\s+(?:agreements?|reservations?)"
    r"|secur(?:e|ed|ing)\s+(?:additional\s+)?(?:supply|capacity|power)"
    r"|power\s+purchase\s+agreements?|multi-year\s+supply"
    r"|purchase\s+(?:obligations|commitments)\s+(?:increased|grew|were\s+\$|of\s+\$))\b",
    re.IGNORECASE)


def _plus_days(d: str, days: int) -> str:
    return (datetime.fromisoformat(d) + timedelta(days=days)).date().isoformat()


def _ret(ticker: Optional[str], start: str, end: str) -> Optional[float]:
    if not ticker:
        return None
    p0, p1 = pit.price_on(ticker, start), pit.price_on(ticker, min(end, pit.today()))
    return round((p1 / p0 - 1) * 100, 1) if p0 and p1 else None


def company_profile(cik: str, session: requests.Session) -> Dict:
    cached = db.cache_get("company_profile", cik, ttl_seconds=30 * 86400)
    if cached:
        return cached
    try:
        d = sec_utils._polite_get(session, sec_utils.SUBMISSIONS_URL.format(cik=cik)).json()
        out = {"name": d.get("name"), "sic": d.get("sic"), "industry": d.get("sicDescription"),
               "tickers": d.get("tickers", [])}
    except (requests.RequestException, ValueError):
        return {"name": None, "sic": None, "industry": None, "tickers": []}
    db.cache_set("company_profile", cik, out)
    return out


def aliases_for(ticker: str, cik: str, session: requests.Session) -> List[str]:
    if ticker in ALIASES:
        return ALIASES[ticker]
    name = (company_profile(cik, session).get("name") or "").strip()
    core = name
    for _ in range(3):
        core = _LEGAL_SUFFIX.sub("", core).strip()
    return [core] if len(core) >= 4 else [name]


# =============================================================================
# 1. Stock after the filing
# =============================================================================

def stock_after(ticker: str, filing_date: str) -> Dict:
    out = {}
    for m in (3, 6, 12):
        end = _plus_days(filing_date, round(m * 30.44))
        if end > pit.today():
            out[f"{m}m"] = None
            continue
        r, spy = _ret(ticker, filing_date, end), _ret("SPY", filing_date, end)
        out[f"{m}m"] = {"return_pct": r, "spy_pct": spy,
                        "vs_spy_pct": round(r - spy, 1) if r is not None and spy is not None else None}
    out["to_today"] = {"return_pct": _ret(ticker, filing_date, pit.today()),
                       "spy_pct": _ret("SPY", filing_date, pit.today())}
    return out


# =============================================================================
# 2a. Other companies' 8-Ks naming this company as investor / counterparty
# =============================================================================

def _item_sections(text: str) -> str:
    """Text of Items 1.01 / 2.01 / 3.02 in an 8-K (where counterparties are named)."""
    flat = re.sub(r"\s+", " ", text)
    parts = []
    for m in re.finditer(r"item\s*(1\.01|2\.01|3\.02)\b", flat, re.IGNORECASE):
        body = flat[m.end():m.end() + 6000]
        nxt = re.search(r"\bitem\s*\d\.\d\d\b", body, re.IGNORECASE)
        parts.append(body[:nxt.start()] if nxt else body)
    return " ".join(parts)


def classify_counterparty(section_text: str, aliases: List[str]) -> Optional[Dict]:
    """
    Pure function. How `aliases` appear in an 8-K's deal sections:
    'invested' (bought the filer's securities), 'agreement' (counterparty
    to a material agreement), or None (absent, or only as a product the
    filer buys/uses — "NVIDIA GPUs").
    """
    alias_re = re.compile(r"\b(?:" + "|".join(re.escape(a) for a in aliases) + r")\b", re.IGNORECASE)
    sentences = re.split(r"(?<=[.;])\s+(?=[A-Z(“\"])", section_text)
    best, evidence = None, None
    for s in sentences:
        m = alias_re.search(s)
        if not m:
            continue
        after = s[m.end():m.end() + 40]
        if _PRODUCT_CONTEXT.search(after) and not re.search(r"(?i)\bagreement\b", s):
            continue  # "NVIDIA GPUs", "NVIDIA-powered"
        window = s[max(0, m.start() - 200):m.end() + 200]
        sold_to = _SOLD_TO.search(s)
        invested = ((_INVEST_VERBS.search(window) and _SECURITIES.search(window))
                    or (sold_to and alias_re.search(s[sold_to.end():sold_to.end() + 80])))
        if invested:
            return {"relationship": "invested", "evidence": s[:500]}
        if re.search(r"(?i)\b(?:agreement|contract|partnership|collaboration|arrangement)\b", s) and \
                re.search(r"(?i)\b(?:with|between|and)\b", s):
            best, evidence = "agreement", s[:500]
    return {"relationship": best, "evidence": evidence} if best else None


def _fts(query: str, forms: str, start: str, end: str, session: requests.Session) -> List[Dict]:
    cache_key = f"{query}|{forms}|{start}|{end}"
    settled = end < _plus_days(pit.today(), -7)
    cached = db.cache_get("fts_query", cache_key, ttl_seconds=None if settled else 24 * 3600)
    if cached is not None:
        return cached
    hits = []
    for page in range(MAX_FTS_PAGES):
        params = {"q": query, "forms": forms, "dateRange": "custom",
                  "startdt": start, "enddt": end, "from": page * 100}
        data = None
        for attempt in range(3):
            try:
                data = sec_utils._polite_get(
                    session, "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(params),
                    timeout=30).json()
                if "hits" in data:
                    break
            except (requests.RequestException, ValueError):
                pass
            time.sleep(2 + 3 * attempt)
        if not data or "hits" not in data:
            break
        batch = data["hits"]["hits"]
        for h in batch:
            src = h["_source"]
            adsh, _, filename = h["_id"].partition(":")
            hits.append({"cik": (src.get("ciks") or [""])[0], "display_name": (src.get("display_names") or [""])[0],
                         "sic": (src.get("sics") or [None])[0], "items": src.get("items") or [],
                         "file_type": src.get("file_type"), "file_date": src.get("file_date"),
                         "adsh": adsh, "filename": filename})
        if len(batch) < 100:
            break
    db.cache_set("fts_query", cache_key, hits)
    return hits


_TICKER_RE = re.compile(r"\(([A-Z0-9.\-]{1,6})(?:,\s*[A-Z0-9.\-]+)*\)\s*\(CIK")


def counterparty_deals(ticker: str, cik: str, start: str, end: str,
                       session: requests.Session) -> List[Dict]:
    aliases = aliases_for(ticker, cik, session)
    query = " OR ".join(f'"{a}"' for a in aliases)
    candidates = {}
    for h in _fts(query, "8-K", start, end, session):
        if h["cik"].lstrip("0") == cik.lstrip("0") or h["file_type"] != "8-K":
            continue
        if not DEAL_ITEMS & set(h["items"]):
            continue
        candidates.setdefault(h["adsh"], h)

    deals = []
    titles = sec_utils_titles(session)
    for h in sorted(candidates.values(), key=lambda h: h["file_date"], reverse=True)[:MAX_COUNTERPARTY_DOCS]:
        key = f"{AFTERMATH_VERSION}|{h['adsh']}|{'|'.join(aliases)}"
        result = db.cache_get("counterparty_doc", key, ttl_seconds=None)
        if result is None:
            url = (f"https://www.sec.gov/Archives/edgar/data/{h['cik'].lstrip('0')}/"
                   f"{h['adsh'].replace('-', '')}/{h['filename']}")
            try:
                resp = sec_utils._polite_get(session, url, timeout=30)
                resp.raise_for_status()
                text = sec_utils.html_to_text(resp.text)
            except requests.RequestException:
                continue
            result = classify_counterparty(_item_sections(text), aliases) or {}
            result["url"] = url
            db.cache_set("counterparty_doc", key, result)
        if not result.get("relationship"):
            continue
        m = _TICKER_RE.search(h["display_name"])
        cp_ticker = m.group(1) if m else None
        deals.append({
            "date": h["file_date"], "relationship": result["relationship"],
            "company": re.sub(r"\s*\(.*$", "", h["display_name"]).strip(),
            "ticker": cp_ticker, "sic": h["sic"], "industry": titles.get(h["sic"] or "", None),
            "items": h["items"], "evidence": result["evidence"], "url": result["url"],
            "return_12m_pct": _ret(cp_ticker, h["file_date"], _plus_days(h["file_date"], 365)),
            "return_to_today_pct": _ret(cp_ticker, h["file_date"], pit.today()),
            "spy_12m_pct": _ret("SPY", h["file_date"], _plus_days(h["file_date"], 365)),
        })
    return deals


def sec_utils_titles(session: requests.Session) -> Dict[str, str]:
    from .industry_radar import sic_descriptions
    return sic_descriptions(session)


# =============================================================================
# 2b. Its own 8-K agreements
# =============================================================================

_COUNTERPARTY_NAME = re.compile(
    r"\bwith\s+(?:the\s+)?([A-Z][A-Za-z0-9&.'\-]+(?:\s+[A-Z][A-Za-z0-9&.'\-]+){0,5})")


def own_deals(cik: str, start: str, end: str, session: requests.Session) -> List[Dict]:
    out = []
    for f in pit.all_filings(cik, session):
        if f["form"] != "8-K" or not (start < f["filing_date"] <= end):
            continue
        items = set(f["items"].split(","))
        if not items & {"1.01", "2.01"}:
            continue
        text = sec_utils.fetch_filing_text(cik, f, session) or ""
        c = deal_monitor.classify_item_101(text)
        if not c or c["deal_type"] == "financing":
            continue
        m = _COUNTERPARTY_NAME.search(c["evidence"] or "")
        out.append({"date": f["filing_date"], "type": c["deal_type"], "evidence": c["evidence"],
                    "counterparty": m.group(1) if m else None,
                    "url": sec_utils.get_filing_document_url(cik, f)})
    return out


# =============================================================================
# 2c. Stakes in public companies (its own 13F)
# =============================================================================

def thirteen_f_changes(cik: str, start: str, end: str, session: requests.Session) -> Optional[Dict]:
    filings = [f for f in pit.all_filings(cik, session) if f["form"] == "13F-HR"]
    if not filings:
        return None
    before = [f for f in filings if f["filing_date"] <= start]
    after = [f for f in filings if f["filing_date"] <= end]
    if not after:
        return None
    later = after[0]  # newest by end of window
    first = before[0] if before else None
    curr = institutional_holdings.fetch_holdings(cik, later, session) or {}
    prev = institutional_holdings.fetch_holdings(cik, first, session) or {} if first else {}
    curr = institutional_holdings.normalize_value_units(curr)
    prev = institutional_holdings.normalize_value_units(prev) if prev else {}
    changes = [c for c in institutional_holdings.compute_changes(prev, curr)
               if c["change_type"] in ("new", "added") and not c["put_call"]]
    tickers = institutional_holdings.map_cusips([c["cusip"] for c in changes])
    rows = []
    for c in changes:
        t = tickers.get(c["cusip"])
        tcik = sec_utils.get_cik_for_ticker(t, session) if t else None
        prof = company_profile(tcik, session) if tcik else {}
        rows.append({
            "ticker": t, "company": c["name"], "change": c["change_type"],
            "value": c["value_curr"], "industry": prof.get("industry"),
            "return_12m_pct": _ret(t, later["filing_date"], _plus_days(later["filing_date"], 365)),
            "return_to_today_pct": _ret(t, later["filing_date"], pit.today()),
        })
    rows.sort(key=lambda r: -(r["value"] or 0))
    return {"from_filing": first["filing_date"] if first else None,
            "to_filing": later["filing_date"], "positions": rows}


# =============================================================================
# 3. In-house fixes and secured supply, from its own filings
# =============================================================================

def disclosed_responses(cik: str, start: str, end: str, session: requests.Session) -> Dict:
    in_house, secured, seen = [], [], set()
    for f in pit.all_filings(cik, session):
        if f["form"] not in ("10-K", "10-Q") or not (start < f["filing_date"] <= end):
            continue
        text = sec_utils.fetch_filing_text(cik, f, session) or ""
        for s in bottleneck_detector._sentences(text):
            if s in seen or bottleneck_detector._NOISE.search(s):
                continue
            # Skip hypotheticals: "we may", "could", "if we" are risk-factor talk.
            if re.search(r"(?i)\b(?:may|might|could|if we|there can be no assurance)\b", s):
                continue
            # The company itself must be the actor — not its competitors or
            # customers ("some of our customers have in-house expertise").
            if not re.search(r"(?i)\b(?:we|our)\b", s) or \
                    re.search(r"(?i)\b(?:competitors?|customers?\s+(?:have|can|may|could|are))\b", s):
                continue
            # Financial-table rows flattened into text ("(In millions) ... $ 8,187").
            if "(In millions)" in s or sum(ch.isdigit() for ch in s) > len(s) * 0.12:
                continue
            seen.add(s)
            entry = {"date": f["filing_date"], "form": f["form"], "sentence": s[:450]}
            if IN_HOUSE_CUES.search(s):
                in_house.append(entry)
            elif SECURED_SUPPLY_CUES.search(s):
                secured.append(entry)
    return {"in_house": in_house[:8], "secured_supply": secured[:8]}


def capex_change(cik: str, filing_date: str, session: requests.Session) -> Optional[Dict]:
    before = pit.annual_value(cik, CAPEX_TAGS, filing_date, session)
    after = pit.annual_value(cik, CAPEX_TAGS, _plus_days(filing_date, 400), session)
    if not before or not after or after["end"] == before["end"]:
        return None
    return {"before_fy": before["end"], "before_usd": before["val"],
            "after_fy": after["end"], "after_usd": after["val"],
            "change_pct": round((after["val"] / before["val"] - 1) * 100, 1) if before["val"] else None}


# =============================================================================
# Entry point
# =============================================================================

def filing_aftermath(ticker: str, filing_date: str, session: Optional[requests.Session] = None) -> Dict:
    session = session or sec_utils.make_sec_session()
    ticker = ticker.strip().upper()
    cik = sec_utils.get_cik_for_ticker(ticker, session)
    if not cik:
        return {"error": f"No SEC filer found for '{ticker}'"}
    end = min(_plus_days(filing_date, WINDOW_DAYS), pit.today())
    cache_key = f"{AFTERMATH_VERSION}|{cik}|{filing_date}|{end}"
    settled = end < _plus_days(pit.today(), -7)
    cached = db.cache_get("aftermath", cache_key, ttl_seconds=None if settled else 24 * 3600)
    if cached is not None:
        return cached

    result = {
        "ticker": ticker, "filing_date": filing_date, "window_end": end,
        "window_complete": _plus_days(filing_date, WINDOW_DAYS) <= pit.today(),
        "stock": stock_after(ticker, filing_date),
        "counterparty_deals": counterparty_deals(ticker, cik, filing_date, end, session),
        "own_deals": own_deals(cik, filing_date, end, session),
        "thirteen_f": thirteen_f_changes(cik, filing_date, end, session),
        "disclosed": disclosed_responses(cik, filing_date, end, session),
        "capex": capex_change(cik, filing_date, session),
    }
    db.cache_set("aftermath", cache_key, result)
    return result
