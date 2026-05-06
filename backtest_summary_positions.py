#!/usr/bin/env python3
"""
Order Flow Summary Position Backtest.

Parses "Summary sent — top bullish/bearish" lines from order_flow_monitor.log.
For each summary event at time T, simulates entering the top-N stocks and
holding until EOD (3:29 PM same day).

Sweeps entry-time buckets (every 30 min) to find the optimal time to trade.

Separate analysis for BULLISH (long) and BEARISH (short) positions.

Note: bearish was added to the log on 2026-04-28. Historical data only has
bullish. Bearish analysis covers dates from 2026-04-28 onwards.

Usage:
    python backtest_summary_positions.py
"""

import json
import os
import re
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

LOG_FILE           = 'logs/order_flow_monitor.log'
TOKEN_FILE         = 'data/all_instrument_tokens.json'
CANDLE_CACHE       = 'data/backtest_summary_cache.json'
ROUND_TRIP_CHARGES = 0.0004   # 0.04% round trip
TOP_N              = 3         # use top-3 from each summary (most consistent)
MIN_TRADES         = 5         # minimum trades for a bucket to be reported
MARKET_OPEN        = dt_time(9, 15)
MARKET_CLOSE       = dt_time(15, 30)
EOD_EXIT           = dt_time(15, 29)   # sell at last minute of session

# ── Log parsing ───────────────────────────────────────────────────────────────

BULL_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .* Summary sent — top bullish: (\[.*?\])'
)
BEAR_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .* Summary sent — top bearish: (\[.*?\])'
)


def parse_summaries(log_file: str) -> Tuple[List[dict], List[dict]]:
    """
    Parse all summary lines from the log.
    Returns (bullish_events, bearish_events) where each event is:
      { 'ts': datetime, 'date': date, 'symbols': [str, ...] }
    """
    bullish_events = []
    bearish_events = []

    with open(log_file) as f:
        for line in f:
            m = BULL_RE.search(line)
            if m:
                ts = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
                symbols = json.loads(m.group(2).replace("'", '"'))
                bullish_events.append({'ts': ts, 'date': ts.date(), 'symbols': symbols})
                continue
            m = BEAR_RE.search(line)
            if m:
                ts = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
                symbols = json.loads(m.group(2).replace("'", '"'))
                bearish_events.append({'ts': ts, 'date': ts.date(), 'symbols': symbols})

    logger.info(f"Parsed {len(bullish_events)} bullish events across "
                f"{len(set(e['date'] for e in bullish_events))} days")
    logger.info(f"Parsed {len(bearish_events)} bearish events across "
                f"{len(set(e['date'] for e in bearish_events))} days")
    return bullish_events, bearish_events


# ── Candle fetching ───────────────────────────────────────────────────────────

def load_token_map() -> Dict[str, int]:
    with open(TOKEN_FILE) as f:
        return json.load(f)


def fetch_candles(kite: KiteConnect, all_symbols: List[str],
                  all_dates: List[date]) -> Dict[str, List[dict]]:
    """
    Fetch 1-min candles for all_symbols × all_dates.
    Returns { "SYMBOL_DATE": [candles] }
    """
    cache: Dict[str, list] = {}
    if os.path.exists(CANDLE_CACHE):
        try:
            with open(CANDLE_CACHE) as f:
                cache = json.load(f)
            logger.info(f"Loaded {len(cache)} cached series")
        except Exception:
            cache = {}

    token_map = load_token_map()
    needed = [(sym, d, f"{sym}_{d}") for sym in all_symbols for d in all_dates]
    to_fetch = [(sym, d, k) for sym, d, k in needed if k not in cache]

    # Validate cached entries: first candle date must match key date
    stale = [k for k, v in cache.items()
             if v and v[0]['date'][:10] != '_'.join(k.split('_')[1:])]
    for k in stale:
        del cache[k]
    if stale:
        logger.info(f"Purged {len(stale)} stale cache entries")
        to_fetch = [(sym, d, k) for sym, d, k in needed if k not in cache]

    logger.info(f"Need to fetch {len(to_fetch)} series (cached: {len(needed)-len(to_fetch)})")

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

    # Deserialise
    result = {}
    for key, candles in cache.items():
        if candles:
            result[key] = [
                {**c, 'date': datetime.strptime(c['date'], '%Y-%m-%d %H:%M:%S')}
                for c in candles
            ]
    return result


# ── Price helpers ─────────────────────────────────────────────────────────────

