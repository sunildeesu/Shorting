#!/usr/bin/env python3
"""Test NSEpy with a small subset of stocks to verify connectivity"""

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
    logger.info("Testing NSEpy with small stock subset")
    logger.info("=" * 60)
    logger.info(f"Demo Mode: {config.DEMO_MODE}")
    logger.info(f"Rate Limit: {config.REQUEST_DELAY_SECONDS}s between requests")
    logger.info(f"Max Retries: {config.MAX_RETRIES}")

    # Create monitor
    monitor = StockMonitor()

    # Test with just first 5 stocks
    original_stocks = monitor.stocks.copy()
    monitor.stocks = original_stocks[:5]

    logger.info(f"\nTesting with {len(monitor.stocks)} stocks: {', '.join(monitor.stocks)}\n")

    # Fetch prices
    prices = monitor.fetch_all_prices_batch()

    logger.info("\n" + "=" * 60)
    logger.info("Results:")
    logger.info("=" * 60)

    if prices:
        logger.info(f"Successfully fetched {len(prices)} prices:")
        for symbol, price in prices.items():
            logger.info(f"  {symbol}: ₹{price:.2f}")
    else:
        logger.error("Failed to fetch any prices - check network/SSL connectivity")
        logger.error("You may need to:")
        logger.error("  1. Use a VPN")
        logger.error("  2. Check firewall settings")
        logger.error("  3. Enable DEMO_MODE=true in .env for testing")

    logger.info("=" * 60)

    return 0 if prices else 1

if __name__ == "__main__":
    sys.exit(main())
