# backend/bottleneck_detector.py
"""
Tier 2 of the playbook: isolate technical bottleneck keywords.

Scans the Business, Risk Factors and MD&A sections of each mega-cap's latest 10-K
for language that signals an infrastructure/component constraint —
the playbook's own examples ("unprecedented supply constraints...",
"material backlogs for critical deployment components...", etc.) —
and scores + extracts evidence for each hit.

This reuses universal_section_extractor.extract_all_sections, the same
section-splitting module the main Streamlit app already relies on, so
section quality is consistent across both features.
"""

import re
import time
from typing import Dict, List

import requests

from universal_section_extractor import extract_all_sections
from . import db, sec_utils

# How it works: a sentence counts toward a category when it contains BOTH a
# constraint cue (shortage, constrained, limited number of suppliers, lead
# times, ...) AND one of that category's subject terms (GPUs, power, ...).
# Matching the two independently — instead of exact phrases — is what makes
# this hold up against real filing language, e.g. Alphabet's "Our ability to
# scale our technical infrastructure is increasingly constrained by the
# availability of power, water, and land" or Amazon's "we rely on a limited
# group of suppliers for semiconductor products ... such as graphics
# processing units". Requiring a subject term is also what keeps out
# boilerplate like "resource constraints" in the internal-controls section.
CONSTRAINT_CUES = re.compile(
    r"\b(?:constrain(?:ed|ts?|ing)?"
    r"|shortages?"
    r"|scarc(?:e|ity)"
    r"|bottlenecks?"
    r"|backlogs?"
    r"|lead[\s-]+times?"
    r"|long[\s-]+lead"
    r"|limited\s+(?:availability|supply|capacity|number\s+of|group\s+of|set\s+of)"
    r"|limitations?\s+(?:in|on)\s+(?:the\s+)?(?:availability|supply|capacity)"
    r"|(?:small|limited)\s+number\s+of\s+(?:qualified\s+)?(?:suppliers|manufacturers|vendors|sources)"
    r"|(?:single|sole|limited)[\s-]+sourc(?:e|ed|es)"
    r"|insufficient\s+(?:supply|capacity|power|availability)"
    r"|unable\s+to\s+(?:secure|obtain|procure|source)"
    r"|secur(?:e|ing)\s+(?:adequate|sufficient|additional|reliable|enough|baseload|long-term)"
    r"|depend(?:s|ent)?\s+(?:on|upon)\s+[^.;]{0,80}?(?:availab|uninterrupted)"
    r"|depend(?:s|ent)?\s+(?:on|upon)\s+access\s+to"
    r"|(?:challenges|difficulties)\s+(?:with|in)\s+(?:the\s+)?supply\s+chain"
    r"|delays?\s+in\s+(?:obtaining|securing|the\s+delivery|delivery|receiving|connecting)"
    r"|demand\s+(?:exceed(?:s|ed|ing)?|outpac(?:es|ed|ing))"
    r"|exceed(?:s|ed|ing)?\s+(?:our\s+)?(?:available\s+)?(?:capacity|supply)"
    r"|supply\s+(?:capacity|is\s+limited|disruptions?|chain\s+(?:constraints?|disruptions?))"
    r"|claim\s+the\s+supply"
    r"|allocat(?:e|ion)\s+(?:of\s+)?(?:supply|capacity))\b",
    re.IGNORECASE,
)

# Infrastructure-spending language — a demand signal rather than a
# constraint, so it's its own category with its own cue.
BUILDOUT_CUES = re.compile(
    r"\b(?:significant(?:ly)?\s+increas\w*"
    r"|substantial\s+and\s+increasing"
    r"|accelerat(?:e|ed|ing)\s+(?:our\s+)?(?:investment|build|deployment|timeline)"
    r"|expand(?:ing|ed)?\s+(?:our\s+)?(?:data\s*cent(?:er|re)|infrastructure|compute)\s+capacity"
    r"|invest(?:ed|ing)?\s+heavily"
    r"|at\s+significant\s+scale)\b",
    re.IGNORECASE,
)
BUILDOUT_SUBJECTS = re.compile(
    r"\b(?:capital\s+expenditures?|data\s*cent(?:er|re)s?|technical\s+infrastructure"
    r"|(?:ai|cloud|compute|technology)\s+infrastructure|servers?)\b",
    re.IGNORECASE,
)

