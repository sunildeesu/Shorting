#!/usr/bin/env python3
"""
Overnight Bounce Backtest — 1 Month.

Strategy (discovered from signal analysis):
  Stocks that close WEAK (near day low, below VWAP) bounce at 9:25 AM next day.
  This is NOT a momentum trade — it is a MEAN-REVERSION overnight bounce.

  Signal analysis result (30 days, 73 stocks, 2129 valid trades):
    close_strength < 0.40 (closing in bottom 40% of day range) → 92.5% win, +1.04% avg
    vwap_gap < -0.50% (closing 0.5%+ below VWAP) → 93.5% win, +1.60% avg

  Why this works:
    - Stocks sold down during the day are oversold at close
    - Overnight: short covering, index rebalancing, retail buying the dip
    - Result: gap-up at 9:25 AM open

Trade:
  - Entry: 3:29 PM close (last minute candle before market close)
  - Exit: 9:25 AM next trading day
  - Charges: 0.04% round trip

Usage:
    python backtest_overnight_1month.py
"""

import json
import os
import time
import logging
from datetime import date, datetime, timedelta, time as dt_time
from itertools import product
from typing import Dict, List, Optional, Tuple

from kiteconnect import KiteConnect
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

CANDLE_CACHE   = 'data/backtest_overnight_1month_cache.json'
TOKEN_FILE     = 'data/all_instrument_tokens.json'

ROUND_TRIP_CHARGES = 0.0004   # 0.04% round trip (futures)
MIN_PRICE          = 100.0    # skip small stocks
EXIT_TIME          = dt_time(9, 25)   # exit at 9:25 AM next day

# NSE trading days from results_cache (30+ days to give us a full month of usable days)
NSE_TRADING_DAYS = sorted([
    date(2026, 3, 28),
    date(2026, 4, 8),  date(2026, 4, 9),  date(2026, 4, 10), date(2026, 4, 11),
    date(2026, 4, 13), date(2026, 4, 14), date(2026, 4, 15),
    date(2026, 4, 16), date(2026, 4, 17), date(2026, 4, 18),
    date(2026, 4, 20), date(2026, 4, 21), date(2026, 4, 22),
    date(2026, 4, 23), date(2026, 4, 24), date(2026, 4, 25),
    date(2026, 4, 26), date(2026, 4, 27), date(2026, 4, 28),
    date(2026, 4, 29), date(2026, 4, 30),
    date(2026, 5, 2),  date(2026, 5, 4),  date(2026, 5, 5),
    date(2026, 5, 6),  date(2026, 5, 7),  date(2026, 5, 8),
    date(2026, 5, 9),  date(2026, 5, 11), date(2026, 5, 12),
    date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15),
    date(2026, 5, 19), date(2026, 5, 20), date(2026, 5, 21),
    date(2026, 5, 22), date(2026, 5, 25), date(2026, 5, 26),
    date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29),
])

def next_trading_day(d: date) -> Optional[date]:
    for td in NSE_TRADING_DAYS:
        if td > d:
            return td
    return None

# Use 30 days as signal days (need a next-day for each)
# Pick the last 30 from the list that have a known next day
SIGNAL_DAYS = [d for d in NSE_TRADING_DAYS if next_trading_day(d) is not None][-30:]

logger.info(f"Signal days: {SIGNAL_DAYS[0]} → {SIGNAL_DAYS[-1]} ({len(SIGNAL_DAYS)} days)")

# ── Liquid F&O stocks — broad universe for institutional flow ─────────────────

