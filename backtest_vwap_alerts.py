#!/usr/bin/env python3
"""
Backtest VWAP alert flow for the last 5 trading days.
Shows every event: touch detected → vol filter → pending → confirmed entry → exit.
Config: C1≥2.0 + T+3 confirm + exit 13:00 (current live monitor settings)
"""

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

# ── Config (matches live monitor) ────────────────────────────────────────────
TOP_N               = 10
VWAP_TOUCH_PCT      = 0.15
C1_MIN              = 2.0
CONFIRM_OFFSET      = 3
ENTRY_START         = "10:00"
EXIT_TIME           = "13:00"
TRAILING_SL_PCT     = 0.50
MAX_TRADES_PER_STOCK = 2
ALERT_COOLDOWN_MIN  = 15
LAST_N_DAYS         = 5
# --offset N  skips the most recent N days (use 5 to test previous week)
# --days N    override LAST_N_DAYS (e.g. --days=69 for full history)
# --weekly    print compact weekly summary table instead of day-by-day events
OFFSET_DAYS         = 0

DB_PATH         = "data/central_quotes.db"
LOT_SIZES_FILE  = "data/lot_sizes.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_vwap(candles):
    if len(candles) < 2:
        return None
    cum_pv = cum_vol = 0.0
    for i, c in enumerate(candles):
        dv = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv  += c['price'] * dv
        cum_vol += dv
    return cum_pv / cum_vol if cum_vol > 0 else None

