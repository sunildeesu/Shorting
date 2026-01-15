"""Pattern alert notifier for pre-market and EOD pattern detection."""
from typing import List, Dict
from datetime import datetime
import logging
from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class PatternAlertNotifier(BaseNotifier):
    """Handles pre-market and EOD pattern detection alerts."""

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

    def send_eod_pattern_summary(self, pattern_results: List[Dict], analysis_date: datetime) -> bool:
        """
        Send consolidated EOD pattern detection summary to Telegram.

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
        import pattern_utils as pu

        # Market opens in X minutes
        now = datetime.now()
        market_open_time = datetime.combine(now.date(), datetime.strptime('09:15', '%H:%M').time())
        minutes_to_open = max(0, int((market_open_time - now).total_seconds() / 60))

        # Market regime emoji
        regime_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(market_regime, "🟡")

        # Header with PURPLE color badge and UNIQUE STYLE for pre-market alerts
        message = f"🟣🟣🟣 <b><u>PRE-MARKET PATTERN ALERT</u></b> 🟣🟣🟣\n"
        message += "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n"
        message += f"🕘 <b>Analysis Time:</b> {now.strftime('%I:%M %p')}\n"
        message += f"⏰ <b>Market Opens in:</b> {minutes_to_open} minutes\n"
        message += f"{regime_emoji} <b>Market Regime:</b> {market_regime}\n"
        message += "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n\n"

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

    def _filter_eod_patterns(self, pattern_results: List[Dict]) -> Dict[str, List[Dict]]:
        """Filter and group patterns for Telegram alert."""

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
        """Format consolidated EOD pattern message."""

        # Header with BLUE color badge and UNIQUE STYLE for EOD Pattern Detection
        message = (
            "🔵🔵🔵 <b><code>EOD PATTERN DETECTION</code></b> 🔵🔵🔵\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"📅 Date: {analysis_date.strftime('%d %B %Y')}\n"
            f"⏰ Analysis Time: 3:30 PM\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
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
