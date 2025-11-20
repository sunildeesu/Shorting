#!/usr/bin/env python3
"""
Test script for sector EOD report generation
"""

import json
import logging
from datetime import datetime
from sector_eod_report_generator import get_sector_eod_report_generator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_report_generation():
    """Test Excel report generation"""
    logger.info("=== Testing Sector EOD Report Generation ===\n")

    # Load sector analysis from cache
    try:
        with open('data/sector_analysis_cache.json', 'r') as f:
            sector_analysis = json.load(f)
        logger.info(f"✓ Loaded sector analysis cache")
        logger.info(f"  Sectors found: {len(sector_analysis.get('sectors', {}))}")
    except FileNotFoundError:
        logger.error("✗ Sector analysis cache not found")
        logger.error("  Run stock monitor first to generate sector analysis data")
        return False
    except Exception as e:
        logger.error(f"✗ Error loading sector analysis: {e}")
        return False

    # Generate report
    try:
        report_generator = get_sector_eod_report_generator()
        logger.info("\nGenerating Excel report...")

        report_path = report_generator.generate_report(sector_analysis)

        if report_path:
            logger.info(f"✓ Report generated successfully!")
            logger.info(f"  Location: {report_path}")

            # Show report details
            logger.info("\nReport Contents:")
            logger.info("  Sheet 1: Summary - Sector rankings and status")
            logger.info("  Sheet 2: Detailed Metrics - All timeframes and metrics")
            logger.info("  Sheet 3: Fund Flow - Market cap distribution and flow analysis")

            # Show sample data
            sectors = sector_analysis.get('sectors', {})
            sorted_sectors = sorted(
                sectors.items(),
                key=lambda x: x[1].get('price_change_10min', 0),
                reverse=True
            )

            logger.info("\nTop 3 Performing Sectors (in report):")
            for i, (sector, data) in enumerate(sorted_sectors[:3], 1):
                sector_name = sector.replace('_', ' ').title()
                change = data.get('price_change_10min', 0)
                market_cap = data.get('total_market_cap_cr', 0)
                logger.info(f"  {i}. {sector_name}: {change:+.2f}% (₹{market_cap:,.0f} Cr)")

            logger.info("\nBottom 3 Performing Sectors (in report):")
            for i, (sector, data) in enumerate(reversed(sorted_sectors[-3:]), 1):
                sector_name = sector.replace('_', ' ').title()
                change = data.get('price_change_10min', 0)
                market_cap = data.get('total_market_cap_cr', 0)
                logger.info(f"  {i}. {sector_name}: {change:+.2f}% (₹{market_cap:,.0f} Cr)")

            return True
        else:
            logger.error("✗ Report generation failed")
            return False

    except Exception as e:
        logger.error(f"✗ Error generating report: {e}", exc_info=True)
        return False

def main():
    """Run test"""
    logger.info("Sector EOD Report Test\n")
    logger.info("="*60)

    success = test_report_generation()

    logger.info("\n" + "="*60)
    if success:
        logger.info("✓ TEST PASSED - Report generation working!")
        logger.info("\nThe report will be automatically generated at 3:25 PM")
        logger.info("during stock monitoring sessions.")
    else:
        logger.info("✗ TEST FAILED - Check errors above")

if __name__ == "__main__":
    main()
