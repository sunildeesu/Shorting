#!/usr/bin/env python3
"""
Script to update F&O stocks list from Kite Connect API
Fetches current F&O eligible stocks and updates fo_stocks.json
"""

import json
from kiteconnect import KiteConnect
import config

def fetch_fo_stocks():
    """Fetch current F&O stock list from Kite Connect"""
    print("Connecting to Kite Connect API...")
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    print("Fetching NFO instruments...")
    # Get all NFO (F&O) instruments
    instruments = kite.instruments("NFO")

    # Extract unique stock symbols (tradingsymbols without expiry dates)
    fo_stocks = set()

    for instrument in instruments:
        # Only process equity futures/options (exclude indices like NIFTY, BANKNIFTY)
        if instrument['instrument_type'] in ['FUT', 'CE', 'PE']:
            # The 'tradingsymbol' contains the stock symbol
            # Example: "RELIANCE25FEB2900CE" -> we want "RELIANCE"
            # The 'name' field contains the clean stock symbol
            symbol = instrument['name']

            # Skip index instruments
            if symbol not in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']:
                fo_stocks.add(symbol)

    # Convert to sorted list
    fo_stocks_list = sorted(list(fo_stocks))

    print(f"\nFound {len(fo_stocks_list)} F&O eligible stocks")

    return fo_stocks_list

def compare_lists(old_list, new_list):
    """Compare old and new lists to find additions and removals"""
    old_set = set(old_list)
    new_set = set(new_list)

    added = new_set - old_set
    removed = old_set - new_set
    unchanged = old_set & new_set

    return {
        'added': sorted(list(added)),
        'removed': sorted(list(removed)),
        'unchanged': sorted(list(unchanged)),
        'total_new': len(new_list),
        'total_old': len(old_list)
    }

def update_fo_stocks_file(stocks_list):
    """Update fo_stocks.json with new list"""
    data = {"stocks": stocks_list}

    with open(config.STOCK_LIST_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\n✅ Updated {config.STOCK_LIST_FILE}")

def main():
    # Read current list
    print("Reading current F&O stock list...")
    with open(config.STOCK_LIST_FILE, 'r') as f:
        current_data = json.load(f)
        current_stocks = current_data['stocks']

    print(f"Current list has {len(current_stocks)} stocks\n")

    # Fetch new list from Kite
    new_stocks = fetch_fo_stocks()

    # Compare lists
    print("\n" + "="*60)
    print("COMPARING LISTS")
    print("="*60)

    comparison = compare_lists(current_stocks, new_stocks)

    print(f"\nTotal stocks in current list: {comparison['total_old']}")
    print(f"Total stocks in new list: {comparison['total_new']}")
    print(f"Unchanged: {len(comparison['unchanged'])}")

    if comparison['added']:
        print(f"\n✅ ADDED ({len(comparison['added'])} stocks):")
        for stock in comparison['added']:
            print(f"  + {stock}")
    else:
        print("\n✅ No new stocks added")

    if comparison['removed']:
        print(f"\n❌ REMOVED ({len(comparison['removed'])} stocks):")
        for stock in comparison['removed']:
            print(f"  - {stock}")
    else:
        print("\n✅ No stocks removed")

    # Ask for confirmation (or auto-update if --auto flag)
    print("\n" + "="*60)

    import sys
    auto_update = '--auto' in sys.argv or '-y' in sys.argv

    if auto_update:
        print("\nAuto-update mode: Updating fo_stocks.json...")
        update_fo_stocks_file(new_stocks)
        print("\n✅ F&O stock list updated successfully!")
        print(f"Now monitoring {len(new_stocks)} stocks")
    else:
        try:
            response = input("\nUpdate fo_stocks.json with the new list? (yes/no): ").strip().lower()
            if response in ['yes', 'y']:
                update_fo_stocks_file(new_stocks)
                print("\n✅ F&O stock list updated successfully!")
                print(f"Now monitoring {len(new_stocks)} stocks")
            else:
                print("\n❌ Update cancelled")
        except EOFError:
            print("\n⚠️  Non-interactive mode detected. Use --auto flag to update automatically.")
            print("Example: ./update_fo_stocks.py --auto")

if __name__ == "__main__":
    main()
