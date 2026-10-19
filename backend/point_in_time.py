# backend/point_in_time.py
"""
"What was publicly known on date X?" — the data layer behind the backtest
AND the live score's valuation factor, so both use identical definitions.

Every accessor takes an `as_of` date (YYYY-MM-DD) and only uses:
- SEC XBRL facts whose `filed` date is on or before as_of (a fact for
  fiscal 2023 filed in Feb 2024 is invisible on 2024-01-15), taking the
  latest version filed by then — so later restatements don't leak back;
- filings (10-K, 8-K) filed on or before as_of;
- prices on or before as_of.

Live scoring just calls the same functions with as_of = today.
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests

from . import db, sec_utils
from .capex_pipeline import CAPEX_TAGS, _cached_companyfacts
from sec_financial_data import NET_INCOME_TAGS, REVENUE_TAGS

OPERATING_CASH_FLOW_TAGS = ["NetCashProvidedByUsedInOperatingActivities"]


def today() -> str:
    return date.today().isoformat()


def _days(a: str, b: str) -> int:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days


# =============================================================================
# Filings (full history — SEC's "recent" window only reaches back ~1,000
# filings, which for an active filer can be as little as 5-6 years)
# =============================================================================

def all_filings(cik: str, session: requests.Session) -> List[Dict]:
    """Every filing for a CIK (recent window + older paginated pages), newest first."""
    cached = db.cache_get("all_filings", cik, ttl_seconds=12 * 3600)
    if cached is not None:
        return cached

    try:
        resp = sec_utils._polite_get(session, sec_utils.SUBMISSIONS_URL.format(cik=cik))
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    blocks = [data.get("filings", {}).get("recent", {})]
    for page in data.get("filings", {}).get("files", []):
        try:
            r = sec_utils._polite_get(session, f"https://data.sec.gov/submissions/{page['name']}")
            r.raise_for_status()
            blocks.append(r.json())
        except (requests.RequestException, ValueError, KeyError):
            continue

    filings = []
    for b in blocks:
        for i, form in enumerate(b.get("form", [])):
            filings.append({
                "form": form,
                "filing_date": b["filingDate"][i],
                "report_date": (b.get("reportDate") or [""] * (i + 1))[i],
                "accession_number": b["accessionNumber"][i].replace("-", ""),
                "primary_document": b["primaryDocument"][i],
                "items": (b.get("items") or [""] * (i + 1))[i] or "",
            })
    filings.sort(key=lambda f: f["filing_date"], reverse=True)
    db.cache_set("all_filings", cik, filings)
    return filings


def latest_10k(cik: str, as_of: str, session: requests.Session) -> Optional[Dict]:
    """Most recent original 10-K filed on or before as_of."""
    for f in all_filings(cik, session):
        if f["form"] == "10-K" and f["filing_date"] <= as_of:
            return f
    return None


def latest_periodic(cik: str, as_of: str, session: requests.Session) -> Optional[Dict]:
    """Most recent original 10-K or 10-Q filed on or before as_of (quarterly freshness)."""
    for f in all_filings(cik, session):
        if f["form"] in ("10-K", "10-Q") and f["filing_date"] <= as_of:
            return f
    return None


def item_101_8ks(cik: str, start: str, end: str, session: requests.Session) -> List[Dict]:
    """8-Ks reporting Item 1.01 filed in (start, end] — no document fetch needed to filter."""
    return [f for f in all_filings(cik, session)
            if f["form"] == "8-K" and start < f["filing_date"] <= end
            and "1.01" in f["items"].split(",")]


# =============================================================================
# XBRL facts as of a date
# =============================================================================

def _us_gaap(cik: str, session: requests.Session) -> Dict:
    return _cached_companyfacts(cik, session).get("facts", {}).get("us-gaap", {})


def _known_facts(facts: List[Dict], as_of: str) -> Dict[Tuple[str, str], Dict]:
    """
    {(start, end): fact} for facts filed by as_of, keeping the most
    recently filed version of each period (what an investor would have
    seen on that date, restatements included only once filed).
    """
    known: Dict[Tuple[str, str], Dict] = {}
    for f in facts:
        if f.get("filed", "9999") > as_of or not f.get("end"):
            continue
        key = (f.get("start", ""), f["end"])
        if key not in known or f["filed"] > known[key]["filed"]:
            known[key] = f
    return known


def annual_series(cik: str, tags: List[str], as_of: str,
                  session: requests.Session) -> List[Dict]:
    """
    Full-fiscal-year values known on as_of, oldest first, from whichever
    tag in `tags` has the most recent fiscal year (companies switch tags;
    see capex_pipeline._annual_series_for_tags).
    """
    us_gaap = _us_gaap(cik, session)
    best: List[Dict] = []
    for tag in tags:
        facts = us_gaap.get(tag, {}).get("units", {}).get("USD", [])
        annual = [f for (start, end), f in _known_facts(facts, as_of).items()
                  if start and 300 <= _days(start, end) <= 400]
        annual.sort(key=lambda f: f["end"])
        # One value per fiscal year end.
        dedup = {f["end"]: f for f in annual}
        annual = [dedup[e] for e in sorted(dedup)]
        if annual and (not best or annual[-1]["end"] > best[-1]["end"]):
            best = annual
    return best


def annual_value(cik: str, tags: List[str], as_of: str,
                 session: requests.Session) -> Optional[Dict]:
    series = annual_series(cik, tags, as_of, session)
    return series[-1] if series else None


def capex_yoy_growth(cik: str, as_of: str, session: requests.Session) -> Optional[float]:
    """Latest fiscal year's CapEx growth known on as_of (same tags as the live CapEx tier)."""
    series = annual_series(cik, CAPEX_TAGS, as_of, session)
    if len(series) < 2 or not series[-2]["val"]:
        return None
    if not 300 <= _days(series[-2]["end"], series[-1]["end"]) <= 400:
        return None  # gap in the series — not a like-for-like comparison
    return round((series[-1]["val"] - series[-2]["val"]) / abs(series[-2]["val"]) * 100, 1)


