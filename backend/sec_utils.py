# backend/sec_utils.py
"""
Small, dependency-light SEC EDGAR helpers for the backend.

Deliberately NOT reusing SEC10KAnalyzerOllama from SEC10K.py for this: that
class's constructor spins up OllamaInterface, which pings Ollama and — on
Windows, if Ollama isn't running — prints instructions and calls
`sys.exit(1)`. That's a reasonable thing for a CLI script the user is
watching to do; it would be a disaster inside a FastAPI background worker,
since it would kill the entire backend process the next time someone
triggers a scan without Ollama running. So this module only ever does
plain SEC data fetching, with its own session, and never touches Ollama.

Every network call here is cached through backend.db so re-running the
scanner doesn't re-hit SEC for data that hasn't changed.
"""

import re
import time
from typing import Dict, List, Optional

import requests
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from . import db

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# SEC asks every requester to identify themselves with a real contact so
# they can reach out if a client is misbehaving instead of just blocking
# it. Change the email below if this isn't the right contact.
USER_AGENT = "SEC10K-Analyzer-BottleneckScanner/1.0 (milesbrown1102@gmail.com)"

_MIN_REQUEST_INTERVAL = 0.15  # be a good citizen; SEC rate-limits aggressively


def make_sec_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    })
    return session


def _polite_get(session: requests.Session, url: str, timeout: int = 20) -> requests.Response:
    resp = session.get(url, timeout=timeout)
    time.sleep(_MIN_REQUEST_INTERVAL)
    return resp


def get_ticker_lookup(session: requests.Session) -> List[Dict]:
    cached = db.cache_get("ticker_lookup", "all", ttl_seconds=24 * 3600)
    if cached is not None:
        return cached

    resp = _polite_get(session, TICKERS_URL, timeout=15)
    resp.raise_for_status()
    data = list(resp.json().values())
    db.cache_set("ticker_lookup", "all", data)
    return data


def get_cik_for_ticker(ticker: str, session: requests.Session) -> Optional[str]:
    ticker_up = ticker.strip().upper()
    cached = db.cache_get("cik_lookup", ticker_up, ttl_seconds=7 * 24 * 3600)
    if cached is not None:
        return cached

    try:
        lookup = get_ticker_lookup(session)
    except requests.RequestException:
        return None

    for row in lookup:
        if row["ticker"].upper() == ticker_up:
            cik = str(row["cik_str"]).zfill(10)
            db.cache_set("cik_lookup", ticker_up, cik)
            return cik
    return None


def get_recent_10k_filing(cik: str, session: requests.Session) -> Optional[Dict]:
    # "_v2" namespace: entries cached before amendments were deprioritized
    # may point at a Part-III-only 10-K/A.
    cached = db.cache_get("recent_10k_v2", cik, ttl_seconds=24 * 3600)
    if cached is not None:
        return cached

    url = SUBMISSIONS_URL.format(cik=cik)
    try:
        resp = _polite_get(session, url)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    # Prefer the original 10-K: a 10-K/A filed afterwards is usually just
    # Part III (executive pay, directors) with no Business / Risk Factors /
    # MD&A — Tesla files one every April. Fall back to an amendment only
    # if there's no original 10-K in the window at all.
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    for wanted in ("10-K", "10-K/A"):
        for i in range(len(forms)):
            if forms[i] == wanted:
                filing = {
                    "form": forms[i],
                    "filing_date": recent["filingDate"][i],
                    "accession_number": recent["accessionNumber"][i].replace("-", ""),
                    "primary_document": recent["primaryDocument"][i],
                }
                db.cache_set("recent_10k_v2", cik, filing)
                return filing
    return None


