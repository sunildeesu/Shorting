"""NIFTY option alert notifier for option selling signals and position updates."""
from datetime import datetime
import logging
from .base_notifier import BaseNotifier
from .formatting_helpers import score_emoji

logger = logging.getLogger(__name__)


class NiftyOptionAlertNotifier(BaseNotifier):
    """Handles NIFTY option selling analysis and position alerts."""

    def send_nifty_option_analysis(self, analysis_data: dict) -> bool:
        """
        Send NIFTY option selling analysis to Telegram channel.

        Args:
            analysis_data: Analysis result dict from NiftyOptionAnalyzer

        Returns:
            True if message sent successfully, False otherwise
        """
        message = self._format_nifty_option_message(analysis_data)
        return self._send_message(message)

    def send_nifty_add_position_alert(self, analysis_data: dict, layer_number: int, is_late_entry: bool = False) -> bool:
        """
        Send add position alert to Telegram.

        Args:
            analysis_data: Current analysis data
            layer_number: Layer number being added
            is_late_entry: True if this is a late entry (first position after 10 AM)

        Returns:
            True if message sent successfully
        """
        score = analysis_data.get('total_score', 0)
        nifty_spot = analysis_data.get('nifty_spot', 0)

        # Get expiry info
        expiry_analyses = analysis_data.get('expiry_analyses', [])
        first_expiry = expiry_analyses[0] if expiry_analyses else {}
        best_strategy = analysis_data.get('best_strategy', 'straddle')

        if best_strategy.lower() == 'straddle':
            strategy_data = first_expiry.get('straddle', {})
        else:
            strategy_data = first_expiry.get('strangle', {})

        strikes = strategy_data.get('strikes', {})
        total_premium = strategy_data.get('total_premium', 0)
        call_premium = strategy_data.get('call_premium', 0)
        put_premium = strategy_data.get('put_premium', 0)

        # Parse timestamp
        try:
            dt = datetime.fromisoformat(analysis_data.get('timestamp', datetime.now().isoformat()))
            date_str = dt.strftime("%d %b %Y")
            time_str = dt.strftime("%I:%M %p")
        except:
            date_str = datetime.now().strftime("%d %b %Y")
            time_str = datetime.now().strftime("%I:%M %p")

        if is_late_entry:
            message = (
                "🟢🟢 <b><i>LATE ENTRY OPPORTUNITY</i></b> 🟢🟢\n"
                "═══════════════════════════════════════\n"
                f"⏰ {date_str} | {time_str}\n"
                "═══════════════════════════════════════\n\n"
                "✅ Entry signal after 10:00 AM\n"
                f"Current Score: <b>{score:.1f}/100</b> ✅\n\n"
                "💡 Conditions improved significantly\n"
                f"Entering Layer 1 now...\n\n"
            )
        else:
            message = (
                f"🟢🟢 <b><i>ADD TO POSITION - Layer {layer_number}</i></b> 🟢🟢\n"
                "═══════════════════════════════════════\n"
                f"⏰ {date_str} | {time_str}\n"
                "═══════════════════════════════════════\n\n"
                f"💰 Current Score: <b>{score:.1f}/100</b>\n\n"
            )

        # Add strikes info
        message += (
            f"📋 <b>Recommended Layer {layer_number} Trade:</b>\n"
            f"   • NIFTY Spot: ₹{nifty_spot:,.2f}\n"
            f"   • Call: {strikes.get('call')} CE (₹{call_premium})\n"
            f"   • Put: {strikes.get('put')} PE (₹{put_premium})\n"
            f"   • Total Premium: <b>₹{total_premium}</b>\n"
            f"   • (Credit received if you execute this trade)\n\n"
            "🔔 #NIFTYOptions #AddPosition"
        )

        return self._send_message(message)

    def send_nifty_exit_alert(self, exit_data: dict) -> bool:
        """
        Send exit signal alert to Telegram.

        Args:
            exit_data: Exit analysis data

        Returns:
            True if message sent successfully
        """
        signal = exit_data.get('signal', 'HOLD_POSITION')
        urgency = exit_data.get('urgency', 'NONE')
        exit_score = exit_data.get('exit_score', 0)
        exit_reasons = exit_data.get('exit_reasons', [])

        # Parse timestamp
        try:
            dt = datetime.fromisoformat(exit_data.get('timestamp', datetime.now().isoformat()))
            date_str = dt.strftime("%d %b %Y")
            time_str = dt.strftime("%I:%M %p")
        except:
            date_str = datetime.now().strftime("%d %b %Y")
            time_str = datetime.now().strftime("%I:%M %p")

        if signal == 'EXIT_NOW':
            urgency_emoji = "🚨" if urgency == "HIGH" else "⚠️"
            # RED for critical exit with UNIQUE STYLE
            color_badge = "🔴🔴🔴" if urgency == "HIGH" else "🔴🔴"
            message = (
                f"{color_badge} <b><i>EXIT POSITION NOW</i></b> {color_badge}\n"
                "═══════════════════════════════════════\n"
                f"⏰ {date_str} | {time_str}\n"
                "═══════════════════════════════════════\n\n"
                f"❌ EXIT SIGNAL (Urgency: <b>{urgency}</b>)\n"
                f"Exit Score: {exit_score}/100\n\n"
            )

            if exit_reasons:
                message += "⚠️ <b>Exit Triggers:</b>\n"
                for reason in exit_reasons:
                    message += f"   • {reason}\n"
                message += "\n"

            message += (
                "💡 <b>Recommendation:</b>\n"
                "Exit position immediately - Market conditions deteriorated\n\n"
                "🔔 #NIFTYOptions #ExitSignal"
            )
        elif signal == 'CONSIDER_EXIT':
            # ORANGE for warning/caution with UNIQUE STYLE
            message = (
                "🟠🟠 <b><i>CONSIDER EXIT</i></b> 🟠🟠\n"
                "═══════════════════════════════════════\n"
                f"⏰ {date_str} | {time_str}\n"
                "═══════════════════════════════════════\n\n"
                f"Exit Score: {exit_score}/100 (Low urgency)\n\n"
            )

            if exit_reasons:
                message += "⚠️ <b>Warning Signs:</b>\n"
                for reason in exit_reasons:
                    message += f"   • {reason}\n"
                message += "\n"

            message += (
                "💡 <b>Recommendation:</b>\n"
                "Monitor closely - Consider exiting if conditions worsen\n\n"
                "🔔 #NIFTYOptions #ExitWarning"
            )
        else:
            return True  # Don't send alert for HOLD_POSITION

        return self._send_message(message)

    def send_nifty_eod_summary(self, position_state: dict, current_analysis: dict) -> bool:
        """
        Send end-of-day position summary to Telegram.

        Args:
            position_state: Current position state from PositionStateManager
            current_analysis: Latest analysis data

        Returns:
            True if message sent successfully
        """
        status = position_state.get('status', 'NO_POSITION')

        if status == 'NO_POSITION' or not position_state:
            # No position today - send brief summary with BLUE color badge and UNIQUE STYLE
            message = (
                "🔵🔵 <b><code>END OF DAY SUMMARY</code></b> 🔵🔵\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                f"📅 {datetime.now().strftime('%d %b %Y')}\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
                "❌ <b>No Position Today</b>\n"
                "No entry signal met criteria.\n\n"
                "🔔 #NIFTYOptions #DailySummary"
            )
            return self._send_message(message)

        # Extract position details
        layers = position_state.get('layers', [])
        entry_timestamp = position_state.get('entry_timestamp', '')
        entry_score = position_state.get('entry_score', 0)
        entry_nifty = position_state.get('entry_nifty_spot', 0)
        entry_premium = position_state.get('entry_premium', 0)
        entry_strikes = position_state.get('entry_strikes', {})

        current_score = current_analysis.get('total_score', 0)
        current_nifty = current_analysis.get('nifty_spot', 0)

        # Calculate duration
        try:
            entry_dt = datetime.fromisoformat(entry_timestamp)
            now = datetime.now()
            duration_minutes = int((now - entry_dt).total_seconds() / 60)
            duration_hours = duration_minutes // 60
            duration_mins = duration_minutes % 60
            duration_str = f"{duration_hours}h {duration_mins}m" if duration_hours > 0 else f"{duration_mins}m"
            entry_time_str = entry_dt.strftime("%I:%M %p")
        except:
            duration_str = "Unknown"
            entry_time_str = "Unknown"

        # Calculate score change
        score_change = current_score - entry_score
        score_emoji_str = "📈" if score_change >= 0 else "📉"

        # Calculate NIFTY move
        nifty_move = current_nifty - entry_nifty
        nifty_move_pct = (nifty_move / entry_nifty) * 100 if entry_nifty > 0 else 0
        nifty_emoji = "🟢" if nifty_move >= 0 else "🔴"

        if status == 'ENTERED':
            # Active position with BLUE color badge and UNIQUE STYLE
            message = (
                "🔵🔵 <b><code>END OF DAY SUMMARY - POSITION ACTIVE</code></b> 🔵🔵\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                f"📅 {datetime.now().strftime('%d %b %Y')}\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            )

            # Entry info
            message += (
                f"✅ <b>Position Entered: {entry_time_str}</b>\n"
                f"   • Layers: {len(layers)}/3\n"
                f"   • Entry Score: {entry_score:.1f}/100\n"
                f"   • Duration: {duration_str}\n\n"
            )

            # Strike details
            message += (
                f"📋 <b>Recommended Trade (ATM {entry_strikes.get('call')}):</b>\n"
                f"   • Straddle Premium: ₹{entry_premium:.0f}\n"
                f"   • (Credit received if trade executed)\n\n"
            )

            # Current status
            message += (
                f"📊 <b>Current Status:</b>\n"
                f"   • Score: {current_score:.1f}/100 ({score_emoji_str} {score_change:+.1f})\n"
                f"   • NIFTY: ₹{current_nifty:,.2f} ({nifty_emoji} {nifty_move:+.2f} / {nifty_move_pct:+.2f}%)\n\n"
            )

            # Layer breakdown if multiple
            if len(layers) > 1:
                message += "📌 <b>Layer Breakdown:</b>\n"
                for layer in layers:
                    layer_num = layer.get('layer_number', 0)
                    layer_score = layer.get('score', 0)
                    layer_time = layer.get('timestamp', '')
                    try:
                        layer_dt = datetime.fromisoformat(layer_time)
                        layer_time_str = layer_dt.strftime("%I:%M %p")
                    except:
                        layer_time_str = "Unknown"
                    message += f"   • Layer {layer_num}: {layer_score:.1f}/100 at {layer_time_str}\n"
                message += "\n"

            # Status
            if score_change >= 10:
                status_msg = "✅ Excellent - Score improved significantly"
            elif score_change >= 0:
                status_msg = "✅ Good - Score holding steady"
            elif score_change >= -10:
                status_msg = "⚠️ Caution - Minor score decline"
            else:
                status_msg = "🚨 Alert - Significant score decline"

            message += f"💡 <b>Status:</b> {status_msg}\n\n"

        elif status == 'EXITED':
            # Position exited during the day
            exit_timestamp = position_state.get('exit_timestamp', '')
            exit_score = position_state.get('exit_score', 0)
            exit_reason = position_state.get('exit_reason', 'Unknown')

            try:
                exit_dt = datetime.fromisoformat(exit_timestamp)
                exit_time_str = exit_dt.strftime("%I:%M %p")
            except:
                exit_time_str = "Unknown"

            # BLUE color badge and UNIQUE STYLE for informational EOD summary
            message = (
                "🔵🔵 <b><code>END OF DAY SUMMARY - POSITION EXITED</code></b> 🔵🔵\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                f"📅 {datetime.now().strftime('%d %b %Y')}\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            )

            # Entry info
            message += (
                f"✅ <b>Entered: {entry_time_str}</b>\n"
                f"   • Entry Score: {entry_score:.1f}/100\n"
                f"   • Recommended Premium: ₹{entry_premium:.0f}\n\n"
            )

            # Exit info
            message += (
                f"❌ <b>Exited: {exit_time_str}</b>\n"
                f"   • Exit Score: {exit_score:.1f}/100\n"
                f"   • Duration: {duration_str}\n"
                f"   • Reason: {exit_reason}\n\n"
            )

            # Score change
            score_change = exit_score - entry_score
            message += f"📊 <b>Score Change:</b> {score_change:+.1f} points\n\n"

            # Status
            if score_change >= 0:
                status_msg = "✅ Good exit - Score improved or held"
            else:
                status_msg = "⚠️ Exit on deterioration - Correct decision"

            message += f"💡 <b>Status:</b> {status_msg}\n\n"

        message += "🔔 #NIFTYOptions #DailySummary"

        return self._send_message(message)

    def _format_nifty_option_message(self, data: dict) -> str:
        """
        Format NIFTY option selling analysis message.

        Args:
            data: Analysis result dict with signal, scores, and recommendations

        Returns:
            Formatted Telegram message with HTML formatting
        """
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
        vix_trend = data.get('vix_trend', 0)
        iv_rank = data.get('iv_rank', 50.0)
        market_regime = data.get('market_regime', 'UNKNOWN')
        best_strategy = data.get('best_strategy', 'straddle').upper()
        recommendation = data.get('recommendation', '')
        risk_factors = data.get('risk_factors', [])
        breakdown = data.get('breakdown', {})
        expiry_analyses = data.get('expiry_analyses', [])

        # NEW: Tier system fields
        signal_tier = data.get('signal_tier', signal)
        position_size = data.get('position_size', 1.0)
        premium_quality = data.get('premium_quality', 'TRADEABLE')

        # Parse timestamp
        try:
            dt = datetime.fromisoformat(data.get('timestamp', datetime.now().isoformat()))
            date_str = dt.strftime("%d %b %Y")
            time_str = dt.strftime("%I:%M %p")
        except:
            date_str = datetime.now().strftime("%d %b %Y")
            time_str = datetime.now().strftime("%I:%M %p")

        # Signal emoji and styling with COLOR BADGES
        # NEW: Tier-specific emojis and colors
        tier_emoji_map = {
            'SELL_STRONG': '🔥',
            'SELL_MODERATE': '⚠️',
            'SELL_WEAK': '⚡',
            'AVOID': '🛑'
        }
        tier_display_map = {
            'SELL_STRONG': 'SELL - EXCELLENT',
            'SELL_MODERATE': 'SELL - GOOD',
            'SELL_WEAK': 'SELL - WEAK',
            'AVOID': 'AVOID'
        }
        # Color badges for header
        tier_color_badge_map = {
            'SELL_STRONG': '🟢🟢🟢',
            'SELL_MODERATE': '🟢🟢',
            'SELL_WEAK': '🟠🟠',
            'AVOID': '🔴🔴🔴'
        }

        if signal == 'SELL':
            signal_emoji = "✅"
            signal_style = "🟢🟢"
        elif signal == 'HOLD':
            signal_emoji = "⏸️"
            signal_style = "🟡🟡"
        else:  # AVOID
            signal_emoji = "🛑"
            signal_style = "🔴🔴🔴"

        # Get tier-specific emoji, display, and color badge
        tier_emoji = tier_emoji_map.get(signal_tier, signal_emoji)
        tier_display = tier_display_map.get(signal_tier, signal)
        tier_color_badge = tier_color_badge_map.get(signal_tier, signal_style)

        # Header with tier-specific color badge and UNIQUE STYLE for Options
        message = (
            f"{tier_color_badge} <b><i>NIFTY OPTION SELLING SIGNAL</i></b> {tier_color_badge}\n"
            "═══════════════════════════════════════\n"
            f"📅 <b>{date_str}</b> | ⏰ {time_str}\n"
            "═══════════════════════════════════════\n\n"
        )

        # Signal and Score
        # Check if tiered signals are enabled
        import config as cfg
        if cfg.ENABLE_TIERED_SIGNALS and signal_tier != 'AVOID':
            message += (
                f"📊 <b>SIGNAL: {tier_display} {tier_emoji}</b>\n"
                f"   Score: <b>{total_score:.1f}/100</b>\n"
                f"   Position Size: <b>{int(position_size * 100)}%</b>\n"
                f"💰 NIFTY Spot: <b>₹{nifty_spot:,.2f}</b>\n\n"
                f"💎 <b>PREMIUM QUALITY: {premium_quality.split(' (')[0]}</b>\n"
                f"   {premium_quality.split(' (')[1] if '(' in premium_quality else ''}\n\n"
            )
        else:
            # Original format for AVOID or when tiered signals disabled
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
        vega_score = breakdown.get('vega_score', 0)
        vix_score = breakdown.get('vix_score', 0)
        regime_score = breakdown.get('regime_score', 0)
        oi_score = breakdown.get('oi_score', 0)

        message += f"   ⏰ Theta Score: <b>{theta_score:.1f}/100</b> {score_emoji(theta_score)} (Time decay)\n"
        message += f"   📉 Gamma Score: <b>{gamma_score:.1f}/100</b> {score_emoji(gamma_score)} (Stability)\n"
        message += f"   📊 Vega Score: <b>{vega_score:.1f}/100</b> {score_emoji(vega_score)} (VIX sensitivity)\n"

        # VIX score with trend and IV Rank indicators
        vix_trend_emoji = ""
        vix_trend_text = ""
        if vix_trend > 1.5:
            vix_trend_emoji = "⬆️"
            vix_trend_text = f" <b>(Rising {vix_trend:+.1f})</b> ⚠️"
        elif vix_trend < -1.5:
            vix_trend_emoji = "⬇️"
            vix_trend_text = f" <b>(Falling {vix_trend:+.1f})</b> ✅"
        else:
            vix_trend_emoji = "➡️"
            vix_trend_text = f" (Stable {vix_trend:+.1f})"

        # IV Rank indicator
        iv_rank_text = ""
        if iv_rank > 75:
            iv_rank_text = f", <b>IV Rank {iv_rank:.0f}%</b> (HIGH - rich premiums) ✅"
        elif iv_rank < 25:
            iv_rank_text = f", <b>IV Rank {iv_rank:.0f}%</b> (LOW - cheap premiums) ⚠️"
        else:
            iv_rank_text = f", IV Rank {iv_rank:.0f}%"

        message += f"   🌊 VIX Score: <b>{vix_score:.1f}/100</b> {score_emoji(vix_score)} (VIX {vix:.1f}{vix_trend_text}{iv_rank_text})\n"
        message += f"   📈 Market Regime: <b>{regime_score:.1f}/100</b> ({market_regime})\n"
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

        # SELL_WEAK specific guidance
        if cfg.ENABLE_TIERED_SIGNALS and signal_tier == 'SELL_WEAK':
            message += (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚠️ <b>WEAK SIGNAL - USER DECISION REQUIRED</b> ⚠️\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "<b>Why Weak Signal?</b>\n"
                f"   • IV Rank in bottom 10-15% of past year ({iv_rank:.1f}%)\n"
                "   • Premiums below average (75-80% of fair value)\n"
                "   • Lower profit potential vs SELL_STRONG\n\n"
                "<b>⚖️ Trade Decision:</b>\n"
                "   ✅ <b>If YES:</b> Trade 50% of normal size\n"
                "   ❌ <b>If NO:</b> Wait for SELL_MODERATE (IV>15%) or SELL_STRONG (IV>25%)\n\n"
                "<b>💡 Recommendation:</b>\n"
                "   Only trade if you understand the trade-offs.\n"
                "   Consider waiting for higher IV Rank days.\n\n"
            )

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
