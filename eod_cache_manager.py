#!/usr/bin/env python3
"""
EOD Cache Manager - Handles caching of 30-day historical data
Minimizes API calls by caching historical data with 24-hour expiry
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class EODCacheManager:
    """Manages caching of historical stock data for EOD analysis"""

    def __init__(self, cache_file: str = "data/eod_cache/historical_cache.json"):
        """
        Initialize cache manager

        Args:
            cache_file: Path to cache file
        """
        self.cache_file = cache_file
        self.cache = self._load_cache()
        self.cache_duration_hours = 24  # Cache expires after 24 hours

    def _load_cache(self) -> Dict:
        """Load cache from file"""
        if not os.path.exists(self.cache_file):
            logger.info(f"Cache file not found, creating new cache")
            return {}

        try:
            with open(self.cache_file, 'r') as f:
                cache = json.load(f)
                logger.info(f"Loaded cache with {len(cache)} stocks")
                return cache
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            return {}

    def _save_cache(self):
        """Save cache to file"""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
            logger.info(f"Cache saved successfully ({len(self.cache)} stocks)")
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def _is_cache_valid(self, cache_entry: Dict) -> bool:
        """
        Check if cache entry is still valid (not expired)

        Args:
            cache_entry: Cache entry with 'cached_at' timestamp

        Returns:
            True if cache is valid, False if expired
        """
        if 'cached_at' not in cache_entry:
            return False

        cached_at = datetime.fromisoformat(cache_entry['cached_at'])
        age_hours = (datetime.now() - cached_at).total_seconds() / 3600

        return age_hours < self.cache_duration_hours

    def get_historical_data(self, symbol: str) -> Optional[List[Dict]]:
        """
        Get cached historical data for a stock

        Args:
            symbol: Stock symbol (e.g., "RELIANCE.NS")

        Returns:
            List of OHLCV dicts if cache valid, None if expired/missing
        """
        if symbol not in self.cache:
            logger.debug(f"{symbol}: Cache miss")
            return None

        cache_entry = self.cache[symbol]

        if not self._is_cache_valid(cache_entry):
            logger.debug(f"{symbol}: Cache expired")
            del self.cache[symbol]
            self._save_cache()
            return None

        logger.debug(f"{symbol}: Cache hit")
        return cache_entry['data']

    def set_historical_data(self, symbol: str, data: List[Dict]):
        """
        Cache historical data for a stock

        Args:
            symbol: Stock symbol (e.g., "RELIANCE.NS")
            data: List of OHLCV dicts from Kite API
        """
        # Convert datetime objects to ISO strings for JSON serialization
        serializable_data = []
        for candle in data:
            candle_copy = candle.copy()
            if 'date' in candle_copy and hasattr(candle_copy['date'], 'isoformat'):
                candle_copy['date'] = candle_copy['date'].isoformat()
            serializable_data.append(candle_copy)

        self.cache[symbol] = {
            'data': serializable_data,
            'cached_at': datetime.now().isoformat()
        }
        logger.debug(f"{symbol}: Cached {len(data)} candles")
        self._save_cache()

    def clear_expired(self):
        """Remove all expired cache entries"""
        expired_symbols = [
            symbol for symbol, entry in self.cache.items()
            if not self._is_cache_valid(entry)
        ]

        for symbol in expired_symbols:
            del self.cache[symbol]

        if expired_symbols:
            logger.info(f"Cleared {len(expired_symbols)} expired cache entries")
            self._save_cache()

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics

        Returns:
            Dict with cache stats (total_stocks, valid_stocks, expired_stocks)
        """
        total_stocks = len(self.cache)
        valid_stocks = sum(1 for entry in self.cache.values() if self._is_cache_valid(entry))
        expired_stocks = total_stocks - valid_stocks

        return {
            'total_stocks': total_stocks,
            'valid_stocks': valid_stocks,
            'expired_stocks': expired_stocks,
            'cache_file': self.cache_file
        }
