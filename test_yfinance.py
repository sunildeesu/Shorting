#!/usr/bin/env python3
"""Test Yahoo Finance connectivity with a single stock"""

import yfinance as yf
from datetime import datetime

print("=" * 60)
print("Yahoo Finance API Test")
print("=" * 60)

# Test with RELIANCE
symbol = "RELIANCE.NS"
print(f"\nTesting symbol: {symbol}")
print(f"Current system time: {datetime.now()}")

try:
    ticker = yf.Ticker(symbol)
    print(f"\nTicker object created successfully")

    # Try to get info
    print("\nAttempting to fetch stock info...")
    info = ticker.info
    print(f"Stock name: {info.get('longName', 'N/A')}")
    print(f"Current price: ₹{info.get('currentPrice', 'N/A')}")
    print(f"Regular market price: ₹{info.get('regularMarketPrice', 'N/A')}")

    # Try fast_info
    print("\nAttempting to fetch fast_info...")
    print(f"Last price: ₹{ticker.fast_info.get('lastPrice', 'N/A')}")

    # Try history
    print("\nAttempting to fetch 1-day history...")
    hist = ticker.history(period="1d")
    print(hist)

    print("\n✅ SUCCESS: Yahoo Finance is working!")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    print(f"Error type: {type(e).__name__}")
    import traceback
    traceback.print_exc()
