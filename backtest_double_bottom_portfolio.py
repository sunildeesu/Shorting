#!/usr/bin/env python3
"""
Double Bottom portfolio backtest — regime-segmented, capital-constrained.

Answers the question the per-trade statistics cannot: what does a real ₹1,00,000 account
actually do, given that only a few positions fit at once and a signal arriving with no
free slot is simply missed?

It deliberately imports the LIVE code paths rather than reimplementing them:
    find_double_bottom_setups / sma / atr_percent / stop_distance_pct
                                          <- double_bottom_support_monitor.py
    find_exit                             <- double_bottom_position_tracker.py
so a backtest result can never drift away from what the running system does.

Regime matters for this strategy, so every run prints the market condition of each period
(median stock return and breadth, measured from the universe itself) beside the strategy
result. Measured over 2023-07..2026-07 at 4 slots with the locked-trail exit: BULL year
+34.3% against a +57.1% median stock, FLAT years +19.3% and +10.3% against +1.8% and
+1.1%. Full 3 years +83.2% against a +70.2% median stock. It beats a flat market and
LOSES to a rising one — the trailing exit caps the winners the market hands out for free.

The entry logic here was de-biased in 2026-08 after audit_double_bottom_backtest.py found
three look-ahead biases in it (see build_table). The numbers above are the corrected ones.
The figures this file used to quote — +101.1% / +43.4% / +40.8%, full 3y +295.9% — were
produced by the biased version and are not reproducible; do not restore them.
A sustained DOWNTREND is untested — no such year is in the data.

Usage:
    venv/bin/python3 backtest_double_bottom_portfolio.py --years 1 --slots 4
    venv/bin/python3 backtest_double_bottom_portfolio.py --by-year
    venv/bin/python3 backtest_double_bottom_portfolio.py --years 3 --target 8 --hold 40

Read-only: never writes the live positions file and never sends an alert.

Author: Claude Code
Date: 2026-07-23
"""

import argparse
import hashlib
import json
import os
import pickle
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from kiteconnect import KiteConnect

import config
from double_bottom_support_monitor import (
    find_double_bottom_setups, sma, atr_percent, stop_distance_pct,
)
from double_bottom_position_tracker import find_exit
from historical_data_cache import get_historical_cache

CANDLE_CACHE = 'data/double_bottom_backtest_candles.json'
TABLE_CACHE = 'data/double_bottom_backtest_table.pkl'
INSTRUMENT_TOKENS_FILE = 'data/instrument_tokens.json'

START_CAPITAL = 100_000.0
COST_PCT = 0.30      # round-trip brokerage + STT + stamp + GST, delivery equity
DP_FEE = 20.0        # flat per-sell charge; hurts small positions disproportionately

# Bars of history handed to the indicators — the live monitor fetches ~70 trading bars,
# so the backtest sees exactly the same amount when computing SMA/ATR.
INDICATOR_BARS = 70

# Bumped whenever build_table's detection logic changes. It is part of the table cache key
# so a table pickled by an earlier (look-ahead) version can never be silently reused —
# the parameter fingerprint alone does not notice that the CODE changed.
#   1 = original, look-ahead entry logic
#   2 = de-biased entry logic (see build_table)
TABLE_LOGIC_VERSION = 2


# ----------------------------------------------------------------------------- data

