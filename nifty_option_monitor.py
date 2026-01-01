#!/usr/bin/env python3
"""
NIFTY Option Monitor - Intraday Scheduler

Entry Analysis: 10:00 AM (SELL/HOLD/AVOID signal)
Exit Monitoring: Every 15 minutes from 10:15 AM to 3:25 PM
Provides exit signals if market conditions deteriorate after entry

Usage:
    python3 nifty_option_monitor.py          # Run once now
    python3 nifty_option_monitor.py --daemon  # Run as daemon (intraday monitoring)

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
from position_state_manager import PositionStateManager
from market_utils import is_trading_day, is_nse_holiday, check_holiday_list_status

# Setup logging
# Note: When run by launchd, stdout is redirected to log file
# So we only need StreamHandler - launchd handles file writing
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class NiftyOptionMonitor:
    """Monitor and schedule NIFTY option analysis with intraday exit signals"""

    def __init__(self):
        """Initialize monitor with Kite connection"""
        self.token_manager = TokenManager()
        self.kite = None
        self.analyzer = None
        self.excel_logger = NiftyOptionLogger()
        self.telegram = TelegramNotifier()
        self.position_manager = PositionStateManager(config.NIFTY_OPTION_POSITION_STATE_FILE)
        self.last_check_minute = None  # Track last check to prevent duplicates

        # Parse times from config
        self.entry_time = self._parse_time(config.NIFTY_OPTION_ANALYSIS_TIME)
        self.end_time = self._parse_time(config.NIFTY_OPTION_MONITOR_END_TIME)
        self.check_interval = config.NIFTY_OPTION_MONITOR_INTERVAL  # minutes

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
        """Check if today is a trading day (excludes weekends and NSE holidays)"""
        trading_day = is_trading_day()

        if not trading_day:
            now = datetime.now()
            current_date = now.date()

            # Check reason for non-trading day
            if now.weekday() >= 5:
                logger.info(f"Weekend - Market closed ({now.strftime('%A, %B %d, %Y')})")
            elif is_nse_holiday(current_date):
                logger.info(f"NSE Holiday - Market closed ({now.strftime('%A, %B %d, %Y')})")

        return trading_day

    def _should_run_entry_analysis(self) -> bool:
        """Check if we should run entry analysis (10:00 AM check)"""
        if not config.ENABLE_NIFTY_OPTION_ANALYSIS:
            return False

        if not self._is_trading_day():
            return False

        # Check if already have position today
        if self.position_manager.has_position_today():
            logger.debug("Position already entered today")
            return False

        now = datetime.now()
        current_time = now.time()

        # Check if current time is entry time (with 1-minute tolerance)
        if current_time.hour == self.entry_time.hour and current_time.minute == self.entry_time.minute:
            return True

        return False

    def _should_run_exit_analysis(self) -> bool:
        """Check if we should run intraday monitoring (15-minute intervals for exit/add checks)"""
        if not config.ENABLE_NIFTY_OPTION_ANALYSIS:
            return False

        if not self._is_trading_day():
            return False

        # Run intraday monitoring regardless of position status
        # (supports both exit monitoring and late entry)

        now = datetime.now()
        current_time = now.time()

        # Check if within monitoring window (after entry time, before end time)
        if current_time < self.entry_time or current_time > self.end_time:
            return False

        # Check if it's a 15-minute interval
        # Run at :15, :30, :45, :00 minute marks
        if current_time.minute % self.check_interval == 0:
            # Prevent duplicate runs in same minute
            current_minute_key = f"{current_time.hour}:{current_time.minute}"
            if self.last_check_minute == current_minute_key:
                return False

            self.last_check_minute = current_minute_key
            return True

        return False

    def run_entry_analysis(self) -> bool:
        """Run entry analysis at 10:00 AM"""
        try:
            logger.info("=" * 70)
            logger.info("ENTRY ANALYSIS - 10:00 AM")
            logger.info("=" * 70)

            # Initialize Kite if needed
            if not self.kite or not self.analyzer:
                if not self._initialize_kite():
                    logger.error("Cannot run analysis - Kite initialization failed")
                    return False

            # Run entry analysis
            result = self.analyzer.analyze_option_selling_opportunity()

            # Check for errors
            if 'error' in result:
                logger.error(f"Analysis failed: {result['error']}")
                self.telegram.send_nifty_option_analysis(result)
                return False

            signal = result.get('signal', 'HOLD')
            score = result.get('total_score', 0)

            logger.info(f"Entry Signal: {signal} (Score: {score:.1f}/100)")

            # Record entry if SELL signal
            if signal == 'SELL':
                logger.info("SELL signal - Recording position entry")
                self.position_manager.record_entry(result)

                # Send Telegram alert
                self.telegram.send_nifty_option_analysis(result)

                # Log to Excel
                self.excel_logger.log_analysis(result, telegram_sent=True)

                logger.info(f"✅ Position entered: {score:.1f}/100")
            else:
                logger.info(f"No entry - Signal is {signal}")

                # Still send Telegram alert for transparency
                self.telegram.send_nifty_option_analysis(result)

                # Log to Excel
                self.excel_logger.log_analysis(result, telegram_sent=True)

            return True

        except Exception as e:
            logger.error(f"Error in entry analysis: {e}", exc_info=True)
            return False

    def run_intraday_monitoring(self) -> bool:
        """Run intraday monitoring (exit analysis + add position check)"""
        try:
            logger.info("=" * 70)
            logger.info(f"INTRADAY MONITORING - {datetime.now().strftime('%H:%M')}")
            logger.info("=" * 70)

            # Initialize Kite if needed
            if not self.kite or not self.analyzer:
                if not self._initialize_kite():
                    logger.error("Cannot run monitoring - Kite initialization failed")
                    return False

            has_position = self.position_manager.has_position_today()
            layer_count = self.position_manager.get_layer_count()

            # Run fresh analysis for current score
            current_analysis = self.analyzer.analyze_option_selling_opportunity()
            current_score = current_analysis.get('total_score', 0)

            logger.info(f"Current Score: {current_score:.1f}/100 | Layers: {layer_count}/{config.NIFTY_OPTION_MAX_LAYERS}")

            # 1. CHECK FOR EXIT (if position exists)
            if has_position:
                entry_data = self.position_manager.get_entry_data()
                exit_result = self.analyzer.analyze_exit_signal(entry_data)

                exit_signal = exit_result.get('signal', 'HOLD_POSITION')
                urgency = exit_result.get('urgency', 'NONE')

                logger.info(f"Exit Signal: {exit_signal} (Urgency: {urgency})")

                if exit_signal == 'EXIT_NOW':
                    exit_reasons = "; ".join(exit_result.get('exit_reasons', []))
                    logger.warning(f"🚨 EXIT SIGNAL: {exit_reasons}")

                    # Record exit
                    self.position_manager.record_exit(exit_result, exit_reasons)

                    # Send Telegram alert
                    self.telegram.send_nifty_exit_alert(exit_result)

                    # Log to Excel
                    self.excel_logger.log_exit(exit_result, telegram_sent=True)

                    logger.info("Position exited - Monitoring will resume for new entries")
                    return True

                elif exit_signal == 'CONSIDER_EXIT':
                    logger.info(f"⚠️  Consider exit: {exit_result.get('recommendation', '')}")
                    # Send warning alert
                    self.telegram.send_nifty_exit_alert(exit_result)
                else:
                    logger.info("✅ Position secure - Checking for add opportunity")

            # 2. CHECK FOR ADD POSITION (if not at max layers)
            can_add = self.position_manager.can_add_layer(
                max_layers=config.NIFTY_OPTION_MAX_LAYERS,
                min_interval_minutes=config.NIFTY_OPTION_ADD_MIN_INTERVAL
            )

            if can_add:
                if not has_position and config.NIFTY_OPTION_ADD_AFTER_NO_ENTRY:
                    # No position yet - treat as first entry if conditions good
                    if current_score >= config.NIFTY_OPTION_ADD_SCORE_THRESHOLD:
                        logger.info(f"📈 Late entry opportunity: Score {current_score:.1f} >= {config.NIFTY_OPTION_ADD_SCORE_THRESHOLD}")
                        logger.info("SELL signal - Recording position entry (late entry)")
                        self.position_manager.record_entry(current_analysis, layer_number=1)

                        # Send Telegram alert
                        self.telegram.send_nifty_add_position_alert(current_analysis, layer_number=1, is_late_entry=True)

                        # Log to Excel
                        self.excel_logger.log_analysis(current_analysis, telegram_sent=True)

                        logger.info(f"✅ Position entered (late): {current_score:.1f}/100")
                        return True
                    else:
                        logger.info(f"No late entry - Score {current_score:.1f} < {config.NIFTY_OPTION_ADD_SCORE_THRESHOLD} (threshold)")

                elif has_position:
                    # Check for adding to existing position
                    last_layer_score = self.position_manager.get_last_layer_score()

                    add_result = self.analyzer.analyze_add_position_signal(
                        current_score=current_score,
                        last_layer_score=last_layer_score,
                        layer_count=layer_count
                    )

                    add_signal = add_result.get('signal', 'NO_ADD')
                    confidence = add_result.get('confidence', 0)

                    logger.info(f"Add Signal: {add_signal} (Confidence: {confidence}%)")

                    if add_signal == 'ADD_POSITION':
                        add_reasons = "; ".join(add_result.get('add_reasons', []))
                        logger.info(f"📈 ADD POSITION: {add_reasons}")

                        # Record additional layer
                        next_layer = layer_count + 1
                        self.position_manager.record_entry(current_analysis, layer_number=next_layer)

                        # Send Telegram alert
                        self.telegram.send_nifty_add_position_alert(current_analysis, layer_number=next_layer)

                        # Log to Excel
                        self.excel_logger.log_add_position(current_analysis, next_layer, telegram_sent=True)

                        logger.info(f"✅ Layer {next_layer} added: {current_score:.1f}/100")
                        return True

                    elif add_signal == 'CONSIDER_ADD':
                        logger.info(f"💡 Consider add: {add_result.get('recommendation', '')}")
                    else:
                        logger.info("No add signal - Conditions not favorable")
            else:
                logger.info(f"Cannot add layer: {layer_count}/{config.NIFTY_OPTION_MAX_LAYERS} layers")

            # Update last check
            if has_position:
                self.position_manager.update_check(current_analysis)

            # Send end-of-day summary at last check (3:25 PM)
            now = datetime.now()
            if now.time().hour == 15 and now.time().minute == 25:
                logger.info("=" * 70)
                logger.info("SENDING END-OF-DAY SUMMARY")
                logger.info("=" * 70)

                # Get current position state
                position_state = self.position_manager.state if self.position_manager.state else {}

                # Send EOD summary
                try:
                    self.telegram.send_nifty_eod_summary(position_state, current_analysis)
                    logger.info("✅ End-of-day summary sent to Telegram")
                except Exception as e:
                    logger.error(f"Failed to send EOD summary: {e}")

            return True

        except Exception as e:
            logger.error(f"Error in intraday monitoring: {e}", exc_info=True)
            return False

    def run_once(self) -> bool:
        """Run analysis once (scheduled by launchd)"""
        # Check if holiday list is up-to-date (warn if missing for current/next year)
        holiday_status = check_holiday_list_status()
        if holiday_status['needs_update'] and holiday_status['warning_message']:
            logger.warning(holiday_status['warning_message'])

        now = datetime.now()
        current_time = now.time()

        # Determine which analysis to run based on time
        if self._should_run_entry_analysis():
            logger.info("Running entry analysis (10:00 AM check)")
            return self.run_entry_analysis()
        elif self._should_run_exit_analysis():
            logger.info("Running intraday monitoring (exit + add checks)")
            return self.run_intraday_monitoring()
        else:
            logger.info(f"No scheduled analysis at {current_time.strftime('%H:%M')} - skipping")
            return True

    def run_daemon(self, check_interval_seconds: int = 60):
        """
        Run as daemon - intraday monitoring with 15-minute exit checks

        Args:
            check_interval_seconds: Seconds between daemon checks (default: 60)
        """
        logger.info(f"Starting NIFTY Option Monitor daemon")
        logger.info(f"Entry analysis: {self.entry_time}")
        logger.info(f"Exit monitoring: Every {self.check_interval} minutes until {self.end_time}")
        logger.info(f"Daemon check interval: {check_interval_seconds} seconds")

        # Check if holiday list is up-to-date
        holiday_status = check_holiday_list_status()
        if holiday_status['needs_update'] and holiday_status['warning_message']:
            logger.warning(holiday_status['warning_message'])

        # Check if it's a new day and reset state
        last_date = None

        while True:
            try:
                now = datetime.now()
                current_date = now.date()

                # Reset state at start of new trading day
                if last_date != current_date and now.time().hour >= 9:
                    logger.info(f"New trading day: {current_date}")
                    if last_date is not None:
                        self.position_manager.reset_for_new_day()
                    last_date = current_date

                # Check for entry analysis (10:00 AM)
                if self._should_run_entry_analysis():
                    logger.info("Entry time reached - Running entry analysis")
                    self.run_entry_analysis()

                # Check for intraday monitoring (every 15 minutes - exit + add checks)
                elif self._should_run_exit_analysis():
                    logger.info("Monitoring time - Running intraday checks")
                    self.run_intraday_monitoring()

                else:
                    # Log status periodically (every 5 minutes)
                    if now.minute % 5 == 0 and now.second < check_interval_seconds:
                        status = self.position_manager.get_status_summary()
                        logger.debug(f"[{now.strftime('%H:%M')}] {status}")

                time.sleep(check_interval_seconds)

            except KeyboardInterrupt:
                logger.info("Daemon stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in daemon loop: {e}", exc_info=True)
                time.sleep(check_interval_seconds)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='NIFTY Option Monitor (Intraday)')
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run as daemon (intraday monitoring)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run test analysis (ignore schedule)'
    )
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Reset position state for new day'
    )

    args = parser.parse_args()

    # Create monitor
    monitor = NiftyOptionMonitor()

    if args.reset:
        # Reset position state
        logger.info("Resetting position state...")
        monitor.position_manager.reset_for_new_day()
        logger.info("Position state reset complete")
        sys.exit(0)

    if args.daemon:
        # Run as daemon (intraday monitoring)
        monitor.run_daemon()
    elif args.test:
        # Test run (ignore schedule)
        logger.info("TEST MODE - Running analysis now")
        success = monitor.run_once()
        sys.exit(0 if success else 1)
    else:
        # Single run (check schedule)
        success = monitor.run_once()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
