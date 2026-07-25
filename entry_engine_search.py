#!/usr/bin/env python3
"""
Entry-engine search: hold the double-bottom EXIT engine fixed, swap the entry rule.

The audit (audit_double_bottom_backtest.py) showed the exit engine — arm at +6%, trail 1.5%
below the running high, 2xATR close stop, 30-day time stop — is doing most of the work, while
the double-bottom entry beat a random stock on the same day by only +0.34%/trade (t=0.90).
So the question worth asking is which ENTRY feeds that exit best.

Every rule here obeys the same contract, which makes the comparison fair and look-ahead free:

    signal is decided on day i's CLOSE  →  entry at day i+1's OPEN  →  exits from day i+2
    stop distance from ATR over days <= i, exits from the live find_exit()
    one new position per day (highest-ranked candidate), 4 slots, size = equity/4

Every rule is scored against the SAME benchmark the audit used: random stocks entered on the
same dates with the same exit engine. A rule only has an edge if it beats that control, not
if it merely makes money in a bull market.

Rules are fitted on TRAIN (first 2 years) and reported on TEST (final year) untouched.

    venv/bin/python3 entry_engine_search.py
    venv/bin/python3 entry_engine_search.py --with-5min   # also test the 5-min hammer alerts

Read-only. Uses the cached daily candles; no API calls, no live state, no alerts.

Author: Claude Code
Date: 2026-07-23
"""

import argparse
import math
import pickle
import random
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import config
from double_bottom_support_monitor import atr_percent, sma, stop_distance_pct
from double_bottom_position_tracker import find_exit
from backtest_double_bottom_portfolio import (
    fetch_candles, market_condition, performance, START_CAPITAL, COST_PCT, INDICATOR_BARS,
)
from audit_double_bottom_backtest import build_table as db_build_table, run as portfolio_run

RESEARCH_PICKLE = 'data/candle_reversal_research.pkl'
CONTROLS_PER_DAY = 25


# ------------------------------------------------------------------------ indicators

def indicators(cd: List[Dict]) -> Dict[str, List[Optional[float]]]:
    """Per-bar indicator arrays, each using ONLY bars up to and including that bar."""
    n = len(cd)
    close = [c['close'] for c in cd]
    out: Dict[str, List[Optional[float]]] = {}

    for p in (20, 50, 200):
        acc, arr = 0.0, []
        for i, v in enumerate(close):
            acc += v
            if i >= p:
                acc -= close[i - p]
            arr.append(acc / p if i >= p - 1 else None)
        out[f'sma{p}'] = arr

    # Wilder RSI(2) and RSI(14)
    for p in (2, 14):
        gains = losses = 0.0
        arr: List[Optional[float]] = [None]
        ag = al = None
        for i in range(1, n):
            ch = close[i] - close[i - 1]
            g, l = max(ch, 0.0), max(-ch, 0.0)
            if i <= p:
                gains += g
                losses += l
                if i == p:
                    ag, al = gains / p, losses / p
                    arr.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
                else:
                    arr.append(None)
            else:
                ag = (ag * (p - 1) + g) / p
                al = (al * (p - 1) + l) / p
                arr.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
        out[f'rsi{p}'] = arr

    out['hi20'] = [max(c['high'] for c in cd[max(0, i - 19):i + 1]) for i in range(n)]
    out['hi120'] = [max(c['high'] for c in cd[max(0, i - 119):i + 1]) for i in range(n)]
    out['lo20'] = [min(c['low'] for c in cd[max(0, i - 19):i + 1]) for i in range(n)]
    out['hiclose20'] = [max(close[max(0, i - 19):i + 1]) for i in range(n)]
    out['ret63'] = [(close[i] / close[i - 63] - 1) * 100 if i >= 63 else None for i in range(n)]
    out['ret21'] = [(close[i] / close[i - 21] - 1) * 100 if i >= 21 else None for i in range(n)]
    out['rng7'] = [min((cd[j]['high'] - cd[j]['low']) / cd[j]['close'] * 100
                       for j in range(max(0, i - 6), i + 1)) for i in range(n)]
    out['atrp'] = [atr_percent(cd[max(0, i - INDICATOR_BARS + 1):i + 1],
                               config.DOUBLE_BOTTOM_ATR_PERIOD) for i in range(n)]
    return out