# category_key -> label + subject terms. Labels intentionally echo the
# supplier taxonomy in supplier_matcher.py so evidence routes to the right
# pick-and-shovel names.
BOTTLENECK_CATEGORIES: Dict[str, Dict] = {
    "ai_compute": {
        "label": "AI compute / GPU supply",
        "subjects": r"\b(?:gpus?|graphics\s+processing|(?:ai\s+)?accelerators?|ai\s+chips?"
                    r"|specialized\s+(?:ai\s+)?chips?|tpus?|semiconductors?|silicon"
                    r"|(?:ai\s+)?compute\s+capacity|ai\s+compute)\b",
    },
    "power_energy": {
        "label": "Power / energy infrastructure",
        "subjects": r"\b(?:power|electricity|electrical|energy|grid|utilit(?:y|ies)"
                    r"|transmission|interconnection|generation\s+capacity|baseload)\b",
    },
    "datacenter_capacity": {
        "label": "Data center capacity / sites",
        "subjects": r"\b(?:data\s*cent(?:er|re)s?|infrastructure\s+capacity|land"
                    r"|technical\s+infrastructure|facilit(?:y|ies)\s+capacity|capacity\s+allocations?)\b",
    },
    "networking_servers": {
        "label": "Servers / networking equipment",
        "subjects": r"\b(?:servers?|network(?:ing)?\s+equipment|networking|optical|interconnects?"
                    r"|switches|transceivers?)\b",
    },
    "memory_storage": {
        "label": "Memory / storage supply",
        "subjects": r"\b(?:memory|dram|hbm|high[\s-]bandwidth\s+memory|nand|flash|storage\s+arrays?|ssds?)\b",
    },
    "cooling_thermal": {
        "label": "Cooling / thermal / water",
        # Not bare "thermal" — utilities say "thermal generation" for plants.
        "subjects": r"\b(?:cooling|thermal\s+management|heat\s+(?:rejection|dissipation)|water)\b",
    },
    "fab_capacity": {
        "label": "Semiconductor fab / foundry capacity",
        "subjects": r"\b(?:foundr(?:y|ies)|fabrication|fabs?|wafers?|lithography"
                    r"|advanced\s+packaging|cowos)\b",
    },
}
_SUBJECT_RES = {k: re.compile(v["subjects"], re.IGNORECASE) for k, v in BOTTLENECK_CATEGORIES.items()}

# Sentences that use a constraint cue about something we don't track.
_NOISE = re.compile(
    r"\b(?:internal\s+control|disclosure\s+controls|resource\s+constraints\s+and\s+that"
    r"|forward-looking\s+statements\s+include|labor\s+(?:market\s+)?constraints?"
    r"|personnel"
    # Generic catastrophe lists ("fire, power shortages, nuclear power plant
    # accidents, terrorist attacks...") are boilerplate, not bottlenecks.
    r"|terroris[tm]|earthquakes?|natural\s+(?:or\s+human-caused\s+)?disasters?|pandemics?"
    r"|climate\s+change|(?:economic|regulatory|competitive)(?:,?\s+and\s+\w+)?\s+constraints)\b",
    re.IGNORECASE,
)

# Below this many characters of MD&A + Risk Factors + Business, section
# extraction probably failed (banks often put MD&A in an exhibit), so scan
# the whole document instead.
MIN_SECTION_CHARS = 20000
MAX_EVIDENCE = 5


# Page furniture on its own line: page numbers and running headers. Left in,
# it glues the sentences either side of a page break into one
# ("...operating results. 11 Table of Contents Our computer...").
_PAGE_FURNITURE = re.compile(
    r"^\s*(?:\d{1,3}|[ivxl]{1,6}|page\s+\d+|table\s+of\s+contents|"
    r"part\s+[iv]+(?:\s+item\s+\d{1,2}[a-c]?)?)\s*$",
    re.IGNORECASE,
)


