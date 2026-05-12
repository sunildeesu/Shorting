#!/usr/bin/env python3
"""
Backtest: Gap-and-Go Opening Range Breakout (ORB) for NSE F&O Stock Futures

Strategy:
  1. Pre-market gap filter: stocks with |gap| > GAP_MIN_PCT from prev close
  2. Opening Range: High/Low of first ORB_MINUTES (default 10) from 09:15 AM
  3. Entry: First candle close OUTSIDE range in gap direction, after ORB window
  4. Volume confirmation: entry candle volume delta > VOL_MIN_RATIO × avg opening-range vol
  5. Stop: ORL (for LONG) or ORH (for SHORT)
  6. Range-too-wide filter: skip if range > MAX_RANGE_PCT of price
  7. Exit: Trailing SL (TRAILING_SL_PCT) or hard exit at EXIT_TIME

CLI flags:
  --days=N       backtest last N trading days  [default: 60]
  --offset=N     skip most recent N days       [default: 0]
  --gap=X        gap threshold %               [default: 1.5]
  --orb=N        opening range minutes         [default: 10]
  --vol=X        volume confirmation ratio     [default: 1.5]
  --max-range=X  skip if range > X% of price  [default: 2.5]
  --exit=HH:MM   hard exit time               [default: 11:00]
  --tsl=X        trailing SL %                [default: 0.5]
  --max-risk=X   cap stop distance at X% of entry (0 = no cap) [default: 0]
  --max-rs=N     skip trade if risk > N rupees per lot (0 = no cap) [default: 0]
  --no-vol-filter  disable volume filter
  --nifty-filter   only take trades aligned with Nifty gap direction; shows comparison
  --weekly       compact weekly summary
"""

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

# ── Config (defaults, overridable via CLI) ────────────────────────────────────
LAST_N_DAYS    = 60
OFFSET_DAYS    = 0
GAP_MIN_PCT    = 1.5      # minimum gap % to qualify
ORB_MINUTES    = 10       # opening range window (minutes from 09:15)
VOL_MIN_RATIO  = 1.5      # entry candle vol delta >= X * avg OR-window vol
MAX_RANGE_PCT  = 2.5      # skip if (ORH-ORL)/ORL > X%
MAX_RISK_PCT   = 0.0      # cap stop distance at X% of entry (0 = use ORL/ORH as-is)
MAX_RISK_RS    = 0        # skip trade if risk (rupees/lot) exceeds this (0 = no cap)
EXIT_TIME      = "11:00"  # hard exit time
TRAILING_SL_PCT = 0.5     # trailing stop %
VOL_FILTER_ON  = True
NIFTY_FILTER   = False    # if True, compare all trades vs Nifty-direction-aligned trades

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"

# ── Parse CLI flags ───────────────────────────────────────────────────────────
weekly_mode = False
for i, arg in enumerate(sys.argv[1:], 1):
    if arg.startswith("--days="):    LAST_N_DAYS    = int(arg.split("=")[1])
    elif arg == "--days" and i + 1 < len(sys.argv): LAST_N_DAYS = int(sys.argv[i + 1])
    elif arg.startswith("--offset="): OFFSET_DAYS  = int(arg.split("=")[1])
    elif arg == "--offset" and i + 1 < len(sys.argv): OFFSET_DAYS = int(sys.argv[i + 1])
    elif arg.startswith("--gap="):   GAP_MIN_PCT    = float(arg.split("=")[1])
    elif arg.startswith("--orb="):   ORB_MINUTES    = int(arg.split("=")[1])
    elif arg.startswith("--vol="):   VOL_MIN_RATIO  = float(arg.split("=")[1])
    elif arg.startswith("--max-range="): MAX_RANGE_PCT = float(arg.split("=")[1])
    elif arg.startswith("--exit="):  EXIT_TIME      = arg.split("=")[1]
    elif arg.startswith("--tsl="):      TRAILING_SL_PCT = float(arg.split("=")[1])
    elif arg.startswith("--max-risk="): MAX_RISK_PCT    = float(arg.split("=")[1])
    elif arg.startswith("--max-rs="):  MAX_RISK_RS     = int(arg.split("=")[1])
    elif arg == "--no-vol-filter":      VOL_FILTER_ON  = False
    elif arg == "--nifty-filter":       NIFTY_FILTER   = True
    elif arg == "--weekly":          weekly_mode    = True