def fetch_candles(years: int, max_stocks: Optional[int], refresh: bool) -> Dict[str, List[Dict]]:
    """Daily candles per symbol, cached on disk so repeat runs need no API calls."""
    if os.path.exists(CANDLE_CACHE) and not refresh:
        with open(CANDLE_CACHE) as f:
            cached = json.load(f)
        if cached.get('years', 0) >= years:
            data = cached['data']
            print(f"Using cached candles: {len(data)} symbols "
                  f"({cached['years']}y, fetched {cached['fetched'][:10]})")
            return {s: c for s, c in list(data.items())[:max_stocks]} if max_stocks else data

    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)
    cache = get_historical_cache()
    with open(INSTRUMENT_TOKENS_FILE) as f:
        tokens = json.load(f)
    with open(config.STOCK_LIST_FILE) as f:
        stocks = [s for s in json.load(f)['stocks'] if s in tokens]
    if max_stocks:
        stocks = stocks[:max_stocks]

    end = datetime.now()
    start = end - timedelta(days=years * 365 + 150)   # padding for warmup + holidays
    print(f"Fetching {years}y daily candles for {len(stocks)} symbols "
          f"(~{len(stocks)} API calls)...")

    data: Dict[str, List[Dict]] = {}
    for n, symbol in enumerate(stocks, 1):
        try:
            cd = cache.get_historical_data(kite=kite, instrument_token=tokens[symbol],
                                           from_date=start, to_date=end, interval='day')
        except Exception as e:
            print(f"  {symbol}: fetch failed ({e})")
            continue
        if cd:
            data[symbol] = [{'date': str(c['date'])[:10], 'open': c['open'], 'high': c['high'],
                             'low': c['low'], 'close': c['close']} for c in cd]
        if n % 25 == 0:
            print(f"  ...{n}/{len(stocks)}", flush=True)
        if n < len(stocks):
            time.sleep(config.REQUEST_DELAY_SECONDS)

    os.makedirs(os.path.dirname(CANDLE_CACHE), exist_ok=True)
    with open(CANDLE_CACHE, 'w') as f:
        json.dump({'years': years, 'fetched': datetime.now().isoformat(), 'data': data}, f)
    print(f"Cached {len(data)} symbols to {CANDLE_CACHE}")
    return data


# ------------------------------------------------------------------- candidate table

def _params_key(data: Dict) -> str:
    """
    Cache key for the candidate table.

    Must fingerprint the DATA as well as the detection parameters — a table built from
    one year of candles is not valid for a three-year run, and the symbol count alone
    does not catch that.
    """
    dates = [c['date'] for cd in data.values() for c in cd]
    parts = [config.DOUBLE_BOTTOM_LOOKBACK_DAYS, config.DOUBLE_BOTTOM_MIN_RALLY_PCT,
             config.DOUBLE_BOTTOM_PIVOT_BARS, config.DOUBLE_BOTTOM_MIN_DAYS_AGO,
             config.DOUBLE_BOTTOM_MAX_DAYS_AGO, config.DOUBLE_BOTTOM_TOUCH_TOLERANCE_PCT,
             config.DOUBLE_BOTTOM_MIN_STRENGTH, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD,
             config.DOUBLE_BOTTOM_ATR_PERIOD, config.DOUBLE_BOTTOM_PROXIMITY_PCT,
             config.DOUBLE_BOTTOM_MAX_BELOW_PCT, config.DOUBLE_BOTTOM_MIN_TOUCHES,
             config.DOUBLE_BOTTOM_REQUIRE_UPTREND, INDICATOR_BARS, TABLE_LOGIC_VERSION,
             len(data), len(dates), min(dates), max(dates)]
    return hashlib.md5('|'.join(str(p) for p in parts).encode()).hexdigest()[:12]


