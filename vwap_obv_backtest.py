#!/usr/bin/env python3
"""
VWAP Mover — OBV Filter Backtest
==================================
Tests "skip signal if last N OBV values trend against trade direction."

OBV (On-Balance Volume):
  - Start at 0 at market open each day
  - Each minute candle: vol_delta = cumulative_vol[i] - cumulative_vol[i-1]
  - If price rose vs prev candle → add vol_delta
  - If price fell → subtract vol_delta
  - If flat → unchanged

Filter variants:
  Net trend  — skip if net OBV change over last N candles is against direction
               (LONG: OBV[now] < OBV[now-N] → skip; SHORT: OBV[now] > OBV[now-N] → skip)
  Strict     — skip only if ALL N consecutive OBV moves are against direction
               (more lenient — mirrors the existing Nifty direction filter)

Configs compared:
  A: Baseline — no extra filters
  B: C-1/C-2 vol filter only  (current live config)
  C: OBV net  N=3
  D: OBV net  N=5
  E: OBV net  N=7
  F: OBV net  N=10
  G: OBV strict N=3
  H: OBV strict N=5
  I: C-1/C-2  + OBV net N=5
  J: C-1/C-2  + OBV net N=7

Window:  10:00 – 14:30  |  TSL 0.5%  |  Last 30 trading days
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ── Parameters ───────────────────────────────────────────────────────────────
VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
ALERT_START_TIME         = "10:00"
EXIT_TIME                = "14:30"
MAX_TRADES_PER_STOCK     = 2
TRAILING_SL_PCT          = 0.50
LAST_N_DAYS              = 30

VOL_C1_MIN = 1.5   # touch candle delta ≥ this (C-1/C-2 filter)
VOL_C2_MAX = 1.0   # prior candle delta < this

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
        vd = c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume'])
        cum_pv += c['price'] * vd
        cum_vol += vd
    return cum_pv / cum_vol if cum_vol > 0 else None


def get_price_at(candles: List[Dict], ts: str) -> Optional[float]:
    v = [c for c in candles if c['timestamp'] <= ts]
    return v[-1]['price'] if v else None


def compute_obv(candles: List[Dict]) -> List[float]:
    """
    Return a list of OBV values, one per candle (same length as input).
    OBV starts at 0 at the first candle. Uses cumulative volume deltas.
    """
    obv_vals: List[float] = []
    obv = 0.0
    for i, c in enumerate(candles):
        if i == 0:
            obv_vals.append(0.0)
            continue
        vol_delta = max(0.0, float(c['volume']) - float(candles[i-1]['volume']))
        if c['price'] > candles[i-1]['price']:
            obv += vol_delta
        elif c['price'] < candles[i-1]['price']:
            obv -= vol_delta
        obv_vals.append(obv)
    return obv_vals


def obv_ok(obv_vals: List[float], direction: str, lookback: int, strict: bool) -> bool:
    """
    Returns True (allow trade) if OBV trend is NOT against trade direction.
    Returns False (skip) if OBV is moving against direction.

    strict=False (net trend):
      LONG  → skip if OBV[now] < OBV[now - lookback]  (net decline)
      SHORT → skip if OBV[now] > OBV[now - lookback]  (net rise)

    strict=True (all consecutive):
      LONG  → skip only if ALL last `lookback` OBV moves were negative
      SHORT → skip only if ALL last `lookback` OBV moves were positive
    """
    if len(obv_vals) < lookback + 1:
        return True   # not enough history → allow

    if strict:
        recent = obv_vals[-(lookback + 1):]
        if direction == "LONG":
            return not all(recent[i] < recent[i-1] for i in range(1, len(recent)))
        else:
            return not all(recent[i] > recent[i-1] for i in range(1, len(recent)))
    else:
        net = obv_vals[-1] - obv_vals[-(lookback + 1)]
        if direction == "LONG":
            return net >= 0    # OBV rising (or flat) → ok for LONG
        else:
            return net <= 0    # OBV falling (or flat) → ok for SHORT


def get_vol_ratios(candles: List[Dict]) -> Tuple[Optional[float], Optional[float]]:
    """C-1/C-2 volume delta ratios. C-1 = touch candle, C-2 = candle before."""
    if len(candles) < 3:
        return None, None
    deltas = [
        float(c['volume'] if i == 0 else max(0, c['volume'] - candles[i-1]['volume']))
        for i, c in enumerate(candles)
    ]
    baseline = deltas[:-2]
    avg = sum(baseline) / len(baseline) if baseline else 0
    if avg <= 0:
        return None, None
    return round(deltas[-1] / avg, 2), round(deltas[-2] / avg, 2)


def get_exit_tsl(
    candles: List[Dict], entry_ts: str, entry_price: float,
    direction: str, sl_pct: float, exit_ts: str
) -> Tuple[Optional[float], str]:
    sl = (entry_price * (1 - sl_pct / 100) if direction == "LONG"
          else entry_price * (1 + sl_pct / 100))
    peak = trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts:
            continue
        p = c['price']
        if direction == "LONG":
            if p > peak:
                peak = p
            sl = peak * (1 - sl_pct / 100)
            if p <= sl:
                return sl, "TSL"
        else:
            if p < trough:
                trough = p
            sl = trough * (1 + sl_pct / 100)
            if p >= sl:
                return sl, "TSL"
    return get_price_at(candles, exit_ts), "EOD"


def run_day(
    date: str,
    prev_close: Dict[str, float],
    all_candles: Dict[str, List[Dict]],
    timestamps: List[str],
    lot_sizes: Dict[str, int],
    use_vol_filter: bool,
    obv_lookback: int,      # 0 = no OBV filter
    obv_strict: bool,
) -> List[Dict]:
    alert_start = f"{date} {ALERT_START_TIME}:00"
    exit_ts     = f"{date} {EXIT_TIME}:00"
    cooldown:    Dict[str, datetime] = {}
    trade_count: Dict[str, int]      = defaultdict(int)
    trades: List[Dict] = []

    for ts_str in timestamps:
        if ts_str > exit_ts:
            break
        if ts_str < alert_start:
            continue
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')

        # Latest snapshot
        latest: Dict[str, Dict] = {}
        for sym, cl in all_candles.items():
            vis = [c for c in cl if c['timestamp'] <= ts_str]
            if vis:
                latest[sym] = vis[-1]

        movers = []
        for sym, q in latest.items():
            pc = prev_close.get(sym, 0)
            if pc <= 0:
                continue
            pct = (q['price'] - pc) / pc * 100
            movers.append((sym, pct, q['price']))
        movers.sort(key=lambda x: abs(x[1]), reverse=True)

        for rank, (symbol, pct_change, price) in enumerate(movers[:TOP_N], 1):
            if trade_count[symbol] >= MAX_TRADES_PER_STOCK:
                continue

            csf = [c for c in all_candles.get(symbol, []) if c['timestamp'] <= ts_str]
            vwap = compute_vwap(csf)
            if vwap is None:
                continue
            if abs(price - vwap) / vwap * 100 > VWAP_TOUCH_THRESHOLD_PCT:
                continue
            if symbol in cooldown and (ts - cooldown[symbol]).total_seconds() / 60 < ALERT_COOLDOWN_MINUTES:
                continue

            direction = "LONG" if pct_change >= 0 else "SHORT"

            # ── C-1/C-2 volume filter ─────────────────────────────────────
            if use_vol_filter:
                c1, c2 = get_vol_ratios(csf)
                if c1 is None or not (c1 >= VOL_C1_MIN and c2 < VOL_C2_MAX):
                    cooldown[symbol] = ts
                    continue

            # ── OBV filter ────────────────────────────────────────────────
            if obv_lookback > 0:
                obv_vals = compute_obv(csf)
                if not obv_ok(obv_vals, direction, obv_lookback, obv_strict):
                    cooldown[symbol] = ts
                    continue

            lot = lot_sizes.get(symbol, 1)
            ep, reason = get_exit_tsl(
                all_candles.get(symbol, []), ts_str, price,
                direction, TRAILING_SL_PCT, exit_ts
            )
            if ep is None:
                cooldown[symbol] = ts
                trade_count[symbol] += 1
                continue

            pnl   = (ep - price) if direction == "LONG" else (price - ep)
            gross = pnl * lot
            chg   = compute_charges(price, ep, lot, direction)

            trades.append({
                'date': date, 'symbol': symbol, 'dir': direction,
                'lot': lot, 'entry': price, 'exit': ep,
                'reason': reason, 'gross': gross, 'net': gross - chg,
                'rank': rank,
            })
            cooldown[symbol] = ts
            trade_count[symbol] += 1

    return trades


def summarise(trades: List[Dict], all_dates: List[str]) -> Dict:
    if not trades:
        return {
            'n': 0, 'wr': 0.0, 'net': 0.0, 'avg': 0.0,
            'green': 0, 'red': 0, 'max_dd': 0.0,
            'tsl': 0, 'eod': 0,
            'avg_win': 0.0, 'avg_loss': 0.0, 'day_nets': {},
        }
    wins   = [t for t in trades if t['net'] > 0]
    losses = [t for t in trades if t['net'] <= 0]
    net    = sum(t['net'] for t in trades)

    day_nets: Dict[str, float] = defaultdict(float)
    for t in trades:
        day_nets[t['date']] += t['net']
    green = sum(1 for v in day_nets.values() if v > 0)
    red   = sum(1 for v in day_nets.values() if v < 0)

    cum = pk = dd = 0.0
    for d in all_dates:
        cum += day_nets.get(d, 0)
        pk   = max(pk, cum)
        dd   = max(dd, pk - cum)

    return {
        'n':        len(trades),
        'wr':       len(wins) / len(trades) * 100,
        'net':      net,
        'avg':      net / len(trades),
        'green':    green,
        'red':      red,
        'max_dd':   dd,
        'tsl':      sum(1 for t in trades if t['reason'] == 'TSL'),
        'eod':      sum(1 for t in trades if t['reason'] == 'EOD'),
        'avg_win':  sum(t['net'] for t in wins)   / len(wins)   if wins   else 0.0,
        'avg_loss': sum(t['net'] for t in losses) / len(losses) if losses else 0.0,
        'day_nets': dict(day_nets),
    }


def run():
    lot_sizes = load_lot_sizes()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates_db = [r['d'] for r in cur.fetchall()]
    all_dates    = all_dates_db[-LAST_N_DAYS:]

    print(f"Building prev_close for last {LAST_N_DAYS} trading days "
          f"({all_dates[0]} → {all_dates[-1]})...")

    prev_close_by_date: Dict[str, Dict[str, float]] = {}
    for date in all_dates:
        idx = all_dates_db.index(date)
        if idx == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            prev_date = all_dates_db[idx - 1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp = (SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp) = ?)
                  AND date(timestamp) = ?
            """, (prev_date, prev_date))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}
    conn.close()

    # configs: (label, use_vol_filter, obv_lookback, obv_strict)
    CONFIGS = [
        ("A: Baseline",              False, 0,  False),
        ("B: C-1/C-2 vol (live)",    True,  0,  False),
        ("C: OBV net  N=3",          False, 3,  False),
        ("D: OBV net  N=5",          False, 5,  False),
        ("E: OBV net  N=7",          False, 7,  False),
        ("F: OBV net  N=10",         False, 10, False),
        ("G: OBV strict N=3",        False, 3,  True),
        ("H: OBV strict N=5",        False, 5,  True),
        ("I: C-1/C-2 + OBV net N=5", True,  5,  False),
        ("J: C-1/C-2 + OBV net N=7", True,  7,  False),
    ]

    # Accumulate trades per config across all dates
    all_trades = [[] for _ in CONFIGS]

    for date in all_dates:
        mo = f"{date} 09:15:00"
        mc = f"{date} {EXIT_TIME}:00"

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT timestamp FROM stock_quotes "
            "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC",
            (mo, mc)
        )
        timestamps = [r['timestamp'] for r in cur.fetchall()]

        cur.execute(
            "SELECT symbol, timestamp, price, volume FROM stock_quotes "
            "WHERE timestamp >= ? AND timestamp <= ? ORDER BY symbol, timestamp ASC",
            (mo, mc)
        )
        candles: Dict[str, List[Dict]] = {}
        for r in cur.fetchall():
            s = r['symbol']
            if s not in candles:
                candles[s] = []
            candles[s].append({
                'timestamp': r['timestamp'],
                'price':     float(r['price']),
                'volume':    float(r['volume'] or 0),
            })
        conn.close()

        if not timestamps:
            continue

        prev = prev_close_by_date[date]
        for i, (_, use_vol, obv_lb, obv_st) in enumerate(CONFIGS):
            day_trades = run_day(date, prev, candles, timestamps, lot_sizes,
                                 use_vol, obv_lb, obv_st)
            all_trades[i].extend(day_trades)

    # ── Summary table ────────────────────────────────────────────────────────
    summaries = [summarise(t, all_dates) for t in all_trades]

    W = 130
    print("\n" + "=" * W)
    print(f"VWAP OBV FILTER BACKTEST  |  Top {TOP_N}  |  TSL {TRAILING_SL_PCT}%  |  "
          f"{ALERT_START_TIME}–{EXIT_TIME}  |  Last {LAST_N_DAYS} days")
    print(f"  {len(all_dates)} trading days: {all_dates[0]} → {all_dates[-1]}")
    print("=" * W)

    hdr = (f"  {'Config':<30}  {'Tr':>4}  {'Win%':>6}  {'Net P&L':>11}  "
           f"{'Avg/tr':>8}  {'G/R':>5}  {'MaxDD':>10}  {'TSL':>4}  {'EOD':>4}  "
           f"{'AvgWin':>8}  {'AvgLoss':>9}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    best_net = max(s['net'] for s in summaries)

    for (lbl, *_), s in zip(CONFIGS, summaries):
        marker = "  ◀ BEST" if s['net'] == best_net and s['n'] > 0 else ""
        print(
            f"  {lbl:<30}  {s['n']:>4}  {s['wr']:>5.1f}%  "
            f"₹{s['net']:>+10,.0f}  ₹{s['avg']:>+7,.0f}  "
            f"{s['green']}/{s['red']:>2}  ₹{s['max_dd']:>9,.0f}  "
            f"{s['tsl']:>4}  {s['eod']:>4}  "
            f"₹{s['avg_win']:>+7,.0f}  ₹{s['avg_loss']:>+8,.0f}"
            f"{marker}"
        )

    # ── Day-by-day table (A, B, D, E, I) ────────────────────────────────────
    SHOW_IDXS = [0, 1, 3, 4, 8]   # A, B, D, E, I
    SHOW_LBLS = [CONFIGS[i][0][:14].strip() for i in SHOW_IDXS]

    print(f"\n{'─'*W}")
    print("  DAY-BY-DAY  (A=Baseline | B=Live C-1/C-2 | D=OBV-net-5 | E=OBV-net-7 | I=C-1/C-2+OBV-5)")
    print(f"{'─'*W}")

    col_hdr = f"  {'Date':10}"
    for lbl in SHOW_LBLS:
        col_hdr += f"  {'Tr':>2} {'W':>2}  {'Net':>10}  {'Cum':>10}"
    print(col_hdr)
    print("  " + "-" * (len(col_hdr) - 2))

    cums = [0.0] * len(SHOW_IDXS)
    for date in all_dates:
        row = f"  {date}"
        has_any = False
        for j, idx in enumerate(SHOW_IDXS):
            day_t = [t for t in all_trades[idx] if t['date'] == date]
            n_t   = len(day_t)
            n_w   = sum(1 for t in day_t if t['net'] > 0)
            day_n = sum(t['net'] for t in day_t)
            cums[j] += day_n
            icon  = "✅" if day_n > 0 else ("⚪" if n_t == 0 else "❌")
            row  += f"  {n_t:>2} {n_w:>2}  {icon}₹{day_n:>+7,.0f}  ₹{cums[j]:>+8,.0f}"
            if n_t > 0:
                has_any = True
        if has_any:
            print(row)

    # ── Signals filtered by OBV (per config) ─────────────────────────────────
    print(f"\n{'─'*W}")
    print("  TRADES COMPARISON vs BASELINE (signals added/removed by each filter)")
    print(f"{'─'*W}")
    base_n = summaries[0]['n']
    for (lbl, *_), s in zip(CONFIGS[1:], summaries[1:], strict=False):
        diff = s['n'] - base_n
        sign = f"+{diff}" if diff >= 0 else str(diff)
        print(f"  {lbl:<30}  trades {sign:>5} vs baseline  "
              f"net Δ = ₹{s['net'] - summaries[0]['net']:>+,.0f}")

    # ── Per-symbol for best OBV config ────────────────────────────────────────
    best_idx = max(range(len(summaries)), key=lambda i: summaries[i]['net'])
    best_lbl = CONFIGS[best_idx][0]
    sym_stats: Dict[str, Dict] = {}
    for t in all_trades[best_idx]:
        s = t['symbol']
        if s not in sym_stats:
            sym_stats[s] = {'n': 0, 'wins': 0, 'net': 0.0}
        sym_stats[s]['n']    += 1
        sym_stats[s]['wins'] += 1 if t['net'] > 0 else 0
        sym_stats[s]['net']  += t['net']

    print(f"\n{'─'*W}")
    print(f"  PER-SYMBOL — {best_lbl}  (sorted by net P&L)")
    print(f"{'─'*W}")
    print(f"  {'Symbol':12}  {'Tr':>3}  {'Win%':>6}  {'Net P&L':>11}")
    print(f"  {'-'*12}  {'-'*3}  {'-'*6}  {'-'*11}")
    for sym, s in sorted(sym_stats.items(), key=lambda x: x[1]['net'], reverse=True):
        icon = "✅" if s['net'] > 0 else "❌"
        wr   = s['wins'] / s['n'] * 100 if s['n'] else 0
        print(f"  {icon} {sym:12}  {s['n']:>3}  {wr:>5.1f}%  ₹{s['net']:>+10,.0f}")

    print(f"\n⚠️  Charges: ₹40 brok | STT 0.02% sell | Exchange 0.00188% | SEBI | Stamp | GST 18%")
    print(f"   OBV net  : skip if OBV[now] < OBV[now-N] (LONG) or OBV[now] > OBV[now-N] (SHORT)")
    print(f"   OBV strict: skip if ALL last N consecutive OBV moves are against direction")
    print(f"   C-1/C-2  : touch candle delta ≥ {VOL_C1_MIN}× avg  AND  prior candle delta < {VOL_C2_MAX}× avg")


if __name__ == "__main__":
    run()
