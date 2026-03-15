#!/usr/bin/env python3
"""
VWAP Mover — Nifty Trend Filter Comparison

All configs use: Max 1/stock, Trailing SL 0.3%, alert start 10:00, exit 15:20

Trend filter variants tested:
  G   Per-stock 9:25  : each stock's own price vs its own VWAP at 9:25 (current baseline)
  H1  Nifty vs Open   : Nifty price at 9:25 vs day's open  → BULL/BEAR
  H2  Nifty vs VWAP   : Nifty price at 9:25 vs Nifty VWAP (9:15–9:25) → BULL/BEAR
  H3  Nifty 1st candle: 9:15 candle direction (close > open?) → BULL/BEAR
  H4  Nifty H1 + Stock: Nifty H1 AND per-stock 9:25 must both agree
  H5  No filter       : no trend filter at all (pure VWAP touch, max 1/stock, TSL)

In H1–H3: Nifty BULL → only LONG trades allowed; Nifty BEAR → only SHORT trades allowed.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ── Fixed parameters ───────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
ALERT_START_TIME         = "10:00"
EXIT_TIME                = "15:20"
STOPLOSS_PCT             = 0.30
TREND_SNAP_TIME          = "09:25"
MAX_TRADES_PER_STOCK     = 1

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"
# ───────────────────────────────────────────────────────────────────────────────


@dataclass
class Config:
    name:  str
    label: str
    trend_mode: str   # "stock", "nifty_open", "nifty_vwap", "nifty_1st", "both", "none"


CONFIGS = [
    Config("G",  "Per-stock 9:25 (current)",         "stock"),
    Config("H1", "Nifty price vs Open  @9:25",        "nifty_open"),
    Config("H2", "Nifty price vs VWAP  @9:25",        "nifty_vwap"),
    Config("H3", "Nifty 1st candle direction @9:15",  "nifty_1st"),
    Config("H4", "Nifty Open + Per-stock (both)",     "both"),
    Config("H5", "No trend filter (baseline)",        "none"),
]


def load_lot_sizes() -> Dict[str, int]:
    try:
        with open(LOT_SIZES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def compute_charges(entry: float, exit_p: float, lot: int, direction: str) -> float:
    buy  = entry  if direction == "LONG" else exit_p
    sell = exit_p if direction == "LONG" else entry
    buy_t, sell_t = buy * lot, sell * lot
    total = buy_t + sell_t
    brok  = 40.0
    stt   = sell_t * 0.0002
    exc   = total  * 0.0000188
    sebi  = total  * 0.000001
    stamp = buy_t  * 0.00002
    gst   = (brok + exc) * 0.18
    return brok + stt + exc + sebi + stamp + gst


def compute_vwap(candles: List[Dict]) -> Optional[float]:
    if len(candles) < 2:
        return None
    cum_pv = cum_vol = 0.0
    for i, c in enumerate(candles):
        vol_delta = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv += c['price'] * vol_delta
        cum_vol += vol_delta
    return cum_pv / cum_vol if cum_vol > 0 else None


def get_price_at(candles: List[Dict], ts_str: str) -> Optional[float]:
    visible = [c for c in candles if c['timestamp'] <= ts_str]
    return visible[-1]['price'] if visible else None


def get_exit_trailing_sl(candles, entry_ts, entry_price, direction, sl_pct, exit_ts):
    sl     = entry_price * (1 - sl_pct/100) if direction == "LONG" else entry_price * (1 + sl_pct/100)
    peak   = entry_price
    trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak:
                peak = p
                sl   = peak * (1 - sl_pct / 100)
            if p <= sl:
                return sl, c['timestamp'], "TSL"
        else:
            if p < trough:
                trough = p
                sl     = trough * (1 + sl_pct / 100)
            if p >= sl:
                return sl, c['timestamp'], "TSL"
    eod = get_price_at(candles, exit_ts)
    return eod, exit_ts, "EOD"


def nifty_trend_for_day(nifty_candles: List[Dict], date: str, mode: str) -> Optional[str]:
    """
    Returns "LONG" (bullish) or "SHORT" (bearish) based on mode.

    H1 — nifty_open  : price at 9:25 vs day's open price
    H2 — nifty_vwap  : price at 9:25 vs VWAP of 9:15–9:25 candles
    H3 — nifty_1st   : direction of the very first 1-min candle (9:15 close vs 9:15 open)
    """
    snap_ts = f"{date} {TREND_SNAP_TIME}:00"

    if mode == "nifty_open":
        # Use the 'open' column (day's opening price) vs price at 9:25
        snap = [c for c in nifty_candles if c['timestamp'] <= snap_ts]
        if not snap:
            return None
        price_925 = snap[-1]['price']
        day_open  = snap[-1]['open']   # NSE day open stored in every row
        if day_open <= 0:
            return None
        return "LONG" if price_925 >= day_open else "SHORT"

    elif mode == "nifty_vwap":
        snap = [c for c in nifty_candles if c['timestamp'] <= snap_ts]
        vwap = compute_vwap(snap)
        if vwap is None:
            return None
        price_925 = snap[-1]['price']
        return "LONG" if price_925 >= vwap else "SHORT"

    elif mode == "nifty_1st":
        # First minute candle: if price rose from open → bullish, fell → bearish
        first_candles = [c for c in nifty_candles
                         if f"{date} 09:15:00" <= c['timestamp'] <= f"{date} 09:16:00"]
        if not first_candles:
            # Fallback: compare first available price to day open
            if nifty_candles:
                c0 = nifty_candles[0]
                return "LONG" if c0['price'] >= c0['open'] else "SHORT"
            return None
        c0 = first_candles[0]
        return "LONG" if c0['price'] >= c0['open'] else "SHORT"

    return None


def backtest_one_config(
    cfg: Config,
    dates: List[str],
    prev_close_by_date: Dict[str, Dict[str, float]],
    nifty_by_date: Dict[str, List[Dict]],
    lot_sizes: Dict[str, int],
) -> Dict:
    total_gross = total_charges = total_net = 0.0
    total_trades = total_wins = total_sl = 0
    green_days = red_days = 0
    daily_nets = []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    for date in dates:
        prev_close   = prev_close_by_date.get(date, {})
        nifty_candles = nifty_by_date.get(date, [])
        market_open  = f"{date} 09:15:00"
        market_close = f"{date} 15:30:00"
        alert_start  = f"{date} {ALERT_START_TIME}:00"
        exit_ts      = f"{date} {EXIT_TIME}:00"
        trend_snap   = f"{date} {TREND_SNAP_TIME}:00"

        # ── Nifty trend (H1/H2/H3/H4) ──
        nifty_dir: Optional[str] = None
        if cfg.trend_mode in ("nifty_open", "nifty_vwap", "nifty_1st", "both"):
            mode = "nifty_open" if cfg.trend_mode == "both" else cfg.trend_mode
            nifty_dir = nifty_trend_for_day(nifty_candles, date, mode)

        cur.execute("""
            SELECT DISTINCT timestamp FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC
        """, (market_open, market_close))
        timestamps = [r['timestamp'] for r in cur.fetchall()]
        if not timestamps:
            continue

        cur.execute("""
            SELECT symbol, timestamp, price, volume FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ? ORDER BY symbol, timestamp ASC
        """, (market_open, market_close))
        all_candles: Dict[str, List[Dict]] = {}
        for r in cur.fetchall():
            sym = r['symbol']
            if sym not in all_candles:
                all_candles[sym] = []
            all_candles[sym].append({
                'timestamp': r['timestamp'], 'price': r['price'], 'volume': r['volume']
            })

        # ── Per-stock 9:25 trend (mode = "stock" or "both") ──
        stock_trend_925: Dict[str, str] = {}
        if cfg.trend_mode in ("stock", "both"):
            for sym, candles in all_candles.items():
                snap = [c for c in candles if c['timestamp'] <= trend_snap]
                vwap = compute_vwap(snap)
                p    = get_price_at(snap, trend_snap)
                if vwap and p:
                    stock_trend_925[sym] = "LONG" if p >= vwap else "SHORT"

        cooldown:    Dict[str, datetime] = {}
        trade_count: Dict[str, int]      = defaultdict(int)
        last_top10:  List[str]           = []
        day_gross = day_charges = day_net = 0.0
        day_trades = day_wins = day_sl = 0

        for ts_str in timestamps:
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

            latest: Dict[str, Dict] = {}
            for sym, candles in all_candles.items():
                visible = [c for c in candles if c['timestamp'] <= ts_str]
                if visible:
                    latest[sym] = visible[-1]

            movers = []
            for sym, q in latest.items():
                if sym not in prev_close or prev_close[sym] <= 0:
                    continue
                pct = (q['price'] - prev_close[sym]) / prev_close[sym] * 100
                movers.append((sym, pct, q['price']))
            movers.sort(key=lambda x: abs(x[1]), reverse=True)
            top10 = movers[:TOP_N]
            top10_symbols = [s for s, _, _ in top10]
            if top10_symbols != last_top10:
                last_top10 = top10_symbols

            for rank, (symbol, pct_change, price) in enumerate(top10, 1):
                if ts_str < alert_start:
                    continue
                if trade_count[symbol] >= MAX_TRADES_PER_STOCK:
                    continue

                candles_so_far = [c for c in all_candles.get(symbol, [])
                                  if c['timestamp'] <= ts_str]
                vwap = compute_vwap(candles_so_far)
                if vwap is None:
                    continue

                if abs(price - vwap) / vwap * 100 > VWAP_TOUCH_THRESHOLD_PCT:
                    continue

                if symbol in cooldown:
                    if (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                        continue

                trade_dir = "LONG" if pct_change >= 0 else "SHORT"

                # ── Apply trend filter ──────────────────────────────────────
                if cfg.trend_mode == "stock":
                    s_dir = stock_trend_925.get(symbol)
                    if s_dir and s_dir != trade_dir:
                        continue

                elif cfg.trend_mode in ("nifty_open", "nifty_vwap", "nifty_1st"):
                    if nifty_dir and nifty_dir != trade_dir:
                        continue

                elif cfg.trend_mode == "both":
                    # Both Nifty AND per-stock must agree with trade_dir
                    if nifty_dir and nifty_dir != trade_dir:
                        continue
                    s_dir = stock_trend_925.get(symbol)
                    if s_dir and s_dir != trade_dir:
                        continue
                # "none" → no filter

                lot = lot_sizes.get(symbol, 1)
                ep, ets, reason = get_exit_trailing_sl(
                    all_candles.get(symbol, []), ts_str, price, trade_dir, STOPLOSS_PCT, exit_ts
                )
                if ep is None:
                    cooldown[symbol] = ts
                    trade_count[symbol] += 1
                    continue

                pnl_ps  = (ep - price) if trade_dir == "LONG" else (price - ep)
                gross   = pnl_ps * lot
                chg     = compute_charges(price, ep, lot, trade_dir)
                net     = gross - chg

                day_gross   += gross
                day_charges += chg
                day_net     += net
                day_trades  += 1
                if net > 0:
                    day_wins += 1
                if reason in ("TSL",) and net < 0:
                    day_sl += 1

                cooldown[symbol] = ts
                trade_count[symbol] += 1

        total_gross   += day_gross
        total_charges += day_charges
        total_net     += day_net
        total_trades  += day_trades
        total_wins    += day_wins
        total_sl      += day_sl
        daily_nets.append(day_net)
        green_days += 1 if day_net > 0 else 0
        red_days   += 1 if day_net < 0 else 0

    conn.close()

    win_rate  = total_wins / total_trades * 100 if total_trades else 0
    sl_rate   = total_sl  / total_trades * 100 if total_trades else 0
    green_pct = green_days / len(dates) * 100 if dates else 0
    avg_day   = total_net / len(dates) if dates else 0
    cum = peak = max_dd = 0.0
    for d in daily_nets:
        cum  += d
        peak  = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    return {
        'trades': total_trades, 'wins': total_wins, 'sl': total_sl,
        'win_rate': win_rate, 'sl_rate': sl_rate,
        'gross': total_gross, 'charges': total_charges, 'net': total_net,
        'green': green_days, 'red': red_days, 'green_pct': green_pct,
        'avg_day': avg_day, 'max_dd': max_dd,
    }


def main():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    dates = [r['d'] for r in cur.fetchall()]

    # Per-date prev_close from last candle of previous trading day
    print("  Building per-date prev_close...")
    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for i, date in enumerate(dates):
        if i == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = dates[i - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp = (SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp) = ?)
                  AND date(timestamp) = ?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}

    # Load Nifty candles per date
    print("  Loading Nifty candles...")
    nifty_by_date: Dict[str, List[Dict]] = {}
    for date in dates:
        cur.execute("""
            SELECT timestamp, price, open, high, low, volume FROM nifty_quotes
            WHERE date(timestamp) = ? ORDER BY timestamp ASC
        """, (date,))
        nifty_by_date[date] = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Print Nifty trend summary to show what each method produces
    print("\n  Nifty trend per date (H1=Open, H2=VWAP, H3=1st candle):")
    print(f"  {'Date':10}  {'Open':8}  {'@9:25':8}  {'H1':6}  {'H2':6}  {'H3':6}")
    print(f"  {'-'*10}  {'-'*8}  {'-'*8}  {'-'*6}  {'-'*6}  {'-'*6}")
    for date in dates:
        nc = nifty_by_date[date]
        h1 = nifty_trend_for_day(nc, date, "nifty_open")
        h2 = nifty_trend_for_day(nc, date, "nifty_vwap")
        h3 = nifty_trend_for_day(nc, date, "nifty_1st")
        snap_ts = f"{date} {TREND_SNAP_TIME}:00"
        snap = [c for c in nc if c['timestamp'] <= snap_ts]
        price_925 = snap[-1]['price'] if snap else 0
        day_open  = snap[-1]['open']  if snap else 0
        icon = "🟢" if h1 == "LONG" else "🔴"
        print(f"  {icon} {date}  {day_open:8.2f}  {price_925:8.2f}  "
              f"{h1 or 'N/A':6}  {h2 or 'N/A':6}  {h3 or 'N/A':6}")

    # Run all configs
    print("\n" + "=" * 115)
    print(f"NIFTY TREND FILTER COMPARISON  ({len(dates)} trading days: {dates[0]} → {dates[-1]})")
    print(f"Trailing SL={STOPLOSS_PCT}%  |  Max 1/stock  |  alert_start={ALERT_START_TIME}  |  exit={EXIT_TIME}")
    print("=" * 115)

    results = {}
    for cfg in CONFIGS:
        print(f"  Running {cfg.name}: {cfg.label} ...", end="", flush=True)
        results[cfg.name] = backtest_one_config(cfg, dates, prev_close_by_date, nifty_by_date, lot_sizes)
        r = results[cfg.name]
        print(f"  net=₹{r['net']:>+,.0f}  ({r['trades']} trades, {r['green']}/34 green)")

    # Summary table
    print("\n" + "=" * 115)
    print("SUMMARY TABLE")
    print("=" * 115)
    print(f"  {'':4}  {'Config':35}  {'Trades':6}  {'Win%':5}  {'Green':6}  "
          f"{'Gross':>12}  {'Charges':>9}  {'Net P&L':>12}  {'Avg/Day':>9}  {'MaxDD':>10}")
    print(f"  {'─'*4}  {'─'*35}  {'─'*6}  {'─'*5}  {'─'*6}  "
          f"{'─'*12}  {'─'*9}  {'─'*12}  {'─'*9}  {'─'*10}")

    baseline = results['G']['net']
    best_net  = max(r['net'] for r in results.values())
    for cfg in CONFIGS:
        r = results[cfg.name]
        delta = r['net'] - baseline
        delta_str = f"({delta:>+,.0f})" if cfg.name != 'G' else ""
        star = " ★" if r['net'] == best_net else ""
        print(f"  {cfg.name:4}  {cfg.label:35}  {r['trades']:6d}  {r['win_rate']:4.1f}%  "
              f"{r['green']:2d}/34  "
              f"₹{r['gross']:>+11,.0f}  ₹{r['charges']:>8,.0f}  ₹{r['net']:>+11,.0f}  "
              f"₹{r['avg_day']:>+8,.0f}  ₹{r['max_dd']:>9,.0f}  {delta_str}{star}")

    print(f"\n  ★ = best net P&L   |  delta vs Config G (per-stock baseline)")

    # Detail for best config
    best_cfg_name = max(results, key=lambda k: results[k]['net'])
    best_cfg = next(c for c in CONFIGS if c.name == best_cfg_name)
    print(f"\n  Best config: [{best_cfg_name}] {best_cfg.label}")
    r = results[best_cfg_name]
    print(f"  Win rate: {r['win_rate']:.1f}%  |  Green days: {r['green']}/34 ({r['green_pct']:.0f}%)")
    print(f"  Gross: ₹{r['gross']:>+,.0f}  |  Charges: ₹{r['charges']:>,.0f}  |  Net: ₹{r['net']:>+,.0f}")
    print(f"  Avg/day: ₹{r['avg_day']:>+,.0f}  |  Max drawdown: ₹{r['max_dd']:>,.0f}")


if __name__ == "__main__":
    main()