def build_table(data: Dict[str, List[Dict]], refresh: bool) -> List[Dict]:
    """
    One row per (symbol, day) where the live monitor would have flagged a retest.

    Mirrors DoubleBottomSupportMonitor._evaluate(): an unbroken level within the proximity
    band, price above its SMA, enough touches. When a day's range intersects more than one
    level's band, the most-recent level is taken, which live path order need not agree
    with — see the tie-break note under L3.

    EVERY boundary below is drawn so the decision uses only what the live monitor knows at
    the moment it fires — intraday, hours before day i's close exists. Three look-ahead
    biases were found here by audit_double_bottom_backtest.py and are corrected in place;
    each fix is marked L1/L2/L3 and explained where it sits. Do not widen these windows
    back to `i + 1` without re-reading those comments: doing so inflated the published
    3-year return from +83% to +296%.
    """
    key = _params_key(data)
    if os.path.exists(TABLE_CACHE) and not refresh:
        with open(TABLE_CACHE, 'rb') as f:
            cached = pickle.load(f)
        if cached.get('key') == key:
            print(f"Using cached candidate table: {len(cached['rows']):,} rows")
            return cached['rows']

    lookback = config.DOUBLE_BOTTOM_LOOKBACK_DAYS
    warmup = max(lookback, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD,
                 config.DOUBLE_BOTTOM_ATR_PERIOD + 1)
    prox = config.DOUBLE_BOTTOM_PROXIMITY_PCT
    max_below = config.DOUBLE_BOTTOM_MAX_BELOW_PCT

    print(f"Building candidate table over {len(data)} symbols "
          f"(detection via find_double_bottom_setups)...")
    rows: List[Dict] = []
    for n, (symbol, cd) in enumerate(data.items(), 1):
        if len(cd) < warmup + 5:
            continue
        for i in range(warmup, len(cd) - 1):
            # L2 — levels come from COMPLETED bars only: days [i-lookback, i-1].
            # The old window was cd[i-lookback+1 : i+1], which let day i's own final low
            # decide whether a level was still unbroken (find_double_bottom_setups drops a
            # low that anything after it traded below), how far the middle-peak rally ran,
            # and how many touches the level had. Live, _compute_levels() runs off history
            # and day i's low is still being formed, so none of that is knowable.
            #
            # Dropping day i also shifts the recency boundary by one bar, unavoidably:
            # find_double_bottom_setups measures bars_ago from the LAST bar it is handed,
            # which live is today's forming bar, so MIN/MAX_DAYS_AGO (5/40) count from day
            # i. Here the window ends at i-1, making the effective window 6..41 bars before
            # day i — a first bottom exactly 5 days old is excluded, one 41 days old is
            # included. The only way to realign that boundary is to put day i back in the
            # window, which IS bias L2, so this is a consequence of the correct fix and not
            # an oversight. Impact is small: a qualifying level is normally eligible on
            # adjacent days too.
            window = cd[i - lookback:i]
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

            # L3 — a day fires if its PATH crossed the alert band, not if its final low
            # happened to settle inside it. _evaluate() runs on every quote, so the alert
            # goes out the first tick price is in the band; that price then carrying on
            # down through support is a loss the trade already owns. The old trigger
            # (low >= level*(1-max_below)) deleted exactly those days, erasing the
            # breakdowns from the sample.
            #
            # The band is the live gate verbatim: |price-level| <= prox AND price >=
            # level*(1-max_below), so the binding lower edge is whichever of the two is
            # tighter (both default to 1.0%). Entry is the first band price the day's path
            # must have touched — down through the top if it opened above, up through the
            # bottom if it opened below, else the open.
            #
            # TIE-BREAK, when a day's range intersects more than one setup's band: the
            # most-recent setup wins, because find_double_bottom_setups returns setups
            # most-recent-first and this loop breaks on the first intersecting one. Live
            # _evaluate() runs per quote and fires on whichever band the price PATH reaches
            # first, which is not necessarily the most recent level, so the two rules can
            # pick different levels. That divergence cannot be removed here: intraday path
            # order is not recoverable from a daily OHLC bar. It is a limit of the data, not
            # an unfinished piece of work — do not "fix" it by inventing a path assumption.
            # Measured across all 382 de-biased signals: 45 span more than one setup band,
            # and the level selected differs from live path order in exactly 1 (UNIONBANK
            # 2025-04-07, whose open 106.91 sits BETWEEN the two bands while low 105.71 and
            # high 112.06 mean the path touched both, so which came first is genuinely
            # unknowable from a daily bar). No signal is gained or lost by the tie-break;
            # only the level and the fill differ.
            bar = cd[i]
            hit = entry = None
            for s in setups:
                top = s['level'] * (1 + prox / 100)
                bottom = s['level'] * (1 - min(prox, max_below) / 100)
                if bar['low'] > top or bar['high'] < bottom:
                    continue
                op = bar['open']
                entry = top if op > top else (bottom if op < bottom else op)
                hit = s
                break
            if not hit:
                continue

            # L1 — trend gate on COMPLETED bars, judged at the ENTRY price. The old code
            # took the SMA over a window ending at day i and compared it to day i's close,
            # which keeps precisely the dips that recovered by the bell and drops the ones
            # that kept falling. Live, the SMA is yesterday's and the price on the other
            # side of the comparison is the retest price, near the day's low.
            #
            # The gate is evaluated ONCE per day, at the entry price. Live, _evaluate()
            # runs on every quote against _compute_levels()'s date-cached SMA, so it can
            # fire on any in-band price — and the band is only ~2% wide, so a 50-day SMA
            # can sit inside it. Where the first band price the path reaches is below the
            # SMA but a later in-band price is above it, live alerts and this drops the day
            # entirely; same on a gap-down open, where entry is the band bottom. That
            # direction is CONSERVATIVE — the backtest UNDER-counts signals relative to
            # live, it does not flatter itself. It is not a look-ahead bias and must not be
            # "fixed" by gating on some more favourable price of the day.
            ind = cd[max(0, i - INDICATOR_BARS):i]
            trend_sma = sma(ind, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD)
            if config.DOUBLE_BOTTOM_REQUIRE_UPTREND and (trend_sma is None or entry <= trend_sma):
                continue

            rows.append({
                'symbol': symbol, 'i': i, 'date': bar['date'], 'entry_price': entry,
                'level': hit['level'], 'strength': hit['strength'],
                'touches': hit['touches'], 'rally': hit['rally_pct'],
                # Same completed-bar window: the ATR that sizes the stop cannot use the
                # range of the day it is sizing.
                'atr_pct': atr_percent(ind, config.DOUBLE_BOTTOM_ATR_PERIOD),
            })
        if n % 25 == 0:
            print(f"  ...{n}/{len(data)}", flush=True)

    rows.sort(key=lambda r: (r['date'], r['symbol']))
    os.makedirs(os.path.dirname(TABLE_CACHE), exist_ok=True)
    with open(TABLE_CACHE, 'wb') as f:
        pickle.dump({'key': key, 'rows': rows}, f)
    print(f"Candidate table: {len(rows):,} retest days")
    return rows