def quarterly_revenue_yoy(cik: str, as_of: str, session: requests.Session) -> Optional[float]:
    """
    Latest reported quarter's revenue vs the same quarter a year earlier,
    using only 10-Q/10-K facts filed by as_of. Fiscal Q4 usually isn't
    tagged as a standalone quarter, so in the weeks after a 10-K this
    reflects Q3 — the same lag an investor reading filings would have.
    """
    us_gaap = _us_gaap(cik, session)
    best: Optional[float] = None
    best_end = ""
    for tag in REVENUE_TAGS:
        facts = us_gaap.get(tag, {}).get("units", {}).get("USD", [])
        quarters = {end: f["val"] for (start, end), f in _known_facts(facts, as_of).items()
                    if start and 80 <= _days(start, end) <= 100}
        if not quarters:
            continue
        latest_end = max(quarters)
        if latest_end <= best_end:
            continue
        prior = [e for e in quarters if 350 <= _days(e, latest_end) <= 380]
        if prior and quarters[prior[0]]:
            best = round((quarters[latest_end] - quarters[prior[0]]) / abs(quarters[prior[0]]) * 100, 1)
            best_end = latest_end
    return best


def shares_outstanding(cik: str, as_of: str, session: requests.Session) -> Optional[Dict]:
    """
    {'shares', 'end'} — shares outstanding from the latest filing by as_of,
    and the date that count is as of (needed to line it up with
    split-adjusted prices). Tries, in order: cover-page dei count (multi-
    class companies report one value per class on the same filing, summed),
    balance-sheet CommonStockSharesOutstanding, diluted weighted average.
    Alphabet, for one, reports no dei count at all.
    """
    all_facts = _cached_companyfacts(cik, session).get("facts", {})
    sources = [
        all_facts.get("dei", {}).get("EntityCommonStockSharesOutstanding", {}),
        all_facts.get("us-gaap", {}).get("CommonStockSharesOutstanding", {}),
        all_facts.get("us-gaap", {}).get("WeightedAverageNumberOfDilutedSharesOutstanding", {}),
    ]
    for source in sources:
        known = [f for f in source.get("units", {}).get("shares", [])
                 if f.get("filed", "9999") <= as_of and f.get("val")]
        if not known:
            continue
        latest = max(known, key=lambda f: (f["filed"], f["end"]))
        same = [f for f in known if f["accn"] == latest["accn"] and f["end"] == latest["end"]
                and f.get("start") == latest.get("start")]
        return {"shares": float(sum(f["val"] for f in same)), "end": latest["end"]}
    return None


# =============================================================================
# Prices
# =============================================================================

def _price_data(ticker: str) -> Dict:
    """
    {'bars': {date: {'close', 'adj_close', 'volume'}}, 'splits': [[date, ratio]]}
    from yfinance, daily since 2015, cached for a day.
    - close: split-adjusted only — for market cap (with split_factor_after)
    - adj_close: split + dividend adjusted — for returns (total return)
    """
    cached = db.cache_get("price_history_v2", ticker, ttl_seconds=20 * 3600)
    if cached is not None:
        return cached
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        hist = tk.history(start="2015-01-01", interval="1d", auto_adjust=False)
        splits = [[d.strftime("%Y-%m-%d"), float(r)] for d, r in tk.splits.items()]
    except Exception:
        return {"bars": {}, "splits": []}
    if hist is None or hist.empty:
        out = {"bars": {}, "splits": []}
    else:
        out = {"bars": {
            idx.strftime("%Y-%m-%d"): {"close": float(row["Close"]),
                                       "adj_close": float(row["Adj Close"]),
                                       "volume": float(row["Volume"])}
            for idx, row in hist.iterrows()
            if row["Close"] == row["Close"] and row["Adj Close"] == row["Adj Close"]
        }, "splits": splits}
    db.cache_set("price_history_v2", ticker, out)
    return out


