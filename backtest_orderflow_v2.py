#!/usr/bin/env python3
"""
Order Flow Alert Backtest v2 — Iterative parameter sweep.

Goals:
  1. Parse ALL alerts from order_flow_monitor.log (Apr 16 + 17)
  2. Tag each alert with its signal composition
  3. Fetch 1-min candles from Kite (cached to avoid repeated API calls)
  4. Sweep parameter combinations:
       - Signal filter (what alerts qualify)
       - Score threshold
       - Trailing stop %
       - Fixed profit target %
       - Max hold time (minutes)
       - Time-of-day window
  5. Report each combination's metrics: win rate, avg P&L, expectancy, trade count

Usage:
    python backtest_orderflow_v2.py
"""

import json
import os
import re
import time
import logging
from datetime import datetime, date, timedelta, time as dt_time
from itertools import product
from typing import Dict, List, Optional, Tuple

from kiteconnect import KiteConnect
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────

LOG_FILE       = 'logs/order_flow_monitor.log'
TOKEN_FILE     = 'data/all_instrument_tokens.json'
CANDLE_CACHE   = 'data/backtest_candle_cache.json'   # avoid re-fetching
BACKTEST_DATES = [date(2026, 4, 16), date(2026, 4, 17)]

# ── Log parsing ───────────────────────────────────────────────────────────────

ALERT_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - (?:__main__|order_flow_monitor) - INFO - '
    r'(BEARISH|BULLISH): (\w[\w\-]*) score=(\d+) — \S+ \((.+)\)'
)

