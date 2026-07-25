#!/usr/bin/env python3
"""
Candle reversal (hammer / shooting star) backtest with a trailing stop on futures.

Question: if we took EVERY alert the live candle_confirmation_monitor fires — long futures on
a confirmed hammer, short futures on a confirmed shooting star — and managed it with nothing
but a percentage trailing stop, squaring off at the end of the same day, what would it earn?

It imports the LIVE detection function (detect_reversal_confirmation) rather than
reimplementing it, so the signal set can never drift from what the running monitor produces.
Each 5-min bar is offered once as the confirmation bar, exactly as the monitor sees the latest
closed bar each cycle, with the same per-(symbol, direction) cooldown.

Trade model:
  entry   = confirmation candle's close (the moment the alert fires)
  stop    = trailing, TRAIL% below the highest price seen since entry (long) / above the
            lowest (short); starts at TRAIL% from entry
  exit    = stop hit, else square-off at the last bar starting <= 15:15
  price   = the stock's 5-min SPOT candles as a proxy for the futures price (expired-contract
            futures history is not reliably fetchable); costs are charged separately

Within a bar the true tick order is unknown, so the stop is tested against the bar's adverse
extreme BEFORE the bar's favourable extreme is allowed to raise the trail — the pessimistic
reading. A gap through the stop fills at the bar's open, not at the stop.

Usage:
    venv/bin/python3 backtest_candle_reversal_trail.py                    # 6 months, 0.3 & 0.5
    venv/bin/python3 backtest_candle_reversal_trail.py --months 3 --stocks 40
    venv/bin/python3 backtest_candle_reversal_trail.py --trail 0.3 0.5 0.75 --cost-pct 0.05

Read-only: fetches candles (cached under data/candle_reversal_5min/) and prints a report.
Sends no alerts and writes no live state.

Author: Claude Code
Date: 2026-07-23
"""

import argparse
import gzip
import json
import os
import pickle
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime
from typing import Dict, List, Optional, Tuple

from kiteconnect import KiteConnect

import config
from candle_confirmation_monitor import detect_reversal_confirmation
from pattern_detectors.reversal_patterns import HammerDetector, ShootingStarDetector

CACHE_DIR = 'data/candle_reversal_5min'
INSTRUMENT_TOKENS_FILE = 'data/instrument_tokens.json'
INTERVAL = '5minute'
CHUNK_DAYS = 60                 # Kite caps a 5-minute historical request at 100 days
SQUARE_OFF = dtime(15, 15)      # last bar allowed to open; it closes at 15:20
# Bars of history handed to the detector each step. It needs 12; more only changes the
# 20-bar volume baseline, which is already covered well before 40.
WINDOW = 40


# ----------------------------------------------------------------------------- data

def _cache_path(symbol: str) -> str:
    return os.path.join(CACHE_DIR, f'{symbol}.pkl.gz')


def fetch_symbol_candles(kite, token: int, symbol: str, start: datetime, end: datetime,
                         refresh: bool) -> List[Dict]:
    """5-min candles for one symbol over [start, end], cached per symbol on disk."""
    path = _cache_path(symbol)
    if os.path.exists(path) and not refresh:
        with gzip.open(path, 'rb') as f:
            cached = pickle.load(f)
        if cached['start'] <= start and cached['end'] >= end - timedelta(days=1):
            return [c for c in cached['candles'] if start <= c['date'].replace(tzinfo=None) <= end]

    candles: List[Dict] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=CHUNK_DAYS), end)
        for attempt in range(3):
            try:
                candles.extend(kite.historical_data(token, cursor, stop, INTERVAL))
                break
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
        cursor = stop
        time.sleep(config.REQUEST_DELAY_SECONDS)

    slim = [{'date': c['date'], 'open': c['open'], 'high': c['high'], 'low': c['low'],
             'close': c['close'], 'volume': c['volume']} for c in candles]
    os.makedirs(CACHE_DIR, exist_ok=True)
    with gzip.open(path, 'wb') as f:
        pickle.dump({'start': start, 'end': end, 'candles': slim}, f)
    return slim


# ------------------------------------------------------------------------- signals

