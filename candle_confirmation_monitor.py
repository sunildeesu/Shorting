#!/usr/bin/env python3
"""
Candle Reversal + Confirmation Monitor (5-minute)

Two-candle reversal signal, both directions:
  • Hammer (bullish): long lower wick, small body at top, after a decline. Confirmed when the
    NEXT candle is bullish and closes ABOVE the hammer's HIGH with above-average volume.
    Long entry = confirmation close; stop = hammer's low.
  • Shooting Star (bearish, mirror): long upper wick, small body at bottom, after a rise.
    Confirmed when the NEXT candle is bearish and closes BELOW the star's LOW with above-average
    volume. Short entry = confirmation close; stop = star's high.

A single candle is never traded — the confirmation candle must close beyond the wick extreme.
Reuses HammerDetector / ShootingStarDetector for shape validation. Posts to the DEBUG channel.
launchd invokes it every 5 minutes during market hours.

Author: Claude Code
Date: 2026-07-22
"""

import json
import logging
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import config
from alert_history_manager import AlertHistoryManager
from telegram_notifier import TelegramNotifier
from market_utils import is_market_open, get_market_status, get_current_ist_time
from central_db_reader import report_cycle_complete, fetch_intraday_candles
from service_health import get_health_tracker
from pattern_detectors.reversal_patterns import HammerDetector, ShootingStarDetector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/candle_confirmation_monitor.log'),
        logging.StreamHandler() if sys.stdout.isatty() else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

SERVICE_NAME = "candle_confirmation_monitor"
CANDLE_MINUTES = 5


def _candle_day(candle: Dict) -> str:
    """Trading-day key ('YYYY-MM-DD') from a candle's date (datetime or ISO string)."""
    d = candle.get('date')
    if hasattr(d, 'strftime'):
        return d.strftime('%Y-%m-%d')
    return str(d)[:10]


def drop_forming_candle(candles: List[Dict]) -> List[Dict]:
    """Return only CLOSED candles: drop the last one if its 5-min bucket hasn't ended yet.

    Candle 'date' may be a datetime (tests) or an ISO string (central DB). We can only judge
    tz-aware timestamps; naive/unparseable dates are assumed already-closed (no drop).
    """
    if not candles:
        return candles
    raw = candles[-1].get('date')
    dt = None
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            dt = None
    elif hasattr(raw, 'tzinfo'):
        dt = raw
    if dt is not None and dt.tzinfo is not None:
        try:
            if get_current_ist_time() < dt + timedelta(minutes=CANDLE_MINUTES):
                return candles[:-1]
        except Exception:
            return candles[:-1]
    return candles


def detect_reversal_confirmation(
    candles: List[Dict],
    hammer: HammerDetector,
    star: ShootingStarDetector,
) -> Optional[Dict]:
    """
    Detect a hammer/shooting-star + confirmation on the last two CLOSED candles.

    Volume is judged per-stock and relative: the confirmation candle's volume must exceed the
    stock's own recent average volume on this timeframe (the candles *before* the confirmation)
    by config.CANDLE_CONFIRM_VOLUME_MULT (e.g. 1.2 = +20%). No absolute share-count threshold —
    each stock is compared against its own baseline.

    Returns a signal dict (direction, levels, candles) or None.
    """
    closed = drop_forming_candle(candles)
    # Need shape history (detector wants >=10) + the signal candle + the confirmation candle.
    if len(closed) < 12:
        return None

    signal_candle = closed[-2]
    confirm = closed[-1]

    # The confirmation must be intraday-contiguous with the signal candle. Skip cross-day pairs
    # (e.g. yesterday's last candle "confirmed" by today's 09:15 open) — an overnight gap up/down
    # isn't a genuine intraday reversal confirmation.
    if _candle_day(signal_candle) != _candle_day(confirm):
        return None

    vol_mult = config.CANDLE_CONFIRM_VOLUME_MULT
    # Baseline = average volume of up to 20 candles BEFORE the confirmation candle (its own
    # timeframe normal), so the ratio is a true "% above average" for this stock.
    base_vols = [c['volume'] for c in closed[-(config.CANDLE_VOLUME_BASELINE + 1):-1]]
    base_avg = sum(base_vols) / len(base_vols) if base_vols else 0.0
    volume_ok = base_avg > 0 and confirm['volume'] >= vol_mult * base_avg
    volume_ratio = (confirm['volume'] / base_avg) if base_avg > 0 else 0.0

    # --- Bullish: hammer then a bullish candle closing above the hammer's high ---
    if config.ENABLE_HAMMER_SIGNAL:
        shape = hammer.detect(closed[:-1], 'NEUTRAL', base_avg)  # closed[:-1][-1] == signal_candle
        if shape and confirm['close'] > confirm['open'] \
                and confirm['close'] > signal_candle['high'] and volume_ok:
            entry, stop = confirm['close'], signal_candle['low']
            risk = entry - stop
            if risk > 0:
                return _build('BULLISH', 'Hammer', signal_candle, confirm, entry, stop,
                              entry + 2 * risk, volume_ratio, shape['confidence_score'])

    # --- Bearish: shooting star then a bearish candle closing below the star's low ---
    if config.ENABLE_SHOOTING_STAR_SIGNAL:
        shape = star.detect(closed[:-1], 'NEUTRAL', base_avg)
        if shape and confirm['close'] < confirm['open'] \
                and confirm['close'] < signal_candle['low'] and volume_ok:
            entry, stop = confirm['close'], signal_candle['high']
            risk = stop - entry
            if risk > 0:
                return _build('BEARISH', 'Shooting Star', signal_candle, confirm, entry, stop,
                              entry - 2 * risk, volume_ratio, shape['confidence_score'])

    return None


