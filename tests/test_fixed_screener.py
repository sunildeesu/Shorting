#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test the FIXED Screener.in scraping logic
"""

import requests
from bs4 import BeautifulSoup
from typing import Optional, Tuple, List, Dict

def fetch_market_cap_fixed(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """Test fixed market cap fetching"""
    print(f"\n{'='*80}")
    print(f"Testing Market Cap: {symbol}")
    print('='*80)

    try:
        url = f"https://www.screener.in/company/{symbol}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"❌ Status code: {response.status_code}")
            return None, None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find market cap
        market_cap_text = None
        for li in soup.find_all('li'):
            text = li.get_text(strip=True)
            if text.startswith('Market Cap'):
                # Extract just the number part
                market_cap_text = text.replace('Market Cap', '').replace('₹', '').replace('Cr.', '').replace(',', '').strip()
                break

        if not market_cap_text:
            print("❌ Market cap not found")
            return None, None

        market_cap_cr = float(market_cap_text)
        print(f"✓ Market Cap: ₹{market_cap_cr:,.0f} Cr")

        # Get current price (second 'number' span - FIXED)
        number_spans = soup.find_all('span', class_='number')
        if len(number_spans) < 2:
            print("❌ Price not found (less than 2 number spans)")
            return market_cap_cr, None

        price = float(number_spans[1].text.replace(',', '').strip())
        print(f"✓ Current Price: ₹{price:,.2f}")

        # Calculate shares
        shares = (market_cap_cr * 10_000_000) / price
        print(f"✓ Shares Outstanding: {shares:,.0f}")

        return market_cap_cr, shares

    except Exception as e:
        print(f"❌ Error: {e}")
        return None, None


def scrape_fundamentals_fixed(symbol: str) -> Optional[List[Dict]]:
    """Test fixed quarterly data extraction"""
    print(f"\n{'='*80}")
    print(f"Testing Quarterly Data: {symbol}")
    print('='*80)

    try:
        url = f"https://www.screener.in/company/{symbol}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"❌ Status code: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the first table with quarterly data
        quarterly_table = None
        all_tables = soup.find_all('table')
        for table in all_tables:
            table_text = table.get_text()
            if 'Mar' in table_text and 'Sep' in table_text and 'Sales' in table_text:
                quarterly_table = table
                break

        if not quarterly_table:
            print("❌ Quarterly table not found")
            return None

        print("✓ Found quarterly table")

        # Extract data
        rows = quarterly_table.find_all('tr')
        if len(rows) < 2:
            print("❌ Insufficient rows")
            return None

        # Get quarter names from header
        header_row = rows[0]
        header_cells = header_row.find_all(['th', 'td'])
        quarters = [cell.text.strip() for cell in header_cells[1:]]
        print(f"✓ Quarters: {quarters[:8]}")

        # Find Sales and Net Profit rows
        revenue_row = None
        pat_row = None

        for row in rows[1:]:
            cells = row.find_all('td')
            if not cells:
                continue

            row_label = cells[0].text.strip()
            if 'Sales' in row_label:
                revenue_row = cells
                print(f"✓ Found revenue row: {row_label}")
            elif 'Net Profit' in row_label and 'NP' not in row_label:
                pat_row = cells
                print(f"✓ Found PAT row: {row_label}")

        if not revenue_row or not pat_row:
            print("❌ Could not find Sales or Net Profit row")
            return None

        # Extract quarterly data
        quarters_data = []
        for i in range(min(len(quarters), len(revenue_row) - 1, len(pat_row) - 1, 12)):
            try:
                quarter_name = quarters[i]
                revenue_text = revenue_row[i + 1].text.strip().replace(',', '')
                pat_text = pat_row[i + 1].text.strip().replace(',', '')

                revenue = float(revenue_text)
                pat = float(pat_text)

                quarters_data.append({
                    'quarter': quarter_name,
                    'revenue': revenue,
                    'pat': pat
                })

            except (ValueError, IndexError) as e:
                continue

        print(f"\n✓ Extracted {len(quarters_data)} quarters:")
        for q in quarters_data[:4]:
            print(f"  {q['quarter']}: Revenue ₹{q['revenue']:,.0f} Cr, PAT ₹{q['pat']:,.0f} Cr")

        return quarters_data

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Test with sample stocks"""
    print("="*80)
    print("TESTING FIXED SCREENER.IN SCRAPING")
    print("="*80)

    test_stocks = ['RELIANCE', 'TCS', 'INFY']

    for symbol in test_stocks:
        # Test market cap
        market_cap, shares = fetch_market_cap_fixed(symbol)

        # Test fundamentals
        quarters_data = scrape_fundamentals_fixed(symbol)

        if market_cap and quarters_data:
            print(f"\n✅ {symbol}: SUCCESS - Both market cap and quarterly data extracted correctly")
        else:
            print(f"\n❌ {symbol}: FAILED")

        print("")
        import time
        time.sleep(3)

    print("="*80)
    print("TEST COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
