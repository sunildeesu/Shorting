#!/usr/bin/env python3
"""
Audit of backtest_double_bottom_portfolio.py: price each look-ahead assumption, and answer
what happens when the 4-slot capital constraint is lifted.

The exit engine was checked by reading it and is clean — replay() excludes the entry day and
only ratchets the trail on COMPLETED bars, both deliberately. Everything suspect is on the
ENTRY side, in build_table(), which decides on which days a signal existed:

  L1  TREND GATE USES THE DAY'S CLOSE. build_table keeps a day when cd[i]['close'] > SMA,
      and the SMA window itself includes day i. Live compares the trend gate against the
      price AT THE MOMENT OF THE RETEST — which is near the day's LOW, hours before that
      close is known. The backtest therefore keeps exactly the dip days that recovered into
      the close and drops the ones that kept falling.
      Fix: SMA over days < i, compared against the entry price.

  L2  LEVEL DETECTION SEES THE SIGNAL DAY. The window handed to find_double_bottom_setups is
      cd[i-lookback+1 : i+1], so day i's own low takes part in the "is this level still
      unbroken" test and in the touch count.
      Fix: build the levels from days < i only.

  L3  BREAKDOWN DAYS ARE DELETED. The trigger requires low >= level*(1-max_below), so any day
      where price sliced more than 1% through support is dropped from the table entirely —
      even though live, price passed DOWN THROUGH the alert band on its way there and the
      monitor would have fired and bought. This removes precisely the worst losses.
      Fix: fire whenever the day's [low, high] range intersects the alert band, entering at
      the first band price the day's path would have touched.

Each fix is applied alone and then together, so the cost of each is visible separately.

Usage:
    venv/bin/python3 audit_double_bottom_backtest.py                 # full audit
    venv/bin/python3 audit_double_bottom_backtest.py --years 3 --stocks 60

Read-only: reuses the cached candles, never writes live state or the shared table cache.

Author: Claude Code
Date: 2026-07-23
"""

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import config
from double_bottom_support_monitor import (
    find_double_bottom_setups, sma, atr_percent, stop_distance_pct,
)
from double_bottom_position_tracker import find_exit
from backtest_double_bottom_portfolio import (
    fetch_candles, market_condition, performance, START_CAPITAL, COST_PCT, DP_FEE,
    INDICATOR_BARS,
)


# --------------------------------------------------------------------- candidate table

def build_table(data: Dict[str, List[Dict]], fix_trend: bool, fix_levels: bool,
                fix_breakdown: bool) -> List[Dict]:
    """
    One row per (symbol, day) a signal existed. Flags switch each look-ahead fix on.

    Returns rows carrying their own entry price, because with fix_breakdown the fill is no
    longer always the top of the band.
    """
    lookback = config.DOUBLE_BOTTOM_LOOKBACK_DAYS
    warmup = max(lookback, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD,
                 config.DOUBLE_BOTTOM_ATR_PERIOD + 1) + 1
    prox = config.DOUBLE_BOTTOM_PROXIMITY_PCT
    max_below = config.DOUBLE_BOTTOM_MAX_BELOW_PCT

    rows: List[Dict] = []
    for symbol, cd in data.items():
        if len(cd) < warmup + 5:
            continue
        for i in range(warmup, len(cd) - 1):
            # L2: levels from completed days only, or the original window that includes day i.
            window = cd[i - lookback:i] if fix_levels else cd[i - lookback + 1:i + 1]
            setups = find_double_bottom_setups(
                window,
                min_rally_pct=config.DOUBLE_BOTTOM_MIN_RALLY_PCT,
                pivot_bars=config.DOUBLE_BOTTOM_PIVOT_BARS,
                min_days_ago=config.DOUBLE_BOTTOM_MIN_DAYS_AGO,
                max_days_ago=config.DOUBLE_BOTTOM_MAX_DAYS_AGO,
                min_strength=config.DOUBLE_BOTTOM_MIN_STRENGTH,
                touch_tolerance_pct=config.DOUBLE_BOTTOM_TOUCH_TOLERANCE_PCT,
            )
            setups = [s for s in setups if s['touches'] >= config.DOUBLE_BOTTOM_MIN_TOUCHES]
            if not setups:
                continue

            bar = cd[i]
            low, high, close, op = bar['low'], bar['high'], bar['close'], bar['open']

            hit = entry = None
            for s in setups:
                lvl = s['level']
                top, bottom = lvl * (1 + prox / 100), lvl * (1 - prox / 100)
                if fix_breakdown:
                    # L3: the alert fires if the day's path crossed the band at all. Entry is
                    # the first band price that path reaches — down through the top, up
                    # through the bottom, or the open if it started inside.
                    if low > top or high < bottom:
                        continue
                    entry = top if op > top else (bottom if op < bottom else op)
                else:
                    if abs(low - lvl) / lvl * 100 > prox or low < lvl * (1 - max_below / 100):
                        continue
                    entry = top
                hit = s
                break
            if not hit:
                continue

            # L1: trend gate on completed days, judged at the entry price, not the close.
            if config.DOUBLE_BOTTOM_REQUIRE_UPTREND:
                if fix_trend:
                    ind = cd[max(0, i - INDICATOR_BARS):i]
                    trend_sma, ref = sma(ind, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD), entry
                else:
                    ind = cd[max(0, i - INDICATOR_BARS + 1):i + 1]
                    trend_sma, ref = sma(ind, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD), close
                if trend_sma is None or ref <= trend_sma:
                    continue

            atr_src = cd[max(0, i - INDICATOR_BARS):i] if fix_trend \
                else cd[max(0, i - INDICATOR_BARS + 1):i + 1]
            rows.append({
                'symbol': symbol, 'i': i, 'date': bar['date'], 'entry_price': entry,
                'level': hit['level'], 'strength': hit['strength'],
                'touches': hit['touches'], 'rally': hit['rally_pct'],
                'atr_pct': atr_percent(atr_src, config.DOUBLE_BOTTOM_ATR_PERIOD),
            })
    rows.sort(key=lambda r: (r['date'], r['symbol']))
    return rows