FOCUS_STOCKS = [
    # Index heavyweights
    'RELIANCE', 'HDFCBANK', 'ICICIBANK', 'INFY', 'TCS', 'AXISBANK', 'KOTAKBANK',
    'SBIN', 'BAJFINANCE', 'BHARTIARTL', 'WIPRO', 'TECHM', 'LTIM',
    # Banking / Finance
    'BAJAJFINSV', 'SHRIRAMFIN', 'CHOLAFIN', 'MUTHOOTFIN', 'PNB', 'CANBK',
    'FEDERALBNK', 'BANDHANBNK', 'RBLBANK', 'SBICARD', 'ANGELONE',
    # Pharma / Consumer
    'SUNPHARMA', 'DRREDDY', 'CIPLA', 'DIVISLAB', 'HINDUNILVR', 'ITC', 'TITAN',
    'TRENT', 'DMART', 'NESTLEIND',
    # IT / Capital goods
    'PERSISTENT', 'COFORGE', 'KPITTECH', 'ABB', 'SIEMENS', 'BHEL',
    'HAL', 'BEL', 'MAZDOCK', 'TIINDIA',
    # Metals / Energy
    'TATASTEEL', 'HINDALCO', 'JSWSTEEL', 'ONGC', 'NTPC', 'POWERGRID',
    'TATAPOWER', 'ADANIPORTS', 'ADANIENT', 'VEDL', 'SAIL', 'NMDC',
    # Mid-cap active
    'PNBHOUSING', 'POLICYBZR', 'KAYNES', 'PAGEIND', 'PRESTIGE',
    'MPHASIS', 'OFSS', 'SONACOMS', 'SOLARINDS', 'MANKIND',
    # Others from alert history
    'IRFC', 'NHPC', 'RVNL', 'RECLTD', 'OIL', 'UPL', 'AMBER',
]

# ── Candle fetching ───────────────────────────────────────────────────────────

def load_token_map() -> Dict[str, int]:
    with open(TOKEN_FILE) as f:
        return json.load(f)


def fetch_candles(kite: KiteConnect, token_map: Dict[str, int]) -> Dict[str, List[dict]]:
    """
    Fetch 1-min candles for FOCUS_STOCKS × (SIGNAL_DAYS + their next days).
    Cache to disk. Returns {"{SYMBOL}_{DATE}": [candles]}.
    """
    cache = {}
    if os.path.exists(CANDLE_CACHE):
        try:
            with open(CANDLE_CACHE) as f:
                cache = json.load(f)
            logger.info(f"Loaded {len(cache)} cached series")
        except Exception:
            cache = {}

    # All days we need: signal days + next days
    all_days = set(SIGNAL_DAYS)
    for d in SIGNAL_DAYS:
        nd = next_trading_day(d)
        if nd:
            all_days.add(nd)

    needed = [(sym, day, f"{sym}_{day}") for sym in FOCUS_STOCKS for day in sorted(all_days)]
    to_fetch = [(sym, day, key) for sym, day, key in needed if key not in cache]
    logger.info(f"Need to fetch {len(to_fetch)} series (cached: {len(needed) - len(to_fetch)})")

    for i, (symbol, day, key) in enumerate(to_fetch):
        token = token_map.get(symbol)
        if not token:
            cache[key] = []
            continue

        from_dt = datetime.combine(day, dt_time(9, 15))
        to_dt   = datetime.combine(day, dt_time(15, 31))
        try:
            raw = kite.historical_data(
                instrument_token=token,
                from_date=from_dt,
                to_date=to_dt,
                interval='minute',
                continuous=False,
                oi=False,
            )
            cache[key] = [
                {'date': c['date'].strftime('%Y-%m-%d %H:%M:%S'),
                 'open': c['open'], 'high': c['high'],
                 'low': c['low'], 'close': c['close'], 'volume': c['volume']}
                for c in raw
            ]
            if (i + 1) % 100 == 0 or len(to_fetch) < 20:
                logger.info(f"  [{i+1}/{len(to_fetch)}] {symbol} {day}: {len(cache[key])} candles")
        except Exception as e:
            logger.warning(f"Failed {symbol} {day}: {e}")
            cache[key] = []
        time.sleep(0.25)

    if to_fetch:
        with open(CANDLE_CACHE, 'w') as f:
            json.dump(cache, f)
        logger.info(f"Cache saved ({len(cache)} series)")

    # Deserialise dates
    result = {}
    for key, candles in cache.items():
        result[key] = [
            {**c, 'date': datetime.strptime(c['date'], '%Y-%m-%d %H:%M:%S')}
            for c in candles
        ]
    return result


