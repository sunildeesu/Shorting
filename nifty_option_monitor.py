#!/usr/bin/env python3
"""
NIFTY Option Monitor - Daily Scheduler

Runs NIFTY option selling analysis daily at 10:00 AM (configurable).
Sends Telegram alerts and logs results to Excel.

Usage:
    python3 nifty_option_monitor.py          # Run once now
    python3 nifty_option_monitor.py --daemon  # Run as daemon (checks every minute)

Author: Sunil Kumar Durganaik
"""

import sys
import time
import logging
import argparse
from datetime import datetime, time as dtime
from kiteconnect import KiteConnect

import config
from token_manager import TokenManager
from nifty_option_analyzer import NiftyOptionAnalyzer
from nifty_option_logger import NiftyOptionLogger
from telegram_notifier import TelegramNotifier

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/nifty_option_monitor.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class NiftyOptionMonitor:
    """Monitor and schedule NIFTY option analysis"""

    def __init__(self):
        """Initialize monitor with Kite connection"""
        self.token_manager = TokenManager()
        self.kite = None
        self.analyzer = None
        self.excel_logger = NiftyOptionLogger()
        self.telegram = TelegramNotifier()
        self.last_run_date = None  # Track last run to prevent duplicates

        # Parse analysis time from config
        self.analysis_time = self._parse_time(config.NIFTY_OPTION_ANALYSIS_TIME)

    def _parse_time(self, time_str: str) -> dtime:
        """Parse time string (HH:MM format) to time object"""
        try:
            hour, minute = map(int, time_str.split(':'))
            return dtime(hour=hour, minute=minute)
        except:
            logger.warning(f"Invalid time format: {time_str}, using default 10:00")
            return dtime(hour=10, minute=0)

    def _initialize_kite(self) -> bool:
        """Initialize Kite Connect with token validation"""
        try:
            # Check token validity
            is_valid, message, hours_remaining = self.token_manager.is_token_valid()

            if not is_valid:
                logger.error(f"Kite token invalid: {message}")
                logger.error("Please run: python3 generate_kite_token.py")
                return False

            if hours_remaining < 2:
                logger.warning(f"Token expiring soon: {hours_remaining:.1f} hours remaining")

            # Initialize Kite
            self.kite = KiteConnect(api_key=config.KITE_API_KEY)
            self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

            # Test connection
            profile = self.kite.profile()
            logger.info(f"Connected to Kite as: {profile.get('user_name', 'Unknown')}")

            # Initialize analyzer
            self.analyzer = NiftyOptionAnalyzer(self.kite)

            return True

        except Exception as e:
            logger.error(f"Failed to initialize Kite: {e}")
            return False

    def _is_trading_day(self) -> bool:
        """
        Check if today is a trading day

        Returns:
            True if market is open today
        """
        now = datetime.now()

        # Check if weekend (Saturday=5, Sunday=6)
        if now.weekday() >= 5:
            logger.info("Weekend - Market closed")
            return False

        # TODO: Add holiday calendar check if needed
        # For now, assume weekdays are trading days

        return True

    def _should_run_analysis(self) -> bool:
        """
        Check if analysis should run now

        Conditions:
        - Trading day (not weekend)
        - Current time >= analysis time
        - Haven't run today yet

        Returns:
            True if should run analysis
        """
        if not config.ENABLE_NIFTY_OPTION_ANALYSIS:
            logger.debug("NIFTY option analysis is disabled in config")
            return False

        if not self._is_trading_day():
            return False

        now = datetime.now()
        current_time = now.time()
        today_str = now.strftime("%Y-%m-%d")

        # Check if already ran today
        if self.last_run_date == today_str:
            logger.debug("Analysis already completed today")
            return False

        # Check if current time >= analysis time
        if current_time < self.analysis_time:
            logger.debug(f"Not yet time for analysis (scheduled: {self.analysis_time})")
            return False

        return True

    def run_analysis(self) -> bool:
        """
        Run NIFTY option analysis

        Returns:
            True if analysis completed successfully
        """
        try:
            logger.info("=" * 70)
            logger.info("STARTING NIFTY OPTION ANALYSIS")
            logger.info("=" * 70)

            # Initialize Kite if not already done
            if not self.kite or not self.analyzer:
                if not self._initialize_kite():
                    logger.error("Cannot run analysis - Kite initialization failed")
                    return False

            # Run analysis
            result = self.analyzer.analyze_option_selling_opportunity()

            # Check for errors
            if 'error' in result:
                logger.error(f"Analysis failed: {result['error']}")
                # Still send Telegram alert about the error
                self.telegram.send_nifty_option_analysis(result)
                return False

            # Log to Excel
            telegram_sent = False
            try:
                excel_success = self.excel_logger.log_analysis(
                    analysis_data=result,
                    telegram_sent=False  # Will update after Telegram send
                )
                if excel_success:
                    logger.info("Analysis logged to Excel successfully")
                else:
                    logger.warning("Failed to log analysis to Excel")
            except Exception as e:
                logger.error(f"Excel logging failed: {e}")

            # Send Telegram alert
            try:
                telegram_sent = self.telegram.send_nifty_option_analysis(result)
                if telegram_sent:
                    logger.info("Telegram alert sent successfully")
                else:
                    logger.warning("Failed to send Telegram alert")

                # Update Excel with telegram_sent status
                if excel_success and telegram_sent:
                    self.excel_logger.log_analysis(
                        analysis_data=result,
                        telegram_sent=True
                    )
            except Exception as e:
                logger.error(f"Telegram notification failed: {e}")

            # Mark as completed for today
            self.last_run_date = datetime.now().strftime("%Y-%m-%d")

            logger.info("=" * 70)
            logger.info(f"ANALYSIS COMPLETE - Signal: {result.get('signal')} ({result.get('total_score', 0):.1f}/100)")
            logger.info("=" * 70)

            return True

        except Exception as e:
            logger.error(f"Error in run_analysis: {e}", exc_info=True)
            return False

    def run_once(self) -> bool:
        """
        Run analysis once (regardless of schedule)

        Returns:
            True if successful
        """
        logger.info("Running NIFTY option analysis (manual trigger)")
        return self.run_analysis()

    def run_daemon(self, check_interval: int = 60):
        """
        Run as daemon - check every interval and run analysis at scheduled time

        Args:
            check_interval: Seconds between checks (default: 60)
        """
        logger.info(f"Starting NIFTY Option Monitor daemon")
        logger.info(f"Analysis scheduled daily at {self.analysis_time}")
        logger.info(f"Check interval: {check_interval} seconds")

        while True:
            try:
                if self._should_run_analysis():
                    logger.info("Scheduled time reached - running analysis")
                    self.run_analysis()
                else:
                    now = datetime.now()
                    logger.debug(f"[{now.strftime('%H:%M:%S')}] Waiting for scheduled time...")

                time.sleep(check_interval)

            except KeyboardInterrupt:
                logger.info("Daemon stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in daemon loop: {e}", exc_info=True)
                time.sleep(check_interval)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='NIFTY Option Monitor')
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run as daemon (continuous monitoring)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run test analysis (ignore schedule)'
    )

    args = parser.parse_args()

    # Create monitor
    monitor = NiftyOptionMonitor()

    if args.daemon:
        # Run as daemon
        monitor.run_daemon()
    elif args.test:
        # Test run (ignore schedule)
        logger.info("TEST MODE - Running analysis now")
        success = monitor.run_once()
        sys.exit(0 if success else 1)
    else:
        # Single run (check schedule)
        if monitor._should_run_analysis():
            success = monitor.run_analysis()
            sys.exit(0 if success else 1)
        else:
            logger.info("Not time for analysis yet (or already completed today)")
            sys.exit(0)


if __name__ == "__main__":
    main()