def _sentences(text: str) -> List[str]:
    lines = [ln for ln in text.split("\n") if not _PAGE_FURNITURE.match(ln)]
    # Lines are rejoined rather than treated as sentence boundaries: older
    # plain-text filings hard-wrap mid-sentence.
    text = re.sub(r"\s+", " ", " ".join(lines))
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z(\"“•])", text)
            if 40 <= len(s.strip()) <= 1200]


def detect_bottleneck_signals(sections: Dict[str, str]) -> List[Dict]:
    """
    Pure function (no network/db). Scans Business + Risk Factors + MD&A
    (or `full_text` when those are missing) for constraint sentences, grouped
    by category. Confidence grows with the number of distinct supporting
    sentences: 1 -> 0.37, 3 -> 0.61, 5+ -> 0.85 (capped at 0.95), so one
    passing mention reads weaker than a theme the company keeps returning to.
    """
    parts = [sections.get(k, "") for k in ("business", "risk_factors", "mda")]
    text_blob = " ".join(p for p in parts if p)
    if len(text_blob) < MIN_SECTION_CHARS and sections.get("full_text"):
        text_blob = sections["full_text"]
    if not text_blob.strip():
        return []

    hits: Dict[str, List[str]] = {k: [] for k in BOTTLENECK_CATEGORIES}
    hits["capacity_buildout"] = []
    seen = set()
    for sent in _sentences(text_blob):
        if sent in seen or _NOISE.search(sent):
            continue
        seen.add(sent)
        if CONSTRAINT_CUES.search(sent):
            for key, subject_re in _SUBJECT_RES.items():
                if subject_re.search(sent):
                    hits[key].append(sent)
        if BUILDOUT_CUES.search(sent) and BUILDOUT_SUBJECTS.search(sent):
            hits["capacity_buildout"].append(sent)

    labels = {k: v["label"] for k, v in BOTTLENECK_CATEGORIES.items()}
    labels["capacity_buildout"] = "Infrastructure capacity buildout"

    signals = []
    for key, sents in hits.items():
        if not sents:
            continue
        # Most on-topic evidence first: most mentions of THIS category's
        # subjects, then fewest other categories (a sentence listing
        # "semiconductors, networking equipment, power systems, cooling"
        # is weaker evidence for any one of them than a focused sentence).
        own = _SUBJECT_RES.get(key, BUILDOUT_SUBJECTS)
        ranked = sorted(
            sents,
            key=lambda s: (
                -len(own.findall(s)),
                sum(bool(r.search(s)) for k, r in _SUBJECT_RES.items() if k != key),
            ),
        )
        evidence = [s[:500] for s in ranked[:MAX_EVIDENCE]]
        signals.append({
            "category_key": key,
            "category": labels[key],
            "evidence": evidence[0],
            "all_evidence": evidence,
            "mention_count": len(sents),
            "confidence": round(min(0.95, 0.25 + 0.12 * len(sents)), 2),
        })

    signals.sort(key=lambda s: -s["confidence"])
    return signals


def scan_filing_text(content: str) -> List[Dict]:
    """Section-extract a 10-K's text and detect signals (full sections, no cap)."""
    sections = extract_all_sections(content, max_chars=None)
    sections["full_text"] = content
    return detect_bottleneck_signals(sections)


def run_bottleneck_tier(watchlist: List[str], session: requests.Session, run_id: int) -> List[Dict]:
    """
    Fetches each mega-cap's latest 10-K, extracts sections, scans for
    bottleneck signals, and persists each hit to backend.db so it survives
    a restart. Returns the flat list of signals (each carrying its new db
    id so Tier 3 can attach supplier matches to it).
    """
    all_signals: List[Dict] = []

    for ticker in watchlist:
        cik = sec_utils.get_cik_for_ticker(ticker, session)
        if not cik:
            continue

        filing = sec_utils.get_recent_10k_filing(cik, session)
        if not filing:
            continue

        content = sec_utils.fetch_filing_text(cik, filing, session)
        if not content:
            continue

        signals = scan_filing_text(content)

        for sig in signals:
            signal_id = db.add_signal(
                run_id, ticker, sig["category"], "\n\n".join(sig["all_evidence"]),
                sig["confidence"],
            )
            sig["id"] = signal_id
            sig["mega_cap_ticker"] = ticker
            sig["suppliers"] = []

        all_signals.extend(signals)
        time.sleep(0.1)

    return all_signals
