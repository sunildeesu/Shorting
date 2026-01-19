#!/usr/bin/env python3
"""
Central Data Collector - Single Source of Truth for Market Data

Fetches all market data every 1 minute and stores in central database:
- F&O stock quotes (NSE equity + NFO futures for OI)
- NIFTY 50 spot data
- India VIX data

All other monitoring services read from this central database.

Author: Claude Sonnet 4.5
Date: 2026-01-19
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional
from kiteconnect import KiteConnect

import config
from central_quote_db import get_central_db
from market_utils import is_market_open, get_market_status
from futures_mapper import get_futures_mapper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/central_collector.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class CentralDataCollector:
    """
    Central data collection service.
    Fetches ALL market data and stores in centralized database.
    """

    def __init__(self):
        """Initialize central collector"""
        logger.info("=" * 80)
        logger.info("CENTRAL DATA COLLECTOR - Initializing")
        logger.info("=" * 80)

        # Market check
        if not is_market_open():
            status = get_market_status()
            if not status['is_trading_day']:
                logger.info("Not a trading day - exiting")
            else:
                logger.info("Outside market hours - exiting")
            sys.exit(0)

        # Initialize Kite Connect
        logger.info("Initializing Kite Connect...")
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
        logger.info("✓ Kite Connect initialized")

        # Initialize central database
        logger.info("Initializing central database...")
        self.db = get_central_db()
        logger.info("✓ Central database initialized")

        # Load F&O stock list
        self.stocks = self._load_stock_list()
        logger.info(f"✓ Loaded {len(self.stocks)} F&O stocks")

        # Initialize futures mapper for OI data
        self.futures_mapper = None
        if config.ENABLE_FUTURES_OI:
            try:
                self.futures_mapper = get_futures_mapper(
                    cache_file=config.FUTURES_MAPPING_FILE
                )
                logger.info("✓ Futures mapper initialized")
            except Exception as e:
                logger.error(f"Failed to initialize futures mapper: {e}")

        logger.info("=" * 80)
        logger.info("CENTRAL DATA COLLECTOR - Ready")
        logger.info("=" * 80)

    def _load_stock_list(self) -> List[str]:
        """Load F&O stock list from JSON file"""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                data = json.load(f)
                return data['stocks']
        except Exception as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

    def collect_and_store(self):
        """
        Main collection cycle - fetch and store all data.
        This runs every 1 minute via LaunchAgent.
        """
        timestamp = datetime.now()
        logger.info(f"Starting collection cycle at {timestamp.strftime('%H:%M:%S')}")

        collection_stats = {
            'stocks_fetched': 0,
            'nifty_fetched': False,
            'vix_fetched': False,
            'api_calls': 0,
            'errors': 0
        }

        start_time = time.time()

        try:
            # Step 1: Fetch F&O stock quotes (equity + futures)
            logger.info(f"Fetching quotes for {len(self.stocks)} stocks...")
            stock_quotes = self._fetch_stock_quotes()
            collection_stats['stocks_fetched'] = len(stock_quotes)

            # Step 2: Fetch NIFTY spot data
            logger.info("Fetching NIFTY 50 quote...")
            nifty_quote = self._fetch_nifty_quote()
            collection_stats['nifty_fetched'] = (nifty_quote is not None)

            # Step 3: Fetch India VIX data
            logger.info("Fetching India VIX quote...")
            vix_quote = self._fetch_vix_quote()
            collection_stats['vix_fetched'] = (vix_quote is not None)

            # Step 4: Store everything in database
            logger.info("Storing data in central database...")

            if stock_quotes:
                self.db.store_stock_quotes(stock_quotes, timestamp)

            if nifty_quote:
                self.db.store_nifty_quote(
                    price=nifty_quote['last_price'],
                    ohlc={
                        'open': nifty_quote.get('ohlc', {}).get('open'),
                        'high': nifty_quote.get('ohlc', {}).get('high'),
                        'low': nifty_quote.get('ohlc', {}).get('low'),
                        'volume': nifty_quote.get('volume', 0)
                    },
                    timestamp=timestamp
                )

            if vix_quote:
                self.db.store_vix_quote(
                    vix_value=vix_quote['last_price'],
                    ohlc={
                        'open': vix_quote.get('ohlc', {}).get('open'),
                        'high': vix_quote.get('ohlc', {}).get('high'),
                        'low': vix_quote.get('ohlc', {}).get('low')
                    },
                    timestamp=timestamp
                )

            # Update metadata
            self.db.update_metadata('last_collection_time', timestamp.isoformat())
            self.db.update_metadata('collection_status', 'success')

        except Exception as e:
            logger.error(f"Collection cycle failed: {e}", exc_info=True)
            collection_stats['errors'] += 1
            self.db.update_metadata('collection_status', f'error: {str(e)}')

        elapsed = time.time() - start_time

        # Summary
        logger.info("=" * 80)
        logger.info(f"Collection cycle complete in {elapsed:.2f}s")
        logger.info(f"  Stocks: {collection_stats['stocks_fetched']}/{len(self.stocks)}")
        logger.info(f"  NIFTY: {'✓' if collection_stats['nifty_fetched'] else '✗'}")
        logger.info(f"  VIX: {'✓' if collection_stats['vix_fetched'] else '✗'}")
        logger.info(f"  API calls: {collection_stats['api_calls']}")
        logger.info(f"  Errors: {collection_stats['errors']}")
        logger.info("=" * 80)

        return collection_stats

    def _fetch_stock_quotes(self) -> Dict[str, Dict]:
        """
        Fetch F&O stock quotes in batches (equity + futures for OI).

        Returns:
            Dict of {symbol: {price, volume, oi, oi_day_high, oi_day_low}}
        """
        if not self.stocks:
            return {}

        stock_data = {}
        batch_size = 200  # Kite supports 500, using 200 for safety
        total_instruments = []
        instrument_map = {}

        # Build instrument list (NSE equity + NFO futures)
        for symbol in self.stocks:
            # Equity quote
            equity_instrument = f"NSE:{symbol}"
            total_instruments.append(equity_instrument)
            instrument_map[equity_instrument] = symbol

            # Futures quote (for OI)
            if self.futures_mapper:
                futures_symbol = self.futures_mapper.get_futures_symbol(symbol)
                if futures_symbol:
                    futures_instrument = f"NFO:{futures_symbol}"
                    total_instruments.append(futures_instrument)
                    instrument_map[futures_instrument] = symbol

        logger.info(f"Fetching {len(total_instruments)} instruments "
                   f"({len(self.stocks)} equity + futures)")

        # Fetch in batches
        all_quotes = {}
        batch_count = 0

        for i in range(0, len(total_instruments), batch_size):
            batch = total_instruments[i:i + batch_size]
            batch_count += 1

            try:
                logger.debug(f"Batch {batch_count}: Fetching {len(batch)} instruments...")
                batch_quotes = self.kite.quote(*batch)
                all_quotes.update(batch_quotes)

                # Rate limiting
                if i + batch_size < len(total_instruments):
                    time.sleep(config.REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"Batch {batch_count} failed: {e}")
                continue

        logger.info(f"Fetched {len(all_quotes)} quotes in {batch_count} API calls")

        # Parse quotes into stock_data
        # Pass 1: Extract equity data (price, volume)
        for instrument, quote in all_quotes.items():
            if instrument.startswith("NSE:"):
                symbol = instrument_map.get(instrument)
                if not symbol:
                    continue

                if symbol not in stock_data:
                    stock_data[symbol] = {}

                stock_data[symbol]['price'] = quote.get('last_price', 0)
                stock_data[symbol]['volume'] = quote.get('volume', 0)

        # Pass 2: Extract futures data (OI)
        for instrument, quote in all_quotes.items():
            if instrument.startswith("NFO:"):
                symbol = instrument_map.get(instrument)
                if not symbol or symbol not in stock_data:
                    continue

                stock_data[symbol]['oi'] = quote.get('oi', 0)
                stock_data[symbol]['oi_day_high'] = quote.get('oi_day_high', 0)
                stock_data[symbol]['oi_day_low'] = quote.get('oi_day_low', 0)

        # Ensure all stocks have OI fields (even if 0)
        for symbol in stock_data:
            if 'oi' not in stock_data[symbol]:
                stock_data[symbol]['oi'] = 0
                stock_data[symbol]['oi_day_high'] = 0
                stock_data[symbol]['oi_day_low'] = 0

        return stock_data

    def _fetch_nifty_quote(self) -> Optional[Dict]:
        """
        Fetch NIFTY 50 spot quote.

        Returns:
            Quote dict or None
        """
        try:
            instrument = "NSE:NIFTY 50"
            quotes = self.kite.quote(instrument)
            return quotes.get(instrument)
        except Exception as e:
            logger.error(f"Failed to fetch NIFTY quote: {e}")
            return None

    def _fetch_vix_quote(self) -> Optional[Dict]:
        """
        Fetch India VIX quote.

        Returns:
            Quote dict or None
        """
        try:
            instrument = "NSE:INDIA VIX"
            quotes = self.kite.quote(instrument)
            return quotes.get(instrument)
        except Exception as e:
            logger.error(f"Failed to fetch VIX quote: {e}")
            return None

    def cleanup_old_data(self):
        """
        Cleanup data older than 1 day.
        Call this once daily (e.g., at market close).
        """
        logger.info("Running database cleanup...")
        self.db.cleanup_old_data(days=1)
        logger.info("Cleanup complete")


def main():
    """Main entry point"""
    try:
        collector = CentralDataCollector()
        collector.collect_and_store()

        # Optional: Cleanup old data (run only at specific times to avoid overhead)
        now = datetime.now()
        if now.hour == 15 and now.minute >= 30:
            # Run cleanup after market close
            collector.cleanup_old_data()

        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
