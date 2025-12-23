#!/usr/bin/env python3
"""
Futures Mapper - Maps equity symbols to their current month futures contracts
Enables OI (Open Interest) data fetching for stock monitoring
"""

import json
import os
import logging
from datetime import datetime, date
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)

# Singleton instance
_futures_mapper_instance = None


class FuturesMapper:
    """
    Maps equity symbols to their current month futures tradingsymbols.

    Example: RELIANCE → RELIANCE25JAN

    Features:
    - Daily refresh at market open (9:15 AM)
    - Automatic expiry detection (nearest expiry = most liquid)
    - Month rollover handling (DEC → JAN)
    - JSON caching for fast lookups
    - Graceful handling of missing futures
    """

    def __init__(self, cache_file: str = "data/futures_mapping.json"):
        """
        Initialize mapper and load cached mappings if available.

        Args:
            cache_file: Path to JSON cache file
        """
        self.cache_file = cache_file
        self.mappings = {}  # symbol → {futures_symbol, expiry, exchange}
        self.metadata = {
            "last_updated": None,
            "total_mappings": 0
        }
        self.stats = {
            "with_futures": 0,
            "without_futures": 0
        }

        # Load cached mappings
        self._load_cache()

    def get_futures_symbol(self, equity_symbol: str) -> Optional[str]:
        """
        Get the current month futures tradingsymbol for an equity symbol.

        Args:
            equity_symbol: Equity symbol (e.g., "RELIANCE")

        Returns:
            Futures tradingsymbol (e.g., "RELIANCE25JAN") or None if no futures

        Example:
            >>> mapper.get_futures_symbol("RELIANCE")
            'RELIANCE25JAN'
            >>> mapper.get_futures_symbol("SMALLCAP_STOCK")
            None
        """
        mapping = self.mappings.get(equity_symbol)
        if mapping:
            return mapping.get("futures_symbol")
        return None

    def refresh_mappings(self, kite_client, stock_symbols: List[str] = None) -> Dict:
        """
        Fetch all NFO instruments and build futures mappings.

        Process:
        1. Fetch all NFO instruments from Kite
        2. Filter for equity futures (instrument_type == 'FUT')
        3. Group by equity symbol
        4. Select nearest expiry (most liquid contract)
        5. Detect expiry rollovers
        6. Save to cache

        Args:
            kite_client: KiteConnect instance
            stock_symbols: Optional list of symbols to map (if None, maps all found)

        Returns:
            Updated mappings dict

        Raises:
            Exception: If NFO instrument fetch fails
        """
        logger.info("Fetching NFO instruments from Kite API...")

        try:
            # Fetch all NFO instruments
            instruments = kite_client.instruments("NFO")

            # Filter for equity futures only
            futures = [
                inst for inst in instruments
                if inst.get('instrument_type') == 'FUT'
            ]

            logger.info(f"Found {len(futures)} total futures contracts")

            # Group by equity symbol and find nearest expiry
            equity_futures = {}  # symbol → list of futures contracts

            for fut in futures:
                symbol = fut['name']  # Base equity symbol (e.g., "RELIANCE")

                if symbol not in equity_futures:
                    equity_futures[symbol] = []

                equity_futures[symbol].append({
                    'tradingsymbol': fut['tradingsymbol'],
                    'expiry': fut['expiry'],
                    'exchange': fut['exchange']
                })

            # Build mappings: select nearest expiry for each symbol
            new_mappings = {}
            old_mappings = self.mappings.copy()

            for symbol, contracts in equity_futures.items():
                # Filter stock_symbols if provided
                if stock_symbols and symbol not in stock_symbols:
                    continue

                # Sort by expiry date (ascending) and select first (nearest)
                contracts.sort(key=lambda x: x['expiry'])
                nearest = contracts[0]

                new_mappings[symbol] = {
                    'futures_symbol': nearest['tradingsymbol'],
                    'expiry': nearest['expiry'].isoformat() if isinstance(nearest['expiry'], date) else str(nearest['expiry']),
                    'exchange': nearest['exchange']
                }

                # Detect expiry rollover
                if symbol in old_mappings:
                    old_futures = old_mappings[symbol].get('futures_symbol')
                    new_futures = nearest['tradingsymbol']

                    if old_futures != new_futures:
                        logger.info(f"📅 Expiry Rollover Detected: {symbol}")
                        logger.info(f"   {old_futures} (expired) → {new_futures} (active)")

            # Update mappings
            self.mappings = new_mappings

            # Update metadata
            self.metadata = {
                "last_updated": datetime.now().isoformat(),
                "total_mappings": len(new_mappings)
            }

            # Update stats
            total_symbols = len(stock_symbols) if stock_symbols else len(equity_futures)
            self.stats = {
                "with_futures": len(new_mappings),
                "without_futures": total_symbols - len(new_mappings)
            }

            # Save to cache
            self._save_cache()

            logger.info(f"✓ Futures mapping complete: {self.stats['with_futures']} stocks with futures")

            return new_mappings

        except Exception as e:
            logger.error(f"Failed to refresh futures mappings: {e}")
            logger.warning("Using stale cache from previous update (if available)")
            raise

    def is_refresh_needed(self) -> bool:
        """
        Check if futures mapping needs refresh.

        Refresh needed if:
        1. No cache file exists (first run)
        2. Last update was on a previous day
        3. Current time is before market open (9:15 AM) and cache is from previous day

        Returns:
            True if refresh needed, False otherwise
        """
        # No cache = needs refresh
        if not self.metadata.get("last_updated"):
            logger.debug("No cache found - refresh needed")
            return True

        try:
            last_update = datetime.fromisoformat(self.metadata["last_updated"])
            now = datetime.now()

            # Different day = needs refresh
            if last_update.date() < now.date():
                logger.debug(f"Cache from previous day ({last_update.date()}) - refresh needed")
                return True

            # Same day, already refreshed = no refresh needed
            logger.debug(f"Cache current (updated {last_update.strftime('%Y-%m-%d %H:%M:%S')})")
            return False

        except Exception as e:
            logger.error(f"Error checking refresh status: {e}")
            return True  # Err on the side of caution

    def get_stats(self) -> Dict[str, int]:
        """
        Get statistics about futures coverage.

        Returns:
            Dict with keys: total, with_futures, without_futures
        """
        return {
            "total": self.metadata.get("total_mappings", 0),
            "with_futures": self.stats.get("with_futures", 0),
            "without_futures": self.stats.get("without_futures", 0)
        }

    def _load_cache(self):
        """Load mappings from JSON cache file."""
        if not os.path.exists(self.cache_file):
            logger.debug(f"Cache file not found: {self.cache_file}")
            return

        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)

            self.mappings = data.get("mappings", {})
            self.metadata = data.get("metadata", {"last_updated": None, "total_mappings": 0})
            self.stats = data.get("stats", {"with_futures": 0, "without_futures": 0})

            logger.info(f"✓ Loaded {len(self.mappings)} futures mappings from cache")
            logger.debug(f"   Last updated: {self.metadata.get('last_updated', 'Unknown')}")

        except Exception as e:
            logger.error(f"Failed to load cache: {e}")
            # Continue with empty mappings

    def _save_cache(self):
        """Save mappings to JSON cache file (atomic write)."""
        try:
            # Ensure directory exists
            cache_dir = os.path.dirname(self.cache_file)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)

            # Prepare data
            data = {
                "metadata": self.metadata,
                "mappings": self.mappings,
                "stats": self.stats
            }

            # Atomic write: write to temp file, then rename
            temp_file = f"{self.cache_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)

            # Atomic rename
            os.replace(temp_file, self.cache_file)

            logger.debug(f"✓ Saved {len(self.mappings)} mappings to cache")

        except Exception as e:
            logger.error(f"Failed to save cache: {e}")


