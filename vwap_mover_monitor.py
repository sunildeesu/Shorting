#!/usr/bin/env python3
"""
VWAP Mover Monitor — Top 20 F&O Movers VWAP Alert System
=========================================================
Improvements from backtesting research (34 days, Jan–Mar 2026):

1. H3 Nifty 1st-candle bias  — only LONG on BULL days, SHORT on BEAR days
2. Alert start time 10:00 AM — skip opening noise window
3. Max 2 alerts per stock/day — 15-min cooldown between signals
4. LONG/SHORT + SL ₹ in alert — actionable, risk-aware messages
5. Nifty bias in alert header — day context always visible
6. Trailing SL exit tracker   — follow-up alert on SL hit or EOD exit
7. EOD P&L summary at 3:25 PM — daily recap via Telegram
8. T+2 confirmation candle    — enter only if T+2 close confirms direction vs VWAP

Strategy (trend-following):
  - Top 20 F&O movers by % from prev day close
  - Signal at VWAP touch (within 0.15%); enter only if T+2 candle confirms direction
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
from typing import Dict, List, Optional, Tuple

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

TRAILING_SL_PCT        = 0.50    # 0.5% trailing SL (best config from backtest)
CONFIRM_OFFSET         = 2       # enter at T+2 candle if it confirms direction (#8)
MAX_TRADES_PER_STOCK   = 2       # max trades per stock per day
ALERT_COOLDOWN_MINUTES = 15      # min gap between signals on the same stock

# ── Volume Filter (backtest-derived: 61% win rate, avg +₹2,414/trade) ───────
# Require C-1 (touch candle) vol ≥ 1.5× day avg  AND  C-2 vol < 1.0× day avg
# Pattern: quiet accumulation → volume spike at VWAP touch = institutional interest
VOLUME_FILTER_ENABLED = True
VOLUME_C1_MIN_RATIO   = 1.5   # touch candle vol delta must be ≥ 1.5× avg
VOLUME_C2_MAX_RATIO   = 1.0   # candle before touch must be < 1.0× avg (quiet)

LOT_SIZES_FILE   = "data/lot_sizes.json"
# ────────────────────────────────────────────────────────────────────────────

os.makedirs('logs', exist_ok=True)
today_str = datetime.now().strftime('%Y%m%d')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/vwap_mover_monitor_{today_str}.log'),
    ]
)
logger = logging.getLogger(__name__)


# ── Redis signal publisher (best-effort, never raises) ───────────────────────
_redis_pub = None


def _redis_publish(payload: dict) -> None:
    """Publish *payload* to 'vwap:signals'. Silently skips on any error."""
    global _redis_pub
    try:
        import redis as _redis_mod
        if _redis_pub is None:
            _redis_pub = _redis_mod.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                db=int(os.getenv("REDIS_DB", 0)),
                password=os.getenv("REDIS_PASS") or None,
                decode_responses=True,
                socket_connect_timeout=1,
            )
        _redis_pub.publish("vwap:signals", json.dumps(payload))
    except Exception as exc:
        logger.warning("[Redis] vwap:signals publish failed: %s", exc)
        _redis_pub = None   # reset so next call retries the connection


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
        self.prev_close_loaded_date: Optional[str] = None   # date when prev_close was refreshed from collector

        # Day state — reset each morning
        self.current_date   = datetime.now().strftime('%Y-%m-%d')
        self.market_bias: Optional[str] = None   # "LONG" | "SHORT" | None
        self.bias_determined = False
        self.trade_count: Dict[str, int] = {}           # trades entered per symbol today
        self.pending_signals: Dict[str, Dict] = {}      # signals queued for T+2 confirm
        self.cooldown_until: Dict[str, datetime] = {}   # symbol → when cooldown expires
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.eod_summary_sent = False
        self.last_top10: List[str] = []
        self.day_trade_log: List[Dict] = []      # for EOD summary

        logger.info(f"Loaded {len(self.fo_symbols)} F&O symbols, "
                    f"{len(self.lot_sizes)} lot size entries")
        vol_status = (f"ON (C-1≥{VOLUME_C1_MIN_RATIO}× + C-2<{VOLUME_C2_MAX_RATIO}×)"
                      if VOLUME_FILTER_ENABLED else "OFF")
        self.notifier.send_debug(
            f"🚀 <b>VWAP Monitor Started</b>\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %I:%M %p')}\n"
            f"Symbols: {len(self.fo_symbols)}  |  Lots loaded: {len(self.lot_sizes)}\n"
            f"Alert start: {ALERT_START_TIME}  |  Exit: {EXIT_TIME}  |  TSL: {TRAILING_SL_PCT}%\n"
            f"Confirm: T+{CONFIRM_OFFSET}  |  Max trades/stock: {MAX_TRADES_PER_STOCK}  |  "
            f"Cooldown: {ALERT_COOLDOWN_MINUTES}min\n"
            f"📊 Vol filter: {vol_status}"
        )

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
        # Track the date of the most recent DB update so we can detect stale loads
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT MAX(updated_at) FROM prev_close_prices")
            row = cursor.fetchone()
            if row and row[0]:
                self.prev_close_loaded_date = row[0][:10]   # 'YYYY-MM-DD'
            else:
                self.prev_close_loaded_date = None
        except Exception:
            self.prev_close_loaded_date = None
        logger.info(f"Loaded prev_close for {len(self.prev_close)} symbols "
                    f"(DB updated_at date: {self.prev_close_loaded_date})")
        if len(self.prev_close) < len(self.fo_symbols) * 0.5:
            logger.warning(
                f"Only {len(self.prev_close)}/{len(self.fo_symbols)} symbols have prev_close. "
                "Ensure central_data_collector.py ran today."
            )
            self.notifier.send_debug(
                f"⚠️ <b>prev_close Warning</b>\n"
                f"Only {len(self.prev_close)}/{len(self.fo_symbols)} symbols have prev_close.\n"
                f"DB updated_at: {self.prev_close_loaded_date}\n"
                f"Ensure central_data_collector.py is running."
            )

    # ── H3 Nifty bias ────────────────────────────────────────────────────────

    def _determine_market_bias(self) -> Optional[str]:
        """
        H3: Compare Nifty 9:15 candle close vs open. Set once, fixed for the day.
        close >= open → LONG   |   close < open → SHORT
        Returns "LONG", "SHORT", or None if data unavailable.
        """
        today  = datetime.now().strftime('%Y-%m-%d')
        ts_915 = f"{today} 09:15:00"
        candle = self.db.get_nifty_candle_at(ts_915)

        if candle is None:
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
            self.notifier.send_debug(
                f"📅 <b>New Trading Day: {today}</b>\n"
                f"Daily state reset. Waiting for collector to update prev_close after 9:15 AM."
            )
            self.current_date         = today
            self.market_bias          = None
            self.bias_determined      = False
            self.trade_count          = {}
            self.pending_signals      = {}
            self.cooldown_until       = {}
            self.active_trades        = {}
            self.eod_summary_sent     = False
            self.last_top10           = []
            self.day_trade_log        = []
            self.prev_close_loaded_date = None   # force reload after collector runs
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

    def _check_volume_filter(self, candles: List[Dict]) -> Tuple[bool, float, float]:
        """
        Returns (passes, c1_ratio, c2_ratio).
        C-1 = touch candle vol delta vs day avg.
        C-2 = candle just before touch vs day avg.
        Pass condition: C-1 >= VOLUME_C1_MIN_RATIO  AND  C-2 < VOLUME_C2_MAX_RATIO
        Always passes (True) if filter disabled or insufficient candle history.
        """
        if not VOLUME_FILTER_ENABLED or len(candles) < 3:
            return True, 0.0, 0.0

        deltas = []
        for i, c in enumerate(candles):
            deltas.append(float(c['volume'] if i == 0
                                else max(0, c['volume'] - candles[i-1]['volume'])))

        # Baseline avg = all candles except the last 2 (C-1 and C-2)
        baseline = deltas[:-2]
        avg = sum(baseline) / len(baseline) if baseline else 0
        if avg <= 0:
            return True, 0.0, 0.0

        c1_ratio = deltas[-1] / avg
        c2_ratio = deltas[-2] / avg
        passes   = (c1_ratio >= VOLUME_C1_MIN_RATIO) and (c2_ratio < VOLUME_C2_MAX_RATIO)
        return passes, round(c1_ratio, 2), round(c2_ratio, 2)

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
        top10: List[Tuple[str, float, float]],
        confirmed: bool = False,
        c1_ratio: float = 0.0, c2_ratio: float = 0.0,
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

        # Volume filter line
        if VOLUME_FILTER_ENABLED and c1_ratio > 0:
            vol_line = f"📊 Vol: C-1={c1_ratio:.2f}× C-2={c2_ratio:.2f}× (quiet→spike ✅)\n"
        else:
            vol_line = ""

        top10_lines = []
        for i, (sym, pct, _) in enumerate(top10, 1):
            s      = "+" if pct >= 0 else ""
            marker = " ← ENTRY" if sym == symbol else ""
            top10_lines.append(f"{i}. {sym}  {s}{pct:.1f}%{marker}")

        header = "✅ <b>VWAP CONFIRMED ENTRY (T+2)</b>" if confirmed else "📊 <b>VWAP TOUCH ALERT</b>"
        return (
            f"{header}\n"
            f"{bias_line}\n"
            f"🏆 #{rank} Top Mover: <b>{symbol}</b>\n"
            f"{pct_icon} Change: {sign}{pct_change:.2f}% | ₹{price:.2f}\n"
            f"🎯 VWAP: ₹{vwap:.2f}  (dist: {distance_pct:.2f}%)\n"
            f"⏱️ Time: {now_str}  |  Candles: {candle_count}\n"
            f"{vol_line}\n"
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
                _redis_publish({
                    "type": "EXIT", "symbol": sym, "direction": trade.direction,
                    "reason": reason, "entry": trade.entry_price,
                    "exit": exit_price, "pnl": int(gross), "ts": time.time(),
                })
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

        # Reload prev_close if the collector has updated it since our last load
        # (fixes race: monitor loads at midnight before collector runs at 9:15)
        today = now.strftime('%Y-%m-%d')
        if now_str >= "09:20" and self.prev_close_loaded_date != today:
            logger.info(
                f"prev_close was loaded from {self.prev_close_loaded_date}, "
                f"collector has since updated it — reloading"
            )
            self._load_prev_close()
            self.notifier.send_debug(
                f"🔄 <b>prev_close Reloaded</b>\n"
                f"Stale data ({self.prev_close_loaded_date or 'unknown'}) replaced with today's values.\n"
                f"Symbols loaded: {len(self.prev_close)}"
            )

        # H3 bias — determined once at 9:16 AM, fixed for the day
        if not self.bias_determined and now_str >= "09:16":
            bias = self._determine_market_bias()
            if bias:
                self.market_bias     = bias
                self.bias_determined = True
                bias_icon = "🟢" if bias == "LONG" else "🔴"
                logger.info(f"Market bias set: {bias_icon} {bias} — "
                            f"will only send {bias} alerts today")
                self.notifier.send_debug(
                    f"{bias_icon} <b>Market Bias Set: {bias}</b>  (H3 9:15 candle)\n"
                    f"Only <b>{bias}</b> alerts will fire today."
                )

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

        # ── Process pending confirmation signals (improvement #8) ────────────
        for sym in list(self.pending_signals.keys()):
            sig = self.pending_signals[sym]
            sig['elapsed'] += 1
            if sig['elapsed'] < CONFIRM_OFFSET:
                continue   # not yet at T+CONFIRM_OFFSET

            # One-shot: check at exactly T+CONFIRM_OFFSET, then discard
            q = latest.get(sym)
            confirmed = False
            if q:
                price_now = q.get('price', 0)
                direction = sig['direction']
                confirmed = (
                    (direction == "LONG"  and price_now > sig['vwap']) or
                    (direction == "SHORT" and price_now < sig['vwap'])
                )
                can_enter = (
                    confirmed
                    and sym not in self.active_trades
                    and self.trade_count.get(sym, 0) < MAX_TRADES_PER_STOCK
                )
                if can_enter:
                    lot      = self.lot_sizes.get(sym, 1)
                    sl_price = (price_now * (1 - TRAILING_SL_PCT / 100)
                                if direction == "LONG"
                                else price_now * (1 + TRAILING_SL_PCT / 100))
                    dist_pct = abs(price_now - sig['vwap']) / sig['vwap'] * 100

                    logger.info(
                        f"CONFIRM ENTRY (T+{CONFIRM_OFFSET}): {sym} | {direction} | "
                        f"price={price_now:.2f} vwap={sig['vwap']:.2f} sl={sl_price:.2f}"
                    )
                    _redis_publish({
                        "type": "ENTRY", "symbol": sym, "direction": direction,
                        "price": price_now, "vwap": sig["vwap"], "sl": sl_price,
                        "ts": time.time(),
                    })

                    msg = self._format_entry_alert(
                        symbol=sym, rank=sig['rank'], pct_change=sig['pct_change'],
                        price=price_now, vwap=sig['vwap'], distance_pct=dist_pct,
                        candle_count=sig['candle_count'],
                        direction=direction, lot=lot, sl_price=sl_price,
                        top10=self._get_top_movers(latest),
                        confirmed=True,
                        c1_ratio=sig.get('c1_ratio', 0.0),
                        c2_ratio=sig.get('c2_ratio', 0.0),
                    )
                    if self.notifier._send_message(msg):
                        self.trade_count[sym] = self.trade_count.get(sym, 0) + 1
                        self.active_trades[sym] = ActiveTrade(
                            symbol=sym, direction=direction, entry_price=price_now,
                            vwap=sig['vwap'], lot=lot, entry_time=now.strftime("%H:%M"),
                            rank=sig['rank'], pct_change=sig['pct_change'],
                        )
                        logger.info(f"  ✓ Confirmed entry & tracking: {sym} {direction} "
                                    f"SL={sl_price:.2f} lot={lot} "
                                    f"trades_today={self.trade_count[sym]}")
                        _redis_publish({
                            "type": "LOT", "symbol": sym, "direction": direction,
                            "lot": lot, "sl": sl_price, "ts": time.time(),
                        })
                    else:
                        logger.error(f"Failed to send confirmed entry alert for {sym}")
                else:
                    logger.info(f"CONFIRM REJECTED (T+{CONFIRM_OFFSET}): {sym} "
                                f"confirmed={confirmed} price={price_now:.2f} vwap={sig['vwap']:.2f}")
            else:
                logger.info(f"CONFIRM SKIPPED: {sym} — no latest quote available")

            del self.pending_signals[sym]  # always remove after one-shot check

        # ── Top movers ────────────────────────────────────────────────────────
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
            # Skip if already at max trades, in pending, or in an active trade
            if self.trade_count.get(symbol, 0) >= MAX_TRADES_PER_STOCK:
                continue
            if symbol in self.pending_signals:
                continue
            if symbol in self.active_trades:
                continue
            # 15-minute cooldown between signals on the same stock
            if now < self.cooldown_until.get(symbol, datetime.min):
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

            # ── Volume filter: C-1 ≥ 1.5× avg AND C-2 < 1.0× avg ─────────
            vol_ok, c1_ratio, c2_ratio = self._check_volume_filter(candles)
            if not vol_ok:
                logger.debug(
                    f"  VOL FILTER rejected {symbol}: C-1={c1_ratio:.2f}× C-2={c2_ratio:.2f}× "
                    f"(need C-1≥{VOLUME_C1_MIN_RATIO} AND C-2<{VOLUME_C2_MAX_RATIO})"
                )
                continue

            logger.info(
                f"VWAP TOUCH (queued T+{CONFIRM_OFFSET}): {symbol} #{rank} | "
                f"{pct_change:+.2f}% | {direction} | "
                f"price={price:.2f} vwap={vwap:.2f} dist={dist_pct:.3f}% | "
                f"vol C-1={c1_ratio:.2f}× C-2={c2_ratio:.2f}×"
            )

            # Queue signal — enter only after T+CONFIRM_OFFSET confirmation
            self.pending_signals[symbol] = {
                'vwap':         vwap,
                'direction':    direction,
                'rank':         rank,
                'pct_change':   pct_change,
                'candle_count': len(candles),
                'elapsed':      0,
                'c1_ratio':     c1_ratio,
                'c2_ratio':     c2_ratio,
            }
            self.cooldown_until[symbol] = now + timedelta(minutes=ALERT_COOLDOWN_MINUTES)

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
                # Still try to send EOD summary even after market closes
                # (handles the race where market closes at exactly 15:25)
                self._maybe_send_eod_summary()
                logger.info("Market closed — sleeping 60s")
                time.sleep(60)
                continue

            cycle_start = time.time()
            try:
                self._run_cycle()
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)
                self.notifier.send_debug(
                    f"❌ <b>Cycle Error</b>\n"
                    f"{datetime.now().strftime('%I:%M %p')}\n"
                    f"<code>{type(e).__name__}: {e}</code>"
                )

            elapsed    = time.time() - cycle_start
            sleep_time = max(0, LOOP_INTERVAL_SECONDS - elapsed)
            logger.debug(f"Cycle took {elapsed:.1f}s, sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)


def main():
    monitor = VWAPMoverMonitor()
    try:
        monitor.run()
    except KeyboardInterrupt:
        logger.info("Shutting down (KeyboardInterrupt)")
        monitor.notifier.send_debug(
            f"🛑 <b>VWAP Monitor Stopped</b>\n"
            f"{datetime.now().strftime('%Y-%m-%d %I:%M %p')}\n"
            f"Trades today: {len(monitor.day_trade_log)}"
        )
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        monitor.notifier.send_debug(
            f"💀 <b>VWAP Monitor CRASHED</b>\n"
            f"{datetime.now().strftime('%Y-%m-%d %I:%M %p')}\n"
            f"<code>{type(e).__name__}: {e}</code>\n"
            f"Restart required."
        )
        raise


if __name__ == "__main__":
    main()
