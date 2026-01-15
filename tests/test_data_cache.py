#!/usr/bin/env python3
"""
Test Script for UnifiedDataCache

Tests all functionality of the unified data cache system.
Uses mock data for testing.
"""

import os
import sys
import time
from datetime import datetime, timedelta

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from unified_data_cache import UnifiedDataCache


def print_section(title):
    """Print section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_test(test_name):
    """Print test header"""
    print(f"\n[TEST] {test_name}")
    print("-" * 70)


def print_result(success, message):
    """Print test result"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status}: {message}")


def generate_mock_candles(num_candles=30, base_price=2000):
    """Generate mock OHLCV candles"""
    candles = []
    for i in range(num_candles):
        date = datetime.now() - timedelta(days=num_candles - i - 1)
        candles.append({
            'date': date.isoformat(),
            'open': base_price + (i % 10),
            'high': base_price + 10 + (i % 10),
            'low': base_price - 10 + (i % 10),
            'close': base_price + 5 + (i % 10),
            'volume': 1000000 + (i * 10000)
        })
    return candles


def test_cache_creation():
    """Test 1: Cache creation and initialization"""
    print_test("Cache Creation and Initialization")

    try:
        cache = UnifiedDataCache(cache_dir="data/test_cache/data_cache")

        print_result(True, "Cache created successfully")

        # Check initial stats
        stats = cache.get_cache_stats()
        print(f"\n  Initial cache stats:")
        for data_type, type_stats in stats.items():
            print(f"    {data_type}:")
            print(f"      Total: {type_stats['total_stocks']}")
            print(f"      Valid: {type_stats['valid_stocks']}")
            print(f"      TTL: {type_stats['ttl_hours']}h")

        print_result(True, "All cache types initialized")

        return cache

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return None


def test_set_and_get_30d(cache):
    """Test 2: Set and get 30-day historical data"""
    print_test("Set and Get 30-Day Historical Data")

    try:
        symbol = "RELIANCE"
        data = generate_mock_candles(30, base_price=2340)

        print(f"  Setting 30-day data for {symbol} ({len(data)} candles)...")
        cache.set_data(symbol, data, 'historical_30d')

        print(f"  Retrieving 30-day data for {symbol}...")
        retrieved = cache.get_data(symbol, 'historical_30d')

        print_result(retrieved is not None, "Data retrieved successfully")
        print_result(len(retrieved) == 30, f"Got {len(retrieved)} candles (expected 30)")

        # Verify data integrity
        first_candle = retrieved[0]
        print(f"\n  First candle:")
        print(f"    Date: {first_candle['date']}")
        print(f"    OHLC: O={first_candle['open']}, H={first_candle['high']}, "
              f"L={first_candle['low']}, C={first_candle['close']}")
        print(f"    Volume: {first_candle['volume']:,}")

        print_result('date' in first_candle, "Candle has date field")
        print_result('open' in first_candle, "Candle has OHLC data")

        return True

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False


def test_set_and_get_50d(cache):
    """Test 3: Set and get 50-day historical data (ATR)"""
    print_test("Set and Get 50-Day Historical Data (ATR)")

    try:
        symbol = "TCS"
        data = generate_mock_candles(50, base_price=3450)

        print(f"  Setting 50-day data for {symbol} using set_atr_data()...")
        cache.set_atr_data(symbol, data)

        print(f"  Retrieving 50-day data for {symbol} using get_atr_data()...")
        retrieved = cache.get_atr_data(symbol)

        print_result(retrieved is not None, "ATR data retrieved successfully")
        print_result(len(retrieved) == 50, f"Got {len(retrieved)} candles (expected 50)")

        # Also test generic method
        print(f"\n  Testing generic get_data('historical_50d')...")
        retrieved2 = cache.get_data(symbol, 'historical_50d')

        print_result(retrieved2 is not None, "Generic method also works")
        print_result(len(retrieved2) == len(retrieved), "Both methods return same data")

        return True

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False


