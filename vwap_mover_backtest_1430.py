#!/usr/bin/env python3
"""
VWAP Mover Backtest — 10:00 AM to 2:30 PM window
=================================================
Entry: 10:00 AM – 2:30 PM only (no positions before or after)
Exit:  EOD at 2:30 PM  OR  TSL 0.5% (whichever fires first)
No H3 Nifty bias filter (matches live monitor — informational only, trades not blocked)
Last 30 trading days from DB.

Compares:
  A: EOD-only (pure 2:30 PM exit, no trailing SL)
  B: TSL 0.5% trailing SL, EOD fallback at 2:30 PM
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
EXIT_TIME                = "14:30"     # no new entries AND exit all positions here
MAX_TRADES_PER_STOCK     = 2
TRAILING_SL_PCT          = 0.50
LAST_N_DAYS              = 30

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"
# ────────────────────────────────────────────────────────────────────────────


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


def get_exit_eod(
    candles: List[Dict], entry_ts: str, exit_ts: str,
) -> Tuple[Optional[float], str, str]:
    """Pure EOD exit at exit_ts."""
    eod = get_price_at(candles, exit_ts)
    return eod, exit_ts, "EOD"


def get_exit_trailing_sl(
    candles: List[Dict], entry_ts: str, entry_price: float,
    direction: str, sl_pct: float, exit_ts: str,
) -> Tuple[Optional[float], str, str]:
    """TSL exit — ratchets with peak/trough, EOD fallback."""
    if direction == "LONG":
        sl = entry_price * (1 - sl_pct / 100)
    else:
        sl = entry_price * (1 + sl_pct / 100)
    peak   = entry_price
    trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak:
                peak = p
            sl = peak * (1 - sl_pct / 100)
            if p <= sl:
                return sl, c['timestamp'], "TSL"
        else:
            if p < trough:
                trough = p
            sl = trough * (1 + sl_pct / 100)
            if p >= sl:
                return sl, c['timestamp'], "TSL"
    eod = get_price_at(candles, exit_ts)
    return eod, exit_ts, "EOD"


def backtest_day(
    date: str,
    prev_close: Dict[str, float],
    all_candles: Dict[str, List[Dict]],
    timestamps: List[str],
    lot_sizes: Dict[str, int],
    use_tsl: bool,
) -> List[Dict]:
    alert_start = f"{date} {ALERT_START_TIME}:00"
    exit_ts     = f"{date} {EXIT_TIME}:00"

    cooldown:    Dict[str, datetime] = {}
    trade_count: Dict[str, int]      = defaultdict(int)
    trades:      List[Dict]          = []
    last_top10:  List[str]           = []

    for ts_str in timestamps:
        if ts_str > exit_ts:
            break   # no new entries or checks after 14:30
        if ts_str < alert_start:
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
        top10_symbols = [s for s, _, _ in top10]
        if top10_symbols != last_top10:
            last_top10 = top10_symbols

        for rank, (symbol, pct_change, price) in enumerate(top10, 1):
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
            lot = lot_sizes.get(symbol, 1)

            if use_tsl:
                exit_price, exit_at, reason = get_exit_trailing_sl(
                    all_candles.get(symbol, []), ts_str, price, trade_dir,
                    TRAILING_SL_PCT, exit_ts,
                )
            else:
                exit_price, exit_at, reason = get_exit_eod(
                    all_candles.get(symbol, []), ts_str, exit_ts,
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
                'exit_price': exit_price, 'exit_at': exit_at,
                'exit_reason': reason,
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
    all_dates_in_db = [r['d'] for r in cur.fetchall()]

    # Last 30 trading days
    all_dates = all_dates_in_db[-LAST_N_DAYS:]

    # Per-date prev_close from last candle of previous trading day
    print(f"Building per-date prev_close for last {LAST_N_DAYS} trading days...")
    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for i, date in enumerate(all_dates):
        idx_in_full = all_dates_in_db.index(date)
        if idx_in_full == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = all_dates_in_db[idx_in_full - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp = (SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp) = ?)
                  AND date(timestamp) = ?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}
    conn.close()

    trades_a: List[Dict] = []
    trades_b: List[Dict] = []

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
            if sym not in candles:
                candles[sym] = []
            candles[sym].append({'timestamp': r['timestamp'], 'price': r['price'], 'volume': r['volume']})
        conn.close()

        if not timestamps:
            continue

        ta = backtest_day(date, prev_close_by_date[date], candles, timestamps, lot_sizes, use_tsl=False)
        tb = backtest_day(date, prev_close_by_date[date], candles, timestamps, lot_sizes, use_tsl=True)
        trades_a.extend(ta)
        trades_b.extend(tb)

    sa = summarise(trades_a, all_dates)
    sb = summarise(trades_b, all_dates)

    W = 110
    print("=" * W)
    print(f"VWAP MOVER — 10:00 AM to 2:30 PM | No H3 filter | Max {MAX_TRADES_PER_STOCK}/stock")
    print(f"  {len(all_dates)} trading days: {all_dates[0]} → {all_dates[-1]}")
    print(f"  A: EOD-only (pure 2:30 PM exit)    B: TSL 0.5% trailing, EOD fallback at 2:30 PM")
    print("=" * W)

    print(f"\n  {'Date':10}  "
          f"{'Tr':>2} {'W':>2} {'Net_A':>10}  {'Cum_A':>11}  |  "
          f"{'Tr':>2} {'W':>2} {'Net_B':>10}  {'Cum_B':>11}")
    sep = f"  {'-'*10}  " + (f"{'-'*2} {'-'*2} {'-'*10}  {'-'*11}  |  ") + f"{'-'*2} {'-'*2} {'-'*10}  {'-'*11}"
    print(sep)

    cum_a = cum_b = 0.0
    day_trades_a = defaultdict(list)
    day_trades_b = defaultdict(list)
    for t in trades_a: day_trades_a[t['date']].append(t)
    for t in trades_b: day_trades_b[t['date']].append(t)

    for date in all_dates:
        ta    = day_trades_a[date]
        tb    = day_trades_b[date]
        net_a = sum(t['net_pnl'] for t in ta)
        net_b = sum(t['net_pnl'] for t in tb)
        win_a = sum(1 for t in ta if t['net_pnl'] > 0)
        win_b = sum(1 for t in tb if t['net_pnl'] > 0)
        cum_a += net_a
        cum_b += net_b

        def di(trades, net): return "✅" if net > 0 else ("⚪" if len(trades) == 0 else "❌")
        print(f"  {date}  "
              f"{len(ta):>2} {win_a:>2} {di(ta,net_a)}₹{net_a:>+8,.0f}  ₹{cum_a:>+10,.0f}  |  "
              f"{len(tb):>2} {win_b:>2} {di(tb,net_b)}₹{net_b:>+8,.0f}  ₹{cum_b:>+10,.0f}")

    print("\n" + "=" * W)
    print(f"{'OVERALL SUMMARY':^{W}}")
    print("=" * W)

    rows = [
        ("Trades",           lambda s: str(s['trades'])),
        ("Win rate",         lambda s: f"{s['win_rate']:.1f}%"),
        ("TSL exits (wins)", lambda s: f"{s['tsl_trades']}({s['tsl_wins']})"),
        ("EOD exits (wins)", lambda s: f"{s['eod_trades']}({s['eod_wins']})"),
        ("Green / Red days", lambda s: f"{s['green']}/{s['red']}"),
        ("Gross P&L",        lambda s: f"₹{s['gross']:>+,.0f}"),
        ("Total charges",    lambda s: f"₹{s['charges']:>,.0f}"),
        ("NET P&L",          lambda s: f"₹{s['net']:>+,.0f}"),
        ("Avg per day",      lambda s: f"₹{s['avg_day']:>+,.0f}"),
        ("Max drawdown",     lambda s: f"₹{s['max_dd']:>,.0f}"),
        ("Avg winner",       lambda s: f"₹{s['avg_winner']:>+,.0f}"),
        ("Avg loser",        lambda s: f"₹{s['avg_loser']:>+,.0f}"),
    ]
    for label, fn in rows:
        print(f"  {label:28}  A(EOD-only): {fn(sa):>18}    B(TSL 0.5%): {fn(sb):>18}")

    print()
    for key, sa_t, sb_t in [("Best trade",  sa['best'],  sb['best']),
                              ("Worst trade", sa['worst'], sb['worst'])]:
        a_str = f"{sa_t['date']} {sa_t['symbol']:12} ₹{sa_t['net_pnl']:>+,.0f}" if sa_t else "N/A"
        b_str = f"{sb_t['date']} {sb_t['symbol']:12} ₹{sb_t['net_pnl']:>+,.0f}" if sb_t else "N/A"
        print(f"  {key:28}  A: {a_str:40}  B: {b_str}")

    # ── Per-symbol breakdown for better config ──────────────────────────────
    best_trades, best_label = (trades_a, "A: EOD-only") if sa['net'] >= sb['net'] else (trades_b, "B: TSL 0.5%")
    sym_stats: Dict[str, Dict] = {}
    for t in best_trades:
        s = t['symbol']
        if s not in sym_stats:
            sym_stats[s] = {'trades': 0, 'wins': 0, 'gross': 0.0, 'charges': 0.0, 'net': 0.0}
        sym_stats[s]['trades']  += 1
        sym_stats[s]['wins']    += 1 if t['net_pnl'] > 0 else 0
        sym_stats[s]['gross']   += t['gross_pnl']
        sym_stats[s]['charges'] += t['charges']['total']
        sym_stats[s]['net']     += t['net_pnl']

    print(f"\n{'─'*W}")
    print(f"  PER-SYMBOL  ({best_label}, sorted by net P&L)")
    print(f"{'─'*W}")
    print(f"  {'Symbol':12}  {'Tr':3}  {'Win%':6}  {'Gross':>10}  {'Chg':>7}  {'Net':>10}")
    print(f"  {'-'*12}  {'-'*3}  {'-'*6}  {'-'*10}  {'-'*7}  {'-'*10}")
    for sym, s in sorted(sym_stats.items(), key=lambda x: x[1]['net'], reverse=True):
        icon = "✅" if s['net'] > 0 else "❌"
        print(f"  {icon} {sym:12}  {s['trades']:3d}  {s['wins']/s['trades']*100:5.0f}%  "
              f"₹{s['gross']:>+9,.0f}  ₹{s['charges']:>6,.0f}  ₹{s['net']:>+9,.0f}")

    print(f"\n⚠️  Charges: Brokerage ₹40 | STT 0.02% sell | Exchange 0.00188% | SEBI | Stamp | GST 18%")


if __name__ == "__main__":
    run()
