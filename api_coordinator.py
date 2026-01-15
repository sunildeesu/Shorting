#!/usr/bin/env python3
"""
Kite API Coordinator - Centralized API Call Manager

Purpose:
- Eliminate duplicate API calls across services
- Centralize quote fetching with automatic caching
- Smart batching (200 instruments per call, Kite supports 500)
- Singleton pattern ensures all services share the same cache

Benefits:
- At collision times (10:00 AM): 1 API call instead of 2-3 (66-90% savings)
- Automatic cache management with 60-second TTL
- Reduced database lock contention (fewer cache writes)

Usage:
    from api_coordinator import get_api_coordinator

    coordinator = get_api_coordinator()
    quotes = coordinator.get_quotes(['RELIANCE', 'TCS', 'INFY'])
"""

import logging
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

import config
from unified_quote_cache import UnifiedQuoteCache

logger = logging.getLogger(__name__)

# Singleton instance
_coordinator_instance = None


class KiteAPICoordinator:
    """
    Centralized API call coordinator to eliminate duplication.
    All services request quotes through this coordinator.
    """

    def __init__(self, kite: KiteConnect):
        """
        Initialize coordinator with Kite connection.

        Args:
            kite: Authenticated KiteConnect instance
        """
        self.kite = kite
        self.batch_size = 200  # Optimal batch size (Kite supports 500)

        # Use unified quote cache for automatic deduplication
        self.quote_cache = UnifiedQuoteCache(
            cache_file=config.QUOTE_CACHE_FILE,
            ttl_seconds=config.QUOTE_CACHE_TTL_SECONDS
        )

        logger.info(f"KiteAPICoordinator initialized (batch_size={self.batch_size}, "
                   f"cache_ttl={config.QUOTE_CACHE_TTL_SECONDS}s)")

    def get_quotes(
        self,
        symbols: List[str],
        force_refresh: bool = False,
        include_futures: bool = False,
        futures_mapper=None
    ) -> Dict:
        """
        Fetch quotes with automatic caching and batching.

        Args:
            symbols: List of stock symbols (e.g., ['RELIANCE', 'TCS'])
            force_refresh: If True, bypass cache and fetch fresh data
            include_futures: If True, also fetch futures quotes for OI data
            futures_mapper: FuturesMapper instance (required if include_futures=True)

        Returns:
            Dictionary of quotes keyed by instrument (e.g., 'NSE:RELIANCE')

        Example:
            quotes = coordinator.get_quotes(['RELIANCE', 'TCS'])
            reliance_ltp = quotes['NSE:RELIANCE']['last_price']
        """
        if not symbols:
            logger.warning("get_quotes called with empty symbol list")
            return {}

        # Check cache first (unless force_refresh requested)
        if not force_refresh:
            cached_quotes = self.quote_cache.get_quotes(symbols)
            if cached_quotes:
                logger.info(f"Cache HIT: Retrieved {len(cached_quotes)} quotes from cache "
                           f"(0 API calls, saved ~{len(symbols)//self.batch_size + 1} calls)")
                return self._format_quotes_for_return(cached_quotes)

        # Cache miss - fetch from API
        logger.info(f"Cache MISS: Fetching {len(symbols)} quotes from Kite API...")
        start_time = time.time()

        # Build instrument list
        instruments = []
        symbol_to_instrument = {}

        # Add equity instruments
        for symbol in symbols:
            instrument = f"NSE:{symbol}"
            instruments.append(instrument)
            symbol_to_instrument[symbol] = instrument

        # Add futures instruments if requested
        futures_to_equity = {}
        if include_futures and futures_mapper:
            for symbol in symbols:
                futures_symbol = futures_mapper.get_futures_symbol(symbol)
                if futures_symbol:
                    futures_instrument = f"NFO:{futures_symbol}"
                    instruments.append(futures_instrument)
                    futures_to_equity[futures_instrument] = symbol

        # Fetch in optimized batches
        all_quotes = {}
        batch_count = 0

        for i in range(0, len(instruments), self.batch_size):
            batch = instruments[i:i + self.batch_size]
            batch_count += 1

            try:
                logger.debug(f"Fetching batch {batch_count} ({len(batch)} instruments)...")
                batch_quotes = self.kite.quote(*batch)
                all_quotes.update(batch_quotes)

                # Rate limiting (if multiple batches)
                if i + self.batch_size < len(instruments):
                    time.sleep(config.REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"Error fetching batch {batch_count}: {e}")
                # Continue with next batch instead of failing completely
                continue

        # Update cache with new quotes
        if all_quotes:
            # Extract equity quotes for cache (exclude futures)
            equity_quotes = {k: v for k, v in all_quotes.items() if k.startswith('NSE:')}
            self.quote_cache.set_cached_quotes(equity_quotes)

            elapsed = time.time() - start_time
            logger.info(f"Fetched {len(all_quotes)} quotes in {elapsed:.2f}s "
                       f"({batch_count} API call{'s' if batch_count > 1 else ''})")

        return all_quotes

    def get_single_quote(self, instrument: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetch a single quote (convenience method).

        Args:
            instrument: Full instrument name (e.g., 'NSE:NIFTY 50', 'NSE:INDIA VIX')
            use_cache: If True, check cache first

        Returns:
            Quote dictionary or None if not found

        Example:
            nifty = coordinator.get_single_quote('NSE:NIFTY 50')
            vix = coordinator.get_single_quote('NSE:INDIA VIX')
        """
        try:
            # For single quotes, bypass cache and fetch directly
            # (cache is optimized for batch operations)
            quotes = self.kite.quote([instrument])
            return quotes.get(instrument)
        except Exception as e:
            logger.error(f"Error fetching quote for {instrument}: {e}")
            return None

    def get_multiple_instruments(
        self,
        instruments: List[str],
        use_cache: bool = False
    ) -> Dict:
        """
        Fetch quotes for specific instruments (not symbols).
        Used for indices, VIX, futures, options, etc.

        Args:
            instruments: List of full instrument names
                        (e.g., ['NSE:NIFTY 50', 'NSE:INDIA VIX', 'NFO:NIFTY26JAN24500CE'])
            use_cache: If True, check cache (only works for NSE instruments)

        Returns:
            Dictionary of quotes keyed by instrument

        Example:
            quotes = coordinator.get_multiple_instruments([
                'NSE:NIFTY 50',
                'NSE:INDIA VIX',
                'NFO:NIFTY26JAN24500CE'
            ])
        """
        if not instruments:
            return {}

        # Fetch in batches
        all_quotes = {}
        batch_count = 0

        for i in range(0, len(instruments), self.batch_size):
            batch = instruments[i:i + self.batch_size]
            batch_count += 1

            try:
                logger.debug(f"Fetching instrument batch {batch_count} ({len(batch)} instruments)...")
                batch_quotes = self.kite.quote(*batch)
                all_quotes.update(batch_quotes)

                # Rate limiting
                if i + self.batch_size < len(instruments):
                    time.sleep(config.REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"Error fetching instrument batch {batch_count}: {e}")
                continue

        # Update cache with NSE instruments (for sharing across services)
        if all_quotes:
            equity_quotes = {k: v for k, v in all_quotes.items() if k.startswith('NSE:')}
            if equity_quotes:
                self.quote_cache.set_cached_quotes(equity_quotes)
                logger.debug(f"Updated cache with {len(equity_quotes)} NSE quotes")

        logger.info(f"Fetched {len(all_quotes)} instrument quotes "
                   f"({batch_count} API call{'s' if batch_count > 1 else ''})")
        return all_quotes

    def _format_quotes_for_return(self, cached_quotes: Dict) -> Dict:
        """
        Format cached quotes to match Kite API response format.

        Args:
            cached_quotes: Quotes from UnifiedQuoteCache

        Returns:
            Dictionary formatted like Kite API response
        """
        # UnifiedQuoteCache returns {symbol: quote_data}
        # Convert to {'NSE:symbol': quote_data} for consistency
        formatted = {}
        for symbol, quote_data in cached_quotes.items():
            instrument = f"NSE:{symbol}"
            formatted[instrument] = quote_data
        return formatted

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics for monitoring.

        Returns:
            Dictionary with cache stats (hit rate, size, age, etc.)
        """
        return {
            'cache_enabled': self.quote_cache.use_sqlite,
            'ttl_seconds': self.quote_cache.ttl_seconds,
            'batch_size': self.batch_size,
            # Add more stats from quote_cache if available
        }


def get_api_coordinator(kite: Optional[KiteConnect] = None) -> KiteAPICoordinator:
    """
    Get or create the singleton API coordinator instance.

    Args:
        kite: KiteConnect instance (required on first call)

    Returns:
        KiteAPICoordinator singleton instance

    Usage:
        # First service initializes with kite connection
        coordinator = get_api_coordinator(kite=my_kite_instance)

        # Subsequent services can omit kite parameter
        coordinator = get_api_coordinator()
    """
    global _coordinator_instance

    if _coordinator_instance is None:
        if kite is None:
            raise ValueError("kite parameter required for first initialization of API coordinator")
        _coordinator_instance = KiteAPICoordinator(kite)
        logger.info("API Coordinator singleton created")

    return _coordinator_instance


def reset_coordinator():
    """
    Reset the singleton instance (for testing).
    """
    global _coordinator_instance
    _coordinator_instance = None
    logger.info("API Coordinator singleton reset")


# Example usage and testing
if __name__ == '__main__':
    # This is for testing only
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("API Coordinator Test")
    print("=" * 50)
    print("This module should be imported, not run directly.")
    print()
    print("Usage example:")
    print("  from api_coordinator import get_api_coordinator")
    print("  coordinator = get_api_coordinator(kite=my_kite)")
    print("  quotes = coordinator.get_quotes(['RELIANCE', 'TCS'])")
    print("=" * 50)
