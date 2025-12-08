# web_search_augmentation.py
"""
Web Search Augmentation for SEC 10-K Analysis
Adds real-time context and news to filing analysis
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List
import streamlit as st

class WebSearchAugmentation:
    """
    Augments SEC filing analysis with web search results
    """
    
    def __init__(self):
        # You can use various APIs:
        # - SerpAPI (paid but reliable)
        # - Google Custom Search API (free tier available)
        # - Bing Search API (free tier available)
        # - DuckDuckGo (free, no API key needed)
        self.search_provider = "duckduckgo"  # Free option
        
    def search_duckduckgo(self, query: str, num_results: int = 5) -> List[Dict]:
        """
        Search using DuckDuckGo (free, no API key required)
        """
        try:
            # DuckDuckGo instant answer API
            url = "https://api.duckduckgo.com/"
            params = {
                'q': query,
                'format': 'json',
                'no_html': 1,
                'skip_disambig': 1
            }
            
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            results = []
            
            # Get instant answer if available
            if data.get('Abstract'):
                results.append({
                    'title': 'Quick Answer',
                    'snippet': data['Abstract'],
                    'source': data.get('AbstractSource', 'DuckDuckGo'),
                    'url': data.get('AbstractURL', '')
                })
            
            # Get related topics
            for topic in data.get('RelatedTopics', [])[:num_results]:
                if isinstance(topic, dict) and 'Text' in topic:
                    results.append({
                        'title': topic.get('Text', '')[:100],
                        'snippet': topic.get('Text', ''),
                        'url': topic.get('FirstURL', ''),
                        'source': 'DuckDuckGo'
                    })
            
            return results
            
        except Exception as e:
            print(f"Search error: {e}")
            return []
    
    def search_news_api(self, company_name: str, days_back: int = 30) -> List[Dict]:
        """
        Search for recent news using NewsAPI (free tier available)
        Get API key from: https://newsapi.org/
        """
        # This is a placeholder - you'd need to sign up for a free API key
        api_key = st.secrets.get("NEWS_API_KEY", "")  # Store in Streamlit secrets
        
        if not api_key:
            return [{
                'title': 'News API Setup Required',
                'snippet': 'Get free API key from newsapi.org for real-time news',
                'date': datetime.now().isoformat(),
                'source': 'Setup Guide'
            }]
        
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                'q': company_name,
                'apiKey': api_key,
                'from': (datetime.now() - timedelta(days=days_back)).isoformat(),
                'sortBy': 'relevancy',
                'pageSize': 10
            }
            
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            results = []
            for article in data.get('articles', [])[:5]:
                results.append({
                    'title': article.get('title'),
                    'snippet': article.get('description'),
                    'date': article.get('publishedAt'),
                    'source': article.get('source', {}).get('name'),
                    'url': article.get('url')
                })
            
            return results
            
        except Exception as e:
            print(f"News API error: {e}")
            return []
    
    def get_augmented_context(self, company_name: str, ticker: str, key_topics: List[str]) -> Dict:
        """
        Get comprehensive augmented context for the company
        """
        augmented_data = {
            'recent_developments': [],
            'competitor_news': [],
            'industry_trends': [],
            'analyst_sentiment': [],
            'risk_alerts': []
        }
        
        # Search for recent developments
        recent_search = f"{company_name} {ticker} latest news {datetime.now().year}"
        augmented_data['recent_developments'] = self.search_duckduckgo(recent_search, 3)
        
        # Search for specific risks or concerns
        risk_search = f"{company_name} lawsuit investigation SEC fine recall"
        risk_results = self.search_duckduckgo(risk_search, 3)
        augmented_data['risk_alerts'] = risk_results
        
        # Search for analyst opinions
        analyst_search = f"{company_name} {ticker} analyst upgrade downgrade price target"
        augmented_data['analyst_sentiment'] = self.search_duckduckgo(analyst_search, 3)
        
        # Search for industry trends based on key topics
        for topic in key_topics[:2]:  # Top 2 topics
            industry_search = f"{topic} industry trends {datetime.now().year}"
            results = self.search_duckduckgo(industry_search, 2)
            augmented_data['industry_trends'].extend(results)
        
        # Search for competitor information
        competitor_search = f"{company_name} competitors market share"
        augmented_data['competitor_news'] = self.search_duckduckgo(competitor_search, 2)
        
        return augmented_data
    
    def generate_web_insights(self, search_results: Dict) -> List[str]:
        """
        Generate insights from web search results
        """
        insights = []
        
        # Analyze recent developments
        if search_results.get('recent_developments'):
            for item in search_results['recent_developments'][:2]:
                if item.get('snippet'):
                    insights.append(f"📰 Recent: {item['snippet'][:150]}...")
        
        # Check for risk alerts
        if search_results.get('risk_alerts'):
            risk_keywords = ['lawsuit', 'investigation', 'SEC', 'fine', 'violation', 'recall']
            for item in search_results['risk_alerts']:
                snippet = item.get('snippet', '').lower()
                if any(keyword in snippet for keyword in risk_keywords):
                    insights.append(f"⚠️ Risk Alert: {item['snippet'][:150]}...")
                    break
        
        # Analyst sentiment
        if search_results.get('analyst_sentiment'):
            for item in search_results['analyst_sentiment'][:1]:
                if 'upgrade' in item.get('snippet', '').lower():
                    insights.append(f"📈 Positive: Analyst upgrade mentioned")
                elif 'downgrade' in item.get('snippet', '').lower():
                    insights.append(f"📉 Concern: Analyst downgrade mentioned")
        
        return insights
    
    def create_search_urls(self, company_name: str, ticker: str, topics: List[str]) -> Dict[str, str]:
        """
        Create direct search URLs for users to explore further
        """
        urls = {
            'Google News': f"https://news.google.com/search?q={company_name.replace(' ', '+')}+{ticker}",
            'Yahoo Finance': f"https://finance.yahoo.com/quote/{ticker}",
            'SEC EDGAR': f"https://www.sec.gov/edgar/search/#/entityName={company_name.replace(' ', '%20')}",
            'Google Scholar': f"https://scholar.google.com/scholar?q={company_name.replace(' ', '+')}+financial+analysis",
            'Reddit Discussion': f"https://www.reddit.com/search/?q={ticker}%20stock",
            'Twitter/X': f"https://twitter.com/search?q=%24{ticker}",
            'Seeking Alpha': f"https://seekingalpha.com/symbol/{ticker}",
            'LinkedIn News': f"https://www.linkedin.com/search/results/content/?keywords={company_name.replace(' ', '%20')}"
        }
        
        # Add topic-specific searches
        for topic in topics[:2]:
            urls[f'{topic} Research'] = f"https://www.google.com/search?q={company_name.replace(' ', '+')}+{topic.replace(' ', '+')}"
        
        return urls


def create_augmented_summary(company_name: str, ticker: str, insights: List, sections: Dict) -> Dict:
    """
    Create an augmented analysis combining filing data with web intelligence
    """
    augmenter = WebSearchAugmentation()
    
    # Extract key topics from the filing
    key_topics = []
    if 'business' in sections:
        # Simple keyword extraction - could be enhanced with NLP
        business_text = sections['business'].lower()
        tech_keywords = ['AI', 'cloud', 'software', 'technology', 'digital']
        for keyword in tech_keywords:
            if keyword.lower() in business_text:
                key_topics.append(keyword)
    
    # Get augmented context
    web_context = augmenter.get_augmented_context(company_name, ticker, key_topics)
    
    # Generate web insights
    web_insights = augmenter.generate_web_insights(web_context)
    
    # Create search URLs for further research
    research_urls = augmenter.create_search_urls(company_name, ticker, key_topics)
    
    return {
        'web_context': web_context,
        'web_insights': web_insights,
        'research_urls': research_urls,
        'key_topics': key_topics
    }