# ------------------------------------------------------------------------- portfolio

def simulate(rows: List[Dict], data: Dict[str, List[Dict]], dates: List[str],
             slots: int, size_div: int, target_pct: float,
             one_per_day: bool = True) -> Tuple[List, List, int, Dict]:
    """
    Same calendar walk as the original, with two knobs separated that it conflates:

      slots    — how many positions may be open at once (the capital constraint)
      size_div — position size = equity / size_div

    The original ties them together, so raising the slot count silently shrinks every
    position. Keeping size_div at 4 while lifting slots answers "what if I could take every
    signal at the same size", which requires leverage — reported as peak exposure.
    """
    by_day: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        by_day[r['date']].append(r)

    prices = {s: {c['date']: c['close'] for c in cd} for s, cd in data.items()}
    cash = START_CAPITAL
    open_pos: List[Dict] = []
    curve: List[Tuple[str, float]] = []
    trades: List[Dict] = []
    missed = 0
    peak_open = 0
    peak_exposure = 0.0

    for d in dates:
        for p in list(open_pos):
            if p['exit'] and p['exit']['date'] <= d:
                cash += p['shares'] * p['exit']['price'] * (1 - COST_PCT / 200) - DP_FEE
                trades.append({'symbol': p['symbol'],
                               'pnl': (p['exit']['price'] - p['entry']) / p['entry'] * 100,
                               'reason': p['exit']['reason'], 'date': p['exit']['date'],
                               'days': p['exit']['days_held']})
                open_pos.remove(p)

        if d in by_day:
            free = [r for r in by_day[d]
                    if not any(p['symbol'] == r['symbol'] for p in open_pos)]
            free.sort(key=lambda r: (r['strength'], r['rally']), reverse=True)
            for best in (free[:1] if one_per_day else free):
                if len(open_pos) >= slots:
                    missed += 1
                    continue
                entry = best['entry_price']
                equity = cash + sum(pp['shares'] * prices[pp['symbol']].get(d, pp['entry'])
                                    for pp in open_pos)
                alloc = equity / size_div
                if cash < alloc:                 # unlevered: no cash, no trade
                    missed += 1
                    continue
                if alloc <= 1000:
                    missed += 1
                    continue
                stop_pct = stop_distance_pct(best['atr_pct'])
                position = {'symbol': best['symbol'], 'entry_date': d, 'entry_price': entry,
                            'stop_price': entry * (1 - stop_pct / 100),
                            'target_price': entry * (1 + target_pct / 100)}
                shares = alloc / (entry * (1 + COST_PCT / 200))
                cash -= alloc
                open_pos.append({'symbol': best['symbol'], 'shares': shares, 'entry': entry,
                                 'exit': find_exit(position, data[best['symbol']][best['i']:])})

        held = sum(p['shares'] * prices[p['symbol']].get(d, p['entry']) for p in open_pos)
        equity = cash + held
        peak_open = max(peak_open, len(open_pos))
        if equity > 0:
            peak_exposure = max(peak_exposure, held / equity)
        curve.append((d, equity))

    return curve, trades, missed, {'peak_open': peak_open, 'peak_exposure': peak_exposure}


