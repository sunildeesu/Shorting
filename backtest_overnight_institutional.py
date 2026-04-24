#!/usr/bin/env python3
"""
Overnight Institutional Buying Backtest — 1 Month.

Strategy: Stocks showing INSTITUTIONAL BUYING signals in the closing window
(2 PM–3:15 PM) are entered at EOD close (3:29 PM) and exited next morning
at 9:25 AM.

Proxy signals (from 1-min OHLCV candles):
  cum_delta_pct : (buy_vol - sell_vol) / total_vol over the closing window
                  buy_fraction = (close - low) / (high - low) per candle
                  Positive = net buying in the window
  vol_ratio     : closing-window avg volume / pre-window 20-bar avg volume
                  ≥ 1.0 = at least normal volume = confirms the signal
  window_chg    : price change % in the closing window (must be positive = price rising)
  close_strength: (close - day_low) / (day_high - day_low)
                  > 0.50 = closing in upper half of day range = buyers dominating

Signal fires when (all gates):
  cum_delta_pct ≥ threshold  (net buying pressure)
  vol_ratio     ≥ threshold  (volume confirms)
  window_chg    ≥ 0.0%       (price rising in window)
  price         ≥ min_price  (filter tiny stocks)

Trade:
  Entry: 3:29 PM close (last minute of session)
  Exit : 9:25 AM next trading day
  Charges: 0.04% round trip

Reuses candle cache from backtest_overnight_1month_cache.json.
"""

import json
import os
import logging
from datetime import date, datetime, timedelta, time as dt_time
from itertools import product
from typing import Dict, List, Optional, Tuple

import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

CANDLE_CACHE       = 'data/backtest_overnight_1month_cache.json'
ROUND_TRIP_CHARGES = 0.0004   # 0.04% round trip (NSE futures)
EXIT_TIME          = dt_time(9, 25)
MIN_TRADES         = 10

# NSE trading days (same as overnight_1month.py)
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

SIGNAL_DAYS = [d for d in NSE_TRADING_DAYS if next_trading_day(d) is not None][-30:]

FOCUS_STOCKS = [
    'RELIANCE', 'HDFCBANK', 'ICICIBANK', 'INFY', 'TCS', 'AXISBANK', 'KOTAKBANK',
    'SBIN', 'BAJFINANCE', 'BHARTIARTL', 'WIPRO', 'TECHM', 'LTIM',
    'BAJAJFINSV', 'SHRIRAMFIN', 'CHOLAFIN', 'MUTHOOTFIN', 'PNB', 'CANBK',
    'FEDERALBNK', 'BANDHANBNK', 'RBLBANK', 'SBICARD', 'ANGELONE',
    'SUNPHARMA', 'DRREDDY', 'CIPLA', 'DIVISLAB', 'HINDUNILVR', 'ITC', 'TITAN',
    'TRENT', 'DMART', 'NESTLEIND',
    'PERSISTENT', 'COFORGE', 'KPITTECH', 'ABB', 'SIEMENS', 'BHEL',
    'HAL', 'BEL', 'MAZDOCK', 'TIINDIA',
    'TATASTEEL', 'HINDALCO', 'JSWSTEEL', 'ONGC', 'NTPC', 'POWERGRID',
    'TATAPOWER', 'ADANIPORTS', 'ADANIENT', 'VEDL', 'SAIL', 'NMDC',
    'PNBHOUSING', 'POLICYBZR', 'KAYNES', 'PAGEIND', 'PRESTIGE',
    'MPHASIS', 'OFSS', 'SONACOMS', 'SOLARINDS', 'MANKIND',
    'IRFC', 'NHPC', 'RVNL', 'RECLTD', 'OIL', 'UPL', 'AMBER',
]

# ── Parameter sweep grid ──────────────────────────────────────────────────────

WINDOW_STARTS = [
    (14,  0, '2:00pm'),
    (14, 30, '2:30pm'),
    (15,  0, '3:00pm'),
]
# Minimum net buy fraction in the closing window (cum_delta_pct)
CUM_DELTA_GATES = [0.10, 0.20, 0.30]
# Minimum volume ratio vs pre-window average (vol_ratio)
VOL_RATIO_GATES = [0.8, 1.0, 1.5]
# Minimum price filter
MIN_PRICE_THRESHOLDS = [100.0, 200.0, 500.0]

