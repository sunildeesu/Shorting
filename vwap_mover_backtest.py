#!/usr/bin/env python3
"""
Backtest VWAP Mover Monitor logic on historical 1-min data from central DB.
Replays every minute candle for a given date and simulates alerts + P&L.

Trade logic:
  - Stock UP (pct_change > 0): pulled back to VWAP → LONG at touch price, exit at 3:20 PM
  - Stock DN (pct_change < 0): bounced up to VWAP  → SHORT at touch price, exit at 3:20 PM
  - Lot size from data/lot_sizes.json (falls back to 1 if symbol missing)
  - Only the FIRST touch per cooldown window is a trade entry; re-entries after cooldown expiry
    are treated as fresh trades.

Charges (Zerodha NSE F&O rates, per round-trip lot):
  Brokerage         : ₹20 × 2 legs = ₹40 flat
  STT               : 0.02% on sell-side turnover only
  Exchange charges  : 0.00188% on total turnover (NSE futures rate)
  SEBI charges      : ₹10 per crore = 0.000001 × total turnover
  Stamp duty        : 0.002% on buy-side turnover
  GST               : 18% on (brokerage + exchange charges)
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ── Parameters ─────────────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
BACKTEST_DATE            = "2026-03-13"
MARKET_OPEN_STR          = f"{BACKTEST_DATE} 09:15:00"   # VWAP calc starts here
ALERT_START_STR          = f"{BACKTEST_DATE} 10:00:00"   # No alerts before this
EXIT_TIME_STR            = f"{BACKTEST_DATE} 15:20:00"   # Exit at 3:20 PM
MARKET_CLOSE_STR         = f"{BACKTEST_DATE} 15:30:00"
STOPLOSS_PCT             = 0.30                           # 0 = disabled
MAX_TRADES_PER_STOCK     = 3

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"
# ───────────────────────────────────────────────────────────────────────────────


def load_lot_sizes() -> Dict[str, int]:
    try:
        with open(LOT_SIZES_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load lot sizes ({e}) — defaulting to 1")
        return {}


def compute_charges(entry_price: float, exit_price: float, lot_size: int, trade_dir: str) -> Dict:
    """
    Compute NSE F&O trading charges (Zerodha rates) for one round-trip lot.

    NSE Futures charge schedule (2024–25):
      Brokerage        : ₹20 per executed order (flat)
      STT              : 0.02% on sell-side turnover
      Exchange charges : 0.00188% on total turnover
      SEBI charges     : ₹10 per crore (0.000001 × turnover)
      Stamp duty       : 0.002% on buy-side turnover
      GST              : 18% on (brokerage + exchange charges)
    """
    qty = lot_size

    buy_price  = entry_price if trade_dir == "LONG" else exit_price
    sell_price = exit_price  if trade_dir == "LONG" else entry_price

    buy_turnover   = buy_price  * qty
    sell_turnover  = sell_price * qty
    total_turnover = buy_turnover + sell_turnover

    brokerage       = 40.0                                   # ₹20 × 2 legs
    stt             = sell_turnover * 0.0002                 # 0.02% sell side
    exchange_charge = total_turnover * 0.0000188             # 0.00188% both sides
    sebi_charge     = total_turnover * 0.000001              # ₹10/crore
    stamp_duty      = buy_turnover   * 0.00002               # 0.002% buy side
    gst             = (brokerage + exchange_charge) * 0.18   # 18%

    total = brokerage + stt + exchange_charge + sebi_charge + stamp_duty + gst

    return {
        'brokerage':       round(brokerage,       2),
        'stt':             round(stt,             2),
        'exchange_charge': round(exchange_charge, 2),
        'sebi_charge':     round(sebi_charge,     4),
        'stamp_duty':      round(stamp_duty,      2),
        'gst':             round(gst,             2),
        'total':           round(total,           2),
    }


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
    """Return price at or just before ts_str."""
    visible = [c for c in candles if c['timestamp'] <= ts_str]
    return visible[-1]['price'] if visible else None


def get_exit_with_sl(
    candles: List[Dict],
    entry_ts: str,
    entry_price: float,
    trade_dir: str,
    sl_pct: float,
    exit_time_str: str,
) -> Tuple[float, str, str]:
    """
    Walk candles after entry. If SL hit, exit there; else exit at exit_time_str.
    Returns (exit_price, exit_ts, exit_reason).
    """
    if sl_pct <= 0:
        price = get_price_at(candles, exit_time_str)
        return price, exit_time_str, "EOD"

    sl_price = (entry_price * (1 - sl_pct / 100) if trade_dir == "LONG"
                else entry_price * (1 + sl_pct / 100))

    after = [c for c in candles if entry_ts < c['timestamp'] <= exit_time_str]
    for c in after:
        if trade_dir == "LONG" and c['price'] <= sl_price:
            return sl_price, c['timestamp'], "SL"
        if trade_dir == "SHORT" and c['price'] >= sl_price:
            return sl_price, c['timestamp'], "SL"

    price = get_price_at(candles, exit_time_str)
    return price, exit_time_str, "EOD"


def run_backtest():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Load prev_close
    cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
    prev_close = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
    print(f"Loaded prev_close for {len(prev_close)} symbols")

    # All minute timestamps for the day
    cur.execute("""
        SELECT DISTINCT timestamp FROM stock_quotes
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC
    """, (MARKET_OPEN_STR, MARKET_CLOSE_STR))
    all_timestamps = [r['timestamp'] for r in cur.fetchall()]
    print(f"Timestamps: {len(all_timestamps)}  ({all_timestamps[0]} → {all_timestamps[-1]})")

    # Prefetch all candles once
    cur.execute("""
        SELECT symbol, timestamp, price, volume FROM stock_quotes
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY symbol, timestamp ASC
    """, (MARKET_OPEN_STR, MARKET_CLOSE_STR))
    all_rows = cur.fetchall()
    conn.close()

    all_candles: Dict[str, List[Dict]] = {}
    for r in all_rows:
        sym = r['symbol']
        if sym not in all_candles:
            all_candles[sym] = []
        all_candles[sym].append({
            'timestamp': r['timestamp'], 'price': r['price'], 'volume': r['volume']
        })

    print(f"Loaded {len(all_rows):,} candles for {len(all_candles)} symbols\n")

    # ── Simulation ─────────────────────────────────────────────────────────────
    alerts: List[Dict] = []
    cooldown: Dict[str, datetime] = {}
    trade_count: Dict[str, int] = defaultdict(int)
    last_top10: List[str] = []

    print("=" * 100)
    print(f"BACKTEST: {BACKTEST_DATE}  |  threshold={VWAP_TOUCH_THRESHOLD_PCT}%  "
          f"|  cooldown={ALERT_COOLDOWN_MINUTES}min  |  TOP_N={TOP_N}  "
          f"|  alert_start={ALERT_START_STR[11:16]}  |  exit={EXIT_TIME_STR[11:16]}  "
          f"|  SL={STOPLOSS_PCT}%  |  max_trades/stock={MAX_TRADES_PER_STOCK}")
    print("=" * 100)

    for ts_str in all_timestamps:
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

        # Latest price per symbol
        latest: Dict[str, Dict] = {}
        for sym, candles in all_candles.items():
            visible = [c for c in candles if c['timestamp'] <= ts_str]
            if visible:
                latest[sym] = visible[-1]

        # Top movers by abs(% change from prev_close)
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

        # VWAP touch check
        for rank, (symbol, pct_change, price) in enumerate(top10, 1):
            if ts_str < ALERT_START_STR:
                continue

            if trade_count[symbol] >= MAX_TRADES_PER_STOCK:
                continue

            candles_so_far = [c for c in all_candles.get(symbol, []) if c['timestamp'] <= ts_str]
            vwap = compute_vwap(candles_so_far)
            if vwap is None:
                continue

            distance_pct = abs(price - vwap) / vwap * 100
            if distance_pct > VWAP_TOUCH_THRESHOLD_PCT:
                continue

            # Cooldown check
            if symbol in cooldown:
                elapsed = (ts - cooldown[symbol]).total_seconds() / 60
                if elapsed < ALERT_COOLDOWN_MINUTES:
                    continue

            trade_dir = "LONG" if pct_change >= 0 else "SHORT"
            lot_size  = lot_sizes.get(symbol, 1)

            exit_price, exit_ts, exit_reason = get_exit_with_sl(
                all_candles.get(symbol, []), ts_str, price,
                trade_dir, STOPLOSS_PCT, EXIT_TIME_STR
            )

            if exit_price is not None:
                if trade_dir == "LONG":
                    pnl_per_share = exit_price - price
                else:
                    pnl_per_share = price - exit_price
                pnl_pct      = pnl_per_share / price * 100
                gross_pnl    = pnl_per_share * lot_size
                charges      = compute_charges(price, exit_price, lot_size, trade_dir)
                net_pnl      = gross_pnl - charges['total']
            else:
                pnl_per_share = pnl_pct = gross_pnl = net_pnl = None
                charges       = None

            alert = {
                'time':         ts_str,
                'rank':         rank,
                'symbol':       symbol,
                'pct_change':   pct_change,
                'entry_price':  price,
                'vwap':         vwap,
                'distance_pct': distance_pct,
                'candles':      len(candles_so_far),
                'trade_dir':    trade_dir,
                'lot_size':     lot_size,
                'exit_price':   exit_price,
                'exit_reason':  exit_reason,
                'pnl_per_share': pnl_per_share,
                'pnl_pct':       pnl_pct,
                'gross_pnl':     gross_pnl,
                'charges':       charges,
                'net_pnl':       net_pnl,
            }
            alerts.append(alert)
            cooldown[symbol] = ts
            trade_count[symbol] += 1

            net_str = (f"  net=₹{net_pnl:+,.0f}  (gross=₹{gross_pnl:+,.0f}  chg=₹{charges['total']:.0f})"
                       if net_pnl is not None else "  net=N/A")
            win = "✅" if (net_pnl or 0) > 0 else "❌"
            sl_tag = f" [{exit_reason}]" if exit_reason == "SL" else ""
            print(f"{win} {ts_str[11:16]}  #{rank} {symbol:12s}  "
                  f"{'▲' if trade_dir=='LONG' else '▼'} {trade_dir:5s}  "
                  f"lot={lot_size:4d}  entry=₹{price:.2f}  VWAP=₹{vwap:.2f}  "
                  f"exit=₹{exit_price:.2f}{sl_tag}"
                  f"{net_str}")

    # ── P&L Summary ────────────────────────────────────────────────────────────
    valid = [a for a in alerts if a['net_pnl'] is not None]
    winners = [a for a in valid if a['net_pnl'] > 0]
    losers  = [a for a in valid if a['net_pnl'] < 0]

    total_gross    = sum(a['gross_pnl']        for a in valid)
    total_charges  = sum(a['charges']['total'] for a in valid)
    total_net      = sum(a['net_pnl']          for a in valid)

    # Charges breakdown
    total_brokerage       = sum(a['charges']['brokerage']       for a in valid)
    total_stt             = sum(a['charges']['stt']             for a in valid)
    total_exchange_charge = sum(a['charges']['exchange_charge'] for a in valid)
    total_sebi            = sum(a['charges']['sebi_charge']     for a in valid)
    total_stamp           = sum(a['charges']['stamp_duty']      for a in valid)
    total_gst             = sum(a['charges']['gst']             for a in valid)

    sl_hits = sum(1 for a in valid if a['exit_reason'] == 'SL')

    print("\n" + "=" * 100)
    print(f"P&L SUMMARY  ({BACKTEST_DATE})  —  SL={STOPLOSS_PCT}%  |  exit={EXIT_TIME_STR[11:16]}")
    print("=" * 100)
    if valid:
        print(f"  Trades          : {len(valid)}  (SL hits: {sl_hits})")
        print(f"  Winners         : {len(winners)}  ({len(winners)/len(valid)*100:.0f}%)")
        print(f"  Losers          : {len(losers)}  ({len(losers)/len(valid)*100:.0f}%)")
        print()
        print(f"  Gross P&L       : ₹{total_gross:>+12,.2f}")
        print(f"  ─── Charges ───────────────────────────")
        print(f"  Brokerage       : ₹{total_brokerage:>10,.2f}")
        print(f"  STT             : ₹{total_stt:>10,.2f}")
        print(f"  Exchange charges: ₹{total_exchange_charge:>10,.2f}")
        print(f"  SEBI charges    : ₹{total_sebi:>10,.4f}")
        print(f"  Stamp duty      : ₹{total_stamp:>10,.2f}")
        print(f"  GST (18%)       : ₹{total_gst:>10,.2f}")
        print(f"  Total charges   : ₹{total_charges:>10,.2f}")
        print(f"  ────────────────────────────────────────")
        print(f"  NET P&L         : ₹{total_net:>+12,.2f}  ← after all charges")
        print()
        if winners:
            print(f"  Avg winner (net): ₹{sum(a['net_pnl'] for a in winners)/len(winners):+,.0f}")
        if losers:
            print(f"  Avg loser  (net): ₹{sum(a['net_pnl'] for a in losers)/len(losers):+,.0f}")
        best  = max(valid, key=lambda a: a['net_pnl'])
        worst = min(valid, key=lambda a: a['net_pnl'])
        print(f"  Best trade      : {best['symbol']} @ {best['time'][11:16]}  net=₹{best['net_pnl']:+,.0f}")
        print(f"  Worst trade     : {worst['symbol']} @ {worst['time'][11:16]}  net=₹{worst['net_pnl']:+,.0f}")

    # Detail table
    print(f"\n  {'Time':5}  {'Symbol':12}  {'Dir':5}  {'Lot':4}  {'Entry':9}  {'Exit':9}  "
          f"{'Exit':4}  {'Gross':10}  {'Charges':8}  {'Net':10}  {'Result'}")
    print(f"  {'-'*5}  {'-'*12}  {'-'*5}  {'-'*4}  {'-'*9}  {'-'*9}  "
          f"{'-'*4}  {'-'*10}  {'-'*8}  {'-'*10}  {'-'*6}")
    for a in valid:
        result = "WIN" if a['net_pnl'] > 0 else "LOSS"
        print(f"  {a['time'][11:16]}  {a['symbol']:12}  "
              f"{'▲' if a['trade_dir']=='LONG' else '▼'} {a['trade_dir']:4}  "
              f"{a['lot_size']:4d}  "
              f"₹{a['entry_price']:8.2f}  ₹{a['exit_price']:8.2f}  "
              f"{a['exit_reason']:4s}  "
              f"₹{a['gross_pnl']:>+9,.0f}  "
              f"₹{a['charges']['total']:>7,.0f}  "
              f"₹{a['net_pnl']:>+9,.0f}  {result}")


if __name__ == "__main__":
    run_backtest()
