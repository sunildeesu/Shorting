#!/usr/bin/env python3
"""
Mock Price Update Test

Simulates price updates for the alert tracking system without requiring Kite API.
Uses mock current prices to demonstrate the update functionality.
"""

import sys
import logging
from datetime import datetime
from alert_excel_logger import AlertExcelLogger
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def mock_price_updates():
    """Test price update functionality with mock data."""

    logger.info("=" * 60)
    logger.info("Mock Price Update Test")
    logger.info("=" * 60)

    # Initialize Excel logger
    excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
    logger.info(f"Excel logger initialized: {config.ALERT_EXCEL_PATH}")

    # Get pending updates
    pending = excel_logger.get_pending_updates()

    if not pending:
        logger.error("No pending alerts found!")
        return

    logger.info(f"\nFound pending alerts in {len(pending)} sheets")

    # Mock current prices (simulating what Kite API would return)
    mock_prices = {
        "PFC": 382.5,      # Current price after the alerts
        "RELIANCE": 1478.0,
        "TCS": 2991.5
    }

    # Test 1: Update 2-minute prices
    logger.info("\n" + "=" * 60)
    logger.info("Test 1: Updating 2-minute prices")
    logger.info("=" * 60)

    updates_2min = []
    for sheet_name, alerts in pending.items():
        for alert in alerts:
            symbol = alert['symbol']
            if symbol in mock_prices:
                # Simulate price 2 minutes after alert (slightly different)
                price_2min = mock_prices[symbol] + 0.5
                updates_2min.append({
                    'row_id': alert['row_id'],
                    'sheet_name': sheet_name,
                    'price': price_2min
                })
                logger.info(f"  {symbol}: ₹{price_2min:.2f}")

    if updates_2min:
        count = excel_logger.update_prices(updates_2min, price_column="2min")
        logger.info(f"\n✓ Updated {count} alerts with 2-min prices")

    # Test 2: Update 10-minute prices
    logger.info("\n" + "=" * 60)
    logger.info("Test 2: Updating 10-minute prices")
    logger.info("=" * 60)

    updates_10min = []
    for sheet_name, alerts in pending.items():
        for alert in alerts:
            symbol = alert['symbol']
            if symbol in mock_prices:
                # Simulate price 10 minutes after alert
                price_10min = mock_prices[symbol] + 1.0
                updates_10min.append({
                    'row_id': alert['row_id'],
                    'sheet_name': sheet_name,
                    'price': price_10min
                })
                logger.info(f"  {symbol}: ₹{price_10min:.2f}")

    if updates_10min:
        count = excel_logger.update_prices(updates_10min, price_column="10min")
        logger.info(f"\n✓ Updated {count} alerts with 10-min prices")

    # Test 3: Update EOD prices
    logger.info("\n" + "=" * 60)
    logger.info("Test 3: Updating EOD prices")
    logger.info("=" * 60)

    # EOD prices for Nov 7, 2025 (from price_cache)
    eod_prices = {
        "PFC": 380.55,      # Actual from price_cache
        "RELIANCE": 1478.2, # Actual from price_cache
        "TCS": 2992.5       # Actual from price_cache
    }

    updates_eod = []
    for sheet_name, alerts in pending.items():
        for alert in alerts:
            symbol = alert['symbol']
            if symbol in eod_prices:
                updates_eod.append({
                    'row_id': alert['row_id'],
                    'sheet_name': sheet_name,
                    'price': eod_prices[symbol]
                })
                logger.info(f"  {symbol}: ₹{eod_prices[symbol]:.2f}")

    if updates_eod:
        count = excel_logger.update_prices(
            updates_eod,
            price_column="EOD",
            auto_complete_eod=True
        )
        logger.info(f"\n✓ Updated {count} alerts with EOD prices")
        logger.info(f"✓ Marked {count} alerts as 'Complete'")

    # Show final status
    logger.info("\n" + "=" * 60)
    logger.info("Final Status Check")
    logger.info("=" * 60)

    pending_after = excel_logger.get_pending_updates()
    complete_count = sum(len(alerts) for alerts in pending.values()) - sum(len(alerts) for alerts in pending_after.values())

    logger.info(f"\nAlerts Summary:")
    logger.info(f"  Total Alerts: {sum(len(alerts) for alerts in pending.values())}")
    logger.info(f"  Completed: {complete_count}")
    logger.info(f"  Still Pending: {sum(len(alerts) for alerts in pending_after.values())}")

    # Close logger
    excel_logger.close()

    logger.info("\n" + "=" * 60)
    logger.info("Test Complete!")
    logger.info("=" * 60)
    logger.info(f"\nOpen the Excel file to see all updates:")
    logger.info(f"  open {config.ALERT_EXCEL_PATH}")
    logger.info("\nExpected results:")
    logger.info("  - All 4 alerts should have Price 2min filled")
    logger.info("  - All 4 alerts should have Price 10min filled")
    logger.info("  - All 4 alerts should have Price EOD filled")
    logger.info("  - All 4 alerts should have Status = 'Complete'")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        mock_price_updates()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)
