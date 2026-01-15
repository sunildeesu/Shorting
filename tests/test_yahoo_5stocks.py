#!/usr/bin/env python3
"""Test Yahoo Finance with 5 stocks to verify rate limiting"""

import sys
import logging
from stock_monitor import StockMonitor
import config

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

def main():
    logger.info("=" * 60)
    logger.info("Testing Yahoo Finance with 5 stocks")
    logger.info("=" * 60)
    logger.info(f"Demo Mode: {config.DEMO_MODE}")
    logger.info(f"Data Source: {config.DATA_SOURCE}")
    logger.info(f"Rate Limit: {config.REQUEST_DELAY_SECONDS}s between requests")
    logger.info(f"Max Retries: {config.MAX_RETRIES}")

    if config.DATA_SOURCE != 'yahoo':
        logger.error("ERROR: DATA_SOURCE is not set to 'yahoo'")
        logger.error("Please edit .env and set DATA_SOURCE=yahoo")
        return 1

    # Create monitor
    monitor = StockMonitor()

    # Test with just first 5 stocks
    original_stocks = monitor.stocks.copy()
    monitor.stocks = original_stocks[:5]

    logger.info(f"\nTesting with {len(monitor.stocks)} stocks:")
    for stock in monitor.stocks:
        logger.info(f"  - {stock}")
    logger.info("")

    # Fetch prices
    prices = monitor.fetch_all_prices_batch()

    logger.info("\n" + "=" * 60)
    logger.info("Results:")
    logger.info("=" * 60)

    if prices:
        logger.info(f"✅ Successfully fetched {len(prices)}/{len(monitor.stocks)} prices:")
        for symbol, price in prices.items():
            logger.info(f"  {symbol}: ₹{price:.2f}")
    else:
        logger.error("❌ Failed to fetch any prices")
        logger.error("\nPossible issues:")
        logger.error("  1. Yahoo Finance is blocked/rate limited")
        logger.error("  2. Network connectivity issue")
        logger.error("  3. Try using a VPN")
        logger.error("  4. Switch to DEMO_MODE=true for testing")

    logger.info("=" * 60)

    return 0 if prices else 1

if __name__ == "__main__":
    sys.exit(main())
