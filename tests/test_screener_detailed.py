#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Detailed test to understand Screener.in HTML structure
"""

import requests
from bs4 import BeautifulSoup

def analyze_screener_page(symbol: str):
    """Analyze the actual HTML structure"""
    print(f"\n{'='*80}")
    print(f"Analyzing Screener.in page for: {symbol}")
    print('='*80)

    url = f"https://www.screener.in/company/{symbol}/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }

    response = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(response.text, 'html.parser')

    print(f"\n1. LOOKING FOR CURRENT PRICE:")
    print("-" * 80)

    # Find price in various locations
    # Method 1: Look for price in top section
    top_ratios = soup.find('ul', id='top-ratios')
    if top_ratios:
        for li in top_ratios.find_all('li'):
            text = li.get_text(strip=True)
            if 'Current Price' in text or '₹' in text[:50]:
                print(f"Found in top-ratios: {text}")

    # Method 2: Look for the first prominent number
    numbers = soup.find_all('span', class_='number')
    if numbers:
        print(f"\nFirst 5 'number' class elements:")
        for i, num in enumerate(numbers[:5]):
            parent_text = num.parent.get_text(strip=True) if num.parent else ""
            print(f"  [{i}] {num.text.strip()} - Context: {parent_text[:80]}")

    print(f"\n2. LOOKING FOR MARKET CAP:")
    print("-" * 80)

    # Find market cap
    for li in soup.find_all('li'):
        text = li.get_text(strip=True)
        if 'Market Cap' in text:
            print(f"Found: {text}")

    print(f"\n3. LOOKING FOR QUARTERLY RESULTS TABLE:")
    print("-" * 80)

    # Find all tables
    all_tables = soup.find_all('table')
    print(f"Total tables found: {len(all_tables)}")

    for idx, table in enumerate(all_tables):
        # Check if this table has quarterly data
        table_text = table.get_text()
        if any(month in table_text for month in ['Mar', 'Jun', 'Sep', 'Dec']):
            print(f"\nTable {idx} - Contains quarterly data")

            # Show headers
            headers = table.find_all('th')
            if headers:
                header_texts = [h.get_text(strip=True) for h in headers]
                print(f"  Headers ({len(header_texts)}): {header_texts[:10]}")

            # Show first 3 data rows
            rows = table.find_all('tr')
            print(f"  Total rows: {len(rows)}")
            print(f"  First 3 rows:")
            for i, row in enumerate(rows[:3]):
                cells = row.find_all(['td', 'th'])
                cell_texts = [c.get_text(strip=True) for c in cells]
                print(f"    Row {i}: {cell_texts[:8]}")

    print("\n" + "="*80)


# Test with RELIANCE
analyze_screener_page('RELIANCE')
