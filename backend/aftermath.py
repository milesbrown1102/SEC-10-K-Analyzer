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

import math
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

from . import bottleneck_detector, db, deal_monitor, institutional_holdings, point_in_time as pit, sec_utils
from .capex_pipeline import CAPEX_TAGS

AFTERMATH_VERSION = "v8"
WINDOW_DAYS = 365
DEAL_ITEMS = {"1.01", "2.01", "3.02"}
# Partnerships are often announced by press release (Item 7.01 / 8.01, the
# release attached as EX-99) rather than as a "material definitive
# agreement" — softer evidence, labelled "announced".
ANNOUNCEMENT_ITEMS = {"7.01", "8.01"}
MAX_FTS_PAGES = 10
MAX_COUNTERPARTY_DOCS = 250

# Names other filers use for the big companies. Everything else falls back
# to the company's SEC name without its legal suffix ("Vistra Corp." ->
# "Vistra"). Short or generic names ("Apple", "Meta") need the long form.
ALIASES = {
    "NVDA": ["NVIDIA"],
    "MSFT": ["Microsoft"],
    "GOOGL": ["Alphabet", "Google"],
    "GOOG": ["Alphabet", "Google"],
    "AMZN": ["Amazon.com", "Amazon Web Services"],
    # Press releases say just "Meta" ("Constellation and Meta sign..."); the
    # product filter below and _ALIAS_EXCLUDE keep out "Meta ads", "Meta
    # Materials", "OneMeta".
    "META": ["Meta Platforms", "Meta"],
    "AAPL": ["Apple Inc"],
    "ORCL": ["Oracle"],
    "TSLA": ["Tesla"],
}
_LEGAL_SUFFIX = re.compile(
    r"[,.]?\s+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|llc|plc|lp|l\.p|"
    r"holdings?|group|n\.v|s\.a|ag|se|/\w+/)\.?$", re.IGNORECASE)

# Names that contain an alias but are other companies.
_ALIAS_EXCLUDE = re.compile(r"(?i)\bMeta\s+(?:Materials|Financial|Data)\b|\bmeta[- ]?(?:data|verse)\b")

