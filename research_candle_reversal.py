#!/usr/bin/env python3
"""
Research dataset builder for the candle-reversal (hammer / shooting star) signal.

Stage 1 of tuning. It walks the cached 5-min candles, detects a deliberately WIDENED superset
of the live signal (min confidence 3.0 instead of 6.0, no confirmation-volume floor), and for
every hit records:

  • context features  — confidence, volume ratio, time of day, ATR, how extended the entry is,
    where price sits in the day's range and versus VWAP, the preceding swing, the daily trend
  • outcome columns   — the result of ~25 different exit rules, plus raw forward returns and
    MFE/MAE at several horizons

Because the superset is stored with its features intact, stage 2 (analyze_candle_reversal.py)
can re-impose the live thresholds, tighten them, or replace them entirely — without re-running
detection or touching the Kite API.

Entry is modelled at the OPEN OF THE BAR AFTER the confirmation bar, not the confirmation
close: the live alert can only reach you once that bar has closed. The gap between the two is
recorded as `slip_pct` so the cost of that realism is measurable.

Usage:
    venv/bin/python3 research_candle_reversal.py                 # build data/candle_reversal_research.pkl
    venv/bin/python3 research_candle_reversal.py --stocks 20     # quick smoke run

Reads only the local candle cache written by backtest_candle_reversal_trail.py. No API calls,
no alerts, no live state.

Author: Claude Code
Date: 2026-07-23
"""

import argparse
import gzip
import json
import os
import pickle
import statistics
from collections import defaultdict
from datetime import time as dtime
from typing import Dict, List, Optional

import config

# Widen the live gates BEFORE importing the detector module so the superset is genuinely wider.
# detect_reversal_confirmation reads these at call time; stage 2 re-imposes real thresholds.
config.CANDLE_CONFIRM_VOLUME_MULT = 0.0        # record volume ratio, filter on it later
RESEARCH_MIN_CONFIDENCE = 3.0                  # live is 6.0

from candle_confirmation_monitor import detect_reversal_confirmation      # noqa: E402
from pattern_detectors.reversal_patterns import (                         # noqa: E402
    HammerDetector, ShootingStarDetector,
)

CACHE_DIR = 'data/candle_reversal_5min'
OUT_FILE = 'data/candle_reversal_research.pkl'
WINDOW = 40
SQUARE_OFF = dtime(15, 15)
ATR_PERIOD = 14

# Exit rules evaluated for every signal. Each becomes a column in the dataset.
TRAIL_PCTS = [0.2, 0.3, 0.5, 0.75, 1.0, 1.5]
ATR_TRAILS = [1.0, 1.5, 2.0, 3.0]              # trail = k × ATR(14) of 5-min bars
R_TARGETS = [1.0, 1.5, 2.0, 3.0]               # fixed stop at the signal-candle extreme
TIME_EXITS = [3, 6, 12, 24]                    # bars, then exit at that bar's close
HORIZONS = [6, 12, 24, 75]                     # bars, for raw forward return / MFE / MAE
MULTIDAY_TRAILS = [1.0, 2.0]                   # % trail, allowed to run up to MULTIDAY_DAYS
MULTIDAY_DAYS = 3


# --------------------------------------------------------------------------- helpers

def atr_series(candles: List[Dict], period: int = ATR_PERIOD) -> List[float]:
    """Wilder ATR per bar (index-aligned with candles); 0.0 until enough history."""
    trs, out, prev_close, atr = [], [], None, None
    for c in candles:
        tr = c['high'] - c['low'] if prev_close is None else max(
            c['high'] - c['low'], abs(c['high'] - prev_close), abs(c['low'] - prev_close))
        trs.append(tr)
        if len(trs) < period:
            out.append(0.0)
        elif atr is None:
            atr = sum(trs[-period:]) / period
            out.append(atr)
        else:
            atr = (atr * (period - 1) + tr) / period
            out.append(atr)
        prev_close = c['close']
    return out


