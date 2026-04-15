#!/usr/bin/env python3
"""
VWAP Mover Backtest — Approach Speed & Nifty Direction Filters
===============================================================
Window:  10:00 AM – 2:30 PM
Exit:    TSL 0.5% trailing, EOD fallback at 2:30 PM
No H3 Nifty bias filter. Last 30 trading days.

Configs compared:
  A: No filters (baseline)
  B: Approach speed filter  — skip if stock reached VWAP in < APPROACH_MIN consecutive candles
                               (fast drop/rise to VWAP = momentum continuation, not bounce)
  C: Nifty direction filter — skip LONG if last NIFTY_LOOKBACK Nifty candles are ALL falling
                               skip SHORT if last NIFTY_LOOKBACK Nifty candles are ALL rising
                               (tape working against the trade)
  D: Both filters combined

Approach speed logic:
  For LONG:  count consecutive down candles just before the touch
             < APPROACH_MIN → too fast a drop → likely breakdown → skip
  For SHORT: count consecutive up candles just before the touch
             < APPROACH_MIN → too fast a rise → likely breakout → skip

Nifty direction logic:
  At touch timestamp, look at Nifty's last NIFTY_LOOKBACK candles.
  If ALL of them move against the trade direction → Nifty tape is hostile → skip.
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

APPROACH_MIN             = 3     # skip if reached VWAP in < 3 consecutive candles
NIFTY_LOOKBACK           = 2     # all last N Nifty candles must be against direction to skip

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


def get_approach_candle_count(candles_so_far: List[Dict], direction: str) -> int:
    """
    Count consecutive candles moving toward VWAP just before the touch.
    LONG:  consecutive falling candles (price declining toward VWAP from above)
    SHORT: consecutive rising candles (price rising toward VWAP from below)
    Returns number of consecutive approach candles.
    """
    if len(candles_so_far) < 2:
        return APPROACH_MIN + 1  # not enough data → allow through

    prices = [c['price'] for c in candles_so_far]
    count  = 0

    if direction == "LONG":
        for i in range(len(prices) - 1, 0, -1):
            if prices[i] < prices[i - 1]:   # price falling toward VWAP
                count += 1
            else:
                break
    else:
        for i in range(len(prices) - 1, 0, -1):
            if prices[i] > prices[i - 1]:   # price rising toward VWAP
                count += 1
            else:
                break

    return count


def nifty_direction_ok(nifty_candles_so_far: List[Dict], direction: str, lookback: int) -> bool:
    """
    Returns False if Nifty tape is fully hostile to the trade direction.
    LONG:  all last `lookback` Nifty moves are DOWN → hostile → return False
    SHORT: all last `lookback` Nifty moves are UP   → hostile → return False
    Returns True (allow trade) if insufficient data or mixed Nifty direction.
    """
    if len(nifty_candles_so_far) < lookback + 1:
        return True  # not enough history → allow

    recent_prices = [c['price'] for c in nifty_candles_so_far[-(lookback + 1):]]

    if direction == "LONG":
        all_down = all(recent_prices[i] < recent_prices[i - 1] for i in range(1, len(recent_prices)))
        return not all_down
    else:
        all_up = all(recent_prices[i] > recent_prices[i - 1] for i in range(1, len(recent_prices)))
        return not all_up


def get_exit_trailing_sl(
    candles: List[Dict], entry_ts: str, entry_price: float,
    direction: str, sl_pct: float, exit_ts: str,
    target_price: Optional[float] = None,
) -> Tuple[Optional[float], str, str]:
    sl     = entry_price * (1 - sl_pct / 100) if direction == "LONG" else entry_price * (1 + sl_pct / 100)
    peak   = entry_price
    trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if target_price and p >= target_price:
                return target_price, c['timestamp'], "TARGET"
            if p > peak:
                peak = p
            sl = peak * (1 - sl_pct / 100)
            if p <= sl:
                return sl, c['timestamp'], "TSL"
        else:
            if target_price and p <= target_price:
                return target_price, c['timestamp'], "TARGET"
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
    nifty_candles: List[Dict],
    timestamps: List[str],
    lot_sizes: Dict[str, int],
    use_approach_filter: bool,
    use_nifty_filter: bool,
    fib_level: Optional[float] = None,
) -> Tuple[List[Dict], int, int]:
    alert_start = f"{date} {ALERT_START_TIME}:00"
    exit_ts     = f"{date} {EXIT_TIME}:00"

    cooldown:    Dict[str, datetime] = {}
    trade_count: Dict[str, int]      = defaultdict(int)
    last_top10:  List[str]           = []
    trades:      List[Dict]          = []
    skipped_approach = 0
    skipped_nifty    = 0

    for ts_str in timestamps:
        if ts_str > exit_ts:
            break
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

        # Nifty candles visible at this timestamp
        nifty_visible = [c for c in nifty_candles if c['timestamp'] <= ts_str]

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

            # ── Filter 1: Approach speed ───────────────────────────────────
            if use_approach_filter:
                approach_count = get_approach_candle_count(candles_so_far, trade_dir)
                if approach_count < APPROACH_MIN:
                    skipped_approach += 1
                    cooldown[symbol] = ts
                    continue

            # ── Filter 2: Nifty direction ──────────────────────────────────
            if use_nifty_filter:
                if not nifty_direction_ok(nifty_visible, trade_dir, NIFTY_LOOKBACK):
                    skipped_nifty += 1
                    cooldown[symbol] = ts
                    continue

            lot = lot_sizes.get(symbol, 1)
            if fib_level and pct_change:
                amplitude = abs(pct_change) / 100 * price
                target_price = (price + amplitude * fib_level if trade_dir == "LONG"
                                else price - amplitude * fib_level)
            else:
                target_price = None
            exit_price, exit_at, reason = get_exit_trailing_sl(
                all_candles.get(symbol, []), ts_str, price,
                trade_dir, TRAILING_SL_PCT, exit_ts,
                target_price=target_price,
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
                'approach_candles': get_approach_candle_count(candles_so_far, trade_dir),
            })
            cooldown[symbol] = ts
            trade_count[symbol] += 1

    return trades, skipped_approach, skipped_nifty


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
    target_trades = [t for t in valid if t['exit_reason'] == 'TARGET']
    target_wins   = [t for t in target_trades if t['net_pnl'] > 0]

    day_nets: Dict[str, float] = {}
    for t in valid:
        day_nets[t['date']] = day_nets.get(t['date'], 0) + t['net_pnl']
    green = sum(1 for v in day_nets.values() if v > 0)
    red   = sum(1 for v in day_nets.values() if v < 0)

    cum = peak_cum = max_dd = 0.0
    for date in all_dates:
        cum      += day_nets.get(date, 0)
        peak_cum  = max(peak_cum, cum)
        max_dd    = max(max_dd, peak_cum - cum)

    return {
        'trades': len(valid), 'winners': len(winners), 'losers': len(losers),
        'win_rate': len(winners) / len(valid) * 100 if valid else 0,
        'tsl_trades': len(tsl_trades), 'tsl_wins': len(tsl_wins),
        'eod_trades': len(eod_trades), 'eod_wins': len(eod_wins),
        'target_trades': len(target_trades), 'target_wins': len(target_wins),
        'gross': total_gross, 'charges': total_charges, 'net': total_net,
        'avg_winner': sum(t['net_pnl'] for t in winners) / len(winners) if winners else 0,
        'avg_loser':  sum(t['net_pnl'] for t in losers)  / len(losers)  if losers  else 0,
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
    all_dates = all_dates_in_db[-LAST_N_DAYS:]

    # Per-date prev_close
    print(f"Building per-date prev_close for last {LAST_N_DAYS} trading days...")
    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for date in all_dates:
        idx = all_dates_in_db.index(date)
        if idx == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = all_dates_in_db[idx - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp = (SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp) = ?)
                  AND date(timestamp) = ?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}

    # Nifty candles per date
    nifty_by_date: Dict[str, List[Dict]] = {}
    for date in all_dates:
        cur.execute("""
            SELECT timestamp, price FROM nifty_quotes
            WHERE date(timestamp) = ? ORDER BY timestamp ASC
        """, (date,))
        nifty_by_date[date] = [dict(r) for r in cur.fetchall()]
    conn.close()

    trades_a, trades_b, trades_c, trades_d = [], [], [], []
    skipped = defaultdict(int)

    FIB_LEVELS = [0.618, 1.0, 1.618]
    fib_trades: Dict[float, List[Dict]] = {fib: [] for fib in FIB_LEVELS}

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

        nifty = nifty_by_date.get(date, [])

        ta, _,  _  = backtest_day(date, prev_close_by_date[date], candles, nifty, timestamps, lot_sizes, False, False)
        tb, sa, _  = backtest_day(date, prev_close_by_date[date], candles, nifty, timestamps, lot_sizes, True,  False)
        tc, _,  sn = backtest_day(date, prev_close_by_date[date], candles, nifty, timestamps, lot_sizes, False, True)
        td, sa2,sn2= backtest_day(date, prev_close_by_date[date], candles, nifty, timestamps, lot_sizes, True,  True)

        trades_a.extend(ta);  trades_b.extend(tb)
        trades_c.extend(tc);  trades_d.extend(td)
        skipped['approach_b'] += sa;  skipped['nifty_c']    += sn
        skipped['approach_d'] += sa2; skipped['nifty_d']    += sn2

        for fib in FIB_LEVELS:
            tf, _, _ = backtest_day(date, prev_close_by_date[date], candles, nifty, timestamps, lot_sizes, False, False, fib_level=fib)
            fib_trades[fib].extend(tf)

    sa_ = summarise(trades_a, all_dates)
    sb_ = summarise(trades_b, all_dates)
    sc_ = summarise(trades_c, all_dates)
    sd_ = summarise(trades_d, all_dates)

    configs = [
        ("A: No filters",          sa_, trades_a, f"({sa_['trades']} trades)"),
        ("B: Approach speed",      sb_, trades_b, f"(skip <{APPROACH_MIN} candles, {sb_['trades']} trades)"),
        ("C: Nifty direction",     sc_, trades_c, f"(skip hostile {NIFTY_LOOKBACK}-candle Nifty, {sc_['trades']} trades)"),
        ("D: Both filters",        sd_, trades_d, f"({sd_['trades']} trades)"),
    ]

    W = 145
    print("=" * W)
    print(f"VWAP FILTER COMPARISON — Approach Speed & Nifty Direction | 10:00–14:30 | TSL 0.5% | Last {LAST_N_DAYS} days")
    print(f"  {len(all_dates)} trading days: {all_dates[0]} → {all_dates[-1]}")
    print(f"  B: skip if reached VWAP in < {APPROACH_MIN} consecutive candles")
    print(f"  C: skip if last {NIFTY_LOOKBACK} Nifty candles ALL move against trade direction")
    print("=" * W)

    # Day-by-day table
    print(f"\n  {'Date':10}  "
          f"{'Tr':>2} {'W':>2} {'Net_A':>10}  {'Cum_A':>10}  |  "
          f"{'Tr':>2} {'W':>2} {'Net_B':>10}  {'Cum_B':>10}  |  "
          f"{'Tr':>2} {'W':>2} {'Net_C':>10}  {'Cum_C':>10}  |  "
          f"{'Tr':>2} {'W':>2} {'Net_D':>10}  {'Cum_D':>10}")
    print(f"  {'-'*10}  " + (f"{'-'*2} {'-'*2} {'-'*10}  {'-'*10}  |  ") * 3 +
          f"{'-'*2} {'-'*2} {'-'*10}  {'-'*10}")

    cum_a = cum_b = cum_c = cum_d = 0.0
    day_a = defaultdict(list); day_b = defaultdict(list)
    day_c = defaultdict(list); day_d = defaultdict(list)
    for t in trades_a: day_a[t['date']].append(t)
    for t in trades_b: day_b[t['date']].append(t)
    for t in trades_c: day_c[t['date']].append(t)
    for t in trades_d: day_d[t['date']].append(t)

    for date in all_dates:
        ta_ = day_a[date]; tb_ = day_b[date]; tc_ = day_c[date]; td_ = day_d[date]
        na = sum(t['net_pnl'] for t in ta_); nb = sum(t['net_pnl'] for t in tb_)
        nc = sum(t['net_pnl'] for t in tc_); nd = sum(t['net_pnl'] for t in td_)
        wa = sum(1 for t in ta_ if t['net_pnl'] > 0); wb = sum(1 for t in tb_ if t['net_pnl'] > 0)
        wc = sum(1 for t in tc_ if t['net_pnl'] > 0); wd = sum(1 for t in td_ if t['net_pnl'] > 0)
        cum_a += na; cum_b += nb; cum_c += nc; cum_d += nd

        def di(trs, net): return "✅" if net > 0 else ("⚪" if not trs else "❌")
        print(f"  {date}  "
              f"{len(ta_):>2} {wa:>2} {di(ta_,na)}₹{na:>+8,.0f}  ₹{cum_a:>+9,.0f}  |  "
              f"{len(tb_):>2} {wb:>2} {di(tb_,nb)}₹{nb:>+8,.0f}  ₹{cum_b:>+9,.0f}  |  "
              f"{len(tc_):>2} {wc:>2} {di(tc_,nc)}₹{nc:>+8,.0f}  ₹{cum_c:>+9,.0f}  |  "
              f"{len(td_):>2} {wd:>2} {di(td_,nd)}₹{nd:>+8,.0f}  ₹{cum_d:>+9,.0f}")

    # Overall summary
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

    best_net = max(s['net'] for _, s, _, _ in configs)
    for label, fn in rows:
        vals  = [fn(s) for _, s, _, _ in configs]
        marks = ["", "", "", ""]
        if label in ("NET P&L", "Avg per day", "Win rate", "Max drawdown"):
            if label == "Max drawdown":
                best_val = min(s['max_dd'] for _, s, _, _ in configs)
                for i, (_, s, _, _) in enumerate(configs):
                    if s['max_dd'] == best_val:
                        marks[i] = " ◀"
            else:
                best_val = max(fn(s) for _, s, _, _ in configs)
                for i, (_, s, _, _) in enumerate(configs):
                    if fn(s) == best_val:
                        marks[i] = " ◀"
        parts = [f"{lbl:25} {hint:38} {v:>14}{mk}"
                 for (lbl, _, _, hint), v, mk in zip(configs, vals, marks)]
        print(f"  {label:22}  " + "  |  ".join(
            f"{fn(s):>14}  {hint}{marks[i]}"
            for i, (_, s, _, hint) in enumerate(configs)
        ))

    print()
    for key, idx in [("Best trade", 'best'), ("Worst trade", 'worst')]:
        parts = [f"{lbl[:1]}: {s[idx]['date']} {s[idx]['symbol']:10} ₹{s[idx]['net_pnl']:>+,.0f}"
                 if s[idx] else f"{lbl[:1]}: N/A"
                 for lbl, s, _, _ in configs]
        print(f"  {key:22}  " + "  |  ".join(parts))

    # Skipped signals
    print(f"\n{'─'*W}")
    print(f"  SIGNALS SKIPPED BY FILTER")
    print(f"{'─'*W}")
    total_signals = sa_['trades'] + skipped['approach_b']
    print(f"  B (approach speed <{APPROACH_MIN} candles):   {skipped['approach_b']:4d} skipped  "
          f"({skipped['approach_b']/max(total_signals,1)*100:.1f}% of all touches)")
    print(f"  C (Nifty hostile {NIFTY_LOOKBACK}-candle):    {skipped['nifty_c']:4d} skipped  "
          f"({skipped['nifty_c']/max(sa_['trades']+skipped['nifty_c'],1)*100:.1f}% of all touches)")
    print(f"  D (both): approach={skipped['approach_d']}  nifty={skipped['nifty_d']}  "
          f"total unique≈{skipped['approach_d']+skipped['nifty_d']}")

    # Approach speed distribution (from baseline trades)
    print(f"\n{'─'*W}")
    print(f"  APPROACH SPEED DISTRIBUTION (baseline trades, grouped by candle count)")
    print(f"{'─'*W}")
    approach_buckets: Dict[int, Dict] = {}
    for t in trades_a:
        k = min(t.get('approach_candles', 0), 10)
        if k not in approach_buckets:
            approach_buckets[k] = {'trades': 0, 'wins': 0, 'net': 0.0}
        approach_buckets[k]['trades'] += 1
        approach_buckets[k]['wins']   += 1 if t['net_pnl'] > 0 else 0
        approach_buckets[k]['net']    += t['net_pnl']
    print(f"  {'Candles':>8}  {'Trades':>7}  {'Win%':>7}  {'Net P&L':>12}  {'Avg/trade':>10}")
    print(f"  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*12}  {'-'*10}")
    for k in sorted(approach_buckets.keys()):
        b = approach_buckets[k]
        wr = b['wins'] / b['trades'] * 100 if b['trades'] else 0
        avg = b['net'] / b['trades'] if b['trades'] else 0
        flag = "  ← FILTERED (B)" if k < APPROACH_MIN else ""
        print(f"  {k:>8}  {b['trades']:>7}  {wr:>6.1f}%  ₹{b['net']:>+10,.0f}  ₹{avg:>+8,.0f}{flag}")

    # Per-symbol for best config
    best_lbl, best_s, best_tlist, _ = max(configs, key=lambda x: x[1]['net'])
    sym_stats: Dict[str, Dict] = {}
    for t in best_tlist:
        s = t['symbol']
        if s not in sym_stats:
            sym_stats[s] = {'trades': 0, 'wins': 0, 'gross': 0.0, 'charges': 0.0, 'net': 0.0}
        sym_stats[s]['trades']  += 1
        sym_stats[s]['wins']    += 1 if t['net_pnl'] > 0 else 0
        sym_stats[s]['gross']   += t['gross_pnl']
        sym_stats[s]['charges'] += t['charges']['total']
        sym_stats[s]['net']     += t['net_pnl']

    print(f"\n{'─'*W}")
    print(f"  PER-SYMBOL  ({best_lbl}, sorted by net P&L)")
    print(f"{'─'*W}")
    print(f"  {'Symbol':12}  {'Tr':3}  {'Win%':6}  {'Gross':>10}  {'Chg':>7}  {'Net':>10}")
    print(f"  {'-'*12}  {'-'*3}  {'-'*6}  {'-'*10}  {'-'*7}  {'-'*10}")
    for sym, s in sorted(sym_stats.items(), key=lambda x: x[1]['net'], reverse=True):
        icon = "✅" if s['net'] > 0 else "❌"
        print(f"  {icon} {sym:12}  {s['trades']:3d}  {s['wins']/s['trades']*100:5.0f}%  "
              f"₹{s['gross']:>+9,.0f}  ₹{s['charges']:>6,.0f}  ₹{s['net']:>+9,.0f}")

    print(f"\n⚠️  Charges: ₹40 brokerage | STT 0.02% sell | Exchange 0.00188% | SEBI | Stamp | GST 18%")
    print(f"   Approach speed filter: skip if < {APPROACH_MIN} consecutive approach candles at VWAP touch")
    print(f"   Nifty direction filter: skip if last {NIFTY_LOOKBACK} Nifty candles ALL against trade direction")

    # ── Fibonacci target comparison ───────────────────────────────────────────
    fib_summaries = {
        None:  sa_,
        0.618: summarise(fib_trades[0.618], all_dates),
        1.0:   summarise(fib_trades[1.0],   all_dates),
        1.618: summarise(fib_trades[1.618], all_dates),
    }
    FIB_ALL    = [None, 0.618, 1.0, 1.618]
    FIB_LABELS = ["No Target (baseline)", "0.618×", "1.000×", "1.618×"]

    print(f"\n{'='*W}")
    print(f"{'FIBONACCI TARGET COMPARISON (baseline config, no filters)':^{W}}")
    print(f"{'='*W}")
    print(f"  {'Fib Level':<22} {'Trades':>6}  {'Win%':>6}  {'Avg W':>8}  {'Avg L':>8}  {'Net PnL':>10}  {'TARGET exits':>13}")
    print(f"  {'-'*22} {'-'*6}  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*10}  {'-'*13}")
    for fib, lbl in zip(FIB_ALL, FIB_LABELS):
        s = fib_summaries[fib]
        tgt = s['target_trades']
        tgt_pct = tgt / s['trades'] * 100 if s['trades'] else 0
        tgt_str = f"{tgt} ({tgt_pct:.0f}%)" if fib is not None else "—"
        print(f"  {lbl:<22} {s['trades']:>6}  {s['win_rate']:>5.1f}%  "
              f"₹{s['avg_winner']:>+7,.0f}  ₹{s['avg_loser']:>+7,.0f}  "
              f"₹{s['net']:>+9,.0f}  {tgt_str:>13}")


if __name__ == "__main__":
    run()
