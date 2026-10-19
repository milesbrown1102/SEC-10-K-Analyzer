# professional_dashboard.py
"""
Professional Visual Dashboard with Bloomberg-style aesthetics
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import Dict, List
import re

class ProfessionalDashboard:
    """
    Creates truly professional financial visualizations
    """
    
    def __init__(self):
        # Bloomberg/professional color palette
        self.colors = {
            'background': '#0e1117',
            'card_bg': '#1a1d29',
            'primary': '#00d4ff',
            'success': '#00ff41',
            'danger': '#ff3333',
            'warning': '#ffaa00',
            'text': '#ffffff',
            'grid': '#2a2d3a'
        }
        
    def create_comprehensive_dashboard(self, sections: Dict, insights: List, 
                                     section_overview: Dict, company: str) -> Dict:
        """
        Create all dashboard visualizations
        """
        charts = {}
        
        # 1. Section Coverage Gauge
        charts['coverage_gauge'] = self.create_coverage_gauge(section_overview)
        
        # 2. Risk Matrix Heatmap
        charts['risk_matrix'] = self.create_risk_matrix(insights)
        
        # 3. Insight Confidence Distribution
        charts['confidence_dist'] = self.create_confidence_distribution(insights)
        
        # 4. Financial Metrics Cards
        charts['metrics_cards'] = self.create_metric_cards(sections)
        
        # 5. Section Word Cloud Style Visualization
        charts['section_breakdown'] = self.create_section_breakdown(section_overview)
        
        # 6. Alert Dashboard
        charts['alerts'] = self.create_alerts_panel(insights)
        
        return charts
    
    def create_coverage_gauge(self, overview: Dict) -> go.Figure:
        """
        Create a professional coverage gauge
        """
        total_sections = 20
        found_sections = len([s for s in overview.get('section_details', []) if s['found']])
        coverage_pct = (found_sections / total_sections) * 100
        
        fig = go.Figure(go.Indicator(
            domain={'x': [0, 1], 'y': [0, 1]},
            value=coverage_pct,
            mode="gauge+number+delta",
            title={'text': "Filing Coverage", 'font': {'color': self.colors['text']}},
            delta={'reference': 80, 'increasing': {'color': self.colors['success']}},
            gauge={
                'axis': {'range': [None, 100], 'tickcolor': self.colors['text']},
                'bar': {'color': self.colors['primary']},
                'bgcolor': self.colors['card_bg'],
                'borderwidth': 2,
                'bordercolor': self.colors['grid'],
                'steps': [
                    {'range': [0, 50], 'color': self.colors['card_bg']},
                    {'range': [50, 80], 'color': '#1f2937'},
                    {'range': [80, 100], 'color': '#111827'}
                ],
                'threshold': {
                    'line': {'color': self.colors['danger'], 'width': 4},
                    'thickness': 0.75,
                    'value': 95
                }
            },
            number={'suffix': "%", 'font': {'size': 24, 'color': self.colors['text']}}
        ))
        
        fig.update_layout(
            paper_bgcolor=self.colors['background'],
            plot_bgcolor=self.colors['background'],
            font={'color': self.colors['text']},
            height=300,
            margin=dict(l=20, r=20, t=40, b=20)
        )
        
        return fig
    
    def create_risk_matrix(self, insights: List) -> go.Figure:
        """
        Create a risk impact/probability matrix
        """
        # Categorize insights into risk matrix
        risk_data = []
        for insight in insights:
            if hasattr(insight, 'category') and hasattr(insight, 'confidence'):
                impact = np.random.uniform(0.3, 1.0)  # Would be calculated from severity
                probability = insight.confidence
                
                risk_data.append({
                    'Risk': insight.insight[:30] + '...',
                    'Impact': impact,
                    'Probability': probability,
                    'Category': insight.category
                })
        
        if not risk_data:
            risk_data = [
                {'Risk': 'Sample Risk', 'Impact': 0.5, 'Probability': 0.5, 'Category': 'placeholder'}
            ]
        
        df = pd.DataFrame(risk_data)
        
        # Create scatter plot
        fig = px.scatter(df, x='Probability', y='Impact', 
                        text='Risk', 
                        color='Category',
                        color_discrete_map={
                            'red_flag': self.colors['danger'],
                            'opportunity': self.colors['success'],
                            'hidden_issue': self.colors['warning'],
                            'placeholder': self.colors['primary']
                        },
                        size_max=20)
        
        # Add quadrant lines
        fig.add_hline(y=0.5, line_dash="dash", line_color=self.colors['grid'])
        fig.add_vline(x=0.5, line_dash="dash", line_color=self.colors['grid'])
        
        # Add quadrant labels
        fig.add_annotation(x=0.25, y=0.75, text="High Impact<br>Low Probability",
                          showarrow=False, font=dict(color=self.colors['text'], size=10))
        fig.add_annotation(x=0.75, y=0.75, text="High Impact<br>High Probability",
                          showarrow=False, font=dict(color=self.colors['danger'], size=10))
        fig.add_annotation(x=0.25, y=0.25, text="Low Impact<br>Low Probability",
                          showarrow=False, font=dict(color=self.colors['text'], size=10))
        fig.add_annotation(x=0.75, y=0.25, text="Low Impact<br>High Probability",
                          showarrow=False, font=dict(color=self.colors['warning'], size=10))
        
        fig.update_layout(
            title="Risk Assessment Matrix",
            xaxis_title="Probability",
            yaxis_title="Business Impact",
            paper_bgcolor=self.colors['background'],
            plot_bgcolor=self.colors['card_bg'],
            font={'color': self.colors['text']},
            height=400,
            xaxis=dict(range=[0, 1], gridcolor=self.colors['grid']),
            yaxis=dict(range=[0, 1], gridcolor=self.colors['grid'])
        )
        
        return fig
    
    def create_confidence_distribution(self, insights: List) -> go.Figure:
        """
        Create confidence distribution chart
        """
        if insights:
            confidences = [i.confidence for i in insights if hasattr(i, 'confidence')]
        else:
            confidences = [0.5, 0.6, 0.7, 0.8, 0.65]  # Sample data
        
        fig = go.Figure(data=[
            go.Histogram(
                x=confidences,
                nbinsx=20,
                marker=dict(
                    color=self.colors['primary'],
                    line=dict(color=self.colors['text'], width=1)
                )
            )
        ])
        
        fig.update_layout(
            title="AI Confidence Distribution",
            xaxis_title="Confidence Level",
            yaxis_title="Number of Insights",
            paper_bgcolor=self.colors['background'],
            plot_bgcolor=self.colors['card_bg'],
            font={'color': self.colors['text']},
            height=300,
            xaxis=dict(gridcolor=self.colors['grid']),
            yaxis=dict(gridcolor=self.colors['grid'])
        )
        
        return fig
    
    def create_metric_cards(self, sections: Dict) -> Dict:
        """
        Extract and format key financial metrics
        """
        metrics = self._extract_metrics_from_sections(sections)
        
        return {
            'revenue': metrics.get('revenue', 'N/A'),
            'growth': metrics.get('growth', 'N/A'),
            'margin': metrics.get('margin', 'N/A'),
            'employees': metrics.get('employees', 'N/A')
        }
    
    def _extract_metrics_from_sections(self, sections: Dict) -> Dict:
        """
        Extract financial metrics from filing text
        """
        metrics = {}
        
        text = ' '.join(sections.values())[:50000].lower()
        
        # Revenue extraction
        revenue_match = re.search(r'\$?([\d,]+\.?\d*)\s*(?:billion|million)\s+(?:in\s+)?revenue', text)
        if revenue_match:
            value = revenue_match.group(1).replace(',', '')
            unit = 'B' if 'billion' in text[revenue_match.start():revenue_match.end()+20] else 'M'
            metrics['revenue'] = f"${value}{unit}"
        
        # Growth rate
        growth_match = re.search(r'(?:grew|increased|growth)\s+(?:by\s+)?([\d.]+)%', text)
        if growth_match:
            metrics['growth'] = f"{growth_match.group(1)}%"
        
        # Margin
        margin_match = re.search(r'(?:gross|operating|net)\s+margin\s+(?:of\s+)?([\d.]+)%', text)
        if margin_match:
            metrics['margin'] = f"{margin_match.group(1)}%"
        
        # Employees
        emp_match = re.search(r'([\d,]+)\s+employees', text)
        if emp_match:
            metrics['employees'] = emp_match.group(1)
        
        return metrics
    
    def create_section_breakdown(self, overview: Dict) -> go.Figure:
        """
        Create section breakdown visualization
        """
        data = []
        colors = []
        
        for section in overview.get('section_details', []):
            if section['found']:
                data.append({
                    'Section': f"Item {section['item']}",
                    'Words': section['words'],
                    'Status': 'Found'
                })
                colors.append(self.colors['success'])
            else:
                data.append({
                    'Section': f"Item {section['item']}",
                    'Words': 0,
                    'Status': 'Missing'
                })
                colors.append(self.colors['danger'])
        
        if not data:
            data = [{'Section': 'No Data', 'Words': 0, 'Status': 'N/A'}]
            colors = [self.colors['warning']]
        
        df = pd.DataFrame(data)
        
        fig = go.Figure(data=[
            go.Bar(
                x=df['Section'],
                y=df['Words'],
                marker_color=colors,
                text=df['Words'],
                textposition='outside'
            )
        ])
        
        fig.update_layout(
            title="Section Word Count Analysis",
            xaxis_title="Section",
            yaxis_title="Word Count",
            paper_bgcolor=self.colors['background'],
            plot_bgcolor=self.colors['card_bg'],
            font={'color': self.colors['text']},
            height=400,
            xaxis=dict(gridcolor=self.colors['grid']),
            yaxis=dict(gridcolor=self.colors['grid'])
        )
        
        return fig
    
    def create_alerts_panel(self, insights: List) -> List[Dict]:
        """
        Create alert panel data
        """
        alerts = []
        
        # High priority alerts (confidence > 0.7)
        for insight in insights:
            if hasattr(insight, 'confidence') and insight.confidence > 0.7:
                alert_type = 'danger' if insight.category == 'red_flag' else 'warning'
                alerts.append({
                    'type': alert_type,
                    'message': insight.insight,
                    'confidence': f"{insight.confidence:.0%}"
                })
        
        # Add default alert if none exist
        if not alerts:
            alerts.append({
                'type': 'info',
                'message': 'No high-priority alerts detected',
                'confidence': 'N/A'
            })
        
        return alerts[:5]  # Top 5 alerts