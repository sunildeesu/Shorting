#!/usr/bin/env python3
"""Test Kite Connect integration with 5 stocks"""

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
    logger.info("Testing Kite Connect Integration")
    logger.info("=" * 60)

    # Verify configuration
    if config.DEMO_MODE:
        logger.error("ERROR: DEMO_MODE is enabled")
        logger.error("Please set DEMO_MODE=false in .env file")
        return 1

    if config.DATA_SOURCE != 'kite':
        logger.error(f"ERROR: DATA_SOURCE is set to '{config.DATA_SOURCE}'")
        logger.error("Please set DATA_SOURCE=kite in .env file")
        return 1

    if not config.KITE_API_KEY:
        logger.error("ERROR: KITE_API_KEY not found in .env file")
        logger.error("Please run: python3 generate_kite_token.py")
        return 1

    if not config.KITE_ACCESS_TOKEN:
        logger.error("ERROR: KITE_ACCESS_TOKEN not found in .env file")
        logger.error("Please run: python3 generate_kite_token.py")
        return 1

    logger.info(f"API Key: {config.KITE_API_KEY[:10]}...")
    logger.info(f"Access Token: {config.KITE_ACCESS_TOKEN[:20]}...")
    logger.info(f"Rate Limit: {config.REQUEST_DELAY_SECONDS}s between requests")
    logger.info(f"Max Retries: {config.MAX_RETRIES}")

    # Create monitor
    try:
        logger.info("\nInitializing Kite Connect...")
        monitor = StockMonitor()
    except ValueError as e:
        logger.error(f"\n❌ Initialization failed: {e}")
        return 1
    except Exception as e:
        logger.error(f"\n❌ Unexpected error: {e}")
        logger.error("Possible issues:")
        logger.error("  - Invalid API key")
        logger.error("  - Invalid or expired access token")
        logger.error("  - Network connectivity issue")
        return 1

    # Test with just first 5 stocks
    original_stocks = monitor.stocks.copy()
    monitor.stocks = original_stocks[:5]

    logger.info(f"\n✅ Kite Connect initialized successfully!")
    logger.info(f"\nTesting with {len(monitor.stocks)} stocks:")
    for stock in monitor.stocks:
        logger.info(f"  - {stock}")
    logger.info("")

    # Fetch prices
    try:
        prices = monitor.fetch_all_prices_batch()
    except Exception as e:
        logger.error(f"\n❌ Error fetching prices: {e}")
        logger.error("\nPossible issues:")
        logger.error("  - Access token expired (valid for 24 hours)")
        logger.error("  - Rate limit exceeded")
        logger.error("  - Network issue")
        logger.error("\nSolution: Run 'python3 generate_kite_token.py' to refresh token")
        return 1

    logger.info("\n" + "=" * 60)
    logger.info("Results:")
    logger.info("=" * 60)

    if prices:
        logger.info(f"✅ Successfully fetched {len(prices)}/{len(monitor.stocks)} prices:")
        for symbol, price in prices.items():
            logger.info(f"  {symbol}: ₹{price:.2f}")

        logger.info("\n" + "=" * 60)
        logger.info("🎉 SUCCESS! Kite Connect is working perfectly!")
        logger.info("=" * 60)
        logger.info("\nNext steps:")
        logger.info("  1. Run the full monitor: python3 main.py")
        logger.info("  2. Set up launchd for automation")
        logger.info("  3. Remember to refresh token daily before 9:30 AM")
        logger.info("=" * 60)
    else:
        logger.error("❌ Failed to fetch any prices")
        logger.error("\nPossible issues:")
        logger.error("  1. Market is closed (only works during trading hours)")
        logger.error("  2. Access token expired - run: python3 generate_kite_token.py")
        logger.error("  3. Network connectivity issue")
        logger.error("  4. Kite Connect subscription inactive")

    logger.info("=" * 60)

    return 0 if prices else 1

if __name__ == "__main__":
    sys.exit(main())
