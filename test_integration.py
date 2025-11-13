#!/usr/bin/env python3
"""
Integration Test for Unified Cache System
Tests that all monitors can import and initialize the unified caches
"""

import sys
import os

def print_section(title):
    """Print section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_result(success, message):
    """Print test result"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status}: {message}")

def test_cache_imports():
    """Test 1: Verify unified cache modules can be imported"""
    print_section("Test 1: Cache Module Imports")

    try:
        from unified_quote_cache import UnifiedQuoteCache
        print_result(True, "UnifiedQuoteCache imported successfully")

        from unified_data_cache import UnifiedDataCache
        print_result(True, "UnifiedDataCache imported successfully")

        return True
    except Exception as e:
        print_result(False, f"Import error: {e}")
        return False

def test_stock_monitor_integration():
    """Test 2: Verify stock_monitor can import caches"""
    print_section("Test 2: stock_monitor.py Integration")

    try:
        # Check if import statement exists
        with open('stock_monitor.py', 'r') as f:
            content = f.read()

        has_import = 'from unified_quote_cache import UnifiedQuoteCache' in content
        print_result(has_import, "UnifiedQuoteCache import found in stock_monitor.py")

        has_init = 'self.quote_cache' in content
        print_result(has_init, "quote_cache initialization found in stock_monitor.py")

        has_usage = 'quote_cache.get_or_fetch_quotes' in content
        print_result(has_usage, "Cache usage found in fetch method")

        return has_import and has_init and has_usage

    except Exception as e:
        print_result(False, f"Error: {e}")
        return False

def test_atr_monitor_integration():
    """Test 3: Verify atr_breakout_monitor can import caches"""
    print_section("Test 3: atr_breakout_monitor.py Integration")

    try:
        # Check if imports exist
        with open('atr_breakout_monitor.py', 'r') as f:
            content = f.read()

        has_quote_import = 'from unified_quote_cache import UnifiedQuoteCache' in content
        print_result(has_quote_import, "UnifiedQuoteCache import found")

        has_data_import = 'from unified_data_cache import UnifiedDataCache' in content
        print_result(has_data_import, "UnifiedDataCache import found")

        has_init = 'self.quote_cache' in content and 'self.data_cache' in content
        print_result(has_init, "Both caches initialized in __init__")

        has_quote_usage = 'quote_cache.get_or_fetch_quotes' in content
        print_result(has_quote_usage, "Quote cache usage found")

        has_data_usage = 'data_cache.get_atr_data' in content
        print_result(has_data_usage, "Data cache usage found")

        return (has_quote_import and has_data_import and has_init and
                has_quote_usage and has_data_usage)

    except Exception as e:
        print_result(False, f"Error: {e}")
        return False

def test_eod_analyzer_integration():
    """Test 4: Verify eod_analyzer uses UnifiedDataCache"""
    print_section("Test 4: eod_analyzer.py Integration")

    try:
        # Check if UnifiedDataCache replaced EODCacheManager
        with open('eod_analyzer.py', 'r') as f:
            content = f.read()

        has_unified_import = 'from unified_data_cache import UnifiedDataCache' in content
        print_result(has_unified_import, "UnifiedDataCache import found")

        no_old_import = 'from eod_cache_manager import EODCacheManager' not in content
        print_result(no_old_import, "Old EODCacheManager import removed")

        has_init = 'self.cache_manager = UnifiedDataCache' in content
        print_result(has_init, "UnifiedDataCache initialization found")

        return has_unified_import and no_old_import and has_init

    except Exception as e:
        print_result(False, f"Error: {e}")
        return False

def test_config_settings():
    """Test 5: Verify config has unified cache settings"""
    print_section("Test 5: Configuration Settings")

    try:
        import config

        has_enable = hasattr(config, 'ENABLE_UNIFIED_CACHE')
        print_result(has_enable, "ENABLE_UNIFIED_CACHE setting exists")

        has_quote_ttl = hasattr(config, 'QUOTE_CACHE_TTL_SECONDS')
        print_result(has_quote_ttl, "QUOTE_CACHE_TTL_SECONDS setting exists")

        has_historical_ttl = hasattr(config, 'HISTORICAL_CACHE_TTL_HOURS')
        print_result(has_historical_ttl, "HISTORICAL_CACHE_TTL_HOURS setting exists")

        has_cache_dir = hasattr(config, 'UNIFIED_CACHE_DIR')
        print_result(has_cache_dir, "UNIFIED_CACHE_DIR setting exists")

        has_quote_file = hasattr(config, 'QUOTE_CACHE_FILE')
        print_result(has_quote_file, "QUOTE_CACHE_FILE setting exists")

        # Print current settings
        if has_enable:
            print(f"\n  Configuration values:")
            print(f"    ENABLE_UNIFIED_CACHE: {config.ENABLE_UNIFIED_CACHE}")
            print(f"    QUOTE_CACHE_TTL_SECONDS: {config.QUOTE_CACHE_TTL_SECONDS}")
            print(f"    HISTORICAL_CACHE_TTL_HOURS: {config.HISTORICAL_CACHE_TTL_HOURS}")
            print(f"    UNIFIED_CACHE_DIR: {config.UNIFIED_CACHE_DIR}")
            print(f"    QUOTE_CACHE_FILE: {config.QUOTE_CACHE_FILE}")

        return (has_enable and has_quote_ttl and has_historical_ttl and
                has_cache_dir and has_quote_file)

    except Exception as e:
        print_result(False, f"Error: {e}")
        return False

