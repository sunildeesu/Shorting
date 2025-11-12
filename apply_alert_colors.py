#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Format Alert Tracking Excel (Sort + Color)

This script applies formatting to the alert tracking Excel file:
1. Sorts all alerts by date and time (oldest to newest)
2. Applies gradient color coding to price columns:
   - Green: Price moved in the predicted direction (good)
   - Red: Price moved against the prediction (bad)
   - Color intensity based on percentage change

For DROP alerts:
- Green if price dropped further than 2min reference
- Red if price rose from 2min reference

For RISE alerts:
- Green if price rose further than 2min reference
- Red if price dropped from 2min reference
"""

import sys
import logging
from alert_excel_logger import AlertExcelLogger
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Apply color formatting and sorting to all existing alert data."""
    try:
        logger.info("=" * 80)
        logger.info("APPLYING FORMATTING TO ALERT TRACKING")
        logger.info("=" * 80)
        logger.info(f"\nExcel File: {config.ALERT_EXCEL_PATH}")

        # Initialize Excel logger
        excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)

        # Fix incorrect directions
        logger.info("\nFixing incorrect direction labels...")
        fixed_count = excel_logger.fix_all_directions()
        logger.info(f"✓ Fixed {fixed_count} directions")

        # Sort alerts by date and time
        logger.info("\nSorting alerts by date and time...")
        sorted_count = excel_logger.sort_all_sheets_by_date()
        logger.info(f"✓ Sorted {sorted_count} sheets")

        # Apply color formatting
        logger.info("\nApplying color formatting to all price data...")
        colored_count = excel_logger.apply_color_formatting_to_all()
        logger.info(f"✓ Colored {colored_count} cells")

        # Close
        excel_logger.close()

        logger.info("\n" + "=" * 80)
        logger.info(f"✅ Formatting complete!")
        logger.info(f"   - Fixed {fixed_count} incorrect directions")
        logger.info(f"   - Sorted {sorted_count} sheets by date/time")
        logger.info(f"   - Colored {colored_count} cells")
        logger.info("=" * 80)
        logger.info(f"\n📊 View results: open {config.ALERT_EXCEL_PATH}")
        logger.info("\nColor Legend:")
        logger.info("  🟢 Green: Price moved in predicted direction (good prediction)")
        logger.info("  🔴 Red: Price reversed direction (failed prediction)")
        logger.info("  Darker shade = Larger price movement")

        return 0

    except Exception as e:
        logger.error(f"Failed to apply formatting: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