# Opening range window end (exclusive of breakout candles)
ORB_END_HM = (datetime.strptime("09:15", "%H:%M").replace(
    minute=15 + ORB_MINUTES) if ORB_MINUTES <= 45 else None)
# Compute as string
_orb_end_min = 15 + ORB_MINUTES
_orb_end_h   = 9 + _orb_end_min // 60
_orb_end_m   = _orb_end_min % 60
ORB_END_STR  = f"{_orb_end_h:02d}:{_orb_end_m:02d}"   # e.g. "09:25"

ENTRY_END_STR = EXIT_TIME  # entry only allowed before exit time


# ── Helpers ───────────────────────────────────────────────────────────────────

# NSE F&O charges (current rates as of 2025)
BROKERAGE_PER_ORDER  = 20.0    # ₹20 flat per executed order (Zerodha)
STT_RATE             = 0.0002  # 0.02% on sell-side notional
EXCHANGE_RATE        = 0.0000188  # 0.00188% per side of notional (NSE equity futures)
SEBI_RATE            = 0.0000001  # ₹10 per crore = 0.000001% per side
GST_RATE             = 0.18    # 18% on (brokerage + exchange + SEBI)
STAMP_RATE           = 0.00002 # 0.002% on buy-side notional


def compute_charges(entry_price, exit_price, lot, direction):
    """
    Compute total NSE F&O charges for a round-trip futures trade.

    For LONG:  buy at entry, sell at exit
    For SHORT: sell at entry, buy at exit

    Returns (charges, breakdown_dict)
    """
    buy_notional  = (entry_price if direction == "LONG" else exit_price) * lot
    sell_notional = (exit_price  if direction == "LONG" else entry_price) * lot
    total_notional = buy_notional + sell_notional

    brokerage = BROKERAGE_PER_ORDER * 2                      # entry + exit
    stt       = STT_RATE * sell_notional                     # sell side only
    exchange  = EXCHANGE_RATE * total_notional               # both sides
    sebi      = SEBI_RATE * total_notional                   # both sides
    gst       = GST_RATE * (brokerage + exchange + sebi)     # 18% on taxable components
    stamp     = STAMP_RATE * buy_notional                    # buy side only

    total = brokerage + stt + exchange + sebi + gst + stamp
    return round(total, 2), {
        'brokerage': round(brokerage, 2),
        'stt':       round(stt, 2),
        'exchange':  round(exchange, 2),
        'sebi':      round(sebi, 2),
        'gst':       round(gst, 2),
        'stamp':     round(stamp, 2),
    }


def vol_delta(candles, idx):
    """Volume delta at candle index (cumulative volume diff)."""
    if idx == 0:
        return float(candles[0]['volume'] or 0)
    return max(0.0, float(candles[idx]['volume'] or 0) - float(candles[idx - 1]['volume'] or 0))


def simulate_exit(candles, entry_idx, entry_price, direction, exit_ts, sl_price):
    """
    Simulate exit with range-based initial stop + trailing stop.

    Stop logic:
    - Initial SL = sl_price (ORL for LONG, ORH for SHORT)
    - Trailing stop (TRAILING_SL_PCT) activates only after a 1R move in our favor
    - Once trailing kicks in, it only ratchets in our direction (never retreats)
    """
    peak   = entry_price
    trough = entry_price
    sl     = sl_price  # start at range boundary (ORL or ORH)
    risk   = abs(entry_price - sl_price)
    # TSL only activates once price moves 1R beyond entry
    activation = (entry_price + risk if direction == "LONG"
                  else entry_price - risk)

    for i in range(entry_idx + 1, len(candles)):
        c = candles[i]
        price = float(c['price'])
        ts    = c['timestamp']

        if direction == "LONG":
            if price > peak:
                peak = price
            # Activate trailing only after 1R move
            if price >= activation:
                trail_sl = peak * (1 - TRAILING_SL_PCT / 100)
                sl = max(sl, trail_sl)  # ratchet up, never retreat
            if price <= sl or ts >= exit_ts:
                reason = "TSL" if price <= sl else "EOD"
                return price, reason, ts
        else:
            if price < trough:
                trough = price
            if price <= activation:
                trail_sl = trough * (1 + TRAILING_SL_PCT / 100)
                sl = min(sl, trail_sl)  # ratchet down, never retreat
            if price >= sl or ts >= exit_ts:
                reason = "TSL" if price >= sl else "EOD"
                return price, reason, ts

    return None, None, None


