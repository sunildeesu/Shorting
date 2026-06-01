"""Flag pattern alert notifier for bull flag Stage 3 setups."""
import logging
from datetime import datetime
from typing import Dict

from .base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class FlagAlertNotifier(BaseNotifier):
    """Sends bull flag Stage 3 setup alerts to Telegram."""

    def send_alert(self, result: Dict) -> bool:
        """
        Send a bull flag Stage 3 alert.

        Args:
            result: Detection result dict from FlagPatternDetector.detect()

        Returns:
            True if sent successfully.
        """
        message = self._format_message(result)
        return self._send_message(message)

    def _format_message(self, r: Dict) -> str:
        symbol = r['symbol']
        score = r['score']
        pole_gain = r['pole_gain_pct']
        pole_days = r['pole_days']
        pole_low = r['pole_low']
        pole_high = r['pole_high']
        pullback = r['pullback_depth_pct']
        flag_days = r['flag_days']
        vol_ratio = r['volume_ratio']
        current = r['current_price']
        breakout = r['breakout_level']
        stop = r['stop_loss']
        ema20 = r.get('ema_20')
        sma50 = r.get('sma_50')
        trend_aligned = r.get('trend_aligned', False)
        adx = r.get('adx')

        stars = self._stars(score)
        vol_tag = f"{vol_ratio:.1f}x contraction" if vol_ratio >= 1.0 else "—"
        trend_tag = "✅" if trend_aligned else "⚠️"
        adx_tag = f" | ADX {adx:.0f}" if adx else ""

        ema_line = ""
        if ema20 and sma50:
            ema_line = f"\n📐 EMA(20): <b>₹{ema20:,.2f}</b> | SMA(50): <b>₹{sma50:,.2f}</b> {trend_tag}{adx_tag}"
        elif ema20:
            ema_line = f"\n📐 EMA(20): <b>₹{ema20:,.2f}</b>{adx_tag}"

        now = datetime.now().strftime('%Y-%m-%d %H:%M IST')

        return (
            f"🚩 <b>Bull Flag Setup — {symbol}</b>\n"
            f"📅 Stage 3 Consolidation (Daily)\n"
            f"\n"
            f"📈 <b>Pole:</b> +{pole_gain:.1f}% in {pole_days} days\n"
            f"   └─ ₹{pole_low:,.2f} → ₹{pole_high:,.2f}\n"
            f"\n"
            f"📉 <b>Flag:</b> {flag_days} days, -{pullback:.1f}% pullback\n"
            f"   └─ Volume: {vol_tag}\n"
            f"   └─ Breakout watch: <b>₹{breakout:,.2f}</b>\n"
            f"\n"
            f"💰 Current: <b>₹{current:,.2f}</b>"
            f"{ema_line}\n"
            f"\n"
            f"🎯 Entry: breakout above <b>₹{breakout:,.2f}</b> with volume\n"
            f"⛔ Stop: <b>₹{stop:,.2f}</b> (flag low −3%)\n"
            f"\n"
            f"⭐ Score: <b>{score}/10</b> {stars}\n"
            f"⏰ {now}"
        )

    @staticmethod
    def _stars(score: float) -> str:
        full = int(score / 2)
        return "★" * full + "☆" * (5 - full)
