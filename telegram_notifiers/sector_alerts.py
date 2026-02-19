"""Sector alert notifier for sector rotation and EOD sector summaries."""
from datetime import datetime
import logging
from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class SectorAlertNotifier(BaseNotifier):
    """Handles sector rotation and EOD sector summary alerts."""

    def send_sector_rotation_alert(self, rotation_data: dict) -> bool:
        """
        Send sector rotation alert to Telegram channel.

        Args:
            rotation_data: Rotation data dict with top gainers/losers

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_sector_rotation_message(rotation_data)
        return self._send_message(message)

    def send_eod_sector_summary(self, sector_analysis: dict) -> bool:
        """
        Send end-of-day sector performance summary to Telegram channel.

        Args:
            sector_analysis: Sector analysis dict with all sector metrics

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_eod_sector_summary(sector_analysis)
        return self._send_message(message)

    def _format_sector_rotation_message(self, rotation_data: dict) -> str:
        """
        Format sector rotation alert message.

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

        # Header with PURPLE color badge and UNIQUE STYLE for Sector Rotation
        message = (
            "🟣🟣🟣 <b><u>SECTOR ROTATION DETECTED</u></b> 🟣🟣🟣\n"
            "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n"
            "💰 <b>FUND FLOW ALERT</b> 💰\n"
            "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n\n"
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

    def _format_eod_sector_summary(self, sector_analysis: dict) -> str:
        """
        Format end-of-day sector performance summary.

        Args:
            sector_analysis: Sector analysis dict with timestamp and sectors

        Returns:
            Formatted EOD summary message
        """
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

        # Header with BLUE color badge and UNIQUE STYLE for EOD Sector Summary
        message = (
            "🔵🔵🔵 <b><code>EOD SECTOR SUMMARY</code></b> 🔵🔵🔵\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"📅 Date: <b>{date_str}</b>\n"
            f"⏰ Time: {time_str}\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        )

        # Sort sectors by full-day performance
        sorted_sectors = sorted(
            sectors.items(),
            key=lambda x: x[1].get('price_change_day', 0),
            reverse=True
        )

        # Calculate overall market sentiment (full day)
        total_up = sum(s[1].get('stocks_up_day', 0) for s in sorted_sectors)
        total_down = sum(s[1].get('stocks_down_day', 0) for s in sorted_sectors)
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
            price_change = data.get('price_change_day', 0)
            volume_ratio = data.get('volume_ratio', 1.0)
            stocks_up = data.get('stocks_up_day', 0)
            total = data.get('total_stocks', 0)

            emoji = "🚀" if price_change > 1.0 else "📈"
            message += (
                f"{i}. <b>{sector_name}</b> {emoji}\n"
                f"   • Day Change: <b>{price_change:+.2f}%</b>\n"
                f"   • Volume: {volume_ratio:.2f}x\n"
                f"   • Breadth: {stocks_up}/{total} up\n"
            )
        message += "\n"

        # Bottom 3 Losers
        message += "🔴 <b>TOP 3 LOSING SECTORS:</b>\n"
        for i, (sector, data) in enumerate(reversed(sorted_sectors[-3:]), 1):
            sector_name = sector.replace('_', ' ').title()
            price_change = data.get('price_change_day', 0)
            volume_ratio = data.get('volume_ratio', 1.0)
            stocks_down = data.get('stocks_down_day', 0)
            total = data.get('total_stocks', 0)

            emoji = "🔻" if price_change < -1.0 else "📉"
            message += (
                f"{i}. <b>{sector_name}</b> {emoji}\n"
                f"   • Day Change: <b>{price_change:+.2f}%</b>\n"
                f"   • Volume: {volume_ratio:.2f}x\n"
                f"   • Breadth: {stocks_down}/{total} down\n"
            )
        message += "\n"

        # Full sector rankings
        message += "📋 <b>ALL SECTORS RANKED:</b>\n"
        for i, (sector, data) in enumerate(sorted_sectors, 1):
            sector_name = sector.replace('_', ' ').title()
            price_change = data.get('price_change_day', 0)

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
            "📊 Full day change (open to close)"
        )

        return message