def is_hammer(c: Dict) -> bool:
    """Daily hammer: small body in the top third, lower wick >= 2x body, tiny upper wick."""
    rng = c['high'] - c['low']
    if rng <= 0:
        return False
    body = abs(c['close'] - c['open'])
    lower = min(c['open'], c['close']) - c['low']
    upper = c['high'] - max(c['open'], c['close'])
    return body <= rng / 3 and lower >= 2 * body and upper <= body and body > 0


# ----------------------------------------------------------------------------- rules
# Each rule: (name, fn(cd, ind, i) -> rank score or None). Signal on day i's close.

def rule_hammer_d(cd, ind, i):
    if not is_hammer(cd[i]) or ind['sma50'][i] is None or ind['ret21'][i] is None:
        return None
    if cd[i]['close'] <= ind['sma50'][i] or ind['ret21'][i] > -2:
        return None                       # hammer after a pullback, inside an uptrend
    return ind['ret63'][i] if ind['ret63'][i] is not None else 0.0


def rule_breakout20(cd, ind, i):
    if ind['sma50'][i] is None or i < 21:
        return None
    if cd[i]['close'] < ind['hiclose20'][i] or cd[i]['close'] <= ind['sma50'][i]:
        return None
    return ind['ret63'][i] if ind['ret63'][i] is not None else 0.0


def rule_breakout120(cd, ind, i):
    if ind['sma50'][i] is None or i < 121:
        return None
    if cd[i]['high'] < ind['hi120'][i] or cd[i]['close'] <= ind['sma50'][i]:
        return None
    return ind['ret63'][i] if ind['ret63'][i] is not None else 0.0


def rule_sma20_touch(cd, ind, i):
    s20, s50 = ind['sma20'][i], ind['sma50'][i]
    if s20 is None or s50 is None or s20 <= s50:
        return None
    if cd[i]['low'] > s20 * 1.01 or cd[i]['close'] < s20:
        return None                       # dipped to the 20-SMA and closed back above it
    return ind['ret63'][i] if ind['ret63'][i] is not None else 0.0


def rule_rsi2(cd, ind, i):
    s50, r2 = ind['sma50'][i], ind['rsi2'][i]
    if s50 is None or r2 is None or cd[i]['close'] <= s50 or r2 >= 10:
        return None
    return ind['ret63'][i] if ind['ret63'][i] is not None else 0.0


def rule_nr7(cd, ind, i):
    if i < 8 or ind['sma50'][i] is None:
        return None
    today = (cd[i]['high'] - cd[i]['low']) / cd[i]['close'] * 100
    if today > ind['rng7'][i] or cd[i]['close'] <= cd[i - 1]['high'] \
            or cd[i]['close'] <= ind['sma50'][i]:
        return None
    return ind['ret63'][i] if ind['ret63'][i] is not None else 0.0


def rule_pullback_strong(cd, ind, i):
    """In a strong uptrend, buy a shallow pullback rather than a breakout."""
    s50, r63, hi20 = ind['sma50'][i], ind['ret63'][i], ind['hi20'][i]
    if s50 is None or r63 is None or cd[i]['close'] <= s50 or r63 < 10:
        return None
    depth = (hi20 - cd[i]['close']) / hi20 * 100
    if depth < 3 or depth > 12:
        return None
    return r63


DAILY_RULES: List[Tuple[str, Callable]] = [
    ('HAMMER_D  daily hammer in uptrend', rule_hammer_d),
    ('BREAKOUT20  20d closing high', rule_breakout20),
    ('BREAKOUT120  120d high', rule_breakout120),
    ('SMA20_TOUCH  dip to 20-SMA', rule_sma20_touch),
    ('RSI2  oversold above 50-SMA', rule_rsi2),
    ('NR7  squeeze breakout', rule_nr7),
    ('PULLBACK_STRONG  3-12% dip in leaders', rule_pullback_strong),
]


# ------------------------------------------------------------------------ evaluation

def signals_for(rule: Callable, data: Dict, inds: Dict) -> List[Dict]:
    """Rows in the shape the portfolio simulator expects. Entry = next day's open."""
    rows = []
    for symbol, cd in data.items():
        ind = inds[symbol]
        for i in range(INDICATOR_BARS, len(cd) - 2):
            score = rule(cd, ind, i)
            if score is None:
                continue
            nxt = i + 1
            rows.append({'symbol': symbol, 'i': nxt, 'date': cd[nxt]['date'],
                         'entry_price': cd[nxt]['open'], 'strength': score, 'rally': 0.0,
                         'atr_pct': ind['atrp'][i], 'level': cd[i]['low'], 'touches': 0})
    rows.sort(key=lambda r: (r['date'], r['symbol']))
    return rows


