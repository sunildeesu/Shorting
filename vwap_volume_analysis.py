#!/usr/bin/env python3
"""
VWAP Volume Pattern Analysis
=============================
For every VWAP touch trade, capture the volume delta of each of the
last 5 candles before the touch and compare to the day's avg candle volume.

Output: for each candle position (-1 to -5), bucket trades by
volume ratio and show win rate / net P&L — reveals which candle's
volume is most predictive of outcome.

Volume ratio = candle_vol_delta / avg_vol_delta_so_far
  < 0.5x  → very low volume
  0.5–1.0 → below average
  1.0–1.5 → above average
  1.5–2.5 → high volume
  > 2.5x  → very high volume (spike)

Window: 10:00 AM – 2:30 PM | TSL 0.5% | Last 30 days | No bias filter
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ── Parameters ──────────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
ALERT_START_TIME         = "10:00"
EXIT_TIME                = "14:30"
MAX_TRADES_PER_STOCK     = 2
TRAILING_SL_PCT          = 0.50
LAST_N_DAYS              = 30
LOOKBACK_CANDLES         = 5     # how many candles back to analyse

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"

VOL_BUCKETS = [
    (0.0,  0.5,  "< 0.5×  (very low)"),
    (0.5,  1.0,  "0.5–1.0× (below avg)"),
    (1.0,  1.5,  "1.0–1.5× (above avg)"),
    (1.5,  2.5,  "1.5–2.5× (high)"),
    (2.5,  999,  "> 2.5×  (spike)"),
]
# ────────────────────────────────────────────────────────────────────────────


def load_lot_sizes():
    try:
        with open(LOT_SIZES_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  lot sizes error ({e}) — defaulting to 1")
        return {}


def compute_charges(entry, exit_p, lot, direction):
    buy  = entry  if direction == "LONG" else exit_p
    sell = exit_p if direction == "LONG" else entry
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
        vol_delta = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv += c['price'] * vol_delta
        cum_vol += vol_delta
    return cum_pv / cum_vol if cum_vol > 0 else None


def get_price_at(candles, ts_str):
    visible = [c for c in candles if c['timestamp'] <= ts_str]
    return visible[-1]['price'] if visible else None


def get_vol_deltas(candles: List[Dict]) -> List[float]:
    """Return per-candle volume deltas for all candles."""
    deltas = []
    for i, c in enumerate(candles):
        delta = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        deltas.append(float(delta))
    return deltas


def get_vol_ratios_lookback(candles_so_far: List[Dict], n: int) -> List[Optional[float]]:
    """
    For the last `n` candles, return their volume ratio vs avg of all prior candles.
    Index 0 = most recent candle (touch candle), index 1 = one before, etc.
    Returns None if not enough candles.
    """
    if len(candles_so_far) < 2:
        return [None] * n

    deltas = get_vol_deltas(candles_so_far)

    # avg = mean of all candles EXCEPT the last n (the "baseline")
    baseline = deltas[:-n] if len(deltas) > n else deltas[:max(1, len(deltas)-1)]
    avg = sum(baseline) / len(baseline) if baseline else 0

    ratios = []
    for i in range(n):
        idx = -(i + 1)   # -1 = touch candle, -2 = one before, etc.
        if abs(idx) > len(deltas):
            ratios.append(None)
        elif avg <= 0:
            ratios.append(None)
        else:
            ratios.append(deltas[idx] / avg)
    return ratios


def get_exit_trailing_sl(candles, entry_ts, entry_price, direction, sl_pct, exit_ts):
    sl     = entry_price * (1 - sl_pct/100) if direction == "LONG" else entry_price * (1 + sl_pct/100)
    peak   = entry_price
    trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak: peak = p
            sl = peak * (1 - sl_pct/100)
            if p <= sl: return sl, "TSL"
        else:
            if p < trough: trough = p
            sl = trough * (1 + sl_pct/100)
            if p >= sl: return sl, "TSL"
    eod = get_price_at(candles, exit_ts)
    return eod, "EOD"


def run():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates_in_db = [r['d'] for r in cur.fetchall()]
    all_dates = all_dates_in_db[-LAST_N_DAYS:]

    print(f"Building prev_close for last {LAST_N_DAYS} days...")
    prev_close_by_date = {}
    for date in all_dates:
        idx = all_dates_in_db.index(date)
        if idx == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = all_dates_in_db[idx - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp=(SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp)=?)
                  AND date(timestamp)=?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}
    conn.close()

    all_trades = []   # each trade has vol_ratios list + outcome

    for date in all_dates:
        market_open  = f"{date} 09:15:00"
        market_close = f"{date} {EXIT_TIME}:00"

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT timestamp FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC
        """, (market_open, market_close))
        timestamps = [r['timestamp'] for r in cur.fetchall()]

        cur.execute("""
            SELECT symbol, timestamp, price, volume FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ? ORDER BY symbol, timestamp ASC
        """, (market_open, market_close))
        candles: Dict[str, List[Dict]] = {}
        for r in cur.fetchall():
            sym = r['symbol']
            if sym not in candles: candles[sym] = []
            candles[sym].append({'timestamp': r['timestamp'], 'price': r['price'], 'volume': r['volume']})
        conn.close()

        if not timestamps:
            continue

        alert_start  = f"{date} {ALERT_START_TIME}:00"
        exit_ts      = f"{date} {EXIT_TIME}:00"
        cooldown     = {}
        trade_count  = defaultdict(int)

        for ts_str in timestamps:
            if ts_str > exit_ts: break
            if ts_str < alert_start: continue

            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

            latest = {}
            for sym, clist in candles.items():
                visible = [c for c in clist if c['timestamp'] <= ts_str]
                if visible: latest[sym] = visible[-1]

            movers = []
            for sym, q in latest.items():
                if sym not in prev_close_by_date[date]: continue
                pc = prev_close_by_date[date][sym]
                if pc <= 0: continue
                pct = (q['price'] - pc) / pc * 100
                movers.append((sym, pct, q['price']))
            movers.sort(key=lambda x: abs(x[1]), reverse=True)
            top10 = movers[:TOP_N]

            for rank, (symbol, pct_change, price) in enumerate(top10, 1):
                if trade_count[symbol] >= MAX_TRADES_PER_STOCK: continue

                csf = [c for c in candles.get(symbol, []) if c['timestamp'] <= ts_str]
                vwap = compute_vwap(csf)
                if vwap is None: continue
                if abs(price - vwap) / vwap * 100 > VWAP_TOUCH_THRESHOLD_PCT: continue

                if symbol in cooldown:
                    if (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                        continue

                trade_dir = "LONG" if pct_change >= 0 else "SHORT"
                lot = lot_sizes.get(symbol, 1)

                # Capture volume ratios for last LOOKBACK_CANDLES
                vol_ratios = get_vol_ratios_lookback(csf, LOOKBACK_CANDLES)

                exit_price, reason = get_exit_trailing_sl(
                    candles.get(symbol, []), ts_str, price, trade_dir, TRAILING_SL_PCT, exit_ts
                )
                if exit_price is None:
                    cooldown[symbol] = ts
                    trade_count[symbol] += 1
                    continue

                pnl_ps = (exit_price - price) if trade_dir == "LONG" else (price - exit_price)
                gross  = pnl_ps * lot
                chg    = compute_charges(price, exit_price, lot, trade_dir)
                net    = gross - chg

                all_trades.append({
                    'date': date, 'symbol': symbol,
                    'trade_dir': trade_dir, 'lot': lot,
                    'entry': price, 'exit': exit_price,
                    'gross': gross, 'net': net,
                    'reason': reason,
                    'vol_ratios': vol_ratios,   # [c-1, c-2, c-3, c-4, c-5]
                })
                cooldown[symbol] = ts
                trade_count[symbol] += 1

    # ── Analysis ──────────────────────────────────────────────────────────────
    W = 105
    print(f"\n{'='*W}")
    print(f"VWAP VOLUME PATTERN ANALYSIS — Last {LAST_N_DAYS} days: {all_dates[0]} → {all_dates[-1]}")
    print(f"  {len(all_trades)} trades  |  10:00–14:30  |  TSL 0.5%")
    print(f"  Volume ratio = candle vol delta / avg of all prior candles that day")
    print(f"{'='*W}")

    overall_net = sum(t['net'] for t in all_trades)
    overall_wr  = sum(1 for t in all_trades if t['net'] > 0) / len(all_trades) * 100 if all_trades else 0
    print(f"\n  Baseline (all trades):  {len(all_trades)} trades  |  "
          f"win rate {overall_wr:.1f}%  |  net ₹{overall_net:+,.0f}")

    for candle_pos in range(1, LOOKBACK_CANDLES + 1):
        print(f"\n{'─'*W}")
        print(f"  CANDLE -{candle_pos}  "
              f"({'touch candle' if candle_pos == 1 else f'{candle_pos} candles before touch'})")
        print(f"{'─'*W}")
        print(f"  {'Volume bucket':28}  {'Trades':>7}  {'% of all':>8}  "
              f"{'Win%':>7}  {'Net P&L':>12}  {'Avg/trade':>10}  {'Avg winner':>11}  {'Avg loser':>10}")
        print(f"  {'-'*28}  {'-'*7}  {'-'*8}  {'-'*7}  {'-'*12}  {'-'*10}  {'-'*11}  {'-'*10}")

        bucket_totals = []
        for lo, hi, label in VOL_BUCKETS:
            bucket = [t for t in all_trades
                      if t['vol_ratios'][candle_pos-1] is not None
                      and lo <= t['vol_ratios'][candle_pos-1] < hi]
            if not bucket:
                bucket_totals.append((label, 0, 0, 0, 0, 0, 0))
                continue
            wins    = [t for t in bucket if t['net'] > 0]
            losses  = [t for t in bucket if t['net'] <= 0]
            net     = sum(t['net'] for t in bucket)
            wr      = len(wins) / len(bucket) * 100
            avg_t   = net / len(bucket)
            avg_w   = sum(t['net'] for t in wins)  / len(wins)  if wins   else 0
            avg_l   = sum(t['net'] for t in losses) / len(losses) if losses else 0
            pct_all = len(bucket) / len(all_trades) * 100
            bucket_totals.append((label, len(bucket), pct_all, wr, net, avg_t, avg_w, avg_l))

            # highlight best/worst
            marker = ""
            if wr == max(b[3] for b in bucket_totals if b[1] > 0): marker = "  ← best win%"
            print(f"  {label:28}  {len(bucket):>7}  {pct_all:>7.1f}%  "
                  f"{wr:>6.1f}%  ₹{net:>+10,.0f}  ₹{avg_t:>+8,.0f}  "
                  f"₹{avg_w:>+9,.0f}  ₹{avg_l:>+8,.0f}")

        # Trades with no data for this candle position
        no_data = [t for t in all_trades if t['vol_ratios'][candle_pos-1] is None]
        if no_data:
            print(f"  {'(insufficient data)':28}  {len(no_data):>7}")

    # ── Cross-candle correlation: which candle predicts best? ─────────────────
    print(f"\n{'='*W}")
    print(f"  PREDICTIVE POWER SUMMARY — best Win% per candle position")
    print(f"{'='*W}")
    print(f"  {'Position':12}  {'Best bucket':28}  {'Trades':>7}  {'Win%':>7}  {'Net P&L':>12}  {'Avg/trade':>10}")
    print(f"  {'-'*12}  {'-'*28}  {'-'*7}  {'-'*7}  {'-'*12}  {'-'*10}")

    for candle_pos in range(1, LOOKBACK_CANDLES + 1):
        best_wr    = -1
        best_label = ""
        best_stats = (0, 0, 0, 0)
        for lo, hi, label in VOL_BUCKETS:
            bucket = [t for t in all_trades
                      if t['vol_ratios'][candle_pos-1] is not None
                      and lo <= t['vol_ratios'][candle_pos-1] < hi]
            if len(bucket) < 10:
                continue
            wr = sum(1 for t in bucket if t['net'] > 0) / len(bucket) * 100
            if wr > best_wr:
                best_wr    = wr
                best_label = label
                net        = sum(t['net'] for t in bucket)
                avg_t      = net / len(bucket)
                best_stats = (len(bucket), wr, net, avg_t)

        n, wr, net, avg_t = best_stats
        print(f"  Candle -{candle_pos:8}  {best_label:28}  {n:>7}  {wr:>6.1f}%  "
              f"₹{net:>+10,.0f}  ₹{avg_t:>+8,.0f}")

    # ── Spike candle (-1) deep dive: win rate by trade direction ──────────────
    print(f"\n{'─'*W}")
    print(f"  SPIKE CANDLE (-1) BREAKDOWN BY DIRECTION  (vol ratio > 1.5×)")
    print(f"{'─'*W}")
    print(f"  {'Direction':8}  {'Trades':>7}  {'Win%':>7}  {'Net P&L':>12}  {'Avg/trade':>10}")
    print(f"  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*12}  {'-'*10}")
    for direction in ["LONG", "SHORT"]:
        spike = [t for t in all_trades
                 if t['trade_dir'] == direction
                 and t['vol_ratios'][0] is not None
                 and t['vol_ratios'][0] >= 1.5]
        if not spike: continue
        wr  = sum(1 for t in spike if t['net'] > 0) / len(spike) * 100
        net = sum(t['net'] for t in spike)
        print(f"  {direction:8}  {len(spike):>7}  {wr:>6.1f}%  ₹{net:>+10,.0f}  ₹{net/len(spike):>+8,.0f}")

    low_vol = [t for t in all_trades
               if t['vol_ratios'][0] is not None and t['vol_ratios'][0] < 0.5]
    if low_vol:
        print(f"\n  VERY LOW VOLUME TOUCH (-1 < 0.5×) BY DIRECTION:")
        for direction in ["LONG", "SHORT"]:
            sub = [t for t in low_vol if t['trade_dir'] == direction]
            if not sub: continue
            wr  = sum(1 for t in sub if t['net'] > 0) / len(sub) * 100
            net = sum(t['net'] for t in sub)
            print(f"  {direction:8}  {len(sub):>7}  {wr:>6.1f}%  ₹{net:>+10,.0f}  ₹{net/len(sub):>+8,.0f}")

    # ── Consecutive candle pattern ──────────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  2-CANDLE COMBO PATTERNS  (candle -2 then candle -1)")
    print(f"  Shows if volume trend (building up vs fading) predicts outcome")
    print(f"{'─'*W}")
    print(f"  {'C-2 bucket':22}  {'C-1 bucket':22}  {'Trades':>7}  {'Win%':>7}  {'Net P&L':>12}  {'Avg/trade':>10}")
    print(f"  {'-'*22}  {'-'*22}  {'-'*7}  {'-'*7}  {'-'*12}  {'-'*10}")

    # Define simplified 3-level buckets for combos
    combo_levels = [
        (0.0, 1.0, "LOW (<1.0×)"),
        (1.0, 1.5, "NORMAL (1.0–1.5×)"),
        (1.5, 999, "HIGH (>1.5×)"),
    ]
    for lo2, hi2, lbl2 in combo_levels:
        for lo1, hi1, lbl1 in combo_levels:
            combo = [t for t in all_trades
                     if t['vol_ratios'][1] is not None and t['vol_ratios'][0] is not None
                     and lo2 <= t['vol_ratios'][1] < hi2
                     and lo1 <= t['vol_ratios'][0] < hi1]
            if len(combo) < 5:
                continue
            wr  = sum(1 for t in combo if t['net'] > 0) / len(combo) * 100
            net = sum(t['net'] for t in combo)
            marker = "  ◀ BEST" if wr >= 50 else ("  ◀ AVOID" if wr <= 25 else "")
            print(f"  {lbl2:22}  {lbl1:22}  {len(combo):>7}  {wr:>6.1f}%  "
                  f"₹{net:>+10,.0f}  ₹{net/len(combo):>+8,.0f}{marker}")

    print(f"\n⚠️  TSL 0.5% | 10:00–14:30 | Top-10 F&O movers | Max 2 trades/stock")


if __name__ == "__main__":
    run()
