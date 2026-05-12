#!/usr/bin/env python3
"""
VWAP Win-Rate Optimizer
========================
Goal: push win rate from ~42% → 70%+ through systematic filter search.

Phase 1 — Individual filter impact (each filter tested alone vs baseline)
Phase 2 — Combination grid search (top Phase-1 filters combined)
Phase 3 — Best combo deep-dive (day-by-day, per-symbol)

Filters tested:
  min_pct      — min |%change| from prev close: 0, 0.5, 1.0, 1.5, 2.0, 3.0
  top_n        — top N movers: 10, 20
  touch_pct    — VWAP touch threshold %: 0.15, 0.10, 0.08
  c1_min       — vol spike ratio: 1.5, 2.0, 2.5
  confirm      — candles to wait before entry: 0 (at touch), 2, 3
  approach     — min consecutive approach candles: 0, 3, 5
  nifty_bars   — skip if last N Nifty moves ALL against direction: 0 (off), 2, 3
  entry_start  — earliest entry time: "10:00", "10:30", "11:00"
  entry_end    — latest entry time: "14:30", "13:30", "13:00"

Baseline: top_n=10, min_pct=0, touch=0.15, c1≥1.5, confirm=0, approach=0,
          nifty=off, window=10:00-14:30, TSL=0.5%

Window: 10:00–14:30 | TSL 0.5% | Last 30 trading days
"""

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import product
from typing import Dict, List, Optional, Tuple

# ── Backtest parameters ───────────────────────────────────────────────────────
TRAILING_SL_PCT          = 0.50
MAX_TRADES_PER_STOCK     = 2
ALERT_COOLDOWN_MINUTES   = 15
LAST_N_DAYS              = 30
DB_PATH                  = "data/central_quotes.db"
LOT_SIZES_FILE           = "data/lot_sizes.json"

# Target
WIN_RATE_TARGET  = 70.0
AVG_TRADE_TARGET = 1500   # ₹ net per trade (objective for max-avg-profit mode)
MIN_TRADES_MONTH = 15     # minimum trades/month to be worth running live

# ── Phase 1: single-filter sweep ─────────────────────────────────────────────
PHASE1_CONFIGS = {
    # label: (top_n, min_pct, touch_pct, c1_min, confirm, approach, nifty_bars,
    #          entry_start, entry_end)
    "Baseline":            (10, 0.0, 0.15, 1.5, 0, 0, 0, "10:00", "14:30"),
    # top_n
    "top_n=20":            (20, 0.0, 0.15, 1.5, 0, 0, 0, "10:00", "14:30"),
    # min_pct
    "min_pct=0.5":         (10, 0.5, 0.15, 1.5, 0, 0, 0, "10:00", "14:30"),
    "min_pct=1.0":         (10, 1.0, 0.15, 1.5, 0, 0, 0, "10:00", "14:30"),
    "min_pct=1.5":         (10, 1.5, 0.15, 1.5, 0, 0, 0, "10:00", "14:30"),
    "min_pct=2.0":         (10, 2.0, 0.15, 1.5, 0, 0, 0, "10:00", "14:30"),
    "min_pct=3.0":         (10, 3.0, 0.15, 1.5, 0, 0, 0, "10:00", "14:30"),
    # touch threshold
    "touch=0.10":          (10, 0.0, 0.10, 1.5, 0, 0, 0, "10:00", "14:30"),
    "touch=0.08":          (10, 0.0, 0.08, 1.5, 0, 0, 0, "10:00", "14:30"),
    # c1_min
    "c1=2.0":              (10, 0.0, 0.15, 2.0, 0, 0, 0, "10:00", "14:30"),
    "c1=2.5":              (10, 0.0, 0.15, 2.5, 0, 0, 0, "10:00", "14:30"),
    # confirmation delay
    "confirm=2":           (10, 0.0, 0.15, 1.5, 2, 0, 0, "10:00", "14:30"),
    "confirm=3":           (10, 0.0, 0.15, 1.5, 3, 0, 0, "10:00", "14:30"),
    # approach candles
    "approach=3":          (10, 0.0, 0.15, 1.5, 0, 3, 0, "10:00", "14:30"),
    "approach=5":          (10, 0.0, 0.15, 1.5, 0, 5, 0, "10:00", "14:30"),
    # nifty direction
    "nifty=2":             (10, 0.0, 0.15, 1.5, 0, 0, 2, "10:00", "14:30"),
    "nifty=3":             (10, 0.0, 0.15, 1.5, 0, 0, 3, "10:00", "14:30"),
    # time windows
    "start=10:30":         (10, 0.0, 0.15, 1.5, 0, 0, 0, "10:30", "14:30"),
    "start=11:00":         (10, 0.0, 0.15, 1.5, 0, 0, 0, "11:00", "14:30"),
    "end=13:30":           (10, 0.0, 0.15, 1.5, 0, 0, 0, "10:00", "13:30"),
    "end=13:00":           (10, 0.0, 0.15, 1.5, 0, 0, 0, "10:00", "13:00"),
    "window=10:30-13:30":  (10, 0.0, 0.15, 1.5, 0, 0, 0, "10:30", "13:30"),
    "window=10:30-13:00":  (10, 0.0, 0.15, 1.5, 0, 0, 0, "10:30", "13:00"),
}