# ------------------------------------------------------------------------- portfolio

def simulate(rows: List[Dict], data: Dict[str, List[Dict]], dates: List[str],
             slots: int, target_pct: float, hold: int) -> Tuple[List, List, int]:
    """
    Walk the calendar with finite capital.

    One new position per day at most (best strength, as _alert_best picks), only while a
    slot is free, sized at equity/slots and compounding. Exits come from the tracker's
    find_exit() so the backtest and the live exit engine are the same code.
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

    for d in dates:
        # --- exits first: a slot freed today can be reused today ---
        for p in list(open_pos):
            if p['exit'] and p['exit']['date'] <= d:
                cash += p['shares'] * p['exit']['price'] * (1 - COST_PCT / 200) - DP_FEE
                pnl = (p['exit']['price'] - p['entry']) / p['entry'] * 100
                trades.append({'symbol': p['symbol'], 'pnl': pnl,
                               'reason': p['exit']['reason'], 'date': p['exit']['date'],
                               'days': p['exit']['days_held']})
                open_pos.remove(p)

        # --- one new entry per day, best strength ---
        if d in by_day:
            free = [r for r in by_day[d] if not any(p['symbol'] == r['symbol'] for p in open_pos)]
            if free:
                if len(open_pos) >= slots:
                    missed += 1
                else:
                    best = max(free, key=lambda r: (r['strength'], r['rally']))
                    # Fill comes from the row: with the L3 fix the entry is no longer
                    # always the top of the band (see build_table).
                    entry = best['entry_price']
                    equity = cash + sum(pp['shares'] * prices[pp['symbol']].get(d, pp['entry'])
                                        for pp in open_pos)
                    alloc = min(equity / slots, cash)
                    if alloc > 1000:
                        stop_pct = stop_distance_pct(best['atr_pct'])
                        position = {
                            'symbol': best['symbol'], 'entry_date': d, 'entry_price': entry,
                            'stop_price': entry * (1 - stop_pct / 100),
                            'target_price': entry * (1 + target_pct / 100),
                        }
                        shares = alloc / (entry * (1 + COST_PCT / 200))
                        cash -= alloc
                        open_pos.append({
                            'symbol': best['symbol'], 'shares': shares, 'entry': entry,
                            'exit': find_exit(position, data[best['symbol']][best['i']:]),
                        })
                    else:
                        missed += 1

        equity = cash + sum(p['shares'] * prices[p['symbol']].get(d, p['entry'])
                            for p in open_pos)
        curve.append((d, equity))

    return curve, trades, missed


# --------------------------------------------------------------------------- metrics

def market_condition(data: Dict[str, List[Dict]], lo: str, hi: str) -> Dict:
    """Regime measured from the universe itself, not an index."""
    rets = []
    for cd in data.values():
        w = [c for c in cd if lo <= c['date'] < hi]
        if len(w) > 20:
            rets.append((w[-1]['close'] / w[0]['close'] - 1) * 100)
    if not rets:
        return {'median': 0.0, 'breadth': 0.0, 'label': 'n/a', 'n': 0}
    med = statistics.median(rets)
    breadth = sum(1 for r in rets if r > 0) / len(rets) * 100
    label = 'BULL' if med > 15 else ('DOWN' if med < -10 else 'FLAT')
    return {'median': med, 'breadth': breadth, 'label': label, 'n': len(rets)}


# Tolerance, in PERCENTAGE POINTS, for comparing a trade's P&L against the target.
# A trade that exits exactly at the armed lock fills at entry*(1+target/100), and that
# round trip lands a hair BELOW the target in binary floating point — entry 105.70 gives
# 5.999999999999998 against a 6.0 threshold. A bare `>=` therefore counts exactly-at-target
# fills as misses (it under-reported the config.py arming figure by 3 trades). 1e-9 of a
# percentage point is orders of magnitude below any real price move, so it absorbs only
# IEEE-754 representation error. Do not simplify this back to a bare `>=`.
PNL_EPS_PCT = 1e-9


def performance(curve, trades, missed,
                target_pct: float = config.DOUBLE_BOTTOM_TARGET_PCT) -> Dict:
    eq = [e for _, e in curve]
    if not eq:
        return {}
    peak, mdd, under, longest = eq[0], 0.0, 0, 0
    for v in eq:
        if v >= peak:
            peak, under = v, 0
        else:
            under += 1
            longest = max(longest, under)
        mdd = max(mdd, (peak - v) / peak * 100)
    wins = [t['pnl'] for t in trades if t['pnl'] > 0]
    losses = [t['pnl'] for t in trades if t['pnl'] <= 0]
    years = len(eq) / 252

    # Arming breakdown — this is the evidence the DOUBLE_BOTTOM_TARGET_PCT comment in
    # config.py quotes, so it is derived here rather than in a throwaway script.
    # target/trail/gap are reachable only from the armed state. A time stop can also fire
    # while armed, and when it does the exit is provably at or above the lock: the armed
    # branch of replay() returns before the time check unless the bar stayed above the
    # locked stop, which is itself never below the lock.
    def at_target(t):
        return t['pnl'] >= target_pct - PNL_EPS_PCT

    armed = [t for t in trades
             if t['reason'] in ('target', 'trail', 'gap')
             or (t['reason'] == 'time' and at_target(t))]
    gaps = [t for t in trades if t['reason'] == 'gap']

    return {
        'final': eq[-1],
        'return': (eq[-1] / START_CAPITAL - 1) * 100,
        'cagr': ((eq[-1] / START_CAPITAL) ** (1 / years) - 1) * 100 if years > 0.2 else float('nan'),
        'mdd': mdd, 'underwater': longest, 'n': len(trades),
        'win': len(wins) / len(trades) * 100 if trades else 0.0,
        'avg_win': sum(wins) / len(wins) if wins else 0.0,
        'avg_loss': sum(losses) / len(losses) if losses else 0.0,
        'worst': min((t['pnl'] for t in trades), default=0.0),
        'missed': missed,
        'armed': len(armed),
        'armed_at_target': sum(1 for t in armed if at_target(t)),
        'armed_losses': sum(1 for t in armed if t['pnl'] <= 0),
        'gaps': len(gaps),
        'gaps_at_target': sum(1 for t in gaps if at_target(t)),
        'worst_gap': min((t['pnl'] for t in gaps), default=None),
    }


def run_period(rows, data, all_dates, lo, hi, slots, target, hold) -> Tuple[Dict, Dict]:
    dates = [d for d in all_dates if lo <= d < hi]
    period_rows = [r for r in rows if lo <= r['date'] < hi]
    curve, trades, missed = simulate(period_rows, data, dates, slots, target, hold)
    return performance(curve, trades, missed, target), market_condition(data, lo, hi)


def print_row(label: str, perf: Dict, mkt: Dict) -> None:
    print(f"{label:<22}{mkt['label']:>6}{mkt['median']:>8.1f}%{mkt['breadth']:>7.0f}%"
          f"{perf['final']:>11,.0f}{perf['return']:>8.1f}%{perf['mdd']:>7.1f}%"
          f"{perf['n']:>7}{perf['win']:>7.1f}%{perf['avg_win']:>7.2f}%"
          f"{perf['avg_loss']:>8.2f}%{perf['missed']:>7}")


HEADER = (f"{'period':<22}{'regime':>6}{'mkt med':>9}{'up':>6}{'final ₹':>11}{'return':>8}"
          f"{'maxDD':>7}{'trades':>7}{'win%':>7}{'avgW%':>7}{'avgL%':>8}{'missed':>7}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--years', type=int, default=3, help='years of history to test')
    ap.add_argument('--slots', type=int, default=config.DOUBLE_BOTTOM_MAX_SLOTS)
    ap.add_argument('--target', type=float, default=config.DOUBLE_BOTTOM_TARGET_PCT)
    ap.add_argument('--hold', type=int, default=config.DOUBLE_BOTTOM_TIME_STOP_DAYS)
    ap.add_argument('--stocks', type=int, help='limit universe size (for a quick run)')
    ap.add_argument('--by-year', action='store_true', help='segment the result by year')
    ap.add_argument('--refresh', action='store_true', help='refetch candles / rebuild table')
    args = ap.parse_args()

    # find_exit() reads the time stop from config; --hold overrides it for this run only.
    config.DOUBLE_BOTTOM_TIME_STOP_DAYS = args.hold

    data = fetch_candles(args.years, args.stocks, args.refresh)
    if not data:
        print("No candle data available")
        sys.exit(1)
    rows = build_table(data, args.refresh)

    all_dates = sorted({c['date'] for cd in data.values() for c in cd})
    end = all_dates[-1]
    horizon = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=args.years * 365)
               ).strftime('%Y-%m-%d')
    tail = '2099-01-01'

    print(f"\n₹{START_CAPITAL:,.0f} start | {args.slots} slots "
          f"(₹{START_CAPITAL/args.slots:,.0f}/position) | target +{args.target:.0f}% | "
          f"stop {config.DOUBLE_BOTTOM_STOP_ATR_MULT:.1f}xATR on close | hold {args.hold}d | "
          f"costs {COST_PCT}% + ₹{DP_FEE:.0f}/sell")
    print(f"universe {len(data)} F&O stocks | 1 new trade/day, best support strength")
    print('=' * len(HEADER))
    print(HEADER)
    print('-' * len(HEADER))

    if args.by_year:
        last = datetime.strptime(end, '%Y-%m-%d')
        bounds = [(last - timedelta(days=365 * (k + 1)),
                   last - timedelta(days=365 * k)) for k in range(args.years)][::-1]
        for n, (lo_dt, hi_dt) in enumerate(bounds):
            lo = lo_dt.strftime('%Y-%m-%d')
            # Most recent bucket runs to the end of the data, so it matches the FULL row
            # instead of dropping the final session.
            hi = tail if n == len(bounds) - 1 else hi_dt.strftime('%Y-%m-%d')
            perf, mkt = run_period(rows, data, all_dates, lo, hi, args.slots,
                                   args.target, args.hold)
            if perf:
                label = f"{lo} -> {'now' if hi == tail else hi[:7]}"
                print_row(label, perf, mkt)
        print('-' * len(HEADER))

    perf, mkt = run_period(rows, data, all_dates, horizon, tail, args.slots,
                           args.target, args.hold)
    print_row(f"FULL {args.years}y", perf, mkt)
    print('=' * len(HEADER))

    if perf:
        print(f"\nCAGR {perf['cagr']:.1f}%  |  max drawdown {perf['mdd']:.1f}%  |  "
              f"longest underwater {perf['underwater']} trading days  |  "
              f"worst trade {perf['worst']:.1f}%")
        print(f"{perf['missed']} signal(s) skipped for lack of a free slot — "
              f"more capital or more slots would have taken them.")
        gap_note = (f", worst {perf['worst_gap']:+.2f}%, {perf['gaps_at_target']} of them "
                    f"still at or above +{args.target:.0f}%" if perf['gaps'] else "")
        print(f"Arming: {perf['armed']} of {perf['n']} trades reached the +{args.target:.0f}% "
              f"lock; {perf['armed_at_target']} finished at or above it and "
              f"{perf['armed_losses']} turned into a loss. "
              f"{perf['gaps']} gapped through the lock overnight{gap_note}.")
        print("\nRegime note: compare the return column against the market-median column, "
              "not against zero.\nOn de-biased entries this strategy beats a FLAT market "
              "and loses to a rising one: the trailing\nexit takes ~6-8% and stands aside "
              "while the median stock compounds. A sustained DOWNTREND has\nnever been "
              "tested; no such year exists in the data, and the SMA trend gate is the only "
              "thing\nstanding between this strategy and one.")
        print("Both columns are inflated by survivorship — the universe is TODAY's F&O list "
              "replayed over\nhistory. See DOUBLE_BOTTOM_BACKTEST_AUDIT.md before trusting "
              "either number.")


if __name__ == '__main__':
    main()
