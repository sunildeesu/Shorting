#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test why specific stocks are failing to fetch from Screener.in
"""

import requests
from bs4 import BeautifulSoup

def test_stock(symbol: str):
    """Test a specific stock and show detailed debug info"""
    print(f"\n{'='*80}")
    print(f"Testing: {symbol}")
    print('='*80)

    try:
        url = f"https://www.screener.in/company/{symbol}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        print(f"URL: {url}")
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status Code: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ Failed with status {response.status_code}")

            # Try common variations
            print("\nTrying variations...")
            variations = [
                symbol.replace('-', ''),  # Remove hyphens
                symbol.split('-')[0],      # First part only
            ]

            for var in variations:
                var_url = f"https://www.screener.in/company/{var}/"
                print(f"  Trying: {var_url}")
                var_response = requests.get(var_url, headers=headers, timeout=10)
                if var_response.status_code == 200:
                    print(f"  ✓ SUCCESS with variation: {var}")
                    symbol = var
                    response = var_response
                    break
                else:
                    print(f"  ✗ Failed: {var_response.status_code}")

            if response.status_code != 200:
                return

        soup = BeautifulSoup(response.text, 'html.parser')

        # Look for market cap in all possible locations
        print("\nSearching for Market Cap...")

        # Method 1: In <li> elements
        found = False
        for li in soup.find_all('li'):
            text = li.get_text(strip=True)
            if 'Market Cap' in text:
                print(f"✓ Found in <li>: {text}")
                found = True
                break

        if not found:
            print("❌ Not found in <li> elements")

            # Method 2: Search entire page for "Market Cap"
            print("\nSearching entire page text...")
            page_text = soup.get_text()
            if 'Market Cap' in page_text:
                print("✓ 'Market Cap' text exists on page")
                # Find context around it
                idx = page_text.find('Market Cap')
                print(f"  Context: {page_text[idx:idx+100]}")
            else:
                print("❌ 'Market Cap' text NOT found anywhere on page")

                # Check if it's a valid company page
                if 'Page not found' in page_text or '404' in page_text:
                    print("❌ This appears to be a 404 page - company not found on Screener.in")
                elif 'Screener' in soup.title.text if soup.title else False:
                    print("⚠️  Valid Screener page but no market cap data (possibly unlisted/delisted)")
                else:
                    print("❌ Unknown page structure")

        # Check for current price
        print("\nSearching for Current Price...")
        number_spans = soup.find_all('span', class_='number')
        if len(number_spans) >= 2:
            print(f"✓ Found {len(number_spans)} number spans:")
            for i, span in enumerate(number_spans[:5]):
                print(f"  [{i}] {span.text.strip()}")
        else:
            print(f"❌ Only found {len(number_spans)} number span(s)")

    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Test problematic stocks"""
    print("="*80)
    print("TESTING FAILING STOCKS")
    print("="*80)

    # Test the failing stocks reported in logs
    failing_stocks = [
        'SANWARIA-BZ',   # From user's error
        'GOLDSTAR-SM',   # From previous logs
        'OMFURN-SM',     # From previous logs
        '656KA30-SG',    # From previous logs (should be filtered now)
    ]

    for stock in failing_stocks:
        test_stock(stock)
        import time
        time.sleep(2)

    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
