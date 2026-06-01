"""Stock alert notifier for price drop/rise alerts."""
import logging
import config
from .base_notifier import BaseNotifier
from .formatting_helpers import format_rsi_section, format_oi_section, format_sector_context
from quarterly_results_checker import get_results_label

logger = logging.getLogger(__name__)


def _ordinal(n: int) -> str:
    """
    Convert an integer to its ordinal string representation.
    Examples: 1 -> '1st', 2 -> '2nd', 3 -> '3rd', 11 -> '11th', 21 -> '21st'

    Args:
        n: Integer to convert

    Returns:
        Ordinal string (e.g., '1st', '2nd', '3rd')
    """
    if n % 100 in (11, 12, 13):
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"


class StockAlertNotifier(BaseNotifier):
    """Handles stock price drop and rise alerts."""

    def __init__(self, excel_logger=None):
        """
        Initialize stock alert notifier.

        Args:
            excel_logger: Optional AlertExcelLogger instance for logging alerts
        """
        super().__init__()
        self.excel_logger = excel_logger

    def send_alert(self, symbol: str, drop_percent: float, current_price: float,
                   previous_price: float, alert_type: str = "10min",
                   volume_data: dict = None, market_cap_cr: float = None,
                   rsi_analysis: dict = None, oi_analysis: dict = None,
                   sector_context: dict = None, alert_count: int = None,
                   direction_arrows: str = None) -> bool:
        """
        Send a stock drop alert to Telegram channel.

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
            alert_count: Optional count of how many times this stock has alerted today
            direction_arrows: Optional string showing direction history (e.g., "↓ ↑ ↓")

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_alert_message(
            symbol, drop_percent, current_price, previous_price, alert_type,
            volume_data, market_cap_cr, rsi_analysis, oi_analysis, sector_context,
            alert_count, direction_arrows
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
                        priority: str = "NORMAL", alert_count: int = None,
                        direction_arrows: str = None) -> bool:
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
            alert_count: Optional count of how many times this stock has alerted today
            direction_arrows: Optional string showing direction history (e.g., "↓ ↑ ↓")

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_1min_alert_message(
            symbol, direction, current_price, previous_price, change_percent,
            volume_data, market_cap_cr, rsi_analysis, oi_analysis, priority,
            alert_count, direction_arrows
        )
        telegram_success = self._send_message(message)

        # Excel logging is handled by onemin_monitor.py
        # (we don't duplicate it here to avoid circular dependencies)

        return telegram_success

    def _format_1min_alert_message(self, symbol: str, direction: str,
                                     current_price: float, previous_price: float,
                                     change_percent: float, volume_data: dict = None,
                                     market_cap_cr: float = None, rsi_analysis: dict = None,
                                     oi_analysis: dict = None, priority: str = "NORMAL",
                                     alert_count: int = None, direction_arrows: str = None) -> str:
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
            alert_count: Optional count of how many times this stock has alerted today
            direction_arrows: Optional string showing direction history (e.g., "↓ ↑ ↓")

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
            # Color badge for 1-min alerts (red for drops, green for rises)
            color_badge = "🔴🔴🔴"
        else:
            emoji = "📈"
            direction_text = "RISE"
            direction_color = "🟢"
            color_badge = "🟢🟢🟢"

        # Priority badge
        if priority == "HIGH":
            priority_badge = "🔥🔥 <b>HIGH PRIORITY</b> 🔥🔥\n"
            priority_note = "(Strong momentum acceleration detected)"
        else:
            priority_badge = "⚡ <b>NORMAL PRIORITY</b> ⚡\n"
            priority_note = "(Fast move without acceleration)"

        # Ultra-fast alert header with color badge and UNIQUE STYLE for 1-min alerts
        header = (
            f"{color_badge} <b><i>⚡ 1-MIN ULTRA-FAST ALERT ⚡</i></b> {color_badge}\n"
            f"{priority_badge}"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"{emoji} <b>{direction_color} {direction_text} DETECTED {direction_color}</b> {emoji}\n"
            f"<i>{priority_note}</i>\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
        )

        # Add timestamp in IST
        from market_utils import get_current_ist_time
        current_time = get_current_ist_time()
        time_str = current_time.strftime("%I:%M:%S %p")

        # Base message
        message = f"{header}\n\n"

        # Alert count indicator with direction arrows
        if alert_count and alert_count > 0:
            if direction_arrows:
                message += f"🔔 <b>{_ordinal(alert_count)} Alert</b> for {display_symbol} today: {direction_arrows}\n\n"
            else:
                message += f"🔔 <b>{_ordinal(alert_count)} Alert</b> for {display_symbol} today\n\n"

        message += f"📊 <b>Stock:</b> {display_symbol}\n"
        message += f"⏰ <b>Alert Time:</b> {time_str}\n"

        # Add quarterly results indicator if applicable
        results_label = get_results_label(display_symbol)
        if results_label:
            message += f"<b>{results_label}</b>\n"
        message += "\n"

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
            message += format_rsi_section(rsi_analysis, is_priority=True)

        # OI section
        if oi_analysis:
            message += format_oi_section(oi_analysis, is_priority=True)

        # Footer
        message += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "⚡ <b>Fastest alert system - 1-min detection!</b>\n"
        message += "⏱️ 5x faster than standard 5-min alerts"

        return message

    def _format_alert_message(self, symbol: str, drop_percent: float,
                              current_price: float, previous_price: float,
                              alert_type: str = "10min", volume_data: dict = None,
                              market_cap_cr: float = None, rsi_analysis: dict = None,
                              oi_analysis: dict = None, sector_context: dict = None,
                              alert_count: int = None, direction_arrows: str = None) -> str:
        """
        Format alert message with stock details for both drops and rises.

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
            alert_count: Optional count of how many times this stock has alerted today
            direction_arrows: Optional string showing direction history (e.g., "↓ ↑ ↓")

        Returns:
            Formatted message string
        """
        # Remove .NS suffix for display
        display_symbol = symbol.replace('.NS', '')

        # Check if this is a pharma stock
        is_pharma = display_symbol in config.PHARMA_STOCKS

        # Determine if this is a rise or drop alert
        is_rise = alert_type.endswith('_rise')

        # Alert header based on type (with priority emphasis and color coding)
        if is_rise:
            if alert_type == "volume_spike_rise":
                header = (
                    "🟢🟢🟢 <b>PRIORITY ALERT</b> 🟢🟢🟢\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "⚡ <b>URGENT</b> ⚡ VOLUME SPIKE RISE ⚡ <b>URGENT</b> ⚡\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
            elif alert_type == "5min_rise":
                header = "🟢🟢 <b>ALERT:</b> Rapid 5-Min Rise!"
            elif alert_type == "30min_rise":
                header = "🟢 <b>ALERT:</b> Gradual 30-Min Rise!"
            else:
                header = "🟢 <b>ALERT:</b> Stock Rise Detected"
        else:
            if alert_type == "volume_spike":
                header = (
                    "🔴🔴🔴 <b>PRIORITY ALERT</b> 🔴🔴🔴\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "⚡ <b>URGENT</b> ⚡ VOLUME SPIKE DROP ⚡ <b>URGENT</b> ⚡\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
            elif alert_type == "5min":
                header = "🔴🔴 <b>ALERT:</b> Rapid 5-Min Drop!"
            elif alert_type == "30min":
                header = "🔴 <b>ALERT:</b> Gradual 30-Min Drop!"
            else:
                header = "🔴 <b>ALERT:</b> Stock Drop Detected"

        # Base message - use bold for priority alerts
        is_priority = alert_type in ["volume_spike", "volume_spike_rise"]

        # Add timestamp in IST
        from market_utils import get_current_ist_time
        current_time = get_current_ist_time()
        time_str = current_time.strftime("%I:%M:%S %p")

        if is_priority:
            message = f"{header}\n\n"
        else:
            message = f"{header}\n\n"

        # Alert count indicator with direction arrows
        if alert_count and alert_count > 0:
            if direction_arrows:
                message += f"🔔 <b>{_ordinal(alert_count)} Alert</b> for {display_symbol} today: {direction_arrows}\n\n"
            else:
                message += f"🔔 <b>{_ordinal(alert_count)} Alert</b> for {display_symbol} today\n\n"

        if is_priority:
            message += f"📊 <b>Stock: {display_symbol}</b>\n⏰ Alert Time: {time_str}\n"
        else:
            message += f"📊 Stock: {display_symbol}\n⏰ Alert Time: {time_str}\n"

        # Add quarterly results indicator if applicable
        results_label = get_results_label(display_symbol)
        if results_label:
            message += f"<b>{results_label}</b>\n"

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
            message += format_rsi_section(rsi_analysis, is_priority)

        # Add OI Analysis (if enabled and available)
        if oi_analysis and config.ENABLE_OI_ANALYSIS:
            message += format_oi_section(oi_analysis, is_priority)

        # Add Sector Context (if enabled and available)
        if sector_context and config.ENABLE_SECTOR_CONTEXT_IN_ALERTS:
            message += format_sector_context(sector_context, is_priority, is_drop=not is_rise)

        return message
