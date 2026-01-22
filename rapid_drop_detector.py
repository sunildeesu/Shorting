#!/usr/bin/env python3
"""
Rapid Drop Detector - 5-Min Alert Detection for Central Collector

Detects 5-minute drops immediately after each data collection cycle.
Reduces alert latency from ~2-3 minutes to ~3-10 seconds.

Key Design:
- Stateless: All state from passed objects (DB, alert_history, telegram)
- Fast: Batch queries, targets <500ms for 209 stocks
- Isolated: Exceptions don't propagate to collection loop

Author: Claude Opus 4.5
Date: 2026-01-22
"""

import logging
import time
from datetime import datetime
from typing import Dict, Optional

import config

logger = logging.getLogger(__name__)


class RapidDropDetector:
    """
    Detects 5-minute price drops immediately after data collection.

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

        # Configurable thresholds from config
        self.drop_threshold = config.DROP_THRESHOLD_5MIN  # Default: 1.25%
        self.cooldown_minutes = 10  # 10-minute cooldown for rapid alerts

        logger.info(f"RapidDropDetector initialized (threshold: {self.drop_threshold}%, cooldown: {self.cooldown_minutes}min)")

    def detect_all(self, current_quotes: Dict[str, Dict]) -> Dict:
        """
        Detect 5-minute drops for all stocks in a single pass.

        Args:
            current_quotes: Dict of {symbol: {price, volume, oi, ...}} from just-collected data

        Returns:
            Dict with stats: {alerts_sent, drops_detected, stocks_checked, execution_ms}
        """
        start_time = time.time()

        stats = {
            'alerts_sent': 0,
            'drops_detected': 0,
            'stocks_checked': 0,
            'execution_ms': 0
        }

        if not current_quotes:
            logger.warning("RapidDropDetector: No current quotes provided")
            return stats

        # Get symbols from current quotes
        symbols = list(current_quotes.keys())

        # Batch query: Get prices from 5 minutes ago for all symbols in ONE query
        prices_5min_ago = self.db.get_stock_prices_at_batch(symbols, minutes_ago=5)

        if not prices_5min_ago:
            logger.debug("RapidDropDetector: No 5-min-ago prices found (likely first 5 mins of collection)")
            return stats

        # Check each stock for 5-min drop
        for symbol, quote_data in current_quotes.items():
            try:
                stats['stocks_checked'] += 1

                current_price = quote_data.get('price')
                if not current_price or current_price <= 0:
                    continue

                price_5min_ago = prices_5min_ago.get(symbol)
                if not price_5min_ago or price_5min_ago <= 0:
                    continue

                # Calculate drop percentage
                drop_pct = ((price_5min_ago - current_price) / price_5min_ago) * 100

                # Check if drop exceeds threshold
                if drop_pct >= self.drop_threshold:
                    stats['drops_detected'] += 1

                    # Apply cooldown deduplication
                    if self.alert_history.should_send_alert(symbol, "5min", cooldown_minutes=self.cooldown_minutes):
                        # Send alert
                        success = self._send_alert(
                            symbol=symbol,
                            drop_pct=drop_pct,
                            current_price=current_price,
                            price_5min_ago=price_5min_ago,
                            volume=quote_data.get('volume', 0)
                        )

                        if success:
                            stats['alerts_sent'] += 1
                            logger.info(f"RAPID DROP ALERT: {symbol} dropped {drop_pct:.2f}% "
                                       f"(₹{price_5min_ago:.2f} → ₹{current_price:.2f})")

            except Exception as e:
                logger.error(f"RapidDropDetector: Error checking {symbol}: {e}")
                # Continue to next stock - error isolation!

        stats['execution_ms'] = int((time.time() - start_time) * 1000)

        if stats['alerts_sent'] > 0:
            logger.info(f"RapidDropDetector: {stats['alerts_sent']} alerts sent, "
                       f"{stats['drops_detected']} drops detected, "
                       f"{stats['stocks_checked']} stocks checked in {stats['execution_ms']}ms")
        else:
            logger.debug(f"RapidDropDetector: No alerts ({stats['drops_detected']} drops below cooldown, "
                        f"{stats['stocks_checked']} stocks in {stats['execution_ms']}ms)")

        return stats

    def _send_alert(
        self,
        symbol: str,
        drop_pct: float,
        current_price: float,
        price_5min_ago: float,
        volume: int = 0
    ) -> bool:
        """
        Send 5-minute drop alert via Telegram.

        Args:
            symbol: Stock symbol
            drop_pct: Drop percentage
            current_price: Current price
            price_5min_ago: Price 5 minutes ago
            volume: Current volume (optional)

        Returns:
            True if alert sent successfully, False otherwise
        """
        try:
            # Prepare volume data (minimal, just current volume)
            volume_data = {
                'current_volume': volume,
                'avg_volume': 0,
                'volume_spike': False
            } if volume > 0 else None

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
                sector_context=None  # Not calculated for rapid alerts
            )

            return success

        except Exception as e:
            logger.error(f"RapidDropDetector: Failed to send alert for {symbol}: {e}")
            return False
