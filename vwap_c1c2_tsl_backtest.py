#!/usr/bin/env python3
"""
VWAP Mover — C-1/C-2 Threshold × Trailing SL Grid Backtest
=============================================================
Sweeps both dimensions to find the best combination:

  C1_MIN  — touch candle vol delta must be ≥ C1_MIN × avg
             (higher = require bigger spike)
  C2_MAX  — candle before touch must be < C2_MAX × avg
             (lower = require quieter pre-touch)
  TSL_PCT — trailing stop-loss %: 0.3 / 0.5 / 0.7 / 1.0

Tables produced:
  1. Baseline (no C-1/C-2) × each TSL
  2. Vary C1_MIN (C2_MAX fixed at 1.0) × each TSL
  3. Vary C2_MAX (C1_MIN fixed at 1.5) × each TSL
  4. Best N cells per TSL (overall grid)

Window: 10:00 – 14:30  |  Last 30 trading days
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ── Parameters ───────────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
ALERT_START_TIME         = "10:00"
EXIT_TIME                = "14:30"
MAX_TRADES_PER_STOCK     = 2
LAST_N_DAYS              = 30

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"

# Sweep values
C1_MINS  = [None, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]   # None = no C1 filter
C2_MAXES = [None, 0.5, 0.75, 1.0, 1.25, 1.5]             # None = no C2 filter
TSL_PCTS = [0.3, 0.5, 0.7, 1.0]

C1_FIXED = 1.5   # held constant when sweeping C2
C2_FIXED = 1.0   # held constant when sweeping C1
# ─────────────────────────────────────────────────────────────────────────────


def load_lot_sizes() -> Dict[str, int]:
    try:
        with open(LOT_SIZES_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load lot sizes ({e}) — defaulting to 1")
        return {}


def compute_charges(entry: float, exit_p: float, lot: int, direction: str) -> float:
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


def compute_vwap(candles: List[Dict]) -> Optional[float]:
    if len(candles) < 2:
        return None
    cum_pv = cum_vol = 0.0
    for i, c in enumerate(candles):
        vd = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv += c['price'] * vd
        cum_vol += vd
    return cum_pv / cum_vol if cum_vol > 0 else None


def get_price_at(candles: List[Dict], ts: str) -> Optional[float]:
    v = [c for c in candles if c['timestamp'] <= ts]
    return v[-1]['price'] if v else None


def get_vol_ratios(candles: List[Dict]) -> Tuple[Optional[float], Optional[float]]:
    if len(candles) < 3:
        return None, None
    deltas = [
        float(c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume']))
        for i, c in enumerate(candles)
    ]
    baseline = deltas[:-2]
    avg = sum(baseline) / len(baseline) if baseline else 0
    if avg <= 0:
        return None, None
    return round(deltas[-1] / avg, 2), round(deltas[-2] / avg, 2)


def get_exit_tsl(
    candles: List[Dict], entry_ts: str, entry_price: float,
    direction: str, tsl_pct: float, exit_ts: str
) -> Tuple[Optional[float], str]:
    sl = (entry_price * (1 - tsl_pct / 100) if direction == "LONG"
          else entry_price * (1 + tsl_pct / 100))
    peak = trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak:
                peak = p
            sl = peak * (1 - tsl_pct / 100)
            if p <= sl:
                return sl, "TSL"
        else:
            if p < trough:
                trough = p
            sl = trough * (1 + tsl_pct / 100)
            if p >= sl:
                return sl, "TSL"
    return get_price_at(candles, exit_ts), "EOD"


def run_day(
    date: str,
    prev_close: Dict[str, float],
    all_candles: Dict[str, List[Dict]],
    timestamps: List[str],
    lot_sizes: Dict[str, int],
    c1_min: Optional[float],
    c2_max: Optional[float],
    tsl_pct: float,
) -> List[Dict]:
    alert_start = f"{date} {ALERT_START_TIME}:00"
    exit_ts     = f"{date} {EXIT_TIME}:00"
    cooldown:    Dict[str, datetime] = {}
    trade_count: Dict[str, int]      = defaultdict(int)
    trades: List[Dict] = []

    for ts_str in timestamps:
        if ts_str > exit_ts:
            break
        if ts_str < alert_start:
            continue
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

        latest: Dict[str, Dict] = {}
        for sym, cl in all_candles.items():
            vis = [c for c in cl if c['timestamp'] <= ts_str]
            if vis:
                latest[sym] = vis[-1]

        movers = []
        for sym, q in latest.items():
            pc = prev_close.get(sym, 0)
            if pc <= 0:
                continue
            pct = (q['price'] - pc) / pc * 100
            movers.append((sym, pct, q['price']))
        movers.sort(key=lambda x: abs(x[1]), reverse=True)

        for rank, (symbol, pct_change, price) in enumerate(movers[:TOP_N], 1):
            if trade_count[symbol] >= MAX_TRADES_PER_STOCK:
                continue

            csf = [c for c in all_candles.get(symbol, []) if c['timestamp'] <= ts_str]
            vwap = compute_vwap(csf)
            if vwap is None:
                continue
            if abs(price - vwap) / vwap * 100 > VWAP_TOUCH_THRESHOLD_PCT:
                continue
            if symbol in cooldown and (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                continue

            # ── C-1/C-2 filter ────────────────────────────────────────────
            if c1_min is not None or c2_max is not None:
                c1, c2 = get_vol_ratios(csf)
                if c1 is None:
                    cooldown[symbol] = ts
                    continue
                if c1_min is not None and c1 < c1_min:
                    cooldown[symbol] = ts
                    continue
                if c2_max is not None and c2 >= c2_max:
                    cooldown[symbol] = ts
                    continue

            direction = "LONG" if pct_change >= 0 else "SHORT"
            lot = lot_sizes.get(symbol, 1)

            ep, reason = get_exit_tsl(
                all_candles.get(symbol, []), ts_str, price,
                direction, tsl_pct, exit_ts
            )
            if ep is None:
                cooldown[symbol] = ts
                trade_count[symbol] += 1
                continue

            pnl   = (ep - price) if direction == "LONG" else (price - ep)
            gross = pnl * lot
            chg   = compute_charges(price, ep, lot, direction)

            trades.append({
                'date': date, 'symbol': symbol, 'dir': direction,
                'lot': lot, 'entry': price, 'exit': ep,
                'reason': reason, 'gross': gross, 'net': gross - chg,
            })
            cooldown[symbol] = ts
            trade_count[symbol] += 1

    return trades


def summarise(trades: List[Dict], all_dates: List[str]) -> Dict:
    if not trades:
        return {'n': 0, 'wr': 0.0, 'net': 0.0, 'avg': 0.0,
                'green': 0, 'red': 0, 'max_dd': 0.0}
    wins = [t for t in trades if t['net'] > 0]
    net  = sum(t['net'] for t in trades)

    day_nets: Dict[str, float] = defaultdict(float)
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
        'n':      len(trades),
        'wr':     len(wins) / len(trades) * 100,
        'net':    net,
        'avg':    net / len(trades),
        'green':  green,
        'red':    red,
        'max_dd': dd,
    }


def cell(s: Dict) -> str:
    """Compact cell: net / trades / win% / maxDD"""
    if s['n'] == 0:
        return f"{'—':^38}"
    return (f"₹{s['net']:>+8,.0f} | {s['n']:>3}tr | "
            f"{s['wr']:>4.0f}% | DD₹{s['max_dd']:>6,.0f}")


def run():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates_db = [r['d'] for r in cur.fetchall()]
    all_dates    = all_dates_db[-LAST_N_DAYS:]
    print(f"Building prev_close for {len(all_dates)} days "
          f"({all_dates[0]} → {all_dates[-1]})...")

    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for date in all_dates:
        idx = all_dates_db.index(date)
        if idx == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = all_dates_db[idx - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp = (SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp) = ?)
                  AND date(timestamp) = ?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}
    conn.close()

    # Pre-load all candle data per date (avoid repeated DB opens)
    candles_by_date: Dict[str, Dict[str, List[Dict]]] = {}
    timestamps_by_date: Dict[str, List[str]] = {}
    print("Loading candle data...")
    for date in all_dates:
        mo = f"{date} 09:15:00"
        mc = f"{date} {EXIT_TIME}:00"
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT timestamp FROM stock_quotes "
            "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC", (mo, mc)
        )
        timestamps_by_date[date] = [r['timestamp'] for r in cur.fetchall()]
        cur.execute(
            "SELECT symbol, timestamp, price, volume FROM stock_quotes "
            "WHERE timestamp >= ? AND timestamp <= ? ORDER BY symbol, timestamp ASC", (mo, mc)
        )
        candles: Dict[str, List[Dict]] = {}
        for r in cur.fetchall():
            s = r['symbol']
            if s not in candles:
                candles[s] = []
            candles[s].append({
                'timestamp': r['timestamp'],
                'price':     float(r['price']),
                'volume':    float(r['volume'] or 0),
            })
        candles_by_date[date] = candles
        conn.close()

    # ── Build result cache: (c1_min, c2_max, tsl_pct) → summary ─────────────
    # Collect all unique (c1, c2, tsl) combos we need
    needed = set()
    needed.add((None, None, 0.5))   # baseline reference

    for tsl in TSL_PCTS:
        needed.add((None, None, tsl))  # baseline per TSL
        for c1 in C1_MINS:
            needed.add((c1, C2_FIXED, tsl))
        for c2 in C2_MAXES:
            needed.add((C1_FIXED, c2, tsl))

    print(f"Running {len(needed)} configs × {len(all_dates)} days...")
    cache: Dict[Tuple, Dict] = {}
    for key in sorted(needed, key=lambda x: (x[2], x[0] or 0, x[1] or 0)):
        c1_min, c2_max, tsl_pct = key
        trades = []
        for date in all_dates:
            if not timestamps_by_date[date]:
                continue
            day_trades = run_day(
                date, prev_close_by_date[date],
                candles_by_date[date], timestamps_by_date[date],
                lot_sizes, c1_min, c2_max, tsl_pct
            )
            trades.extend(day_trades)
        cache[key] = summarise(trades, all_dates)

    W = 130
    TSL_HDR = "  |  ".join(f"TSL {t:.1f}%  {'Net':>9} | {'Tr':>3} | {'Win%':>4} | {'MaxDD':>8}"
                            for t in TSL_PCTS)

    # ── Table 1: Baseline (no filter) ────────────────────────────────────────
    print("\n" + "=" * W)
    print(f"  TABLE 1 — BASELINE (no C-1/C-2 filter)  |  Top {TOP_N}  |  10:00–14:30  |  Last {LAST_N_DAYS} days")
    print("=" * W)
    print(f"  {'TSL':>6}  {'Trades':>6}  {'Win%':>6}  {'Net P&L':>11}  {'Avg/tr':>8}  "
          f"{'Green/Red':>10}  {'MaxDD':>10}")
    print("  " + "-" * 70)
    for tsl in TSL_PCTS:
        s = cache[(None, None, tsl)]
        marker = "  ← current live TSL" if tsl == 0.5 else ""
        print(f"  {tsl:.1f}%   {s['n']:>6}  {s['wr']:>5.1f}%  "
              f"₹{s['net']:>+10,.0f}  ₹{s['avg']:>+7,.0f}  "
              f"{s['green']:>4}/{s['red']:<4}  ₹{s['max_dd']:>9,.0f}{marker}")

    # ── Table 2: Vary C1_MIN (C2_MAX=1.0 fixed) × TSL ───────────────────────
    print("\n" + "=" * W)
    print(f"  TABLE 2 — VARY C1_MIN  (C2_MAX fixed = {C2_FIXED})  |  columns = TSL %")
    print(f"  {'Net':>9} | {'Tr':>3} | {'W%':>4} | {'DD':>8}    per TSL")
    print("=" * W)

    col_w = 36
    hdr = f"  {'C1_MIN':>8}  "
    for tsl in TSL_PCTS:
        hdr += f"  TSL {tsl:.1f}%{' '*(col_w-8)}"
    print(hdr)
    print("  " + "-" * (W - 2))

    best_nets = {tsl: max(cache[(c1, C2_FIXED, tsl)]['net'] for c1 in C1_MINS) for tsl in TSL_PCTS}

    for c1 in C1_MINS:
        lbl = f"no C1" if c1 is None else f"C1≥{c1:.1f}×"
        row = f"  {lbl:>8}  "
        for tsl in TSL_PCTS:
            s = cache[(c1, C2_FIXED, tsl)]
            marker = "◀" if s['net'] == best_nets[tsl] and s['n'] > 0 else " "
            row += (f"  {marker}₹{s['net']:>+8,.0f} | {s['n']:>3} | "
                    f"{s['wr']:>4.0f}% | ₹{s['max_dd']:>6,.0f}")
        live = "  ← live" if c1 == 1.5 else ""
        print(row + live)

    # ── Table 3: Vary C2_MAX (C1_MIN=1.5 fixed) × TSL ───────────────────────
    print("\n" + "=" * W)
    print(f"  TABLE 3 — VARY C2_MAX  (C1_MIN fixed = {C1_FIXED})  |  columns = TSL %")
    print("=" * W)

    hdr = f"  {'C2_MAX':>8}  "
    for tsl in TSL_PCTS:
        hdr += f"  TSL {tsl:.1f}%{' '*(col_w-8)}"
    print(hdr)
    print("  " + "-" * (W - 2))

    best_nets2 = {tsl: max(cache[(C1_FIXED, c2, tsl)]['net'] for c2 in C2_MAXES) for tsl in TSL_PCTS}

    for c2 in C2_MAXES:
        lbl = f"no C2" if c2 is None else f"C2<{c2:.2f}×"
        row = f"  {lbl:>8}  "
        for tsl in TSL_PCTS:
            s = cache[(C1_FIXED, c2, tsl)]
            marker = "◀" if s['net'] == best_nets2[tsl] and s['n'] > 0 else " "
            row += (f"  {marker}₹{s['net']:>+8,.0f} | {s['n']:>3} | "
                    f"{s['wr']:>4.0f}% | ₹{s['max_dd']:>6,.0f}")
        live = "  ← live" if c2 == 1.0 else ""
        print(row + live)

    # ── Table 4: Top 5 combos per TSL ────────────────────────────────────────
    print("\n" + "=" * W)
    print(f"  TABLE 4 — TOP 5 COMBOS BY NET P&L  (per TSL)")
    print("=" * W)
    for tsl in TSL_PCTS:
        # All (c1, c2) combinations tested for this TSL
        candidates = [(c1, C2_FIXED, tsl) for c1 in C1_MINS] + \
                     [(C1_FIXED, c2, tsl) for c2 in C2_MAXES if c2 != C2_FIXED]
        candidates = list(set(candidates))
        ranked = sorted(candidates, key=lambda k: cache[k]['net'], reverse=True)[:5]
        print(f"\n  TSL {tsl:.1f}%:")
        print(f"  {'Config':>22}  {'Trades':>6}  {'Win%':>6}  {'Net P&L':>11}  "
              f"{'Avg/tr':>8}  {'MaxDD':>10}")
        print("  " + "-" * 75)
        for key in ranked:
            c1, c2, _ = key
            s = cache[key]
            c1_s = "no-C1" if c1 is None else f"C1≥{c1:.1f}"
            c2_s = f"C2<{c2:.2f}" if c2 is not None else "no-C2"
            lbl  = f"{c1_s} + {c2_s}"
            live = "  ← live" if c1 == 1.5 and c2 == 1.0 else ""
            print(f"  {lbl:>22}  {s['n']:>6}  {s['wr']:>5.1f}%  "
                  f"₹{s['net']:>+10,.0f}  ₹{s['avg']:>+7,.0f}  "
                  f"₹{s['max_dd']:>9,.0f}{live}")

    print(f"\n⚠️  Charges included: ₹40 brok | STT 0.02% sell | Exchange 0.00188% | SEBI | Stamp | GST 18%")
    print(f"   C1_MIN: touch candle vol delta ≥ C1_MIN × day avg  (higher = bigger spike required)")
    print(f"   C2_MAX: pre-touch candle vol delta < C2_MAX × day avg  (lower = quieter pre-touch required)")
    print(f"   Live config: C1≥1.5 + C2<1.0 + TSL 0.5%")


if __name__ == "__main__":
    run()
