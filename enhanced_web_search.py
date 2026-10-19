# enhanced_web_search.py
"""
Enhanced Web Search with Google fallback for comprehensive answers
"""

import requests
import re
from typing import Dict, List, Tuple
from datetime import datetime
import urllib.parse

class EnhancedWebSearch:
    """
    Provides comprehensive web search with multiple fallback options
    """

    def __init__(self):
        self.search_engines = {
            'duckduckgo': self._search_duckduckgo,
            'google': self._search_google_cse,
            'serp': self._search_serp_api
        }

    def search_with_fallback(self, query: str, company: str = None) -> Dict:
        """
        Search with multiple fallback options
        """
        results = {
            'direct_answer': None,
            'web_results': [],
            'competitor_info': [],
            'sources': [],
            'confidence': 0.0
        }

        # Try multiple search strategies
        strategies = [
            f"{query} {company} SEC filing",
            f"{query} {company} investor relations",
            f"{query} {company} annual report",
            f"{query} industry analysis",
            query  # Raw query
        ]

        all_results = []
        for strategy in strategies:
            search_results = self._search_duckduckgo(strategy)
            if search_results:
                all_results.extend(search_results)

        results['web_results'] = all_results[:10]

        # Extract key information
        if all_results:
            results['direct_answer'] = self._extract_answer(all_results, query)
            results['sources'] = self._format_sources(all_results[:5])
            results['confidence'] = min(0.8, len(all_results) * 0.1)

        return results

    def _search_duckduckgo(self, query: str) -> List[Dict]:
        """
        Free search using DuckDuckGo Instant Answer API
        """
        try:
            # HTML search (more comprehensive than instant answer API)
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(url, headers=headers, timeout=5)

            # Parse HTML results (simplified)
            results = []

            # Extract snippets using regex (simplified parsing)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', response.text, re.DOTALL)
            titles = re.findall(r'class="result__title"[^>]*>(.*?)</a>', response.text, re.DOTALL)

            for i, (title, snippet) in enumerate(zip(titles[:5], snippets[:5])):
                # Clean HTML
                title = re.sub('<[^>]+>', '', title).strip()
                snippet = re.sub('<[^>]+>', '', snippet).strip()

                results.append({
                    'title': title,
                    'snippet': snippet,
                    'url': f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
                    'source': 'DuckDuckGo'
                })

            return results

        except requests.RequestException as e:
            print(f"DuckDuckGo search error: {e}")
            return []

    def _search_google_cse(self, query: str) -> List[Dict]:
        """
        Google Custom Search Engine (requires API key)
        Free tier: 100 queries/day
        """
        # Get free API key from: https://developers.google.com/custom-search/v1/introduction
        api_key = "YOUR_GOOGLE_API_KEY"  # User needs to add their key
        cx = "YOUR_SEARCH_ENGINE_ID"  # User needs to add their CSE ID

        if api_key == "YOUR_GOOGLE_API_KEY":
            return []  # Not configured

        try:
            url = f"https://www.googleapis.com/customsearch/v1"
            params = {
                'key': api_key,
                'cx': cx,
                'q': query,
                'num': 5
            }

            response = requests.get(url, params=params, timeout=5)
            data = response.json()

            results = []
            for item in data.get('items', []):
                results.append({
                    'title': item.get('title'),
                    'snippet': item.get('snippet'),
                    'url': item.get('link'),
                    'source': 'Google'
                })

            return results

        except requests.RequestException as e:
            print(f"Google search error: {e}")
            return []

    def _search_serp_api(self, query: str) -> List[Dict]:
        """
        SerpAPI - Professional search API (paid but reliable)
        """
        # Get API key from: https://serpapi.com/
        api_key = "YOUR_SERPAPI_KEY"

        if api_key == "YOUR_SERPAPI_KEY":
            return []

        try:
            url = "https://serpapi.com/search"
            params = {
                'q': query,
                'api_key': api_key,
                'engine': 'google',
                'num': 5
            }

            response = requests.get(url, params=params, timeout=5)
            data = response.json()

            results = []
            for result in data.get('organic_results', []):
                results.append({
                    'title': result.get('title'),
                    'snippet': result.get('snippet'),
                    'url': result.get('link'),
                    'source': 'Google (via SerpAPI)'
                })

            return results

        except requests.RequestException as e:
            print(f"SerpAPI error: {e}")
            return []

    def _extract_answer(self, results: List[Dict], query: str) -> str:
        """
        Extract the most relevant answer from search results
        """
        if not results:
            return None

        # Simple relevance scoring
        query_words = set(query.lower().split())
        best_snippet = ""
        best_score = 0

        for result in results:
            snippet = result.get('snippet', '')
            snippet_words = set(snippet.lower().split())

            # Calculate overlap
            overlap = len(query_words & snippet_words)
            if overlap > best_score:
                best_score = overlap
                best_snippet = snippet

        return best_snippet if best_score > 2 else None

    def _format_sources(self, results: List[Dict]) -> List[str]:
        """
        Format sources with clickable links
        """
        sources = []
        for result in results:
            title = result.get('title', 'Web Result')
            url = result.get('url', '#')
            sources.append(f"[{title}]({url})")
        return sources

    def search_competitor_info(self, query: str, peers: List[str] = None) -> Dict:
        """
        Search for information from competitor filings.

        `peers` should be supplied by the caller (typically the tickers
        already discovered by peer_analysis.get_peer_companies) so this
        works for any company instead of only the handful that used to be
        hardcoded here.
        """
        comp_results = {}
        if not peers:
            return comp_results

        for comp in peers[:3]:
            search_query = f"{comp} {query} 10-K filing"
            results = self._search_duckduckgo(search_query)
            if results:
                comp_results[comp] = results[0].get('snippet', '')

        return comp_results

    def generate_search_urls(self, query: str, company: str) -> Dict[str, str]:
        """
        Generate direct search URLs for manual exploration
        """
        encoded_query = urllib.parse.quote(f"{company} {query}")

        return {
            '🔍 Google Search': f"https://www.google.com/search?q={encoded_query}",
            '📈 Yahoo Finance': f"https://finance.yahoo.com/quote/{company}",
            '📊 MarketWatch': f"https://www.marketwatch.com/search?q={encoded_query}",
            '📰 Google News': f"https://news.google.com/search?q={encoded_query}",
            '🏢 SEC EDGAR': f"https://www.sec.gov/edgar/search/#/q={encoded_query}",
            '💬 Reddit': f"https://www.reddit.com/search/?q={encoded_query}",
            '📚 Google Scholar': f"https://scholar.google.com/scholar?q={encoded_query}",
            '🐦 X/Twitter': f"https://twitter.com/search?q=${company}%20{urllib.parse.quote(query)}"
        }


