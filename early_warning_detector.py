#!/usr/bin/env python3
"""
Early Warning Detector - Pre-Alert System for 5-Min Alerts

Detects early momentum (0.5% move in 3-4 minutes) that often precedes
full 5-minute alerts (1.25% move). Gives 3-4 minute lead time for entry.

Based on analysis of historical alerts:
- At T-4: 48% of eventual 5-min alerts show 0.5% move
- At T-3: 65% show 0.5% move
- At T-2: 73% show 0.5% move

Key Design:
- Runs alongside RapidAlertDetector
- Sends lightweight "⚠️ PRE-ALERT" notifications
- 15-minute cooldown per stock (longer than 5-min alert cooldown)
- Suppresses pre-alert if 5-min alert was just sent

Author: Claude Opus 4.5
Date: 2026-02-09
"""

import logging
import time
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, List, Optional, Set, Tuple

import config
from quarterly_results_checker import get_results_checker, get_results_label

logger = logging.getLogger(__name__)


class EarlyWarningDetector:
    """
    Detects early momentum signals that precede 5-minute alerts.

    Sends pre-alert notifications when a stock shows 0.5% move in 3-4 minutes,
    giving traders lead time before the full 5-min alert triggers.
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

        # Configuration from config.py
        self.price_threshold = config.EARLY_WARNING_THRESHOLD  # Default: 1.0%
        self.lookback_minutes = config.EARLY_WARNING_LOOKBACK  # Default: 3 min
        self.cooldown_minutes = config.EARLY_WARNING_COOLDOWN  # Default: 15 min
        self.volume_multiplier = config.EARLY_WARNING_VOLUME_MULT  # Default: 1.2x

        # Filter flags
        self.require_obv = getattr(config, 'EARLY_WARNING_REQUIRE_OBV', True)
        self.require_oi = getattr(config, 'EARLY_WARNING_REQUIRE_OI', True)
        self.require_rsi = getattr(config, 'EARLY_WARNING_REQUIRE_RSI', True)
        self.require_vwap = getattr(config, 'EARLY_WARNING_REQUIRE_VWAP', True)

        # Track recently sent pre-alerts to avoid duplicates within session
        self._recent_prealerts: Set[str] = set()  # "SYMBOL_YYYY-MM-DD_HH:MM"

        # Cache for VWAP calculations (reset daily)
        self._vwap_cache: Dict[str, Tuple[float, str]] = {}  # symbol -> (vwap, date)

        # Alert start time: 9:25 AM (from config)
        self.alert_start_time = dt_time(config.MARKET_START_HOUR, config.MARKET_START_MINUTE)

        filters_enabled = []
        if self.require_obv: filters_enabled.append('OBV')
        if self.require_oi: filters_enabled.append('OI')
        if self.require_rsi: filters_enabled.append('RSI')
        if self.require_vwap: filters_enabled.append('VWAP')

        logger.info(f"EarlyWarningDetector initialized "
                   f"(threshold: {self.price_threshold}%, "
                   f"lookback: {self.lookback_minutes}min, "
                   f"filters: {'+'.join(filters_enabled) if filters_enabled else 'none'})")

    def _get_recent_history(self, symbol: str, minutes: int = 10) -> List[Dict]:
        """Get recent price/volume history for OBV calculation."""
        try:
            # Use the db's get_stock_history method if available
            if hasattr(self.db, 'get_stock_history'):
                return self.db.get_stock_history(symbol, minutes)

            # Fallback: query directly
            from datetime import datetime, timedelta
            cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:00')

            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT timestamp, price, volume
                FROM stock_quotes
                WHERE symbol = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (symbol, cutoff))

            return [{'timestamp': r[0], 'price': r[1], 'volume': r[2] or 0}
                    for r in cursor.fetchall()]
        except Exception as e:
            logger.debug(f"Failed to get history for {symbol}: {e}")
            return []

    def _calculate_obv(self, history: List[Dict]) -> List[float]:
        """Calculate OBV (On-Balance Volume) from price/volume history."""
        if len(history) < 2:
            return []

        obv = [0]
        for i in range(1, len(history)):
            prev_price = history[i-1].get('price', 0)
            curr_price = history[i].get('price', 0)
            volume = history[i].get('volume', 0) or 0

            if curr_price > prev_price:
                obv.append(obv[-1] + volume)
            elif curr_price < prev_price:
                obv.append(obv[-1] - volume)
            else:
                obv.append(obv[-1])

        return obv

    def _check_obv_confirmation(self, symbol: str, direction: str) -> Tuple[bool, str]:
        """
        Check if OBV confirms the price direction.

        Returns:
            (is_confirmed, pattern_type)
            - is_confirmed: True if OBV is moving in same direction as price
            - pattern_type: 'confirmation', 'divergence', or 'neutral'
        """
        history = self._get_recent_history(symbol, 10)

        if len(history) < 5:
            return True, 'neutral'  # Not enough data, allow signal

        prices = [h['price'] for h in history]
        obv = self._calculate_obv(history)

        if len(obv) < 5:
            return True, 'neutral'

        # Calculate OBV slope over last 5 points
        obv_recent = obv[-5:]
        n = len(obv_recent)
        x_mean = (n - 1) / 2
        y_mean = sum(obv_recent) / n

        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(obv_recent))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        obv_slope = numerator / denominator if denominator != 0 else 0

        # Normalize slope
        avg_change = sum(abs(obv[i] - obv[i-1]) for i in range(1, len(obv))) / (len(obv) - 1) if len(obv) > 1 else 1
        if avg_change > 0:
            normalized_slope = obv_slope / avg_change
        else:
            normalized_slope = 0

        # Check confirmation
        obv_up = normalized_slope > 0.1
        obv_down = normalized_slope < -0.1

        if direction == 'drop':
            # For drops, OBV should be falling (confirmation)
            if obv_down:
                return True, 'confirmation'
            elif obv_up:
                return False, 'divergence'
        else:  # rise
            # For rises, OBV should be rising (confirmation)
            if obv_up:
                return True, 'confirmation'
            elif obv_down:
                return False, 'divergence'

        return True, 'neutral'

    def _check_oi_confirmation(self, symbol: str, direction: str, quote_data: Dict) -> Tuple[bool, str]:
        """
        Check if OI pattern confirms the price move.

        OI Patterns:
        - Long Buildup: Price ↑ + OI ↑ (strong bullish)
        - Short Buildup: Price ↓ + OI ↑ (strong bearish)
        - Short Covering: Price ↑ + OI ↓ (weak rally, likely reversal)
        - Long Unwinding: Price ↓ + OI ↓ (weak fall, likely reversal)

        Returns:
            (is_confirmed, pattern_type)
        """
        try:
            current_oi = quote_data.get('oi', 0)
            if not current_oi or current_oi <= 0:
                return True, 'no_oi_data'  # Allow if no OI data

            # Get day-start OI from the database
            today = datetime.now().strftime('%Y-%m-%d')
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT oi FROM stock_quotes
                WHERE symbol = ? AND date(timestamp) = ?
                AND time(timestamp) >= '09:15:00'
                ORDER BY timestamp ASC
                LIMIT 1
            """, (symbol, today))

            row = cursor.fetchone()
            if not row or not row[0]:
                return True, 'no_oi_data'

            day_start_oi = row[0]
            oi_change_pct = ((current_oi - day_start_oi) / day_start_oi) * 100

            # OI increasing = new positions being built
            # OI decreasing = positions being closed
            oi_increasing = oi_change_pct > 0.5  # At least 0.5% increase
            oi_decreasing = oi_change_pct < -0.5  # At least 0.5% decrease

            if direction == 'drop':
                # For drops:
                # - Short Buildup (OI ↑) = Strong signal, institutions adding shorts
                # - Long Unwinding (OI ↓) = Weak signal, just position closing
                if oi_increasing:
                    return True, 'short_buildup'
                elif oi_decreasing:
                    return False, 'long_unwinding'  # Reject weak signals
                else:
                    return True, 'neutral'
            else:  # rise
                # For rises:
                # - Long Buildup (OI ↑) = Strong signal, institutions adding longs
                # - Short Covering (OI ↓) = Weak signal, just shorts closing
                if oi_increasing:
                    return True, 'long_buildup'
                elif oi_decreasing:
                    return False, 'short_covering'  # Reject weak signals
                else:
                    return True, 'neutral'

        except Exception as e:
            logger.debug(f"OI check failed for {symbol}: {e}")
            return True, 'error'

    def _check_rsi_momentum(self, symbol: str, direction: str) -> Tuple[bool, float]:
        """
        Check if RSI confirms momentum has room to continue.

        For drops: RSI should be > 40 (room to fall, not already oversold)
        For rises: RSI should be < 60 (room to rise, not already overbought)

        Returns:
            (is_confirmed, rsi_value)
        """
        try:
            history = self._get_recent_history(symbol, 15)  # Need ~14 points for RSI

            if len(history) < 10:
                return True, 50.0  # Allow if insufficient data

            prices = [h['price'] for h in history if h.get('price')]
            if len(prices) < 10:
                return True, 50.0

            # Calculate RSI(9)
            gains = []
            losses = []
            for i in range(1, len(prices)):
                change = prices[i] - prices[i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))

            # Use last 9 periods
            period = min(9, len(gains))
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period

            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

            if direction == 'drop':
                # For drops: RSI should have room to fall (not already oversold)
                # Accept if RSI > 40 (plenty of room to fall)
                return rsi > 40, rsi
            else:  # rise
                # For rises: RSI should have room to rise (not already overbought)
                # Accept if RSI < 60 (plenty of room to rise)
                return rsi < 60, rsi

        except Exception as e:
            logger.debug(f"RSI check failed for {symbol}: {e}")
            return True, 50.0

    def _calculate_vwap(self, symbol: str) -> Optional[float]:
        """
        Calculate intraday VWAP from today's data.

        VWAP = Σ(Price × Volume) / Σ(Volume)
        """
        try:
            today = datetime.now().strftime('%Y-%m-%d')

            # Check cache
            if symbol in self._vwap_cache:
                cached_vwap, cached_date = self._vwap_cache[symbol]
                if cached_date == today:
                    return cached_vwap

            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT price, volume FROM stock_quotes
                WHERE symbol = ? AND date(timestamp) = ?
                AND time(timestamp) >= '09:15:00'
                ORDER BY timestamp ASC
            """, (symbol, today))

            rows = cursor.fetchall()
            if not rows:
                return None

            total_pv = 0  # Price × Volume
            total_volume = 0

            for price, volume in rows:
                if price and volume and price > 0 and volume > 0:
                    total_pv += price * volume
                    total_volume += volume

            if total_volume == 0:
                return None

            vwap = total_pv / total_volume

            # Cache result
            self._vwap_cache[symbol] = (vwap, today)

            return vwap

        except Exception as e:
            logger.debug(f"VWAP calculation failed for {symbol}: {e}")
            return None

    def _check_vwap_position(self, symbol: str, current_price: float, direction: str) -> Tuple[bool, str]:
        """
        Check price position relative to VWAP.

        For drops: Price should be BELOW VWAP (already showing weakness)
        For rises: Price should be ABOVE VWAP (already showing strength)

        Returns:
            (is_confirmed, position_str)
        """
        vwap = self._calculate_vwap(symbol)

        if vwap is None:
            return True, 'no_vwap'

        position = 'above' if current_price > vwap else 'below'
        deviation_pct = ((current_price - vwap) / vwap) * 100

        if direction == 'drop':
            # For drops: Price should be below VWAP (weakness confirmed)
            # Small buffer: allow if within 0.2% of VWAP
            return current_price <= vwap * 1.002, position
        else:  # rise
            # For rises: Price should be above VWAP (strength confirmed)
            # Small buffer: allow if within 0.2% of VWAP
            return current_price >= vwap * 0.998, position

    def detect_all(self, current_quotes: Dict[str, Dict]) -> Dict:
        """
        Detect early warning signals for all stocks.

        Args:
            current_quotes: Dict of {symbol: {price, volume, oi, ...}} from just-collected data

        Returns:
            Dict with stats: {prealerts_sent, signals_detected, stocks_checked, execution_ms}
        """
        start_time = time.time()

        stats = {
            'prealerts_sent': 0,
            'signals_detected': 0,
            'stocks_checked': 0,
            'execution_ms': 0,
            'alerted_symbols': []  # for P&L tracker
        }

        # Skip before market stabilization
        current_time = datetime.now().time()
        if current_time < self.alert_start_time:
            return stats

        if not current_quotes:
            return stats

        symbols = list(current_quotes.keys())

        # Batch query: Get prices from N minutes ago
        quotes_ago = self.db.get_stock_quotes_at_batch(symbols, minutes_ago=self.lookback_minutes)

        if not quotes_ago:
            logger.debug(f"EarlyWarningDetector: No {self.lookback_minutes}-min-ago data")
            return stats

        now = datetime.now()

        for symbol, quote_data in current_quotes.items():
            try:
                stats['stocks_checked'] += 1

                current_price = quote_data.get('price')
                current_volume = quote_data.get('volume', 0)

                if not current_price or current_price <= 0:
                    continue

                prev_data = quotes_ago.get(symbol)
                if not prev_data:
                    continue

                prev_price = prev_data.get('price')
                prev_volume = prev_data.get('volume', 0)

                if not prev_price or prev_price <= 0:
                    continue

                # Check volume trend (optional, lower bar)
                has_volume_signal = True
                volume_ratio = 0
                if prev_volume > 0 and current_volume > 0:
                    volume_ratio = current_volume / prev_volume
                    has_volume_signal = volume_ratio >= self.volume_multiplier

                # Calculate price changes
                drop_pct = ((prev_price - current_price) / prev_price) * 100
                rise_pct = ((current_price - prev_price) / prev_price) * 100

                # Check for DROP pre-alert
                if drop_pct >= self.price_threshold and has_volume_signal:
                    stats['signals_detected'] += 1

                    # Filter 1: OBV confirmation (if enabled)
                    obv_confirmed, obv_pattern = True, 'neutral'
                    if self.require_obv:
                        obv_confirmed, obv_pattern = self._check_obv_confirmation(symbol, 'drop')
                        if not obv_confirmed:
                            logger.debug(f"EarlyWarning: {symbol} DROP skipped - OBV divergence")
                            continue

                    # Filter 2: OI Pattern (if enabled)
                    oi_confirmed, oi_pattern = True, 'neutral'
                    if self.require_oi:
                        oi_confirmed, oi_pattern = self._check_oi_confirmation(symbol, 'drop', quote_data)
                        if not oi_confirmed:
                            logger.debug(f"EarlyWarning: {symbol} DROP skipped - {oi_pattern}")
                            continue

                    # Filter 3: RSI Momentum (if enabled)
                    rsi_confirmed, rsi_value = True, 50.0
                    if self.require_rsi:
                        rsi_confirmed, rsi_value = self._check_rsi_momentum(symbol, 'drop')
                        if not rsi_confirmed:
                            logger.debug(f"EarlyWarning: {symbol} DROP skipped - RSI={rsi_value:.0f} (oversold)")
                            continue

                    # Filter 4: VWAP Position (if enabled)
                    vwap_confirmed, vwap_pos = True, 'neutral'
                    if self.require_vwap:
                        vwap_confirmed, vwap_pos = self._check_vwap_position(symbol, current_price, 'drop')
                        if not vwap_confirmed:
                            logger.debug(f"EarlyWarning: {symbol} DROP skipped - price above VWAP")
                            continue

                    if self._should_send_prealert(symbol, "drop", now):
                        success = self._send_prealert(
                            symbol=symbol,
                            direction="DROP",
                            change_pct=drop_pct,
                            current_price=current_price,
                            prev_price=prev_price,
                            volume_ratio=volume_ratio,
                            obv_pattern=obv_pattern,
                            oi_pattern=oi_pattern,
                            rsi_value=rsi_value,
                            vwap_position=vwap_pos
                        )
                        if success:
                            stats['prealerts_sent'] += 1
                            stats['alerted_symbols'].append({
                                'symbol': symbol, 'direction': 'drop',
                                'price': current_price, 'time': now.isoformat(),
                                'alert_type': 'prealert', 'alert_count': 1
                            })
                            self._record_prealert(symbol, "drop", now)

                # Check for RISE pre-alert
                if rise_pct >= self.price_threshold and has_volume_signal:
                    stats['signals_detected'] += 1

                    # Filter 1: OBV confirmation (if enabled)
                    obv_confirmed, obv_pattern = True, 'neutral'
                    if self.require_obv:
                        obv_confirmed, obv_pattern = self._check_obv_confirmation(symbol, 'rise')
                        if not obv_confirmed:
                            logger.debug(f"EarlyWarning: {symbol} RISE skipped - OBV divergence")
                            continue

                    # Filter 2: OI Pattern (if enabled)
                    oi_confirmed, oi_pattern = True, 'neutral'
                    if self.require_oi:
                        oi_confirmed, oi_pattern = self._check_oi_confirmation(symbol, 'rise', quote_data)
                        if not oi_confirmed:
                            logger.debug(f"EarlyWarning: {symbol} RISE skipped - {oi_pattern}")
                            continue

                    # Filter 3: RSI Momentum (if enabled)
                    rsi_confirmed, rsi_value = True, 50.0
                    if self.require_rsi:
                        rsi_confirmed, rsi_value = self._check_rsi_momentum(symbol, 'rise')
                        if not rsi_confirmed:
                            logger.debug(f"EarlyWarning: {symbol} RISE skipped - RSI={rsi_value:.0f} (overbought)")
                            continue

                    # Filter 4: VWAP Position (if enabled)
                    vwap_confirmed, vwap_pos = True, 'neutral'
                    if self.require_vwap:
                        vwap_confirmed, vwap_pos = self._check_vwap_position(symbol, current_price, 'rise')
                        if not vwap_confirmed:
                            logger.debug(f"EarlyWarning: {symbol} RISE skipped - price below VWAP")
                            continue

                    if self._should_send_prealert(symbol, "rise", now):
                        success = self._send_prealert(
                            symbol=symbol,
                            direction="RISE",
                            change_pct=rise_pct,
                            current_price=current_price,
                            prev_price=prev_price,
                            volume_ratio=volume_ratio,
                            obv_pattern=obv_pattern,
                            oi_pattern=oi_pattern,
                            rsi_value=rsi_value,
                            vwap_position=vwap_pos
                        )
                        if success:
                            stats['prealerts_sent'] += 1
                            stats['alerted_symbols'].append({
                                'symbol': symbol, 'direction': 'rise',
                                'price': current_price, 'time': now.isoformat(),
                                'alert_type': 'prealert', 'alert_count': 1
                            })
                            self._record_prealert(symbol, "rise", now)

            except Exception as e:
                logger.error(f"EarlyWarningDetector: Error checking {symbol}: {e}")

        stats['execution_ms'] = int((time.time() - start_time) * 1000)

        if stats['prealerts_sent'] > 0:
            logger.info(f"EarlyWarningDetector: {stats['prealerts_sent']} pre-alerts sent, "
                       f"{stats['signals_detected']} signals detected, "
                       f"{stats['stocks_checked']} stocks in {stats['execution_ms']}ms")

        return stats

    def _should_send_prealert(self, symbol: str, direction: str, now: datetime) -> bool:
        """
        Check if we should send a pre-alert.

        Conditions:
        1. Not in cooldown period for this stock
        2. No 5-min alert was sent recently for this stock
        3. Not a duplicate within this session
        """
        # Check cooldown using alert history (separate alert type for pre-alerts)
        alert_type = f"prealert_{direction}"
        if not self.alert_history.should_send_alert(symbol, alert_type, cooldown_minutes=self.cooldown_minutes):
            return False

        # Check if 5-min alert was sent in last 5 minutes (avoid noise after main alert)
        # IMPORTANT: Use read-only check (get_last_alert_time) instead of should_send_alert,
        # because should_send_alert has a side effect of recording the current time,
        # which would poison the cooldown for the actual 5-min rapid alert detector.
        five_min_type = "5min" if direction == "drop" else "5min_rise"
        last_5min_alert = self.alert_history.get_last_alert_time(symbol, five_min_type)
        if last_5min_alert and (now - last_5min_alert) < timedelta(minutes=5):
            logger.debug(f"Skipping pre-alert for {symbol} - recent 5-min alert")
            return False

        # Check session duplicates
        key = f"{symbol}_{now.strftime('%Y-%m-%d_%H')}"
        if key in self._recent_prealerts:
            return False

        return True

    def _record_prealert(self, symbol: str, direction: str, now: datetime):
        """Record that we sent a pre-alert."""
        # Use alert history for persistent tracking
        alert_type = f"prealert_{direction}"
        self.alert_history.should_send_alert(symbol, alert_type, cooldown_minutes=self.cooldown_minutes)

        # Track in session memory
        key = f"{symbol}_{now.strftime('%Y-%m-%d_%H')}"
        self._recent_prealerts.add(key)

        # Clean old entries (keep last hour only)
        cutoff = (now - timedelta(hours=1)).strftime('%Y-%m-%d_%H')
        self._recent_prealerts = {k for k in self._recent_prealerts
                                   if k.split('_')[1] + '_' + k.split('_')[2] >= cutoff}

    def _send_prealert(self, symbol: str, direction: str, change_pct: float,
                       current_price: float, prev_price: float, volume_ratio: float,
                       obv_pattern: str = 'neutral', oi_pattern: str = 'neutral',
                       rsi_value: float = 50.0, vwap_position: str = 'neutral') -> bool:
        """
        Send pre-alert notification via Telegram.
        """
        try:
            # Format prices
            if current_price >= 1000:
                price_str = f"₹{current_price:,.0f}"
                prev_price_str = f"₹{prev_price:,.0f}"
            else:
                price_str = f"₹{current_price:.2f}"
                prev_price_str = f"₹{prev_price:.2f}"

            # Emoji based on direction
            emoji = "📉" if direction == "DROP" else "📈"
            arrow = "↓" if direction == "DROP" else "↑"

            # Volume indicator
            vol_str = f"{volume_ratio:.1f}x" if volume_ratio > 0 else "-"

            # Build confirmation indicators line
            confirmations = []

            # OBV indicator
            if obv_pattern == 'confirmation':
                confirmations.append("OBV✓")

            # OI indicator
            if oi_pattern in ('short_buildup', 'long_buildup'):
                oi_label = "Short Buildup" if oi_pattern == 'short_buildup' else "Long Buildup"
                confirmations.append(f"OI:{oi_label}")

            # RSI indicator
            if rsi_value > 0:
                confirmations.append(f"RSI:{rsi_value:.0f}")

            # VWAP indicator
            if vwap_position in ('above', 'below'):
                vwap_label = "↑VWAP" if vwap_position == 'above' else "↓VWAP"
                confirmations.append(vwap_label)

            # Format confirmations line
            confirm_str = " | ".join(confirmations) if confirmations else ""
            confirm_line = f"🎯 {confirm_str}\n" if confirm_str else ""

            # Check for quarterly results
            results_label = get_results_label(symbol)
            results_line = f"<b>{results_label}</b>\n" if results_label else ""

            # Build message (keep it short - this is a pre-alert)
            message = (
                f"⚠️ <b>PRE-ALERT: {symbol}</b> ⚠️\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{results_line}"
                f"{emoji} Early {direction} Signal\n"
                f"{arrow} <b>{change_pct:.2f}%</b> in {self.lookback_minutes} min\n\n"
                f"💰 {prev_price_str} → {price_str}\n"
                f"📊 Vol: {vol_str}\n"
                f"{confirm_line}\n"
                f"<i>Watch for 5-min alert in 1-3 min</i>\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

            # Send via base notifier method
            return self._send_telegram_message(message)

        except Exception as e:
            logger.error(f"EarlyWarningDetector: Failed to send pre-alert for {symbol}: {e}")
            return False

    def _send_telegram_message(self, message: str) -> bool:
        """Send message to Telegram using the notifier's connection."""
        try:
            import requests

            url = f"https://api.telegram.org/bot{self.telegram.bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram.channel_id,
                "text": message,
                "parse_mode": "HTML"
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return True

        except Exception as e:
            logger.error(f"EarlyWarningDetector: Telegram send failed: {e}")
            return False
