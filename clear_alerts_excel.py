#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Clear Alert Tracking Excel

This script clears all alert data from the Excel file while preserving:
- Sheet structure
- Column headers
- Formatting

Useful for starting fresh with new backtest data.
"""

import sys
import logging
from alert_excel_logger import AlertExcelLogger
import config
import shutil
from datetime import datetime

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
    """Clear all alert data from Excel file."""
    try:
        logger.info("=" * 80)
        logger.info("CLEARING ALERT TRACKING EXCEL")
        logger.info("=" * 80)
        logger.info(f"\nExcel File: {config.ALERT_EXCEL_PATH}")

        # Create backup first
        backup_path = config.ALERT_EXCEL_PATH.replace('.xlsx', f'_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
        logger.info(f"\nCreating backup: {backup_path}")
        shutil.copy2(config.ALERT_EXCEL_PATH, backup_path)
        logger.info("✓ Backup created successfully")

        # Initialize Excel logger
        excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)

        # Count existing alerts
        total_alerts = 0
        for sheet_name in set(excel_logger.SHEET_NAMES.values()):
            ws = excel_logger.workbook[sheet_name]
            alert_count = ws.max_row - 1  # Subtract header row
            if alert_count > 0:
                total_alerts += alert_count
                logger.info(f"  {sheet_name}: {alert_count} alerts")

        logger.info(f"\nTotal alerts to clear: {total_alerts}")

        # Ask for confirmation
        response = input("\nAre you sure you want to clear all alerts? (yes/no): ").strip().lower()
        if response != 'yes':
            logger.info("Operation cancelled.")
            excel_logger.close()
            return 0

        # Clear all data rows (keep headers)
        cleared_count = 0
        for sheet_name in set(excel_logger.SHEET_NAMES.values()):
            ws = excel_logger.workbook[sheet_name]

            # Delete all rows except header (row 1)
            if ws.max_row > 1:
                ws.delete_rows(2, ws.max_row - 1)
                cleared_count += 1
                logger.info(f"✓ Cleared {sheet_name}")

        # Save the cleared workbook
        excel_logger._save_workbook()
        excel_logger.close()

        logger.info("\n" + "=" * 80)
        logger.info(f"✅ Successfully cleared {total_alerts} alerts from {cleared_count} sheets!")
        logger.info(f"📁 Backup saved: {backup_path}")
        logger.info("=" * 80)
        logger.info(f"\nExcel file is now empty and ready for new backtest data.")

        return 0

    except Exception as e:
        logger.error(f"Failed to clear Excel file: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
