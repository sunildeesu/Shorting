#!/usr/bin/env python3
"""
Central Data Backfill - Fill Missing Historical Data

Automatically backfills missing intraday data when the central collector starts.
Ensures central_quotes.db always has the last 2 trading days of data.

Use Cases:
- Collector was down due to network issues
- Collector failed to start on a trading day
- Database was corrupted/deleted

Author: Claude Opus 4.5
Date: 2026-02-13
"""

import json
import logging
import os
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple
from kiteconnect import KiteConnect
import config
from central_quote_db import get_central_db_writer
from market_utils import is_nse_holiday

logger = logging.getLogger(__name__)

# Configuration
BACKFILL_DAYS = 2  # Always ensure last 2 trading days are available
MARKET_START = dt_time(9, 15)
MARKET_END = dt_time(15, 30)


class CentralDataBackfill:
    """
    Backfills missing historical data into central_quotes.db.

    Called at startup to ensure data continuity even after collector downtime.
    """

    def __init__(self, kite: KiteConnect):
        """
        Initialize backfill with existing Kite connection.

        Args:
            kite: Authenticated KiteConnect instance
        """
        self.kite = kite
        self.db = get_central_db_writer()
        self.stocks = self._load_stock_list()
        self.instrument_tokens = self._load_instrument_tokens()

        logger.info(f"CentralDataBackfill initialized: {len(self.stocks)} stocks")

    def _load_stock_list(self) -> List[str]:
        """Load F&O stock list"""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                data = json.load(f)
                return data['stocks']
        except Exception as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

    def _load_instrument_tokens(self) -> Dict[str, int]:
        """Load instrument tokens for historical API"""
        tokens_file = "data/instrument_tokens.json"
        try:
            if os.path.exists(tokens_file):
                with open(tokens_file, 'r') as f:
                    return json.load(f)
            else:
                logger.warning("Instrument tokens not found, fetching...")
                return self._fetch_instrument_tokens()
        except Exception as e:
            logger.error(f"Failed to load instrument tokens: {e}")
            return {}

    def _fetch_instrument_tokens(self) -> Dict[str, int]:
        """Fetch and save instrument tokens from Kite"""
        try:
            instruments = self.kite.instruments("NSE")
            token_map = {}
            for inst in instruments:
                if inst['tradingsymbol'] in self.stocks:
                    token_map[inst['tradingsymbol']] = inst['instrument_token']

            # Add NIFTY 50 token
            token_map['NIFTY 50'] = config.NIFTY_50_TOKEN
            token_map['INDIA VIX'] = config.INDIA_VIX_TOKEN

            os.makedirs("data", exist_ok=True)
            with open("data/instrument_tokens.json", 'w') as f:
                json.dump(token_map, f, indent=2)

            logger.info(f"Fetched {len(token_map)} instrument tokens")
            return token_map
        except Exception as e:
            logger.error(f"Failed to fetch instrument tokens: {e}")
            return {}

    def get_last_data_timestamp(self) -> Optional[datetime]:
        """
        Get the timestamp of the most recent data in the database.

        Returns:
            datetime of last data, or None if no data
        """
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT MAX(timestamp) FROM stock_quotes")
            row = cursor.fetchone()

            if row and row[0]:
                return datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            return None
        except Exception as e:
            logger.error(f"Failed to get last timestamp: {e}")
            return None

    def get_trading_days_to_backfill(self, last_timestamp: Optional[datetime]) -> List[datetime]:
        """
        Calculate which trading days need backfilling.

        Args:
            last_timestamp: Last data timestamp in DB

        Returns:
            List of dates that need backfilling
        """
        today = datetime.now().date()
        days_to_check = []

        # Check last BACKFILL_DAYS trading days
        check_date = today
        trading_days_found = 0

        while trading_days_found < BACKFILL_DAYS:
            # Skip weekends
            if check_date.weekday() < 5:  # Monday = 0, Friday = 4
                # Skip NSE holidays
                if not is_nse_holiday(check_date):
                    days_to_check.append(check_date)
                    trading_days_found += 1
            check_date -= timedelta(days=1)

        # Filter to only days that need backfilling
        days_to_backfill = []

        for day in days_to_check:
            if last_timestamp is None:
                # No data at all - backfill everything
                days_to_backfill.append(day)
            elif day > last_timestamp.date():
                # Day is after last data - needs backfill
                days_to_backfill.append(day)
            elif day == last_timestamp.date():
                # Same day - check if we have full day's data
                # If last timestamp is before 15:00, we need more data
                if last_timestamp.time() < dt_time(15, 0):
                    days_to_backfill.append(day)

        return sorted(days_to_backfill)

    def backfill_stock_data(self, symbol: str, date: datetime) -> int:
        """
        Backfill 1-minute data for a single stock on a specific date.

        Args:
            symbol: Stock symbol
            date: Date to backfill

        Returns:
            Number of records stored
        """
        if symbol not in self.instrument_tokens:
            return 0

        token = self.instrument_tokens[symbol]

        try:
            # Fetch 1-minute historical data for the day
            from_datetime = datetime.combine(date, MARKET_START)
            to_datetime = datetime.combine(date, MARKET_END)

            data = self.kite.historical_data(
                instrument_token=token,
                from_date=from_datetime,
                to_date=to_datetime,
                interval="minute"
            )

            if not data:
                return 0

            # Store each minute's data
            cursor = self.db.conn.cursor()
            records_stored = 0

            for candle in data:
                timestamp = candle['date']
                if hasattr(timestamp, 'strftime'):
                    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
                else:
                    ts_str = str(timestamp)[:16] + ':00'

                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # Use INSERT OR IGNORE to skip duplicates
                cursor.execute("""
                    INSERT OR IGNORE INTO stock_quotes
                    (symbol, timestamp, price, volume, oi, oi_day_high, oi_day_low, last_updated)
                    VALUES (?, ?, ?, ?, 0, 0, 0, ?)
                """, (symbol, ts_str, candle['close'], candle['volume'], now_str))

                if cursor.rowcount > 0:
                    records_stored += 1

            self.db.conn.commit()
            return records_stored

        except Exception as e:
            logger.error(f"{symbol} backfill error for {date}: {e}")
            return 0

    def backfill_nifty_data(self, date: datetime) -> int:
        """
        Backfill 1-minute NIFTY data for a specific date.

        Args:
            date: Date to backfill

        Returns:
            Number of records stored
        """
        try:
            from_datetime = datetime.combine(date, MARKET_START)
            to_datetime = datetime.combine(date, MARKET_END)

            data = self.kite.historical_data(
                instrument_token=config.NIFTY_50_TOKEN,
                from_date=from_datetime,
                to_date=to_datetime,
                interval="minute"
            )

            if not data:
                return 0

            cursor = self.db.conn.cursor()
            records_stored = 0

            for candle in data:
                timestamp = candle['date']
                if hasattr(timestamp, 'strftime'):
                    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
                else:
                    ts_str = str(timestamp)[:16] + ':00'

                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                cursor.execute("""
                    INSERT OR IGNORE INTO nifty_quotes
                    (timestamp, price, open, high, low, volume, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (ts_str, candle['close'], candle['open'], candle['high'],
                      candle['low'], candle['volume'], now_str))

                if cursor.rowcount > 0:
                    records_stored += 1

            self.db.conn.commit()
            return records_stored

        except Exception as e:
            logger.error(f"NIFTY backfill error for {date}: {e}")
            return 0

    def backfill_vix_data(self, date: datetime) -> int:
        """
        Backfill 1-minute VIX data for a specific date.

        Args:
            date: Date to backfill

        Returns:
            Number of records stored
        """
        try:
            from_datetime = datetime.combine(date, MARKET_START)
            to_datetime = datetime.combine(date, MARKET_END)

            data = self.kite.historical_data(
                instrument_token=config.INDIA_VIX_TOKEN,
                from_date=from_datetime,
                to_date=to_datetime,
                interval="minute"
            )

            if not data:
                return 0

            cursor = self.db.conn.cursor()
            records_stored = 0

            for candle in data:
                timestamp = candle['date']
                if hasattr(timestamp, 'strftime'):
                    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
                else:
                    ts_str = str(timestamp)[:16] + ':00'

                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                cursor.execute("""
                    INSERT OR IGNORE INTO vix_quotes
                    (timestamp, vix_value, open, high, low, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (ts_str, candle['close'], candle['open'], candle['high'],
                      candle['low'], now_str))

                if cursor.rowcount > 0:
                    records_stored += 1

            self.db.conn.commit()
            return records_stored

        except Exception as e:
            logger.error(f"VIX backfill error for {date}: {e}")
            return 0

    def run_backfill(self) -> Dict:
        """
        Run the full backfill process.

        Returns:
            Dict with backfill statistics
        """
        logger.info("=" * 80)
        logger.info("CENTRAL DATA BACKFILL - Starting")
        logger.info("=" * 80)

        stats = {
            'days_checked': 0,
            'days_backfilled': 0,
            'stocks_backfilled': 0,
            'stock_records': 0,
            'nifty_records': 0,
            'vix_records': 0,
            'errors': 0
        }

        # Get last timestamp
        last_timestamp = self.get_last_data_timestamp()

        if last_timestamp:
            age_hours = (datetime.now() - last_timestamp).total_seconds() / 3600
            logger.info(f"Last data timestamp: {last_timestamp} ({age_hours:.1f} hours ago)")
        else:
            logger.info("No existing data in database - full backfill needed")

        # Get days to backfill
        days_to_backfill = self.get_trading_days_to_backfill(last_timestamp)
        stats['days_checked'] = BACKFILL_DAYS

        if not days_to_backfill:
            logger.info("No backfill needed - data is up to date")
            logger.info("=" * 80)
            return stats

        logger.info(f"Days to backfill: {[d.strftime('%Y-%m-%d') for d in days_to_backfill]}")

        # Backfill each day
        for day in days_to_backfill:
            logger.info(f"\nBackfilling {day.strftime('%Y-%m-%d')}...")
            day_stock_records = 0

            # Skip today if market is still open (will collect live data)
            if day == datetime.now().date():
                now = datetime.now().time()
                if MARKET_START <= now <= MARKET_END:
                    logger.info(f"  Skipping today - market is open, will collect live data")
                    continue

            # Backfill NIFTY first
            nifty_records = self.backfill_nifty_data(day)
            stats['nifty_records'] += nifty_records
            logger.info(f"  NIFTY: {nifty_records} records")

            # Backfill VIX
            vix_records = self.backfill_vix_data(day)
            stats['vix_records'] += vix_records
            logger.info(f"  VIX: {vix_records} records")

            # Backfill stocks (with rate limiting)
            stocks_done = 0
            for symbol in self.stocks:
                try:
                    records = self.backfill_stock_data(symbol, day)
                    if records > 0:
                        day_stock_records += records
                        stocks_done += 1

                    # Rate limiting - Kite allows ~3 req/sec for historical
                    import time
                    time.sleep(0.35)

                    # Progress logging every 50 stocks
                    if stocks_done % 50 == 0 and stocks_done > 0:
                        logger.info(f"  Stocks: {stocks_done}/{len(self.stocks)} done, {day_stock_records} records")

                except Exception as e:
                    logger.error(f"  {symbol} error: {e}")
                    stats['errors'] += 1

            stats['stock_records'] += day_stock_records
            stats['stocks_backfilled'] += stocks_done
            stats['days_backfilled'] += 1

            logger.info(f"  Day complete: {stocks_done} stocks, {day_stock_records} stock records")

        logger.info("\n" + "=" * 80)
        logger.info("CENTRAL DATA BACKFILL - Complete")
        logger.info(f"  Days backfilled: {stats['days_backfilled']}")
        logger.info(f"  Stock records: {stats['stock_records']}")
        logger.info(f"  NIFTY records: {stats['nifty_records']}")
        logger.info(f"  VIX records: {stats['vix_records']}")
        logger.info(f"  Errors: {stats['errors']}")
        logger.info("=" * 80)

        return stats


def run_backfill_standalone():
    """Run backfill as standalone script"""
    from kiteconnect import KiteConnect

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/central_backfill.log'),
            logging.StreamHandler()
        ]
    )

    logger.info("Initializing Kite Connect...")
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Validate token
    try:
        profile = kite.profile()
        logger.info(f"Token valid - User: {profile.get('user_name', 'Unknown')}")
    except Exception as e:
        logger.error(f"Token invalid: {e}")
        return

    # Run backfill
    backfill = CentralDataBackfill(kite)
    stats = backfill.run_backfill()

    print(f"\nBackfill complete: {stats}")


if __name__ == "__main__":
    run_backfill_standalone()
