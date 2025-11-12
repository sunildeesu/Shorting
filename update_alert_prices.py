#!/usr/bin/env python3
"""
Update Alert Prices Script

Fetches and updates 2-minute and 10-minute prices for pending alerts in the Excel tracking file.
Only fetches prices for stocks that have generated alerts (API efficient).

Usage:
    python3 update_alert_prices.py [--2min] [--10min] [--both]

Examples:
    python3 update_alert_prices.py --2min      # Update only 2-min prices
    python3 update_alert_prices.py --10min     # Update only 10-min prices
    python3 update_alert_prices.py --both      # Update both (default)
"""

import sys
import logging
import argparse
from datetime import datetime, timedelta
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


class AlertPriceUpdater:
    """Updates historical prices for logged alerts using Kite API."""

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

    def update_2min_prices(self) -> int:
        """
        Update Price_2min column for alerts that are at least 2 minutes old.

        Returns:
            Number of alerts updated
        """
        logger.info("=" * 60)
        logger.info("Starting 2-minute price updates...")

        # Get pending updates (alerts at least 2 minutes old)
        pending = self.excel_logger.get_pending_updates(min_age_minutes=2)

        if not pending:
            logger.info("No alerts found that need 2-min price updates")
            return 0

        # Filter alerts that don't have Price_2min filled yet
        alerts_to_update = []
        symbols_needed = set()

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
                    symbols_needed.add(alert['symbol'])

        if not alerts_to_update:
            logger.info("All eligible alerts already have 2-min prices")
            return 0

        logger.info(f"Found {len(alerts_to_update)} alerts needing 2-min price updates")
        logger.info(f"Fetching prices for {len(symbols_needed)} unique stocks")

        # Fetch current prices for all needed symbols
        prices = self._fetch_prices_batch(list(symbols_needed))

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
            else:
                logger.warning(f"Price not available for {symbol}")

        # Update Excel
        if updates:
            updated_count = self.excel_logger.update_prices(updates, price_column="2min")
            logger.info(f"✓ Updated {updated_count} alerts with 2-min prices")
            return updated_count
        else:
            logger.warning("No prices fetched, nothing to update")
            return 0

    def update_10min_prices(self) -> int:
        """
        Update Price_10min column for alerts that are at least 10 minutes old.

        Returns:
            Number of alerts updated
        """
        logger.info("=" * 60)
        logger.info("Starting 10-minute price updates...")

        # Get pending updates (alerts at least 10 minutes old)
        pending = self.excel_logger.get_pending_updates(min_age_minutes=10)

        if not pending:
            logger.info("No alerts found that need 10-min price updates")
            return 0

        # Filter alerts that don't have Price_10min filled yet
        alerts_to_update = []
        symbols_needed = set()

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
                    symbols_needed.add(alert['symbol'])

        if not alerts_to_update:
            logger.info("All eligible alerts already have 10-min prices")
            return 0

        logger.info(f"Found {len(alerts_to_update)} alerts needing 10-min price updates")
        logger.info(f"Fetching prices for {len(symbols_needed)} unique stocks")

        # Fetch current prices for all needed symbols
        prices = self._fetch_prices_batch(list(symbols_needed))

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
            else:
                logger.warning(f"Price not available for {symbol}")

        # Update Excel
        if updates:
            updated_count = self.excel_logger.update_prices(updates, price_column="10min")
            logger.info(f"✓ Updated {updated_count} alerts with 10-min prices")
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
    """Main entry point for alert price updater."""
    parser = argparse.ArgumentParser(
        description="Update 2-min and 10-min prices for pending alerts"
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
        updater = AlertPriceUpdater()

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