# ── Proxy signal computation ───────────────────────────────────────────────────

def compute_closing_window_signal(candles: List[dict],
                                   window_start_hour: int,
                                   window_start_minute: int = 0) -> Optional[dict]:
    """
    Compute institutional buying proxy for the closing window using multiple signals.

    Signals:
      close_strength  : (close - day_low) / (day_high - day_low)
                        > 0.70 = closing in top 30% of day range = strong close
      vwap_gap_pct    : (close - vwap) / vwap × 100
                        positive = closing above VWAP = buyers dominating
      window_chg_pct  : price change % during the window (must be positive for BULLISH)
      vol_ratio       : window avg volume / pre-window avg volume
                        ≥ 1.0 = at least normal volume in closing window
      window_vol      : raw volume in the window (minimum liquidity check)
    """
    window_start = dt_time(window_start_hour, window_start_minute)
    window_end   = dt_time(15, 15)

    # Closing window candles
    window = [c for c in candles
              if window_start <= c['date'].time() <= window_end]
    if len(window) < 3:
        return None

    # Minimum liquidity: window must have traded at least 500 shares
    window_vol = sum(c['volume'] for c in window)
    if window_vol < 500:
        return None

    # Closing price (last candle in window)
    close = window[-1]['close']
    if close <= 0:
        return None

    # Full-day range (for close_strength)
    all_highs = [c['high'] for c in candles]
    all_lows  = [c['low']  for c in candles]
    day_high  = max(all_highs)
    day_low   = min(all_lows)
    if day_high == day_low:
        return None
    close_strength = (close - day_low) / (day_high - day_low)

    # VWAP of the full day (volume-weighted)
    total_vol = sum(c['volume'] for c in candles)
    if total_vol == 0:
        return None
    vwap = sum(c['close'] * c['volume'] for c in candles) / total_vol
    vwap_gap_pct = (close - vwap) / vwap * 100

    # Window price change
    window_open  = window[0]['open']
    window_chg_pct = (close - window_open) / window_open * 100 if window_open > 0 else 0

    # Volume ratio: window avg vs pre-window avg (last 20 bars)
    pre_window = [c for c in candles if c['date'].time() < window_start]
    if len(pre_window) < 5:
        return None
    pre_avg_vol  = sum(c['volume'] for c in pre_window[-20:]) / min(20, len(pre_window))
    window_avg_vol = window_vol / len(window)
    vol_ratio = window_avg_vol / pre_avg_vol if pre_avg_vol > 0 else 1.0

    return {
        'close_strength':  round(close_strength, 3),  # 0–1, want > 0.70
        'vwap_gap_pct':    round(vwap_gap_pct, 3),    # want > 0 (above VWAP)
        'window_chg_pct':  round(window_chg_pct, 3),  # want > 0 (rising in window)
        'vol_ratio':       round(vol_ratio, 2),        # want ≥ 1.0 (at least normal vol)
        'window_vol':      window_vol,
        'current_price':   close,
    }


def get_price_at(candles: List[dict], target_time: dt_time,
                  max_age_minutes: int = 10,
                  min_volume: int = 100) -> Optional[float]:
    """
    Return close of last candle at or before target_time that has real volume.
    - max_age_minutes: candle must be within this many minutes of target_time
    - min_volume: candle must have traded at least this many shares (filters phantom candles)
    """
    from datetime import timedelta
    target_dt = datetime.min.replace(
        hour=target_time.hour, minute=target_time.minute)
    cutoff_dt = target_dt - timedelta(minutes=max_age_minutes)
    cutoff_time = dt_time(cutoff_dt.hour, cutoff_dt.minute)

    eligible = [c for c in candles
                if cutoff_time <= c['date'].time() <= target_time
                and c.get('volume', 0) >= min_volume]
    return eligible[-1]['close'] if eligible else None


