# app.py
import time
import streamlit as st
from datetime import datetime
from SEC10K import SEC10KAnalyzerOllama  # your class

# Page config should be near the top
st.set_page_config(page_title="SEC 10-K Analyst", layout="wide")

# Import the universal section extractor
from universal_section_extractor import extract_all_sections, get_section_overview
# Import intelligent inference engine
from intelligent_inference_engine import integrate_inference_engine
from web_search_augmentation import create_augmented_summary

# ---------- Session state init ----------
for k, v in {
    "analyzer": None,
    "model": "llama3.2",
    "company": None,
    "cik": None,
    "filing": None,
    "sections": None,
    "suggestions": [],
    "summary_obj": None,
    "accession_url": None,
    "filing_date": None,
    "conversation_history": [],  
    "current_company_conversation": None,
    "filing_content": None,  # Store the full content
}.items():
    st.session_state.setdefault(k, v)


# ---------- Helper Functions ----------
def add_to_conversation(question, answer, source):
    """Add Q&A pair to conversation history"""
    st.session_state.conversation_history.append({
        "question": question,
        "answer": answer,
        "source": source,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })

def show_tags(tags):
    """Display tags in a nice format"""
    tag_html = " ".join([f'<span style="background-color: #f0f2f6; padding: 4px 12px; border-radius: 20px; margin: 4px; display: inline-block;">{tag}</span>' for tag in tags])
    st.markdown(tag_html, unsafe_allow_html=True)
def clear_conversation():
    """Clear conversation history when analyzing a new company"""
    st.session_state.conversation_history = []
    st.session_state.current_company_conversation = None


def get_section_stats(sections):
    """Get statistics about the sections"""
    stats = {
        "total_sections": 0,
        "sections_found": [],
        "sections_empty": [],
        "total_chars": 0,
        "total_words": 0
    }
    
    for section_name, content in sections.items():
        if content and len(content.strip()) > 100:  # Has meaningful content
            stats["sections_found"].append(section_name)
            stats["total_chars"] += len(content)
            stats["total_words"] += len(content.split())
        else:
            stats["sections_empty"].append(section_name)
    
    stats["total_sections"] = len(stats["sections_found"])
    return stats


# ---------- Sidebar ----------
with st.sidebar:
    st.title("⚙️ Settings")
    st.session_state.model = st.selectbox(
        "Ollama model",
        ["llama3.2", "phi3", "llama3.2:1b", "mistral"],
        index=["llama3.2", "phi3", "llama3.2:1b", "mistral"].index(st.session_state.model),
    )
    st.caption("Tip: keep `ollama serve` running.")

    st.divider()

    # Conversation controls
    st.subheader("💬 Conversation")
    if st.session_state.conversation_history:
        st.info(f"📝 {len(st.session_state.conversation_history)} messages")
        if st.button("Clear Conversation", type="secondary"):
            clear_conversation()
            st.rerun()

    # Show current company context
    if st.session_state.current_company_conversation:
        st.success(f"📊 Context: {st.session_state.current_company_conversation}")
        st.caption(f"Filing: {st.session_state.filing_date}")
        
        # Show section stats in sidebar
        if st.session_state.sections:
            stats = get_section_stats(st.session_state.sections)
            st.divider()
            st.subheader("📄 Filing Overview")
            st.metric("Sections Found", stats["total_sections"])
            st.metric("Total Words", f"{stats['total_words']:,}")
            st.metric("Total Characters", f"{stats['total_chars']:,}")
            
            with st.expander("Available Sections"):
                for sec in stats["sections_found"]:
                    st.caption(f"✅ {sec.replace('_', ' ').title()}")
                if stats["sections_empty"]:
                    st.caption("Missing/Empty:")
                    for sec in stats["sections_empty"]:
                        st.caption(f"❌ {sec.replace('_', ' ').title()}")


# ---------- Header ----------
st.title("📊 SEC 10-K Analyst (Local LLM)")
st.caption("Ask about a company's latest 10-K. Fully local via Ollama.")

# ---------- Inputs ----------
col1, col2 = st.columns([2, 3])
with col1:
    company_in = st.text_input("Company or ticker", placeholder="e.g., NVDA, AAPL, Microsoft")
