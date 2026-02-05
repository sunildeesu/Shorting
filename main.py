#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
NSE Stock Monitor - Main Entry Point (CONTINUOUS MODE)
Monitors NSE F&O stocks for significant price drops and sends Telegram alerts

Runs from 9:25 AM to 3:25 PM with internal 5-minute loop
- Starts ONCE at 9:25 AM via launchd
- Runs continuous loop during market hours
- Exits cleanly after 3:25 PM
"""

import sys
import time
import logging
import os
from datetime import datetime, time as dt_time
from market_utils import is_market_open, get_market_status
from stock_monitor import StockMonitor
import config

# Market monitoring window: 9:25 AM to 3:25 PM
MONITOR_START = dt_time(9, 25)
MONITOR_END = dt_time(15, 25)
MONITOR_INTERVAL_SECONDS = 300  # 5 minutes


def setup_logging():
    """Configure logging to file and optionally console (avoids duplicate logging under LaunchD)"""
    # Create logs directory if it doesn't exist
    os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)

    # Configure logging format
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # File handler (always enabled)
    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    # Console handler (only if running interactively, NOT under LaunchD)
    # Avoids duplicate logging when LaunchD redirects stdout to the same log file
    if sys.stdout.isatty():
        # Running interactively in terminal - add console output
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(log_format, date_format))
        root_logger.addHandler(console_handler)
    # If stdout is redirected (LaunchD case), skip console handler to avoid duplicates


def is_within_monitor_hours() -> bool:
    """Check if current time is between 9:25 AM and 3:25 PM"""
    now = datetime.now().time()
    return MONITOR_START <= now <= MONITOR_END


def check_kite_token(logger) -> bool:
    """Check Kite Connect token validity. Returns True if valid or not using Kite."""
    if config.DATA_SOURCE != 'kite':
        return True

    logger.info("Checking Kite Connect token validity...")
    try:
        from token_manager import TokenManager
        manager = TokenManager()
        is_valid, message, hours_remaining = manager.is_token_valid()

        if not is_valid:
            logger.error(f"Kite Connect token is invalid: {message}")
            logger.error("=" * 60)
            logger.error("ACTION REQUIRED: Run the following command to refresh your token:")
            logger.error("  python3 generate_kite_token.py")
            logger.error("=" * 60)

            # Send Telegram alert
            warning = manager.get_expiry_warning_message()
            if warning:
                try:
                    from telegram_notifier import TelegramNotifier
                    telegram = TelegramNotifier()
                    telegram._send_message(warning)
                    logger.info("Sent token expiry alert via Telegram")
                except Exception as e:
                    logger.error(f"Failed to send Telegram alert: {e}")

            return False
        else:
            logger.info(f"Token valid: {message}")
            if hours_remaining < 2:
                logger.warning(f"Token expires soon! ({hours_remaining:.1f} hours remaining)")
                logger.warning("Consider refreshing token: python3 generate_kite_token.py")
            return True
    except Exception as e:
        logger.error(f"Error checking token validity: {e}")
        logger.warning("Proceeding anyway, but monitoring may fail if token is invalid.")
        return True


def run_monitoring_cycle(monitor, logger) -> dict:
    """Run a single monitoring cycle. Returns stats dict."""
    detection_info = []
    detection_info.append(f"{config.DROP_THRESHOLD_PERCENT}% drops")
    if config.ENABLE_RISE_ALERTS:
        detection_info.append(f"{config.RISE_THRESHOLD_PERCENT}% rises")

    logger.info(f"Monitoring for {' and '.join(detection_info)}...")
    stats = monitor.monitor_all_stocks()

    logger.info(f"Cycle complete: {stats['checked']}/{stats['total']} stocks, "
                f"{stats['alerts_sent']} alerts ({stats['drop_alerts']} drops"
                f"{', ' + str(stats['rise_alerts']) + ' rises' if config.ENABLE_RISE_ALERTS else ''}), "
                f"{stats['errors']} errors")

    return stats


def main():
    """Main continuous monitoring loop"""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 80)
    logger.info("NSE STOCK MONITOR - CONTINUOUS MODE")
    logger.info("=" * 80)
    if config.DEMO_MODE:
        logger.info("DEMO MODE ENABLED - Using mock data")

    # Check if trading day
    market_status = get_market_status()
    logger.info(f"Current time: {market_status['current_time']}")
    logger.info(f"Is trading day: {market_status['is_trading_day']}")

    if not market_status['is_trading_day']:
        logger.info("Not a trading day (weekend/holiday) - exiting")
        return 0

    logger.info("Trading day confirmed")

    # Verify Telegram credentials are set
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHANNEL_ID:
        logger.error("Telegram credentials not set. Please configure .env file.")
        return 1

    # Check Kite token
    if not check_kite_token(logger):
        return 1

    # Initialize monitor ONCE (reused for all cycles)
    try:
        logger.info("Initializing stock monitor...")
        monitor = StockMonitor()
        logger.info("Stock monitor initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize stock monitor: {e}", exc_info=True)
        return 1

    # Continuous monitoring loop
    cycle_count = 0
    total_alerts_sent = 0

    logger.info("=" * 80)
    logger.info("Starting continuous monitoring loop")
    logger.info(f"Monitor hours: {MONITOR_START.strftime('%H:%M')} - {MONITOR_END.strftime('%H:%M')}")
    logger.info(f"Interval: Every {MONITOR_INTERVAL_SECONDS // 60} minutes")
    logger.info("=" * 80)

    while True:
        try:
            # Check if still within monitoring hours
            if not is_within_monitor_hours():
                logger.info("=" * 80)
                logger.info(f"Monitor hours ended ({MONITOR_END.strftime('%H:%M')}) - exiting")
                logger.info(f"Total cycles completed: {cycle_count}")
                logger.info(f"Total alerts sent: {total_alerts_sent}")
                logger.info("=" * 80)
                break

            cycle_count += 1
            logger.info("")
            logger.info(f"{'=' * 60}")
            logger.info(f"CYCLE #{cycle_count} - {datetime.now().strftime('%H:%M:%S')}")
            logger.info(f"{'=' * 60}")

            # Run monitoring cycle
            stats = run_monitoring_cycle(monitor, logger)
            total_alerts_sent += stats['alerts_sent']

            # Sleep until next cycle
            logger.info(f"Sleeping {MONITOR_INTERVAL_SECONDS // 60} minutes until next cycle...")
            time.sleep(MONITOR_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("\nInterrupted by user - exiting gracefully")
            break
        except Exception as e:
            logger.error(f"Cycle {cycle_count} error: {e}", exc_info=True)
            logger.info(f"Waiting {MONITOR_INTERVAL_SECONDS // 60} minutes before retry...")
            time.sleep(MONITOR_INTERVAL_SECONDS)

    # Final summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("NSE STOCK MONITOR - Shutdown Complete")
    logger.info(f"Total cycles: {cycle_count}")
    logger.info(f"Total alerts sent: {total_alerts_sent}")
    logger.info("=" * 80)

    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
