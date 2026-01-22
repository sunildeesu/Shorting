#!/usr/bin/env python3
"""
Central Data Collector - Single Source of Truth for Market Data

Fetches all market data every 1 minute and stores in central database:
- F&O stock quotes (NSE equity + NFO futures for OI)
- NIFTY 50 spot data
- India VIX data

All other monitoring services read from this central database.

ROBUSTNESS FEATURES:
- Retry with exponential backoff (3 attempts per batch)
- Batch-level retry with smaller batch sizes on failure
- Partial success handling (store successful data, retry failed)
- Token validation before collection
- Health tracking and alerting
- Graceful degradation

Author: Claude Sonnet 4.5
Date: 2026-01-19
"""

import json
import logging
import os
import sys
import time
import random
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from kiteconnect import KiteConnect
from kiteconnect.exceptions import (
    TokenException, NetworkException, GeneralException,
    DataException, InputException
)

import config
from central_quote_db import get_central_db_writer
# Note: Market hour checks handled by central_data_collector_continuous.py
from futures_mapper import get_futures_mapper

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 10.0  # seconds
BACKOFF_MULTIPLIER = 2.0

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

    ROBUSTNESS: Includes retry logic, health tracking, and graceful degradation.
    """

    def __init__(self):
        """Initialize central collector"""
        logger.info("=" * 80)
        logger.info("CENTRAL DATA COLLECTOR - Initializing")
        logger.info("=" * 80)

        # Health tracking
        self._consecutive_failures = 0
        self._total_failures = 0
        self._total_successes = 0
        self._last_successful_collection = None

        # NOTE: Market hour checks removed from here.
        # When used via central_data_collector_continuous.py (the normal case),
        # the continuous script handles market hour checks with its own logic
        # (9:15 AM - 3:30 PM vs config's 9:25 AM for stock_monitor).
        # When running standalone, collect_and_store() will simply fail gracefully
        # if the API returns no data outside market hours.

        # Initialize Kite Connect
        logger.info("Initializing Kite Connect...")
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Validate token before proceeding
        if not self._validate_token():
            logger.error("❌ Token validation failed - cannot proceed")
            sys.exit(1)

        logger.info("✓ Kite Connect initialized and token validated")

        # Initialize central database
        logger.info("Initializing central database...")
        self.db = get_central_db_writer()  # Writer mode for central collector
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

    def _validate_token(self) -> bool:
        """
        Validate Kite access token by making a test API call.

        Returns:
            True if token is valid, False otherwise
        """
        try:
            # Simple profile call to validate token
            profile = self.kite.profile()
            logger.info(f"✓ Token valid - User: {profile.get('user_name', 'Unknown')}")
            return True
        except TokenException as e:
            logger.error(f"Token invalid or expired: {e}")
            return False
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return False

    def _retry_with_backoff(self, func, *args, max_retries: int = MAX_RETRIES, **kwargs):
        """
        Execute a function with exponential backoff retry.

        Args:
            func: Function to execute
            *args: Function arguments
            max_retries: Maximum retry attempts
            **kwargs: Function keyword arguments

        Returns:
            Function result or None if all retries failed
        """
        last_exception = None
        delay = INITIAL_RETRY_DELAY

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)

            except TokenException as e:
                # Token errors are fatal - don't retry
                logger.error(f"Token error (not retrying): {e}")
                raise

            except NetworkException as e:
                last_exception = e
                logger.warning(f"Network error (attempt {attempt + 1}/{max_retries}): {e}")

            except (GeneralException, DataException) as e:
                last_exception = e
                logger.warning(f"API error (attempt {attempt + 1}/{max_retries}): {e}")

            except Exception as e:
                last_exception = e
                logger.warning(f"Unexpected error (attempt {attempt + 1}/{max_retries}): {e}")

            # Don't sleep after last attempt
            if attempt < max_retries - 1:
                # Add jitter to prevent thundering herd
                jittered_delay = delay * (1 + random.uniform(-0.1, 0.1))
                logger.info(f"Retrying in {jittered_delay:.1f}s...")
                time.sleep(jittered_delay)
                delay = min(delay * BACKOFF_MULTIPLIER, MAX_RETRY_DELAY)

        logger.error(f"All {max_retries} retry attempts failed. Last error: {last_exception}")
        return None

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

        DATA ACCURACY POLICY:
        - Only store COMPLETE data (no partial updates)
        - If stocks < 95% success → DON'T store, keep last known good data
        - If NIFTY/VIX fails → DON'T store, keep last known good data
        - Better to have stale accurate data than fresh incomplete data
        """
        timestamp = datetime.now()
        logger.info(f"Starting collection cycle at {timestamp.strftime('%H:%M:%S')}")

        # Minimum accuracy thresholds
        MIN_STOCK_SUCCESS_RATE = 0.95  # 95% of stocks must succeed
        min_stocks_required = int(len(self.stocks) * MIN_STOCK_SUCCESS_RATE)

        collection_stats = {
            'stocks_fetched': 0,
            'stocks_expected': len(self.stocks),
            'stocks_stored': 0,
            'nifty_fetched': False,
            'nifty_stored': False,
            'vix_fetched': False,
            'vix_stored': False,
            'errors': 0,
            'data_quality': 'UNKNOWN',
            'stock_quotes': {}  # For rapid_drop_detector: {symbol: {price, volume, oi, ...}}
        }

        start_time = time.time()

        try:
            # ============================================
            # Step 1: Fetch ALL data first (don't store yet)
            # ============================================

            # Fetch F&O stock quotes
            logger.info(f"Fetching quotes for {len(self.stocks)} stocks...")
            stock_quotes = self._fetch_stock_quotes()
            collection_stats['stocks_fetched'] = len(stock_quotes)
            collection_stats['stock_quotes'] = stock_quotes  # Include for rapid_drop_detector

            # Fetch NIFTY spot data
            logger.info("Fetching NIFTY 50 quote...")
            nifty_quote = self._fetch_nifty_quote()
            collection_stats['nifty_fetched'] = (nifty_quote is not None)

            # Fetch India VIX data
            logger.info("Fetching India VIX quote...")
            vix_quote = self._fetch_vix_quote()
            collection_stats['vix_fetched'] = (vix_quote is not None)

            # ============================================
            # Step 2: Validate data quality BEFORE storing
            # ============================================

            stocks_ok = len(stock_quotes) >= min_stocks_required
            nifty_ok = nifty_quote is not None
            vix_ok = vix_quote is not None

            logger.info("Data quality check:")
            logger.info(f"  Stocks: {len(stock_quotes)}/{len(self.stocks)} "
                       f"(need {min_stocks_required}, {'✓ PASS' if stocks_ok else '✗ FAIL'})")
            logger.info(f"  NIFTY: {'✓ PASS' if nifty_ok else '✗ FAIL'}")
            logger.info(f"  VIX: {'✓ PASS' if vix_ok else '✗ FAIL'}")

            # ============================================
            # Step 3: Store ONLY if data quality is acceptable
            # ============================================

            if stocks_ok:
                # Stock data meets accuracy threshold - store it
                self.db.store_stock_quotes(stock_quotes, timestamp)
                collection_stats['stocks_stored'] = len(stock_quotes)
                logger.info(f"✓ Stored {len(stock_quotes)} stock quotes (accuracy: "
                           f"{len(stock_quotes)/len(self.stocks)*100:.1f}%)")
            else:
                # Stock data incomplete - DON'T store, keep last known good data
                collection_stats['errors'] += 1
                logger.error(f"✗ NOT storing stock quotes - only {len(stock_quotes)}/{len(self.stocks)} "
                            f"({len(stock_quotes)/len(self.stocks)*100:.1f}% < {MIN_STOCK_SUCCESS_RATE*100}% threshold)")
                logger.error("  Keeping last known good data in database")

            if nifty_ok:
                # NIFTY data valid - store it
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
                collection_stats['nifty_stored'] = True
                logger.info(f"✓ Stored NIFTY quote: ₹{nifty_quote['last_price']:.2f}")
            else:
                # NIFTY failed - DON'T store, keep last known good data
                collection_stats['errors'] += 1
                logger.error("✗ NOT storing NIFTY quote - fetch failed, keeping last known good data")

            if vix_ok:
                # VIX data valid - store it
                self.db.store_vix_quote(
                    vix_value=vix_quote['last_price'],
                    ohlc={
                        'open': vix_quote.get('ohlc', {}).get('open'),
                        'high': vix_quote.get('ohlc', {}).get('high'),
                        'low': vix_quote.get('ohlc', {}).get('low')
                    },
                    timestamp=timestamp
                )
                collection_stats['vix_stored'] = True
                logger.info(f"✓ Stored VIX quote: {vix_quote['last_price']:.2f}")
            else:
                # VIX failed - DON'T store, keep last known good data
                collection_stats['errors'] += 1
                logger.error("✗ NOT storing VIX quote - fetch failed, keeping last known good data")

            # ============================================
            # Step 4: Determine overall data quality
            # ============================================

            if stocks_ok and nifty_ok and vix_ok:
                collection_stats['data_quality'] = 'COMPLETE'
                self._consecutive_failures = 0
                self._total_successes += 1
                self._last_successful_collection = timestamp
                self.db.update_metadata('last_collection_time', timestamp.isoformat())
                self.db.update_metadata('collection_status', 'success')
            elif stocks_ok:
                # Stocks OK but NIFTY/VIX failed - partial success
                collection_stats['data_quality'] = 'PARTIAL'
                self.db.update_metadata('last_collection_time', timestamp.isoformat())
                self.db.update_metadata('collection_status', 'partial: stocks_only')
            else:
                # Stocks failed - this is a failure
                collection_stats['data_quality'] = 'FAILED'
                self._consecutive_failures += 1
                self._total_failures += 1
                self.db.update_metadata('collection_status',
                    f'failed: {collection_stats["stocks_fetched"]}/{collection_stats["stocks_expected"]} stocks')

                # Alert on consecutive failures
                if self._consecutive_failures >= 3:
                    logger.critical(f"🚨 ALERT: {self._consecutive_failures} consecutive collection failures!")
                    logger.critical("🚨 Database contains STALE data - services may be using outdated prices!")
                    self.db.update_metadata('health_alert',
                        f'consecutive_failures: {self._consecutive_failures}, data may be stale')

        except TokenException as e:
            logger.error(f"❌ TOKEN ERROR: {e}")
            logger.error("Token may have expired. Please regenerate token.")
            logger.error("NOT storing any data - keeping last known good data")
            collection_stats['errors'] += 1
            collection_stats['data_quality'] = 'TOKEN_ERROR'
            self._consecutive_failures += 1
            self._total_failures += 1
            self.db.update_metadata('collection_status', f'token_error: {str(e)}')

        except Exception as e:
            logger.error(f"❌ Collection cycle failed: {e}", exc_info=True)
            logger.error("NOT storing any data - keeping last known good data")
            collection_stats['errors'] += 1
            collection_stats['data_quality'] = 'ERROR'
            self._consecutive_failures += 1
            self._total_failures += 1
            self.db.update_metadata('collection_status', f'error: {str(e)}')

        elapsed = time.time() - start_time

        # Summary
        logger.info("=" * 80)
        quality_icon = {'COMPLETE': '✓', 'PARTIAL': '⚠️', 'FAILED': '✗',
                       'TOKEN_ERROR': '🔑', 'ERROR': '❌', 'UNKNOWN': '?'}
        logger.info(f"Collection cycle {quality_icon.get(collection_stats['data_quality'], '?')} "
                   f"{collection_stats['data_quality']} in {elapsed:.2f}s")
        logger.info(f"  Stocks: fetched={collection_stats['stocks_fetched']}, "
                   f"stored={collection_stats['stocks_stored']}/{collection_stats['stocks_expected']}")
        logger.info(f"  NIFTY: fetched={'✓' if collection_stats['nifty_fetched'] else '✗'}, "
                   f"stored={'✓' if collection_stats['nifty_stored'] else '✗'}")
        logger.info(f"  VIX: fetched={'✓' if collection_stats['vix_fetched'] else '✗'}, "
                   f"stored={'✓' if collection_stats['vix_stored'] else '✗'}")
        logger.info(f"  Errors: {collection_stats['errors']}")
        logger.info(f"  Health: {self._total_successes} successes, {self._total_failures} failures, "
                   f"{self._consecutive_failures} consecutive failures")
        logger.info("=" * 80)

        return collection_stats

    def _fetch_batch_with_retry(self, instruments: List[str], batch_num: int) -> Tuple[Dict, List[str]]:
        """
        Fetch a batch of instruments with retry logic.

        Args:
            instruments: List of instruments to fetch
            batch_num: Batch number for logging

        Returns:
            Tuple of (successful_quotes, failed_instruments)
        """
        # Try with full batch first
        result = self._retry_with_backoff(
            lambda: self.kite.quote(*instruments)
        )

        if result is not None:
            return result, []

        # If full batch failed, try smaller sub-batches
        logger.warning(f"Batch {batch_num} failed completely. Trying smaller sub-batches...")

        successful_quotes = {}
        failed_instruments = []
        sub_batch_size = 50  # Much smaller batch

        for i in range(0, len(instruments), sub_batch_size):
            sub_batch = instruments[i:i + sub_batch_size]
            sub_batch_num = i // sub_batch_size + 1

            result = self._retry_with_backoff(
                lambda batch=sub_batch: self.kite.quote(*batch),
                max_retries=2  # Fewer retries for sub-batches
            )

            if result is not None:
                successful_quotes.update(result)
                logger.info(f"  Sub-batch {sub_batch_num}: ✓ {len(result)} quotes")
            else:
                failed_instruments.extend(sub_batch)
                logger.warning(f"  Sub-batch {sub_batch_num}: ✗ {len(sub_batch)} instruments failed")

            # Small delay between sub-batches
            time.sleep(0.2)

        return successful_quotes, failed_instruments

    def _fetch_stock_quotes(self) -> Dict[str, Dict]:
        """
        Fetch F&O stock quotes in batches (equity + futures for OI).

        ROBUSTNESS:
        - Retry with exponential backoff on failures
        - Fall back to smaller batches if large batch fails
        - Track and report partial failures
        - Continue with partial data rather than complete failure

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

        # Fetch in batches with robust retry
        all_quotes = {}
        all_failed = []
        batch_count = 0
        successful_batches = 0

        for i in range(0, len(total_instruments), batch_size):
            batch = total_instruments[i:i + batch_size]
            batch_count += 1

            logger.debug(f"Batch {batch_count}: Fetching {len(batch)} instruments...")

            batch_quotes, failed = self._fetch_batch_with_retry(batch, batch_count)

            if batch_quotes:
                all_quotes.update(batch_quotes)
                successful_batches += 1

            if failed:
                all_failed.extend(failed)

            # Rate limiting between batches
            if i + batch_size < len(total_instruments):
                time.sleep(config.REQUEST_DELAY_SECONDS)

        # Log summary
        logger.info(f"Fetched {len(all_quotes)} quotes in {batch_count} batches "
                   f"({successful_batches} successful)")

        if all_failed:
            logger.warning(f"⚠️  {len(all_failed)} instruments failed after all retries")
            # Log first few failed instruments for debugging
            logger.warning(f"  Failed (first 10): {all_failed[:10]}")

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
        Fetch NIFTY 50 spot quote with retry logic.

        Returns:
            Quote dict or None
        """
        instrument = "NSE:NIFTY 50"

        result = self._retry_with_backoff(
            lambda: self.kite.quote(instrument)
        )

        if result:
            return result.get(instrument)

        logger.error("Failed to fetch NIFTY quote after all retries")
        return None

    def _fetch_vix_quote(self) -> Optional[Dict]:
        """
        Fetch India VIX quote with retry logic.

        Returns:
            Quote dict or None
        """
        instrument = "NSE:INDIA VIX"

        result = self._retry_with_backoff(
            lambda: self.kite.quote(instrument)
        )

        if result:
            return result.get(instrument)

        logger.error("Failed to fetch VIX quote after all retries")
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
