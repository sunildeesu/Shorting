#!/usr/bin/env python3
"""
Order Flow Alert Backtest — trailing stop P&L simulation.

Reads alerts fired on 2026-04-16 and 2026-04-17 from order_flow_monitor.log,
applies the NEW execution gate filter (only alerts with confirmed cash execution),
then fetches minute candles from Kite and simulates a 0.5% trailing stop loss.

Trailing stop logic:
  BULLISH (long):  enter at first candle close after alert
                   stop = highest_close_seen × (1 - 0.005)
                   exit when close <= stop OR at 3:30 PM
  BEARISH (short): enter at first candle close after alert
                   stop = lowest_close_seen × (1 + 0.005)
                   exit when close >= stop OR at 3:30 PM
"""

import json
import re
import time
import logging
from datetime import datetime, date, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple

from kiteconnect import KiteConnect
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

LOG_FILE    = 'logs/order_flow_monitor.log'
TOKEN_FILE  = 'data/all_instrument_tokens.json'
BACKTEST_DATES = [date(2026, 4, 16), date(2026, 4, 17)]
TRAILING_STOP_PCT = 0.005   # 0.5%
MARKET_OPEN  = dt_time(9, 20)   # alerts before 9:20 AM are opening noise
MARKET_CLOSE = dt_time(15, 30)

# Regex to parse alert lines
ALERT_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - __main__ - INFO - '
    r'(BEARISH|BULLISH): (\w[\w\-]*) score=(\d+) — \S+ \((.+)\)'
)


# ── Log parsing ──────────────────────────────────────────────────────────────

def parse_alerts(log_file: str, target_dates: List[date]) -> List[dict]:
    """
    Parse BEARISH/BULLISH alerts from log.
    Filter: time >= 9:20 AM, must contain '5m flow' OR 'vel ₹[2-9]' in reasons
    (signals that real cash execution occurred, passing the new execution gate).
    """
    alerts = []
    date_strs = {str(d) for d in target_dates}

    with open(log_file) as f:
        for line in f:
            m = ALERT_RE.match(line)
            if not m:
                continue
            ts_str, direction, symbol, score, reasons = m.groups()
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

            if str(ts.date()) not in date_strs:
                continue
            if ts.time() < MARKET_OPEN:
                continue   # opening auction noise

            # NEW execution gate filter: must have cash executed flow confirmed
            has_cash_flow = '5m flow' in reasons
            has_velocity  = bool(re.search(r'vel ₹[2-9]', reasons))  # velocity ≥ ₹2/tick
            if not (has_cash_flow or has_velocity):
                continue   # would fail new execution gate — skip

            alerts.append({
                'ts':        ts,
                'direction': direction,
                'symbol':    symbol,
                'score':     int(score),
                'reasons':   reasons,
            })

    # Deduplicate: keep only the first alert per (symbol, direction, date)
    seen = set()
    deduped = []
    for a in alerts:
        key = (a['symbol'], a['direction'], a['ts'].date())
        if key not in seen:
            seen.add(key)
            deduped.append(a)

    logger.info(f"Parsed {len(deduped)} alerts (after dedup) across {target_dates}")
    return deduped


# ── Kite helpers ─────────────────────────────────────────────────────────────

def load_token_map(token_file: str) -> Dict[str, int]:
    with open(token_file) as f:
        return json.load(f)   # {symbol: token}


def fetch_minute_candles(kite: KiteConnect, token: int,
                         alert_dt: datetime) -> List[dict]:
    """Fetch 1-min candles from alert time to 3:30 PM on that day."""
    day_close = datetime.combine(alert_dt.date(), MARKET_CLOSE)
    try:
        candles = kite.historical_data(
            instrument_token=token,
            from_date=alert_dt,
            to_date=day_close,
            interval='minute',
            continuous=False,
            oi=False,
        )
        return candles
    except Exception as e:
        logger.warning(f"Failed to fetch candles for token {token}: {e}")
        return []


# ── Trailing stop simulation ──────────────────────────────────────────────────

