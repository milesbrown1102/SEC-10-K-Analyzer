# integrate_full_extraction.py
"""
Integration code to add comprehensive section extraction to your existing analyzer
"""

def monkey_patch_extract_sections(analyzer_class):
    """
    Replace the extract_sections method with comprehensive version
    """
    
    original_extract = analyzer_class.extract_sections
    
    def extract_sections_comprehensive(self, content: str):
        """
        Enhanced extraction that gets ALL sections
        """
        import re
        
        # All 10-K sections with better patterns
        ALL_PATTERNS = {
            # Core sections (your existing ones)
            'business': r'(?is)(item\s+1\.*\s*(?:business|overview).*?)(?=item\s+1a\b|item\s+2\b)',
            'risk_factors': r'(?is)(item\s+1a\.*\s*risk\s*factors.*?)(?=item\s+1b\b|item\s+2\b)',
            'financial_data': r'(?is)(item\s+6\.*\s*(?:selected|key)\s*financial\s*data.*?)(?=item\s+7\b)',
            'mda': r'(?is)(item\s+7\.*\s*management.*?discussion.*?analysis.*?)(?=item\s+7a\b|item\s+8\b)',
            'financial_statements': r'(?is)(item\s+8\.*\s*financial\s*statements.*?)(?=item\s+9\b)',
            
            # Additional important sections often missed
            'unresolved_comments': r'(?is)(item\s+1b\.*\s*unresolved\s*staff\s*comments.*?)(?=item\s+2\b)',
            'properties': r'(?is)(item\s+2\.*\s*properties.*?)(?=item\s+3\b)',
            'legal_proceedings': r'(?is)(item\s+3\.*\s*legal\s*proceedings.*?)(?=item\s+4\b)',
            'mine_safety': r'(?is)(item\s+4\.*\s*mine\s*safety.*?)(?=item\s+5\b|part\s+ii)',
            
            # Part II sections
            'market_for_equity': r'(?is)(item\s+5\.*\s*market\s*for.*?common.*?)(?=item\s+6\b)',
            'market_risk': r'(?is)(item\s+7a\.*\s*quantitative.*?qualitative.*?)(?=item\s+8\b)',
            'disagreements': r'(?is)(item\s+9\.*\s*changes.*?disagreements.*?)(?=item\s+9a\b)',
            'controls': r'(?is)(item\s+9a\.*\s*controls.*?procedures.*?)(?=item\s+9b\b|item\s+10\b)',
            'other_info': r'(?is)(item\s+9b\.*\s*other\s*information.*?)(?=item\s+10\b|part\s+iii)',
            
            # Part III sections (governance/compensation)
            'directors': r'(?is)(item\s+10\.*\s*directors.*?executive.*?)(?=item\s+11\b)',
            'executive_compensation': r'(?is)(item\s+11\.*\s*executive\s*compensation.*?)(?=item\s+12\b)',
            'security_ownership': r'(?is)(item\s+12\.*\s*security\s*ownership.*?)(?=item\s+13\b)',
            'relationships': r'(?is)(item\s+13\.*\s*certain\s*relationships.*?)(?=item\s+14\b)',
            'accountant_fees': r'(?is)(item\s+14\.*\s*principal.*?account.*?fees.*?)(?=item\s+15\b|part\s+iv)',
            
            # Part IV
            'exhibits': r'(?is)(item\s+15\.*\s*exhibits.*?)(?=signatures|$)'
        }
        
        sections = {}
        sections_found = []
        sections_missing = []
        
        print("\n📚 Extracting comprehensive 10-K sections...")
        print("-" * 50)
        
        for section_name, pattern in ALL_PATTERNS.items():
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                # Extract and clean the section
                section_content = match.group(1)
                
                # Clean excessive whitespace
                section_content = re.sub(r'\n{3,}', '\n\n', section_content)
                section_content = re.sub(r'[ \t]+', ' ', section_content)
                
                # Limit size but keep substantial content
                sections[section_name] = section_content[:30000]  # 30k chars per section
                
                word_count = len(section_content.split())
                sections_found.append(f"✓ {section_name:25s} ({word_count:,} words)")
            else:
                sections[section_name] = ""
                sections_missing.append(f"✗ {section_name:25s}")
        
        # Print extraction summary
        print("\nSections Found:")
        for s in sections_found:
            print(f"  {s}")
        
        if sections_missing:
            print("\nSections Missing:")
            for s in sections_missing:
                print(f"  {s}")
        
        print(f"\n📊 Extraction Summary:")
        print(f"  Total sections found: {len(sections_found)}/{len(ALL_PATTERNS)}")
        print(f"  Coverage: {len(sections_found)/len(ALL_PATTERNS)*100:.1f}%")
        
        # Ensure backward compatibility - if financial_data is empty, use MDA
        if not sections.get('financial_data') and sections.get('mda'):
            sections['financial_data'] = sections['mda'][:10000]
        
        # Extract key financial metrics from any section
        financial_metrics = self._extract_financial_metrics(content)
        if financial_metrics:
            sections['extracted_metrics'] = financial_metrics
        
        return sections
    
    def _extract_financial_metrics(self, content: str):
        """
        Extract key financial metrics from anywhere in the filing
        """
        import re
        
        metrics = {}
        
        # Revenue patterns
        revenue_patterns = [
            (r'\$?([\d,]+\.?\d*)\s*(?:million|billion)\s+.*?(?:revenue|sales)', 'revenue'),
            (r'(?:revenue|sales).*?\$?([\d,]+\.?\d*)\s*(?:million|billion)', 'revenue'),
        ]
        
        # Net income patterns
        income_patterns = [
            (r'net\s+income.*?\$?([\d,]+\.?\d*)\s*(?:million|billion)', 'net_income'),
            (r'\$?([\d,]+\.?\d*)\s*(?:million|billion).*?net\s+income', 'net_income'),
        ]
        
        # Extract metrics
        for patterns, metric_name in [(revenue_patterns, 'revenue'), (income_patterns, 'net_income')]:
            for pattern, name in patterns:
                matches = re.findall(pattern, content[:50000], re.IGNORECASE)
                if matches:
                    try:
                        value = matches[0].replace(',', '')
                        metrics[name] = float(value)
                        break
                    except:
                        pass
        
        return str(metrics) if metrics else ""
    
    # Replace the method
    analyzer_class.extract_sections = extract_sections_comprehensive
    analyzer_class._extract_financial_metrics = _extract_financial_metrics
    
    return analyzer_class