def _build(direction, pattern, sig, confirm, entry, stop, target, vol_ratio, confidence) -> Dict:
    return {
        'direction': direction,
        'pattern': pattern,
        'signal_candle': sig,
        'confirm_candle': confirm,
        'entry': entry,
        'stop': stop,
        'target': target,
        'rr': abs(target - entry) / abs(entry - stop) if entry != stop else 0.0,
        'volume_ratio': vol_ratio,
        'confidence': confidence,
    }


class CandleConfirmationMonitor:
    """Intraday 5-min monitor for hammer/shooting-star + confirmation signals."""

    def __init__(self):
        logger.info("=" * 80)
        logger.info("CANDLE REVERSAL + CONFIRMATION MONITOR - Initializing")
        logger.info("=" * 80)

        if not getattr(config, 'ENABLE_CANDLE_REVERSAL_ALERTS', False):
            logger.info("Candle reversal alerts disabled (ENABLE_CANDLE_REVERSAL_ALERTS=false)")
            sys.exit(0)

        if not is_market_open():
            status = get_market_status()
            if not status['is_trading_day']:
                logger.info("Not a trading day (weekend/holiday) - skipping")
            else:
                logger.info("Outside market hours - skipping")
            sys.exit(0)

        # Candles come from the central DB (no Kite client needed in this consumer).
        self.alert_history = AlertHistoryManager()
        self.telegram = TelegramNotifier()
        self.stocks = self._load_stock_list()

        self.hammer = HammerDetector(config.CANDLE_MIN_CONFIDENCE, 14, 2.0, 1.0)
        self.star = ShootingStarDetector(config.CANDLE_MIN_CONFIDENCE, 14, 2.0, 1.0)

        self.dry_run = getattr(config, 'CANDLE_DRY_RUN_MODE', False)
        if self.dry_run:
            logger.warning("🔔 DRY RUN MODE ENABLED - Alerts will NOT be sent")

        logger.info(f"Initialized with {len(self.stocks)} stocks (reading candles from central DB)")

    def _load_stock_list(self) -> List[str]:
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                return json.load(f)['stocks']
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

    def _send(self, symbol: str, sig: Dict):
        c, s = sig['confirm_candle'], sig['signal_candle']
        if sig['direction'] == 'BULLISH':
            badge = "🔨🟢 HAMMER + CONFIRMATION (BULLISH)"
            side, gain = "LONG", (sig['target'] - sig['entry']) / sig['entry'] * 100
        else:
            badge = "⭐🔴 SHOOTING STAR + CONFIRMATION (BEARISH)"
            side, gain = "SHORT", (sig['entry'] - sig['target']) / sig['entry'] * 100
        risk_pct = abs(sig['entry'] - sig['stop']) / sig['entry'] * 100

        msg = (
            f"{badge}\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"📊 <b>{symbol}</b>  ({side})\n"
            f"🎯 Pattern: {sig['pattern']}  |  Confidence: {sig['confidence']:.1f}/10\n"
            f"⏰ {get_current_ist_time().strftime('%d %b %I:%M %p')}\n\n"
            f"🕯️ <b>Signal candle</b>: O {s['open']:.2f} H {s['high']:.2f} "
            f"L {s['low']:.2f} C {s['close']:.2f}\n"
            f"✅ <b>Confirm candle</b>: O {c['open']:.2f} H {c['high']:.2f} "
            f"L {c['low']:.2f} C {c['close']:.2f}\n"
            f"📈 Confirm volume: {sig['volume_ratio']:.1f}× avg\n\n"
            f"💰 Entry: ₹{sig['entry']:.2f}\n"
            f"🎯 Target: ₹{sig['target']:.2f} ({gain:+.1f}%)\n"
            f"🛡️ Stop: ₹{sig['stop']:.2f} (-{risk_pct:.1f}%)  |  R:R 1:{sig['rr']:.1f}\n\n"
            "⚠️ <i>Not financial advice.</i>"
        )
        if self.dry_run:
            logger.info(f"[DRY RUN] Would send {sig['direction']} {sig['pattern']} for {symbol}")
            return
        self.telegram.send_candle_reversal_alert(msg)

    def monitor(self) -> Dict:
        cycle_start = time.time()
        logger.info("=" * 80)
        logger.info(f"CANDLE MONITOR - cycle at {get_current_ist_time().strftime('%H:%M:%S')}")
        logger.info("=" * 80)
        stats = {'checked': 0, 'signals': 0, 'alerts_sent': 0}

        try:
            # Single shared read from the central DB — no per-symbol Kite calls.
            candles_by_symbol = fetch_intraday_candles(
                self.stocks, config.INTRADAY_CANDLE_INTERVAL, SERVICE_NAME
            )
            if not candles_by_symbol:
                logger.warning("No fresh intraday candles in central DB - skipping cycle")
                report_cycle_complete(service_name=SERVICE_NAME, cycle_start_time=cycle_start,
                                      stats=stats)
                return stats

            for symbol, candles in candles_by_symbol.items():
                if len(candles) < 12:
                    continue
                # Price sanity only (skip penny stocks). Volume is judged per-stock/relative
                # inside the detector (confirmation vs the stock's own timeframe average) —
                # no generic absolute share-count floor.
                if candles[-1]['close'] < config.PRICE_ACTION_MIN_PRICE:
                    continue
                stats['checked'] += 1

                sig = detect_reversal_confirmation(candles, self.hammer, self.star)
                if not sig:
                    continue
                stats['signals'] += 1

                alert_key = f"REVERSAL_{sig['direction']}"
                if not self.alert_history.should_send_alert(
                    symbol, alert_key, cooldown_minutes=config.CANDLE_COOLDOWN_MINUTES
                ):
                    logger.info(f"⏸️  {symbol} {sig['direction']}: cooldown - skipping")
                    continue

                logger.info(f"🔔 {symbol} {sig['direction']} {sig['pattern']} confirmed "
                            f"(entry {sig['entry']:.2f}, stop {sig['stop']:.2f}, "
                            f"vol {sig['volume_ratio']:.1f}x)")
                self._send(symbol, sig)
                stats['alerts_sent'] += 1

            logger.info(f"Cycle complete: {stats['checked']} checked, {stats['signals']} signals, "
                        f"{stats['alerts_sent']} alerts sent")
            report_cycle_complete(service_name=SERVICE_NAME, cycle_start_time=cycle_start, stats=stats)
            return stats
        except Exception as e:
            logger.error(f"Error in monitor cycle: {e}", exc_info=True)
            report_cycle_complete(service_name=SERVICE_NAME, cycle_start_time=cycle_start,
                                  stats={"error": True})
            return stats


def main():
    cycle_start = time.time()
    health = get_health_tracker()
    try:
        monitor = CandleConfirmationMonitor()
        result = monitor.monitor()
        logger.info(f"✅ Candle monitor completed - {result['alerts_sent']} alert(s) sent")
        health.heartbeat(SERVICE_NAME, int((time.time() - cycle_start) * 1000))
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        health.heartbeat(SERVICE_NAME, int((time.time() - cycle_start) * 1000))
        health.report_error(SERVICE_NAME, "fatal_error", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
