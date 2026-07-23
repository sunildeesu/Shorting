#!/usr/bin/env python3
"""
Potential Double Bottom Monitor - Alert when price is AT the probable second bottom

Fires an intraday alert the moment live price returns to within a tight band of a prior
significant daily low that previously held and rallied — i.e. price is at the probable
second bottom, BEFORE the bounce.

This is deliberately a separate, EARLY, UNCONFIRMED signal. The confirmed DOUBLE_BOTTOM
pattern in eod_pattern_detector.py only fires after price has already recovered above the
second low (current_price >= second_low), which is "too late" — this monitor complements it
by alerting at support.

Structure mirrors cpr_first_touch_monitor.py (a "price touches a precomputed level"
monitor). launchd invokes it every 5 minutes during market hours.

Author: Claude Code
Date: 2026-07-10
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from kiteconnect import KiteConnect

import config
import double_bottom_positions as positions
from api_coordinator import get_api_coordinator
from historical_data_cache import get_historical_cache
from alert_history_manager import AlertHistoryManager
from telegram_notifier import TelegramNotifier
from market_utils import is_market_open, get_market_status, get_current_ist_time
from central_db_reader import fetch_stock_prices, report_cycle_complete
from service_health import get_health_tracker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/double_bottom_support_monitor.log'),
        logging.StreamHandler() if sys.stdout.isatty() else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

SERVICE_NAME = "double_bottom_support_monitor"
INSTRUMENT_TOKENS_FILE = "data/instrument_tokens.json"


def sma(candles: List[Dict], period: int) -> Optional[float]:
    """Simple moving average of closes, or None if there is not enough history."""
    if len(candles) < period:
        return None
    return sum(c['close'] for c in candles[-period:]) / period


def atr_percent(candles: List[Dict], period: int = 14) -> Optional[float]:
    """Wilder ATR as a % of the last close — the unit the stop distance is set in."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]['high'], candles[i]['low'], candles[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    last_close = candles[-1]['close']
    return atr / last_close * 100 if last_close else None


def stop_distance_pct(atr_pct: Optional[float]) -> float:
    """Stop distance from entry: ATR multiple, clamped. Evaluated on the CLOSE."""
    if atr_pct is None:
        return config.DOUBLE_BOTTOM_STOP_MIN_PCT
    return min(max(config.DOUBLE_BOTTOM_STOP_ATR_MULT * atr_pct,
                   config.DOUBLE_BOTTOM_STOP_MIN_PCT),
               config.DOUBLE_BOTTOM_STOP_MAX_PCT)


def _count_touches(candles: List[Dict], level: float, tolerance_pct: float,
                   pivot_bars: int) -> int:
    """
    Count how many separate times price visited a level (the anchor visit included).

    Bars from the same visit collapse into one touch: a later bar only opens a new touch
    if it is at least pivot_bars bars away from the previous touching bar AND price closed
    clear of the band (2% above it) in between — otherwise a multi-day base sitting on the
    level would score once per bar.
    """
    band_lo = level * (1 - tolerance_pct / 100)
    band_hi = level * (1 + tolerance_pct / 100)
    clear_of_band = level * 1.02
    touches = 0
    last_touch_idx = None
    left_band = True
    for i, c in enumerate(candles):
        if band_lo <= c['low'] <= band_hi:
            if left_band and (last_touch_idx is None or i - last_touch_idx >= pivot_bars):
                touches += 1
                left_band = False
            last_touch_idx = i
        elif c['low'] >= clear_of_band:
            left_band = True
    return touches


