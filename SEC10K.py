#!/usr/bin/env python3
"""
SEC 10-K Filing Analyzer with Ollama LLM Integration
Enhanced version with natural language support and improved UX
"""

import requests
import json
import re
import time
import os
import subprocess
import sys
import platform
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import argparse
from bs4 import BeautifulSoup
import warnings
from dataclasses import dataclass
from pathlib import Path
import hashlib
import pickle
from requests.adapters import HTTPAdapter, Retry

warnings.filterwarnings('ignore')

# Constants
MAX_CHARS = 6000  # Max characters to send to LLM per section


def _make_session():
    """Create a robust requests session with retries and rate limiting"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "MilesBrown-SEC10K-Analyzer/1.0 (miles@example.com)",
        "Accept-Encoding": "gzip, deflate",
    })
    retries = Retry(total=5, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


@dataclass
class AnalysisResult:
    """Structured result from LLM analysis"""
    summary: str
    key_insights: List[str]
    financial_highlights: Dict[str, str]
    risks: List[str]
    opportunities: List[str]
    confidence_score: float


class OllamaInterface:
    """Interface for Ollama local LLM"""
    
    def __init__(self, model_name: str = "llama3.2", base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url
        self.available_models = []
        self._check_ollama_installation()
        self._check_model_availability()
    
    def _check_ollama_installation(self):
        """Check if Ollama is installed and running"""
        try:
            response = requests.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                print("✅ Ollama is running")
                self.available_models = [m['name'] for m in response.json().get('models', [])]
            else:
                self._start_ollama()
        except requests.exceptions.ConnectionError:
            print("⚠️ Ollama is not running. Attempting to start...")
            self._start_ollama()
    
    def _start_ollama(self):
        """Try to start Ollama service"""
        is_windows = platform.system() == "Windows"
        
        if is_windows:
            print("""
❌ Ollama is not running on Windows.

Please start Ollama manually:
1. Open a new terminal/command prompt
2. Run: ollama serve
3. Keep that terminal open
4. Run this script again in a different terminal

If Ollama is not installed, download from:
https://ollama.com/download/windows
            """)
            sys.exit(1)
        
        try:
            # Try to start Ollama on Unix-like systems
            subprocess.Popen(['ollama', 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)  # Wait for service to start
            
            # Check again
            response = requests.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                print("✅ Successfully started Ollama")
                self.available_models = [m['name'] for m in response.json().get('models', [])]
            else:
                self._provide_installation_instructions()
        except FileNotFoundError:
            self._provide_installation_instructions()
    
    def _provide_installation_instructions(self):
        """Provide instructions for installing Ollama"""
        print("""
❌ Ollama is not installed or cannot be started.

To install Ollama:

macOS/Linux:
  curl -fsSL https://ollama.com/install.sh | sh

Windows:
  Download from: https://ollama.com/download

After installation, start Ollama:
  ollama serve

Then pull a model:
  ollama pull llama3.2

