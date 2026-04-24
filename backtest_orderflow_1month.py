#!/usr/bin/env python3
"""
Order Flow Proxy Backtest — 1 Month, with Trading Charges.

Since raw tick/order-book data only exists for Apr 16-17, this script
builds a candle-based proxy for the order flow signals and backtests
across the last 30 trading days on 50 liquid F&O stocks.

Proxy signals (from 1-min OHLCV candles, sliding 5-min window):
  cum_delta_pct  : (buy_vol - sell_vol) / total_vol using bulk-volume classification
                   buy_fraction = (close - low) / (high - low) per candle
  velocity       : ₹/tick = abs(price_change) / ticks_estimate
  vol_spike      : current_5m_vol / rolling_20bar_avg_vol
  price_chg_5m   : % price change over 5 minutes

Signal fires when:
  - cum_delta_pct passes direction gate (≥ threshold)
  - vol_spike ≥ 1.5× (at least 50% above normal)
  - Price > ₹50 (no penny stocks)

Then simulates trade with configurable trailing stop.

Trading charges (NSE Futures, round trip):
  - Brokerage: ₹20 each way = ₹40 flat
  - STT (sell side): 0.0125% of notional
  - NSE transaction charges: 0.00173% × 2
  - SEBI charges: 0.0001% × 2
  - GST 18% on (brokerage + exchange charges)
  - Stamp duty 0.003% on buy
  Effective % cost depends on lot notional — for a typical ₹5L lot ≈ 0.035-0.05%
  We use a flat 0.04% round-trip as conservative estimate.

Usage:
    python backtest_orderflow_1month.py
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

CANDLE_CACHE_1M    = 'data/bt1m_candle_cache_1month.json'
TOKEN_FILE         = 'data/all_instrument_tokens.json'
FO_STOCKS_FILE     = 'fo_stocks.json'

ROUND_TRIP_CHARGES = 0.0004   # 0.04% of trade notional (conservative futures estimate)
MIN_PRICE          = 50.0     # skip penny stocks
MARKET_OPEN        = dt_time(9, 20)   # skip opening auction noise
MARKET_CLOSE       = dt_time(15, 15)  # no new entries after 3:15 PM (close exits at 3:30)

# 30 trading days back from today
TODAY = date.today()
def _trading_days_back(n: int) -> List[date]:
    days = []
    d = TODAY
    while len(days) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:   # Mon-Fri only
            days.append(d)
    return list(reversed(days))

BACKTEST_DATES = _trading_days_back(30)

# Top 50 liquid F&O stocks (most commonly traded, spread across sectors)
FOCUS_STOCKS = [
    # Large-cap index heavyweights
    'RELIANCE', 'HDFCBANK', 'ICICIBANK', 'INFY', 'TCS', 'HDFC', 'AXISBANK',
    'KOTAKBANK', 'SBIN', 'BAJFINANCE', 'BHARTIARTL', 'WIPRO', 'TECHM',
    # Mid/small with high F&O activity
    'ADANIENT', 'ADANIPORTS', 'TATASTEEL', 'HINDALCO', 'JSWSTEEL', 'ONGC',
    'NTPC', 'POWERGRID', 'BEL', 'HAL', 'IRFC', 'NHPC', 'RVNL',
    # Finance / NBFC
    'BAJAJFINSV', 'ANGELONE', 'MUTHOOTFIN', 'SHRIRAMFIN', 'CHOLAFIN',
    # Consumer / Pharma
    'SUNPHARMA', 'DIVISLAB', 'DRREDDY', 'CIPLA', 'HINDUNILVR', 'ITC',
    'TITAN', 'TRENT', 'DMART',
    # IT / Capital goods
    'PERSISTENT', 'COFORGE', 'KPITTECH', 'ABB', 'SIEMENS', 'BHEL',
    # Others from alert history
    'YESBANK', 'IDEA', 'JINDALSTEL', 'AMBUJACEM',
]

# ── Candle fetching with cache ─────────────────────────────────────────────────

def load_token_map() -> Dict[str, int]:
    with open(TOKEN_FILE) as f:
        return json.load(f)

def fetch_candles(kite: KiteConnect, token_map: Dict[str, int]) -> Dict[str, List[dict]]:
    """
    Fetch 1-min candles for FOCUS_STOCKS × BACKTEST_DATES.
    Cache to disk; skip already-cached keys.
    Returns {"{SYMBOL}_{DATE}": [candles]}
    """
    cache = {}
    if os.path.exists(CANDLE_CACHE_1M):
        try:
            with open(CANDLE_CACHE_1M) as f:
                cache = json.load(f)
            logger.info(f"Loaded {len(cache)} cached candle series from 1-month cache")
        except Exception:
            cache = {}

    needed = [
        (sym, day, f"{sym}_{day}")
        for sym in FOCUS_STOCKS
        for day in BACKTEST_DATES
    ]
    to_fetch = [(sym, day, key) for sym, day, key in needed if key not in cache]
    logger.info(f"Need to fetch {len(to_fetch)} series (already cached: {len(needed)-len(to_fetch)})")

    for i, (symbol, day, key) in enumerate(to_fetch):
        token = token_map.get(symbol)
        if not token:
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
            cache[key] = [
                {'date': c['date'].strftime('%Y-%m-%d %H:%M:%S'),
                 'open': c['open'], 'high': c['high'], 'low': c['low'],
                 'close': c['close'], 'volume': c['volume']}
                for c in raw
            ]
            if (i + 1) % 50 == 0:
                logger.info(f"  Fetched {i+1}/{len(to_fetch)}...")
        except Exception as e:
            logger.warning(f"Failed {symbol} {day}: {e}")
            cache[key] = []
        time.sleep(0.25)

    if to_fetch:
        with open(CANDLE_CACHE_1M, 'w') as f:
            json.dump(cache, f)
        logger.info(f"Saved cache ({len(cache)} series total)")

    # Deserialise dates
    result = {}
    for key, candles in cache.items():
        result[key] = [
            {**c, 'date': datetime.strptime(c['date'], '%Y-%m-%d %H:%M:%S')}
            for c in candles
        ]
    return result


# ── Proxy signal computation ───────────────────────────────────────────────────

def bulk_volume_classify(c: dict) -> Tuple[float, float]:
    """
    Bulk volume classification (Easley et al.):
    buy_fraction = (close - low) / (high - low)
    Returns (buy_vol, sell_vol).
    """
    h, l, cls, vol = c['high'], c['low'], c['close'], c['volume']
    if h == l:
        return vol * 0.5, vol * 0.5
    buy_frac = (cls - l) / (h - l)
    return vol * buy_frac, vol * (1 - buy_frac)


def compute_proxy_signals(candles: List[dict], window: int = 5) -> List[dict]:
    """
    Slide a 5-minute window over the candles and compute order-flow proxies.
    Returns a list of signal events, one per eligible bar.
    """
    if len(candles) < window + 20:   # need history for vol average
        return []

    # Pre-compute volume series for rolling average
    vols = [c['volume'] for c in candles]
    signals = []

    for i in range(20, len(candles) - window + 1):
        # Window bars for signal computation
        w = candles[i:i + window]
        bar_time = w[0]['date']

        # Market hours filter
        if bar_time.time() < MARKET_OPEN or bar_time.time() > MARKET_CLOSE:
            continue

        # Current price
        price = w[-1]['close']
        if price < MIN_PRICE:
            continue

        # Bulk volume classification over the 5-min window
        total_buy = total_sell = 0.0
        for c in w:
            bv, sv = bulk_volume_classify(c)
            total_buy += bv
            total_sell += sv
        total_vol = total_buy + total_sell
        if total_vol == 0:
            continue

        cum_delta_pct = (total_buy - total_sell) / total_vol

        # Volume spike vs rolling 20-bar average (bars before window)
        hist_vol = sum(vols[i-20:i]) / 20
        w_vol    = sum(c['volume'] for c in w)
        vol_spike = (w_vol / hist_vol) if hist_vol > 0 else 1.0

        # 5-min price change
        price_open  = w[0]['open']
        price_close = w[-1]['close']
        price_chg   = (price_close - price_open) / price_open * 100

        # Tick velocity proxy: ₹ moved per minute
        tick_vel = abs(price_close - price_open) / window

        signals.append({
            'bar_time':     bar_time,
            'price':        price,
            'cum_delta_pct': cum_delta_pct,
            'vol_spike':    vol_spike,
            'price_chg_5m': price_chg,
            'tick_vel':     tick_vel,
            'total_vol':    w_vol,
        })

    return signals


def detect_alerts(signals: List[dict],
                  cum_gate: float,
                  vol_spike_min: float,
                  vel_min: float) -> List[dict]:
    """
    Convert proxy signals into directional alerts using the given thresholds.
    Deduplicates: only one alert per direction per 30-minute window.
    """
    alerts = []
    last_bear = datetime.min
    last_bull = datetime.min
    cooldown  = timedelta(minutes=30)

    for s in signals:
        if s['vol_spike'] < vol_spike_min:
            continue

        cum = s['cum_delta_pct']
        t   = s['bar_time']

        if cum <= -cum_gate:
            if t - last_bear >= cooldown:
                alerts.append({**s, 'direction': 'BEARISH'})
                last_bear = t
        elif cum >= cum_gate:
            if t - last_bull >= cooldown:
                alerts.append({**s, 'direction': 'BULLISH'})
                last_bull = t

    return alerts


# ── Trade simulation ───────────────────────────────────────────────────────────

def simulate_trade(candles: List[dict], alert_time: datetime,
                   direction: str, trail_pct: float,
                   max_hold: int = 90) -> Optional[dict]:
    """
    Enter at first candle close after alert_time.
    Exit on trailing stop or max_hold minutes or 15:30.
    """
    start = alert_time + timedelta(minutes=1)  # first full candle after signal
    end   = min(alert_time + timedelta(minutes=max_hold),
                alert_time.replace(hour=15, minute=30, second=0, microsecond=0))
    trade_candles = [c for c in candles if start <= c['date'] <= end]
    if not trade_candles:
        return None

    entry = trade_candles[0]['close']
    if entry <= 0:
        return None

    trail_ref = entry
    for i, c in enumerate(trade_candles):
        price = c['close']
        if direction == 'BULLISH':
            if price > trail_ref:
                trail_ref = price
            stop = trail_ref * (1 - trail_pct)
            if i > 0 and price <= stop:
                return _trade_result(entry, price, direction, i, 'trail_stop', c['date'])
        else:
            if price < trail_ref:
                trail_ref = price
            stop = trail_ref * (1 + trail_pct)
            if i > 0 and price >= stop:
                return _trade_result(entry, price, direction, i, 'trail_stop', c['date'])

    last = trade_candles[-1]
    return _trade_result(entry, last['close'], direction, len(trade_candles), 'time_exit', last['date'])


def _trade_result(entry, exit_p, direction, hold, reason, exit_time) -> dict:
    if direction == 'BULLISH':
        pnl_pct = (exit_p - entry) / entry * 100
    else:
        pnl_pct = (entry - exit_p) / entry * 100
    # Deduct charges: 0.04% round trip
    pnl_net = pnl_pct - (ROUND_TRIP_CHARGES * 100)
    return {
        'entry_price':  entry,
        'exit_price':   exit_p,
        'pnl_pct':      round(pnl_pct, 3),
        'pnl_net':      round(pnl_net, 3),   # after charges
        'hold_minutes': hold,
        'exit_reason':  reason,
        'exit_time':    exit_time,
    }


# ── Parameter sweep ────────────────────────────────────────────────────────────

# cum_delta gate thresholds to test
CUM_GATE_VALUES    = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
# volume spike minimums
VOL_SPIKE_VALUES   = [1.3, 1.5, 2.0, 2.5]
# trailing stop %
TRAIL_PCT_VALUES   = [0.003, 0.004, 0.005, 0.006]
# velocity minimum (₹/min price movement)
VEL_MIN_VALUES     = [0.0, 0.5, 1.0]

MIN_TRADES = 30   # skip configs with too few trades


def run_sweep(candle_map: Dict[str, List[dict]]) -> List[dict]:
    results = []

    total_combos = len(CUM_GATE_VALUES) * len(VOL_SPIKE_VALUES) * len(TRAIL_PCT_VALUES) * len(VEL_MIN_VALUES)
    logger.info(f"Running sweep: {total_combos} parameter combinations...")

    for cum_gate, vol_spike_min, trail_pct, vel_min in product(
            CUM_GATE_VALUES, VOL_SPIKE_VALUES, TRAIL_PCT_VALUES, VEL_MIN_VALUES):

        trades = []
        alerts_generated = 0

        for sym in FOCUS_STOCKS:
            for day in BACKTEST_DATES:
                key = f"{sym}_{day}"
                candles = candle_map.get(key, [])
                if not candles:
                    continue

                proxy_signals = compute_proxy_signals(candles)
                alerts = detect_alerts(proxy_signals, cum_gate, vol_spike_min, vel_min)
                alerts_generated += len(alerts)

                for alert in alerts:
                    sim = simulate_trade(candles, alert['bar_time'], alert['direction'], trail_pct)
                    if sim:
                        trades.append({
                            'symbol':    sym,
                            'date':      day,
                            'direction': alert['direction'],
                            'bar_time':  alert['bar_time'],
                            'vol_spike': alert['vol_spike'],
                            'cum_delta': alert['cum_delta_pct'],
                            **sim,
                        })

        if len(trades) < MIN_TRADES:
            continue

        winners   = [t for t in trades if t['pnl_net'] > 0]
        losers    = [t for t in trades if t['pnl_net'] <= 0]
        win_rate  = len(winners) / len(trades) * 100
        avg_win   = sum(t['pnl_net'] for t in winners) / len(winners) if winners else 0
        avg_loss  = sum(t['pnl_net'] for t in losers)  / len(losers)  if losers  else 0
        avg_net   = sum(t['pnl_net'] for t in trades)  / len(trades)
        # Expectancy: expected ₹ per ₹100 traded after charges
        expectancy = avg_net

        results.append({
            'cum_gate':    cum_gate,
            'vol_spike':   vol_spike_min,
            'trail_pct':   trail_pct,
            'vel_min':     vel_min,
            'n_trades':    len(trades),
            'n_alerts':    alerts_generated,
            'win_rate':    round(win_rate, 1),
            'avg_win':     round(avg_win, 3),
            'avg_loss':    round(avg_loss, 3),
            'avg_net':     round(avg_net, 3),
            'expectancy':  round(expectancy, 3),
            'trades':      trades,
        })

    results.sort(key=lambda x: x['expectancy'], reverse=True)
    logger.info(f"Sweep done: {len(results)} valid combinations")
    return results


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_report(results: List[dict]):
    charge_pct = ROUND_TRIP_CHARGES * 100

    print("\n" + "="*115)
    print(f"ORDER FLOW PROXY BACKTEST — 1 Month ({BACKTEST_DATES[0]} to {BACKTEST_DATES[-1]})")
    print(f"Stocks: {len(FOCUS_STOCKS)}  |  Trading charges: {charge_pct:.2f}% round trip")
    print(f"TARGET: 70% win rate + positive avg P&L after charges")
    print("="*115)

    if not results:
        print("No valid configurations found.")
        return

    # Show how many configs hit 70% win rate
    above70 = [r for r in results if r['win_rate'] >= 70.0]
    profitable = [r for r in results if r['avg_net'] > 0]
    above70_profitable = [r for r in above70 if r['avg_net'] > 0]
    print(f"\n  Configs with win rate ≥ 70%:         {len(above70)}")
    print(f"  Configs with avg net P&L > 0:        {len(profitable)}")
    print(f"  Both (70%+ win AND positive avg net): {len(above70_profitable)}")

    print(f"\nTOP 20 BY AVG NET P&L (after {charge_pct:.2f}% charges):\n")
    print(f"{'#':3s} {'CumGate':>8s} {'VolSpk':>7s} {'Trail':>7s} {'VelMin':>7s} "
          f"{'N':>6s} {'WinRate':>9s} {'AvgWin':>8s} {'AvgLoss':>9s} {'AvgNet':>8s}")
    print("-"*115)
    for i, r in enumerate(results[:20], 1):
        flag = ' ★' if r['win_rate'] >= 70 and r['avg_net'] > 0 else ''
        print(
            f"{i:3d} {r['cum_gate']:>8.2f} {r['vol_spike']:>7.1f} {r['trail_pct']*100:>6.2f}% "
            f"{r['vel_min']:>7.1f} {r['n_trades']:>6d} {r['win_rate']:>8.1f}% "
            f"{r['avg_win']:>+8.3f}% {r['avg_loss']:>+9.3f}% {r['avg_net']:>+8.3f}%{flag}"
        )

    if above70_profitable:
        best = above70_profitable[0]
    else:
        best = results[0]
        print(f"\n  ⚠ No config hit both 70% win rate AND positive net P&L.")
        print(f"    Showing best by net P&L:")

    print(f"\n{'='*115}")
    print(f"BEST CONFIG: cum_gate={best['cum_gate']}  vol_spike={best['vol_spike']}  "
          f"trail={best['trail_pct']*100:.2f}%  vel_min={best['vel_min']}")
    print(f"  Trades: {best['n_trades']}  Win rate: {best['win_rate']}%  "
          f"Avg net: {best['avg_net']:+.3f}%  "
          f"Avg win: {best['avg_win']:+.3f}%  Avg loss: {best['avg_loss']:+.3f}%")
    print("="*115)

    # Per-day breakdown
    by_date: Dict[str, list] = {}
    for t in best['trades']:
        d = str(t['date'])
        by_date.setdefault(d, []).append(t)

    print(f"\n{'Date':12s} {'Trades':>7s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>8s} {'DayPnL':>8s}")
    print("-"*60)
    total_pnl = 0.0
    for d in sorted(by_date.keys()):
        day_t = by_date[d]
        wins  = sum(1 for t in day_t if t['pnl_net'] > 0)
        wr    = wins / len(day_t) * 100
        avg   = sum(t['pnl_net'] for t in day_t) / len(day_t)
        total_pnl += sum(t['pnl_net'] for t in day_t)
        flag = ' ★' if wr >= 70 else ''
        print(f"{d:12s} {len(day_t):7d} {wins:5d} {wr:7.1f}% {avg:+8.3f}% "
              f"{sum(t['pnl_net'] for t in day_t):+8.3f}%{flag}")
    print(f"\n  Total P&L (all trades, net): {total_pnl:+.3f}%  "
          f"Avg per trade: {total_pnl/len(best['trades']):+.3f}%")

    # Per-symbol breakdown
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

    print(f"\n{'='*115}")
    print(f"PER-SYMBOL PERFORMANCE (best config):\n")
    print(f"{'Symbol':14s} {'N':>5s} {'Wins':>5s} {'WinRate':>8s} {'AvgNet':>9s}")
    print("-"*50)
    for sym, n, wins, wr, avg in sym_rows:
        flag = ' ★' if wr >= 70 and avg > 0 else ''
        print(f"{sym:14s} {n:5d} {wins:5d} {wr:7.1f}% {avg:+8.3f}%{flag}")

    # Direction breakdown
    bears = [t for t in best['trades'] if t['direction'] == 'BEARISH']
    bulls = [t for t in best['trades'] if t['direction'] == 'BULLISH']

    print(f"\n{'='*115}")
    print(f"DIRECTION BREAKDOWN:\n")
    for label, sub in [('BEARISH (short)', bears), ('BULLISH (long)', bulls)]:
        if not sub:
            continue
        wins = [t for t in sub if t['pnl_net'] > 0]
        wr   = len(wins) / len(sub) * 100
        avg  = sum(t['pnl_net'] for t in sub) / len(sub)
        aw   = sum(t['pnl_net'] for t in wins) / len(wins) if wins else 0
        ll   = [t for t in sub if t['pnl_net'] <= 0]
        al   = sum(t['pnl_net'] for t in ll) / len(ll) if ll else 0
        print(f"  {label:20s}: n={len(sub):5d}  win={wr:5.1f}%  avg={avg:+.3f}%  "
              f"avg_win={aw:+.3f}%  avg_loss={al:+.3f}%")

    # What win rate do we need to be profitable?
    bw = best['avg_win']
    bl = best['avg_loss']
    if bw > 0 and bl < 0:
        breakeven_wr = abs(bl) / (bw + abs(bl)) * 100
        print(f"\n  Breakeven win rate with these avg win/loss: {breakeven_wr:.1f}%")
        print(f"  Charges per trade: {charge_pct:.3f}%")
        print(f"  Actual win rate: {best['win_rate']:.1f}%  →  "
              f"{'PROFITABLE' if best['win_rate'] > breakeven_wr else 'LOSS-MAKING'} after charges")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    token_map = load_token_map()

    # Filter FOCUS_STOCKS to only those in token map
    available = [s for s in FOCUS_STOCKS if s in token_map]
    missing   = [s for s in FOCUS_STOCKS if s not in token_map]
    if missing:
        logger.warning(f"No token for {missing}")
    logger.info(f"Backtesting {len(available)} stocks × {len(BACKTEST_DATES)} days")
    logger.info(f"Date range: {BACKTEST_DATES[0]} → {BACKTEST_DATES[-1]}")

    candle_map = fetch_candles(kite, token_map)

    # Only keep available stocks
    candle_map = {k: v for k, v in candle_map.items()
                  if k.split('_')[0] in available}

    results = run_sweep(candle_map)
    print_report(results)


if __name__ == '__main__':
    main()