# A mention that's just about buying the company's products, not a deal with it.
_PRODUCT_CONTEXT = re.compile(
    r"\b(?:gpus?|chips?|graphics|accelerators?|h100|h200|b200|gb200|gb300|blackwell|hopper|rubin|"
    r"ads|advertising|advertisers|ad\s+platforms?|platforms|quest|ray-ban|glasses|llama|instagram|"
    r"facebook|whatsapp|threads|pixel|campaigns?|marketplace|business\s+suite|"
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


# Words that may follow the alias and still mean the same company.
_SAME_COMPANY_FOLLOWERS = {"platforms", "inc", "inc.", "corporation", "corp", "corp.", "llc", "cloud",
                           "and", "to", "has", "have", "will", "is", "was", "agreed", "signed", "entered",
                           "selected", "announced", "plans", "intends", "committed", "would", "the"}
_PARTY_BEFORE = re.compile(r"(?i)\b(?:with|between|and|from|by|to|for)\s+(?:the\s+)?$")
_PARTY_AFTER = re.compile(
    r"(?i)^(?:,?\s*(?:Inc\.?|Platforms,?\s*Inc\.?|Corporation|Corp\.?|LLC))?\s*(?:\([^)]{0,40}\)\s*)?,?\s*"
    r"(?:and\b|has\b|have\b|will\b|signed\b|selected\b|agreed\b|entered\b|announced\b|committed\b|"
    r"is\s+(?:investing|acquiring|purchasing)|plans\b|intends\b)")
_DEAL_WORDS = re.compile(
    r"(?i)\b(?:agreement|contract|partnership|collaboration|arrangement|order\s+form|"
    r"power\s+purchase|supply|lease|investment|alliance|joint\s+venture|commitment)\b")
_ALIAS_INVESTS = r"[^.;]{0,80}?\b(?:invest\w*|agreed\s+to\s+(?:purchase|acquire|buy)|will\s+(?:purchase|acquire|buy)|purchased|acquired|subscribed|led|anchored)\b"


# Executive biographies mention past employers ("Prior to Meta, he was...").
_BIO = re.compile(
    r"(?i)\b(?:prior\s+to|previously|formerly|served\s+as|serving\s+as|joined|he\s+led|she\s+led|"
    r"his\s+career|her\s+career|tenure|was\s+(?:vice\s+president|vp|director|ceo|cfo|head|chief))\b")
_NOT_A_PARTY_BEFORE = {"with", "and", "the", "between", "from", "by", "to", "for"}


def _is_party(s: str, m: re.Match) -> bool:
    """The alias is a party to the sentence's deal, not a passing mention or another company's name."""
    prev = re.search(r"([A-Za-z]+)\s+$", s[:m.start()])
    if prev and prev.group(1)[0].isupper() and prev.group(1).lower() not in _NOT_A_PARTY_BEFORE \
            and m.start() > 0 and s[m.start() - 1] == " " and not re.search(r"[.;:]\s*$", s[:prev.start()]):
        return False  # "Hupecol Meta" is a different company
    nxt = re.match(r"\s*([A-Za-z.\-]+)", s[m.end():])
    if s[m.end():m.end() + 1] == "-":
        return False  # "Meta-PURE", "NVIDIA-powered"
    if nxt and nxt.group(1)[0].isupper() and nxt.group(1).lower() not in _SAME_COMPANY_FOLLOWERS:
        return False  # "Meta Healthcare Group" is a different company
    return bool(_PARTY_BEFORE.search(s[max(0, m.start() - 30):m.start()])
                or _PARTY_AFTER.search(s[m.end():m.end() + 80]))


def classify_counterparty(section_text: str, aliases: List[str]) -> Optional[Dict]:
    """
    Pure function. How `aliases` appear in a deal filing or press release:
    'invested' (the company bought or committed to buy the filer's
    securities), 'agreement' (a party to a deal), or None — absent, only a
    product the filer uses ("NVIDIA GPUs", "Meta ads"), or only mentioned
    in passing rather than as a party.
    """
    names = "|".join(re.escape(a) for a in aliases)
    alias_re = re.compile(r"\b(?:" + names + r")\b", re.IGNORECASE)
    invests_re = re.compile(r"(?i)\b(?:" + names + r")\b" + _ALIAS_INVESTS)
    invest_from_re = re.compile(r"(?i)\b(?:investment|purchase|financing|backing)\s+(?:from|by)\s+(?:" + names + r")\b")
    sentences = re.split(r"(?<=[.;])\s+(?=[A-Z(“\"])", section_text)
    best = None
    for s in sentences:
        letters = [c for c in s if c.isalpha()]
        if _BIO.search(s) or (letters and sum(c.isupper() for c in letters) > 0.6 * len(letters)):
            continue  # executive bio, or an all-caps legal disclaimer
        for m in alias_re.finditer(s):
            if _ALIAS_EXCLUDE.search(s[max(0, m.start() - 5):m.end() + 15]):
                continue
            if _PRODUCT_CONTEXT.search(s[m.end():m.end() + 40]) and not _DEAL_WORDS.search(s):
                continue
            sold_to = _SOLD_TO.search(s)
            invested = _SECURITIES.search(s) and (
                invests_re.search(s) or invest_from_re.search(s)
                or (sold_to and alias_re.search(s[sold_to.end():sold_to.end() + 80])))
            if invested:
                return {"relationship": "invested", "evidence": s[:500]}
            if _is_party(s, m) and _DEAL_WORDS.search(s) and best is None:
                best = {"relationship": "agreement", "evidence": s[:500]}
            break
    return best


_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(billion|million|thousand|bn|mm|m|b)?\b", re.IGNORECASE)
_SHARES_AT_PRICE = re.compile(
    r"(\d[\d,]{2,})\s+(?:shares|units)[^.;]{0,160}?(?:price|purchase\s+price|price\s+per\s+share)\s+of\s+"
    r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*per\s+(?:share|unit)", re.IGNORECASE)
_AMOUNT_CONTEXT = re.compile(
    r"\b(?:aggregate\s+purchase\s+price|gross\s+proceeds|purchase\s+price|investment\s+of|invest(?:ed)?\s+"
    r"(?:up\s+to\s+)?\$|for\s+(?:an\s+)?aggregate|total\s+consideration|commitment\s+of)\b", re.IGNORECASE)
_SCALE = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6, "thousand": 1e3}


def _money(num: str, unit: Optional[str]) -> float:
    return float(num.replace(",", "")) * _SCALE.get((unit or "").lower(), 1.0)


def extract_amount(section_text: str, aliases: List[str]) -> Optional[Dict]:
    """
    Pure function. Dollar size of the deal, from sentences that name the
    company or describe the purchase price: stated amounts ("$5.0 billion",
    "aggregate purchase price of $2,000,000,000") or shares x per-share
    price. Returns the largest plausible figure, with the sentence it
    came from; None if the filing states no amount.
    """
    alias_re = re.compile(r"\b(?:" + "|".join(re.escape(a) for a in aliases) + r")\b", re.IGNORECASE)
    best = None
    for s in re.split(r"(?<=[.;])\s+(?=[A-Z(“\"])", section_text):
        if not (alias_re.search(s) or _AMOUNT_CONTEXT.search(s)):
            continue
        # "$275 billion market", "$1.6 trillion opportunity" are market sizes, not deal sizes.
        if re.search(r"(?i)\b(?:market|tam|industry|opportunity|addressable|trillion|annually|per\s+year)\b", s) \
                and not _AMOUNT_CONTEXT.search(s):
            continue
        candidates = []
        for m in _SHARES_AT_PRICE.finditer(s):
            candidates.append(float(m.group(1).replace(",", "")) * float(m.group(2).replace(",", "")))
        if _AMOUNT_CONTEXT.search(s) or alias_re.search(s):
            for m in _MONEY.finditer(s):
                v = _money(m.group(1), m.group(2))
                # Per-share prices and par values aren't deal sizes.
                if v >= 1e6 and not re.match(r"\s*per\s+share", s[m.end():m.end() + 12], re.IGNORECASE):
                    candidates.append(v)
        for v in candidates:
            if v < 5e11 and (best is None or v > best["amount_usd"]):
                best = {"amount_usd": v, "amount_sentence": s[:400]}
    return best


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
                       session: requests.Session, explain: bool = True) -> List[Dict]:
    aliases = aliases_for(ticker, cik, session)
    query = " OR ".join(f'"{a}"' for a in aliases)
    candidates = {}
    for h in _fts(query, "8-K", start, end, session):
        if h["cik"].lstrip("0") == cik.lstrip("0"):
            continue
        items = set(h["items"])
        if DEAL_ITEMS & items and h["file_type"] == "8-K":
            candidates[h["adsh"]] = {**h, "kind": "filing"}  # formal items win over a press release
        elif ANNOUNCEMENT_ITEMS & items and (h["file_type"] or "").startswith("EX-99"):
            candidates.setdefault(h["adsh"], {**h, "kind": "press_release"})

    deals = []
    titles = sec_utils_titles(session)
    ordered = sorted(candidates.values(), key=lambda h: (h["kind"] != "filing", h["file_date"]), reverse=False)
    ordered = sorted(ordered[:MAX_COUNTERPARTY_DOCS], key=lambda h: h["file_date"], reverse=True)
    for h in ordered:
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
            # A press release has no Item headings — read its opening instead.
            sections = _item_sections(text) if h["kind"] == "filing" else re.sub(r"\s+", " ", text)[:8000]
            result = classify_counterparty(sections, aliases) or {}
            if result.get("relationship"):
                result.update(extract_amount(sections, aliases) or {})
            result["url"] = url
            db.cache_set("counterparty_doc", key, result)
        if not result.get("relationship"):
            continue
        m = _TICKER_RE.search(h["display_name"])
        cp_ticker = m.group(1) if m else None
        relationship = result["relationship"]
        if h["kind"] == "press_release" and relationship == "agreement":
            relationship = "announced"
        deals.append({
            "date": h["file_date"], "relationship": relationship, "source_kind": h["kind"],
            "company": re.sub(r"\s*\(.*$", "", h["display_name"]).strip(),
            "ticker": cp_ticker, "sic": h["sic"], "industry": titles.get(h["sic"] or "", None),
            "items": h["items"], "evidence": result["evidence"], "url": result["url"],
            "return_12m_pct": _ret(cp_ticker, h["file_date"], _plus_days(h["file_date"], 365)),
            "return_to_today_pct": _ret(cp_ticker, h["file_date"], pit.today()),
            "spy_12m_pct": _ret("SPY", h["file_date"], _plus_days(h["file_date"], 365)),
            "amount_usd": result.get("amount_usd"),
            "amount_sentence": result.get("amount_sentence"),
        })
    for d in deals:
        if d.get("amount_usd") and d["ticker"]:
            v = pit.valuation(d["ticker"], d["date"], session)
            if v.get("market_cap") and d["amount_usd"] > 3 * v["market_cap"] and d["relationship"] != "agreement":
                d["amount_usd"], d["amount_sentence"] = None, None  # implausible: likely a market size
        d["why"] = (explain_move(d["ticker"], d["date"], session, d["relationship"], d.get("amount_usd"))
                    if explain else None)
    return deals


