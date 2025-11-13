#!/usr/bin/env python3
"""
Update EOD (End-of-Day) Prices Script V2 (PROPER FIX)

Fetches ACTUAL historical closing prices for the date of the alert.
Uses Kite historical data API to get the day's closing price, not current price.

Usage:
    python3 update_eod_prices_v2.py [--date YYYY-MM-DD]

Examples:
    python3 update_eod_prices_v2.py              # Update today's alerts
    python3 update_eod_prices_v2.py --date 2025-11-08  # Update specific date
"""

import sys
import logging
import argparse
import time
from datetime import datetime, date, timedelta
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


class EODPriceUpdaterV2:
    """Updates end-of-day HISTORICAL closing prices for logged alerts."""

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

    def update_eod_prices(self, target_date: str = None) -> int:
        """
        Update EOD prices for all alerts from a specific date.
        Fetches the ACTUAL closing price for that trading day.

        Args:
            target_date: Date string in YYYY-MM-DD format (defaults to today)

        Returns:
            Number of alerts updated
        """
        if target_date is None:
            target_date = date.today().strftime("%Y-%m-%d")

        logger.info("=" * 60)
        logger.info(f"Starting EOD HISTORICAL price updates for {target_date}...")

        # Get all pending updates (no age filter)
        pending = self.excel_logger.get_pending_updates(min_age_minutes=0)

        if not pending:
            logger.info(f"No alerts found for {target_date}")
            return 0

        # Filter alerts from target date that don't have Price_EOD filled yet
        alerts_to_update = []

        for sheet_name, alerts in pending.items():
            ws = self.excel_logger.workbook[sheet_name]

            for alert in alerts:
                # Check if alert is from target date
                if alert['date'] != target_date:
                    continue

                row_num = alert['row_num']
                price_eod = ws.cell(row=row_num, column=16).value  # Column P

                # Only update if Price_EOD is empty
                if not price_eod:
                    alerts_to_update.append({
                        'sheet_name': sheet_name,
                        'row_num': row_num,
                        'symbol': alert['symbol'],
                        'row_id': alert['row_id'],
                        'date': alert['date'],
                        'time': alert['time']
                    })

        if not alerts_to_update:
            logger.info(f"All alerts from {target_date} already have EOD prices")
            return 0

        logger.info(f"Found {len(alerts_to_update)} alerts from {target_date} needing EOD prices")

        # Group by symbol to minimize API calls
        symbols_needed = set(alert['symbol'].replace('.NS', '') for alert in alerts_to_update)
        logger.info(f"Fetching EOD prices for {len(symbols_needed)} unique stocks")

        # Fetch EOD prices for all symbols
        eod_prices = self._fetch_eod_prices_batch(list(symbols_needed), target_date)

        if not eod_prices:
            logger.error("Failed to fetch any EOD prices")
            return 0

        # Prepare updates
        updates = []
        for alert in alerts_to_update:
            symbol = alert['symbol'].replace('.NS', '')

            if symbol in eod_prices:
                updates.append({
                    'row_id': alert['row_id'],
                    'sheet_name': alert['sheet_name'],
                    'price': eod_prices[symbol]
                })
                logger.info(f"  {symbol}: ₹{eod_prices[symbol]:.2f}")
            else:
                logger.warning(f"EOD price not available for {symbol}")

        # Update Excel (auto-complete status when EOD is filled)
        if updates:
            updated_count = self.excel_logger.update_prices(
                updates,
                price_column="EOD",
                auto_complete_eod=True  # Mark as Complete when EOD is filled
            )
            logger.info(f"✓ Updated {updated_count} alerts with EOD HISTORICAL prices")
            logger.info(f"✓ Marked {updated_count} alerts as 'Complete'")
            return updated_count
        else:
            logger.warning("No prices fetched, nothing to update")
            return 0

    def _fetch_eod_prices_batch(self, symbols: List[str], target_date: str) -> Dict[str, float]:
        """
        Fetch end-of-day closing prices for multiple symbols for a specific date.
        Uses historical data API to get the actual closing price.

        Args:
            symbols: List of stock symbols (without .NS suffix)
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dict mapping symbol to EOD closing price
        """
        if not symbols:
            return {}

        eod_prices = {}
        target_datetime = datetime.strptime(target_date, "%Y-%m-%d")

        # Fetch EOD price for each symbol
        for symbol in symbols:
            try:
                # Get instrument token
                if symbol not in self.instrument_tokens:
                    logger.warning(f"Instrument token not found for {symbol}")
                    continue

                instrument_token = self.instrument_tokens[symbol]

                # Fetch daily candle for the target date
                # Request a 3-day window to ensure we get the date even if it's a holiday
                from_date = target_datetime - timedelta(days=1)
                to_date = target_datetime + timedelta(days=1)

                try:
                    candles = self.kite.historical_data(
                        instrument_token=instrument_token,
                        from_date=from_date,
                        to_date=to_date,
                        interval="day"  # Daily candles
                    )

                    if not candles:
                        logger.warning(f"{symbol}: No EOD candle data returned")
                        continue

                    # Find the candle for the target date
                    for candle in candles:
                        candle_date = candle['date']
                        # Remove timezone info
                        if candle_date.tzinfo:
                            candle_date = candle_date.replace(tzinfo=None)

                        # Check if this is the target date (compare dates only)
                        if candle_date.date() == target_datetime.date():
                            # Use the closing price
                            eod_prices[symbol] = candle['close']
                            break

                    if symbol not in eod_prices:
                        logger.warning(f"{symbol}: No candle found for {target_date}")

                except Exception as e:
                    logger.error(f"Error fetching EOD data for {symbol}: {e}")

                # Rate limiting
                time.sleep(0.1)

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")

        return eod_prices

    def close(self):
        """Close resources."""
        if self.excel_logger:
            self.excel_logger.close()


def main():
    """Main entry point for EOD price updater."""
    parser = argparse.ArgumentParser(
        description="Update EOD HISTORICAL prices for today's alerts"
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Target date in YYYY-MM-DD format (default: today)',
        default=None
    )

    args = parser.parse_args()

    # Validate date format if provided
    target_date = args.date
    if target_date:
        try:
            datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            logger.error(f"Invalid date format: {target_date}. Use YYYY-MM-DD")
            return 1

    try:
        updater = EODPriceUpdaterV2()

        # Update EOD prices
        updated_count = updater.update_eod_prices(target_date)

        logger.info("=" * 60)
        logger.info(f"SUMMARY: Updated {updated_count} alerts with EOD HISTORICAL prices")
        logger.info("=" * 60)

        updater.close()

        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
