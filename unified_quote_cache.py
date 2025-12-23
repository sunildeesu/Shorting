"""
Unified Quote Cache

Shared cache for current quote data (price, OHLC, volume) used by all monitors.
Prevents duplicate API calls when multiple monitors run within a short time window.

Usage:
    cache = UnifiedQuoteCache()
    quotes = cache.get_or_fetch_quotes(stock_list, kite_client)

Author: Sunil Kumar Durganaik
"""

import json
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
import fcntl

logger = logging.getLogger(__name__)


class UnifiedQuoteCache:
    """
    Unified cache for quote data shared across all monitoring modules.

    Features:
    - 60-second TTL (default) - fresh enough for intraday, avoids redundant calls
    - Thread-safe file locking
    - Batch fetch integration
    - Automatic expiry and refresh
    """

    def __init__(self, cache_file: str = "data/unified_cache/quote_cache.json", ttl_seconds: int = 60):
        """
        Initialize unified quote cache.

        Args:
            cache_file: Path to cache file
            ttl_seconds: Time-to-live for cached data (default 60 seconds)
        """
        self.cache_file = cache_file
        self.ttl_seconds = ttl_seconds
        self.cache_data = None
        self.cache_timestamp = None

        # Ensure directory exists
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)

        # Load existing cache if available
        self._load_cache()

    def _load_cache(self):
        """Load cache from disk"""
        if not os.path.exists(self.cache_file):
            logger.debug("No existing quote cache found")
            return

        try:
            with open(self.cache_file, 'r') as f:
                # Acquire shared lock for reading
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                    self.cache_data = data.get('quotes', {})
                    timestamp_str = data.get('timestamp')

                    if timestamp_str:
                        self.cache_timestamp = datetime.fromisoformat(timestamp_str)
                        logger.debug(f"Loaded quote cache from {self.cache_timestamp}")
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        except (json.JSONDecodeError, IOError, ValueError) as e:
            logger.warning(f"Failed to load quote cache: {e}")
            self.cache_data = None
            self.cache_timestamp = None

    def _serialize_quotes(self, quotes: Dict) -> Dict:
        """
        Serialize quote data for JSON storage (convert datetime objects to strings)

        Args:
            quotes: Raw quote data from Kite API

        Returns:
            JSON-serializable dictionary
        """
        serialized = {}

        for key, value in quotes.items():
            if isinstance(value, dict):
                # Recursively serialize nested dicts
                serialized[key] = self._serialize_quotes(value)
            elif hasattr(value, 'isoformat'):
                # Convert datetime objects to ISO strings
                serialized[key] = value.isoformat()
            else:
                # Keep other values as-is
                serialized[key] = value

        return serialized

    def _save_cache(self):
        """Save cache to disk"""
        try:
            # Serialize quotes (convert datetime objects to strings)
            serialized_quotes = self._serialize_quotes(self.cache_data) if self.cache_data else {}

            data = {
                'quotes': serialized_quotes,
                'timestamp': self.cache_timestamp.isoformat() if self.cache_timestamp else None,
                'ttl_seconds': self.ttl_seconds
            }

            with open(self.cache_file, 'w') as f:
                # Acquire exclusive lock for writing
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(data, f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            logger.debug(f"Saved quote cache at {self.cache_timestamp}")

        except Exception as e:
            logger.error(f"Failed to save quote cache: {e}")

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid (within TTL)"""
        if self.cache_data is None or self.cache_timestamp is None:
            return False

        age = datetime.now() - self.cache_timestamp
        is_valid = age.total_seconds() < self.ttl_seconds

        if not is_valid:
            logger.debug(f"Quote cache expired (age: {age.total_seconds():.1f}s, TTL: {self.ttl_seconds}s)")

        return is_valid

    def get_cached_quotes(self) -> Optional[Dict]:
        """
        Get cached quotes if valid, otherwise None

        Returns:
            Dictionary of quotes or None if cache invalid/expired
        """
        if self._is_cache_valid():
            logger.info(f"✓ Using cached quotes ({len(self.cache_data)} stocks, "
                       f"age: {(datetime.now() - self.cache_timestamp).total_seconds():.1f}s)")
            return self.cache_data
        return None

    def set_cached_quotes(self, quotes: Dict):
        """
        Update cache with fresh quote data

        Args:
            quotes: Dictionary mapping "NSE:SYMBOL" to quote data
        """
        self.cache_data = quotes
        self.cache_timestamp = datetime.now()
        self._save_cache()

        logger.info(f"✓ Cached {len(quotes)} quote records (TTL: {self.ttl_seconds}s)")

    def get_or_fetch_quotes(
        self,
        symbols: List[str],
        kite_client,
        batch_size: int = 50,
        futures_mapper=None
    ) -> Dict:
        """
        Get quotes from cache if valid, otherwise fetch fresh from Kite API

        This is the main method to use - handles cache logic automatically.

        Args:
            symbols: List of stock symbols (without NSE: prefix)
            kite_client: KiteConnect instance
            batch_size: Batch size for API calls (default 50)
            futures_mapper: Optional FuturesMapper instance for fetching NFO futures OI

        Returns:
            Dictionary mapping "NSE:SYMBOL" (and "NFO:SYMBOL" if futures) to quote data
        """
        # Try to get from cache first
        cached_quotes = self.get_cached_quotes()
        if cached_quotes is not None:
            return cached_quotes

        # Cache miss or expired - fetch fresh data
        logger.info(f"Quote cache miss - fetching fresh data for {len(symbols)} stocks...")
        quotes = self._fetch_batch_quotes(symbols, kite_client, batch_size, futures_mapper)

        # Update cache with fresh data
        self.set_cached_quotes(quotes)

        return quotes

    def _fetch_batch_quotes(
        self,
        symbols: List[str],
        kite_client,
        batch_size: int = 50,
        futures_mapper=None
    ) -> Dict:
        """
        Fetch quotes in batches from Kite API (supports mixed NSE+NFO for OI data)

        Args:
            symbols: List of stock symbols
            kite_client: KiteConnect instance
            batch_size: Stocks per batch (default 50)
            futures_mapper: Optional FuturesMapper for fetching NFO futures OI

        Returns:
            Dictionary mapping "NSE:SYMBOL" and "NFO:FUTURES" to quote data
        """
        quote_data = {}
        total_batches = (len(symbols) + batch_size - 1) // batch_size

        start_time = time.time()

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            batch_index = (i // batch_size) + 1

            # Build MIXED batch: NSE equity + NFO futures (if mapper provided)
            instruments = []

            for symbol in batch:
                instruments.append(f"NSE:{symbol}")  # Always fetch equity

                # Add futures if available and OI enabled
                if futures_mapper:
                    futures_symbol = futures_mapper.get_futures_symbol(symbol)
                    if futures_symbol:
                        instruments.append(f"NFO:{futures_symbol}")

            try:
                # SINGLE API CALL FOR ENTIRE BATCH (NSE + NFO)
                quotes = kite_client.quote(*instruments)
                quote_data.update(quotes)

                logger.debug(f"Batch {batch_index}/{total_batches}: Fetched {len(quotes)} quotes "
                           f"({len(batch)} equity + futures)")

                # Rate limiting between batches
                if batch_index < total_batches:
                    time.sleep(0.4)  # Respect rate limits

            except Exception as e:
                logger.error(f"Batch {batch_index}/{total_batches}: Failed to fetch quotes: {e}")
                continue

        elapsed = time.time() - start_time
        logger.info(f"✓ Fetched {len(quote_data)} quotes in {elapsed:.1f}s "
                   f"({total_batches} API calls)")

        return quote_data

    def invalidate(self):
        """Force cache invalidation (for testing or manual refresh)"""
        self.cache_data = None
        self.cache_timestamp = None
        logger.info("Quote cache invalidated")

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics for monitoring

        Returns:
            Dictionary with cache stats
        """
        if self.cache_timestamp is None:
            return {
                'status': 'empty',
                'stocks_cached': 0,
                'age_seconds': None,
                'ttl_seconds': self.ttl_seconds,
                'is_valid': False
            }

        age = (datetime.now() - self.cache_timestamp).total_seconds()

        return {
            'status': 'valid' if self._is_cache_valid() else 'expired',
            'stocks_cached': len(self.cache_data) if self.cache_data else 0,
            'age_seconds': age,
            'ttl_seconds': self.ttl_seconds,
            'is_valid': self._is_cache_valid(),
            'timestamp': self.cache_timestamp.isoformat()
        }


def main():
    """Test/demonstration of UnifiedQuoteCache"""
    import config
    from kiteconnect import KiteConnect

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Test stock list
    test_stocks = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']

    # Initialize cache
    cache = UnifiedQuoteCache(ttl_seconds=60)

    print("=" * 60)
    print("UNIFIED QUOTE CACHE - TEST")
    print("=" * 60)

    # First call - should fetch fresh
    print("\n1. First call (cache miss - will fetch fresh)...")
    quotes1 = cache.get_or_fetch_quotes(test_stocks, kite)
    print(f"   Got {len(quotes1)} quotes")

    # Print stats
    stats = cache.get_cache_stats()
    print(f"\n   Cache stats: {stats}")

    # Second call within TTL - should use cache
    print("\n2. Second call within TTL (should use cache)...")
    quotes2 = cache.get_or_fetch_quotes(test_stocks, kite)
    print(f"   Got {len(quotes2)} quotes")

    # Verify they're the same
    print(f"\n3. Verification: quotes1 == quotes2? {quotes1 == quotes2}")

    # Show sample quote
    if quotes1:
        sample_key = list(quotes1.keys())[0]
        sample_quote = quotes1[sample_key]
        print(f"\n4. Sample quote for {sample_key}:")
        print(f"   Last Price: ₹{sample_quote['last_price']}")
        print(f"   Volume: {sample_quote['volume']:,}")
        print(f"   OHLC: O={sample_quote['ohlc']['open']}, "
              f"H={sample_quote['ohlc']['high']}, "
              f"L={sample_quote['ohlc']['low']}, "
              f"C={sample_quote['ohlc']['close']}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
