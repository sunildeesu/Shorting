#!/usr/bin/env python3
"""
Historical Data Cache - Cache OHLC Data to Reduce API Calls

Purpose:
- Cache historical data that doesn't change intraday
- Avoid refetching VIX/NIFTY history 22 times per day
- Automatic cache invalidation at market open (new trading day)

Benefits:
- 44+ API calls saved per day (historical_data calls)
- Faster analysis (instant cache hits vs 2-3 second API calls)
- Reduced load on Kite servers

Usage:
    from historical_data_cache import get_historical_cache

    cache = get_historical_cache()
    vix_data = cache.get_historical_data(
        kite=kite_instance,
        instrument_token=config.INDIA_VIX_TOKEN,
        from_date=start_date,
        to_date=end_date,
        interval='day'
    )
"""

import json
import logging
import os
from datetime import datetime, date, time as dtime
from pathlib import Path
from typing import List, Dict, Optional
from kiteconnect import KiteConnect

import config

logger = logging.getLogger(__name__)

# Singleton instance
_cache_instance = None


class HistoricalDataCache:
    """Cache for historical OHLC data (doesn't change intraday)"""

    def __init__(self, cache_dir: str = 'data/historical_cache'):
        """
        Initialize historical data cache.

        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"HistoricalDataCache initialized (cache_dir={self.cache_dir})")

    def get_historical_data(
        self,
        kite: KiteConnect,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False
    ) -> List[Dict]:
        """
        Fetch historical data with caching.

        Cache Strategy:
        - Cache key: instrument_token + interval + date range
        - TTL: Until market opens next day (intraday data won't change)
        - Invalidation: Automatic on new trading day

        Args:
            kite: KiteConnect instance
            instrument_token: Instrument token
            from_date: Start date
            to_date: End date
            interval: Candle interval (minute, day, etc.)
            continuous: True for continuous data (futures)
            oi: True to include OI data

        Returns:
            List of OHLC candles

        Example:
            vix_history = cache.get_historical_data(
                kite=kite,
                instrument_token=config.INDIA_VIX_TOKEN,
                from_date=datetime(2026, 1, 1),
                to_date=datetime(2026, 1, 10),
                interval='day'
            )
        """
        # Generate cache key
        cache_key = self._generate_cache_key(
            instrument_token,
            from_date,
            to_date,
            interval,
            continuous,
            oi
        )
        cache_file = self.cache_dir / f"{cache_key}.json"

        # Check cache
        if cache_file.exists():
            if self._is_cache_valid(cache_file):
                logger.info(f"Cache HIT: {cache_key} (0 API calls saved)")
                return self._load_from_cache(cache_file)
            else:
                logger.info(f"Cache EXPIRED: {cache_key}")
                # Delete expired cache
                cache_file.unlink()

        # Cache miss - fetch from API
        logger.info(f"Cache MISS: Fetching {cache_key} from Kite API...")

        try:
            data = kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
                continuous=continuous,
                oi=oi
            )

            # Save to cache
            self._save_to_cache(cache_file, data)
            logger.info(f"Cached {len(data)} candles to {cache_file.name}")

            return data

        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            # Return empty list on error (don't crash the service)
            return []

    def _generate_cache_key(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool,
        oi: bool
    ) -> str:
        """
        Generate unique cache key for historical data request.

        Args:
            instrument_token: Instrument token
            from_date: Start date
            to_date: End date
            interval: Candle interval
            continuous: Continuous flag
            oi: OI flag

        Returns:
            Cache key string

        Example:
            "264969_day_2026-01-01_2026-01-10"
        """
        from_str = from_date.date().isoformat()
        to_str = to_date.date().isoformat()

        key = f"{instrument_token}_{interval}_{from_str}_{to_str}"

        if continuous:
            key += "_continuous"
        if oi:
            key += "_oi"

        return key

    def _is_cache_valid(self, cache_file: Path) -> bool:
        """
        Check if cache file is still valid.

        Cache is valid if:
        1. Market is currently open (intraday) AND cached today
        2. Market is closed AND cached after previous market close

        Args:
            cache_file: Path to cache file

        Returns:
            True if cache is valid, False otherwise
        """
        file_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
        now = datetime.now()

        # If cached today during market hours, it's valid
        if file_time.date() == now.date():
            # Check if we're still in the same market session
            if self._is_market_open():
                return True

        # If market is closed, cache is valid until next market open
        if not self._is_market_open():
            # Check if cached after last market close
            last_close = self._get_last_market_close()
            if last_close and file_time > last_close:
                return True

        # Cache is expired
        return False

    def _is_market_open(self) -> bool:
        """
        Check if market is currently open.

        Returns:
            True if market is open, False otherwise
        """
        now = datetime.now()

        # Check time
        market_start = dtime(config.MARKET_START_HOUR, config.MARKET_START_MINUTE)
        market_end = dtime(config.MARKET_END_HOUR, config.MARKET_END_MINUTE)
        current_time = now.time()

        if not (market_start <= current_time <= market_end):
            return False

        # Check if it's a weekend
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # TODO: Add holiday check if needed
        # For now, assume weekdays during market hours = market open

        return True

    def _get_last_market_close(self) -> Optional[datetime]:
        """
        Get the last market close time.

        Returns:
            Datetime of last market close, or None
        """
        now = datetime.now()

        # If market is closed today, last close was today at 3:30 PM
        market_close_time = dtime(config.MARKET_END_HOUR, config.MARKET_END_MINUTE)

        if now.time() > market_close_time:
            # Market closed today
            return datetime.combine(now.date(), market_close_time)

        # Market hasn't closed today yet, so last close was yesterday (or Friday)
        # This is simplified - could be enhanced with holiday checking
        return None

    def _load_from_cache(self, cache_file: Path) -> List[Dict]:
        """
        Load data from cache file.

        Args:
            cache_file: Path to cache file

        Returns:
            List of OHLC candles
        """
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            return data
        except Exception as e:
            logger.error(f"Error loading cache file {cache_file}: {e}")
            return []

    def _save_to_cache(self, cache_file: Path, data: List[Dict]) -> None:
        """
        Save data to cache file.

        Args:
            cache_file: Path to cache file
            data: List of OHLC candles to cache
        """
        try:
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving cache file {cache_file}: {e}")

    def clear_cache(self, instrument_token: Optional[int] = None) -> int:
        """
        Clear cache files.

        Args:
            instrument_token: If provided, clear only caches for this instrument.
                            If None, clear all caches.

        Returns:
            Number of files deleted
        """
        deleted = 0

        if instrument_token is not None:
            # Clear specific instrument
            pattern = f"{instrument_token}_*.json"
        else:
            # Clear all
            pattern = "*.json"

        for cache_file in self.cache_dir.glob(pattern):
            try:
                cache_file.unlink()
                deleted += 1
            except Exception as e:
                logger.error(f"Error deleting cache file {cache_file}: {e}")

        logger.info(f"Cleared {deleted} cache file(s)")
        return deleted

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache stats (file count, total size, etc.)
        """
        cache_files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)

        return {
            'cache_dir': str(self.cache_dir),
            'file_count': len(cache_files),
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / 1024 / 1024, 2),
        }


