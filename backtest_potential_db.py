#!/usr/bin/env python3
"""
Backtest the intraday potential-double-bottom logic (OLD vs NEW detection).

Trade model for a "price retested support" signal (long):
  entry  = the support level (price dipped into the band that day)
  stop   = level - STOP_PCT%   (a decisive breakdown)
  target = the prior middle-peak of the W (peak_between)
  hold   <= HOLD trading days, else exit at close. One trade per symbol at a time.

OLD = every local-minima level (3% rally), ±2% band.
NEW = significant swing-low setups (pivot), 6% rally, ±1.5% band, not-below, best-only.

Usage: venv/bin/python3 backtest_potential_db.py --months 6 [--cost 0.20] [--stocks N]
"""
import argparse, json, time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from kiteconnect import KiteConnect
import config
from double_bottom_support_monitor import find_double_bottom_setups

HOLD = 20      # overridden by --hold
STOP_PCT = 2.5


def old_setups(cd: List[Dict]) -> List[Dict]:
    n = len(cd); out = []
    for i in range(1, n - 1):
        lo = cd[i]['low']
        if lo < cd[i-1]['low'] and lo < cd[i+1]['low'] and (n-1)-i >= 5:
            peak = max(c['high'] for c in cd[i+1:])
            if peak >= lo * 1.03:
                out.append({'level': lo, 'peak_between': peak, 'rally_pct': (peak-lo)/lo*100})
    out.sort(key=lambda s: s['rally_pct'], reverse=True)
    return out


def simulate(level, target, fwd, cost):
    stop = level * (1 - STOP_PCT/100)
    entry = level
    for c in fwd:
        if c['low'] <= stop:
            return {'pnl': (stop-entry)/entry*100 - cost, 'win': False, 'tgt': False}
        if c['high'] >= target:
            return {'pnl': (target-entry)/entry*100 - cost, 'win': True, 'tgt': True}
    ex = fwd[-1]['close']
    p = (ex-entry)/entry*100 - cost
    return {'pnl': p, 'win': p > 0, 'tgt': False}


def run(months, cost, max_stocks):
    kite = KiteConnect(api_key=config.KITE_API_KEY); kite.set_access_token(config.KITE_ACCESS_TOKEN)
    tokens = json.load(open('data/instrument_tokens.json'))
    stocks = [s for s in json.load(open('fo_stocks.json'))['stocks'] if s in tokens]
    if max_stocks: stocks = stocks[:max_stocks]
    lb = config.DOUBLE_BOTTOM_LOOKBACK_DAYS
    prox_new, prox_old = config.DOUBLE_BOTTOM_PROXIMITY_PCT, 2.0
    maxbelow = config.DOUBLE_BOTTOM_MAX_BELOW_PCT
    end = datetime.now(); start = end - timedelta(days=months*30)
    frm = start - timedelta(days=int(lb*1.6)+20)

    trades = {'OLD': [], 'NEW': []}
    for n, s in enumerate(stocks, 1):
        try: cd = kite.historical_data(tokens[s], frm.date(), end.date(), 'day')
        except: continue
        if len(cd) < lb + 2:
            if n < len(stocks): time.sleep(config.REQUEST_DELAY_SECONDS)
            continue
        next_ok = {'OLD': -1, 'NEW': -1}
        for i in range(lb, len(cd)-1):
            if cd[i]['date'].replace(tzinfo=None) < start: continue
            win = cd[i-lb+1:i+1]; low_i = cd[i]['low']
            variants = {
                'NEW': (find_double_bottom_setups(win, config.DOUBLE_BOTTOM_MIN_RALLY_PCT,
                        config.DOUBLE_BOTTOM_PIVOT_BARS, min_days_ago=config.DOUBLE_BOTTOM_MIN_DAYS_AGO,
                        max_days_ago=config.DOUBLE_BOTTOM_MAX_DAYS_AGO), prox_new),
                'OLD': (old_setups(win), prox_old),
            }
            for name, (setups, prox) in variants.items():
                if i < next_ok[name]: continue
                m = [x for x in setups
                     if low_i <= x['level']*(1+prox/100) and low_i >= x['level']*(1-maxbelow/100)]
                if not m: continue
                best = m[0]
                t = simulate(best['level'], best['peak_between'], cd[i+1:i+1+HOLD], cost)
                trades[name].append(t); next_ok[name] = i + HOLD
        if n % 25 == 0: print(f"  ...{n}/{len(stocks)}")
        if n < len(stocks): time.sleep(config.REQUEST_DELAY_SECONDS)

    print("\n" + "="*78)
    print(f"POTENTIAL DOUBLE-BOTTOM logic backtest | {months}mo | {len(stocks)} stocks | cost {cost}%/trade")
    print("="*78)
    print(f"{'Logic':<6}{'Trades':>8}{'Win%':>8}{'TgtHit%':>9}{'AvgNet%':>9}{'TotNet%':>9}{'₹1L/tr':>11}")
    print("-"*78)
    for name in ('OLD', 'NEW'):
        t = trades[name]; nt = len(t)
        if not nt: print(f"{name:<6}{0:>8}"); continue
        wr = sum(x['win'] for x in t)/nt*100
        th = sum(x['tgt'] for x in t)/nt*100
        avg = sum(x['pnl'] for x in t)/nt
        tot = sum(x['pnl'] for x in t)
        print(f"{name:<6}{nt:>8}{wr:>7.1f}%{th:>8.1f}%{avg:>8.2f}%{tot:>8.1f}%{tot/100*100000:>10,.0f}")
    print("-"*78)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--months', type=int, default=6)
    ap.add_argument('--cost', type=float, default=0.20)
    ap.add_argument('--stocks', type=int)
    ap.add_argument('--hold', type=int, default=20)
    a = ap.parse_args()
    globals()['HOLD'] = a.hold
    print(f"(holding window = {a.hold} trading days)")
    run(a.months, a.cost, a.stocks)
