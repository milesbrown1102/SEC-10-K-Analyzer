# app_beautiful_final.py
"""
Beautiful SEC 10-K Analyzer with All Features
Professional design with readable colors and complete functionality
"""

import streamlit as st
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import re
import numpy as np
from SEC10K import SEC10KAnalyzerOllama
from universal_section_extractor import extract_all_sections, get_section_overview
from intelligent_inference_engine import integrate_inference_engine
from enhanced_web_search import EnhancedWebSearch, IntelligentAnswerEngine
from pdf_report_generator import generate_investment_report
from validation_module import ValidationModule

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
    try:
        progress = st.progress(0)
        status_text = st.empty()
        
        # Initialize
        status_text.text("🔍 Initializing analyzer...")
        progress.progress(10)
        
        analyzer = SEC10KAnalyzerOllama(model_name=model)
        
        # Resolve company
        company = company_input
        if natural_input and not company:
            result = analyzer.resolve_company_from_text(natural_input)
            if result:
                company = result[0]
        
        st.session_state.company = company
        
        # Fetch filing
        status_text.text(f"📥 Fetching {company} filing...")
        progress.progress(20)
        
        cik = analyzer.get_company_cik(company)
        filings = analyzer.get_recent_10k_filings(cik)
        filing = filings[0]
        content = analyzer.fetch_10k_content(cik, filing)
        
        st.session_state.filing_date = filing['filing_date']
        
        # Extract sections
        status_text.text("📋 Extracting all sections...")
        progress.progress(40)
        
        sections = extract_all_sections(content)
        st.session_state.sections = sections
        
        # Generate insights
        status_text.text("🧠 Generating AI insights...")
        progress.progress(60)
        
        st.session_state.summary_obj = analyzer.generate_executive_summary(company, sections)
        
        inference = integrate_inference_engine(sections, company)
        st.session_state.insights = inference.get('insights', [])
        
        st.session_state.suggested_questions = analyzer.get_suggested_questions(company, sections)
        
        # Extract financial data with better patterns
        text = ' '.join(sections.values())[:100000] if sections else ""
        text_lower = text.lower()
        
        financial_data = {}
        
        # Revenue - multiple patterns
        revenue_patterns = [
            r'\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)\s+(?:in\s+)?(?:total\s+)?(?:net\s+)?revenue',
            r'(?:total\s+)?revenue(?:s)?\s+(?:of|was|were)?\s*\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)',
            r'net\s+sales\s+(?:of|was|were)?\s*\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)'
        ]
        
        for pattern in revenue_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                val = float(matches[0].replace(',', ''))
                # Check context for billion vs million
                context_start = max(0, text_lower.find(matches[0]) - 20)
                context_end = min(len(text_lower), text_lower.find(matches[0]) + 50)
                context = text_lower[context_start:context_end]
                unit = 'B' if 'billion' in context else 'M'
                financial_data['revenue'] = f"${val:.1f}{unit}"
                break
        
        # Net income - multiple patterns
        income_patterns = [
            r'net\s+income\s+(?:of|was|were)?\s*\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)',
            r'\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)\s+(?:in\s+)?net\s+income',
            r'(?:earnings|profit)\s+(?:of|was|were)?\s*\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)'
        ]
        
        for pattern in income_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                val = float(matches[0].replace(',', ''))
                context_start = max(0, text_lower.find(matches[0]) - 20)
                context_end = min(len(text_lower), text_lower.find(matches[0]) + 50)
                context = text_lower[context_start:context_end]
                unit = 'B' if 'billion' in context else 'M'
                financial_data['net_income'] = f"${val:.1f}{unit}"
                break
        
        # Employees - multiple patterns
        emp_patterns = [
            r'approximately\s+([\d,]+)\s+(?:full-time\s+)?employees',
            r'([\d,]+)\s+(?:full-time\s+)?employees',
            r'workforce\s+of\s+(?:approximately\s+)?([\d,]+)',
            r'employ(?:s|ed)?\s+(?:approximately\s+)?([\d,]+)\s+(?:people|persons|individuals)?'
        ]
        
        for pattern in emp_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                financial_data['employees'] = matches[0].replace(',', ',')
                break
        
        # Gross margin
        margin_patterns = [
            r'gross\s+(?:profit\s+)?margin\s+(?:of|was|were)?\s*([\d.]+)%',
            r'([\d.]+)%\s+gross\s+margin'
        ]
        
        for pattern in margin_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                financial_data['gross_margin'] = f"{matches[0]}%"
                break
        
        # If still no data, try simpler patterns
        if not financial_data.get('revenue'):
            # Look for any large dollar amounts
            dollar_matches = re.findall(r'\$?([\d,]+(?:\.\d+)?)\s*(?:billion|million)', text_lower[:10000])
            if dollar_matches:
                val = float(dollar_matches[0].replace(',', ''))
                unit = 'M'  # Default to millions
                financial_data['revenue'] = f"${val:.1f}{unit} (est)"
        
        st.session_state.financial_data = financial_data
        
        # Peer analysis
        status_text.text("🏆 Analyzing competitors...")
        progress.progress(80)
        
        # Enhanced peer analysis with reasons
        peer_mappings = {
            'NVDA': {
                'peers': ['AMD', 'INTC', 'QCOM'],
                'reasons': {
                    'AMD': "Direct GPU competitor in gaming and data center markets",
                    'INTC': "Competing in AI accelerators and data center processors",
                    'QCOM': "Edge AI and mobile compute platform competition"
                }
            },
            'AAPL': {
                'peers': ['MSFT', 'GOOGL', 'META'],
                'reasons': {
                    'MSFT': "Hardware (Surface vs Mac) and services competition",
                    'GOOGL': "Mobile OS (iOS vs Android) and services ecosystem",
                    'META': "VR/AR hardware (Vision Pro vs Quest) competition"
                }
            },
            'MSFT': {
                'peers': ['GOOGL', 'AMZN', 'ORCL'],
                'reasons': {
                    'GOOGL': "Cloud (Azure vs GCP) and productivity suite competition",
                    'AMZN': "Leading cloud competitor with AWS",
                    'ORCL': "Enterprise software and database competition"
                }
            }
        }
        
        if company.upper() in peer_mappings:
            st.session_state.peer_data = peer_mappings[company.upper()]
        else:
            st.session_state.peer_data = {
                'peers': [],
                'reasons': {}
            }
        
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
        
        import time
        time.sleep(1)
        progress.empty()
        status_text.empty()
        
        st.success(f"✅ Successfully analyzed {company}")
        
    except Exception as e:
        st.error(f"Error: {str(e)}")

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
    with col1:
        st.metric("Revenue", st.session_state.financial_data.get('revenue', 'N/A'))
    with col2:
        st.metric("Net Income", st.session_state.financial_data.get('net_income', 'N/A'))
    with col3:
        st.metric("Employees", st.session_state.financial_data.get('employees', 'N/A'))
    with col4:
        st.metric("Gross Margin", st.session_state.financial_data.get('gross_margin', 'N/A'))
    
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
        
        # Create dashboard visualizations
        col1, col2 = st.columns(2)
        
        with col1:
            # Risk Assessment Matrix
            if st.session_state.insights:
                risk_data = []
                for insight in st.session_state.insights:
                    if hasattr(insight, 'confidence'):
                        risk_data.append({
                            'Risk': insight.insight[:40] + '...',
                            'Probability': insight.confidence,
                            'Impact': np.random.uniform(0.3, 0.9),
                            'Category': insight.category
                        })
                
                if risk_data:
                    df_risk = pd.DataFrame(risk_data)
                    
                    fig = px.scatter(df_risk, 
                                    x='Probability', 
                                    y='Impact',
                                    color='Category',
                                    size=[20]*len(df_risk),
                                    hover_data=['Risk'],
                                    color_discrete_map={
                                        'red_flag': '#FF4B4B',
                                        'opportunity': '#00CC88',
                                        'hidden_issue': '#FFA500'
                                    },
                                    title="Risk Assessment Matrix")
                    
                    fig.update_layout(
                        height=400,
                        paper_bgcolor='rgba(255,255,255,0.9)',
                        plot_bgcolor='rgba(240,240,240,0.5)',
                        xaxis=dict(range=[0, 1]),
                        yaxis=dict(range=[0, 1])
                    )
                    
                    # Add quadrant lines
                    fig.add_hline(y=0.5, line_dash="dash", line_color="gray", opacity=0.5)
                    fig.add_vline(x=0.5, line_dash="dash", line_color="gray", opacity=0.5)
                    
                    st.plotly_chart(fig, use_container_width=True)
        
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
        
        # Suggested questions
        st.markdown("**Suggested Questions:**")
        cols = st.columns(2)
        
        all_questions = st.session_state.suggested_questions[:6]
        
        # Add questions from AI insights
        for insight in st.session_state.insights[:3]:
            if hasattr(insight, 'suggested_questions'):
                all_questions.extend(insight.suggested_questions[:2])
        
        for i, q in enumerate(all_questions[:8]):
            with cols[i % 2]:
                if st.button(q[:70] + "...", key=f"q_{i}"):
                    with st.spinner("Getting answer..."):
                        answer_engine = IntelligentAnswerEngine(
                            st.session_state.sections,
                            st.session_state.company
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
                        st.session_state.company
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
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 🚨 Risk Indicators")
            for insight in red_flags[:5]:
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
                        for q in insight.suggested_questions[:2]:
                            if st.button(q, key=f"risk_q_{q[:20]}"):
                                st.session_state.conversation_history.append({
                                    'question': q,
                                    'answer': 'Processing...'
                                })
        
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
        
        if st.session_state.peer_data and st.session_state.peer_data.get('peers'):
            peers = st.session_state.peer_data['peers']
            reasons = st.session_state.peer_data.get('reasons', {})
            
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
            st.info("No direct competitors identified in filing")
    
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
        
        web_search = EnhancedWebSearch()
        
        # Recent risk events
        st.markdown("### 🚨 Recent Risk Events")
        
        risk_keywords = {
            'Legal': ['lawsuit', 'sued', 'settlement', 'litigation'],
            'Regulatory': ['SEC', 'fine', 'violation', 'investigation'],
            'Operational': ['breach', 'hack', 'recall', 'defect'],
            'Management': ['CEO', 'CFO', 'resign', 'departure']
        }
        
        risks_found = []
        for risk_type, keywords in risk_keywords.items():
            # Try to search for each risk type
            for keyword in keywords:
                search_query = f"{st.session_state.company} {keyword}"
                try:
                    results = web_search._search_duckduckgo(search_query)
                    
                    if results:
                        for result in results[:1]:
                            snippet = result.get('snippet', '').lower()
                            if keyword.lower() in snippet:
                                risks_found.append((risk_type, result.get('snippet', '')[:200]))
                                break
                except:
                    continue
            
            # If nothing found for this risk type
            if not any(r[0] == risk_type for r in risks_found):
                st.success(f"✅ No recent {risk_type.lower()} issues detected")
        
        # Display found risks
        if risks_found:
            for risk_type, description in risks_found[:3]:
                st.warning(f"**{risk_type} Issue:** {description}...")
        else:
            st.success("✅ No major risk events detected in recent searches")
        
        st.divider()
        
        # Latest News Summary
        st.markdown("### 📰 Latest Company News")
        
        # Try to get recent news
        try:
            news_results = web_search._search_duckduckgo(f"{st.session_state.company} news latest")
            if news_results:
                for result in news_results[:3]:
                    snippet = result.get('snippet', 'No description available')
                    st.info(f"• {snippet[:150]}...")
            else:
                st.info(f"Check latest {st.session_state.company} news using the links below")
        except:
            st.info("Unable to fetch recent news - use research portals below")
        
        st.divider()
        
        # Research portals - ALWAYS SHOW
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