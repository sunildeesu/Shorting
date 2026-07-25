#!/usr/bin/env python3
"""
Stage 2 of candle-reversal tuning: find whatever edge exists, then prove it out of sample.

Reads the superset dataset from research_candle_reversal.py and runs, in order:

  1. EXIT SWEEP    — every exit rule applied to the current live signal set (TRAIN only),
                     so we can see whether exit management alone can turn the signal positive
  2. FEATURE SCAN  — each context feature split into quintiles (TRAIN only); a feature that
                     matters shows a monotone gradient in net return across its buckets
  3. CANDIDATE     — a tuned variant assembled from what stages 1-2 showed
  4. VALIDATION    — the tuned variant re-run untouched on the held-out TEST period

Only step 4 is evidence. Steps 1-3 look at the training data as many times as they like, and
anything found there is a hypothesis, not a result. A t-stat is printed beside every mean so
that "edge" and "noise that happened to sort well" stay distinguishable.

Usage:
    venv/bin/python3 analyze_candle_reversal.py
    venv/bin/python3 analyze_candle_reversal.py --split 2026-05-11 --cost-pct 0.05

Author: Claude Code
Date: 2026-07-23
"""

import argparse
import math
import pickle
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

import config
from research_candle_reversal import (
    TRAIL_PCTS, ATR_TRAILS, R_TARGETS, TIME_EXITS, HORIZONS, MULTIDAY_TRAILS,
)

DATA_FILE = 'data/candle_reversal_research.pkl'
COOLDOWN_MIN = config.CANDLE_COOLDOWN_MINUTES

EXIT_COLS = ([f'trail_{t}' for t in TRAIL_PCTS]
             + [f'atrtrail_{k}' for k in ATR_TRAILS]
             + [f'fixed_{r}R' for r in R_TARGETS]
             + [f'time_{n}' for n in TIME_EXITS]
             + [f'multiday_{m}' for m in MULTIDAY_TRAILS]
             + ['r_eod'])

SCAN_FEATURES = [
    'confidence', 'volume_ratio', 'tod_min', 'atr_pct', 'chase_atr', 'risk_pct',
    'confirm_range_pct', 'confirm_body_pct', 'slip_pct', 'day_pos_signed', 'day_range_pct',
    'vwap_dist_signed', 'prior_swing_signed', 'gap_signed', 'trend_signed', 'ret5d_signed',
]


# ------------------------------------------------------------------------- statistics

def summarise(rows: List[Dict], col: str, cost: float) -> Dict:
    if not rows:
        return {'n': 0}
    r = [x[col] - cost for x in rows]
    wins = [v for v in r if v > 0]
    losses = [v for v in r if v <= 0]
    sd = statistics.pstdev(r) if len(r) > 1 else 0.0
    mean = statistics.mean(r)
    return {
        'n': len(r), 'mean': mean, 'median': statistics.median(r), 'total': sum(r),
        'win_rate': len(wins) / len(r) * 100,
        'avg_win': statistics.mean(wins) if wins else 0.0,
        'avg_loss': statistics.mean(losses) if losses else 0.0,
        'pf': (sum(wins) / abs(sum(losses))) if losses and sum(losses) else float('inf'),
        't': (mean / (sd / math.sqrt(len(r)))) if sd > 0 else 0.0,
    }


HDR = (f"  {'':<26} {'N':>5} {'Win%':>6} {'Mean':>8} {'Median':>8} {'Total':>9} "
       f"{'AvgWin':>7} {'AvgLoss':>7} {'PF':>5} {'t':>6}")


def row_line(label: str, s: Dict, mark: str = ''):
    if not s['n']:
        print(f"  {label:<26}     —")
        return
    print(f"  {label:<26} {s['n']:>5} {s['win_rate']:>5.1f}% {s['mean']:>+7.3f}% "
          f"{s['median']:>+7.3f}% {s['total']:>+8.1f}% {s['avg_win']:>+6.2f}% "
          f"{s['avg_loss']:>+6.2f}% {s['pf']:>5.2f} {s['t']:>+6.2f}{mark}")


# ------------------------------------------------------------------- signal selection

def apply_cooldown(rows: List[Dict]) -> List[Dict]:
    """Live behaviour: at most one alert per (symbol, direction) per cooldown window."""
    kept, last = [], {}
    for r in sorted(rows, key=lambda x: x['time']):
        key = (r['symbol'], r['direction'])
        prev = last.get(key)
        if prev and (r['time'] - prev).total_seconds() / 60 < COOLDOWN_MIN:
            continue
        last[key] = r['time']
        kept.append(r)
    return kept


