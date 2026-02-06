#!/usr/bin/env python3
"""
Rapid Alert Detector - 5-Min Alert Detection for Central Collector

Detects 5-minute drops AND rises immediately after each data collection cycle.
Reduces alert latency from ~2-3 minutes to ~3-10 seconds.

Key Design:
- Stateless: All state from passed objects (DB, alert_history, telegram)
- Fast: Batch queries, targets <500ms for 209 stocks
- Isolated: Exceptions don't propagate to collection loop

Author: Claude Opus 4.5
Date: 2026-01-22
Updated: 2026-01-30 - Added rise detection for trending stocks
"""

import logging
import time
from datetime import datetime, time as dt_time
from typing import Dict, Optional

import config
from alert_excel_logger import AlertExcelLogger

logger = logging.getLogger(__name__)


class RapidAlertDetector:
    """
    Detects 5-minute price drops AND rises immediately after data collection.

    Runs in central_data_collector_continuous.py after each collect_and_store() cycle.
    """

    def __init__(self, central_db, alert_history, telegram):
        """
        Initialize detector with shared components.

        Args:
            central_db: CentralQuoteDB instance (reader mode)
            alert_history: AlertHistoryManager instance
            telegram: TelegramNotifier instance
        """
        self.db = central_db
        self.alert_history = alert_history
        self.telegram = telegram

        # Initialize Excel logger for tracking
        self.excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH) if config.ENABLE_EXCEL_LOGGING else None

        # Configurable thresholds from config
        self.drop_threshold = config.DROP_THRESHOLD_5MIN  # Default: 1.25%
        self.rise_threshold = config.RISE_THRESHOLD_5MIN  # Default: 1.25%
        self.enable_rise_alerts = config.ENABLE_RISE_ALERTS  # Default: True
        self.cooldown_minutes = 10  # 10-minute cooldown for rapid alerts
        self.volume_spike_multiplier = 1.25  # Require current_volume > prev_volume * 1.25

        # Alert start time: 9:25 AM (from config)
        self.alert_start_time = dt_time(config.MARKET_START_HOUR, config.MARKET_START_MINUTE)

        logger.info(f"RapidAlertDetector initialized (drop: {self.drop_threshold}%, rise: {self.rise_threshold}%, "
                   f"volume_spike: {self.volume_spike_multiplier}x, "
                   f"rise_alerts: {self.enable_rise_alerts}, cooldown: {self.cooldown_minutes}min, "
                   f"start_time: {self.alert_start_time.strftime('%H:%M')}, "
                   f"excel_logging: {self.excel_logger is not None})")

    def detect_all(self, current_quotes: Dict[str, Dict]) -> Dict:
        """
        Detect 5-minute drops AND rises for all stocks in a single pass.

        Args:
            current_quotes: Dict of {symbol: {price, volume, oi, ...}} from just-collected data

        Returns:
            Dict with stats: {alerts_sent, drops_detected, rise_alerts_sent, rises_detected, stocks_checked, execution_ms}
        """
        start_time = time.time()

        stats = {
            'alerts_sent': 0,       # drop alerts
            'drops_detected': 0,
            'rise_alerts_sent': 0,  # rise alerts
            'rises_detected': 0,
            'stocks_checked': 0,
            'execution_ms': 0
        }

        # Skip alerts before 9:25 AM (market opening volatility)
        current_time = datetime.now().time()
        if current_time < self.alert_start_time:
            logger.debug(f"RapidAlertDetector: Skipping - before {self.alert_start_time.strftime('%H:%M')} AM")
            return stats

        if not current_quotes:
            logger.warning("RapidAlertDetector: No current quotes provided")
            return stats

        # Get symbols from current quotes
        symbols = list(current_quotes.keys())

        # Batch query: Get prices AND volumes from 5 minutes ago for all symbols in ONE query
        quotes_5min_ago = self.db.get_stock_quotes_at_batch(symbols, minutes_ago=5)

        if not quotes_5min_ago:
            logger.debug("RapidAlertDetector: No 5-min-ago data found (likely first 5 mins of collection)")
            return stats

        # Check each stock for 5-min drop/rise WITH volume spike
        for symbol, quote_data in current_quotes.items():
            try:
                stats['stocks_checked'] += 1

                current_price = quote_data.get('price')
                current_volume = quote_data.get('volume', 0)
                if not current_price or current_price <= 0:
                    continue

                prev_data = quotes_5min_ago.get(symbol)
                if not prev_data:
                    continue

                price_5min_ago = prev_data.get('price')
                volume_5min_ago = prev_data.get('volume', 0)

                if not price_5min_ago or price_5min_ago <= 0:
                    continue

                # Check for VOLUME SPIKE (required for all alerts)
                # Volume spike = current_volume > volume_5min_ago * 2.5
                has_volume_spike = False
                volume_multiplier = 0
                if volume_5min_ago > 0 and current_volume > 0:
                    volume_multiplier = current_volume / volume_5min_ago
                    has_volume_spike = current_volume > (volume_5min_ago * self.volume_spike_multiplier)

                if not has_volume_spike:
                    # No volume spike - skip this stock (don't even count as detected)
                    continue

                # Calculate drop percentage
                drop_pct = ((price_5min_ago - current_price) / price_5min_ago) * 100

                # Check if drop exceeds threshold (volume spike already confirmed)
                if drop_pct >= self.drop_threshold:
                    stats['drops_detected'] += 1

                    # Apply cooldown deduplication
                    if self.alert_history.should_send_alert(symbol, "5min", cooldown_minutes=self.cooldown_minutes):
                        # Get and increment alert count for today (with direction)
                        alert_count = self.alert_history.increment_alert_count(symbol, direction="drop")
                        direction_arrows = self.alert_history.get_direction_arrows(symbol)

                        # Send alert
                        success = self._send_alert(
                            symbol=symbol,
                            drop_pct=drop_pct,
                            current_price=current_price,
                            price_5min_ago=price_5min_ago,
                            current_volume=current_volume,
                            volume_5min_ago=volume_5min_ago,
                            volume_multiplier=volume_multiplier,
                            alert_count=alert_count,
                            direction_arrows=direction_arrows
                        )

                        if success:
                            stats['alerts_sent'] += 1
                            logger.info(f"RAPID DROP ALERT: {symbol} dropped {drop_pct:.2f}% "
                                       f"(₹{price_5min_ago:.2f} → ₹{current_price:.2f}) "
                                       f"VOL: {volume_multiplier:.1f}x spike")

                # Check for 5-min RISE (trending stocks) - volume spike already confirmed
                if self.enable_rise_alerts:
                    rise_pct = ((current_price - price_5min_ago) / price_5min_ago) * 100

                    if rise_pct >= self.rise_threshold:
                        stats['rises_detected'] += 1

                        # Apply cooldown deduplication (separate from drop cooldown)
                        if self.alert_history.should_send_alert(symbol, "5min_rise", cooldown_minutes=self.cooldown_minutes):
                            # Get and increment alert count for today (with direction)
                            alert_count = self.alert_history.increment_alert_count(symbol, direction="rise")
                            direction_arrows = self.alert_history.get_direction_arrows(symbol)

                            # Send rise alert
                            success = self._send_rise_alert(
                                symbol=symbol,
                                rise_pct=rise_pct,
                                current_price=current_price,
                                price_5min_ago=price_5min_ago,
                                current_volume=current_volume,
                                volume_5min_ago=volume_5min_ago,
                                volume_multiplier=volume_multiplier,
                                alert_count=alert_count,
                                direction_arrows=direction_arrows
                            )

                            if success:
                                stats['rise_alerts_sent'] += 1
                                logger.info(f"RAPID RISE ALERT: {symbol} rose {rise_pct:.2f}% "
                                           f"(₹{price_5min_ago:.2f} → ₹{current_price:.2f}) "
                                           f"VOL: {volume_multiplier:.1f}x spike")

            except Exception as e:
                logger.error(f"RapidAlertDetector: Error checking {symbol}: {e}")
                # Continue to next stock - error isolation!

        stats['execution_ms'] = int((time.time() - start_time) * 1000)

        if stats['alerts_sent'] > 0 or stats['rise_alerts_sent'] > 0:
            logger.info(f"RapidAlertDetector: {stats['alerts_sent']} drop alerts, "
                       f"{stats['rise_alerts_sent']} rise alerts, "
                       f"{stats['stocks_checked']} stocks checked in {stats['execution_ms']}ms")
        else:
            logger.debug(f"RapidAlertDetector: No alerts ({stats['drops_detected']} drops, "
                        f"{stats['rises_detected']} rises below cooldown, "
                        f"{stats['stocks_checked']} stocks in {stats['execution_ms']}ms)")

        return stats

    def _send_alert(
        self,
        symbol: str,
        drop_pct: float,
        current_price: float,
        price_5min_ago: float,
        current_volume: int = 0,
        volume_5min_ago: int = 0,
        volume_multiplier: float = 0,
        alert_count: int = None,
        direction_arrows: str = None
    ) -> bool:
        """
        Send 5-minute drop alert via Telegram.

        Args:
            symbol: Stock symbol
            drop_pct: Drop percentage
            current_price: Current price
            price_5min_ago: Price 5 minutes ago
            current_volume: Current volume
            volume_5min_ago: Volume 5 minutes ago
            volume_multiplier: Current volume / previous volume ratio
            alert_count: Count of how many times this stock has alerted today
            direction_arrows: Direction history arrows (e.g., "↓ ↑ ↓")

        Returns:
            True if alert sent successfully, False otherwise
        """
        try:
            # Prepare volume data with spike info
            volume_data = {
                'current_volume': current_volume,
                'avg_volume': volume_5min_ago,
                'volume_spike': True  # We only call this if spike detected
            } if current_volume > 0 else None

            # Send alert via TelegramNotifier
            success = self.telegram.send_alert(
                symbol=symbol,
                drop_percent=drop_pct,
                current_price=current_price,
                previous_price=price_5min_ago,
                alert_type="5min",
                volume_data=volume_data,
                market_cap_cr=None,  # Not calculated for rapid alerts
                rsi_analysis=None,   # Not calculated for rapid alerts
                oi_analysis=None,    # Not calculated for rapid alerts
                sector_context=None,  # Not calculated for rapid alerts
                alert_count=alert_count,
                direction_arrows=direction_arrows
            )

            # Log to Excel for tracking
            if self.excel_logger:
                try:
                    self.excel_logger.log_alert(
                        symbol=symbol,
                        alert_type="5min",
                        drop_percent=drop_pct,
                        current_price=current_price,
                        previous_price=price_5min_ago,
                        volume_data=volume_data,
                        market_cap_cr=None,
                        telegram_sent=success
                    )
                except Exception as e:
                    logger.error(f"RapidAlertDetector: Failed to log drop alert to Excel for {symbol}: {e}")

            return success

        except Exception as e:
            logger.error(f"RapidAlertDetector: Failed to send drop alert for {symbol}: {e}")
            return False

    def _send_rise_alert(
        self,
        symbol: str,
        rise_pct: float,
        current_price: float,
        price_5min_ago: float,
        current_volume: int = 0,
        volume_5min_ago: int = 0,
        volume_multiplier: float = 0,
        alert_count: int = None,
        direction_arrows: str = None
    ) -> bool:
        """
        Send 5-minute rise alert via Telegram.

        Args:
            symbol: Stock symbol
            rise_pct: Rise percentage
            current_price: Current price
            price_5min_ago: Price 5 minutes ago
            current_volume: Current volume
            volume_5min_ago: Volume 5 minutes ago
            volume_multiplier: Current volume / previous volume ratio
            alert_count: Count of how many times this stock has alerted today
            direction_arrows: Direction history arrows (e.g., "↓ ↑ ↓")

        Returns:
            True if alert sent successfully, False otherwise
        """
        try:
            # Prepare volume data with spike info
            volume_data = {
                'current_volume': current_volume,
                'avg_volume': volume_5min_ago,
                'volume_spike': True  # We only call this if spike detected
            } if current_volume > 0 else None

            # Send alert via TelegramNotifier (uses same interface, alert_type differentiates)
            success = self.telegram.send_alert(
                symbol=symbol,
                drop_percent=rise_pct,  # Reuses same param (positive value = rise)
                current_price=current_price,
                previous_price=price_5min_ago,
                alert_type="5min_rise",  # Key difference from drops
                volume_data=volume_data,
                market_cap_cr=None,  # Not calculated for rapid alerts
                rsi_analysis=None,   # Not calculated for rapid alerts
                oi_analysis=None,    # Not calculated for rapid alerts
                sector_context=None,  # Not calculated for rapid alerts
                alert_count=alert_count,
                direction_arrows=direction_arrows
            )

            # Log to Excel for tracking
            if self.excel_logger:
                try:
                    self.excel_logger.log_alert(
                        symbol=symbol,
                        alert_type="5min_rise",
                        drop_percent=rise_pct,
                        current_price=current_price,
                        previous_price=price_5min_ago,
                        volume_data=volume_data,
                        market_cap_cr=None,
                        telegram_sent=success
                    )
                except Exception as e:
                    logger.error(f"RapidAlertDetector: Failed to log rise alert to Excel for {symbol}: {e}")

            return success

        except Exception as e:
            logger.error(f"RapidAlertDetector: Failed to send rise alert for {symbol}: {e}")
            return False
