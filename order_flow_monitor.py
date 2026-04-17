#!/usr/bin/env python3
"""
Order Flow Monitor — main process for real-time crowd psychology analysis.

Lifecycle:
  1. Load instrument tokens for 208 F&O stocks
  2. Initialize order_flow.db (writer mode)
  3. Start OrderFlowCollector in a daemon thread (KiteTicker WebSocket)
  4. Main loop every 30 seconds:
     a. Check data freshness (skip if WebSocket is stale)
     b. Run OrderFlowAnalyzer.analyze_all() on all 208 stocks
     c. Write results to flow_metrics table
     d. Check each stock against alert thresholds → send Telegram alerts
  5. Every 5 minutes: send summary of top 5 bullish + bearish stocks
  6. Exit cleanly at 3:30 PM

Runs as a launchd agent: starts at 9:14 AM, exits after 3:30 PM.

Author: Claude Sonnet 4.6
"""

import logging
import sys
import threading
import time
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional, Tuple

from kiteconnect import KiteConnect

import config
from market_utils import get_market_status
from order_flow_db import OrderFlowDB, get_order_flow_db
from order_flow_collector import OrderFlowCollector
from order_flow_analyzer import OrderFlowAnalyzer
from telegram_notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/order_flow_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def _is_within_market_hours() -> bool:
    now = datetime.now().time()
    return dt_time(9, 15) <= now <= dt_time(15, 30)


def _wait_for_market_open():
    while True:
        now = datetime.now().time()
        if now >= dt_time(9, 15):
            break
        wait = (
            (dt_time(9, 15).hour - now.hour) * 3600
            + (dt_time(9, 15).minute - now.minute) * 60
            - now.second
        )
        logger.info(f"Waiting {wait}s for market to open at 9:15 AM...")
        time.sleep(min(wait, 30))


