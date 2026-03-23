#!/usr/bin/env python3
"""
Confirmation Candle Backtest for VWAP Mover
============================================
Compares entry strategies with exact-candle confirmation:
  0  → Baseline:  Enter immediately at VWAP touch (candle T)
  N  → Enter at exactly T+N if that candle confirms direction vs VWAP
       (close > VWAP for LONG, close < VWAP for SHORT); else discard signal.

Tests N = 0 (baseline), 1, 2, 3, 4 across max_trades = 1, 2, 3, 4, 5.
Top 20 movers by % change.  Alert start: 10:00  |  Exit: 15:20  |  Candles: 1-min.
Data: last 30 trading days from central_quotes.db.
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ── Parameters ─────────────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT  = 0.15
ALERT_COOLDOWN_MINUTES    = 15
TOP_N                     = 20
ALERT_START_TIME          = "10:00"
EXIT_TIME                 = "15:20"
MAX_TRADES_PER_STOCK_LIST = [1, 2, 3, 4, 5]
CONFIRM_OFFSETS           = [0, 1, 2, 3, 4]       # 0=baseline, N=check at exactly T+N

TSL_INIT  = 0.30   # Hybrid C: initial SL from entry
TSL_TRAIL = 0.50   # Hybrid C: trailing ratchet from peak/trough

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
        vol_delta = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv  += c['price'] * vol_delta
        cum_vol += vol_delta
    return cum_pv / cum_vol if cum_vol > 0 else None


def get_exit_trailing_sl(
    candles: List[Dict], entry_ts: str, entry_price: float,
    direction: str, sl_pct: float, exit_ts: str, trail_pct: float,
) -> Tuple[Optional[float], str, str]:
    initial_sl = (entry_price * (1 - sl_pct / 100) if direction == "LONG"
                  else entry_price * (1 + sl_pct / 100))
    sl = initial_sl
    peak = trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak:
                peak = p
            sl = max(initial_sl, peak * (1 - trail_pct / 100))
            if p <= sl:
                return sl, c['timestamp'], "TSL"
        else:
            if p < trough:
                trough = p
            sl = min(initial_sl, trough * (1 + trail_pct / 100))
            if p >= sl:
                return sl, c['timestamp'], "TSL"
    visible = [c for c in candles if c['timestamp'] <= exit_ts]
    eod = visible[-1]['price'] if visible else None
    return eod, exit_ts, "EOD"


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


def backtest_day(
    date: str,
    prev_close: Dict[str, float],
    all_candles: Dict[str, List[Dict]],
    nifty_candles: List[Dict],
    timestamps: List[str],
    lot_sizes: Dict[str, int],
    market_bias: Optional[str],
    confirm_offset: int,   # 0=baseline; N=check at exactly T+N (one-shot)
    max_trades: int,
) -> Tuple[List[Dict], int]:
    """
    confirm_offset=0 : baseline — enter immediately at VWAP touch price.
    confirm_offset=N : wait exactly N candles; check direction at T+N;
                       enter if confirmed, else discard. One-shot check.
    Returns (trades, rejected_confirmations).
    """
    alert_start = f"{date} {ALERT_START_TIME}:00"
    exit_ts     = f"{date} {EXIT_TIME}:00"

    cooldown:    Dict[str, datetime] = {}
    trade_count: Dict[str, int]      = defaultdict(int)
    trades:      List[Dict]          = []
    rejected_confirmations           = 0

    # pending_signals: symbol → {signal_ts, vwap, direction, rank, pct_change, elapsed}
    pending_signals: Dict[str, Dict] = {}

    for ts_str in timestamps:
        if ts_str < alert_start or ts_str > exit_ts:
            continue
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

        # Snapshot: latest candle per symbol at ts_str
        latest: Dict[str, Dict] = {}
        for sym, candles in all_candles.items():
            visible = [c for c in candles if c['timestamp'] <= ts_str]
            if visible:
                latest[sym] = visible[-1]

        # ── Step 1: Advance pending signals; fire check at exactly T+N ───────
        if confirm_offset > 0:
            for sym in list(pending_signals.keys()):
                sig = pending_signals[sym]
                if ts_str <= sig['signal_ts']:
                    continue

                sig['elapsed'] += 1
                if sig['elapsed'] < confirm_offset:
                    continue  # not yet at T+N

                # Exactly at T+N — one-shot check
                confirmed = False
                if sym in latest:
                    price_now = latest[sym]['price']
                    direction = sig['direction']
                    confirmed = (
                        (direction == "LONG"  and price_now > sig['vwap']) or
                        (direction == "SHORT" and price_now < sig['vwap'])
                    )
                    if confirmed and trade_count[sym] < max_trades:
                        entry_price = price_now
                        lot = lot_sizes.get(sym, 1)
                        exit_price, exit_at, reason = get_exit_trailing_sl(
                            all_candles.get(sym, []), ts_str, entry_price,
                            direction, TSL_INIT, exit_ts, TSL_TRAIL,
                        )
                        if exit_price is not None:
                            pnl_ps = ((exit_price - entry_price) if direction == "LONG"
                                      else (entry_price - exit_price))
                            gross  = pnl_ps * lot
                            chg    = compute_charges(entry_price, exit_price, lot, direction)
                            net    = gross - chg
                            trades.append({
                                'date':        date,
                                'time':        ts_str,
                                'signal_ts':   sig['signal_ts'],
                                'rank':        sig['rank'],
                                'symbol':      sym,
                                'pct_change':  sig['pct_change'],
                                'trade_dir':   direction,
                                'entry_price': entry_price,
                                'exit_price':  exit_price,
                                'exit_reason': reason,
                                'lot_size':    lot,
                                'gross_pnl':   gross,
                                'charges':     chg,
                                'net_pnl':     net,
                            })
                        trade_count[sym] += 1
                    else:
                        rejected_confirmations += 1
                else:
                    rejected_confirmations += 1

                del pending_signals[sym]   # one-shot — remove regardless

        # ── Step 2: Detect new VWAP touches ─────────────────────────────────
        movers = []
        for sym, q in latest.items():
            if sym not in prev_close or prev_close[sym] <= 0:
                continue
            pct = (q['price'] - prev_close[sym]) / prev_close[sym] * 100
            movers.append((sym, pct, q['price']))
        movers.sort(key=lambda x: abs(x[1]), reverse=True)
        top_n = movers[:TOP_N]

        for rank, (symbol, pct_change, price) in enumerate(top_n, 1):
            if trade_count[symbol] >= max_trades:
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

            cooldown[symbol] = ts

            if confirm_offset == 0:
                lot = lot_sizes.get(symbol, 1)
                exit_price, exit_at, reason = get_exit_trailing_sl(
                    all_candles.get(symbol, []), ts_str, price, trade_dir,
                    TSL_INIT, exit_ts, TSL_TRAIL,
                )
                if exit_price is None:
                    trade_count[symbol] += 1
                    continue
                pnl_ps = ((exit_price - price) if trade_dir == "LONG"
                          else (price - exit_price))
                gross  = pnl_ps * lot
                chg    = compute_charges(price, exit_price, lot, trade_dir)
                net    = gross - chg
                trades.append({
                    'date':        date,
                    'time':        ts_str,
                    'signal_ts':   ts_str,
                    'rank':        rank,
                    'symbol':      symbol,
                    'pct_change':  pct_change,
                    'trade_dir':   trade_dir,
                    'entry_price': price,
                    'exit_price':  exit_price,
                    'exit_reason': reason,
                    'lot_size':    lot,
                    'gross_pnl':   gross,
                    'charges':     chg,
                    'net_pnl':     net,
                })
                trade_count[symbol] += 1
            else:
                if symbol not in pending_signals:
                    pending_signals[symbol] = {
                        'signal_ts':  ts_str,
                        'vwap':       vwap,
                        'direction':  trade_dir,
                        'rank':       rank,
                        'pct_change': pct_change,
                        'elapsed':    0,
                    }

    return trades, rejected_confirmations


def summarise(all_trades: List[Dict], all_dates: List[str]) -> Dict:
    valid   = [t for t in all_trades if t['net_pnl'] is not None]
    winners = [t for t in valid if t['net_pnl'] > 0]
    losers  = [t for t in valid if t['net_pnl'] <= 0]

    day_nets: Dict[str, float] = {}
    for t in valid:
        day_nets[t['date']] = day_nets.get(t['date'], 0) + t['net_pnl']

    cum = peak = max_dd = 0.0
    for d in all_dates:
        cum   += day_nets.get(d, 0)
        peak   = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    return {
        'trades':   len(valid),
        'win_rate': len(winners) / len(valid) * 100 if valid else 0,
        'gross':    sum(t['gross_pnl'] for t in valid),
        'charges':  sum(t['charges']   for t in valid),
        'net':      sum(t['net_pnl']   for t in valid),
        'avg_day':  sum(day_nets.values()) / len(all_dates) if all_dates else 0,
        'max_dd':   max_dd,
        'green':    sum(1 for v in day_nets.values() if v > 0),
        'red':      sum(1 for v in day_nets.values() if v < 0),
        'avg_win':  sum(t['net_pnl'] for t in winners) / len(winners) if winners else 0,
        'avg_los':  sum(t['net_pnl'] for t in losers)  / len(losers)  if losers  else 0,
        'day_nets': day_nets,
    }


def per_symbol_stats(trades: List[Dict]) -> Dict[str, Dict]:
    stats: Dict[str, Dict] = {}
    for t in trades:
        s = t['symbol']
        if s not in stats:
            stats[s] = {'trades': 0, 'wins': 0, 'gross': 0.0, 'charges': 0.0, 'net': 0.0}
        stats[s]['trades']  += 1
        stats[s]['wins']    += 1 if t['net_pnl'] > 0 else 0
        stats[s]['gross']   += t['gross_pnl']
        stats[s]['charges'] += t['charges']
        stats[s]['net']     += t['net_pnl']
    return stats


def print_day_table(
    all_dates: List[str],
    h3_by_date: Dict[str, Optional[str]],
    trades_base: List[Dict],
    trades_conf: List[Dict],
) -> None:
    day_base = defaultdict(list)
    day_conf = defaultdict(list)
    for t in trades_base: day_base[t['date']].append(t)
    for t in trades_conf: day_conf[t['date']].append(t)

    print(f"\n  {'Date':10}  {'H3':5}  "
          f"{'Tr':>2} {'W':>2} {'Net_Baseline':>13} {'Cum_B':>12}  |  "
          f"{'Tr':>2} {'W':>2} {'Net_Confirm':>13} {'Cum_C':>12}  {'Δ':>12}")
    print("  " + "-" * 10 + "  " + "-" * 5 + "  " +
          "-" * 2 + " " + "-" * 2 + " " + "-" * 13 + " " + "-" * 12 + "  |  " +
          "-" * 2 + " " + "-" * 2 + " " + "-" * 13 + " " + "-" * 12 + "  " + "-" * 12)

    cum_b = cum_c = 0.0
    for date in all_dates:
        h3   = h3_by_date.get(date) or "?"
        tb   = day_base[date]
        tc   = day_conf[date]
        nb   = sum(t['net_pnl'] for t in tb)
        nc   = sum(t['net_pnl'] for t in tc)
        wb   = sum(1 for t in tb if t['net_pnl'] > 0)
        wc   = sum(1 for t in tc if t['net_pnl'] > 0)
        cum_b += nb
        cum_c += nc
        delta = nc - nb

        h3_icon  = "🟢" if h3 == "LONG" else ("🔴" if h3 == "SHORT" else "⚪")
        di_b     = "✅" if nb > 0 else ("⚪" if not tb else "❌")
        di_c     = "✅" if nc > 0 else ("⚪" if not tc else "❌")
        delta_str = f"{'▲' if delta > 0 else ('▼' if delta < 0 else '─')}₹{abs(delta):>+,.0f}"

        print(f"  {date}  {h3_icon}{h3:5}  "
              f"{len(tb):>2} {wb:>2} {di_b}₹{nb:>+11,.0f} ₹{cum_b:>+11,.0f}  |  "
              f"{len(tc):>2} {wc:>2} {di_c}₹{nc:>+11,.0f} ₹{cum_c:>+11,.0f}  {delta_str:>12}")


def print_summary_comparison(
    sb: Dict, sc: Dict, rejected: int, label: str
) -> None:
    rows = [
        ("Trades",           lambda s: str(s['trades'])),
        ("Win rate",         lambda s: f"{s['win_rate']:.1f}%"),
        ("Green / Red days", lambda s: f"{s['green']}✅ / {s['red']}❌"),
        ("Gross P&L",        lambda s: f"₹{s['gross']:>+,.0f}"),
        ("Charges",          lambda s: f"₹{s['charges']:>,.0f}"),
        ("NET P&L",          lambda s: f"₹{s['net']:>+,.0f}"),
        ("Avg per day",      lambda s: f"₹{s['avg_day']:>+,.0f}"),
        ("Max drawdown",     lambda s: f"₹{s['max_dd']:>,.0f}"),
        ("Avg winner",       lambda s: f"₹{s['avg_win']:>+,.0f}"),
        ("Avg loser",        lambda s: f"₹{s['avg_los']:>+,.0f}"),
    ]
    W = 90
    print(f"\n  {'Metric':30}  {'Baseline':>20}    {'Confirmation':>20}")
    print("  " + "-" * 30 + "  " + "-" * 20 + "    " + "-" * 20)
    for lbl, fn in rows:
        vb = fn(sb)
        vc = fn(sc)
        better = ""
        if lbl in ("NET P&L", "Avg per day", "Win rate", "Avg winner"):
            # higher is better — compare numeric values
            try:
                nb = float(vb.replace("₹", "").replace(",", "").replace("%", "").strip())
                nc = float(vc.replace("₹", "").replace(",", "").replace("%", "").strip())
                better = " ◀" if nc > nb else (" ▶" if nb > nc else "")
            except ValueError:
                pass
        elif lbl in ("Max drawdown", "Charges"):
            # lower is better
            try:
                nb = float(vb.replace("₹", "").replace(",", "").strip())
                nc = float(vc.replace("₹", "").replace(",", "").strip())
                better = " ◀" if nc < nb else (" ▶" if nb < nc else "")
            except ValueError:
                pass
        print(f"  {lbl:30}  {vb:>20}    {vc:>20}{better}")
    net_delta = sc['net'] - sb['net']
    arrow = "▲" if net_delta > 0 else "▼"
    print(f"\n  Confirmation {arrow} ₹{abs(net_delta):>+,.0f} vs Baseline  "
          f"(signals filtered by confirmation: {rejected})")


def print_per_symbol(trades: List[Dict], label: str) -> None:
    stats = per_symbol_stats(trades)
    W = 75
    print(f"\n{'─' * W}")
    print(f"  PER-SYMBOL ({label}, sorted by net P&L)")
    print(f"{'─' * W}")
    print(f"  {'Symbol':14}  {'Tr':3}  {'Win%':6}  {'Gross':>11}  {'Chg':>8}  {'Net':>11}")
    print(f"  {'-'*14}  {'-'*3}  {'-'*6}  {'-'*11}  {'-'*8}  {'-'*11}")
    for sym, s in sorted(stats.items(), key=lambda x: x[1]['net'], reverse=True):
        icon = "✅" if s['net'] > 0 else "❌"
        pct  = s['wins'] / s['trades'] * 100 if s['trades'] else 0
        print(f"  {icon} {sym:14}  {s['trades']:3d}  {pct:5.0f}%  "
              f"₹{s['gross']:>+10,.0f}  ₹{s['charges']:>7,.0f}  ₹{s['net']:>+10,.0f}")


def run():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates = [r['d'] for r in cur.fetchall()]
    all_dates = all_dates[-30:]   # last 30 trading days

    # ── Per-date prev_close ──────────────────────────────────────────────────
    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates_full = [r['d'] for r in cur.fetchall()]

    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for i_full, date in enumerate(all_dates_full):
        if date not in all_dates:
            continue
        if i_full == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = all_dates_full[i_full - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp = (SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp)=?)
                  AND date(timestamp)=?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}

    # ── Nifty candles per date ───────────────────────────────────────────────
    nifty_by_date: Dict[str, List[Dict]] = {}
    for date in all_dates:
        cur.execute("""
            SELECT timestamp, price, open, volume FROM nifty_quotes
            WHERE date(timestamp)=? ORDER BY timestamp ASC
        """, (date,))
        nifty_by_date[date] = [dict(r) for r in cur.fetchall()]
    conn.close()

    h3_by_date = {d: h3_bias(nifty_by_date[d], d) for d in all_dates}

    # ── Run: 5 confirm_offsets × 5 max_trades = 25 combinations ─────────────
    # all_results[(offset, max_trades)] = {'trades': [...], 'rejected': int}
    all_results: Dict[Tuple[int, int], Dict] = {}

    # Cache candle data per date (avoid reloading 25 times)
    candles_by_date:    Dict[str, Dict[str, List[Dict]]] = {}
    timestamps_by_date: Dict[str, List[str]]              = {}

    for date in all_dates:
        market_open  = f"{date} 09:15:00"
        market_close = f"{date} 15:30:00"

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()

        cur.execute("""
            SELECT DISTINCT timestamp FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC
        """, (market_open, market_close))
        timestamps_by_date[date] = [r['timestamp'] for r in cur.fetchall()]

        cur.execute("""
            SELECT symbol, timestamp, price, volume FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ? ORDER BY symbol, timestamp ASC
        """, (market_open, market_close))
        candles: Dict[str, List[Dict]] = {}
        for r in cur.fetchall():
            sym = r['symbol']
            if sym not in candles:
                candles[sym] = []
            candles[sym].append({
                'timestamp': r['timestamp'],
                'price':     r['price'],
                'volume':    r['volume'],
            })
        conn.close()
        candles_by_date[date] = candles

    for max_trades in MAX_TRADES_PER_STOCK_LIST:
        for offset in CONFIRM_OFFSETS:
            trades_all:    List[Dict] = []
            total_rejected = 0

            for date in all_dates:
                if not timestamps_by_date[date]:
                    continue
                day_trades, rej = backtest_day(
                    date, prev_close_by_date[date], candles_by_date[date],
                    nifty_by_date[date], timestamps_by_date[date],
                    lot_sizes, h3_by_date[date],
                    confirm_offset=offset, max_trades=max_trades,
                )
                trades_all.extend(day_trades)
                total_rejected += rej

            all_results[(offset, max_trades)] = {
                'trades':   trades_all,
                'rejected': total_rejected,
            }

    # Pre-compute summaries
    sums: Dict[Tuple[int, int], Dict] = {
        k: summarise(v['trades'], all_dates) for k, v in all_results.items()
    }

    # ── Output ───────────────────────────────────────────────────────────────
    off_labels = ["Base", "T+1", "T+2", "T+3", "T+4"]
    mt_list    = MAX_TRADES_PER_STOCK_LIST
    off_list   = CONFIRM_OFFSETS

    col_w = 14
    row_w = 6
    W     = 10 + row_w + (col_w + 2) * len(mt_list) + 16

    def grid(title: str, fn_val, fn_best, higher_is_better: bool = True):
        """Print a grid: rows = confirm_offset, cols = max_trades."""
        print(f"\n  {title}")
        print(f"  {'Conf':>{row_w}}", end="")
        for mt in mt_list:
            print(f"  {('MT='+str(mt)):>{col_w}}", end="")
        print(f"  {'Row best':>10}")
        print("  " + "-" * row_w + ("  " + "-" * col_w) * len(mt_list) + "  " + "-" * 10)

        overall_best = max(
            ((o, mt) for o in off_list for mt in mt_list),
            key=lambda k: fn_best(sums[k]) * (1 if higher_is_better else -1),
        )

        for i, o in enumerate(off_list):
            lbl = off_labels[i]
            row_best_mt = max(mt_list,
                              key=lambda mt: fn_best(sums[(o, mt)]) * (1 if higher_is_better else -1))
            print(f"  {lbl:>{row_w}}", end="")
            for mt in mt_list:
                val = fn_val(sums[(o, mt)], all_results[(o, mt)])
                star = " ★" if (o, mt) == overall_best else (" ◀" if mt == row_best_mt else "")
                print(f"  {str(val)+star:>{col_w}}", end="")
            print(f"  MT={row_best_mt:>2}")

        # Column best row
        print(f"  {'ColBest':>{row_w}}", end="")
        for mt in mt_list:
            best_o = max(off_list,
                         key=lambda o: fn_best(sums[(o, mt)]) * (1 if higher_is_better else -1))
            print(f"  {off_labels[best_o]:>{col_w}}", end="")
        print()

    print("=" * W)
    print(f"CONFIRMATION CANDLE BACKTEST  (TOP {TOP_N} movers)  |  "
          f"{len(all_dates)} days: {all_dates[0]} → {all_dates[-1]}")
    print(f"  VWAP Mover + H3 bias + Hybrid TSL (0.3%→0.5%)  |  Alert: {ALERT_START_TIME}  |  1-min candles")
    print(f"  One-shot confirmation at exactly T+N  |  ★ = overall best combination")
    print("=" * W)

    grid("NET P&L  (★ = overall best)",
         lambda s, r: f"₹{s['net']:>+,.0f}",
         fn_best=lambda s: s['net'])

    grid("TRADES  (★ = fewest)",
         lambda s, r: str(s['trades']),
         fn_best=lambda s: -s['trades'],
         higher_is_better=False)

    grid("CHARGES  (★ = lowest)",
         lambda s, r: f"₹{s['charges']:>,.0f}",
         fn_best=lambda s: s['charges'],
         higher_is_better=False)

    grid("WIN RATE",
         lambda s, r: f"{s['win_rate']:.1f}%",
         fn_best=lambda s: s['win_rate'])

    grid("GREEN / RED DAYS",
         lambda s, r: f"{s['green']}✅/{s['red']}❌",
         fn_best=lambda s: s['green'] - s['red'])

    grid("MAX DRAWDOWN  (★ = lowest)",
         lambda s, r: f"₹{s['max_dd']:>,.0f}",
         fn_best=lambda s: s['max_dd'],
         higher_is_better=False)

    grid("AVG / DAY",
         lambda s, r: f"₹{s['avg_day']:>+,.0f}",
         fn_best=lambda s: s['avg_day'])

    grid("SIGNALS REJECTED",
         lambda s, r: str(r['rejected']) if r['rejected'] > 0 else "—",
         fn_best=lambda s: 0)

    # ── Summary: best offset per max_trades ──────────────────────────────────
    print(f"\n{'═' * W}")
    print(f"  BEST CONFIRMATION PER MAX_TRADES  (by NET P&L)")
    print(f"{'═' * W}")
    print(f"  {'MT':>4}  {'Best':>5}  {'Trades':>7}  {'Charges':>12}  {'Win%':>7}  "
          f"{'Green/Red':>10}  {'Max DD':>12}  {'Avg/day':>12}  {'NET P&L':>14}")
    print(f"  {'-'*4}  {'-'*5}  {'-'*7}  {'-'*12}  {'-'*7}  "
          f"{'-'*10}  {'-'*12}  {'-'*12}  {'-'*14}")
    for mt in mt_list:
        best_o = max(off_list, key=lambda o: sums[(o, mt)]['net'])
        s      = sums[(best_o, mt)]
        print(f"  {mt:>4}  {off_labels[best_o]:>5}  {s['trades']:>7}  "
              f"₹{s['charges']:>10,.0f}  {s['win_rate']:>6.1f}%  "
              f"{s['green']:>4}✅/{s['red']:<4}❌  ₹{s['max_dd']:>10,.0f}  "
              f"₹{s['avg_day']:>+10,.0f}  ₹{s['net']:>+12,.0f}")
    print()


if __name__ == "__main__":
    run()