def get_price_at(candles: List[dict], target: dt_time,
                 max_age: int = 5, min_vol: int = 0) -> Optional[float]:
    """Price of last candle within max_age minutes of target with volume ≥ min_vol."""
    target_dt = datetime.min.replace(hour=target.hour, minute=target.minute)
    cutoff    = target_dt - timedelta(minutes=max_age)
    cutoff_t  = dt_time(cutoff.hour, cutoff.minute)
    eligible  = [c for c in candles
                 if cutoff_t <= c['date'].time() <= target
                 and c.get('volume', 0) >= min_vol]
    return eligible[-1]['close'] if eligible else None


# ── Backtest core ─────────────────────────────────────────────────────────────

def run_backtest(events: List[dict], candle_map: Dict[str, List[dict]],
                 direction: str) -> List[dict]:
    """
    For each summary event, enter top-N stocks at event time, exit at EOD.
    direction: 'BULLISH' (long) or 'BEARISH' (short)
    Returns list of trade dicts.
    """
    trades = []
    sign = 1 if direction == 'BULLISH' else -1   # +1 long, -1 short

    for ev in events:
        d      = ev['date']
        ts     = ev['ts']
        syms   = ev['symbols'][:TOP_N]
        entry_t = ts.time()

        # Only trade within reasonable market hours (9:20 AM – 3:00 PM)
        if entry_t < dt_time(9, 20) or entry_t > dt_time(15, 0):
            continue

        for sym in syms:
            key = f"{sym}_{d}"
            candles = candle_map.get(key, [])
            if not candles:
                continue

            # Entry: price at summary time (next candle after event)
            entry_price = get_price_at(candles, entry_t, max_age=2)
            if not entry_price or entry_price <= 0:
                continue

            # Exit: EOD close
            exit_price = get_price_at(candles, EOD_EXIT, max_age=5)
            if not exit_price or exit_price <= 0:
                continue

            # P&L: long gains when price rises, short gains when price falls
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
                'entry_hour':  ts.hour,
                'entry_hhmm':  ts.strftime('%H:%M'),
            })

    return trades


# ── Time-bucket analysis ──────────────────────────────────────────────────────