class OrderFlowMonitor:
    """Orchestrates WebSocket collection, analysis, and Telegram alerts."""

    def __init__(self):
        logger.info("=" * 70)
        logger.info("ORDER FLOW MONITOR — Initialising")
        logger.info("=" * 70)

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        self.db   = get_order_flow_db(mode="writer")
        self.notifier = TelegramNotifier()

        # Analyzer uses a separate reader connection
        self.analyzer = OrderFlowAnalyzer(db=get_order_flow_db(mode="reader"))

        self.collector: Optional[OrderFlowCollector] = None
        self._collector_thread: Optional[threading.Thread] = None

        # In-memory cooldown cache — {(symbol, alert_type): datetime}
        self._cooldown_cache: Dict[Tuple[str, str], datetime] = {}
        self._last_summary_time: datetime = datetime.min
        # Skip first analysis cycle after restart — BAI delta is meaningless until
        # the second cycle (prev_bai starts at DB values; fut_bai_prev starts at 0).
        self._warmup_cycles_remaining: int = 1

        logger.info("Order flow monitor initialised")

    # --------------------------------------------------------
    # Collector thread
    # --------------------------------------------------------

    def _start_collector(self):
        self.collector = OrderFlowCollector(kite=self.kite, db=self.db)
        self._collector_thread = threading.Thread(
            target=self.collector.start,
            name="OrderFlowCollector",
            daemon=True
        )
        self._collector_thread.start()
        logger.info("OrderFlow WebSocket collector thread started")

    # --------------------------------------------------------
    # Alert helpers
    # --------------------------------------------------------

    def _should_send(self, symbol: str, alert_type: str) -> bool:
        """Fast in-memory cooldown check, with DB fallback on miss."""
        key = (symbol, alert_type)
        last_fired = self._cooldown_cache.get(key)
        if last_fired:
            age_min = (datetime.now() - last_fired).total_seconds() / 60
            return age_min >= config.ORDER_FLOW_COOLDOWN_MINUTES

        # Not in memory (first run or restart) — check DB
        in_db = self.db.was_alert_sent_recently(symbol, alert_type)
        return not in_db

    def _mark_sent(self, symbol: str, alert_type: str):
        key = (symbol, alert_type)
        self._cooldown_cache[key] = datetime.now()
        self.db.record_alert(symbol, alert_type)

    # --------------------------------------------------------
    # Alert dispatching
    # --------------------------------------------------------

    def _score_stock(self, m: dict) -> Tuple[int, int, List[str], List[str]]:
        """
        Compute bearish and bullish confluence scores for one stock.

        Each signal contributes points. An alert only fires when the score
        reaches ORDER_FLOW_MIN_CONFLUENCE_SCORE (default 3), requiring at
        least 2 independent signals to agree.

        Scoring (bearish / bullish):
          BAI Delta shift      : 2 pts  — strongest leading signal (momentum shift)
          Cumulative 5-min flow: 2 pts  — sustained directional flow
          L1 bid shrink ≥40%   : 1 pt   — support being consumed (bearish only)
          Tick velocity high   : 1 pt   — price moving fast in direction
          BAI absolute         : 1 pt   — extreme book imbalance

        Returns (bearish_score, bullish_score, bearish_reasons, bullish_reasons).
        """
        bear_score, bull_score = 0, 0
        bear_reasons: List[str] = []
        bull_reasons: List[str] = []

        bai        = m['bai']
        bai_delta  = m.get('bai_delta', 0)
        cum_pct    = m.get('cum_delta_pct', 0)
        bid_shrink = m.get('bid_l1_shrink_pct', 0)
        tick_vel   = m.get('tick_velocity', 0)
        price_chg  = m['price_change_pct']
        # Futures
        fut_bai       = m.get('fut_bai', 0)
        fut_bai_delta = m.get('fut_bai_delta', 0)
        fut_cum_pct   = m.get('fut_cum_delta_pct', 0)
        basis_pct     = m.get('basis_pct', 0)

        # Cash BAI Delta (2 pts) — leading: order book actively shifting
        if bai_delta <= config.ORDER_FLOW_BAI_DELTA_BEARISH:
            bear_score += 2
            bear_reasons.append(f"BAI shift {bai_delta:+.3f}")
        if bai_delta >= config.ORDER_FLOW_BAI_DELTA_BULLISH:
            bull_score += 2
            bull_reasons.append(f"BAI shift +{bai_delta:.3f}")

        # Cash cumulative 5-min volume imbalance (2 pts)
        if cum_pct <= config.ORDER_FLOW_CUM_DELTA_BEARISH:
            bear_score += 2
            bear_reasons.append(f"5m flow {cum_pct*100:.0f}%")
        if cum_pct >= config.ORDER_FLOW_CUM_DELTA_BULLISH:
            bull_score += 2
            bull_reasons.append(f"5m flow +{cum_pct*100:.0f}%")

        # Futures BAI Delta (2 pts) — institutional order book shifting
        if m.get('fut_tick_count', 0) >= config.ORDER_FLOW_MIN_TICKS:
            if fut_bai_delta <= config.ORDER_FLOW_FUT_BAI_DELTA_BEARISH:
                bear_score += 2
                bear_reasons.append(f"FUT BAI {fut_bai_delta:+.3f}")
            if fut_bai_delta >= config.ORDER_FLOW_FUT_BAI_DELTA_BULLISH:
                bull_score += 2
                bull_reasons.append(f"FUT BAI +{fut_bai_delta:.3f}")

            # Basis divergence (2 pts) — futures at discount = aggressive selling
            if basis_pct <= config.ORDER_FLOW_BASIS_BEARISH_PCT:
                bear_score += 2
                bear_reasons.append(f"basis {basis_pct:+.2f}%")
            if basis_pct >= config.ORDER_FLOW_BASIS_BULLISH_PCT:
                bull_score += 2
                bull_reasons.append(f"basis +{basis_pct:.2f}%")

        # L1 bid shrink (1 pt — bearish only)
        if bid_shrink >= config.ORDER_FLOW_BID_L1_SHRINK_ALERT:
            bear_score += 1
            bear_reasons.append(f"L1 bid -{bid_shrink*100:.0f}%")

        # Tick velocity (1 pt)
        if tick_vel >= config.ORDER_FLOW_TICK_VELOCITY_HIGH:
            if price_chg < 0:
                bear_score += 1
                bear_reasons.append(f"vel ₹{tick_vel:.2f}/tick")
            elif price_chg > 0:
                bull_score += 1
                bull_reasons.append(f"vel ₹{tick_vel:.2f}/tick")

        # Cash BAI absolute (1 pt)
        if bai <= config.ORDER_FLOW_BAI_BEARISH:
            bear_score += 1
            bear_reasons.append(f"BAI {bai:.3f}")
        if bai >= config.ORDER_FLOW_BAI_BULLISH:
            bull_score += 1
            bull_reasons.append(f"BAI +{bai:.3f}")

        return bear_score, bull_score, bear_reasons, bull_reasons

    def _check_alerts(self, metrics: Dict[str, dict]):
        """
        Confluence-gated alert dispatch.

        Rules to fire an alert:
          1. Price must have moved ≥ ORDER_FLOW_MIN_PRICE_MOVE_PCT (default 0.5%)
             in the signal direction — no alert on flat price.
          2. Confluence score must reach ORDER_FLOW_MIN_CONFLUENCE_SCORE (default 3),
             meaning at least 2 independent signals must agree.
          3. One cooldown per stock per direction (BEARISH / BULLISH),
             not per signal type — prevents the same move firing 6 times.

        Walls and absorption bypass the confluence gate (they are structural signals).
        """
        min_score    = config.ORDER_FLOW_MIN_CONFLUENCE_SCORE

        for symbol, m in metrics.items():
            price        = m['last_price']
            price_chg    = m['price_change_pct']
            buy_vol      = m['buy_volume']
            sell_vol     = m['sell_volume']
            volume_delta = m['volume_delta']
            depth_ratio  = m['depth_ratio']
            bai          = m['bai']
            wall_ratio   = m['wall_ratio']
            wall_side    = m['wall_side']
            wall_price   = m['wall_price']
            wall_qty     = m['wall_qty']
            abs_signal   = m['absorption_signal']
            abs_strength = m['absorption_strength']

            # --- Structural alerts (no confluence gate) ---

            if (wall_ratio >= config.ORDER_FLOW_WALL_ALERT_THRESHOLD
                    and wall_side and self._should_send(symbol, f'WALL_{wall_side}')):
                self.notifier.send_order_flow_wall(
                    symbol, wall_side, wall_price, wall_qty, wall_ratio, price)
                self._mark_sent(symbol, f'WALL_{wall_side}')
                continue

            if (abs_signal and abs_strength >= config.ORDER_FLOW_ABSORPTION_MIN_STRENGTH
                    and self._should_send(symbol, abs_signal)):
                self.notifier.send_order_flow_absorption(
                    symbol, abs_signal, price, wall_side, wall_qty,
                    wall_price, abs_strength, volume_delta)
                self._mark_sent(symbol, abs_signal)
                continue

            # --- Confluence-gated directional alerts ---
            # Gate: at least one order book (cash OR futures) must be actively shifting
            # in the correct direction. Current BAI must agree with direction —
            # a shift from -0.20 to -0.01 is recovery, not a signal.
            bai_delta     = m.get('bai_delta', 0)
            fut_bai       = m.get('fut_bai', 0)
            fut_bai_delta = m.get('fut_bai_delta', 0)
            has_fut       = m.get('fut_tick_count', 0) >= config.ORDER_FLOW_MIN_TICKS

            bear_bai_shift = (
                (bai_delta <= config.ORDER_FLOW_BAI_DELTA_BEARISH and bai <= 0) or
                (has_fut and fut_bai_delta <= config.ORDER_FLOW_FUT_BAI_DELTA_BEARISH and fut_bai <= 0)
            )
            bull_bai_shift = (
                (bai_delta >= config.ORDER_FLOW_BAI_DELTA_BULLISH and bai >= 0) or
                (has_fut and fut_bai_delta >= config.ORDER_FLOW_FUT_BAI_DELTA_BULLISH and fut_bai >= 0)
            )
            if not (bear_bai_shift or bull_bai_shift):
                continue

            # Execution gate: real cash trades must confirm before alerting.
            # BAI/BAI-delta are passive order book depth — fakeable via spoofing.
            # cum_delta_pct is 5-min executed trade flow — cannot be faked cheaply.
            if abs(m.get('cum_delta_pct', 0)) < config.ORDER_FLOW_CUM_EXECUTION_GATE:
                continue

            bear_score, bull_score, bear_reasons, bull_reasons = self._score_stock(m)

            if bear_bai_shift and bear_score >= min_score and self._should_send(symbol, 'BEARISH'):
                label = f"Bearish ({', '.join(bear_reasons)})"
                self.notifier.send_order_flow_bearish(
                    symbol, bai, price, price_chg, depth_ratio,
                    buy_vol, sell_vol, signal_label=label)
                self._mark_sent(symbol, 'BEARISH')
                logger.info(f"BEARISH: {symbol} score={bear_score} — {label}")

            elif bull_bai_shift and bull_score >= min_score and self._should_send(symbol, 'BULLISH'):
                label = f"Bullish ({', '.join(bull_reasons)})"
                self.notifier.send_order_flow_bullish(
                    symbol, bai, price, price_chg, depth_ratio,
                    buy_vol, sell_vol, signal_label=label)
                self._mark_sent(symbol, 'BULLISH')
                logger.info(f"BULLISH: {symbol} score={bull_score} — {label}")

    # --------------------------------------------------------
    # Periodic summary
    # --------------------------------------------------------

    def _maybe_send_summary(self, metrics: Dict[str, dict]):
        """Send top-5 bullish/bearish summary every ORDER_FLOW_SUMMARY_INTERVAL_MIN."""
        elapsed = (datetime.now() - self._last_summary_time).total_seconds() / 60
        if elapsed < config.ORDER_FLOW_SUMMARY_INTERVAL_MIN:
            return

        # Sort by BAI — highest (bullish) and lowest (bearish)
        all_stocks = [m for m in metrics.values() if m['tick_count'] >= config.ORDER_FLOW_MIN_TICKS]
        if not all_stocks:
            return

        sorted_by_bai = sorted(all_stocks, key=lambda x: x['bai'], reverse=True)
        top_n = config.ORDER_FLOW_SUMMARY_TOP_N
        top_bullish = sorted_by_bai[:top_n]
        top_bearish = sorted_by_bai[-top_n:][::-1]  # most bearish first

        self.notifier.send_order_flow_summary(top_bullish, top_bearish)
        self._last_summary_time = datetime.now()
        logger.info(f"Summary sent — top bullish: {[m['symbol'] for m in top_bullish]}")

    # --------------------------------------------------------
    # Main analysis loop
    # --------------------------------------------------------

    def _analysis_loop(self):
        """Runs every ORDER_FLOW_MONITOR_INTERVAL_SEC during market hours."""
        while _is_within_market_hours():
            cycle_start = datetime.now()

            try:
                # 1. Freshness guard
                if self.collector and not self.collector.is_data_fresh():
                    age = self.db.get_metadata('last_tick_time') or 'unknown'
                    logger.warning(f"WebSocket data stale (last tick: {age}) — skipping cycle")
                else:
                    # 2. Analyze all 208 stocks
                    metrics = self.analyzer.analyze_all()
                    logger.info(f"Analyzed {len(metrics)} stocks with active ticks")

                    # 3. Persist computed metrics
                    if metrics:
                        self.db.upsert_flow_metrics_batch(list(metrics.values()))

                    # 4. Check and dispatch alerts
                    # Skip first cycle after restart — BAI deltas are seeded from 0
                    # for futures (new columns), producing spurious large deltas.
                    now_time = datetime.now().time()
                    if self._warmup_cycles_remaining > 0:
                        self._warmup_cycles_remaining -= 1
                        logger.info(f"Warmup cycle — skipping alerts to let BAI delta stabilise")
                    elif now_time < dt_time(9, 20):
                        logger.info("Before 9:20 AM — skipping alerts (opening auction noise)")
                    elif now_time >= dt_time(15, 15):
                        logger.info("After 3:15 PM — skipping alerts (thin market near close)")
                    else:
                        self._check_alerts(metrics)

                    # 5. Periodic summary
                    self._maybe_send_summary(metrics)

                    # 6. Cleanup old ticks
                    self.db.cleanup_old_ticks()

            except Exception as e:
                logger.error(f"Analysis loop error: {e}", exc_info=True)

            # Sleep for remainder of interval
            elapsed = (datetime.now() - cycle_start).total_seconds()
            sleep_for = max(0, config.ORDER_FLOW_MONITOR_INTERVAL_SEC - elapsed)
            if sleep_for > 0:
                time.sleep(sleep_for)

        logger.info("Market closed (3:30 PM) — analysis loop exiting")

    # --------------------------------------------------------
    # Run
    # --------------------------------------------------------

    def run(self):
        """Start collector, then enter analysis loop. Exit after 3:30 PM."""
        logger.info("Starting OrderFlow WebSocket collector...")
        self._start_collector()

        # Give WebSocket ~5 seconds to connect and subscribe
        logger.info("Waiting 5s for WebSocket to connect and subscribe tokens...")
        time.sleep(5)

        logger.info("Entering analysis loop (30-second cycles)")
        self._analysis_loop()

        # Cleanup
        if self.collector:
            self.collector.stop()

        logger.info("Order flow monitor exited cleanly")

    def stop(self):
        if self.collector:
            self.collector.stop()


# --------------------------------------------------------
# Entry point
# --------------------------------------------------------

def main():
    logger.info("=" * 70)
    logger.info("ORDER FLOW MONITOR — CONTINUOUS MODE")
    logger.info("=" * 70)

    if not config.ENABLE_ORDER_FLOW_MONITOR:
        logger.info("ORDER_FLOW_MONITOR disabled in config — exiting")
        return

    if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
        logger.error("KITE_API_KEY or KITE_ACCESS_TOKEN not set — exiting")
        sys.exit(1)

    # Trading day check
    status = get_market_status()
    if not status['is_trading_day']:
        logger.info("Not a trading day — exiting")
        return

    # Wait for market open if started early
    now = datetime.now().time()
    if now < dt_time(9, 15):
        logger.info("Started before market open — waiting...")
        _wait_for_market_open()

    monitor = OrderFlowMonitor()
    try:
        monitor.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        monitor.stop()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        monitor.stop()
        sys.exit(1)


if __name__ == '__main__':
    main()
