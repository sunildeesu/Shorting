#!/usr/bin/env python3
"""
Start-time Comparison: 9:30 AM vs 10:00 AM alert start
Uses same strategy as vwap_mover_backtest_30d.py (H3 Nifty bias filter)
Runs all 3 TSL configs (A/B/C) for each start time and compares.
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ── Fixed parameters ─────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
EXIT_TIME                = "15:20"
MAX_TRADES_PER_STOCK     = 1

TSL_A       = 0.30
TSL_B       = 0.50
TSL_C_INIT  = 0.30
TSL_C_TRAIL = 0.50

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"

START_TIMES = ["09:30", "10:00"]   # ← the two configs we compare
# ─────────────────────────────────────────────────────────────────────────────


def load_lot_sizes() -> Dict[str, int]:
    try:
        with open(LOT_SIZES_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load lot sizes ({e}) — defaulting to 1")
        return {}


def compute_charges(entry: float, exit_p: float, lot: int, direction: str) -> Dict:
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
    return {
        'brokerage': brok, 'stt': stt, 'exchange': exc,
        'sebi': sebi, 'stamp': stamp, 'gst': gst,
        'total': brok + stt + exc + sebi + stamp + gst,
    }


def compute_vwap(candles: List[Dict]) -> Optional[float]:
    if len(candles) < 2:
        return None
    cum_pv = cum_vol = 0.0
    for i, c in enumerate(candles):
        vol_delta = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv += c['price'] * vol_delta
        cum_vol += vol_delta
    return cum_pv / cum_vol if cum_vol > 0 else None


def get_price_at(candles: List[Dict], ts_str: str) -> Optional[float]:
    visible = [c for c in candles if c['timestamp'] <= ts_str]
    return visible[-1]['price'] if visible else None


def get_exit_trailing_sl(
    candles: List[Dict], entry_ts: str, entry_price: float,
    direction: str, sl_pct: float, exit_ts: str,
    trail_pct: Optional[float] = None,
) -> Tuple[Optional[float], str, str]:
    ratchet_pct = trail_pct if trail_pct is not None else sl_pct
    if direction == "LONG":
        initial_sl = entry_price * (1 - sl_pct / 100)
        sl = initial_sl
    else:
        initial_sl = entry_price * (1 + sl_pct / 100)
        sl = initial_sl
    peak   = entry_price
    trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak:
                peak = p
            sl = max(initial_sl, peak * (1 - ratchet_pct / 100))
            if p <= sl:
                return sl, c['timestamp'], "TSL"
        else:
            if p < trough:
                trough = p
            sl = min(initial_sl, trough * (1 + ratchet_pct / 100))
            if p >= sl:
                return sl, c['timestamp'], "TSL"
    eod = get_price_at(candles, exit_ts)
    return eod, exit_ts, "EOD"


def nifty_bias(nifty_candles: List[Dict], date: str) -> Optional[str]:
    first_ts = f"{date} 09:15:00"
    first    = [c for c in nifty_candles if c['timestamp'] == first_ts]
    if first:
        c0 = first[0]
        return "LONG" if c0['price'] >= c0['open'] else "SHORT"
    if nifty_candles:
        c0 = nifty_candles[0]
        return "LONG" if c0['price'] >= c0['open'] else "SHORT"
    return None


def backtest_day(
    date: str, alert_start_time: str,
    prev_close: Dict[str, float],
    all_candles: Dict[str, List[Dict]],
    timestamps: List[str],
    lot_sizes: Dict[str, int],
    market_bias: Optional[str],
    sl_pct: float,
    trail_pct: Optional[float] = None,
) -> List[Dict]:
    alert_start = f"{date} {alert_start_time}:00"
    exit_ts     = f"{date} {EXIT_TIME}:00"

    cooldown:    Dict[str, datetime] = {}
    trade_count: Dict[str, int]      = defaultdict(int)
    trades:      List[Dict]          = []

    for ts_str in timestamps:
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

        latest: Dict[str, Dict] = {}
        for sym, candles in all_candles.items():
            visible = [c for c in candles if c['timestamp'] <= ts_str]
            if visible:
                latest[sym] = visible[-1]

        movers = []
        for sym, q in latest.items():
            if sym not in prev_close or prev_close[sym] <= 0:
                continue
            pct = (q['price'] - prev_close[sym]) / prev_close[sym] * 100
            movers.append((sym, pct, q['price']))
        movers.sort(key=lambda x: abs(x[1]), reverse=True)
        top10 = movers[:TOP_N]

        for rank, (symbol, pct_change, price) in enumerate(top10, 1):
            if ts_str < alert_start:
                continue
            if trade_count[symbol] >= MAX_TRADES_PER_STOCK:
                continue

            candles_so_far = [c for c in all_candles.get(symbol, []) if c['timestamp'] <= ts_str]
            vwap = compute_vwap(candles_so_far)
            if vwap is None:
                continue

            if abs(price - vwap) / vwap * 100 > VWAP_TOUCH_THRESHOLD_PCT:
                continue

            if symbol in cooldown:
                if (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                    continue

            trade_dir = "LONG" if pct_change >= 0 else "SHORT"
            if market_bias and market_bias != trade_dir:
                continue

            lot = lot_sizes.get(symbol, 1)
            exit_price, exit_at, reason = get_exit_trailing_sl(
                all_candles.get(symbol, []), ts_str, price, trade_dir, sl_pct, exit_ts,
                trail_pct=trail_pct,
            )
            if exit_price is None:
                cooldown[symbol] = ts
                trade_count[symbol] += 1
                continue

            pnl_ps = (exit_price - price) if trade_dir == "LONG" else (price - exit_price)
            gross  = pnl_ps * lot
            chg    = compute_charges(price, exit_price, lot, trade_dir)
            net    = gross - chg['total']

            trades.append({
                'date': date, 'time': ts_str, 'rank': rank,
                'symbol': symbol, 'pct_change': pct_change,
                'entry_price': price, 'vwap': vwap,
                'trade_dir': trade_dir, 'lot_size': lot,
                'exit_price': exit_price, 'exit_reason': reason,
                'pnl_per_share': pnl_ps, 'gross_pnl': gross,
                'charges': chg, 'net_pnl': net,
            })
            cooldown[symbol] = ts
            trade_count[symbol] += 1

    return trades


def summarise(all_trades: List[Dict], all_dates: List[str]) -> Dict:
    valid         = [t for t in all_trades if t['net_pnl'] is not None]
    total_gross   = sum(t['gross_pnl']       for t in valid)
    total_charges = sum(t['charges']['total'] for t in valid)
    total_net     = sum(t['net_pnl']         for t in valid)
    winners       = [t for t in valid if t['net_pnl'] > 0]
    losers        = [t for t in valid if t['net_pnl'] <= 0]
    tsl_trades    = [t for t in valid if t['exit_reason'] == 'TSL']
    tsl_wins      = [t for t in tsl_trades if t['net_pnl'] > 0]
    eod_trades    = [t for t in valid if t['exit_reason'] == 'EOD']
    eod_wins      = [t for t in eod_trades if t['net_pnl'] > 0]

    day_nets: Dict[str, float] = {}
    for t in valid:
        day_nets[t['date']] = day_nets.get(t['date'], 0) + t['net_pnl']
    green = sum(1 for v in day_nets.values() if v > 0)
    red   = sum(1 for v in day_nets.values() if v < 0)

    cum = peak = max_dd = 0.0
    for date in all_dates:
        cum  += day_nets.get(date, 0)
        peak  = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    return {
        'trades': len(valid), 'winners': len(winners), 'losers': len(losers),
        'win_rate': len(winners)/len(valid)*100 if valid else 0,
        'tsl_trades': len(tsl_trades), 'tsl_wins': len(tsl_wins),
        'eod_trades': len(eod_trades), 'eod_wins': len(eod_wins),
        'gross': total_gross, 'charges': total_charges, 'net': total_net,
        'avg_winner': sum(t['net_pnl'] for t in winners)/len(winners) if winners else 0,
        'avg_loser':  sum(t['net_pnl'] for t in losers)/len(losers)   if losers  else 0,
        'best':  max(valid, key=lambda t: t['net_pnl']) if valid else None,
        'worst': min(valid, key=lambda t: t['net_pnl']) if valid else None,
        'green': green, 'red': red,
        'avg_day': total_net / len(all_dates) if all_dates else 0,
        'max_dd': max_dd,
        'day_nets': day_nets,
    }


def run():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates = [r['d'] for r in cur.fetchall()]

    print("Building per-date prev_close...")
    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for i, date in enumerate(all_dates):
        if i == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = all_dates[i - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp = (SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp) = ?)
                  AND date(timestamp) = ?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}

    nifty_by_date: Dict[str, List[Dict]] = {}
    for date in all_dates:
        cur.execute("""
            SELECT timestamp, price, open FROM nifty_quotes
            WHERE date(timestamp) = ? ORDER BY timestamp ASC
        """, (date,))
        nifty_by_date[date] = [dict(r) for r in cur.fetchall()]
    conn.close()

    biases = {date: nifty_bias(nifty_by_date[date], date) for date in all_dates}
    bull_days = sum(1 for b in biases.values() if b == "LONG")
    bear_days = sum(1 for b in biases.values() if b == "SHORT")
    print(f"Nifty H3 bias: {bull_days} BULL days, {bear_days} BEAR days out of {len(all_dates)}\n")

    # ── Run all 6 combinations (2 start times × 3 TSL configs) ──────────────
    # results[start_time] = {'A': trades, 'B': trades, 'C': trades}
    results = {st: {'A': [], 'B': [], 'C': []} for st in START_TIMES}

    for date in all_dates:
        market_open  = f"{date} 09:15:00"
        market_close = f"{date} 15:30:00"

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
            if sym not in candles:
                candles[sym] = []
            candles[sym].append({'timestamp': r['timestamp'], 'price': r['price'], 'volume': r['volume']})
        conn.close()

        if not timestamps:
            continue

        bias = biases[date]
        for st in START_TIMES:
            ta = backtest_day(date, st, prev_close_by_date[date], candles, timestamps, lot_sizes, bias, TSL_A)
            tb = backtest_day(date, st, prev_close_by_date[date], candles, timestamps, lot_sizes, bias, TSL_B)
            tc = backtest_day(date, st, prev_close_by_date[date], candles, timestamps, lot_sizes, bias, TSL_C_INIT, trail_pct=TSL_C_TRAIL)
            results[st]['A'].extend(ta)
            results[st]['B'].extend(tb)
            results[st]['C'].extend(tc)

    # ── Summarise ────────────────────────────────────────────────────────────
    summaries = {}
    for st in START_TIMES:
        summaries[st] = {
            'A': summarise(results[st]['A'], all_dates),
            'B': summarise(results[st]['B'], all_dates),
            'C': summarise(results[st]['C'], all_dates),
        }

    W = 140
    # ── Day-by-day: best config (C) for each start time ───────────────────────
    for st in START_TIMES:
        trades_c = results[st]['C']
        day_t = defaultdict(list)
        for t in trades_c:
            day_t[t['date']].append(t)

        print("=" * W)
        print(f"  START {st}  —  Config C (Hybrid 0.3%→0.5%)  |  {len(all_dates)} days: {all_dates[0]} → {all_dates[-1]}")
        print("=" * W)
        print(f"  {'Date':10}  {'Bias':5}  {'Tr':>2}  {'W':>2}  {'Net':>10}  {'Cumulative':>12}")
        print(f"  {'-'*10}  {'-'*5}  {'-'*2}  {'-'*2}  {'-'*10}  {'-'*12}")
        cum = 0.0
        for date in all_dates:
            bias_str   = biases.get(date, "N/A") or "N/A"
            bias_icon  = "🟢" if bias_str == "LONG" else ("🔴" if bias_str == "SHORT" else "⚪")
            td         = day_t[date]
            net        = sum(t['net_pnl'] for t in td)
            wins       = sum(1 for t in td if t['net_pnl'] > 0)
            cum       += net
            di         = "✅" if net > 0 else ("⚪" if len(td) == 0 else "❌")
            print(f"  {date}  {bias_icon}{bias_str:5}  {len(td):>2}  {wins:>2}  {di}₹{net:>+8,.0f}  ₹{cum:>+10,.0f}")
        print()

    # ── Head-to-head comparison table ────────────────────────────────────────
    print("=" * W)
    print(f"{'HEAD-TO-HEAD: 09:30 vs 10:00  (all TSL configs)':^{W}}")
    print("=" * W)

    header = (f"  {'Metric':28}  "
              f"{'09:30 A(0.3%)':>14}  {'09:30 B(0.5%)':>14}  {'09:30 C(hybrid)':>16}  ||  "
              f"{'10:00 A(0.3%)':>14}  {'10:00 B(0.5%)':>14}  {'10:00 C(hybrid)':>16}  ||  "
              f"{'Δ C (9:30-10:00)':>16}")
    print(header)
    print("  " + "-" * (W - 2))

    def fv(s, key):
        if   key == 'trades':   return str(s['trades'])
        elif key == 'win_rate': return f"{s['win_rate']:.1f}%"
        elif key == 'tsl':      return f"{s['tsl_trades']}({s['tsl_wins']})"
        elif key == 'eod':      return f"{s['eod_trades']}({s['eod_wins']})"
        elif key == 'days':     return f"{s['green']}✅/{s['red']}❌"
        elif key == 'gross':    return f"₹{s['gross']:>+,.0f}"
        elif key == 'charges':  return f"₹{s['charges']:>,.0f}"
        elif key == 'net':      return f"₹{s['net']:>+,.0f}"
        elif key == 'avg_day':  return f"₹{s['avg_day']:>+,.0f}"
        elif key == 'max_dd':   return f"₹{s['max_dd']:>,.0f}"
        elif key == 'avg_winner':  return f"₹{s['avg_winner']:>+,.0f}"
        elif key == 'avg_loser':   return f"₹{s['avg_loser']:>+,.0f}"
        return "?"

    rows = [
        ("Trades",           'trades'),
        ("Win rate",         'win_rate'),
        ("TSL exits (wins)", 'tsl'),
        ("EOD exits (wins)", 'eod'),
        ("Green / Red days", 'days'),
        ("Gross P&L",        'gross'),
        ("Total charges",    'charges'),
        ("NET P&L",          'net'),
        ("Avg per day",      'avg_day'),
        ("Max drawdown",     'max_dd'),
        ("Avg winner",       'avg_winner'),
        ("Avg loser",        'avg_loser'),
    ]

    for label, key in rows:
        s930 = summaries['09:30']
        s1000 = summaries['10:00']
        # Delta for config C on net/avg_day
        if key in ('net', 'avg_day', 'gross', 'max_dd', 'avg_winner', 'avg_loser'):
            delta = s930['C'][key] - s1000['C'][key]
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "─")
            delta_str = f"{arrow} ₹{abs(delta):>+,.0f}"
        elif key == 'win_rate':
            delta = s930['C']['win_rate'] - s1000['C']['win_rate']
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "─")
            delta_str = f"{arrow} {delta:>+.1f}%"
        elif key == 'trades':
            delta = s930['C']['trades'] - s1000['C']['trades']
            delta_str = f"{'▲' if delta>0 else '▼'} {delta:>+d}"
        else:
            delta_str = "—"

        print(f"  {label:28}  "
              f"{fv(s930['A'],key):>14}  {fv(s930['B'],key):>14}  {fv(s930['C'],key):>16}  ||  "
              f"{fv(s1000['A'],key):>14}  {fv(s1000['B'],key):>14}  {fv(s1000['C'],key):>16}  ||  "
              f"{delta_str:>16}")

    # ── Best/worst per start time (config C) ──────────────────────────────────
    print()
    print("─" * W)
    print("  BEST / WORST TRADES  (Config C — Hybrid)")
    print("─" * W)
    for label, key in [("Best trade", 'best'), ("Worst trade", 'worst')]:
        for st in START_TIMES:
            t = summaries[st]['C'][key]
            if t:
                print(f"  {st} {label:12}  {t['date']}  {t['symbol']:12}  {t['trade_dir']:5}  ₹{t['net_pnl']:>+,.0f}")
            else:
                print(f"  {st} {label:12}  N/A")
    print()

    # ── Trade-count extra trades that 9:30 brings in vs 10:00 ─────────────────
    print("─" * W)
    print("  EXTRA TRADES from starting at 09:30 (Config C — trades in 09:30 but not in 10:00)")
    print("─" * W)
    keys_1000 = {(t['date'], t['symbol'], t['time']) for t in results['10:00']['C']}
    extra = [t for t in results['09:30']['C'] if (t['date'], t['symbol'], t['time']) not in keys_1000]
    if extra:
        print(f"  {'Date':10}  {'Time':8}  {'Symbol':12}  {'Dir':5}  {'Entry':>8}  {'Exit':>8}  {'Net':>10}  Reason")
        print(f"  {'-'*10}  {'-'*8}  {'-'*12}  {'-'*5}  {'-'*8}  {'-'*8}  {'-'*10}  {'-'*6}")
        extra_net = 0.0
        for t in sorted(extra, key=lambda x: x['time']):
            di = "✅" if t['net_pnl'] > 0 else "❌"
            extra_net += t['net_pnl']
            print(f"  {t['date']}  {t['time'][11:19]}  {t['symbol']:12}  {t['trade_dir']:5}  "
                  f"₹{t['entry_price']:>7,.1f}  ₹{t['exit_price']:>7,.1f}  "
                  f"{di}₹{t['net_pnl']:>+8,.0f}  {t['exit_reason']}")
        print(f"\n  Extra trades: {len(extra)}  |  Net contribution: ₹{extra_net:>+,.0f}")
    else:
        print("  No extra trades (same trades in both windows)")
    print()


if __name__ == "__main__":
    run()
