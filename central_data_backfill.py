#!/usr/bin/env python3
"""
Central Data Backfill - Fill Missing Historical Data

Automatically backfills missing intraday data when the central collector starts.
Ensures central_quotes.db always has the last 2 trading days of data.

Use Cases:
- Collector was down due to network issues
- Collector failed to start on a trading day
- Database was corrupted/deleted

Each candidate day is judged on its own rows (is_day_complete), so a day that a
mid-session crash truncated is still repaired after newer days have landed.
`--date YYYY-MM-DD` (repeatable) forces a specific past day regardless.

Author: Claude Opus 4.5
Date: 2026-02-13
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple
from kiteconnect import KiteConnect
import config
import instrument_token_map
from central_quote_db import get_central_db_writer
from market_utils import is_nse_holiday

logger = logging.getLogger(__name__)

# Configuration
BACKFILL_DAYS = 2  # Always ensure last 2 trading days are available
MARKET_START = dt_time(9, 15)
MARKET_END = dt_time(15, 30)

# Completeness of a stored day. The collector writes one tick per minute of the
# session, timestamped HH:MM:00, so a clean day holds every minute in
# [MARKET_START, MARKET_END) - 375 ticks, the last one at 15:29.
EXPECTED_TICKS_PER_DAY = ((MARKET_END.hour * 60 + MARKET_END.minute)
                          - (MARKET_START.hour * 60 + MARKET_START.minute))  # 375
LAST_TICK_TIME = (datetime.combine(datetime.min, MARKET_END) - timedelta(minutes=1)).time()  # 15:29
# A live collector cycle that runs long can drop a single minute; that is not a
# crash and not worth ~210 Kite calls to repair. A crash loses tens to hundreds
# of minutes. Anything short by more than this many ticks is treated as truncated.
TICK_SHORTFALL_TOLERANCE = 5


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
        """
        Load instrument tokens for historical API.

        The map must cover the universe: on 2026-08-31 a nine-month-old map silently
        capped every backfilled tick at 192 of 210 symbols. If the file is missing or
        does not resolve every universe symbol, regenerate it from kite.instruments("NSE")
        - the same source refresh_fo_universe.py writes it from - before using it.
        """
        try:
            if os.path.exists(instrument_token_map.TOKENS_FILE):
                tokens = instrument_token_map.load_token_map()
                missing = instrument_token_map.missing_tokens(self.stocks, tokens)
                if not missing:
                    return tokens
                logger.warning(f"Instrument token map is behind the universe "
                               f"({len(missing)} symbols unresolved) - refreshing from Kite")
                refreshed = self._fetch_instrument_tokens()
                return refreshed or tokens
            else:
                logger.warning("Instrument tokens not found, fetching...")
                return self._fetch_instrument_tokens()
        except Exception as e:
            logger.error(f"Failed to load instrument tokens: {e}")
            return {}

    def _fetch_instrument_tokens(self) -> Dict[str, int]:
        """Fetch and save instrument tokens from Kite (same shape and source as refresh_fo_universe.py)"""
        try:
            token_map = instrument_token_map.build_token_map(
                self.kite.instruments("NSE"), self.stocks)
            instrument_token_map.save_token_map(token_map)
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

    def get_day_coverage(self, day) -> Tuple[int, Optional[datetime]]:
        """
        How much of one trading day the stock_quotes table holds.

        Returns:
            (distinct tick count, timestamp of the last tick or None if no rows)
        """
        day_start = f"{day.strftime('%Y-%m-%d')} 00:00:00"
        next_day = f"{(day + timedelta(days=1)).strftime('%Y-%m-%d')} 00:00:00"
        cursor = self.db.conn.cursor()
        cursor.execute(
            "SELECT COUNT(DISTINCT timestamp), MAX(timestamp) FROM stock_quotes "
            "WHERE timestamp >= ? AND timestamp < ?",
            (day_start, next_day)
        )
        ticks, last_ts = cursor.fetchone()
        last_tick = datetime.strptime(last_ts, '%Y-%m-%d %H:%M:%S') if last_ts else None
        return ticks, last_tick

    def is_day_complete(self, day) -> bool:
        """
        A day is complete when its last tick reaches LAST_TICK_TIME and it is
        short by no more than TICK_SHORTFALL_TOLERANCE ticks. A day with no rows
        is incomplete. Each day is judged on its own rows - never against the
        newest row in the table - so a day truncated by a crash stays visible
        after later days have landed.
        """
        ticks, last_tick = self.get_day_coverage(day)
        if last_tick is None:
            return False
        if last_tick.time() < LAST_TICK_TIME:
            return False
        return ticks >= EXPECTED_TICKS_PER_DAY - TICK_SHORTFALL_TOLERANCE

    def get_trading_days_to_backfill(self, days: int = BACKFILL_DAYS, today=None) -> List[datetime]:
        """
        Calculate which of the last `days` trading days need backfilling:
        every one that is not complete per is_day_complete().

        Note: Kite publishes the tail of an equity session late (see AGENTS.md),
        so a day backfilled within about a week of the close may stop at ~15:14
        and stay "incomplete" while it remains inside the window. Re-runs are
        cheap and idempotent (INSERT OR IGNORE); a day that falls out of the
        window still short can be forced later with --date.

        Args:
            days: Number of trading days to look back
            today: Date to count back from (default: today)

        Returns:
            Sorted list of dates that need backfilling
        """
        if today is None:
            today = datetime.now().date()
        days_to_check = []

        # Check last `days` trading days
        check_date = today
        trading_days_found = 0

        while trading_days_found < days:
            # Skip weekends
            if check_date.weekday() < 5:  # Monday = 0, Friday = 4
                # Skip NSE holidays
                if not is_nse_holiday(check_date):
                    days_to_check.append(check_date)
                    trading_days_found += 1
            check_date -= timedelta(days=1)

        days_to_backfill = []
        for day in days_to_check:
            ticks, last_tick = self.get_day_coverage(day)
            if self.is_day_complete(day):
                logger.info(f"  {day}: complete ({ticks} ticks, last {last_tick.time()})")
            else:
                last_desc = last_tick.time() if last_tick else 'no rows'
                logger.info(f"  {day}: incomplete ({ticks} ticks, last {last_desc}) - will backfill")
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

    def run_backfill(self, days: int = BACKFILL_DAYS, dates: Optional[List] = None) -> Dict:
        """
        Run the full backfill process.

        Args:
            days: Number of trading days to look back (default: BACKFILL_DAYS)
            dates: Explicit dates to backfill regardless of completeness. When
                given, only these dates are processed and the window scan is skipped.

        Returns:
            Dict with backfill statistics. 'complete' is False and
            'missing_token_symbols' lists the names when the token map cannot resolve
            part of the universe: those symbols are NOT backfilled. The backfill still
            runs for the symbols it can resolve rather than aborting, because the days
            it is asked for are exactly the days with no data at all (the collector's
            startup path), and INSERT OR IGNORE makes a later re-run fill the rest
            once the map is repaired - but the shortfall is logged at ERROR, sent to
            Telegram, and never reported as success.
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
            'errors': 0,
            'missing_token_symbols': [],
            'complete': True,
        }

        # Get last timestamp
        last_timestamp = self.get_last_data_timestamp()

        if last_timestamp:
            age_hours = (datetime.now() - last_timestamp).total_seconds() / 3600
            logger.info(f"Last data timestamp: {last_timestamp} ({age_hours:.1f} hours ago)")
        else:
            logger.info("No existing data in database - full backfill needed")

        # Get days to backfill
        if dates:
            days_to_backfill = sorted(set(dates))
            stats['days_checked'] = len(days_to_backfill)
            logger.info(f"Forced dates (completeness check bypassed): "
                        f"{[d.strftime('%Y-%m-%d') for d in days_to_backfill]}")
        else:
            days_to_backfill = self.get_trading_days_to_backfill(days)
            stats['days_checked'] = days

        if not days_to_backfill:
            logger.info("No backfill needed - data is up to date")
            logger.info("=" * 80)
            return stats

        logger.info(f"Days to backfill: {[d.strftime('%Y-%m-%d') for d in days_to_backfill]}")

        # Fail loudly on a short universe: a map that resolves fewer symbols than the
        # collector collects must never look like a complete repair.
        missing = instrument_token_map.report_missing_tokens(
            self.stocks, self.instrument_tokens, caller='central_data_backfill')
        if missing:
            stats['missing_token_symbols'] = missing
            stats['complete'] = False

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
        if stats['complete']:
            logger.info("CENTRAL DATA BACKFILL - Complete")
        else:
            logger.error(f"CENTRAL DATA BACKFILL - INCOMPLETE: "
                         f"{len(stats['missing_token_symbols'])} symbols had no instrument token")
        logger.info(f"  Days backfilled: {stats['days_backfilled']}")
        logger.info(f"  Stock records: {stats['stock_records']}")
        logger.info(f"  NIFTY records: {stats['nifty_records']}")
        logger.info(f"  VIX records: {stats['vix_records']}")
        logger.info(f"  Errors: {stats['errors']}")
        logger.info("=" * 80)

        return stats


def run_backfill_standalone():
    """Run backfill as standalone script"""
    import argparse
    from kiteconnect import KiteConnect

    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=BACKFILL_DAYS,
                        help='Number of trading days to backfill (default: %(default)s)')
    parser.add_argument('--date', action='append', dest='dates', metavar='YYYY-MM-DD',
                        type=lambda s: datetime.strptime(s, '%Y-%m-%d').date(),
                        help='Force this day to be backfilled regardless of how complete it '
                             'looks. Repeatable. When given, --days is ignored and only the '
                             'named days are processed. Existing rows are kept (INSERT OR IGNORE).')
    args = parser.parse_args()

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
    stats = backfill.run_backfill(days=args.days, dates=args.dates)

    if not stats['complete']:
        print(f"\nBackfill INCOMPLETE: {stats}")
        return 1
    print(f"\nBackfill complete: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(run_backfill_standalone())