def _support_strength(candles: List[Dict], i: int, level: float, rally_pct: float,
                      min_rally_pct: float, touches: int) -> float:
    """
    Score a support level 0-10: how often price respected it, how hard it bounced.

    Touches (0-5): a level tested once is just a low; tested repeatedly it is support.
    Backtest (6mo, 120 F&O stocks) shows win rate climbing with touch count — 2 touches
    35%, 3 touches 40%, 4+ touches 46-50% — so the tiers are weighted to make a 2-touch
    level pass only when its bounce was exceptional.
    Bounce (0-5): rally size relative to the minimum, plus a prompt recovery and a
    rejection candle at the low itself (both signs buyers stepped in AT the level).
    """
    score = 5.0 if touches >= 4 else (4.0 if touches == 3 else (2.0 if touches == 2 else 0.0))

    ratio = rally_pct / min_rally_pct if min_rally_pct > 0 else 0
    if ratio >= 2.0:
        score += 3.0
    elif ratio >= 1.5:
        score += 2.5
    elif ratio >= 1.2:
        score += 2.0
    else:
        score += 1.5

    # Prompt recovery: price pulled away from the level within 3 bars.
    after = candles[i + 1:i + 4]
    if after and max(c['close'] for c in after) >= level * 1.02:
        score += 1.0

    # Rejection candle: the low bar closed in the upper half of its own range.
    c = candles[i]
    rng = c['high'] - c['low']
    if rng > 0 and (c['close'] - c['low']) / rng >= 0.5:
        score += 1.0

    return round(score, 1)


def find_double_bottom_setups(
    candles: List[Dict],
    min_rally_pct: float,
    pivot_bars: int,
    min_days_ago: int = 5,
    max_days_ago: int = 40,
    min_strength: float = 0.0,
    touch_tolerance_pct: float = 1.0,
) -> List[Dict]:
    """
    Find the candidate first bottoms of a potential double bottom.

    A low is only a valid second-bottom target while it is still *unbroken* — i.e. no
    later candle traded below it. A low that price has since undercut is dead: the more
    recent, lower low took over as the level being retested. So the candidates are the
    swing lows that are the minimum of everything after them; walking back in time they
    get progressively lower, and the list is returned most-recent-first. The caller picks
    the first one live price is actually at, which means a breakdown through the recent
    low automatically hands the signal to the next lower low behind it.

    Each low must also have been followed by a rally of at least min_rally_pct (the
    middle peak of the W), and must score at least min_strength as a support level —
    a low price only visited once and drifted away from is not support worth alerting
    on. The live retest / proximity check happens later against the live price, so this
    returns the stable historical context only.

    Args:
        candles: Daily OHLCV dicts in chronological (ascending) order
        min_rally_pct: Minimum rally above the low to qualify as a real W (e.g. 6.0)
        pivot_bars: Bars either side that must not be lower for a swing low
        min_days_ago / max_days_ago: recency window for the first bottom
        min_strength: Minimum support-strength score (0-10, see _support_strength)
        touch_tolerance_pct: Band around the level that counts as a touch

    Returns:
        List of {'level','date','peak_between','rally_pct','strength','touches'},
        most recent first (and therefore descending in level), or [] if none qualifies.
    """
    n = len(candles)
    if n < min_days_ago + 2:
        return []

    setups = []
    min_low_after = None   # lowest low strictly after i
    peak_after = None      # highest high strictly after i
    for i in range(n - 2, -1, -1):
        nxt = candles[i + 1]
        min_low_after = nxt['low'] if min_low_after is None else min(min_low_after, nxt['low'])
        peak_after = nxt['high'] if peak_after is None else max(peak_after, nxt['high'])

        bars_ago = (n - 1) - i
        if bars_ago > max_days_ago:
            break
        if bars_ago < min_days_ago:
            continue

        low = candles[i]['low']
        # Already undercut by later price action - the lower low replaced it.
        if low > min_low_after:
            continue
        # Swing low: no lower low in the surrounding pivot_bars window.
        lo_j, hi_j = max(0, i - pivot_bars), min(n, i + pivot_bars + 1)
        if any(candles[j]['low'] < low for j in range(lo_j, hi_j)):
            continue
        # A real intervening rally (middle peak of the W) after the low.
        rally_pct = (peak_after - low) / low * 100
        if rally_pct < min_rally_pct:
            continue
        # Only levels price has actually respected are worth alerting on.
        touches = _count_touches(candles, low, touch_tolerance_pct, pivot_bars)
        strength = _support_strength(candles, i, low, rally_pct, min_rally_pct, touches)
        if strength < min_strength:
            continue

        setups.append({
            'level': low,
            'date': str(candles[i].get('date', '')),
            'peak_between': peak_after,
            'rally_pct': rally_pct,
            'strength': strength,
            'touches': touches,
        })

    return setups


