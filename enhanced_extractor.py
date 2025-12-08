# enhanced_extractor.py
"""
Enhanced section extraction that handles various 10-K formats
"""

import re
from typing import Dict

def enhanced_extract_sections(content: str) -> Dict[str, str]:
    """
    Enhanced extraction that handles various 10-K filing formats
    Including those with dashes, different spacing, and non-standard formatting
    """
    sections = {
        'business': '',
        'risk_factors': '',
        'financial_data': '',
        'mda': '',
        'financial_statements': ''
    }
    
    if not content:
        return sections
    
    # Clean content for better matching
    # Replace various dashes with standard dash
    content_clean = content.replace('—', '-').replace('–', '-').replace('−', '-')
    
    # Enhanced patterns that handle more variations
    patterns = {
        'business': [
            # Standard patterns
            r'(?is)item\s*1\s*\.?\s*(?:-|—|–)?\s*business(.*?)(?=item\s*1a|item\s*2|part\s*ii)',
            r'(?is)item\s*1\s+business(.*?)(?=item\s*1a|risk\s*factors)',
            # Apple-specific patterns (they sometimes use different formatting)
            r'(?is)item\s*1\s*\.\s*business(.*?)(?=item\s*1a)',
            r'(?is)(?:^|\n)\s*business\s*\n(.*?)(?=risk\s*factors)',
            # Fallback - just find business section
            r'(?is)business\s*(?:overview|description)?\s*\n(.*?)(?=risk|item\s*1a)',
        ],
        'risk_factors': [
            r'(?is)item\s*1a\s*\.?\s*(?:-|—|–)?\s*risk\s*factors(.*?)(?=item\s*1b|item\s*2|unresolved)',
            r'(?is)risk\s*factors\s*\n(.*?)(?=item\s*1b|item\s*2|unresolved\s*staff)',
            # More flexible pattern
            r'(?is)(?:item\s*1a|risk\s*factors)(.*?)(?=item\s*[12]|\bunresolved\b)',
        ],
        'financial_data': [
            r'(?is)item\s*6\s*\.?\s*(?:-|—|–)?\s*selected\s*financial\s*data(.*?)(?=item\s*7)',
            r'(?is)selected\s*financial\s*data\s*\n(.*?)(?=item\s*7|management)',
            # Also try consolidated variation
            r'(?is)item\s*6\s*\.?\s*(?:consolidated\s*)?selected\s*financial(.*?)(?=item\s*7)',
            # Fallback to just financial data
            r'(?is)financial\s*data\s*\n(.*?)(?=management|item\s*7)',
        ],
        'mda': [
            r'(?is)item\s*7\s*\.?\s*(?:-|—|–)?\s*management.*?discussion.*?analysis(.*?)(?=item\s*7a|item\s*8)',
            r'(?is)management.*?discussion.*?analysis\s*\n(.*?)(?=item\s*7a|item\s*8|quantitative)',
            # Shorter version
            r'(?is)item\s*7\s*\.?\s*md&a(.*?)(?=item\s*7a|item\s*8)',
            # Very flexible
            r'(?is)(?:management.*?discussion|md&a)(.*?)(?=item\s*7a|item\s*8|market\s*risk)',
        ],
        'financial_statements': [
            r'(?is)item\s*8\s*\.?\s*(?:-|—|–)?\s*financial\s*statements(.*?)(?=item\s*9)',
            r'(?is)financial\s*statements\s*and\s*supplementary\s*data(.*?)(?=item\s*9)',
            r'(?is)item\s*8\s*\.?\s*consolidated\s*financial\s*statements(.*?)(?=item\s*9)',
            # Fallback
            r'(?is)(?:consolidated\s*)?financial\s*statements(.*?)(?=item\s*9|changes\s*in)',
        ]
    }
    
    # Try each pattern for each section
    for section, pattern_list in patterns.items():
        for pattern in pattern_list:
            try:
                match = re.search(pattern, content_clean, re.DOTALL)
                if match:
                    # Get the content
                    section_content = match.group(1) if len(match.groups()) > 0 else match.group(0)
                    
                    # Clean up the content
                    section_content = section_content.strip()
                    
                    # Limit size but keep substantial content
                    sections[section] = section_content[:30000]  # Increased to 30k chars
                    
                    # If we found content, break out of the pattern loop
                    if len(section_content) > 100:  # Only count as found if substantial
                        break
            except Exception as e:
                continue
    
    # Special handling: If financial_data is empty but we have MDA, use part of MDA
    if not sections['financial_data'] and sections['mda']:
        sections['financial_data'] = sections['mda'][:10000]
    
    # Try to find any table of contents to understand structure
    toc_match = re.search(r'(?is)table\s*of\s*contents(.*?)(?:part\s*i\b|item\s*1\b)', content_clean[:20000])
    if toc_match:
        sections['_toc'] = toc_match.group(1)[:5000]
    
    # Count how many sections we found
    found = sum(1 for s in sections.values() if s and len(s) > 100)
    
    # If we found very few sections, the format might be completely different
    if found < 2:
        # Try a last-ditch effort to find any content
        print(f"⚠️ Only found {found} sections. Attempting fallback extraction...")
        
        # Just try to find major sections by keywords
        fallback_patterns = {
            'business': r'(?is)(our\s*business|company\s*overview|what\s*we\s*do)(.*?)(?=risk|financial|management)',
            'risk_factors': r'(?is)(risks?\s*(?:factors?|considerations?))(.*?)(?=financial|management|business)',
            'mda': r'(?is)(management.*?discussion|results\s*of\s*operations)(.*?)(?=financial|item|part)',
        }
        
        for section, pattern in fallback_patterns.items():
            if not sections[section]:  # Only if we haven't found it yet
                match = re.search(pattern, content_clean[:100000])
                if match:
                    sections[section] = match.group(2) if len(match.groups()) > 1 else match.group(0)
                    sections[section] = sections[section][:20000]
    
    return sections


def monkey_patch_enhanced_extraction(analyzer_class):
    """
    Monkey patch the SEC10KAnalyzerOllama class with better extraction
    """
    analyzer_class.extract_sections = enhanced_extract_sections
    return analyzer_class