# ── Signal utilities ──────────────────────────────────────────────────────────

def bulk_volume_classify(c: dict) -> Tuple[float, float]:
    """
    Easley et al. bulk volume classification.
    buy_fraction = (close - low) / (high - low)
    """
    h, l, cls, vol = c['high'], c['low'], c['close'], c['volume']
    if h == l:
        return vol * 0.5, vol * 0.5
    frac = (cls - l) / (h - l)
    return vol * frac, vol * (1 - frac)


def compute_institutional_signal(candles: List[dict],
                                  window_start_hour: int,
                                  window_start_minute: int = 0) -> Optional[dict]:
    """
    Compute institutional buying proxy for the closing window.

    Returns dict with:
      cum_delta_pct : net buy fraction in window  (>0 = net buying)
      vol_ratio     : window avg vol / pre-window 20-bar avg vol
      window_chg    : price % change during window
      close_strength: where close sits in day's high-low range (0=low, 1=high)
      window_vol    : raw total volume in window (liquidity check)
    """
    window_start = dt_time(window_start_hour, window_start_minute)
    window_end   = dt_time(15, 15)

    window   = [c for c in candles if window_start <= c['date'].time() <= window_end]
    if len(window) < 3:
        return None

    window_vol = sum(c['volume'] for c in window)
    if window_vol < 500:
        return None

    # Net buy pressure (bulk volume classification)
    total_buy = total_sell = 0.0
    for c in window:
        bv, sv = bulk_volume_classify(c)
        total_buy += bv
        total_sell += sv
    total_vol = total_buy + total_sell
    cum_delta_pct = (total_buy - total_sell) / total_vol if total_vol > 0 else 0.0

    # Volume ratio vs pre-window 20-bar average
    pre_window = [c for c in candles if c['date'].time() < window_start]
    if len(pre_window) < 5:
        return None
    pre_avg = sum(c['volume'] for c in pre_window[-20:]) / min(20, len(pre_window))
    vol_ratio = (window_vol / len(window)) / pre_avg if pre_avg > 0 else 1.0

    # Price change in the window (must be positive = price rising)
    window_open  = window[0]['open']
    window_close = window[-1]['close']
    window_chg   = (window_close - window_open) / window_open * 100 if window_open > 0 else 0.0

    # Close strength: where close sits in day's range
    day_high = max(c['high'] for c in candles)
    day_low  = min(c['low']  for c in candles)
    close_strength = (window_close - day_low) / (day_high - day_low) if day_high > day_low else 0.5

    return {
        'cum_delta_pct':  round(cum_delta_pct, 4),
        'vol_ratio':      round(vol_ratio, 2),
        'window_chg':     round(window_chg, 3),
        'close_strength': round(close_strength, 3),
        'window_vol':     window_vol,
        'price':          window_close,
    }


def get_price_at(candles: List[dict], target: dt_time, max_age: int = 5) -> Optional[float]:
    """Close of the last candle within max_age minutes of target that has real volume."""
    target_dt = datetime.min.replace(hour=target.hour, minute=target.minute)
    cutoff    = (target_dt - timedelta(minutes=max_age))
    cutoff_t  = dt_time(cutoff.hour, cutoff.minute)
    eligible  = [c for c in candles
                 if cutoff_t <= c['date'].time() <= target
                 and c.get('volume', 0) >= 100]
    return eligible[-1]['close'] if eligible else None


# ── Main sweep ────────────────────────────────────────────────────────────────

def load_cache() -> Dict[str, List[dict]]:
    logger.info(f"Loading candle cache: {CANDLE_CACHE}")
    with open(CANDLE_CACHE) as f:
        raw = json.load(f)
    result = {}
    for key, candles in raw.items():
        if not candles:
            continue
        parsed = [{**c, 'date': datetime.strptime(c['date'], '%Y-%m-%d %H:%M:%S')} for c in candles]
        # Validate: data must match key date
        key_date = '_'.join(key.split('_')[1:])
        if parsed[0]['date'].strftime('%Y-%m-%d') != key_date:
            continue
        # Only keep candles within market hours (9:15 AM–3:30 PM)
        parsed = [c for c in parsed if dt_time(9, 14) <= c['date'].time() <= dt_time(15, 30)]
        if parsed:
            result[key] = parsed
    logger.info(f"Valid cache entries: {len(result)}")
    return result