def day_context(candles: List[Dict]) -> Dict[str, List[float]]:
    """Per-bar intraday context: VWAP so far, day high/low so far, bars elapsed, day open."""
    vwap, day_hi, day_lo, bars_in, day_open = [], [], [], [], []
    cum_pv = cum_v = 0.0
    hi = lo = None
    n = 0
    cur_day = None
    d_open = 0.0
    for c in candles:
        d = c['date'].date()
        if d != cur_day:
            cur_day, cum_pv, cum_v, hi, lo, n = d, 0.0, 0.0, c['high'], c['low'], 0
            d_open = c['open']
        tp = (c['high'] + c['low'] + c['close']) / 3
        cum_pv += tp * c['volume']
        cum_v += c['volume']
        hi, lo, n = max(hi, c['high']), min(lo, c['low']), n + 1
        vwap.append(cum_pv / cum_v if cum_v else c['close'])
        day_hi.append(hi)
        day_lo.append(lo)
        bars_in.append(n)
        day_open.append(d_open)
    return {'vwap': vwap, 'day_hi': day_hi, 'day_lo': day_lo, 'bars_in': bars_in,
            'day_open': day_open}


def daily_frame(candles: List[Dict]) -> Dict:
    """Daily OHLC aggregated from the 5-min bars, plus a date → day-index map."""
    days: Dict = {}
    order: List = []
    for c in candles:
        d = c['date'].date()
        if d not in days:
            days[d] = {'open': c['open'], 'high': c['high'], 'low': c['low'],
                       'close': c['close'], 'volume': 0.0}
            order.append(d)
        day = days[d]
        day['high'] = max(day['high'], c['high'])
        day['low'] = min(day['low'], c['low'])
        day['close'] = c['close']
        day['volume'] += c['volume']
    return {'days': days, 'order': order, 'index': {d: i for i, d in enumerate(order)}}


# ------------------------------------------------------------------------ exit models

def _walk(candles: List[Dict], start: int, long: bool, entry: float,
          stop_fn, target: Optional[float], max_days: int) -> Dict:
    """
    Shared bar walker. `stop_fn(best)` returns the current stop given the best price so far.

    Pessimistic within a bar: the stop is tested against the adverse extreme before the bar's
    favourable extreme can move the trail. A gap through the stop fills at the bar's open.
    """
    day0 = candles[start - 1]['date'].date()
    days_seen = 0
    prev_day = day0
    best = entry
    stop = stop_fn(best)
    for j in range(start, len(candles)):
        c = candles[j]
        d = c['date'].date()
        if d != prev_day:
            days_seen += 1
            prev_day = d
            if days_seen > max_days:
                px = candles[j - 1]['close']
                return {'exit': px, 'reason': 'EOD', 'bars': j - start}
        if long and c['low'] <= stop:
            return {'exit': min(stop, c['open']), 'reason': 'STOP', 'bars': j - start + 1}
        if not long and c['high'] >= stop:
            return {'exit': max(stop, c['open']), 'reason': 'STOP', 'bars': j - start + 1}
        if target is not None:
            if long and c['high'] >= target:
                return {'exit': max(target, c['open']), 'reason': 'TARGET', 'bars': j - start + 1}
            if not long and c['low'] <= target:
                return {'exit': min(target, c['open']), 'reason': 'TARGET', 'bars': j - start + 1}
        best = max(best, c['high']) if long else min(best, c['low'])
        stop = max(stop, stop_fn(best)) if long else min(stop, stop_fn(best))
        if max_days == 0 and c['date'].time() >= SQUARE_OFF:
            return {'exit': c['close'], 'reason': 'EOD', 'bars': j - start + 1}
    return {'exit': candles[-1]['close'], 'reason': 'EOD', 'bars': len(candles) - start}


def pct(entry: float, exit_px: float, long: bool) -> float:
    return ((exit_px - entry) if long else (entry - exit_px)) / entry * 100


