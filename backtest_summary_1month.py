#!/usr/bin/env python3
"""
Order Flow Summary — 1-Month Proxy Backtest.

Simulates what the live order flow monitor's "top bullish/bearish" summary
would have produced over the past month, using bulk-volume cum_delta as a proxy
for the live BAI signal.

For each 5-minute interval during market hours:
  - Compute cum_delta_pct for each stock (buy vs sell pressure in last 5 min)
  - Select top-3 bullish (highest) and top-3 bearish (lowest)
  - Enter at that candle's close price, exit at EOD 3:29 PM

This mimics the live monitor's 5-minute summary cycle.

Usage:
    python backtest_summary_1month.py
"""

import json
import os
import time
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple

from kiteconnect import KiteConnect
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

CANDLE_CACHE       = 'data/backtest_summary_1month_cache.json'
TOKEN_FILE         = 'data/all_instrument_tokens.json'
ROUND_TRIP_CHARGES = 0.0004   # 0.04% round trip
TOP_N              = 3        # top-3 per summary, same as live monitor
MIN_TRADES         = 10       # min trades for a bucket to appear in report
EOD_EXIT           = dt_time(15, 29)
SUMMARY_INTERVAL   = 5        # minutes — live monitor fires every 5 min

# NSE trading days — 1 month back from Apr 28, 2026
NSE_TRADING_DAYS = sorted([
    date(2026, 3, 28),
    date(2026, 4, 1),  date(2026, 4, 2),  date(2026, 4, 3),  date(2026, 4, 4),
    date(2026, 4, 7),  date(2026, 4, 8),  date(2026, 4, 9),  date(2026, 4, 10),
    date(2026, 4, 11), date(2026, 4, 14), date(2026, 4, 15), date(2026, 4, 16),
    date(2026, 4, 17), date(2026, 4, 22), date(2026, 4, 23), date(2026, 4, 24),
    date(2026, 4, 25), date(2026, 4, 28),
])

# F&O stocks — same universe as the live monitor's candle cache
FOCUS_STOCKS = [
    'ADANIENSOL', 'ADANIENT', 'ALKEM', 'ANGELONE', 'ASTRAL', 'AUBANK',
    'BAJAJ-AUTO', 'BAJAJHLDNG', 'BANDHANBNK', 'BPCL', 'CHOLAFIN', 'COFORGE',
    'COLPAL', 'CONCOR', 'CROMPTON', 'CUMMINSIND', 'DABUR', 'DALBHARAT',
    'DELHIVERY', 'DRREDDY', 'EICHERMOT', 'FEDERALBNK', 'GLENMARK',
    'GODREJPROP', 'GRANULES', 'GSPL', 'HAVELLS', 'HDFCBANK', 'HDFCLIFE',
    'HINDUNILVR', 'ICICIBANK', 'IDEA', 'IDFCFIRSTB', 'IGL', 'INDHOTEL',
    'INDUSINDBK', 'INFY', 'IRCTC', 'ITC', 'JIOFIN', 'JSWSTEEL',
    'KOTAKBANK', 'LTIM', 'LUPIN', 'MARICO', 'MFSL', 'MUTHOOTFIN',
    'NAUKRI', 'NTPC', 'OBEROIRLTY', 'OFSS', 'PAGEIND', 'PERSISTENT',
    'PIIND', 'PNB', 'POLICYBZR', 'POLYCAB', 'PVRINOX', 'RBLBANK',
    'RECLTD', 'RELIANCE', 'SBICARD', 'SBILIFE', 'SHRIRAMFIN', 'SIEMENS',
    'SUNPHARMA', 'TATAPOWER', 'TCS', 'TIINDIA', 'TITAN', 'TRENT',
    'ULTRACEMCO', 'WIPRO',
]


# ── Candle fetching ───────────────────────────────────────────────────────────

def load_token_map() -> Dict[str, int]:
    with open(TOKEN_FILE) as f:
        return json.load(f)