def simulate_trailing_stop(candles: List[dict], direction: str,
                            stop_pct: float = TRAILING_STOP_PCT) -> dict:
    """
    Simulate trailing stop on minute candles.
    Entry = close of first candle.
    Returns dict with entry, exit, pnl_pct, hold_minutes, exit_reason.
    """
    if not candles:
        return {}

    entry_price = candles[0]['close']
    if entry_price <= 0:
        return {}

    trail_ref = entry_price   # highest seen (long) or lowest seen (short)
    stop = None

    for i, c in enumerate(candles):
        price = c['close']
        candle_time = c['date']

        if direction == 'BULLISH':
            if price > trail_ref:
                trail_ref = price
            stop = trail_ref * (1 - stop_pct)
            if i > 0 and price <= stop:
                pnl = (price - entry_price) / entry_price * 100
                return {
                    'entry_price':   entry_price,
                    'exit_price':    price,
                    'pnl_pct':       round(pnl, 3),
                    'hold_minutes':  i,
                    'exit_reason':   'trailing_stop',
                    'exit_time':     candle_time,
                    'peak_price':    trail_ref,
                }
        else:  # BEARISH (short)
            if price < trail_ref:
                trail_ref = price
            stop = trail_ref * (1 + stop_pct)
            if i > 0 and price >= stop:
                pnl = (entry_price - price) / entry_price * 100
                return {
                    'entry_price':   entry_price,
                    'exit_price':    price,
                    'pnl_pct':       round(pnl, 3),
                    'hold_minutes':  i,
                    'exit_reason':   'trailing_stop',
                    'exit_time':     candle_time,
                    'peak_price':    trail_ref,
                }

    # Market close exit
    last = candles[-1]
    exit_price = last['close']
    if direction == 'BULLISH':
        pnl = (exit_price - entry_price) / entry_price * 100
    else:
        pnl = (entry_price - exit_price) / entry_price * 100

    return {
        'entry_price':  entry_price,
        'exit_price':   exit_price,
        'pnl_pct':      round(pnl, 3),
        'hold_minutes': len(candles),
        'exit_reason':  'market_close',
        'exit_time':    last['date'],
        'peak_price':   trail_ref,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    token_map = load_token_map(TOKEN_FILE)
    alerts    = parse_alerts(LOG_FILE, BACKTEST_DATES)

    if not alerts:
        print("No alerts found matching the execution gate filter.")
        return

    results = []
    missing  = []

    for i, alert in enumerate(alerts):
        symbol = alert['symbol']
        token  = token_map.get(symbol)
        if not token:
            missing.append(symbol)
            continue

        candles = fetch_minute_candles(kite, token, alert['ts'])
        if not candles:
            missing.append(symbol)
            continue

        sim = simulate_trailing_stop(candles, alert['direction'])
        if not sim:
            continue

        results.append({**alert, **sim})
        logger.info(
            f"{alert['ts'].strftime('%m-%d %H:%M')} {alert['direction']:7s} "
            f"{symbol:12s} entry={sim['entry_price']:.2f} "
            f"exit={sim['exit_price']:.2f} "
            f"P&L={sim['pnl_pct']:+.2f}% ({sim['exit_reason']}, {sim['hold_minutes']}min)"
        )
        time.sleep(0.25)  # rate limit: 4 calls/sec

    # ── Print summary ─────────────────────────────────────────────────────────
    print("\n" + "="*90)
    print(f"ORDER FLOW ALERT BACKTEST  |  Trailing stop: {TRAILING_STOP_PCT*100:.1f}%  |  Dates: {BACKTEST_DATES}")
    print("="*90)

    if not results:
        print("No results to show.")
        return

    winners = [r for r in results if r['pnl_pct'] > 0]
    losers  = [r for r in results if r['pnl_pct'] <= 0]
    win_rate = len(winners) / len(results) * 100

    by_date = {}
    for r in results:
        d = str(r['ts'].date())
        by_date.setdefault(d, []).append(r)

    for d, day_results in sorted(by_date.items()):
        print(f"\n── {d} ──────────────────────────────────────────────────────────")
        print(f"{'Time':7s} {'Dir':7s} {'Symbol':12s} {'Score':5s} {'Entry':8s} {'Exit':8s} "
              f"{'P&L':7s} {'Minutes':7s} {'Exit':12s} Signals")
        print("-"*90)
        for r in sorted(day_results, key=lambda x: x['ts']):
            pnl_str = f"{r['pnl_pct']:+.2f}%"
            print(
                f"{r['ts'].strftime('%H:%M'):7s} "
                f"{r['direction']:7s} "
                f"{r['symbol']:12s} "
                f"{r['score']:5d} "
                f"{r['entry_price']:8.2f} "
                f"{r['exit_price']:8.2f} "
                f"{pnl_str:7s} "
                f"{r['hold_minutes']:7d} "
                f"{r['exit_reason']:12s} "
                f"{r['reasons']}"
            )
        day_wins = [r for r in day_results if r['pnl_pct'] > 0]
        avg_pnl  = sum(r['pnl_pct'] for r in day_results) / len(day_results)
        print(f"\n  {d}: {len(day_wins)}/{len(day_results)} winners | avg P&L: {avg_pnl:+.2f}%")

    print("\n" + "="*90)
    print(f"OVERALL:  {len(results)} trades  |  {len(winners)} wins / {len(losers)} losses  "
          f"|  win rate: {win_rate:.0f}%")
    avg_win  = sum(r['pnl_pct'] for r in winners) / len(winners) if winners else 0
    avg_loss = sum(r['pnl_pct'] for r in losers)  / len(losers)  if losers  else 0
    avg_all  = sum(r['pnl_pct'] for r in results) / len(results)
    print(f"          avg win: {avg_win:+.2f}%  |  avg loss: {avg_loss:+.2f}%  |  avg all: {avg_all:+.2f}%")

    stop_exits  = sum(1 for r in results if r['exit_reason'] == 'trailing_stop')
    close_exits = sum(1 for r in results if r['exit_reason'] == 'market_close')
    avg_hold = sum(r['hold_minutes'] for r in results) / len(results)
    print(f"          stop exits: {stop_exits}  |  market-close exits: {close_exits}  "
          f"|  avg hold: {avg_hold:.0f} min")

    if missing:
        print(f"\n  No data for: {sorted(set(missing))}")
    print("="*90)


if __name__ == '__main__':
    main()
