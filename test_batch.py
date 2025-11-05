#!/usr/bin/env python3
"""Test batch downloading with yfinance"""

import yfinance as yf
from datetime import datetime

symbols = ["RELIANCE.NS", "TCS.NS", "INFY.NS"]

print("=" * 60)
print("Testing Yahoo Finance batch download")
print(f"Current time: {datetime.now()}")
print("=" * 60)

print(f"\nDownloading {len(symbols)} stocks...")
print(f"Symbols: {symbols}")

# Try with different periods and intervals
for period, interval in [("1d", "1m"), ("1d", "5m"), ("5d", "1d")]:
    print(f"\n--- Testing period={period}, interval={interval} ---")
    try:
        data = yf.download(
            tickers=symbols,
            period=period,
            interval=interval,
            group_by='ticker',
            progress=False,
            threads=True
        )

        print(f"Data shape: {data.shape}")
        print(f"Data empty: {data.empty}")
        print(f"Columns: {data.columns if not data.empty else 'N/A'}")

        if not data.empty:
            print("\nLast few rows:")
            print(data.tail())

            # Try to extract price for first symbol
            symbol = symbols[0]
            if len(symbols) == 1:
                if 'Close' in data.columns:
                    price = data['Close'].iloc[-1]
                    print(f"\n{symbol} latest close: ₹{price:.2f}")
            else:
                if hasattr(data.columns, 'levels') and symbol in data.columns.levels[0]:
                    stock_data = data[symbol]
                    if 'Close' in stock_data.columns:
                        price = stock_data['Close'].iloc[-1]
                        print(f"\n{symbol} latest close: ₹{price:.2f}")

    except Exception as e:
        print(f"ERROR: {e}")
