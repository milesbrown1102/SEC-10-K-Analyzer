# visual_dashboard.py
"""
Professional Visual Analytics for SEC 10-K Analysis
Creates Bloomberg-terminal style visualizations
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import Dict, List
import re
from datetime import datetime

class VisualDashboard:
    """
    Creates professional financial visualizations
    """
    
    def __init__(self):
        # Professional color scheme (Bloomberg-inspired)
        self.colors = {
            'primary': '#FF6B35',    # Orange
            'secondary': '#004E89',  # Dark Blue
            'success': '#00A676',    # Green
            'danger': '#EE6C4D',     # Red
            'warning': '#FFD23F',    # Yellow
            'dark': '#1A1B41',       # Dark Navy
            'light': '#F7F9FB'       # Light Gray
        }
        
        # Professional theme
        self.theme = {
            'bgcolor': '#0E1117',
            'gridcolor': '#1E2130',
            'textcolor': '#FAFAFA'
        }
    
    def create_section_heatmap(self, section_overview: Dict) -> go.Figure:
        """
        Create heatmap showing section completeness and size
        """
        sections = []
        availability = []
        word_counts = []
        
        for detail in section_overview.get('section_details', []):
            sections.append(f"Item {detail['item']}")
            availability.append(1 if detail['found'] else 0)
            word_counts.append(detail.get('words', 0))
        
        # Create subplot with two heatmaps
        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=('Section Availability', 'Section Size (Words)'),
            column_widths=[0.3, 0.7]
        )
        
        # Availability heatmap
        fig.add_trace(
            go.Heatmap(
                z=[availability],
                x=sections,
                y=['Status'],
                colorscale=[[0, '#EE6C4D'], [1, '#00A676']],
                showscale=False,
                text=[[('✓' if a else '✗') for a in availability]],
                texttemplate='%{text}',
                textfont={"size": 14, "color": "white"},
                hovertemplate='%{x}: %{text}<extra></extra>'
            ),
            row=1, col=1
        )
        
        # Word count heatmap
        fig.add_trace(
            go.Heatmap(
                z=[word_counts],
                x=sections,
                y=['Words'],
                colorscale='Viridis',
                text=[[f'{w:,}' if w > 0 else '-' for w in word_counts]],
                texttemplate='%{text}',
                textfont={"size": 10},
                hovertemplate='%{x}: %{text} words<extra></extra>'
            ),
            row=1, col=2
        )
        
        fig.update_layout(
            title='10-K Section Analysis Heatmap',
            height=250,
            paper_bgcolor=self.theme['bgcolor'],
            plot_bgcolor=self.theme['bgcolor'],
            font=dict(color=self.theme['textcolor']),
            showlegend=False
        )
        
        return fig
    
    def create_risk_radar(self, insights: List) -> go.Figure:
        """
        Create radar chart showing risk levels across categories
        """
        categories = {
            'Management': 0,
            'Accounting': 0,
            'Liquidity': 0,
            'Competition': 0,
            'Regulatory': 0,
            'Customer': 0
        }
        
        # Aggregate risk scores from insights
        for insight in insights:
            if 'management' in insight.insight.lower():
                categories['Management'] += insight.confidence
            elif 'account' in insight.insight.lower():
                categories['Accounting'] += insight.confidence
            elif 'liquid' in insight.insight.lower() or 'cash' in insight.insight.lower():
                categories['Liquidity'] += insight.confidence
            elif 'compet' in insight.insight.lower():
                categories['Competition'] += insight.confidence
            elif 'regulat' in insight.insight.lower() or 'SEC' in insight.insight:
                categories['Regulatory'] += insight.confidence
            elif 'customer' in insight.insight.lower():
                categories['Customer'] += insight.confidence
        
        # Normalize to 0-100 scale
        max_score = max(categories.values()) if max(categories.values()) > 0 else 1
        for cat in categories:
            categories[cat] = (categories[cat] / max_score) * 100
        
        fig = go.Figure(data=go.Scatterpolar(
            r=list(categories.values()),
            theta=list(categories.keys()),
            fill='toself',
            name='Risk Level',
            line_color=self.colors['danger'],
            fillcolor='rgba(238, 108, 77, 0.3)'
        ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 100],
                    gridcolor=self.theme['gridcolor']
                ),
                bgcolor=self.theme['bgcolor']
            ),
            title='Risk Assessment Radar',
            height=400,
            paper_bgcolor=self.theme['bgcolor'],
            font=dict(color=self.theme['textcolor']),
            showlegend=False
        )
        
        return fig
    
    def create_confidence_gauge(self, avg_confidence: float) -> go.Figure:
        """
        Create a gauge showing average confidence in insights
        """
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=avg_confidence * 100,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': "Analysis Confidence"},
            delta={'reference': 70},
            gauge={
                'axis': {'range': [None, 100]},
                'bar': {'color': self.colors['primary']},
                'steps': [
                    {'range': [0, 30], 'color': self.theme['gridcolor']},
                    {'range': [30, 70], 'color': "lightgray"},
                    {'range': [70, 100], 'color': self.theme['gridcolor']}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': 90
                }
            }
        ))
        
        fig.update_layout(
            height=250,
            paper_bgcolor=self.theme['bgcolor'],
            font={'color': self.theme['textcolor'], 'family': "Arial"}
        )
        
        return fig
    
    def create_financial_metrics_chart(self, sections: Dict) -> go.Figure:
        """
        Extract and visualize key financial metrics
        """
        metrics = self._extract_financial_metrics(sections)
        
        if not metrics:
            # Return empty chart with message
            fig = go.Figure()
            fig.add_annotation(
                text="Financial metrics will appear here once extracted",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=14, color=self.theme['textcolor'])
            )
            fig.update_layout(
                height=300,
                paper_bgcolor=self.theme['bgcolor'],
                plot_bgcolor=self.theme['bgcolor']
            )
            return fig
        
        # Create bar chart of metrics
        fig = go.Figure(data=[
            go.Bar(
                x=list(metrics.keys()),
                y=list(metrics.values()),
                marker_color=self.colors['primary'],
                text=[f'${v:,.0f}M' if v > 0 else 'N/A' for v in metrics.values()],
                textposition='outside'
            )
        ])
        
        fig.update_layout(
            title='Extracted Financial Metrics',
            xaxis_title='Metric',
            yaxis_title='Value (Millions)',
            height=400,
            paper_bgcolor=self.theme['bgcolor'],
            plot_bgcolor=self.theme['bgcolor'],
            font=dict(color=self.theme['textcolor']),
            xaxis=dict(gridcolor=self.theme['gridcolor']),
            yaxis=dict(gridcolor=self.theme['gridcolor'])
        )
        
        return fig
    
    def _extract_financial_metrics(self, sections: Dict) -> Dict[str, float]:
        """
        Extract numerical metrics from sections
        """
        metrics = {}
        
        # Combine relevant sections
        text = ""
        for section in ['financial_data', 'mda', 'financial_statements']:
            if section in sections:
                text += sections[section]
        
        # Revenue patterns
        revenue_pattern = r'\$?([\d,]+\.?\d*)\s*(?:billion|million)\s+(?:in\s+)?(?:total\s+)?(?:net\s+)?revenue'
        revenue_matches = re.findall(revenue_pattern, text.lower())
        if revenue_matches:
            try:
                value = float(revenue_matches[0].replace(',', ''))
                if 'billion' in text[text.lower().find(revenue_matches[0]):text.lower().find(revenue_matches[0])+50].lower():
                    value *= 1000
                metrics['Revenue'] = value
            except:
                pass
        
        # Net income patterns
        income_pattern = r'net\s+income\s+(?:of\s+)?\$?([\d,]+\.?\d*)\s*(?:billion|million)'
        income_matches = re.findall(income_pattern, text.lower())
        if income_matches:
            try:
                value = float(income_matches[0].replace(',', ''))
                if 'billion' in text[text.lower().find(income_matches[0]):text.lower().find(income_matches[0])+50].lower():
                    value *= 1000
                metrics['Net Income'] = value
            except:
                pass
        
        # Cash patterns
        cash_pattern = r'cash\s+and\s+cash\s+equivalents\s+(?:of\s+)?\$?([\d,]+\.?\d*)\s*(?:billion|million)'
        cash_matches = re.findall(cash_pattern, text.lower())
        if cash_matches:
            try:
                value = float(cash_matches[0].replace(',', ''))
                if 'billion' in text[text.lower().find(cash_matches[0]):text.lower().find(cash_matches[0])+50].lower():
                    value *= 1000
                metrics['Cash'] = value
            except:
                pass
        
        return metrics
    
    def create_insight_timeline(self, insights: List) -> go.Figure:
        """
        Create timeline visualization of insights by category
        """
        categories = []
        confidence_scores = []
        texts = []
        colors = []
        
        for i, insight in enumerate(insights[:10]):  # Top 10 insights
            categories.append(insight.category.replace('_', ' ').title())
            confidence_scores.append(insight.confidence * 100)
            texts.append(insight.insight[:50] + '...')
            
            # Color by category
            if insight.category == 'red_flag':
                colors.append(self.colors['danger'])
            elif insight.category == 'opportunity':
                colors.append(self.colors['success'])
            else:
                colors.append(self.colors['warning'])
        
        fig = go.Figure(data=[
            go.Bar(
                y=categories,
                x=confidence_scores,
                orientation='h',
                marker_color=colors,
                text=texts,
                textposition='inside',
                textfont=dict(size=10),
                hovertemplate='%{text}<br>Confidence: %{x:.0f}%<extra></extra>'
            )
        ])
        
        fig.update_layout(
            title='Top Insights by Confidence',
            xaxis_title='Confidence %',
            height=400,
            paper_bgcolor=self.theme['bgcolor'],
            plot_bgcolor=self.theme['bgcolor'],
            font=dict(color=self.theme['textcolor']),
            xaxis=dict(gridcolor=self.theme['gridcolor'], range=[0, 100]),
            yaxis=dict(gridcolor=self.theme['gridcolor'])
        )
        
        return fig

def create_dashboard_view(sections: Dict, insights: List, section_overview: Dict):
    """
    Helper function to create complete dashboard view
    """
    dashboard = VisualDashboard()
    
    charts = {
        'section_heatmap': dashboard.create_section_heatmap(section_overview),
        'risk_radar': dashboard.create_risk_radar(insights),
        'confidence_gauge': dashboard.create_confidence_gauge(
            np.mean([i.confidence for i in insights]) if insights else 0.5
        ),
        'financial_metrics': dashboard.create_financial_metrics_chart(sections),
        'insight_timeline': dashboard.create_insight_timeline(insights)
    }
    
    return charts