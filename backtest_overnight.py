#!/usr/bin/env python3
"""
Overnight Order Flow Backtest — Buy/Short at EOD close, exit next day at 9:25 AM.

Strategy:
  BULLISH alert fires during day → buy at 3:29 PM close → sell next day at 9:25 AM
  BEARISH alert fires during day → short at 3:29 PM close → cover next day at 9:25 AM

Uses alerts from order_flow_monitor.log across all available dates.
Sweeps over signal quality filters to find which produce profitable overnight moves.

Usage:
    python backtest_overnight.py
"""

import json
import os
import re
import time
import logging
from datetime import date, datetime, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple

from kiteconnect import KiteConnect
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

LOG_FILE      = 'logs/order_flow_monitor.log'
TOKEN_FILE    = 'data/all_instrument_tokens.json'
CANDLE_CACHE  = 'data/backtest_overnight_candle_cache.json'

# Exit time: 9:25 AM next day
EXIT_TIME = dt_time(9, 25)

# Trading charges: 0.04% round trip (futures, conservative)
ROUND_TRIP_CHARGES = 0.0004

# Known NSE trading days (from results_cache) — used to find "next trading day"
NSE_TRADING_DAYS = sorted([
    date(2026, 4, 16), date(2026, 4, 17), date(2026, 4, 18),
    date(2026, 4, 20), date(2026, 4, 21), date(2026, 4, 22),
    date(2026, 4, 23), date(2026, 4, 24), date(2026, 4, 25),
    date(2026, 4, 26), date(2026, 4, 27), date(2026, 4, 28),
    date(2026, 4, 29), date(2026, 4, 30),
    date(2026, 5, 2),  date(2026, 5, 4),  date(2026, 5, 5),
    date(2026, 5, 6),  date(2026, 5, 7),  date(2026, 5, 8),
    date(2026, 5, 9),  date(2026, 5, 11), date(2026, 5, 12),
    date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15),
    date(2026, 5, 19), date(2026, 5, 20), date(2026, 5, 21),
    date(2026, 5, 22), date(2026, 5, 25), date(2026, 5, 26),
    date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29),
])
NSE_TRADING_DAYS_SET = set(NSE_TRADING_DAYS)


def next_trading_day(d: date) -> Optional[date]:
    """Return the next NSE trading day after d."""
    for td in NSE_TRADING_DAYS:
        if td > d:
            return td
    return None


# ── Log parsing ───────────────────────────────────────────────────────────────

ALERT_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - (?:__main__|order_flow_monitor) - INFO - '
    r'(BEARISH|BULLISH): (\w[\w\-]*) score=(\d+) — \S+ \((.+)\)'
)


def parse_alerts(log_file: str) -> List[dict]:
    """Parse all BEARISH/BULLISH alerts from log. Tag signal components."""
    alerts = []

    with open(log_file) as f:
        for line in f:
            m = ALERT_RE.match(line)
            if not m:
                continue
            ts_str, direction, symbol, score, reasons = m.groups()
            if symbol in ('TESTSTOCK', 'BULLSTOCK'):
                continue
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

            # Only include dates where we have a known next trading day
            alert_date = ts.date()
            next_day = next_trading_day(alert_date)
            if next_day is None:
                continue

            # Tag signal components
            has_cash_flow_bear = bool(re.search(r'5m flow -', reasons))
            has_cash_flow_bull = bool(re.search(r'5m flow \+', reasons))
            has_cash_flow = has_cash_flow_bear or has_cash_flow_bull
            directional_cash = (
                (direction == 'BEARISH' and has_cash_flow_bear) or
                (direction == 'BULLISH' and has_cash_flow_bull)
            )
            has_velocity  = bool(re.search(r'vel ₹[1-9]', reasons))
            has_fut_bai   = 'FUT BAI' in reasons
            has_fut_flow  = 'FUT 5m' in reasons
            has_basis     = 'basis' in reasons
            has_bai_shift = 'BAI shift' in reasons
            has_l1_shrink = 'L1 bid' in reasons

            score_int = int(score)
            # Adjusted score: remove L1 shrink point (known noise signal)
            adj_score = max(0, score_int - (1 if has_l1_shrink else 0))

            alerts.append({
                'ts':               ts,
                'alert_date':       alert_date,
                'next_day':         next_day,
                'direction':        direction,
                'symbol':           symbol,
                'score':            score_int,
                'adj_score':        adj_score,
                'reasons':          reasons,
                'has_cash_flow':    has_cash_flow,
                'directional_cash': directional_cash,
                'has_velocity':     has_velocity,
                'has_fut_bai':      has_fut_bai,
                'has_fut_flow':     has_fut_flow,
                'has_basis':        has_basis,
                'has_bai_shift':    has_bai_shift,
                'has_l1_shrink':    has_l1_shrink,
            })

    logger.info(f"Parsed {len(alerts)} total alerts")
    by_date = {}
    for a in alerts:
        by_date.setdefault(str(a['alert_date']), 0)
        by_date[str(a['alert_date'])] += 1
    for d, n in sorted(by_date.items()):
        logger.info(f"  {d}: {n} alerts")
    return alerts