def parse_all_alerts(log_file: str, target_dates: List[date]) -> List[dict]:
    """
    Parse ALL BEARISH/BULLISH alerts from log without any filter.
    Tag each with signal components for later filtering.
    """
    alerts = []
    date_strs = {str(d) for d in target_dates}

    with open(log_file) as f:
        for line in f:
            m = ALERT_RE.match(line)
            if not m:
                continue
            ts_str, direction, symbol, score, reasons = m.groups()
            # skip synthetic test entries
            if symbol in ('TESTSTOCK', 'BULLSTOCK'):
                continue
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
            if str(ts.date()) not in date_strs:
                continue

            # Tag signal components
            has_cash_flow_bear = bool(re.search(r'5m flow -[\d%]', reasons))
            has_cash_flow_bull = bool(re.search(r'5m flow \+[\d%]', reasons))
            has_cash_flow      = has_cash_flow_bear or has_cash_flow_bull
            directional_cash   = (
                (direction == 'BEARISH' and has_cash_flow_bear) or
                (direction == 'BULLISH' and has_cash_flow_bull)
            )
            has_velocity   = bool(re.search(r'vel ₹[1-9]', reasons))
            has_fut_bai    = 'FUT BAI' in reasons
            has_fut_flow   = 'FUT 5m' in reasons
            has_basis      = 'basis' in reasons
            has_bai_shift  = 'BAI shift' in reasons
            has_l1_shrink  = 'L1 bid' in reasons
            has_bai_abs    = bool(re.search(r'BAI -0\.|BAI 0\.', reasons)) and 'FUT BAI' not in reasons.split('BAI')[0]

            # Recompute score under new rules:
            # - L1 shrink removed (was 1pt; backtest shows 33% win rate = loser signal)
            # - FUT 5m restored only for liquid futures (leave as-is from log since we can't
            #   know fut_tick_count; treat presence of FUT 5m as a good signal)
            new_score = int(score)
            if has_l1_shrink:
                new_score = max(0, new_score - 1)  # remove L1 shrink point

            alerts.append({
                'ts':               ts,
                'direction':        direction,
                'symbol':           symbol,
                'score':            int(score),
                'new_score':        new_score,
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

    logger.info(f"Parsed {len(alerts)} total alerts across {target_dates}")
    return alerts


# ── Kite helpers ──────────────────────────────────────────────────────────────

def load_token_map(token_file: str) -> Dict[str, int]:
    with open(token_file) as f:
        return json.load(f)   # {symbol: token}


def fetch_all_candles(kite: KiteConnect, alerts: List[dict],
                      token_map: Dict[str, int]) -> Dict[str, List[dict]]:
    """
    Fetch 1-min candles for each unique (symbol, date) pair.
    Cache to disk to avoid re-fetching across runs.
    Returns {"{symbol}_{date}": [candles]}
    """
    # Load cache
    cache = {}
    if os.path.exists(CANDLE_CACHE):
        try:
            with open(CANDLE_CACHE) as f:
                cache = json.load(f)
            logger.info(f"Loaded {len(cache)} cached candle series")
        except Exception:
            cache = {}

    # Determine which keys we need
    needed = set()
    for a in alerts:
        key = f"{a['symbol']}_{a['ts'].date()}"
        needed.add((a['symbol'], a['ts'].date(), key))

    market_open  = datetime.min.replace(hour=9, minute=15)
    market_close = datetime.min.replace(hour=15, minute=31)

    newly_fetched = 0
    for symbol, day, key in sorted(needed):
        if key in cache:
            continue
        token = token_map.get(symbol)
        if not token:
            logger.warning(f"No token for {symbol}")
            cache[key] = []
            continue

        from_dt = datetime.combine(day, dt_time(9, 15))
        to_dt   = datetime.combine(day, dt_time(15, 30))
        try:
            raw = kite.historical_data(
                instrument_token=token,
                from_date=from_dt,
                to_date=to_dt,
                interval='minute',
                continuous=False,
                oi=False,
            )
            # Serialise datetimes for JSON
            serialised = []
            for c in raw:
                serialised.append({
                    'date':   c['date'].strftime('%Y-%m-%d %H:%M:%S'),
                    'open':   c['open'],
                    'high':   c['high'],
                    'low':    c['low'],
                    'close':  c['close'],
                    'volume': c['volume'],
                })
            cache[key] = serialised
            newly_fetched += 1
            logger.info(f"Fetched {len(serialised)} candles for {symbol} on {day}")
        except Exception as e:
            logger.warning(f"Failed to fetch {symbol} {day}: {e}")
            cache[key] = []
        time.sleep(0.25)

    if newly_fetched:
        with open(CANDLE_CACHE, 'w') as f:
            json.dump(cache, f)
        logger.info(f"Saved {newly_fetched} new series to cache")

    # Deserialise dates back to datetime for simulation
    result = {}
    for key, candles in cache.items():
        result[key] = [
            {**c, 'date': datetime.strptime(c['date'], '%Y-%m-%d %H:%M:%S')}
            for c in candles
        ]
    return result


# ── Simulation ────────────────────────────────────────────────────────────────

def get_candles_from(all_candles: List[dict], alert_ts: datetime,
                     max_hold_minutes: int) -> List[dict]:
    """
    Return candles starting at or after alert_ts, up to max_hold_minutes.
    Uses the next full candle after alert_ts (entry on close of first candle).
    """
    start = alert_ts
    end   = alert_ts + timedelta(minutes=max_hold_minutes)
    market_close = alert_ts.replace(hour=15, minute=30, second=0, microsecond=0)
    end = min(end, market_close)

    return [c for c in all_candles
            if c['date'] >= start and c['date'] <= end]


def simulate_trade(candles: List[dict], direction: str,
                   trail_pct: float, target_pct: float) -> Optional[dict]:
    """
    Simulate one trade.
    - Entry: close of first candle
    - Exit: trailing stop OR fixed target OR last candle (time limit / market close)
    trail_pct=0 means no trailing stop (only target or time exit).
    target_pct=0 means no fixed target (only trailing stop or time exit).
    """
    if not candles:
        return None
    entry = candles[0]['close']
    if entry <= 0:
        return None

    trail_ref = entry
    stop      = None

    for i, c in enumerate(candles):
        price = c['close']

        if direction == 'BULLISH':
            if price > trail_ref:
                trail_ref = price
            if trail_pct > 0:
                stop = trail_ref * (1 - trail_pct)
            # Check fixed target first
            if target_pct > 0:
                pnl = (price - entry) / entry
                if pnl >= target_pct:
                    return _result(entry, price, direction, i, 'target', c['date'], trail_ref)
            # Trailing stop
            if trail_pct > 0 and i > 0 and price <= stop:
                return _result(entry, price, direction, i, 'trail_stop', c['date'], trail_ref)

        else:  # BEARISH (short)
            if price < trail_ref:
                trail_ref = price
            if trail_pct > 0:
                stop = trail_ref * (1 + trail_pct)
            if target_pct > 0:
                pnl = (entry - price) / entry
                if pnl >= target_pct:
                    return _result(entry, price, direction, i, 'target', c['date'], trail_ref)
            if trail_pct > 0 and i > 0 and price >= stop:
                return _result(entry, price, direction, i, 'trail_stop', c['date'], trail_ref)

    # Time / market close exit
    last = candles[-1]
    return _result(entry, last['close'], direction, len(candles), 'time_exit', last['date'], trail_ref)


def _result(entry, exit_p, direction, hold, reason, exit_time, peak) -> dict:
    if direction == 'BULLISH':
        pnl = (exit_p - entry) / entry * 100
    else:
        pnl = (entry - exit_p) / entry * 100
    return {
        'entry_price':  entry,
        'exit_price':   exit_p,
        'pnl_pct':      round(pnl, 3),
        'hold_minutes': hold,
        'exit_reason':  reason,
        'exit_time':    exit_time,
        'peak_price':   peak,
    }


# ── Parameter sweep ───────────────────────────────────────────────────────────

# ── Market regime detection (from alert batch within ±3 min window) ──────────

def tag_market_regime(alerts: List[dict]) -> List[dict]:
    """
    For each alert, compute the market regime at that moment:
    Look at all alerts fired within ±3 minutes and count bullish vs bearish.
    - 'bullish'  if bull_count > bear_count * 1.5
    - 'bearish'  if bear_count > bull_count * 1.5
    - 'neutral'  otherwise
    This approximates what the live monitor would see from cum_delta distribution.
    """
    from datetime import timedelta
    for a in alerts:
        window_start = a['ts'] - timedelta(minutes=3)
        window_end   = a['ts'] + timedelta(minutes=3)
        nearby = [x for x in alerts
                  if window_start <= x['ts'] <= window_end and x is not a
                  and x['ts'].date() == a['ts'].date()]
        bulls = sum(1 for x in nearby if x['direction'] == 'BULLISH')
        bears = sum(1 for x in nearby if x['direction'] == 'BEARISH')
        total = bulls + bears
        if total == 0:
            a['market_regime'] = 'neutral'
        elif bulls > bears * 1.5:
            a['market_regime'] = 'bullish'
        elif bears > bulls * 1.5:
            a['market_regime'] = 'bearish'
        else:
            a['market_regime'] = 'neutral'
    return alerts


# Signal filter presets: (name, filter_fn)
SIGNAL_FILTERS = [
    ('all_alerts',        lambda a: True),
    ('directional_cash',  lambda a: a['directional_cash']),
    ('cash_or_vel',       lambda a: a['directional_cash'] or a['has_velocity']),
    ('cash_AND_bai',      lambda a: a['directional_cash'] and (a['has_fut_bai'] or a['has_bai_shift'])),
    ('high_quality',      lambda a: a['directional_cash'] and (a['has_fut_bai'] or a['has_basis'])),
    ('score5plus',        lambda a: a['score'] >= 5),
    ('score6plus',        lambda a: a['score'] >= 6),
    ('new_score4plus',    lambda a: a['new_score'] >= 4 and a['directional_cash']),
    # Regime-aligned: only fire when alert direction matches the broader flow
    ('regime_aligned',    lambda a: (
        a['directional_cash'] and (a['has_fut_bai'] or a['has_basis']) and
        (a['market_regime'] == 'neutral' or a['market_regime'] == (
            'bearish' if a['direction'] == 'BEARISH' else 'bullish'))
    )),
    # Regime-aligned OR counter-trend only if score >= 6
    ('regime_or_high_score', lambda a: (
        a['directional_cash'] and (a['has_fut_bai'] or a['has_basis']) and
        (a['market_regime'] == 'neutral' or
         a['market_regime'] == ('bearish' if a['direction'] == 'BEARISH' else 'bullish') or
         a['score'] >= 6)
    )),
    ('no_bai_shift',      lambda a: a['directional_cash'] and a['has_fut_bai'] and not a['has_bai_shift']),
    # Simulate new scoring: no L1 shrink, min price ₹50
    ('new_code_sim',      lambda a: (
        a['directional_cash'] and (a['has_fut_bai'] or a['has_basis']) and
        a['new_score'] >= 4 and
        # proxy for price >= 50: exclude IDEA (₹9) — mark by checking score anomalies
        a['symbol'] not in ('IDEA', 'YESBANK')   # ₹9-20 range stocks
    )),
    # New code + regime aligned
    ('new_code_regime',   lambda a: (
        a['directional_cash'] and (a['has_fut_bai'] or a['has_basis']) and
        a['new_score'] >= 4 and
        a['symbol'] not in ('IDEA', 'YESBANK') and
        (a['market_regime'] == 'neutral' or
         a['market_regime'] == ('bearish' if a['direction'] == 'BEARISH' else 'bullish') or
         a['score'] >= 6)
    )),
]

# Time-of-day windows (start_time, label)
TIME_WINDOWS = [
    (dt_time(9, 20),  'all_day'),
    (dt_time(10, 0),  'after_10am'),
    (dt_time(11, 0),  'after_11am'),
]

# Exit strategies: (trail_pct, target_pct, max_hold_minutes)
EXIT_STRATEGIES = [
    (0.003, 0.0,  120, 'trail0.3%'),
    (0.005, 0.0,  120, 'trail0.5%'),
    (0.005, 0.0,   60, 'trail0.5%_60m'),
    (0.008, 0.0,  120, 'trail0.8%'),
    (0.010, 0.0,  120, 'trail1.0%'),
    (0.005, 0.005, 60, 'trail0.5%_tgt0.5%'),
    (0.005, 0.010, 90, 'trail0.5%_tgt1%'),
    (0.003, 0.008, 60, 'trail0.3%_tgt0.8%'),
    (0.0,   0.005, 60, 'tgt0.5%_only'),
    (0.0,   0.010, 90, 'tgt1%_only'),
]

MIN_TRADES = 5  # skip combinations with too few trades to be meaningful


def run_sweep(alerts: List[dict], candle_map: Dict[str, List[dict]]) -> List[dict]:
    """Run full parameter sweep. Returns list of result dicts sorted by expectancy."""
    all_results = []

    for (filter_name, filter_fn), (min_time, time_label), \
        (trail_pct, target_pct, max_hold, exit_label) in product(
            SIGNAL_FILTERS, TIME_WINDOWS, EXIT_STRATEGIES):

        trades = []
        for alert in alerts:
            if not filter_fn(alert):
                continue
            if alert['ts'].time() < min_time:
                continue

            key = f"{alert['symbol']}_{alert['ts'].date()}"
            all_candles = candle_map.get(key, [])
            candles = get_candles_from(all_candles, alert['ts'], max_hold)
            if not candles:
                continue

            sim = simulate_trade(candles, alert['direction'], trail_pct, target_pct)
            if sim:
                trades.append({**alert, **sim})

        if len(trades) < MIN_TRADES:
            continue

        winners = [t for t in trades if t['pnl_pct'] > 0]
        losers  = [t for t in trades if t['pnl_pct'] <= 0]
        win_rate    = len(winners) / len(trades) * 100
        avg_win     = sum(t['pnl_pct'] for t in winners) / len(winners) if winners else 0
        avg_loss    = sum(t['pnl_pct'] for t in losers)  / len(losers)  if losers  else 0
        avg_all     = sum(t['pnl_pct'] for t in trades)  / len(trades)
        # Expectancy = avg_win * win_rate - abs(avg_loss) * loss_rate
        expectancy  = avg_all   # equivalent: E[P&L per trade]

        all_results.append({
            'filter':      filter_name,
            'time_window': time_label,
            'exit':        exit_label,
            'n_trades':    len(trades),
            'win_rate':    round(win_rate, 1),
            'avg_win':     round(avg_win, 3),
            'avg_loss':    round(avg_loss, 3),
            'avg_all':     round(avg_all, 3),
            'expectancy':  round(expectancy, 3),
            'trades':      trades,
        })

    all_results.sort(key=lambda x: x['expectancy'], reverse=True)
    return all_results


def print_sweep_summary(results: List[dict], top_n: int = 20):
    """Print top-N combinations and then drill into the best one."""
    print("\n" + "="*110)
    print(f"ORDER FLOW BACKTEST v2 — Parameter Sweep  |  Dates: {BACKTEST_DATES}")
    print("="*110)
    print(f"\nTOP {top_n} CONFIGURATIONS (by avg P&L / trade, min {MIN_TRADES} trades):\n")
    print(f"{'#':3s} {'Filter':20s} {'Time':12s} {'Exit':26s} {'N':>5s} {'WinRate':>8s} "
          f"{'AvgWin':>8s} {'AvgLoss':>9s} {'AvgAll':>8s}")
    print("-"*110)

    for i, r in enumerate(results[:top_n], 1):
        print(
            f"{i:3d} {r['filter']:20s} {r['time_window']:12s} {r['exit']:26s} "
            f"{r['n_trades']:5d} {r['win_rate']:7.1f}% "
            f"{r['avg_win']:+8.3f}% {r['avg_loss']:+9.3f}% {r['avg_all']:+8.3f}%"
        )

    if not results:
        print("No results.")
        return

    print("\n" + "="*110)
    print("WORST 10 CONFIGURATIONS:\n")
    print(f"{'#':3s} {'Filter':20s} {'Time':12s} {'Exit':26s} {'N':>5s} {'WinRate':>8s} "
          f"{'AvgWin':>8s} {'AvgLoss':>9s} {'AvgAll':>8s}")
    print("-"*110)
    for i, r in enumerate(results[-10:], len(results)-9):
        print(
            f"{i:3d} {r['filter']:20s} {r['time_window']:12s} {r['exit']:26s} "
            f"{r['n_trades']:5d} {r['win_rate']:7.1f}% "
            f"{r['avg_win']:+8.3f}% {r['avg_loss']:+9.3f}% {r['avg_all']:+8.3f}%"
        )

    # Drill into the best config
    best = results[0]
    print(f"\n\n{'='*110}")
    print(f"BEST CONFIG DRILL-DOWN: filter={best['filter']}  time={best['time_window']}  exit={best['exit']}")
    print(f"  Trades: {best['n_trades']}  Win rate: {best['win_rate']}%  "
          f"Avg P&L: {best['avg_all']:+.3f}%  "
          f"Avg win: {best['avg_win']:+.3f}%  Avg loss: {best['avg_loss']:+.3f}%")
    print("="*110)
    print(f"\n{'Date':12s} {'Time':7s} {'Dir':8s} {'Symbol':12s} {'Score':5s} "
          f"{'Entry':9s} {'Exit':9s} {'P&L':8s} {'Hold':6s} {'ExitType':12s} Signals")
    print("-"*110)

    by_date: Dict[str, list] = {}
    for t in best['trades']:
        d = str(t['ts'].date())
        by_date.setdefault(d, []).append(t)

    for d, day_trades in sorted(by_date.items()):
        wins  = [t for t in day_trades if t['pnl_pct'] > 0]
        total = len(day_trades)
        avg   = sum(t['pnl_pct'] for t in day_trades) / total
        print(f"\n── {d} ({len(wins)}/{total} wins | avg P&L: {avg:+.3f}%)")
        for t in sorted(day_trades, key=lambda x: x['ts']):
            pnl_marker = '✓' if t['pnl_pct'] > 0 else '✗'
            print(
                f"{str(t['ts'].date()):12s} {t['ts'].strftime('%H:%M'):7s} "
                f"{t['direction']:8s} {t['symbol']:12s} {t['score']:5d} "
                f"{t['entry_price']:9.2f} {t['exit_price']:9.2f} "
                f"{t['pnl_pct']:+7.3f}% {t['hold_minutes']:5d}m "
                f"{t['exit_reason']:12s} {pnl_marker} {t['reasons']}"
            )

    # Signal analysis: which signals correlate with winners vs losers
    print(f"\n\n{'='*110}")
    print("SIGNAL QUALITY ANALYSIS — best config:")
    print("(What % of trades with each signal were winners?)\n")

    all_trades = best['trades']
    signals = [
        ('has_cash_flow', 'cash_flow'),
        ('directional_cash', 'directional_cash'),
        ('has_velocity', 'velocity'),
        ('has_fut_bai', 'fut_bai'),
        ('has_basis', 'basis'),
        ('has_l1_shrink', 'l1_shrink'),
        ('has_bai_shift', 'bai_shift'),
        ('has_fut_flow', 'fut_flow'),
    ]
    for field, label in signals:
        with_signal = [t for t in all_trades if t.get(field)]
        without     = [t for t in all_trades if not t.get(field)]
        if len(with_signal) >= 3:
            wr = sum(1 for t in with_signal if t['pnl_pct'] > 0) / len(with_signal) * 100
            avg = sum(t['pnl_pct'] for t in with_signal) / len(with_signal)
            print(f"  {label:20s}: n={len(with_signal):3d}  win={wr:5.1f}%  avg={avg:+.3f}%")
        if len(without) >= 3:
            wr = sum(1 for t in without if t['pnl_pct'] > 0) / len(without) * 100
            avg = sum(t['pnl_pct'] for t in without) / len(without)
            print(f"  no_{label:17s}: n={len(without):3d}  win={wr:5.1f}%  avg={avg:+.3f}%")
        if len(with_signal) >= 3 or len(without) >= 3:
            print()


def print_per_stock_stats(results: List[dict]):
    """Show per-stock hit rate across the best config."""
    if not results:
        return
    best = results[0]
    trades = best['trades']
    by_symbol: Dict[str, list] = {}
    for t in trades:
        by_symbol.setdefault(t['symbol'], []).append(t)

    print(f"\n\n{'='*110}")
    print(f"PER-SYMBOL STATS (best config: {best['filter']} / {best['time_window']} / {best['exit']}):\n")
    print(f"{'Symbol':14s} {'N':>4s} {'Wins':>5s} {'WinRate':>8s} {'AvgP&L':>9s} {'Trades'}")
    print("-"*70)
    rows = []
    for sym, sym_trades in by_symbol.items():
        wins = sum(1 for t in sym_trades if t['pnl_pct'] > 0)
        wr   = wins / len(sym_trades) * 100
        avg  = sum(t['pnl_pct'] for t in sym_trades) / len(sym_trades)
        rows.append((sym, len(sym_trades), wins, wr, avg))
    rows.sort(key=lambda x: x[4], reverse=True)
    for sym, n, wins, wr, avg in rows:
        print(f"{sym:14s} {n:4d} {wins:5d} {wr:7.1f}% {avg:+8.3f}%")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    token_map = load_token_map(TOKEN_FILE)
    alerts    = parse_all_alerts(LOG_FILE, BACKTEST_DATES)

    logger.info(f"Total alerts to backtest: {len(alerts)}")
    logger.info(f"  with directional cash flow: {sum(1 for a in alerts if a['directional_cash'])}")
    logger.info(f"  score >= 5: {sum(1 for a in alerts if a['score'] >= 5)}")
    logger.info(f"  score >= 6: {sum(1 for a in alerts if a['score'] >= 6)}")

    # Tag market regime per alert
    alerts = tag_market_regime(alerts)
    regime_counts = {}
    for a in alerts:
        k = (a['direction'], a['market_regime'])
        regime_counts[k] = regime_counts.get(k, 0) + 1
    for k, v in sorted(regime_counts.items()):
        logger.info(f"  {k[0]:8s} in {k[1]:8s} regime: {v}")

    # Fetch/cache all minute candles
    logger.info("Fetching/loading candle data...")
    candle_map = fetch_all_candles(kite, alerts, token_map)

    # Run sweep
    logger.info("Running parameter sweep...")
    results = run_sweep(alerts, candle_map)

    logger.info(f"Sweep complete: {len(results)} valid combinations")

    # Print output
    print_sweep_summary(results, top_n=25)
    print_per_stock_stats(results)

    print(f"\n\nDone. Total combinations evaluated: {len(results)}")


if __name__ == '__main__':
    main()
