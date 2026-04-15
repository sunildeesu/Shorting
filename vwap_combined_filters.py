#!/usr/bin/env python3
"""
VWAP Mover — Combined Multi-Filter Backtest (Tasks 2–6)
========================================================
Window:  10:00 AM – 2:30 PM (entries); exits always at 14:30 or TSL
Exit:    TSL 0.5% trailing, EOD fallback at 2:30 PM
Last 30 trading days.

Configs compared:
  A: No filters (baseline — TSL 0.5%, entries 10:00–14:30)
  B: Volume filter only  — skip if touch-candle volume > VOL_RATIO_THRESHOLD × avg
  C: Approach + Nifty    — skip if approach < APPROACH_MIN candles OR Nifty hostile
  D: All three combined  — Volume + Approach + Nifty
  E: Time-of-day only    — entries restricted to 10:30–13:30 (avoid open noise + late reversals)
  F: Time + Vol          — time restriction + volume filter (best of T2 + T3)
  G: Trend alignment     — LONG only if price > 5-day avg close; SHORT only if below
  H: Time + Trend        — E + G (best Task 3 + Task 4)
  I: RSI confirmation    — LONG: RSI 30–55 at touch; SHORT: RSI 45–70 at touch
  J: Time + RSI          — E + I
  K: Trend + RSI         — G + I
  L: ATR TSL only        — 1×ATR(14) trailing SL (no fixed target)
  M: ATR TSL + target    — 1×ATR(14) trailing SL + 2×ATR target
  N: Time + ATR          — E + M
  O: Trend + ATR         — G + M

Filters:
  Volume:   touch-candle vol delta > 1.5× prior avg → breakdown/breakout, skip
  Approach: consecutive candles approaching VWAP < 3 → too fast, skip
  Nifty:    last 2 Nifty candles ALL against trade direction → hostile tape, skip
  Time:     entries only accepted 10:30–13:30; TSL/EOD exits still run until 14:30
  Trend:    LONG only if price > 5-day avg close; SHORT only if price < 5-day avg close
  RSI:      LONG only if RSI(14) in [30,55]; SHORT only if RSI(14) in [45,70]
  ATR exit: 1×ATR(14) trailing SL instead of fixed 0.5%; optional 2×ATR profit target
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ── Parameters ───────────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
ALERT_START_TIME         = "10:00"
EXIT_TIME                = "14:30"
MAX_TRADES_PER_STOCK     = 2
TRAILING_SL_PCT          = 0.50
LAST_N_DAYS              = 30

VOL_RATIO_THRESHOLD      = 1.5   # skip if touch-candle vol > 1.5× avg
APPROACH_MIN             = 3     # skip if consecutive approach candles < 3
NIFTY_LOOKBACK           = 2     # all last N Nifty candles must be against direction

# Task 3 — Time-of-day restriction
ENTRY_START_RESTRICTED   = "10:30"   # no entries before this (avoid open noise)
ENTRY_END_RESTRICTED     = "13:30"   # no new entries after this (avoid late reversals)

# Task 4 — Trend alignment
TREND_DAYS               = 5         # look-back days for avg close alignment

# Task 5 — RSI confirmation
RSI_PERIOD               = 14
# Task 6 — ATR-based dynamic trailing SL
ATR_PERIOD               = 14
ATR_SL_MULT              = 1.0       # trailing SL = ATR_SL_MULT × ATR below peak
ATR_TARGET_MULT          = 2.0       # profit target = ATR_TARGET_MULT × ATR above entry
RSI_LONG_MIN             = 30        # LONG: RSI must be >= this (not oversold exhaustion)
RSI_LONG_MAX             = 55        # LONG: RSI must be <= this (not overbought)
RSI_SHORT_MIN            = 45        # SHORT: RSI must be >= this (not oversold)
RSI_SHORT_MAX            = 70        # SHORT: RSI must be <= this (not overbought exhaustion)

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"
# ─────────────────────────────────────────────────────────────────────────────


def load_lot_sizes() -> Dict[str, int]:
    try:
        with open(LOT_SIZES_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load lot sizes ({e}) — defaulting to 1")
        return {}


def compute_charges(entry: float, exit_p: float, lot: int, direction: str) -> Dict:
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
    return {
        'brokerage': brok, 'stt': stt, 'exchange': exc,
        'sebi': sebi, 'stamp': stamp, 'gst': gst,
        'total': brok + stt + exc + sebi + stamp + gst,
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
    visible = [c for c in candles if c['timestamp'] <= ts_str]
    return visible[-1]['price'] if visible else None


def candle_volume_ratio(candles_so_far: List[Dict]) -> float:
    """Touch-candle vol delta / avg prior candle vol delta. >1 = above-average volume."""
    if len(candles_so_far) < 3:
        return 1.0
    deltas = []
    for i, c in enumerate(candles_so_far):
        delta = c['volume'] if i == 0 else max(0, c['volume'] - candles_so_far[i-1]['volume'])
        deltas.append(delta)
    prior = deltas[:-1]
    avg = sum(prior) / len(prior) if prior else 0
    return deltas[-1] / avg if avg > 0 else 1.0


def get_approach_candle_count(candles_so_far: List[Dict], direction: str) -> int:
    """Count consecutive candles approaching VWAP just before the touch."""
    if len(candles_so_far) < 2:
        return APPROACH_MIN + 1  # not enough data → allow
    prices = [c['price'] for c in candles_so_far]
    count  = 0
    if direction == "LONG":
        for i in range(len(prices) - 1, 0, -1):
            if prices[i] < prices[i - 1]:
                count += 1
            else:
                break
    else:
        for i in range(len(prices) - 1, 0, -1):
            if prices[i] > prices[i - 1]:
                count += 1
            else:
                break
    return count


def nifty_direction_ok(nifty_candles_so_far: List[Dict], direction: str, lookback: int) -> bool:
    """Returns False if all last `lookback` Nifty moves are against the trade direction."""
    if len(nifty_candles_so_far) < lookback + 1:
        return True
    recent = [c['price'] for c in nifty_candles_so_far[-(lookback + 1):]]
    if direction == "LONG":
        return not all(recent[i] < recent[i-1] for i in range(1, len(recent)))
    else:
        return not all(recent[i] > recent[i-1] for i in range(1, len(recent)))


def compute_rsi(candles_so_far: List[Dict], period: int = RSI_PERIOD) -> Optional[float]:
    """Compute RSI(period) from candle prices. Returns None if insufficient data."""
    prices = [c['price'] for c in candles_so_far]
    if len(prices) < period + 1:
        return None
    prices = prices[-(period + 1):]   # only need last period+1 prices
    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_atr(candles_so_far: List[Dict], period: int = ATR_PERIOD) -> Optional[float]:
    """ATR approximation from consecutive price deltas (no OHLC available)."""
    prices = [c['price'] for c in candles_so_far]
    if len(prices) < period + 1:
        return None
    prices = prices[-(period + 1):]
    trs = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    return sum(trs) / len(trs) if trs else None


def get_exit_atr_tsl(
    candles: List[Dict], entry_ts: str, entry_price: float,
    direction: str, atr: float, exit_ts: str,
    use_target: bool = False,
) -> Tuple[Optional[float], str, str]:
    """ATR-based trailing SL exit. SL = ATR_SL_MULT×ATR below peak/above trough."""
    sl_distance = ATR_SL_MULT * atr
    target_price = None
    if use_target:
        target_distance = ATR_TARGET_MULT * atr
        target_price = (entry_price + target_distance if direction == "LONG"
                        else entry_price - target_distance)

    sl     = entry_price - sl_distance if direction == "LONG" else entry_price + sl_distance
    peak   = entry_price
    trough = entry_price

    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if target_price and p >= target_price:
                return target_price, c['timestamp'], "TARGET"
            if p > peak:
                peak = p
            sl = peak - sl_distance
            if p <= sl:
                return sl, c['timestamp'], "ATR-TSL"
        else:
            if target_price and p <= target_price:
                return target_price, c['timestamp'], "TARGET"
            if p < trough:
                trough = p
            sl = trough + sl_distance
            if p >= sl:
                return sl, c['timestamp'], "ATR-TSL"
    eod = get_price_at(candles, exit_ts)
    return eod, exit_ts, "EOD"


def get_exit_trailing_sl(
    candles: List[Dict], entry_ts: str, entry_price: float,
    direction: str, sl_pct: float, exit_ts: str,
) -> Tuple[Optional[float], str, str]:
    sl     = entry_price * (1 - sl_pct / 100) if direction == "LONG" else entry_price * (1 + sl_pct / 100)
    peak   = entry_price
    trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak:
                peak = p
            sl = peak * (1 - sl_pct / 100)
            if p <= sl:
                return sl, c['timestamp'], "TSL"
        else:
            if p < trough:
                trough = p
            sl = trough * (1 + sl_pct / 100)
            if p >= sl:
                return sl, c['timestamp'], "TSL"
    eod = get_price_at(candles, exit_ts)
    return eod, exit_ts, "EOD"


def backtest_day(
    date: str,
    prev_close: Dict[str, float],
    all_candles: Dict[str, List[Dict]],
    nifty_candles: List[Dict],
    timestamps: List[str],
    lot_sizes: Dict[str, int],
    use_vol_filter: bool,
    use_approach_filter: bool,
    use_nifty_filter: bool,
    use_time_filter: bool = False,
    trend_avg: Optional[Dict[str, float]] = None,
    use_rsi_filter: bool = False,
    atr_exit: Optional[str] = None,   # None | "tsl" | "tsl+target"
) -> Tuple[List[Dict], Dict[str, int]]:
    if use_time_filter:
        alert_start = f"{date} {ENTRY_START_RESTRICTED}:00"
        entry_end   = f"{date} {ENTRY_END_RESTRICTED}:00"
    else:
        alert_start = f"{date} {ALERT_START_TIME}:00"
        entry_end   = f"{date} {EXIT_TIME}:00"
    exit_ts     = f"{date} {EXIT_TIME}:00"

    cooldown:    Dict[str, datetime] = {}
    trade_count: Dict[str, int]      = defaultdict(int)
    trades:      List[Dict]          = []
    skipped = {'vol': 0, 'approach': 0, 'nifty': 0, 'trend': 0, 'rsi': 0}

    for ts_str in timestamps:
        if ts_str > exit_ts:
            break
        if ts_str < alert_start or ts_str > entry_end:
            continue

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

        nifty_visible = [c for c in nifty_candles if c['timestamp'] <= ts_str]

        for rank, (symbol, pct_change, price) in enumerate(top10, 1):
            if trade_count[symbol] >= MAX_TRADES_PER_STOCK:
                continue

            candles_so_far = [c for c in all_candles.get(symbol, []) if c['timestamp'] <= ts_str]
            vwap = compute_vwap(candles_so_far)
            if vwap is None:
                continue

            if abs(price - vwap) / vwap * 100 > VWAP_TOUCH_THRESHOLD_PCT:
                continue

            if symbol in cooldown:
                if (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                    continue

            trade_dir = "LONG" if pct_change >= 0 else "SHORT"

            # ── Filter 1: Volume ───────────────────────────────────────────
            if use_vol_filter:
                vol_ratio = candle_volume_ratio(candles_so_far)
                if vol_ratio > VOL_RATIO_THRESHOLD:
                    skipped['vol'] += 1
                    cooldown[symbol] = ts
                    continue

            # ── Filter 2: Approach speed ───────────────────────────────────
            if use_approach_filter:
                approach = get_approach_candle_count(candles_so_far, trade_dir)
                if approach < APPROACH_MIN:
                    skipped['approach'] += 1
                    cooldown[symbol] = ts
                    continue

            # ── Filter 3: Nifty direction ──────────────────────────────────
            if use_nifty_filter:
                if not nifty_direction_ok(nifty_visible, trade_dir, NIFTY_LOOKBACK):
                    skipped['nifty'] += 1
                    cooldown[symbol] = ts
                    continue

            # ── Filter 4: Trend alignment (5-day avg close) ────────────────
            if trend_avg is not None and symbol in trend_avg:
                avg5 = trend_avg[symbol]
                if trade_dir == "LONG" and price < avg5:
                    skipped['trend'] += 1
                    cooldown[symbol] = ts
                    continue
                if trade_dir == "SHORT" and price > avg5:
                    skipped['trend'] += 1
                    cooldown[symbol] = ts
                    continue

            # ── Filter 5: RSI confirmation ─────────────────────────────────
            if use_rsi_filter:
                rsi = compute_rsi(candles_so_far)
                if rsi is not None:
                    if trade_dir == "LONG" and not (RSI_LONG_MIN <= rsi <= RSI_LONG_MAX):
                        skipped['rsi'] += 1
                        cooldown[symbol] = ts
                        continue
                    if trade_dir == "SHORT" and not (RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX):
                        skipped['rsi'] += 1
                        cooldown[symbol] = ts
                        continue

            lot = lot_sizes.get(symbol, 1)
            if atr_exit:
                atr_val = compute_atr(candles_so_far)
                if atr_val and atr_val > 0:
                    exit_price, exit_at, reason = get_exit_atr_tsl(
                        all_candles.get(symbol, []), ts_str, price, trade_dir,
                        atr_val, exit_ts, use_target=(atr_exit == "tsl+target"),
                    )
                else:
                    # fall back to fixed TSL if ATR unavailable
                    exit_price, exit_at, reason = get_exit_trailing_sl(
                        all_candles.get(symbol, []), ts_str, price, trade_dir, TRAILING_SL_PCT, exit_ts,
                    )
            else:
                exit_price, exit_at, reason = get_exit_trailing_sl(
                    all_candles.get(symbol, []), ts_str, price, trade_dir, TRAILING_SL_PCT, exit_ts,
                )
            if exit_price is None:
                cooldown[symbol] = ts
                trade_count[symbol] += 1
                continue

            pnl_ps = (exit_price - price) if trade_dir == "LONG" else (price - exit_price)
            gross  = pnl_ps * lot
            chg    = compute_charges(price, exit_price, lot, trade_dir)
            net    = gross - chg['total']

            trades.append({
                'date': date, 'time': ts_str, 'rank': rank,
                'symbol': symbol, 'pct_change': pct_change,
                'entry_price': price, 'vwap': vwap,
                'trade_dir': trade_dir, 'lot_size': lot,
                'exit_price': exit_price, 'exit_at': exit_at,
                'exit_reason': reason,
                'pnl_per_share': pnl_ps, 'gross_pnl': gross,
                'charges': chg, 'net_pnl': net,
                'approach_candles': get_approach_candle_count(candles_so_far, trade_dir),
                'vol_ratio': candle_volume_ratio(candles_so_far),
            })
            cooldown[symbol] = ts
            trade_count[symbol] += 1

    return trades, skipped


def summarise(all_trades: List[Dict], all_dates: List[str]) -> Dict:
    valid         = [t for t in all_trades if t['net_pnl'] is not None]
    total_gross   = sum(t['gross_pnl']       for t in valid)
    total_charges = sum(t['charges']['total'] for t in valid)
    total_net     = sum(t['net_pnl']         for t in valid)
    winners       = [t for t in valid if t['net_pnl'] > 0]
    losers        = [t for t in valid if t['net_pnl'] <= 0]
    tsl_trades    = [t for t in valid if t['exit_reason'] in ('TSL', 'ATR-TSL')]
    tsl_wins      = [t for t in tsl_trades if t['net_pnl'] > 0]
    eod_trades    = [t for t in valid if t['exit_reason'] == 'EOD']
    eod_wins      = [t for t in eod_trades if t['net_pnl'] > 0]
    tgt_trades    = [t for t in valid if t['exit_reason'] == 'TARGET']
    tgt_wins      = [t for t in tgt_trades if t['net_pnl'] > 0]

    day_nets: Dict[str, float] = {}
    for t in valid:
        day_nets[t['date']] = day_nets.get(t['date'], 0) + t['net_pnl']
    green = sum(1 for v in day_nets.values() if v > 0)
    red   = sum(1 for v in day_nets.values() if v < 0)

    cum = peak_cum = max_dd = 0.0
    for date in all_dates:
        cum      += day_nets.get(date, 0)
        peak_cum  = max(peak_cum, cum)
        max_dd    = max(max_dd, peak_cum - cum)

    return {
        'trades': len(valid), 'winners': len(winners), 'losers': len(losers),
        'win_rate': len(winners) / len(valid) * 100 if valid else 0,
        'tsl_trades': len(tsl_trades), 'tsl_wins': len(tsl_wins),
        'eod_trades': len(eod_trades), 'eod_wins': len(eod_wins),
        'gross': total_gross, 'charges': total_charges, 'net': total_net,
        'avg_winner': sum(t['net_pnl'] for t in winners) / len(winners) if winners else 0,
        'avg_loser':  sum(t['net_pnl'] for t in losers)  / len(losers)  if losers  else 0,
        'best':  max(valid, key=lambda t: t['net_pnl']) if valid else None,
        'worst': min(valid, key=lambda t: t['net_pnl']) if valid else None,
        'green': green, 'red': red,
        'avg_day': total_net / len(all_dates) if all_dates else 0,
        'max_dd': max_dd,
        'day_nets': day_nets,
    }


def run():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates_in_db = [r['d'] for r in cur.fetchall()]
    all_dates = all_dates_in_db[-LAST_N_DAYS:]

    print(f"Building per-date prev_close for last {LAST_N_DAYS} trading days...")
    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for date in all_dates:
        idx = all_dates_in_db.index(date)
        if idx == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = all_dates_in_db[idx - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp = (SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp) = ?)
                  AND date(timestamp) = ?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}

    nifty_by_date: Dict[str, List[Dict]] = {}
    for date in all_dates:
        cur.execute("""
            SELECT timestamp, price FROM nifty_quotes
            WHERE date(timestamp) = ? ORDER BY timestamp ASC
        """, (date,))
        nifty_by_date[date] = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Task 4 — build 5-day avg close per date per symbol
    # prev_close_by_date[d] = closing prices of the day BEFORE d
    # So 5-day avg for date D = avg of prev_close from D, D-1, D-2, D-3, D-4
    trend_avg_by_date: Dict[str, Dict[str, float]] = {}
    for i, date in enumerate(all_dates):
        syms: Dict[str, List[float]] = {}
        for j in range(TREND_DAYS):
            # look back j days in all_dates (or further into all_dates_in_db)
            idx_in_full = all_dates_in_db.index(date)
            lookback_idx = idx_in_full - j
            if lookback_idx < 0:
                break
            lb_date = all_dates_in_db[lookback_idx]
            closes = prev_close_by_date.get(lb_date, {})
            for sym, close in closes.items():
                if close > 0:
                    syms.setdefault(sym, []).append(close)
        trend_avg_by_date[date] = {
            sym: sum(prices) / len(prices)
            for sym, prices in syms.items()
            if len(prices) >= 3   # need at least 3 days to be meaningful
        }

    trades_a, trades_b, trades_c, trades_d = [], [], [], []
    trades_e, trades_f = [], []
    trades_g, trades_h = [], []
    trades_i, trades_j, trades_k = [], [], []
    trades_l, trades_m, trades_n, trades_o = [], [], [], []
    skipped_totals = {'vol': 0, 'approach': 0, 'nifty': 0,
                      'all_vol': 0, 'all_approach': 0, 'all_nifty': 0,
                      'time_f_vol': 0,
                      'trend_g': 0, 'trend_h': 0,
                      'rsi_i': 0, 'rsi_j': 0, 'rsi_k': 0}

    for date in all_dates:
        market_open  = f"{date} 09:15:00"
        market_close = f"{date} {EXIT_TIME}:00"

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT timestamp FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC
        """, (market_open, market_close))
        timestamps = [r['timestamp'] for r in cur.fetchall()]

        cur.execute("""
            SELECT symbol, timestamp, price, volume FROM stock_quotes
            WHERE timestamp >= ? AND timestamp <= ? ORDER BY symbol, timestamp ASC
        """, (market_open, market_close))
        candles: Dict[str, List[Dict]] = {}
        for r in cur.fetchall():
            sym = r['symbol']
            if sym not in candles:
                candles[sym] = []
            candles[sym].append({'timestamp': r['timestamp'], 'price': r['price'], 'volume': r['volume']})
        conn.close()

        if not timestamps:
            continue

        nifty  = nifty_by_date.get(date, [])
        prev   = prev_close_by_date[date]
        trend5 = trend_avg_by_date.get(date, {})

        ta, _   = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, False)
        tb, skb = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, True,  False, False, False)
        tc, skc = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, True,  True,  False)
        td, skd = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, True,  True,  True,  False)
        te, ske = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, True)
        tf, skf = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, True,  False, False, True)
        tg, skg = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, False, trend5)
        th, skh = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, True,  trend5)
        ti, ski = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, False, None,   True)
        tj, skj = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, True,  None,   True)
        tk, skk = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, False, trend5, True)
        tl, _   = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, False, None,   False, "tsl")
        tm, _   = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, False, None,   False, "tsl+target")
        tn, _   = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, True,  None,   False, "tsl+target")
        to, _   = backtest_day(date, prev, candles, nifty, timestamps, lot_sizes, False, False, False, False, trend5, False, "tsl+target")

        trades_a.extend(ta); trades_b.extend(tb)
        trades_c.extend(tc); trades_d.extend(td)
        trades_e.extend(te); trades_f.extend(tf)
        trades_g.extend(tg); trades_h.extend(th)
        trades_i.extend(ti); trades_j.extend(tj); trades_k.extend(tk)
        trades_l.extend(tl); trades_m.extend(tm)
        trades_n.extend(tn); trades_o.extend(to)
        skipped_totals['vol']         += skb['vol']
        skipped_totals['approach']    += skc['approach']
        skipped_totals['nifty']       += skc['nifty']
        skipped_totals['all_vol']     += skd['vol']
        skipped_totals['all_approach']+= skd['approach']
        skipped_totals['all_nifty']   += skd['nifty']
        skipped_totals['time_f_vol']  += skf['vol']
        skipped_totals['trend_g']     += skg['trend']
        skipped_totals['trend_h']     += skh['trend']
        skipped_totals['rsi_i']       += ski['rsi']
        skipped_totals['rsi_j']       += skj['rsi']
        skipped_totals['rsi_k']       += skk['rsi']

    sa = summarise(trades_a, all_dates)
    sb = summarise(trades_b, all_dates)
    sc = summarise(trades_c, all_dates)
    sd = summarise(trades_d, all_dates)
    se = summarise(trades_e, all_dates)
    sf = summarise(trades_f, all_dates)
    sg = summarise(trades_g, all_dates)
    sh = summarise(trades_h, all_dates)
    si = summarise(trades_i, all_dates)
    sj = summarise(trades_j, all_dates)
    sk = summarise(trades_k, all_dates)
    sl = summarise(trades_l, all_dates)
    sm = summarise(trades_m, all_dates)
    sn = summarise(trades_n, all_dates)
    so = summarise(trades_o, all_dates)

    configs = [
        ("A: No filters",      sa, trades_a),
        ("B: Vol filter",      sb, trades_b),
        ("C: Approach+Nifty",  sc, trades_c),
        ("D: All T2 filters",  sd, trades_d),
        ("E: Time 10:30-13:30",se, trades_e),
        ("F: Time+Vol",        sf, trades_f),
        ("G: Trend 5-day",     sg, trades_g),
        ("H: Time+Trend",      sh, trades_h),
        ("I: RSI only",        si, trades_i),
        ("J: Time+RSI",        sj, trades_j),
        ("K: Trend+RSI",       sk, trades_k),
        ("L: ATR-TSL",         sl, trades_l),
        ("M: ATR-TSL+Target",  sm, trades_m),
        ("N: Time+ATR",        sn, trades_n),
        ("O: Trend+ATR",       so, trades_o),
    ]

    W = 145
    print("=" * W)
    print(f"VWAP MOVER — COMBINED MULTI-FILTER BACKTEST | TSL 0.5% | Last {LAST_N_DAYS} days")
    print(f"  {len(all_dates)} trading days: {all_dates[0]} → {all_dates[-1]}")
    print(f"  A: Baseline(TSL 0.5%)  E: Time 10:30–13:30  M: ATR({ATR_PERIOD}) {ATR_SL_MULT}×SL+{ATR_TARGET_MULT}×Tgt  N: Time+ATR  O: Trend+ATR")
    print(f"  (B/C/D/F/G/H/I/J/K/L also tracked in full summary below)")
    print("=" * W)

    # Day-by-day table — show A, E, M, N, O (Task 6 focus)
    print(f"\n  {'Date':10}  "
          f"{'Tr':>2} {'W':>2} {'Net_A':>10}  {'Cum_A':>10}  |  "
          f"{'Tr':>2} {'W':>2} {'Net_E':>10}  {'Cum_E':>10}  |  "
          f"{'Tr':>2} {'W':>2} {'Net_M':>10}  {'Cum_M':>10}  |  "
          f"{'Tr':>2} {'W':>2} {'Net_O':>10}  {'Cum_O':>10}")
    print(f"  {'-'*10}  " + (f"{'-'*2} {'-'*2} {'-'*10}  {'-'*10}  |  ") * 3 +
          f"{'-'*2} {'-'*2} {'-'*10}  {'-'*10}")

    cum_a = cum_e = cum_m = cum_o = 0.0
    day_a = defaultdict(list); day_e = defaultdict(list)
    day_m = defaultdict(list); day_o = defaultdict(list)
    for t in trades_a: day_a[t['date']].append(t)
    for t in trades_e: day_e[t['date']].append(t)
    for t in trades_m: day_m[t['date']].append(t)
    for t in trades_o: day_o[t['date']].append(t)

    for date in all_dates:
        ta_ = day_a[date]; te_ = day_e[date]
        tm_ = day_m[date]; to_ = day_o[date]
        na = sum(t['net_pnl'] for t in ta_); ne = sum(t['net_pnl'] for t in te_)
        nm = sum(t['net_pnl'] for t in tm_); no_ = sum(t['net_pnl'] for t in to_)
        wa = sum(1 for t in ta_ if t['net_pnl'] > 0); we = sum(1 for t in te_ if t['net_pnl'] > 0)
        wm = sum(1 for t in tm_ if t['net_pnl'] > 0); wo = sum(1 for t in to_ if t['net_pnl'] > 0)
        cum_a += na; cum_e += ne; cum_m += nm; cum_o += no_

        def di(trs, net): return "✅" if net > 0 else ("⚪" if not trs else "❌")
        print(f"  {date}  "
              f"{len(ta_):>2} {wa:>2} {di(ta_,na)}₹{na:>+8,.0f}  ₹{cum_a:>+9,.0f}  |  "
              f"{len(te_):>2} {we:>2} {di(te_,ne)}₹{ne:>+8,.0f}  ₹{cum_e:>+9,.0f}  |  "
              f"{len(tm_):>2} {wm:>2} {di(tm_,nm)}₹{nm:>+8,.0f}  ₹{cum_m:>+9,.0f}  |  "
              f"{len(to_):>2} {wo:>2} {di(to_,no_)}₹{no_:>+8,.0f}  ₹{cum_o:>+9,.0f}")

    # Overall summary
    print("\n" + "=" * W)
    print(f"{'OVERALL SUMMARY':^{W}}")
    print("=" * W)

    rows = [
        ("Trades",           lambda s: str(s['trades'])),
        ("Win rate",         lambda s: f"{s['win_rate']:.1f}%"),
        ("TSL exits (wins)", lambda s: f"{s['tsl_trades']}({s['tsl_wins']})"),
        ("EOD exits (wins)", lambda s: f"{s['eod_trades']}({s['eod_wins']})"),
        ("Green / Red days", lambda s: f"{s['green']}/{s['red']}"),
        ("Gross P&L",        lambda s: f"₹{s['gross']:>+,.0f}"),
        ("Total charges",    lambda s: f"₹{s['charges']:>,.0f}"),
        ("NET P&L",          lambda s: f"₹{s['net']:>+,.0f}"),
        ("Avg per day",      lambda s: f"₹{s['avg_day']:>+,.0f}"),
        ("Max drawdown",     lambda s: f"₹{s['max_dd']:>,.0f}"),
        ("Avg winner",       lambda s: f"₹{s['avg_winner']:>+,.0f}"),
        ("Avg loser",        lambda s: f"₹{s['avg_loser']:>+,.0f}"),
    ]

    hints = [
        f"({sa['trades']} tr, TSL 0.5%)",
        f"({sb['trades']} tr, vol skip {skipped_totals['vol']})",
        f"({sc['trades']} tr, {skipped_totals['approach']}ap+{skipped_totals['nifty']}nif skip)",
        f"({sd['trades']} tr, all T2)",
        f"({se['trades']} tr, {ENTRY_START_RESTRICTED}–{ENTRY_END_RESTRICTED})",
        f"({sf['trades']} tr, time+vol)",
        f"({sg['trades']} tr, trend skip {skipped_totals['trend_g']})",
        f"({sh['trades']} tr, time+trend)",
        f"({si['trades']} tr, RSI skip {skipped_totals['rsi_i']})",
        f"({sj['trades']} tr, time+RSI)",
        f"({sk['trades']} tr, trend+RSI)",
        f"({sl['trades']} tr, ATR {ATR_SL_MULT}×SL only)",
        f"({sm['trades']} tr, ATR {ATR_SL_MULT}×SL+{ATR_TARGET_MULT}×Tgt)",
        f"({sn['trades']} tr, time+ATR)",
        f"({so['trades']} tr, trend+ATR)",
    ]

    for label, fn in rows:
        marks = [""] * len(configs)
        if label == "Max drawdown":
            best_val = min(s['max_dd'] for _, s, _ in configs)
            for i, (_, s, _) in enumerate(configs):
                if s['max_dd'] == best_val:
                    marks[i] = " ◀"
        elif label in ("NET P&L", "Avg per day", "Win rate"):
            vals_num = [s['net'] if label == "NET P&L" else
                        s['avg_day'] if label == "Avg per day" else
                        s['win_rate'] for _, s, _ in configs]
            best_val = max(vals_num)
            for i, v in enumerate(vals_num):
                if v == best_val:
                    marks[i] = " ◀ BEST"
        print(f"  {label:22}  " + "  |  ".join(
            f"{fn(s):>12}  {hints[i]}{marks[i]}"
            for i, (_, s, _) in enumerate(configs)
        ))

    print()
    for key, idx in [("Best trade", 'best'), ("Worst trade", 'worst')]:
        parts = [f"{lbl[:1]}: {s[idx]['date']} {s[idx]['symbol']:10} ₹{s[idx]['net_pnl']:>+,.0f}"
                 if s[idx] else f"{lbl[:1]}: N/A"
                 for lbl, s, _ in configs]
        print(f"  {key:22}  " + "  |  ".join(parts))

    # Skipped breakdown
    print(f"\n{'─'*W}")
    print(f"  SIGNALS SKIPPED BY FILTER")
    print(f"{'─'*W}")
    total_b = sa['trades'] + skipped_totals['vol']
    print(f"  B (vol >{VOL_RATIO_THRESHOLD}×):           {skipped_totals['vol']:4d} skipped  "
          f"({skipped_totals['vol']/max(total_b,1)*100:.1f}% of signals)")
    print(f"  C (approach <{APPROACH_MIN}c):         {skipped_totals['approach']:4d} skipped by approach  "
          f"{skipped_totals['nifty']:4d} skipped by Nifty")
    print(f"  D (all three):         vol={skipped_totals['all_vol']}  "
          f"approach={skipped_totals['all_approach']}  nifty={skipped_totals['all_nifty']}")
    print(f"  E (time {ENTRY_START_RESTRICTED}–{ENTRY_END_RESTRICTED}):  "
          f"{sa['trades'] - se['trades']:4d} trades excluded vs baseline")
    print(f"  F (time+vol):          {sa['trades'] - sf['trades']:4d} trades excluded vs baseline  "
          f"(vol also skipped {skipped_totals['time_f_vol']})")
    print(f"  G (trend {TREND_DAYS}-day avg):    {skipped_totals['trend_g']:4d} trades skipped by trend filter")
    print(f"  H (time+trend):        {skipped_totals['trend_h']:4d} trades skipped by trend inside time window")
    print(f"  I (RSI L{RSI_LONG_MIN}-{RSI_LONG_MAX}/S{RSI_SHORT_MIN}-{RSI_SHORT_MAX}):  {skipped_totals['rsi_i']:4d} trades skipped by RSI filter")
    print(f"  J (time+RSI):          {skipped_totals['rsi_j']:4d} trades skipped by RSI inside time window")
    print(f"  K (trend+RSI):         {skipped_totals['rsi_k']:4d} trades skipped by RSI inside trend filter")

    # Approach candle distribution
    print(f"\n{'─'*W}")
    print(f"  APPROACH SPEED DISTRIBUTION (from baseline A trades)")
    print(f"{'─'*W}")
    buckets: Dict[int, Dict] = {}
    for t in trades_a:
        k = min(t.get('approach_candles', 0), 10)
        if k not in buckets:
            buckets[k] = {'trades': 0, 'wins': 0, 'net': 0.0}
        buckets[k]['trades'] += 1
        buckets[k]['wins']   += 1 if t['net_pnl'] > 0 else 0
        buckets[k]['net']    += t['net_pnl']
    print(f"  {'Candles':>8}  {'Trades':>7}  {'Win%':>7}  {'Net P&L':>12}  {'Avg/trade':>10}")
    print(f"  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*12}  {'-'*10}")
    for k in sorted(buckets.keys()):
        b = buckets[k]
        wr  = b['wins'] / b['trades'] * 100 if b['trades'] else 0
        avg = b['net']  / b['trades']        if b['trades'] else 0
        flag = "  ← filtered by C/D" if k < APPROACH_MIN else ""
        print(f"  {k:>8}  {b['trades']:>7}  {wr:>6.1f}%  ₹{b['net']:>+10,.0f}  ₹{avg:>+8,.0f}{flag}")

    # Time-of-day breakdown (win rate by entry hour, from baseline A)
    print(f"\n{'─'*W}")
    print(f"  TIME-OF-DAY WIN RATE (baseline A trades, grouped by entry hour)")
    print(f"{'─'*W}")
    hour_buckets: Dict[str, Dict] = {}
    for t in trades_a:
        hh = t['time'][11:16]   # "HH:MM"
        hour = t['time'][11:13]  # "HH"
        if hour not in hour_buckets:
            hour_buckets[hour] = {'trades': 0, 'wins': 0, 'net': 0.0}
        hour_buckets[hour]['trades'] += 1
        hour_buckets[hour]['wins']   += 1 if t['net_pnl'] > 0 else 0
        hour_buckets[hour]['net']    += t['net_pnl']
    print(f"  {'Hour':>6}  {'Trades':>7}  {'Win%':>7}  {'Net P&L':>12}  {'Avg/trade':>10}")
    print(f"  {'-'*6}  {'-'*7}  {'-'*7}  {'-'*12}  {'-'*10}")
    for hr in sorted(hour_buckets.keys()):
        b = hour_buckets[hr]
        wr  = b['wins'] / b['trades'] * 100 if b['trades'] else 0
        avg = b['net']  / b['trades']        if b['trades'] else 0
        in_window = "  ← E/F window" if ENTRY_START_RESTRICTED[:2] <= hr <= ENTRY_END_RESTRICTED[:2] else ""
        print(f"  {hr}:xx  {b['trades']:>7}  {wr:>6.1f}%  ₹{b['net']:>+10,.0f}  ₹{avg:>+8,.0f}{in_window}")

    # Per-symbol for best config
    best_lbl, best_s, best_tlist = max(configs, key=lambda x: x[1]['net'])
    sym_stats: Dict[str, Dict] = {}
    for t in best_tlist:
        s = t['symbol']
        if s not in sym_stats:
            sym_stats[s] = {'trades': 0, 'wins': 0, 'gross': 0.0, 'charges': 0.0, 'net': 0.0}
        sym_stats[s]['trades']  += 1
        sym_stats[s]['wins']    += 1 if t['net_pnl'] > 0 else 0
        sym_stats[s]['gross']   += t['gross_pnl']
        sym_stats[s]['charges'] += t['charges']['total']
        sym_stats[s]['net']     += t['net_pnl']

    print(f"\n{'─'*W}")
    print(f"  PER-SYMBOL  ({best_lbl}, sorted by net P&L)")
    print(f"{'─'*W}")
    print(f"  {'Symbol':12}  {'Tr':3}  {'Win%':6}  {'Gross':>10}  {'Chg':>7}  {'Net':>10}")
    print(f"  {'-'*12}  {'-'*3}  {'-'*6}  {'-'*10}  {'-'*7}  {'-'*10}")
    for sym, s in sorted(sym_stats.items(), key=lambda x: x[1]['net'], reverse=True):
        icon = "✅" if s['net'] > 0 else "❌"
        print(f"  {icon} {sym:12}  {s['trades']:3d}  {s['wins']/s['trades']*100:5.0f}%  "
              f"₹{s['gross']:>+9,.0f}  ₹{s['charges']:>6,.0f}  ₹{s['net']:>+9,.0f}")

    print(f"\n⚠️  Charges: ₹40 brokerage | STT 0.02% sell | Exchange 0.00188% | SEBI | Stamp | GST 18%")
    print(f"   Vol filter:      skip if touch-candle volume delta > {VOL_RATIO_THRESHOLD}× prior avg")
    print(f"   Approach filter: skip if < {APPROACH_MIN} consecutive approach candles at VWAP touch")
    print(f"   Nifty filter:    skip if last {NIFTY_LOOKBACK} Nifty candles ALL against trade direction")


if __name__ == "__main__":
    run()
