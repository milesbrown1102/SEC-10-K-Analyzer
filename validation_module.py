# validation_module.py
"""
Validation and Accuracy Testing Module
For internal QA and accuracy measurement
"""

import json
from typing import Dict, List, Tuple
from datetime import datetime
import hashlib
import re

class ValidationModule:
    """
    Tests and validates LLM accuracy
    """
    
    def __init__(self):
        self.test_cases = self._load_test_cases()
        self.validation_results = []
        
    def _load_test_cases(self) -> List[Dict]:
        """
        Load known test cases with ground truth
        """
        return [
            {
                'company': 'AAPL',
                'question': 'What is Apple\'s primary business?',
                'expected_keywords': ['iPhone', 'consumer electronics', 'services'],
                'section': 'business'
            },
            {
                'company': 'MSFT',
                'question': 'What are Microsoft\'s main revenue segments?',
                'expected_keywords': ['Azure', 'Office', 'Windows', 'cloud'],
                'section': 'mda'
            },
            {
                'company': 'NVDA',
                'question': 'What are NVIDIA\'s key risks?',
                'expected_keywords': ['competition', 'supply chain', 'regulation'],
                'section': 'risk_factors'
            }
        ]
    
    def validate_extraction_accuracy(self, sections: Dict, company: str) -> Dict:
        """
        Validate section extraction accuracy
        """
        validation = {
            'company': company,
            'timestamp': datetime.now().isoformat(),
            'extraction_tests': [],
            'overall_score': 0.0
        }
        
        # Test 1: Check if standard sections are found
        standard_sections = ['business', 'risk_factors', 'mda', 'financial_data']
        found_count = sum(1 for s in standard_sections if s in sections and sections[s])
        
        validation['extraction_tests'].append({
            'test': 'Standard Sections Found',
            'expected': len(standard_sections),
            'actual': found_count,
            'score': found_count / len(standard_sections),
            'pass': found_count >= 3  # At least 3 of 4
        })
        
        # Test 2: Check section sizes (should be substantial)
        size_test = []
        for section_name, content in sections.items():
            if content:
                word_count = len(content.split())
                size_test.append({
                    'section': section_name,
                    'words': word_count,
                    'adequate': word_count > 100
                })
        
        adequate_sections = sum(1 for s in size_test if s['adequate'])
        validation['extraction_tests'].append({
            'test': 'Section Size Adequacy',
            'details': size_test,
            'score': adequate_sections / len(size_test) if size_test else 0,
            'pass': adequate_sections >= 3
        })
        
        # Test 3: Check for financial data
        financial_keywords = ['revenue', 'income', 'cash', 'debt', 'million', 'billion']
        financial_content = sections.get('financial_data', '') + sections.get('mda', '')
        financial_found = sum(1 for kw in financial_keywords if kw in financial_content.lower())
        
        validation['extraction_tests'].append({
            'test': 'Financial Data Extraction',
            'keywords_found': financial_found,
            'expected_keywords': len(financial_keywords),
            'score': financial_found / len(financial_keywords),
            'pass': financial_found >= 4
        })
        
        # Calculate overall score
        scores = [t['score'] for t in validation['extraction_tests']]
        validation['overall_score'] = sum(scores) / len(scores) if scores else 0
        
        return validation
    
    def validate_llm_responses(self, question: str, answer: str, 
                              expected_keywords: List[str] = None) -> Dict:
        """
        Validate LLM answer quality
        """
        validation = {
            'question': question,
            'answer_length': len(answer),
            'tests': [],
            'score': 0.0
        }
        
        # Test 1: Answer length (not too short, not too long)
        length_score = 0
        if 50 <= len(answer) <= 1000:
            length_score = 1.0
        elif len(answer) < 50:
            length_score = 0.3
        else:
            length_score = 0.7
        
        validation['tests'].append({
            'test': 'Answer Length',
            'score': length_score,
            'pass': length_score >= 0.7
        })
        
        # Test 2: Keyword presence (if expected keywords provided)
        if expected_keywords:
            found_keywords = sum(1 for kw in expected_keywords 
                               if kw.lower() in answer.lower())
            keyword_score = found_keywords / len(expected_keywords)
            
            validation['tests'].append({
                'test': 'Expected Keywords',
                'found': found_keywords,
                'expected': len(expected_keywords),
                'score': keyword_score,
                'pass': keyword_score >= 0.5
            })
        
        # Test 3: Coherence (basic check for complete sentences)
        sentences = answer.split('.')
        complete_sentences = sum(1 for s in sentences if len(s.strip()) > 10)
        coherence_score = min(1.0, complete_sentences / 3)  # At least 3 sentences
        
        validation['tests'].append({
            'test': 'Answer Coherence',
            'sentences': complete_sentences,
            'score': coherence_score,
            'pass': coherence_score >= 0.6
        })
        
        # Test 4: Source attribution
        has_source = any(word in answer.lower() for word in ['source:', 'from:', 'section:'])
        validation['tests'].append({
            'test': 'Source Attribution',
            'score': 1.0 if has_source else 0.0,
            'pass': has_source
        })
        
        # Calculate overall score
        scores = [t['score'] for t in validation['tests']]
        validation['score'] = sum(scores) / len(scores) if scores else 0
        
        return validation
    
    def validate_insights(self, insights: List) -> Dict:
        """
        Validate insight quality and relevance
        """
        validation = {
            'total_insights': len(insights),
            'tests': [],
            'score': 0.0
        }
        
        # Test 1: Number of insights
        insight_count_score = min(1.0, len(insights) / 5)  # Expect at least 5
        validation['tests'].append({
            'test': 'Insight Count',
            'count': len(insights),
            'expected_min': 5,
            'score': insight_count_score,
            'pass': len(insights) >= 3
        })
        
        # Test 2: Confidence distribution
        if insights:
            confidences = [i.confidence for i in insights if hasattr(i, 'confidence')]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            validation['tests'].append({
                'test': 'Average Confidence',
                'value': avg_confidence,
                'score': avg_confidence,
                'pass': avg_confidence >= 0.5
            })
            
            # Test 3: Category distribution
            categories = {}
            for i in insights:
                if hasattr(i, 'category'):
                    categories[i.category] = categories.get(i.category, 0) + 1
            
            has_diverse_categories = len(categories) >= 2
            validation['tests'].append({
                'test': 'Category Diversity',
                'categories': categories,
                'score': 1.0 if has_diverse_categories else 0.5,
                'pass': has_diverse_categories
            })
        
        # Calculate overall score
        scores = [t['score'] for t in validation['tests']]
        validation['score'] = sum(scores) / len(scores) if scores else 0
        
        return validation
    
    def run_comprehensive_validation(self, sections: Dict, company: str,
                                    insights: List, sample_qa: List[Tuple[str, str]]) -> Dict:
        """
        Run all validation tests
        """
        report = {
            'company': company,
            'timestamp': datetime.now().isoformat(),
            'tests': {}
        }
        
        # 1. Extraction validation
        report['tests']['extraction'] = self.validate_extraction_accuracy(sections, company)
        
        # 2. Insight validation
        report['tests']['insights'] = self.validate_insights(insights)
        
        # 3. Q&A validation (if sample Q&A provided)
        if sample_qa:
            qa_validations = []
            for question, answer in sample_qa[:3]:  # Test first 3 Q&As
                qa_validations.append(self.validate_llm_responses(question, answer))
            
            report['tests']['qa_quality'] = {
                'samples_tested': len(qa_validations),
                'average_score': sum(v['score'] for v in qa_validations) / len(qa_validations),
                'details': qa_validations
            }
        
        # Overall system score
        all_scores = []
        if 'extraction' in report['tests']:
            all_scores.append(report['tests']['extraction']['overall_score'])
        if 'insights' in report['tests']:
            all_scores.append(report['tests']['insights']['score'])
        if 'qa_quality' in report['tests']:
            all_scores.append(report['tests']['qa_quality']['average_score'])
        
        report['overall_system_score'] = sum(all_scores) / len(all_scores) if all_scores else 0
        report['grade'] = self._calculate_grade(report['overall_system_score'])
        
        return report
    
    def _calculate_grade(self, score: float) -> str:
        """
        Convert score to letter grade
        """
        if score >= 0.9:
            return 'A+'
        elif score >= 0.85:
            return 'A'
        elif score >= 0.80:
            return 'B+'
        elif score >= 0.75:
            return 'B'
        elif score >= 0.70:
            return 'C+'
        elif score >= 0.65:
            return 'C'
        elif score >= 0.60:
            return 'D'
        else:
            return 'F'
    
    def generate_validation_report_html(self, report: Dict) -> str:
        """
        Generate HTML validation report
        """
        html = f"""
        <div style="background: #1a1d29; padding: 20px; border-radius: 10px; color: white;">
            <h2>🔍 Validation Report</h2>
            <p><strong>Company:</strong> {report['company']}</p>
            <p><strong>Timestamp:</strong> {report['timestamp']}</p>
            <p><strong>Overall Score:</strong> {report['overall_system_score']:.2%}</p>
            <p><strong>Grade:</strong> <span style="font-size: 24px; color: #00d4ff;">{report['grade']}</span></p>
            
            <h3>📊 Test Results</h3>
        """
        
        # Extraction tests
        if 'extraction' in report['tests']:
            ext = report['tests']['extraction']
            html += f"""
            <h4>Section Extraction</h4>
            <ul>
            """
            for test in ext['extraction_tests']:
                status = "✅" if test['pass'] else "❌"
                html += f"<li>{status} {test['test']}: {test['score']:.2%}</li>"
            html += "</ul>"
        
        # Insight tests
        if 'insights' in report['tests']:
            ins = report['tests']['insights']
            html += f"""
            <h4>Insight Generation</h4>
            <ul>
            """
            for test in ins['tests']:
                status = "✅" if test['pass'] else "❌"
                html += f"<li>{status} {test['test']}: {test['score']:.2%}</li>"
            html += "</ul>"
        
        # Q&A tests
        if 'qa_quality' in report['tests']:
            qa = report['tests']['qa_quality']
            html += f"""
            <h4>Q&A Quality</h4>
            <p>Average Score: {qa['average_score']:.2%}</p>
            """
        
        html += "</div>"
        
        return html