def _seed_from_existing_caches(cache: Dict) -> int:
    """Copy valid entries from existing candle caches to avoid re-fetching."""
    seeded = 0
    for src_file in ['data/backtest_summary_cache.json',
                     'data/backtest_overnight_1month_cache.json']:
        if not os.path.exists(src_file):
            continue
        try:
            with open(src_file) as f:
                src = json.load(f)
            for key, candles in src.items():
                if key in cache or not candles:
                    continue
                parts = key.split('_')
                key_date = '_'.join(parts[1:])
                # Validate: first candle must match key date
                if candles[0]['date'][:10] != key_date:
                    continue
                cache[key] = candles
                seeded += 1
        except Exception as e:
            logger.warning(f"Could not seed from {src_file}: {e}")
    return seeded


def fetch_candles(kite: KiteConnect) -> Dict[str, List[dict]]:
    """
    Fetch 1-min candles for FOCUS_STOCKS × NSE_TRADING_DAYS.
    Seeds from existing caches first to avoid re-fetching.
    Returns { "SYMBOL_DATE": [candles with datetime objects] }.
    """
    cache: Dict[str, list] = {}
    if os.path.exists(CANDLE_CACHE):
        try:
            with open(CANDLE_CACHE) as f:
                cache = json.load(f)
            logger.info(f"Loaded {len(cache)} cached series from {CANDLE_CACHE}")
        except Exception:
            cache = {}

    # Seed from existing caches (free data)
    seeded = _seed_from_existing_caches(cache)
    if seeded:
        logger.info(f"Seeded {seeded} series from existing candle caches")

    # Validate: purge stale entries
    stale = [k for k, v in cache.items()
             if v and v[0]['date'][:10] != '_'.join(k.split('_')[1:])]
    for k in stale:
        del cache[k]
    if stale:
        logger.info(f"Purged {len(stale)} stale entries")

    token_map = load_token_map()
    needed = [(sym, d, f"{sym}_{d}") for sym in FOCUS_STOCKS for d in NSE_TRADING_DAYS]
    to_fetch = [(sym, d, k) for sym, d, k in needed if k not in cache]
    logger.info(f"Need to fetch {len(to_fetch)} series "
                f"(cached: {len(needed) - len(to_fetch)})")

    for i, (symbol, day, key) in enumerate(to_fetch):
        token = token_map.get(symbol)
        if not token:
            cache[key] = []
            continue
        from_dt = datetime.combine(day, dt_time(9, 14))
        to_dt   = datetime.combine(day, dt_time(15, 31))
        try:
            raw = kite.historical_data(
                instrument_token=token,
                from_date=from_dt, to_date=to_dt,
                interval='minute', continuous=False, oi=False,
            )
            cache[key] = [
                {'date': c['date'].strftime('%Y-%m-%d %H:%M:%S'),
                 'open': c['open'], 'high': c['high'],
                 'low': c['low'], 'close': c['close'], 'volume': c['volume']}
                for c in raw
            ]
            if (i + 1) % 100 == 0:
                logger.info(f"  [{i+1}/{len(to_fetch)}] fetched")
        except Exception as e:
            logger.warning(f"Failed {symbol} {day}: {e}")
            cache[key] = []
        time.sleep(0.25)

    if to_fetch:
        with open(CANDLE_CACHE, 'w') as f:
            json.dump(cache, f)
        logger.info(f"Cache saved ({len(cache)} series)")

    # Deserialise dates and return only valid, non-empty entries
    result = {}
    for key, candles in cache.items():
        if not candles:
            continue
        parts = key.split('_')
        key_date = '_'.join(parts[1:])
        if candles[0]['date'][:10] != key_date:
            continue
        result[key] = [
            {**c, 'date': datetime.strptime(c['date'], '%Y-%m-%d %H:%M:%S')}
            for c in candles
        ]
    return result


# ── Bulk-volume cum_delta signal ──────────────────────────────────────────────

