import requests
from typing import Optional, List, Dict
from datetime import datetime
import config
import logging
from alert_excel_logger import AlertExcelLogger

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """Handles sending notifications to Telegram channel"""

    def __init__(self):
        self.bot_token = config.TELEGRAM_BOT_TOKEN
        self.channel_id = config.TELEGRAM_CHANNEL_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

        if not self.bot_token or not self.channel_id:
            raise ValueError("Telegram bot token and channel ID must be set in .env file")

        # Initialize Excel logger if enabled
        self.excel_logger = None
        if config.ENABLE_EXCEL_LOGGING:
            try:
                self.excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
                logger.info("Alert Excel logging enabled")
            except Exception as e:
                logger.error(f"Failed to initialize Excel logger: {e}")
                self.excel_logger = None

    def send_alert(self, symbol: str, drop_percent: float, current_price: float,
                   previous_price: float, alert_type: str = "10min",
                   volume_data: dict = None, market_cap_cr: float = None,
                   rsi_analysis: dict = None, oi_analysis: dict = None,
                   sector_context: dict = None) -> bool:
        """
        Send a stock drop alert to Telegram channel

        Args:
            symbol: Stock symbol
            drop_percent: Percentage drop (positive number)
            current_price: Current stock price
            previous_price: Previous stock price
            alert_type: Type of alert ("10min", "30min", "volume_spike")
            volume_data: Optional volume data dict with current_volume, avg_volume
            market_cap_cr: Optional market cap in crores
            rsi_analysis: Optional RSI analysis dict with RSI values and crossovers
            oi_analysis: Optional OI analysis dict with pattern and signal
            sector_context: Optional sector context dict with sector performance

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_alert_message(
            symbol, drop_percent, current_price, previous_price, alert_type, volume_data, market_cap_cr, rsi_analysis, oi_analysis, sector_context
        )
        telegram_success = self._send_message(message)

        # Log to Excel if enabled
        if self.excel_logger:
            try:
                self.excel_logger.log_alert(
                    symbol=symbol,
                    alert_type=alert_type,
                    drop_percent=drop_percent,
                    current_price=current_price,
                    previous_price=previous_price,
                    volume_data=volume_data,
                    market_cap_cr=market_cap_cr,
                    telegram_sent=telegram_success,
                    rsi_analysis=rsi_analysis,
                    oi_analysis=oi_analysis
                )
            except Exception as e:
                logger.error(f"Failed to log alert to Excel: {e}")

        return telegram_success

    def send_1min_alert(self, symbol: str, direction: str, current_price: float,
                        previous_price: float, change_percent: float,
                        volume_data: dict = None, market_cap_cr: float = None,
                        rsi_analysis: dict = None, oi_analysis: dict = None,
                        priority: str = "NORMAL") -> bool:
        """
        Send a 1-minute ultra-fast alert to Telegram channel.

        Args:
            symbol: Stock symbol
            direction: "drop" or "rise"
            current_price: Current stock price
            previous_price: Price from 1 minute ago
            change_percent: Percentage change (absolute value)
            volume_data: Volume data dict with current_volume, avg_volume, spike_multiplier
            market_cap_cr: Market cap in crores
            rsi_analysis: Optional RSI analysis dict
            oi_analysis: Optional OI analysis dict
            priority: "HIGH" or "NORMAL"

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_1min_alert_message(
            symbol, direction, current_price, previous_price, change_percent,
            volume_data, market_cap_cr, rsi_analysis, oi_analysis, priority
        )
        telegram_success = self._send_message(message)

        # Excel logging is handled by onemin_monitor.py
        # (we don't duplicate it here to avoid circular dependencies)

        return telegram_success

    def _format_1min_alert_message(self, symbol: str, direction: str,
                                     current_price: float, previous_price: float,
                                     change_percent: float, volume_data: dict = None,
                                     market_cap_cr: float = None, rsi_analysis: dict = None,
                                     oi_analysis: dict = None, priority: str = "NORMAL") -> str:
        """
        Format 1-minute alert message with ultra-fast alert branding.

        Args:
            symbol: Stock symbol
            direction: "drop" or "rise"
            current_price: Current price
            previous_price: Price from 1 minute ago
            change_percent: Percentage change (absolute value)
            volume_data: Volume data
            market_cap_cr: Market cap in crores
            rsi_analysis: Optional RSI analysis
            oi_analysis: Optional OI analysis
            priority: "HIGH" or "NORMAL"

        Returns:
            Formatted message string
        """
        # Remove .NS suffix for display
        display_symbol = symbol.replace('.NS', '')

        # Determine emoji and header based on direction
        if direction == "drop":
            emoji = "📉"
            direction_text = "DROP"
            direction_color = "🔴"
        else:
            emoji = "📈"
            direction_text = "RISE"
            direction_color = "🟢"

        # Priority badge
        if priority == "HIGH":
            priority_badge = "🔥🔥 <b>HIGH PRIORITY</b> 🔥🔥\n"
            priority_note = "(Strong momentum acceleration detected)"
        else:
            priority_badge = "⚡ <b>NORMAL PRIORITY</b> ⚡\n"
            priority_note = "(Fast move without acceleration)"

        # Ultra-fast alert header
        header = (
            "⚡⚡⚡ <b>1-MIN ULTRA-FAST ALERT</b> ⚡⚡⚡\n"
            f"{priority_badge}"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} <b>{direction_color} {direction_text} DETECTED {direction_color}</b> {emoji}\n"
            f"<i>{priority_note}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        # Add timestamp in IST
        from market_utils import get_current_ist_time
        current_time = get_current_ist_time()
        time_str = current_time.strftime("%I:%M:%S %p")

        # Base message
        message = f"{header}\n\n"
        message += f"📊 <b>Stock:</b> {display_symbol}\n"
        message += f"⏰ <b>Alert Time:</b> {time_str}\n\n"

        # Price section
        message += "💰 <b>PRICE:</b>\n"
        message += f"   Current: ₹{current_price:,.2f}\n"
        message += f"   Previous (1m): ₹{previous_price:,.2f}\n"
        message += f"   Change: {direction_color} <b>{change_percent:.2f}%</b> in 1 minute\n"

        # Market cap
        if market_cap_cr and market_cap_cr > 0:
            message += f"\n💼 <b>Market Cap:</b> ₹{market_cap_cr:,.0f} Cr\n"

        # Volume section (MANDATORY for 1-min alerts)
        if volume_data:
            message += "\n📊 <b>VOLUME:</b>\n"
            current_vol = volume_data.get('current_volume', 0)
            avg_vol = volume_data.get('avg_volume', 0)
            spike_mult = volume_data.get('spike_multiplier', 0)

            message += f"   Current: {current_vol:,}\n"
            if avg_vol > 0:
                message += f"   Average: {avg_vol:,}\n"
                message += f"   🔥 <b>Spike: {spike_mult:.1f}x average</b>\n"

        # RSI section
        if rsi_analysis:
            message += self._format_rsi_section(rsi_analysis, is_priority=True)

        # OI section
        if oi_analysis:
            message += self._format_oi_section(oi_analysis, is_priority=True)

        # Footer
        message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "⚡ <b>Fastest alert system - 1-min detection!</b>\n"
        message += "⏱️ 5x faster than standard 5-min alerts"

        return message

    def _format_alert_message(self, symbol: str, drop_percent: float,
                              current_price: float, previous_price: float,
                              alert_type: str = "10min", volume_data: dict = None,
                              market_cap_cr: float = None, rsi_analysis: dict = None,
                              oi_analysis: dict = None, sector_context: dict = None) -> str:
        """
        Format alert message with stock details for both drops and rises

        Args:
            symbol: Stock symbol
            drop_percent: Drop/Rise percentage
            current_price: Current price
            previous_price: Previous price
            alert_type: Type of alert ("10min", "30min", "volume_spike",
                                      "10min_rise", "30min_rise", "volume_spike_rise")
            volume_data: Volume data if applicable
            market_cap_cr: Market cap in crores
            rsi_analysis: Optional RSI analysis dict with RSI values and crossovers
            oi_analysis: Optional OI analysis dict with pattern and signal
            sector_context: Optional sector context dict with sector performance

        Returns:
            Formatted message string
        """
        # Remove .NS suffix for display
        display_symbol = symbol.replace('.NS', '')

        # Check if this is a pharma stock
        is_pharma = display_symbol in config.PHARMA_STOCKS

        # Determine if this is a rise or drop alert
        is_rise = alert_type.endswith('_rise')

        # Alert header based on type (with priority emphasis for volume spikes)
        if is_rise:
            if alert_type == "volume_spike_rise":
                header = (
                    "🚨🚨🚨 <b>PRIORITY ALERT</b> 🚨🚨🚨\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "⚡ <b>URGENT</b> ⚡ VOLUME SPIKE RISE ⚡ <b>URGENT</b> ⚡\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
            elif alert_type == "5min_rise":
                header = "⚡ ALERT: Rapid 5-Min Rise!"
            elif alert_type == "30min_rise":
                header = "📈 ALERT: Gradual 30-Min Rise!"
            else:
                header = "🟢 ALERT: Stock Rise Detected"
        else:
            if alert_type == "volume_spike":
                header = (
                    "🚨🚨🚨 <b>PRIORITY ALERT</b> 🚨🚨🚨\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "⚡ <b>URGENT</b> ⚡ VOLUME SPIKE DROP ⚡ <b>URGENT</b> ⚡\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
            elif alert_type == "5min":
                header = "⚡ ALERT: Rapid 5-Min Drop!"
            elif alert_type == "30min":
                header = "⚠️ ALERT: Gradual 30-Min Drop!"
            else:
                header = "🔴 ALERT: Stock Drop Detected"

        # Base message - use bold for priority alerts
        is_priority = alert_type in ["volume_spike", "volume_spike_rise"]

        # Add timestamp in IST
        from market_utils import get_current_ist_time
        current_time = get_current_ist_time()
        time_str = current_time.strftime("%I:%M:%S %p")

        if is_priority:
            message = f"{header}\n\n📊 <b>Stock: {display_symbol}</b>\n⏰ Alert Time: {time_str}\n"
        else:
            message = f"{header}\n\n📊 Stock: {display_symbol}\n⏰ Alert Time: {time_str}\n"

        # Add market cap if available
        if market_cap_cr:
            # Format market cap in crores with commas
            market_cap_formatted = f"{market_cap_cr:,.0f}"
            message += f"💰 Market Cap: ₹{market_cap_formatted} Cr\n"

        # Add pharma indicator (only for drops)
        if is_pharma and not is_rise:
            message += f"💊 PHARMA STOCK - Good shorting indicator!\n"
            message += f"⚠️ Likely driven by negative news about medicines\n\n"
        else:
            message += "\n"

        # Time period description
        if alert_type in ["volume_spike", "volume_spike_rise"]:
            time_desc = "5 minutes"  # Updated to 5-min comparison
            prev_label = "5 Min Ago"
        elif alert_type in ["5min", "5min_rise"]:
            time_desc = "5 minutes"
            prev_label = "5 Min Ago"
        elif alert_type in ["30min", "30min_rise"]:
            time_desc = "30 minutes"
            prev_label = "30 Min Ago"
        else:
            time_desc = "10 minutes"
            prev_label = "10 Min Ago"

        # Add price details - adjust based on rise or drop
        # Use bold formatting for priority alerts
        if is_rise:
            if is_priority:
                message += (
                    f"📈 <b>Rise: {drop_percent:.2f}%</b> (in {time_desc})\n"
                    f"💰 {prev_label}: ₹{previous_price:.2f}\n"
                    f"💸 <b>Current: ₹{current_price:.2f}</b>\n"
                    f"📊 Change: +₹{(current_price - previous_price):.2f}\n"
                )
            else:
                message += (
                    f"📈 Rise: {drop_percent:.2f}% (in {time_desc})\n"
                    f"💰 {prev_label}: ₹{previous_price:.2f}\n"
                    f"💸 Current: ₹{current_price:.2f}\n"
                    f"📊 Change: +₹{(current_price - previous_price):.2f}\n"
                )
        else:
            if is_priority:
                message += (
                    f"📉 <b>Drop: {drop_percent:.2f}%</b> (in {time_desc})\n"
                    f"💰 {prev_label}: ₹{previous_price:.2f}\n"
                    f"💸 <b>Current: ₹{current_price:.2f}</b>\n"
                    f"📊 Change: -₹{(previous_price - current_price):.2f}\n"
                )
            else:
                message += (
                    f"📉 Drop: {drop_percent:.2f}% (in {time_desc})\n"
                    f"💰 {prev_label}: ₹{previous_price:.2f}\n"
                    f"💸 Current: ₹{current_price:.2f}\n"
                    f"📊 Change: -₹{(previous_price - current_price):.2f}\n"
                )

        # Add volume information for ALL alerts with context (multiplier vs average)
        if volume_data:
            current_vol = volume_data.get("current_volume", 0)
            avg_vol = volume_data.get("avg_volume", 0)

            # Show volume with multiplier context for better interpretation
            if current_vol > 0:
                if avg_vol > 0:
                    multiplier = current_vol / avg_vol
                    message += f"📊 Volume: {current_vol:,} ({multiplier:.1f}x avg)\n"
                else:
                    # Fallback if no historical average available yet
                    message += f"📊 Volume: {current_vol:,} shares\n"

        # Add detailed volume spike analysis if applicable (with enhanced formatting for priority)
        if alert_type in ["volume_spike", "volume_spike_rise"] and volume_data:
            current_vol = volume_data.get("current_volume", 0)
            avg_vol = volume_data.get("avg_volume", 0)
            if avg_vol > 0:
                spike_ratio = current_vol / avg_vol
                message += (
                    f"\n<b>📊 VOLUME ANALYSIS:</b>\n"
                    f"   🔥 Current: <b>{current_vol:,}</b>\n"
                    f"   📊 Average: {int(avg_vol):,}\n"
                    f"   ⚡ Spike: <b>{spike_ratio:.1f}x above average!</b>\n"
                    f"\n⏰ <b>IMMEDIATE ATTENTION REQUIRED</b> ⏰\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )

        # Add RSI Momentum Analysis
        if rsi_analysis:
            message += self._format_rsi_section(rsi_analysis, is_priority)

        # Add OI Analysis (if enabled and available)
        if oi_analysis and config.ENABLE_OI_ANALYSIS:
            message += self._format_oi_section(oi_analysis, is_priority)

        # Add Sector Context (if enabled and available)
        if sector_context and config.ENABLE_SECTOR_CONTEXT_IN_ALERTS:
            message += self._format_sector_context(sector_context, is_priority)

        return message

    def _format_sector_context(self, sector_context: dict, is_priority: bool = False) -> str:
        """
        Format sector context section for Telegram alert.

        Args:
            sector_context: Sector context dict with sector performance data
            is_priority: Whether this is a priority alert (for bold formatting)

        Returns:
            Formatted sector context string
        """
        sector_section = "\n\n"

        # Use bold header for priority alerts
        if is_priority:
            sector_section += "<b>📊 SECTOR CONTEXT:</b>\n"
        else:
            sector_section += "📊 <b>Sector Context:</b>\n"

        # Extract sector data
        sector_name = sector_context.get('sector_name', 'Unknown')
        sector_change_10min = sector_context.get('sector_change_10min', 0)
        stock_vs_sector = sector_context.get('stock_vs_sector', 0)
        sector_volume_ratio = sector_context.get('sector_volume_ratio', 1.0)
        sector_momentum = sector_context.get('sector_momentum', 0)
        stocks_up = sector_context.get('stocks_up_10min', 0)
        stocks_down = sector_context.get('stocks_down_10min', 0)
        total_stocks = sector_context.get('total_stocks', 0)

        # Format sector name (replace underscores with spaces, title case)
        display_sector = sector_name.replace('_', ' ').title()

        # Sector performance line
        sector_emoji = "🟢" if sector_change_10min > 0 else "🔴" if sector_change_10min < 0 else "⚪"
        sector_section += f"   <b>Sector:</b> {display_sector} {sector_emoji}\n"
        sector_section += f"   <b>10-min Change:</b> {sector_change_10min:+.2f}%\n"

        # Stock vs Sector differential
        if stock_vs_sector != 0:
            vs_emoji = "⬆️" if stock_vs_sector > 0 else "⬇️"
            vs_desc = "outperforming" if stock_vs_sector > 0 else "underperforming"
            sector_section += f"   <b>vs Sector:</b> {vs_emoji} {vs_desc} by {abs(stock_vs_sector):.2f}%\n"

        # Sector breadth (participation)
        if total_stocks > 0:
            up_pct = (stocks_up / total_stocks) * 100
            down_pct = (stocks_down / total_stocks) * 100
            sector_section += f"   <b>Breadth:</b> {stocks_up}↑ ({up_pct:.0f}%) / {stocks_down}↓ ({down_pct:.0f}%)\n"

        # Volume context
        if sector_volume_ratio != 1.0:
            vol_emoji = "🔥" if sector_volume_ratio > 1.2 else "📊"
            sector_section += f"   {vol_emoji} <b>Volume:</b> {sector_volume_ratio:.2f}x average\n"

        # Momentum summary
        if sector_momentum != 0:
            mom_emoji = "🚀" if sector_momentum > 0 else "🔻"
            sector_section += f"   {mom_emoji} <b>Momentum:</b> {sector_momentum:+.2f}\n"

        return sector_section

    def _format_rsi_section(self, rsi_analysis: dict, is_priority: bool = False) -> str:
        """
        Format RSI momentum analysis section for Telegram alert.

        Args:
            rsi_analysis: RSI analysis dict with RSI values and crossovers
            is_priority: Whether this is a priority alert (for bold formatting)

        Returns:
            Formatted RSI section string
        """
        rsi_section = "\n\n"

        # Use bold header for priority alerts
        if is_priority:
            rsi_section += "<b>📊 RSI MOMENTUM ANALYSIS:</b>\n"
        else:
            rsi_section += "📊 <b>RSI Momentum Analysis:</b>\n"

        # RSI Values
        rsi_9 = rsi_analysis.get('rsi_9')
        rsi_14 = rsi_analysis.get('rsi_14')
        rsi_21 = rsi_analysis.get('rsi_21')

        if rsi_9 is not None or rsi_14 is not None or rsi_21 is not None:
            rsi_section += "   <b>RSI Values:</b>\n"

            if rsi_9 is not None:
                # Add emoji indicators for overbought/oversold
                if rsi_9 > 70:
                    emoji = "🔥"  # Overbought
                elif rsi_9 < 30:
                    emoji = "❄️"  # Oversold
                else:
                    emoji = "📊"
                rsi_section += f"      {emoji} RSI(9): {rsi_9:.2f}\n"

            if rsi_14 is not None:
                if rsi_14 > 70:
                    emoji = "🔥"
                elif rsi_14 < 30:
                    emoji = "❄️"
                else:
                    emoji = "📊"
                rsi_section += f"      {emoji} RSI(14): {rsi_14:.2f}\n"

            if rsi_21 is not None:
                if rsi_21 > 70:
                    emoji = "🔥"
                elif rsi_21 < 30:
                    emoji = "❄️"
                else:
                    emoji = "📊"
                rsi_section += f"      {emoji} RSI(21): {rsi_21:.2f}\n"

        # RSI Crossovers
        crossovers = rsi_analysis.get('crossovers', {})
        if crossovers:
            rsi_section += "   <b>Crossovers:</b>\n"

            for pair, crossover_data in crossovers.items():
                if crossover_data.get('status') and crossover_data.get('strength') is not None:
                    fast, slow = pair.split('_')
                    status = crossover_data['status']
                    strength = crossover_data['strength']

                    # Arrow indicator
                    arrow = "↑" if status == 'above' else "↓"
                    sign = "+" if strength >= 0 else ""

                    rsi_section += f"      • RSI({fast}){arrow}RSI({slow}): {sign}{strength:.2f}\n"

        # Recent Crossovers
        recent_crosses = []
        for pair, crossover_data in crossovers.items():
            recent = crossover_data.get('recent_cross', {})
            if recent.get('occurred'):
                bars_ago = recent.get('bars_ago', 0)
                direction = recent.get('direction', '').capitalize()
                emoji = "🟢" if direction == 'Bullish' else "🔴"
                fast, slow = pair.split('_')
                recent_crosses.append(f"{emoji} RSI({fast})×RSI({slow}) {direction} {bars_ago}d ago")

        if recent_crosses:
            rsi_section += "   <b>Recent Crosses:</b>\n"
            for cross in recent_crosses:
                rsi_section += f"      • {cross}\n"

        # Overall Summary
        summary = rsi_analysis.get('summary', '')
        if summary:
            # Add emoji based on summary
            if 'Bullish' in summary:
                emoji = "🟢"
            elif 'Bearish' in summary:
                emoji = "🔴"
            else:
                emoji = "⚪"

            rsi_section += f"   <b>Summary:</b> {emoji} {summary}\n"

        return rsi_section

    def _format_oi_section(self, oi_analysis: dict, is_priority: bool = False) -> str:
        """
        Format OI (Open Interest) analysis section for Telegram alert.

        Args:
            oi_analysis: OI analysis dict with pattern, signal, and strength
            is_priority: Whether this is a priority alert (for bold formatting)

        Returns:
            Formatted OI section string
        """
        oi_section = "\n\n"

        # Use bold header for priority alerts
        if is_priority:
            oi_section += "<b>🔥 OI ANALYSIS:</b> 🔥\n"
        else:
            oi_section += "🔥 <b>OI Analysis:</b>\n"

        # Extract OI data
        pattern = oi_analysis.get('pattern', '')
        signal = oi_analysis.get('signal', '')
        interpretation = oi_analysis.get('interpretation', '')
        oi_change_pct = oi_analysis.get('oi_change_pct', 0)
        strength = oi_analysis.get('strength', '')
        priority = oi_analysis.get('priority', '')
        at_day_high = oi_analysis.get('at_day_high', False)
        at_day_low = oi_analysis.get('at_day_low', False)

        # Pattern and Signal (with emoji indicators)
        pattern_emoji_map = {
            'LONG_BUILDUP': '🟢',
            'SHORT_BUILDUP': '🔴',
            'SHORT_COVERING': '🟡',
            'LONG_UNWINDING': '🟠'
        }
        pattern_emoji = pattern_emoji_map.get(pattern, '📊')

        # Format pattern name for display
        pattern_display = pattern.replace('_', ' ').title()

        oi_section += f"   {pattern_emoji} <b>Pattern:</b> {pattern_display}\n"

        # OI Change with strength indicator
        strength_emoji_map = {
            'VERY_STRONG': '🔥🔥🔥',
            'STRONG': '🔥🔥',
            'SIGNIFICANT': '🔥',
            'MINIMAL': '📊'
        }
        strength_emoji = strength_emoji_map.get(strength, '📊')

        change_sign = "+" if oi_change_pct >= 0 else ""
        oi_section += f"   {strength_emoji} <b>OI Change:</b> {change_sign}{oi_change_pct:.2f}% ({strength})\n"

        # Signal interpretation
        signal_emoji_map = {
            'BULLISH': '🟢',
            'BEARISH': '🔴',
            'WEAK_BULLISH': '🟡',
            'WEAK_BEARISH': '🟠'
        }
        signal_emoji = signal_emoji_map.get(signal, '⚪')

        oi_section += f"   {signal_emoji} <b>Signal:</b> {signal}\n"
        oi_section += f"   💡 <b>Meaning:</b> {interpretation}\n"

        # Priority indicator
        if priority == 'HIGH':
            oi_section += f"   ⚠️ <b>PRIORITY:</b> HIGH - Fresh positions building!\n"
        elif priority == 'MEDIUM':
            oi_section += f"   📌 Priority: Medium\n"

        # OI extremes (only shown when OI change >= 5%)
        if at_day_high:
            oi_section += f"   🎯 <b>At Day High!</b> - OI at intraday peak ({oi_change_pct:+.1f}% from day start)\n"
        elif at_day_low:
            oi_section += f"   📉 <b>At Day Low!</b> - OI at intraday bottom ({oi_change_pct:+.1f}% from day start)\n"

        return oi_section

    def _send_message(self, message: str) -> bool:
        """
        Send message to Telegram channel

        Args:
            message: Message text to send

        Returns:
            True if successful, False otherwise
        """
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.channel_id,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Telegram message sent successfully")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_premarket_pattern_alert(
        self,
        top_patterns: List[Dict],
        market_regime: str = "NEUTRAL",
        stocks_analyzed: int = 0,
        total_patterns_found: int = 0
    ) -> bool:
        """
        Send pre-market pattern alert with top 1-3 setups.

        Args:
            top_patterns: List of top ranked patterns (max 3)
            market_regime: Current market regime
            stocks_analyzed: Number of stocks analyzed
            total_patterns_found: Total patterns detected

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_premarket_alert_message(
            top_patterns, market_regime, stocks_analyzed, total_patterns_found
        )
        return self._send_message(message)

    def _format_premarket_alert_message(
        self,
        top_patterns: List[Dict],
        market_regime: str,
        stocks_analyzed: int,
        total_patterns_found: int
    ) -> str:
        """
        Format pre-market pattern alert message.

        Args:
            top_patterns: Top ranked patterns
            market_regime: Market regime
            stocks_analyzed: Number of stocks analyzed
            total_patterns_found: Total patterns found

        Returns:
            Formatted HTML message string
        """
        from datetime import datetime
        import pattern_utils as pu

        # Market opens in X minutes
        now = datetime.now()
        market_open_time = datetime.combine(now.date(), datetime.strptime('09:15', '%H:%M').time())
        minutes_to_open = max(0, int((market_open_time - now).total_seconds() / 60))

        # Market regime emoji
        regime_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(market_regime, "🟡")

        # Header
        message = f"📊📊📊 <b>PRE-MARKET PATTERN ALERT</b> 📊📊📊\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += f"🕘 <b>Analysis Time:</b> {now.strftime('%I:%M %p')}\n"
        message += f"⏰ <b>Market Opens in:</b> {minutes_to_open} minutes\n"
        message += f"{regime_emoji} <b>Market Regime:</b> {market_regime}\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        if not top_patterns:
            message += "❌ <b>No high-quality patterns found today</b>\n"
            message += f"Analyzed {stocks_analyzed} stocks, found {total_patterns_found} patterns below threshold.\n"
            return message

        message += f"🏆 <b>TOP {len(top_patterns)} PATTERN{'S' if len(top_patterns) > 1 else ''} FOR TODAY</b> 🏆\n\n"

        # Pattern details
        for i, pattern in enumerate(top_patterns, 1):
            details = pattern['details']
            symbol = pattern['symbol']
            pattern_name = pu.format_pattern_name(pattern['pattern_name'])
            timeframe = pattern['timeframe'].upper()

            # Calculate percentages
            entry = details.get('buy_price', 0)
            target = details.get('target_price', 0)
            stop = details.get('stop_loss', 0)

            target_pct = ((target - entry) / entry * 100) if entry > 0 else 0
            stop_pct = ((entry - stop) / entry * 100) if entry > 0 else 0
            rr_ratio = pu.calculate_risk_reward_ratio(entry, target, stop)

            # Rank emoji
            rank_emoji = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣"}.get(i, f"{i}️⃣")

            # Pattern header
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += f"{rank_emoji} <b>{symbol} - {pattern_name} ({timeframe})</b> 🟢\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Pattern details
            message += "   📊 <b>Pattern Details:</b>\n"
            message += f"   • Timeframe: {timeframe}\n"
            message += f"   • Confidence: {details.get('confidence_score', 0):.1f}/10 🔥🔥\n"
            message += f"   • Priority Score: {pattern.get('priority_score', 0):.2f}/10\n\n"

            # Trade setup
            message += "   💰 <b>TRADE SETUP:</b>\n"
            message += f"   • Entry:  ₹{entry:.2f}\n"
            message += f"   • Target: ₹{target:.2f} (+{target_pct:.1f}%)\n"
            message += f"   • Stop:   ₹{stop:.2f} (-{stop_pct:.1f}%)\n"
            message += f"   • R:R Ratio: 1:{rr_ratio:.1f}\n\n"

            # Technical strength
            message += "   📈 <b>Technical Strength:</b>\n"
            message += f"   • Volume: {details.get('volume_ratio', 0):.1f}x average 🔥\n"

            pattern_height_pct = 0
            if 'DOUBLE_BOTTOM' in pattern['pattern_name'].upper():
                first_low = details.get('first_low', 0)
                second_low = details.get('second_low', 0)
                peak = details.get('peak_between', 0)
                pattern_height_pct = pu.calculate_pattern_height_pct(peak, second_low, second_low)
                message += f"   • Pattern Height: {pattern_height_pct:.1f}%\n"
            elif 'RESISTANCE_BREAKOUT' in pattern['pattern_name'].upper():
                resistance = details.get('resistance_level', 0)
                support = details.get('support_level', 0)
                pattern_height_pct = pu.calculate_pattern_height_pct(resistance, support, resistance)
                message += f"   • Pattern Range: {pattern_height_pct:.1f}%\n"

            # Freshness
            candles_ago = pattern.get('candles_ago', 0)
            if candles_ago == 0:
                message += "   • Formed: Just now (fresh!) ✨\n"
            elif timeframe == 'DAILY':
                message += f"   • Formed: {candles_ago} day(s) ago\n"
            else:
                message += f"   • Formed: {candles_ago} hour(s) ago\n"

            message += "\n"

        # Footer
        message += "⚠️ <b>PREPARATION CHECKLIST:</b>\n"
        message += "✅ Review charts before 9:15 AM\n"
        message += "✅ Set entry orders at trigger prices\n"
        message += "✅ Place stop losses immediately\n"
        message += "✅ Monitor for first 15 minutes\n\n"

        message += f"<i>Analyzed {stocks_analyzed} stocks | Found {total_patterns_found} total patterns</i>"

        return message

    def send_test_message(self) -> bool:
        """Send a test message to verify Telegram setup"""
        message = "✅ NSE Stock Monitor is active and ready to send alerts!"
        return self._send_message(message)

    def send_sector_rotation_alert(self, rotation_data: dict) -> bool:
        """
        Send sector rotation alert to Telegram channel

        Args:
            rotation_data: Rotation data dict with top gainers/losers

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_sector_rotation_message(rotation_data)
        return self._send_message(message)

    def send_eod_sector_summary(self, sector_analysis: dict) -> bool:
        """
        Send end-of-day sector performance summary to Telegram channel

        Args:
            sector_analysis: Sector analysis dict with all sector metrics

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_eod_sector_summary(sector_analysis)
        return self._send_message(message)

    def _format_eod_sector_summary(self, sector_analysis: dict) -> str:
        """
        Format end-of-day sector performance summary

        Args:
            sector_analysis: Sector analysis dict with timestamp and sectors

        Returns:
            Formatted EOD summary message
        """
        from datetime import datetime

        # Extract data
        timestamp = sector_analysis.get('timestamp', '')
        sectors = sector_analysis.get('sectors', {})

        if not sectors:
            return "📊 EOD Sector Summary: No sector data available"

        # Parse timestamp
        try:
            dt = datetime.fromisoformat(timestamp)
            date_str = dt.strftime("%d %b %Y")
            time_str = dt.strftime("%I:%M %p")
        except:
            date_str = "Today"
            time_str = ""

        # Header
        message = (
            "📊📊📊 <b>EOD SECTOR SUMMARY</b> 📊📊📊\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Date: <b>{date_str}</b>\n"
            f"⏰ Time: {time_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        # Sort sectors by 10-min performance
        sorted_sectors = sorted(
            sectors.items(),
            key=lambda x: x[1].get('price_change_10min', 0),
            reverse=True
        )

        # Calculate overall market sentiment
        total_up = sum(s[1].get('stocks_up_10min', 0) for s in sorted_sectors)
        total_down = sum(s[1].get('stocks_down_10min', 0) for s in sorted_sectors)
        total_stocks = sum(s[1].get('total_stocks', 0) for s in sorted_sectors)

        if total_stocks > 0:
            up_pct = (total_up / total_stocks) * 100
            market_emoji = "🟢" if up_pct > 50 else "🔴" if up_pct < 40 else "⚪"
            message += (
                f"<b>📈 MARKET SENTIMENT:</b> {market_emoji}\n"
                f"   • Stocks Up: {total_up} ({up_pct:.1f}%)\n"
                f"   • Stocks Down: {total_down} ({100-up_pct:.1f}%)\n"
                f"   • Total Active: {total_stocks} stocks\n\n"
            )

        # Top 3 Gainers
        message += "🟢 <b>TOP 3 GAINING SECTORS:</b>\n"
        for i, (sector, data) in enumerate(sorted_sectors[:3], 1):
            sector_name = sector.replace('_', ' ').title()
            price_change = data.get('price_change_10min', 0)
            momentum = data.get('momentum_score_10min', 0)
            volume_ratio = data.get('volume_ratio', 1.0)
            stocks_up = data.get('stocks_up_10min', 0)
            total = data.get('total_stocks', 0)

            emoji = "🚀" if price_change > 1.0 else "📈"
            message += (
                f"{i}. <b>{sector_name}</b> {emoji}\n"
                f"   • Change: <b>{price_change:+.2f}%</b>\n"
                f"   • Momentum: {momentum:+.2f}\n"
                f"   • Volume: {volume_ratio:.2f}x\n"
                f"   • Breadth: {stocks_up}/{total} up\n"
            )
        message += "\n"

        # Bottom 3 Losers
        message += "🔴 <b>TOP 3 LOSING SECTORS:</b>\n"
        for i, (sector, data) in enumerate(reversed(sorted_sectors[-3:]), 1):
            sector_name = sector.replace('_', ' ').title()
            price_change = data.get('price_change_10min', 0)
            momentum = data.get('momentum_score_10min', 0)
            volume_ratio = data.get('volume_ratio', 1.0)
            stocks_down = data.get('stocks_down_10min', 0)
            total = data.get('total_stocks', 0)

            emoji = "🔻" if price_change < -1.0 else "📉"
            message += (
                f"{i}. <b>{sector_name}</b> {emoji}\n"
                f"   • Change: <b>{price_change:+.2f}%</b>\n"
                f"   • Momentum: {momentum:+.2f}\n"
                f"   • Volume: {volume_ratio:.2f}x\n"
                f"   • Breadth: {stocks_down}/{total} down\n"
            )
        message += "\n"

        # Full sector rankings
        message += "📋 <b>ALL SECTORS RANKED:</b>\n"
        for i, (sector, data) in enumerate(sorted_sectors, 1):
            sector_name = sector.replace('_', ' ').title()
            price_change = data.get('price_change_10min', 0)

            if price_change > 0:
                emoji = "🟢"
            elif price_change < 0:
                emoji = "🔴"
            else:
                emoji = "⚪"

            message += f"{i}. {emoji} {sector_name}: {price_change:+.2f}%\n"

        # Footer
        message += (
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <b>Day Summary Complete</b>\n"
            "📊 Analysis based on 10-min price changes"
        )

        return message

    def _format_sector_rotation_message(self, rotation_data: dict) -> str:
        """
        Format sector rotation alert message

        Args:
            rotation_data: Rotation data with divergence, top gainers, top losers

        Returns:
            Formatted message string
        """
        # Extract rotation data
        timestamp = rotation_data.get('timestamp', '')
        divergence = rotation_data.get('divergence', 0)
        top_gainers = rotation_data.get('top_gainers', [])
        top_losers = rotation_data.get('top_losers', [])

        # Header with priority emphasis
        message = (
            "🔄🔄🔄 <b>SECTOR ROTATION DETECTED</b> 🔄🔄🔄\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💰 <b>FUND FLOW ALERT</b> 💰\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        # Divergence info
        message += f"⚡ <b>Divergence:</b> {divergence:.2f}% momentum spread\n\n"

        # Top Gaining Sectors (Money Flowing IN)
        if top_gainers:
            message += "🟢 <b>TOP GAINING SECTORS (Money IN):</b>\n"
            for i, gainer in enumerate(top_gainers, 1):
                sector = gainer['sector'].replace('_', ' ').title()
                price_change = gainer['price_change']
                momentum = gainer['momentum']
                volume_ratio = gainer['volume_ratio']

                emoji = "🚀" if momentum > 1.0 else "📈"
                message += (
                    f"{i}. <b>{sector}</b> {emoji}\n"
                    f"   • Price: {price_change:+.2f}%\n"
                    f"   • Momentum: {momentum:+.2f}\n"
                    f"   • Volume: {volume_ratio:.2f}x\n"
                )
            message += "\n"

        # Top Losing Sectors (Money Flowing OUT)
        if top_losers:
            message += "🔴 <b>TOP LOSING SECTORS (Money OUT):</b>\n"
            # Reverse the list so worst loser is first
            for i, loser in enumerate(reversed(top_losers), 1):
                sector = loser['sector'].replace('_', ' ').title()
                price_change = loser['price_change']
                momentum = loser['momentum']
                volume_ratio = loser['volume_ratio']

                emoji = "🔻" if momentum < -1.0 else "📉"
                message += (
                    f"{i}. <b>{sector}</b> {emoji}\n"
                    f"   • Price: {price_change:+.2f}%\n"
                    f"   • Momentum: {momentum:+.2f}\n"
                    f"   • Volume: {volume_ratio:.2f}x\n"
                )
            message += "\n"

        # Footer with interpretation
        message += (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <b>Action:</b> Monitor individual stocks in gaining sectors\n"
            "⚠️ <b>Caution:</b> Review positions in losing sectors"
        )

        return message

    def send_eod_pattern_summary(self, pattern_results: List[Dict], analysis_date: datetime) -> bool:
        """
        Send consolidated EOD pattern detection summary to Telegram

        Args:
            pattern_results: List of pattern detection results from batch_detect()
            analysis_date: Date of analysis

        Returns:
            True if message sent successfully, False if no patterns or send failed
        """
        # Filter patterns for Telegram (Cup & Handle, Double Bottom, Double Top only)
        filtered_patterns = self._filter_eod_patterns(pattern_results)

        # Check if any patterns found
        total_patterns = sum(len(stocks) for stocks in filtered_patterns.values())
        if total_patterns == 0:
            logger.info("No EOD patterns meet Telegram alert criteria (confidence >= 7.0)")
            return False

        # Format consolidated message
        message = self._format_eod_pattern_summary(filtered_patterns, analysis_date, total_patterns)

        # Send to Telegram
        try:
            success = self._send_message(message)
            if success:
                logger.info(f"EOD pattern summary sent to Telegram ({total_patterns} patterns)")
            return success
        except Exception as e:
            logger.error(f"Failed to send EOD pattern summary: {e}")
            return False

    def _filter_eod_patterns(self, pattern_results: List[Dict]) -> Dict[str, List[Dict]]:
        """Filter and group patterns for Telegram alert"""

        # Pattern types to include (user requested only these 3)
        INCLUDED_PATTERNS = {'CUP_HANDLE', 'DOUBLE_BOTTOM', 'DOUBLE_TOP'}
        CONFIDENCE_THRESHOLD = 7.0

        grouped = {
            'cup_handle': [],
            'double_bottom': [],
            'double_top': []
        }

        for result in pattern_results:
            if not result.get('has_patterns'):
                continue

            symbol = result['symbol']
            patterns_found = result.get('patterns_found', [])
            pattern_details = result.get('pattern_details', {})

            for pattern in patterns_found:
                if pattern not in INCLUDED_PATTERNS:
                    continue

                # Get pattern details
                pattern_key = pattern.lower()
                details = pattern_details.get(pattern_key, {})

                if not details:
                    continue

                # Check confidence threshold
                confidence = details.get('confidence_score', 0)
                if confidence < CONFIDENCE_THRESHOLD:
                    logger.debug(f"{symbol} {pattern}: confidence {confidence:.1f} < {CONFIDENCE_THRESHOLD}")
                    continue

                # Add to grouped results
                grouped[pattern_key].append({
                    'symbol': symbol,
                    'details': details
                })

        return grouped

    def _format_eod_pattern_summary(self, filtered_patterns: Dict, analysis_date: datetime, total_count: int) -> str:
        """Format consolidated EOD pattern message"""

        # Header
        message = (
            "📊📊📊 <b>EOD PATTERN DETECTION</b> 📊📊📊\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Date: {analysis_date.strftime('%d %B %Y')}\n"
            f"⏰ Analysis Time: 3:30 PM\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        bullish_count = 0
        bearish_count = 0

        # Cup & Handle section
        if filtered_patterns['cup_handle']:
            stocks = filtered_patterns['cup_handle']
            bullish_count += len(stocks)
            message += f"🏆 <b>CUP & HANDLE PATTERNS</b> ({len(stocks)} stocks)\n\n"

            for idx, item in enumerate(stocks, 1):
                symbol = item['symbol']
                details = item['details']
                confidence = details['confidence_score']
                buy = details['buy_price']
                target = details['target_price']
                stop = details['stop_loss']
                volume = details['volume_ratio']
                cup_days = details.get('cup_days', 0)
                handle_days = details.get('handle_days', 0)

                target_gain_pct = ((target - buy) / buy) * 100
                stop_loss_pct = ((stop - buy) / buy) * 100

                conf_emoji = "🟢" if confidence >= 8.0 else "🟡"

                message += (
                    f"{idx}. <b>{symbol}</b> - Confidence: {confidence:.1f}/10 {conf_emoji}\n"
                    f"   💰 Buy: ₹{buy:,.2f}\n"
                    f"   🎯 Target: ₹{target:,.2f} (+{target_gain_pct:.1f}%)\n"
                    f"   🛡️ Stop: ₹{stop:,.2f} ({stop_loss_pct:+.1f}%)\n"
                    f"   📊 Volume: {volume:.1f}x average\n"
                    f"   💡 Cup: {cup_days} days, Handle: {handle_days} days\n\n"
                )

        # Double Bottom section
        if filtered_patterns['double_bottom']:
            stocks = filtered_patterns['double_bottom']
            bullish_count += len(stocks)
            message += f"📈 <b>DOUBLE BOTTOM PATTERNS</b> ({len(stocks)} stocks)\n\n"

            for idx, item in enumerate(stocks, 1):
                symbol = item['symbol']
                details = item['details']
                confidence = details['confidence_score']
                buy = details['buy_price']
                target = details['target_price']
                stop = details['stop_loss']
                volume = details['volume_ratio']

                target_gain_pct = ((target - buy) / buy) * 100
                stop_loss_pct = ((stop - buy) / buy) * 100

                conf_emoji = "🟢" if confidence >= 8.0 else "🟡"

                message += (
                    f"{idx}. <b>{symbol}</b> - Confidence: {confidence:.1f}/10 {conf_emoji}\n"
                    f"   💰 Buy: ₹{buy:,.2f}\n"
                    f"   🎯 Target: ₹{target:,.2f} (+{target_gain_pct:.1f}%)\n"
                    f"   🛡️ Stop: ₹{stop:,.2f} ({stop_loss_pct:+.1f}%)\n"
                    f"   📊 Volume: {volume:.1f}x average\n\n"
                )

        # Double Top section
        if filtered_patterns['double_top']:
            stocks = filtered_patterns['double_top']
            bearish_count += len(stocks)
            message += f"📉 <b>DOUBLE TOP PATTERNS</b> ({len(stocks)} stocks)\n\n"

            for idx, item in enumerate(stocks, 1):
                symbol = item['symbol']
                details = item['details']
                confidence = details['confidence_score']
                buy = details['buy_price']
                target = details['target_price']
                stop = details['stop_loss']
                volume = details['volume_ratio']

                target_gain_pct = ((target - buy) / buy) * 100
                stop_loss_pct = ((stop - buy) / buy) * 100

                conf_emoji = "🔴" if confidence >= 8.0 else "🟠"

                message += (
                    f"{idx}. <b>{symbol}</b> - Confidence: {confidence:.1f}/10 {conf_emoji}\n"
                    f"   💰 Entry: ₹{buy:,.2f}\n"
                    f"   🎯 Target: ₹{target:,.2f} ({target_gain_pct:+.1f}%)\n"
                    f"   🛡️ Stop: ₹{stop:,.2f} ({stop_loss_pct:+.1f}%)\n"
                    f"   📊 Volume: {volume:.1f}x average\n\n"
                )

        # Footer
        message += (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Total Patterns:</b> {total_count} stocks\n"
            f"🟢 <b>Bullish:</b> {bullish_count} | 🔴 <b>Bearish:</b> {bearish_count}\n"
            "💡 <b>Min Confidence:</b> 7.0/10\n\n"
            "⚠️ <b>Risk Disclaimer:</b>\n"
            "These are technical patterns only. Always use stop losses and manage position sizing appropriately."
        )

        return message

    def send_price_action_alert(
        self,
        symbol: str,
        pattern_name: str,
        pattern_type: str,
        confidence_score: float,
        entry_price: float,
        target: Optional[float],
        stop_loss: Optional[float],
        volume_ratio: float,
        pattern_description: str,
        candle_data: Dict,
        market_regime: str,
        confidence_breakdown: Optional[Dict] = None
    ) -> bool:
        """
        Send price action pattern alert to Telegram

        Args:
            symbol: Stock symbol
            pattern_name: Pattern name (e.g., "Bullish Engulfing")
            pattern_type: 'bullish', 'bearish', or 'neutral'
            confidence_score: 0-10 confidence score
            entry_price: Suggested entry price
            target: Target price (if applicable)
            stop_loss: Stop loss price (if applicable)
            volume_ratio: Current volume / average volume
            pattern_description: Human-readable pattern description
            candle_data: OHLCV data for relevant candles
            market_regime: Current market regime
            confidence_breakdown: Optional breakdown of confidence components

        Returns:
            True if sent successfully, False otherwise
        """
        message = self._format_price_action_message(
            symbol, pattern_name, pattern_type, confidence_score,
            entry_price, target, stop_loss, volume_ratio,
            pattern_description, candle_data, market_regime,
            confidence_breakdown
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
        volume_ratio: float,
        pattern_description: str,
        candle_data: Dict,
        market_regime: str,
        confidence_breakdown: Optional[Dict]
    ) -> str:
        """Format price action alert message"""

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

            message += (
                f"💰 <b>TRADE SETUP</b>\n"
                f"   Entry:  ₹{entry_price:.2f}\n"
                f"   Target: ₹{target:.2f} ({target_pct:+.1f}%)\n"
                f"   Stop:   ₹{stop_loss:.2f} ({stop_pct:+.1f}%)\n"
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

    def send_nifty_option_analysis(self, analysis_data: dict) -> bool:
        """
        Send NIFTY option selling analysis to Telegram channel

        Args:
            analysis_data: Analysis result dict from NiftyOptionAnalyzer

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_nifty_option_message(analysis_data)
        return self._send_message(message)

    def _format_nifty_option_message(self, data: dict) -> str:
        """
        Format NIFTY option selling analysis message

        Args:
            data: Analysis result dict with signal, scores, and recommendations

        Returns:
            Formatted Telegram message with HTML formatting
        """
        from datetime import datetime

        # Handle error response
        if 'error' in data:
            return (
                "❌ <b>NIFTY OPTION ANALYSIS - ERROR</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Error: {data['error']}\n"
                "Please check logs for details."
            )

        # Extract data
        signal = data.get('signal', 'HOLD')
        total_score = data.get('total_score', 0)
        nifty_spot = data.get('nifty_spot', 0)
        vix = data.get('vix', 0)
        market_regime = data.get('market_regime', 'UNKNOWN')
        best_strategy = data.get('best_strategy', 'straddle').upper()
        recommendation = data.get('recommendation', '')
        risk_factors = data.get('risk_factors', [])
        breakdown = data.get('breakdown', {})
        expiry_analyses = data.get('expiry_analyses', [])

        # Parse timestamp
        try:
            dt = datetime.fromisoformat(data.get('timestamp', datetime.now().isoformat()))
            date_str = dt.strftime("%d %b %Y")
            time_str = dt.strftime("%I:%M %p")
        except:
            date_str = datetime.now().strftime("%d %b %Y")
            time_str = datetime.now().strftime("%I:%M %p")

        # Signal emoji and styling
        if signal == 'SELL':
            signal_emoji = "✅"
            signal_style = "🟢"
        elif signal == 'HOLD':
            signal_emoji = "⏸️"
            signal_style = "🟡"
        else:  # AVOID
            signal_emoji = "🛑"
            signal_style = "🔴"

        # Header
        message = (
            f"{signal_style} <b>NIFTY OPTION SELLING SIGNAL</b> {signal_style}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>{date_str}</b> | ⏰ {time_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        # Signal and Score
        message += (
            f"📊 <b>SIGNAL: {signal} {signal_emoji}</b>\n"
            f"   Score: <b>{total_score:.1f}/100</b>\n"
            f"💰 NIFTY Spot: <b>₹{nifty_spot:,.2f}</b>\n\n"
        )

        # Expiry Information
        if expiry_analyses:
            message += "📅 <b>EXPIRIES:</b>\n"
            for i, exp_data in enumerate(expiry_analyses[:2], 1):
                expiry = exp_data.get('expiry_date')
                days = exp_data.get('days_to_expiry', 0)
                if expiry:
                    exp_str = expiry.strftime("%d %b %Y")
                    label = "Next Week" if i == 1 else "Next-to-Next"
                    message += f"   • {label}: {exp_str} ({days} days)\n"
            message += "\n"

        # Analysis Breakdown
        message += "📈 <b>ANALYSIS BREAKDOWN:</b>\n"
        theta_score = breakdown.get('theta_score', 0)
        gamma_score = breakdown.get('gamma_score', 0)
        vix_score = breakdown.get('vix_score', 0)
        regime_score = breakdown.get('regime_score', 0)
        oi_score = breakdown.get('oi_score', 0)

        message += f"   ⏰ Theta Score: <b>{theta_score:.1f}/100</b> {self._score_emoji(theta_score)}\n"
        message += f"   📉 Gamma Score: <b>{gamma_score:.1f}/100</b> {self._score_emoji(gamma_score)}\n"
        message += f"   🌊 VIX Score: <b>{vix_score:.1f}/100</b> {self._score_emoji(vix_score)} (VIX at {vix:.1f})\n"
        message += f"   📊 Market Regime: <b>{regime_score:.1f}/100</b> ({market_regime})\n"
        message += f"   🔄 OI Pattern: <b>{oi_score:.1f}/100</b>\n\n"

        # Recommendation
        message += (
            "💡 <b>RECOMMENDATION:</b>\n"
            f"   {recommendation}\n\n"
        )

        # Risk Factors
        message += "⚠️ <b>RISK FACTORS:</b>\n"
        for risk in risk_factors:
            message += f"   • {risk}\n"
        message += "\n"

        # Strike Suggestions (if available)
        if expiry_analyses and len(expiry_analyses) > 0:
            primary_exp = expiry_analyses[0]
            exp_date = primary_exp.get('expiry_date')

            if exp_date:
                exp_str = exp_date.strftime("%d %b")

                # Get the best strategy data
                if best_strategy == 'STRADDLE':
                    strategy_data = primary_exp.get('straddle', {})
                else:
                    strategy_data = primary_exp.get('strangle', {})

                strikes = strategy_data.get('strikes', {})
                call_premium = strategy_data.get('call_premium', 0)
                put_premium = strategy_data.get('put_premium', 0)
                total_premium = strategy_data.get('total_premium', 0)
                greeks = strategy_data.get('greeks', {})
                theta = abs(greeks.get('theta', 0))

                if strikes:
                    message += f"📋 <b>SUGGESTED {best_strategy} ({exp_str}):</b>\n"
                    message += f"   • Call Strike: <b>{strikes.get('call', 0)}</b> CE (₹{call_premium:.0f})\n"
                    message += f"   • Put Strike: <b>{strikes.get('put', 0)}</b> PE (₹{put_premium:.0f})\n"
                    message += f"   • Total Premium: <b>₹{total_premium:.0f}</b>\n"
                    message += f"   • Daily Theta Decay: <b>₹{theta:.0f}/day</b>\n\n"

        # Footer
        message += (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <b>Disclaimer:</b> For informational purposes only.\n"
            "Options trading involves substantial risk. Trade at your own risk.\n"
            "🔔 #NIFTYOptions #OptionSelling #Greeks"
        )

        return message

    @staticmethod
    def _score_emoji(score: float) -> str:
        """Get emoji based on score value"""
        if score >= 70:
            return "✅"
        elif score >= 40:
            return "⚠️"
        else:
            return "❌"
