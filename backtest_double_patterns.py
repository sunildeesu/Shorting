#!/usr/bin/env python3
"""
Backtest the EOD Double Bottom (bullish) and Double Top (bearish) patterns.

Drives EODPatternDetector's _detect_double_bottom / _detect_double_top directly
(double-top is disabled in the live service, so we invoke it to see its numbers).
Fetches each stock's daily series once, slides the detector over it in-memory, and
simulates each signal with fill + stop-loss + target using the detector's own
buy_price/target_price/stop_loss. Reports win rate, expectancy and net-of-cost earnings.

Usage: venv/bin/python3 backtest_double_patterns.py --months 6 [--cost 0.20] [--stocks N]
"""
import argparse
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from kiteconnect import KiteConnect

import config
from eod_pattern_detector import EODPatternDetector

WINDOW = 30   # candles fed to the detector each step (it internally uses last ~15)
HOLD = 20     # max forward trading days to hold a position


def load_stocks() -> List[str]:
    return json.load(open(config.STOCK_LIST_FILE))['stocks']


def load_tokens() -> Dict[str, int]:
    return json.load(open('data/instrument_tokens.json'))


def simulate(det: EODPatternDetector, sig: Dict, fwd: List[Dict], cost: float) -> Optional[Dict]:
    """Simulate one signal forward. Returns trade dict or None (bullish never filled)."""
    entry, target, stop = sig['buy_price'], sig['target_price'], sig['stop_loss']
    bullish = sig['pattern_type'] == 'BULLISH'
    if not fwd:
        return None

    if bullish:
        filled = False
        for c in fwd:
            if not filled:
                if c['low'] <= entry:   # limit fill near the second low
                    filled = True
                else:
                    continue
            # once filled (incl. fill day): stop checked before target (conservative)
            if c['low'] <= stop:
                return _mk(sig, entry, stop, cost, 'STOP')
            if c['high'] >= target:
                return _mk(sig, entry, target, cost, 'TARGET')
        if filled:
            return _mk(sig, entry, fwd[-1]['close'], cost, 'TIME')
        return None  # price ran away, limit never hit → no trade
    else:  # BEARISH: enter at market (buy_price == current_price), hold from next day
        for c in fwd:
            if c['high'] >= stop:
                return _mk(sig, entry, stop, cost, 'STOP')
            if c['low'] <= target:
                return _mk(sig, entry, target, cost, 'TARGET')
        return _mk(sig, entry, fwd[-1]['close'], cost, 'TIME')


def _mk(sig, entry, exit_price, cost, reason) -> Dict:
    if sig['pattern_type'] == 'BULLISH':
        pnl = (exit_price - entry) / entry * 100
    else:
        pnl = (entry - exit_price) / entry * 100
    return {'pnl': pnl, 'net': pnl - cost, 'reason': reason,
            'win': pnl > 0, 'target_hit': reason == 'TARGET'}


