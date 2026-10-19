# app_beautiful_final.py
"""
Beautiful SEC 10-K Analyzer with All Features
Professional design with readable colors and complete functionality
"""

import time
from typing import Dict, Optional

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import re

from SEC10K import SEC10KAnalyzerOllama
from universal_section_extractor import extract_all_sections, get_section_overview
from intelligent_inference_engine import integrate_inference_engine
from enhanced_web_search import EnhancedWebSearch, IntelligentAnswerEngine
from pdf_report_generator import generate_investment_report
from validation_module import ValidationModule
from sec_financial_data import get_xbrl_financial_data
from peer_analysis import get_peer_companies

# Optional persistent cache (backend/db.py — the same SQLite store the
# Bottleneck Scanner uses). This is intentionally best-effort: if the
# backend/ package isn't present or sqlite3 has some local issue, the app
# just falls back to st.cache_data's in-memory caching like before, rather
# than failing to start. When it IS available, this makes filings/CIK
# lookups survive a Streamlit restart instead of only a rerun — and, as a
# bonus, a filing fetched here is reused by the Bottleneck Scanner (and
# vice versa) since they share the same cache keys for a company's CIK and
# its filing text.
try:
    from backend import db as _persistent_cache
    _persistent_cache.init_db()
    _PERSISTENT_CACHE_AVAILABLE = True
except Exception:
    _persistent_cache = None
    _PERSISTENT_CACHE_AVAILABLE = False

# Page config with professional theme
st.set_page_config(
    page_title="SEC 10-K Analyst Pro",
    layout="wide",
    page_icon="📊",
    initial_sidebar_state="expanded"
)