def compute_cum_delta(window_candles: List[dict]) -> Optional[float]:
    """
    Compute cum_delta_pct for a window of 1-min candles.
    Uses bulk volume classification: buy_fraction = (close - low) / (high - low).
    Returns net buy fraction in [-1, +1], or None if insufficient data.
    """
    total_buy = 0.0
    total_vol = 0
    for c in window_candles:
        vol = c.get('volume', 0)
        if vol <= 0:
            continue
        hi = c['high']
        lo = c['low']
        spread = hi - lo
        if spread > 0:
            buy_frac = (c['close'] - lo) / spread
        else:
            buy_frac = 0.5  # doji candle — neutral
        total_buy += vol * buy_frac
        total_vol += vol

    if total_vol == 0:
        return None
    return (2 * total_buy / total_vol) - 1   # normalize to [-1, +1]


# ── Summary simulation ────────────────────────────────────────────────────────

def simulate_summaries(candle_map: Dict[str, List[dict]]) -> Tuple[List[dict], List[dict]]:
    """
    For each day and each 5-min interval, simulate a summary event:
      - Compute cum_delta for each stock
      - Pick top-N bullish (highest) and top-N bearish (lowest)
    Returns (bull_events, bear_events) in the same format as parse_summaries().
    """
    # Group candles by date and symbol
    by_date_sym: Dict[str, Dict[str, List[dict]]] = defaultdict(dict)
    for key, candles in candle_map.items():
        parts = key.split('_')
        sym = parts[0]
        dt_str = '_'.join(parts[1:])
        by_date_sym[dt_str][sym] = candles

    bull_events = []
    bear_events = []

    for dt_str in sorted(by_date_sym.keys()):
        sym_candles = by_date_sym[dt_str]
        day = date.fromisoformat(dt_str)

        # Build a time-indexed lookup for fast access: sym → {minute_str: candle}
        sym_time_map: Dict[str, Dict[str, dict]] = {}
        for sym, candles in sym_candles.items():
            sym_time_map[sym] = {c['date'].strftime('%H:%M'): c for c in candles}

        # Fire summary every SUMMARY_INTERVAL minutes from 9:20 AM to 3:00 PM
        # (9:15 is the opening candle — wait at least 5 min for signal)
        t = datetime.combine(day, dt_time(9, 20))
        eod = datetime.combine(day, dt_time(15, 0))

        while t <= eod:
            # Collect cum_delta for all stocks at this timestamp
            scores: Dict[str, float] = {}
            for sym, time_map in sym_time_map.items():
                # Last 5 1-min candles ending at t
                window = []
                for offset in range(4, -1, -1):
                    wt = t - timedelta(minutes=offset)
                    wt_str = wt.strftime('%H:%M')
                    c = time_map.get(wt_str)
                    if c:
                        window.append(c)
                if len(window) < 3:   # need at least 3 candles for a signal
                    continue
                delta = compute_cum_delta(window)
                if delta is not None:
                    scores[sym] = delta

            if len(scores) >= TOP_N * 2:
                sorted_syms = sorted(scores, key=lambda s: scores[s])
                ts = t  # timestamp of this summary event

                # Bearish: lowest cum_delta (most selling pressure)
                bear_syms = sorted_syms[:TOP_N]
                bear_events.append({'ts': ts, 'date': day, 'symbols': bear_syms})

                # Bullish: highest cum_delta (most buying pressure)
                bull_syms = sorted_syms[-TOP_N:][::-1]
                bull_events.append({'ts': ts, 'date': day, 'symbols': bull_syms})

            t += timedelta(minutes=SUMMARY_INTERVAL)

    logger.info(f"Simulated {len(bull_events)} bullish summary events across "
                f"{len(set(e['date'] for e in bull_events))} days")
    logger.info(f"Simulated {len(bear_events)} bearish summary events across "
                f"{len(set(e['date'] for e in bear_events))} days")
    return bull_events, bear_events


# ── Price helpers ─────────────────────────────────────────────────────────────

def get_price_at(candles: List[dict], target: dt_time, max_age: int = 2) -> Optional[float]:
    """Close price of last candle within max_age minutes of target."""
    eligible = [c for c in candles
                if abs((c['date'].hour * 60 + c['date'].minute) -
                       (target.hour * 60 + target.minute)) <= max_age]
    return eligible[-1]['close'] if eligible else None


# ── Backtest core ─────────────────────────────────────────────────────────────

