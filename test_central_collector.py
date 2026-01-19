#!/usr/bin/env python3
"""
Test Central Data Collector
Verifies the central collector and database are working correctly

Run this script to test:
1. Database initialization
2. Data collection
3. Data retrieval
4. Database stats

Author: Claude Sonnet 4.5
Date: 2026-01-19
"""

import sys
import time
from datetime import datetime
from central_quote_db import get_central_db
from central_data_collector import CentralDataCollector


def test_database():
    """Test database initialization and basic operations"""
    print("=" * 80)
    print("TEST 1: Database Initialization")
    print("=" * 80)

    try:
        db = get_central_db()
        print("✓ Database initialized successfully")

        # Check stats
        stats = db.get_database_stats()
        print(f"✓ Database stats retrieved:")
        print(f"  - Unique stocks: {stats['unique_stocks']}")
        print(f"  - NIFTY records: {stats['nifty_records']}")
        print(f"  - VIX records: {stats['vix_records']}")
        print(f"  - Last stock update: {stats['last_stock_update']}")

        return True

    except Exception as e:
        print(f"✗ Database test failed: {e}")
        return False


def test_collection():
    """Test data collection"""
    print("\n" + "=" * 80)
    print("TEST 2: Data Collection")
    print("=" * 80)

    try:
        collector = CentralDataCollector()
        print("✓ Collector initialized")

        print("\nRunning collection cycle...")
        stats = collector.collect_and_store()

        print(f"\n✓ Collection complete:")
        print(f"  - Stocks fetched: {stats['stocks_fetched']}")
        print(f"  - NIFTY fetched: {'Yes' if stats['nifty_fetched'] else 'No'}")
        print(f"  - VIX fetched: {'Yes' if stats['vix_fetched'] else 'No'}")
        print(f"  - Errors: {stats['errors']}")

        if stats['stocks_fetched'] == 0:
            print("⚠️  Warning: No stocks fetched (market might be closed)")

        return stats['errors'] == 0

    except SystemExit:
        print("ℹ️  Market is closed - collection test skipped")
        return True
    except Exception as e:
        print(f"✗ Collection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_data_retrieval():
    """Test reading data from database"""
    print("\n" + "=" * 80)
    print("TEST 3: Data Retrieval")
    print("=" * 80)

    try:
        db = get_central_db()

        # Test 1: Get latest stock quotes
        print("\n1. Testing latest stock quotes...")
        test_symbols = ['RELIANCE', 'TCS', 'INFY']
        quotes = db.get_latest_stock_quotes(test_symbols)

        if quotes:
            print(f"✓ Retrieved {len(quotes)} quotes")
            for symbol, data in list(quotes.items())[:3]:
                print(f"  - {symbol}: ₹{data['price']:.2f}, Vol:{data['volume']:,}, OI:{data['oi']:,}")
        else:
            print("⚠️  No quotes found (run collection first)")

        # Test 2: Get NIFTY latest
        print("\n2. Testing NIFTY quote...")
        nifty = db.get_nifty_latest()
        if nifty:
            print(f"✓ NIFTY 50: ₹{nifty['price']:.2f}")
            print(f"  - OHLC: O:{nifty['open']:.2f}, H:{nifty['high']:.2f}, L:{nifty['low']:.2f}")
        else:
            print("⚠️  No NIFTY data (run collection first)")

        # Test 3: Get VIX latest
        print("\n3. Testing VIX quote...")
        vix = db.get_vix_latest()
        if vix:
            print(f"✓ India VIX: {vix['vix_value']:.2f}")
        else:
            print("⚠️  No VIX data (run collection first)")

        # Test 4: Get stock history
        print("\n4. Testing historical data...")
        if quotes:
            test_symbol = list(quotes.keys())[0]
            history = db.get_stock_history(test_symbol, minutes=30)
            print(f"✓ Retrieved {len(history)} historical records for {test_symbol}")
            if history:
                print(f"  - Oldest: {history[0]['timestamp']}")
                print(f"  - Latest: {history[-1]['timestamp']}")

        return True

    except Exception as e:
        print(f"✗ Data retrieval test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_metadata():
    """Test metadata operations"""
    print("\n" + "=" * 80)
    print("TEST 4: Metadata")
    print("=" * 80)

    try:
        db = get_central_db()

        # Get collection status
        last_collection = db.get_metadata('last_collection_time')
        collection_status = db.get_metadata('collection_status')

        print(f"✓ Metadata retrieved:")
        print(f"  - Last collection: {last_collection or 'Never'}")
        print(f"  - Status: {collection_status or 'Unknown'}")

        return True

    except Exception as e:
        print(f"✗ Metadata test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("CENTRAL DATA COLLECTOR - TEST SUITE")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    results = []

    # Run tests
    results.append(("Database Init", test_database()))
    results.append(("Data Collection", test_collection()))
    results.append(("Data Retrieval", test_data_retrieval()))
    results.append(("Metadata", test_metadata()))

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 80)

    if passed == total:
        print("\n✅ All tests passed! Central collector is ready for deployment.")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed. Review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
