#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
NSE Stock Monitor - Main Entry Point
Monitors NSE F&O stocks for significant price drops and sends Telegram alerts
"""

import sys
import logging
import os
from datetime import datetime
from market_utils import is_market_open, get_market_status
from stock_monitor import StockMonitor
import config

def setup_logging():
    """Configure logging to both file and console"""
    # Create logs directory if it doesn't exist
    os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)

    # Configure logging format
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # File handler
    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

def main():
    """Main execution function"""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("NSE Stock Monitor Starting...")
    if config.DEMO_MODE:
        logger.info("🎭 DEMO MODE ENABLED - Using mock data")
    logger.info("=" * 60)

    # Check market status
    market_status = get_market_status()
    logger.info(f"Current time: {market_status['current_time']}")
    logger.info(f"Is trading day: {market_status['is_trading_day']}")
    logger.info(f"Is market hours: {market_status['is_market_hours']}")
    logger.info(f"Market open: {market_status['is_open']}")

    # Only run if market is open
    if not is_market_open():
        logger.info("Market is closed. Exiting without monitoring.")
        return 0

    # Verify Telegram credentials are set
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHANNEL_ID:
        logger.error("Telegram credentials not set. Please configure .env file.")
        return 1

    # Check Kite Connect token validity
    if config.DATA_SOURCE == 'kite':
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

                return 1
            else:
                logger.info(f"✓ Token valid: {message}")
                if hours_remaining < 2:
                    logger.warning(f"⚠️ Token expires soon! ({hours_remaining:.1f} hours remaining)")
                    logger.warning("Consider refreshing token before next run: python3 generate_kite_token.py")
        except Exception as e:
            logger.error(f"Error checking token validity: {e}")
            logger.warning("Proceeding anyway, but monitoring may fail if token is invalid.")

    # Run stock monitoring
    try:
        logger.info("Initializing stock monitor...")
        monitor = StockMonitor()

        detection_info = []
        detection_info.append(f"{config.DROP_THRESHOLD_PERCENT}% drops")
        if config.ENABLE_RISE_ALERTS:
            detection_info.append(f"{config.RISE_THRESHOLD_PERCENT}% rises")

        logger.info(f"Starting monitoring for {' and '.join(detection_info)}...")
        stats = monitor.monitor_all_stocks()

        logger.info("=" * 60)
        logger.info("Monitoring Session Complete")
        logger.info(f"Total stocks: {stats['total']}")
        logger.info(f"Successfully checked: {stats['checked']}")
        logger.info(f"Drop alerts sent: {stats['drop_alerts']}")
        if config.ENABLE_RISE_ALERTS:
            logger.info(f"Rise alerts sent: {stats['rise_alerts']}")
        logger.info(f"Total alerts sent: {stats['alerts_sent']}")
        logger.info(f"Errors: {stats['errors']}")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"Fatal error during monitoring: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
