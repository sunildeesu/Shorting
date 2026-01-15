"""Volume profile alert notifier for EOD volume profile analysis."""
from typing import List, Dict
from datetime import datetime
import logging
import config
from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class VolumeProfileAlertNotifier(BaseNotifier):
    """Handles volume profile analysis alerts."""

    def send_volume_profile_summary(self,
                                    profile_results: List[Dict],
                                    analysis_time: datetime,
                                    execution_window: str) -> bool:
        """
        Send volume profile summary to Telegram.

        Args:
            profile_results: List of volume profile results
            analysis_time: Time of analysis
            execution_window: "3:00PM" or "3:15PM"

        Returns:
            True if message sent successfully, False if no high-confidence patterns
        """
        # Filter high-confidence P-shaped and B-shaped profiles
        p_shaped = [r for r in profile_results
                   if r.get('profile_shape') == 'P-SHAPE'
                   and r.get('confidence', 0) >= config.VOLUME_PROFILE_MIN_CONFIDENCE]
        b_shaped = [r for r in profile_results
                   if r.get('profile_shape') == 'B-SHAPE'
                   and r.get('confidence', 0) >= config.VOLUME_PROFILE_MIN_CONFIDENCE]

        # Skip if no high-confidence patterns
        if not p_shaped and not b_shaped:
            logger.info("No high-confidence volume profiles to alert")
            return False

        # Sort by confidence (descending)
        p_shaped.sort(key=lambda x: x.get('confidence', 0), reverse=True)
        b_shaped.sort(key=lambda x: x.get('confidence', 0), reverse=True)

        # Format message
        message = self._format_volume_profile_message(
            p_shaped, b_shaped, analysis_time, execution_window
        )

        return self._send_message(message)

    def _format_volume_profile_message(self,
                                       p_shaped: List[Dict],
                                       b_shaped: List[Dict],
                                       analysis_time: datetime,
                                       execution_window: str) -> str:
        """Format volume profile summary message."""

        # Header with PURPLE color badge and UNIQUE STYLE for Volume Profile Analysis
        time_label = "3:00 PM" if "3:00" in execution_window else "3:15 PM"
        message = (
            "🟣🟣🟣 <b><code>VOLUME PROFILE ANALYSIS</code></b> 🟣🟣🟣\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"📅 Date: {analysis_time.strftime('%d %B %Y')}\n"
            f"⏰ Analysis Time: {time_label}\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        )

        # P-shaped profiles (Bullish Strength)
        if p_shaped:
            message += f"📈 <b>P-SHAPED PROFILES</b> (Bullish Strength)\n"
            message += f"<i>Price held at highs - buyers in control</i>\n\n"

            for idx, result in enumerate(p_shaped[:10], 1):  # Limit to top 10
                symbol = result.get('symbol', 'UNKNOWN')
                poc_price = result.get('poc_price', 0)
                poc_position = result.get('poc_position', 0) * 100
                confidence = result.get('confidence', 0)
                value_area_high = result.get('value_area_high', 0)
                value_area_low = result.get('value_area_low', 0)

                conf_emoji = "🟢" if confidence >= 8.5 else "🟡"  # Green for bullish

                message += (
                    f"{idx}. <b>{symbol}</b> - Confidence: {confidence:.1f}/10 {conf_emoji}\n"
                    f"   📍 POC at <b>{poc_position:.1f}%</b> of range (₹{poc_price:.2f})\n"
                    f"   📊 Value Area: ₹{value_area_low:.2f} - ₹{value_area_high:.2f}\n\n"
                )

        # B-shaped profiles (Bearish Weakness)
        if b_shaped:
            message += f"📉 <b>B-SHAPED PROFILES</b> (Bearish Weakness)\n"
            message += f"<i>Price stuck at lows - sellers in control</i>\n\n"

            for idx, result in enumerate(b_shaped[:10], 1):  # Limit to top 10
                symbol = result.get('symbol', 'UNKNOWN')
                poc_price = result.get('poc_price', 0)
                poc_position = result.get('poc_position', 0) * 100
                confidence = result.get('confidence', 0)
                value_area_high = result.get('value_area_high', 0)
                value_area_low = result.get('value_area_low', 0)

                conf_emoji = "🔴" if confidence >= 8.5 else "🟠"  # Red for bearish

                message += (
                    f"{idx}. <b>{symbol}</b> - Confidence: {confidence:.1f}/10 {conf_emoji}\n"
                    f"   📍 POC at <b>{poc_position:.1f}%</b> of range (₹{poc_price:.2f})\n"
                    f"   📊 Value Area: ₹{value_area_low:.2f} - ₹{value_area_high:.2f}\n\n"
                )

        # Footer
        total_patterns = len(p_shaped) + len(b_shaped)
        message += (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Total Patterns:</b> {total_patterns} stocks\n"
            f"🟢 <b>P-Shaped:</b> {len(p_shaped)} (Bullish) | 🔴 <b>B-Shaped:</b> {len(b_shaped)} (Bearish)\n"
            f"💡 <b>Min Confidence:</b> {config.VOLUME_PROFILE_MIN_CONFIDENCE}/10\n\n"
            "📚 <b>Interpretation:</b>\n"
            "  • P-shape: POC at top of range = strength (bullish continuation)\n"
            "  • B-shape: POC at bottom = weakness (bearish continuation)\n"
            "  • POC = Point of Control (highest volume price)\n\n"
            f"📄 <b>Full Report:</b> volume_profile_{time_label.replace(' ', '').replace(':', '').lower()}_{analysis_time.strftime('%Y-%m-%d')}.xlsx"
        )

        return message