def get_futures_mapper(cache_file: str = "data/futures_mapping.json") -> FuturesMapper:
    """
    Get singleton FuturesMapper instance.

    Args:
        cache_file: Path to cache file (default: data/futures_mapping.json)

    Returns:
        FuturesMapper instance

    Example:
        >>> mapper = get_futures_mapper()
        >>> futures_symbol = mapper.get_futures_symbol("RELIANCE")
    """
    global _futures_mapper_instance

    if _futures_mapper_instance is None:
        _futures_mapper_instance = FuturesMapper(cache_file)

    return _futures_mapper_instance


# Test/Demo code
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

    print("=" * 80)
    print("FUTURES MAPPER - TEST/DEMO")
    print("=" * 80)

    # Create mapper
    mapper = get_futures_mapper()

    # Show current mappings
    print(f"\nCurrent mappings loaded: {len(mapper.mappings)}")
    print(f"Last updated: {mapper.metadata.get('last_updated', 'Never')}")
    print(f"Stats: {mapper.get_stats()}")

    # Test lookups (will work if cache exists)
    test_symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"]
    print(f"\nTesting lookups for {len(test_symbols)} symbols:")
    for symbol in test_symbols:
        futures_symbol = mapper.get_futures_symbol(symbol)
        if futures_symbol:
            print(f"  ✓ {symbol:12} → {futures_symbol}")
        else:
            print(f"  ✗ {symbol:12} → No futures contract")

    # Check if refresh needed
    print(f"\nRefresh needed: {mapper.is_refresh_needed()}")

    print("\n" + "=" * 80)
    print("To fetch fresh data: mapper.refresh_mappings(kite_client)")
    print("=" * 80)
