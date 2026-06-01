#!/usr/bin/env python3
"""
Gap-and-Go Opening Range Breakout (ORB) Monitor
================================================
Runs 9:00 AM - 11:05 AM IST daily.

Strategy:
  1. Pre-market: identify stocks with gap > GAP_MIN_PCT from prev close
  2. 9:15-9:24: record opening range (ORH/ORL = max/min price)
  3. 9:25-10:59: enter on first candle close outside range in gap direction
     — with volume confirmation (breakout candle vol delta > VOL_MIN_RATIO × OR avg)
  4. Stop: ORL (LONG) or ORH (SHORT); range-too-wide filter (> MAX_RANGE_PCT)
  5. Trailing SL activates only after 1R move (then trails at TRAILING_SL_PCT from peak)
  6. Hard exit: 11:00 AM for all open positions
  7. EOD summary sent at 11:05 AM

Reads from data/central_quotes.db — no live Kite API calls.
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from kiteconnect import KiteConnect

import config
from central_quote_db import get_central_db_reader
from market_utils import is_trading_day
from telegram_notifiers.base_notifier import BaseNotifier

# ── Parameters ────────────────────────────────────────────────────────────────
GAP_MIN_PCT     = 2.0     # minimum gap % from prev close to qualify
VOL_MIN_RATIO   = 1.5     # entry candle vol delta >= X × avg OR-window delta
MAX_RANGE_PCT   = 2.5     # skip if (ORH-ORL)/ORL > X% (too volatile / wide stop)
MAX_RISK_PCT    = 0.75    # cap stop distance at 0.75% of entry (tightens wide ORL/ORH stops)
MAX_RISK_RS     = 5000    # skip trade if risk (rupees per lot) exceeds this
TRAILING_SL_PCT = 0.5     # trailing SL % from peak/trough (activates after 1R)

ORB_START_TIME  = "09:15"
ORB_END_TIME    = "09:25"   # opening range ends; entry window starts
ORB_MINUTES     = 10        # duration of the opening range window
ENTRY_END_TIME  = "11:00"   # no new entries after this
EXIT_TIME       = "11:00"   # hard exit for all open positions
SUMMARY_TIME    = "11:05"   # EOD summary telegram message

LOOP_INTERVAL   = 30        # seconds between each check loop

LOT_SIZES_FILE  = "data/lot_sizes.json"

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs('logs', exist_ok=True)
today_str = datetime.now().strftime('%Y%m%d')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/gap_orb_monitor_{today_str}.log'),
    ]
)
logger = logging.getLogger(__name__)


# ── Data class for active trade ───────────────────────────────────────────────
@dataclass
class OrbTrade:
    symbol:      str
    direction:   str        # "LONG" or "SHORT"
    gap_pct:     float
    entry_price: float
    entry_time:  str
    lot:         int
    orh:         float      # opening range high
    orl:         float      # opening range low
    init_sl:     float      # ORL (LONG) or ORH (SHORT)
    activation:  float      # price at which TSL activates (1R from entry)
    current_sl:  float      # current stop (starts at init_sl, ratchets with TSL)
    peak:        float = 0.0   # peak/trough for trailing
    trough:      float = 0.0

    def __post_init__(self):
        self.peak   = self.entry_price
        self.trough = self.entry_price

    def update(self, price: float):
        """Update trailing stop. TSL only activates after 1R move."""
        if self.direction == "LONG":
            if price > self.peak:
                self.peak = price
            if price >= self.activation:
                trail_sl = self.peak * (1 - TRAILING_SL_PCT / 100)
                self.current_sl = max(self.current_sl, trail_sl)
        else:
            if price < self.trough:
                self.trough = price
            if price <= self.activation:
                trail_sl = self.trough * (1 + TRAILING_SL_PCT / 100)
                self.current_sl = min(self.current_sl, trail_sl)

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


# ── Main Monitor ──────────────────────────────────────────────────────────────
class GapOrbMonitor:

    def __init__(self):
        logger.info("=" * 70)
        logger.info("GAP-AND-GO ORB MONITOR — Initializing")
        logger.info("=" * 70)

        self.db       = get_central_db_reader()
        self.notifier = BaseNotifier()
        self.lot_sizes: Dict[str, int] = self._load_lot_sizes()
        self.fo_symbols: List[str]     = self._load_fo_symbols()

        # Day state
        self.today          = datetime.now().strftime('%Y-%m-%d')
        self.prev_close:    Dict[str, float] = {}
        self.gap_stocks:    Dict[str, float] = {}   # sym → gap_pct (loaded after prev_close ready)
        self.or_high:       Dict[str, float] = {}   # sym → ORH
        self.or_low:        Dict[str, float] = {}   # sym → ORL
        self.or_volumes:    Dict[str, List]  = {}   # sym → list of vol deltas during OR window
        self.or_finalized   = False                 # True after 9:25 AM
        self.entered:       Dict[str, bool]  = {}   # sym → traded today (1 trade/stock)
        self.last_entry_ts: Dict[str, str]   = {}   # sym → last candle timestamp checked for entry
        self.active_trades: Dict[str, OrbTrade] = {}
        self.day_log:       List[Dict] = []
        self.summary_sent   = False

        self.notifier.send_debug(
            f"🚀 <b>Gap ORB Monitor Started</b>\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %I:%M %p')}\n"
            f"Gap ≥ {GAP_MIN_PCT}% | ORB {ORB_MINUTES}min | TSL {TRAILING_SL_PCT}%\n"
            f"Entry window: {ORB_END_TIME} – {ENTRY_END_TIME} | Exit: {EXIT_TIME}\n"
            f"Symbols tracked: {len(self.fo_symbols)}"
        )

    def _load_lot_sizes(self) -> Dict[str, int]:
        try:
            with open(LOT_SIZES_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load lot sizes ({e}) — defaulting to 1")
            return {}

    def _load_fo_symbols(self) -> List[str]:
        try:
            with open(config.STOCK_LIST_FILE) as f:
                return json.load(f)['stocks']
        except Exception as e:
            logger.error(f"Cannot load fo_stocks.json: {e}")
            sys.exit(1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _hm(self) -> str:
        """Current time as 'HH:MM'."""
        return datetime.now().strftime('%H:%M')

    def _fetch_prev_close_from_kite(self) -> Dict[str, float]:
        """
        Fetch previous day close prices directly from Kite API.

        Uses kite.quote() → ohlc.close, which is the NSE official previous
        day close. Called once at startup; does not depend on the DB being
        populated by central_data_collector.

        Returns {symbol: prev_close} for all successfully fetched symbols.
        """
        kite = KiteConnect(api_key=config.KITE_API_KEY)
        kite.set_access_token(config.KITE_ACCESS_TOKEN)

        instruments = [f"NSE:{sym}" for sym in self.fo_symbols]
        batch_size  = 200
        result: Dict[str, float] = {}

        for i in range(0, len(instruments), batch_size):
            batch = instruments[i:i + batch_size]
            for attempt in range(config.MAX_RETRIES):
                try:
                    quotes = kite.quote(*batch)
                    for instr, q in quotes.items():
                        sym   = instr.replace("NSE:", "")
                        close = q.get("ohlc", {}).get("close")
                        if close:
                            result[sym] = float(close)
                    break
                except Exception as e:
                    wait = config.RETRY_DELAY_SECONDS * (2 ** attempt)
                    logger.warning(f"Kite quote batch {i//batch_size+1} attempt {attempt+1} failed: {e} — retry in {wait:.0f}s")
                    time.sleep(wait)
            # Rate limit between batches
            if i + batch_size < len(instruments):
                time.sleep(config.REQUEST_DELAY_SECONDS)

        logger.info(f"Fetched prev_close from Kite API for {len(result)}/{len(self.fo_symbols)} symbols")
        return result

    def _get_today_candles(self, symbol: str) -> List[Dict]:
        """Fetch today's 1-min candles from 9:15 AM onwards."""
        cur = self.db.conn.cursor()
        ts_start = f"{self.today} {ORB_START_TIME}:00"
        cur.execute("""
            SELECT timestamp, price, volume FROM stock_quotes
            WHERE symbol = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (symbol, ts_start))
        return [{'timestamp': r[0], 'price': float(r[1]), 'volume': float(r[2] or 0)}
                for r in cur.fetchall()]

    def _vol_delta(self, candles: List[Dict], idx: int) -> float:
        if idx == 0:
            return float(candles[0]['volume'])
        return max(0.0, candles[idx]['volume'] - candles[idx - 1]['volume'])

    # ── Opening Range Computation ─────────────────────────────────────────────

    def _finalize_opening_ranges(self):
        """
        Called once at ORB_END_TIME (9:25 AM).
        Compute ORH/ORL for all gap stocks; apply range-too-wide filter.
        """
        # Identify gap stocks
        self.gap_stocks = {}
        ts_start = f"{self.today} {ORB_START_TIME}:00"
        ts_end   = f"{self.today} {ORB_END_TIME}:00"

        cur = self.db.conn.cursor()
        # Get earliest price today for each symbol (approximation for open price)
        cur.execute("""
            SELECT symbol, MIN(timestamp), price
            FROM stock_quotes
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY symbol
        """, (ts_start, ts_end))
        open_prices = {}
        for row in cur.fetchall():
            open_prices[row[0]] = float(row[2])

        for sym, pc in self.prev_close.items():
            if pc <= 0 or sym not in open_prices:
                continue
            op = open_prices[sym]
            gap_pct = (op - pc) / pc * 100.0
            if abs(gap_pct) >= GAP_MIN_PCT:
                self.gap_stocks[sym] = gap_pct

        logger.info(f"Gap qualifiers (gap≥{GAP_MIN_PCT}%): {len(self.gap_stocks)}")

        # Compute ORH/ORL for gap stocks
        if not self.gap_stocks:
            self.or_finalized = True
            return

        sym_list = list(self.gap_stocks.keys())
        ph = ','.join('?' * len(sym_list))
        cur.execute(f"""
            SELECT symbol, MAX(price) as orh, MIN(price) as orl, COUNT(*) as n_candles
            FROM stock_quotes
            WHERE symbol IN ({ph}) AND timestamp >= ? AND timestamp < ?
            GROUP BY symbol
        """, sym_list + [ts_start, ts_end])

        rows = cur.fetchall()
        valid = 0
        skipped_wide = 0
        for row in rows:
            sym, orh, orl, n = row[0], float(row[1]), float(row[2]), row[3]
            if n < 2:   # need at least 2 data points
                continue
            range_pct = (orh - orl) / orl * 100.0 if orl > 0 else 99
            if range_pct > MAX_RANGE_PCT:
                logger.info(f"  SKIP {sym}: range {range_pct:.1f}% > {MAX_RANGE_PCT}% max")
                skipped_wide += 1
                continue
            self.or_high[sym] = orh
            self.or_low[sym]  = orl
            valid += 1

        # Load average OR volume delta for each qualifying symbol
        for sym in list(self.or_high.keys()):
            candles = self._get_today_candles(sym)
            or_candles = [c for c in candles if c['timestamp'][11:16] < ORB_END_TIME]
            if or_candles:
                deltas = [self._vol_delta(or_candles, i) for i in range(len(or_candles))]
                self.or_volumes[sym] = deltas
            else:
                del self.or_high[sym]
                del self.or_low[sym]

        logger.info(
            f"Opening ranges computed: {valid} valid, {skipped_wide} skipped (wide range)"
        )
        self.or_finalized = True

    # ── Entry Check ───────────────────────────────────────────────────────────

    def _check_entries(self):
        """Check for breakout entries on all qualifying symbols."""
        now_hm = self._hm()
        if now_hm >= ENTRY_END_TIME:
            return

        for sym in list(self.or_high.keys()):
            if sym in self.entered:
                continue
            gap_pct   = self.gap_stocks.get(sym, 0)
            direction = "LONG" if gap_pct > 0 else "SHORT"
            orh       = self.or_high[sym]
            orl       = self.or_low[sym]
            init_sl   = orl if direction == "LONG" else orh

            # Full candle list from 9:15 (needed for vol_delta index)
            candles = self._get_today_candles(sym)

            # Only new post-OR candles since the last poll for this symbol
            last_ts = self.last_entry_ts.get(sym, "")
            new_candles = [
                (i, c) for i, c in enumerate(candles)
                if c['timestamp'][11:16] >= ORB_END_TIME
                and c['timestamp'][11:16] < ENTRY_END_TIME
                and c['timestamp'] > last_ts
            ]
            if not new_candles:
                continue

            # Advance the pointer so next poll skips these candles
            self.last_entry_ts[sym] = new_candles[-1][1]['timestamp']

            # Average OR window volume delta
            or_vols    = self.or_volumes.get(sym, [])
            avg_or_vol = sum(or_vols) / len(or_vols) if or_vols else 0.0

            # Scan new candles in chronological order — enter on first qualifying breakout
            for idx, candle in new_candles:
                price = candle['price']

                # Breakout check: price must be outside range in gap direction
                if direction == "LONG"  and price <= orh:
                    continue
                if direction == "SHORT" and price >= orl:
                    continue

                # Volume confirmation
                delta = self._vol_delta(candles, idx)
                if avg_or_vol > 0 and delta < VOL_MIN_RATIO * avg_or_vol:
                    logger.debug(f"  {sym}: vol fail {delta:.0f} < {VOL_MIN_RATIO * avg_or_vol:.0f}")
                    continue

                # Apply max-risk cap: tighten stop if ORL/ORH is too far
                trade_sl = init_sl
                if MAX_RISK_PCT > 0:
                    if direction == "LONG":
                        capped   = price * (1 - MAX_RISK_PCT / 100)
                        trade_sl = max(init_sl, capped)   # higher = tighter for LONG
                    else:
                        capped   = price * (1 + MAX_RISK_PCT / 100)
                        trade_sl = min(init_sl, capped)   # lower = tighter for SHORT

                # Rupee risk filter: skip if 1 lot risks more than MAX_RISK_RS
                lot      = self.lot_sizes.get(sym, 1)
                risk_rs  = abs(price - trade_sl) * lot
                if risk_rs > MAX_RISK_RS:
                    logger.debug(f"  {sym}: rupee risk ₹{risk_rs:,.0f} > ₹{MAX_RISK_RS:,} — skipped")
                    continue

                # Enter trade
                risk       = abs(price - trade_sl)
                activation = price + risk if direction == "LONG" else price - risk

                trade = OrbTrade(
                    symbol      = sym,
                    direction   = direction,
                    gap_pct     = round(gap_pct, 2),
                    entry_price = round(price, 2),
                    entry_time  = candle['timestamp'][11:16],
                    lot         = lot,
                    orh         = round(orh, 2),
                    orl         = round(orl, 2),
                    init_sl     = round(trade_sl, 2),
                    activation  = round(activation, 2),
                    current_sl  = round(trade_sl, 2),
                )
                self.active_trades[sym] = trade
                self.entered[sym]       = True

                arrow   = "🟢" if direction == "LONG" else "🔴"
                sl_pct  = abs(price - trade_sl) / price * 100
                t1      = round(price + 2 * risk, 2) if direction == "LONG" else round(price - 2 * risk, 2)
                vol_str = f"{delta/avg_or_vol:.1f}x" if avg_or_vol > 0 else "no baseline"

                msg = (
                    f"{arrow} <b>GAP ORB {direction}</b> — {sym}\n"
                    f"Gap: {gap_pct:+.1f}% | OR: {orl:.1f}–{orh:.1f}\n"
                    f"Entry: <b>₹{price:.1f}</b> @{candle['timestamp'][11:16]}\n"
                    f"SL: ₹{trade_sl:.1f} ({sl_pct:.1f}% risk)\n"
                    f"T1 (2R): ₹{t1:.1f} | Lot: {lot}\n"
                    f"Vol conf: {delta:.0f} vs avg {avg_or_vol:.0f} ({vol_str})\n"
                    f"<i>via SI·Gap-ORB</i>"
                )
                self.notifier.send_debug(msg)
                logger.info(f"ENTERED {direction} {sym}: entry={price} SL={trade_sl} lot={lot}")
                break  # one trade per stock

    # ── Active Trade Tracking ─────────────────────────────────────────────────

    def _track_active_trades(self):
        """Update TSL for active trades; close if stopped out."""
        # Get latest prices for all active symbols
        syms = list(self.active_trades.keys())
        if not syms:
            return

        quotes = self.db.get_latest_stock_quotes(syms)

        for sym in list(self.active_trades.keys()):
            trade = self.active_trades[sym]
            q = quotes.get(sym)
            if not q:
                continue
            price = float(q['price'])
            trade.update(price)

            if trade.is_stopped(price):
                pnl = trade.pnl(price)
                self._record_exit(trade, price, "TSL", pnl)
                del self.active_trades[sym]

    def _close_all_eod(self):
        """Force-exit all open positions at EOD (11:00 AM)."""
        if not self.active_trades:
            return
        syms   = list(self.active_trades.keys())
        quotes = self.db.get_latest_stock_quotes(syms)
        for sym in list(self.active_trades.keys()):
            trade  = self.active_trades[sym]
            q      = quotes.get(sym)
            if q:
                price = float(q['price'])
            else:
                logger.warning(f"EOD exit: no quote for {sym}, using entry price (P&L will be ₹0)")
                price = trade.entry_price
            pnl = trade.pnl(price)
            self._record_exit(trade, price, "EOD", pnl)
        self.active_trades.clear()

    def _record_exit(self, trade: OrbTrade, exit_price: float, reason: str, pnl: float):
        """Record exit, log, and send Telegram alert."""
        now_hm = datetime.now().strftime('%H:%M')
        flag   = "✅" if pnl > 0 else "❌"
        arrow  = "🟢" if trade.direction == "LONG" else "🔴"

        msg = (
            f"{flag} <b>ORB EXIT [{reason}]</b> {arrow} {trade.symbol}\n"
            f"Direction: {trade.direction} | Gap: {trade.gap_pct:+.1f}%\n"
            f"Entry: ₹{trade.entry_price:.1f} @{trade.entry_time} → "
            f"Exit: ₹{exit_price:.1f} @{now_hm}\n"
            f"P&L: <b>₹{pnl:,.0f}</b> | Lot: {trade.lot}\n"
            f"<i>via SI·Gap-ORB</i>"
        )
        self.notifier.send_debug(msg)
        logger.info(
            f"EXIT {trade.direction} {trade.symbol}: "
            f"entry={trade.entry_price} exit={exit_price:.2f} [{reason}] PnL=₹{pnl:,.0f}"
        )

        self.day_log.append({
            'symbol':    trade.symbol,
            'direction': trade.direction,
            'gap_pct':   trade.gap_pct,
            'entry':     trade.entry_price,
            'exit':      round(exit_price, 2),
            'reason':    reason,
            'pnl':       round(pnl, 2),
            'lot':       trade.lot,
        })

    # ── EOD Summary ───────────────────────────────────────────────────────────

    def _send_eod_summary(self):
        if self.summary_sent:
            return
        self.summary_sent = True

        if not self.day_log:
            self.notifier.send_debug(
                f"📊 <b>Gap ORB Daily Summary — {self.today}</b>\n"
                f"No trades taken today."
            )
            logger.info("EOD summary: no trades taken today.")
            return

        total  = sum(t['pnl'] for t in self.day_log)
        wins   = sum(1 for t in self.day_log if t['pnl'] > 0)
        losses = len(self.day_log) - wins

        lines = [
            f"📊 <b>Gap ORB Daily Summary — {self.today}</b>",
            f"Setup: Gap-and-Go ORB | Gap≥{GAP_MIN_PCT}% | OR 9:15–9:24 | "
            f"Vol≥{VOL_MIN_RATIO}x | MaxRisk {MAX_RISK_PCT}%/₹{MAX_RISK_RS:,} | TSL {TRAILING_SL_PCT}% | Exit {EXIT_TIME}",
            f"Trades: {len(self.day_log)} | W: {wins} L: {losses} | "
            f"Win%: {100*wins/len(self.day_log):.0f}%",
            f"Total P&L: <b>₹{total:,.0f}</b>",
            "",
        ]
        for t in sorted(self.day_log, key=lambda x: x['pnl'], reverse=True):
            flag = "✅" if t['pnl'] > 0 else "❌"
            lines.append(
                f"  {flag} {t['symbol']} {t['direction']} "
                f"gap={t['gap_pct']:+.1f}% P&L=₹{t['pnl']:,.0f} [{t['reason']}]"
            )

        self.notifier.send_debug('\n'.join(lines))
        logger.info(f"EOD summary sent. Total P&L: ₹{total:,.0f}")

    # ── Main Loop ─────────────────────────────────────────────────────────────

    def run(self):
        logger.info("Starting Gap ORB monitor loop")
        if not is_trading_day():
            msg = f"🗓️ Gap ORB: Today ({self.today}) is not a trading day — exiting."
            logger.info(msg)
            self.notifier.send_debug(msg)
            return

        logger.info("Fetching prev_close directly from Kite API...")
        self.prev_close = self._fetch_prev_close_from_kite()
        if not self.prev_close:
            self.notifier.send_debug("❌ Gap ORB: Kite API prev_close fetch failed at startup. Exiting.")
            logger.error("Could not fetch prev_close from Kite. Exiting.")
            sys.exit(1)
        logger.info(f"prev_close ready: {len(self.prev_close)} symbols")

        while True:
            now    = datetime.now()
            now_hm = now.strftime('%H:%M')

            # Shut down after summary time
            if now_hm >= "11:10":
                logger.info("Market window closed. Exiting.")
                break

            # Send EOD summary (close any remaining positions first)
            if now_hm >= SUMMARY_TIME and not self.summary_sent:
                self._close_all_eod()
                self._send_eod_summary()

            # Finalize opening range once at 9:25 AM
            if not self.or_finalized and now_hm >= ORB_END_TIME:
                logger.info("Finalizing opening ranges at 9:25 AM")
                self._finalize_opening_ranges()

                if self.gap_stocks:
                    count = len(self.or_high)
                    logger.info(f"Gap stocks with valid OR: {count}")
                    self.notifier.send_debug(
                        f"📐 <b>ORB Initialized</b>\n"
                        f"Gap ≥{GAP_MIN_PCT}% stocks: {len(self.gap_stocks)} | "
                        f"Valid ORs: {count}\n"
                        f"Looking for breakouts until {ENTRY_END_TIME}"
                    )
                else:
                    logger.info("No gap stocks today. Monitor will idle.")
                    self.notifier.send_debug(
                        f"ℹ️ Gap ORB: No stocks with gap ≥ {GAP_MIN_PCT}% today."
                    )

            # Check entries and track trades
            if now_hm >= ORB_END_TIME and now_hm < EXIT_TIME:
                self._check_entries()
                self._track_active_trades()

            # Force-exit at exit time
            if now_hm >= EXIT_TIME and self.active_trades:
                self._close_all_eod()

            time.sleep(LOOP_INTERVAL)


def main():
    monitor = GapOrbMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