def select(rows: List[Dict], **gates) -> List[Dict]:
    """
    Filter by feature gates, then apply the cooldown.

    Gate forms: `feature_min=x`, `feature_max=x`, `direction='BULLISH'`.
    """
    out = []
    for r in rows:
        ok = True
        for gate, val in gates.items():
            if gate == 'direction':
                ok = r['direction'] == val
            elif gate.endswith('_min'):
                v = r.get(gate[:-4])
                ok = v is not None and v >= val
            elif gate.endswith('_max'):
                v = r.get(gate[:-4])
                ok = v is not None and v <= val
            else:
                raise ValueError(f'bad gate {gate}')
            if not ok:
                break
        if ok:
            out.append(r)
    return apply_cooldown(out)


LIVE_GATES = {'confidence_min': 6.0, 'volume_ratio_min': 1.2}


# ------------------------------------------------------------------------- the stages

def stage_exit_sweep(train: List[Dict], cost: float):
    print()
    print("=" * 112)
    print("1. EXIT SWEEP — current live signal set (conf≥6, vol≥1.2×), TRAIN period")
    print("=" * 112)
    live = select(train, **LIVE_GATES)
    print(f"  {len(live)} trades after cooldown\n")
    print(HDR)
    ranked = sorted(EXIT_COLS, key=lambda c: -summarise(live, c, cost)['mean'])
    for col in ranked:
        row_line(col, summarise(live, col, cost))
    print()
    print("  Reference (no cost charged, no stop) — is there ANY directional edge?")
    print(HDR)
    for h in HORIZONS:
        row_line(f'raw r{h} (gross)', summarise(live, f'r{h}', 0.0))
    row_line('raw r_eod (gross)', summarise(live, 'r_eod', 0.0))
    mfe = statistics.mean(r['mfe24'] for r in live)
    mae = statistics.mean(r['mae24'] for r in live)
    print(f"\n  Average path over 24 bars: best +{mfe:.2f}% / worst {mae:.2f}% "
          f"→ payoff is symmetric, which is why no exit rule fixes it.")
    return ranked[0]


def stage_feature_scan(train: List[Dict], col: str, cost: float):
    print()
    print("=" * 112)
    print(f"2. FEATURE SCAN — quintiles on TRAIN, outcome = {col}")
    print("=" * 112)
    print("  A feature worth gating on shows a gradient across its buckets, not one odd cell.\n")
    live = select(train, **LIVE_GATES)
    for feat in SCAN_FEATURES:
        vals = sorted(r[feat] for r in live if r.get(feat) is not None)
        if len(vals) < 500:
            continue
        cuts = [vals[int(len(vals) * q / 5)] for q in range(1, 5)]
        buckets: List[List[Dict]] = [[] for _ in range(5)]
        for r in live:
            v = r.get(feat)
            if v is None:
                continue
            b = sum(1 for c in cuts if v >= c)
            buckets[b].append(r)
        means = [summarise(b, col, cost)['mean'] if b else 0.0 for b in buckets]
        spread = max(means) - min(means)
        print(f"  {feat:<20} cuts {'/'.join(f'{c:.2f}' for c in cuts):<28} "
              f"means {' '.join(f'{m:+.3f}' for m in means)}   spread {spread:.3f}%")
    print()


def describe(label: str, rows: List[Dict], col: str, cost: float, period: str):
    s = summarise(rows, col, cost)
    days = len({r['date'] for r in rows}) or 1
    print(f"\n  {label}  [{period}]")
    print(HDR)
    row_line(col, s)
    if s['n']:
        print(f"      {s['n'] / days:.1f} trades/day over {days} days")
    return s


def stage_candidate(train: List[Dict], test: List[Dict], cost: float,
                    candidates: List[Dict]):
    print()
    print("=" * 112)
    print("3/4. CANDIDATES — built on TRAIN, then re-run untouched on TEST")
    print("=" * 112)
    for cand in candidates:
        name, gates, col = cand['name'], cand['gates'], cand['exit']
        print(f"\n{'─' * 112}")
        print(f"{name}")
        print(f"  gates: {gates or '(none)'}   exit: {col}")
        tr = describe('TRAIN', select(train, **gates), col, cost, 'in-sample')
        te = describe('TEST ', select(test, **gates), col, cost, 'HELD OUT')
        if tr['n'] and te['n']:
            verdict = ('holds up' if te['mean'] > 0 and te['t'] > 1.5
                       else 'does NOT survive out of sample')
            print(f"\n  → {verdict}: train {tr['mean']:+.3f}%/trade (t={tr['t']:+.2f}), "
                  f"test {te['mean']:+.3f}%/trade (t={te['t']:+.2f})")


