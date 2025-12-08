# intelligent_inference_engine.py
"""
Intelligent Inference Engine for SEC 10-K Analysis
Reads between the lines, detects hidden risks, and augments with web search
"""

import re
import json
import requests
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

@dataclass
class IntelligentInsight:
    """Represents an intelligent inference from the filing"""
    category: str  # 'risk', 'opportunity', 'red_flag', 'hidden_issue'
    confidence: float  # 0.0 to 1.0
    insight: str
    evidence: List[str]
    suggested_questions: List[str]
    web_search_queries: List[str]

class InferenceEngine:
    """
    Reads between the lines of SEC filings to find hidden insights
    """
    
    def __init__(self, llm_interface=None):
        self.llm = llm_interface
        self.red_flag_patterns = self._load_red_flag_patterns()
        self.opportunity_patterns = self._load_opportunity_patterns()
        
    def _load_red_flag_patterns(self) -> Dict:
        """Patterns that indicate potential hidden problems"""
        return {
            'management_issues': {
                'patterns': [
                    r'resignat|departed|left the company|stepped down',
                    r'interim\s+(?:CEO|CFO|COO)',
                    r'search(?:ing)?\s+for\s+(?:a\s+)?new\s+(?:chief|CEO|CFO)',
                    r'management\s+(?:changes|turnover|transition)',
                ],
                'inference': "High executive turnover often signals internal problems",
                'questions': [
                    "Why did the previous executive leave?",
                    "How long has the interim been in place?",
                    "What's the company's succession planning?"
                ]
            },
            'accounting_concerns': {
                'patterns': [
                    r'restat(?:e|ing|ement)',
                    r'material\s+weakness',
                    r'ineffective\s+(?:internal\s+)?controls',
                    r'change\s+in\s+account(?:ing|ants)',
                    r'delay(?:ed)?\s+filing',
                    r'going\s+concern',
                ],
                'inference': "Accounting issues often precede larger problems",
                'questions': [
                    "What triggered the restatement?",
                    "Has the auditor changed recently?",
                    "Are there any SEC investigations?"
                ]
            },
            'customer_concentration': {
                'patterns': [
                    r'\d{2,}%\s+of\s+(?:our\s+)?(?:total\s+)?(?:revenue|sales)',
                    r'largest\s+customer\s+(?:accounts?|represents?)',
                    r'significant\s+customer|major\s+customer',
                    r'customer\s+concentration',
                ],
                'inference': "High customer concentration is a major risk if that customer leaves",
                'questions': [
                    "What's the contract duration with major customers?",
                    "Are there any renewal risks?",
                    "What's the customer diversification strategy?"
                ]
            },
            'liquidity_stress': {
                'patterns': [
                    r'covenant\s+(?:violation|waiver|amendment)',
                    r'drew\s+(?:down\s+)?(?:on\s+)?(?:our\s+)?credit\s+facility',
                    r'negative\s+(?:working\s+capital|cash\s+flow)',
                    r'ability\s+to\s+continue\s+as\s+a\s+going\s+concern',
                    r'substantial\s+doubt',
                ],
                'inference': "Liquidity issues can lead to bankruptcy or dilutive financing",
                'questions': [
                    "What's the cash runway?",
                    "Are there any debt maturities coming up?",
                    "What are the covenant requirements?"
                ]
            },
            'competitive_pressure': {
                'patterns': [
                    r'price\s+(?:pressure|competition|erosion)',
                    r'market\s+share\s+(?:loss|decline|decreased)',
                    r'increased\s+competition',
                    r'new\s+entrants?\s+(?:in|to)\s+(?:the\s+)?market',
                    r'commoditiz(?:ed|ation)',
                ],
                'inference': "Margin compression likely if competitive pressure continues",
                'questions': [
                    "Who are the new competitors?",
                    "What's the pricing trend?",
                    "Is there differentiation strategy?"
                ]
            },
            'regulatory_risk': {
                'patterns': [
                    r'regulatory\s+(?:investigation|inquiry|review)',
                    r'subpoena|consent\s+decree',
                    r'SEC\s+(?:investigation|inquiry)',
                    r'DOJ|Department\s+of\s+Justice',
                    r'compliance\s+(?:failure|issue|violation)',
                ],
                'inference': "Regulatory issues can result in massive fines and restrictions",
                'questions': [
                    "What's the potential fine exposure?",
                    "Are there criminal charges possible?",
                    "What operational changes might be required?"
                ]
            }
        }
    
    def _load_opportunity_patterns(self) -> Dict:
        """Patterns that indicate potential hidden opportunities"""
        return {
            'expansion_signals': {
                'patterns': [
                    r'new\s+(?:facility|facilities|plant|office)',
                    r'expand(?:ing|ed)?\s+(?:into|our|the)',
                    r'enter(?:ing|ed)?\s+(?:new\s+)?markets?',
                    r'geographic\s+expansion',
                ],
                'inference': "Expansion often precedes revenue growth",
                'questions': [
                    "What's the expected ROI on expansion?",
                    "How long until break-even?",
                    "What's the total addressable market?"
                ]
            },
            'innovation_signals': {
                'patterns': [
                    r'R&D\s+(?:spending|investment|expense)\s+increased',
                    r'new\s+(?:product|technology|platform)\s+(?:launch|development)',
                    r'patent(?:s|ed)?\s+(?:filed|granted|pending)',
                    r'artificial\s+intelligence|machine\s+learning|AI\s+',
                ],
                'inference': "Innovation investment suggests future competitive advantages",
                'questions': [
                    "What's the product pipeline?",
                    "When will new products launch?",
                    "What's the competitive moat?"
                ]
            }
        }
    
    def analyze_for_hidden_insights(self, sections: Dict[str, str], company_name: str) -> List[IntelligentInsight]:
        """
        Analyze filing sections to find hidden insights
        """
        insights = []
        
        # Combine all text for analysis
        full_text = ' '.join(sections.values()).lower()
        
        # Check for red flags
        for category, config in self.red_flag_patterns.items():
            evidence = []
            for pattern in config['patterns']:
                matches = re.findall(pattern, full_text, re.IGNORECASE)
                if matches:
                    # Find the actual sentence containing the match
                    sentences = full_text.split('.')
                    for sentence in sentences:
                        if any(match in sentence.lower() for match in matches):
                            evidence.append(sentence.strip()[:200])
                            break
            
            if evidence:
                confidence = min(1.0, len(evidence) * 0.3)  # More evidence = higher confidence
                
                # Create web search queries
                search_queries = [
                    f"{company_name} {category.replace('_', ' ')}",
                    f"{company_name} news {matches[0]}" if matches else f"{company_name} {category}",
                ]
                
                insight = IntelligentInsight(
                    category='red_flag',
                    confidence=confidence,
                    insight=f"⚠️ {config['inference']}",
                    evidence=evidence[:3],  # Top 3 pieces of evidence
                    suggested_questions=config['questions'],
                    web_search_queries=search_queries
                )
                insights.append(insight)
        
        # Check for opportunities
        for category, config in self.opportunity_patterns.items():
            evidence = []
            for pattern in config['patterns']:
                matches = re.findall(pattern, full_text, re.IGNORECASE)
                if matches:
                    evidence.extend(matches[:2])
            
            if evidence:
                confidence = min(1.0, len(evidence) * 0.4)
                
                search_queries = [
                    f"{company_name} {category.replace('_', ' ')} analysis",
                    f"{company_name} growth strategy",
                ]
                
                insight = IntelligentInsight(
                    category='opportunity',
                    confidence=confidence,
                    insight=f"💡 {config['inference']}",
                    evidence=evidence[:3],
                    suggested_questions=config['questions'],
                    web_search_queries=search_queries
                )
                insights.append(insight)
        
        # Add cross-section analysis
        insights.extend(self._cross_section_analysis(sections, company_name))
        
        # Sort by confidence
        insights.sort(key=lambda x: x.confidence, reverse=True)
        
        return insights
    
    def _cross_section_analysis(self, sections: Dict[str, str], company_name: str) -> List[IntelligentInsight]:
        """
        Analyze relationships between different sections to find hidden insights
        """
        insights = []
        
        # Example: Compare Risk Factors with MD&A
        if 'risk_factors' in sections and 'mda' in sections:
            risks_mentioned = re.findall(r'risk[s]?\s+(?:of|from|related)', 
                                        sections.get('risk_factors', '').lower())
            mda_text = sections.get('mda', '').lower()
            
            # Check if risks mentioned in Risk Factors are addressed in MD&A
            unaddressed_risks = []
            for risk in risks_mentioned[:5]:  # Check top 5 risks
                if risk not in mda_text:
                    unaddressed_risks.append(risk)
            
            if unaddressed_risks:
                insight = IntelligentInsight(
                    category='hidden_issue',
                    confidence=0.6,
                    insight="🔍 Management not discussing certain risks in MD&A - possible blind spots",
                    evidence=unaddressed_risks[:2],
                    suggested_questions=[
                        "Why aren't certain risks discussed in management analysis?",
                        "Is management aware of these risk factors?",
                        "What's the mitigation strategy for undiscussed risks?"
                    ],
                    web_search_queries=[
                        f"{company_name} risk management",
                        f"{company_name} analyst concerns"
                    ]
                )
                insights.append(insight)
        
        # Example: Revenue growth vs Employee growth
        if 'business' in sections and 'mda' in sections:
            # Extract employee count changes
            employee_pattern = r'(\d{1,3}[,\d]*)\s+employees?'
            employee_matches = re.findall(employee_pattern, sections.get('business', ''))
            
            # Extract revenue changes
            revenue_pattern = r'revenue[s]?\s+(?:increased?|decreased?|grew|declined)\s+(\d+)%'
            revenue_matches = re.findall(revenue_pattern, sections.get('mda', '').lower())
            
            if employee_matches and revenue_matches:
                # This is a simple example - you'd want more sophisticated analysis
                insight = IntelligentInsight(
                    category='opportunity',
                    confidence=0.5,
                    insight="📊 Check efficiency metrics - compare headcount growth vs revenue growth",
                    evidence=[f"Employees: {employee_matches[0]}", f"Revenue change: {revenue_matches[0]}%"],
                    suggested_questions=[
                        "Is the company becoming more efficient?",
                        "What's the revenue per employee trend?",
                        "Are they over-hiring or under-hiring?"
                    ],
                    web_search_queries=[
                        f"{company_name} employee productivity",
                        f"{company_name} operational efficiency"
                    ]
                )
                insights.append(insight)
        
        return insights
    
    def generate_smart_questions(self, insights: List[IntelligentInsight], existing_questions: List[str]) -> List[str]:
        """
        Generate intelligent questions based on insights that aren't already being asked
        """
        smart_questions = []
        
        # Collect all suggested questions from insights
        for insight in insights[:5]:  # Top 5 insights
            smart_questions.extend(insight.suggested_questions)
        
        # Add cross-cutting questions based on patterns
        if any('management' in i.insight.lower() for i in insights):
            smart_questions.append("What's driving the management changes?")
        
        if any('customer' in i.insight.lower() for i in insights):
            smart_questions.append("How diversified is the customer base?")
        
        if any('competition' in i.insight.lower() for i in insights):
            smart_questions.append("What's the competitive moat?")
        
        # Remove duplicates and questions similar to existing ones
        unique_questions = []
        for q in smart_questions:
            if q not in existing_questions and q not in unique_questions:
                # Check if similar question exists
                similar = False
                for existing in existing_questions + unique_questions:
                    if any(word in existing.lower() for word in q.lower().split()[:3]):
                        similar = True
                        break
                
                if not similar:
                    unique_questions.append(q)
        
        return unique_questions[:10]  # Return top 10 unique questions
    
    def web_augmentation(self, company_name: str, insights: List[IntelligentInsight]) -> Dict:
        """
        Search web for additional context on the insights
        """
        # This is a placeholder - you'd integrate with a real search API
        # Options: Google Search API, Bing Search API, or web scraping
        
        augmented_data = {
            'recent_news': [],
            'analyst_opinions': [],
            'competitive_intel': [],
            'regulatory_updates': []
        }
        
        # Example search queries based on insights
        search_queries = []
        for insight in insights[:3]:  # Top 3 insights
            search_queries.extend(insight.web_search_queries)
        
        # Add standard searches
        search_queries.extend([
            f"{company_name} latest news {datetime.now().year}",
            f"{company_name} analyst downgrade upgrade",
            f"{company_name} SEC investigation",
            f"{company_name} competitor analysis"
        ])
        
        # Placeholder for web search results
        # In production, you'd actually search and parse results
        augmented_data['search_queries'] = search_queries
        
        return augmented_data


def integrate_inference_engine(sections: Dict[str, str], company_name: str, llm_interface=None):
    """
    Easy integration function for the inference engine
    """
    engine = InferenceEngine(llm_interface)
    
    # Get hidden insights
    insights = engine.analyze_for_hidden_insights(sections, company_name)
    
    # Generate smart questions
    existing_questions = []  # You'd pass existing questions here
    smart_questions = engine.generate_smart_questions(insights, existing_questions)
    
    # Get web augmentation suggestions
    web_data = engine.web_augmentation(company_name, insights)
    
    return {
        'insights': insights,
        'smart_questions': smart_questions,
        'web_augmentation': web_data
    }