#!/usr/bin/env python3
"""
Order Flow Analyzer — crowd psychology metrics from real-time tick data.

LESSON LEARNED (SUNPHARMA 11:18 AM):
  KiteTicker's total_buy_quantity / total_sell_quantity = passive order book depth.
  For liquid F&O stocks, bids always outnumber asks (depth_ratio ~1.8). BAI stays
  near zero even during a 1.65% drop because the order book always has large pending
  bids sitting below the market. BAI threshold of -0.65 was never reachable.

CORRECT APPROACH — what actually signals aggressive moves:
  1. BAI Delta (ΔBAI):        rate of BAI decline over consecutive cycles
  2. Tick velocity:           avg absolute price change per tick (momentum proxy)
  3. L1 bid shrinkage:        top-of-book bid quantity being consumed (thinning support)
  4. Cumulative volume delta: 5-minute buy vs sell flow (not just 30-second window)
  5. BAI (absolute):          still useful for extreme cases, but threshold lowered to ±0.35

Author: Claude Sonnet 4.6
"""

import logging
from typing import Dict, List, Optional, Tuple

import config
from order_flow_db import OrderFlowDB

logger = logging.getLogger(__name__)


class OrderFlowAnalyzer:
    """
    Computes per-stock order flow metrics from the last N seconds of tick data.
    Reads all ticks in a single batch query — one pass for all 208 stocks.
    """

    def __init__(self, db: OrderFlowDB):
        self.db = db
        self._prev_bai: Dict[str, float] = {}      # cash BAI from previous cycle
        self._prev_fut_bai: Dict[str, float] = {}  # futures BAI from previous cycle

    # --------------------------------------------------------
    # Main entry point
    # --------------------------------------------------------

    def analyze_all(self) -> Dict[str, dict]:
        """
        Analyze all stocks in one pass. Returns {symbol: metrics_dict}.
        Also loads previous BAI values from DB for delta computation.
        """
        # Load previous BAI for delta computation before overwriting
        self._prev_bai, self._prev_fut_bai = self.db.get_previous_bai_map()

        # all_ticks: {symbol: {'CASH': [...], 'FUT': [...]}}
        all_ticks = self.db.get_all_ticks_since(config.ORDER_FLOW_ANALYSIS_WINDOW)
        results = {}
        for symbol, tick_sets in all_ticks.items():
            cash_ticks = tick_sets.get('CASH', [])
            if len(cash_ticks) < config.ORDER_FLOW_MIN_TICKS:
                continue
            fut_ticks = tick_sets.get('FUT', [])
            results[symbol] = self.analyze_symbol(symbol, cash_ticks, fut_ticks)
        return results

    # --------------------------------------------------------
    # Per-symbol analysis
    # --------------------------------------------------------

    def analyze_symbol(self, symbol: str, cash_ticks: List[dict],
                       fut_ticks: List[dict] = None) -> dict:
        """Compute all metrics for one stock from cash and (optionally) futures tick lists."""
        from datetime import datetime
        if fut_ticks is None:
            fut_ticks = []

        # --- Cash metrics (unchanged) ---
        bai          = self._compute_bai(cash_ticks)
        bai_prev     = self._prev_bai.get(symbol, bai)
        bai_delta    = bai - bai_prev

        depth_ratio  = self._compute_depth_ratio(cash_ticks)
        delta, buy_vol, sell_vol = self._compute_volume_delta(cash_ticks)
        tick_velocity = self._compute_tick_velocity(cash_ticks)
        bid_l1_shrink = self._compute_bid_l1_shrink(cash_ticks)
        price_chg    = self._compute_price_change(cash_ticks)

        cum_buy, cum_sell = self.db.get_cumulative_volume_stats(symbol, minutes=5, asset_type='CASH')
        cum_total = cum_buy + cum_sell
        cum_delta_pct = (cum_buy - cum_sell) / cum_total if cum_total > 0 else 0.0

        has_bid_wall, has_ask_wall, wall_ratio, wall_side, wall_price, wall_qty = (
            self._detect_walls(cash_ticks)
        )
        abs_signal, abs_strength = self._detect_absorption(
            cash_ticks, bai, price_chg, has_bid_wall, has_ask_wall,
            wall_side, buy_vol, sell_vol
        )
        cash_last_price = cash_ticks[-1]['last_price']

        # --- Futures metrics ---
        fut_bai = fut_bai_prev = fut_bai_delta = 0.0
        fut_cum_delta_pct = fut_tick_velocity = 0.0
        fut_last_price = 0.0
        basis_pct = 0.0

        if len(fut_ticks) >= config.ORDER_FLOW_MIN_TICKS:
            fut_bai      = self._compute_bai(fut_ticks)
            fut_bai_prev = self._prev_fut_bai.get(symbol, fut_bai)
            fut_bai_delta = fut_bai - fut_bai_prev

            fut_cum_buy, fut_cum_sell = self.db.get_cumulative_volume_stats(
                symbol, minutes=5, asset_type='FUT')
            fut_cum_total = fut_cum_buy + fut_cum_sell
            fut_cum_delta_pct = (
                (fut_cum_buy - fut_cum_sell) / fut_cum_total if fut_cum_total > 0 else 0.0
            )

            fut_tick_velocity = self._compute_tick_velocity(fut_ticks)
            fut_last_price = fut_ticks[-1]['last_price']

            if cash_last_price > 0:
                basis_pct = (fut_last_price - cash_last_price) / cash_last_price * 100

        return {
            'symbol':            symbol,
            'ts':                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'bai':               round(bai, 4),
            'bai_prev':          round(bai_prev, 4),
            'bai_delta':         round(bai_delta, 4),
            'depth_ratio':       round(depth_ratio, 4),
            'volume_delta':      delta,
            'buy_volume':        buy_vol,
            'sell_volume':       sell_vol,
            'cum_delta_pct':     round(cum_delta_pct, 4),
            'bid_l1_shrink_pct': round(bid_l1_shrink, 4),
            'tick_velocity':     round(tick_velocity, 4),
            'price_change_pct':  round(price_chg, 4),
            'has_bid_wall':      has_bid_wall,
            'has_ask_wall':      has_ask_wall,
            'wall_ratio':        round(wall_ratio, 2),
            'wall_side':         wall_side,
            'wall_price':        wall_price,
            'wall_qty':          wall_qty,
            'absorption_signal': abs_signal,
            'absorption_strength': round(abs_strength, 4),
            'last_price':        cash_last_price,
            'tick_count':        len(cash_ticks),
            # Futures
            'fut_bai':           round(fut_bai, 4),
            'fut_bai_prev':      round(fut_bai_prev, 4),
            'fut_bai_delta':     round(fut_bai_delta, 4),
            'fut_cum_delta_pct': round(fut_cum_delta_pct, 4),
            'fut_tick_velocity': round(fut_tick_velocity, 4),
            'fut_last_price':    fut_last_price,
            'fut_tick_count':    len(fut_ticks),
            'basis_pct':         round(basis_pct, 4),
        }

    # --------------------------------------------------------
    # Metric computations
    # --------------------------------------------------------

    def _compute_bai(self, ticks: List[dict]) -> float:
        """
        Bid-Ask Imbalance: average of (buy_qty - sell_qty) / (buy_qty + sell_qty).
        Measures passive order book imbalance, not active flow.
        For liquid stocks, rarely crosses ±0.35 even on strong moves.
        """
        total, count = 0.0, 0
        for t in ticks:
            b, s = t['buy_quantity'], t['sell_quantity']
            denom = b + s
            if denom > 0:
                total += (b - s) / denom
                count += 1
        return total / count if count > 0 else 0.0

    def _compute_depth_ratio(self, ticks: List[dict]) -> float:
        """bid_depth_total / ask_depth_total averaged over window."""
        total, count = 0.0, 0
        for t in ticks:
            ask = t['ask_depth_total']
            if ask > 0:
                total += t['bid_depth_total'] / ask
                count += 1
        return total / count if count > 0 else 1.0

    def _compute_volume_delta(self, ticks: List[dict]) -> Tuple[int, int, int]:
        """
        Classify each trade tick: last_price >= best_ask → buy-initiated,
        last_price <= best_bid → sell-initiated.
        Returns (delta, buy_volume, sell_volume).
        """
        buy_vol = sell_vol = 0
        for t in ticks:
            qty = t['last_quantity']
            if qty <= 0:
                continue
            price, best_ask, best_bid = t['last_price'], t['best_ask'], t['best_bid']
            if best_ask > 0 and price >= best_ask:
                buy_vol += qty
            elif best_bid > 0 and price <= best_bid:
                sell_vol += qty
        return (buy_vol - sell_vol), buy_vol, sell_vol

    def _compute_tick_velocity(self, ticks: List[dict]) -> float:
        """
        Average absolute price change per consecutive tick pair.
        High velocity = price moving fast tick-by-tick = directional momentum.
        Returns value in ₹ per tick (e.g. 0.50 = price moving ₹0.50 per tick on avg).
        """
        if len(ticks) < 2:
            return 0.0
        moves = []
        for i in range(1, len(ticks)):
            delta = abs(ticks[i]['last_price'] - ticks[i-1]['last_price'])
            if delta > 0:
                moves.append(delta)
        return sum(moves) / len(moves) if moves else 0.0

    def _compute_bid_l1_shrink(self, ticks: List[dict]) -> float:
        """
        % drop in L1 bid quantity from first tick to last tick in window.
        Positive value = bid wall being consumed (bearish).
        e.g. 0.40 = L1 bid dropped 40% → support being eaten.
        """
        first_l1 = ticks[0]['bid_l1_qty']
        last_l1  = ticks[-1]['bid_l1_qty']
        if first_l1 <= 0:
            return 0.0
        shrink = (first_l1 - last_l1) / first_l1
        return max(0.0, shrink)   # only positive (growth means support building)

    def _detect_walls(self, ticks: List[dict]) -> Tuple[bool, bool, float, str, float, int]:
        """
        Wall = single depth level with qty > WALL_THRESHOLD × avg level qty.
        Uses the LAST tick (most current book snapshot).
        Returns (has_bid_wall, has_ask_wall, wall_ratio, wall_side, wall_price, wall_qty).
        """
        last = ticks[-1]

        bid_levels = [
            (last['bid_l1_qty'], last['bid_l1_price']),
            (last['bid_l2_qty'], last.get('bid_l2_price', 0)),
            (last['bid_l3_qty'], last.get('bid_l3_price', 0)),
            (last['bid_l4_qty'], last.get('bid_l4_price', 0)),
            (last['bid_l5_qty'], last.get('bid_l5_price', 0)),
        ]
        ask_levels = [
            (last['ask_l1_qty'], last['ask_l1_price']),
            (last['ask_l2_qty'], last.get('ask_l2_price', 0)),
            (last['ask_l3_qty'], last.get('ask_l3_price', 0)),
            (last['ask_l4_qty'], last.get('ask_l4_price', 0)),
            (last['ask_l5_qty'], last.get('ask_l5_price', 0)),
        ]

        def _check(levels):
            qtys = [q for q, p in levels if q > 0]
            if len(qtys) < 2:
                return False, 0.0, 0.0, 0
            avg_qty = sum(qtys) / len(qtys)
            max_qty = max(qtys)
            ratio = max_qty / avg_qty if avg_qty > 0 else 0.0
            if ratio >= config.ORDER_FLOW_WALL_THRESHOLD:
                max_price = next((p for q, p in levels if q == max_qty), 0.0)
                return True, ratio, max_price, max_qty
            return False, ratio, 0.0, 0

        bid_wall, bid_ratio, bid_price, bid_qty = _check(bid_levels)
        ask_wall, ask_ratio, ask_price, ask_qty = _check(ask_levels)

        if bid_wall and (not ask_wall or bid_ratio >= ask_ratio):
            return True, ask_wall, bid_ratio, 'BID', bid_price, bid_qty
        elif ask_wall:
            return bid_wall, True, ask_ratio, 'ASK', ask_price, ask_qty
        return False, False, max(bid_ratio, ask_ratio), '', 0.0, 0

    def _detect_absorption(
        self, ticks, bai, price_change_pct,
        has_bid_wall, has_ask_wall, wall_side, buy_vol, sell_vol
    ) -> Tuple[str, float]:
        """
        Absorption: strong order flow + price NOT moving = institutional absorption.
        SELL_ABSORPTION (bullish): ask wall + sell volume + price holding.
        BUY_ABSORPTION (bearish):  bid wall + buy volume + price not rising.
        """
        total_vol = buy_vol + sell_vol
        if total_vol == 0:
            return '', 0.0

        price_still = abs(price_change_pct) < 0.10
        min_strength = config.ORDER_FLOW_ABSORPTION_MIN_STRENGTH

        if (has_ask_wall and wall_side == 'ASK'
                and sell_vol > buy_vol and price_change_pct >= -0.05 and price_still):
            strength = min((sell_vol / total_vol) * (1 - abs(price_change_pct) / 0.5), 1.0)
            if strength >= min_strength:
                return 'SELL_ABSORPTION', strength

        if (has_bid_wall and wall_side == 'BID'
                and buy_vol > sell_vol and price_change_pct <= 0.05 and price_still):
            strength = min((buy_vol / total_vol) * (1 - abs(price_change_pct) / 0.5), 1.0)
            if strength >= min_strength:
                return 'BUY_ABSORPTION', strength

        return '', 0.0

    def _compute_price_change(self, ticks: List[dict]) -> float:
        """Price change % from first to last tick in the 30-second window."""
        first = ticks[0]['last_price']
        last  = ticks[-1]['last_price']
        return ((last - first) / first * 100) if first > 0 else 0.0