# Beautiful, professional CSS with readable colors
st.markdown("""
<style>
    /* Professional theme with good contrast */
    .main {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        background-attachment: fixed;
    }
    .stApp {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }

    /* Cards with good readability */
    .metric-card {
        background: rgba(255, 255, 255, 0.95);
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 8px 32px rgba(31, 38, 135, 0.15);
        backdrop-filter: blur(4px);
        border: 1px solid rgba(255, 255, 255, 0.18);
    }

    /* Better metric styling */
    div[data-testid="metric-container"] {
        background: rgba(255, 255, 255, 0.9);
        border: 1px solid #e0e0e0;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }

    /* Improved tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 5px;
        background: rgba(255, 255, 255, 0.7);
        padding: 5px;
        border-radius: 10px;
    }

    .stTabs [data-baseweb="tab"] {
        background-color: rgba(255, 255, 255, 0.5);
        color: #333;
        border-radius: 8px;
        font-weight: 500;
    }

    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
    }

    /* Make text always readable */
    .stMarkdown {
        color: #2c3e50;
    }

    h1, h2, h3 {
        color: #2c3e50 !important;
    }

    /* Success/Error messages with better colors */
    .stSuccess {
        background-color: #d4edda;
        color: #155724;
        border: 1px solid #c3e6cb;
    }

    .stError {
        background-color: #f8d7da;
        color: #721c24;
        border: 1px solid #f5c6cb;
    }

    .stWarning {
        background-color: #fff3cd;
        color: #856404;
        border: 1px solid #ffeeba;
    }

    .stInfo {
        background-color: #d1ecf1;
        color: #0c5460;
        border: 1px solid #bee5eb;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# Cached wrappers around expensive network calls.
#
# The original app re-fetched the ticker list, CIK, filing list, filing HTML,
# and ran a batch of DuckDuckGo searches on every single Streamlit rerun
# (which happens on almost any button click anywhere in the app, not just
# "Analyze"). That's slow, hammers SEC/DuckDuckGo, and risks getting rate
# limited. st.cache_data keys on the arguments, so the same company/CIK/
# filing is only fetched once per hour (or until "Clear Cache" is pressed).
# Arguments prefixed with `_` are excluded from the cache key since they
# aren't hashable (session objects, the analyzer, the LLM interface).
# =============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def cached_get_cik(_analyzer, company: str) -> Optional[str]:
    key = company.strip().upper()
    if _PERSISTENT_CACHE_AVAILABLE:
        cached = _persistent_cache.cache_get("cik_lookup", key, ttl_seconds=7 * 24 * 3600)
        if cached is not None:
            return cached

    cik = _analyzer.get_company_cik(company)

    if _PERSISTENT_CACHE_AVAILABLE and cik:
        _persistent_cache.cache_set("cik_lookup", key, cik)
    return cik


@st.cache_data(ttl=3600, show_spinner=False)
def cached_get_filings(_analyzer, cik: str):
    # Namespace kept distinct from the Scanner backend's "recent_10k" cache
    # (backend/sec_utils.py) since that stores a single filing dict, while
    # this stores the list SEC10KAnalyzerOllama.get_recent_10k_filings
    # returns — different shapes, so they aren't shared.
    if _PERSISTENT_CACHE_AVAILABLE:
        cached = _persistent_cache.cache_get("recent_10k_filings_list", cik, ttl_seconds=24 * 3600)
        if cached is not None:
            return cached

    filings = _analyzer.get_recent_10k_filings(cik)

    if _PERSISTENT_CACHE_AVAILABLE and filings:
        _persistent_cache.cache_set("recent_10k_filings_list", cik, filings)
    return filings


@st.cache_data(ttl=3600, show_spinner=False)
def cached_fetch_content(_analyzer, cik: str, filing: dict):
    # Shared "filing_text" namespace/key format with backend/sec_utils.py —
    # a filing's raw text never changes once it's been filed, so this is
    # safe to cache indefinitely and to share between this app and the
    # Bottleneck Scanner: analyzing AAPL here means a later scan that
    # includes AAPL doesn't have to re-download the same document.
    cache_key = f"{cik}_{filing.get('accession_number', '')}"
    if _PERSISTENT_CACHE_AVAILABLE:
        cached = _persistent_cache.cache_get("filing_text", cache_key, ttl_seconds=None)
        if cached is not None:
            return cached

    content = _analyzer.fetch_10k_content(cik, filing)

    if _PERSISTENT_CACHE_AVAILABLE and content:
        _persistent_cache.cache_set("filing_text", cache_key, content)
    return content


@st.cache_data(ttl=3600, show_spinner=False)
def cached_xbrl_data(_session, cik: str) -> Dict:
    if _PERSISTENT_CACHE_AVAILABLE:
        cached = _persistent_cache.cache_get("xbrl_financial_snapshot", cik, ttl_seconds=24 * 3600)
        if cached is not None:
            return cached

    data = get_xbrl_financial_data(cik, _session)

    if _PERSISTENT_CACHE_AVAILABLE and data:
        _persistent_cache.cache_set("xbrl_financial_snapshot", cik, data)
    return data


@st.cache_data(ttl=3600, show_spinner=False)
def cached_peer_companies(company: str, sections: dict, _session, _llm_interface) -> Dict:
    return get_peer_companies(company, sections, _session, _llm_interface)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_ddg_search(query: str):
    return EnhancedWebSearch()._search_duckduckgo(query)


# =============================================================================
# Financial data extraction: real SEC XBRL numbers first, regex over the
# filing text only for whatever XBRL doesn't cover (employee headcount has
# no standard XBRL tag). Each value carries a `source` so the UI can be
# honest about how solid the number is, instead of presenting a text-mined
# guess with the same confidence as an audited XBRL figure.
# =============================================================================

def _regex_extract_revenue(text_lower: str) -> Optional[str]:
    patterns = [
        r'\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)\s+(?:in\s+)?(?:total\s+)?(?:net\s+)?revenue',
        r'(?:total\s+)?revenue(?:s)?\s+(?:of|was|were)?\s*\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)',
        r'net\s+sales\s+(?:of|was|were)?\s*\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text_lower)
        if matches:
            val = float(matches[0].replace(',', ''))
            idx = text_lower.find(matches[0])
            context = text_lower[max(0, idx - 20):idx + 50]
            unit = 'B' if 'billion' in context else 'M'
            return f"${val:.1f}{unit}"

    dollar_matches = re.findall(r'\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)', text_lower[:10000])
    if dollar_matches:
        val = float(dollar_matches[0].replace(',', ''))
        return f"${val:.1f}M"
    return None


def _regex_extract_net_income(text_lower: str) -> Optional[str]:
    patterns = [
        r'net\s+income\s+(?:of|was|were)?\s*\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)',
        r'\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)\s+(?:in\s+)?net\s+income',
        r'(?:earnings|profit)\s+(?:of|was|were)?\s*\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text_lower)
        if matches:
            val = float(matches[0].replace(',', ''))
            idx = text_lower.find(matches[0])
            context = text_lower[max(0, idx - 20):idx + 50]
            unit = 'B' if 'billion' in context else 'M'
            return f"${val:.1f}{unit}"
    return None


def _regex_extract_gross_margin(text_lower: str) -> Optional[str]:
    patterns = [
        r'gross\s+(?:profit\s+)?margin\s+(?:of|was|were)?\s*([\d.]+)%',
        r'([\d.]+)%\s+gross\s+margin',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text_lower)
        if matches:
            return f"{matches[0]}%"
    return None


def _regex_extract_employees(text_lower: str) -> Optional[str]:
    patterns = [
        r'approximately\s+([\d,]+)\s+(?:full-time\s+)?employees',
        r'([\d,]+)\s+(?:full-time\s+)?employees',
        r'workforce\s+of\s+(?:approximately\s+)?([\d,]+)',
        r'employ(?:s|ed)?\s+(?:approximately\s+)?([\d,]+)\s+(?:people|persons|individuals)?',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text_lower)
        if matches:
            try:
                # NOTE: this used to be `matches[0].replace(',', ',')`, a
                # no-op that just returned the raw regex match unchanged.
                count = int(matches[0].replace(',', ''))
                return f"{count:,}"
            except ValueError:
                continue
    return None


def build_financial_snapshot(analyzer, cik: str, sections: dict) -> Dict[str, Dict[str, str]]:
    """
    Returns {field: {'value': str, 'source': str}} for revenue, net_income,
    gross_margin, and employees. Prefers SEC XBRL (audited, structured data);
    falls back to text-pattern extraction only for fields XBRL didn't have.
    """
    financial_data: Dict[str, Dict[str, str]] = {}

    xbrl = cached_xbrl_data(analyzer.session, cik)

    if xbrl.get('revenue_formatted'):
        financial_data['revenue'] = {
            'value': xbrl['revenue_formatted'],
            'source': f"SEC XBRL, period ending {xbrl.get('fiscal_year_end', 'n/a')}",
        }
    if xbrl.get('net_income_formatted'):
        financial_data['net_income'] = {'value': xbrl['net_income_formatted'], 'source': 'SEC XBRL'}
    if xbrl.get('gross_margin_formatted'):
        financial_data['gross_margin'] = {
            'value': xbrl['gross_margin_formatted'],
            'source': 'SEC XBRL (computed from Gross Profit / Revenue)',
        }

    text = ' '.join(sections.values())[:100000] if sections else ""
    text_lower = text.lower()

    if 'revenue' not in financial_data:
        val = _regex_extract_revenue(text_lower)
        if val:
            financial_data['revenue'] = {'value': val, 'source': 'Estimated from filing text — verify independently'}

    if 'net_income' not in financial_data:
        val = _regex_extract_net_income(text_lower)
        if val:
            financial_data['net_income'] = {'value': val, 'source': 'Estimated from filing text — verify independently'}

    if 'gross_margin' not in financial_data:
        val = _regex_extract_gross_margin(text_lower)
        if val:
            financial_data['gross_margin'] = {'value': val, 'source': 'Estimated from filing text — verify independently'}

    emp = _regex_extract_employees(text_lower)
    if emp:
        financial_data['employees'] = {'value': emp, 'source': 'Parsed from filing text'}

    return financial_data


def _metric_value_and_help(financial_data: Dict[str, Dict[str, str]], key: str):
    item = financial_data.get(key)
    if not item:
        return 'N/A', None
    return item['value'], item.get('source')


# Initialize session state with all features
if 'initialized' not in st.session_state:
    st.session_state.update({
        'initialized': True,
        'analyzer': None,
        'company': None,
        'sections': {},
        'insights': [],
        'conversation_history': [],
        'summary_obj': None,
        'filing_date': None,
        'peer_data': None,
        'suggested_questions': [],
        'financial_data': {},
        'validation_report': None,
        'validator': ValidationModule(),
        'dashboard_data': None,
        'web_intelligence': {}
    })

# Sidebar with validation
with st.sidebar:
    st.title("⚙️ Configuration")

    model = st.selectbox(
        "LLM Model",
        ["llama3.2", "mistral", "phi3"],
        help="Select Ollama model"
    )

    if st.button("🔄 Clear Cache", use_container_width=True,
                 help="Force fresh data from SEC/search instead of cached results"):
        st.cache_data.clear()
        if _PERSISTENT_CACHE_AVAILABLE:
            # Only clear the namespaces this app writes to — leave the
            # Bottleneck Scanner's own scan history/results alone.
            for ns in ("cik_lookup", "recent_10k_filings_list", "filing_text", "xbrl_financial_snapshot"):
                _persistent_cache.cache_clear(ns)
        st.success("Cache cleared.")

    st.divider()

    # Validation Section (for accuracy)
    if st.session_state.get('validation_report'):
        st.markdown("### ✅ System Accuracy")
        report = st.session_state.validation_report

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Score", f"{report['overall_system_score']:.1%}")
        with col2:
            st.metric("Grade", report['grade'])

        with st.expander("View Details"):
            if 'extraction' in report['tests']:
                st.write("**Extraction Quality:**")
                for test in report['tests']['extraction']['extraction_tests']:
                    status = "✅" if test['pass'] else "❌"
                    st.write(f"{status} {test['test']}: {test['score']:.0%}")

    st.divider()

    # Export
    if st.session_state.sections:
        if st.button("📄 Generate PDF Report", type="secondary", use_container_width=True):
            with st.spinner("Creating report..."):
                pdf = generate_investment_report(
                    st.session_state.company,
                    st.session_state.filing_date,
                    st.session_state.sections,
                    st.session_state.summary_obj,
                    st.session_state.insights,
                    st.session_state.peer_data
                )
                st.download_button(
                    "Download PDF",
                    pdf,
                    f"{st.session_state.company}_Report.pdf",
                    "application/pdf"
                )

# Main header
col1, col2, col3 = st.columns([2, 3, 1])
with col1:
    st.title("📊 SEC 10-K Analyst Pro")
with col2:
    st.caption("Institutional-grade analysis with AI-powered insights")
with col3:
    if st.session_state.validation_report:
        accuracy = st.session_state.validation_report['overall_system_score']
        st.metric("System Accuracy", f"{accuracy:.0%}")

# Input section
col1, col2, col3 = st.columns([3, 3, 1])
with col1:
    company_input = st.text_input("Company/Ticker", placeholder="AAPL, MSFT, NVDA...")
with col2:
    natural_input = st.text_input("Or ask naturally", placeholder="How is Apple doing?")
with col3:
    analyze_btn = st.button("🚀 Analyze", type="primary", use_container_width=True)

# Analysis
if analyze_btn and (company_input or natural_input):
    progress = st.progress(0)
    status_text = st.empty()

    try:
        status_text.text("🔍 Initializing analyzer...")
        progress.progress(10)

        analyzer = SEC10KAnalyzerOllama(model_name=model)

        # Resolve company
        company = company_input
        if natural_input and not company:
            result = analyzer.resolve_company_from_text(natural_input)
            if result:
                company = result[0]

        if not company:
            raise ValueError(
                "Could not determine a company from your input. "
                "Try entering an exact ticker symbol (e.g. AAPL)."
            )

        st.session_state.company = company

        # Fetch filing
        status_text.text(f"📥 Fetching {company} filing...")
        progress.progress(20)

        cik = cached_get_cik(analyzer, company)
        if not cik:
            raise ValueError(f"Could not find a CIK for '{company}'. Try the exact ticker symbol.")

        filings = cached_get_filings(analyzer, cik)
        if not filings:
            raise ValueError(f"No recent 10-K filings found for {company}.")

        filing = filings[0]
        content = cached_fetch_content(analyzer, cik, filing)
        if not content:
            raise ValueError(f"Could not fetch the 10-K filing content for {company}.")

        st.session_state.filing_date = filing['filing_date']

        # Extract sections
        status_text.text("📋 Extracting all sections...")
        progress.progress(40)

        sections = extract_all_sections(content)
        st.session_state.sections = sections

        # Generate insights
        status_text.text("🧠 Generating AI insights...")
        progress.progress(55)

        st.session_state.summary_obj = analyzer.generate_executive_summary(company, sections)

        inference = integrate_inference_engine(sections, company)
        st.session_state.insights = inference.get('insights', [])

        st.session_state.suggested_questions = analyzer.get_suggested_questions(company, sections)

        # Real financial data: SEC XBRL first, filing-text regex only as a
        # fallback for what XBRL doesn't cover.
        status_text.text("💰 Pulling financial data from SEC XBRL...")
        progress.progress(70)

        st.session_state.financial_data = build_financial_snapshot(analyzer, cik, sections)

        # Peer analysis: dynamic discovery for any company (curated list is
        # just a fast-path for a few well-known names now, not the only path).
        status_text.text("🏆 Identifying competitors...")
        progress.progress(80)

        st.session_state.peer_data = cached_peer_companies(
            company, sections, analyzer.session, analyzer.llm
        )

        # Reset any stale web-intelligence results from a previous company —
        # that tab is opt-in (see Tab 6) so it won't auto-refetch here.
        st.session_state.web_intelligence = {}

        # Validation
        status_text.text("✅ Running validation...")
        progress.progress(90)

        sample_qa = []
        if st.session_state.conversation_history:
            sample_qa = [(q['question'], q['answer']) for q in st.session_state.conversation_history[:3]]

        st.session_state.validation_report = st.session_state.validator.run_comprehensive_validation(
            sections, company, st.session_state.insights, sample_qa
        )

        progress.progress(100)
        status_text.text("✅ Analysis complete!")
        time.sleep(0.6)

        st.success(f"✅ Successfully analyzed {company}")

    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        # Always clear the progress UI, even on failure — previously a
        # mid-pipeline exception left a stuck progress bar on screen.
        progress.empty()
        status_text.empty()

# Display results
if st.session_state.company:

    # Company overview bar
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Company", st.session_state.company)
    with col2:
        st.metric("Filing Date", st.session_state.filing_date)
    with col3:
        sections_found = len([s for s in st.session_state.sections.values() if s])
        st.metric("Sections", f"{sections_found}/20")
    with col4:
        if st.session_state.peer_data and st.session_state.peer_data.get('peers'):
            st.metric("Competitors", len(st.session_state.peer_data['peers']))

    # Financial overview
    st.markdown("### 💰 Financial Overview")
    col1, col2, col3, col4 = st.columns(4)
    fd = st.session_state.financial_data or {}
    with col1:
        value, help_text = _metric_value_and_help(fd, 'revenue')
        st.metric("Revenue", value, help=help_text)
    with col2:
        value, help_text = _metric_value_and_help(fd, 'net_income')
        st.metric("Net Income", value, help=help_text)
    with col3:
        value, help_text = _metric_value_and_help(fd, 'employees')
        st.metric("Employees", value, help=help_text)
    with col4:
        value, help_text = _metric_value_and_help(fd, 'gross_margin')
        st.metric("Gross Margin", value, help=help_text)

    # Company summary
    if st.session_state.summary_obj:
        st.markdown("### Company Summary")
        st.write(st.session_state.summary_obj.summary)

    st.divider()

    # Main tabs with all features
    tabs = st.tabs([
        "📊 Dashboard",
        "💬 Q&A Chat",
        "🧠 AI Insights",
        "🏆 Peer Analysis",
        "📋 Filing Details",
        "🌐 Web Intelligence"
    ])

    # Tab 1: Dashboard (with beautiful graphs)
    with tabs[0]:
        st.subheader("📊 Visual Analytics Dashboard")

        col1, col2 = st.columns(2)

        with col1:
            # Insight confidence by category. This used to be a scatter plot
            # with a fabricated "Impact" axis (np.random.uniform) presented
            # next to real model confidence scores — that's random noise
            # dressed up as financial analysis. It's gone; this chart only
            # shows real numbers the model actually produced.
            st.markdown("**AI-Detected Insights by Confidence**")

            scored_insights = [i for i in st.session_state.insights if hasattr(i, 'confidence')]
            if scored_insights:
                df_risk = pd.DataFrame([
                    {
                        'Insight': (i.insight[:50] + '...') if len(i.insight) > 50 else i.insight,
                        'Confidence': i.confidence,
                        'Category': i.category,
                    }
                    for i in scored_insights
                ]).sort_values('Confidence', ascending=True)

                fig = px.bar(
                    df_risk, x='Confidence', y='Insight', color='Category', orientation='h',
                    color_discrete_map={
                        'red_flag': '#FF4B4B',
                        'opportunity': '#00CC88',
                        'hidden_issue': '#FFA500'
                    },
                    title="Insights ranked by model confidence"
                )
                fig.update_layout(
                    height=400,
                    paper_bgcolor='rgba(255,255,255,0.9)',
                    plot_bgcolor='rgba(240,240,240,0.5)',
                    xaxis=dict(range=[0, 1]),
                    showlegend=True,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No scored insights available for this filing yet.")

        with col2:
            # Filing Coverage Gauge
            sections_found = len([s for s in st.session_state.sections.values() if s])
            coverage = (sections_found / 20) * 100

            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=coverage,
                title={'text': "Filing Coverage %"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': "#667eea"},
                    'steps': [
                        {'range': [0, 50], 'color': "lightgray"},
                        {'range': [50, 80], 'color': "lightblue"},
                        {'range': [80, 100], 'color': "lightgreen"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': 90
                    }
                }
            ))

            fig.update_layout(
                height=400,
                paper_bgcolor='rgba(255,255,255,0.9)'
            )

            st.plotly_chart(fig, use_container_width=True)

        # Priority Alerts
        st.markdown("### 🚨 Priority Alerts")

        if st.session_state.insights:
            for insight in st.session_state.insights[:5]:
                if insight.category == 'red_flag' and insight.confidence > 0.7:
                    st.error(f"⚠️ {insight.insight} (Confidence: {insight.confidence:.0%})")
                elif insight.category == 'opportunity' and insight.confidence > 0.7:
                    st.success(f"💡 {insight.insight} (Confidence: {insight.confidence:.0%})")
                else:
                    st.warning(f"ℹ️ {insight.insight} (Confidence: {insight.confidence:.0%})")

    # Tab 2: Q&A Chat (that doesn't kick you out)
    with tabs[1]:
        st.subheader("💬 Ask Any Question")

        peers_for_qa = st.session_state.peer_data.get('peers', []) if st.session_state.peer_data else []

        # Suggested questions
        st.markdown("**Suggested Questions:**")
        cols = st.columns(2)

        all_questions = st.session_state.suggested_questions[:6]

        # Add questions from AI insights
        for insight in st.session_state.insights[:3]:
            if hasattr(insight, 'suggested_questions'):
                all_questions.extend(insight.suggested_questions[:2])

        for i, q in enumerate(all_questions[:8]):
            label = q if len(q) <= 70 else q[:70] + "..."
            with cols[i % 2]:
                if st.button(label, key=f"q_{i}"):
                    with st.spinner("Getting answer..."):
                        answer_engine = IntelligentAnswerEngine(
                            st.session_state.sections,
                            st.session_state.company,
                            peers_for_qa
                        )
                        response = answer_engine.answer_with_fallback(q)

                        st.session_state.conversation_history.append({
                            'question': q,
                            'answer': response['answer'],
                            'found_in_filing': response['found_in_filing'],
                            'sources': response.get('search_urls', {})
                        })

        # Custom question
        st.divider()
        user_question = st.text_area("Your question:", height=100, key="custom_q")
        if st.button("Ask", type="primary"):
            if user_question:
                with st.spinner("Analyzing..."):
                    answer_engine = IntelligentAnswerEngine(
                        st.session_state.sections,
                        st.session_state.company,
                        peers_for_qa
                    )
                    response = answer_engine.answer_with_fallback(user_question)

                    st.session_state.conversation_history.append({
                        'question': user_question,
                        'answer': response['answer'],
                        'found_in_filing': response['found_in_filing'],
                        'sources': response.get('search_urls', {})
                    })

        # Display conversation
        if st.session_state.conversation_history:
            st.divider()
            st.markdown("### Conversation History")

            for conv in reversed(st.session_state.conversation_history):
                with st.container():
                    st.markdown(f"**Q:** {conv['question']}")
                    st.markdown(f"**A:** {conv['answer']}")

                    if not conv.get('found_in_filing'):
                        st.info("💡 Answer includes web search data")
                        if conv.get('sources'):
                            with st.expander("View Sources"):
                                for name, url in list(conv['sources'].items())[:6]:
                                    st.markdown(f"• [{name}]({url})")

                    st.divider()

    # Tab 3: AI Insights (with depth)
    with tabs[2]:
        st.subheader("🧠 AI-Detected Insights & Hidden Issues")

        st.markdown("""
        Our AI reads between the lines to find:
        - **Hidden risks** not explicitly stated
        - **Inconsistencies** between sections
        - **Missing information** that should be disclosed
        """)

        # Group insights
        red_flags = [i for i in st.session_state.insights if i.category == 'red_flag']
        opportunities = [i for i in st.session_state.insights if i.category == 'opportunity']
        hidden = [i for i in st.session_state.insights if i.category == 'hidden_issue']

        peers_for_qa = st.session_state.peer_data.get('peers', []) if st.session_state.peer_data else []

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 🚨 Risk Indicators")
            for ridx, insight in enumerate(red_flags[:5]):
                with st.expander(f"Risk: {insight.insight[:60]}...", expanded=False):
                    st.write(f"**Full Analysis:** {insight.insight}")
                    st.progress(insight.confidence)
                    st.write(f"**Confidence:** {insight.confidence:.0%}")

                    if hasattr(insight, 'evidence'):
                        st.write("**Evidence from filing:**")
                        for e in insight.evidence[:2]:
                            st.caption(f"• {e[:150]}...")

                    if hasattr(insight, 'suggested_questions'):
                        st.write("**Investigate further:**")
                        for qidx, q in enumerate(insight.suggested_questions[:2]):
                            # This used to append a placeholder answer of
                            # 'Processing...' that nothing ever resolved —
                            # clicking it looked like it worked but never
                            # produced a real answer. It now actually asks.
                            if st.button(q, key=f"risk_q_{ridx}_{qidx}"):
                                with st.spinner("Getting answer..."):
                                    answer_engine = IntelligentAnswerEngine(
                                        st.session_state.sections,
                                        st.session_state.company,
                                        peers_for_qa
                                    )
                                    response = answer_engine.answer_with_fallback(q)
                                    st.session_state.conversation_history.append({
                                        'question': q,
                                        'answer': response['answer'],
                                        'found_in_filing': response['found_in_filing'],
                                        'sources': response.get('search_urls', {})
                                    })
                                st.success("Answered — see the Q&A Chat tab.")

        with col2:
            st.markdown("### 💡 Opportunities")
            for insight in opportunities[:5]:
                with st.expander(f"Opportunity: {insight.insight[:60]}...", expanded=False):
                    st.write(f"**Full Analysis:** {insight.insight}")
                    st.progress(insight.confidence)
                    st.write(f"**Confidence:** {insight.confidence:.0%}")

                    if hasattr(insight, 'evidence'):
                        st.write("**Supporting evidence:**")
                        for e in insight.evidence[:2]:
                            st.caption(f"• {e[:150]}...")

        if hidden:
            st.markdown("### 🔍 Hidden Issues (Reading Between Lines)")
            for insight in hidden[:3]:
                st.warning(f"**Hidden Issue:** {insight.insight}")
                st.caption(f"Confidence: {insight.confidence:.0%}")

    # Tab 4: Peer Analysis (with detailed reasons)
    with tabs[3]:
        st.subheader("🏆 Competitive Intelligence")

        peer_info = st.session_state.peer_data or {}
        peers = peer_info.get('peers', [])
        reasons = peer_info.get('reasons', {})
        method = peer_info.get('method', 'none')

        if peers:
            method_label = {
                'curated': 'Hand-curated comparison set',
                'llm': "AI-extracted from this filing's Business/Risk Factors sections",
                'regex': "Pattern-matched from this filing's Business section",
            }.get(method, 'Unknown')
            st.caption(f"Source: {method_label}")

            st.markdown(f"### Identified Competitors for {st.session_state.company}")

            # Explain each peer
            for peer in peers:
                with st.expander(f"📊 {peer} - Why They're a Competitor"):
                    if peer in reasons:
                        st.write(f"**Competitive Overlap:** {reasons[peer]}")

                    st.markdown("**Why Monitor This Competitor:**")
                    st.write("""
                    • Their regulatory issues often spread industry-wide
                    • Customer defections between competitors are common
                    • Technology shifts affect all players
                    • Pricing pressure from one impacts all
                    """)

                    # Check for peer risks
                    st.markdown(f"**Check {peer} Recent Issues:**")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.markdown(f"[📰 {peer} News](https://news.google.com/search?q={peer})")
                    with col2:
                        st.markdown(f"[💰 {peer} Financials](https://finance.yahoo.com/quote/{peer})")
                    with col3:
                        st.markdown(f"[🏛️ {peer} SEC](https://www.sec.gov/edgar/search/#/entityName={peer})")

                    # Potential risks from this peer
                    st.warning(f"""
                    ⚠️ **Risks from {peer} to monitor:**
                    • If {peer} faces regulatory action, {st.session_state.company} may be next
                    • {peer}'s product recalls could affect similar {st.session_state.company} products
                    • Lawsuits against {peer} often expand to include competitors
                    """)
        else:
            st.info(
                f"No competitors could be automatically identified for "
                f"{st.session_state.company} from this filing. Try the research "
                f"portals in the Web Intelligence tab."
            )

    # Tab 5: Filing Details
    with tabs[4]:
        st.subheader("📋 Filing Details & Coverage")

        overview = get_section_overview(' '.join(st.session_state.sections.values()))

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Sections", len(overview.get('section_details', [])))
        with col2:
            st.metric("Total Words", f"{overview.get('total_words', 0):,}")
        with col3:
            st.metric("Est. Pages", overview.get('total_words', 0) // 250)
        with col4:
            sections_found = len([s for s in overview.get('section_details', []) if s['found']])
            st.metric("Coverage", f"{(sections_found/20)*100:.0f}%")

        # Section breakdown
        st.markdown("### Section Analysis")

        section_data = []
        for section in overview.get('section_details', []):
            section_data.append({
                'Section': f"Item {section.get('item', 'Unknown')}",
                'Name': section.get('name', 'Unknown Section'),
                'Found': '✅' if section.get('found', False) else '❌',
                'Words': section.get('words', 0) if section.get('found', False) else 0,
                'Pages': section.get('words', 0) // 250 if section.get('found', False) else 0
            })

        df = pd.DataFrame(section_data)
        st.dataframe(df, use_container_width=True)

        # Visualize section coverage
        fig = px.bar(df, x='Section', y='Words', color='Found',
                    color_discrete_map={'✅': '#00CC88', '❌': '#FF4B4B'},
                    title="Section Word Count Distribution")
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    # Tab 6: Web Intelligence (comprehensive)
    with tabs[5]:
        st.subheader("🌐 Web Intelligence & Recent Events")

        st.caption(
            "This scan hits external search on demand — it no longer runs "
            "automatically on every click elsewhere in the app."
        )

        risk_keywords = {
            'Legal': ['lawsuit', 'sued', 'settlement', 'litigation'],
            'Regulatory': ['SEC', 'fine', 'violation', 'investigation'],
            'Operational': ['breach', 'hack', 'recall', 'defect'],
            'Management': ['CEO', 'CFO', 'resign', 'departure']
        }

        if st.button("🔍 Scan for Recent Risk Events & News"):
            with st.spinner("Scanning recent news..."):
                risks_found = []
                categories_clear = []

                for risk_type, keywords in risk_keywords.items():
                    found_for_category = False
                    for keyword in keywords:
                        search_query = f"{st.session_state.company} {keyword}"
                        try:
                            results = cached_ddg_search(search_query)
                        except Exception:
                            results = []

                        if results:
                            snippet = results[0].get('snippet', '').lower()
                            if keyword.lower() in snippet:
                                risks_found.append((risk_type, results[0].get('snippet', '')[:200]))
                                found_for_category = True
                                break  # stop scanning more keywords for this category

                    if not found_for_category:
                        categories_clear.append(risk_type)

                try:
                    news_results = cached_ddg_search(f"{st.session_state.company} news latest")
                except Exception:
                    news_results = []

                st.session_state.web_intelligence = {
                    'risks_found': risks_found,
                    'categories_clear': categories_clear,
                    'news_results': news_results,
                }

        web_intel = st.session_state.get('web_intelligence') or {}

        st.markdown("### 🚨 Recent Risk Events")
        if not web_intel:
            st.info("Click the button above to scan for recent news and risk events.")
        else:
            for risk_type in web_intel.get('categories_clear', []):
                st.success(f"✅ No recent {risk_type.lower()} issues detected")

            if web_intel.get('risks_found'):
                for risk_type, description in web_intel['risks_found'][:3]:
                    st.warning(f"**{risk_type} Issue:** {description}...")
            elif not web_intel.get('categories_clear'):
                st.info("No results returned from search — try again shortly.")

            st.divider()
            st.markdown("### 📰 Latest Company News")
            news_results = web_intel.get('news_results') or []
            if news_results:
                for result in news_results[:3]:
                    snippet = result.get('snippet', 'No description available')
                    st.info(f"• {snippet[:150]}...")
            else:
                st.info(f"Check latest {st.session_state.company} news using the links below")

        st.divider()

        # Research portals - ALWAYS SHOW (static links, no network calls)
        st.markdown("### 🔗 Research Portals")

        col1, col2, col3, col4 = st.columns(4)

        portals = {
            '📈 Yahoo Finance': f"https://finance.yahoo.com/quote/{st.session_state.company}",
            '📰 Google News': f"https://news.google.com/search?q={st.session_state.company}",
            '🏛️ SEC EDGAR': f"https://www.sec.gov/edgar/search/#/entityName={st.session_state.company}",
            '💬 Reddit': f"https://reddit.com/search/?q=${st.session_state.company}",
            '🐦 Twitter/X': f"https://twitter.com/search?q=${st.session_state.company}",
            '📚 Google Scholar': f"https://scholar.google.com/scholar?q={st.session_state.company}",
            '📊 MarketWatch': f"https://www.marketwatch.com/investing/stock/{st.session_state.company}",
            '💼 LinkedIn': f"https://www.linkedin.com/company/{st.session_state.company.lower()}"
        }

        for i, (name, url) in enumerate(portals.items()):
            with [col1, col2, col3, col4][i % 4]:
                st.markdown(f"[{name}]({url})")

        st.divider()

        # Competitor monitoring - ALWAYS SHOW
        st.markdown("### 🏆 Competitor Risk Monitoring")

        if st.session_state.peer_data and st.session_state.peer_data.get('peers'):
            st.error("""
            ⚠️ **Why Monitor Competitors:**
            • Their lawsuits often expand to include industry peers
            • Regulatory actions against one company signal industry-wide scrutiny
            • Product recalls at competitors may indicate similar issues at your company
            • Customer complaints about competitors reveal industry vulnerabilities
            """)

            for peer in st.session_state.peer_data['peers'][:3]:
                with st.expander(f"Monitor {peer} Issues"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.markdown(f"[{peer} Lawsuits](https://news.google.com/search?q={peer}+lawsuit+sued)")
                    with col2:
                        st.markdown(f"[{peer} SEC Issues](https://www.sec.gov/edgar/search/#/entityName={peer})")
                    with col3:
                        st.markdown(f"[{peer} News](https://finance.yahoo.com/quote/{peer})")
        else:
            st.info("Run analysis to identify competitors for monitoring")

# Footer
st.divider()
col1, col2, col3 = st.columns(3)
with col1:
    st.caption("💡 Powered by Ollama & Local LLMs")
with col2:
    st.caption("🔒 100% Private - All analysis local")
with col3:
    if st.session_state.validation_report:
        st.caption(f"✅ Accuracy: {st.session_state.validation_report['grade']}")
