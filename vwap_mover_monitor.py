#!/usr/bin/env python3
"""
VWAP Mover Monitor — Top 10 F&O Movers VWAP Alert System
=========================================================
Improvements from backtesting research (34 days, Jan–Mar 2026):

1. H3 Nifty 1st-candle bias  — only LONG on BULL days, SHORT on BEAR days
2. Alert start time 10:00 AM — skip opening noise window
3. Max 1 alert per stock/day — no repeat entries
4. LONG/SHORT + SL ₹ in alert — actionable, risk-aware messages
5. Nifty bias in alert header — day context always visible
6. Trailing SL exit tracker   — follow-up alert on SL hit or EOD exit
7. EOD P&L summary at 3:25 PM — daily recap via Telegram

Strategy (trend-following):
  - Top 10 F&O movers by % from prev day close
  - Enter LONG if stock is UP, SHORT if DOWN — at VWAP touch
  - H3 Nifty bias: shown in alert as context (BULL/BEAR day) — no trades are blocked
  - Trailing SL 0.5% from peak/trough
  - EOD exit at 3:20 PM

Reads from data/central_quotes.db — no live Kite API calls.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

import config
from central_quote_db import get_central_db_reader
from market_utils import is_market_open
from telegram_notifiers.base_notifier import BaseNotifier

# ── Parameters ──────────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15   # within 0.15% of VWAP counts as a touch
TOP_N                    = 10     # track top N movers
LOOP_INTERVAL_SECONDS    = 60

MARKET_OPEN_TIME = "09:15"        # VWAP calculation starts here
ALERT_START_TIME = "10:00"        # no alerts before this (improvement #2)
EXIT_TIME        = "15:20"        # trailing SL positions close here
EOD_SUMMARY_TIME = "15:25"        # EOD P&L summary sent here

TRAILING_SL_PCT  = 0.50           # 0.5% trailing SL (best config from backtest)

LOT_SIZES_FILE   = "data/lot_sizes.json"
# ────────────────────────────────────────────────────────────────────────────

os.makedirs('logs', exist_ok=True)
today_str = datetime.now().strftime('%Y%m%d')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/vwap_mover_monitor_{today_str}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ── Data class for a tracked trade ──────────────────────────────────────────
class ActiveTrade:
    def __init__(self, symbol: str, direction: str, entry_price: float,
                 vwap: float, lot: int, entry_time: str, rank: int, pct_change: float):
        self.symbol      = symbol
        self.direction   = direction
        self.entry_price = entry_price
        self.vwap        = vwap
        self.lot         = lot
        self.entry_time  = entry_time
        self.rank        = rank
        self.pct_change  = pct_change
        self.peak        = entry_price   # for LONG trailing
        self.trough      = entry_price   # for SHORT trailing
        self.current_sl  = (entry_price * (1 - TRAILING_SL_PCT / 100)
                            if direction == "LONG"
                            else entry_price * (1 + TRAILING_SL_PCT / 100))

    def update(self, price: float):
        """Update peak/trough and ratchet trailing SL."""
        if self.direction == "LONG":
            if price > self.peak:
                self.peak = price
            self.current_sl = self.peak * (1 - TRAILING_SL_PCT / 100)
        else:
            if price < self.trough:
                self.trough = price
            self.current_sl = self.trough * (1 + TRAILING_SL_PCT / 100)

    def is_stopped(self, price: float) -> bool:
        if self.direction == "LONG":
            return price <= self.current_sl
        else:
            return price >= self.current_sl

    def pnl(self, exit_price: float) -> float:
        if self.direction == "LONG":
            return (exit_price - self.entry_price) * self.lot
        else:
            return (self.entry_price - exit_price) * self.lot


# ── Main monitor class ───────────────────────────────────────────────────────
class VWAPMoverMonitor:

    def __init__(self):
        logger.info("=" * 80)
        logger.info("VWAP MOVER MONITOR — Initializing")
        logger.info("=" * 80)

        self.db       = get_central_db_reader()
        self.notifier = BaseNotifier()

        self.fo_symbols  = self._load_fo_symbols()
        self.lot_sizes   = self._load_lot_sizes()
        self.prev_close: Dict[str, float] = {}

        # Day state — reset each morning
        self.current_date   = datetime.now().strftime('%Y-%m-%d')
        self.market_bias: Optional[str] = None   # "LONG" | "SHORT" | None
        self.bias_determined = False
        self.alerted_today: Set[str] = set()     # improvement #3: max 1/stock/day
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.eod_summary_sent = False
        self.last_top10: List[str] = []
        self.day_trade_log: List[Dict] = []      # for EOD summary

        logger.info(f"Loaded {len(self.fo_symbols)} F&O symbols, "
                    f"{len(self.lot_sizes)} lot size entries")

    # ── Loaders ─────────────────────────────────────────────────────────────

    def _load_fo_symbols(self) -> List[str]:
        try:
            with open(config.STOCK_LIST_FILE) as f:
                return json.load(f)['stocks']
        except Exception as e:
            logger.error(f"Failed to load fo_stocks.json: {e}")
            sys.exit(1)

    def _load_lot_sizes(self) -> Dict[str, int]:
        try:
            with open(LOT_SIZES_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load lot sizes ({e}) — defaulting to 1")
            return {}

    def _load_prev_close(self):
        self.prev_close = self.db.get_prev_close_prices_batch(self.fo_symbols)
        logger.info(f"Loaded prev_close for {len(self.prev_close)} symbols")
        if len(self.prev_close) < len(self.fo_symbols) * 0.5:
            logger.warning(
                f"Only {len(self.prev_close)}/{len(self.fo_symbols)} symbols have prev_close. "
                "Ensure central_data_collector.py ran today."
            )

    # ── H3 Nifty bias (improvement #1) ──────────────────────────────────────

    def _determine_market_bias(self) -> Optional[str]:
        """
        H3: Compare Nifty 9:15 candle close vs open.
        close >= open  → BULL (only LONG trades)
        close <  open  → BEAR (only SHORT trades)
        Returns "LONG", "SHORT", or None if data unavailable.
        """
        today  = datetime.now().strftime('%Y-%m-%d')
        ts_915 = f"{today} 09:15:00"
        candle = self.db.get_nifty_candle_at(ts_915)

        if candle is None:
            # Fallback: use first available candle today vs its own open
            since     = f"{today} 09:00:00"
            nifty_now = self.db.get_nifty_latest()
            if nifty_now and nifty_now['open'] and nifty_now['open'] > 0:
                bias = "LONG" if nifty_now['price'] >= nifty_now['open'] else "SHORT"
                logger.info(f"H3 fallback (no 9:15 candle): Nifty {nifty_now['price']:.0f} "
                            f"vs open {nifty_now['open']:.0f} → {bias}")
                return bias
            return None

        close = candle['price']
        open_ = candle['open']
        if not open_ or open_ <= 0:
            logger.warning("H3: Nifty 9:15 candle open is 0/None — bias undetermined")
            return None

        bias = "LONG" if close >= open_ else "SHORT"
        logger.info(f"H3 Nifty bias: 9:15 close={close:.0f} vs open={open_:.0f} → {bias}")
        return bias

    # ── Daily reset ──────────────────────────────────────────────────────────

    def _check_day_reset(self):
        """Reset all daily state at the start of a new trading day."""
        today = datetime.now().strftime('%Y-%m-%d')
        if today != self.current_date:
            logger.info(f"New day detected ({today}) — resetting daily state")
            self.current_date    = today
            self.market_bias     = None
            self.bias_determined = False
            self.alerted_today   = set()
            self.active_trades   = {}
            self.eod_summary_sent = False
            self.last_top10      = []
            self.day_trade_log   = []
            self._load_prev_close()

    # ── VWAP ─────────────────────────────────────────────────────────────────

    def _compute_vwap(self, candles: List[Dict]) -> Optional[float]:
        if len(candles) < 2:
            return None
        cum_pv = cum_vol = 0.0
        for i, c in enumerate(candles):
            vol_delta = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
            cum_pv  += c['price'] * vol_delta
            cum_vol += vol_delta
        return cum_pv / cum_vol if cum_vol > 0 else None

    # ── Top movers ───────────────────────────────────────────────────────────

    def _get_top_movers(self, latest: Dict[str, Dict]) -> List[Tuple[str, float, float]]:
        movers = []
        for sym, q in latest.items():
            if sym not in self.prev_close or self.prev_close[sym] <= 0:
                continue
            price = q.get('price', 0)
            if price <= 0:
                continue
            pct = (price - self.prev_close[sym]) / self.prev_close[sym] * 100
            movers.append((sym, pct, price))
        movers.sort(key=lambda x: abs(x[1]), reverse=True)
        return movers[:TOP_N]

    # ── Alert formatting (improvements #4 & #5) ─────────────────────────────

    def _format_entry_alert(
        self,
        symbol: str, rank: int, pct_change: float, price: float,
        vwap: float, distance_pct: float, candle_count: int,
        direction: str, lot: int, sl_price: float,
        top10: List[Tuple[str, float, float]]
    ) -> str:
        dir_icon  = "📈 BUY (LONG)"   if direction == "LONG" else "📉 SELL SHORT"
        pct_icon  = "📈" if pct_change >= 0 else "📉"
        sign      = "+" if pct_change >= 0 else ""
        now_str   = datetime.now().strftime("%I:%M %p")

        # Bias header (improvement #5)
        if self.market_bias == "LONG":
            bias_line = "🟢 <b>BULL DAY</b> (Nifty 9:15 bias)\n"
        elif self.market_bias == "SHORT":
            bias_line = "🔴 <b>BEAR DAY</b> (Nifty 9:15 bias)\n"
        else:
            bias_line = "⚪ <b>Bias: Undetermined</b>\n"

        # SL loss in ₹ (improvement #4)
        sl_dist_pct = abs(price - sl_price) / price * 100
        sl_loss_rs  = sl_dist_pct / 100 * price * lot

        top10_lines = []
        for i, (sym, pct, _) in enumerate(top10, 1):
            s      = "+" if pct >= 0 else ""
            marker = " ← ENTRY" if sym == symbol else ""
            top10_lines.append(f"{i}. {sym}  {s}{pct:.1f}%{marker}")

        return (
            f"📊 <b>VWAP TOUCH ALERT</b>\n"
            f"{bias_line}\n"
            f"🏆 #{rank} Top Mover: <b>{symbol}</b>\n"
            f"{pct_icon} Change: {sign}{pct_change:.2f}% | ₹{price:.2f}\n"
            f"🎯 VWAP: ₹{vwap:.2f}  (dist: {distance_pct:.2f}%)\n"
            f"⏱️ Time: {now_str}  |  Candles: {candle_count}\n\n"
            f"<b>➡️ Action: {dir_icon}</b>\n"
            f"📦 Lot size: {lot}\n"
            f"🛑 SL: ₹{sl_price:.2f}  ({sl_dist_pct:.2f}% = ₹{sl_loss_rs:,.0f} risk/lot)\n\n"
            f"<b>Top {TOP_N} Movers</b>\n"
            + "\n".join(top10_lines)
        )

    def _format_exit_alert(self, trade: ActiveTrade, exit_price: float, reason: str) -> str:
        gross  = trade.pnl(exit_price)
        sign   = "+" if gross >= 0 else ""
        icon   = "✅" if gross >= 0 else "🔴"
        r_icon = "🛑 SL HIT" if reason == "TSL" else "🏁 EOD EXIT"

        move_pct = abs(exit_price - trade.entry_price) / trade.entry_price * 100
        dir_icon = "📈" if trade.direction == "LONG" else "📉"

        return (
            f"{icon} <b>{r_icon} — {trade.symbol}</b>\n\n"
            f"{dir_icon} {trade.direction}  #{trade.rank} | {'+' if trade.pct_change>=0 else ''}{trade.pct_change:.2f}%\n"
            f"Entry: ₹{trade.entry_price:.2f}  →  Exit: ₹{exit_price:.2f}\n"
            f"Move: {move_pct:.2f}%  |  Lot: {trade.lot}\n"
            f"<b>P&L: {sign}₹{gross:,.0f}</b> (gross, before charges)\n"
            f"⏱️ Exited: {datetime.now().strftime('%I:%M %p')}"
        )

    def _format_eod_summary(self) -> str:
        bias_str = (f"🟢 BULL" if self.market_bias == "LONG"
                    else f"🔴 BEAR" if self.market_bias == "SHORT"
                    else "⚪ Unfiltered")
        total_gross = sum(t['gross_pnl'] for t in self.day_trade_log)
        total_lots  = sum(t['lot']       for t in self.day_trade_log)
        winners     = [t for t in self.day_trade_log if t['gross_pnl'] > 0]
        losers      = [t for t in self.day_trade_log if t['gross_pnl'] <= 0]
        sign        = "+" if total_gross >= 0 else ""
        day_icon    = "✅" if total_gross > 0 else "❌"

        lines = [
            f"📊 <b>EOD SUMMARY — {self.current_date}</b>",
            f"Nifty Bias: {bias_str}",
            f"",
            f"Trades: {len(self.day_trade_log)}  |  W: {len(winners)}  L: {len(losers)}",
            f"<b>Gross P&L: {day_icon} {sign}₹{total_gross:,.0f}</b>",
            f"",
            f"<b>Trade Details</b>",
        ]
        for t in self.day_trade_log:
            s    = "+" if t['gross_pnl'] >= 0 else ""
            icon = "✅" if t['gross_pnl'] > 0 else "❌"
            lines.append(
                f"{icon} {t['symbol']} {t['direction']} @{t['entry']:.0f}→{t['exit']:.0f} "
                f"lot={t['lot']}  {s}₹{t['gross_pnl']:,.0f}  [{t['exit_reason']}]"
            )

        lines += ["", "⚠️ Charges not included — add ~₹200-300/trade for Zerodha F&O"]
        return "\n".join(lines)

    # ── Exit/SL tracker (improvement #6) ────────────────────────────────────

    def _update_active_trades(self, latest: Dict[str, Dict]):
        """Check all active trades against trailing SL and EOD exit."""
        now_str  = datetime.now().strftime("%H:%M")
        is_eod   = now_str >= EXIT_TIME
        to_close = []

        for sym, trade in self.active_trades.items():
            q = latest.get(sym)
            if not q:
                continue
            price = q.get('price', 0)
            if price <= 0:
                continue

            trade.update(price)

            if is_eod:
                reason = "EOD"
            elif trade.is_stopped(price):
                reason = "TSL"
            else:
                continue

            to_close.append((sym, price, reason))

        for sym, exit_price, reason in to_close:
            trade = self.active_trades.pop(sym)
            gross = trade.pnl(exit_price)

            self.day_trade_log.append({
                'symbol': sym, 'direction': trade.direction,
                'entry': trade.entry_price, 'exit': exit_price,
                'lot': trade.lot, 'gross_pnl': gross,
                'exit_reason': reason, 'entry_time': trade.entry_time,
            })

            msg = self._format_exit_alert(trade, exit_price, reason)
            if self.notifier._send_message(msg):
                logger.info(f"EXIT {reason}: {sym} {trade.direction} "
                            f"entry={trade.entry_price:.2f} exit={exit_price:.2f} "
                            f"P&L=₹{gross:+,.0f}")
            else:
                logger.error(f"Failed to send exit alert for {sym}")

    # ── EOD summary (improvement #7) ────────────────────────────────────────

    def _maybe_send_eod_summary(self):
        now_str = datetime.now().strftime("%H:%M")
        if now_str >= EOD_SUMMARY_TIME and not self.eod_summary_sent:
            if self.day_trade_log:
                msg = self._format_eod_summary()
                if self.notifier._send_message(msg):
                    logger.info("EOD summary sent")
                    self.eod_summary_sent = True
                else:
                    logger.error("Failed to send EOD summary")
            else:
                logger.info("EOD: no trades today, skipping summary")
                self.eod_summary_sent = True

    # ── Main cycle ───────────────────────────────────────────────────────────

    def _run_cycle(self):
        now     = datetime.now()
        now_str = now.strftime("%H:%M")

        # Try to determine H3 bias (improvement #1)
        if not self.bias_determined and now_str >= "09:16":
            bias = self._determine_market_bias()
            if bias:
                self.market_bias     = bias
                self.bias_determined = True
                bias_icon = "🟢" if bias == "LONG" else "🔴"
                logger.info(f"Market bias set: {bias_icon} {bias} — "
                            f"will only send {'LONG' if bias=='LONG' else 'SHORT'} alerts today")

        # Latest quotes
        latest = self.db.get_latest_stock_quotes()
        if not latest:
            logger.warning("No quotes in DB")
            return

        # Update active trades / check exits (improvement #6)
        if self.active_trades:
            self._update_active_trades(latest)

        # EOD summary (improvement #7)
        self._maybe_send_eod_summary()

        # Skip new entry signals before ALERT_START_TIME (improvement #2)
        if now_str < ALERT_START_TIME:
            logger.debug(f"Before {ALERT_START_TIME} — no entry signals yet")
            return

        # Skip new entries after exit time
        if now_str >= EXIT_TIME:
            return

        # Top movers
        top10 = self._get_top_movers(latest)
        if not top10:
            logger.warning("No movers — prev_close may be missing")
            return

        top10_symbols = [s for s, _, _ in top10]
        if top10_symbols != self.last_top10:
            logger.info("Top 10 movers:")
            for i, (sym, pct, price) in enumerate(top10, 1):
                logger.info(f"  #{i} {sym}: {pct:+.2f}% @ ₹{price:.2f}")
            self.last_top10 = top10_symbols

        # Candle history for top10
        market_open_str = now.strftime(f'%Y-%m-%d {MARKET_OPEN_TIME}:00')
        history = self.db.get_stock_history_since_batch(top10_symbols, market_open_str)

        for rank, (symbol, pct_change, price) in enumerate(top10, 1):
            # Improvement #3: max 1 alert per stock per day
            if symbol in self.alerted_today:
                continue

            candles = history.get(symbol, [])
            vwap    = self._compute_vwap(candles)
            if vwap is None:
                continue

            dist_pct = abs(price - vwap) / vwap * 100
            if dist_pct > VWAP_TOUCH_THRESHOLD_PCT:
                continue

            # Trade direction
            direction = "LONG" if pct_change >= 0 else "SHORT"

            # H3 bias is informational only — shown in alert, no trades blocked

            lot      = self.lot_sizes.get(symbol, 1)
            sl_price = (price * (1 - TRAILING_SL_PCT / 100)
                        if direction == "LONG"
                        else price * (1 + TRAILING_SL_PCT / 100))

            logger.info(
                f"VWAP TOUCH: {symbol} #{rank} | {pct_change:+.2f}% | {direction} | "
                f"price={price:.2f} vwap={vwap:.2f} dist={dist_pct:.3f}% sl={sl_price:.2f}"
            )

            msg = self._format_entry_alert(
                symbol=symbol, rank=rank, pct_change=pct_change, price=price,
                vwap=vwap, distance_pct=dist_pct, candle_count=len(candles),
                direction=direction, lot=lot, sl_price=sl_price, top10=top10,
            )

            if self.notifier._send_message(msg):
                self.alerted_today.add(symbol)
                # Start tracking this trade (improvement #6)
                self.active_trades[symbol] = ActiveTrade(
                    symbol=symbol, direction=direction, entry_price=price,
                    vwap=vwap, lot=lot, entry_time=now.strftime("%H:%M"),
                    rank=rank, pct_change=pct_change,
                )
                logger.info(f"  ✓ Alert sent & trade tracking started: {symbol} {direction} "
                            f"SL={sl_price:.2f} lot={lot}")
            else:
                logger.error(f"Failed to send alert for {symbol}")

    # ── Run loop ─────────────────────────────────────────────────────────────

    def run(self):
        logger.info("Starting VWAP Mover Monitor...")
        logger.info(f"  Alert start: {ALERT_START_TIME} | Exit: {EXIT_TIME} | EOD summary: {EOD_SUMMARY_TIME}")
        logger.info(f"  Trailing SL: {TRAILING_SL_PCT}% | VWAP threshold: {VWAP_TOUCH_THRESHOLD_PCT}%")

        self._load_prev_close()
        if not self.prev_close:
            logger.error(
                "No prev_close prices found. "
                "Restart central_data_collector.py first, then rerun this script."
            )
            sys.exit(1)

        while True:
            self._check_day_reset()

            if not is_market_open():
                logger.info("Market closed — sleeping 60s")
                time.sleep(60)
                continue

            cycle_start = time.time()
            try:
                self._run_cycle()
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)

            elapsed    = time.time() - cycle_start
            sleep_time = max(0, LOOP_INTERVAL_SECONDS - elapsed)
            logger.debug(f"Cycle took {elapsed:.1f}s, sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)


def main():
    monitor = VWAPMoverMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