def run_sweep(candle_map: Dict[str, List[dict]]):
    logger.info(f"Signal days: {SIGNAL_DAYS[0]} → {SIGNAL_DAYS[-1]} ({len(SIGNAL_DAYS)} days)")
    logger.info(f"Stocks: {len(FOCUS_STOCKS)}  |  Window starts: {[w[2] for w in WINDOW_STARTS]}")

    # ── Pre-compute all (symbol, day) signals and prices ─────────────────────
    precomputed: Dict[str, dict] = {}

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

            # Compute institutional buying signal for each window start
            sigs = {}
            for wh, wm, wlabel in WINDOW_STARTS:
                sig = compute_institutional_signal(day_candles, wh, wm)
                if sig:
                    sigs[wlabel] = sig
            if not sigs:
                continue

            # Entry and exit prices
            entry = get_price_at(day_candles,  dt_time(15, 29), max_age=5)
            exit_ = get_price_at(next_candles, EXIT_TIME,       max_age=5)

            if not entry or not exit_ or entry <= 0:
                continue
            if abs(entry - exit_) < 0.01:   # skip stale/frozen prices
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

    logger.info(f"Pre-computed {len(precomputed)} valid (symbol, day) pairs")

    # ── Parameter sweep ───────────────────────────────────────────────────────
    results = []

    for (wh, wm, wlabel), delta_gate, vol_gate, min_px in product(
            WINDOW_STARTS, CUM_DELTA_GATES, VOL_RATIO_GATES, MIN_PRICE_THRESHOLDS):

        trades = []
        sym_count: Dict[str, int] = {}

        for day in SIGNAL_DAYS:
            for sym in FOCUS_STOCKS:
                dk = f"{sym}_{day}"
                pc = precomputed.get(dk)
                if not pc:
                    continue
                if pc['price'] < min_px:
                    continue

                sig = pc['sigs'].get(wlabel)
                if not sig:
                    continue

                # Institutional BUYING gates
                if sig['cum_delta_pct'] < delta_gate:   # must have net buying
                    continue
                if sig['vol_ratio'] < vol_gate:          # must have volume confirmation
                    continue
                if sig['window_chg'] < 0.0:              # price must be rising in window
                    continue

                # Cap at 5 per symbol across all days
                if sym_count.get(sym, 0) >= 5:
                    continue
                sym_count[sym] = sym_count.get(sym, 0) + 1

                trades.append({**pc,
                                'cum_delta':    sig['cum_delta_pct'],
                                'vol_ratio':    sig['vol_ratio'],
                                'window_chg':   sig['window_chg'],
                                'close_str':    sig['close_strength'],
                                })

        if len(trades) < MIN_TRADES:
            continue

        winners  = [t for t in trades if t['pnl_net'] > 0]
        losers   = [t for t in trades if t['pnl_net'] <= 0]
        win_rate = len(winners) / len(trades) * 100
        avg_win  = sum(t['pnl_net'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pnl_net'] for t in losers)  / len(losers)  if losers  else 0
        avg_net  = sum(t['pnl_net'] for t in trades)  / len(trades)
        breakeven_wr = abs(avg_loss) / (avg_win - avg_loss) * 100 if (avg_win - avg_loss) > 0 else 50

        results.append({
            'window':       wlabel,
            'delta_gate':   delta_gate,
            'vol_gate':     vol_gate,
            'min_px':       min_px,
            'n_trades':     len(trades),
            'win_rate':     round(win_rate, 1),
            'avg_win':      round(avg_win, 3),
            'avg_loss':     round(avg_loss, 3),
            'avg_net':      round(avg_net, 3),
            'breakeven_wr': round(breakeven_wr, 1),
            'trades':       trades,
        })

    results.sort(key=lambda x: (x['avg_net'], x['win_rate']), reverse=True)
    return results


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_report(results: List[dict]):
    charge_pct = ROUND_TRIP_CHARGES * 100

    print("\n" + "=" * 120)
    print("OVERNIGHT INSTITUTIONAL BUYING BACKTEST — 1 Month")
    print(f"Signal days: {SIGNAL_DAYS[0]} → {SIGNAL_DAYS[-1]}  ({len(SIGNAL_DAYS)} days)")
    print(f"Stocks: {len(FOCUS_STOCKS)}  |  Charges: {charge_pct:.2f}% round trip")
    print(f"Entry: 3:29 PM close  |  Exit: next day 9:25 AM")
    print(f"Signal: net buying in closing window (cum_delta > threshold) + volume confirmation")
    print("=" * 120)

    if not results:
        print("No valid configurations found (all below MIN_TRADES threshold).")
        return

    profitable = [r for r in results if r['avg_net'] > 0]
    above60    = [r for r in results if r['win_rate'] >= 60 and r['avg_net'] > 0]
    above70    = [r for r in results if r['win_rate'] >= 70 and r['avg_net'] > 0]
    print(f"\n  Configs evaluated: {len(results)}")
    print(f"  Profitable (avg_net > 0): {len(profitable)}")
    print(f"  ≥60% win AND profitable: {len(above60)}")
    print(f"  ≥70% win AND profitable: {len(above70)}")

    print(f"\nTOP 20 CONFIGURATIONS:\n")
    print(f"{'#':3s} {'Window':8s} {'Delta≥':>7s} {'Vol≥':>6s} {'MinPx':>7s}  "
          f"{'N':>5s} {'WinRate':>8s} {'AvgWin':>8s} {'AvgLoss':>9s} {'AvgNet':>8s} {'BEvWR':>7s}")
    print("-" * 110)

    for i, r in enumerate(results[:20], 1):
        flag = ' ★' if r['win_rate'] >= 60 and r['avg_net'] > 0 else ''
        print(
            f"{i:3d} {r['window']:8s} {r['delta_gate']:>7.0%} {r['vol_gate']:>6.1f}x "
            f"₹{r['min_px']:>6.0f}  {r['n_trades']:>5d} {r['win_rate']:>7.1f}% "
            f"{r['avg_win']:>+8.3f}% {r['avg_loss']:>+9.3f}% {r['avg_net']:>+8.3f}%"
            f"  BE:{r['breakeven_wr']:.0f}%{flag}"
        )

    # ── Best config drill-down ────────────────────────────────────────────────
    best = results[0]
    print(f"\n\n{'='*120}")
    print(f"BEST CONFIG:")
    print(f"  Window: {best['window']}  |  cum_delta ≥ {best['delta_gate']:.0%}  "
          f"|  vol_ratio ≥ {best['vol_gate']:.1f}x  |  price ≥ ₹{best['min_px']:.0f}")
    print(f"  Trades: {best['n_trades']}  Win rate: {best['win_rate']}%  "
          f"Avg net: {best['avg_net']:+.3f}%  "
          f"Avg win: {best['avg_win']:+.3f}%  Avg loss: {best['avg_loss']:+.3f}%")
    print(f"  Breakeven win rate: {best['breakeven_wr']:.1f}%  → "
          f"{'PROFITABLE' if best['avg_net'] > 0 else 'LOSS-MAKING'} after {charge_pct:.2f}% charges")
    print("=" * 120)

    # Per-day breakdown
    by_date: Dict[str, list] = {}
    for t in best['trades']:
        by_date.setdefault(str(t['day']), []).append(t)

    print(f"\n{'Date':12s} {'Exit':12s} {'Trades':>7s} {'Wins':>5s} {'WinRate':>8s} "
          f"{'AvgNet':>8s} {'DayPnL':>9s} Stocks")
    print("-" * 100)
    total_pnl = 0.0
    for d in sorted(by_date):
        dt = by_date[d]
        wins    = sum(1 for t in dt if t['pnl_net'] > 0)
        wr      = wins / len(dt) * 100
        avg     = sum(t['pnl_net'] for t in dt) / len(dt)
        day_pnl = sum(t['pnl_net'] for t in dt)
        total_pnl += day_pnl
        exit_d  = str(dt[0]['next_day'])
        stocks  = ', '.join(t['symbol'] for t in sorted(dt, key=lambda x: -x['pnl_net'])[:5])
        flag    = ' ★' if wr >= 60 else ''
        print(f"{d:12s} {exit_d:12s} {len(dt):7d} {wins:5d} {wr:7.1f}% "
              f"{avg:+8.3f}% {day_pnl:+9.3f}%{flag}  [{stocks}]")
    print(f"\n  Total P&L (sum, {len(best['trades'])} trades): {total_pnl:+.3f}%  "
          f"| Avg per trade: {total_pnl/len(best['trades']):+.3f}%")

    # Top winners and losers
    sorted_t = sorted(best['trades'], key=lambda x: -x['pnl_net'])
    print(f"\nTOP 10 WINNERS:")
    print(f"{'Date':12s} {'Symbol':14s} {'Entry':>9s} {'Exit(9:25)':>10s} "
          f"{'PnL':>8s} {'Delta':>7s} {'VolRatio':>9s} {'WinChg':>8s}")
    print("-" * 90)
    for t in sorted_t[:10]:
        print(f"{str(t['day']):12s} {t['symbol']:14s} {t['entry']:>9.2f} {t['exit']:>10.2f} "
              f"{t['pnl_net']:>+8.3f}% {t['cum_delta']:>+7.1%} {t['vol_ratio']:>9.2f}x "
              f"{t['window_chg']:>+8.3f}%")

    print(f"\nBOTTOM 10 LOSERS:")
    print(f"{'Date':12s} {'Symbol':14s} {'Entry':>9s} {'Exit(9:25)':>10s} "
          f"{'PnL':>8s} {'Delta':>7s} {'VolRatio':>9s} {'WinChg':>8s}")
    print("-" * 90)
    for t in sorted_t[-10:]:
        print(f"{str(t['day']):12s} {t['symbol']:14s} {t['entry']:>9.2f} {t['exit']:>10.2f} "
              f"{t['pnl_net']:>+8.3f}% {t['cum_delta']:>+7.1%} {t['vol_ratio']:>9.2f}x "
              f"{t['window_chg']:>+8.3f}%")

    # ── Signal distribution analysis ──────────────────────────────────────────
    # Use all valid precomputed pairs to show how cum_delta correlates with next-day returns
    # (Collect from best config window's precomputed data)
    print(f"\n\n{'='*120}")
    print(f"CUM DELTA vs NEXT-DAY RETURN (all {len(results[0]['trades'])} raw trades — {best['window']} window):")
    print(f"{'Delta Range':25s} {'N':>5s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>8s}")
    print("-" * 60)

    # Gather all trades from widest filter (delta ≥ 0%, vol ≥ 0.8x, price ≥ 100)
    widest = [r for r in results
              if r['window'] == best['window']
              and r['delta_gate'] == 0.10
              and r['vol_gate'] == 0.8
              and r['min_px'] == 100.0]
    if widest:
        all_t = widest[0]['trades']
        for lo, hi in [(-1.0, 0.0), (0.0, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 1.0)]:
            bucket = [t for t in all_t if lo <= t['cum_delta'] < hi]
            if bucket:
                wins = sum(1 for t in bucket if t['pnl_net'] > 0)
                wr   = wins / len(bucket) * 100
                avg  = sum(t['pnl_net'] for t in bucket) / len(bucket)
                flag = ' ★' if wr >= 60 and avg > 0 else ''
                print(f"  [{lo:+.0%}, {hi:+.0%})          {len(bucket):>5d} {wins:>5d} "
                      f"{wr:>7.1f}% {avg:>+8.3f}%{flag}")

    # ── Per-symbol stats ──────────────────────────────────────────────────────
    print(f"\nPER-SYMBOL STATS (best config):")
    print(f"{'Symbol':16s} {'N':>4s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>8s}")
    print("-" * 50)
    sym_stats: Dict[str, dict] = {}
    for t in best['trades']:
        s = sym_stats.setdefault(t['symbol'], {'n': 0, 'wins': 0, 'pnl': 0.0})
        s['n'] += 1
        s['wins'] += 1 if t['pnl_net'] > 0 else 0
        s['pnl'] += t['pnl_net']
    for sym, s in sorted(sym_stats.items(), key=lambda x: -x[1]['pnl']/x[1]['n']):
        avg = s['pnl'] / s['n']
        wr  = s['wins'] / s['n'] * 100
        flag = ' ★' if wr >= 60 and avg > 0 else ''
        print(f"{sym:16s} {s['n']:>4d} {s['wins']:>5d} {wr:>7.1f}% {avg:>+8.3f}%{flag}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(CANDLE_CACHE):
        logger.error(f"Candle cache not found: {CANDLE_CACHE}")
        logger.error("Run backtest_overnight_1month.py first to build the cache.")
        return

    candle_map = load_cache()
    results = run_sweep(candle_map)
    print_report(results)
    logger.info(f"Done. {len(results)} configurations evaluated.")


if __name__ == '__main__':
    main()