# ── Candle fetching ───────────────────────────────────────────────────────────

def load_token_map() -> Dict[str, int]:
    with open(TOKEN_FILE) as f:
        return json.load(f)


def fetch_candles(kite: KiteConnect, alerts: List[dict], token_map: Dict[str, int]) -> Dict[str, List[dict]]:
    """
    Fetch 1-min candles for each unique (symbol, date) and (symbol, next_day).
    Cache to disk. Returns {"{SYMBOL}_{DATE}": [candles]}.
    """
    cache = {}
    if os.path.exists(CANDLE_CACHE):
        try:
            with open(CANDLE_CACHE) as f:
                cache = json.load(f)
            logger.info(f"Loaded {len(cache)} cached series")
        except Exception:
            cache = {}

    # Collect all (symbol, day) pairs needed
    needed = set()
    for a in alerts:
        needed.add((a['symbol'], a['alert_date']))
        needed.add((a['symbol'], a['next_day']))

    to_fetch = [(sym, day, f"{sym}_{day}") for sym, day in sorted(needed)
                if f"{sym}_{day}" not in cache]
    logger.info(f"Need to fetch {len(to_fetch)} series (cached: {len(needed) - len(to_fetch)})")

    for i, (symbol, day, key) in enumerate(to_fetch):
        token = token_map.get(symbol)
        if not token:
            cache[key] = []
            continue

        from_dt = datetime.combine(day, dt_time(9, 15))
        to_dt   = datetime.combine(day, dt_time(15, 31))
        try:
            raw = kite.historical_data(
                instrument_token=token,
                from_date=from_dt,
                to_date=to_dt,
                interval='minute',
                continuous=False,
                oi=False,
            )
            cache[key] = [
                {'date': c['date'].strftime('%Y-%m-%d %H:%M:%S'),
                 'open': c['open'], 'high': c['high'],
                 'low': c['low'], 'close': c['close'], 'volume': c['volume']}
                for c in raw
            ]
            logger.info(f"Fetched {len(cache[key])} candles for {symbol} on {day}")
        except Exception as e:
            logger.warning(f"Failed {symbol} {day}: {e}")
            cache[key] = []
        time.sleep(0.25)

    if to_fetch:
        with open(CANDLE_CACHE, 'w') as f:
            json.dump(cache, f)
        logger.info(f"Cache saved ({len(cache)} series total)")

    # Deserialise
    result = {}
    for key, candles in cache.items():
        result[key] = [
            {**c, 'date': datetime.strptime(c['date'], '%Y-%m-%d %H:%M:%S')}
            for c in candles
        ]
    return result


# ── Price lookup ──────────────────────────────────────────────────────────────

def get_eod_price(candles: List[dict], target_time: dt_time = dt_time(15, 29)) -> Optional[float]:
    """
    Get the closing price at EOD — last candle at or before target_time.
    Uses 3:29 PM candle (last full minute before 3:30 PM close).
    """
    eligible = [c for c in candles if c['date'].time() <= target_time]
    if not eligible:
        return None
    return eligible[-1]['close']


