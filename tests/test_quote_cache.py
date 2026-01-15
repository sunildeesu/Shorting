#!/usr/bin/env python3
"""
Test Script for UnifiedQuoteCache

Tests all functionality of the unified quote cache system without requiring Kite API.
Uses mock data for testing.
"""

import os
import sys
import time
import json
from datetime import datetime
from typing import Dict

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from unified_quote_cache import UnifiedQuoteCache


class MockKiteClient:
    """Mock Kite client for testing without API"""

    def __init__(self):
        self.call_count = 0

    def quote(self, *instruments):
        """Mock quote API call"""
        self.call_count += 1
        print(f"  [MOCK API] Called quote() with {len(instruments)} instruments (call #{self.call_count})")

        # Generate mock quote data
        quotes = {}
        for instrument in instruments:
            symbol = instrument.replace("NSE:", "")
            quotes[instrument] = {
                'last_price': 2000 + (hash(symbol) % 500),
                'volume': 1000000 + (hash(symbol) % 5000000),
                'ohlc': {
                    'open': 1990 + (hash(symbol) % 500),
                    'high': 2010 + (hash(symbol) % 500),
                    'low': 1980 + (hash(symbol) % 500),
                    'close': 2000 + (hash(symbol) % 500)
                },
                'average_price': 2000 + (hash(symbol) % 500)
            }

        return quotes


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


def test_cache_creation():
    """Test 1: Cache creation and initialization"""
    print_test("Cache Creation and Initialization")

    try:
        # Create cache with custom TTL
        cache = UnifiedQuoteCache(
            cache_file="data/test_cache/quote_cache_test.json",
            ttl_seconds=5
        )

        print_result(True, "Cache created successfully")

        # Check initial state
        stats = cache.get_cache_stats()
        print(f"  Initial status: {stats['status']}")
        print(f"  Stocks cached: {stats['stocks_cached']}")
        print(f"  TTL: {stats['ttl_seconds']}s")

        print_result(stats['status'] == 'empty', "Initial cache is empty")
        print_result(stats['stocks_cached'] == 0, "No stocks cached initially")

        return cache

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return None


def test_first_fetch(cache, mock_kite):
    """Test 2: First fetch (cache miss)"""
    print_test("First Fetch (Cache Miss)")

    try:
        test_stocks = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']

        print(f"  Fetching quotes for {len(test_stocks)} stocks...")
        mock_kite.call_count = 0  # Reset counter

        quotes = cache.get_or_fetch_quotes(test_stocks, mock_kite, batch_size=3)

        print_result(len(quotes) == len(test_stocks),
                    f"Got {len(quotes)} quotes (expected {len(test_stocks)})")

        print_result(mock_kite.call_count > 0,
                    f"API was called {mock_kite.call_count} time(s) (cache miss)")

        # Check cache stats
        stats = cache.get_cache_stats()
        print(f"\n  Cache stats after fetch:")
        print(f"    Status: {stats['status']}")
        print(f"    Stocks cached: {stats['stocks_cached']}")
        print(f"    Age: {stats['age_seconds']:.1f}s")
        print(f"    Valid: {stats['is_valid']}")

        print_result(stats['is_valid'], "Cache is valid after fetch")

        return quotes

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return None


def test_cache_hit(cache, mock_kite, test_stocks):
    """Test 3: Second fetch (cache hit)"""
    print_test("Second Fetch (Cache Hit)")

    try:
        print(f"  Fetching same quotes again (should use cache)...")
        previous_call_count = mock_kite.call_count

        quotes2 = cache.get_or_fetch_quotes(test_stocks, mock_kite, batch_size=3)

        print_result(mock_kite.call_count == previous_call_count,
                    f"API was NOT called (count still {mock_kite.call_count})")

        print_result(len(quotes2) == len(test_stocks),
                    f"Got {len(quotes2)} quotes from cache")

        # Check cache age
        stats = cache.get_cache_stats()
        print(f"\n  Cache age: {stats['age_seconds']:.2f}s")
        print_result(stats['is_valid'], "Cache still valid")

        return quotes2

    except Exception as e:
        print_result(False, f"Exception: {e}")
        return None


def test_cache_expiry(cache, mock_kite, test_stocks):
    """Test 4: Cache expiry"""
    print_test("Cache Expiry")

    try:
        ttl = cache.ttl_seconds
        print(f"  Cache TTL: {ttl}s")
        print(f"  Waiting {ttl + 1} seconds for cache to expire...")

        time.sleep(ttl + 1)

        # Check if expired
        stats = cache.get_cache_stats()
        print(f"  Cache age after wait: {stats['age_seconds']:.1f}s")
        print_result(not stats['is_valid'], f"Cache expired (age {stats['age_seconds']:.1f}s > TTL {ttl}s)")

        # Fetch again (should hit API)
        print(f"\n  Fetching after expiry (should hit API)...")
        previous_call_count = mock_kite.call_count

        quotes3 = cache.get_or_fetch_quotes(test_stocks, mock_kite, batch_size=3)

        print_result(mock_kite.call_count > previous_call_count,
                    f"API was called again (count: {previous_call_count} → {mock_kite.call_count})")

        print_result(len(quotes3) == len(test_stocks),
                    f"Got {len(quotes3)} fresh quotes")

    except Exception as e:
        print_result(False, f"Exception: {e}")


