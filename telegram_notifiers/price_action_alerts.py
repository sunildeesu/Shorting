"""Price action alert notifier for candlestick pattern detection."""
from typing import Optional, Dict
import logging
from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class PriceActionAlertNotifier(BaseNotifier):
    """Handles price action pattern alerts."""

    def send_price_action_alert(
        self,
        symbol: str,
        pattern_name: str,
        pattern_type: str,
        confidence_score: float,
        entry_price: float,
        target: Optional[float],
        stop_loss: Optional[float],
        current_price: float,
        pattern_details: Optional[Dict] = None,
        market_regime: str = None,
        market_cap_cr: float = None
    ) -> bool:
        """
        Send price action pattern alert to Telegram.

        Args:
            symbol: Stock symbol
            pattern_name: Pattern name (e.g., "Bullish Engulfing")
            pattern_type: 'bullish', 'bearish', or 'neutral'
            confidence_score: 0-10 confidence score
            entry_price: Suggested entry price
            target: Target price (if applicable)
            stop_loss: Stop loss price (if applicable)
            current_price: Current market price
            pattern_details: Full pattern detection details dict
            market_regime: Current market regime
            market_cap_cr: Market cap in crores (optional)

        Returns:
            True if sent successfully, False otherwise
        """
        # Extract additional details from pattern_details if provided
        volume_ratio = pattern_details.get('volume_ratio', 0) if pattern_details else 0
        pattern_description = pattern_details.get('pattern_description', '') if pattern_details else ''
        candle_data = pattern_details.get('candle_data', {}) if pattern_details else {}
        confidence_breakdown = pattern_details.get('confidence_breakdown') if pattern_details else None

        message = self._format_price_action_message(
            symbol, pattern_name, pattern_type, confidence_score,
            entry_price, target, stop_loss, current_price, volume_ratio,
            pattern_description, candle_data, market_regime,
            confidence_breakdown, market_cap_cr
        )

        return self._send_message(message)

    def _format_price_action_message(
        self,
        symbol: str,
        pattern_name: str,
        pattern_type: str,
        confidence_score: float,
        entry_price: float,
        target: Optional[float],
        stop_loss: Optional[float],
        current_price: float,
        volume_ratio: float,
        pattern_description: str,
        candle_data: Dict,
        market_regime: str,
        confidence_breakdown: Optional[Dict],
        market_cap_cr: Optional[float] = None
    ) -> str:
        """Format price action alert message."""

        # Remove .NS suffix
        display_symbol = symbol.replace('.NS', '')

        # Determine emoji based on pattern type
        if pattern_type == 'bullish':
            type_emoji = "🟢"
            type_label = "BULLISH PATTERN"
            signal_emoji = "📈"
        elif pattern_type == 'bearish':
            type_emoji = "🔴"
            type_label = "BEARISH PATTERN"
            signal_emoji = "📉"
        else:
            type_emoji = "⚪"
            type_label = "NEUTRAL PATTERN"
            signal_emoji = "📊"

        # Confidence emoji
        if confidence_score >= 8.5:
            conf_emoji = "🔥🔥🔥"
        elif confidence_score >= 8.0:
            conf_emoji = "🔥🔥"
        elif confidence_score >= 7.5:
            conf_emoji = "🔥"
        else:
            conf_emoji = "✓"

        # Header
        message = (
            f"{type_emoji}{type_emoji}{type_emoji} <b>PRICE ACTION ALERT</b> {type_emoji}{type_emoji}{type_emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{signal_emoji} <b>{type_label}</b> {signal_emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        # Time
        from market_utils import get_current_ist_time
        current_time = get_current_ist_time()
        time_str = current_time.strftime("%I:%M %p")

        # Stock info
        message += (
            f"📊 <b>Stock:</b> {display_symbol}\n"
            f"⏰ <b>Time:</b> {time_str}\n"
            f"🌐 <b>Market:</b> {market_regime}\n\n"
        )

        # Pattern details
        message += (
            f"🎯 <b>PATTERN DETECTED</b>\n"
            f"   Pattern: <b>{pattern_name}</b>\n"
            f"   Type: {type_emoji} {pattern_type.upper()}\n"
            f"   Confidence: <b>{confidence_score:.1f}/10</b> {conf_emoji}\n"
            f"   {pattern_description}\n\n"
        )

        # Current candle OHLCV
        curr = candle_data.get('curr_candle', {})
        if curr:
            message += (
                f"📊 <b>CURRENT 5-MIN CANDLE</b>\n"
                f"   Open:   ₹{curr['open']:.2f}\n"
                f"   High:   ₹{curr['high']:.2f}\n"
                f"   Low:    ₹{curr['low']:.2f}\n"
                f"   Close:  ₹{curr['close']:.2f}\n"
                f"   Volume: {curr['volume']:,} ({volume_ratio:.1f}x avg)\n\n"
            )

        # Previous candle (if relevant)
        prev = candle_data.get('prev_candle')
        if prev:
            message += (
                f"📉 <b>PREVIOUS CANDLE</b>\n"
                f"   O: ₹{prev['open']:.2f} | H: ₹{prev['high']:.2f} | "
                f"L: ₹{prev['low']:.2f} | C: ₹{prev['close']:.2f}\n\n"
            )

        # Trade setup
        if target and stop_loss:
            risk = abs(entry_price - stop_loss)
            reward = abs(target - entry_price)
            rr_ratio = reward / risk if risk > 0 else 0

            target_pct = ((target - entry_price) / entry_price * 100)
            stop_pct = ((stop_loss - entry_price) / entry_price * 100)

            # Calculate remaining move to target
            remaining_to_target = target - current_price
            remaining_pct = (remaining_to_target / current_price * 100) if current_price > 0 else 0

            message += (
                f"💰 <b>TRADE SETUP</b>\n"
                f"   Current: ₹{current_price:.2f} 🔴\n"
                f"   Entry:   ₹{entry_price:.2f}\n"
                f"   Target:  ₹{target:.2f} ({target_pct:+.1f}% from entry | {remaining_pct:+.1f}% remaining)\n"
                f"   Stop:    ₹{stop_loss:.2f} ({stop_pct:+.1f}%)\n"
                f"   R:R Ratio: 1:{rr_ratio:.1f}\n\n"
            )

        # Confidence breakdown (optional)
        if confidence_breakdown:
            message += "🔍 <b>CONFIDENCE BREAKDOWN</b>\n"
            for component, score in confidence_breakdown.items():
                component_name = component.replace('_', ' ').title()
                message += f"   • {component_name}: {score:.1f}\n"
            message += "\n"

        # Footer
        message += (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <b>Disclaimer:</b> Technical pattern only. Use proper risk management.\n"
            "💡 Always verify with price action and volume before entry."
        )

        return message