def price_history(ticker: str) -> Dict[str, Dict[str, float]]:
    return _price_data(ticker)["bars"]


def split_factor_after(ticker: str, since: str) -> float:
    """Product of split ratios after `since` — converts a share count reported
    on that date to the same basis as yfinance's split-adjusted prices."""
    factor = 1.0
    for d, ratio in _price_data(ticker)["splits"]:
        if d > since:
            factor *= ratio
    return factor


def _dates_upto(hist: Dict, as_of: str) -> List[str]:
    return sorted(d for d in hist if d <= as_of)


def price_on(ticker: str, as_of: str, max_staleness_days: int = 7,
             field: str = "adj_close") -> Optional[float]:
    hist = price_history(ticker)
    dates = _dates_upto(hist, as_of)
    if not dates or _days(dates[-1], as_of) > max_staleness_days:
        return None
    return hist[dates[-1]][field]


def technicals(ticker: str, as_of: str) -> Dict:
    """Relative volume and 200-day SMA position on as_of — same rules as market_screener."""
    hist = price_history(ticker)
    dates = _dates_upto(hist, as_of)
    out = {"relative_volume": None, "above_200sma": None, "price": None}
    if not dates or _days(dates[-1], as_of) > 7:
        return out
    closes = [hist[d]["adj_close"] for d in dates]
    out["price"] = closes[-1]
    if len(closes) >= 200:
        out["above_200sma"] = closes[-1] > sum(closes[-200:]) / 200
    if len(dates) >= 21:
        avg = sum(hist[d]["volume"] for d in dates[-21:-1]) / 20
        if avg > 0:
            out["relative_volume"] = round(hist[dates[-1]]["volume"] / avg, 2)
    return out


def forward_return(ticker: str, start: str, months: int) -> Optional[float]:
    """Total return from the close on/before `start` to the close ~`months` later."""
    p0 = price_on(ticker, start)
    end = (datetime.fromisoformat(start) + timedelta(days=round(months * 30.44))).date().isoformat()
    if end > today():
        return None
    p1 = price_on(ticker, end)
    if not p0 or not p1:
        return None
    return p1 / p0 - 1


# =============================================================================
# Valuation
# =============================================================================

def valuation(ticker: str, as_of: str, session: requests.Session) -> Dict:
    """
    Market cap from price x shares outstanding, against the latest fiscal
    year known on as_of. Yields (E/P, S/P, FCF/P) rather than multiples so
    "higher = cheaper" holds and loss-makers stay on the same scale
    (negative earnings -> negative yield, not an undefined P/E).
    """
    out = {"market_cap": None, "earnings_yield": None, "sales_yield": None,
           "fcf_yield": None, "revenue_growth_annual": None, "growth_adjusted_sales_yield": None,
           "fiscal_year_end": None}
    cik = sec_utils.get_cik_for_ticker(ticker, session)
    price = price_on(ticker, as_of, field="close")
    if not cik or not price:
        return out
    shares = shares_outstanding(cik, as_of, session)
    if not shares:
        return out
    mcap = price * shares["shares"] * split_factor_after(ticker, shares["end"])
    out["market_cap"] = mcap

    revenue = annual_series(cik, REVENUE_TAGS, as_of, session)
    if revenue:
        fy_end = revenue[-1]["end"]
        out["fiscal_year_end"] = fy_end
        out["sales_yield"] = round(revenue[-1]["val"] / mcap, 4)
        if len(revenue) >= 2 and revenue[-2]["val"] and 300 <= _days(revenue[-2]["end"], fy_end) <= 400:
            growth = (revenue[-1]["val"] - revenue[-2]["val"]) / abs(revenue[-2]["val"])
            out["revenue_growth_annual"] = round(growth * 100, 1)
            # Sales yield per point of growth: a high-growth company "earns"
            # a lower yield. Only meaningful for growing companies.
            if growth > 0:
                out["growth_adjusted_sales_yield"] = round(out["sales_yield"] * growth * 100, 4)

        def _same_year(tags):
            v = annual_value(cik, tags, as_of, session)
            return v["val"] if v and v["end"] == fy_end else None

        net_income = _same_year(NET_INCOME_TAGS)
        if net_income is not None:
            out["earnings_yield"] = round(net_income / mcap, 4)
        ocf, capex = _same_year(OPERATING_CASH_FLOW_TAGS), _same_year(CAPEX_TAGS)
        if ocf is not None:
            out["fcf_yield"] = round((ocf - (capex or 0)) / mcap, 4)
    return out