with col2:
    nl_ask_in = st.text_input('Or ask in natural language', placeholder='e.g., "How is Microsoft doing?"')

analyze = st.button("Analyze", type="primary")

# ---------- Analyze flow ----------
if analyze:
    try:
        # Check if we're analyzing a new company
        new_company = company_in.strip() if company_in else None

        # If it's a different company, clear the conversation
        if new_company and new_company != st.session_state.current_company_conversation:
            clear_conversation()

        # Create analyzer
        st.session_state.analyzer = SEC10KAnalyzerOllama(model_name=st.session_state.model)

        # Resolve company if only natural-language ask provided
        initial_ask = None
        final_company = new_company
        if nl_ask_in and not final_company:
            with st.status("🔎 Detecting company…", expanded=False) as s:
                res = st.session_state.analyzer.resolve_company_from_text(nl_ask_in)
                if not res:
                    s.update(label="❌ Could not detect company. Please enter a ticker/name.", state="error")
                    st.stop()
                ticker, title, cik = res
                final_company = ticker
                initial_ask = nl_ask_in
                s.update(label=f"✅ Detected: **{title} ({ticker})**", state="complete")

        if not final_company:
            st.warning("Please enter a company or a natural-language question.")
            st.stop()

        # Check if this is a new company
        if final_company != st.session_state.current_company_conversation:
            clear_conversation()
            st.session_state.current_company_conversation = final_company

        st.session_state.company = final_company

        with st.status(f"📥 Fetching latest 10-K for **{final_company}**…", expanded=False) as s:
            cik = st.session_state.analyzer.get_company_cik(final_company)
            if not cik:
                s.update(label=f"❌ Company not found: {final_company}", state="error")
                st.stop()
            filings = st.session_state.analyzer.get_recent_10k_filings(cik)
            if not filings:
                s.update(label="❌ No recent 10-K filings found.", state="error")
                st.stop()

            filing = filings[0]
            content = st.session_state.analyzer.fetch_10k_content(cik, filing)
            if not content:
                s.update(label="❌ Could not fetch filing content.", state="error")
                st.stop()

            # Store the full content
            st.session_state.filing_content = content
            
            # Use universal extraction to find ALL sections
            sections = extract_all_sections(content)

            # Save to session for later Q&A
            st.session_state.cik = cik
            st.session_state.filing = filing
            st.session_state.sections = sections

            # Set up accession URL and filing date
            accession = filing['accession_number']
            st.session_state.accession_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik.lstrip('0')}/{accession}/index.html"
            )
            st.session_state.filing_date = filing["filing_date"]

            # Update analyzer's current filing info
            st.session_state.analyzer.current_accession_url = st.session_state.accession_url
            st.session_state.analyzer.current_filing_date = st.session_state.filing_date

            s.update(label=f"✅ Filing date: {st.session_state.filing_date}", state="complete")

        with st.spinner("🧠 Generating executive summary & suggestions…"):
            st.session_state.suggestions = st.session_state.analyzer.get_suggested_questions(
                final_company, sections
            )
            st.session_state.summary_obj = st.session_state.analyzer.generate_executive_summary(
                final_company, sections
            )

        # If they typed a natural-language ask, answer it immediately
        if initial_ask:
            with st.spinner("🤔 Answering your question…"):
                ans, src = st.session_state.analyzer.answer_question_with_ollama(
                    st.session_state.sections, initial_ask
                )
                add_to_conversation(initial_ask, ans, src)

    except Exception as e:
        st.error(f"Error: {e}")
        import traceback
        st.code(traceback.format_exc())
        st.stop()