def explain_move(ticker: Optional[str], start: str, session: requests.Session,
                 relationship: str = "", amount_usd: Optional[float] = None) -> Optional[Dict]:
    """
    Why did the counterparty's stock move after the deal? Splits the change
    in market value into (a) reported revenue change and (b) re-rating —
    the change in price/sales, i.e. what investors pay per dollar of sales
    — next to the market's move, the company's size at the time and the
    deal's size relative to it. The explanation is generated from these
    numbers by fixed rules, not written by a model.
    """
    if not ticker:
        return None
    end = min(_plus_days(start, 365), pit.today())
    r, spy = _ret(ticker, start, end), _ret("SPY", start, end)
    if r is None:
        return None
    v0, v1 = pit.valuation(ticker, start, session), pit.valuation(ticker, end, session)
    cik = sec_utils.get_cik_for_ticker(ticker, session)
    q_end = pit.quarterly_revenue_yoy(cik, end, session) if cik else None
    out = {"period_end": end, "return_pct": r, "spy_pct": spy,
           "market_cap_at_deal": v0.get("market_cap"), "latest_quarter_revenue_yoy_pct": q_end,
           "revenue_change_pct": None, "ps_start": None, "ps_end": None, "reasons": []}
    same_fy = v0.get("fiscal_year_end") and v0.get("fiscal_year_end") == v1.get("fiscal_year_end")
    if v0.get("sales_yield") and v1.get("sales_yield") and v0.get("market_cap") and v1.get("market_cap"):
        rev0 = v0["sales_yield"] * v0["market_cap"]
        rev1 = v1["sales_yield"] * v1["market_cap"]
        # Same fiscal year at both dates = no new annual results yet, so a
        # "revenue change" of 0% would be an artifact, not a fact.
        if not same_fy:
            out["revenue_change_pct"] = round((rev1 / rev0 - 1) * 100, 1) if rev0 else None
        out["ps_start"], out["ps_end"] = round(1 / v0["sales_yield"], 1), round(1 / v1["sales_yield"], 1)
    reasons = out["reasons"]

    if spy is not None:
        excess = r - spy
        reasons.append(f"The S&P 500 moved {spy:+.0f}% over the same period, so the stock did "
                       f"{abs(excess):.0f} points {'better' if excess >= 0 else 'worse'} than the market.")
    if same_fy and out["ps_start"] and out["ps_end"]:
        reasons.append(f"No new annual results came out in this window, so the move is investors re-pricing "
                       f"the same reported sales: price/sales {out['ps_start']}x → {out['ps_end']}x"
                       + (f", alongside {q_end:+.0f}% year-over-year growth in its latest quarter."
                          if q_end is not None else "."))
    elif out["revenue_change_pct"] is not None and out["ps_start"]:
        rev_log = math.log1p(out["revenue_change_pct"] / 100) if out["revenue_change_pct"] > -100 else -9
        ps_log = math.log(out["ps_end"] / out["ps_start"]) if out["ps_end"] and out["ps_start"] else 0
        driver = ("re-rating — investors paid more per dollar of sales" if ps_log > 0 else
                  "de-rating — investors paid less per dollar of sales")
        if abs(ps_log) > abs(rev_log):
            reasons.append(f"Mostly {driver}: price/sales went from {out['ps_start']}x to {out['ps_end']}x, "
                           f"while reported annual revenue changed {out['revenue_change_pct']:+.0f}%.")
        else:
            reasons.append(f"Mostly the business itself: reported annual revenue changed "
                           f"{out['revenue_change_pct']:+.0f}% (price/sales {out['ps_start']}x → {out['ps_end']}x).")
    if q_end is not None and not same_fy:
        reasons.append(f"Its latest reported quarter had revenue {q_end:+.0f}% vs a year earlier.")
    e0, e1 = v0.get("earnings_yield"), v1.get("earnings_yield")
    if e0 is not None and e1 is not None and (e0 < 0) != (e1 < 0):
        reasons.append("It went from losing money to profitable." if e1 > 0
                       else "It went from profitable to losing money.")
    mcap = v0.get("market_cap")
    if mcap:
        size = (f"${mcap / 1e9:,.1f}B" if mcap >= 1e9 else f"${mcap / 1e6:,.0f}M" if mcap >= 1e6
                else "under $1M")
        if amount_usd:
            reasons.append(f"The deal (${amount_usd / 1e9:,.2f}B) was {amount_usd / mcap * 100:.1f}% of its "
                           f"{size} market value at the time." if amount_usd >= 1e9 else
                           f"The deal (${amount_usd / 1e6:,.0f}M) was {amount_usd / mcap * 100:.1f}% of its "
                           f"{size} market value at the time.")
        if amount_usd and relationship in ("agreement", "announced") and amount_usd / mcap > 0.25:
            reasons.append("A commitment that large relative to the company's own size usually has to be "
                           "financed by issuing shares or taking on debt, which tends to weigh on the stock.")
        if mcap < 2e9 and relationship in ("agreement", "announced"):
            reasons.append(f"Small company ({size}) announcing an agreement with a giant: these "
                           f"announcements often spike on the news and fade as the deal turns out "
                           f"small or slow to produce revenue.")
    return out


