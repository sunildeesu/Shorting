#!/usr/bin/env python3
"""
Unified Data Cache Manager

Handles caching of various types of stock data with configurable TTLs.
Shared across stock_monitor, atr_breakout_monitor, eod_analyzer, and value_screener.

Data types supported:
- historical_30d: 30-day daily candles (for EOD analysis)
- historical_50d: 50-day daily candles (for ATR calculation)
- historical_3year: 3-year daily candles (for value screener)
- intraday_5d: 5-day 15-minute candles (for EOD volume analysis)
- hourly_10d: 10-day hourly candles (for pre-market pattern detection)

Author: Sunil Kumar Durganaik
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class UnifiedDataCache:
    """
    Unified cache manager for historical and intraday stock data.

    Replaces EODCacheManager with enhanced multi-type caching.
    """

    # Default TTL (time-to-live) for different data types (in hours)
    DEFAULT_TTL = {
        'historical_30d': 24,    # Daily candles - refresh daily
        'historical_50d': 24,    # Daily candles - refresh daily
        'historical_3year': 24,  # 3-year daily candles - refresh daily (for value screener)
        'intraday_5d': 1,        # 15-min candles - refresh hourly
        'intraday_1d': 0.25,     # 15-min candles - refresh every 15 min
        'intraday_1min': 0.25,   # 1-min candles - refresh every 15 min (for volume profile)
        'hourly_10d': 6          # Hourly candles - refresh every 6 hours (for pre-market patterns)
    }

    def __init__(self, cache_dir: str = "data/unified_cache"):
        """
        Initialize unified cache manager.

        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = cache_dir
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

        # Separate cache files for different data types
        self.cache_files = {
            'historical_30d': os.path.join(cache_dir, 'historical_30d.json'),
            'historical_50d': os.path.join(cache_dir, 'historical_50d.json'),
            'historical_3year': os.path.join(cache_dir, 'historical_3year.json'),
            'intraday_5d': os.path.join(cache_dir, 'intraday_5d.json'),
            'intraday_1d': os.path.join(cache_dir, 'intraday_1d.json'),
            'intraday_1min': os.path.join(cache_dir, 'intraday_1min.json'),
            'hourly_10d': os.path.join(cache_dir, 'hourly_10d.json')
        }

        # Load all caches
        self.caches = {}
        for data_type, cache_file in self.cache_files.items():
            self.caches[data_type] = self._load_cache(cache_file, data_type)

        logger.info(f"Unified cache initialized: {cache_dir}")

    def _load_cache(self, cache_file: str, data_type: str) -> Dict:
        """Load cache from file"""
        if not os.path.exists(cache_file):
            logger.debug(f"{data_type}: No existing cache")
            return {}

        try:
            with open(cache_file, 'r') as f:
                cache = json.load(f)
                logger.info(f"{data_type}: Loaded cache with {len(cache)} stocks")
                return cache
        except Exception as e:
            logger.error(f"{data_type}: Error loading cache: {e}")
            return {}

    def _save_cache(self, data_type: str):
        """Save cache to file"""
        try:
            cache_file = self.cache_files[data_type]
            with open(cache_file, 'w') as f:
                json.dump(self.caches[data_type], f, indent=2)
            logger.debug(f"{data_type}: Cache saved ({len(self.caches[data_type])} stocks)")
        except Exception as e:
            logger.error(f"{data_type}: Error saving cache: {e}")

    def _is_cache_valid(self, cache_entry: Dict, data_type: str) -> bool:
        """
        Check if cache entry is still valid (not expired).

        Args:
            cache_entry: Cache entry with 'cached_at' timestamp
            data_type: Type of data (determines TTL)

        Returns:
            True if cache is valid, False if expired
        """
        if 'cached_at' not in cache_entry:
            return False

        try:
            cached_at = datetime.fromisoformat(cache_entry['cached_at'])
            age_hours = (datetime.now() - cached_at).total_seconds() / 3600
            ttl_hours = self.DEFAULT_TTL.get(data_type, 24)

            return age_hours < ttl_hours
        except (ValueError, TypeError):
            return False

    def get_data(self, symbol: str, data_type: str = 'historical_30d') -> Optional[List[Dict]]:
        """
        Get cached data for a stock.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE" or "RELIANCE.NS")
            data_type: Type of data ('historical_30d', 'historical_50d', 'historical_3year', 'intraday_5d')

        Returns:
            List of OHLCV dicts if cache valid, None if expired/missing
        """
        if data_type not in self.caches:
            logger.error(f"Invalid data type: {data_type}")
            return None

        cache = self.caches[data_type]

        if symbol not in cache:
            logger.debug(f"{symbol} ({data_type}): Cache miss")
            return None

        cache_entry = cache[symbol]

        if not self._is_cache_valid(cache_entry, data_type):
            age_hours = (datetime.now() - datetime.fromisoformat(cache_entry['cached_at'])).total_seconds() / 3600
            logger.debug(f"{symbol} ({data_type}): Cache expired (age: {age_hours:.1f}h)")
            del cache[symbol]
            self._save_cache(data_type)
            return None

        logger.debug(f"{symbol} ({data_type}): Cache hit")
        return cache_entry['data']

    def set_data(self, symbol: str, data: List[Dict], data_type: str = 'historical_30d'):
        """
        Cache data for a stock.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE" or "RELIANCE.NS")
            data: List of OHLCV dicts from Kite API
            data_type: Type of data ('historical_30d', 'historical_50d', 'historical_3year', 'intraday_5d')
        """
        if data_type not in self.caches:
            logger.error(f"Invalid data type: {data_type}")
            return

        # Convert datetime objects to ISO strings for JSON serialization
        serializable_data = []
        for candle in data:
            candle_copy = candle.copy()
            if 'date' in candle_copy and hasattr(candle_copy['date'], 'isoformat'):
                candle_copy['date'] = candle_copy['date'].isoformat()
            serializable_data.append(candle_copy)

        self.caches[data_type][symbol] = {
            'data': serializable_data,
            'cached_at': datetime.now().isoformat(),
            'candle_count': len(data)
        }

        logger.debug(f"{symbol} ({data_type}): Cached {len(data)} candles")
        self._save_cache(data_type)

    def clear_expired(self, data_type: Optional[str] = None):
        """
        Remove all expired cache entries.

        Args:
            data_type: Specific data type to clear, or None for all types
        """
        types_to_clear = [data_type] if data_type else self.caches.keys()

        total_cleared = 0
        for dtype in types_to_clear:
            cache = self.caches[dtype]
            expired_symbols = [
                symbol for symbol, entry in cache.items()
                if not self._is_cache_valid(entry, dtype)
            ]

            for symbol in expired_symbols:
                del cache[symbol]

            if expired_symbols:
                logger.info(f"{dtype}: Cleared {len(expired_symbols)} expired entries")
                self._save_cache(dtype)
                total_cleared += len(expired_symbols)

        return total_cleared

    def get_cache_stats(self, data_type: Optional[str] = None) -> Dict:
        """
        Get cache statistics.

        Args:
            data_type: Specific data type, or None for all types

        Returns:
            Dict with cache stats
        """
        if data_type:
            cache = self.caches.get(data_type, {})
            valid_stocks = sum(1 for entry in cache.values() if self._is_cache_valid(entry, data_type))

            return {
                'data_type': data_type,
                'total_stocks': len(cache),
                'valid_stocks': valid_stocks,
                'expired_stocks': len(cache) - valid_stocks,
                'ttl_hours': self.DEFAULT_TTL.get(data_type, 24)
            }

        # Stats for all data types
        all_stats = {}
        for dtype in self.caches.keys():
            all_stats[dtype] = self.get_cache_stats(dtype)

        return all_stats

    # Backward compatibility methods for EOD analyzer
    def get_historical_data(self, symbol: str) -> Optional[List[Dict]]:
        """
        Get 30-day historical data (backward compatible with EODCacheManager).

        Args:
            symbol: Stock symbol

        Returns:
            List of OHLCV dicts if cache valid, None otherwise
        """
        return self.get_data(symbol, 'historical_30d')

    def set_historical_data(self, symbol: str, data: List[Dict]):
        """
        Cache 30-day historical data (backward compatible with EODCacheManager).

        Args:
            symbol: Stock symbol
            data: List of OHLCV dicts
        """
        self.set_data(symbol, data, 'historical_30d')

    # Helper methods for specific use cases
    def get_atr_data(self, symbol: str) -> Optional[List[Dict]]:
        """Get 50-day historical data for ATR calculation"""
        return self.get_data(symbol, 'historical_50d')

    def set_atr_data(self, symbol: str, data: List[Dict]):
        """Cache 50-day historical data for ATR calculation"""
        self.set_data(symbol, data, 'historical_50d')

    def get_intraday_data(self, symbol: str, days: int = 5) -> Optional[List[Dict]]:
        """Get intraday 15-minute data"""
        data_type = f'intraday_{days}d'
        return self.get_data(symbol, data_type)

    def set_intraday_data(self, symbol: str, data: List[Dict], days: int = 5):
        """Cache intraday 15-minute data"""
        data_type = f'intraday_{days}d'
        self.set_data(symbol, data, data_type)

    def get_hourly_data(self, symbol: str) -> Optional[List[Dict]]:
        """Get 10-day hourly data for pre-market pattern detection"""
        return self.get_data(symbol, 'hourly_10d')

    def set_hourly_data(self, symbol: str, data: List[Dict]):
        """Cache 10-day hourly data for pre-market pattern detection"""
        self.set_data(symbol, data, 'hourly_10d')