# ---------- Show results if we have an analysis ----------
if st.session_state.sections:
    # Company info banner
    col1, col2, col3 = st.columns(3)
    with col1:
        st.success(f"**Company:** {st.session_state.company}")
    with col2:
        st.success(f"**Filing Date:** {st.session_state.filing_date}")
    with col3:
        st.success(f"**Messages:** {len(st.session_state.conversation_history)}")

    # Create tabs for better organization - Added "Intelligent Insights" tab
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Executive Summary", "💬 Q&A Chat", "💡 Suggestions", "📋 Filing Overview", "🧠 Intelligent Insights"])

    with tab1:
        st.subheader("Executive Summary")
        st.write(st.session_state.summary_obj.summary or "—")

        cols = st.columns(3)
        with cols[0]:
            st.markdown("**Key Insights**")
            for i, k in enumerate(st.session_state.summary_obj.key_insights[:5], 1):
                st.write(f"{i}. {k}")
        with cols[1]:
            st.markdown("**Top Risks**")
            for i, r in enumerate(st.session_state.summary_obj.risks[:5], 1):
                st.write(f"{i}. {r}")
        with cols[2]:
            st.markdown("**Opportunities**")
            for i, o in enumerate(st.session_state.summary_obj.opportunities[:5], 1):
                st.write(f"{i}. {o}")

        if st.session_state.summary_obj.financial_highlights:
            st.markdown("**Key Financial Metrics**")
            for k, v in list(st.session_state.summary_obj.financial_highlights.items())[:8]:
                st.write(f"- **{k}**: {v}")

        st.info(
            f"📍 Source: [SEC EDGAR Filing]({st.session_state.accession_url}) "
            f"• Filed: {st.session_state.filing_date}"
        )

    with tab2:
        st.subheader("💬 Conversation History")

        # Display conversation history
        if st.session_state.conversation_history:
            chat_container = st.container()
            with chat_container:
                for i, msg in enumerate(st.session_state.conversation_history):
                    # Question
                    with st.chat_message("user"):
                        st.write(f"**Q:** {msg['question']}")
                        st.caption(f"Asked at {msg['timestamp']}")

                    # Answer
                    with st.chat_message("assistant"):
                        st.write(f"**A:** {msg['answer']}")
                        st.caption(
                            f"📍 Source: {msg['source']} • {st.session_state.filing_date}"
                        )
        else:
            st.info("No questions asked yet. Start by asking a question below!")

        st.divider()

        # Question input area
        st.subheader("Ask a New Question")

        # Create a form for better UX
        with st.form(key="qa_form", clear_on_submit=True):
            user_q = st.text_area(
                "Your question",
                placeholder=(
                    "e.g., What are the main revenue segments? "
                    "How is AI impacting the business?"
                ),
                height=80,
                key="qa_input_form",
            )

            col1, col2 = st.columns([1, 5])
            with col1:
                submit_btn = st.form_submit_button(
                    "Ask", type="primary", use_container_width=True
                )
            with col2:
                st.caption("💡 Tip: Check the Suggestions tab for question ideas")

        # Process the question
        if submit_btn and user_q.strip():
            with st.spinner("🤔 Analyzing the filing to answer your question…"):
                try:
                    # Make sure we have sections
                    if not st.session_state.sections:
                        st.error("No filing data available. Please analyze a company first.")
                    else:
                        ans, src = st.session_state.analyzer.answer_question_with_ollama(
                            st.session_state.sections,
                            user_q.strip(),
                        )
                        add_to_conversation(user_q.strip(), ans, src)
                        st.rerun()  # Refresh to show the new message
                except Exception as e:
                    st.error(f"Error answering question: {e}")

    with tab3:
        st.subheader("💡 Suggested Questions")
        st.caption("Click any question to ask it")

        # Group suggestions by category
        business_qs = [
            q
            for q in st.session_state.suggestions
            if any(k in q.lower() for k in ["business", "product", "competitor", "customer"])
        ]
        financial_qs = [
            q
            for q in st.session_state.suggestions
            if any(k in q.lower() for k in ["revenue", "income", "margin", "cash", "dividend"])
        ]
        risk_qs = [
            q
            for q in st.session_state.suggestions
            if any(k in q.lower() for k in ["risk", "regulatory", "geopolitical"])
        ]
        other_qs = [
            q
            for q in st.session_state.suggestions
            if q not in business_qs + financial_qs + risk_qs
        ]

        if business_qs:
            st.markdown("**📊 Business & Operations**")
            for q in business_qs:
                if st.button(q, key=f"biz_{q[:20]}", use_container_width=True):
                    with st.spinner("Getting answer..."):
                        ans, src = st.session_state.analyzer.answer_question_with_ollama(
                            st.session_state.sections, q
                        )
                        add_to_conversation(q, ans, src)
                        st.rerun()

        if financial_qs:
            st.markdown("**💰 Financial Performance**")
            for q in financial_qs:
                if st.button(q, key=f"fin_{q[:20]}", use_container_width=True):
                    with st.spinner("Getting answer..."):
                        ans, src = st.session_state.analyzer.answer_question_with_ollama(
                            st.session_state.sections, q
                        )
                        add_to_conversation(q, ans, src)
                        st.rerun()

        if risk_qs:
            st.markdown("**⚠️ Risks & Challenges**")
            for q in risk_qs:
                if st.button(q, key=f"risk_{q[:20]}", use_container_width=True):
                    with st.spinner("Getting answer..."):
                        ans, src = st.session_state.analyzer.answer_question_with_ollama(
                            st.session_state.sections, q
                        )
                        add_to_conversation(q, ans, src)
                        st.rerun()

        if other_qs:
            st.markdown("**🔍 Other Insights**")
            for q in other_qs:
                if st.button(q, key=f"other_{q[:20]}", use_container_width=True):
                    with st.spinner("Getting answer..."):
                        ans, src = st.session_state.analyzer.answer_question_with_ollama(
                            st.session_state.sections, q
                        )
                        add_to_conversation(q, ans, src)
                        st.rerun()

    with tab4:
        st.subheader("📋 Filing Overview")
        
        # Get comprehensive section overview
        if st.session_state.filing_content:
            overview = get_section_overview(st.session_state.filing_content)
            
            # Display overview metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📚 Total Sections", len([s for s in overview['section_details'] if s['found']]))
            with col2:
                st.metric("📝 Total Words", f"{overview['total_words']:,}")
            with col3:
                st.metric("📄 Approx. Pages", f"{overview['total_words'] // 250:,}")
            with col4:
                st.metric("💾 Total Size", f"{overview['total_chars']:,} chars")
            
            st.divider()
            
            # Show detailed section information
            st.markdown("### Section Details")
            st.caption("All standard SEC 10-K sections and their availability")
            
            # Create a table of all sections
            section_data = []
            for section in overview['section_details']:
                section_data.append({
                    "Item": section['item'].upper(),
                    "Section": section['title'],
                    "Words": f"{section['words']:,}" if section['found'] else "0",
                    "Characters": f"{section['chars']:,}" if section['found'] else "0",
                    "Est. Pages": f"{section['words'] / 250:.1f}" if section['found'] else "0",
                    "Status": "✅ Available" if section['found'] else "❌ Not Found"
                })
            
            import pandas as pd
            df = pd.DataFrame(section_data)
            
            # Style the dataframe
            def style_status(val):
                if "✅" in val:
                    return 'background-color: #d4edda'
                else:
                    return 'background-color: #f8d7da'
            
            styled_df = df.style.applymap(style_status, subset=['Status'])
            st.dataframe(styled_df, use_container_width=True)
            
            # Show summary statistics
            found_count = len([s for s in overview['section_details'] if s['found']])
            total_count = len(overview['section_details'])
            
            col1, col2 = st.columns(2)
            with col1:
                st.success(f"✅ Found: {found_count} sections")
            with col2:
                st.warning(f"❌ Missing: {total_count - found_count} sections")
            
            # Show filing metadata
            st.divider()
            st.markdown("### Filing Metadata")
            col1, col2 = st.columns(2)
            with col1:
                st.info(f"**Company:** {st.session_state.company}")
                st.info(f"**CIK:** {st.session_state.cik}")
                st.info(f"**Filing Date:** {st.session_state.filing_date}")
            with col2:
                st.info(f"**Form Type:** 10-K")
                st.info(f"**Accession Number:** {st.session_state.filing['accession_number']}")
                st.info(f"[📄 View on SEC EDGAR]({st.session_state.accession_url})")
        else:
            st.warning("No filing content available. Please analyze a company first.")
    
    with tab5:
        st.subheader("🧠 Intelligent Insights")
        st.caption("AI-powered analysis reading between the lines")
        
        if st.session_state.sections and st.session_state.company:
            # Get intelligent insights
            inference_results = integrate_inference_engine(
                st.session_state.sections, 
                st.session_state.company,
                st.session_state.analyzer.llm if hasattr(st.session_state.analyzer, 'llm') else None
            )
            
            # Display hidden insights
            st.markdown("### 🔍 Hidden Insights & Red Flags")
            st.caption("What the filing doesn't explicitly say but implies")
            
            insights = inference_results.get('insights', [])
            
            if insights:
                for i, insight in enumerate(insights[:5]):  # Show top 5
                    with st.expander(f"{insight.insight[:100]}... (Confidence: {insight.confidence:.0%})", expanded=(i==0)):
                        st.write(f"**Insight:** {insight.insight}")
                        st.write(f"**Category:** {insight.category.replace('_', ' ').title()}")
                        st.write(f"**Confidence:** {insight.confidence:.0%}")
                        
                        if insight.evidence:
                            st.write("**Evidence found in filing:**")
                            for evidence in insight.evidence[:3]:
                                st.caption(f"• {evidence[:200]}...")
                        
                        if insight.suggested_questions:
                            st.write("**Questions to investigate:**")
                            for q in insight.suggested_questions[:3]:
                                if st.button(f"Ask: {q}", key=f"insight_q_{i}_{q[:20]}"):
                                    with st.spinner("Analyzing..."):
                                        ans, src = st.session_state.analyzer.answer_question_with_ollama(
                                            st.session_state.sections, q
                                        )
                                        add_to_conversation(q, ans, src)
                                        st.rerun()
            else:
                st.info("No significant hidden insights detected. This could be a good sign!")
            
            st.divider()
            
            # Smart questions section
            st.markdown("### 💡 Smart Questions You Should Ask")
            st.caption("AI-generated questions based on what's missing or concerning")
            
            smart_questions = inference_results.get('smart_questions', [])
            if smart_questions:
                cols = st.columns(2)
                for i, q in enumerate(smart_questions[:6]):
                    with cols[i % 2]:
                        if st.button(q, key=f"smart_q_{i}", use_container_width=True):
                            with st.spinner("Getting answer..."):
                                ans, src = st.session_state.analyzer.answer_question_with_ollama(
                                    st.session_state.sections, q
                                )
                                add_to_conversation(q, ans, src)
                                st.rerun()
            
            st.divider()
            
            # Web augmentation section
            st.markdown("### 🌐 Web Intelligence")
            st.caption("Real-time context from web searches")
            
            with st.spinner("Searching for recent developments..."):
                augmented_data = create_augmented_summary(
                    st.session_state.company,
                    st.session_state.company,  # Use ticker
                    insights,
                    st.session_state.sections
                )
            
            # Display web insights
            web_insights = augmented_data.get('web_insights', [])
            if web_insights:
                for insight in web_insights[:5]:
                    st.info(insight)
            
            # Research links
            st.markdown("### 🔗 Deep Dive Research Links")
            research_urls = augmented_data.get('research_urls', {})
            
            cols = st.columns(3)
            for i, (name, url) in enumerate(research_urls.items()):
                with cols[i % 3]:
                    st.markdown(f"[📎 {name}]({url})")
            
            # Key topics identified
            if augmented_data.get('key_topics'):
                st.markdown("### 🏷️ Key Topics Detected")
                for topic in augmented_data['key_topics']:
                    tags_html = " ".join([
                        f'<span style="background-color: #e1f5fe; padding: 4px 12px; '
                        f'border-radius: 20px; margin: 4px; display: inline-block; '
                        f'font-size: 14px;">{topic}</span>' 
                        for topic in augmented_data['key_topics']
                    ])
                    st.markdown(tags_html, unsafe_allow_html=True)
        else:
            st.warning("Please analyze a company first to see intelligent insights.")

# ---------- Footer ----------
st.divider()
st.caption("💡 This tool uses Ollama for local LLM processing. All analysis happens on your machine.")
if st.session_state.accession_url:
    st.caption(f"📄 [View Original Filing on SEC EDGAR]({st.session_state.accession_url})")