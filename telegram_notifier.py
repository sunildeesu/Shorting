import requests
from typing import Optional
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
                   rsi_analysis: dict = None) -> bool:
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

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_alert_message(
            symbol, drop_percent, current_price, previous_price, alert_type, volume_data, market_cap_cr, rsi_analysis
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
                    rsi_analysis=rsi_analysis
                )
            except Exception as e:
                logger.error(f"Failed to log alert to Excel: {e}")

        return telegram_success

    def _format_alert_message(self, symbol: str, drop_percent: float,
                              current_price: float, previous_price: float,
                              alert_type: str = "10min", volume_data: dict = None,
                              market_cap_cr: float = None, rsi_analysis: dict = None) -> str:
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
        if is_priority:
            message = f"{header}\n\n📊 <b>Stock: {display_symbol}</b>\n"
        else:
            message = f"{header}\n\n📊 Stock: {display_symbol}\n"

        # Add market cap if available
        if market_cap_cr:
            # Format market cap in crores with commas
            market_cap_formatted = f"{market_cap_cr:,.0f}"
            # Market cap % change = price % change
            message += f"💰 Market Cap: ₹{market_cap_formatted} Cr ({drop_percent:+.2f}%)\n"

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

        return message

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

    def send_test_message(self) -> bool:
        """Send a test message to verify Telegram setup"""
        message = "✅ NSE Stock Monitor is active and ready to send alerts!"
        return self._send_message(message)