def main():
    """Test/demonstration of UnifiedDataCache"""
    cache = UnifiedDataCache()

    print("=" * 60)
    print("UNIFIED DATA CACHE - TEST")
    print("=" * 60)

    # Test data (mock)
    test_symbol = "RELIANCE"
    test_data = [
        {'date': datetime.now().isoformat(), 'open': 2340, 'high': 2350, 'low': 2330, 'close': 2345, 'volume': 1000000},
        {'date': (datetime.now() - timedelta(days=1)).isoformat(), 'open': 2330, 'high': 2340, 'low': 2320, 'close': 2335, 'volume': 950000}
    ]

    print("\n1. Setting 30-day historical data...")
    cache.set_data(test_symbol, test_data, 'historical_30d')

    print("\n2. Setting 50-day historical data (for ATR)...")
    cache.set_atr_data(test_symbol, test_data * 2)  # More candles

    print("\n3. Getting cached data...")
    data_30d = cache.get_data(test_symbol, 'historical_30d')
    data_50d = cache.get_atr_data(test_symbol)

    print(f"   30-day data: {len(data_30d) if data_30d else 0} candles")
    print(f"   50-day data: {len(data_50d) if data_50d else 0} candles")

    print("\n4. Cache statistics...")
    stats = cache.get_cache_stats()
    for data_type, type_stats in stats.items():
        print(f"   {data_type}:")
        print(f"     Valid: {type_stats['valid_stocks']}")
        print(f"     Expired: {type_stats['expired_stocks']}")
        print(f"     TTL: {type_stats['ttl_hours']}h")

    print("\n5. Testing backward compatibility...")
    old_data = cache.get_historical_data(test_symbol)
    print(f"   get_historical_data() returned: {len(old_data) if old_data else 0} candles")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
