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


def find_double_bottom_setups(
    candles: List[Dict],
    min_rally_pct: float,
    pivot_bars: int,
    min_days_ago: int = 5,
    max_days_ago: int = 40,
) -> List[Dict]:
    """
    Find the first bottom of a potential double bottom.

    A double bottom forms at the *major low* — so we anchor only on the single lowest
    low within the recency window [min_days_ago, max_days_ago]; higher intermediate lows
    are ignored. That low must have been followed by a rally of at least min_rally_pct
    (the middle peak of the W). The live retest / proximity check happens later against
    the live price, so this returns the stable historical context only.

    Args:
        candles: Daily OHLCV dicts in chronological (ascending) order
        min_rally_pct: Minimum rally above the low to qualify as a real W (e.g. 6.0)
        pivot_bars: kept for signature compatibility; the global minimum is used
        min_days_ago / max_days_ago: recency window for the first bottom

    Returns:
        List with the single lowest-low setup {'level','date','peak_between','rally_pct'},
        or [] if none qualifies.
    """
    n = len(candles)
    if n < min_days_ago + 2:
        return []

    # The major bottom = lowest low within the recency window.
    lo_idx = None
    for i in range(0, n - 1):
        bars_ago = (n - 1) - i
        if not (min_days_ago <= bars_ago <= max_days_ago):
            continue
        if lo_idx is None or candles[i]['low'] < candles[lo_idx]['low']:
            lo_idx = i
    if lo_idx is None:
        return []

    low = candles[lo_idx]['low']
    # A real intervening rally (middle peak of the W) after the major low.
    peak_between = max(c['high'] for c in candles[lo_idx + 1:])
    rally_pct = (peak_between - low) / low * 100
    if rally_pct < min_rally_pct:
        return []

    return [{
        'level': low,
        'date': str(candles[lo_idx].get('date', '')),
        'peak_between': peak_between,
        'rally_pct': rally_pct,
    }]


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

    def _compute_levels(self) -> Dict[str, List[Dict]]:
        """Compute double-bottom support levels for every symbol (once per trading day)."""
        today = get_current_ist_time().date()
        if self._levels_cache is not None and self._levels_date == today:
            return self._levels_cache

        lookback = config.DOUBLE_BOTTOM_LOOKBACK_DAYS
        min_rally = config.DOUBLE_BOTTOM_MIN_RALLY_PCT
        to_date = datetime.now()
        from_date = to_date - timedelta(days=int(lookback * 1.6) + 10)  # calendar padding

        levels: Dict[str, List[Dict]] = {}
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
            )
            if found:
                levels[symbol] = found

        logger.info(f"Computed double-bottom levels for {len(levels)} symbols")
        self._levels_cache = levels
        self._levels_date = today
        return levels

    def _check_symbol(self, symbol: str, price: float, setups: List[Dict]) -> bool:
        """Alert at most once per symbol: pick the single best retested setup."""
        proximity = config.DOUBLE_BOTTOM_PROXIMITY_PCT
        max_below = config.DOUBLE_BOTTOM_MAX_BELOW_PCT

        # Keep only setups the live price is currently retesting: within the proximity
        # band and not broken decisively below the first bottom (that would be a breakdown).
        matches = [
            s for s in setups
            if abs(price - s['level']) / s['level'] * 100 <= proximity
            and price >= s['level'] * (1 - max_below / 100)
        ]
        if not matches:
            return False

        # Single best = clearest W (largest rally). setups are pre-sorted by rally_pct.
        best = matches[0]
        level = best['level']
        distance_pct = (price - level) / level * 100

        # One alert per symbol per cooldown (not per level) — removes duplicate noise.
        if not self.alert_history.should_send_alert(
            symbol, "POTENTIAL_DB", cooldown_minutes=config.DOUBLE_BOTTOM_COOLDOWN_MINUTES
        ):
            logger.info(f"⏸️  {symbol}: already alerted (cooldown) - skipping")
            return False

        logger.info(f"🔔 {symbol} at probable double bottom: price {price:.2f} near prior "
                    f"low {level:.2f} ({distance_pct:+.2f}%, rally {best['rally_pct']:.1f}%)")

        if self.dry_run:
            logger.info(f"[DRY RUN] Would send POTENTIAL_DOUBLE_BOTTOM alert for {symbol} "
                        f"(price {price:.2f}, support {level:.2f})")
        else:
            self.telegram.send_potential_double_bottom_alert(
                symbol=symbol,
                current_price=price,
                support_level=level,
                first_low_date=best.get('date', ''),
                peak_between=best.get('peak_between', 0.0)
            )
        return True

    def monitor(self) -> Dict:
        """Run one monitoring cycle."""
        cycle_start = time.time()
        logger.info("=" * 80)
        logger.info(f"DOUBLE BOTTOM MONITOR - cycle at {get_current_ist_time().strftime('%H:%M:%S')}")
        logger.info("=" * 80)

        stats = {'symbols_checked': 0, 'alerts_sent': 0}

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

            for symbol, candidates in levels.items():
                quote = prices.get(symbol)
                if not quote or not quote.get('price'):
                    continue
                stats['symbols_checked'] += 1
                if self._check_symbol(symbol, float(quote['price']), candidates):
                    stats['alerts_sent'] += 1

            logger.info(f"Cycle complete: {stats['symbols_checked']} checked, "
                        f"{stats['alerts_sent']} alerts sent")
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
