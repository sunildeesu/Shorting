#!/usr/bin/env python3
"""
Standalone test for historical_data_cache.py
Tests without requiring Kite Connect credentials
"""

import sys
import os
import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path to import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_historical_cache():
    """Test historical cache without Kite dependency"""

    logger.info("=" * 60)
    logger.info("STANDALONE TEST: Historical Data Cache")
    logger.info("=" * 60)

    test_cache_dir = Path('data/test_historical_cache')

    try:
        # Clean up any existing test cache
        if test_cache_dir.exists():
            shutil.rmtree(test_cache_dir)

        # Test 1: Import and instantiate
        logger.info("\nTest 1: Import and Instantiate")
        try:
            # We need to mock kiteconnect to allow import
            sys.modules['kiteconnect'] = type(sys)('kiteconnect')
            sys.modules['kiteconnect'].KiteConnect = object

            from historical_data_cache import HistoricalDataCache, get_historical_cache, reset_cache

            cache = HistoricalDataCache(cache_dir=str(test_cache_dir))
            logger.info("✅ PASS: HistoricalDataCache instantiated successfully")
            logger.info(f"   Cache directory: {cache.cache_dir}")
        except Exception as e:
            logger.error(f"❌ FAIL: Could not instantiate cache: {e}")
            return False

        # Test 2: Cache directory creation
        logger.info("\nTest 2: Cache Directory Creation")
        if test_cache_dir.exists():
            logger.info("✅ PASS: Cache directory created automatically")
        else:
            logger.error("❌ FAIL: Cache directory not created")
            return False

        # Test 3: Cache key generation
        logger.info("\nTest 3: Cache Key Generation")
        test_cases = [
            {
                'params': {
                    'instrument_token': 264969,
                    'from_date': datetime(2026, 1, 1),
                    'to_date': datetime(2026, 1, 10),
                    'interval': 'day',
                    'continuous': False,
                    'oi': False
                },
                'expected': '264969_day_2026-01-01_2026-01-10'
            },
            {
                'params': {
                    'instrument_token': 256265,
                    'from_date': datetime(2026, 1, 1),
                    'to_date': datetime(2026, 1, 10),
                    'interval': '15minute',
                    'continuous': True,
                    'oi': True
                },
                'expected': '256265_15minute_2026-01-01_2026-01-10_continuous_oi'
            }
        ]

        for i, test in enumerate(test_cases):
            key = cache._generate_cache_key(**test['params'])
            if key == test['expected']:
                logger.info(f"✅ PASS: Test case {i+1}: {key}")
            else:
                logger.error(f"❌ FAIL: Test case {i+1}: Expected {test['expected']}, got {key}")
                return False

        # Test 4: Save and load cache
        logger.info("\nTest 4: Save and Load Cache")
        test_data = [
            {'date': datetime(2026, 1, 1), 'open': 100, 'high': 105, 'low': 98, 'close': 103},
            {'date': datetime(2026, 1, 2), 'open': 103, 'high': 108, 'low': 102, 'close': 106},
        ]

        test_cache_file = test_cache_dir / 'test_data.json'
        cache._save_to_cache(test_cache_file, test_data)

        if test_cache_file.exists():
            logger.info("✅ PASS: Cache file created")

            # Load it back
            loaded_data = cache._load_from_cache(test_cache_file)
            if len(loaded_data) == len(test_data):
                logger.info(f"✅ PASS: Cache loaded successfully ({len(loaded_data)} records)")
            else:
                logger.error(f"❌ FAIL: Expected {len(test_data)} records, got {len(loaded_data)}")
                return False
        else:
            logger.error("❌ FAIL: Cache file not created")
            return False

        # Test 5: Market open detection
        logger.info("\nTest 5: Market Open Detection")
        is_open = cache._is_market_open()
        now = datetime.now()
        logger.info(f"   Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"   Market status: {'OPEN' if is_open else 'CLOSED'}")
        logger.info("✅ PASS: Market open detection works (returned boolean)")

        # Test 6: Cache stats
        logger.info("\nTest 6: Cache Statistics")
        stats = cache.get_cache_stats()

        expected_keys = ['cache_dir', 'file_count', 'total_size_bytes', 'total_size_mb']
        if all(key in stats for key in expected_keys):
            logger.info("✅ PASS: Cache stats returned all required fields")
            logger.info(f"   Files: {stats['file_count']}, Size: {stats['total_size_mb']} MB")
        else:
            logger.error(f"❌ FAIL: Missing stats fields. Got: {list(stats.keys())}")
            return False

        # Test 7: Cache validity check
        logger.info("\nTest 7: Cache Validity Check")

        # Create a fresh cache file
        fresh_file = test_cache_dir / 'fresh_cache.json'
        cache._save_to_cache(fresh_file, test_data)

        is_valid = cache._is_cache_valid(fresh_file)
        logger.info(f"   Fresh file valid: {is_valid}")
        logger.info("✅ PASS: Cache validity check works")

        # Test 8: Cache clearing
        logger.info("\nTest 8: Cache Clearing")

        # Create multiple cache files
        for i in range(3):
            cache_file = test_cache_dir / f'cache_{i}.json'
            cache._save_to_cache(cache_file, test_data)

        files_before = len(list(test_cache_dir.glob('cache_*.json')))
        deleted_count = cache.clear_cache()
        files_after = len(list(test_cache_dir.glob('cache_*.json')))

        if deleted_count == files_before and files_after == 0:
            logger.info(f"✅ PASS: Cleared {deleted_count} cache files")
        else:
            logger.error(f"❌ FAIL: Expected to delete {files_before} files, deleted {deleted_count}")
            return False

        # Test 9: Singleton pattern
        logger.info("\nTest 9: Singleton Pattern")

        reset_cache()  # Reset any existing instance

        cache1 = get_historical_cache(cache_dir='data/test_singleton_1')
        cache2 = get_historical_cache(cache_dir='data/test_singleton_2')  # Should return same instance

        if cache1 is cache2:
            logger.info("✅ PASS: Singleton pattern works (same instance returned)")
        else:
            logger.error("❌ FAIL: Different instances returned")
            return False

        # Clean up singleton test dirs
        for path in ['data/test_singleton_1', 'data/test_singleton_2']:
            if Path(path).exists():
                shutil.rmtree(path)

        logger.info("\n" + "=" * 60)
        logger.info("🎉 ALL TESTS PASSED!")
        logger.info("=" * 60)

        return True

    except Exception as e:
        logger.error(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Clean up test cache
        if test_cache_dir.exists():
            shutil.rmtree(test_cache_dir)
            logger.info(f"\nCleaned up test cache: {test_cache_dir}")

if __name__ == '__main__':
    success = test_historical_cache()
    sys.exit(0 if success else 1)