def run(rows, data, all_dates, lo, hi, slots, size_div, target, one_per_day=True):
    dates = [d for d in all_dates if lo <= d < hi]
    period_rows = [r for r in rows if lo <= r['date'] < hi]
    curve, trades, missed, extra = simulate(period_rows, data, dates, slots, size_div,
                                            target, one_per_day)
    perf = performance(curve, trades, missed, target)
    perf.update(extra)
    return perf, trades


HDR = (f"{'variant':<34}{'signals':>8}{'trades':>7}{'return':>9}{'CAGR':>8}{'maxDD':>7}"
       f"{'win%':>7}{'avgW%':>7}{'avgL%':>8}{'worst':>8}")


def line(label: str, n_rows: int, perf: Dict):
    if not perf or not perf.get('n'):
        print(f"{label:<34}{n_rows:>8}{'—':>7}")
        return
    print(f"{label:<34}{n_rows:>8}{perf['n']:>7}{perf['return']:>8.1f}%{perf['cagr']:>7.1f}%"
          f"{perf['mdd']:>6.1f}%{perf['win']:>6.1f}%{perf['avg_win']:>6.2f}%"
          f"{perf['avg_loss']:>7.2f}%{perf['worst']:>7.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', type=int, default=3)
    ap.add_argument('--stocks', type=int)
    ap.add_argument('--target', type=float, default=config.DOUBLE_BOTTOM_TARGET_PCT)
    args = ap.parse_args()

    data = fetch_candles(args.years, args.stocks, False)
    if not data:
        print("No candle data available")
        sys.exit(1)
    all_dates = sorted({c['date'] for cd in data.values() for c in cd})
    end = all_dates[-1]
    lo = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=args.years * 365)).strftime('%Y-%m-%d')
    hi = '2099-01-01'

    print(f"\n₹{START_CAPITAL:,.0f} | {args.years}y to {end} | {len(data)} stocks | "
          f"target +{args.target:.0f}% | costs {COST_PCT}% + ₹{DP_FEE:.0f}/sell")

    variants = [
        ('BASELINE (as published)',           False, False, False),
        ('fix L1 trend gate only',            True,  False, False),
        ('fix L2 level window only',          False, True,  False),
        ('fix L3 breakdown days only',        False, False, True),
        ('fix L2+L3 (entry-day info out)',    False, True,  True),
        ('fix L1+L2',                         True,  True,  False),
        ('ALL FIXES (no look-ahead)',         True,  True,  True),
    ]
    print()
    print("=" * 110)
    print("PART 1 — COST OF EACH LOOK-AHEAD (4 slots, 1 new trade/day, as published)")
    print("=" * 110)
    print(HDR)
    print('-' * 110)
    tables = {}
    for label, ft, fl, fb in variants:
        rows = build_table(data, ft, fl, fb)
        tables[label] = rows
        perf, _ = run(rows, data, all_dates, lo, hi, 4, 4, args.target)
        line(label, len(rows), perf)

    clean = tables['ALL FIXES (no look-ahead)']
    base = tables['BASELINE (as published)']

    print()
    print("=" * 110)
    print("PART 2 — LIFTING THE 4-SLOT CONSTRAINT")
    print("=" * 110)
    print("  slots = max concurrent positions; size = equity/N per position.")
    print("  Raising slots WITHOUT changing size needs leverage; peak exposure is reported.")
    for tag, rows in (('BASELINE table', base), ('CLEAN table (no look-ahead)', clean)):
        print(f"\n  {tag}")
        print('  ' + HDR)
        print('  ' + '-' * 108)
        for slots, size_div, opd, label in [
            (4,   4,  True,  '4 slots, size/4 (published)'),
            (8,   8,  True,  '8 slots, size/8'),
            (12,  12, True,  '12 slots, size/12'),
            (20,  20, True,  '20 slots, size/20'),
            (999, 4,  True,  'unlimited slots, size/4'),
            (999, 8,  True,  'unlimited slots, size/8'),
            (999, 20, True,  'unlimited slots, size/20'),
            (999, 20, False, 'unlimited + all signals/day'),
        ]:
            perf, _ = run(rows, data, all_dates, lo, hi, slots, size_div, args.target, opd)
            print('  ', end='')
            line(label, len(rows), perf)
            if perf and perf.get('n'):
                print(f"      → peak {perf['peak_open']} concurrent positions, "
                      f"peak exposure {perf['peak_exposure'] * 100:.0f}% of equity, "
                      f"{perf['missed']} signals skipped")

    print()
    print("=" * 110)
    print("PART 3 — PER-TRADE QUALITY, capital constraints removed entirely")
    print("=" * 110)
    print("  Every signal taken at equal weight; no slots, no one-per-day, no compounding.")
    print(f"  {'table':<34}{'signals':>8}{'mean%':>9}{'median%':>9}{'win%':>8}{'worst%':>8}")
    for tag, rows in (('BASELINE', base), ('CLEAN (no look-ahead)', clean)):
        pnls = []
        for r in rows:
            entry = r['entry_price']
            stop_pct = stop_distance_pct(r['atr_pct'])
            pos = {'symbol': r['symbol'], 'entry_date': r['date'], 'entry_price': entry,
                   'stop_price': entry * (1 - stop_pct / 100),
                   'target_price': entry * (1 + args.target / 100)}
            ex = find_exit(pos, data[r['symbol']][r['i']:])
            if ex:
                pnls.append((ex['price'] - entry) / entry * 100 - COST_PCT)
        if pnls:
            print(f"  {tag:<34}{len(rows):>8}{statistics.mean(pnls):>+8.2f}%"
                  f"{statistics.median(pnls):>+8.2f}%"
                  f"{sum(1 for p in pnls if p > 0) / len(pnls) * 100:>7.1f}%"
                  f"{min(pnls):>7.1f}%")

    print()
    print("=" * 110)
    print("PART 4 — RANDOM-ENTRY CONTROL: is the edge the pattern, or the bull market?")
    print("=" * 110)
    print("  Same dates, same exit engine, same ATR stop geometry — but a RANDOM stock instead")
    print("  of the one the double-bottom scan chose. If the pattern adds nothing, the control")
    print("  matches the strategy. 20 random draws per signal.\n")
    import random
    random.seed(11)
    by_date_idx = defaultdict(list)
    for sym, cd in data.items():
        for idx, c in enumerate(cd):
            by_date_idx[c['date']].append((sym, idx))

    for tag, rows in (('CLEAN signals', clean),):
        real, ctrl = [], []
        for r in rows:
            entry = r['entry_price']
            stop_pct = stop_distance_pct(r['atr_pct'])
            pos = {'symbol': r['symbol'], 'entry_date': r['date'], 'entry_price': entry,
                   'stop_price': entry * (1 - stop_pct / 100),
                   'target_price': entry * (1 + args.target / 100)}
            ex = find_exit(pos, data[r['symbol']][r['i']:])
            if ex:
                real.append((ex['price'] - entry) / entry * 100 - COST_PCT)
            pool = by_date_idx.get(r['date'], [])
            for _ in range(20):
                if not pool:
                    break
                sym, idx = random.choice(pool)
                cd = data[sym]
                if idx < INDICATOR_BARS or idx >= len(cd) - 2:
                    continue
                e = cd[idx]['close']
                ap_ = atr_percent(cd[max(0, idx - INDICATOR_BARS):idx],
                                  config.DOUBLE_BOTTOM_ATR_PERIOD)
                sp = stop_distance_pct(ap_)
                cpos = {'symbol': sym, 'entry_date': r['date'], 'entry_price': e,
                        'stop_price': e * (1 - sp / 100),
                        'target_price': e * (1 + args.target / 100)}
                cex = find_exit(cpos, cd[idx:])
                if cex:
                    ctrl.append((cex['price'] - e) / e * 100 - COST_PCT)
        print(f"  {'cohort':<34}{'n':>7}{'mean%':>9}{'median%':>9}{'win%':>8}")
        for lab, v in (('double-bottom signals', real), ('random stock, same dates', ctrl)):
            if v:
                print(f"  {lab:<34}{len(v):>7}{statistics.mean(v):>+8.2f}%"
                      f"{statistics.median(v):>+8.2f}%"
                      f"{sum(1 for p in v if p > 0) / len(v) * 100:>7.1f}%")
        if real and ctrl:
            import math
            m1, m2 = statistics.mean(real), statistics.mean(ctrl)
            s1, s2 = statistics.pstdev(real), statistics.pstdev(ctrl)
            t = (m1 - m2) / math.sqrt(s1 ** 2 / len(real) + s2 ** 2 / len(ctrl))
            print(f"\n  edge over random selection: {m1 - m2:+.2f}%/trade  (Welch t = {t:+.2f})")

    mkt = market_condition(data, lo, hi)
    print(f"\nMarket over the same window: median stock {mkt['median']:+.1f}%, "
          f"{mkt['breadth']:.0f}% of stocks up ({mkt['label']}).")
    print("Universe is TODAY's F&O list applied to 3 years of history — survivorship bias "
          "inflates\nboth the strategy and this benchmark; the comparison between them is the "
          "meaningful number.")


if __name__ == '__main__':
    main()
