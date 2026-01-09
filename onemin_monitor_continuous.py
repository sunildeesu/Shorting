#!/usr/bin/env python3
"""
1-Minute Alert Monitor - CONTINUOUS MODE
Runs from 9:30 AM to 3:25 PM with internal 1-minute loop

Efficiency improvements:
- Starts ONCE at 9:29 AM via launchd
- Runs continuous loop during market hours
- Exits cleanly after 3:25 PM
- Zero checks outside market hours
"""

import time
import logging
from datetime import datetime, time as dt_time
from onemin_monitor import OneMinMonitor
from market_utils import is_market_open, get_market_status

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/onemin_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def is_within_market_hours() -> bool:
    """Check if current time is between 9:30 AM and 3:25 PM"""
    now = datetime.now().time()
    market_start = dt_time(9, 30)
    market_end = dt_time(15, 25)
    return market_start <= now <= market_end


def wait_for_market_open():
    """Wait until market opens (9:30 AM)"""
    while True:
        now = datetime.now().time()
        market_start = dt_time(9, 30)

        if now >= market_start:
            logger.info("✅ Market is open - starting monitoring")
            break

        wait_seconds = ((market_start.hour - now.hour) * 3600 +
                       (market_start.minute - now.minute) * 60 +
                       (market_start.second - now.second))

        if wait_seconds > 0:
            logger.info(f"⏳ Waiting {wait_seconds}s for market to open at 9:30 AM...")
            time.sleep(min(wait_seconds, 30))  # Check every 30s max


def main():
    """Main continuous monitoring loop"""

    logger.info("=" * 80)
    logger.info("1-MIN ALERT MONITOR - CONTINUOUS MODE")
    logger.info("=" * 80)

    # Check if trading day
    status = get_market_status()
    if not status['is_trading_day']:
        logger.info("❌ Not a trading day (weekend/holiday) - exiting")
        return

    logger.info("✅ Trading day confirmed")

    # Wait for market open if we're early
    now = datetime.now().time()
    if now < dt_time(9, 30):
        logger.info("⏳ Started before market open - waiting...")
        wait_for_market_open()

    # Initialize monitor ONCE
    try:
        logger.info("Initializing 1-min monitor...")
        monitor = OneMinMonitor()
        logger.info("✅ Monitor initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize monitor: {e}", exc_info=True)
        return

    # Continuous monitoring loop
    cycle_count = 0
    total_alerts = 0

    logger.info("=" * 80)
    logger.info("🚀 Starting continuous monitoring loop")
    logger.info("📊 Market hours: 9:30 AM - 3:25 PM")
    logger.info("⏱️  Check interval: Every 60 seconds")
    logger.info("=" * 80)

    while True:
        try:
            # Check if still within market hours
            if not is_within_market_hours():
                logger.info("=" * 80)
                logger.info(f"✅ Market closed (3:25 PM) - Exiting gracefully")
                logger.info(f"📊 Session Summary:")
                logger.info(f"   - Total cycles: {cycle_count}")
                logger.info(f"   - Total alerts: {total_alerts}")
                logger.info("=" * 80)
                break

            # Run one monitoring cycle
            cycle_count += 1
            logger.info(f"\n{'='*80}")
            logger.info(f"Cycle #{cycle_count} - {datetime.now().strftime('%H:%M:%S')}")
            logger.info(f"{'='*80}")

            stats = monitor.monitor()
            total_alerts += stats.get('alerts_sent', 0)

            logger.info(f"Cycle complete: {stats.get('alerts_sent', 0)} alerts sent")

            # Wait 60 seconds before next cycle
            logger.info("⏳ Waiting 60 seconds for next cycle...")
            time.sleep(60)

        except KeyboardInterrupt:
            logger.info("\n⚠️  Interrupted by user - exiting gracefully")
            break
        except Exception as e:
            logger.error(f"❌ Error in monitoring cycle: {e}", exc_info=True)
            # Wait 60 seconds before retry
            logger.info("⏳ Waiting 60 seconds before retry...")
            time.sleep(60)

    logger.info("👋 1-min monitor shutdown complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