# ── Parameter sweep ───────────────────────────────────────────────────────────

# Closing window start times to test (hour, minute)
WINDOW_STARTS = [
    (14,  0, '2:00pm'),
    (14, 30, '2:30pm'),
    (15,  0, '3:00pm'),
]

# Close strength MAX (upper bound): closing in BOTTOM X% of day range
# Lower = weaker close = stronger mean-reversion signal
CLOSE_STRENGTH_MAX = [0.20, 0.30, 0.40, 0.50]

# VWAP gap MAX (upper bound): must be closing BELOW VWAP by at least this amount
# More negative = further below VWAP = stronger signal
VWAP_GAP_MAX = [-1.0, -0.5, -0.2, 0.0]

# Minimum price for the stock
MIN_PRICE_THRESHOLDS = [100.0, 200.0, 500.0]

MIN_TRADES = 10

# Market breadth filter: skip signal days where too many stocks are in broad sell-off.
# Broad crash days (macro/news events) show 0% win rate because selling continues next morning.
# This fraction is tested as a sweep parameter below.
BREADTH_FILTERS = [0.60, 0.70, 0.80, None]   # None = no filter


def compute_day_breadth(day: date, precomp_all: Dict[str, dict]) -> float:
    """
    Fraction of stocks that close below VWAP (<-0.2%) on this day.
    Uses 2:30pm signal window for VWAP gap calculation.
    """
    stocks_below = 0
    total = 0
    for sym in FOCUS_STOCKS:
        dk = f"{sym}_{day}"
        pc = precomp_all.get(dk)
        if not pc:
            continue
        sig = pc['sigs'].get('2:30pm') or (list(pc['sigs'].values())[0] if pc['sigs'] else None)
        if not sig:
            continue
        total += 1
        if sig['vwap_gap_pct'] < -0.2:
            stocks_below += 1
    return stocks_below / total if total > 0 else 0.0