def build_outcomes(candles: List[Dict], i: int, long: bool, entry: float,
                   fixed_stop: float, atr: float) -> Dict[str, float]:
    """Every exit rule's return (%, gross) for one signal. Entry is at bar i+1's open."""
    out: Dict[str, float] = {}
    start = i + 2                       # first bar that can act on the position

    for t in TRAIL_PCTS:
        f = (lambda b, t=t: b * (1 - t / 100)) if long else (lambda b, t=t: b * (1 + t / 100))
        r = _walk(candles, start, long, entry, f, None, 0)
        out[f'trail_{t}'] = pct(entry, r['exit'], long)
        out[f'trail_{t}_bars'] = r['bars']
        out[f'trail_{t}_stopped'] = 1.0 if r['reason'] == 'STOP' else 0.0

    for k in ATR_TRAILS:
        d = k * atr
        f = (lambda b, d=d: b - d) if long else (lambda b, d=d: b + d)
        out[f'atrtrail_{k}'] = pct(entry, _walk(candles, start, long, entry, f, None, 0)['exit'], long)

    risk = abs(entry - fixed_stop)
    for rr in R_TARGETS:
        tgt = entry + rr * risk if long else entry - rr * risk
        f = (lambda b, s=fixed_stop: s)          # static stop at the signal-candle extreme
        out[f'fixed_{rr}R'] = pct(entry, _walk(candles, start, long, entry, f, tgt, 0)['exit'], long)

    for md in MULTIDAY_TRAILS:
        f = (lambda b, t=md: b * (1 - t / 100)) if long else (lambda b, t=md: b * (1 + t / 100))
        r = _walk(candles, start, long, entry, f, None, MULTIDAY_DAYS)
        out[f'multiday_{md}'] = pct(entry, r['exit'], long)

    # Raw forward path: no stop at all. Tells us whether the signal has any directional edge.
    day0 = candles[i + 1]['date'].date()
    same_day = [c for c in candles[start:] if c['date'].date() == day0]
    for h in HORIZONS:
        seg = same_day[:h]
        if not seg:
            out[f'r{h}'] = out[f'mfe{h}'] = out[f'mae{h}'] = 0.0
            continue
        out[f'r{h}'] = pct(entry, seg[-1]['close'], long)
        out[f'mfe{h}'] = max(pct(entry, c['high'] if long else c['low'], long) for c in seg)
        out[f'mae{h}'] = min(pct(entry, c['low'] if long else c['high'], long) for c in seg)
    usable = [c for c in same_day if c['date'].time() <= SQUARE_OFF] or same_day[:1]
    out['r_eod'] = pct(entry, usable[-1]['close'], long)
    out['bars_left'] = len(usable)

    for n in TIME_EXITS:
        seg = same_day[:n]
        out[f'time_{n}'] = pct(entry, seg[-1]['close'], long) if seg else 0.0
    return out


# ------------------------------------------------------------------------ extraction

