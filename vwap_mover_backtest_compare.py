#!/usr/bin/env python3
"""
VWAP Mover Strategy — Multi-Config Comparison Backtest (34 trading days)

Configs tested:
  A  Baseline        : current settings (SL=0.3%, max=3/stock, no filters)
  B  Trend @9:25     : only trade in direction of 9:25 price-vs-VWAP trend
  C  Max-move filter : exclude stocks with abs(pct_change) > 3% at entry
  D  Max 1/stock     : cap entries per stock per day at 1
  E  Prev-candle     : only enter if previous candle moved TOWARD VWAP
  F  B+C+D+E         : all fixes combined
  G  B+D             : trend filter + max 1/stock (minimal combo)

Exit modes (controlled by TARGET_PCT):
  TARGET_PCT = 0   → hold until 3:20 PM (original behaviour)
  TARGET_PCT = 2.0 → exit at 2% profit OR SL OR 3:20 PM, whichever first
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ── Fixed parameters (same for all configs) ────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
ALERT_START_TIME         = "10:00"
EXIT_TIME                = "15:20"
STOPLOSS_PCT             = 0.30
TARGET_PCT               = 0        # take-profit target; 0 = disabled
TRAILING_SL              = True     # trail the SL as price moves in profit direction
TREND_SNAP_TIME          = "09:25"  # time to lock intraday trend direction

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"
# ───────────────────────────────────────────────────────────────────────────────


@dataclass
class Config:
    name: str
    label: str
    use_trend_filter: bool    = False  # B: only trade in 9:25 trend direction
    max_pct_move: float       = 999.0  # C: skip stocks with abs(pct) > this
    max_trades_per_stock: int = 3      # D: cap per-stock trades/day
    use_prev_candle: bool     = False  # E: require prev candle toward VWAP


CONFIGS = [
    Config("A", "Baseline (current)",          False, 999, 3, False),
    Config("B", "Trend @9:25",                 True,  999, 3, False),
    Config("C", "Max-move ≤3%",                False, 3.0, 3, False),
    Config("D", "Max 1/stock",                 False, 999, 1, False),
    Config("E", "Prev-candle toward VWAP",     False, 999, 3, True),
    Config("F", "B+C+D+E (all fixes)",         True,  3.0, 1, True),
    Config("G", "B+D (trend + max 1)",         True,  999, 1, False),
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
    buy_t  = buy  * lot
    sell_t = sell * lot
    total  = buy_t + sell_t
    brok   = 40.0
    stt    = sell_t * 0.0002
    exc    = total  * 0.0000188
    sebi   = total  * 0.000001
    stamp  = buy_t  * 0.00002
    gst    = (brok + exc) * 0.18
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


def get_exit_with_sl(candles, entry_ts, entry_price, direction,
                     sl_pct, target_pct, exit_ts, trailing: bool = False):
    """
    Walk candles after entry. Exit at whichever triggers first:
      1. Profit target  (target_pct > 0)
      2. Stop loss      (sl_pct > 0)  — fixed or trailing
      3. EOD            (exit_ts)

    Trailing SL (trailing=True):
      LONG  — SL trails 0.3% below the highest price seen so far.
              Once price sets a new high, the SL ratchets up and never comes back down.
      SHORT — SL trails 0.3% above the lowest price seen so far.
    Returns (exit_price, exit_ts, reason).
    """
    if sl_pct <= 0 and target_pct <= 0:
        return get_price_at(candles, exit_ts), exit_ts, "EOD"

    # Initialise SL at entry
    sl_price = None
    if sl_pct > 0:
        sl_price = (entry_price * (1 - sl_pct / 100) if direction == "LONG"
                    else entry_price * (1 + sl_pct / 100))

    target_price = None
    if target_pct > 0:
        target_price = (entry_price * (1 + target_pct / 100) if direction == "LONG"
                        else entry_price * (1 - target_pct / 100))

    # Peak/trough for trailing SL
    peak   = entry_price   # LONG: highest price seen
    trough = entry_price   # SHORT: lowest price seen

    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']

        if direction == "LONG":
            # Ratchet SL up as new highs are set
            if trailing and sl_pct > 0 and p > peak:
                peak     = p
                sl_price = peak * (1 - sl_pct / 100)
            if target_price and p >= target_price:
                return target_price, c['timestamp'], "TGT"
            if sl_price and p <= sl_price:
                return sl_price, c['timestamp'], "TSL" if trailing else "SL"
        else:
            # Ratchet SL down as new lows are set
            if trailing and sl_pct > 0 and p < trough:
                trough   = p
                sl_price = trough * (1 + sl_pct / 100)
            if target_price and p <= target_price:
                return target_price, c['timestamp'], "TGT"
            if sl_price and p >= sl_price:
                return sl_price, c['timestamp'], "TSL" if trailing else "SL"

    return get_price_at(candles, exit_ts), exit_ts, "EOD"


def prev_candle_toward_vwap(candles: List[Dict], ts_str: str, direction: str) -> bool:
    """
    Check if the candle immediately before ts_str moved toward VWAP.
    For LONG (stock above VWAP from above, pulling back): prev candle should be DOWN (price fell).
    For SHORT (stock below VWAP, bouncing up): prev candle should be UP (price rose).
    """
    visible = [c for c in candles if c['timestamp'] <= ts_str]
    if len(visible) < 2:
        return False
    prev, curr = visible[-2], visible[-1]
    if direction == "LONG":
        return curr['price'] < prev['price']   # falling toward VWAP
    else:
        return curr['price'] > prev['price']   # rising toward VWAP


def backtest_one_config(
    cfg: Config,
    dates: List[str],
    prev_close_by_date: Dict[str, Dict[str, float]],
    lot_sizes: Dict[str, int],
    db_conn_str: str,
) -> Dict:
    """Run all dates for one config, return summary stats."""
    total_gross = total_charges = total_net = 0.0
    total_trades = total_wins = total_sl = total_tgt = 0
    green_days = red_days = 0
    daily_nets = []

    conn = sqlite3.connect(db_conn_str)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    for date in dates:
        prev_close = prev_close_by_date.get(date, {})
        market_open  = f"{date} 09:15:00"
        market_close = f"{date} 15:30:00"
        alert_start  = f"{date} {ALERT_START_TIME}:00"
        exit_ts      = f"{date} {EXIT_TIME}:00"
        trend_snap   = f"{date} {TREND_SNAP_TIME}:00"

        cur.execute("""
            SELECT DISTINCT timestamp FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (market_open, market_close))
        timestamps = [r['timestamp'] for r in cur.fetchall()]
        if not timestamps:
            continue

        cur.execute("""
            SELECT symbol, timestamp, price, volume FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY symbol, timestamp ASC
        """, (market_open, market_close))
        all_candles: Dict[str, List[Dict]] = {}
        for r in cur.fetchall():
            sym = r['symbol']
            if sym not in all_candles:
                all_candles[sym] = []
            all_candles[sym].append({
                'timestamp': r['timestamp'], 'price': r['price'], 'volume': r['volume']
            })

        # Compute 9:25 trend direction per symbol (for trend-filter config)
        trend_dir_925: Dict[str, str] = {}
        if cfg.use_trend_filter:
            for sym, candles in all_candles.items():
                snap_candles = [c for c in candles if c['timestamp'] <= trend_snap]
                vwap_925 = compute_vwap(snap_candles)
                price_925 = get_price_at(snap_candles, trend_snap)
                if vwap_925 and price_925:
                    trend_dir_925[sym] = "LONG" if price_925 >= vwap_925 else "SHORT"

        cooldown: Dict[str, datetime] = {}
        trade_count: Dict[str, int]   = defaultdict(int)
        last_top10: List[str]         = []
        day_gross = day_charges = day_net = 0.0
        day_trades = day_wins = day_sl = day_tgt = 0

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
                if trade_count[symbol] >= cfg.max_trades_per_stock:
                    continue

                # C: Max-move filter
                if abs(pct_change) > cfg.max_pct_move:
                    continue

                candles_so_far = [c for c in all_candles.get(symbol, []) if c['timestamp'] <= ts_str]
                vwap = compute_vwap(candles_so_far)
                if vwap is None:
                    continue

                distance_pct = abs(price - vwap) / vwap * 100
                if distance_pct > VWAP_TOUCH_THRESHOLD_PCT:
                    continue

                if symbol in cooldown:
                    if (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                        continue

                trade_dir = "LONG" if pct_change >= 0 else "SHORT"

                # B: Trend filter — trade direction must match 9:25 trend
                if cfg.use_trend_filter:
                    snap_dir = trend_dir_925.get(symbol)
                    if snap_dir and snap_dir != trade_dir:
                        continue

                # E: Prev-candle toward VWAP
                if cfg.use_prev_candle:
                    if not prev_candle_toward_vwap(candles_so_far, ts_str, trade_dir):
                        continue

                lot = lot_sizes.get(symbol, 1)
                ep, ets, reason = get_exit_with_sl(
                    all_candles.get(symbol, []), ts_str, price, trade_dir,
                    STOPLOSS_PCT, TARGET_PCT, exit_ts, trailing=TRAILING_SL
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
                if reason in ("SL", "TSL") and net < 0:
                    day_sl += 1
                if reason in ("TSL", "TGT") and net > 0:
                    day_tgt += 1

                cooldown[symbol] = ts
                trade_count[symbol] += 1

        total_gross   += day_gross
        total_charges += day_charges
        total_net     += day_net
        total_trades  += day_trades
        total_wins    += day_wins
        total_sl      += day_sl
        total_tgt     += day_tgt
        daily_nets.append(day_net)
        if day_net > 0:
            green_days += 1
        elif day_net < 0:
            red_days += 1

    conn.close()

    win_rate = total_wins / total_trades * 100 if total_trades else 0
    sl_rate  = total_sl  / total_trades * 100 if total_trades else 0
    tgt_rate = total_tgt / total_trades * 100 if total_trades else 0
    green_pct = green_days / len(dates) * 100 if dates else 0
    avg_per_day = total_net / len(dates) if dates else 0
    max_dd = 0.0
    peak = 0.0
    cum = 0.0
    for d in daily_nets:
        cum += d
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    return {
        'trades':      total_trades,
        'wins':        total_wins,
        'sl_hits':     total_sl,
        'tgt_hits':    total_tgt,
        'win_rate':    win_rate,
        'sl_rate':     sl_rate,
        'tgt_rate':    tgt_rate,
        'gross':       total_gross,
        'charges':     total_charges,
        'net':         total_net,
        'green_days':  green_days,
        'red_days':    red_days,
        'green_pct':   green_pct,
        'avg_per_day': avg_per_day,
        'max_dd':      max_dd,
    }


def main():
    lot_sizes  = load_lot_sizes()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    dates = [r['d'] for r in cur.fetchall()]

    # Build per-date prev_close: last candle price from the previous trading day.
    # This is correct for any backtest date, not just the most recent.
    print("  Building per-date prev_close from historical candles...")
    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for i, date in enumerate(dates):
        if i == 0:
            # No prior day in DB — fall back to stored prev_close_prices
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = dates[i - 1]
            cur.execute("""
                SELECT symbol, price
                FROM stock_quotes
                WHERE timestamp = (
                    SELECT MAX(timestamp) FROM stock_quotes
                    WHERE date(timestamp) = ?
                )
                AND date(timestamp) = ?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}
    conn.close()
    print(f"  Done. Coverage: {[len(v) for v in prev_close_by_date.values()]} symbols/day\n")

    if TRAILING_SL:
        exit_label = f"TRAILING SL={STOPLOSS_PCT}% (ratchets with price) + EOD 3:20"
    elif TARGET_PCT > 0:
        exit_label = f"TARGET={TARGET_PCT}%  |  SL={STOPLOSS_PCT}%"
    else:
        exit_label = f"SL={STOPLOSS_PCT}%  |  EOD exit"
    print("=" * 115)
    print(f"VWAP MOVER STRATEGY — CONFIG COMPARISON  ({len(dates)} trading days: {dates[0]} → {dates[-1]})")
    print(f"Exit: {exit_label}  |  cooldown={ALERT_COOLDOWN_MINUTES}min  |  threshold={VWAP_TOUCH_THRESHOLD_PCT}%  |  TOP_N={TOP_N}")
    print("=" * 115)

    results = {}
    for cfg in CONFIGS:
        print(f"  Running config {cfg.name}: {cfg.label} ...", end="", flush=True)
        results[cfg.name] = backtest_one_config(cfg, dates, prev_close_by_date, lot_sizes, DB_PATH)
        r = results[cfg.name]
        print(f"  done  → net=₹{r['net']:>+,.0f}")

    # ── Comparison table ────────────────────────────────────────────────────────
    print("\n" + "=" * 115)
    print("SUMMARY COMPARISON TABLE")
    print("=" * 115)
    tsl_col = "TSL%" if TRAILING_SL else "TGT%"
    print(f"  {'':2}  {'Config':30}  {'Trades':6}  {'Win%':5}  {'SL%':5}  {tsl_col:5}  "
          f"{'Green':6}  {'Gross':>12}  {'Charges':>9}  {'Net P&L':>12}  {'Avg/Day':>9}  {'MaxDD':>10}")
    print(f"  {'─'*2}  {'─'*30}  {'─'*6}  {'─'*5}  {'─'*5}  {'─'*5}  "
          f"{'─'*6}  {'─'*12}  {'─'*9}  {'─'*12}  {'─'*9}  {'─'*10}")

    baseline_net = results['A']['net']
    for cfg in CONFIGS:
        r = results[cfg.name]
        delta = r['net'] - baseline_net
        delta_str = f"({delta:>+,.0f})" if cfg.name != 'A' else "          "
        best_marker = " ★" if r['net'] == max(res['net'] for res in results.values()) else ""
        print(f"  {cfg.name:2}  {cfg.label:30}  {r['trades']:6d}  {r['win_rate']:4.1f}%  "
              f"{r['sl_rate']:4.1f}%  {r['tgt_rate']:4.1f}%  "
              f"{r['green_days']:2d}/34  "
              f"₹{r['gross']:>+11,.0f}  "
              f"₹{r['charges']:>8,.0f}  "
              f"₹{r['net']:>+11,.0f}  "
              f"₹{r['avg_per_day']:>+8,.0f}  "
              f"₹{r['max_dd']:>9,.0f}  "
              f"{delta_str}{best_marker}")

    tsl_note = "TSL% = trades where trailing SL locked in profit" if TRAILING_SL else "TGT% = trades that hit profit target"
    print(f"\n  ★ = best net P&L   |  {tsl_note}")
    print(f"\n  Note: charges include brokerage ₹40/trade, STT 0.02% sell-side,")
    print(f"        exchange 0.00188%, SEBI ₹10/cr, stamp duty 0.002% buy-side, GST 18%")

    # ── Per-config deep dive ────────────────────────────────────────────────────
    print("\n" + "=" * 115)
    print("KEY METRICS DETAIL")
    print("=" * 115)
    for cfg in CONFIGS:
        r = results[cfg.name]
        print(f"\n  [{cfg.name}] {cfg.label}")
        tsl_lbl = "TSL-win" if TRAILING_SL else "TGT"
        print(f"       Trades/day  : {r['trades']/len(dates):.1f}  |  Win rate: {r['win_rate']:.1f}%  |  SL/loss rate: {r['sl_rate']:.1f}%  |  {tsl_lbl} rate: {r['tgt_rate']:.1f}%")
        print(f"       Green days  : {r['green_days']}/34 ({r['green_pct']:.0f}%)  |  Red: {r['red_days']}/34")
        print(f"       Gross P&L   : ₹{r['gross']:>+,.0f}")
        print(f"       Charges     : ₹{r['charges']:>,.0f}  ({r['charges']/abs(r['gross'])*100:.1f}% of |gross|)" if r['gross'] != 0 else "")
        print(f"       Net P&L     : ₹{r['net']:>+,.0f}  (avg ₹{r['avg_per_day']:>+,.0f}/day)")
        print(f"       Max drawdown: ₹{r['max_dd']:>,.0f}")


if __name__ == "__main__":
    main()