def find_signals(symbol: str, candles: List[Dict], hammer, star) -> List[Dict]:
    """Replay the live detector bar by bar; return the alerts it would have fired."""
    signals = []
    last_alert: Dict[str, datetime] = {}
    for i in range(WINDOW, len(candles)):
        window = candles[i - WINDOW:i + 1]
        sig = detect_reversal_confirmation(window, hammer, star)
        if not sig:
            continue
        ts = candles[i]['date']
        direction = sig['direction']
        prev = last_alert.get(direction)
        if prev and (ts - prev).total_seconds() / 60 < config.CANDLE_COOLDOWN_MINUTES:
            continue                                   # cooldown suppresses, same as live
        last_alert[direction] = ts
        signals.append({
            'symbol': symbol, 'time': ts, 'direction': direction, 'pattern': sig['pattern'],
            'entry': sig['entry'], 'fixed_stop': sig['stop'], 'target': sig['target'],
            'volume_ratio': sig['volume_ratio'], 'confidence': sig['confidence'],
            'bar_index': i,
        })
    return signals


# --------------------------------------------------------------------- trade model

def simulate(signal: Dict, candles: List[Dict], trail_pct: float) -> Optional[Dict]:
    """
    Walk the bars after the alert with a trailing stop; square off at the end of the day.

    Returns the trade dict, or None if the alert fired on the day's last usable bar (nothing
    left to trade).
    """
    entry = signal['entry']
    long = signal['direction'] == 'BULLISH'
    day = signal['time'].date()
    t = trail_pct / 100.0

    best = entry
    stop = entry * (1 - t) if long else entry * (1 + t)
    exit_price = None
    exit_reason = ''
    bars = 0
    mfe = 0.0                                          # best unrealised move, % of entry

    for c in candles[signal['bar_index'] + 1:]:
        if c['date'].date() != day:
            break
        bars += 1
        # Pessimistic intra-bar order: the stop is tested before this bar can raise the trail.
        if long and c['low'] <= stop:
            exit_price, exit_reason = min(stop, c['open']), 'TRAIL'
            break
        if not long and c['high'] >= stop:
            exit_price, exit_reason = max(stop, c['open']), 'TRAIL'
            break

        if long:
            best = max(best, c['high'])
            stop = max(stop, best * (1 - t))
            mfe = max(mfe, (best - entry) / entry * 100)
        else:
            best = min(best, c['low'])
            stop = min(stop, best * (1 + t))
            mfe = max(mfe, (entry - best) / entry * 100)

        if c['date'].time() >= SQUARE_OFF:
            exit_price, exit_reason = c['close'], 'EOD'
            break

    if exit_price is None:
        if bars == 0:
            return None                                # alert on the last bar of the day
        exit_price, exit_reason = candles[signal['bar_index'] + bars]['close'], 'EOD'

    gross = ((exit_price - entry) if long else (entry - exit_price)) / entry * 100
    return {**signal, 'exit_price': exit_price, 'exit_reason': exit_reason,
            'bars_held': bars, 'gross_pct': gross, 'mfe_pct': mfe}


def simulate_hold(signal: Dict, candles: List[Dict]) -> Optional[Dict]:
    """Reference case: no stop at all, hold from the alert to the day's square-off."""
    day = signal['time'].date()
    same_day = [c for c in candles[signal['bar_index'] + 1:] if c['date'].date() == day]
    if not same_day:
        return None
    usable = [c for c in same_day if c['date'].time() <= SQUARE_OFF] or same_day[:1]
    entry, exit_price = signal['entry'], usable[-1]['close']
    long = signal['direction'] == 'BULLISH'
    gross = ((exit_price - entry) if long else (entry - exit_price)) / entry * 100
    return {**signal, 'exit_price': exit_price, 'exit_reason': 'EOD', 'exit_time': usable[-1]['date'],
            'bars_held': len(usable), 'gross_pct': gross, 'mfe_pct': 0.0}


# ---------------------------------------------------------------------- reporting

def stats(trades: List[Dict], cost_pct: float) -> Dict:
    if not trades:
        return {'n': 0}
    net = [t['gross_pct'] - cost_pct for t in trades]
    wins = [r for r in net if r > 0]
    losses = [r for r in net if r <= 0]
    return {
        'n': len(net),
        'win_rate': len(wins) / len(net) * 100,
        'avg': statistics.mean(net),
        'median': statistics.median(net),
        'total': sum(net),
        'avg_win': statistics.mean(wins) if wins else 0.0,
        'avg_loss': statistics.mean(losses) if losses else 0.0,
        'best': max(net),
        'worst': min(net),
        'expectancy': statistics.mean(net),
        'profit_factor': (sum(wins) / abs(sum(losses))) if losses and sum(losses) else float('inf'),
        'avg_bars': statistics.mean([t['bars_held'] for t in trades]),
        'avg_mfe': statistics.mean([t['mfe_pct'] for t in trades]),
        'trail_exits': sum(1 for t in trades if t['exit_reason'] == 'TRAIL') / len(net) * 100,
    }