def get_historical_10k_filings(cik: str, session: requests.Session,
                                max_filings: int = 6) -> List[Dict]:
    """
    Like get_recent_10k_filing, but returns up to `max_filings` past 10-Ks
    (oldest to newest never assumed — caller sorts) instead of just the
    latest one. Used for the multi-year "trend" view (Pass 3), so an older
    signal-vs-time question like "when did this bottleneck language start
    showing up in the filings" can actually be answered.

    Reads from the same submissions.json 'recent' window everything else
    here uses, which SEC keeps a healthy number of years of for any filer
    that's still active — for a long-lived mega-cap this comfortably covers
    6+ annual reports. It does NOT walk the older, paginated
    'filings.files' index some very long-lived filers have, since that
    would mean extra network calls for a feature this is meant to keep
    lightweight; if a ticker has fewer than max_filings 10-Ks in the recent
    window, this just returns what's there.
    """
    cache_key = f"{cik}_{max_filings}"
    cached = db.cache_get("historical_10ks_v2", cache_key, ttl_seconds=24 * 3600)
    if cached is not None:
        return cached

    url = SUBMISSIONS_URL.format(cik=cik)
    try:
        resp = _polite_get(session, url)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    recent = data.get("filings", {}).get("recent", {})
    filings = []
    for i in range(len(recent.get("form", []))):
        # Originals only — amendments would duplicate a year with a
        # Part-III-only document (see get_recent_10k_filing).
        if recent["form"][i] == "10-K":
            filings.append({
                "form": recent["form"][i],
                "filing_date": recent["filingDate"][i],
                "accession_number": recent["accessionNumber"][i].replace("-", ""),
                "primary_document": recent["primaryDocument"][i],
            })
        if len(filings) >= max_filings:
            break

    db.cache_set("historical_10ks_v2", cache_key, filings)
    return filings


def get_recent_8k_filings(cik: str, session: requests.Session,
                           max_filings: int = 6) -> List[Dict]:
    """Same idea as get_historical_10k_filings, for 8-Ks (deal monitor)."""
    cache_key = f"{cik}_{max_filings}"
    cached = db.cache_get("recent_8ks", cache_key, ttl_seconds=6 * 3600)
    if cached is not None:
        return cached

    url = SUBMISSIONS_URL.format(cik=cik)
    try:
        resp = _polite_get(session, url)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    recent = data.get("filings", {}).get("recent", {})
    filings = []
    for i in range(len(recent.get("form", []))):
        if recent["form"][i] == "8-K":
            filings.append({
                "form": recent["form"][i],
                "filing_date": recent["filingDate"][i],
                "accession_number": recent["accessionNumber"][i].replace("-", ""),
                "primary_document": recent["primaryDocument"][i],
            })
        if len(filings) >= max_filings:
            break

    db.cache_set("recent_8ks", cache_key, filings)
    return filings


def get_filing_document_url(cik: str, filing: Dict) -> str:
    acc = filing["accession_number"]
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
        f"{acc}/{filing['primary_document']}"
    )


def fetch_filing_text(cik: str, filing: Dict, session: requests.Session) -> Optional[str]:
    """
    Fetch + clean a 10-K's text, cached indefinitely (a filed 10-K never
    changes) so this is only ever downloaded once per company.
    """
    cache_key = f"{cik}_{filing['accession_number']}"
    # "_v2": text cached before html_to_text existed has words split
    # across inline-XBRL spans ("i nvestment").
    cached = db.cache_get("filing_text_v2", cache_key, ttl_seconds=None)
    if cached is not None:
        return cached

    url = get_filing_document_url(cik, filing)
    try:
        resp = _polite_get(session, url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    text = html_to_text(resp.text)
    db.cache_set("filing_text_v2", cache_key, text)
    return text


# Inline-XBRL filings are XHTML; lxml's HTML parser handles them fine.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_BLOCK_TAGS = ["p", "div", "br", "tr", "li", "table", "section",
               "h1", "h2", "h3", "h4", "h5", "h6"]


def html_to_text(html: str) -> str:
    """
    Filing HTML -> plain text with line breaks only at block boundaries.
    get_text("\n") would also break between inline tags, and inline-XBRL
    filings split single words across <span>s, so words came out broken
    ("i nvestment") and regexes silently missed them.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except ValueError:
        # Some filer-made press releases have malformed namespaced
        # attributes that lxml rejects; the stdlib parser tolerates them.
        soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")
    for tag in soup.find_all(["td", "th"]):
        tag.append(" ")

    text = soup.get_text()
    text = re.sub(r"[ \t\xa0\u2009\u200b]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text)