class DoubleBottomSupportMonitor:
    """Intraday monitor: alert when price is at a probable double-bottom support level."""

    def __init__(self):
        logger.info("=" * 80)
        logger.info("POTENTIAL DOUBLE BOTTOM MONITOR - Initializing")
        logger.info("=" * 80)

        if not getattr(config, 'ENABLE_DOUBLE_BOTTOM_ALERTS', False):
            logger.info("Double bottom alerts disabled in config (ENABLE_DOUBLE_BOTTOM_ALERTS=false)")
            sys.exit(0)

        if not is_market_open():
            status = get_market_status()
            if not status['is_trading_day']:
                logger.info("Not a trading day (weekend/holiday) - skipping")
            else:
                logger.info("Outside market hours (9:15 AM - 3:30 PM) - skipping")
            sys.exit(0)

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        self.coordinator = get_api_coordinator(kite=self.kite)
        self.historical_cache = get_historical_cache()
        self.alert_history = AlertHistoryManager()
        self.telegram = TelegramNotifier()

        self.stocks = self._load_stock_list()
        self.instrument_tokens = self._load_instrument_tokens()

        # Support levels computed once per trading day, cached in memory.
        self._levels_cache: Optional[Dict[str, List[Dict]]] = None
        self._levels_date = None

        self.dry_run = getattr(config, 'DOUBLE_BOTTOM_DRY_RUN_MODE', False)
        if self.dry_run:
            logger.warning("🔔 DRY RUN MODE ENABLED - Alerts will NOT be sent")

        logger.info(f"Initialized with {len(self.stocks)} stocks, "
                    f"{len(self.instrument_tokens)} instrument tokens")

    def _load_stock_list(self) -> List[str]:
        """Load F&O stock list (raw NSE symbols)."""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                return json.load(f)['stocks']
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

    def _load_instrument_tokens(self) -> Dict[str, int]:
        """Load symbol -> instrument token map maintained by stock_monitor."""
        try:
            if os.path.exists(INSTRUMENT_TOKENS_FILE):
                with open(INSTRUMENT_TOKENS_FILE, 'r') as f:
                    return json.load(f)
            logger.warning(f"Instrument tokens file not found: {INSTRUMENT_TOKENS_FILE}")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load instrument tokens: {e}")
        return {}

    def _compute_levels(self) -> Dict[str, Dict]:
        """Compute support levels + trend/volatility context per symbol (once per day)."""
        today = get_current_ist_time().date()
        if self._levels_cache is not None and self._levels_date == today:
            return self._levels_cache

        lookback = config.DOUBLE_BOTTOM_LOOKBACK_DAYS
        min_rally = config.DOUBLE_BOTTOM_MIN_RALLY_PCT
        to_date = datetime.now()
        # Enough calendar days to cover whichever needs more bars: the lookback window or
        # the trend SMA. ~1.6 calendar days per trading day, plus padding for holidays.
        bars_needed = max(lookback, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD + 5)
        from_date = to_date - timedelta(days=int(bars_needed * 1.6) + 15)

        levels: Dict[str, Dict] = {}
        for symbol in self.stocks:
            token = self.instrument_tokens.get(symbol)
            if not token:
                continue
            try:
                candles = self.historical_cache.get_historical_data(
                    kite=self.kite,
                    instrument_token=token,
                    from_date=from_date,
                    to_date=to_date,
                    interval='day'
                )
            except Exception as e:
                logger.debug(f"{symbol}: failed to fetch daily candles: {e}")
                continue

            if not candles or len(candles) < 10:
                continue

            found = find_double_bottom_setups(
                candles[-lookback:],
                min_rally_pct=min_rally,
                pivot_bars=config.DOUBLE_BOTTOM_PIVOT_BARS,
                min_days_ago=config.DOUBLE_BOTTOM_MIN_DAYS_AGO,
                max_days_ago=config.DOUBLE_BOTTOM_MAX_DAYS_AGO,
                min_strength=config.DOUBLE_BOTTOM_MIN_STRENGTH,
                touch_tolerance_pct=config.DOUBLE_BOTTOM_TOUCH_TOLERANCE_PCT,
            )
            found = [s for s in found if s['touches'] >= config.DOUBLE_BOTTOM_MIN_TOUCHES]
            if found:
                levels[symbol] = {
                    'setups': found,
                    # Trend gate and stop distance both come from the same daily series.
                    'sma': sma(candles, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD),
                    'atr_pct': atr_percent(candles, config.DOUBLE_BOTTOM_ATR_PERIOD),
                }

        logger.info(f"Computed double-bottom levels for {len(levels)} symbols")
        self._levels_cache = levels
        self._levels_date = today
        return levels

    def _evaluate(self, symbol: str, price: float, ctx: Dict) -> Optional[Dict]:
        """Return the retest candidate for this symbol right now, or None."""
        proximity = config.DOUBLE_BOTTOM_PROXIMITY_PCT
        max_below = config.DOUBLE_BOTTOM_MAX_BELOW_PCT

        # Only buy support inside an uptrend - the largest single edge in testing.
        if config.DOUBLE_BOTTOM_REQUIRE_UPTREND:
            trend_sma = ctx.get('sma')
            if trend_sma is None or price <= trend_sma:
                return None

        # Keep only setups the live price is currently retesting: within the proximity
        # band and not broken decisively below the first bottom (that would be a breakdown).
        matches = [
            s for s in ctx['setups']
            if abs(price - s['level']) / s['level'] * 100 <= proximity
            and price >= s['level'] * (1 - max_below / 100)
        ]
        if not matches:
            return None

        # setups are ordered most-recent-first, so the first match is the nearest
        # unbroken low price is retesting. Once that breaks (max_below), it drops out
        # of matches and the next older, lower low becomes the active level.
        best = matches[0]
        return {'symbol': symbol, 'price': price, 'setup': best, 'atr_pct': ctx.get('atr_pct')}

    def _alert_best(self, candidates: List[Dict]) -> bool:
        """Alert the single best candidate of the day, if a slot is free."""
        today = get_current_ist_time().date().isoformat()

        if positions.opened_on(today):
            logger.info(f"⏸️  Already entered a position today - {len(candidates)} candidate(s) skipped")
            return False

        free = positions.slots_free()
        if free <= 0:
            logger.info(f"⏸️  All {config.DOUBLE_BOTTOM_MAX_SLOTS} slots occupied "
                        f"({', '.join(p['symbol'] for p in positions.open_positions())}) - "
                        f"{len(candidates)} candidate(s) skipped")
            return False

        # Best = strongest support (score), rally as tie-break.
        candidates = [c for c in candidates if not positions.has_open(c['symbol'])]
        if not candidates:
            return False
        pick = max(candidates, key=lambda c: (c['setup']['strength'], c['setup']['rally_pct']))

        symbol, price, best = pick['symbol'], pick['price'], pick['setup']
        level = best['level']
        distance_pct = (price - level) / level * 100

        if not self.alert_history.should_send_alert(
            symbol, "POTENTIAL_DB", cooldown_minutes=config.DOUBLE_BOTTOM_COOLDOWN_MINUTES
        ):
            logger.info(f"⏸️  {symbol}: already alerted (cooldown) - skipping")
            return False

        stop_pct = stop_distance_pct(pick['atr_pct'])
        stop_price = price * (1 - stop_pct / 100)
        target_price = price * (1 + config.DOUBLE_BOTTOM_TARGET_PCT / 100)

        if len(candidates) > 1:
            others = ', '.join(f"{c['symbol']}({c['setup']['strength']:.1f})"
                               for c in candidates if c['symbol'] != symbol)
            logger.info(f"Best of {len(candidates)} candidates: {symbol}. Passed over: {others}")

        logger.info(f"🔔 {symbol} at probable double bottom: price {price:.2f} near prior "
                    f"low {level:.2f} ({distance_pct:+.2f}%, rally {best['rally_pct']:.1f}%, "
                    f"strength {best['strength']:.1f}/10, {best['touches']} touches) | "
                    f"stop {stop_price:.2f} (-{stop_pct:.1f}% on close), "
                    f"target {target_price:.2f} (+{config.DOUBLE_BOTTOM_TARGET_PCT:.1f}%), "
                    f"slots free {free}/{config.DOUBLE_BOTTOM_MAX_SLOTS}")

        if self.dry_run:
            logger.info(f"[DRY RUN] Would send POTENTIAL_DOUBLE_BOTTOM alert for {symbol} "
                        f"(price {price:.2f}, support {level:.2f}) and open a tracked position")
            return True

        self.telegram.send_potential_double_bottom_alert(
            symbol=symbol,
            current_price=price,
            support_level=level,
            first_low_date=best.get('date', ''),
            peak_between=best.get('peak_between', 0.0),
            strength=best.get('strength', 0.0),
            touches=best.get('touches', 0),
            stop_price=stop_price,
            stop_pct=stop_pct,
            target_price=target_price,
            target_pct=config.DOUBLE_BOTTOM_TARGET_PCT,
            time_stop_days=config.DOUBLE_BOTTOM_TIME_STOP_DAYS,
            slots_free=free,
        )

        positions.add({
            'symbol': symbol,
            'entry_date': today,
            'entry_price': price,
            'support_level': level,
            'stop_price': stop_price,
            'stop_pct': stop_pct,
            'target_price': target_price,
            'atr_pct': pick['atr_pct'],
            'strength': best.get('strength', 0.0),
            'touches': best.get('touches', 0),
            'opened_at': get_current_ist_time().isoformat(),
        })
        return True

    def monitor(self) -> Dict:
        """Run one monitoring cycle."""
        cycle_start = time.time()
        logger.info("=" * 80)
        logger.info(f"DOUBLE BOTTOM MONITOR - cycle at {get_current_ist_time().strftime('%H:%M:%S')}")
        logger.info("=" * 80)

        stats = {'symbols_checked': 0, 'candidates': 0, 'alerts_sent': 0}

        try:
            levels = self._compute_levels()
            if not levels:
                logger.info("No candidate double-bottom levels today - nothing to monitor")
                return stats

            prices = fetch_stock_prices(
                symbols=list(levels.keys()),
                service_name=SERVICE_NAME,
                kite_client=self.kite,
                coordinator=self.coordinator
            )

            # Collect every symbol at support first, then alert only the best one — the
            # backtested edge assumes one new position per day, not one per symbol.
            candidates = []
            for symbol, ctx in levels.items():
                quote = prices.get(symbol)
                if not quote or not quote.get('price'):
                    continue
                stats['symbols_checked'] += 1
                cand = self._evaluate(symbol, float(quote['price']), ctx)
                if cand:
                    candidates.append(cand)

            stats['candidates'] = len(candidates)
            if candidates and self._alert_best(candidates):
                stats['alerts_sent'] = 1

            logger.info(f"Cycle complete: {stats['symbols_checked']} checked, "
                        f"{stats['candidates']} at support, {stats['alerts_sent']} alerts sent")
            report_cycle_complete(
                service_name=SERVICE_NAME,
                cycle_start_time=cycle_start,
                stats=stats
            )
            return stats

        except Exception as e:
            logger.error(f"Error in monitor cycle: {e}", exc_info=True)
            report_cycle_complete(
                service_name=SERVICE_NAME,
                cycle_start_time=cycle_start,
                stats={"error": True}
            )
            return stats


def main():
    cycle_start = time.time()
    health = get_health_tracker()
    try:
        monitor = DoubleBottomSupportMonitor()
        result = monitor.monitor()
        logger.info(f"✅ Double bottom monitor completed - {result['alerts_sent']} alert(s) sent")
        health.heartbeat(SERVICE_NAME, int((time.time() - cycle_start) * 1000))
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        health.heartbeat(SERVICE_NAME, int((time.time() - cycle_start) * 1000))
        health.report_error(SERVICE_NAME, "fatal_error", str(e))
        sys.exit(1)


if __name__ == "__main__":
    import proctitle; proctitle.set_title("nse-doublebottom-monitor")
    main()
