#!/usr/bin/env python3
"""
VWAP Backtest — Top-20 with Volume Filter (C-1≥1.5× AND C-2<1.0×)
====================================================================
Compares four scenarios over last 30 days:
  1. Top-10, No filter (original baseline)
  2. Top-10, Volume filter ON
  3. Top-20, No filter
  4. Top-20, Volume filter ON  ← the primary target

Window: 10:00–14:30 | TSL 0.5% | Last 30 trading days
Volume filter: touch candle delta ≥ 1.5× avg AND prior candle delta < 1.0× avg
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

# ── Parameters ──────────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
ALERT_START_TIME         = "10:00"
EXIT_TIME                = "14:30"
MAX_TRADES_PER_STOCK     = 2
TRAILING_SL_PCT          = 0.50
LAST_N_DAYS              = 30

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"

# Volume filter thresholds
VOL_C1_MIN = 1.5   # touch candle delta ≥ this
VOL_C2_MAX = 1.0   # previous candle delta < this


def load_lot_sizes():
    try:
        with open(LOT_SIZES_FILE) as f:
            return json.load(f)
    except:
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
        vd = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv += c['price'] * vd
        cum_vol += vd
    return cum_pv / cum_vol if cum_vol > 0 else None


def get_price_at(candles, ts):
    v = [c for c in candles if c['timestamp'] <= ts]
    return v[-1]['price'] if v else None


def get_vol_ratios(candles_so_far: List[Dict]):
    """Return (c1_ratio, c2_ratio) or (None, None) if insufficient data."""
    if len(candles_so_far) < 3:
        return None, None
    deltas = []
    for i, c in enumerate(candles_so_far):
        deltas.append(float(c['volume'] if i == 0 else max(0, c['volume'] - candles_so_far[i-1]['volume'])))
    baseline = deltas[:-2]  # all except last 2 candles
    avg = sum(baseline) / len(baseline) if baseline else 0
    if avg <= 0:
        return None, None
    c1_ratio = deltas[-1] / avg   # touch candle
    c2_ratio = deltas[-2] / avg   # candle before touch
    return round(c1_ratio, 2), round(c2_ratio, 2)


def get_exit_tsl(candles, entry_ts, entry_price, direction, sl_pct, exit_ts):
    sl = entry_price * (1 - sl_pct / 100) if direction == "LONG" else entry_price * (1 + sl_pct / 100)
    peak = trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak:
                peak = p
            sl = peak * (1 - sl_pct / 100)
            if p <= sl:
                return sl, "TSL"
        else:
            if p < trough:
                trough = p
            sl = trough * (1 + sl_pct / 100)
            if p >= sl:
                return sl, "TSL"
    return get_price_at(candles, exit_ts), "EOD"


def simulate(all_dates, all_dates_db, prev_close_by_date, lot_sizes, top_n, vol_filter):
    """Run simulation and return list of trade dicts."""
    all_trades = []

    for date in all_dates:
        mo = f"{date} 09:15:00"
        mc = f"{date} {EXIT_TIME}:00"

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            "SELECT DISTINCT timestamp FROM stock_quotes WHERE timestamp>=? AND timestamp<=? ORDER BY timestamp ASC",
            (mo, mc)
        )
        timestamps = [r['timestamp'] for r in cur.fetchall()]

        cur.execute(
            "SELECT symbol,timestamp,price,volume FROM stock_quotes "
            "WHERE timestamp>=? AND timestamp<=? ORDER BY symbol,timestamp ASC",
            (mo, mc)
        )
        candles = {}
        for r in cur.fetchall():
            s = r['symbol']
            if s not in candles:
                candles[s] = []
            candles[s].append({'timestamp': r['timestamp'], 'price': r['price'], 'volume': r['volume']})
        conn.close()

        if not timestamps:
            continue

        alert_start = f"{date} {ALERT_START_TIME}:00"
        exit_ts     = f"{date} {EXIT_TIME}:00"
        cooldown    = {}
        trade_count = defaultdict(int)

        for ts_str in timestamps:
            if ts_str > exit_ts:
                break
            if ts_str < alert_start:
                continue
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

            # Build snapshot of latest prices
            latest = {}
            for sym, cl in candles.items():
                vis = [c for c in cl if c['timestamp'] <= ts_str]
                if vis:
                    latest[sym] = vis[-1]

            # Rank movers
            movers = []
            for sym, q in latest.items():
                pc = prev_close_by_date[date].get(sym, 0)
                if pc <= 0:
                    continue
                pct = (q['price'] - pc) / pc * 100
                movers.append((sym, pct, q['price']))
            movers.sort(key=lambda x: abs(x[1]), reverse=True)

            for rank, (symbol, pct_change, price) in enumerate(movers[:top_n], 1):
                if trade_count[symbol] >= MAX_TRADES_PER_STOCK:
                    continue
                csf = [c for c in candles.get(symbol, []) if c['timestamp'] <= ts_str]
                vwap = compute_vwap(csf)
                if vwap is None:
                    continue
                if abs(price - vwap) / vwap * 100 > VWAP_TOUCH_THRESHOLD_PCT:
                    continue
                if symbol in cooldown and (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                    continue

                # Volume filter
                c1, c2 = get_vol_ratios(csf)
                if vol_filter:
                    if c1 is None or c2 is None:
                        continue
                    if not (c1 >= VOL_C1_MIN and c2 < VOL_C2_MAX):
                        continue

                trade_dir = "LONG" if pct_change >= 0 else "SHORT"
                lot = lot_sizes.get(symbol, 1)

                ep, reason = get_exit_tsl(candles.get(symbol, []), ts_str, price, trade_dir, TRAILING_SL_PCT, exit_ts)
                if ep is None:
                    cooldown[symbol] = ts
                    trade_count[symbol] += 1
                    continue

                pnl   = (ep - price) if trade_dir == "LONG" else (price - ep)
                gross = pnl * lot
                chg   = compute_charges(price, ep, lot, trade_dir)
                net   = gross - chg

                all_trades.append({
                    'date':   date,
                    'symbol': symbol,
                    'dir':    trade_dir,
                    'lot':    lot,
                    'entry':  price,
                    'exit':   ep,
                    'reason': reason,
                    'gross':  gross,
                    'net':    net,
                    'c1':     c1,
                    'c2':     c2,
                    'rank':   rank,
                })
                cooldown[symbol] = ts
                trade_count[symbol] += 1

    return all_trades


def print_stats(label, trades, all_dates, W=115):
    if not trades:
        print(f"  {label:45}  {'0 trades':>8}")
        return

    wins   = [t for t in trades if t['net'] > 0]
    losses = [t for t in trades if t['net'] <= 0]
    n      = len(trades)
    wr     = len(wins) / n * 100
    net    = sum(t['net'] for t in trades)
    avg    = net / n

    day_nets = defaultdict(float)
    for t in trades:
        day_nets[t['date']] += t['net']
    green = sum(1 for v in day_nets.values() if v > 0)
    red   = sum(1 for v in day_nets.values() if v < 0)

    # Max drawdown
    cum = pk = dd = 0.0
    for d in all_dates:
        cum += day_nets.get(d, 0)
        pk   = max(pk, cum)
        dd   = max(dd, pk - cum)

    tsl_exits = sum(1 for t in trades if t['reason'] == 'TSL')
    eod_exits = sum(1 for t in trades if t['reason'] == 'EOD')

    print(f"  {label:45}  trades={n:>4}  win%={wr:>5.1f}  net=₹{net:>+9,.0f}  "
          f"avg=₹{avg:>+6,.0f}  green/red={green}/{red}  maxDD=₹{dd:>7,.0f}  "
          f"TSL={tsl_exits} EOD={eod_exits}")


def print_daily(label, trades, all_dates, W=115):
    print(f"\n  Daily breakdown — {label}")
    print(f"  {'Date':12}  {'Trades':>7}  {'Win':>5}  {'Win%':>6}  {'Net P&L':>10}  Symbols")
    print(f"  {'-'*12}  {'-'*7}  {'-'*5}  {'-'*6}  {'-'*10}  {'-'*40}")

    day_map = defaultdict(list)
    for t in trades:
        day_map[t['date']].append(t)

    total_net = 0
    for d in all_dates:
        day_trades = day_map.get(d, [])
        if not day_trades:
            continue
        d_wins = sum(1 for t in day_trades if t['net'] > 0)
        d_net  = sum(t['net'] for t in day_trades)
        total_net += d_net
        wr     = d_wins / len(day_trades) * 100
        icon   = "✅" if d_net > 0 else "❌"
        syms   = ", ".join(
            f"{t['symbol']}({'+' if t['net']>0 else ''}₹{t['net']:,.0f})"
            for t in sorted(day_trades, key=lambda x: x['net'], reverse=True)
        )
        print(f"  {d}  {len(day_trades):>7}  {d_wins:>5}  {wr:>5.1f}%  "
              f"{icon}₹{d_net:>+8,.0f}  {syms[:80]}")

    print(f"  {'TOTAL':12}  {'':>7}  {'':>5}  {'':>6}  ₹{total_net:>+9,.0f}")


def run():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates_db = [r['d'] for r in cur.fetchall()]
    all_dates    = all_dates_db[-LAST_N_DAYS:]

    print(f"Building prev_close for {len(all_dates)} days...")
    prev_close_by_date = {}
    for date in all_dates:
        idx = all_dates_db.index(date)
        if idx == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            pd = all_dates_db[idx - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp=(SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp)=?)
                  AND date(timestamp)=?
            """, (pd, pd))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}
    conn.close()

    W = 140
    print(f"\n{'='*W}")
    print(f"  VWAP BACKTEST — Top-10 vs Top-20 × No Filter vs Volume Filter")
    print(f"  {len(all_dates)} days: {all_dates[0]} → {all_dates[-1]}")
    print(f"  Window: {ALERT_START_TIME}–{EXIT_TIME}  |  TSL {TRAILING_SL_PCT}%  |  "
          f"Vol filter: C-1≥{VOL_C1_MIN}× AND C-2<{VOL_C2_MAX}×")
    print(f"{'='*W}")

    print(f"\n  Running 4 scenarios (this may take 1–2 minutes)...")

    # Run all 4 scenarios
    t10_nofilter = simulate(all_dates, all_dates_db, prev_close_by_date, lot_sizes, top_n=10,  vol_filter=False)
    print(f"  ✓ Top-10 no filter:   {len(t10_nofilter)} trades")
    t10_filter   = simulate(all_dates, all_dates_db, prev_close_by_date, lot_sizes, top_n=10,  vol_filter=True)
    print(f"  ✓ Top-10 vol filter:  {len(t10_filter)} trades")
    t20_nofilter = simulate(all_dates, all_dates_db, prev_close_by_date, lot_sizes, top_n=20,  vol_filter=False)
    print(f"  ✓ Top-20 no filter:   {len(t20_nofilter)} trades")
    t20_filter   = simulate(all_dates, all_dates_db, prev_close_by_date, lot_sizes, top_n=20,  vol_filter=True)
    print(f"  ✓ Top-20 vol filter:  {len(t20_filter)} trades")

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  SUMMARY COMPARISON")
    print(f"{'─'*W}")
    print(f"  {'Scenario':45}  {'trades':>6}  {'win%':>5}  {'net P&L':>10}  "
          f"{'avg/tr':>7}  {'green/red':>9}  {'maxDD':>9}  {'TSL exits':>9}")
    print(f"  {'-'*45}  {'-'*6}  {'-'*5}  {'-'*10}  {'-'*7}  {'-'*9}  {'-'*9}  {'-'*9}")

    print_stats("Top-10  |  No filter  (original baseline)", t10_nofilter, all_dates)
    print_stats("Top-10  |  Vol filter (C-1≥1.5× C-2<1.0×)", t10_filter,   all_dates)
    print_stats("Top-20  |  No filter",                       t20_nofilter, all_dates)
    print_stats("Top-20  |  Vol filter (C-1≥1.5× C-2<1.0×)", t20_filter,   all_dates)

    # ── Daily breakdown for the target scenario ───────────────────────────────
    print_daily("Top-20  |  Vol filter ON", t20_filter, all_dates)

    # ── Best & worst days analysis for Top-20 filtered ────────────────────────
    if t20_filter:
        print(f"\n{'─'*W}")
        print(f"  TOP-20 VOL FILTER — Top 5 Best / Worst Days")
        print(f"{'─'*W}")
        day_map = defaultdict(list)
        for t in t20_filter:
            day_map[t['date']].append(t)
        day_nets = {d: sum(t['net'] for t in ts) for d, ts in day_map.items()}
        sorted_days = sorted(day_nets.items(), key=lambda x: x[1], reverse=True)

        print(f"\n  Best 5 days:")
        for d, dn in sorted_days[:5]:
            ts = day_map[d]
            syms = ", ".join(f"{t['symbol']}(₹{t['net']:+,.0f})" for t in sorted(ts, key=lambda x: x['net'], reverse=True))
            print(f"    {d}  ₹{dn:>+9,.0f}  [{len(ts)} trades]  {syms[:80]}")

        print(f"\n  Worst 5 days:")
        for d, dn in sorted_days[-5:]:
            ts = day_map[d]
            syms = ", ".join(f"{t['symbol']}(₹{t['net']:+,.0f})" for t in sorted(ts, key=lambda x: x['net']))
            print(f"    {d}  ₹{dn:>+9,.0f}  [{len(ts)} trades]  {syms[:80]}")

        # ── Win/Loss streak ──────────────────────────────────────────────────
        print(f"\n{'─'*W}")
        print(f"  TOP-20 VOL FILTER — Trade-level win/loss distribution")
        print(f"{'─'*W}")
        wins   = [t['net'] for t in t20_filter if t['net'] > 0]
        losses = [t['net'] for t in t20_filter if t['net'] <= 0]
        if wins:
            print(f"  Winners: {len(wins)} trades | avg ₹{sum(wins)/len(wins):+,.0f} | "
                  f"max ₹{max(wins):+,.0f} | min ₹{min(wins):+,.0f}")
        if losses:
            print(f"  Losers:  {len(losses)} trades | avg ₹{sum(losses)/len(losses):+,.0f} | "
                  f"max ₹{max(losses):+,.0f} | min ₹{min(losses):+,.0f}")
        if wins and losses:
            rr = abs(sum(wins)/len(wins)) / abs(sum(losses)/len(losses))
            print(f"  Risk/Reward ratio: {rr:.2f}×  (avg win / avg loss)")

    print(f"\n{'='*W}")
    print(f"  ⚠️  TSL {TRAILING_SL_PCT}% | Window {ALERT_START_TIME}–{EXIT_TIME} | Charges: Zerodha F&O")
    print(f"  Vol filter: C-1≥{VOL_C1_MIN}× (touch candle spike) AND C-2<{VOL_C2_MAX}× (quiet before)")
    print(f"{'='*W}")


if __name__ == "__main__":
    run()