def get_open_price(candles: List[dict], target_time: dt_time = EXIT_TIME) -> Optional[float]:
    """
    Get price at target_time on next day (9:25 AM).
    Takes the close of the candle at or just before target_time.
    """
    eligible = [c for c in candles if c['date'].time() <= target_time]
    if not eligible:
        return None
    # Find the candle closest to target_time
    return eligible[-1]['close']


# ── Simulation ────────────────────────────────────────────────────────────────

def simulate_overnight(alert: dict, candle_map: Dict[str, List[dict]]) -> Optional[dict]:
    """
    Simulate the overnight trade for a single alert.
    Entry: EOD price on alert_date (3:29 PM close)
    Exit: 9:25 AM price on next_day
    """
    sym = alert['symbol']
    alert_date = alert['alert_date']
    next_day = alert['next_day']
    direction = alert['direction']

    day_key  = f"{sym}_{alert_date}"
    next_key = f"{sym}_{next_day}"

    day_candles  = candle_map.get(day_key, [])
    next_candles = candle_map.get(next_key, [])

    if not day_candles or not next_candles:
        return None

    entry_price = get_eod_price(day_candles)
    exit_price  = get_open_price(next_candles)

    if not entry_price or not exit_price or entry_price <= 0:
        return None

    if direction == 'BULLISH':
        pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:  # BEARISH (short)
        pnl_pct = (entry_price - exit_price) / entry_price * 100

    pnl_net = pnl_pct - (ROUND_TRIP_CHARGES * 100)

    return {
        'entry_price': round(entry_price, 2),
        'exit_price':  round(exit_price, 2),
        'pnl_pct':     round(pnl_pct, 3),
        'pnl_net':     round(pnl_net, 3),
    }


# ── Parameter sweep ───────────────────────────────────────────────────────────

# Alert time windows: only consider alerts fired AFTER this time
TIME_WINDOWS = [
    (dt_time(9, 20),  'any_time'),
    (dt_time(10, 0),  'after_10am'),
    (dt_time(12, 0),  'after_noon'),
    (dt_time(13, 0),  'after_1pm'),
    (dt_time(14, 0),  'after_2pm'),
    (dt_time(14, 30), 'after_230pm'),
]

# Alert time cutoffs: only consider alerts fired BEFORE this time
TIME_CUTOFFS = [
    (dt_time(15, 30), 'before_close'),
    (dt_time(15, 15), 'before_315pm'),
    (dt_time(14, 30), 'before_230pm'),
]

# Signal quality filters: (name, filter_fn)
SIGNAL_FILTERS = [
    ('all_alerts',       lambda a: True),
    ('directional_cash', lambda a: a['directional_cash']),
    ('score6plus',       lambda a: a['score'] >= 6),
    ('score7plus',       lambda a: a['score'] >= 7),
    ('score8plus',       lambda a: a['score'] >= 8),
    ('cash_AND_fut_bai', lambda a: a['directional_cash'] and a['has_fut_bai']),
    ('cash_AND_basis',   lambda a: a['directional_cash'] and a['has_basis']),
    ('cash_fut_OR_basis',lambda a: a['directional_cash'] and (a['has_fut_bai'] or a['has_basis'])),
    ('fut_bai_only',     lambda a: a['has_fut_bai']),
    ('basis_only',       lambda a: a['has_basis']),
    ('high_quality',     lambda a: a['directional_cash'] and (a['has_fut_bai'] or a['has_basis']) and a['score'] >= 6),
    ('top_quality',      lambda a: a['directional_cash'] and (a['has_fut_bai'] or a['has_basis']) and a['score'] >= 7),
    ('adj_score5plus',   lambda a: a['directional_cash'] and a['adj_score'] >= 5),
    ('adj_score6plus',   lambda a: a['directional_cash'] and a['adj_score'] >= 6),
    ('cash_AND_vel',     lambda a: a['directional_cash'] and a['has_velocity']),
    ('fut_bai_vel',      lambda a: a['has_fut_bai'] and a['has_velocity']),
    ('late_day_quality', lambda a: a['directional_cash'] and (a['has_fut_bai'] or a['has_basis'])),
]

