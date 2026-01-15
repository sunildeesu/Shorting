#!/usr/bin/env python3
"""Test Yahoo Finance with a single stock to verify connectivity"""

import yfinance as yf
from datetime import datetime

symbol = "RELIANCE.NS"

print("=" * 60)
print("Testing Yahoo Finance API - Single Stock Test")
print("=" * 60)
print(f"Symbol: {symbol}")
print(f"Current time: {datetime.now()}")
print()

try:
    print("Method 1: Using Ticker.info")
    print("-" * 60)
    ticker = yf.Ticker(symbol)

    # Try to get basic info
    try:
        info = ticker.info
        if info:
            print(f"✓ Company Name: {info.get('longName', 'N/A')}")
            print(f"✓ Current Price: ₹{info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))}")
            print(f"✓ Previous Close: ₹{info.get('previousClose', 'N/A')}")
            print(f"✓ Market Cap: {info.get('marketCap', 'N/A')}")
            print("\n✅ SUCCESS: Yahoo Finance .info is working!")
        else:
            print("❌ Info is empty")
    except Exception as e:
        print(f"❌ FAILED with .info: {e}")

    print("\n" + "=" * 60)
    print("Method 2: Using Ticker.history()")
    print("-" * 60)

    # Try different periods
    for period in ["1d", "5d"]:
        try:
            print(f"\nTrying period={period}...")
            hist = ticker.history(period=period)

            if not hist.empty:
                latest = hist.iloc[-1]
                print(f"✓ Date: {hist.index[-1]}")
                print(f"✓ Close: ₹{latest['Close']:.2f}")
                print(f"✓ Volume: {latest['Volume']:,.0f}")
                print(f"\n✅ SUCCESS: Yahoo Finance .history(period='{period}') is working!")
                break
            else:
                print(f"❌ Empty data for period={period}")
        except Exception as e:
            print(f"❌ FAILED with period={period}: {e}")

    print("\n" + "=" * 60)
    print("Method 3: Using yf.download()")
    print("-" * 60)

    try:
        print(f"Downloading {symbol}...")
        data = yf.download(symbol, period="1d", progress=False)

        if not data.empty:
            latest_price = data['Close'].iloc[-1]
            print(f"✓ Latest Close Price: ₹{latest_price:.2f}")
            print(f"✓ Data points: {len(data)}")
            print(f"\n✅ SUCCESS: Yahoo Finance yf.download() is working!")
        else:
            print("❌ No data returned from download")
    except Exception as e:
        print(f"❌ FAILED with download: {e}")

except Exception as e:
    print(f"\n❌ FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Test Complete")
print("=" * 60)