def run_backtest(events: List[dict], candle_map: Dict[str, List[dict]],
                 direction: str) -> List[dict]:
    """
    For each simulated summary event, enter top-N stocks at event time, exit EOD.
    direction: 'BULLISH' (long) or 'BEARISH' (short).
    """
    trades = []
    sign = 1 if direction == 'BULLISH' else -1

    for ev in events:
        d      = ev['date']
        ts     = ev['ts']
        syms   = ev['symbols']
        entry_t = ts.time()

        for sym in syms:
            key = f"{sym}_{d}"
            candles = candle_map.get(key, [])
            if not candles:
                continue

            entry_price = get_price_at(candles, entry_t, max_age=2)
            if not entry_price or entry_price <= 0:
                continue

            exit_price = get_price_at(candles, EOD_EXIT, max_age=5)
            if not exit_price or exit_price <= 0:
                continue

            raw_pnl = (exit_price - entry_price) / entry_price * 100
            net_pnl = sign * raw_pnl - ROUND_TRIP_CHARGES * 100

            trades.append({
                'direction':   direction,
                'date':        d,
                'symbol':      sym,
                'entry_time':  entry_t,
                'entry_price': round(entry_price, 2),
                'exit_price':  round(exit_price, 2),
                'raw_pnl':     round(raw_pnl, 3),
                'net_pnl':     round(net_pnl, 3),
                'entry_hhmm':  ts.strftime('%H:%M'),
            })

    return trades


# ── Time-bucket analysis ──────────────────────────────────────────────────────

