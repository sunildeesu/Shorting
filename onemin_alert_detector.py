#!/usr/bin/env python3
"""
1-Minute Alert Detection Logic
Multi-layer filtering with TIERED PRIORITY system

NORMAL Priority (Layers 1-5):
1. Price threshold (0.50% change in 1 minute)
2. Volume spike requirement (2.5x average - percentage-based only, no absolute minimum)
3. Quality filters (price >=50, no ban list stocks)
4. Cooldown (10 minutes per stock)
5. Cross-alert deduplication (no 5-min alert in last 3 minutes)

HIGH Priority (All 6 Layers):
6. Momentum confirmation (price acceleration - 30% faster than 4-min avg)
   → Only HIGH priority alerts show strong momentum acceleration

Note: Volume filter uses ONLY percentage-based multiplier (2.5x average).
No absolute minimum because different stocks have vastly different normal volumes:
- Large-cap stocks: 500K shares/min normal
- Mid-cap stocks: 50K shares/min normal
- Small-cap stocks: 5K shares/min normal
A 2.5x spike is significant regardless of absolute volume.
"""

from typing import Optional
from datetime import datetime, timedelta
import logging
import config
from price_cache import PriceCache
from alert_history_manager import AlertHistoryManager

logger = logging.getLogger(__name__)