For more info: https://ollama.com
        """)
        sys.exit(1)
    
    def _check_model_availability(self):
        """Check if the specified model is available, if not, pull it"""
        if self.model_name not in self.available_models:
            print(f"📥 Model '{self.model_name}' not found. Downloading...")
            self._pull_model(self.model_name)
    
    def _pull_model(self, model_name: str):
        """Pull a model using Ollama CLI"""
        try:
            print(f"Downloading {model_name}... This may take a few minutes.")
            result = subprocess.run(['ollama', 'pull', model_name], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✅ Successfully downloaded {model_name}")
                self.available_models.append(model_name)
            else:
                print(f"❌ Failed to download {model_name}")
                self._suggest_alternative_model()
        except FileNotFoundError:
            print("❌ Ollama CLI not found. Please install Ollama first.")
            sys.exit(1)
    
    def _suggest_alternative_model(self):
        """Suggest alternative models if download fails"""
        print("\nAvailable models on your system:")
        if self.available_models:
            for model in self.available_models:
                print(f"  • {model}")
            if self.available_models:
                self.model_name = self.available_models[0]
                print(f"\n✅ Using available model: {self.model_name}")
        else:
            print("  No models available. Trying to pull a lightweight model...")
            self._pull_model("phi3")
            if "phi3" in self.available_models:
                self.model_name = "phi3"
    
    def generate(self, prompt: str, max_tokens: int = 1000, temperature: float = 0.3, 
                system_prompt: str = None) -> str:
        """Generate text using Ollama"""
        try:
            data = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            if system_prompt:
                data["system"] = system_prompt
            
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=data,
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get('response', '')
            else:
                print(f"Error from Ollama: {response.status_code}")
                return ""
                
        except Exception as e:
            print(f"Error generating response: {e}")
            return ""
    
    def chat(self, messages, max_tokens=800, temperature=0.3):
        """Chat endpoint using /api/chat for better context handling"""
        data = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        try:
            r = requests.post(f"{self.base_url}/api/chat", json=data, timeout=120)
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "")
        except Exception as e:
            print(f"Chat error: {e}")
            return self.generate(messages[-1].get("content", ""), max_tokens, temperature)
    
    def list_models(self) -> List[str]:
        """List available models"""
        return self.available_models


class SEC10KAnalyzerOllama:
    """SEC 10-K analyzer using Ollama for local LLM analysis"""
    
    RECOMMENDED_MODELS = [
        "llama3.2",
        "mistral",
        "phi3",
        "qwen2.5",
        "gemma2",
        "llama3.2:1b",
    ]
    
    def __init__(self, model_name: str = None):
        self.base_url = "https://data.sec.gov"
        self.session = _make_session()  # Use robust session
        self.filing_cache = {}
        self.analysis_cache = {}
        self.cache_dir = Path.home() / '.sec_analyzer_cache'
        self.cache_dir.mkdir(exist_ok=True)
        
        # Store current filing info for citations
        self.current_accession_url = None
        self.current_filing_date = None
        
        # Initialize Ollama
        if model_name:
            self.llm = OllamaInterface(model_name)
        else:
            self.llm = self._auto_select_model()
        
        print(f"🤖 Using Ollama model: {self.llm.model_name}")
    
    def _auto_select_model(self) -> OllamaInterface:
        """Automatically select the best available model"""
        ollama = OllamaInterface("llama3.2")
        
        available = ollama.list_models()
        for model in self.RECOMMENDED_MODELS:
            if model in available:
                print(f"✅ Found recommended model: {model}")
                ollama.model_name = model
                return ollama
        
        if available:
            ollama.model_name = available[0]
            print(f"ℹ️ Using available model: {ollama.model_name}")
        else:
            print("📥 No models found. Downloading recommended model...")
            ollama._pull_model("llama3.2")
            ollama.model_name = "llama3.2"
        
        return ollama
    
    def resolve_company_from_text(self, text: str) -> Optional[Tuple[str, str, str]]:
        """Detect company/ticker from natural language text
        Returns (ticker, title, cik) or None"""
        try:
            r = self.session.get("https://www.sec.gov/files/company_tickers.json")
            r.raise_for_status()
            time.sleep(0.2)  # Rate limiting
            data = r.json()
            
            # Build ticker lookup
            by_ticker = {v['ticker'].upper(): v for v in data.values()}
            
            # Quick ticker pass - look for exact ticker matches
            tokens = re.findall(r"[A-Za-z]{1,5}", text.upper())
            for t in tokens:
                if t in by_ticker:
                    v = by_ticker[t]
                    return v['ticker'], v['title'], str(v['cik_str']).zfill(10)
            
            # Fuzzy title pass - look for company name matches
            q = text.lower()
            for v in data.values():
                title_lower = v['title'].lower()
                # Check if any significant word from query matches the title
                if any(w for w in q.split() if len(w) > 2 and w in title_lower):
                    return v['ticker'], v['title'], str(v['cik_str']).zfill(10)
            
            return None
        except Exception as e:
            print(f"Error resolving company: {e}")
            return None
    
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text"""
        return hashlib.md5(f"{self.llm.model_name}_{text[:1000]}".encode()).hexdigest()
    
    def _load_from_cache(self, cache_key: str) -> Optional[Dict]:
        """Load analysis from cache"""
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    cached = pickle.load(f)
                    if cached.get('model') == self.llm.model_name:
                        return cached.get('data')
            except Exception:
                pass
        return None
    
    def _save_to_cache(self, cache_key: str, data: Dict):
        """Save analysis to cache with model info"""
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        try:
            cache_data = {
                'model': self.llm.model_name,
                'timestamp': datetime.now().isoformat(),
                'data': data
            }
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
        except Exception:
            pass
    
    def get_company_cik(self, company_name: str) -> Optional[str]:
        """Get CIK for a company"""
        tickers_url = "https://www.sec.gov/files/company_tickers.json"
        
        try:
            response = self.session.get(tickers_url)
            response.raise_for_status()
            time.sleep(0.2)  # Rate limiting
            companies = response.json()
            
            company_search = company_name.upper()
            for key, company in companies.items():
                if (company['ticker'] == company_search or 
                    company_search in company['title'].upper()):
                    cik = str(company['cik_str']).zfill(10)
                    print(f"Found company: {company['title']} (CIK: {cik})")
                    return cik
                    
        except Exception as e:
            print(f"Error searching for company: {e}")
            
        return None
    
    def get_recent_10k_filings(self, cik: str, num_filings: int = 1) -> List[Dict]:
        """Get recent 10-K filings"""
        submissions_url = f"{self.base_url}/submissions/CIK{cik}.json"
        
        try:
            response = self.session.get(submissions_url)
            response.raise_for_status()
            time.sleep(0.2)  # Rate limiting
            data = response.json()
            
            filings = []
            recent_filings = data.get('filings', {}).get('recent', {})
            
            for i in range(len(recent_filings.get('form', []))):
                if recent_filings['form'][i] in ['10-K', '10-K/A'] and len(filings) < num_filings:
                    filing = {
                        'form': recent_filings['form'][i],
                        'filing_date': recent_filings['filingDate'][i],
                        'accession_number': recent_filings['accessionNumber'][i].replace('-', ''),
                        'primary_document': recent_filings['primaryDocument'][i],
                        'report_date': recent_filings.get('reportDate', [None])[i]
                    }
                    filings.append(filing)
            
            return filings
            
        except Exception as e:
            print(f"Error fetching filings: {e}")
            return []
    
    def _best_10k_doc_url(self, cik: str, filing: Dict) -> str:
        """Choose the best 10-K document URL using index.json"""
        try:
            acc = filing['accession_number']
            index_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc}/index.json"
            r = self.session.get(index_url, timeout=30)
            r.raise_for_status()
            time.sleep(0.2)  # Rate limiting
            
            items = r.json().get("directory", {}).get("item", [])
            htmls = [it for it in items if it["name"].lower().endswith((".htm", ".html"))]
            
            # Sort: prefer files with '10k' in name, then by size
            htmls.sort(key=lambda it: ("10k" not in it["name"].lower(), -it.get("size", 0)))
            
            fname = htmls[0]["name"] if htmls else filing["primary_document"]
            return f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc}/{fname}"
            
        except Exception as e:
            # Fallback to primary document
            return (f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
                   f"{filing['accession_number']}/{filing['primary_document']}")
    
    def fetch_10k_content(self, cik: str, filing: Dict) -> Optional[str]:
        """Fetch the actual 10-K filing content"""
        cache_key = f"{cik}_{filing['accession_number']}"
        if cache_key in self.filing_cache:
            return self.filing_cache[cache_key]
        
        # Try best URL first
        doc_url = self._best_10k_doc_url(cik, filing)
        
        try:
            print(f"Fetching 10-K from SEC EDGAR...")
            response = self.session.get(doc_url)
            response.raise_for_status()
            time.sleep(0.2)  # Rate limiting
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for script in soup(['script', 'style']):
                script.decompose()
            
            # Preserve line breaks for better section detection
            text = soup.get_text("\n")
            text = re.sub(r'\n{3,}', '\n\n', text)
            
            self.filing_cache[cache_key] = text
            return text
            
        except Exception as e:
            print(f"Error fetching filing content: {e}")
            return None
    
    def extract_sections(self, content: str) -> Dict[str, str]:
        """Extract major sections from 10-K filing with improved patterns"""
        sections = {
            'business': '',
            'risk_factors': '',
            'financial_data': '',
            'mda': '',
            'financial_statements': ''
        }
        
        if not content:
            return sections
        
        # Improved patterns for better extraction
        patterns = {
            'business': r'(?is)(item\s+1\.*\s*business.*?)(?=item\s+1a\b|item\s+2\b)',
            'risk_factors': r'(?is)(item\s+1a\.*\s*risk\s*factors.*?)(?=item\s+1b\b|item\s+2\b)',
            'financial_data': r'(?is)(item\s+6\.*\s*selected\s*financial.*?)(?=item\s+7\b)|(?is)(selected\s*financial\s*data.*?)(?=item\s+7\b)',
            'mda': r'(?is)(item\s+7\.*\s*management.*?discussion.*?analysis.*?)(?=item\s+7a\b|item\s+8\b)',
            'financial_statements': r'(?is)(item\s+8\.*\s*financial\s*statements.*?)(?=item\s+9\b)'
        }
        
        for section, pattern in patterns.items():
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                sections[section] = match.group(1)[:15000]
        
        # If financial_data is empty, use MDA as fallback
        if not sections['financial_data'] and sections['mda']:
            sections['financial_data'] = sections['mda'][:8000]
        
        return sections
    
    def get_suggested_questions(self, company: str, sections: Dict[str, str]) -> List[str]:
        """Generate smart suggested questions based on filing content"""
        name = company.strip()
        qs = [
            f"What does {name} list as its core business and main products?",
            f"What are {name}'s primary revenue sources and segments?",
            f"What are the top risks {name} highlights in this filing?",
            f"What trends does management discuss in MD&A for the latest year?",
        ]
        
        if sections.get("business"):
            qs += [
                f"Who are {name}'s principal competitors?",
                f"Which customer groups or industries does {name} serve?",
            ]
        
        fin_text = sections.get("financial_data") or sections.get("mda")
        if fin_text:
            qs += [
                f"What were {name}'s revenue and net income trends year over year?",
                f"What does {name} report about margins, cash flow, and debt levels?",
                f"Did {name} repurchase shares or issue dividends in the period?",
            ]
        
        if sections.get("risk_factors"):
            qs += [
                f"Are there regulatory or geopolitical risks mentioned for {name}?",
                f"Does {name} cite customer concentration or supply chain risks?",
            ]
        
        # Check for segment/geography mentions
        joined = " ".join((sections.get("business", ""), sections.get("mda", ""))).lower()
        if any(k in joined for k in ["segment", "segments"]):
            qs.append(f"How does {name}'s performance break down by segment?")
        if any(k in joined for k in ["geograph", "international", "americas", "emea", "apac"]):
            qs.append(f"How is {name}'s revenue distributed by geography?")
        
        # Remove duplicates while preserving order
        seen, out = set(), []
        for q in qs:
            if q not in seen:
                seen.add(q)
                out.append(q)
        
        return out[:12]
    
    def _rank_sections(self, sections: Dict[str, str], query: str) -> List[str]:
        """Simple relevance ranking for sections based on query"""
        terms = [t for t in re.findall(r'\w+', query.lower()) if len(t) > 2]
        
        def score(txt: str):
            if not txt:
                return 0.0
            L = max(500, len(txt))
            t = txt.lower()
            return sum(t.count(w) for w in terms) / L
        
        ranked = sorted(sections.items(), key=lambda kv: score(kv[1]), reverse=True)
        return [kv[0] for kv in ranked[:3]]
    
    def analyze_section_with_ollama(self, section_name: str, section_content: str) -> Dict:
        """Use Ollama to analyze a section"""
        if not section_content:
            return {'summary': 'No content available.', 'insights': []}
        
        cache_key = self._get_cache_key(f"{section_name}_{section_content[:500]}")
        cached = self._load_from_cache(cache_key)
        if cached:
            print(f"  📂 Using cached analysis for {section_name}")
            return cached
        
        print(f"  🔍 Analyzing {section_name} with {self.llm.model_name}...")
        
        # Use chat endpoint for better results
        messages = [
            {"role": "system", "content": "You are a financial analyst. Be precise and factual."},
            {"role": "user", "content": f"""Analyze this {section_name} section from a 10-K filing.

Section content (truncated):
{section_content[:MAX_CHARS]}

Provide:
1. Brief summary (2 sentences max)
2. Top 3 key points
3. Important numbers or metrics
4. Main concern if any

Be concise and specific. Focus on facts and numbers."""}
        ]
        
        response = self.llm.chat(messages, max_tokens=500, temperature=0.3)
        
        result = self._parse_analysis_response(response, section_name)
        self._save_to_cache(cache_key, result)
        
        return result
    
    def _parse_analysis_response(self, response: str, section_name: str) -> Dict:
        """Parse the LLM response into structured format"""
        result = {
            'summary': '',
            'insights': [],
            'metrics': {},
            'concerns': []
        }
        
        if not response:
            return result
        
        lines = response.split('\n')
        current_section = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if 'summary' in line.lower() or line.startswith('1.'):
                current_section = 'summary'
            elif 'key point' in line.lower() or 'top 3' in line.lower() or line.startswith('2.'):
                current_section = 'insights'
            elif 'number' in line.lower() or 'metric' in line.lower() or line.startswith('3.'):
                current_section = 'metrics'
            elif 'concern' in line.lower() or line.startswith('4.'):
                current_section = 'concerns'
            
            if current_section == 'summary' and not line.startswith(('1.', 'Summary')):
                result['summary'] += line + ' '
            elif current_section == 'insights' and not line.startswith(('2.', 'Key', 'Top')):
                if line.startswith(('•', '-', '*')) or any(line.startswith(str(i)) for i in range(1, 10)):
                    result['insights'].append(line.lstrip('•-* 123456789.'))
            elif current_section == 'metrics' and not line.startswith(('3.', 'Number', 'Metric')):
                if ':' in line:
                    key, value = line.split(':', 1)
                    result['metrics'][key.strip()] = value.strip()
            elif current_section == 'concerns' and not line.startswith(('4.', 'Concern')):
                result['concerns'].append(line.lstrip('•-* '))
        
        result['summary'] = result['summary'].strip()
        result['insights'] = result['insights'][:3]
        
        return result
    
    def answer_question_with_ollama(self, sections: Dict[str, str], question: str) -> Tuple[str, str]:
        """Use Ollama to answer questions about the filing
        Returns (answer, section_source)"""
        
        # Rank sections by relevance
        ranked_sections = self._rank_sections(sections, question)
        
        # Build relevant content from top sections
        relevant_content = ""
        section_sources = []
        chars_per_section = MAX_CHARS // 3
        
        for section_key in ranked_sections[:3]:
            if sections.get(section_key):
                relevant_content += f"\n[{section_key.upper()}]\n{sections[section_key][:chars_per_section]}\n"
                section_sources.append(section_key.upper())
        
        if not relevant_content:
            return "I couldn't find relevant information to answer your question.", "UNKNOWN"
        
        print("  🤔 Processing your question with Ollama...")
        
        messages = [
            {"role": "system", "content": "You are a financial analyst reviewing SEC filings. Be factual and precise."},
            {"role": "user", "content": f"""Based on this 10-K filing content, answer the question below.

Question: {question}

Relevant filing sections:
{relevant_content}

Provide a direct, factual answer using specific information from the filing.
Include numbers, dates, and concrete details where available.
If the information isn't clearly stated, say so.
Keep your answer concise (2-3 sentences)."""}
        ]
        
        response = self.llm.chat(messages, max_tokens=300, temperature=0.2)
        
        answer = response if response else "Unable to generate an answer. Please try rephrasing your question."
        source = ", ".join(section_sources[:2]) if section_sources else "MULTIPLE SECTIONS"
        
        return answer, source
    
    def generate_executive_summary(self, company_name: str, sections: Dict[str, str]) -> AnalysisResult:
        """Generate executive summary using Ollama"""
        print("\n🎯 Generating executive summary with Ollama...")
        
        # Use financial_data or MDA as fallback
        fin_section = sections.get('financial_data') or sections.get('mda', '')
        
        condensed = f"""
Company: {company_name}

Business Overview: {sections.get('business', '')[:2000]}

Financial Highlights: {fin_section[:2000]}

Management Discussion: {sections.get('mda', '')[:2000]}

Risk Factors: {sections.get('risk_factors', '')[:2000]}
"""
        
        messages = [
            {"role": "system", "content": "You are a financial analyst creating an executive briefing."},
            {"role": "user", "content": f"""Create an executive summary of this 10-K filing:

{condensed}

Provide:
1. Executive Summary (3 sentences)
2. Top 3 insights
3. Key financial metrics
4. Top 3 risks
5. Top 3 opportunities

Format each section clearly with headers."""}
        ]
        
        response = self.llm.chat(messages, max_tokens=800, temperature=0.3)
        
        return self._parse_executive_summary(response)
    
    def _parse_executive_summary(self, response: str) -> AnalysisResult:
        """Parse executive summary response"""
        lines = response.split('\n') if response else []
        
        result = AnalysisResult(
            summary="Analysis in progress...",
            key_insights=[],
            financial_highlights={},
            risks=[],
            opportunities=[],
            confidence_score=0.75
        )
        
        current_section = None
        summary_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if 'executive summary' in line.lower() or line.startswith('1.'):
                current_section = 'summary'
            elif 'insight' in line.lower() or line.startswith('2.'):
                current_section = 'insights'
            elif 'financial' in line.lower() or 'metric' in line.lower() or line.startswith('3.'):
                current_section = 'financial'
            elif 'risk' in line.lower() or line.startswith('4.'):
                current_section = 'risks'
            elif 'opportunit' in line.lower() or line.startswith('5.'):
                current_section = 'opportunities'
            else:
                if current_section == 'summary':
                    summary_lines.append(line)
                elif current_section == 'insights' and len(result.key_insights) < 5:
                    if line.startswith(('•', '-', '*')) or any(line.startswith(str(i)) for i in range(1, 10)):
                        result.key_insights.append(line.lstrip('•-* 123456789.'))
                elif current_section == 'financial':
                    if ':' in line:
                        key, value = line.split(':', 1)
                        result.financial_highlights[key.strip()] = value.strip()
                elif current_section == 'risks' and len(result.risks) < 5:
                    if line.startswith(('•', '-', '*')) or any(line.startswith(str(i)) for i in range(1, 10)):
                        result.risks.append(line.lstrip('•-* 123456789.'))
                elif current_section == 'opportunities' and len(result.opportunities) < 5:
                    if line.startswith(('•', '-', '*')) or any(line.startswith(str(i)) for i in range(1, 10)):
                        result.opportunities.append(line.lstrip('•-* 123456789.'))
        
        result.summary = ' '.join(summary_lines)[:500]
        
        return result
    
    def analyze_company(self, company_name: str, questions: Optional[List[str]] = None,
                       non_interactive: bool = False, save_json: Optional[str] = None,
                       initial_ask: Optional[str] = None):
        """Main method to analyze a company's 10-K filing"""
        print(f"\n{'='*60}")
        print(f"SEC 10-K Analyzer with Ollama (Free Local LLM)")
        print(f"{'='*60}")
        print(f"Company: {company_name}")
        print(f"Model: {self.llm.model_name}")
        print(f"{'='*60}\n")
        
        # Get company CIK
        cik = self.get_company_cik(company_name)
        if not cik:
            print(f"Could not find company: {company_name}")
            print("Try using the exact ticker symbol (e.g., AAPL, MSFT, GOOGL)")
            return
        
        # Get recent 10-K filings
        filings = self.get_recent_10k_filings(cik)
        if not filings:
            print("No recent 10-K filings found")
            return
        
        filing = filings[0]
        print(f"📅 Using filing from: {filing['filing_date']}")
        
        # Store filing info for citations
        accession = filing['accession_number']
        self.current_accession_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/index.html"
        self.current_filing_date = filing['filing_date']
        
        # Fetch filing content
        content = self.fetch_10k_content(cik, filing)
        if not content:
            print("Could not fetch filing content")
            return
        
        print(f"✅ Successfully fetched 10-K content ({len(content):,} characters)")
        
        # Extract sections
        print("\n📋 Extracting filing sections...")
        sections = self.extract_sections(content)
        
        # Generate and show suggested questions
        suggested_questions = self.get_suggested_questions(company_name, sections)
        print("\n💡 Suggested questions you can ask:")
        for q in suggested_questions:
            print(f"  • {q}")
        print("\n(Type ':suggest' in Q&A to see these again)")
        
        # Generate executive summary
        analysis = self.generate_executive_summary(company_name, sections)
        
        print("\n" + "="*60)
        print("EXECUTIVE SUMMARY (AI-Generated)")
        print("="*60)
        
        print(f"\n{analysis.summary}")
        
        if analysis.key_insights:
            print(f"\n### Key Insights ###")
            for i, insight in enumerate(analysis.key_insights[:3], 1):
                print(f"{i}. {insight}")
        
        if analysis.financial_highlights:
            print(f"\n### Financial Highlights ###")
            for metric, value in list(analysis.financial_highlights.items())[:5]:
                print(f"• {metric}: {value}")
        
        if analysis.risks:
            print(f"\n### Top Risks ###")
            for i, risk in enumerate(analysis.risks[:3], 1):
                print(f"{i}. {risk}")
        
        if analysis.opportunities:
            print(f"\n### Opportunities ###")
            for i, opp in enumerate(analysis.opportunities[:3], 1):
                print(f"{i}. {opp}")
        
        # Save JSON if requested
        if save_json:
            payload = {
                "company": company_name,
                "cik": cik,
                "filing_date": filing['filing_date'],
                "accession_url": self.current_accession_url,
                "summary": analysis.summary,
                "key_insights": analysis.key_insights,
                "financial_highlights": analysis.financial_highlights,
                "risks": analysis.risks,
                "opportunities": analysis.opportunities
            }
            with open(save_json, "w") as f:
                json.dump(payload, f, indent=2)
            print(f"\n✅ Analysis saved to {save_json}")
        
        # Answer specific questions
        if questions or initial_ask:
            print("\n" + "="*60)
            print("ANSWERS TO YOUR QUESTIONS")
            print("="*60)
            
            all_questions = questions or []
            if initial_ask and initial_ask not in all_questions:
                all_questions.insert(0, initial_ask)
            
            for question in all_questions:
                print(f"\n❓ Q: {question}")
                answer, source = self.answer_question_with_ollama(sections, question)
                print(f"💡 A: {answer}")
                print(f"📍 Source: {source}, filed {self.current_filing_date} — {self.current_accession_url}")
        
        # Interactive Q&A mode (skip if non-interactive)
        if not non_interactive:
            print("\n" + "="*60)
            print("INTERACTIVE Q&A MODE")
            print("="*60)
            print("Ask questions about the 10-K filing (type 'quit' to exit, ':suggest' for suggestions)")
            print(f"AI Model: {self.llm.model_name}")
            
            while True:
                question = input("\n❓ Your question: ").strip()
                
                if question.lower() in ['quit', 'exit', 'q']:
                    break
                
                if question.lower() in [':suggest', 'suggest']:
                    print("\n💡 Suggested questions:")
                    for q in suggested_questions:
                        print(f"  • {q}")
                    continue
                
                if question:
                    answer, source = self.answer_question_with_ollama(sections, question)
                    print(f"\n💡 Answer: {answer}")
                    print(f"📍 Source: {source}, filed {self.current_filing_date} — {self.current_accession_url}")
        
        print("\n✅ Analysis complete!")


