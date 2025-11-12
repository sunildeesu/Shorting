#!/usr/bin/env python3
"""
Test Alert Tracking System

Tests the alert Excel logging system with historical alert data from Nov 7, 2025.
This simulates what would have been logged if the system was active.
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


def test_alert_logging():
    """Test logging historical alerts from Nov 7, 2025."""

    logger.info("=" * 60)
    logger.info("Testing Alert Excel Logging System")
    logger.info("=" * 60)

    # Initialize Excel logger
    excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
    logger.info(f"Excel logger initialized: {config.ALERT_EXCEL_PATH}")

    # Historical alert data from Nov 7, 2025 (PFC alerts)
    test_alerts = [
        {
            "symbol": "PFC",
            "alert_type": "5min",
            "timestamp": datetime(2025, 11, 7, 14, 50, 5),
            "current_price": 386.6,
            "previous_price": 391.5,  # Estimated 5min before
            "drop_percent": -1.25,
            "volume_data": {
                "current_volume": 6857525,
                "avg_volume": 5500000,
                "volume_spike": True
            },
            "market_cap_cr": None,
            "telegram_sent": True
        },
        {
            "symbol": "PFC",
            "alert_type": "30min",
            "timestamp": datetime(2025, 11, 7, 15, 15, 5),
            "current_price": 381.6,
            "previous_price": 386.6,  # 30min before (from previous6)
            "drop_percent": -1.29,
            "volume_data": {
                "current_volume": 11631319,
                "avg_volume": 8500000,
                "volume_spike": False
            },
            "market_cap_cr": None,
            "telegram_sent": True
        },
        {
            "symbol": "RELIANCE",
            "alert_type": "10min",
            "timestamp": datetime(2025, 11, 7, 15, 10, 6),
            "current_price": 1477.3,
            "previous_price": 1480.1,  # 10min before
            "drop_percent": -0.19,
            "volume_data": {
                "current_volume": 6897799,
                "avg_volume": 6400000,
                "volume_spike": False
            },
            "market_cap_cr": 999123.45,
            "telegram_sent": True
        },
        {
            "symbol": "TCS",
            "alert_type": "volume_spike",
            "timestamp": datetime(2025, 11, 7, 14, 55, 10),
            "current_price": 2990.0,
            "previous_price": 2995.0,
            "drop_percent": -0.17,
            "volume_data": {
                "current_volume": 1600000,
                "avg_volume": 500000,
                "volume_spike": True
            },
            "market_cap_cr": 1089234.56,
            "telegram_sent": True
        }
    ]

    # Log each test alert
    logger.info(f"\nLogging {len(test_alerts)} test alerts...")
    logger.info("-" * 60)

    for i, alert in enumerate(test_alerts, 1):
        logger.info(f"\nAlert {i}/{len(test_alerts)}:")
        logger.info(f"  Symbol: {alert['symbol']}")
        logger.info(f"  Type: {alert['alert_type']}")
        logger.info(f"  Time: {alert['timestamp']}")
        logger.info(f"  Price: ₹{alert['current_price']} (was ₹{alert['previous_price']})")
        logger.info(f"  Change: {alert['drop_percent']:.2f}%")

        success = excel_logger.log_alert(
            symbol=alert["symbol"],
            alert_type=alert["alert_type"],
            drop_percent=alert["drop_percent"],
            current_price=alert["current_price"],
            previous_price=alert["previous_price"],
            volume_data=alert["volume_data"],
            market_cap_cr=alert["market_cap_cr"],
            telegram_sent=alert["telegram_sent"],
            timestamp=alert["timestamp"]
        )

        if success:
            logger.info(f"  ✓ Logged successfully")
        else:
            logger.error(f"  ✗ Failed to log")

    logger.info("\n" + "=" * 60)
    logger.info("Alert Logging Complete")
    logger.info("=" * 60)

    # Show summary
    pending = excel_logger.get_pending_updates()
    total_pending = sum(len(alerts) for alerts in pending.values())

    logger.info(f"\nSummary:")
    logger.info(f"  Excel File: {config.ALERT_EXCEL_PATH}")
    logger.info(f"  Alerts Logged: {len(test_alerts)}")
    logger.info(f"  Pending Updates: {total_pending}")
    logger.info(f"\nSheets:")
    for sheet_name, alerts in pending.items():
        logger.info(f"  - {sheet_name}: {len(alerts)} alerts")

    # Close logger
    excel_logger.close()

    logger.info("\n" + "=" * 60)
    logger.info("Next Steps:")
    logger.info("=" * 60)
    logger.info("1. Open Excel file:")
    logger.info(f"   open {config.ALERT_EXCEL_PATH}")
    logger.info("\n2. Test price updates (2min/10min):")
    logger.info("   python3 update_alert_prices.py --both")
    logger.info("\n3. Test EOD price updates:")
    logger.info("   python3 update_eod_prices.py --date 2025-11-07")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        test_alert_logging()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)
