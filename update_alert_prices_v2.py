#!/usr/bin/env python3
"""
Update Alert Prices Script V2 (PROPER FIX)

Fetches ACTUAL historical prices based on alert timestamps:
- 2-min price: Price from exactly 2 minutes after alert
- 10-min price: Price from exactly 10 minutes after alert

Uses Kite historical data API with 1-minute candles.

Usage:
    python3 update_alert_prices_v2.py [--2min] [--10min] [--both]
"""

import sys
import logging
import argparse
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from kiteconnect import KiteConnect
import config
from alert_excel_logger import AlertExcelLogger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/alert_excel_updates.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AlertPriceUpdaterV2:
    """Updates historical prices for logged alerts using Kite historical data API."""

    def __init__(self):
        """Initialize Kite connection and Excel logger."""
        # Initialize Kite Connect
        if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
            raise ValueError("Kite Connect requires KITE_API_KEY and KITE_ACCESS_TOKEN in .env file")

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
        logger.info("Kite Connect initialized successfully")

        # Initialize Excel logger
        self.excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
        logger.info(f"Excel logger initialized: {config.ALERT_EXCEL_PATH}")

        # Cache for instrument tokens
        self.instrument_tokens = {}
        self._load_instrument_tokens()

    def _load_instrument_tokens(self):
        """Load and cache NSE instrument tokens for symbol lookup."""
        try:
            logger.info("Loading NSE instrument tokens...")
            instruments = self.kite.instruments("NSE")

            for instrument in instruments:
                symbol = instrument['tradingsymbol']
                token = instrument['instrument_token']
                self.instrument_tokens[symbol] = token

            logger.info(f"Loaded {len(self.instrument_tokens)} instrument tokens")

        except Exception as e:
            logger.error(f"Error loading instrument tokens: {e}")
            raise

    def update_2min_prices(self) -> int:
        """
        Update Price_2min column for alerts that are at least 2 minutes old.
        Fetches HISTORICAL price from exactly 2 minutes after the alert.

        Returns:
            Number of alerts updated
        """
        logger.info("=" * 60)
        logger.info("Starting 2-minute HISTORICAL price updates...")

        # Get pending updates (alerts at least 2 minutes old)
        pending = self.excel_logger.get_pending_updates(min_age_minutes=2)

        if not pending:
            logger.info("No alerts found that need 2-min price updates")
            return 0

        # Filter alerts that don't have Price_2min filled yet
        alerts_to_update = []

        for sheet_name, alerts in pending.items():
            ws = self.excel_logger.workbook[sheet_name]

            for alert in alerts:
                row_num = alert['row_num']
                price_2min = ws.cell(row=row_num, column=14).value  # Column N

                # Only update if Price_2min is empty
                if not price_2min:
                    alerts_to_update.append({
                        'sheet_name': sheet_name,
                        'row_num': row_num,
                        'symbol': alert['symbol'],
                        'row_id': alert['row_id'],
                        'date': alert['date'],
                        'time': alert['time']
                    })

        if not alerts_to_update:
            logger.info("All eligible alerts already have 2-min prices")
            return 0

        logger.info(f"Found {len(alerts_to_update)} alerts needing 2-min price updates")

        # Fetch historical prices for each alert
        updates = []
        for alert in alerts_to_update:
            symbol = alert['symbol'].replace('.NS', '')
            alert_datetime = datetime.strptime(f"{alert['date']} {alert['time']}", "%Y-%m-%d %H:%M:%S")
            target_time = alert_datetime + timedelta(minutes=2)

            # Fetch price at target time
            price = self._fetch_price_at_time(symbol, target_time)

            if price:
                updates.append({
                    'row_id': alert['row_id'],
                    'sheet_name': alert['sheet_name'],
                    'price': price
                })
                logger.info(f"  {symbol} @ {target_time.strftime('%H:%M:%S')}: ₹{price:.2f}")
            else:
                logger.warning(f"  {symbol}: No price data at {target_time.strftime('%H:%M:%S')}")

            # Rate limiting
            time.sleep(0.1)

        # Update Excel
        if updates:
            updated_count = self.excel_logger.update_prices(updates, price_column="2min")
            logger.info(f"✓ Updated {updated_count} alerts with 2-min HISTORICAL prices")
            return updated_count
        else:
            logger.warning("No prices fetched, nothing to update")
            return 0

    def update_10min_prices(self) -> int:
        """
        Update Price_10min column for alerts that are at least 10 minutes old.
        Fetches HISTORICAL price from exactly 10 minutes after the alert.

        Returns:
            Number of alerts updated
        """
        logger.info("=" * 60)
        logger.info("Starting 10-minute HISTORICAL price updates...")

        # Get pending updates (alerts at least 10 minutes old)
        pending = self.excel_logger.get_pending_updates(min_age_minutes=10)

        if not pending:
            logger.info("No alerts found that need 10-min price updates")
            return 0

        # Filter alerts that don't have Price_10min filled yet
        alerts_to_update = []

        for sheet_name, alerts in pending.items():
            ws = self.excel_logger.workbook[sheet_name]

            for alert in alerts:
                row_num = alert['row_num']
                price_10min = ws.cell(row=row_num, column=15).value  # Column O

                # Only update if Price_10min is empty
                if not price_10min:
                    alerts_to_update.append({
                        'sheet_name': sheet_name,
                        'row_num': row_num,
                        'symbol': alert['symbol'],
                        'row_id': alert['row_id'],
                        'date': alert['date'],
                        'time': alert['time']
                    })

        if not alerts_to_update:
            logger.info("All eligible alerts already have 10-min prices")
            return 0

        logger.info(f"Found {len(alerts_to_update)} alerts needing 10-min price updates")

        # Fetch historical prices for each alert
        updates = []
        for alert in alerts_to_update:
            symbol = alert['symbol'].replace('.NS', '')
            alert_datetime = datetime.strptime(f"{alert['date']} {alert['time']}", "%Y-%m-%d %H:%M:%S")
            target_time = alert_datetime + timedelta(minutes=10)

            # Fetch price at target time
            price = self._fetch_price_at_time(symbol, target_time)

            if price:
                updates.append({
                    'row_id': alert['row_id'],
                    'sheet_name': alert['sheet_name'],
                    'price': price
                })
                logger.info(f"  {symbol} @ {target_time.strftime('%H:%M:%S')}: ₹{price:.2f}")
            else:
                logger.warning(f"  {symbol}: No price data at {target_time.strftime('%H:%M:%S')}")

            # Rate limiting
            time.sleep(0.1)

        # Update Excel
        if updates:
            updated_count = self.excel_logger.update_prices(updates, price_column="10min")
            logger.info(f"✓ Updated {updated_count} alerts with 10-min HISTORICAL prices")
            return updated_count
        else:
            logger.warning("No prices fetched, nothing to update")
            return 0

    def _fetch_price_at_time(self, symbol: str, target_datetime: datetime) -> Optional[float]:
        """
        Fetch historical price at a specific datetime using 1-minute candles.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")
            target_datetime: The datetime to fetch price for

        Returns:
            Close price of the 1-minute candle at that time, or None if unavailable
        """
        try:
            # Get instrument token
            if symbol not in self.instrument_tokens:
                logger.error(f"Instrument token not found for {symbol}")
                return None

            instrument_token = self.instrument_tokens[symbol]

            # Fetch 1-minute candles for a window around the target time
            # Get 15 minutes of data to ensure we capture the target candle
            from_datetime = target_datetime - timedelta(minutes=5)
            to_datetime = target_datetime + timedelta(minutes=5)

            # Fetch historical data
            try:
                candles = self.kite.historical_data(
                    instrument_token=instrument_token,
                    from_date=from_datetime,
                    to_date=to_datetime,
                    interval="minute"  # 1-minute candles
                )

                if not candles:
                    logger.warning(f"{symbol}: No candle data returned")
                    return None

                # Find the candle closest to our target time
                closest_candle = None
                min_time_diff = float('inf')

                for candle in candles:
                    candle_time = candle['date']
                    # Remove timezone info for comparison
                    if candle_time.tzinfo:
                        candle_time = candle_time.replace(tzinfo=None)

                    time_diff = abs((candle_time - target_datetime).total_seconds())

                    if time_diff < min_time_diff:
                        min_time_diff = time_diff
                        closest_candle = candle

                if closest_candle:
                    # Use close price of the closest candle
                    price = closest_candle['close']
                    candle_time = closest_candle['date']
                    if candle_time.tzinfo:
                        candle_time = candle_time.replace(tzinfo=None)

                    time_diff_minutes = min_time_diff / 60
                    if time_diff_minutes > 5:
                        logger.warning(f"{symbol}: Closest candle is {time_diff_minutes:.1f} mins away")

                    return price
                else:
                    logger.warning(f"{symbol}: No suitable candle found")
                    return None

            except Exception as e:
                logger.error(f"Error fetching historical data for {symbol}: {e}")
                return None

        except Exception as e:
            logger.error(f"Error in _fetch_price_at_time for {symbol}: {e}")
            return None

    def close(self):
        """Close resources."""
        if self.excel_logger:
            self.excel_logger.close()


def main():
    """Main entry point for alert price updater."""
    parser = argparse.ArgumentParser(
        description="Update 2-min and 10-min HISTORICAL prices for pending alerts"
    )
    parser.add_argument(
        '--2min',
        action='store_true',
        dest='update_2min',
        help='Update only 2-minute prices'
    )
    parser.add_argument(
        '--10min',
        action='store_true',
        dest='update_10min',
        help='Update only 10-minute prices'
    )
    parser.add_argument(
        '--both',
        action='store_true',
        help='Update both 2-min and 10-min prices (default)'
    )

    args = parser.parse_args()

    # Default to both if no specific option provided
    if not (args.update_2min or args.update_10min or args.both):
        args.both = True

    try:
        updater = AlertPriceUpdaterV2()

        total_updated = 0

        # Update 2-min prices
        if args.update_2min or args.both:
            count = updater.update_2min_prices()
            total_updated += count

        # Update 10-min prices
        if args.update_10min or args.both:
            count = updater.update_10min_prices()
            total_updated += count

        logger.info("=" * 60)
        logger.info(f"SUMMARY: Total alerts updated: {total_updated}")
        logger.info("=" * 60)

        updater.close()

        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
