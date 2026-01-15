#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test the symbol variation logic
"""

import requests
from bs4 import BeautifulSoup
from typing import Optional, Tuple

def fetch_market_cap_with_variations(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """Test the fixed version with symbol variations"""
    print(f"\n{'='*80}")
    print(f"Testing: {symbol}")
    print('='*80)

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        # Try original symbol first, then variations if it fails
        symbols_to_try = [symbol]

        # If symbol has suffix (e.g., "SANWARIA-BZ"), try without suffix
        if '-' in symbol:
            base_symbol = symbol.split('-')[0]
            symbols_to_try.append(base_symbol)

        print(f"Will try: {symbols_to_try}")

        response = None
        successful_symbol = None

        for try_symbol in symbols_to_try:
            url = f"https://www.screener.in/company/{try_symbol}/"
            print(f"\nTrying: {url}")
            response = requests.get(url, headers=headers, timeout=10)
            print(f"Status: {response.status_code}")

            if response.status_code == 200:
                successful_symbol = try_symbol
                print(f"✓ SUCCESS with: {try_symbol}")
                break

        if not response or response.status_code != 200:
            print("❌ All variations failed")
            return None, None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find market cap
        market_cap_text = None
        for li in soup.find_all('li'):
            text = li.get_text(strip=True)
            if text.startswith('Market Cap'):
                market_cap_text = text.replace('Market Cap', '').replace('₹', '').replace('Cr.', '').replace(',', '').strip()
                break

        if not market_cap_text:
            print("❌ Market cap not found")
            return None, None

        market_cap_cr = float(market_cap_text)
        print(f"✓ Market Cap: ₹{market_cap_cr:,.2f} Cr")

        # Get current price (second 'number' span)
        number_spans = soup.find_all('span', class_='number')
        if len(number_spans) < 2:
            print(f"⚠️  Price not available (only {len(number_spans)} spans)")
            return market_cap_cr, None

        price = float(number_spans[1].text.replace(',', '').strip())
        shares = (market_cap_cr * 10_000_000) / price

        print(f"✓ Current Price: ₹{price:,.2f}")
        print(f"✓ Shares Outstanding: {shares:,.0f}")

        return market_cap_cr, shares

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def main():
    """Test with previously failing stocks"""
    print("="*80)
    print("TESTING SYMBOL VARIATION LOGIC")
    print("="*80)

    test_stocks = [
        'SANWARIA-BZ',   # Should try SANWARIA
        'GOLDSTAR-SM',   # Should try GOLDSTAR
        'OMFURN-SM',     # Should try OMFURN
        'RELIANCE',      # Should work as-is
        'TCS',           # Should work as-is
    ]

    results = {}
    for stock in test_stocks:
        market_cap, shares = fetch_market_cap_with_variations(stock)
        results[stock] = (market_cap is not None)

        import time
        time.sleep(2)

    print("\n" + "="*80)
    print("RESULTS SUMMARY")
    print("="*80)

    for stock, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{stock:20s} {status}")

    success_count = sum(results.values())
    print(f"\nTotal: {success_count}/{len(results)} stocks successful")
    print("="*80)


if __name__ == "__main__":
    main()