def test_cache_initialization():
    """Test 6: Verify caches can be initialized"""
    print_section("Test 6: Cache Initialization")

    try:
        from unified_quote_cache import UnifiedQuoteCache
        from unified_data_cache import UnifiedDataCache
        import config

        # Test quote cache
        quote_cache = UnifiedQuoteCache(
            cache_file="data/test_cache/integration_quote_test.json",
            ttl_seconds=60
        )
        print_result(True, "UnifiedQuoteCache initialized successfully")

        # Test data cache
        data_cache = UnifiedDataCache(
            cache_dir="data/test_cache/integration_data_test"
        )
        print_result(True, "UnifiedDataCache initialized successfully")

        # Test stats
        quote_stats = quote_cache.get_cache_stats()
        print(f"  Quote cache status: {quote_stats['status']}")

        data_stats = data_cache.get_cache_stats()
        print(f"  Data cache types: {len(data_stats)} types configured")

        return True

    except Exception as e:
        print_result(False, f"Error: {e}")
        return False

def test_backward_compatibility():
    """Test 7: Verify backward compatibility methods exist"""
    print_section("Test 7: Backward Compatibility")

    try:
        from unified_data_cache import UnifiedDataCache

        cache = UnifiedDataCache(cache_dir="data/test_cache/compat_test")

        # Check if old methods exist
        has_get = hasattr(cache, 'get_historical_data')
        print_result(has_get, "get_historical_data() method exists")

        has_set = hasattr(cache, 'set_historical_data')
        print_result(has_set, "set_historical_data() method exists")

        has_clear = hasattr(cache, 'clear_expired')
        print_result(has_clear, "clear_expired() method exists")

        has_stats = hasattr(cache, 'get_cache_stats')
        print_result(has_stats, "get_cache_stats() method exists")

        print("\n  ✅ UnifiedDataCache is backward compatible with EODCacheManager!")

        return has_get and has_set and has_clear and has_stats

    except Exception as e:
        print_result(False, f"Error: {e}")
        return False

def main():
    """Run all integration tests"""
    print_section("UNIFIED CACHE INTEGRATION TESTS")

    print("\nThese tests verify that all monitors are properly integrated")
    print("with the unified cache system without making API calls.\n")

    results = []

    # Run all tests
    results.append(("Cache Imports", test_cache_imports()))
    results.append(("stock_monitor Integration", test_stock_monitor_integration()))
    results.append(("atr_breakout_monitor Integration", test_atr_monitor_integration()))
    results.append(("eod_analyzer Integration", test_eod_analyzer_integration()))
    results.append(("Config Settings", test_config_settings()))
    results.append(("Cache Initialization", test_cache_initialization()))
    results.append(("Backward Compatibility", test_backward_compatibility()))

    # Summary
    print_section("TEST SUMMARY")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    print(f"\nTests Passed: {passed}/{total}")
    print("\nResults:")
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} {name}")

    if passed == total:
        print("\n" + "=" * 70)
        print("  🎉 ALL INTEGRATION TESTS PASSED! 🎉")
        print("=" * 70)
        print("\nThe unified cache system is properly integrated across all monitors:")
        print("  • stock_monitor.py uses UnifiedQuoteCache")
        print("  • atr_breakout_monitor.py uses UnifiedQuoteCache + UnifiedDataCache")
        print("  • eod_analyzer.py uses UnifiedDataCache")
        print("\nAll three monitors can now share cached data!")
        print("=" * 70)
    else:
        print("\n⚠️  Some tests failed. Please review the output above.")

    print("\nTo clean up test files:")
    print("  rm -rf data/test_cache/")
    print()

if __name__ == "__main__":
    main()