def get_historical_cache(cache_dir: str = 'data/historical_cache') -> HistoricalDataCache:
    """
    Get or create the singleton historical cache instance.

    Args:
        cache_dir: Directory for cache files (used on first call only)

    Returns:
        HistoricalDataCache singleton instance

    Usage:
        cache = get_historical_cache()
        data = cache.get_historical_data(...)
    """
    global _cache_instance

    if _cache_instance is None:
        _cache_instance = HistoricalDataCache(cache_dir=cache_dir)
        logger.info("HistoricalDataCache singleton created")

    return _cache_instance


def reset_cache():
    """
    Reset the singleton instance (for testing).
    """
    global _cache_instance
    _cache_instance = None
    logger.info("HistoricalDataCache singleton reset")


# Example usage and testing
if __name__ == '__main__':
    # This is for testing only
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    cache = get_historical_cache()

    print("Historical Data Cache Test")
    print("=" * 50)
    print(f"Cache directory: {cache.cache_dir}")
    print(f"Market open: {cache._is_market_open()}")
    print()

    stats = cache.get_cache_stats()
    print("Cache Stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print("=" * 50)

    print()
    print("Usage example:")
    print("  from historical_data_cache import get_historical_cache")
    print("  cache = get_historical_cache()")
    print("  data = cache.get_historical_data(kite, token, from_date, to_date, 'day')")
    print("=" * 50)