def run_sweep(candle_map: Dict[str, List[dict]]) -> Tuple[List[dict], List[dict]]:
    """
    For each parameter combination:
      1. Find all stocks with institutional buying signal in closing window
      2. Enter at EOD close (3:29 PM), exit next day 9:25 AM
      3. Compute stats — cap one trade per (symbol, day) and max 5 appearances per symbol
    Returns (results sorted by avg_net, all_raw_trades).
    """
    total = (len(WINDOW_STARTS) * len(CLOSE_STRENGTH_MAX) * len(VWAP_GAP_MAX)
             * len(MIN_PRICE_THRESHOLDS) * len(BREADTH_FILTERS))
    logger.info(f"Parameter sweep: {total} combinations across {len(SIGNAL_DAYS)} days × {len(FOCUS_STOCKS)} stocks")

    # Pre-compute signals and prices for all (symbol, day) pairs once
    logger.info("Pre-computing signals for all (symbol, day) pairs...")
    precomputed: Dict[str, dict] = {}
    all_raw_trades = []

    for day in SIGNAL_DAYS:
        next_day = next_trading_day(day)
        if not next_day:
            continue
        for sym in FOCUS_STOCKS:
            day_key  = f"{sym}_{day}"
            next_key = f"{sym}_{next_day}"
            day_candles  = candle_map.get(day_key, [])
            next_candles = candle_map.get(next_key, [])
            if len(day_candles) < 30 or not next_candles:
                continue

            # Compute signals for each window start
            sigs = {}
            for wh, wm, wlabel in WINDOW_STARTS:
                sig = compute_closing_window_signal(day_candles, wh, wm)
                if sig:
                    sigs[wlabel] = sig
            if not sigs:
                continue

            # Entry: 3:29 PM close (last 5-min window)
            entry = get_price_at(day_candles, dt_time(15, 29), max_age_minutes=5)
            # Exit: 9:25 AM next day
            exit_ = get_price_at(next_candles, EXIT_TIME, max_age_minutes=5)

            if not entry or not exit_ or entry <= 0:
                continue
            # Skip stale prices (entry == exit = stock didn't trade at these times)
            if abs(entry - exit_) < 0.01:
                continue

            pnl_pct = (exit_ - entry) / entry * 100
            pnl_net = pnl_pct - ROUND_TRIP_CHARGES * 100

            precomputed[day_key] = {
                'symbol':   sym,
                'day':      day,
                'next_day': next_day,
                'entry':    round(entry, 2),
                'exit':     round(exit_, 2),
                'pnl_pct':  round(pnl_pct, 3),
                'pnl_net':  round(pnl_net, 3),
                'sigs':     sigs,
                'price':    entry,
            }
            sig_raw = sigs.get('2:30pm') or list(sigs.values())[0]
            all_raw_trades.append({
                **precomputed[day_key],
                'close_strength': sig_raw['close_strength'],
                'vwap_gap_pct':   sig_raw['vwap_gap_pct'],
                'window_chg_pct': sig_raw['window_chg_pct'],
                'vol_ratio':      sig_raw['vol_ratio'],
            })

    # Remove circuit-stuck stocks: entry price EXACTLY same as previous day (true circuit lock)
    # Circuit stocks trade ONLY at the circuit price — true duplicates have 0.00% change.
    # We allow small moves (up to 0.1%) to avoid removing legitimate low-volatility stocks.
    sym_prev_entry: Dict[str, float] = {}
    circuit_removed = 0
    for dk in sorted(precomputed.keys()):   # sort to process in date order
        pc = precomputed[dk]
        prev = sym_prev_entry.get(pc['symbol'])
        if prev is not None and prev > 0:
            pct_change = abs(pc['entry'] - prev) / prev
            if pct_change < 0.001:   # < 0.1% = genuinely frozen (true circuit/stuck)
                del precomputed[dk]
                circuit_removed += 1
                continue
        sym_prev_entry[pc['symbol']] = pc['entry']
    if circuit_removed:
        logger.info(f"Removed {circuit_removed} circuit/frozen-price entries")

    logger.info(f"Pre-computed {len(precomputed)} valid (symbol, day) pairs")

    # Pre-compute per-day breadth (fraction of stocks below VWAP)
    day_breadth: Dict[str, float] = {}
    for day in SIGNAL_DAYS:
        day_breadth[str(day)] = compute_day_breadth(day, precomputed)
    logger.info("Day breadth (fraction below VWAP -0.2%):")
    for d, b in sorted(day_breadth.items()):
        if b > 0:
            logger.info(f"  {d}: {b:.0%} stocks below VWAP")

    results = []
    for (wh, wm, wlabel), cs_max, vwap_max, min_px, breadth_max in product(
            WINDOW_STARTS, CLOSE_STRENGTH_MAX, VWAP_GAP_MAX, MIN_PRICE_THRESHOLDS, BREADTH_FILTERS):

        trades = []
        sym_count: Dict[str, int] = {}

        for day in SIGNAL_DAYS:
            # Market breadth filter: skip broad crash days
            if breadth_max is not None and day_breadth.get(str(day), 0) > breadth_max:
                continue

            for sym in FOCUS_STOCKS:
                dk = f"{sym}_{day}"
                pc = precomputed.get(dk)
                if not pc:
                    continue

                # Price filter
                if pc['price'] < min_px:
                    continue

                sig = pc['sigs'].get(wlabel)
                if not sig:
                    continue

                # WEAK CLOSE gates (mean-reversion strategy)
                # close_strength BELOW threshold (closing near day lows)
                if sig['close_strength'] > cs_max:
                    continue
                # vwap_gap BELOW threshold (closing below VWAP)
                if sig['vwap_gap_pct'] > vwap_max:
                    continue

                # Cap at 5 per symbol to prevent one stock dominating
                if sym_count.get(sym, 0) >= 5:
                    continue
                sym_count[sym] = sym_count.get(sym, 0) + 1

                trades.append({
                    'symbol':         sym,
                    'day':            day,
                    'next_day':       pc['next_day'],
                    'entry':          pc['entry'],
                    'exit':           pc['exit'],
                    'pnl_pct':        pc['pnl_pct'],
                    'pnl_net':        pc['pnl_net'],
                    'close_strength': sig['close_strength'],
                    'vwap_gap_pct':   sig['vwap_gap_pct'],
                    'window_chg_pct': sig['window_chg_pct'],
                    'vol_ratio':      sig['vol_ratio'],
                    'breadth_filter': breadth_max,
                })

        if len(trades) < MIN_TRADES:
            continue

        winners = [t for t in trades if t['pnl_net'] > 0]
        losers  = [t for t in trades if t['pnl_net'] <= 0]
        win_rate = len(winners) / len(trades) * 100
        avg_win  = sum(t['pnl_net'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pnl_net'] for t in losers)  / len(losers)  if losers  else 0
        avg_net  = sum(t['pnl_net'] for t in trades)  / len(trades)

        results.append({
            'window':       wlabel,
            'cs_max':       cs_max,
            'vwap_max':     vwap_max,
            'min_px':       min_px,
            'breadth_max':  breadth_max,
            'n_trades':     len(trades),
            'win_rate':     round(win_rate, 1),
            'avg_win':      round(avg_win, 3),
            'avg_loss':     round(avg_loss, 3),
            'avg_net':      round(avg_net, 3),
            'trades':    trades,
        })

    results.sort(key=lambda x: (x['avg_net'], x['win_rate']), reverse=True)
    return results, all_raw_trades


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_report(results: List[dict], all_raw_trades: List[dict]):
    charge_pct = ROUND_TRIP_CHARGES * 100

    print("\n" + "="*120)
    print("OVERNIGHT INSTITUTIONAL BUYING BACKTEST — 1 Month")
    print(f"Signal days: {SIGNAL_DAYS[0]} → {SIGNAL_DAYS[-1]}  ({len(SIGNAL_DAYS)} days)")
    print(f"Stocks: {len(FOCUS_STOCKS)}  |  Charges: {charge_pct:.2f}% round trip")
    print(f"Entry: 3:29 PM close  |  Exit: next day 9:25 AM")
    print("="*120)

    if not results:
        print("No valid configurations found (all below MIN_TRADES threshold).")
        return

    above60 = [r for r in results if r['win_rate'] >= 60 and r['avg_net'] > 0]
    above70 = [r for r in results if r['win_rate'] >= 70 and r['avg_net'] > 0]
    print(f"\n  Total configs evaluated: {len(results)}")
    print(f"  Configs ≥60% win AND positive net P&L: {len(above60)}")
    print(f"  Configs ≥70% win AND positive net P&L: {len(above70)}")

    print(f"\nTOP 25 CONFIGURATIONS (by avg net P&L after {charge_pct:.2f}% charges):\n")
    print(f"{'#':3s} {'Window':10s} {'CloseStr<':>10s} {'VWAPGap<':>9s} {'MinPrice':>9s} {'Breadth<':>9s} "
          f"{'N':>6s} {'WinRate':>8s} {'AvgWin':>8s} {'AvgLoss':>9s} {'AvgNet':>8s}")
    print("-"*130)

    for i, r in enumerate(results[:25], 1):
        flag = ' ★' if r['win_rate'] >= 60 and r['avg_net'] > 0 else ''
        bmax = f"{r['breadth_max']:.0%}" if r['breadth_max'] is not None else 'none'
        print(
            f"{i:3d} {r['window']:10s} {r['cs_max']:>10.2f} {r['vwap_max']:>9.1f} "
            f"₹{r['min_px']:>8.0f} {bmax:>9s} {r['n_trades']:>6d} {r['win_rate']:>7.1f}% "
            f"{r['avg_win']:>+8.3f}% {r['avg_loss']:>+9.3f}% {r['avg_net']:>+8.3f}%{flag}"
        )

    # Best config drill-down
    best = results[0]
    bmax_str = f"{best['breadth_max']:.0%}" if best['breadth_max'] is not None else 'none'
    print(f"\n\n{'='*120}")
    print(f"BEST CONFIG (Mean-Reversion Overnight Bounce):")
    print(f"  Window: closing {best['window']}  |  close_strength < {best['cs_max']}  "
          f"|  vwap_gap < {best['vwap_max']}%  |  price ≥ ₹{best['min_px']:.0f}  "
          f"|  breadth filter: skip days where >{bmax_str} stocks below VWAP")
    print(f"  Trades: {best['n_trades']}  Win rate: {best['win_rate']}%  "
          f"Avg net: {best['avg_net']:+.3f}%  "
          f"Avg win: {best['avg_win']:+.3f}%  Avg loss: {best['avg_loss']:+.3f}%")
    print("="*120)

    # Per-day breakdown of best config
    by_date: Dict[str, list] = {}
    for t in best['trades']:
        d = str(t['day'])
        by_date.setdefault(d, []).append(t)

    print(f"\n{'Date':12s} {'ExitDay':12s} {'Trades':>7s} {'Wins':>5s} {'WinRate':>8s} "
          f"{'AvgNet':>8s} {'DayPnL':>8s} {'Stocks'}")
    print("-"*100)
    total_pnl = 0.0
    for d in sorted(by_date.keys()):
        day_t = by_date[d]
        wins  = sum(1 for t in day_t if t['pnl_net'] > 0)
        wr    = wins / len(day_t) * 100
        avg   = sum(t['pnl_net'] for t in day_t) / len(day_t)
        day_pnl = sum(t['pnl_net'] for t in day_t)
        total_pnl += day_pnl
        exit_d = str(day_t[0]['next_day'])
        stocks = ', '.join(t['symbol'] for t in sorted(day_t, key=lambda x: -x['pnl_net'])[:5])
        flag = ' ★' if wr >= 60 else ''
        print(f"{d:12s} {exit_d:12s} {len(day_t):7d} {wins:5d} {wr:7.1f}% "
              f"{avg:+8.3f}% {day_pnl:+8.3f}%{flag}  [{stocks}]")
    print(f"\n  30-day total P&L (sum, all trades): {total_pnl:+.3f}%  "
          f"| Avg per trade: {total_pnl/len(best['trades']):+.3f}%")

    # Top and bottom trades of best config
    sorted_trades = sorted(best['trades'], key=lambda x: -x['pnl_net'])
    print(f"\nTOP 10 WINNERS:")
    print(f"{'Date':12s} {'Symbol':14s} {'Entry':9s} {'Exit(9:25)':10s} {'PnL Net':9s} {'CloseStr':9s} {'VWAPGap':8s} {'WinChg':8s}")
    print("-"*90)
    for t in sorted_trades[:10]:
        print(f"{str(t['day']):12s} {t['symbol']:14s} {t['entry']:9.2f} {t['exit']:10.2f} "
              f"{t['pnl_net']:+8.3f}% {t['close_strength']:9.3f} {t['vwap_gap_pct']:+7.2f}% "
              f"{t['window_chg_pct']:+7.2f}%")

    print(f"\nBOTTOM 10 LOSERS:")
    print(f"{'Date':12s} {'Symbol':14s} {'Entry':9s} {'Exit(9:25)':10s} {'PnL Net':9s} {'CloseStr':9s} {'VWAPGap':8s} {'WinChg':8s}")
    print("-"*90)
    for t in sorted_trades[-10:]:
        print(f"{str(t['day']):12s} {t['symbol']:14s} {t['entry']:9.2f} {t['exit']:10.2f} "
              f"{t['pnl_net']:+8.3f}% {t['close_strength']:9.3f} {t['vwap_gap_pct']:+7.2f}% "
              f"{t['window_chg_pct']:+7.2f}%")

    # Per-symbol stats
    by_sym: Dict[str, list] = {}
    for t in best['trades']:
        by_sym.setdefault(t['symbol'], []).append(t)
    sym_rows = []
    for sym, sym_trades in by_sym.items():
        wins = sum(1 for t in sym_trades if t['pnl_net'] > 0)
        wr   = wins / len(sym_trades) * 100
        avg  = sum(t['pnl_net'] for t in sym_trades) / len(sym_trades)
        sym_rows.append((sym, len(sym_trades), wins, wr, avg))
    sym_rows.sort(key=lambda x: x[4], reverse=True)

    print(f"\n\n{'='*120}")
    print(f"PER-SYMBOL STATS (best config):\n")
    print(f"{'Symbol':16s} {'N':>4s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>9s}")
    print("-"*50)
    for sym, n, wins, wr, avg in sym_rows:
        flag = ' ★' if wr >= 60 and avg > 0 else ''
        print(f"{sym:16s} {n:4d} {wins:5d} {wr:7.1f}% {avg:+8.3f}%{flag}")

    # Signal distribution analysis
    print(f"\n\n{'='*120}")
    print("CLOSE STRENGTH vs WIN RATE (all raw trades — 2:30pm window):\n")
    print(f"{'CloseStrength Range':22s} {'N':>5s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>9s}")
    print("-"*55)
    cs_buckets = [(0.0, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 1.01)]
    for lo, hi in cs_buckets:
        sub = [t for t in all_raw_trades if lo <= t['close_strength'] < hi]
        if not sub:
            continue
        wins = sum(1 for t in sub if t['pnl_net'] > 0)
        wr   = wins / len(sub) * 100
        avg  = sum(t['pnl_net'] for t in sub) / len(sub)
        flag = ' ★' if wr >= 55 and avg > 0 and len(sub) >= 10 else ''
        print(f"  [{lo:.2f}, {hi:.2f})          {len(sub):5d} {wins:5d} {wr:7.1f}% {avg:+8.3f}%{flag}")

    print(f"\nVWAP GAP vs WIN RATE:\n")
    print(f"{'VWAP Gap Range':22s} {'N':>5s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>9s}")
    print("-"*55)
    vwap_buckets = [(-5.0, -0.5), (-0.5, 0.0), (0.0, 0.20), (0.20, 0.50), (0.50, 5.0)]
    for lo, hi in vwap_buckets:
        sub = [t for t in all_raw_trades if lo <= t['vwap_gap_pct'] < hi]
        if not sub:
            continue
        wins = sum(1 for t in sub if t['pnl_net'] > 0)
        wr   = wins / len(sub) * 100
        avg  = sum(t['pnl_net'] for t in sub) / len(sub)
        flag = ' ★' if wr >= 55 and avg > 0 and len(sub) >= 10 else ''
        print(f"  [{lo:+.2f}%, {hi:+.2f}%)      {len(sub):5d} {wins:5d} {wr:7.1f}% {avg:+8.3f}%{flag}")

    # Breakeven analysis
    bw = best['avg_win']
    bl = best['avg_loss']
    if bw > 0 and bl < 0:
        be_wr = abs(bl) / (bw + abs(bl)) * 100
        print(f"\n  Breakeven win rate: {be_wr:.1f}%  |  Actual: {best['win_rate']:.1f}%  "
              f"→  {'PROFITABLE' if best['win_rate'] > be_wr else 'LOSS-MAKING'} after charges")

    print(f"\n\nDone. {len(results)} configurations evaluated.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    token_map = load_token_map()
    available = [s for s in FOCUS_STOCKS if s in token_map]
    missing   = [s for s in FOCUS_STOCKS if s not in token_map]
    if missing:
        logger.warning(f"No token for: {missing}")
    logger.info(f"Backtesting {len(available)} stocks × {len(SIGNAL_DAYS)} signal days")

    logger.info("Fetching candle data (this will take several minutes for new data)...")
    candle_map = fetch_candles(kite, token_map)

    logger.info("Running parameter sweep...")
    results, all_raw_trades = run_sweep(candle_map)

    logger.info(f"Sweep done: {len(results)} valid configurations")
    print_report(results, all_raw_trades)


if __name__ == '__main__':
    main()