def extract_symbol(symbol: str, candles: List[Dict], hammer, star) -> List[Dict]:
    if len(candles) < WINDOW + 5:
        return []
    atrs = atr_series(candles)
    ctx = day_context(candles)
    daily = daily_frame(candles)
    closes_d = [daily['days'][d]['close'] for d in daily['order']]

    rows: List[Dict] = []
    for i in range(WINDOW, len(candles) - 3):
        sig = detect_reversal_confirmation(candles[i - WINDOW:i + 1], hammer, star)
        if not sig:
            continue
        confirm, signal_c = candles[i], candles[i - 1]
        nxt = candles[i + 1]
        # Need the entry bar AND at least one bar to manage the position in, both on the
        # signal's own day — otherwise the alert is unenterable (or instantly squared off).
        if nxt['date'].date() != confirm['date'].date() \
                or candles[i + 2]['date'].date() != confirm['date'].date():
            continue
        long = sig['direction'] == 'BULLISH'
        entry = nxt['open']                      # realistic fill: the bar after the alert
        atr = atrs[i]
        if entry < config.PRICE_ACTION_MIN_PRICE or atr <= 0:
            continue

        di = daily['index'][confirm['date'].date()]
        prior_d = closes_d[max(0, di - 20):di]
        sma20 = statistics.mean(prior_d) if len(prior_d) >= 10 else None
        ret5d = ((closes_d[di - 1] / closes_d[di - 6] - 1) * 100
                 if di >= 6 else None)
        prev_close = closes_d[di - 1] if di >= 1 else None

        rng = ctx['day_hi'][i] - ctx['day_lo'][i]
        swing_from = candles[max(0, i - 13)]['close']

        row = {
            'symbol': symbol,
            'date': confirm['date'].date(),
            'time': confirm['date'],
            'direction': sig['direction'],
            'long': long,
            'entry': entry,
            'fixed_stop': sig['stop'],
            # --- context features ---
            'confidence': sig['confidence'],
            'volume_ratio': sig['volume_ratio'],
            'tod_min': (confirm['date'].hour - 9) * 60 + confirm['date'].minute - 15,
            'bars_in_day': ctx['bars_in'][i],
            'atr_pct': atr / entry * 100,
            # how far the entry already is from the wick extreme, in ATRs — the "chase" cost
            'chase_atr': abs(entry - sig['stop']) / atr,
            'risk_pct': abs(entry - sig['stop']) / entry * 100,
            'confirm_range_pct': (confirm['high'] - confirm['low']) / entry * 100,
            'confirm_body_pct': abs(confirm['close'] - confirm['open']) / entry * 100,
            'slip_pct': pct(sig['entry'], entry, long),      # alert close → next open, signed
            'day_pos': ((entry - ctx['day_lo'][i]) / rng) if rng > 0 else 0.5,
            'day_range_pct': rng / entry * 100,
            'vwap_dist_pct': (entry - ctx['vwap'][i]) / entry * 100,
            'prior_swing_pct': (signal_c['close'] - swing_from) / swing_from * 100,
            'gap_pct': ((ctx['day_open'][i] / prev_close - 1) * 100) if prev_close else 0.0,
            'trend_sma20_pct': ((entry / sma20 - 1) * 100) if sma20 else None,
            'ret5d_pct': ret5d,
        }
        # Direction-normalised versions: positive = "with the trade".
        row['vwap_dist_signed'] = row['vwap_dist_pct'] if long else -row['vwap_dist_pct']
        row['trend_signed'] = (row['trend_sma20_pct'] if long else -row['trend_sma20_pct']) \
            if row['trend_sma20_pct'] is not None else None
        row['ret5d_signed'] = (row['ret5d_pct'] if long else -row['ret5d_pct']) \
            if row['ret5d_pct'] is not None else None
        row['prior_swing_signed'] = row['prior_swing_pct'] if long else -row['prior_swing_pct']
        row['day_pos_signed'] = row['day_pos'] if long else 1 - row['day_pos']
        row['gap_signed'] = row['gap_pct'] if long else -row['gap_pct']

        row.update(build_outcomes(candles, i, long, entry, sig['stop'], atr))
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stocks', type=int, help='limit symbols (smoke test)')
    ap.add_argument('--out', default=OUT_FILE)
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(CACHE_DIR) if f.endswith('.pkl.gz'))
    if args.stocks:
        files = files[:args.stocks]

    hammer = HammerDetector(RESEARCH_MIN_CONFIDENCE, 14, 2.0, 1.0)
    star = ShootingStarDetector(RESEARCH_MIN_CONFIDENCE, 14, 2.0, 1.0)

    rows: List[Dict] = []
    for n, fn in enumerate(files, 1):
        symbol = fn[:-len('.pkl.gz')]
        with gzip.open(os.path.join(CACHE_DIR, fn), 'rb') as f:
            candles = pickle.load(f)['candles']
        rows.extend(extract_symbol(symbol, candles, hammer, star))
        if n % 25 == 0:
            print(f"  ...{n}/{len(files)} symbols, {len(rows)} signals", flush=True)

    with open(args.out, 'wb') as f:
        pickle.dump(rows, f)
    live = [r for r in rows
            if r['confidence'] >= 6.0 and r['volume_ratio'] >= 1.2]
    print(f"\n{len(rows)} superset signals from {len(files)} symbols → {args.out}")
    print(f"  of which {len(live)} pass the CURRENT live gates (conf≥6, vol≥1.2×)")
    print(f"  cooldown is NOT applied here; stage 2 applies it after filtering")


if __name__ == '__main__':
    main()