def run(months: int, cost: float, max_stocks: Optional[int]):
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)
    det = EODPatternDetector(pattern_tolerance=2.0, volume_confirmation=True,
                             min_confidence=7.5, require_confirmation=False)  # live params
    tokens = load_tokens()
    stocks = [s for s in load_stocks() if s in tokens]
    if max_stocks:
        stocks = stocks[:max_stocks]

    end = datetime.now()
    start = end - timedelta(days=months * 30)
    fetch_from = start - timedelta(days=60)  # warmup buffer

    res = {'DOUBLE_BOTTOM': [], 'DOUBLE_TOP': []}
    detectors = [('DOUBLE_BOTTOM', det._detect_double_bottom),
                 ('DOUBLE_TOP', det._detect_double_top)]

    for n, sym in enumerate(stocks, 1):
        try:
            candles = kite.historical_data(tokens[sym], fetch_from.date(), end.date(), 'day')
        except Exception:
            continue
        if len(candles) < WINDOW + 2:
            if n < len(stocks):
                time.sleep(config.REQUEST_DELAY_SECONDS)
            continue
        next_ok = {'DOUBLE_BOTTOM': -1, 'DOUBLE_TOP': -1}
        for i in range(WINDOW, len(candles) - 1):
            if candles[i]['date'].replace(tzinfo=None) < start:
                continue
            window = candles[i - WINDOW + 1:i + 1]
            avgvol = det._calculate_avg_volume(window)
            for name, fn in detectors:
                if i < next_ok[name]:
                    continue
                sig = fn(window, avgvol, 'NEUTRAL')
                if not sig or sig.get('confidence_score', 0) < det.min_confidence:
                    continue
                trade = simulate(det, sig, candles[i + 1:i + 1 + HOLD], cost)
                if trade:
                    trade['symbol'] = sym
                    trade['date'] = candles[i]['date'].replace(tzinfo=None)
                    res[name].append(trade)
                    next_ok[name] = i + HOLD  # cooldown = holding window
        if n % 25 == 0:
            print(f"  ...{n}/{len(stocks)} stocks")
        if n < len(stocks):
            time.sleep(config.REQUEST_DELAY_SECONDS)

    print("\n" + "=" * 92)
    print(f"DOUBLE PATTERN BACKTEST | past {months} months | {len(stocks)} stocks | "
          f"cost {cost:.2f}%/trade | hold ≤{HOLD}d")
    print("=" * 92)
    print(f"{'Pattern':<16}{'Signals':>8}{'Win%':>7}{'TgtHit%':>9}{'Gross%':>9}"
          f"{'Avg%':>8}{'NetAvg%':>9}{'NetTot%':>9}{'₹1L/tr net':>13}")
    print("-" * 92)
    for name in ('DOUBLE_BOTTOM', 'DOUBLE_TOP'):
        t = res[name]
        n = len(t)
        if n == 0:
            print(f"{name:<16}{0:>8}   (no filled signals)")
            continue
        wins = sum(x['win'] for x in t)
        tgt = sum(x['target_hit'] for x in t)
        gross = sum(x['pnl'] for x in t)
        avg = gross / n
        net_tot = sum(x['net'] for x in t)
        print(f"{name:<16}{n:>8}{wins/n*100:>6.1f}%{tgt/n*100:>8.1f}%{gross:>8.1f}%"
              f"{avg:>7.2f}%{avg - cost:>8.2f}%{net_tot:>8.1f}%{net_tot/100*100000:>12,.0f}")
    print("-" * 92)
    print("Double-bottom = limit fill at buy price (near 2nd low); unfilled signals excluded.")
    print("Double-top = market entry. Same-day stop+target → stop assumed first (conservative).")

    # Diagnostics: outlier concentration + monthly net (regime check)
    import statistics as st
    for name in ('DOUBLE_BOTTOM', 'DOUBLE_TOP'):
        t = res[name]
        if not t:
            continue
        pnls = sorted((x['pnl'] for x in t), reverse=True)
        gross = sum(pnls)
        top3 = sum(pnls[:3])
        print(f"\n[{name}] n={len(t)}  median={st.median(pnls):+.2f}%  "
              f"best={pnls[0]:+.1f}%  worst={pnls[-1]:+.1f}%  "
              f"top-3 winners = {top3:+.1f}% ({(top3/gross*100 if gross else 0):.0f}% of gross)")
        monthly = {}
        for x in t:
            m = x['date'].strftime('%Y-%m')
            monthly.setdefault(m, []).append(x['net'])
        cells = "  ".join(f"{m}:{sum(v):+.0f}%(n{len(v)})" for m, v in sorted(monthly.items()))
        print(f"   monthly net: {cells}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--months', type=int, default=6)
    ap.add_argument('--cost', type=float, default=0.20)
    ap.add_argument('--stocks', type=int)
    args = ap.parse_args()
    run(args.months, args.cost, args.stocks)