class OneMinAlertDetector:
    """Detect 1-minute price movements with strict filtering"""

    def __init__(self, price_cache: PriceCache, alert_history: AlertHistoryManager):
        self.price_cache = price_cache
        self.alert_history = alert_history

    def check_for_drop_1min(self, symbol: str, current_price: float,
                            price_1min_ago: float, current_volume: int,
                            oi: float = 0, price_5min_ago: float = None) -> Optional[str]:
        """
        Check if stock meets 1-min drop criteria with tiered priority.

        Args:
            symbol: Stock symbol
            current_price: Current price
            price_1min_ago: Price from 1 minute ago
            current_volume: Current trading volume
            oi: Open interest (optional)
            price_5min_ago: Price from 5 minutes ago (optional, for momentum check)

        Returns:
            "HIGH" if passes all 6 layers (with momentum)
            "NORMAL" if passes layers 1-5 (without momentum)
            None if doesn't pass basic filters
        """
        # Layer 1: Price threshold
        if not self._meets_price_threshold_drop(current_price, price_1min_ago):
            return None

        # Layer 2: Volume spike requirement (MANDATORY)
        if not self._has_volume_spike(symbol, current_volume):
            return None

        # Layer 3: Quality filters
        if not self._is_high_quality_alert(symbol, current_price):
            return None

        # Layer 4: Cooldown check
        if not self._meets_cooldown(symbol):
            return None

        # Layer 5: Cross-alert deduplication
        if not self._no_recent_5min_alert(symbol):
            return None

        # Layers 1-5 passed → At least NORMAL priority
        priority = "NORMAL"

        # Layer 6: Momentum confirmation (drop acceleration) → Upgrade to HIGH priority
        if price_5min_ago and self._has_drop_momentum(current_price, price_1min_ago, price_5min_ago):
            priority = "HIGH"
            logger.debug(f"{symbol}: HIGH priority (momentum acceleration detected)")
        else:
            logger.debug(f"{symbol}: NORMAL priority (no momentum acceleration)")

        return priority

    def check_for_rise_1min(self, symbol: str, current_price: float,
                            price_1min_ago: float, current_volume: int,
                            oi: float = 0, price_5min_ago: float = None) -> Optional[str]:
        """
        Check if stock meets 1-min rise criteria with tiered priority.

        Args:
            symbol: Stock symbol
            current_price: Current price
            price_1min_ago: Price from 1 minute ago
            current_volume: Current trading volume
            oi: Open interest (optional)
            price_5min_ago: Price from 5 minutes ago (optional, for momentum check)

        Returns:
            "HIGH" if passes all 6 layers (with momentum)
            "NORMAL" if passes layers 1-5 (without momentum)
            None if doesn't pass basic filters
        """
        # Layer 1: Price threshold
        if not self._meets_price_threshold_rise(current_price, price_1min_ago):
            return None

        # Layer 2: Volume spike requirement (MANDATORY)
        if not self._has_volume_spike(symbol, current_volume):
            return None

        # Layer 3: Quality filters
        if not self._is_high_quality_alert(symbol, current_price):
            return None

        # Layer 4: Cooldown check
        if not self._meets_cooldown(symbol):
            return None

        # Layer 5: Cross-alert deduplication
        if not self._no_recent_5min_alert(symbol):
            return None

        # Layers 1-5 passed → At least NORMAL priority
        priority = "NORMAL"

        # Layer 6: Momentum confirmation (rise acceleration) → Upgrade to HIGH priority
        if price_5min_ago and self._has_rise_momentum(current_price, price_1min_ago, price_5min_ago):
            priority = "HIGH"
            logger.debug(f"{symbol}: HIGH priority (momentum acceleration detected)")
        else:
            logger.debug(f"{symbol}: NORMAL priority (no momentum acceleration)")

        return priority

    # ====================================
    # Layer 1: Price Threshold
    # ====================================

    def _meets_price_threshold_drop(self, current_price: float, price_1min_ago: float) -> bool:
        """Check if price drop meets 0.85% threshold"""
        change_pct = ((current_price - price_1min_ago) / price_1min_ago) * 100

        if change_pct >= -config.DROP_THRESHOLD_1MIN:
            logger.debug(f"Price drop {change_pct:.2f}% below threshold {config.DROP_THRESHOLD_1MIN}%")
            return False

        return True

    def _meets_price_threshold_rise(self, current_price: float, price_1min_ago: float) -> bool:
        """Check if price rise meets 0.85% threshold"""
        change_pct = ((current_price - price_1min_ago) / price_1min_ago) * 100

        if change_pct <= config.RISE_THRESHOLD_1MIN:
            logger.debug(f"Price rise {change_pct:.2f}% below threshold {config.RISE_THRESHOLD_1MIN}%")
            return False

        return True

    # ====================================
    # Layer 2: Volume Spike Requirement
    # ====================================

    def _has_volume_spike(self, symbol: str, current_volume: int) -> bool:
        """
        Check for volume spike using percentage-based multiplier (2.5x average).
        This is MANDATORY for all 1-min alerts.

        Uses ONLY percentage-based logic (no absolute minimum) because different stocks
        have vastly different normal trading volumes. For example:
        - Large-cap: 500K shares/min normal
        - Mid-cap: 50K shares/min normal
        - Small-cap: 5K shares/min normal

        A 2.5x spike is significant regardless of absolute volume.

        Args:
            symbol: Stock symbol
            current_volume: Current trading volume

        Returns:
            True if volume spike detected, False otherwise
        """
        # Get volume from 1 minute ago
        volume_data = self.price_cache.get_volume_data_1min(symbol)
        avg_volume = volume_data.get("avg_volume", 0)

        if avg_volume == 0:
            logger.debug(f"{symbol}: No previous volume data for comparison")
            return False

        # Check percentage-based condition only:
        # Current volume >= 2.5x average (percentage-based, fair for all stock sizes)
        if current_volume < config.VOLUME_SPIKE_MULTIPLIER_1MIN * avg_volume:
            logger.debug(f"{symbol}: Volume {current_volume:,} < {config.VOLUME_SPIKE_MULTIPLIER_1MIN}x avg {avg_volume:,}")
            return False

        logger.debug(f"{symbol}: Volume spike detected: {current_volume:,} = {current_volume/avg_volume:.1f}x avg {avg_volume:,}")
        return True

    # ====================================
    # Layer 3: Quality Filters
    # ====================================

    def _is_high_quality_alert(self, symbol: str, current_price: float) -> bool:
        """
        Filter out low-quality stocks.

        Checks:
        1. Price >= Rs. 50 (no penny stocks)
        2. Not in F&O ban list (if available)
        3. Market cap >= 1000 Cr (if available)

        Args:
            symbol: Stock symbol
            current_price: Current price

        Returns:
            True if high quality, False otherwise
        """
        # Check 1: Price >= Rs. 50 (no penny stocks)
        if current_price < 50:
            logger.debug(f"{symbol}: Price {current_price:.2f} < 50 (penny stock)")
            return False

        # Check 2: Not in F&O ban list
        # TODO: Add ban list check when available
        # if symbol in self.ban_list:
        #     logger.debug(f"{symbol}: In F&O ban list")
        #     return False

        # Check 3: Market cap >= 1000 Cr
        # TODO: Add market cap check when available
        # market_cap = self.get_market_cap(symbol)
        # if market_cap and market_cap < 1000:
        #     logger.debug(f"{symbol}: Market cap {market_cap} Cr < 1000 Cr")
        #     return False

        return True

    # ====================================
    # Layer 4: Cooldown Check
    # ====================================

    def _meets_cooldown(self, symbol: str) -> bool:
        """
        Check if 10-minute cooldown has passed since last 1-min alert.

        Args:
            symbol: Stock symbol

        Returns:
            True if cooldown passed, False otherwise
        """
        if not self.alert_history.should_send_alert(symbol, "1min",
                                                     cooldown_minutes=config.COOLDOWN_1MIN_ALERTS):
            logger.debug(f"{symbol}: Cooldown active (last alert within {config.COOLDOWN_1MIN_ALERTS} minutes)")
            return False

        return True

    # ====================================
    # Layer 5: Cross-Alert Deduplication
    # ====================================

    def _no_recent_5min_alert(self, symbol: str) -> bool:
        """
        Ensure no 5-min alert was sent in the last 3 minutes.
        Prevents duplicate alerts for the same movement.

        Args:
            symbol: Stock symbol

        Returns:
            True if no recent 5-min alert, False otherwise
        """
        last_5min = self.alert_history.get_last_alert_time(symbol, "5min")
        if last_5min:
            age = (datetime.now() - last_5min).total_seconds()
            if age <= 180:  # 3 minutes
                logger.debug(f"{symbol}: 5-min alert sent {age:.0f}s ago (< 3 min)")
                return False

        return True

    # ====================================
    # Layer 6: Momentum Confirmation
    # ====================================

    def _has_drop_momentum(self, current_price: float, price_1min_ago: float,
                           price_5min_ago: float) -> bool:
        """
        Check if drop is accelerating (momentum confirmation).
        Requires that the 1-minute drop rate is faster than the 4-minute average.

        This prevents alerts on temporary blips by ensuring sustained downward momentum.

        Args:
            current_price: Current price
            price_1min_ago: Price 1 minute ago
            price_5min_ago: Price 5 minutes ago

        Returns:
            True if drop is accelerating, False otherwise
        """
        # Calculate drop rate per minute
        drop_1min_rate = ((price_1min_ago - current_price) / price_1min_ago) * 100

        # Calculate average drop rate from 5min to 1min (4 minutes)
        drop_4min = ((price_5min_ago - price_1min_ago) / price_5min_ago) * 100
        drop_4min_rate = drop_4min / 4  # Average per minute

        # Require acceleration: current 1-min drop must be > 4-min average
        # This ensures the drop is getting faster, not slowing down
        if drop_1min_rate > drop_4min_rate * 1.3:  # 30% faster than recent average
            logger.debug(f"Drop accelerating: 1min={drop_1min_rate:.2f}%/min vs 4min_avg={drop_4min_rate:.2f}%/min")
            return True

        logger.debug(f"Drop NOT accelerating: 1min={drop_1min_rate:.2f}%/min <= 4min_avg={drop_4min_rate:.2f}%/min")
        return False

    def _has_rise_momentum(self, current_price: float, price_1min_ago: float,
                           price_5min_ago: float) -> bool:
        """
        Check if rise is accelerating (momentum confirmation).
        Requires that the 1-minute rise rate is faster than the 4-minute average.

        This prevents alerts on temporary spikes by ensuring sustained upward momentum.

        Args:
            current_price: Current price
            price_1min_ago: Price 1 minute ago
            price_5min_ago: Price 5 minutes ago

        Returns:
            True if rise is accelerating, False otherwise
        """
        # Calculate rise rate per minute
        rise_1min_rate = ((current_price - price_1min_ago) / price_1min_ago) * 100

        # Calculate average rise rate from 5min to 1min (4 minutes)
        rise_4min = ((price_1min_ago - price_5min_ago) / price_5min_ago) * 100
        rise_4min_rate = rise_4min / 4  # Average per minute

        # Require acceleration: current 1-min rise must be > 4-min average
        # This ensures the rise is getting faster, not slowing down
        if rise_1min_rate > rise_4min_rate * 1.3:  # 30% faster than recent average
            logger.debug(f"Rise accelerating: 1min={rise_1min_rate:.2f}%/min vs 4min_avg={rise_4min_rate:.2f}%/min")
            return True

        logger.debug(f"Rise NOT accelerating: 1min={rise_1min_rate:.2f}%/min <= 4min_avg={rise_4min_rate:.2f}%/min")
        return False

    # ====================================
    # Helper Methods
    # ====================================

    def get_drop_percentage(self, current_price: float, price_1min_ago: float) -> float:
        """Calculate drop percentage"""
        return ((price_1min_ago - current_price) / price_1min_ago) * 100

    def get_rise_percentage(self, current_price: float, price_1min_ago: float) -> float:
        """Calculate rise percentage"""
        return ((current_price - price_1min_ago) / price_1min_ago) * 100