def main():
    parser = argparse.ArgumentParser(description='SEC 10-K Analyzer with Ollama (Free Local LLM)')
    parser.add_argument('company', type=str, nargs='?', help='Company name or ticker symbol')
    parser.add_argument('--model', type=str, default=None,
                       help='Ollama model to use (e.g., llama3.2, mistral, phi3)')
    parser.add_argument('--questions', type=str, nargs='*',
                       help='Specific questions to answer')
    parser.add_argument('--ask', type=str, 
                       help='Natural-language question; auto-detect company')
    parser.add_argument('--non-interactive', action='store_true',
                       help='Skip interactive Q&A loop')
    parser.add_argument('--save-json', type=str,
                       help='Save executive summary JSON to a file')
    parser.add_argument('--list-models', action='store_true',
                       help='List recommended Ollama models')
    parser.add_argument('--clear-cache', action='store_true',
                       help='Clear analysis cache')
    
    args = parser.parse_args()
    
    if args.list_models:
        print("""
╔══════════════════════════════════════════════════════════════════╗
║            RECOMMENDED OLLAMA MODELS FOR FINANCIAL ANALYSIS      ║
╚══════════════════════════════════════════════════════════════════╝

Best for Quality (Larger models, slower):
  • llama3.2        - Best overall, 3B parameters
  • mistral         - Great for structured data, 7B parameters  
  • qwen2.5         - Excellent reasoning, 7B parameters

Best for Speed (Smaller models, faster):
  • phi3            - Microsoft's efficient model, 3.8B
  • llama3.2:1b     - Ultra-fast, 1B parameters
  • tinyllama       - Very fast, 1.1B parameters

To install: ollama pull llama3.2
        """)
        return
    
    # Clear cache if requested
    if args.clear_cache:
        cache_dir = Path.home() / '.sec_analyzer_cache'
        if cache_dir.exists():
            import shutil
            shutil.rmtree(cache_dir)
            print("✅ Cache cleared")
    
    # Create analyzer
    analyzer = SEC10KAnalyzerOllama(model_name=args.model)
    
    # Handle natural language ask
    company_name = args.company
    initial_ask = args.ask
    
    if args.ask and not args.company:
        # Try to detect company from the ask text
        print(f"🔍 Analyzing: '{args.ask}'")
        result = analyzer.resolve_company_from_text(args.ask)
        if result:
            ticker, title, cik = result
            print(f"✅ Detected company: {title} ({ticker})")
            company_name = ticker
            initial_ask = args.ask
        else:
            print("❌ Could not detect company from your question.")
            print("Please specify a ticker symbol or company name.")
            return
    
    if not company_name:
        print("Please specify a company or use --ask with a natural language question")
        return
    
    # Analyze company
    analyzer.analyze_company(
        company_name,
        args.questions,
        non_interactive=args.non_interactive,
        save_json=args.save_json,
        initial_ask=initial_ask
    )


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) == 1:
        print("""
╔══════════════════════════════════════════════════════════════════╗
║        SEC 10-K ANALYZER WITH OLLAMA (FREE LOCAL LLM)           ║
╚══════════════════════════════════════════════════════════════════╝

Natural Language Support - Just ask questions!

EXAMPLES:
─────────
Natural language query:
  python sec_10k_ollama.py --ask "how is nvidia doing?"

Traditional usage:
  python sec_10k_ollama.py AAPL

With questions:
  python sec_10k_ollama.py MSFT --questions "Revenue?" "AI strategy?"

Non-interactive mode:
  python sec_10k_ollama.py GOOGL --non-interactive --save-json analysis.json

FEATURES:
─────────
• Auto-detects companies from natural language
• Smart question suggestions based on filing content
• Citations with SEC accession URLs
• Robust retry logic and rate limiting
• JSON export for further analysis

Type ':suggest' in Q&A mode to see suggested questions again.

Starting demo...
        """)
        
        # Check if Ollama is available
        try:
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                print("\n✅ Ollama is running! Starting demo...")
                analyzer = SEC10KAnalyzerOllama()
                analyzer.analyze_company("AAPL", ["What are the main revenue sources?"],
                                       non_interactive=True)
        except:
            print("\n❌ Ollama is not running. Please install:")
            print("  curl -fsSL https://ollama.com/install.sh | sh")
            print("  ollama serve")
    else:
        main()