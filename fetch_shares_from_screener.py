#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Fetch Market Cap from Screener.in (Indian Stock Data Source)
Calculate shares outstanding from: Shares = Market Cap / Current Price
Uses web scraping - more reliable for NSE stocks than Yahoo Finance
"""

import json
import requests
from bs4 import BeautifulSoup
import time
import os
from typing import Dict, Tuple
import random

def load_stock_list() -> list:
    """Load F&O stock list from fo_stocks.json"""
    with open('fo_stocks.json', 'r') as f:
        data = json.load(f)
        return data['stocks']

def fetch_market_cap_from_screener(symbol: str) -> Tuple[float, float]:
    """
    Fetch market cap and current price from Screener.in

    Args:
        symbol: Stock symbol (e.g., 'RELIANCE')

    Returns:
        Tuple of (market_cap_cr, current_price) or (None, None) if failed
    """
    try:
        url = f"https://www.screener.in/company/{symbol}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find market cap (format: "Market Cap ₹ 20,01,385 Cr.")
        market_cap_cr = None
        current_price = None

        # Look for market cap in the page
        for li in soup.find_all('li'):
            text = li.get_text()
            if 'Market Cap' in text:
                # Extract number from "Market Cap ₹ 20,01,385 Cr."
                parts = text.split('₹')
                if len(parts) > 1:
                    cap_str = parts[1].replace('Cr.', '').replace(',', '').strip()
                    try:
                        market_cap_cr = float(cap_str)
                    except:
                        pass

            # Look for current price
            if 'Current Price' in text or text.strip().startswith('₹'):
                # Extract price
                parts = text.split('₹')
                if len(parts) > 1:
                    price_str = parts[1].split()[0].replace(',', '')
                    try:
                        current_price = float(price_str)
                    except:
                        pass

        # Alternative: Check for price in specific div
        if not current_price:
            price_elem = soup.select_one('#top-ratios .number')
            if price_elem:
                try:
                    current_price = float(price_elem.text.replace(',', ''))
                except:
                    pass

        if market_cap_cr and current_price:
            return market_cap_cr, current_price
        else:
            print(f"  ⚠️  {symbol}: Missing data (cap={market_cap_cr}, price={current_price})")
            return None, None

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"  ❌ {symbol}: Not found on screener.in")
        else:
            print(f"  ❌ {symbol}: HTTP {e.response.status_code}")
        return None, None
    except Exception as e:
        print(f"  ❌ {symbol}: Error - {str(e)[:50]}")
        return None, None

def fetch_all_market_caps(stocks: list) -> Dict[str, int]:
    """
    Fetch market cap and calculate shares outstanding for all stocks

    Args:
        stocks: List of stock symbols

    Returns:
        Dictionary mapping symbol to shares outstanding
    """
    shares_data = {}
    total = len(stocks)
    success_count = 0

    print(f"\n{'='*60}")
    print(f"Fetching Market Cap for {total} F&O Stocks")
    print(f"Source: Screener.in (Indian Stock Data)")
    print(f"{'='*60}\n")

    for idx, symbol in enumerate(stocks, 1):
        print(f"[{idx}/{total}] {symbol}...", end=" ")

        market_cap_cr, current_price = fetch_market_cap_from_screener(symbol)

        if market_cap_cr and current_price:
            # Calculate shares outstanding
            # Market Cap (Crores) = Price × Shares (Crores)
            # Shares (Crores) = Market Cap (Cr) / Price
            shares_cr = market_cap_cr / current_price
            shares = int(shares_cr * 10000000)  # Convert crores to actual number

            shares_data[symbol] = shares
            success_count += 1
            print(f"✓ Cap: ₹{market_cap_cr:,.0f} Cr, Price: ₹{current_price:.2f}, Shares: {shares:,}")
        else:
            print()  # New line after error

        # Rate limiting - be respectful to screener.in
        if idx < total:
            delay = random.uniform(2.0, 4.0)
            time.sleep(delay)

    print(f"\n{'='*60}")
    print(f"✅ Success: {success_count}/{total} stocks ({success_count/total*100:.1f}%)")
    print(f"❌ Failed: {total - success_count} stocks")
    print(f"{'='*60}\n")

    return shares_data

def save_shares_data(shares_data: Dict[str, int], filename: str = 'data/shares_outstanding.json'):
    """Save shares outstanding data to JSON file"""

    # Ensure data directory exists
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    # Save with nice formatting
    with open(filename, 'w') as f:
        json.dump(shares_data, f, indent=2, sort_keys=True)

    print(f"💾 Saved to: {filename}")
    print(f"📊 Total stocks: {len(shares_data)}")

    # Show sample data
    print(f"\n📋 Sample entries:")
    for symbol, shares in list(shares_data.items())[:5]:
        print(f"  {symbol}: {shares:,} shares")

def main():
    """Main execution"""
    print("\n🚀 Starting Market Cap Fetcher (Screener.in)\n")

    # Load stock list
    stocks = load_stock_list()
    print(f"📂 Loaded {len(stocks)} stocks from fo_stocks.json\n")

    # Fetch market caps and calculate shares
    shares_data = fetch_all_market_caps(stocks)

    if not shares_data:
        print("❌ No data fetched. Exiting.")
        return

    # Save to file
    save_shares_data(shares_data)

    print(f"\n✅ Done! Shares outstanding database created.")
    print(f"📝 Market cap will be calculated as: Price × Shares Outstanding\n")

if __name__ == "__main__":
    main()