def bucket_label(t: dt_time) -> str:
    """Round time down to nearest 30-min bucket, return label like '10:00–10:30'."""
    mins = t.hour * 60 + t.minute
    bucket_start = (mins // 30) * 30
    bucket_end   = bucket_start + 30
    s = f"{bucket_start//60:02d}:{bucket_start%60:02d}"
    e = f"{bucket_end//60:02d}:{bucket_end%60:02d}"
    return f"{s}–{e}"


def analyze_by_time(trades: List[dict], direction: str):
    """Print bucket-by-bucket win rate and avg P&L, then overall stats."""
    charge_pct = ROUND_TRIP_CHARGES * 100

    print(f"\n{'='*100}")
    print(f"{direction} POSITIONS — enter at summary time, exit EOD 3:29 PM")
    print(f"Top-{TOP_N} stocks per summary  |  Charges: {charge_pct:.2f}% round trip")
    print(f"{'='*100}")

    if not trades:
        print("  No trades found.")
        return

    # Group by 30-min bucket
    by_bucket = defaultdict(list)
    for t in trades:
        lbl = bucket_label(t['entry_time'])
        by_bucket[lbl].append(t)

    print(f"\n{'Time Bucket':15s} {'N':>5s} {'Wins':>5s} {'WinRate':>8s} "
          f"{'AvgWin':>8s} {'AvgLoss':>9s} {'AvgNet':>8s} {'TotalPnL':>10s}")
    print("-" * 80)

    bucket_results = []
    for bucket in sorted(by_bucket.keys()):
        bt = by_bucket[bucket]
        if len(bt) < MIN_TRADES:
            continue
        wins   = [t for t in bt if t['net_pnl'] > 0]
        losses = [t for t in bt if t['net_pnl'] <= 0]
        wr     = len(wins) / len(bt) * 100
        avg_w  = sum(t['net_pnl'] for t in wins)  / len(wins)  if wins   else 0
        avg_l  = sum(t['net_pnl'] for t in losses) / len(losses) if losses else 0
        avg_n  = sum(t['net_pnl'] for t in bt) / len(bt)
        tot    = sum(t['net_pnl'] for t in bt)
        flag   = ' ★' if wr >= 55 and avg_n > 0 else ''
        print(f"{bucket:15s} {len(bt):>5d} {len(wins):>5d} {wr:>7.1f}%"
              f" {avg_w:>+8.3f}% {avg_l:>+9.3f}% {avg_n:>+8.3f}% {tot:>+10.3f}%{flag}")
        bucket_results.append((bucket, len(bt), wr, avg_n))

    # Overall
    all_wins = [t for t in trades if t['net_pnl'] > 0]
    all_loss = [t for t in trades if t['net_pnl'] <= 0]
    wr_all   = len(all_wins) / len(trades) * 100
    avg_n_all = sum(t['net_pnl'] for t in trades) / len(trades)
    be_wr    = abs(sum(t['net_pnl'] for t in all_loss)/len(all_loss)) / \
               (sum(t['net_pnl'] for t in all_wins)/len(all_wins) -
                abs(sum(t['net_pnl'] for t in all_loss)/len(all_loss))) * 100 \
               if all_wins and all_loss else 50
    print("-" * 80)
    print(f"{'OVERALL':15s} {len(trades):>5d} {len(all_wins):>5d} {wr_all:>7.1f}%"
          f"             {avg_n_all:>+8.3f}%")
    print(f"\n  Breakeven win rate: {be_wr:.1f}%  |  "
          f"{'PROFITABLE' if avg_n_all > 0 else 'LOSS-MAKING'} after charges")

    # Best bucket
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

    # Top winners and losers
    sorted_t = sorted(trades, key=lambda x: -x['net_pnl'])
    print(f"\nTOP 10 WINNERS:")
    print(f"{'Date':12s} {'Time':7s} {'Symbol':14s} {'Entry':>8s} {'Exit':>8s} {'Net PnL':>9s}")
    print("-" * 65)
    for t in sorted_t[:10]:
        print(f"{str(t['date']):12s} {t['entry_hhmm']:7s} {t['symbol']:14s} "
              f"{t['entry_price']:>8.2f} {t['exit_price']:>8.2f} {t['net_pnl']:>+9.3f}%")

    print(f"\nBOTTOM 10 LOSERS:")
    print(f"{'Date':12s} {'Time':7s} {'Symbol':14s} {'Entry':>8s} {'Exit':>8s} {'Net PnL':>9s}")
    print("-" * 65)
    for t in sorted_t[-10:]:
        print(f"{str(t['date']):12s} {t['entry_hhmm']:7s} {t['symbol']:14s} "
              f"{t['entry_price']:>8.2f} {t['exit_price']:>8.2f} {t['net_pnl']:>+9.3f}%")

    # Most frequent winners (consistent performers)
    sym_stats: Dict[str, dict] = {}
    for t in trades:
        s = sym_stats.setdefault(t['symbol'], {'n': 0, 'wins': 0, 'pnl': 0.0})
        s['n'] += 1
        s['wins'] += 1 if t['net_pnl'] > 0 else 0
        s['pnl'] += t['net_pnl']

    print(f"\nTOP PERFORMING SYMBOLS (≥3 appearances):")
    print(f"{'Symbol':16s} {'N':>4s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>8s} {'TotalPnL':>10s}")
    print("-" * 60)
    top_syms = sorted(
        [(sym, s) for sym, s in sym_stats.items() if s['n'] >= 3],
        key=lambda x: -x[1]['pnl'] / x[1]['n']
    )
    for sym, s in top_syms[:15]:
        avg = s['pnl'] / s['n']
        wr  = s['wins'] / s['n'] * 100
        flag = ' ★' if wr >= 60 and avg > 0 else ''
        print(f"{sym:16s} {s['n']:>4d} {s['wins']:>5d} {wr:>7.1f}% "
              f"{avg:>+8.3f}% {s['pnl']:>+10.3f}%{flag}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # 1. Parse log
    bull_events, bear_events = parse_summaries(LOG_FILE)

    if not bull_events and not bear_events:
        logger.error("No summary events found in log.")
        return

    # 2. Collect all symbols and dates needed
    all_events = bull_events + bear_events
    all_symbols = sorted(set(sym for ev in all_events for sym in ev['symbols'][:TOP_N]))
    all_dates   = sorted(set(ev['date'] for ev in all_events))
    logger.info(f"Need candle data: {len(all_symbols)} symbols × {len(all_dates)} dates")

    # 3. Fetch candle data
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)
    candle_map = fetch_candles(kite, all_symbols, all_dates)

    # 4. Run backtests
    bull_trades = run_backtest(bull_events, candle_map, 'BULLISH')
    bear_trades = run_backtest(bear_events, candle_map, 'BEARISH')

    logger.info(f"Bullish trades: {len(bull_trades)}, Bearish trades: {len(bear_trades)}")

    # 5. Report
    analyze_by_time(bull_trades, 'BULLISH')
    if bear_trades:
        analyze_by_time(bear_trades, 'BEARISH')
    else:
        print(f"\n{'='*100}")
        print("BEARISH: No historical data yet. The log was updated to record bearish summaries")
        print("going forward. Run again in a few days to see bearish performance.")
        print("="*100)


if __name__ == '__main__':
    main()
