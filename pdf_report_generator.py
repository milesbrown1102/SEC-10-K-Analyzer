# pdf_report_generator.py
"""
Professional PDF Report Generator for SEC 10-K Analysis
Creates investment-grade PDF reports
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.platypus import Image as ReportLabImage
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_RIGHT
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart
from datetime import datetime
import io
from typing import Dict, List
import base64

class PDFReportGenerator:
    """
    Generates professional investment reports
    """

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """
        Create custom styles for professional appearance
        """
        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Title'],
            fontSize=24,
            textColor=colors.HexColor('#1A1B41'),
            spaceAfter=30,
            alignment=TA_CENTER
        ))

        # Section header
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#004E89'),
            spaceAfter=12,
            spaceBefore=12,
            leftIndent=0
        ))

        # Body text
        self.styles.add(ParagraphStyle(
            name='CustomBody',
            parent=self.styles['BodyText'],
            fontSize=11,
            alignment=TA_JUSTIFY,
            spaceAfter=12,
            leading=14
        ))

        # Executive summary
        self.styles.add(ParagraphStyle(
            name='ExecutiveSummary',
            parent=self.styles['BodyText'],
            fontSize=12,
            alignment=TA_JUSTIFY,
            spaceAfter=12,
            leftIndent=20,
            rightIndent=20,
            textColor=colors.HexColor('#333333')
        ))

    def generate_report(self,
                       company: str,
                       filing_date: str,
                       sections: Dict,
                       analysis_result,
                       insights: List,
                       peer_comparison=None,
                       output_path: str = None) -> bytes:
        """
        Generate complete PDF report
        """
        # Create PDF buffer
        buffer = io.BytesIO()

        # Create document
        doc = SimpleDocTemplate(
            buffer if not output_path else output_path,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )

        # Build content
        content = []

        # Cover page
        content.extend(self._create_cover_page(company, filing_date))
        content.append(PageBreak())

        # Table of contents
        content.extend(self._create_table_of_contents())
        content.append(PageBreak())

        # Executive summary
        content.extend(self._create_executive_summary(company, analysis_result))
        content.append(PageBreak())

        # Key insights section
        content.extend(self._create_insights_section(insights))
        content.append(PageBreak())

        # Financial analysis
        content.extend(self._create_financial_section(sections))

        # Risk assessment
        content.extend(self._create_risk_section(analysis_result, insights))
        content.append(PageBreak())

        # Peer comparison (if we actually have peer data — a dict with a
        # non-empty 'peers' list. This used to check truthiness of any
        # peer_comparison dict at all, which is always true even when
        # peers is [], and then crashed trying to read attributes that
        # were never set on it. See _create_peer_section.)
        if peer_comparison and peer_comparison.get('peers'):
            content.extend(self._create_peer_section(peer_comparison))
            content.append(PageBreak())

        # Investment recommendation
        content.extend(self._create_recommendation_section(company, insights))

        # Appendix
        content.extend(self._create_appendix(sections))

        # Build PDF
        doc.build(content, onFirstPage=self._add_header_footer,
                 onLaterPages=self._add_header_footer)

        if not output_path:
            buffer.seek(0)
            return buffer.getvalue()

        return None

    def _create_cover_page(self, company: str, filing_date: str) -> List:
        """
        Create professional cover page
        """
        content = []

        # Add spacing
        content.append(Spacer(1, 2*inch))

        # Title
        title = Paragraph(
            f"<b>{company.upper()}</b><br/>SEC 10-K Analysis Report",
            self.styles['CustomTitle']
        )
        content.append(title)

        content.append(Spacer(1, 0.5*inch))

        # Date and filing info
        info_text = f"""
        <para align=center>
        <b>Filing Date:</b> {filing_date}<br/>
        <b>Analysis Date:</b> {datetime.now().strftime('%Y-%m-%d')}<br/>
        <b>Report Type:</b> Comprehensive 10-K Analysis
        </para>
        """
        content.append(Paragraph(info_text, self.styles['Normal']))

        content.append(Spacer(1, 2*inch))

        # Disclaimer
        disclaimer = """
        <para align=center fontSize=9>
        This report is generated using AI-powered analysis of SEC filings.
        It should not be considered as investment advice.
        Please conduct your own due diligence before making investment decisions.
        </para>
        """
        content.append(Paragraph(disclaimer, self.styles['Normal']))

        return content

    def _create_table_of_contents(self) -> List:
        """
        Create table of contents
        """
        content = []

        content.append(Paragraph("Table of Contents", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.25*inch))

        toc_items = [
            ("1. Executive Summary", "3"),
            ("2. Key Insights & Intelligence", "4"),
            ("3. Financial Analysis", "5"),
            ("4. Risk Assessment", "6"),
            ("5. Peer Comparison", "7"),
            ("6. Investment Recommendation", "8"),
            ("7. Appendix", "9")
        ]

        for item, page in toc_items:
            toc_line = f"<para>{item}{'.'*(70-len(item))}{page}</para>"
            content.append(Paragraph(toc_line, self.styles['Normal']))
            content.append(Spacer(1, 0.1*inch))

        return content

    def _create_executive_summary(self, company: str, analysis_result) -> List:
        """
        Create executive summary section
        """
        content = []

        content.append(Paragraph("1. Executive Summary", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.25*inch))

        # Summary text
        if analysis_result and hasattr(analysis_result, 'summary'):
            content.append(Paragraph(analysis_result.summary, self.styles['ExecutiveSummary']))
        else:
            content.append(Paragraph(
                f"{company} operates in a competitive market with both opportunities and challenges...",
                self.styles['ExecutiveSummary']
            ))

        content.append(Spacer(1, 0.25*inch))

        # Key metrics table
        content.append(Paragraph("<b>Key Findings:</b>", self.styles['Normal']))

        if analysis_result and hasattr(analysis_result, 'financial_highlights'):
            data = [['Metric', 'Value']]
            for key, value in list(analysis_result.financial_highlights.items())[:5]:
                data.append([key, str(value)])

            table = Table(data, colWidths=[3*inch, 2*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#004E89')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            content.append(table)

        return content

    def _create_insights_section(self, insights: List) -> List:
        """
        Create insights section
        """
        content = []

        content.append(Paragraph("2. Key Insights & Intelligence", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.25*inch))

        # Group insights by category
        red_flags = [i for i in insights if i.category == 'red_flag']
        opportunities = [i for i in insights if i.category == 'opportunity']

        # Red flags
        if red_flags:
            content.append(Paragraph("<b>🚨 Red Flags Identified:</b>", self.styles['Normal']))
            for insight in red_flags[:3]:
                text = f"• {insight.insight} (Confidence: {insight.confidence:.0%})"
                content.append(Paragraph(text, self.styles['CustomBody']))
            content.append(Spacer(1, 0.2*inch))

        # Opportunities
        if opportunities:
            content.append(Paragraph("<b>💡 Opportunities Detected:</b>", self.styles['Normal']))
            for insight in opportunities[:3]:
                text = f"• {insight.insight} (Confidence: {insight.confidence:.0%})"
                content.append(Paragraph(text, self.styles['CustomBody']))

        return content

    def _create_financial_section(self, sections: Dict) -> List:
        """
        Create financial analysis section
        """
        content = []

        content.append(Paragraph("3. Financial Analysis", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.25*inch))

        # Extract some financial text
        financial_text = sections.get('financial_data', '')[:1000]
        if financial_text:
            content.append(Paragraph(
                "Financial performance summary based on latest filing:",
                self.styles['Normal']
            ))
            content.append(Paragraph(financial_text[:500] + "...", self.styles['CustomBody']))

        return content

    def _create_risk_section(self, analysis_result, insights: List) -> List:
        """
        Create risk assessment section
        """
        content = []

        content.append(Paragraph("4. Risk Assessment", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.25*inch))

        # List top risks
        if analysis_result and hasattr(analysis_result, 'risks'):
            content.append(Paragraph("<b>Primary Risk Factors:</b>", self.styles['Normal']))
            for risk in analysis_result.risks[:5]:
                content.append(Paragraph(f"• {risk}", self.styles['CustomBody']))

        return content

    def _create_peer_section(self, peer_comparison) -> List:
        """
        Create peer comparison section.

        `peer_comparison` is the {'peers': [...], 'reasons': {...}} dict
        produced by peer_analysis.get_peer_companies (or the legacy
        hardcoded mapping) — a plain dict, not a custom object. This used
        to assume a `.competitive_position` / `.insights` attribute that
        nothing in the app ever actually set, which crashed PDF generation
        with an AttributeError any time peer data was present.
        """
        content = []

        content.append(Paragraph("5. Peer Comparison", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.25*inch))

        peers = peer_comparison.get('peers', []) if isinstance(peer_comparison, dict) else []
        reasons = peer_comparison.get('reasons', {}) if isinstance(peer_comparison, dict) else {}

        if not peers:
            content.append(Paragraph(
                "No competitors were identified for this filing.",
                self.styles['Normal']
            ))
            return content

        content.append(Paragraph("<b>Identified Competitors:</b>", self.styles['Normal']))
        for peer in peers:
            reason = reasons.get(peer, "Identified as a competitor")
            content.append(Paragraph(f"• <b>{peer}</b>: {reason}", self.styles['CustomBody']))

        return content

    def _create_recommendation_section(self, company: str, insights: List) -> List:
        """
        Create investment recommendation
        """
        content = []

        content.append(Paragraph("6. Investment Recommendation", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.25*inch))

        # Calculate recommendation based on insights
        red_flags = len([i for i in insights if i.category == 'red_flag'])
        opportunities = len([i for i in insights if i.category == 'opportunity'])

        if opportunities > red_flags * 1.5:
            recommendation = "BUY"
            rationale = "Strong opportunities outweigh identified risks"
        elif red_flags > opportunities * 1.5:
            recommendation = "SELL"
            rationale = "Significant risks identified with limited upside"
        else:
            recommendation = "HOLD"
            rationale = "Balanced risk/reward profile"

        content.append(Paragraph(
            f"<b>Recommendation:</b> {recommendation}",
            self.styles['Normal']
        ))
        content.append(Paragraph(
            f"<b>Rationale:</b> {rationale}",
            self.styles['CustomBody']
        ))

        return content

    def _create_appendix(self, sections: Dict) -> List:
        """
        Create appendix with additional data
        """
        content = []

        content.append(Paragraph("7. Appendix", self.styles['SectionHeader']))
        content.append(Spacer(1, 0.25*inch))

        content.append(Paragraph(
            "Full filing available at SEC EDGAR database.",
            self.styles['Normal']
        ))

        # Section availability
        content.append(Paragraph("<b>Sections Analyzed:</b>", self.styles['Normal']))
        for section_name in sections.keys():
            if sections[section_name]:
                content.append(Paragraph(
                    f"✓ {section_name.replace('_', ' ').title()}",
                    self.styles['CustomBody']
                ))

        return content

    def _add_header_footer(self, canvas, doc):
        """
        Add header and footer to each page
        """
        canvas.saveState()

        # Header
        canvas.setFont('Helvetica', 9)
        canvas.drawString(inch, 10.5*inch, "SEC 10-K Analysis Report")
        canvas.drawRightString(7.5*inch, 10.5*inch,
                              datetime.now().strftime('%Y-%m-%d'))

        # Footer
        canvas.drawString(inch, 0.5*inch, "Confidential - AI Generated Analysis")
        canvas.drawRightString(7.5*inch, 0.5*inch, f"Page {canvas.getPageNumber()}")

        # Line
        canvas.setStrokeColor(colors.HexColor('#004E89'))
        canvas.line(inch, 10.4*inch, 7.5*inch, 10.4*inch)
        canvas.line(inch, 0.65*inch, 7.5*inch, 0.65*inch)

        canvas.restoreState()

def generate_investment_report(company: str, filing_date: str, sections: Dict,
                              analysis_result, insights: List,
                              peer_comparison=None) -> bytes:
    """
    Helper function to generate PDF report
    """
    generator = PDFReportGenerator()

    pdf_bytes = generator.generate_report(
        company=company,
        filing_date=filing_date,
        sections=sections,
        analysis_result=analysis_result,
        insights=insights,
        peer_comparison=peer_comparison
    )

    return pdf_bytes