def stage_decomposition(rows: List[Dict], cost: float):
    """
    Split each outcome into the part caused by the PATTERN and the part caused by market drift.

        long return  = signal effect + drift
        short return = signal effect − drift
      → signal = (long + short) / 2,  drift = (long − short) / 2

    This matters because a bullish backtest period flatters every long-heavy strategy. Only the
    signal term is edge; the drift term is beta you could have had by buying anything.
    """
    print()
    print("=" * 112)
    print("1b. SIGNAL vs DRIFT — is the pattern predictive, or is it just the market?")
    print("=" * 112)
    live = select(rows, **LIVE_GATES)
    longs = [r for r in live if r['long']]
    shorts = [r for r in live if not r['long']]
    print(f"  {len(longs)} hammer longs / {len(shorts)} shooting-star shorts, "
          f"gross (no cost), full period\n")
    print(f"  {'horizon':<12} {'long':>9} {'short':>9} {'SIGNAL':>9} {'drift':>9}   interpretation")
    for col in [f'r{h}' for h in HORIZONS] + ['r_eod']:
        lm = statistics.mean(r[col] for r in longs)
        sm = statistics.mean(r[col] for r in shorts)
        sig, drift = (lm + sm) / 2, (lm - sm) / 2
        tag = ('pattern works' if sig > 0.02 else
               'pattern is ANTI-predictive' if sig < -0.02 else 'pattern is neutral')
        print(f"  {col:<12} {lm:>+8.3f}% {sm:>+8.3f}% {sig:>+8.3f}% {drift:>+8.3f}%   {tag}")
    print(f"\n  Costs are {cost}% round trip — an edge has to clear that before it is a strategy.")


def stage_fade(rows: List[Dict], cost: float):
    """If the pattern is anti-predictive, does trading AGAINST it pay? (path-independent exits)"""
    print()
    print("=" * 112)
    print("1c. FADE TEST — take the OPPOSITE side of every alert")
    print("=" * 112)
    live = select(rows, **LIVE_GATES)
    print("  Only exits whose result can be mirrored without re-simulating a stop path.\n")
    print(HDR)
    for col in [f'time_{n}' for n in TIME_EXITS] + ['r_eod']:
        faded = [{**r, col: -r[col]} for r in live]
        row_line(f'fade {col}', summarise(faded, col, cost))


# ------------------------------------------------------------------------ grid search

def gate_grid() -> List[Dict]:
    """Gate combinations to search: up to three active families at once, plus the empty set."""
    families = {
        'conf':    [{'confidence_min': 7.0}, {'confidence_min': 8.0}],
        'vol':     [{'volume_ratio_min': 1.5}, {'volume_ratio_min': 2.0},
                    {'volume_ratio_min': 3.0}],
        'tod':     [{'tod_min_max': 60}, {'tod_min_min': 60}, {'tod_min_min': 300},
                    {'tod_min_min': 60, 'tod_min_max': 300}],
        'atr':     [{'atr_pct_min': 0.25}, {'atr_pct_min': 0.35}],
        'chase':   [{'chase_atr_max': 1.5}, {'chase_atr_max': 2.0}],
        'vwap':    [{'vwap_dist_signed_min': 0.0}],
        'trend':   [{'trend_signed_min': 0.0}],
        'daypos':  [{'day_pos_signed_min': 0.5}, {'day_pos_signed_min': 0.8}],
        'dir':     [{'direction': 'BULLISH'}, {'direction': 'BEARISH'}],
    }
    from itertools import combinations, product
    names = list(families)
    grid: List[Dict] = [{}]
    for k in (1, 2, 3):
        for combo in combinations(names, k):
            for picks in product(*(families[c] for c in combo)):
                g = {}
                for p in picks:
                    g.update(p)
                grid.append(g)
    return grid