def c1_ratio(candles):
    if len(candles) < 3:
        return 0.0
    deltas = [float(c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume']))
              for i, c in enumerate(candles)]
    baseline = deltas[:-1]
    avg = sum(baseline) / len(baseline) if baseline else 0
    return round(deltas[-1] / avg, 2) if avg > 0 else 0.0

def get_exit_price(candles, entry_ts, entry_price, direction, exit_ts):
    """TSL exit or hard exit at exit_ts."""
    in_trade = False
    peak = trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts:
            continue
        price = c['price']
        if direction == "LONG":
            if price > peak:
                peak = price
            sl = peak * (1 - TRAILING_SL_PCT / 100)
            if price <= sl or c['timestamp'] >= exit_ts:
                return price, ("TSL" if price <= sl else "EOD")
        else:
            if price < trough:
                trough = price
            sl = trough * (1 + TRAILING_SL_PCT / 100)
            if price >= sl or c['timestamp'] >= exit_ts:
                return price, ("TSL" if price >= sl else "EOD")
    return None, None


def run():
    try:
        lot_sizes = json.load(open(LOT_SIZES_FILE))
    except Exception:
        lot_sizes = {}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Parse CLI flags
    offset = OFFSET_DAYS
    n_days = LAST_N_DAYS
    weekly_mode = False
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg.startswith("--offset="):
            offset = int(arg.split("=")[1])
        elif arg == "--offset" and i + 1 < len(sys.argv):
            offset = int(sys.argv[i + 1])
        elif arg.startswith("--days="):
            n_days = int(arg.split("=")[1])
        elif arg == "--days" and i + 1 < len(sys.argv):
            n_days = int(sys.argv[i + 1])
        elif arg == "--weekly":
            weekly_mode = True

    # Last N trading days (with optional offset to go back further)
    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d DESC")
    all_dates_desc = [r['d'] for r in cur.fetchall()]
    window_start = offset
    window_end   = offset + n_days
    dates     = list(reversed(all_dates_desc[window_start:window_end]))
    date_set  = set(dates)
    prev_date = all_dates_desc[window_end] if len(all_dates_desc) > window_end else None

    print(f"Backtesting {n_days} days: {dates[0]} → {dates[-1]}")
    print(f"Config: TOP_N={TOP_N} | C1≥{C1_MIN} | T+{CONFIRM_OFFSET} | exit {EXIT_TIME} | TSL {TRAILING_SL_PCT}%\n")

    # Prev close
    cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
    day0_prev = {r['symbol']: float(r['prev_close']) for r in cur.fetchall()}

    # Load last price for all days that serve as prev_close (prev_date + each backtest day)
    prev_days_needed = set()
    if prev_date:
        prev_days_needed.add(prev_date)
    for d in dates[:-1]:          # each day in window is prev_close for the next
        prev_days_needed.add(d)

    last_price_by_sym_date = {}
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
        for r in cur.fetchall():
            last_price_by_sym_date[(r['symbol'], r['d'])] = float(r['price'])

    prev_close_by_date = {}
    for i, date in enumerate(dates):
        prev_d = prev_date if i == 0 else dates[i - 1]
        if prev_d:
            prev_close_by_date[date] = {
                sym: last_price_by_sym_date[(sym, prev_d)]
                for sym in day0_prev
                if (sym, prev_d) in last_price_by_sym_date
            }
        else:
            prev_close_by_date[date] = day0_prev

    # Candles bulk load
    ts_start = f"{dates[0]} 09:15:00"
    ts_end   = f"{dates[-1]} 14:30:00"
    cur.execute("""
        SELECT symbol, timestamp, price, volume FROM stock_quotes
        WHERE timestamp >= ? AND timestamp <= ?
          AND time(timestamp) >= '09:15:00' AND time(timestamp) <= '14:30:00'
        ORDER BY symbol, timestamp ASC
    """, (ts_start, ts_end))
    candles_by_date = {d: {} for d in dates}
    ts_set_by_date  = {d: set() for d in dates}
    for r in cur.fetchall():
        d = r['timestamp'][:10]
        if d not in date_set: continue
        s = r['symbol']
        candles_by_date[d].setdefault(s, []).append({
            'timestamp': r['timestamp'], 'price': float(r['price']),
            'volume': float(r['volume'] or 0)
        })
        ts_set_by_date[d].add(r['timestamp'])
    conn.close()

    timestamps_by_date = {d: sorted(ts_set_by_date[d]) for d in dates}

    # ── Per-day simulation ────────────────────────────────────────────────────
    total_touches = total_vol_fail = total_queued = total_confirm_fail = total_trades = 0
    total_wins = total_net = 0.0
    weekly_rows = []   # for --weekly mode: one dict per calendar week

    for date in dates:
        prev_close  = prev_close_by_date[date]
        all_candles = candles_by_date[date]
        timestamps  = timestamps_by_date[date]
        exit_ts     = f"{date} {EXIT_TIME}:00"
        alert_start = f"{date} {ENTRY_START}:00"

        sorted_cl   = {sym: sorted(cl, key=lambda c: c['timestamp'])
                       for sym, cl in all_candles.items()}
        sym_cursor  = {sym: 0 for sym in sorted_cl}
        candle_hist = {sym: [] for sym in sorted_cl}
        latest_price = {}
        price_at_ts  = {}

        cooldown     = {}
        trade_count  = defaultdict(int)
        pending      = {}   # sym → {vwap, direction, elapsed, touch_ts, c1}
        day_events   = []

        for ts_str in timestamps:
            if ts_str > exit_ts:
                break
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
            ts_hm = ts_str[11:16]

            for sym, cl in sorted_cl.items():
                idx = sym_cursor[sym]
                while idx < len(cl) and cl[idx]['timestamp'] <= ts_str:
                    candle_hist[sym].append(cl[idx])
                    latest_price[sym] = cl[idx]['price']
                    price_at_ts[(sym, cl[idx]['timestamp'])] = cl[idx]['price']
                    idx += 1
                sym_cursor[sym] = idx

            # Process pending confirmations
            for sym in list(pending.keys()):
                sig = pending[sym]
                sig['elapsed'] += 1
                if sig['elapsed'] < CONFIRM_OFFSET:
                    continue
                price_now = price_at_ts.get((sym, ts_str), 0)
                if price_now > 0:
                    direction = sig['direction']
                    confirmed = ((direction == "LONG"  and price_now > sig['vwap']) or
                                 (direction == "SHORT" and price_now < sig['vwap']))
                    if confirmed and trade_count[sym] < MAX_TRADES_PER_STOCK:
                        ep, reason = get_exit_price(
                            sorted_cl.get(sym, []), ts_str, price_now, direction, exit_ts)
                        if ep is not None:
                            gross = ((ep - price_now) if direction == "LONG"
                                     else (price_now - ep)) * lot_sizes.get(sym, 1)
                            day_events.append({
                                'type': 'TRADE', 'time': ts_hm, 'sym': sym,
                                'dir': direction, 'entry': price_now, 'exit': ep,
                                'reason': reason, 'gross': gross,
                                'c1': sig['c1'], 'vwap': sig['vwap'],
                                'touch_time': sig['touch_ts'],
                            })
                            trade_count[sym] += 1
                    else:
                        day_events.append({
                            'type': 'CONFIRM_FAIL', 'time': ts_hm, 'sym': sym,
                            'dir': sig['direction'], 'price': price_now,
                            'vwap': sig['vwap'], 'confirmed': confirmed,
                            'touch_time': sig['touch_ts'],
                        })
                del pending[sym]

            if ts_str < alert_start:
                continue

            movers = []
            for sym, price in latest_price.items():
                pc = prev_close.get(sym, 0)
                if pc <= 0: continue
                pct = (price - pc) / pc * 100
                movers.append((sym, pct, price))
            movers.sort(key=lambda x: abs(x[1]), reverse=True)

            for rank, (sym, pct, price) in enumerate(movers[:TOP_N], 1):
                if trade_count[sym] >= MAX_TRADES_PER_STOCK: continue
                if sym in pending: continue
                if sym in cooldown and (ts - cooldown[sym]).total_seconds() / 60 < ALERT_COOLDOWN_MIN:
                    continue

                csf = candle_hist[sym]
                vwap = compute_vwap(csf)
                if vwap is None: continue
                dist = abs(price - vwap) / vwap * 100
                if dist > VWAP_TOUCH_PCT: continue

                direction = "LONG" if pct >= 0 else "SHORT"
                c1 = c1_ratio(csf)

                # Volume filter
                if c1 < C1_MIN:
                    day_events.append({
                        'type': 'VOL_FAIL', 'time': ts_hm, 'sym': sym,
                        'dir': direction, 'price': price, 'vwap': vwap,
                        'dist': dist, 'c1': c1, 'rank': rank, 'pct': pct,
                    })
                    cooldown[sym] = ts
                    continue

                # Queue for confirmation
                day_events.append({
                    'type': 'QUEUED', 'time': ts_hm, 'sym': sym,
                    'dir': direction, 'price': price, 'vwap': vwap,
                    'dist': dist, 'c1': c1, 'rank': rank, 'pct': pct,
                })
                pending[sym] = {
                    'vwap': vwap, 'direction': direction, 'elapsed': 0,
                    'c1': c1, 'touch_ts': ts_hm,
                }
                cooldown[sym] = ts

        # Compute day stats
        d_touches    = sum(1 for e in day_events if e['type'] in ('VOL_FAIL', 'QUEUED'))
        d_vol_fail   = sum(1 for e in day_events if e['type'] == 'VOL_FAIL')
        d_queued     = sum(1 for e in day_events if e['type'] == 'QUEUED')
        d_conf_fail  = sum(1 for e in day_events if e['type'] == 'CONFIRM_FAIL')
        d_trades     = [e for e in day_events if e['type'] == 'TRADE']
        d_wins       = sum(1 for t in d_trades if t['gross'] > 0)
        d_net        = sum(t['gross'] for t in d_trades)

        if not weekly_mode:
            print(f"{'='*72}")
            print(f"  {date}  |  Touches: {d_touches}  Vol✗: {d_vol_fail}  "
                  f"Queued: {d_queued}  Conf✗: {d_conf_fail}  Trades: {len(d_trades)}")
            print(f"{'='*72}")

            for e in day_events:
                if e['type'] == 'VOL_FAIL':
                    print(f"  {e['time']}  ✗VOL  #{e['rank']} {e['sym']:<12} "
                          f"{e['dir']:<5} {e['pct']:>+.1f}%  "
                          f"price={e['price']:.1f} vwap={e['vwap']:.1f} "
                          f"dist={e['dist']:.2f}%  C1={e['c1']:.2f}× (need {C1_MIN}×)")
                elif e['type'] == 'QUEUED':
                    print(f"  {e['time']}  →Q    #{e['rank']} {e['sym']:<12} "
                          f"{e['dir']:<5} {e['pct']:>+.1f}%  "
                          f"price={e['price']:.1f} vwap={e['vwap']:.1f} "
                          f"dist={e['dist']:.2f}%  C1={e['c1']:.2f}×  (waiting T+{CONFIRM_OFFSET})")
                elif e['type'] == 'CONFIRM_FAIL':
                    print(f"  {e['time']}  ✗CNF  {e['sym']:<12} "
                          f"{e['dir']:<5}  price={e['price']:.1f} vwap={e['vwap']:.1f}  "
                          f"(no confirm — touched at {e['touch_time']})")
                elif e['type'] == 'TRADE':
                    icon = "✅" if e['gross'] > 0 else "❌"
                    sign = "+" if e['gross'] >= 0 else ""
                    print(f"  {e['time']}  {icon}ENTRY {e['sym']:<12} "
                          f"{e['dir']:<5} C1={e['c1']:.2f}×  "
                          f"entry={e['entry']:.1f}  exit={e['exit']:.1f} [{e['reason']}]  "
                          f"gross={sign}₹{e['gross']:,.0f}")

            if d_trades:
                wins_str = f"{d_wins}/{len(d_trades)}"
                sign = "+" if d_net >= 0 else ""
                print(f"  {'─'*68}")
                print(f"  Day P&L: {sign}₹{d_net:,.0f}  ({wins_str} wins)")
            print()

        # Accumulate into weekly bucket
        dt = datetime.strptime(date, "%Y-%m-%d")
        iso_year, iso_week, _ = dt.isocalendar()
        wkey = (iso_year, iso_week)
        if not weekly_rows or weekly_rows[-1]['wkey'] != wkey:
            weekly_rows.append({
                'wkey': wkey, 'first': date, 'last': date,
                'tdays': 0, 'touches': 0, 'vol_fail': 0, 'queued': 0,
                'conf_fail': 0, 'trades': 0, 'wins': 0, 'net': 0.0,
            })
        w = weekly_rows[-1]
        w['last'] = date
        w['tdays']     += 1
        w['touches']   += d_touches
        w['vol_fail']  += d_vol_fail
        w['queued']    += d_queued
        w['conf_fail'] += d_conf_fail
        w['trades']    += len(d_trades)
        w['wins']      += d_wins
        w['net']       += d_net

        total_touches   += d_touches
        total_vol_fail  += d_vol_fail
        total_queued    += d_queued
        total_confirm_fail += d_conf_fail
        total_trades    += len(d_trades)
        total_wins      += d_wins
        total_net       += d_net

    if weekly_mode:
        # ── Weekly summary table ──────────────────────────────────────────────
        print(f"Config: TOP_N={TOP_N} | C1≥{C1_MIN} | T+{CONFIRM_OFFSET} | exit {EXIT_TIME} | TSL {TRAILING_SL_PCT}%")
        print()
        hdr = (f"{'Wk':<3}  {'Date Range':<23}  {'Days':>4}  "
               f"{'Touch':>5}  {'Vol✗%':>6}  {'Qd':>3}  {'Cf✗':>4}  "
               f"{'Tr':>3}  {'W':>3}  {'Win%':>5}  {'Gross P&L':>12}  {'Cum P&L':>12}")
        print(hdr)
        print("─" * len(hdr))
        cum = 0.0
        for n, w in enumerate(weekly_rows, 1):
            cum += w['net']
            wr_s  = f"{w['wins']/w['trades']*100:.0f}%" if w['trades'] else "  —"
            vf_s  = f"{w['vol_fail']/w['touches']*100:.0f}%" if w['touches'] else " —"
            net_s = f"{'+'if w['net']>=0 else ''}₹{w['net']:,.0f}"
            cum_s = f"{'+'if cum>=0 else ''}₹{cum:,.0f}"
            fr, to = w['first'][5:], w['last'][5:]   # MM-DD
            print(f"W{n:<2}  {w['first']} – {w['last']}  "
                  f"{w['tdays']:>4}  {w['touches']:>5}  {vf_s:>6}  "
                  f"{w['queued']:>3}  {w['conf_fail']:>4}  "
                  f"{w['trades']:>3}  {w['wins']:>3}  {wr_s:>5}  "
                  f"{net_s:>12}  {cum_s:>12}")
        print("─" * len(hdr))
        wr_tot  = f"{total_wins/total_trades*100:.0f}%" if total_trades else "—"
        vf_tot  = f"{total_vol_fail/total_touches*100:.0f}%" if total_touches else "—"
        net_tot = f"{'+'if total_net>=0 else ''}₹{total_net:,.0f}"
        print(f"{'TOT':<4}  {dates[0]} – {dates[-1]}  "
              f"{len(dates):>4}  {total_touches:>5}  {vf_tot:>6}  "
              f"{total_queued:>3}  {total_confirm_fail:>4}  "
              f"{total_trades:>3}  {int(total_wins):>3}  {wr_tot:>5}  "
              f"{net_tot:>12}  {net_tot:>12}")
        print()
        if total_trades:
            avg = total_net / total_trades
            print(f"  Avg gross/trade: {'+'if avg>=0 else ''}₹{avg:,.0f}")
        print(f"  ⚠  Gross P&L — subtract ~₹200-300/trade for Zerodha F&O charges")
    else:
        print(f"{'='*72}")
        print(f"  SUMMARY — {n_days} days")
        print(f"{'='*72}")
        print(f"  VWAP touches detected : {total_touches}")
        print(f"  Vol filter failed     : {total_vol_fail}  (C1 < {C1_MIN}×)")
        print(f"  Queued for T+{CONFIRM_OFFSET} confirm : {total_queued}")
        print(f"  Confirmation failed   : {total_confirm_fail}")
        print(f"  Trades entered        : {total_trades}")
        if total_trades:
            wr = total_wins / total_trades * 100
            avg = total_net / total_trades
            sign = "+" if total_net >= 0 else ""
            print(f"  Win rate              : {wr:.1f}%  ({int(total_wins)}/{total_trades})")
            print(f"  Avg gross/trade       : {sign}₹{avg:,.0f}")
            print(f"  Total gross P&L       : {sign}₹{total_net:,.0f}")
        print()
        print(f"⚠️  Gross P&L shown — subtract ~₹200-300/trade for Zerodha F&O charges")


if __name__ == "__main__":
    run()