class IntelligentAnswerEngine:
    """
    Provides comprehensive answers using filing data + web search
    """

    def __init__(self, sections: Dict, company: str, peers: List[str] = None):
        self.sections = sections
        self.company = company
        self.peers = peers or []
        self.web_search = EnhancedWebSearch()

    def answer_with_fallback(self, question: str) -> Dict:
        """
        Answer question using filing, then web search if needed
        """
        response = {
            'answer': None,
            'source': None,
            'found_in_filing': False,
            'web_results': [],
            'search_urls': {},
            'confidence': 0.0
        }

        # First, check if answer is in filing
        filing_answer = self._search_filing(question)

        if filing_answer['found']:
            response['answer'] = filing_answer['answer']
            response['source'] = filing_answer['source']
            response['found_in_filing'] = True
            response['confidence'] = filing_answer['confidence']
        else:
            # Fallback to web search
            response['answer'] = (
                f"This information is not explicitly stated in the {self.company} 10-K filing. "
                f"However, based on web search:\n\n"
            )

            # Search the web
            web_results = self.web_search.search_with_fallback(question, self.company)

            if web_results['direct_answer']:
                response['answer'] += web_results['direct_answer']
                response['web_results'] = web_results['sources']
                response['confidence'] = web_results['confidence']
            else:
                response['answer'] += (
                    "I couldn't find a definitive answer, but you can explore these resources:"
                )

            # Always provide search URLs
            response['search_urls'] = self.web_search.generate_search_urls(question, self.company)

            # Check competitor filings (uses the peers discovered for this
            # company, not a hardcoded shortlist)
            comp_info = self.web_search.search_competitor_info(question, self.peers)
            if comp_info:
                response['answer'] += "\n\nFrom competitor filings:\n"
                for comp, info in comp_info.items():
                    response['answer'] += f"• {comp}: {info[:200]}...\n"

        return response

    def _search_filing(self, question: str) -> Dict:
        """
        Search for answer in filing sections
        """
        question_lower = question.lower()
        best_match = {
            'found': False,
            'answer': None,
            'source': None,
            'confidence': 0.0
        }

        # Keywords to section mapping
        keyword_sections = {
            'revenue': ['financial_data', 'mda'],
            'risk': ['risk_factors'],
            'business': ['business'],
            'competition': ['business', 'risk_factors'],
            'employee': ['business'],
            'product': ['business', 'mda'],
            'debt': ['financial_data', 'mda'],
            'cash': ['financial_data', 'mda']
        }

        # Find relevant sections
        relevant_sections = []
        for keyword, sections in keyword_sections.items():
            if keyword in question_lower:
                relevant_sections.extend(sections)

        if not relevant_sections:
            relevant_sections = ['business', 'mda', 'risk_factors']  # Default

        # Search in relevant sections
        for section_name in relevant_sections:
            if section_name in self.sections and self.sections[section_name]:
                section_text = self.sections[section_name][:10000]

                # Simple keyword matching (could be enhanced with NLP)
                if any(word in section_text.lower() for word in question_lower.split()):
                    # Extract relevant paragraph
                    paragraphs = section_text.split('\n\n')
                    for para in paragraphs:
                        if any(word in para.lower() for word in question_lower.split()[:3]):
                            best_match['found'] = True
                            best_match['answer'] = para[:500]
                            best_match['source'] = section_name.upper()
                            best_match['confidence'] = 0.7
                            return best_match

        return best_match