def stage_search(train: List[Dict], test: List[Dict], cost: float, min_trades: int, top: int):
    print()
    print("=" * 112)
    print("3. GRID SEARCH — best (filter × exit) on TRAIN, then the SAME config on TEST")
    print("=" * 112)
    grid = gate_grid()
    print(f"  {len(grid)} filter combinations × {len(EXIT_COLS)} exit rules "
          f"= {len(grid) * len(EXIT_COLS)} configurations tested on TRAIN")
    print(f"  Keeping only configs with ≥{min_trades} train trades.\n")

    results = []
    for gates in grid:
        sel = select(train, **{**LIVE_GATES, **gates})
        if len(sel) < min_trades:
            continue
        for col in EXIT_COLS:
            s = summarise(sel, col, cost)
            results.append({'gates': gates, 'exit': col, 'train': s})
    results.sort(key=lambda x: -x['train']['mean'])
    print(f"  {len(results)} configurations qualified. Top {top} by TRAIN mean:\n")

    print(f"  {'#':>2} {'exit':<14} {'filter':<46} "
          f"{'TRAIN n':>7} {'mean':>8} {'t':>6} | {'TEST n':>6} {'mean':>8} {'t':>6}")
    survivors = []
    for i, res in enumerate(results[:top], 1):
        te = summarise(select(test, **{**LIVE_GATES, **res['gates']}), res['exit'], cost)
        res['test'] = te
        g = ', '.join(f'{k}={v}' for k, v in res['gates'].items()) or '(live gates only)'
        print(f"  {i:>2} {res['exit']:<14} {g[:46]:<46} "
              f"{res['train']['n']:>7} {res['train']['mean']:>+7.3f}% {res['train']['t']:>+6.2f} | "
              f"{te['n']:>6} {te['mean']:>+7.3f}% {te['t']:>+6.2f}")
        if te['n'] >= 100 and te['mean'] > 0 and te['t'] > 2.0:
            survivors.append(res)

    tested = [r for r in results[:top] if r['test']['n'] >= 50]
    if tested:
        med = statistics.median(r['test']['mean'] for r in tested)
        pos = sum(1 for r in tested if r['test']['mean'] > 0)
        print(f"\n  Out-of-sample reality check on those {len(tested)} 'best' configs:")
        print(f"    median TEST mean {med:+.3f}%/trade | {pos}/{len(tested)} still positive")
        print(f"    (if the search were finding real edge, nearly all would stay positive)")
    print(f"\n  Configurations clearing TEST mean>0 AND t>2.0: {len(survivors)}")
    for res in survivors:
        g = ', '.join(f'{k}={v}' for k, v in res['gates'].items()) or '(live gates only)'
        print(f"    ✓ {res['exit']} | {g} | test {res['test']['mean']:+.3f}%/trade "
              f"(n={res['test']['n']}, t={res['test']['t']:+.2f})")
    return survivors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DATA_FILE)
    ap.add_argument('--split', default='2026-05-11', help='first date of the TEST period')
    ap.add_argument('--cost-pct', type=float, default=0.05)
    ap.add_argument('--min-trades', type=int, default=250,
                    help='minimum TRAIN trades for a grid config to qualify')
    ap.add_argument('--top', type=int, default=20, help='grid configs carried to TEST')
    args = ap.parse_args()

    with open(args.data, 'rb') as f:
        rows: List[Dict] = pickle.load(f)
    split = datetime.strptime(args.split, '%Y-%m-%d').date()
    train = [r for r in rows if r['date'] < split]
    test = [r for r in rows if r['date'] >= split]
    cost = args.cost_pct

    print("=" * 112)
    print("CANDLE REVERSAL — TUNING STUDY")
    print("=" * 112)
    print(f"Superset : {len(rows)} signals (conf≥3.0, no volume floor) "
          f"from {min(r['date'] for r in rows)} to {max(r['date'] for r in rows)}")
    print(f"Split    : TRAIN {len(train)} signals (< {split}) | "
          f"TEST {len(test)} signals (≥ {split})")
    print(f"Costs    : {cost}% round trip charged per trade; entry at the OPEN of the bar "
          f"AFTER the alert")
    slip = statistics.mean(r['slip_pct'] for r in rows)
    print(f"Entry slip: {slip:+.3f}%/trade average versus the confirmation close "
          f"(the price of a realistic fill)")

    best_exit = stage_exit_sweep(train, cost)
    stage_decomposition(rows, cost)
    stage_fade(rows, cost)
    stage_feature_scan(train, 'trail_0.5', cost)

    survivors = stage_search(train, test, cost, args.min_trades, args.top)

    candidates = [
        {'name': 'A. LIVE BASELINE (what runs today)',
         'gates': dict(LIVE_GATES), 'exit': 'trail_0.5'},
        {'name': 'B. LIVE SIGNAL + best exit from the TRAIN sweep',
         'gates': dict(LIVE_GATES), 'exit': best_exit},
    ]
    for res in survivors[:2]:
        candidates.append({'name': f"C. GRID SURVIVOR — {res['exit']}",
                           'gates': {**LIVE_GATES, **res['gates']}, 'exit': res['exit']})
    stage_candidate(train, test, cost, candidates)


if __name__ == '__main__':
    main()
