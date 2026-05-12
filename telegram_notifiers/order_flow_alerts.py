"""Order flow alert messages — crowd psychology signals from bid/ask depth analysis."""

import logging
from datetime import datetime
from typing import List

from telegram_notifiers.base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class OrderFlowAlertNotifier(BaseNotifier):
    """Formats and sends order flow alert messages to the main Telegram channel."""

    def send_bullish_imbalance(self, symbol: str, bai: float, price: float,
                               price_change_pct: float, depth_ratio: float,
                               buy_volume: int, sell_volume: int,
                               signal_label: str = 'Bullish Pressure',
                               wall_context: str = '') -> bool:
        direction = "▲" if price_change_pct >= 0 else "▼"
        sign = "+" if price_change_pct >= 0 else ""
        delta = buy_volume - sell_volume
        delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"

        msg = (
            f"📈 <b>ORDER FLOW: {signal_label}</b>\n\n"
            f"📌 <b>{symbol}</b>  ₹{price:,.2f} {direction}{sign}{price_change_pct:.2f}%\n"
            f"⏰ {datetime.now().strftime('%I:%M %p')}\n\n"
            f"📊 <b>BAI:</b> +{bai:.3f}  |  <b>Depth:</b> {depth_ratio:.1f}×\n"
            f"📦 <b>Delta:</b> {delta_str}  |  🟢 {buy_volume:,}  🔴 {sell_volume:,}"
        )
        if wall_context:
            msg += f"\n{wall_context}"
        return self.send_debug(msg)

    def send_bearish_imbalance(self, symbol: str, bai: float, price: float,
                               price_change_pct: float, depth_ratio: float,
                               buy_volume: int, sell_volume: int,
                               signal_label: str = 'Bearish Pressure',
                               wall_context: str = '') -> bool:
        direction = "▼" if price_change_pct <= 0 else "▲"
        sign = "+" if price_change_pct >= 0 else ""
        delta = buy_volume - sell_volume
        delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"

        msg = (
            f"📉 <b>ORDER FLOW: {signal_label}</b>\n\n"
            f"📌 <b>{symbol}</b>  ₹{price:,.2f} {direction}{sign}{price_change_pct:.2f}%\n"
            f"⏰ {datetime.now().strftime('%I:%M %p')}\n\n"
            f"📊 <b>BAI:</b> {bai:.3f}  |  <b>Depth:</b> {depth_ratio:.2f}×\n"
            f"📦 <b>Delta:</b> {delta_str}  |  🟢 {buy_volume:,}  🔴 {sell_volume:,}"
        )
        if wall_context:
            msg += f"\n{wall_context}"
        return self.send_debug(msg)

    def send_overnight_bullish(self, symbol: str, price: float,
                               score: int, signals: str,
                               bai: float, fut_bai_delta: float) -> bool:
        """
        Overnight Hold alert — institutional BULLISH signal in closing window.
        Strategy: buy at today's EOD close, sell next day at 9:25 AM.
        Backtest: 80% win rate, +0.80% avg on quality BULLISH signals after 2 PM.
        """
        msg = (
            f"🌙 <b>OVERNIGHT HOLD — Institutional Buying</b>\n\n"
            f"📌 <b>{symbol}</b>  ₹{price:,.2f}\n"
            f"⏰ {datetime.now().strftime('%I:%M %p')} (closing window)\n\n"
            f"📊 <b>Score:</b> {score}/12  |  <b>BAI:</b> +{bai:.3f}  |  "
            f"<b>FUT Δ:</b> +{fut_bai_delta:.3f}\n"
            f"🔍 <b>Signals:</b> {signals}\n\n"
            f"💡 <b>Strategy:</b> Buy at close (~3:29 PM), sell tomorrow 9:25 AM\n"
            f"⚠️ <b>Note:</b> Broad crash-day filter active | Use small size"
        )
        return self.send_debug(msg)

    def send_absorption_alert(self, symbol: str, signal_type: str, price: float,
                              wall_side: str, wall_qty: int, wall_price: float,
                              absorption_strength: float, volume_delta: int) -> bool:
        """
        Absorption: heavy order flow one direction but price NOT moving.
        signal_type: 'BUY_ABSORPTION' (bearish) or 'SELL_ABSORPTION' (bullish reversal).
        """
        if signal_type == 'SELL_ABSORPTION':
            emoji = "🔄"
            header = "Absorption Signal (BULLISH)"
            desc = "Sell wall being absorbed\nSellers present but price NOT falling → buyers absorbing"
            wall_label = "ASK"
            verdict = "⚠️ Potential reversal <b>upward</b>"
        else:
            emoji = "🔄"
            header = "Absorption Signal (BEARISH)"
            desc = "Buy wall being absorbed\nBuyers present but price NOT rising → sellers absorbing"
            wall_label = "BID"
            verdict = "⚠️ Potential reversal <b>downward</b>"

        delta_str = f"+{volume_delta:,}" if volume_delta >= 0 else f"{volume_delta:,}"

        msg = (
            f"{emoji} <b>ORDER FLOW: {header}</b>\n\n"
            f"📌 <b>{symbol}</b>  ₹{price:,.2f}\n"
            f"⏰ {datetime.now().strftime('%I:%M %p')}\n\n"
            f"♻️ <b>Signal:</b> {desc}\n"
            f"📍 <b>Wall:</b> {wall_label} wall at ₹{wall_price:,.2f}  ({wall_qty:,} qty)\n"
            f"📦 <b>Volume Delta:</b> {delta_str}\n"
            f"💪 <b>Absorption Strength:</b> {absorption_strength:.2f}/1.0\n\n"
            f"{verdict}"
        )
        return self.send_debug(msg)

    def send_wall_alert(self, symbol: str, wall_side: str, wall_price: float,
                        wall_qty: int, wall_ratio: float, current_price: float) -> bool:
        """Massive single-level wall detected (> 10× average level size)."""
        if wall_side == 'BID':
            side_label = "BID (support)"
            context = "Institutional support level — watch for bounce or absorption"
        else:
            side_label = "ASK (resistance)"
            context = "Institutional resistance level — watch for breakout or rejection"

        msg = (
            f"🧱 <b>ORDER FLOW: Massive Wall Detected</b>\n\n"
            f"📌 <b>{symbol}</b>  ₹{current_price:,.2f}\n"
            f"⏰ {datetime.now().strftime('%I:%M %p')}\n\n"
            f"📍 <b>Wall Type:</b> {side_label}\n"
            f"💰 <b>Wall Price:</b> ₹{wall_price:,.2f}\n"
            f"📦 <b>Wall Size:</b> {wall_qty:,} qty  ({wall_ratio:.1f}× avg level)\n\n"
            f"⚡ {context}"
        )
        return self.send_debug(msg)

    def send_order_flow_summary(self, top_bullish: List[dict],
                                top_bearish: List[dict]) -> bool:
        """Periodic 5-minute summary of top bullish and bearish stocks by BAI."""
        now_str = datetime.now().strftime('%I:%M %p')

        bullish_lines = []
        for i, m in enumerate(top_bullish, 1):
            flow_pct = m.get('cum_delta_pct', 0) * 100
            bullish_lines.append(
                f"  {i}. <b>{m['symbol']}</b>  flow +{flow_pct:.0f}%  ₹{m['last_price']:,.0f}"
            )

        bearish_lines = []
        for i, m in enumerate(top_bearish, 1):
            flow_pct = m.get('cum_delta_pct', 0) * 100
            bearish_lines.append(
                f"  {i}. <b>{m['symbol']}</b>  flow {flow_pct:.0f}%  ₹{m['last_price']:,.0f}"
            )

        bullish_block = "\n".join(bullish_lines) if bullish_lines else "  —"
        bearish_block = "\n".join(bearish_lines) if bearish_lines else "  —"

        msg = (
            f"📊 <b>ORDER FLOW SUMMARY</b>  —  {now_str}\n\n"
            f"🟢 <b>TOP BULLISH</b>\n{bullish_block}\n\n"
            f"🔴 <b>TOP BEARISH</b>\n{bearish_block}\n\n"
            f"<i>208 F&O stocks  |  WebSocket active</i>"
        )
        return self.send_debug(msg)
