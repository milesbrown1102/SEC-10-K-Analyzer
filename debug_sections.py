# debug_sections.py
"""
Debug script to understand why sections aren't being extracted
"""

from SEC10K import SEC10KAnalyzerOllama
import re

# Create analyzer
analyzer = SEC10KAnalyzerOllama(model_name="llama3.2")

# Test with Apple
print("Testing section extraction for AAPL...")
print("-" * 50)

# Get company CIK
cik = analyzer.get_company_cik("AAPL")
if not cik:
    print("Could not find company")
    exit()

# Get filing
filings = analyzer.get_recent_10k_filings(cik)
if not filings:
    print("No filings found")
    exit()

filing = filings[0]
print(f"Filing date: {filing['filing_date']}")

# Fetch content
content = analyzer.fetch_10k_content(cik, filing)
if not content:
    print("Could not fetch content")
    exit()

print(f"Content fetched: {len(content):,} characters")

# Let's check what's actually in the content
print("\nFirst 2000 characters of content:")
print("-" * 50)
print(content[:2000])

print("\n" + "="*50)
print("Looking for Item patterns in the filing...")
print("="*50)

# Search for various Item patterns
patterns_to_test = [
    r'item\s+1\.',
    r'item\s+1\s',
    r'item\s+1[^0-9]',
    r'part\s+i\b',
    r'business',
    r'risk\s+factors',
    r'item.*?business',
    r'(?i)item\s+1.*?business',
    r'(?i)part\s+i.*?item\s+1',
]

for pattern in patterns_to_test:
    matches = re.findall(pattern, content[:50000], re.IGNORECASE)
    if matches:
        print(f"✓ Pattern '{pattern}' found {len(matches)} times")
        print(f"  First match: {matches[0][:100]}")
    else:
        print(f"✗ Pattern '{pattern}' not found")

print("\n" + "="*50)
print("Testing current extract_sections method...")
print("="*50)

# Now test the actual method
sections = analyzer.extract_sections(content)

print(f"\nExtracted sections:")
for section_name, section_content in sections.items():
    if section_content:
        print(f"✓ {section_name}: {len(section_content)} chars")
    else:
        print(f"✗ {section_name}: EMPTY")

# Let's try a more flexible extraction
print("\n" + "="*50)
print("Attempting flexible extraction...")
print("="*50)

def flexible_extract(content):
    """Try various patterns to extract sections"""
    sections = {}
    
    # More flexible patterns
    flexible_patterns = {
        'business': [
            r'(?is)(item\s*1\.*\s*(?:—|-|–)?\s*business.*?)(?=item\s*1a|item\s*2|part\s*ii)',
            r'(?is)(item\s*1\s+business.*?)(?=item\s*1a|item\s*2)',
            r'(?is)(business\s*overview.*?)(?=risk\s*factors|item)',
        ],
        'risk_factors': [
            r'(?is)(item\s*1a\.*\s*(?:—|-|–)?\s*risk\s*factors.*?)(?=item\s*1b|item\s*2)',
            r'(?is)(risk\s*factors.*?)(?=item\s*1b|item\s*2|unresolved)',
        ],
        'mda': [
            r'(?is)(item\s*7\.*\s*(?:—|-|–)?\s*management.*?discussion.*?)(?=item\s*7a|item\s*8)',
            r'(?is)(management.*?discussion.*?analysis.*?)(?=item\s*7a|item\s*8|quantitative)',
        ]
    }
    
    for section_name, patterns in flexible_patterns.items():
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                sections[section_name] = match.group(1)[:5000]
                print(f"✓ Found {section_name} with pattern: {pattern[:50]}...")
                break
        if section_name not in sections:
            sections[section_name] = ""
            print(f"✗ Could not find {section_name}")
    
    return sections

flexible_sections = flexible_extract(content)

print("\n" + "="*50)
print("SUMMARY")
print("="*50)
print(f"Content size: {len(content):,} characters")
print(f"Standard extraction found: {sum(1 for s in sections.values() if s)} sections")
print(f"Flexible extraction found: {sum(1 for s in flexible_sections.values() if s)} sections")

# Check if content might be in a different format
if "Part I" in content[:10000] or "PART I" in content[:10000]:
    print("✓ Filing contains 'PART I' - standard 10-K structure detected")
else:
    print("⚠️ 'PART I' not found in first 10,000 chars - might be non-standard format")

# Save a sample for analysis
with open("sample_filing.txt", "w") as f:
    f.write(content[:20000])
    print("\nSaved first 20,000 chars to 'sample_filing.txt' for inspection")