def bucket_label(t: dt_time) -> str:
    mins = t.hour * 60 + t.minute
    bucket_start = (mins // 30) * 30
    bucket_end   = bucket_start + 30
    s = f"{bucket_start//60:02d}:{bucket_start%60:02d}"
    e = f"{bucket_end//60:02d}:{bucket_end%60:02d}"
    return f"{s}–{e}"


def analyze_by_time(trades: List[dict], direction: str):
    charge_pct = ROUND_TRIP_CHARGES * 100

    print(f"\n{'='*100}")
    print(f"{direction} POSITIONS — simulated 5-min summary → exit EOD 3:29 PM")
    print(f"Top-{TOP_N} stocks per summary  |  Charges: {charge_pct:.2f}% round trip")
    print(f"{'='*100}")

    if not trades:
        print("  No trades found.")
        return

    by_bucket = defaultdict(list)
    for t in trades:
        lbl = bucket_label(t['entry_time'])
        by_bucket[lbl].append(t)

    print(f"\n{'Time Bucket':15s} {'N':>6s} {'Wins':>5s} {'WinRate':>8s} "
          f"{'AvgWin':>8s} {'AvgLoss':>9s} {'AvgNet':>8s} {'TotalPnL':>10s}")
    print("-" * 82)

    bucket_results = []
    for bucket in sorted(by_bucket.keys()):
        bt = by_bucket[bucket]
        if len(bt) < MIN_TRADES:
            continue
        wins   = [t for t in bt if t['net_pnl'] > 0]
        losses = [t for t in bt if t['net_pnl'] <= 0]
        wr     = len(wins) / len(bt) * 100
        avg_w  = sum(t['net_pnl'] for t in wins)  / len(wins)   if wins   else 0
        avg_l  = sum(t['net_pnl'] for t in losses) / len(losses) if losses else 0
        avg_n  = sum(t['net_pnl'] for t in bt) / len(bt)
        tot    = sum(t['net_pnl'] for t in bt)
        flag   = ' ★' if wr >= 55 and avg_n > 0 else ''
        print(f"{bucket:15s} {len(bt):>6d} {len(wins):>5d} {wr:>7.1f}%"
              f" {avg_w:>+8.3f}% {avg_l:>+9.3f}% {avg_n:>+8.3f}% {tot:>+10.3f}%{flag}")
        bucket_results.append((bucket, len(bt), wr, avg_n))

    all_wins = [t for t in trades if t['net_pnl'] > 0]
    all_loss = [t for t in trades if t['net_pnl'] <= 0]
    wr_all   = len(all_wins) / len(trades) * 100
    avg_n_all = sum(t['net_pnl'] for t in trades) / len(trades)
    be_wr = 0.0
    if all_wins and all_loss:
        avg_w = sum(t['net_pnl'] for t in all_wins) / len(all_wins)
        avg_l = abs(sum(t['net_pnl'] for t in all_loss) / len(all_loss))
        be_wr = avg_l / (avg_w + avg_l) * 100

    print("-" * 82)
    print(f"{'OVERALL':15s} {len(trades):>6d} {len(all_wins):>5d} {wr_all:>7.1f}%"
          f"              {avg_n_all:>+8.3f}%")
    print(f"\n  Breakeven win rate: {be_wr:.1f}%  |  "
          f"{'PROFITABLE' if avg_n_all > 0 else 'LOSS-MAKING'} after charges")

    if bucket_results:
        best = max(bucket_results, key=lambda x: x[3])
        print(f"\n  Best entry window: {best[0]}  "
              f"({best[1]} trades, {best[2]:.1f}% wins, {best[3]:+.3f}% avg net)")

    # Per-date breakdown
    by_date = defaultdict(list)
    for t in trades:
        by_date[str(t['date'])].append(t)

    print(f"\nPER-DATE BREAKDOWN:")
    print(f"{'Date':12s} {'N':>5s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>8s} {'DayPnL':>9s}")
    print("-" * 60)
    for d in sorted(by_date.keys()):
        dt_t = by_date[d]
        wins = sum(1 for t in dt_t if t['net_pnl'] > 0)
        wr   = wins / len(dt_t) * 100
        avg  = sum(t['net_pnl'] for t in dt_t) / len(dt_t)
        tot  = sum(t['net_pnl'] for t in dt_t)
        flag = ' ★' if wr >= 55 and avg > 0 else ''
        print(f"{d:12s} {len(dt_t):>5d} {wins:>5d} {wr:>7.1f}% {avg:>+8.3f}% {tot:>+9.3f}%{flag}")

    # Top symbols
    sym_stats: Dict[str, dict] = {}
    for t in trades:
        s = sym_stats.setdefault(t['symbol'], {'n': 0, 'wins': 0, 'pnl': 0.0})
        s['n'] += 1
        s['wins'] += 1 if t['net_pnl'] > 0 else 0
        s['pnl'] += t['net_pnl']

    print(f"\nTOP PERFORMING SYMBOLS (≥5 appearances):")
    print(f"{'Symbol':16s} {'N':>5s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>8s} {'TotalPnL':>10s}")
    print("-" * 62)
    top_syms = sorted(
        [(sym, s) for sym, s in sym_stats.items() if s['n'] >= 5],
        key=lambda x: -x[1]['pnl'] / x[1]['n']
    )
    for sym, s in top_syms[:20]:
        avg = s['pnl'] / s['n']
        wr  = s['wins'] / s['n'] * 100
        flag = ' ★' if wr >= 60 and avg > 0 else ''
        print(f"{sym:16s} {s['n']:>5d} {s['wins']:>5d} {wr:>7.1f}% "
              f"{avg:>+8.3f}% {s['pnl']:>+10.3f}%{flag}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    logger.info(f"Trading days: {NSE_TRADING_DAYS[0]} → {NSE_TRADING_DAYS[-1]} "
                f"({len(NSE_TRADING_DAYS)} days)")

    # 1. Fetch candle data
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)
    candle_map = fetch_candles(kite)

    covered_dates = sorted(set(
        '_'.join(k.split('_')[1:]) for k in candle_map.keys()
    ))
    logger.info(f"Valid data for {len(covered_dates)} dates: {covered_dates}")

    # 2. Simulate 5-min summary events using bulk-volume cum_delta
    bull_events, bear_events = simulate_summaries(candle_map)

    # 3. Run backtests
    bull_trades = run_backtest(bull_events, candle_map, 'BULLISH')
    bear_trades = run_backtest(bear_events, candle_map, 'BEARISH')
    logger.info(f"Bullish trades: {len(bull_trades)}, Bearish trades: {len(bear_trades)}")

    # 4. Report
    analyze_by_time(bull_trades, 'BULLISH')
    analyze_by_time(bear_trades, 'BEARISH')


if __name__ == '__main__':
    main()
