#!/usr/bin/env python3
"""
CPR First Touch Monitor - Alert when NIFTY first touches CPR levels

Monitors NIFTY spot price every 1 minute and alerts when price first touches
TC (Top Central) or BC (Bottom Central) CPR levels during the trading day.

Features:
- Detects first touch only (once per day per level)
- Directional context (FROM_ABOVE or FROM_BELOW)
- Persistent state tracking (survives restarts)
- Shares 1-min NIFTY data with nifty_option_analyzer.py via cache

Author: Claude Sonnet 4.5
Date: 2026-01-12
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, date
from typing import Dict, Optional
from kiteconnect import KiteConnect

import time
import config
from api_coordinator import get_api_coordinator
from historical_data_cache import get_historical_cache
from alert_history_manager import AlertHistoryManager
from alert_excel_logger import AlertExcelLogger
from telegram_notifier import TelegramNotifier
from cpr_state_tracker import CPRStateTracker
from market_utils import is_market_open, get_market_status, get_current_ist_time
from central_db_reader import fetch_nifty_vix, report_cycle_complete
from service_health import get_health_tracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/cpr_first_touch_monitor.log'),
        logging.StreamHandler() if sys.stdout.isatty() else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)


class CPRFirstTouchMonitor:
    """CPR first touch monitoring system"""

    def __init__(self):
        """Initialize CPR monitor with all required components"""

        logger.info("=" * 80)
        logger.info("CPR FIRST TOUCH MONITOR - Initializing")
        logger.info("=" * 80)

        # Feature flag check
        if not hasattr(config, 'ENABLE_CPR_ALERTS') or not config.ENABLE_CPR_ALERTS:
            logger.info("CPR alerts disabled in config (ENABLE_CPR_ALERTS=false)")
            sys.exit(0)

        # Market check (trading day + market hours)
        if not is_market_open():
            status = get_market_status()
            if not status['is_trading_day']:
                logger.info(f"Not a trading day (weekend/holiday) - skipping")
            else:
                logger.info(f"Outside market hours (9:15 AM - 3:30 PM) - skipping")
            sys.exit(0)

        # Initialize Kite Connect
        logger.info("Initializing Kite Connect...")
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Initialize API Coordinator (Tier 2 optimization)
        self.coordinator = get_api_coordinator(kite=self.kite)
        logger.info("API Coordinator enabled (shared cache with nifty_option_analyzer)")

        # Initialize Historical Cache (for CPR calculation)
        self.historical_cache = get_historical_cache()
        logger.info("Historical cache enabled (for CPR calculation)")

        # Initialize core components
        logger.info("Initializing core components...")
        self.state_tracker = CPRStateTracker(state_file=config.CPR_STATE_FILE)
        self.alert_history = AlertHistoryManager()
        self.excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH) if config.ENABLE_EXCEL_LOGGING else None
        self.telegram = TelegramNotifier()

        # CPR cache (calculated once per day, cached in memory)
        self._cpr_cache = None

        # Dry-run mode
        self.dry_run = config.CPR_DRY_RUN_MODE
        if self.dry_run:
            logger.warning("🔔 DRY RUN MODE ENABLED - Alerts will NOT be sent to Telegram")

        logger.info("CPR First Touch Monitor initialized successfully")

    def _calculate_cpr(self) -> Optional[Dict]:
        """
        Calculate CPR (Central Pivot Range) from previous day's OHLC.

        Reuses logic from nifty_option_analyzer.py.

        Returns:
            Dict with 'tc', 'pivot', 'bc', 'width_pct', 'width_points'
            Returns None if insufficient data or error
        """
        try:
            # Get previous day's OHLC data
            end_date = datetime.now()
            start_date = end_date - timedelta(days=5)  # Get last 5 days to ensure we have previous day

            # Use historical cache (Tier 2 optimization)
            daily_data = self.historical_cache.get_historical_data(
                kite=self.kite,
                instrument_token=config.NIFTY_50_TOKEN,
                from_date=start_date,
                to_date=end_date,
                interval='day'
            )

            if not daily_data or len(daily_data) < 2:
                logger.warning("Insufficient data to calculate CPR")
                return None

            # Get previous trading day's data (second last candle, last is today incomplete)
            prev_day = daily_data[-2]

            high = prev_day['high']
            low = prev_day['low']
            close = prev_day['close']

            # Calculate CPR levels
            pivot = (high + low + close) / 3
            bc = (high + low) / 2
            tc = (pivot - bc) + pivot  # Same as 2*pivot - bc

            # CPR width (narrow = trending, wide = sideways)
            width_points = tc - bc
            width_pct = (width_points / pivot) * 100

            # Sanity check: TC should be greater than BC
            if tc <= bc:
                logger.error(f"⚠️ INVERTED CPR DETECTED: TC={tc:.2f} <= BC={bc:.2f}")
                logger.error(f"   Previous day OHLC: H={high}, L={low}, C={close}")
                logger.error(f"   Skipping CPR monitoring for today - invalid levels")
                return None

            logger.info(f"CPR Calculated - Pivot: {pivot:.2f}, TC: {tc:.2f}, BC: {bc:.2f}, Width: {width_pct:.3f}%")

            return {
                'tc': tc,
                'pivot': pivot,
                'bc': bc,
                'width_points': width_points,
                'width_pct': width_pct,
                'prev_day_high': high,
                'prev_day_low': low,
                'prev_day_close': close,
                'prev_day_date': prev_day.get('date', 'unknown')
            }

        except Exception as e:
            logger.error(f"Error calculating CPR: {e}", exc_info=True)
            return None

    def _ensure_cpr_is_fresh(self) -> Optional[Dict]:
        """
        Ensure CPR levels are for current trading day.
        Uses persistent state file to check if it's a new trading day.

        Returns:
            Dict with CPR levels or None if error
        """
        current_date = get_current_ist_time().date()

        # Check state file for trading date (persistent across restarts)
        state_trading_date = self.state_tracker.get_trading_date()

        if state_trading_date and state_trading_date == current_date:
            # Same trading day - use cached CPR from state file
            cpr_levels = self.state_tracker.get_cpr_levels()
            if cpr_levels and cpr_levels.get('tc'):
                logger.debug(f"Using existing CPR levels for {current_date}")
                return {
                    'tc': cpr_levels['tc'],
                    'bc': cpr_levels['bc'],
                    'pivot': cpr_levels['pivot'],
                    'width_pct': ((cpr_levels['tc'] - cpr_levels['bc']) / cpr_levels['pivot']) * 100
                }

        # New trading day - recalculate CPR and reset state
        logger.info(f"New trading day detected: {current_date}")
        logger.info("Recalculating CPR from previous day's OHLC...")

        cpr_data = self._calculate_cpr()

        if not cpr_data:
            logger.error("Failed to calculate CPR - skipping monitoring")
            return None

        # Reset state tracker for new day
        self.state_tracker.reset_for_new_day(current_date)

        # Set CPR levels in state tracker
        self.state_tracker.set_cpr_levels(
            tc=cpr_data['tc'],
            bc=cpr_data['bc'],
            pivot=cpr_data['pivot'],
            trading_date=current_date
        )

        # Cache for rest of the day
        self._cpr_cache = {
            'trading_date': current_date.isoformat(),
            'levels': cpr_data
        }

        logger.info(f"CPR levels cached for {current_date}: TC={cpr_data['tc']:.2f}, BC={cpr_data['bc']:.2f}")

        return cpr_data

    def _get_nifty_spot(self) -> Optional[float]:
        """
        Get current NIFTY spot price from Central DB with freshness check + API fallback.

        Returns:
            NIFTY spot price or None if error
        """
        # Use centralized helper with freshness check + health reporting
        result = fetch_nifty_vix(
            service_name="cpr_first_touch_monitor",
            kite_client=self.kite,
            coordinator=self.coordinator,
            max_age_minutes=2
        )

        nifty_spot = result.get('nifty_spot')

        if nifty_spot:
            return float(nifty_spot)

        logger.error("Failed to fetch NIFTY spot from Central DB and API fallback")
        return None

    def _format_cpr_touch_alert(self, touch_info: Dict, cpr_data: Dict, nifty_spot: float) -> str:
        """
        Format CPR first touch alert message for Telegram.

        Args:
            touch_info: Dict with crossing info from state_tracker
            cpr_data: Dict with CPR levels
            nifty_spot: Current NIFTY spot price

        Returns:
            Formatted alert message (HTML format)
        """
        level = touch_info['level']
        direction = touch_info['direction']
        level_value = touch_info['level_value']

        # Determine badge and insight based on level and direction
        if level == 'TC':
            if direction == "FROM_BELOW":
                emoji = "🔴"
                badge = "🔴🔴 CPR RESISTANCE TOUCH 🔴🔴"
                insight = "BULLISH signal - Price testing resistance from below. Watch for breakout or rejection."
            else:  # FROM_ABOVE
                emoji = "🟢"
                badge = "🟢🟢 CPR RESISTANCE TOUCH 🟢🟢"
                insight = "BEARISH signal - Price rejected resistance from above. Potential reversal."
        else:  # BC
            if direction == "FROM_ABOVE":
                emoji = "🟢"
                badge = "🟢🟢 CPR SUPPORT TOUCH 🟢🟢"
                insight = "BEARISH signal - Price testing support from above. Watch for breakdown or bounce."
            else:  # FROM_BELOW
                emoji = "🔴"
                badge = "🔴🔴 CPR SUPPORT TOUCH 🔴🔴"
                insight = "BULLISH signal - Price bounced from support below. Potential reversal."

        # Format timestamp
        current_time = get_current_ist_time()
        time_str = current_time.strftime("%I:%M:%S %p")

        # Build message
        message = f"{badge}\n"
        message += "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        message += f"{emoji} <b>FIRST TOUCH ALERT - {level}</b> {emoji}\n\n"

        # Level details
        message += f"📊 <b>Level Touched:</b> {level} (₹{level_value:,.2f})\n"
        message += f"📍 <b>Current Price:</b> ₹{nifty_spot:,.2f}\n"
        message += f"↗️ <b>Direction:</b> {direction.replace('_', ' ')}\n"
        message += f"⏰ <b>Time:</b> {time_str}\n\n"

        # Full CPR context
        message += "📈 <b>CPR LEVELS (Today):</b>\n"
        message += f"   TC (Resistance): ₹{cpr_data['tc']:,.2f}\n"
        message += f"   Pivot: ₹{cpr_data['pivot']:,.2f}\n"
        message += f"   BC (Support): ₹{cpr_data['bc']:,.2f}\n"
        message += f"   Width: {abs(cpr_data['width_pct']):.2f}% ({abs(cpr_data['width_points']):.2f} pts)\n\n"

        # Trading insight
        message += f"💡 <b>Insight:</b> {insight}\n\n"

        # Disclaimer
        message += "⚠️ <i>First touch of the day - Monitor for breakout/rejection</i>\n"

        return message

    def _send_cpr_alert(self, touch_info: Dict, cpr_data: Dict, nifty_spot: float):
        """
        Send CPR first touch alert to Telegram and log to Excel.

        Args:
            touch_info: Dict with crossing info
            cpr_data: Dict with CPR levels
            nifty_spot: Current NIFTY spot price
        """
        level = touch_info['level']
        direction = touch_info['direction']

        # Format alert message
        message = self._format_cpr_touch_alert(touch_info, cpr_data, nifty_spot)

        # Dry-run mode - log but don't send
        if self.dry_run:
            logger.info(f"[DRY RUN] Would send alert:")
            logger.info(message.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', ''))
            return

        # Send to Telegram
        try:
            success = self.telegram.send_message(message, parse_mode='HTML')

            if success:
                logger.info(f"✅ Alert sent to Telegram: {level} {direction}")

                # Log to Excel if enabled
                if self.excel_logger:
                    self.excel_logger.log_alert(
                        timestamp=datetime.now(),
                        symbol='NIFTY',
                        alert_type=f'CPR_{level}_TOUCH',
                        price=nifty_spot,
                        change_percent=0.0,  # Not applicable for CPR
                        volume=0,  # Not applicable
                        additional_data={
                            'level': level,
                            'level_value': touch_info['level_value'],
                            'direction': direction,
                            'cpr_tc': cpr_data['tc'],
                            'cpr_bc': cpr_data['bc'],
                            'cpr_pivot': cpr_data['pivot'],
                            'cpr_width_pct': cpr_data['width_pct']
                        }
                    )
                    logger.info("Alert logged to Excel")
            else:
                logger.error("Failed to send alert to Telegram")

        except Exception as e:
            logger.error(f"Error sending alert: {e}", exc_info=True)

    def monitor(self) -> Dict:
        """
        Main monitoring function - runs every 1 minute.

        Returns:
            Statistics dict with alert counts
        """
        cycle_start_time = time.time()  # Track cycle time for health reporting

        logger.info("=" * 80)
        logger.info(f"CPR MONITOR - Starting cycle at {get_current_ist_time().strftime('%H:%M:%S')}")
        logger.info("=" * 80)

        stats = {
            'alerts_sent': 0,
            'crossings_detected': 0,
            'nifty_spot': None,
            'cpr_levels': None
        }

        try:
            # Step 1: Ensure CPR levels are fresh (calculate once per day)
            cpr_data = self._ensure_cpr_is_fresh()
            if not cpr_data:
                logger.error("Failed to get CPR levels - aborting cycle")
                return stats

            stats['cpr_levels'] = {
                'tc': cpr_data['tc'],
                'bc': cpr_data['bc'],
                'pivot': cpr_data['pivot'],
                'width_pct': cpr_data['width_pct']
            }

            # Step 2: Get current NIFTY spot price (force_refresh=True to write to cache)
            nifty_spot = self._get_nifty_spot()
            if nifty_spot is None:
                logger.error("Failed to fetch NIFTY spot - aborting cycle")
                return stats

            stats['nifty_spot'] = nifty_spot
            logger.info(f"NIFTY Spot: {nifty_spot:.2f} | TC: {cpr_data['tc']:.2f} | BC: {cpr_data['bc']:.2f}")

            # Step 3: Check for TC and BC touches
            levels_to_check = [
                ('TC', cpr_data['tc']),
                ('BC', cpr_data['bc'])
            ]

            for level_name, level_value in levels_to_check:
                # Detect crossing
                touch_info = self.state_tracker.detect_crossing(level_name, nifty_spot, level_value)

                if touch_info:
                    # CROSSING DETECTED!
                    stats['crossings_detected'] += 1
                    logger.info(f"🔔 CROSSING DETECTED: {level_name} {touch_info['direction']} at {nifty_spot:.2f}")

                    # Check if alert already sent today (resets at 9:15 AM each trading day)
                    if not self.state_tracker.was_alert_sent_today(level_name):
                        logger.info(f"✅ First touch of the day - sending alert for {level_name}")

                        # Send alert
                        self._send_cpr_alert(touch_info, cpr_data, nifty_spot)

                        # Mark alert as sent for today
                        self.state_tracker.mark_alert_sent(level_name)

                        stats['alerts_sent'] += 1
                    else:
                        # Already alerted today - skip
                        logger.info(f"⏸️  Alert already sent for {level_name} today - skipping duplicate")

            # Log current positions
            tc_position = self.state_tracker.get_position('TC')
            bc_position = self.state_tracker.get_position('BC')
            logger.info(f"Current positions: TC={tc_position}, BC={bc_position}")

            # Summary
            logger.info(f"Cycle complete: {stats['crossings_detected']} crossings detected, {stats['alerts_sent']} alerts sent")

            # Report health metrics at end of cycle
            report_cycle_complete(
                service_name="cpr_first_touch_monitor",
                cycle_start_time=cycle_start_time,
                stats={
                    "crossings_detected": stats['crossings_detected'],
                    "alerts_sent": stats['alerts_sent']
                }
            )

            return stats

        except Exception as e:
            logger.error(f"Error in monitor cycle: {e}", exc_info=True)
            # Still report cycle completion even on error
            report_cycle_complete(
                service_name="cpr_first_touch_monitor",
                cycle_start_time=cycle_start_time,
                stats={"error": True}
            )
            return stats


def main():
    """Main entry point"""
    cycle_start = time.time()
    health = get_health_tracker()

    try:
        monitor = CPRFirstTouchMonitor()
        result = monitor.monitor()

        # Exit with status
        if result['alerts_sent'] > 0:
            logger.info(f"✅ CPR monitor completed successfully - {result['alerts_sent']} alert(s) sent")
        else:
            logger.info("✅ CPR monitor completed successfully - no alerts")

        # Record heartbeat
        cycle_duration_ms = int((time.time() - cycle_start) * 1000)
        health.heartbeat("cpr_first_touch_monitor", cycle_duration_ms)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Still record heartbeat on error so service shows as running
        cycle_duration_ms = int((time.time() - cycle_start) * 1000)
        health.heartbeat("cpr_first_touch_monitor", cycle_duration_ms)
        health.report_error("cpr_first_touch_monitor", "fatal_error", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
