#!/usr/bin/env python3
"""
VWAP Volume 5-Candle Deep Analysis
====================================
For every VWAP touch, capture volume ratios for C-1 through C-5.
Classify each as: L=low(<1.0×)  N=normal(1.0-1.5×)  H=high(>1.5×)

Outputs:
  1. Consolidated heatmap — all 5 positions in one view
  2. Volume trend patterns (rising/falling into touch)
  3. All significant 5-candle pattern combos
  4. Filter simulation: require specific volume condition per position

Window: 10:00–14:30 | TSL 0.5% | Last 30 days
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict
from itertools import product

VWAP_TOUCH_THRESHOLD_PCT = 0.15
ALERT_COOLDOWN_MINUTES   = 15
TOP_N                    = 10
ALERT_START_TIME         = "10:00"
EXIT_TIME                = "14:30"
MAX_TRADES_PER_STOCK     = 2
TRAILING_SL_PCT          = 0.50
LAST_N_DAYS              = 30
LOOKBACK                 = 5

DB_PATH        = "data/central_quotes.db"
LOT_SIZES_FILE = "data/lot_sizes.json"

# Volume classification thresholds
LOW_MAX  = 1.0   # < 1.0× avg → L
HIGH_MIN = 1.5   # > 1.5× avg → H
# between LOW_MAX and HIGH_MIN → N


def classify(ratio: Optional[float]) -> str:
    if ratio is None: return "?"
    if ratio < LOW_MAX:  return "L"
    if ratio >= HIGH_MIN: return "H"
    return "N"


def load_lot_sizes():
    try:
        with open(LOT_SIZES_FILE) as f: return json.load(f)
    except: return {}


def compute_charges(entry, exit_p, lot, direction):
    buy  = entry  if direction == "LONG" else exit_p
    sell = exit_p if direction == "LONG" else entry
    buy_t, sell_t = buy*lot, sell*lot
    total = buy_t + sell_t
    brok = 40.0; stt = sell_t*0.0002; exc = total*0.0000188
    sebi = total*0.000001; stamp = buy_t*0.00002; gst = (brok+exc)*0.18
    return brok+stt+exc+sebi+stamp+gst


def compute_vwap(candles):
    if len(candles) < 2: return None
    cum_pv = cum_vol = 0.0
    for i, c in enumerate(candles):
        vd = c['volume'] if i==0 else max(0, c['volume']-candles[i-1]['volume'])
        cum_pv += c['price']*vd; cum_vol += vd
    return cum_pv/cum_vol if cum_vol > 0 else None


def get_price_at(candles, ts):
    v = [c for c in candles if c['timestamp'] <= ts]
    return v[-1]['price'] if v else None


def get_vol_ratios(candles_so_far: List[Dict], n: int) -> List[Optional[float]]:
    if len(candles_so_far) < 2: return [None]*n
    deltas = []
    for i, c in enumerate(candles_so_far):
        deltas.append(float(c['volume'] if i==0 else max(0, c['volume']-candles_so_far[i-1]['volume'])))
    baseline = deltas[:-n] if len(deltas) > n else deltas[:max(1, len(deltas)-1)]
    avg = sum(baseline)/len(baseline) if baseline else 0
    ratios = []
    for i in range(n):
        idx = -(i+1)
        if abs(idx) > len(deltas) or avg <= 0: ratios.append(None)
        else: ratios.append(deltas[idx]/avg)
    return ratios


def get_exit_tsl(candles, entry_ts, entry_price, direction, sl_pct, exit_ts):
    sl = entry_price*(1-sl_pct/100) if direction=="LONG" else entry_price*(1+sl_pct/100)
    peak = trough = entry_price
    for c in candles:
        if c['timestamp'] <= entry_ts or c['timestamp'] > exit_ts: continue
        p = c['price']
        if direction == "LONG":
            if p > peak: peak = p
            sl = peak*(1-sl_pct/100)
            if p <= sl: return sl, "TSL"
        else:
            if p < trough: trough = p
            sl = trough*(1+sl_pct/100)
            if p >= sl: return sl, "TSL"
    return get_price_at(candles, exit_ts), "EOD"


def bucket_stats(trades):
    if not trades: return 0, 0.0, 0.0, 0.0
    wins = [t for t in trades if t['net'] > 0]
    net  = sum(t['net'] for t in trades)
    wr   = len(wins)/len(trades)*100
    avg  = net/len(trades)
    return len(trades), wr, net, avg


def run():
    lot_sizes = load_lot_sizes()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT date(timestamp) as d FROM stock_quotes ORDER BY d")
    all_dates_db = [r['d'] for r in cur.fetchall()]
    all_dates    = all_dates_db[-LAST_N_DAYS:]

    print(f"Building prev_close...")
    prev_close_by_date = {}
    for date in all_dates:
        idx = all_dates_db.index(date)
        if idx == 0:
            cur.execute("SELECT symbol, prev_close FROM prev_close_prices")
            prev_close_by_date[date] = {r['symbol']: r['prev_close'] for r in cur.fetchall()}
        else:
            pd = all_dates_db[idx-1]
            cur.execute("""
                SELECT symbol, price FROM stock_quotes
                WHERE timestamp=(SELECT MAX(timestamp) FROM stock_quotes WHERE date(timestamp)=?)
                  AND date(timestamp)=?
            """, (pd, pd))
            prev_close_by_date[date] = {r['symbol']: r['price'] for r in cur.fetchall()}
    conn.close()

    all_trades = []
    for date in all_dates:
        mo = f"{date} 09:15:00"; mc = f"{date} {EXIT_TIME}:00"
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; cur = conn.cursor()
        cur.execute("SELECT DISTINCT timestamp FROM stock_quotes WHERE timestamp>=? AND timestamp<=? ORDER BY timestamp ASC", (mo,mc))
        timestamps = [r['timestamp'] for r in cur.fetchall()]
        cur.execute("SELECT symbol,timestamp,price,volume FROM stock_quotes WHERE timestamp>=? AND timestamp<=? ORDER BY symbol,timestamp ASC", (mo,mc))
        candles = {}
        for r in cur.fetchall():
            s = r['symbol']
            if s not in candles: candles[s] = []
            candles[s].append({'timestamp':r['timestamp'],'price':r['price'],'volume':r['volume']})
        conn.close()
        if not timestamps: continue

        alert_start = f"{date} {ALERT_START_TIME}:00"
        exit_ts     = f"{date} {EXIT_TIME}:00"
        cooldown    = {}; trade_count = defaultdict(int)

        for ts_str in timestamps:
            if ts_str > exit_ts: break
            if ts_str < alert_start: continue
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
            latest = {}
            for sym, cl in candles.items():
                vis = [c for c in cl if c['timestamp'] <= ts_str]
                if vis: latest[sym] = vis[-1]
            movers = []
            for sym, q in latest.items():
                pc = prev_close_by_date[date].get(sym, 0)
                if pc <= 0: continue
                pct = (q['price']-pc)/pc*100
                movers.append((sym, pct, q['price']))
            movers.sort(key=lambda x: abs(x[1]), reverse=True)
            for rank, (symbol, pct_change, price) in enumerate(movers[:TOP_N], 1):
                if trade_count[symbol] >= MAX_TRADES_PER_STOCK: continue
                csf = [c for c in candles.get(symbol,[]) if c['timestamp'] <= ts_str]
                vwap = compute_vwap(csf)
                if vwap is None: continue
                if abs(price-vwap)/vwap*100 > VWAP_TOUCH_THRESHOLD_PCT: continue
                if symbol in cooldown and (ts-cooldown[symbol]).total_seconds()/60 < ALERT_COOLDOWN_MINUTES: continue
                trade_dir = "LONG" if pct_change >= 0 else "SHORT"
                lot = lot_sizes.get(symbol, 1)
                vols = get_vol_ratios(csf, LOOKBACK)   # [C-1, C-2, C-3, C-4, C-5]
                ep, reason = get_exit_tsl(candles.get(symbol,[]), ts_str, price, trade_dir, TRAILING_SL_PCT, exit_ts)
                if ep is None:
                    cooldown[symbol]=ts; trade_count[symbol]+=1; continue
                pnl = (ep-price) if trade_dir=="LONG" else (price-ep)
                gross = pnl*lot; chg = compute_charges(price,ep,lot,trade_dir); net = gross-chg
                all_trades.append({
                    'date':date,'symbol':symbol,'dir':trade_dir,'lot':lot,
                    'entry':price,'exit':ep,'gross':gross,'net':net,'reason':reason,
                    'vols':vols,                          # raw ratios [C-1..C-5]
                    'cls': [classify(v) for v in vols],   # L/N/H labels [C-1..C-5]
                })
                cooldown[symbol]=ts; trade_count[symbol]+=1

    total_n, total_wr, total_net, total_avg = bucket_stats(all_trades)
    W = 115
    print(f"\n{'='*W}")
    print(f"VWAP 5-CANDLE VOLUME ANALYSIS  |  {len(all_dates)} days: {all_dates[0]}→{all_dates[-1]}")
    print(f"  {total_n} trades  |  win rate {total_wr:.1f}%  |  net ₹{total_net:+,.0f}")
    print(f"  L = <1.0× avg  |  N = 1.0–1.5×  |  H = >1.5×  |  ? = insufficient data")
    print(f"{'='*W}")

    # ── Section 1: Consolidated heatmap — all 5 positions ──────────────────
    print(f"\n{'─'*W}")
    print(f"  SECTION 1 — EACH CANDLE POSITION vs BASELINE")
    print(f"  (Reading: for each position, which volume level produces best outcomes?)")
    print(f"{'─'*W}")
    header = f"  {'Pos':6}  {'Vol':22}  {'Trades':>7}  {'%all':>5}  {'Win%':>6}  {'Net P&L':>11}  {'Avg/tr':>8}  {'Avg W':>8}  {'Avg L':>8}"
    print(header)
    print(f"  {'-'*6}  {'-'*22}  {'-'*7}  {'-'*5}  {'-'*6}  {'-'*11}  {'-'*8}  {'-'*8}  {'-'*8}")

    vol_buckets_detail = [
        (0.0, 0.5,  "< 0.5×  (very low) "),
        (0.5, 1.0,  "0.5–1.0× (low)    "),
        (1.0, 1.5,  "1.0–1.5× (normal) "),
        (1.5, 2.5,  "1.5–2.5× (high)   "),
        (2.5, 999,  "> 2.5×  (spike)   "),
    ]
    for pos in range(1, LOOKBACK+1):
        best_wr = -1
        for lo, hi, lbl in vol_buckets_detail:
            sub = [t for t in all_trades
                   if t['vols'][pos-1] is not None and lo <= t['vols'][pos-1] < hi]
            if not sub: continue
            n, wr, net, avg = bucket_stats(sub)
            wins = [t for t in sub if t['net'] > 0]
            losses = [t for t in sub if t['net'] <= 0]
            aw = sum(t['net'] for t in wins)/len(wins) if wins else 0
            al = sum(t['net'] for t in losses)/len(losses) if losses else 0
            pall = n/total_n*100
            flag = " ◀" if wr > best_wr else ""
            if wr > best_wr: best_wr = wr
            print(f"  C-{pos}     {lbl}  {n:>7}  {pall:>4.1f}%  {wr:>5.1f}%  ₹{net:>+9,.0f}  ₹{avg:>+6,.0f}  ₹{aw:>+6,.0f}  ₹{al:>+6,.0f}{flag}")
        # no-data row
        nd = [t for t in all_trades if t['vols'][pos-1] is None]
        if nd: print(f"  C-{pos}     {'(no data)':22}  {len(nd):>7}")
        print()

    # ── Section 2: Volume trend into touch ──────────────────────────────────
    print(f"{'─'*W}")
    print(f"  SECTION 2 — VOLUME TREND INTO TOUCH")
    print(f"  Pattern across C-5→C-4→C-3→C-2→C-1 (left=oldest, right=touch)")
    print(f"{'─'*W}")

    # Summarise trend type for each trade
    def trend_type(cls_list):
        # cls_list = [C-1, C-2, C-3, C-4, C-5]
        # Reverse to chronological: C-5, C-4, C-3, C-2, C-1
        chron = list(reversed(cls_list))
        if '?' in chron: return "incomplete"
        # Identify pattern
        last = chron[-1]   # C-1 (touch)
        prev = chron[:-1]  # C-5 to C-2
        if last == 'H' and all(c == 'L' for c in prev[-2:]): return "quiet→spike (C-2L+C-1H)"
        if last == 'H' and prev[-1] == 'L':                  return "dip→spike (C-2L,C-1H)"
        if last == 'H':                                       return "spike touch (C-1H, mixed)"
        if last == 'L' and all(c == 'L' for c in prev):      return "all quiet (all L)"
        if last == 'L' and any(c == 'H' for c in prev):      return "fading (H→L into touch)"
        if last == 'N':                                       return "normal touch (C-1N)"
        return "other"

    trend_groups = defaultdict(list)
    for t in all_trades:
        trend_groups[trend_type(t['cls'])].append(t)

    print(f"  {'Pattern':38}  {'Trades':>7}  {'Win%':>6}  {'Net P&L':>11}  {'Avg/tr':>8}")
    print(f"  {'-'*38}  {'-'*7}  {'-'*6}  {'-'*11}  {'-'*8}")
    # Sort by avg/trade descending
    trend_rows = []
    for pattern, trades in trend_groups.items():
        n, wr, net, avg = bucket_stats(trades)
        trend_rows.append((pattern, n, wr, net, avg))
    for pattern, n, wr, net, avg in sorted(trend_rows, key=lambda x: x[4], reverse=True):
        flag = "  ◀ BEST" if avg > 1000 else ("  ◀ AVOID" if avg < -500 and n >= 10 else "")
        print(f"  {pattern:38}  {n:>7}  {wr:>5.1f}%  ₹{net:>+9,.0f}  ₹{avg:>+6,.0f}{flag}")

    # ── Section 3: All 5-position LNH combos (min 8 trades) ────────────────
    print(f"\n{'─'*W}")
    print(f"  SECTION 3 — FULL 5-CANDLE PATTERN COMBOS  (C-5 C-4 C-3 C-2 C-1, min 8 trades)")
    print(f"  Sorted by avg/trade — reveals exact patterns to trade or avoid")
    print(f"{'─'*W}")
    print(f"  {'C5 C4 C3 C2 C1':16}  {'Trades':>7}  {'Win%':>6}  {'Net P&L':>11}  {'Avg/tr':>8}  {'Avg W':>8}  {'Avg L':>8}")
    print(f"  {'-'*16}  {'-'*7}  {'-'*6}  {'-'*11}  {'-'*8}  {'-'*8}  {'-'*8}")

    combo_rows = []
    for combo in product('LNH', repeat=5):
        # combo[0]=C-5, combo[4]=C-1  (chronological)
        # trade cls = [C-1, C-2, C-3, C-4, C-5] so reverse
        pattern = list(reversed(combo))  # [C-1, C-2, C-3, C-4, C-5]
        sub = [t for t in all_trades
               if t['cls'][:5] == list(pattern) or
               (t['cls'][:5] == list(pattern) and '?' not in t['cls'][:5])]
        # match exactly
        sub = [t for t in all_trades
               if len(t['cls']) >= 5
               and t['cls'][0] == pattern[0]
               and t['cls'][1] == pattern[1]
               and t['cls'][2] == pattern[2]
               and t['cls'][3] == pattern[3]
               and t['cls'][4] == pattern[4]]
        if len(sub) < 8: continue
        n, wr, net, avg = bucket_stats(sub)
        wins   = [t for t in sub if t['net'] > 0]
        losses = [t for t in sub if t['net'] <= 0]
        aw = sum(t['net'] for t in wins)/len(wins) if wins else 0
        al = sum(t['net'] for t in losses)/len(losses) if losses else 0
        combo_rows.append((' '.join(combo), n, wr, net, avg, aw, al))

    for row in sorted(combo_rows, key=lambda x: x[4], reverse=True):
        pat, n, wr, net, avg, aw, al = row
        flag = "  ◀ BEST" if avg > 800 else ("  ◀ AVOID" if avg < -500 else "")
        print(f"  {pat:16}  {n:>7}  {wr:>5.1f}%  ₹{net:>+9,.0f}  ₹{avg:>+6,.0f}  ₹{aw:>+6,.0f}  ₹{al:>+6,.0f}{flag}")

    # ── Section 4: C-1 filter simulation ────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  SECTION 4 — FILTER SIMULATION: require C-1 volume condition")
    print(f"{'─'*W}")
    filters = [
        ("No filter (baseline)",     lambda t: True),
        ("C-1 ≥ 1.5× (HIGH)",        lambda t: t['vols'][0] is not None and t['vols'][0] >= 1.5),
        ("C-1 ≥ 2.0×",               lambda t: t['vols'][0] is not None and t['vols'][0] >= 2.0),
        ("C-1 ≥ 1.5× AND C-2 < 1.0×",lambda t: t['vols'][0] is not None and t['vols'][1] is not None
                                                and t['vols'][0] >= 1.5 and t['vols'][1] < 1.0),
        ("C-1 < 1.0× (LOW)",          lambda t: t['vols'][0] is not None and t['vols'][0] < 1.0),
        ("C-1 1.0–1.5× (NORMAL)",     lambda t: t['vols'][0] is not None and 1.0 <= t['vols'][0] < 1.5),
    ]
    print(f"  {'Filter':38}  {'Trades':>7}  {'Win%':>6}  {'Net P&L':>11}  {'Avg/tr':>8}  {'Green days':>10}  {'Max DD':>10}")
    print(f"  {'-'*38}  {'-'*7}  {'-'*6}  {'-'*11}  {'-'*8}  {'-'*10}  {'-'*10}")

    for label, fn in filters:
        sub = [t for t in all_trades if fn(t)]
        if not sub:
            print(f"  {label:38}  {'0':>7}"); continue
        n, wr, net, avg = bucket_stats(sub)
        day_nets = defaultdict(float)
        for t in sub: day_nets[t['date']] += t['net']
        green = sum(1 for v in day_nets.values() if v > 0)
        total_days = len(all_dates)
        # max drawdown
        cum = pk = dd = 0.0
        for d in all_dates:
            cum += day_nets.get(d, 0); pk = max(pk, cum); dd = max(dd, pk-cum)
        print(f"  {label:38}  {n:>7}  {wr:>5.1f}%  ₹{net:>+9,.0f}  ₹{avg:>+6,.0f}  "
              f"{green}/{total_days}{'':>5}  ₹{dd:>8,.0f}")

    # ── Section 5: Volume ratio raw distribution ─────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  SECTION 5 — RAW VOLUME RATIO DISTRIBUTION (how often each level occurs)")
    print(f"{'─'*W}")
    print(f"  {'':6}  {'<0.5×':>8}  {'0.5–1×':>8}  {'1–1.5×':>8}  {'1.5–2.5×':>9}  {'>2.5×':>8}  {'no data':>8}")
    print(f"  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*9}  {'-'*8}  {'-'*8}")
    ranges = [(0,0.5),(0.5,1.0),(1.0,1.5),(1.5,2.5),(2.5,999)]
    for pos in range(1, LOOKBACK+1):
        counts = []
        for lo, hi in ranges:
            c = sum(1 for t in all_trades if t['vols'][pos-1] is not None and lo <= t['vols'][pos-1] < hi)
            counts.append(f"{c:>5}({c/total_n*100:>4.1f}%)")
        nd = sum(1 for t in all_trades if t['vols'][pos-1] is None)
        print(f"  C-{pos}     {'  '.join(counts)}  {nd:>5}")

    print(f"\n  Baseline: {total_n} trades | win rate {total_wr:.1f}% | net ₹{total_net:+,.0f} | avg ₹{total_net/total_n:+,.0f}/trade")
    print(f"⚠️  TSL 0.5% | 10:00–14:30 | Top-10 F&O movers | L=<1.0× N=1.0-1.5× H=>1.5×")


if __name__ == "__main__":
    run()