def print_row(label: str, s: Dict):
    if not s['n']:
        print(f"  {label:<22} —")
        return
    print(f"  {label:<22} {s['n']:>5}  {s['win_rate']:>6.1f}%  {s['avg']:>+7.3f}%  "
          f"{s['median']:>+7.3f}%  {s['total']:>+9.1f}%  {s['avg_win']:>+6.2f}% "
          f"{s['avg_loss']:>+6.2f}%  {s['profit_factor']:>5.2f}  {s['avg_bars']:>5.1f}")


HEADER = (f"  {'':<22} {'N':>5}  {'Win%':>6}  {'Avg':>8}  {'Median':>8}  {'Total':>9}  "
          f"{'AvgWin':>7} {'AvgLoss':>7}  {'PF':>5}  {'Bars':>5}")


def report(all_trades: Dict[float, List[Dict]], hold_trades: List[Dict],
           cost_pct: float, meta: Dict):
    print()
    print("=" * 108)
    print("CANDLE REVERSAL (HAMMER / SHOOTING STAR) — FUTURES WITH TRAILING STOP")
    print("=" * 108)
    print(f"Period      : {meta['start']:%d %b %Y} → {meta['end']:%d %b %Y}  "
          f"({meta['days']} trading days)")
    print(f"Universe    : {meta['symbols']} stocks with candles")
    print(f"Signals     : {meta['signals']} alerts "
          f"({meta['bullish']} hammer / {meta['bearish']} shooting star), "
          f"{meta['tradeable']} tradeable")
    print(f"Filters     : vol ≥ {config.CANDLE_CONFIRM_VOLUME_MULT}× avg, "
          f"confidence ≥ {config.CANDLE_MIN_CONFIDENCE}, "
          f"cooldown {config.CANDLE_COOLDOWN_MINUTES}m")
    print(f"Costs       : {cost_pct:.3f}% round trip charged on every trade "
          f"(brokerage + STT + slippage); returns below are NET")
    print(f"Price series: spot 5-min candles as futures proxy; square-off at 15:15 bar")

    print()
    print("─" * 108)
    print("OVERALL — one row per trailing-stop width")
    print("─" * 108)
    print(HEADER)
    for trail, trades in sorted(all_trades.items()):
        print_row(f"trail {trail}%", stats(trades, cost_pct))
    print_row("no stop (EOD only)", stats(hold_trades, cost_pct))

    for trail, trades in sorted(all_trades.items()):
        s = stats(trades, cost_pct)
        if not s['n']:
            continue
        print()
        print("─" * 108)
        print(f"TRAIL {trail}%  —  {s['trail_exits']:.0f}% of trades stopped out, "
              f"{100 - s['trail_exits']:.0f}% ran to square-off  |  "
              f"avg best-move-in-trade {s['avg_mfe']:+.2f}%")
        print("─" * 108)
        print(HEADER)

        for direction, label in (('BULLISH', 'Hammer (long)'), ('BEARISH', 'Star (short)')):
            print_row(label, stats([t for t in trades if t['direction'] == direction], cost_pct))

        print(f"  {'':-<22}")
        by_hour = defaultdict(list)
        for t in trades:
            by_hour[t['time'].hour].append(t)
        for hour in sorted(by_hour):
            print_row(f"entry {hour:02d}:00-{hour:02d}:59", stats(by_hour[hour], cost_pct))

        print(f"  {'':-<22}")
        by_month = defaultdict(list)
        for t in trades:
            by_month[t['time'].strftime('%Y-%m')].append(t)
        for month in sorted(by_month):
            print_row(month, stats(by_month[month], cost_pct))

        print(f"  {'':-<22}")
        for lo, hi in ((0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 99)):
            bucket = [t for t in trades if lo <= t['volume_ratio'] < hi]
            print_row(f"vol {lo}–{hi}× avg", stats(bucket, cost_pct))