def print_summary(trades, dates, label="OVERALL SUMMARY"):
    """Print performance summary for a set of trades."""
    print("\n" + "═" * 65)
    print(label)
    print("═" * 65)

    n_trades = len(trades)
    if n_trades == 0:
        print("  No trades.")
        return

    n_wins      = sum(1 for t in trades if t['win'])
    n_loss      = n_trades - n_wins
    total_gross = sum(t['gross'] for t in trades)
    total_chg   = sum(t['charges'] for t in trades)
    total_net   = sum(t['net'] for t in trades)
    avg_win     = (sum(t['net'] for t in trades if t['win']) / n_wins) if n_wins else 0
    avg_loss    = (sum(t['net'] for t in trades if not t['win']) / n_loss) if n_loss else 0
    win_rate    = (n_wins / n_trades * 100) if n_trades else 0
    avg_pnl     = total_net / n_trades if n_trades else 0

    avg_gap_win  = (sum(abs(t['gap_pct']) for t in trades if t['win']) / n_wins) if n_wins else 0
    avg_gap_loss = (sum(abs(t['gap_pct']) for t in trades if not t['win']) / n_loss) if n_loss else 0

    exit_reasons = defaultdict(int)
    for t in trades:
        exit_reasons[t['exit_reason']] += 1

    long_trades  = [t for t in trades if t['direction'] == "LONG"]
    short_trades = [t for t in trades if t['direction'] == "SHORT"]
    long_wins    = sum(1 for t in long_trades if t['win'])
    short_wins   = sum(1 for t in short_trades if t['win'])

    print(f"  Period          : {dates[0]} → {dates[-1]} ({len(dates)} days)")
    print(f"  Trades taken    : {n_trades}")
    print(f"  Win / Loss      : {n_wins} / {n_loss}  (win = net P&L > 0 after charges)")
    print(f"  Win Rate        : {win_rate:.1f}%")
    print(f"  Gross P&L       : ₹{total_gross:,.0f}")
    print(f"  Total charges   : ₹{total_chg:,.0f}  (₹{total_chg/n_trades:,.0f}/trade avg)")
    print(f"  Net P&L         : ₹{total_net:,.0f}")
    print(f"  Avg net/trade   : ₹{avg_pnl:,.0f}")
    print(f"  Avg win (net)   : ₹{avg_win:,.0f}  (avg gap {avg_gap_win:.1f}%)")
    print(f"  Avg loss (net)  : ₹{avg_loss:,.0f}  (avg gap {avg_gap_loss:.1f}%)")
    print(f"  Exit breakdown  : {dict(exit_reasons)}")
    print()
    if long_trades:
        print(f"  LONG  trades: {len(long_trades)} | wins: {long_wins} "
              f"({100*long_wins/len(long_trades):.0f}%)")
    else:
        print("  LONG  trades: 0")
    if short_trades:
        print(f"  SHORT trades: {len(short_trades)} | wins: {short_wins} "
              f"({100*short_wins/len(short_trades):.0f}%)")
    else:
        print("  SHORT trades: 0")

    # Drawdown (on net P&L)
    running_pnl = 0.0
    peak_pnl    = 0.0
    max_dd      = 0.0
    for t in trades:
        running_pnl += t['net']
        if running_pnl > peak_pnl:
            peak_pnl = running_pnl
        dd = peak_pnl - running_pnl
        if dd > max_dd:
            max_dd = dd
    print(f"\n  Max Drawdown    : ₹{max_dd:,.0f}")

    # Top 10 best trades (by net P&L)
    print("\n  Top 10 Trades by Net P&L:")
    top10 = sorted(trades, key=lambda t: t['net'], reverse=True)[:10]
    for t in top10:
        print(f"    {t['date']} {t['symbol']:12s} {t['direction']:5s} "
              f"gap={t['gap_pct']:+.1f}% gross=₹{t['gross']:,.0f} "
              f"chg=₹{t['charges']:,.0f} net=₹{t['net']:,.0f}")


