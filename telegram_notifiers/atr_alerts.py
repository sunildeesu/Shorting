"""ATR breakout alert messages — volatility-contraction breakout signals (long/buy)."""

import logging
from datetime import datetime

import config
from telegram_notifiers.base_notifier import BaseNotifier
from telegram_notifiers.formatting_helpers import format_rsi_section

logger = logging.getLogger(__name__)


class ATRAlertNotifier(BaseNotifier):
    """Formats and sends ATR breakout alerts to the main Telegram channel."""

    def send_atr_breakout(self, analysis: dict) -> bool:
        """Build and send an ATR breakout alert message to the main channel."""
        message = self._format_message(analysis)
        return self._send_message(message)

    def _format_message(self, analysis: dict) -> str:
        """Format ATR breakout alert message for Telegram (HTML)."""
        symbol = analysis['symbol']
        today_open = analysis['today_open']
        current_price = analysis['current_price']
        entry_level = analysis['entry_level']
        stop_loss = analysis['stop_loss']
        atr_20 = analysis['atr_20']
        atr_30 = analysis['atr_30']
        volatility_filter = "✅ PASSED" if analysis['volatility_filter_passed'] else "❌ FAILED"
        breakout_distance = analysis['breakout_distance']
        risk_amount = analysis['risk_amount']
        risk_percent = analysis['risk_percent']
        market_cap_cr = analysis['market_cap_cr']
        volume = analysis['volume']
        is_friday = analysis['is_friday']

        # Format volume in lakhs
        volume_lakhs = volume / 100000

        # Build message
        message = "🎯🎯🎯 ATR BREAKOUT SIGNAL 🎯🎯🎯\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "⚡ VOLATILITY CONTRACTION BREAKOUT ⚡\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        message += "📢 <b>RECOMMENDATION:</b> 🟢 <b>BUY / LONG</b>\n\n"

        message += f"📊 Stock: <b>{symbol}</b>\n"
        if market_cap_cr:
            message += f"💰 Market Cap: ₹{market_cap_cr:,.0f} Cr\n"
        message += "\n"

        message += "📈 <b>Breakout Details:</b>\n"
        message += f"   Today's Open: ₹{today_open:.2f}\n"
        message += f"   Entry Level: ₹{entry_level:.2f} (O + {config.ATR_ENTRY_MULTIPLIER}×ATR)\n"
        message += f"   Current Price: <b>₹{current_price:.2f}</b> ✅\n"
        message += f"   Breakout: +₹{breakout_distance:.2f} above entry\n"
        message += "\n"

        message += "📊 <b>ATR Analysis:</b>\n"
        message += f"   ATR(20): ₹{atr_20:.2f}\n"
        message += f"   ATR(30): ₹{atr_30:.2f}\n"
        message += f"   Volatility Filter: {volatility_filter}\n"
        if analysis['volatility_filter_passed']:
            message += "   💡 Volatility contracting (ATR20 &lt; ATR30)\n"
        message += "\n"

        # Show all filter statuses
        message += "🔍 <b>Quality Filters:</b>\n"
        price_filter = "✅ PASSED" if analysis['price_filter_passed'] else "❌ FAILED"
        volume_filter = "✅ PASSED" if analysis['volume_filter_passed'] else "❌ FAILED"
        message += f"   Price Trend: {price_filter}"
        if analysis['ma_20']:
            message += f" (&gt;₹{analysis['ma_20']:.2f} MA20)"
        message += "\n"
        message += f"   Volume Confirm: {volume_filter}"
        if analysis['avg_volume']:
            vol_multiplier = volume / analysis['avg_volume']
            message += f" ({vol_multiplier:.1f}× avg)"
        message += "\n"
        message += "\n"

        message += "🛡️ <b>Risk Management:</b>\n"
        message += f"   Stop Loss: ₹{stop_loss:.2f}\n"
        message += f"   Risk: ₹{risk_amount:.2f} ({risk_percent:.2f}%)\n"
        message += f"   R:R Ratio: 1:2 (₹{risk_amount * 2:.2f} target)\n"
        message += "\n"

        message += "📊 <b>Volume:</b>\n"
        message += f"   Today: {volume_lakhs:.2f}L shares\n"

        # RSI Momentum Analysis (shared helper — HTML-safe)
        rsi_analysis = analysis.get('rsi_analysis')
        if rsi_analysis:
            message += format_rsi_section(rsi_analysis)

        message += "\n"

        # Friday exit warning
        if is_friday and config.ATR_FRIDAY_EXIT:
            message += "⚠️ <b>FRIDAY EXIT RULE ACTIVE</b> ⚠️\n"
            message += "   Close all positions before market close!\n"
            message += "\n"

        message += f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

        return message
