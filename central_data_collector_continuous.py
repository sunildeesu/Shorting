#!/usr/bin/env python3
"""
Central Data Collector - CONTINUOUS MODE
Runs from 9:15 AM to 3:30 PM with internal 1-minute loop

Efficiency:
- Starts ONCE at 9:14 AM via launchd
- Runs continuous loop during market hours
- Exits cleanly after 3:30 PM
- Zero checks outside market hours

Author: Claude Sonnet 4.5
Date: 2026-01-19
"""

import time
import logging
from datetime import datetime, time as dt_time
from central_data_collector import CentralDataCollector
from market_utils import is_market_open, get_market_status
from central_quote_db import get_central_db
from alert_history_manager import AlertHistoryManager
from telegram_notifier import TelegramNotifier
from rapid_drop_detector import RapidAlertDetector
from early_warning_detector import EarlyWarningDetector
import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/central_collector.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def is_within_market_hours() -> bool:
    """Check if current time is between 9:15 AM and 3:30 PM"""
    now = datetime.now().time()
    market_start = dt_time(9, 15)
    market_end = dt_time(15, 30)
    return market_start <= now <= market_end


def wait_for_market_open():
    """Wait until market opens (9:15 AM)"""
    while True:
        now = datetime.now().time()
        market_start = dt_time(9, 15)

        if now >= market_start:
            logger.info("✅ Market is open - starting collection")
            break

        wait_seconds = ((market_start.hour - now.hour) * 3600 +
                       (market_start.minute - now.minute) * 60 +
                       (market_start.second - now.second))

        if wait_seconds > 0:
            logger.info(f"⏳ Waiting {wait_seconds}s for market to open at 9:15 AM...")
            time.sleep(min(wait_seconds, 30))  # Check every 30s max


def main():
    """Main continuous collection loop"""

    logger.info("=" * 80)
    logger.info("CENTRAL DATA COLLECTOR - CONTINUOUS MODE")
    logger.info("=" * 80)

    # Check if trading day
    status = get_market_status()
    if not status['is_trading_day']:
        logger.info("❌ Not a trading day (weekend/holiday) - exiting")
        return

    logger.info("✅ Trading day confirmed")

    # Wait for market open if we're early
    now = datetime.now().time()
    if now < dt_time(9, 15):
        logger.info("⏳ Started before market open - waiting...")
        wait_for_market_open()

    # Initialize collector ONCE
    try:
        logger.info("Initializing central data collector...")
        collector = CentralDataCollector()
        logger.info("✅ Collector initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize collector: {e}", exc_info=True)
        return

    # Initialize rapid alert detector (error-isolated - collection continues if this fails)
    rapid_detector = None
    early_warning = None
    try:
        logger.info("Initializing alert detectors...")
        alert_history = AlertHistoryManager()
        telegram = TelegramNotifier()
        detection_db = get_central_db(mode="reader")

        # 5-minute alert detector
        rapid_detector = RapidAlertDetector(detection_db, alert_history, telegram)
        logger.info("✅ Rapid alert detector initialized (5-min drop + rise alerts)")

        # Early warning detector (pre-alerts)
        if config.ENABLE_EARLY_WARNING:
            early_warning = EarlyWarningDetector(detection_db, alert_history, telegram)
            logger.info("✅ Early warning detector initialized (pre-alerts enabled)")
        else:
            logger.info("ℹ️ Early warning detector disabled in config")

    except Exception as e:
        logger.error(f"⚠️ Detector init failed (collection will continue): {e}")
        rapid_detector = None
        early_warning = None

    # Continuous collection loop
    cycle_count = 0
    total_stocks_collected = 0

    logger.info("=" * 80)
    logger.info("🚀 Starting continuous collection loop")
    logger.info("📊 Market hours: 9:15 AM - 3:30 PM")
    logger.info("⏱️  Collection interval: Every 60 seconds")
    logger.info("=" * 80)

    while True:
        try:
            # Check if still within market hours
            if not is_within_market_hours():
                logger.info("=" * 80)
                logger.info("🏁 Market hours ended (3:30 PM) - exiting")
                logger.info(f"📊 Total cycles completed: {cycle_count}")
                logger.info(f"📈 Total stock records collected: {total_stocks_collected}")
                logger.info("=" * 80)
                break

            cycle_count += 1
            logger.info(f"\n{'=' * 80}")
            logger.info(f"CYCLE #{cycle_count} - {datetime.now().strftime('%H:%M:%S')}")
            logger.info(f"{'=' * 80}")

            # Run collection cycle
            stats = collector.collect_and_store()
            total_stocks_collected += stats['stocks_fetched']

            # Run detection immediately after collection
            # (error-isolated - collection continues if detection fails)
            if stats.get('stocks_stored', stats.get('stocks_fetched', 0)) > 0:
                stock_quotes = stats.get('stock_quotes', {})
                if stock_quotes:
                    # Early warning detection (pre-alerts for 5-min moves)
                    if early_warning:
                        try:
                            ew_stats = early_warning.detect_all(stock_quotes)
                            if ew_stats['prealerts_sent'] > 0:
                                logger.info(f"⚠️ Early warning: {ew_stats['prealerts_sent']} pre-alerts sent")
                        except Exception as e:
                            logger.error(f"⚠️ Early warning failed: {e}")

                    # Rapid drop/rise detection (5-min alerts)
                    if rapid_detector:
                        try:
                            detection_stats = rapid_detector.detect_all(stock_quotes)
                            if detection_stats['alerts_sent'] > 0 or detection_stats.get('rise_alerts_sent', 0) > 0:
                                logger.info(f"🚨 Rapid detection: {detection_stats['alerts_sent']} drop, "
                                           f"{detection_stats.get('rise_alerts_sent', 0)} rise alerts")
                        except Exception as e:
                            logger.error(f"⚠️ Rapid detection failed: {e}")

            # Sleep until next minute
            # Sleep logic: If current time is 10:30:15, sleep until 10:31:00
            now = datetime.now()
            seconds_past_minute = now.second
            sleep_seconds = 60 - seconds_past_minute

            logger.info(f"⏸️  Sleeping {sleep_seconds}s until next collection...")
            time.sleep(sleep_seconds)

        except KeyboardInterrupt:
            logger.info("\n🛑 Interrupted by user - exiting gracefully")
            break
        except Exception as e:
            logger.error(f"❌ Cycle {cycle_count} error: {e}", exc_info=True)
            logger.info("⏸️  Waiting 60s before retry...")
            time.sleep(60)

    # Final summary
    logger.info("\n" + "=" * 80)
    logger.info("CENTRAL DATA COLLECTOR - Shutdown Complete")
    logger.info(f"Total cycles: {cycle_count}")
    logger.info(f"Total stock records: {total_stocks_collected}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