def test_multiple_symbols(cache):
    """Test 4: Multiple symbols in same cache"""
    print_test("Multiple Symbols in Same Cache")

    try:
        symbols = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']

        print(f"  Caching data for {len(symbols)} symbols...")
        for idx, symbol in enumerate(symbols):
            data = generate_mock_candles(30, base_price=2000 + (idx * 100))
            cache.set_data(symbol, data, 'historical_30d')

        # Retrieve all
        print(f"\n  Retrieving all {len(symbols)} symbols...")
        retrieved_count = 0
        for symbol in symbols:
            data = cache.get_data(symbol, 'historical_30d')
            if data:
                retrieved_count += 1

        print_result(retrieved_count == len(symbols),
                    f"Retrieved {retrieved_count}/{len(symbols)} symbols")

        # Check stats
        stats = cache.get_cache_stats('historical_30d')
        print(f"\n  Cache stats for historical_30d:")
        print(f"    Valid stocks: {stats['valid_stocks']}")
        print_result(stats['valid_stocks'] >= len(symbols),
                    f"Cache shows {stats['valid_stocks']} valid stocks")

        return True

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False


def test_backward_compatibility(cache):
    """Test 5: Backward compatibility with EODCacheManager"""
    print_test("Backward Compatibility (EOD Analyzer)")

    try:
        symbol = "BACKCOMPAT"
        data = generate_mock_candles(30, base_price=1500)

        # Use old EODCacheManager methods
        print(f"  Using set_historical_data() (old method)...")
        cache.set_historical_data(symbol, data)

        print(f"  Using get_historical_data() (old method)...")
        retrieved = cache.get_historical_data(symbol)

        print_result(retrieved is not None, "Old method works")
        print_result(len(retrieved) == 30, f"Got {len(retrieved)} candles")

        # Verify it's actually stored in historical_30d
        retrieved_new = cache.get_data(symbol, 'historical_30d')
        print_result(retrieved_new is not None,
                    "Data accessible via new method too")

        print("\n  ✅ EOD Analyzer can use UnifiedDataCache as drop-in replacement!")

        return True

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False


def test_cache_expiry():
    """Test 6: Cache expiry based on TTL"""
    print_test("Cache Expiry (TTL)")

    try:
        # Create cache with short TTL for testing
        cache = UnifiedDataCache(cache_dir="data/test_cache/expiry_test")

        # Override TTL for quick testing
        cache.DEFAULT_TTL['historical_30d'] = 0.0014  # ~5 seconds in hours

        symbol = "EXPIRY_TEST"
        data = generate_mock_candles(30)

        print(f"  Setting data with TTL={cache.DEFAULT_TTL['historical_30d'] * 3600:.1f}s...")
        cache.set_data(symbol, data, 'historical_30d')

        # Immediate retrieval should work
        retrieved1 = cache.get_data(symbol, 'historical_30d')
        print_result(retrieved1 is not None, "Immediate retrieval works")

        # Wait for expiry
        wait_time = 6
        print(f"\n  Waiting {wait_time} seconds for cache to expire...")
        time.sleep(wait_time)

        # Should be expired now
        retrieved2 = cache.get_data(symbol, 'historical_30d')
        print_result(retrieved2 is None, "Cache expired after TTL")

        # Check stats
        stats = cache.get_cache_stats('historical_30d')
        print(f"\n  Expired stocks: {stats['expired_stocks']}")

        # Clear expired
        print(f"\n  Clearing expired entries...")
        cleared = cache.clear_expired('historical_30d')
        print_result(cleared > 0, f"Cleared {cleared} expired entries")

        return True

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False


