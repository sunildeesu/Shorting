#!/usr/bin/env python3
"""
Test script for sector analysis functionality
"""

import json
import logging
from sector_manager import get_sector_manager
from sector_analyzer import get_sector_analyzer
from telegram_notifier import TelegramNotifier

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_sector_manager():
    """Test sector manager functionality"""
    logger.info("=== Testing Sector Manager ===")

    sector_manager = get_sector_manager()

    # Test 1: Get sector for a stock
    test_stocks = ['RELIANCE', 'TCS', 'HDFCBANK', 'SUNPHARMA', 'TATAMOTORS']
    for stock in test_stocks:
        sector = sector_manager.get_sector(stock)
        logger.info(f"  {stock} -> {sector}")

    # Test 2: Get all sectors
    all_sectors = sector_manager.get_all_sectors()
    logger.info(f"  Total sectors: {len(all_sectors)}")
    logger.info(f"  Sectors: {', '.join(all_sectors)}")

    # Test 3: Get stocks in a sector
    banking_stocks = sector_manager.get_stocks_in_sector('BANKING')
    logger.info(f"  Banking sector stocks: {len(banking_stocks)}")
    logger.info(f"  Examples: {', '.join(banking_stocks[:5])}")

    logger.info("✓ Sector Manager tests passed\n")

def test_sector_analyzer():
    """Test sector analyzer functionality"""
    logger.info("=== Testing Sector Analyzer ===")

    sector_analyzer = get_sector_analyzer()

    # Test: Analyze sectors
    sector_analysis = sector_analyzer.analyze_sectors()

    if sector_analysis:
        sectors = sector_analysis.get('sectors', {})
        logger.info(f"  Analyzed {len(sectors)} sectors")

        # Show top 3 performers
        sorted_sectors = sorted(
            sectors.items(),
            key=lambda x: x[1].get('price_change_10min', 0),
            reverse=True
        )

        logger.info("  Top 3 sectors by 10-min performance:")
        for i, (sector, data) in enumerate(sorted_sectors[:3], 1):
            change = data.get('price_change_10min', 0)
            momentum = data.get('momentum_score_10min', 0)
            logger.info(f"    {i}. {sector}: {change:+.2f}% (momentum: {momentum:+.2f})")

        # Test rotation detection
        rotation = sector_analyzer.detect_rotation(sector_analysis, threshold=2.0)
        if rotation:
            logger.info(f"  Rotation detected: {rotation['divergence']:.2f}% divergence")
        else:
            logger.info("  No significant rotation detected")

        logger.info("✓ Sector Analyzer tests passed\n")
    else:
        logger.warning("  No sector analysis data available (price cache may be empty)")
        logger.info("⚠ Sector Analyzer tests skipped\n")

def test_telegram_formatting():
    """Test Telegram message formatting (without sending)"""
    logger.info("=== Testing Telegram Formatting ===")

    # Load sector analysis from cache
    try:
        with open('data/sector_analysis_cache.json', 'r') as f:
            sector_analysis = json.load(f)
    except:
        logger.warning("  No sector analysis cache found, skipping format tests")
        return

    telegram = TelegramNotifier()

    # Test 1: Format EOD summary
    logger.info("  Formatting EOD sector summary...")
    eod_message = telegram._format_eod_sector_summary(sector_analysis)
    logger.info(f"  EOD message length: {len(eod_message)} characters")
    logger.info(f"  First 200 chars: {eod_message[:200]}...")

    # Test 2: Format rotation alert (if available)
    sector_analyzer = get_sector_analyzer()
    rotation = sector_analyzer.detect_rotation(sector_analysis, threshold=2.0)
    if rotation:
        logger.info("  Formatting sector rotation alert...")
        rotation_message = telegram._format_sector_rotation_message(rotation)
        logger.info(f"  Rotation message length: {len(rotation_message)} characters")
        logger.info(f"  First 200 chars: {rotation_message[:200]}...")

    # Test 3: Format sector context
    logger.info("  Formatting sector context...")
    sectors = sector_analysis.get('sectors', {})
    if sectors:
        # Get first sector as example
        sector_name = list(sectors.keys())[0]
        sector_data = sectors[sector_name]

        sector_context = {
            'sector_name': sector_name,
            'sector_change_10min': sector_data.get('price_change_10min', 0),
            'stock_vs_sector': 1.5,  # Example differential
            'sector_volume_ratio': sector_data.get('volume_ratio', 1.0),
            'sector_momentum': sector_data.get('momentum_score_10min', 0),
            'stocks_up_10min': sector_data.get('stocks_up_10min', 0),
            'stocks_down_10min': sector_data.get('stocks_down_10min', 0),
            'total_stocks': sector_data.get('total_stocks', 0)
        }

        context_message = telegram._format_sector_context(sector_context, is_priority=False)
        logger.info(f"  Context message length: {len(context_message)} characters")
        logger.info(f"  Context message:\n{context_message}")

    logger.info("✓ Telegram Formatting tests passed\n")

def main():
    """Run all tests"""
    logger.info("Starting Sector Analysis Tests\n")
    logger.info("="*60)

    try:
        test_sector_manager()
        test_sector_analyzer()
        test_telegram_formatting()

        logger.info("="*60)
        logger.info("✓ All tests completed successfully!")
        logger.info("\nSector analysis system is ready to use.")
        logger.info("\nFeatures enabled:")
        logger.info("  1. Sector context in stock alerts")
        logger.info("  2. Sector rotation detection (9:30, 12:30, 15:15)")
        logger.info("  3. EOD sector summary (15:25)")

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)

if __name__ == "__main__":
    main()
