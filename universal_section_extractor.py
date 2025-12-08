# universal_section_extractor.py
"""
Universal SEC 10-K Section Extractor
Finds ALL sections regardless of company-specific formatting
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass

@dataclass
class Section:
    """Represents a detected section"""
    item_number: str
    title: str
    content: str
    start_pos: int
    end_pos: int
    word_count: int
    char_count: int

def extract_all_sections(content: str) -> Dict[str, str]:
    """
    Universal section extractor that finds ALL sections in a 10-K
    Works with any company's formatting
    """
    if not content:
        return {}
    
    # Clean content for better matching
    content_clean = content.replace('—', '-').replace('–', '-').replace('−', '-')
    
    # Find ALL Item patterns in the document
    # This regex will find any "Item X" followed by text
    item_pattern = r'(?i)\b(item\s*(\d+[a-z]?\.?))\s*[-–—•·]?\s*([^\n\r]{3,100})'
    
    all_matches = []
    for match in re.finditer(item_pattern, content_clean):
        item_full = match.group(1)
        item_num = match.group(2).strip('.')
        item_title = match.group(3).strip()
        
        # Clean up the title
        item_title = re.sub(r'[\s\-–—•·]+$', '', item_title)
        item_title = re.sub(r'^[\s\-–—•·]+', '', item_title)
        
        # Skip if title is too short or looks like a continuation
        if len(item_title) < 3 or item_title[0].islower():
            continue
            
        all_matches.append({
            'pos': match.start(),
            'item': item_num,
            'title': item_title,
            'full_match': match.group(0)
        })
    
    # Sort by position
    all_matches.sort(key=lambda x: x['pos'])
    
    # Extract content for each section
    sections = {}
    
    for i, match in enumerate(all_matches):
        # Determine the end of this section (start of next section or end of document)
        if i + 1 < len(all_matches):
            end_pos = all_matches[i + 1]['pos']
        else:
            end_pos = len(content_clean)
        
        # Extract section content
        section_content = content_clean[match['pos']:end_pos]
        
        # Clean up section content
        section_content = section_content.strip()
        
        # Calculate metrics
        word_count = len(section_content.split())
        char_count = len(section_content)
        
        # Create section key (normalize item number)
        section_key = f"item_{match['item'].lower().replace('.', '')}"
        
        # Store section
        sections[section_key] = section_content[:50000]  # Limit to 50k chars per section
        
        # Also store with descriptive name for common sections
        descriptive_name = get_descriptive_name(match['item'], match['title'])
        if descriptive_name:
            sections[descriptive_name] = section_content[:50000]
    
    # If we didn't find standard Item patterns, try alternative approach
    if len(sections) < 5:
        print("⚠️ Few sections found with Item pattern. Trying alternative extraction...")
        alt_sections = extract_by_headers(content_clean)
        sections.update(alt_sections)
    
    # Special handling for table of contents
    toc = extract_table_of_contents(content_clean)
    if toc:
        sections['_table_of_contents'] = toc
        
        # Use TOC to find sections we might have missed
        toc_sections = parse_toc_for_sections(toc, content_clean)
        for key, value in toc_sections.items():
            if key not in sections and value:
                sections[key] = value
    
    return sections

def get_descriptive_name(item_num: str, title: str) -> str:
    """Map item numbers to descriptive section names"""
    title_lower = title.lower()
    
    # Map common item numbers to section names
    item_map = {
        '1': 'business',
        '1a': 'risk_factors',
        '1b': 'unresolved_comments',
        '2': 'properties',
        '3': 'legal_proceedings',
        '4': 'mine_safety',
        '5': 'market_for_equity',
        '6': 'financial_data',
        '7': 'mda',
        '7a': 'market_risk',
        '8': 'financial_statements',
        '9': 'disagreements',
        '9a': 'controls',
        '9b': 'other_info',
        '10': 'directors',
        '11': 'executive_compensation',
        '12': 'security_ownership',
        '13': 'relationships',
        '14': 'accountant_fees',
        '15': 'exhibits',
        '16': 'form_summary'
    }
    
    # Clean item number
    item_clean = item_num.lower().strip('.')
    
    # Try to match by item number
    if item_clean in item_map:
        return item_map[item_clean]
    
    # Try to match by title keywords
    if 'business' in title_lower:
        return 'business'
    elif 'risk' in title_lower and 'factor' in title_lower:
        return 'risk_factors'
    elif 'financial' in title_lower and 'data' in title_lower:
        return 'financial_data'
    elif 'management' in title_lower and 'discussion' in title_lower:
        return 'mda'
    elif 'financial' in title_lower and 'statement' in title_lower:
        return 'financial_statements'
    elif 'properties' in title_lower:
        return 'properties'
    elif 'legal' in title_lower:
        return 'legal_proceedings'
    elif 'control' in title_lower:
        return 'controls'
    elif 'director' in title_lower:
        return 'directors'
    elif 'compensation' in title_lower:
        return 'executive_compensation'
    elif 'exhibit' in title_lower:
        return 'exhibits'
    
    return None

def extract_by_headers(content: str) -> Dict[str, str]:
    """
    Alternative extraction method using common header patterns
    For companies that don't use standard Item numbering
    """
    sections = {}
    
    # Common section headers (without Item numbers)
    header_patterns = {
        'business': [
            r'(?i)^\s*(business\s*overview|our\s*business|company\s*overview)\s*$',
            r'(?i)^\s*(description\s*of\s*business)\s*$',
        ],
        'risk_factors': [
            r'(?i)^\s*(risk\s*factors?|risks?\s*and\s*uncertainties)\s*$',
            r'(?i)^\s*(factors\s*that\s*may\s*affect)\s*$',
        ],
        'financial_data': [
            r'(?i)^\s*(selected\s*financial\s*data)\s*$',
            r'(?i)^\s*(financial\s*highlights?|key\s*financial\s*data)\s*$',
        ],
        'mda': [
            r'(?i)^\s*(management[\'s]*\s*discussion\s*and\s*analysis)\s*$',
            r'(?i)^\s*(md&a|results\s*of\s*operations)\s*$',
        ],
        'financial_statements': [
            r'(?i)^\s*(financial\s*statements?)\s*$',
            r'(?i)^\s*(consolidated\s*financial\s*statements?)\s*$',
        ]
    }
    
    for section_name, patterns in header_patterns.items():
        for pattern in patterns:
            matches = list(re.finditer(pattern, content, re.MULTILINE))
            if matches:
                # Take the first match
                match = matches[0]
                start_pos = match.end()
                
                # Find the end (next major header or end of document)
                end_pos = len(content)
                for next_section_patterns in header_patterns.values():
                    for next_pattern in next_section_patterns:
                        next_matches = list(re.finditer(next_pattern, content[start_pos:], re.MULTILINE))
                        if next_matches:
                            potential_end = start_pos + next_matches[0].start()
                            if potential_end < end_pos and potential_end > start_pos:
                                end_pos = potential_end
                
                sections[section_name] = content[start_pos:end_pos][:50000]
                break
    
    return sections

def extract_table_of_contents(content: str) -> str:
    """Extract the table of contents if present"""
    toc_patterns = [
        r'(?is)(table\s*of\s*contents.*?)(?=part\s*i\b|item\s*1\b|\bpage\s*\d)',
        r'(?is)(index\s*to.*?)(?=part\s*i\b|item\s*1\b)',
        r'(?is)(contents\s*\n.*?)(?=part\s*i\b|item\s*1\b)',
    ]
    
    for pattern in toc_patterns:
        match = re.search(pattern, content[:30000])  # TOC usually at the beginning
        if match:
            return match.group(1)[:10000]
    
    return ""

def parse_toc_for_sections(toc: str, full_content: str) -> Dict[str, str]:
    """Parse the table of contents to find section locations"""
    sections = {}
    
    # Look for patterns like "Item 1. Business ... 5" (where 5 is page number)
    toc_entries = re.findall(r'(?i)(item\s*(\d+[a-z]?\.?))\s*[-–—]?\s*([^\n\r]{3,50})\s*\.+\s*(\d+)', toc)
    
    for entry in toc_entries:
        item_num = entry[1].strip('.')
        title = entry[2].strip()
        page_num = entry[3]
        
        # Try to find this section in the content
        section_key = f"item_{item_num.lower()}"
        
        # Search for the section header in the full content
        search_pattern = rf'(?i)\b{re.escape(entry[0])}\s*[-–—]?\s*{re.escape(title[:20])}'
        match = re.search(search_pattern, full_content)
        
        if match:
            start_pos = match.start()
            # Find next section or end
            end_pos = len(full_content)
            
            # Look for next Item
            next_item_pattern = r'(?i)\bitem\s*\d+[a-z]?\.?\s*[-–—]'
            next_matches = list(re.finditer(next_item_pattern, full_content[start_pos + 100:]))
            if next_matches:
                end_pos = start_pos + 100 + next_matches[0].start()
            
            sections[section_key] = full_content[start_pos:end_pos][:50000]
    
    return sections

def get_section_overview(content: str) -> Dict:
    """
    Get a complete overview of all sections found in the 10-K
    """
    sections = extract_all_sections(content)
    
    overview = {
        'total_sections': len(sections),
        'sections_found': [],
        'total_words': 0,
        'total_chars': 0,
        'section_details': []
    }
    
    # Standard 10-K sections to check
    standard_sections = [
        ('1', 'Business'),
        ('1a', 'Risk Factors'),
        ('1b', 'Unresolved Staff Comments'),
        ('2', 'Properties'),
        ('3', 'Legal Proceedings'),
        ('4', 'Mine Safety Disclosures'),
        ('5', 'Market for Registrant\'s Common Equity'),
        ('6', 'Selected Financial Data'),
        ('7', 'Management\'s Discussion and Analysis'),
        ('7a', 'Quantitative and Qualitative Disclosures About Market Risk'),
        ('8', 'Financial Statements and Supplementary Data'),
        ('9', 'Changes in and Disagreements with Accountants'),
        ('9a', 'Controls and Procedures'),
        ('9b', 'Other Information'),
        ('10', 'Directors, Executive Officers and Corporate Governance'),
        ('11', 'Executive Compensation'),
        ('12', 'Security Ownership'),
        ('13', 'Certain Relationships and Related Transactions'),
        ('14', 'Principal Accountant Fees and Services'),
        ('15', 'Exhibits and Financial Statement Schedules'),
    ]
    
    for item_num, title in standard_sections:
        section_key = f"item_{item_num}"
        if section_key in sections:
            content = sections[section_key]
            word_count = len(content.split())
            char_count = len(content)
            
            overview['sections_found'].append(item_num)
            overview['total_words'] += word_count
            overview['total_chars'] += char_count
            
            overview['section_details'].append({
                'item': item_num,
                'title': title,
                'found': True,
                'words': word_count,
                'chars': char_count
            })
        else:
            overview['section_details'].append({
                'item': item_num,
                'title': title,
                'found': False,
                'words': 0,
                'chars': 0
            })
    
    # Add any additional sections found that aren't standard
    for key, content in sections.items():
        if not key.startswith('item_') or key == '_table_of_contents':
            continue
        
        item_num = key.replace('item_', '')
        if item_num not in [s[0] for s in standard_sections]:
            word_count = len(content.split())
            char_count = len(content)
            
            overview['section_details'].append({
                'item': item_num,
                'title': f'Item {item_num}',
                'found': True,
                'words': word_count,
                'chars': char_count
            })
            
            overview['total_words'] += word_count
            overview['total_chars'] += char_count
    
    return overview