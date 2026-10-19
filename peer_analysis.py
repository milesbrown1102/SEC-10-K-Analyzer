# peer_analysis.py
"""
Dynamic competitor / peer discovery for ANY company — not just a hardcoded
shortlist of three tickers.

Strategy, in order:
1. Curated fast-path for a handful of extremely well-known tickers where a
   hand-written comparison reads better than a generated one.
2. LLM-assisted extraction: ask the local Ollama model (already wired into
   this app) to read the filing's own Business and Risk Factors sections —
   10-Ks frequently name competitors directly ("we compete with X, Y and
   Z") — and name up to 4 direct public competitors with tickers and a
   one-line reason each.
3. Regex fallback: scan for "compete with ...", "competitors include ...",
   "principal competitors are ..." patterns directly, in case the LLM step
   is unavailable (e.g. Ollama not running) or returns nothing usable.

Every candidate name is validated against SEC's official
company_tickers.json before it's shown, so the UI never displays a
ticker that doesn't actually exist.
"""

import json
import re
from typing import Dict, List, Optional, Tuple

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Fast-path overrides for a handful of extremely well known names. Everything
# else goes through dynamic discovery below, so coverage isn't limited to
# whatever tickers happen to be hardcoded here.
CURATED_PEERS: Dict[str, Dict] = {
    "NVDA": {
        "peers": ["AMD", "INTC", "QCOM"],
        "reasons": {
            "AMD": "Direct GPU competitor in gaming and data center markets",
            "INTC": "Competing in AI accelerators and data center processors",
            "QCOM": "Edge AI and mobile compute platform competition",
        },
    },
    "AAPL": {
        "peers": ["MSFT", "GOOGL", "META"],
        "reasons": {
            "MSFT": "Hardware (Surface vs Mac) and services competition",
            "GOOGL": "Mobile OS (iOS vs Android) and services ecosystem",
            "META": "VR/AR hardware (Vision Pro vs Quest) competition",
        },
    },
    "MSFT": {
        "peers": ["GOOGL", "AMZN", "ORCL"],
        "reasons": {
            "GOOGL": "Cloud (Azure vs GCP) and productivity suite competition",
            "AMZN": "Leading cloud competitor with AWS",
            "ORCL": "Enterprise software and database competition",
        },
    },
}


