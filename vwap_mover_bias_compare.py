#!/usr/bin/env python3
"""
Bias Strategy Comparison Backtest
==================================
Compares two bias methods for the VWAP Mover strategy:
  A) Static H3  — 9:15 candle close vs open, set once for the whole day
  B) Dynamic    — re-evaluated every 30 min using Nifty price vs intraday VWAP

Uses Config C (Hybrid TSL 0.3%→0.5%) throughout as the base strategy.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ── Parameters ─────────────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
ALERT_START_TIME         = "10:00"
EXIT_TIME                = "15:20"
MAX_TRADES_PER_STOCK     = 1

TSL_INIT  = 0.30
TSL_TRAIL = 0.50

BIAS_RECHECK_MINUTES = 30    # dynamic bias re-evaluation interval

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"
# ───────────────────────────────────────────────────────────────────────────────


def load_lot_sizes() -> Dict[str, int]:
    try:
        with open(LOT_SIZES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def compute_charges(entry: float, exit_p: float, lot: int, direction: str) -> float:
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


def compute_vwap(candles: List[Dict]) -> Optional[float]:
    if len(candles) < 2:
        return None
    cum_pv = cum_vol = 0.0
    for i, c in enumerate(candles):
        vol_delta = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv  += c['price'] * vol_delta
        cum_vol += vol_delta
    return cum_pv / cum_vol if cum_vol > 0 else None


def get_exit_trailing_sl(
    candles: List[Dict], entry_ts: str, entry_price: float,
    direction: str, sl_pct: float, exit_ts: str, trail_pct: float,
) -> Tuple[Optional[float], str, str]:
    initial_sl = entry_price * (1 - sl_pct/100) if direction == "LONG" else entry_price * (1 + sl_pct/100)
    sl = initial_sl
    peak = trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak: peak = p
            sl = max(initial_sl, peak * (1 - trail_pct/100))
            if p <= sl:
                return sl, c['timestamp'], "TSL"
        else:
            if p < trough: trough = p
            sl = min(initial_sl, trough * (1 + trail_pct/100))
            if p >= sl:
                return sl, c['timestamp'], "TSL"
    visible = [c for c in candles if c['timestamp'] <= exit_ts]
    eod = visible[-1]['price'] if visible else None
    return eod, exit_ts, "EOD"


# ── Bias helpers ────────────────────────────────────────────────────────────────

def h3_bias(nifty_candles: List[Dict], date: str) -> Optional[str]:
    """Static H3: 9:15 candle close vs day open."""
    first_ts = f"{date} 09:15:00"
    first = [c for c in nifty_candles if c['timestamp'] == first_ts]
    if first:
        c0 = first[0]
        return "LONG" if c0['price'] >= c0['open'] else "SHORT"
    if nifty_candles:
        c0 = nifty_candles[0]
        return "LONG" if c0['price'] >= c0['open'] else "SHORT"
    return None


def dynamic_bias_at(nifty_candles: List[Dict], ts_str: str) -> Optional[str]:
    """
    Dynamic: Nifty price vs intraday VWAP at a given timestamp.
    Falls back to Nifty price vs day open if volume data is unavailable.
    """
    relevant = [c for c in nifty_candles if c['timestamp'] <= ts_str]
    if len(relevant) < 2:
        return None

    # Try VWAP (requires non-zero volume)
    total_vol = sum(c.get('volume') or 0 for c in relevant)
    if total_vol > 0:
        vwap = compute_vwap(relevant)
        if vwap:
            return "LONG" if relevant[-1]['price'] >= vwap else "SHORT"

    # Fallback: price vs day open (from first candle's open field)
    day_open = relevant[0].get('open')
    if day_open and day_open > 0:
        return "LONG" if relevant[-1]['price'] >= day_open else "SHORT"

    return None


def build_dynamic_bias_schedule(
    nifty_candles: List[Dict], date: str
) -> Dict[str, Optional[str]]:
    """
    Build a map of {HH:MM → bias} for every 30-min slot from ALERT_START_TIME to EXIT_TIME.
    This is what the live monitor would see at each re-check.
    """
    schedule: Dict[str, Optional[str]] = {}
    start = datetime.strptime(f"{date} {ALERT_START_TIME}", "%Y-%m-%d %H:%M")
    end   = datetime.strptime(f"{date} {EXIT_TIME}",        "%Y-%m-%d %H:%M")
    slot  = start
    while slot <= end:
        ts_str = slot.strftime("%Y-%m-%d %H:%M:00")
        schedule[slot.strftime("%H:%M")] = dynamic_bias_at(nifty_candles, ts_str)
        slot += timedelta(minutes=BIAS_RECHECK_MINUTES)
    return schedule


def get_current_dynamic_bias(
    bias_schedule: Dict[str, Optional[str]],
    ts_str: str,
    initial_h3: Optional[str],
) -> Optional[str]:
    """
    Return the most recent dynamic bias at or before ts_str.
    Falls back to H3 if no dynamic slot has fired yet.
    """
    hhmm = ts_str[11:16]
    last_bias = initial_h3
    for slot_time in sorted(bias_schedule.keys()):
        if slot_time <= hhmm:
            last_bias = bias_schedule[slot_time] or last_bias
        else:
            break
    return last_bias


# ── Core backtest ───────────────────────────────────────────────────────────────

def backtest_day(
    date: str,
    prev_close: Dict[str, float],
    all_candles: Dict[str, List[Dict]],
    nifty_candles: List[Dict],
    timestamps: List[str],
    lot_sizes: Dict[str, int],
    bias_mode: str,           # "static" or "dynamic"
    initial_h3: Optional[str],
) -> List[Dict]:
    alert_start = f"{date} {ALERT_START_TIME}:00"
    exit_ts     = f"{date} {EXIT_TIME}:00"

    # Pre-build dynamic schedule if needed
    bias_schedule = (build_dynamic_bias_schedule(nifty_candles, date)
                     if bias_mode == "dynamic" else {})

    cooldown:    Dict[str, datetime] = {}
    trade_count: Dict[str, int]      = defaultdict(int)
    trades:      List[Dict]          = []

    for ts_str in timestamps:
        if ts_str < alert_start or ts_str > exit_ts:
            continue
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

        # Current bias
        if bias_mode == "dynamic":
            market_bias = get_current_dynamic_bias(bias_schedule, ts_str, initial_h3)
        else:
            market_bias = initial_h3

        for rank, (symbol, pct_change, price) in enumerate(top10, 1):
            if trade_count[symbol] >= MAX_TRADES_PER_STOCK:
                continue
            if symbol in cooldown:
                if (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                    continue

            candles_so_far = [c for c in all_candles.get(symbol, []) if c['timestamp'] <= ts_str]
            vwap = compute_vwap(candles_so_far)
            if vwap is None:
                continue
            if abs(price - vwap) / vwap * 100 > VWAP_TOUCH_THRESHOLD_PCT:
                continue

            trade_dir = "LONG" if pct_change >= 0 else "SHORT"
            if market_bias and market_bias != trade_dir:
                continue

            lot = lot_sizes.get(symbol, 1)
            exit_price, exit_at, reason = get_exit_trailing_sl(
                all_candles.get(symbol, []), ts_str, price, trade_dir,
                TSL_INIT, exit_ts, TSL_TRAIL,
            )
            if exit_price is None:
                cooldown[symbol] = ts
                trade_count[symbol] += 1
                continue

            pnl_ps = (exit_price - price) if trade_dir == "LONG" else (price - exit_price)
            gross  = pnl_ps * lot
            chg    = compute_charges(price, exit_price, lot, trade_dir)
            net    = gross - chg

            trades.append({
                'date': date, 'time': ts_str, 'rank': rank,
                'symbol': symbol, 'pct_change': pct_change,
                'trade_dir': trade_dir, 'entry_price': price,
                'exit_price': exit_price, 'exit_reason': reason,
                'lot_size': lot, 'gross_pnl': gross, 'net_pnl': net,
                'bias_at_entry': market_bias,
            })
            cooldown[symbol] = ts
            trade_count[symbol] += 1

    return trades


def summarise(all_trades: List[Dict], all_dates: List[str]) -> Dict:
    valid   = [t for t in all_trades if t['net_pnl'] is not None]
    winners = [t for t in valid if t['net_pnl'] > 0]
    losers  = [t for t in valid if t['net_pnl'] <= 0]

    day_nets: Dict[str, float] = {}
    for t in valid:
        day_nets[t['date']] = day_nets.get(t['date'], 0) + t['net_pnl']

    cum = peak = max_dd = 0.0
    for d in all_dates:
        cum  += day_nets.get(d, 0)
        peak  = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    return {
        'trades':   len(valid),
        'win_rate': len(winners)/len(valid)*100 if valid else 0,
        'gross':    sum(t['gross_pnl'] for t in valid),
        'net':      sum(t['net_pnl']   for t in valid),
        'avg_day':  sum(day_nets.values()) / len(all_dates) if all_dates else 0,
        'max_dd':   max_dd,
        'green':    sum(1 for v in day_nets.values() if v > 0),
        'red':      sum(1 for v in day_nets.values() if v < 0),
        'avg_win':  sum(t['net_pnl'] for t in winners)/len(winners) if winners else 0,
        'avg_los':  sum(t['net_pnl'] for t in losers) /len(losers)  if losers  else 0,
        'best':     max(valid, key=lambda t: t['net_pnl']) if valid else None,
        'worst':    min(valid, key=lambda t: t['net_pnl']) if valid else None,
        'day_nets': day_nets,
    }


def run():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates = [r['d'] for r in cur.fetchall()]

    # prev_close per date
    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for i, date in enumerate(all_dates):
        if i == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = all_dates[i-1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp = (SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp)=?)
                  AND date(timestamp)=?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}

    # Nifty candles per date
    nifty_by_date: Dict[str, List[Dict]] = {}
    for date in all_dates:
        cur.execute("""
            SELECT timestamp, price, open, volume FROM nifty_quotes
            WHERE date(timestamp)=? ORDER BY timestamp ASC
        """, (date,))
        nifty_by_date[date] = [dict(r) for r in cur.fetchall()]
    conn.close()

    # H3 bias per date (static)
    h3_by_date = {d: h3_bias(nifty_by_date[d], d) for d in all_dates}

    # Track bias changes per day for the dynamic version
    bias_changes_by_date: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)  # date → [(slot, old, new)]

    trades_static:  List[Dict] = []
    trades_dynamic: List[Dict] = []

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
            if sym not in candles: candles[sym] = []
            candles[sym].append({'timestamp': r['timestamp'], 'price': r['price'], 'volume': r['volume']})
        conn.close()

        if not timestamps:
            continue

        initial_h3   = h3_by_date[date]
        nifty_candles = nifty_by_date[date]

        # Record bias changes for dynamic mode
        bias_schedule = build_dynamic_bias_schedule(nifty_candles, date)
        prev_b = initial_h3
        for slot in sorted(bias_schedule.keys()):
            b = bias_schedule[slot] or prev_b
            if b != prev_b:
                bias_changes_by_date[date].append((slot, prev_b, b))
                prev_b = b

        ts_static  = backtest_day(date, prev_close_by_date[date], candles, nifty_candles,
                                   timestamps, lot_sizes, "static",  initial_h3)
        ts_dynamic = backtest_day(date, prev_close_by_date[date], candles, nifty_candles,
                                   timestamps, lot_sizes, "dynamic", initial_h3)
        trades_static.extend(ts_static)
        trades_dynamic.extend(ts_dynamic)

    ss = summarise(trades_static,  all_dates)
    sd = summarise(trades_dynamic, all_dates)

    W = 120
    print("=" * W)
    print(f"BIAS STRATEGY COMPARISON  |  {len(all_dates)} trading days: {all_dates[0]} → {all_dates[-1]}")
    print(f"  Strategy: VWAP Mover + Hybrid TSL (0.3%→0.5%)  |  Alert start: {ALERT_START_TIME}")
    print(f"  Static : H3 — 9:15 candle close vs open, fixed all day")
    print(f"  Dynamic: H3 initial, then Nifty vs VWAP every {BIAS_RECHECK_MINUTES} min from {ALERT_START_TIME}")
    print("=" * W)

    # ── Day-by-day ────────────────────────────────────────────────────────────
    day_trades_s = defaultdict(list)
    day_trades_d = defaultdict(list)
    for t in trades_static:  day_trades_s[t['date']].append(t)
    for t in trades_dynamic: day_trades_d[t['date']].append(t)

    print(f"\n  {'Date':10}  {'H3':5}  "
          f"{'Tr':>2} {'W':>2} {'Net_Static':>11} {'Cum_S':>11}  |  "
          f"{'Tr':>2} {'W':>2} {'Net_Dynamic':>11} {'Cum_D':>11}  "
          f"{'Δ':>10}  Bias changes")
    sep = "  " + "-"*10 + "  " + "-"*5 + "  " + ("-"*2+" "*1)*2 + "-"*11 + " " + "-"*11 + "  |  " + ("-"*2+" "*1)*2 + "-"*11 + " " + "-"*11 + "  " + "-"*10
    print(sep)

    cum_s = cum_d = 0.0
    for date in all_dates:
        h3   = h3_by_date.get(date, "?") or "?"
        ts   = day_trades_s[date]
        td   = day_trades_d[date]
        ns   = sum(t['net_pnl'] for t in ts)
        nd   = sum(t['net_pnl'] for t in td)
        ws   = sum(1 for t in ts if t['net_pnl'] > 0)
        wd   = sum(1 for t in td if t['net_pnl'] > 0)
        cum_s += ns; cum_d += nd
        delta = nd - ns
        delta_str = f"{'▲' if delta>0 else ('▼' if delta<0 else '─')}₹{abs(delta):>+,.0f}"
        h3_icon = "🟢" if h3 == "LONG" else ("🔴" if h3 == "SHORT" else "⚪")
        di_s = "✅" if ns > 0 else ("⚪" if not ts else "❌")
        di_d = "✅" if nd > 0 else ("⚪" if not td else "❌")

        changes = bias_changes_by_date.get(date, [])
        changes_str = "  ".join(f"{slot} {o}→{n}" for slot, o, n in changes) if changes else ""

        print(f"  {date}  {h3_icon}{h3:5}  "
              f"{len(ts):>2} {ws:>2} {di_s}₹{ns:>+9,.0f} ₹{cum_s:>+10,.0f}  |  "
              f"{len(td):>2} {wd:>2} {di_d}₹{nd:>+9,.0f} ₹{cum_d:>+10,.0f}  "
              f"{delta_str:>10}  {changes_str}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * W)
    print(f"{'OVERALL COMPARISON':^{W}}")
    print("=" * W)

    rows = [
        ("Trades",           lambda s: str(s['trades'])),
        ("Win rate",         lambda s: f"{s['win_rate']:.1f}%"),
        ("Green / Red days", lambda s: f"{s['green']}✅ / {s['red']}❌"),
        ("Gross P&L",        lambda s: f"₹{s['gross']:>+,.0f}"),
        ("NET P&L",          lambda s: f"₹{s['net']:>+,.0f}"),
        ("Avg per day",      lambda s: f"₹{s['avg_day']:>+,.0f}"),
        ("Max drawdown",     lambda s: f"₹{s['max_dd']:>,.0f}"),
        ("Avg winner",       lambda s: f"₹{s['avg_win']:>+,.0f}"),
        ("Avg loser",        lambda s: f"₹{s['avg_los']:>+,.0f}"),
    ]

    for label, fn in rows:
        vs = fn(ss)
        vd = fn(sd)
        print(f"  {label:28}  Static H3: {vs:>18}    Dynamic: {vd:>18}")

    # Delta
    net_delta = sd['net'] - ss['net']
    arrow = "▲" if net_delta > 0 else "▼"
    print(f"\n  {'NET P&L difference':28}  Dynamic {arrow} ₹{abs(net_delta):>+,.0f} vs Static")
    print(f"  {'Avg/day difference':28}  Dynamic {arrow} ₹{abs(sd['avg_day']-ss['avg_day']):>+,.0f}/day vs Static")

    # Best/worst
    print()
    for label, key in [("Best trade", 'best'), ("Worst trade", 'worst')]:
        ts_t, td_t = ss[key], sd[key]
        s_str = f"{ts_t['date']} {ts_t['symbol']:12} ₹{ts_t['net_pnl']:>+,.0f}" if ts_t else "N/A"
        d_str = f"{td_t['date']} {td_t['symbol']:12} ₹{td_t['net_pnl']:>+,.0f}" if td_t else "N/A"
        print(f"  {label:28}  Static: {s_str:40}  Dynamic: {d_str}")

    # ── Bias flip summary ─────────────────────────────────────────────────────
    total_flips = sum(len(v) for v in bias_changes_by_date.values())
    print(f"\n{'─'*W}")
    print(f"  DYNAMIC BIAS FLIP SUMMARY  ({total_flips} flips across {len(bias_changes_by_date)} days)")
    print(f"{'─'*W}")
    print(f"  {'Date':10}  {'H3 Initial':12}  {'Flip at':8}  {'Change':14}  Static Net    Dynamic Net   Δ")
    print(f"  {'-'*10}  {'-'*12}  {'-'*8}  {'-'*14}  {'-'*12}  {'-'*12}  {'-'*10}")
    for date in all_dates:
        changes = bias_changes_by_date.get(date, [])
        if not changes:
            continue
        h3 = h3_by_date.get(date, "?") or "?"
        ns = sum(t['net_pnl'] for t in day_trades_s[date])
        nd = sum(t['net_pnl'] for t in day_trades_d[date])
        delta = nd - ns
        for i, (slot, old, new) in enumerate(changes):
            if i == 0:
                print(f"  {date}  {h3:12}  {slot:8}  {old}→{new:10}  "
                      f"₹{ns:>+10,.0f}  ₹{nd:>+10,.0f}  "
                      f"{'▲' if delta>0 else '▼'}₹{abs(delta):>+,.0f}")
            else:
                print(f"  {'':10}  {'':12}  {slot:8}  {old}→{new}")


if __name__ == "__main__":
    run()