# ── Phase 2: combinations of top single filters ───────────────────────────────
# top_n, min_pct, touch_pct, c1_min, confirm, approach, nifty_bars, start, end
PHASE2_SWEEP = {
    "top_n":      [10, 20],
    "min_pct":    [0.0, 1.0, 2.0],
    "touch_pct":  [0.15, 0.10],
    "c1_min":     [1.5, 2.0],
    "confirm":    [0, 3],           # confirm=3 > confirm=2 from Phase 1
    "approach":   [0, 3],
    "nifty_bars": [0, 3],           # nifty=3 had good avg/trade
    "start":      ["10:00", "10:30"],
    "end":        ["14:30", "13:30", "13:00"],  # end=13:00 best avg/trade in Phase 1
}
# ─────────────────────────────────────────────────────────────────────────────


def load_lot_sizes():
    try:
        with open(LOT_SIZES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def compute_charges(entry, exit_p, lot, direction):
    buy   = entry  if direction == "LONG" else exit_p
    sell  = exit_p if direction == "LONG" else entry
    buy_t, sell_t = buy * lot, sell * lot
    total = buy_t + sell_t
    brok  = 40.0
    stt   = sell_t * 0.0002
    exc   = total  * 0.0000188
    sebi  = total  * 0.000001
    stamp = buy_t  * 0.00002
    gst   = (brok + exc) * 0.18
    return brok + stt + exc + sebi + stamp + gst


def compute_vwap(candles):
    if len(candles) < 2:
        return None
    cum_pv = cum_vol = 0.0
    for i, c in enumerate(candles):
        vd = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv += c['price'] * vd
        cum_vol += vd
    return cum_pv / cum_vol if cum_vol > 0 else None


def get_price_at(candles, ts):
    v = [c for c in candles if c['timestamp'] <= ts]
    return v[-1]['price'] if v else None


def c1_ratio(candles):
    if len(candles) < 3:
        return 0.0
    deltas = [float(c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume']))
              for i, c in enumerate(candles)]
    baseline = deltas[:-2]
    avg = sum(baseline) / len(baseline) if baseline else 0
    return deltas[-1] / avg if avg > 0 else 0.0


def approach_count(candles, direction):
    """Consecutive candles approaching VWAP before touch."""
    if len(candles) < 2:
        return 99
    prices = [c['price'] for c in candles]
    count = 0
    if direction == "LONG":      # price was falling toward VWAP
        for i in range(len(prices) - 1, 0, -1):
            if prices[i] < prices[i-1]:
                count += 1
            else:
                break
    else:                        # price was rising toward VWAP
        for i in range(len(prices) - 1, 0, -1):
            if prices[i] > prices[i-1]:
                count += 1
            else:
                break
    return count


def nifty_ok(nifty_visible, direction, lookback):
    """False if ALL last `lookback` Nifty moves are against direction."""
    if lookback == 0 or len(nifty_visible) < lookback + 1:
        return True
    recent = [c['price'] for c in nifty_visible[-(lookback + 1):]]
    if direction == "LONG":
        return not all(recent[i] < recent[i-1] for i in range(1, len(recent)))
    return not all(recent[i] > recent[i-1] for i in range(1, len(recent)))


def get_exit_tsl(candles, entry_ts, entry_price, direction, exit_ts):
    sl = (entry_price * (1 - TRAILING_SL_PCT / 100) if direction == "LONG"
          else entry_price * (1 + TRAILING_SL_PCT / 100))
    peak = trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak: peak = p
            sl = peak * (1 - TRAILING_SL_PCT / 100)
            if p <= sl: return sl, "TSL"
        else:
            if p < trough: trough = p
            sl = trough * (1 + TRAILING_SL_PCT / 100)
            if p >= sl: return sl, "TSL"
    return get_price_at(candles, exit_ts), "EOD"


def run_day(date, prev_close, all_candles, nifty_candles, timestamps, lot_sizes,
            top_n, min_pct, touch_pct, c1_min, confirm, approach_min,
            nifty_bars, entry_start, entry_end):

    alert_start  = f"{date} {entry_start}:00"
    entry_end_ts = f"{date} {entry_end}:00"
    exit_ts      = f"{date} 14:30:00"

    cooldown    = {}
    trade_count = defaultdict(int)
    pending     = {}
    trades      = []

    # Pre-sort candle lists once; build running cursor per symbol
    sorted_cl    = {sym: sorted(cl, key=lambda c: c['timestamp'])
                    for sym, cl in all_candles.items()}
    sym_cursor   = {sym: 0 for sym in sorted_cl}
    candle_hist  = {sym: [] for sym in sorted_cl}  # cumulative candles seen so far
    latest_price = {}  # sym → latest price

    nifty_sorted = sorted(nifty_candles, key=lambda c: c['timestamp'])
    nifty_cursor = 0
    nifty_hist   = []

    # Lookup: ts → price per symbol for fast pending confirmation
    price_at_ts = {}  # (sym, ts_str) → price

    for ts_str in timestamps:
        if ts_str > exit_ts:
            break
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

        # ── Advance cursors for all symbols ──────────────────────────────────
        for sym, cl in sorted_cl.items():
            idx = sym_cursor[sym]
            while idx < len(cl) and cl[idx]['timestamp'] <= ts_str:
                candle_hist[sym].append(cl[idx])
                latest_price[sym] = cl[idx]['price']
                price_at_ts[(sym, cl[idx]['timestamp'])] = cl[idx]['price']
                idx += 1
            sym_cursor[sym] = idx

        while nifty_cursor < len(nifty_sorted) and nifty_sorted[nifty_cursor]['timestamp'] <= ts_str:
            nifty_hist.append(nifty_sorted[nifty_cursor])
            nifty_cursor += 1

        # ── Process pending T+confirm signals ────────────────────────────────
        for sym in list(pending.keys()):
            sig = pending[sym]
            sig['elapsed'] += 1
            if sig['elapsed'] < confirm:
                continue
            price_now = price_at_ts.get((sym, ts_str), 0)
            if price_now > 0:
                direction = sig['direction']
                confirmed = ((direction == "LONG"  and price_now > sig['vwap']) or
                             (direction == "SHORT" and price_now < sig['vwap']))
                if confirmed and trade_count[sym] < MAX_TRADES_PER_STOCK:
                    lot = lot_sizes.get(sym, 1)
                    ep, reason = get_exit_tsl(sorted_cl.get(sym, []),
                                              ts_str, price_now, direction, exit_ts)
                    if ep is not None:
                        pnl = (ep - price_now) if direction == "LONG" else (price_now - ep)
                        gross = pnl * lot
                        chg   = compute_charges(price_now, ep, lot, direction)
                        trades.append({'date': date, 'symbol': sym,
                                       'dir': direction, 'lot': lot,
                                       'entry': price_now, 'exit': ep,
                                       'reason': reason,
                                       'gross': gross, 'net': gross - chg})
                        trade_count[sym] += 1
                        cooldown[sym] = ts
            del pending[sym]

        if ts_str < alert_start or ts_str > entry_end_ts:
            continue

        # ── Build snapshot using pre-maintained running state ─────────────────
        movers = []
        for sym, price in latest_price.items():
            pc = prev_close.get(sym, 0)
            if pc <= 0: continue
            pct = (price - pc) / pc * 100
            movers.append((sym, pct, price))
        movers.sort(key=lambda x: abs(x[1]), reverse=True)

        for rank, (symbol, pct_change, price) in enumerate(movers[:top_n], 1):
            if trade_count[symbol] >= MAX_TRADES_PER_STOCK:
                continue
            if symbol in pending:
                continue
            if symbol in cooldown and (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                continue

            if abs(pct_change) < min_pct:
                continue

            csf = candle_hist[symbol]  # cumulative history — no re-scan needed
            vwap = compute_vwap(csf)
            if vwap is None:
                continue
            if abs(price - vwap) / vwap * 100 > touch_pct:
                continue

            direction = "LONG" if pct_change >= 0 else "SHORT"

            if c1_min > 0 and c1_ratio(csf) < c1_min:
                cooldown[symbol] = ts
                continue

            if approach_min > 0 and approach_count(csf, direction) < approach_min:
                cooldown[symbol] = ts
                continue

            if not nifty_ok(nifty_hist, direction, nifty_bars):
                cooldown[symbol] = ts
                continue

            cooldown[symbol] = ts

            if confirm == 0:
                lot = lot_sizes.get(symbol, 1)
                ep, reason = get_exit_tsl(sorted_cl.get(symbol, []),
                                          ts_str, price, direction, exit_ts)
                if ep is None:
                    trade_count[symbol] += 1
                    continue
                pnl   = (ep - price) if direction == "LONG" else (price - ep)
                gross = pnl * lot
                chg   = compute_charges(price, ep, lot, direction)
                trades.append({'date': date, 'symbol': symbol,
                               'dir': direction, 'lot': lot,
                               'entry': price, 'exit': ep,
                               'reason': reason,
                               'gross': gross, 'net': gross - chg})
                trade_count[symbol] += 1
            else:
                pending[symbol] = {'vwap': vwap, 'direction': direction, 'elapsed': 0}

    return trades


def summarise(trades, all_dates):
    if not trades:
        return {'n': 0, 'wr': 0.0, 'net': 0.0, 'avg': 0.0,
                'green': 0, 'red': 0, 'max_dd': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0}
    wins   = [t for t in trades if t['net'] > 0]
    losses = [t for t in trades if t['net'] <= 0]
    net    = sum(t['net'] for t in trades)

    day_nets = defaultdict(float)
    for t in trades:
        day_nets[t['date']] += t['net']
    green = sum(1 for v in day_nets.values() if v > 0)
    red   = sum(1 for v in day_nets.values() if v < 0)

    cum = pk = dd = 0.0
    for d in all_dates:
        cum += day_nets.get(d, 0)
        pk   = max(pk, cum)
        dd   = max(dd, pk - cum)

    return {
        'n':        len(trades),
        'wr':       len(wins) / len(trades) * 100,
        'net':      net,
        'avg':      net / len(trades),
        'green':    green,
        'red':      red,
        'max_dd':   dd,
        'avg_win':  sum(t['net'] for t in wins)   / len(wins)   if wins   else 0.0,
        'avg_loss': sum(t['net'] for t in losses) / len(losses) if losses else 0.0,
    }


def cfg_label(cfg):
    top_n, min_pct, touch_pct, c1_min, confirm, approach, nifty_bars, start, end = cfg
    parts = []
    if top_n != 10:        parts.append(f"top{top_n}")
    if min_pct > 0:        parts.append(f"pct≥{min_pct}")
    if touch_pct != 0.15:  parts.append(f"tch{touch_pct}")
    if c1_min != 1.5:      parts.append(f"C1≥{c1_min}")
    if confirm > 0:        parts.append(f"T+{confirm}")
    if approach > 0:       parts.append(f"app{approach}")
    if nifty_bars > 0:     parts.append(f"N{nifty_bars}")
    if start != "10:00":   parts.append(f">{start}")
    if end != "14:30":     parts.append(f"<{end}")
    return "+".join(parts) if parts else "Baseline"


def run():
    lot_sizes = load_lot_sizes()

    # ── Load all data in bulk (single pass per table) ─────────────────────────
    print("Loading data from DB (single pass)...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates_db = [r['d'] for r in cur.fetchall()]
    all_dates    = all_dates_db[-LAST_N_DAYS:]
    date_set     = set(all_dates)
    print(f"Dates: {all_dates[0]} → {all_dates[-1]}  ({len(all_dates)} days)")

    # Build prev_close: last price per symbol for each needed "prev day"
    # Need prev close for each backtest date = closing price of the prior trading day
    prev_days_needed = set()
    for date in all_dates:
        idx = all_dates_db.index(date)
        if idx > 0:
            prev_days_needed.add(all_dates_db[idx - 1])

    # Load last price per (symbol, date) for all needed prev days in one query
    if prev_days_needed:
        placeholders = ",".join("?" * len(prev_days_needed))
        cur.execute(f"""
            SELECT symbol, date(timestamp) as d, price FROM stock_quotes
            WHERE (symbol, timestamp) IN (
                SELECT symbol, MAX(timestamp) FROM stock_quotes
                WHERE date(timestamp) IN ({placeholders})
                GROUP BY symbol, date(timestamp)
            )
        """, list(prev_days_needed))
        last_price_by_sym_date = {}
        for r in cur.fetchall():
            last_price_by_sym_date[(r['symbol'], r['d'])] = float(r['price'])
    else:
        last_price_by_sym_date = {}

    cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
    day0_prev = {r['symbol']: float(r['prev_close']) for r in cur.fetchall()}

    prev_close_by_date = {}
    for date in all_dates:
        idx = all_dates_db.index(date)
        if idx == 0:
            prev_close_by_date[date] = day0_prev
        else:
            prev_date = all_dates_db[idx - 1]
            prev_close_by_date[date] = {
                sym: last_price_by_sym_date[(sym, prev_date)]
                for sym in day0_prev
                if (sym, prev_date) in last_price_by_sym_date
            }

    # Load nifty in one pass
    nifty_start = f"{all_dates[0]} 00:00:00"
    nifty_end   = f"{all_dates[-1]} 23:59:59"
    cur.execute("SELECT timestamp, price FROM nifty_quotes WHERE timestamp>=? AND timestamp<=? ORDER BY timestamp ASC",
                (nifty_start, nifty_end))
    nifty_by_date: dict = {}
    for r in cur.fetchall():
        d = r['timestamp'][:10]
        if d in date_set:
            nifty_by_date.setdefault(d, []).append({'timestamp': r['timestamp'], 'price': float(r['price'])})

    # Load all candle data in ONE query across all 30 days
    print("Loading candle data (bulk)...")
    ts_start = f"{all_dates[0]} 09:15:00"
    ts_end   = f"{all_dates[-1]} 14:30:00"
    cur.execute("""
        SELECT symbol, timestamp, price, volume FROM stock_quotes
        WHERE timestamp >= ? AND timestamp <= ?
          AND time(timestamp) >= '09:15:00' AND time(timestamp) <= '14:30:00'
        ORDER BY symbol, timestamp ASC
    """, (ts_start, ts_end))

    candles_by_date: dict  = {d: {} for d in all_dates}
    timestamps_set_by_date: dict = {d: set() for d in all_dates}
    for r in cur.fetchall():
        d = r['timestamp'][:10]
        if d not in date_set:
            continue
        s = r['symbol']
        if s not in candles_by_date[d]:
            candles_by_date[d][s] = []
        candles_by_date[d][s].append({'timestamp': r['timestamp'], 'price': float(r['price']), 'volume': float(r['volume'] or 0)})
        timestamps_set_by_date[d].add(r['timestamp'])

    conn.close()
    timestamps_by_date = {d: sorted(timestamps_set_by_date[d]) for d in all_dates}

    def run_config(cfg_tuple):
        top_n, min_pct, touch_pct, c1_min, confirm, approach, nifty_bars, start, end = cfg_tuple
        all_trades = []
        for date in all_dates:
            if not timestamps_by_date[date]: continue
            day_trades = run_day(
                date, prev_close_by_date[date],
                candles_by_date[date], nifty_by_date.get(date, []),
                timestamps_by_date[date], lot_sizes,
                top_n, min_pct, touch_pct, c1_min, confirm, approach,
                nifty_bars, start, end
            )
            all_trades.extend(day_trades)
        return summarise(all_trades, all_dates), all_trades

    W = 130

    # ── --phase3-only: skip Phase 1+2, run Phase 3 with known best config ──────
    if "--phase3-only" in sys.argv:
        # Best config from Phase 2: C1≥2.0+T+2+app3+<13:30 (75% win, 4 trades)
        # Second best liveable:     C1≥2.0+app3             (64.3% win, 14 trades)
        for label, p3_cfg in [
            ("C1≥2.0+T+2+app3+<13:30", (10, 0.0, 0.15, 2.0, 2, 3, 0, "10:00", "13:30")),
            ("C1≥2.0+app3",             (10, 0.0, 0.15, 2.0, 0, 3, 0, "10:00", "14:30")),
        ]:
            p3_s, p3_trades = run_config(p3_cfg)
            base_s, base_trades = run_config(PHASE1_CONFIGS["Baseline"])
            print("\n" + "=" * W)
            print(f"  PHASE 3 — DEEP-DIVE: {label}")
            print(f"  Win%={p3_s['wr']:.1f}%  |  Trades={p3_s['n']}  |  "
                  f"Net=₹{p3_s['net']:+,.0f}  |  MaxDD=₹{p3_s['max_dd']:,.0f}")
            print("=" * W)

            base_day = defaultdict(list)
            best_day = defaultdict(list)
            for t in base_trades:  base_day[t['date']].append(t)
            for t in p3_trades:    best_day[t['date']].append(t)

            print(f"\n  {'Date':10}  {'Baseline':>35}  {'Best Config':>35}")
            print(f"  {'':10}  {'Tr':>3} {'W':>3} {'Net':>12} {'Cum':>12}  "
                  f"{'Tr':>3} {'W':>3} {'Net':>12} {'Cum':>12}")
            print("  " + "-" * 92)
            cum_b = cum_best = 0.0
            for date in all_dates:
                tb = base_day[date]; tb2 = best_day[date]
                nb = sum(t['net'] for t in tb);  nb2 = sum(t['net'] for t in tb2)
                wb = sum(1 for t in tb if t['net']>0); wb2 = sum(1 for t in tb2 if t['net']>0)
                cum_b += nb; cum_best += nb2
                if tb or tb2:
                    ib  = "✅" if nb  > 0 else ("⚪" if not tb  else "❌")
                    ib2 = "✅" if nb2 > 0 else ("⚪" if not tb2 else "❌")
                    print(f"  {date}  {len(tb):>3} {wb:>3} {ib}₹{nb:>+8,.0f} ₹{cum_b:>+9,.0f}  "
                          f"{len(tb2):>3} {wb2:>3} {ib2}₹{nb2:>+8,.0f} ₹{cum_best:>+9,.0f}")

            sym_stats = {}
            for t in p3_trades:
                s = t['symbol']
                if s not in sym_stats:
                    sym_stats[s] = {'n': 0, 'wins': 0, 'net': 0.0}
                sym_stats[s]['n']    += 1
                sym_stats[s]['wins'] += 1 if t['net'] > 0 else 0
                sym_stats[s]['net']  += t['net']
            print(f"\n  PER-SYMBOL (sorted by win rate, min 2 trades):")
            print(f"  {'Symbol':12}  {'Tr':>3}  {'Win%':>6}  {'Net P&L':>11}")
            for sym, ss in sorted(sym_stats.items(),
                                  key=lambda x: (-x[1]['wins']/max(x[1]['n'],1), -x[1]['net'])):
                if ss['n'] < 2: continue
                wr = ss['wins']/ss['n']*100
                icon = "✅" if ss['net'] > 0 else "❌"
                print(f"  {icon} {sym:12}  {ss['n']:>3}  {wr:>5.1f}%  ₹{ss['net']:>+10,.0f}")
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 1 — Individual filters
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * W)
    print("  PHASE 1 — INDIVIDUAL FILTER IMPACT  (each vs baseline, TSL 0.5%, last 30 days)")
    print("=" * W)
    print(f"  {'Config':<28}  {'Trades':>6}  {'Win%':>6}  {'Net P&L':>11}  "
          f"{'Avg/tr':>8}  {'MaxDD':>10}  {'AvgWin':>8}  {'AvgLoss':>9}  {'G/R':>5}")
    print("  " + "-" * (W - 2))

    phase1_results = {}
    baseline_s = None
    for label, cfg in PHASE1_CONFIGS.items():
        s, trades = run_config(cfg)
        phase1_results[label] = (s, cfg)
        target_mark = "  🎯 best" if s['avg'] >= AVG_TRADE_TARGET and s['n'] >= MIN_TRADES_MONTH else ""
        base_mark   = "  ← baseline" if label == "Baseline" else ""
        print(f"  {label:<28}  {s['n']:>6}  {s['wr']:>5.1f}%  "
              f"₹{s['net']:>+10,.0f}  ₹{s['avg']:>+7,.0f}  ₹{s['max_dd']:>9,.0f}  "
              f"₹{s['avg_win']:>+7,.0f}  ₹{s['avg_loss']:>+8,.0f}  "
              f"{s['green']}/{s['red']}{target_mark}{base_mark}")
        if label == "Baseline":
            baseline_s = s

    # Rank by avg net/trade (min 10 trades)
    ranked = sorted(
        [(lbl, s, cfg) for lbl, (s, cfg) in phase1_results.items()
         if s['n'] >= 10 and lbl != "Baseline"],
        key=lambda x: x[1]['avg'], reverse=True
    )
    print(f"\n  Top filters by avg net/trade (≥10 trades):")
    for lbl, s, _ in ranked[:8]:
        delta_avg = s['avg'] - baseline_s['avg']
        print(f"    {lbl:<28}  ₹{s['avg']:>+7,.0f}/tr  ({delta_avg:>+,.0f} vs baseline)  {s['n']} trades")

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 2 — Combination grid (focused on top-performing single filters)
    # ═══════════════════════════════════════════════════════════════════════════

    # Pick top-5 dimensions from Phase 1 to sweep
    top_filters = ranked[:5]
    print(f"\n  Top-5 single filters going into Phase 2:")
    for lbl, s, cfg in top_filters:
        print(f"    {lbl}: avg=₹{s['avg']:+,.0f}/tr  n={s['n']}")

    print("\n" + "=" * W)
    print("  PHASE 2 — COMBINATION GRID SEARCH  (all combos of high-value filters)")
    print(f"  Objective: MAX avg net/trade  |  Target: avg ≥ ₹{AVG_TRADE_TARGET:,}/tr  AND  trades ≥ {MIN_TRADES_MONTH}/month")
    print("=" * W)

    # Focused sweep: min_pct × c1_min × approach × time_window × confirm
    combo_results = []
    total_combos = (len(PHASE2_SWEEP['top_n'])   * len(PHASE2_SWEEP['min_pct'])  *
                    len(PHASE2_SWEEP['touch_pct'])* len(PHASE2_SWEEP['c1_min'])  *
                    len(PHASE2_SWEEP['confirm'])  * len(PHASE2_SWEEP['approach']) *
                    len(PHASE2_SWEEP['nifty_bars'])* len(PHASE2_SWEEP['start'])  *
                    len(PHASE2_SWEEP['end']))
    print(f"  Running {total_combos} combinations...")

    hits_70 = []
    done = 0
    for (top_n, min_pct, touch_pct, c1_min, confirm, approach,
         nifty_bars, start, end) in product(
            PHASE2_SWEEP['top_n'],    PHASE2_SWEEP['min_pct'],
            PHASE2_SWEEP['touch_pct'],PHASE2_SWEEP['c1_min'],
            PHASE2_SWEEP['confirm'],  PHASE2_SWEEP['approach'],
            PHASE2_SWEEP['nifty_bars'],PHASE2_SWEEP['start'],
            PHASE2_SWEEP['end']):

        cfg = (top_n, min_pct, touch_pct, c1_min, confirm, approach,
               nifty_bars, start, end)
        s, trades = run_config(cfg)
        combo_results.append((cfg, s, trades))
        if s['avg'] >= AVG_TRADE_TARGET and s['n'] >= MIN_TRADES_MONTH:
            hits_70.append((cfg, s, trades))
        done += 1
        if done % 50 == 0:
            print(f"  ... {done}/{total_combos} done | hits so far: {len(hits_70)}")

    # Sort all combos by avg net/trade (descending), break ties by trade count
    combo_results.sort(key=lambda x: (x[1]['avg'], x[1]['n']), reverse=True)
    hits_70.sort(key=lambda x: x[1]['avg'], reverse=True)

    print(f"\n  {'Config':<45}  {'Trades':>6}  {'Win%':>6}  {'Net P&L':>11}  "
          f"{'Avg/tr':>8}  {'MaxDD':>10}")
    print("  " + "-" * (W - 2))

    if hits_70:
        print(f"\n  ✅ {len(hits_70)} combos hit ₹{AVG_TRADE_TARGET:,}/tr avg with {MIN_TRADES_MONTH}+ trades:")
        for cfg, s, _ in hits_70[:20]:
            print(f"  🎯 {cfg_label(cfg):<45}  {s['n']:>6}  {s['wr']:>5.1f}%  "
                  f"₹{s['net']:>+10,.0f}  ₹{s['avg']:>+7,.0f}  ₹{s['max_dd']:>9,.0f}")
    else:
        print(f"\n  ❌ No combo hit ₹{AVG_TRADE_TARGET:,}/tr avg with {MIN_TRADES_MONTH}+ trades.")

    print(f"\n  Top 20 by avg net/trade (any trade count):")
    for cfg, s, _ in combo_results[:20]:
        print(f"  {cfg_label(cfg):<45}  {s['n']:>6}  {s['wr']:>5.1f}%  "
              f"₹{s['net']:>+10,.0f}  ₹{s['avg']:>+7,.0f}  ₹{s['max_dd']:>9,.0f}")

    # Top 10 by avg/trade among combos with ≥ 15 trades (most useful for live)
    liquid = [(c, s, t) for c, s, t in combo_results if s['n'] >= MIN_TRADES_MONTH]
    if liquid:
        print(f"\n  Best by avg/trade  (trades≥{MIN_TRADES_MONTH}/month):")
        for cfg, s, _ in liquid[:10]:
            print(f"  {cfg_label(cfg):<45}  {s['n']:>6}  {s['wr']:>5.1f}%  "
                  f"₹{s['net']:>+10,.0f}  ₹{s['avg']:>+7,.0f}  ₹{s['max_dd']:>9,.0f}")

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 3 — Best combo deep-dive
    # ═══════════════════════════════════════════════════════════════════════════
    # Prefer: best avg/trade with ≥15 trades; fall back to best avg/trade overall
    liquid = [(c, s, t) for c, s, t in combo_results if s['n'] >= MIN_TRADES_MONTH]
    best_list = liquid if liquid else combo_results
    best_cfg, best_s, best_trades = best_list[0]

    print("\n" + "=" * W)
    print(f"  PHASE 3 — BEST CONFIG DEEP-DIVE: {cfg_label(best_cfg)}")
    print(f"  Win%={best_s['wr']:.1f}%  |  Trades={best_s['n']}  |  "
          f"Net=₹{best_s['net']:+,.0f}  |  MaxDD=₹{best_s['max_dd']:,.0f}")
    print("=" * W)

    # Day-by-day vs baseline
    base_cfg = PHASE1_CONFIGS["Baseline"]
    base_s, base_trades = run_config(base_cfg)

    print(f"\n  {'Date':10}  {'Baseline':>35}  {'Best Config':>35}")
    print(f"  {'':10}  {'Tr':>3} {'W':>3} {'Net':>12} {'Cum':>12}  "
          f"{'Tr':>3} {'W':>3} {'Net':>12} {'Cum':>12}")
    print("  " + "-" * 92)

    base_day   = defaultdict(list)
    best_day   = defaultdict(list)
    for t in base_trades:    base_day[t['date']].append(t)
    for t in best_trades:    best_day[t['date']].append(t)

    cum_b = cum_best = 0.0
    for date in all_dates:
        tb = base_day[date]; tb2 = best_day[date]
        nb = sum(t['net'] for t in tb);  nb2 = sum(t['net'] for t in tb2)
        wb = sum(1 for t in tb if t['net']>0); wb2 = sum(1 for t in tb2 if t['net']>0)
        cum_b += nb; cum_best += nb2
        if tb or tb2:
            ib  = "✅" if nb  > 0 else ("⚪" if not tb  else "❌")
            ib2 = "✅" if nb2 > 0 else ("⚪" if not tb2 else "❌")
            print(f"  {date}  {len(tb):>3} {wb:>3} {ib}₹{nb:>+8,.0f} ₹{cum_b:>+9,.0f}  "
                  f"{len(tb2):>3} {wb2:>3} {ib2}₹{nb2:>+8,.0f} ₹{cum_best:>+9,.0f}")

    # Per-symbol for best config
    sym_stats = {}
    for t in best_trades:
        s = t['symbol']
        if s not in sym_stats:
            sym_stats[s] = {'n': 0, 'wins': 0, 'net': 0.0}
        sym_stats[s]['n']    += 1
        sym_stats[s]['wins'] += 1 if t['net'] > 0 else 0
        sym_stats[s]['net']  += t['net']

    print(f"\n  PER-SYMBOL (sorted by win rate, min 2 trades):")
    print(f"  {'Symbol':12}  {'Tr':>3}  {'Win%':>6}  {'Net P&L':>11}")
    for sym, s in sorted(sym_stats.items(), key=lambda x: (-x[1]['wins']/max(x[1]['n'],1), -x[1]['net'])):
        if s['n'] < 2: continue
        wr = s['wins']/s['n']*100
        icon = "✅" if s['net'] > 0 else "❌"
        print(f"  {icon} {sym:12}  {s['n']:>3}  {wr:>5.1f}%  ₹{s['net']:>+10,.0f}")

    # Config summary
    top_n, min_pct, touch_pct, c1_min, confirm, approach, nifty_bars, start, end = best_cfg
    print(f"\n  BEST CONFIG PARAMETERS:")
    print(f"    Top N movers  : {top_n}")
    print(f"    Min % move    : {min_pct}%  (only trade stocks moved >{min_pct}% from prev close)")
    print(f"    VWAP touch    : within {touch_pct}%")
    print(f"    C1 vol ratio  : ≥{c1_min}×")
    print(f"    Confirmation  : T+{confirm} candles")
    print(f"    Approach      : ≥{approach} consecutive candles approaching VWAP")
    print(f"    Nifty filter  : last {nifty_bars} bars (0=off)")
    print(f"    Entry window  : {start} – {end}")
    print(f"    TSL           : {TRAILING_SL_PCT}%")
    print(f"\n⚠️  Charges included | All results net of Zerodha F&O fees")


if __name__ == "__main__":
    run()