# Direction filters
DIRECTION_FILTERS = [
    ('both',     lambda a: True),
    ('BULLISH',  lambda a: a['direction'] == 'BULLISH'),
    ('BEARISH',  lambda a: a['direction'] == 'BEARISH'),
]

MIN_TRADES = 5   # skip configs with too few trades


def run_sweep(alerts: List[dict], candle_map: Dict[str, List[dict]]) -> List[dict]:
    """Sweep all parameter combinations, return results sorted by avg net P&L."""

    # Pre-simulate all alerts first (avoid re-simulating in nested loop)
    logger.info("Pre-simulating all alerts...")
    simulated = []
    for a in alerts:
        sim = simulate_overnight(a, candle_map)
        if sim:
            simulated.append({**a, **sim})

    logger.info(f"Successfully simulated {len(simulated)} / {len(alerts)} alerts")

    # First deduplicate per (symbol, direction, date) — keep best-scoring alert of the day
    # This avoids counting the same overnight position multiple times
    deduped = []
    seen = {}
    for t in sorted(simulated, key=lambda x: -x['score']):  # highest score first
        key = (t['symbol'], t['direction'], t['alert_date'])
        if key not in seen:
            seen[key] = t
            deduped.append(t)
    logger.info(f"After dedup (1 trade per stock/direction/day): {len(deduped)} trades")

    results = []
    total_combos = len(SIGNAL_FILTERS) * len(TIME_WINDOWS) * len(TIME_CUTOFFS) * len(DIRECTION_FILTERS)
    logger.info(f"Running sweep: {total_combos} combinations...")

    for (filter_name, filter_fn), (min_time, time_label), (max_time, cutoff_label), (dir_name, dir_fn) in (
        (sf, tw, tc, df)
        for sf in SIGNAL_FILTERS
        for tw in TIME_WINDOWS
        for tc in TIME_CUTOFFS
        for df in DIRECTION_FILTERS
    ):
        if min_time >= max_time:
            continue

        trades = [
            t for t in deduped
            if filter_fn(t) and dir_fn(t)
            and t['ts'].time() >= min_time
            and t['ts'].time() < max_time
        ]

        if len(trades) < MIN_TRADES:
            continue

        winners = [t for t in trades if t['pnl_net'] > 0]
        losers  = [t for t in trades if t['pnl_net'] <= 0]
        win_rate  = len(winners) / len(trades) * 100
        avg_win   = sum(t['pnl_net'] for t in winners) / len(winners) if winners else 0
        avg_loss  = sum(t['pnl_net'] for t in losers)  / len(losers)  if losers  else 0
        avg_net   = sum(t['pnl_net'] for t in trades)  / len(trades)

        results.append({
            'filter':     filter_name,
            'time_from':  time_label,
            'time_to':    cutoff_label,
            'direction':  dir_name,
            'n_trades':   len(trades),
            'win_rate':   round(win_rate, 1),
            'avg_win':    round(avg_win, 3),
            'avg_loss':   round(avg_loss, 3),
            'avg_net':    round(avg_net, 3),
            'trades':     trades,
        })

    results.sort(key=lambda x: (x['avg_net'], x['win_rate']), reverse=True)
    return results, deduped


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_report(results: List[dict], all_trades: List[dict]):
    charge_pct = ROUND_TRIP_CHARGES * 100

    print("\n" + "="*120)
    print("OVERNIGHT ORDER FLOW BACKTEST — Buy at EOD Close, Exit Next Day at 9:25 AM")
    print(f"Charges: {charge_pct:.2f}% round trip  |  Min trades threshold: {MIN_TRADES}")
    print("="*120)

    # Overall stats on all deduped trades
    if all_trades:
        w = [t for t in all_trades if t['pnl_net'] > 0]
        print(f"\nALL ALERTS (no filter): {len(all_trades)} trades | "
              f"win rate: {len(w)/len(all_trades)*100:.1f}% | "
              f"avg net: {sum(t['pnl_net'] for t in all_trades)/len(all_trades):+.3f}%\n")

    if not results:
        print("No valid configurations found.")
        return

    above60 = [r for r in results if r['win_rate'] >= 60.0]
    profitable = [r for r in results if r['avg_net'] > 0]
    above60_profitable = [r for r in results if r['win_rate'] >= 60 and r['avg_net'] > 0]
    above70_profitable = [r for r in results if r['win_rate'] >= 70 and r['avg_net'] > 0]

    print(f"  Configs with win rate ≥ 60% AND positive net P&L: {len(above60_profitable)}")
    print(f"  Configs with win rate ≥ 70% AND positive net P&L: {len(above70_profitable)}")
    print(f"  Total valid configurations: {len(results)}")

    print(f"\nTOP 25 CONFIGURATIONS (by avg net P&L after {charge_pct:.2f}% charges):\n")
    print(f"{'#':3s} {'Filter':20s} {'From':12s} {'To':14s} {'Dir':8s} "
          f"{'N':>5s} {'WinRate':>8s} {'AvgWin':>8s} {'AvgLoss':>9s} {'AvgNet':>8s}")
    print("-"*120)

    for i, r in enumerate(results[:25], 1):
        flag = ' ★' if r['win_rate'] >= 60 and r['avg_net'] > 0 else ''
        print(
            f"{i:3d} {r['filter']:20s} {r['time_from']:12s} {r['time_to']:14s} "
            f"{r['direction']:8s} {r['n_trades']:5d} {r['win_rate']:7.1f}% "
            f"{r['avg_win']:+8.3f}% {r['avg_loss']:+9.3f}% {r['avg_net']:+8.3f}%{flag}"
        )

    # Best config drill-down
    best = results[0]
    print(f"\n\n{'='*120}")
    print(f"BEST CONFIG DRILL-DOWN:")
    print(f"  filter={best['filter']}  time={best['time_from']} → {best['time_to']}  "
          f"direction={best['direction']}")
    print(f"  Trades: {best['n_trades']}  Win rate: {best['win_rate']}%  "
          f"Avg net: {best['avg_net']:+.3f}%  "
          f"Avg win: {best['avg_win']:+.3f}%  Avg loss: {best['avg_loss']:+.3f}%")
    print("="*120)
    print(f"\n{'Date':12s} {'Time':7s} {'Dir':8s} {'Symbol':12s} {'Score':5s} "
          f"{'Entry':9s} {'Exit(9:25)':10s} {'P&L net':8s} {'Win':4s} Signals")
    print("-"*120)

    by_date: Dict[str, list] = {}
    for t in best['trades']:
        d = str(t['alert_date'])
        by_date.setdefault(d, []).append(t)

    for d, day_trades in sorted(by_date.items()):
        wins = [t for t in day_trades if t['pnl_net'] > 0]
        avg  = sum(t['pnl_net'] for t in day_trades) / len(day_trades)
        print(f"\n── {d} (exit on {day_trades[0]['next_day']}) "
              f"— {len(wins)}/{len(day_trades)} wins | avg: {avg:+.3f}%")
        for t in sorted(day_trades, key=lambda x: x['ts']):
            mark = '✓' if t['pnl_net'] > 0 else '✗'
            print(
                f"{str(t['alert_date']):12s} {t['ts'].strftime('%H:%M'):7s} "
                f"{t['direction']:8s} {t['symbol']:12s} {t['score']:5d} "
                f"{t['entry_price']:9.2f} {t['exit_price']:10.2f} "
                f"{t['pnl_net']:+7.3f}% {mark}  {t['reasons']}"
            )

    # Direction breakdown across all deduped trades
    print(f"\n\n{'='*120}")
    print("DIRECTION BREAKDOWN (all deduped trades, no filter):\n")
    for dir_label in ['BULLISH', 'BEARISH']:
        sub = [t for t in all_trades if t['direction'] == dir_label]
        if not sub:
            continue
        wins = [t for t in sub if t['pnl_net'] > 0]
        wr   = len(wins) / len(sub) * 100
        avg  = sum(t['pnl_net'] for t in sub) / len(sub)
        aw   = sum(t['pnl_net'] for t in wins) / len(wins) if wins else 0
        ll   = [t for t in sub if t['pnl_net'] <= 0]
        al   = sum(t['pnl_net'] for t in ll) / len(ll) if ll else 0
        print(f"  {dir_label:8s}: n={len(sub):4d}  win={wr:5.1f}%  avg_net={avg:+.3f}%  "
              f"avg_win={aw:+.3f}%  avg_loss={al:+.3f}%")

    # Signal quality breakdown
    print(f"\n\n{'='*120}")
    print("SIGNAL QUALITY BREAKDOWN (all deduped trades):\n")
    signal_fields = [
        ('directional_cash', 'directional cash flow'),
        ('has_fut_bai',      'futures BAI shift'),
        ('has_basis',        'basis divergence'),
        ('has_velocity',     'tick velocity'),
        ('has_fut_flow',     'futures 5m flow'),
        ('has_l1_shrink',    'L1 bid shrink'),
    ]
    print(f"{'Signal':25s} {'N':>5s} {'WinRate':>8s} {'AvgNet':>9s}")
    print("-"*55)
    for field, label in signal_fields:
        with_sig = [t for t in all_trades if t.get(field)]
        without  = [t for t in all_trades if not t.get(field)]
        if with_sig:
            wr  = sum(1 for t in with_sig if t['pnl_net'] > 0) / len(with_sig) * 100
            avg = sum(t['pnl_net'] for t in with_sig) / len(with_sig)
            print(f"  {label:23s}: {len(with_sig):5d} {wr:7.1f}% {avg:+8.3f}%")
        if without:
            wr  = sum(1 for t in without if t['pnl_net'] > 0) / len(without) * 100
            avg = sum(t['pnl_net'] for t in without) / len(without)
            print(f"  no {label:20s}: {len(without):5d} {wr:7.1f}% {avg:+8.3f}%")

    # Score histogram
    print(f"\n\n{'='*120}")
    print("WIN RATE BY SCORE (all deduped trades):\n")
    print(f"{'Score':8s} {'N':>5s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>9s}")
    print("-"*40)
    score_groups = {}
    for t in all_trades:
        score_groups.setdefault(t['score'], []).append(t)
    for s in sorted(score_groups.keys()):
        sub = score_groups[s]
        wins = [t for t in sub if t['pnl_net'] > 0]
        wr  = len(wins) / len(sub) * 100
        avg = sum(t['pnl_net'] for t in sub) / len(sub)
        print(f"  score={s}: {len(sub):5d} {len(wins):5d} {wr:7.1f}% {avg:+8.3f}%")

    # Time-of-day analysis
    print(f"\n\n{'='*120}")
    print("WIN RATE BY TIME OF DAY (all deduped trades, 30-min buckets):\n")
    print(f"{'Window':18s} {'N':>5s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>9s}")
    print("-"*50)
    hour_groups = {}
    for t in all_trades:
        h = t['ts'].hour
        m = (t['ts'].minute // 30) * 30
        bucket = f"{h:02d}:{m:02d}-{h:02d}:{m+29:02d}"
        hour_groups.setdefault(bucket, []).append(t)
    for bucket in sorted(hour_groups.keys()):
        sub = hour_groups[bucket]
        wins = [t for t in sub if t['pnl_net'] > 0]
        wr  = len(wins) / len(sub) * 100
        avg = sum(t['pnl_net'] for t in sub) / len(sub)
        print(f"  {bucket:16s}: {len(sub):5d} {len(wins):5d} {wr:7.1f}% {avg:+8.3f}%")

    print(f"\n\nDone. {len(results)} configurations evaluated.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    token_map = load_token_map()

    logger.info("Parsing alerts from log...")
    alerts = parse_alerts(LOG_FILE)

    if not alerts:
        print("No alerts found in log file.")
        return

    logger.info("Fetching/loading candle data...")
    candle_map = fetch_candles(kite, alerts, token_map)

    logger.info("Running parameter sweep...")
    results, all_deduped_trades = run_sweep(alerts, candle_map)

    logger.info(f"Sweep complete: {len(results)} valid configurations")
    print_report(results, all_deduped_trades)


if __name__ == '__main__':
    main()
