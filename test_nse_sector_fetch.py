#!/usr/bin/env python3
"""
Test NSE sector fetching with a few stocks
"""

import sys
sys.path.insert(0, '.')

from fetch_nse_sectors import NSESectorFetcher
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_nse_fetch():
    """Test fetching sector data for sample stocks"""

    # Test with diverse stock types
    test_stocks = [
        'RELIANCE',      # Energy
        'TCS',           # IT
        'HDFCBANK',      # Banking
        'SOLARINDS',     # Defense (explosives)
        'BEL',           # Defense (electronics)
        'SUNPHARMA',     # Pharma
        'TATAMOTORS',    # Auto
    ]

    logger.info("Testing NSE Sector Fetch")
    logger.info("="*80)

    fetcher = NSESectorFetcher()

    results = []
    for symbol in test_stocks:
        logger.info(f"\nFetching: {symbol}")
        info = fetcher.fetch_stock_info(symbol)

        if info:
            logger.info(f"  Company: {info['company_name']}")
            logger.info(f"  NSE Sector: {info['sector']}")
            logger.info(f"  Industry: {info['industry']}")
            logger.info(f"  Normalized: {fetcher._normalize_sector(info['sector'], info['industry'])}")
            results.append(info)
        else:
            logger.error(f"  ✗ Failed to fetch {symbol}")

        import time
        time.sleep(2)  # Rate limiting

    logger.info("\n" + "="*80)
    logger.info("Test Summary:")
    logger.info(f"  Successful: {len(results)}/{len(test_stocks)}")

    if len(results) == len(test_stocks):
        logger.info("\n✓ NSE API is working correctly!")
        logger.info("You can now run: ./venv/bin/python3 fetch_nse_sectors.py")
    else:
        logger.warning("\n⚠ Some fetches failed. Check NSE API availability.")

    return len(results) == len(test_stocks)

if __name__ == "__main__":
    success = test_nse_fetch()
    sys.exit(0 if success else 1)
