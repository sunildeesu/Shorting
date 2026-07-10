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


def find_double_bottom_levels(
    candles: List[Dict],
    min_rally_pct: float,
    min_days_ago: int = 5,
    cluster_pct: float = 1.0
) -> List[Dict]:
    """
    Find candidate "first bottom" support levels from daily candles.

    A candidate is a prior swing low that (a) occurred at least `min_days_ago` bars ago,
    and (b) was followed by a rally of at least `min_rally_pct` above the low (the middle
    of the W). Nearby levels are merged so a cluster of lows reports once.

    Args:
        candles: Daily OHLCV dicts in chronological (ascending) order
        min_rally_pct: Minimum rally above the low to qualify (e.g. 3.0)
        min_days_ago: Low must be at least this many bars before the latest candle
        cluster_pct: Merge candidate levels within this % of each other

    Returns:
        List of {'level': float, 'date': str, 'peak_between': float}, most recent first
    """
    n = len(candles)
    if n < 10:
        return []

    candidates: List[Dict] = []
    # Local minima: a low lower than both neighbours. Range stops at n-1 so a valid
    # minimum always has a following candle (a rally can only be measured after the low).
    for i in range(1, n - 1):
        low = candles[i]['low']
        if not (low < candles[i - 1]['low'] and low < candles[i + 1]['low']):
            continue
        # Must be old enough that a rally + pullback could have formed since.
        if (n - 1) - i < min_days_ago:
            continue
        # Rally after the low must reach min_rally_pct above it.
        peak_between = max(c['high'] for c in candles[i + 1:])
        if peak_between < low * (1 + min_rally_pct / 100):
            continue
        candidates.append({
            'level': low,
            'date': str(candles[i].get('date', '')),
            'peak_between': peak_between,
            'index': i
        })

    if not candidates:
        return []

    # Merge clusters: keep the most recent low in each price cluster.
    candidates.sort(key=lambda c: c['index'], reverse=True)  # most recent first
    merged: List[Dict] = []
    for cand in candidates:
        if any(abs(cand['level'] - m['level']) / m['level'] * 100 <= cluster_pct
               for m in merged):
            continue
        merged.append(cand)

    for m in merged:
        m.pop('index', None)
    return merged


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

            found = find_double_bottom_levels(candles[-lookback:], min_rally_pct=min_rally)
            if found:
                levels[symbol] = found

        logger.info(f"Computed double-bottom levels for {len(levels)} symbols")
        self._levels_cache = levels
        self._levels_date = today
        return levels

    def _check_symbol(self, symbol: str, price: float, candidates: List[Dict]) -> bool:
        """Alert if price is within the proximity band of any candidate level. One per level/day."""
        proximity = config.DOUBLE_BOTTOM_PROXIMITY_PCT
        sent = False
        for cand in candidates:
            level = cand['level']
            distance_pct = abs(price - level) / level * 100
            if distance_pct > proximity:
                continue

            alert_type = f"POTENTIAL_DB_{round(level)}"
            if not self.alert_history.should_send_alert(
                symbol, alert_type, cooldown_minutes=config.DOUBLE_BOTTOM_COOLDOWN_MINUTES
            ):
                logger.info(f"⏸️  {symbol} @ {level:.2f}: already alerted (cooldown) - skipping")
                continue

            logger.info(f"🔔 {symbol} at probable double bottom: price {price:.2f} "
                        f"near prior low {level:.2f} ({distance_pct:.2f}%)")

            if self.dry_run:
                logger.info(f"[DRY RUN] Would send POTENTIAL_DOUBLE_BOTTOM alert for {symbol} "
                            f"(price {price:.2f}, support {level:.2f})")
            else:
                self.telegram.send_potential_double_bottom_alert(
                    symbol=symbol,
                    current_price=price,
                    support_level=level,
                    first_low_date=cand.get('date', ''),
                    peak_between=cand.get('peak_between', 0.0)
                )
            sent = True
        return sent

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
    main()