# Easy integration function
def upgrade_to_full_extraction():
    """
    Simple function to upgrade your existing SEC10K analyzer
    """
    from SEC10K import SEC10KAnalyzerOllama
    
    # Monkey patch the class
    monkey_patch_extract_sections(SEC10KAnalyzerOllama)
    
    print("✅ Upgraded to comprehensive section extraction!")
    print("Your analyzer now extracts ALL 20+ sections of the 10-K filing")
    
    return SEC10KAnalyzerOllama


# For your Streamlit app - add this at the top
def initialize_enhanced_analyzer(model_name="llama3.2"):
    """
    Initialize analyzer with full section extraction
    """
    from SEC10K import SEC10KAnalyzerOllama
    
    # Apply the enhancement
    monkey_patch_extract_sections(SEC10KAnalyzerOllama)
    
    # Create instance
    analyzer = SEC10KAnalyzerOllama(model_name=model_name)
    
    return analyzer


# Test it
if __name__ == "__main__":
    # Test the enhancement
    enhanced_class = upgrade_to_full_extraction()
    analyzer = enhanced_class()
    
    # Now it will extract ALL sections
    print("\n🚀 Your analyzer now extracts:")
    print("  • Item 1: Business")
    print("  • Item 1A: Risk Factors") 
    print("  • Item 1B: Unresolved Staff Comments")
    print("  • Item 2: Properties")
    print("  • Item 3: Legal Proceedings")
    print("  • Item 4: Mine Safety")
    print("  • Item 5: Market for Common Equity")
    print("  • Item 6: Selected Financial Data")
    print("  • Item 7: MD&A")
    print("  • Item 7A: Market Risk")
    print("  • Item 8: Financial Statements")
    print("  • Item 9: Changes with Accountants")
    print("  • Item 9A: Controls and Procedures")
    print("  • Item 10: Directors & Officers")
    print("  • Item 11: Executive Compensation")
    print("  • Item 12: Security Ownership")
    print("  • Item 13: Related Transactions")
    print("  • Item 14: Accountant Fees")
    print("  • Item 15: Exhibits")
    print("\n  Plus financial metrics extraction!")