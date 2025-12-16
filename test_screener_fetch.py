#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test script to verify Screener.in data fetching
"""

import requests
from bs4 import BeautifulSoup
import time

def test_screener_market_cap(symbol: str):
    """Test fetching market cap from Screener.in"""
    print(f"\n{'='*60}")
    print(f"Testing: {symbol}")
    print('='*60)

    try:
        url = f"https://www.screener.in/company/{symbol}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        print(f"Fetching: {url}")
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status Code: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ Failed to fetch (status {response.status_code})")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find market cap
        market_cap_text = None
        for li in soup.find_all('li', class_='flex'):
            span = li.find('span', class_='name')
            if span and 'Market Cap' in span.text:
                value_span = li.find('span', class_='number')
                if value_span:
                    market_cap_text = value_span.text.strip()
                    break

        if not market_cap_text:
            print("❌ Market cap not found in page")
            print("\nSearching for alternative patterns...")

            # Debug: Show all <li> elements
            all_lis = soup.find_all('li')
            print(f"Found {len(all_lis)} <li> elements")

            # Try to find any text containing "Market Cap"
            for tag in soup.find_all(text=lambda text: text and 'Market Cap' in text):
                print(f"Found 'Market Cap' in: {tag.parent.name} - {tag}")

            return None

        print(f"✓ Raw Market Cap Text: {market_cap_text}")

        # Parse market cap
        market_cap_str = market_cap_text.replace('₹', '').replace('Cr.', '').replace(',', '').strip()
        market_cap_cr = float(market_cap_str)
        print(f"✓ Parsed Market Cap: ₹{market_cap_cr:,.0f} Cr")

        # Get current price
        price_tag = soup.find('span', class_='number')
        if price_tag:
            price_text = price_tag.text.replace(',', '').strip()
            price = float(price_text)
            print(f"✓ Current Price: ₹{price:,.2f}")

            # Calculate shares outstanding
            shares = (market_cap_cr * 10_000_000) / price
            print(f"✓ Shares Outstanding: {shares:,.0f}")

            return {
                'market_cap_cr': market_cap_cr,
                'price': price,
                'shares': shares
            }
        else:
            print("⚠ Price not found, but market cap available")
            return {
                'market_cap_cr': market_cap_cr,
                'price': None,
                'shares': None
            }

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_screener_fundamentals(symbol: str):
    """Test fetching Revenue/PAT from Screener.in"""
    print(f"\n{'='*60}")
    print(f"Testing Fundamentals: {symbol}")
    print('='*60)

    try:
        url = f"https://www.screener.in/company/{symbol}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        print(f"Fetching: {url}")
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Status Code: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ Failed to fetch (status {response.status_code})")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find quarterly results table
        quarterly_table = None
        for section in soup.find_all('section', id='quarters'):
            table = section.find('table', class_='data-table')
            if table:
                quarterly_table = table
                break

        if not quarterly_table:
            print("❌ Quarterly results table not found")

            # Debug: Try to find the table with different selectors
            print("\nSearching for alternative table patterns...")
            all_tables = soup.find_all('table')
            print(f"Found {len(all_tables)} tables total")

            for i, table in enumerate(all_tables):
                if 'quarter' in str(table).lower():
                    print(f"Table {i} contains 'quarter'")

            return None

        print("✓ Found quarterly results table")

        # Extract quarterly data
        quarters_data = []
        rows = quarterly_table.find_all('tr')
        print(f"Found {len(rows)} rows in table")

        # Show headers
        if rows:
            headers = [th.text.strip() for th in rows[0].find_all('th')]
            print(f"Headers: {headers}")

        for idx, row in enumerate(rows[1:13], 1):  # Get last 12 quarters
            cols = row.find_all('td')
            if len(cols) < 4:
                continue

            quarter = cols[0].text.strip()
            revenue_text = cols[1].text.strip().replace(',', '')
            pat_text = cols[3].text.strip().replace(',', '')

            try:
                revenue = float(revenue_text)
                pat = float(pat_text)

                quarters_data.append({
                    'quarter': quarter,
                    'revenue': revenue,
                    'pat': pat
                })

                print(f"  Q{idx}: {quarter} - Revenue: ₹{revenue:,.0f} Cr, PAT: ₹{pat:,.0f} Cr")
            except ValueError:
                print(f"  Q{idx}: {quarter} - Could not parse (Revenue: {revenue_text}, PAT: {pat_text})")

        if quarters_data:
            print(f"\n✓ Successfully extracted {len(quarters_data)} quarters of data")
            return quarters_data
        else:
            print("\n❌ No quarterly data could be extracted")
            return None

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Test with sample stocks"""
    print("="*60)
    print("SCREENER.IN DATA FETCH VERIFICATION")
    print("="*60)

    # Test stocks
    test_stocks = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK']

    for symbol in test_stocks:
        # Test market cap fetching
        market_cap_data = test_screener_market_cap(symbol)

        time.sleep(2)  # Rate limiting

        # Test fundamentals fetching
        fundamentals_data = test_screener_fundamentals(symbol)

        if market_cap_data and fundamentals_data:
            print(f"\n✅ {symbol}: Both market cap and fundamentals fetched successfully")
        elif market_cap_data:
            print(f"\n⚠️  {symbol}: Market cap OK, but fundamentals failed")
        elif fundamentals_data:
            print(f"\n⚠️  {symbol}: Fundamentals OK, but market cap failed")
        else:
            print(f"\n❌ {symbol}: Both failed")

        time.sleep(4)  # Rate limiting between stocks

    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()
