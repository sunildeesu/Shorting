#!/usr/bin/env python3
"""
ATR strategy comparison: entry 1.5x vs 2.5x, Friday-exit vs ATR trailing-stop.

Fetches each stock's daily data ONCE and simulates all variants in memory, so
results are directly comparable to backtest_atr_strategy.py (same entry/stop/filter
semantics). Reports gross and net-of-cost expectancy.

Usage: venv/bin/python3 backtest_atr_compare.py --months 2 [--cost 0.20]
"""
import argparse
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import pandas_ta as ta
from kiteconnect import KiteConnect

import config
from backtest_atr_strategy import ATRBacktester  # reuse stock/token loading + fetch

TRAIL_MULT = 2.0  # ATR trailing-stop distance (chandelier-style), representative value


def simulate(df: pd.DataFrame, entry_mult: float, exit_mode: str) -> List[float]:
    """Return list of trade P&L% for one variant. exit_mode: 'friday' | 'trail'."""
    trades: List[float] = []
    pos = None
    for _, row in df.iterrows():
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        a20, a30 = row['atr_20'], row['atr_30']
        if pd.isna(a20) or pd.isna(a30):
            continue
        entry_level = o + entry_mult * a20
        init_stop = entry_level - config.ATR_STOP_MULTIPLIER * a20
        vol_ok = a20 < a30 if config.ATR_FILTER_CONTRACTION else True

        if pos is None:
            if h >= entry_level and vol_ok:
                pos = {'entry': entry_level, 'stop': init_stop, 'atr': a20,
                       'hi': h, 'edate': row['date']}
        else:
            exit_price = None
            if exit_mode == 'trail':
                # trail stop up using highest high since entry, never down
                pos['hi'] = max(pos['hi'], h)
                pos['stop'] = max(pos['stop'], pos['hi'] - TRAIL_MULT * pos['atr'])
            if l <= pos['stop']:
                exit_price = pos['stop']
            elif exit_mode == 'friday' and row['date'].weekday() == 4 and config.ATR_FRIDAY_EXIT:
                exit_price = c
            if exit_price is not None:
                trades.append((exit_price - pos['entry']) / pos['entry'] * 100)
                pos = None
    if pos is not None:  # close at end
        last_c = df.iloc[-1]['close']
        trades.append((last_c - pos['entry']) / pos['entry'] * 100)
    return trades


def stats(trades: List[float], cost_pct: float) -> Dict:
    n = len(trades)
    if n == 0:
        return {'n': 0}
    s = pd.Series(trades)
    wins = s[s > 0]
    total = s.sum()
    net_total = total - n * cost_pct  # round-trip cost per trade
    return {
        'n': n,
        'win_rate': len(wins) / n * 100,
        'total': total,
        'avg': s.mean(),
        'net_avg': s.mean() - cost_pct,
        'net_total': net_total,
        'avg_win': wins.mean() if len(wins) else 0,
        'avg_loss': s[s <= 0].mean() if (s <= 0).any() else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--months', type=int, default=2)
    ap.add_argument('--stocks', type=int)
    ap.add_argument('--cost', type=float, default=0.20,
                    help='round-trip cost %% per trade (charges+slippage)')
    args = ap.parse_args()

    end = datetime.now()
    start = end - timedelta(days=args.months * 30)
    bt = ATRBacktester(start, end)  # reuses loaders + fetch_historical_data
    symbols = bt.stocks[:args.stocks] if args.stocks else bt.stocks

    variants = [('1.5x + Friday', 1.5, 'friday'), ('2.5x + Friday', 2.5, 'friday'),
                ('1.5x + Trail2.0', 1.5, 'trail'), ('2.5x + Trail2.0', 2.5, 'trail')]
    agg: Dict[str, List[float]] = {v[0]: [] for v in variants}

    for i, sym in enumerate(symbols, 1):
        df = bt.fetch_historical_data(sym, start, end)
        if df is None or len(df) < config.ATR_PERIOD_LONG:
            continue
        df['atr_20'] = ta.atr(df['high'], df['low'], df['close'], length=config.ATR_PERIOD_SHORT)
        df['atr_30'] = ta.atr(df['high'], df['low'], df['close'], length=config.ATR_PERIOD_LONG)
        df = df[df['date'] >= start].copy()
        for name, em, ex in variants:
            agg[name].extend(simulate(df, em, ex))
        if i % 25 == 0:
            print(f"  ...{i}/{len(symbols)} stocks")
        if i < len(symbols):
            time.sleep(config.REQUEST_DELAY_SECONDS)

    print("\n" + "=" * 96)
    print(f"ATR COMPARISON | past {args.months} months | {len(symbols)} stocks | "
          f"cost assumption {args.cost:.2f}% round-trip/trade")
    print("=" * 96)
    hdr = f"{'Variant':<18}{'Trades':>7}{'Win%':>7}{'Gross%':>9}{'Avg%':>8}{'NetAvg%':>9}{'NetTot%':>9}{'₹1L/trade net':>15}"
    print(hdr)
    print("-" * 96)
    for name, _, _ in variants:
        st = stats(agg[name], args.cost)
        if st['n'] == 0:
            print(f"{name:<18}{'0':>7}")
            continue
        net_rs = st['net_total'] / 100 * 100000
        print(f"{name:<18}{st['n']:>7}{st['win_rate']:>6.1f}%{st['total']:>8.1f}%"
              f"{st['avg']:>7.2f}%{st['net_avg']:>8.2f}%{st['net_total']:>8.1f}%{net_rs:>14,.0f}")
    print("-" * 96)
    print("NetAvg% = per-trade expectancy after cost. NetTot% = summed net P&L. "
          f"₹ col = NetTot applied to ₹1L/trade.\nTrail uses {TRAIL_MULT}xATR chandelier stop, no Friday exit.")


if __name__ == '__main__':
    main()