def trade_pnl(row: Dict, data: Dict, target: float) -> Optional[float]:
    entry = row['entry_price']
    stop_pct = stop_distance_pct(row['atr_pct'])
    pos = {'symbol': row['symbol'], 'entry_date': row['date'], 'entry_price': entry,
           'stop_price': entry * (1 - stop_pct / 100),
           'target_price': entry * (1 + target / 100)}
    ex = find_exit(pos, data[row['symbol']][row['i']:])
    if not ex:
        return None
    return (ex['price'] - entry) / entry * 100 - COST_PCT


def build_controls(data: Dict, inds: Dict, dates: List[str], target: float) -> Dict[str, List[float]]:
    """Random stock entered at each date's open, same exit engine — the benchmark."""
    random.seed(23)
    idx_by_date: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for symbol, cd in data.items():
        for i, c in enumerate(cd):
            idx_by_date[c['date']].append((symbol, i))

    controls: Dict[str, List[float]] = {}
    for d in dates:
        pool = idx_by_date.get(d, [])
        vals = []
        for _ in range(CONTROLS_PER_DAY):
            if not pool:
                break
            symbol, i = random.choice(pool)
            cd = data[symbol]
            if i < INDICATOR_BARS or i >= len(cd) - 3:
                continue
            row = {'symbol': symbol, 'i': i, 'date': cd[i]['date'],
                   'entry_price': cd[i]['open'], 'atr_pct': inds[symbol]['atrp'][i - 1]}
            p = trade_pnl(row, data, target)
            if p is not None:
                vals.append(p)
        controls[d] = vals
    return controls


def evaluate(rows: List[Dict], data: Dict, controls: Dict[str, List[float]],
             lo: str, hi: str, target: float) -> Optional[Dict]:
    """Per-trade result against the date-matched random control."""
    sel = [r for r in rows if lo <= r['date'] < hi]
    if not sel:
        return None
    pnls, ctrl = [], []
    for r in sel:
        p = trade_pnl(r, data, target)
        if p is None:
            continue
        pnls.append(p)
        ctrl.extend(controls.get(r['date'], []))
    if len(pnls) < 15 or not ctrl:
        return None
    m1, m2 = statistics.mean(pnls), statistics.mean(ctrl)
    s1, s2 = statistics.pstdev(pnls), statistics.pstdev(ctrl)
    t = (m1 - m2) / math.sqrt(s1 ** 2 / len(pnls) + s2 ** 2 / len(ctrl)) if s1 and s2 else 0.0
    return {'n': len(pnls), 'mean': m1, 'median': statistics.median(pnls),
            'win': sum(1 for p in pnls if p > 0) / len(pnls) * 100,
            'ctrl': m2, 'edge': m1 - m2, 't': t}


HDR = (f"  {'entry rule':<38}{'trades':>7}{'mean%':>8}{'ctrl%':>8}{'EDGE%':>8}{'t':>7}"
       f"{'win%':>7}{'port ret':>10}{'maxDD':>7}")