def test_manual_operations(cache):
    """Test 5: Manual cache operations"""
    print_test("Manual Cache Operations")

    try:
        # Test manual get
        print("  Testing get_cached_quotes()...")
        cached_quotes = cache.get_cached_quotes()
        print_result(cached_quotes is not None, "Retrieved cached quotes manually")

        # Test manual set
        print("\n  Testing set_cached_quotes()...")
        test_data = {
            "NSE:TEST1": {"last_price": 100},
            "NSE:TEST2": {"last_price": 200}
        }
        cache.set_cached_quotes(test_data)

        retrieved = cache.get_cached_quotes()
        print_result(len(retrieved) == 2, f"Manually set {len(test_data)} quotes")
        print_result("NSE:TEST1" in retrieved, "TEST1 found in cache")

        # Test invalidation
        print("\n  Testing invalidate()...")
        cache.invalidate()

        stats = cache.get_cache_stats()
        print_result(stats['status'] == 'empty', "Cache invalidated successfully")

    except Exception as e:
        print_result(False, f"Exception: {e}")


def test_file_persistence(cache, test_stocks, mock_kite):
    """Test 6: File persistence across instances"""
    print_test("File Persistence")

    try:
        # Fetch and cache some data
        print("  Caching data in first instance...")
        cache1 = cache
        quotes1 = cache1.get_or_fetch_quotes(test_stocks, mock_kite, batch_size=3)

        cache_file = cache1.cache_file
        print(f"  Cache file: {cache_file}")
        print_result(os.path.exists(cache_file), "Cache file exists on disk")

        # Create new cache instance (simulating restart)
        print("\n  Creating new cache instance (simulating restart)...")
        cache2 = UnifiedQuoteCache(cache_file=cache_file, ttl_seconds=60)

        # Should load from file
        stats = cache2.get_cache_stats()
        print(f"  Loaded cache status: {stats['status']}")
        print(f"  Stocks in cache: {stats['stocks_cached']}")

        print_result(stats['stocks_cached'] > 0,
                    f"Loaded {stats['stocks_cached']} stocks from file")

        # Verify data matches
        quotes2 = cache2.get_cached_quotes()
        print_result(quotes2 is not None and len(quotes2) == len(quotes1),
                    "Data matches original cache")

    except Exception as e:
        print_result(False, f"Exception: {e}")


def test_batch_fetching(cache, mock_kite):
    """Test 7: Batch fetching logic"""
    print_test("Batch Fetching Logic")

    try:
        # Test with many stocks requiring multiple batches
        many_stocks = [f"STOCK{i}" for i in range(125)]  # 125 stocks
        batch_size = 50

        print(f"  Fetching {len(many_stocks)} stocks with batch_size={batch_size}...")
        print(f"  Expected batches: {(len(many_stocks) + batch_size - 1) // batch_size}")

        cache.invalidate()  # Clear cache first
        mock_kite.call_count = 0

        quotes = cache.get_or_fetch_quotes(many_stocks, mock_kite, batch_size=batch_size)

        expected_batches = 3  # 125 / 50 = 3 batches
        print_result(mock_kite.call_count == expected_batches,
                    f"Made {mock_kite.call_count} API calls (expected {expected_batches})")

        print_result(len(quotes) == len(many_stocks),
                    f"Got all {len(quotes)} quotes")

    except Exception as e:
        print_result(False, f"Exception: {e}")


def test_concurrent_safety():
    """Test 8: File locking (concurrent access simulation)"""
    print_test("File Locking (Concurrent Safety)")

    try:
        import threading

        cache_file = "data/test_cache/concurrent_test.json"
        cache = UnifiedQuoteCache(cache_file=cache_file, ttl_seconds=60)
        mock_kite = MockKiteClient()

        test_stocks = ['STOCK1', 'STOCK2', 'STOCK3']
        errors = []

        def reader():
            try:
                for _ in range(5):
                    quotes = cache.get_cached_quotes()
                    time.sleep(0.01)
            except Exception as e:
                errors.append(f"Reader error: {e}")

        def writer():
            try:
                for i in range(3):
                    quotes = cache.get_or_fetch_quotes(test_stocks, mock_kite)
                    time.sleep(0.02)
            except Exception as e:
                errors.append(f"Writer error: {e}")

        print("  Simulating concurrent reads/writes...")
        threads = []

        # Create threads
        for _ in range(3):
            threads.append(threading.Thread(target=reader))
        for _ in range(2):
            threads.append(threading.Thread(target=writer))

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        print_result(len(errors) == 0,
                    f"No errors in concurrent access ({len(threads)} threads)")

        if errors:
            for error in errors:
                print(f"  Error: {error}")

        # Verify cache is still valid
        stats = cache.get_cache_stats()
        print_result(stats['stocks_cached'] > 0, "Cache intact after concurrent access")

    except Exception as e:
        print_result(False, f"Exception: {e}")


def main():
    """Run all tests"""
    print_section("UNIFIED QUOTE CACHE - COMPREHENSIVE TESTING")

    print("\nTest Environment:")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Working Directory: {os.getcwd()}")

    # Initialize
    mock_kite = MockKiteClient()
    test_stocks = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']

    # Run tests
    cache = test_cache_creation()
    if cache:
        quotes1 = test_first_fetch(cache, mock_kite)
        if quotes1:
            quotes2 = test_cache_hit(cache, mock_kite, test_stocks)
            test_cache_expiry(cache, mock_kite, test_stocks)
            test_manual_operations(cache)
            test_file_persistence(cache, test_stocks, mock_kite)
            test_batch_fetching(cache, mock_kite)
            test_concurrent_safety()

    # Summary
    print_section("TEST SUMMARY")
    print("\nAll tests completed!")
    print("\nTest Files Created:")
    print(f"  - data/test_cache/quote_cache_test.json")
    print(f"  - data/test_cache/concurrent_test.json")
    print("\nTo clean up test files:")
    print("  rm -rf data/test_cache/")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
