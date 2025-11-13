#!/usr/bin/env python3
"""
Update EOD (End-of-Day) Prices Script

Fetches and updates end-of-day closing prices for today's alerts.
Designed to run automatically at market close (3:30 PM IST).

Usage:
    python3 update_eod_prices.py [--date YYYY-MM-DD]

Examples:
    python3 update_eod_prices.py              # Update today's alerts
    python3 update_eod_prices.py --date 2025-11-08  # Update specific date
"""

import sys
import logging
import argparse
from datetime import datetime, date
from typing import Dict, List, Set
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


class EODPriceUpdater:
    """Updates end-of-day prices for logged alerts using Kite API."""

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

    def update_eod_prices(self, target_date: str = None) -> int:
        """
        Update EOD prices for all alerts from a specific date.

        Args:
            target_date: Date string in YYYY-MM-DD format (defaults to today)

        Returns:
            Number of alerts updated
        """
        if target_date is None:
            target_date = date.today().strftime("%Y-%m-%d")

        logger.info("=" * 60)
        logger.info(f"Starting EOD price updates for {target_date}...")

        # Get all pending updates (no age filter)
        pending = self.excel_logger.get_pending_updates(min_age_minutes=0)

        if not pending:
            logger.info(f"No alerts found for {target_date}")
            return 0

        # Filter alerts from target date that don't have Price_EOD filled yet
        alerts_to_update = []
        symbols_needed = set()

        for sheet_name, alerts in pending.items():
            ws = self.excel_logger.workbook[sheet_name]

            # Determine column number based on sheet type (RSI columns added)
            if sheet_name == "ATR_Breakout_alerts":
                price_eod_col = 27  # Column AA (ATR sheet with RSI)
            else:
                price_eod_col = 24  # Column X (Standard sheets with RSI)

            for alert in alerts:
                # Check if alert is from target date
                if alert['date'] != target_date:
                    continue

                row_num = alert['row_num']
                price_eod = ws.cell(row=row_num, column=price_eod_col).value

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
                    symbols_needed.add(alert['symbol'])

        if not alerts_to_update:
            logger.info(f"All alerts from {target_date} already have EOD prices")
            return 0

        logger.info(f"Found {len(alerts_to_update)} alerts from {target_date} needing EOD prices")
        logger.info(f"Fetching prices for {len(symbols_needed)} unique stocks")

        # Fetch current prices for all needed symbols
        prices = self._fetch_prices_batch(list(symbols_needed))

        if not prices:
            logger.error("Failed to fetch any prices")
            return 0

        # Prepare updates
        updates = []
        for alert in alerts_to_update:
            symbol = alert['symbol']
            clean_symbol = symbol.replace('.NS', '')

            if clean_symbol in prices:
                updates.append({
                    'row_id': alert['row_id'],
                    'sheet_name': alert['sheet_name'],
                    'price': prices[clean_symbol]
                })
                logger.info(f"  {clean_symbol}: ₹{prices[clean_symbol]:.2f}")
            else:
                logger.warning(f"Price not available for {symbol}")

        # Update Excel (auto-complete status when EOD is filled)
        if updates:
            updated_count = self.excel_logger.update_prices(
                updates,
                price_column="EOD",
                auto_complete_eod=True  # Mark as Complete when EOD is filled
            )
            logger.info(f"✓ Updated {updated_count} alerts with EOD prices")
            logger.info(f"✓ Marked {updated_count} alerts as 'Complete'")
            return updated_count
        else:
            logger.warning("No prices fetched, nothing to update")
            return 0

    def _fetch_prices_batch(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch current prices for multiple symbols using batch API.

        Args:
            symbols: List of stock symbols (without .NS suffix)

        Returns:
            Dict mapping symbol to current price
        """
        if not symbols:
            return {}

        prices = {}

        try:
            # Convert to NSE instruments format
            instruments = [f"NSE:{symbol.replace('.NS', '')}" for symbol in symbols]

            # Batch fetch (Kite supports up to 500 instruments per call)
            batch_size = 50
            for i in range(0, len(instruments), batch_size):
                batch = instruments[i:i + batch_size]

                try:
                    quotes = self.kite.quote(*batch)

                    for instrument, data in quotes.items():
                        symbol = instrument.replace('NSE:', '')
                        # Use last_price (current LTP at EOD time)
                        prices[symbol] = data['last_price']

                    logger.info(f"Fetched {len(batch)} prices (batch {i // batch_size + 1})")

                except Exception as e:
                    logger.error(f"Error fetching batch {i // batch_size + 1}: {e}")

            return prices

        except Exception as e:
            logger.error(f"Error in batch price fetch: {e}")
            return {}

    def close(self):
        """Close resources."""
        if self.excel_logger:
            self.excel_logger.close()


def main():
    """Main entry point for EOD price updater."""
    parser = argparse.ArgumentParser(
        description="Update EOD prices for today's alerts"
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
        updater = EODPriceUpdater()

        # Update EOD prices
        updated_count = updater.update_eod_prices(target_date)

        logger.info("=" * 60)
        logger.info(f"SUMMARY: Updated {updated_count} alerts with EOD prices")
        logger.info("=" * 60)

        updater.close()

        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