def show(label: str, ev: Optional[Dict], port: Optional[Dict]):
    if not ev:
        print(f"  {label:<38}{'too few trades':>7}")
        return
    p = (f"{port['return']:>9.1f}%{port['mdd']:>6.1f}%"
         if port and port.get('n') else f"{'—':>10}{'—':>7}")
    print(f"  {label:<38}{ev['n']:>7}{ev['mean']:>+7.2f}%{ev['ctrl']:>+7.2f}%"
          f"{ev['edge']:>+7.2f}%{ev['t']:>+7.2f}{ev['win']:>6.1f}%{p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', type=int, default=3)
    ap.add_argument('--target', type=float, default=config.DOUBLE_BOTTOM_TARGET_PCT)
    ap.add_argument('--with-5min', action='store_true',
                    help='also test the 5-min hammer alerts as a daily entry trigger')
    args = ap.parse_args()

    data = fetch_candles(args.years, None, False)
    all_dates = sorted({c['date'] for cd in data.values() for c in cd})
    end = all_dates[-1]
    start = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=args.years * 365)).strftime('%Y-%m-%d')
    mid = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=365)).strftime('%Y-%m-%d')
    tail = '2099-01-01'

    print(f"Computing indicators for {len(data)} symbols...", flush=True)
    inds = {s: indicators(cd) for s, cd in data.items()}
    print(f"Building random-entry controls ({CONTROLS_PER_DAY}/day)...", flush=True)
    controls = build_controls(data, inds, all_dates, args.target)

    print(f"\nExit engine held FIXED: arm +{args.target:.0f}%, trail "
          f"{config.DOUBLE_BOTTOM_TRAIL_PCT}%, {config.DOUBLE_BOTTOM_STOP_ATR_MULT}xATR close "
          f"stop, {config.DOUBLE_BOTTOM_TIME_STOP_DAYS}d time stop")
    print(f"Portfolio: 1 entry/day (best rank), 4 slots, ₹{START_CAPITAL:,.0f}, "
          f"costs {COST_PCT}%")

    rulesets: List[Tuple[str, List[Dict]]] = []
    print("\nGenerating signals...", flush=True)
    db_rows = db_build_table(data, True, True, True)
    rulesets.append(('DOUBLE_BOTTOM (clean, baseline)', db_rows))
    for name, fn in DAILY_RULES:
        rulesets.append((name, signals_for(fn, data, inds)))

    # Confluence: a clean double-bottom retest that is ALSO a daily hammer.
    db_days = {(r['symbol'], r['date']) for r in db_rows}
    conf = [r for r in db_rows
            if is_hammer(next(c for c in data[r['symbol']] if c['date'] == r['date']))]
    rulesets.append(('DB + daily hammer confluence', conf))

    for period, lo, hi in (('TRAIN  (years 1-2)', start, mid), ('TEST   (final year)', mid, tail)):
        mkt = market_condition(data, lo, hi)
        print()
        print("=" * 118)
        print(f"{period}   {lo} → {'now' if hi == tail else hi}   "
              f"market: median stock {mkt['median']:+.1f}%, {mkt['breadth']:.0f}% up ({mkt['label']})")
        print("=" * 118)
        print(HDR)
        print('  ' + '-' * 116)
        scored = []
        for name, rows in rulesets:
            ev = evaluate(rows, data, controls, lo, hi, args.target)
            port, _ = portfolio_run(rows, data, all_dates, lo, hi, 4, 4, args.target)
            scored.append((name, ev, port))
        for name, ev, port in sorted(scored, key=lambda x: -(x[1]['edge'] if x[1] else -99)):
            show(name, ev, port)

    if args.with_5min:
        print()
        print("=" * 118)
        print("5-MIN HAMMER ALERTS AS A SWING ENTRY  (only 2026-01-12 → 2026-07-23 has 5-min data)")
        print("=" * 118)
        with open(RESEARCH_PICKLE, 'rb') as f:
            sig = pickle.load(f)
        live = [r for r in sig if r['long'] and r['confidence'] >= 6.0
                and r['volume_ratio'] >= 1.2]
        print(f"  {len(live)} bullish 5-min hammer alerts (live gates) in the window")

        idx = {s: {c['date']: i for i, c in enumerate(cd)} for s, cd in data.items()}
        rows, seen = [], set()
        for r in live:
            d = r['date'].isoformat()
            key = (r['symbol'], d)
            if key in seen or r['symbol'] not in idx or d not in idx[r['symbol']]:
                continue
            seen.add(key)
            i = idx[r['symbol']][d]
            cd = data[r['symbol']]
            if i + 1 >= len(cd) - 2 or i < INDICATOR_BARS:
                continue
            rows.append({'symbol': r['symbol'], 'i': i + 1, 'date': cd[i + 1]['date'],
                         'entry_price': cd[i + 1]['open'], 'strength': r['confidence'],
                         'rally': 0.0, 'atr_pct': inds[r['symbol']]['atrp'][i],
                         'level': cd[i]['low'], 'touches': 0})
        rows.sort(key=lambda r: (r['date'], r['symbol']))
        lo5 = min(r['date'] for r in rows) if rows else start
        print(f"  → {len(rows)} distinct (stock, day) entries after de-duplication\n")
        print(HDR)
        print('  ' + '-' * 116)
        ev = evaluate(rows, data, controls, lo5, tail, args.target)
        port, _ = portfolio_run(rows, data, all_dates, lo5, tail, 4, 4, args.target)
        show('5MIN_HAMMER → next-day open', ev, port)

        db5 = [r for r in db_rows if r['date'] >= lo5]
        overlap = {(r['symbol'], r['date']) for r in rows} & {(r['symbol'], r['date']) for r in db5}
        print(f"\n  Double-bottom ∩ 5-min hammer in the same window: {len(overlap)} overlaps "
              f"({len(db5)} DB signals, {len(rows)} hammer days) — too few to test.")


if __name__ == '__main__':
    main()