def _load_ticker_lookup(session: requests.Session) -> List[Dict]:
    """Raw list of {ticker, title, cik_str} dicts from SEC's official file."""
    resp = session.get(TICKERS_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return list(data.values())


def resolve_ticker(name: str, ticker_lookup: List[Dict]) -> Optional[str]:
    """Best-effort match of a free-text company name (or a ticker) to a real ticker."""
    if not name:
        return None

    upper = name.strip().upper()
    for row in ticker_lookup:
        if row["ticker"].upper() == upper:
            return row["ticker"]

    name_clean = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    name_words = [w for w in name_clean.split() if len(w) > 2]
    if not name_words:
        return None

    best, best_score = None, 0
    for row in ticker_lookup:
        title_clean = re.sub(r"[^a-z0-9 ]", "", row["title"].lower())
        score = sum(1 for w in name_words if w in title_clean)
        if score > best_score:
            best_score = score
            best = row["ticker"]
    return best if best_score > 0 else None


def extract_peers_with_llm(
    company: str, business_text: str, risk_text: str, llm_interface
) -> List[Tuple[str, str]]:
    """Ask the local LLM to name direct competitors. Returns [(ticker_or_name, reason), ...]."""
    if not llm_interface or not (business_text or risk_text):
        return []

    excerpt = (business_text[:3000] + "\n" + risk_text[:1500]).strip()
    messages = [
        {
            "role": "system",
            "content": (
                "You are a financial analyst. Respond with ONLY valid JSON, "
                "no prose, no markdown fences."
            ),
        },
        {
            "role": "user",
            "content": f"""Read this excerpt from {company}'s SEC 10-K filing and
identify up to 4 direct, publicly-traded competitors it names or clearly implies.

Excerpt:
{excerpt}

Respond with ONLY a JSON array like this, nothing else:
[{{"ticker": "XXXX", "reason": "one short sentence on the competitive overlap"}}, ...]

If you cannot confidently identify any public competitors, respond with [].""",
        },
    ]

    try:
        response = llm_interface.chat(messages, max_tokens=400, temperature=0.1)
    except Exception:
        return []

    if not response:
        return []

    # Be forgiving in case the model wraps the JSON in prose or fences.
    match = re.search(r"\[.*\]", response, re.DOTALL)
    if not match:
        return []

    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return []

    out = []
    for item in parsed:
        if isinstance(item, dict) and item.get("ticker"):
            out.append((str(item["ticker"]).strip(), str(item.get("reason", "")).strip()))
    return out


def extract_peers_with_regex(business_text: str) -> List[str]:
    """Fallback: pull raw names out of 'we compete with X, Y and Z'-style sentences."""
    if not business_text:
        return []

    patterns = [
        r"(?:principal\s+)?competitors?\s+(?:include|are|such as)\s+([^.]{5,150})",
        r"compete\s+with\s+([^.]{5,150})",
        r"competition\s+from\s+([^.]{5,150})",
    ]

    names = []
    for pattern in patterns:
        for m in re.finditer(pattern, business_text, re.IGNORECASE):
            chunk = m.group(1)
            parts = re.split(r",|\band\b", chunk)
            for part in parts:
                part = part.strip(" .")
                if 2 < len(part) < 40 and not part.lower().startswith(
                    ("other", "various", "many", "numerous")
                ):
                    names.append(part)

    seen, out = set(), []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out[:8]


def get_peer_companies(
    company: str,
    sections: Dict[str, str],
    session: requests.Session,
    llm_interface=None,
) -> Dict:
    """
    Main entry point.

    Returns {'peers': [tickers...], 'reasons': {ticker: reason}, 'method': str}
    where method is one of 'curated', 'llm', 'regex', or 'none'. Works for any
    company, unlike the old 3-ticker hardcoded mapping.
    """
    ticker = company.strip().upper()

    if ticker in CURATED_PEERS:
        result = {
            "peers": list(CURATED_PEERS[ticker]["peers"]),
            "reasons": dict(CURATED_PEERS[ticker]["reasons"]),
        }
        result["method"] = "curated"
        return result

    business_text = sections.get("business", "") or sections.get("item_1", "")
    risk_text = sections.get("risk_factors", "") or sections.get("item_1a", "")

    llm_candidates = extract_peers_with_llm(company, business_text, risk_text, llm_interface)
    candidate_names = [name for name, _ in llm_candidates]
    reasons_by_name = {name: reason for name, reason in llm_candidates if reason}
    method = "llm" if candidate_names else None

    if not candidate_names:
        candidate_names = extract_peers_with_regex(business_text)
        method = "regex" if candidate_names else None

    if not candidate_names:
        return {"peers": [], "reasons": {}, "method": "none"}

    try:
        ticker_lookup = _load_ticker_lookup(session)
    except Exception:
        # Can't validate candidate names into real tickers right now — don't
        # show unverified names/links in the UI.
        return {"peers": [], "reasons": {}, "method": "none"}

    resolved_peers: List[str] = []
    reasons: Dict[str, str] = {}
    for name in candidate_names:
        resolved = resolve_ticker(name, ticker_lookup)
        if resolved and resolved != ticker and resolved not in resolved_peers:
            resolved_peers.append(resolved)
            reasons[resolved] = reasons_by_name.get(
                name, f"Identified as a competitor in {company}'s own 10-K filing"
            )
        if len(resolved_peers) >= 4:
            break

    if not resolved_peers:
        return {"peers": [], "reasons": {}, "method": "none"}

    return {"peers": resolved_peers, "reasons": reasons, "method": method or "regex"}