def dump_trades(trades: List[Dict], path: str, cost_pct: float):
    rows = [{'symbol': t['symbol'], 'time': t['time'].isoformat(), 'direction': t['direction'],
             'pattern': t['pattern'], 'entry': round(t['entry'], 2),
             'exit': round(t['exit_price'], 2), 'reason': t['exit_reason'],
             'bars': t['bars_held'], 'gross_pct': round(t['gross_pct'], 3),
             'net_pct': round(t['gross_pct'] - cost_pct, 3), 'mfe_pct': round(t['mfe_pct'], 3),
             'volume_ratio': round(t['volume_ratio'], 2), 'confidence': t['confidence']}
            for t in sorted(trades, key=lambda x: x['time'])]
    with open(path, 'w') as f:
        json.dump(rows, f, indent=1)
    print(f"\nTrade log ({len(rows)} trades) → {path}")


# ---------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--months', type=int, default=6, help='months of history (default 6)')
    ap.add_argument('--stocks', type=int, help='limit universe size (faster runs)')
    ap.add_argument('--trail', type=float, nargs='+', default=[0.3, 0.5],
                    help='trailing stop widths in %% (default 0.3 0.5)')
    ap.add_argument('--cost-pct', type=float, default=0.05,
                    help='round-trip cost %% of notional (default 0.05)')
    ap.add_argument('--refresh', action='store_true', help='ignore the candle cache')
    ap.add_argument('--dump', help='write the trade log for the FIRST trail width to this file')
    args = ap.parse_args()

    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)
    with open(INSTRUMENT_TOKENS_FILE) as f:
        tokens = json.load(f)
    with open(config.STOCK_LIST_FILE) as f:
        symbols = [s for s in json.load(f)['stocks'] if s in tokens]
    if args.stocks:
        symbols = symbols[:args.stocks]

    end = datetime.now().replace(hour=23, minute=59, second=0, microsecond=0)
    start = end - timedelta(days=int(args.months * 30.5) + 10)   # padding for the warm-up window

    hammer = HammerDetector(config.CANDLE_MIN_CONFIDENCE, 14, 2.0, 1.0)
    star = ShootingStarDetector(config.CANDLE_MIN_CONFIDENCE, 14, 2.0, 1.0)

    print(f"Backtesting {len(symbols)} stocks, {start:%d %b %Y} → {end:%d %b %Y} "
          f"(5-min candles, cached in {CACHE_DIR}/)", flush=True)

    trades: Dict[float, List[Dict]] = {t: [] for t in args.trail}
    hold_trades: List[Dict] = []
    n_signals = n_bull = n_bear = n_tradeable = 0
    days = set()
    ok_symbols = 0

    for n, symbol in enumerate(symbols, 1):
        try:
            candles = fetch_symbol_candles(kite, tokens[symbol], symbol, start, end, args.refresh)
        except Exception as e:
            print(f"  {symbol}: fetch failed ({e})", flush=True)
            continue
        if len(candles) < WINDOW + 2:
            continue
        ok_symbols += 1
        days.update(c['date'].date() for c in candles)

        for sig in find_signals(symbol, candles, hammer, star):
            if sig['entry'] < config.PRICE_ACTION_MIN_PRICE:
                continue                               # same penny-stock filter as the monitor
            n_signals += 1
            n_bull += sig['direction'] == 'BULLISH'
            n_bear += sig['direction'] == 'BEARISH'
            sims = {t: simulate(sig, candles, t) for t in args.trail}
            hold = simulate_hold(sig, candles)
            if not all(sims.values()) or not hold:
                continue                               # alert on the day's last bar
            n_tradeable += 1
            for t, trade in sims.items():
                trades[t].append(trade)
            hold_trades.append(hold)

        if n % 25 == 0:
            print(f"  ...{n}/{len(symbols)} symbols, {n_signals} signals so far", flush=True)

    if not n_tradeable:
        print("No tradeable signals found.")
        return

    report(trades, hold_trades, args.cost_pct,
           {'start': min(days), 'end': max(days), 'days': len(days), 'symbols': ok_symbols,
            'signals': n_signals, 'bullish': n_bull, 'bearish': n_bear, 'tradeable': n_tradeable})

    if args.dump:
        dump_trades(trades[args.trail[0]], args.dump, args.cost_pct)


if __name__ == '__main__':
    main()
