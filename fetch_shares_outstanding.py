#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Fetch Shares Outstanding for F&O Stocks
One-time script to create shares_outstanding.json database
Uses Yahoo Finance (yfinance) - FREE, no API key needed
"""

import json
import yfinance as yf
import time
from typing import Dict
import os
import random

def load_stock_list() -> list:
    """Load F&O stock list from fo_stocks.json"""
    with open('fo_stocks.json', 'r') as f:
        data = json.load(f)
        return data['stocks']

def fetch_shares_outstanding(symbol: str, retry_count: int = 3) -> int:
    """
    Fetch shares outstanding for a single stock from Yahoo Finance
    With retry logic for rate limiting

    Args:
        symbol: Stock symbol (e.g., 'RELIANCE')
        retry_count: Number of retries for rate limit errors

    Returns:
        Shares outstanding (int) or None if failed
    """
    for attempt in range(retry_count):
        try:
            # Yahoo Finance requires .NS suffix for NSE stocks
            ticker = yf.Ticker(f"{symbol}.NS")
            info = ticker.info

            shares = info.get('sharesOutstanding')
            if shares and shares > 0:
                return int(shares)
            else:
                print(f"  ⚠️  {symbol}: No shares outstanding data")
                return None

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "Too Many Requests" in error_str:
                if attempt < retry_count - 1:
                    wait_time = (attempt + 1) * 5  # 5, 10, 15 seconds
                    print(f"  ⏳ {symbol}: Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  ❌ {symbol}: Rate limit - skipping")
                    return None
            else:
                print(f"  ❌ {symbol}: Error - {error_str[:50]}")
                return None

    return None

def fetch_all_shares(stocks: list) -> Dict[str, int]:
    """
    Fetch shares outstanding for all stocks

    Args:
        stocks: List of stock symbols

    Returns:
        Dictionary mapping symbol to shares outstanding
    """
    shares_data = {}
    total = len(stocks)
    success_count = 0

    print(f"\n{'='*60}")
    print(f"Fetching Shares Outstanding for {total} F&O Stocks")
    print(f"Source: Yahoo Finance (yfinance)")
    print(f"{'='*60}\n")

    for idx, symbol in enumerate(stocks, 1):
        print(f"[{idx}/{total}] {symbol}...", end=" ")

        shares = fetch_shares_outstanding(symbol)

        if shares:
            shares_data[symbol] = shares
            success_count += 1
            print(f"✓ {shares:,} shares")
        else:
            print()  # New line after error message

        # Rate limiting - be nice to Yahoo Finance (avoid 429 errors)
        # Use random delay between 3-6 seconds to avoid pattern detection
        if idx < total:
            delay = random.uniform(3.0, 6.0)
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
    print("\n🚀 Starting Shares Outstanding Fetcher\n")

    # Load stock list
    stocks = load_stock_list()
    print(f"📂 Loaded {len(stocks)} stocks from fo_stocks.json\n")

    # Fetch shares outstanding
    shares_data = fetch_all_shares(stocks)

    if not shares_data:
        print("❌ No data fetched. Exiting.")
        return

    # Save to file
    save_shares_data(shares_data)

    print(f"\n✅ Done! Shares outstanding database created.")
    print(f"📝 Update this data quarterly or when stock splits occur.\n")

if __name__ == "__main__":
    main()