def run():
    try:
        lot_sizes = json.load(open(LOT_SIZES_FILE))
    except Exception:
        lot_sizes = {}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ── Select trading days ───────────────────────────────────────────────────
    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d DESC")
    all_dates_desc = [r['d'] for r in cur.fetchall()]
    window_end   = OFFSET_DAYS + LAST_N_DAYS
    dates        = list(reversed(all_dates_desc[OFFSET_DAYS:window_end]))
    if not dates:
        print("No data found for the requested window.")
        return
    date_set  = set(dates)
    prev_date = all_dates_desc[window_end] if len(all_dates_desc) > window_end else None

    print(f"Backtesting {len(dates)} days: {dates[0]} → {dates[-1]}")
    print(f"Config: gap≥{GAP_MIN_PCT}% | ORB={ORB_MINUTES}min ({ORB_END_STR}) | "
          f"exit {EXIT_TIME} | TSL {TRAILING_SL_PCT}% | max_range {MAX_RANGE_PCT}% | "
          f"vol_filter={'ON ('+str(VOL_MIN_RATIO)+'x)' if VOL_FILTER_ON else 'OFF'} | "
          f"nifty_filter={'ON' if NIFTY_FILTER else 'OFF'}\n")

    # ── Prev close lookup ─────────────────────────────────────────────────────
    cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
    day0_prev = {r['symbol']: float(r['prev_close']) for r in cur.fetchall()}

    prev_days_needed = set()
    if prev_date:
        prev_days_needed.add(prev_date)
    for d in dates[:-1]:
        prev_days_needed.add(d)

    last_price_by_sym_date = {}
    if prev_days_needed:
        ph = ",".join("?" * len(prev_days_needed))
        cur.execute(f"""
            SELECT symbol, date(timestamp) as d, price FROM stock_quotes
            WHERE (symbol, timestamp) IN (
                SELECT symbol, MAX(timestamp) FROM stock_quotes
                WHERE date(timestamp) IN ({ph})
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

    # ── Nifty direction per day (for --nifty-filter) ──────────────────────────
    nifty_direction_by_date = {}
    if NIFTY_FILTER:
        # Nifty first price of each backtest day (open approximation)
        ph_dates = ",".join("?" * len(dates))
        cur.execute(f"""
            SELECT date(timestamp) as d, MIN(timestamp), price
            FROM nifty_quotes
            WHERE date(timestamp) IN ({ph_dates})
              AND time(timestamp) >= '09:15:00'
            GROUP BY d
        """, dates)
        nifty_open_by_date = {r['d']: float(r['price']) for r in cur.fetchall()}

        # Nifty last price of each day needed as prev_close for next day
        nifty_prev_days = set()
        if prev_date:
            nifty_prev_days.add(prev_date)
        for d in dates[:-1]:
            nifty_prev_days.add(d)

        nifty_last_by_date = {}
        if nifty_prev_days:
            ph_np = ",".join("?" * len(nifty_prev_days))
            cur.execute(f"""
                SELECT date(timestamp) as d, price FROM nifty_quotes
                WHERE (date(timestamp), timestamp) IN (
                    SELECT date(timestamp), MAX(timestamp)
                    FROM nifty_quotes
                    WHERE date(timestamp) IN ({ph_np})
                    GROUP BY date(timestamp)
                )
            """, list(nifty_prev_days))
            nifty_last_by_date = {r['d']: float(r['price']) for r in cur.fetchall()}

        # Compute gap direction for each backtest date
        missing_nifty = 0
        for i, date in enumerate(dates):
            prev_d    = prev_date if i == 0 else dates[i - 1]
            nifty_open = nifty_open_by_date.get(date)
            nifty_pc   = nifty_last_by_date.get(prev_d) if prev_d else None
            if nifty_open and nifty_pc and nifty_pc > 0:
                gap = (nifty_open - nifty_pc) / nifty_pc * 100
                nifty_direction_by_date[date] = "LONG" if gap >= 0 else "SHORT"
            else:
                missing_nifty += 1

        print(f"Nifty direction resolved for {len(nifty_direction_by_date)}/{len(dates)} days "
              f"({missing_nifty} days missing Nifty data — those days: all trades kept)\n")

    # ── Bulk load candles ─────────────────────────────────────────────────────
    ts_start = f"{dates[0]} 09:15:00"
    ts_end   = f"{dates[-1]} 12:00:00"
    cur.execute("""
        SELECT symbol, timestamp, price, volume FROM stock_quotes
        WHERE timestamp >= ? AND timestamp <= ?
          AND time(timestamp) >= '09:15:00' AND time(timestamp) <= '12:00:00'
        ORDER BY symbol, timestamp ASC
    """, (ts_start, ts_end))

    candles_by_date = {d: {} for d in dates}
    for r in cur.fetchall():
        d = r['timestamp'][:10]
        if d not in date_set:
            continue
        s = r['symbol']
        candles_by_date[d].setdefault(s, []).append({
            'timestamp': r['timestamp'],
            'price':     float(r['price']),
            'volume':    float(r['volume'] or 0),
        })
    conn.close()

    # ── Per-day simulation ────────────────────────────────────────────────────
    all_trades = []
    total_gap_qualifiers = 0
    total_wide_range_skip = 0
    total_no_breakout   = 0
    total_vol_fail      = 0

    day_summaries = []   # for weekly mode

    for date in dates:
        prev_close  = prev_close_by_date.get(date, {})
        all_candles = candles_by_date.get(date, {})
        exit_ts     = f"{date} {EXIT_TIME}:00"

        # Nifty direction for this day (None = no data, treat as unfiltered)
        nifty_dir = nifty_direction_by_date.get(date) if NIFTY_FILTER else None

        day_trades  = []
        day_gap_q   = 0
        day_wide    = 0
        day_no_brk  = 0
        day_vol_f   = 0

        for sym, candles in all_candles.items():
            if not candles or sym not in prev_close:
                continue
            pc = prev_close[sym]
            if pc <= 0:
                continue

            # First price of day = open approximation
            open_price = candles[0]['price']
            gap_pct    = (open_price - pc) / pc * 100.0
            if abs(gap_pct) < GAP_MIN_PCT:
                continue

            day_gap_q += 1
            direction  = "LONG" if gap_pct > 0 else "SHORT"

            # Opening range: first ORB_MINUTES candles
            orb_candles  = [c for c in candles if c['timestamp'][11:16] < ORB_END_STR]
            post_candles = [c for c in candles if c['timestamp'][11:16] >= ORB_END_STR
                            and c['timestamp'] < exit_ts]
            if not orb_candles or not post_candles:
                day_no_brk += 1
                continue

            orh = max(c['price'] for c in orb_candles)
            orl = min(c['price'] for c in orb_candles)

            # Range-too-wide filter
            range_pct = (orh - orl) / orl * 100.0 if orl > 0 else 99
            if range_pct > MAX_RANGE_PCT:
                day_wide += 1
                continue

            # Average opening-range volume delta (for vol confirmation baseline)
            orb_deltas = [vol_delta(candles, candles.index(c)) for c in orb_candles]
            avg_orb_vol = sum(orb_deltas) / len(orb_deltas) if orb_deltas else 0.0

            # Initial stop = other side of range
            init_sl = orl if direction == "LONG" else orh

            # Find first breakout candle
            traded = False
            for i, c in enumerate(post_candles):
                price = c['price']
                ts    = c['timestamp']

                # Check breakout in gap direction
                if direction == "LONG"  and price <= orh:
                    continue
                if direction == "SHORT" and price >= orl:
                    continue

                # Volume confirmation
                global_idx = candles.index(c)
                delta = vol_delta(candles, global_idx)
                if VOL_FILTER_ON and avg_orb_vol > 0 and delta < VOL_MIN_RATIO * avg_orb_vol:
                    day_vol_f += 1
                    break   # only attempt first eligible candle

                # Entry confirmed
                entry_price = price
                entry_ts    = ts

                # Apply max-risk cap: if stop is too far, tighten it
                trade_sl = init_sl
                if MAX_RISK_PCT > 0:
                    if direction == "LONG":
                        capped_sl = entry_price * (1 - MAX_RISK_PCT / 100)
                        trade_sl  = max(init_sl, capped_sl)
                    else:
                        capped_sl = entry_price * (1 + MAX_RISK_PCT / 100)
                        trade_sl  = min(init_sl, capped_sl)

                # Rupee risk filter: skip if 1 lot risks more than MAX_RISK_RS
                lot = lot_sizes.get(sym, 1)
                risk_rs = abs(entry_price - trade_sl) * lot
                if MAX_RISK_RS > 0 and risk_rs > MAX_RISK_RS:
                    break

                # Simulate exit
                exit_price, reason, exit_time = simulate_exit(
                    candles, global_idx, entry_price, direction, exit_ts, trade_sl)

                if exit_price is None:
                    break

                gross = ((exit_price - entry_price) if direction == "LONG"
                         else (entry_price - exit_price)) * lot
                charges, _ = compute_charges(entry_price, exit_price, lot, direction)
                net  = gross - charges
                win  = net > 0

                # Mark whether this trade aligns with Nifty's gap direction
                nifty_aligned = (nifty_dir is None or direction == nifty_dir)

                trade = {
                    'date':          date,
                    'symbol':        sym,
                    'direction':     direction,
                    'gap_pct':       round(gap_pct, 2),
                    'orh':           round(orh, 2),
                    'orl':           round(orl, 2),
                    'range_pct':     round(range_pct, 2),
                    'entry_price':   round(entry_price, 2),
                    'entry_time':    entry_ts[11:16],
                    'sl':            round(init_sl, 2),
                    'exit_price':    round(exit_price, 2),
                    'exit_reason':   reason,
                    'exit_time':     exit_time[11:16] if exit_time else '--',
                    'gross':         round(gross, 2),
                    'charges':       charges,
                    'net':           round(net, 2),
                    'lot':           lot,
                    'win':           win,
                    'nifty_dir':     nifty_dir,
                    'nifty_aligned': nifty_aligned,
                }
                day_trades.append(trade)
                traded = True
                break

            if not traded and not day_vol_f:
                pass

        all_trades.extend(day_trades)
        total_gap_qualifiers += day_gap_q
        total_wide_range_skip += day_wide
        total_no_breakout     += day_no_brk
        total_vol_fail        += day_vol_f

        # Per-day summary
        wins     = sum(1 for t in day_trades if t['win'])
        day_net  = sum(t['gross'] for t in day_trades)
        day_summaries.append({
            'date':   date,
            'trades': len(day_trades),
            'wins':   wins,
            'net':    day_net,
            'gap_q':  day_gap_q,
        })

        if not weekly_mode:
            if day_trades:
                day_net_net = sum(t['net'] for t in day_trades)
                day_chg     = sum(t['charges'] for t in day_trades)
                nifty_tag   = f" | nifty={nifty_dir or '?'}" if NIFTY_FILTER else ""
                print(f"\n─── {date} ──── gap qualifiers: {day_gap_q} | "
                      f"trades: {len(day_trades)} | wins: {wins} | "
                      f"gross: ₹{day_net:,.0f}  chg: ₹{day_chg:,.0f}  net: ₹{day_net_net:,.0f}{nifty_tag}")
                for t in day_trades:
                    flag    = "✓" if t['win'] else "✗"
                    aligned = "" if not NIFTY_FILTER else (" [aligned]" if t['nifty_aligned'] else " [counter]")
                    print(f"  {flag} {t['symbol']:12s} {t['direction']:5s} "
                          f"gap={t['gap_pct']:+.1f}% | range={t['range_pct']:.1f}% | "
                          f"entry={t['entry_price']:.1f} @{t['entry_time']} "
                          f"→ exit={t['exit_price']:.1f} @{t['exit_time']} [{t['exit_reason']}] "
                          f"gross=₹{t['gross']:,.0f} net=₹{t['net']:,.0f}{aligned}")

    # ── Weekly summary ────────────────────────────────────────────────────────
    if weekly_mode:
        from collections import OrderedDict
        weeks = OrderedDict()
        for ds in day_summaries:
            d = datetime.strptime(ds['date'], '%Y-%m-%d')
            wk = d.strftime('%Y-W%V')
            weeks.setdefault(wk, {'trades': 0, 'wins': 0, 'net': 0.0, 'days': 0})
            w = weeks[wk]
            w['trades'] += ds['trades']
            w['wins']   += ds['wins']
            w['net']    += ds['net']
            w['days']   += 1

        print(f"{'Week':<10} {'Days':>4} {'Trades':>7} {'Win%':>6} {'Net ₹':>12}")
        print("-" * 45)
        for wk, w in weeks.items():
            winpct = (w['wins'] / w['trades'] * 100) if w['trades'] > 0 else 0.0
            print(f"{wk:<10} {w['days']:>4} {w['trades']:>7} {winpct:>5.1f}% "
                  f"{w['net']:>12,.0f}")

    # ── Overall summary ───────────────────────────────────────────────────────
    print(f"\n  Gap qualifiers  : {total_gap_qualifiers} (gap ≥ {GAP_MIN_PCT}%)")
    print(f"  Skipped (range) : {total_wide_range_skip} (range > {MAX_RANGE_PCT}%)")
    print(f"  No breakout     : {total_no_breakout}")
    print(f"  Vol filter fail : {total_vol_fail}")

    # Baseline: all trades
    print_summary(all_trades, dates, "ALL TRADES (baseline)")

    # Nifty-aligned comparison
    if NIFTY_FILTER:
        aligned_trades = [t for t in all_trades if t['nifty_aligned']]
        counter_trades = [t for t in all_trades if not t['nifty_aligned']]

        print_summary(aligned_trades, dates,
                      f"NIFTY-ALIGNED TRADES ({len(aligned_trades)} of {len(all_trades)})")
        print_summary(counter_trades, dates,
                      f"COUNTER-NIFTY TRADES ({len(counter_trades)} of {len(all_trades)})")

        # Quick comparison table
        def stats(trades):
            n = len(trades)
            if n == 0:
                return 0, 0.0, 0.0, 0.0
            wins = sum(1 for t in trades if t['win'])
            net  = sum(t['net'] for t in trades)
            return n, wins / n * 100, net / n, net

        n_all,  wr_all,  ap_all,  tot_all  = stats(all_trades)
        n_ali,  wr_ali,  ap_ali,  tot_ali  = stats(aligned_trades)
        n_ctr,  wr_ctr,  ap_ctr,  tot_ctr  = stats(counter_trades)

        print("\n" + "═" * 65)
        print("COMPARISON (net of charges)")
        print("═" * 65)
        print(f"  {'':25s}  {'Trades':>7}  {'Win%':>6}  {'Avg net':>9}  {'Total net':>11}")
        print(f"  {'-'*25}  {'-'*7}  {'-'*6}  {'-'*9}  {'-'*11}")
        print(f"  {'All trades':25s}  {n_all:>7}  {wr_all:>5.1f}%  ₹{ap_all:>8,.0f}  ₹{tot_all:>10,.0f}")
        print(f"  {'Nifty-aligned':25s}  {n_ali:>7}  {wr_ali:>5.1f}%  ₹{ap_ali:>8,.0f}  ₹{tot_ali:>10,.0f}")
        print(f"  {'Counter-Nifty':25s}  {n_ctr:>7}  {wr_ctr:>5.1f}%  ₹{ap_ctr:>8,.0f}  ₹{tot_ctr:>10,.0f}")

        # Nifty day breakdown
        up_days   = sum(1 for d in dates if nifty_direction_by_date.get(d) == "LONG")
        down_days = sum(1 for d in dates if nifty_direction_by_date.get(d) == "SHORT")
        no_data   = len(dates) - up_days - down_days
        print(f"\n  Nifty direction: {up_days} UP days, {down_days} DOWN days"
              + (f", {no_data} no-data days" if no_data else ""))


if __name__ == "__main__":
    run()