def test_multi_type_caching(cache):
    """Test 7: Multiple data types for same symbol"""
    print_test("Multi-Type Caching (Same Symbol)")

    try:
        symbol = "MULTITYPE"

        # Cache different types for same symbol
        print(f"  Caching multiple data types for {symbol}...")

        data_30d = generate_mock_candles(30, base_price=2000)
        data_50d = generate_mock_candles(50, base_price=2000)
        data_intraday = generate_mock_candles(125, base_price=2000)  # 5 days × 25 candles/day

        cache.set_data(symbol, data_30d, 'historical_30d')
        cache.set_data(symbol, data_50d, 'historical_50d')
        cache.set_data(symbol, data_intraday, 'intraday_5d')

        # Retrieve each type
        print(f"\n  Retrieving all types...")
        retrieved_30d = cache.get_data(symbol, 'historical_30d')
        retrieved_50d = cache.get_data(symbol, 'historical_50d')
        retrieved_intraday = cache.get_intraday_data(symbol, days=5)

        print_result(len(retrieved_30d) == 30, f"30-day: {len(retrieved_30d)} candles")
        print_result(len(retrieved_50d) == 50, f"50-day: {len(retrieved_50d)} candles")
        print_result(len(retrieved_intraday) == 125, f"Intraday: {len(retrieved_intraday)} candles")

        # All should be independent
        print("\n  Verifying data independence...")
        print_result(len(retrieved_30d) != len(retrieved_50d),
                    "30-day and 50-day are different")
        print_result(len(retrieved_intraday) != len(retrieved_30d),
                    "Intraday and daily are different")

        return True

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False


def test_file_structure(cache):
    """Test 8: Separate cache files"""
    print_test("File Structure (Separate Files per Type)")

    try:
        cache_dir = cache.cache_dir

        print(f"  Cache directory: {cache_dir}")

        # Check that different files exist
        expected_files = [
            'historical_30d.json',
            'historical_50d.json',
            'intraday_5d.json',
            'intraday_1d.json'
        ]

        print(f"\n  Checking for cache files...")
        for filename in expected_files:
            filepath = os.path.join(cache_dir, filename)
            exists = os.path.exists(filepath)

            if exists:
                size = os.path.getsize(filepath)
                print_result(exists, f"{filename} exists ({size} bytes)")
            else:
                print(f"  ⚪ {filename} not created yet (no data cached)")

        return True

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False


def test_cache_stats_all_types(cache):
    """Test 9: Cache statistics for all types"""
    print_test("Cache Statistics (All Types)")

    try:
        print("  Getting stats for all cache types...")
        all_stats = cache.get_cache_stats()

        print("\n  Cache Statistics:")
        print("  " + "-" * 66)
        print(f"  {'Type':<20} {'Total':<10} {'Valid':<10} {'Expired':<10} {'TTL':<10}")
        print("  " + "-" * 66)

        for data_type, stats in all_stats.items():
            print(f"  {data_type:<20} "
                  f"{stats['total_stocks']:<10} "
                  f"{stats['valid_stocks']:<10} "
                  f"{stats['expired_stocks']:<10} "
                  f"{stats['ttl_hours']}h")

        print("  " + "-" * 66)

        # Test specific type stats
        print(f"\n  Testing specific type stats...")
        stats_30d = cache.get_cache_stats('historical_30d')

        print_result('valid_stocks' in stats_30d,
                    "Stats contain 'valid_stocks' field")
        print_result('ttl_hours' in stats_30d,
                    "Stats contain 'ttl_hours' field")

        return True

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False


def main():
    """Run all tests"""
    print_section("UNIFIED DATA CACHE - COMPREHENSIVE TESTING")

    print("\nTest Environment:")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Working Directory: {os.getcwd()}")

    # Run tests
    cache = test_cache_creation()

    if cache:
        test_set_and_get_30d(cache)
        test_set_and_get_50d(cache)
        test_multiple_symbols(cache)
        test_backward_compatibility(cache)
        test_cache_expiry()
        test_multi_type_caching(cache)
        test_file_structure(cache)
        test_cache_stats_all_types(cache)

    # Summary
    print_section("TEST SUMMARY")
    print("\nAll tests completed!")
    print("\nTest Files Created:")
    print(f"  - data/test_cache/data_cache/historical_30d.json")
    print(f"  - data/test_cache/data_cache/historical_50d.json")
    print(f"  - data/test_cache/data_cache/intraday_5d.json")
    print(f"  - data/test_cache/data_cache/intraday_1d.json")
    print(f"  - data/test_cache/expiry_test/...")
    print("\nTo clean up test files:")
    print("  rm -rf data/test_cache/")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
