# enhanced_section_extractor.py
"""
Enhanced SEC 10-K Section Extractor
Captures ALL sections of the filing, not just select few
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass

@dataclass
class FilingSection:
    """Represents a section of the 10-K filing"""
    item_number: str
    title: str
    content: str
    start_pos: int
    end_pos: int
    word_count: int

class ComprehensiveSectionExtractor:
    """
    Extracts ALL sections from a 10-K filing
    """
    
    # Complete list of 10-K sections
    SECTION_PATTERNS = {
        # PART I
        '1': {
            'names': ['Business', 'Overview', 'Description of Business'],
            'pattern': r'(?is)item\s+1\.\s*(?:business|overview|description\s+of\s+business)'
        },
        '1A': {
            'names': ['Risk Factors'],
            'pattern': r'(?is)item\s+1a\.\s*risk\s+factors'
        },
        '1B': {
            'names': ['Unresolved Staff Comments'],
            'pattern': r'(?is)item\s+1b\.\s*unresolved\s+staff\s+comments'
        },
        '2': {
            'names': ['Properties'],
            'pattern': r'(?is)item\s+2\.\s*properties'
        },
        '3': {
            'names': ['Legal Proceedings'],
            'pattern': r'(?is)item\s+3\.\s*legal\s+proceedings'
        },
        '4': {
            'names': ['Mine Safety Disclosures'],
            'pattern': r'(?is)item\s+4\.\s*mine\s+safety\s+disclosures'
        },
        
        # PART II
        '5': {
            'names': ['Market for Common Equity', 'Stock Performance'],
            'pattern': r'(?is)item\s+5\.\s*market\s+for\s+(?:registrant|common)'
        },
        '6': {
            'names': ['Selected Financial Data', 'Key Financial Data'],
            'pattern': r'(?is)item\s+6\.\s*(?:selected|key)\s+financial\s+data'
        },
        '7': {
            'names': ['MD&A', "Management's Discussion and Analysis"],
            'pattern': r'(?is)item\s+7\.\s*management[\'s]*\s+discussion'
        },
        '7A': {
            'names': ['Quantitative and Qualitative Disclosures About Market Risk'],
            'pattern': r'(?is)item\s+7a\.\s*quantitative\s+and\s+qualitative'
        },
        '8': {
            'names': ['Financial Statements and Supplementary Data'],
            'pattern': r'(?is)item\s+8\.\s*financial\s+statements'
        },
        '9': {
            'names': ['Changes in and Disagreements with Accountants'],
            'pattern': r'(?is)item\s+9\.\s*changes\s+in\s+and\s+disagreements'
        },
        '9A': {
            'names': ['Controls and Procedures'],
            'pattern': r'(?is)item\s+9a\.\s*controls\s+and\s+procedures'
        },
        '9B': {
            'names': ['Other Information'],
            'pattern': r'(?is)item\s+9b\.\s*other\s+information'
        },
        
        # PART III
        '10': {
            'names': ['Directors, Executive Officers and Corporate Governance'],
            'pattern': r'(?is)item\s+10\.\s*directors[,\s]+executive\s+officers'
        },
        '11': {
            'names': ['Executive Compensation'],
            'pattern': r'(?is)item\s+11\.\s*executive\s+compensation'
        },
        '12': {
            'names': ['Security Ownership'],
            'pattern': r'(?is)item\s+12\.\s*security\s+ownership'
        },
        '13': {
            'names': ['Certain Relationships and Related Transactions'],
            'pattern': r'(?is)item\s+13\.\s*certain\s+relationships'
        },
        '14': {
            'names': ['Principal Accountant Fees and Services'],
            'pattern': r'(?is)item\s+14\.\s*principal\s+account(?:ant|ing)\s+fees'
        },
        
        # PART IV
        '15': {
            'names': ['Exhibits and Financial Statement Schedules'],
            'pattern': r'(?is)item\s+15\.\s*exhibits?\s+and\s+financial'
        }
    }
    
    def __init__(self):
        self.sections = {}
        self.table_of_contents = []
        
    def extract_all_sections(self, content: str) -> Dict[str, FilingSection]:
        """
        Extract ALL sections from the 10-K filing
        """
        print("\n📚 Extracting ALL 10-K sections...")
        
        # First, find all section headers and their positions
        section_positions = []
        
        for item_num, info in self.SECTION_PATTERNS.items():
            pattern = info['pattern']
            matches = list(re.finditer(pattern, content))
            
            if matches:
                # Take the first clear match (usually from table of contents)
                match = matches[0]
                section_positions.append({
                    'item': item_num,
                    'title': info['names'][0],
                    'start': match.start(),
                    'pattern_match': match.group()
                })
                print(f"  ✓ Found Item {item_num}: {info['names'][0]}")
            else:
                print(f"  ✗ Missing Item {item_num}: {info['names'][0]}")
        
        # Sort by position in document
        section_positions.sort(key=lambda x: x['start'])
        
        # Extract content for each section
        sections = {}
        for i, section in enumerate(section_positions):
            # Determine end position (start of next section or end of document)
            end_pos = section_positions[i + 1]['start'] if i + 1 < len(section_positions) else len(content)
            
            # Extract section content
            section_content = content[section['start']:end_pos]
            
            # Clean up the content
            section_content = self._clean_section_content(section_content)
            
            # Calculate word count
            word_count = len(section_content.split())
            
            # Create FilingSection object
            filing_section = FilingSection(
                item_number=section['item'],
                title=section['title'],
                content=section_content[:50000],  # Limit each section to 50k chars
                start_pos=section['start'],
                end_pos=end_pos,
                word_count=word_count
            )
            
            sections[section['item']] = filing_section
        
        self.sections = sections
        return sections
    
    def _clean_section_content(self, content: str) -> str:
        """
        Clean section content while preserving structure
        """
        # Remove excessive whitespace but preserve paragraph breaks
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r'[ \t]+', ' ', content)
        
        # Remove page numbers and headers/footers
        content = re.sub(r'^\d+\s*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^Table of Contents\s*$', '', content, flags=re.MULTILINE | re.IGNORECASE)
        
        return content.strip()
    
    def extract_tables_and_exhibits(self, content: str) -> Dict[str, str]:
        """
        Extract tables, exhibits, and financial data
        """
        tables = {}
        
        # Pattern for tables
        table_pattern = r'(?is)(table\s+[\d\.]+.*?(?:\n.*?){1,50}?(?=\n\n|\btable\s+[\d\.]|\bitem\s+\d))'
        matches = re.findall(table_pattern, content)
        
        for i, match in enumerate(matches[:20]):  # Limit to 20 tables
            tables[f'table_{i+1}'] = match
        
        # Pattern for financial statements
        financial_patterns = [
            r'(?is)(consolidated\s+balance\s+sheet.*?(?:\n.*?){1,100}?(?=\n\n\n|\bconsolidated|\bnote))',
            r'(?is)(consolidated\s+statement\s+of\s+income.*?(?:\n.*?){1,100}?(?=\n\n\n|\bconsolidated|\bnote))',
            r'(?is)(consolidated\s+statement\s+of\s+cash\s+flows.*?(?:\n.*?){1,100}?(?=\n\n\n|\bconsolidated|\bnote))',
        ]
        
        for pattern in financial_patterns:
            matches = re.findall(pattern, content)
            if matches:
                tables['financial_statements'] = '\n\n'.join(matches)
                break
        
        return tables
    
    def get_missing_sections(self) -> List[str]:
        """
        Identify which standard sections are missing
        """
        missing = []
        for item_num, info in self.SECTION_PATTERNS.items():
            if item_num not in self.sections:
                missing.append(f"Item {item_num}: {info['names'][0]}")
        return missing
    
    def generate_table_of_contents(self) -> str:
        """
        Generate a table of contents from extracted sections
        """
        toc = []
        toc.append("="*60)
        toc.append("10-K TABLE OF CONTENTS")
        toc.append("="*60)
        
        # Group by parts
        part_sections = {
            'PART I': ['1', '1A', '1B', '2', '3', '4'],
            'PART II': ['5', '6', '7', '7A', '8', '9', '9A', '9B'],
            'PART III': ['10', '11', '12', '13', '14'],
            'PART IV': ['15']
        }
        
        for part, items in part_sections.items():
            toc.append(f"\n{part}")
            toc.append("-" * 40)
            
            for item in items:
                if item in self.sections:
                    section = self.sections[item]
                    status = "✓"
                    words = f"{section.word_count:,} words"
                else:
                    status = "✗"
                    words = "Not found"
                    section = None
                
                title = self.SECTION_PATTERNS[item]['names'][0]
                toc.append(f"  {status} Item {item:3s}: {title:40s} {words:>15s}")
        
        # Summary stats
        toc.append("\n" + "="*60)
        toc.append(f"EXTRACTION SUMMARY")
        toc.append("-" * 40)
        toc.append(f"Sections found: {len(self.sections)}/{len(self.SECTION_PATTERNS)}")
        toc.append(f"Total words: {sum(s.word_count for s in self.sections.values()):,}")
        
        missing = self.get_missing_sections()
        if missing:
            toc.append(f"\nMissing sections:")
            for m in missing:
                toc.append(f"  - {m}")
        
        return '\n'.join(toc)
    
    def get_section_by_topic(self, topic: str) -> List[FilingSection]:
        """
        Find sections related to a specific topic
        """
        topic_lower = topic.lower()
        relevant_sections = []
        
        # Keywords for different topics
        topic_keywords = {
            'competition': ['compet', 'rival', 'market share'],
            'employees': ['employ', 'workforce', 'personnel', 'human capital'],
            'technology': ['technolog', 'AI', 'artificial intelligence', 'software', 'innovation'],
            'international': ['foreign', 'international', 'global', 'geographic'],
            'debt': ['debt', 'borrow', 'loan', 'credit', 'leverage'],
            'legal': ['legal', 'litigation', 'lawsuit', 'regulatory', 'compliance'],
            'compensation': ['compensation', 'salary', 'bonus', 'equity', 'stock option'],
            'governance': ['governance', 'board', 'director', 'committee'],
            'accounting': ['accounting', 'audit', 'financial control', 'internal control']
        }
        
        # Find matching keywords
        matching_keywords = []
        for key, keywords in topic_keywords.items():
            if any(kw in topic_lower for kw in keywords):
                matching_keywords.extend(keywords)
        
        if not matching_keywords:
            matching_keywords = [topic_lower]
        
        # Search sections
        for item_num, section in self.sections.items():
            content_lower = section.content[:5000].lower()  # Check first 5000 chars
            
            # Count keyword occurrences
            relevance_score = sum(content_lower.count(kw) for kw in matching_keywords)
            
            if relevance_score > 0:
                relevant_sections.append((relevance_score, section))
        
        # Sort by relevance
        relevant_sections.sort(key=lambda x: x[0], reverse=True)
        
        return [s[1] for s in relevant_sections[:5]]  # Return top 5 most relevant


def enhance_analyzer_with_full_extraction(analyzer_instance, content: str):
    """
    Enhance the existing analyzer with comprehensive section extraction
    """
    extractor = ComprehensiveSectionExtractor()
    
    # Extract all sections
    all_sections = extractor.extract_all_sections(content)
    
    # Generate and print table of contents
    toc = extractor.generate_table_of_contents()
    print(toc)
    
    # Extract tables and exhibits
    tables = extractor.extract_tables_and_exhibits(content)
    if tables:
        print(f"\n📊 Found {len(tables)} tables/exhibits")
    
    # Convert to format expected by existing analyzer
    enhanced_sections = {}
    
    # Map to existing section names
    section_mapping = {
        '1': 'business',
        '1A': 'risk_factors',
        '6': 'financial_data', 
        '7': 'mda',
        '8': 'financial_statements',
        '3': 'legal_proceedings',
        '7A': 'market_risk',
        '9A': 'controls',
        '11': 'executive_compensation',
        '10': 'governance'
    }
    
    for item_num, section_key in section_mapping.items():
        if item_num in all_sections:
            enhanced_sections[section_key] = all_sections[item_num].content
        else:
            enhanced_sections[section_key] = ""
    
    # Add additional sections not in original analyzer
    enhanced_sections['all_sections'] = all_sections
    enhanced_sections['tables'] = tables
    enhanced_sections['extractor'] = extractor
    
    return enhanced_sections


# Example usage with your existing analyzer
if __name__ == "__main__":
    # Test with sample content
    sample_10k = """
    TABLE OF CONTENTS
    
    PART I
    Item 1. Business
    We are a technology company...
    
    Item 1A. Risk Factors
    The following risk factors...
    
    Item 1B. Unresolved Staff Comments
    None.
    
    Item 2. Properties
    Our headquarters are located...
    
    PART II
    Item 5. Market for Registrant's Common Equity
    Our common stock is listed...
    
    Item 6. Selected Financial Data
    The following table sets forth...
    
    Item 7. Management's Discussion and Analysis
    The following discussion...
    
    Item 8. Financial Statements
    See consolidated financial statements...
    
    PART III
    Item 10. Directors, Executive Officers
    Information about our directors...
    
    Item 11. Executive Compensation
    Compensation information...
    
    PART IV
    Item 15. Exhibits
    The following exhibits are filed...
    """
    
    extractor = ComprehensiveSectionExtractor()
    sections = extractor.extract_all_sections(sample_10k)
    print(extractor.generate_table_of_contents())