def deal_patterns(deals: List[Dict]) -> Dict:
    """
    Pure function. Average 12-month return vs the S&P 500 grouped by deal
    type and by the counterparty's size at the time — which kinds of deals
    were followed by gains, and which by losses.
    """
    def summarize(rows):
        xs = [d["return_12m_pct"] - d["spy_12m_pct"] for d in rows
              if d.get("return_12m_pct") is not None and d.get("spy_12m_pct") is not None]
        return {"deals": len(rows), "with_returns": len(xs),
                "avg_vs_spy_pct": round(sum(xs) / len(xs), 1) if xs else None,
                "share_beating_spy_pct": round(sum(1 for x in xs if x > 0) / len(xs) * 100) if xs else None}

    def size(d):
        m = (d.get("why") or {}).get("market_cap_at_deal")
        return None if m is None else "under $2B" if m < 2e9 else "$2–20B" if m < 2e10 else "over $20B"

    by_type = {k: summarize([d for d in deals if d["relationship"] == k])
               for k in ("invested", "agreement", "announced")}
    by_size = {k: summarize([d for d in deals if size(d) == k]) for k in ("under $2B", "$2–20B", "over $20B")}
    notes = []
    inv, agr = by_type["invested"], by_type["agreement"]
    if inv["avg_vs_spy_pct"] is not None and agr["avg_vs_spy_pct"] is not None:
        notes.append(f"Companies it invested in averaged {inv['avg_vs_spy_pct']:+.0f} pts vs the S&P 500 over "
                     f"12 months; companies announcing agreements averaged {agr['avg_vs_spy_pct']:+.0f} pts.")
    small = by_size["under $2B"]
    if small["avg_vs_spy_pct"] is not None and small["with_returns"] >= 2:
        notes.append(f"Small counterparties (under $2B) averaged {small['avg_vs_spy_pct']:+.0f} pts across "
                     f"{small['with_returns']} deals. An investment means the giant put its own money in; an "
                     f"\"agreement\" announced by a small company is often a customer or partner program "
                     f"that gets a pop on the headline and fades.")
    return {"by_type": by_type, "by_size": by_size, "notes": notes}


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
        "counterparty_deals": (deals := counterparty_deals(ticker, cik, filing_date, end, session)),
        "deal_patterns": deal_patterns(deals),
        "own_deals": own_deals(cik, filing_date, end, session),
        "thirteen_f": thirteen_f_changes(cik, filing_date, end, session),
        "disclosed": disclosed_responses(cik, filing_date, end, session),
        "capex": capex_change(cik, filing_date, session),
    }
    db.cache_set("aftermath", cache_key, result)
    return result
