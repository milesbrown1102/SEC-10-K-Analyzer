# peer_comparison.py
"""
Peer Comparison Engine for SEC 10-K Analysis
Automatically identifies and compares against competitors
"""

import re
from typing import Dict, List, Tuple
import pandas as pd
from dataclasses import dataclass
import concurrent.futures

@dataclass
class PeerComparison:
    """Results of peer comparison analysis"""
    company: str
    peers: List[str]
    metrics: Dict[str, Dict[str, float]]  # metric -> {company: value}
    rankings: Dict[str, int]  # metric -> company rank
    insights: List[str]
    competitive_position: str

class PeerAnalyzer:
    """
    Analyzes company against its peer group
    """
    
    def __init__(self, sec_analyzer):
        self.analyzer = sec_analyzer
        self.industry_peers = self._load_industry_peers()
        
    def _load_industry_peers(self) -> Dict[str, List[str]]:
        """
        Industry peer mappings
        """
        return {
            'AAPL': ['MSFT', 'GOOGL', 'META', 'AMZN'],  # Big Tech
            'MSFT': ['AAPL', 'GOOGL', 'META', 'AMZN', 'ORCL'],
            'GOOGL': ['META', 'MSFT', 'AAPL', 'AMZN'],
            'META': ['GOOGL', 'SNAP', 'TWTR', 'PINS'],
            'TSLA': ['F', 'GM', 'RIVN', 'NIO', 'LI'],  # Auto
            'JPM': ['BAC', 'WFC', 'C', 'GS', 'MS'],  # Banks
            'BAC': ['JPM', 'WFC', 'C', 'USB'],
            'NVDA': ['AMD', 'INTC', 'QCOM', 'AVGO'],  # Semis
            'AMD': ['NVDA', 'INTC', 'MU', 'QCOM'],
            'AMZN': ['WMT', 'TGT', 'COST', 'GOOGL', 'MSFT'],  # Retail/Cloud
            'WMT': ['AMZN', 'TGT', 'COST', 'DG'],
            'NFLX': ['DIS', 'PARA', 'WBD', 'CMCSA'],  # Streaming
            'DIS': ['NFLX', 'PARA', 'WBD', 'CMCSA'],
        }
    
    def identify_peers(self, company: str, sections: Dict) -> List[str]:
        """
        Identify peer companies from the filing or use predefined list
        """
        # First try predefined peers
        if company.upper() in self.industry_peers:
            return self.industry_peers[company.upper()][:3]  # Top 3 peers
        
        # Try to extract from competition section
        peers = self._extract_peers_from_filing(sections)
        if peers:
            return peers[:3]
        
        # Fallback to industry detection
        return self._detect_industry_peers(company, sections)
    
    def _extract_peers_from_filing(self, sections: Dict) -> List[str]:
        """
        Extract competitor names from filing
        """
        peers = []
        
        # Look in business and risk sections
        text = ""
        for section in ['business', 'risk_factors']:
            if section in sections:
                text += sections.get(section, "")
        
        # Common competition phrases
        patterns = [
            r'compete\s+with\s+([\w\s,]+)',
            r'competitors?\s+include\s+([\w\s,]+)',
            r'competition\s+from\s+([\w\s,]+)',
            r'primary\s+competitors?\s+are\s+([\w\s,]+)'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text[:10000], re.IGNORECASE)
            if matches:
                # Extract company names (simplified - you'd want NER here)
                companies = matches[0].split(',')
                for company in companies[:5]:
                    # Clean up and validate
                    company = company.strip()
                    if len(company) > 2 and len(company) < 50:
                        peers.append(company)
        
        return peers
    
    def _detect_industry_peers(self, company: str, sections: Dict) -> List[str]:
        """
        Detect industry and return generic peers
        """
        # Industry detection based on keywords
        text = sections.get('business', '')[:5000].lower()
        
        if 'software' in text or 'cloud' in text:
            return ['MSFT', 'GOOGL', 'CRM']
        elif 'retail' in text or 'e-commerce' in text:
            return ['AMZN', 'WMT', 'TGT']
        elif 'bank' in text or 'financial services' in text:
            return ['JPM', 'BAC', 'WFC']
        elif 'pharmaceutical' in text or 'drug' in text:
            return ['JNJ', 'PFE', 'MRK']
        elif 'automotive' in text or 'vehicle' in text:
            return ['TSLA', 'F', 'GM']
        else:
            return []  # No peers identified
    
    def fetch_peer_filings(self, peers: List[str]) -> Dict[str, Dict]:
        """
        Fetch 10-K sections for peer companies
        """
        peer_data = {}
        
        for peer in peers:
            try:
                # Get CIK
                cik = self.analyzer.get_company_cik(peer)
                if not cik:
                    continue
                
                # Get latest filing
                filings = self.analyzer.get_recent_10k_filings(cik, 1)
                if not filings:
                    continue
                
                filing = filings[0]
                content = self.analyzer.fetch_10k_content(cik, filing)
                
                if content:
                    sections = self.analyzer.extract_sections(content)
                    peer_data[peer] = {
                        'sections': sections,
                        'filing_date': filing['filing_date'],
                        'metrics': self._extract_peer_metrics(sections)
                    }
            except Exception as e:
                print(f"Error fetching {peer}: {e}")
                continue
        
        return peer_data
    
    def _extract_peer_metrics(self, sections: Dict) -> Dict[str, float]:
        """
        Extract comparable metrics from peer filings
        """
        metrics = {}
        
        text = ' '.join(sections.values())[:50000].lower()
        
        # Extract various metrics
        patterns = {
            'revenue': r'\$?([\d,]+\.?\d*)\s*(?:billion|million)\s+(?:in\s+)?(?:total\s+)?revenue',
            'employees': r'approximately\s+([\d,]+)\s+employees',
            'rd_spend': r'research\s+and\s+development.*?\$?([\d,]+\.?\d*)\s*(?:billion|million)',
            'gross_margin': r'gross\s+margin\s+(?:of\s+)?([\d.]+)%',
        }
        
        for metric, pattern in patterns.items():
            matches = re.findall(pattern, text)
            if matches:
                try:
                    value = float(matches[0].replace(',', ''))
                    if 'billion' in text[max(0, text.find(matches[0])-20):text.find(matches[0])+50]:
                        value *= 1000
                    metrics[metric] = value
                except:
                    pass
        
        # Count risk factors
        if 'risk_factors' in sections:
            metrics['risk_count'] = len(re.findall(r'•|\d+\.', sections['risk_factors']))
        
        # Section completeness
        metrics['section_completeness'] = sum(1 for v in sections.values() if v) / 20
        
        return metrics
    
    def compare_metrics(self, company: str, company_metrics: Dict, 
                       peer_data: Dict) -> PeerComparison:
        """
        Compare company against peers
        """
        all_metrics = {'revenue': {}, 'employees': {}, 'rd_spend': {}, 
                      'risk_count': {}, 'section_completeness': {}}
        
        # Add company metrics
        for metric in all_metrics:
            if metric in company_metrics:
                all_metrics[metric][company] = company_metrics[metric]
        
        # Add peer metrics
        for peer, data in peer_data.items():
            for metric in all_metrics:
                if metric in data.get('metrics', {}):
                    all_metrics[metric][peer] = data['metrics'][metric]
        
        # Calculate rankings
        rankings = {}
        for metric, values in all_metrics.items():
            if company in values and len(values) > 1:
                sorted_companies = sorted(values.items(), 
                                        key=lambda x: x[1], 
                                        reverse=True)
                for i, (comp, _) in enumerate(sorted_companies, 1):
                    if comp == company:
                        rankings[metric] = i
                        break
        
        # Generate insights
        insights = self._generate_peer_insights(company, all_metrics, rankings)
        
        # Determine competitive position
        avg_rank = sum(rankings.values()) / len(rankings) if rankings else 0
        if avg_rank <= 1.5:
            position = "Market Leader"
        elif avg_rank <= 2.5:
            position = "Strong Competitor"
        elif avg_rank <= 3.5:
            position = "Average Performer"
        else:
            position = "Lagging Competitor"
        
        return PeerComparison(
            company=company,
            peers=list(peer_data.keys()),
            metrics=all_metrics,
            rankings=rankings,
            insights=insights,
            competitive_position=position
        )
    
    def _generate_peer_insights(self, company: str, metrics: Dict, 
                               rankings: Dict) -> List[str]:
        """
        Generate insights from peer comparison
        """
        insights = []
        
        # Revenue comparison
        if 'revenue' in rankings:
            rank = rankings['revenue']
            total_companies = len(metrics.get('revenue', {}))
            if rank == 1:
                insights.append(f"💰 {company} is the revenue leader among peers")
            elif rank == total_companies:
                insights.append(f"⚠️ {company} has the lowest revenue among peers")
        
        # R&D spending
        if 'rd_spend' in metrics and company in metrics['rd_spend']:
            rd_values = list(metrics['rd_spend'].values())
            company_rd = metrics['rd_spend'][company]
            avg_rd = sum(rd_values) / len(rd_values)
            if company_rd > avg_rd * 1.2:
                insights.append(f"🔬 Higher R&D investment than peers (bullish for innovation)")
            elif company_rd < avg_rd * 0.8:
                insights.append(f"⚠️ Lower R&D spending may impact future competitiveness")
        
        # Risk comparison
        if 'risk_count' in metrics and company in metrics['risk_count']:
            risk_values = list(metrics['risk_count'].values())
            company_risks = metrics['risk_count'][company]
            avg_risks = sum(risk_values) / len(risk_values)
            if company_risks > avg_risks * 1.3:
                insights.append(f"🚨 Significantly more risk factors than peers")
        
        # Disclosure quality
        if 'section_completeness' in rankings:
            rank = rankings['section_completeness']
            if rank == 1:
                insights.append(f"📊 Best disclosure quality among peers")
        
        return insights

def run_peer_comparison(company: str, sections: Dict, analyzer) -> PeerComparison:
    """
    Helper function to run peer comparison
    """
    peer_analyzer = PeerAnalyzer(analyzer)
    
    # Identify peers
    peers = peer_analyzer.identify_peers(company, sections)
    
    if not peers:
        return None
    
    # Fetch peer data
    peer_data = peer_analyzer.fetch_peer_filings(peers)
    
    # Extract company metrics
    company_metrics = peer_analyzer._extract_peer_metrics(sections)
    
    # Compare
    comparison = peer_analyzer.compare_metrics(company, company_metrics, peer_data)
    
    return comparison