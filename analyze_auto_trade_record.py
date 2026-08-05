#!/usr/bin/env python3
"""
Measure the real track record behind the auto-trader's win-rate claim.

`config.py` and `auto_trader.py` asserted "97% win rate, +1.67% avg P&L over 181 trades
(30 days)" from the day auto_trader.py was created (0bd742e, 2026-02-11). No script in
this repo produces those numbers and no result file records them. This script is the
re-runnable substitute: it measures what the auto-trader's rule would have produced using
the only per-alert outcome data the system actually keeps, the AlertPnLTracker workbook
(`config.ALERT_PNL_EXCEL_PATH`, sheet `Daily_PnL`).

Reconstruction of the auto-trader's rule:
  * alert types  - the auto-trader is driven from rapid_drop_detector._try_auto_trade(),
                   which fires on that detector's own alert types only:
                   5min / volume_spike (DROP -> short) and
                   5min_rise / volume_spike_rise (RISE -> long).
                   `prealert` comes from early_warning_detector.py and is NOT auto-traded.
  * first alert  - _try_auto_trade() returns unless alert_count == 1, i.e. the first
                   alert of the day for that stock. Applied here per (Date, Symbol).
  * P&L sign     - alert_pnl_tracker._compute_pnl() already signs P&L by direction
                   (short for drop, long for rise), so a positive % is a win either way.

Caveats are printed with the results; read them. This is a proxy, not the auto-trader.

Usage:
    venv/bin/python analyze_auto_trade_record.py [--file path/to/alert_pnl_tracker.xlsx]

Read-only: opens the workbook, writes nothing.
"""

import argparse
import collections
import math
import statistics
import sys

import openpyxl

# Alert types rapid_drop_detector.py can auto-trade on. Anything else in the workbook
# (notably `prealert`) never reaches the auto-trader.
AUTO_TRADED_TYPES = {'5min', 'volume_spike', '5min_rise', 'volume_spike_rise'}

SHEET = 'Daily_PnL'


def load_rows(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)[SHEET]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    return [dict(zip(header, r)) for r in rows[1:] if r[0] is not None]


def summarise(rows, column):
    """Win rate / average / spread over the rows that have an outcome in `column`."""
    values = [r[column] for r in rows if r[column] is not None]
    if not values:
        return None
    wins = sum(1 for v in values if v > 0)
    mean = statistics.mean(values)
    stdev = statistics.stdev(values) if len(values) > 1 else 0.0
    stderr = stdev / math.sqrt(len(values)) if values else 0.0
    win_rate = wins / len(values)
    win_stderr = math.sqrt(win_rate * (1 - win_rate) / len(values))
    return {
        'n': len(values),
        'win_rate': 100 * win_rate,
        'win_ci': (100 * (win_rate - 1.96 * win_stderr), 100 * (win_rate + 1.96 * win_stderr)),
        'mean': mean,
        'mean_ci': (mean - 1.96 * stderr, mean + 1.96 * stderr),
        'median': statistics.median(values),
        'stdev': stdev,
        'best': max(values),
        'worst': min(values),
        'sum': sum(values),
    }


def show(label, s):
    if s is None:
        print(f"  {label}: no completed outcomes")
        return
    print(f"  {label}: n={s['n']}  win rate {s['win_rate']:.1f}% "
          f"(95% CI {s['win_ci'][0]:.1f}-{s['win_ci'][1]:.1f}%)  "
          f"avg {s['mean']:+.3f}% (95% CI {s['mean_ci'][0]:+.3f} to {s['mean_ci'][1]:+.3f})  "
          f"median {s['median']:+.3f}%  sd {s['stdev']:.2f}  "
          f"best {s['best']:+.2f}%  worst {s['worst']:+.2f}%")


def best_30day_windows(rows, days, column):
    """Most favourable 30-trading-day window, to test the '30 days' framing of the claim."""
    best_win = best_avg = None
    for i in range(len(days) - 29):
        window = set(days[i:i + 30])
        vals = [r[column] for r in rows
                if str(r['Date']) in window and r[column] is not None]
        if len(vals) < 20:
            continue
        wr = 100 * sum(1 for v in vals if v > 0) / len(vals)
        av = statistics.mean(vals)
        if best_win is None or wr > best_win[1]:
            best_win = (days[i], wr, av, len(vals))
        if best_avg is None or av > best_avg[2]:
            best_avg = (days[i], wr, av, len(vals))
    return best_win, best_avg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default=None,
                    help='alert_pnl_tracker.xlsx (default: config.ALERT_PNL_EXCEL_PATH)')
    args = ap.parse_args()

    path = args.file
    if path is None:
        import config
        path = config.ALERT_PNL_EXCEL_PATH

    rows = load_rows(path)
    days = sorted({str(r['Date']) for r in rows})
    print(f"Workbook: {path}")
    print(f"Alerts logged: {len(rows)} over {len(days)} trading days "
          f"({days[0]} to {days[-1]})")
    print(f"By type: {dict(collections.Counter(r['Type'] for r in rows))}")
    print(f"Missing 15m outcome: {sum(1 for r in rows if r['P&L % 15m'] is None)}, "
          f"missing 30m outcome: {sum(1 for r in rows if r['P&L % 30m'] is None)}")

    tradeable = sorted((r for r in rows if r['Type'] in AUTO_TRADED_TYPES),
                       key=lambda r: (str(r['Date']), str(r['Time'])))

    # First auto-tradeable alert per stock per day (the auto-trader's alert_count == 1 gate).
    first = {}
    for r in tradeable:
        first.setdefault((str(r['Date']), r['Symbol']), r)
    first = list(first.values())

    print(f"\nAuto-tradeable alert types {sorted(AUTO_TRADED_TYPES)}: {len(tradeable)} alerts")
    print(f"After the first-alert-per-stock-per-day gate: {len(first)} "
          f"({len(tradeable) - len(first)} same-stock repeats dropped)")
    fdays = sorted({str(r['Date']) for r in first})
    print(f"Span: {len(fdays)} trading days, {fdays[0]} to {fdays[-1]}")
    print(f"Directions: {dict(collections.Counter(r['Direction'] for r in first))}")

    print("\nWHAT THE AUTO-TRADER'S RULE WOULD HAVE PRODUCED (tracker proxy):")
    show('exit at alert+15m (13 min held; closest to the 10-min exit)',
         summarise(first, 'P&L % 15m'))
    show('exit at alert+30m (28 min held)', summarise(first, 'P&L % 30m'))
    for direction in ('drop', 'rise'):
        show(f'  {direction} only, 15m',
             summarise([r for r in first if r['Direction'] == direction], 'P&L % 15m'))

    print("\nFOR CONTRAST:")
    show('prealert alerts (never auto-traded), 15m',
         summarise([r for r in rows if r['Type'] == 'prealert'], 'P&L % 15m'))
    show('every logged alert, 15m', summarise(rows, 'P&L % 15m'))

    print("\nBEST 30-TRADING-DAY WINDOW ANYWHERE IN THE SAMPLE (>=20 outcomes):")
    bw, ba = best_30day_windows(first, days, 'P&L % 15m')
    if bw:
        print(f"  highest win rate: {bw[1]:.1f}% (avg {bw[2]:+.3f}%, n={bw[3]}) "
              f"starting {bw[0]}")
    if ba:
        print(f"  highest avg P&L:  {ba[2]:+.3f}% (win rate {ba[1]:.1f}%, n={ba[3]}) "
              f"starting {ba[0]}")

    print("""
CAVEATS - every one of these must be read with the numbers above:
  * Exit timing. The tracker enters at alert+2min and exits at alert+15/+30min (13 and 28
    minutes held). The auto-trader enters at the alert and exits after
    AUTO_TRADE_EXIT_MINUTES (10). Bias: unknown sign. A shorter hold captures less of any
    real edge and less mean reversion alike; the 15m column is the closest proxy available
    and the 15m/30m gap here (win rate falls, average goes negative) shows the result is
    sensitive to hold length, so treat the 15m figure as indicative, not exact.
  * Instrument and sizing. The tracker simulates 1 futures lot (lot_size * price move);
    the auto-trader buys/sells cash equity at ~AUTO_TRADE_POSITION_SIZE notional. Only the
    percentage columns are comparable - the rupee columns are not the auto-trader's rupees.
    Bias: none on win rate; the Rs columns overstate the auto-trader's absolute P&L by
    roughly the ratio of lot notional to Rs 10,000.
  * Coverage. alert_pnl_tracker skips any symbol with no NFO lot size, so alerts on
    non-F&O stocks are absent here but ARE traded by the auto-trader. Bias: unknown sign;
    non-F&O names are typically less liquid, which usually makes execution worse, so the
    proxy more likely flatters than penalises.
  * Shared first-alert counter. alert_count comes from the shared AlertHistoryManager file
    and is also incremented by onemin_monitor and stock_monitor, whose alerts this workbook
    does not record. The live auto-trader would therefore skip some trades counted here.
    Bias: reduces trade count; effect on win rate unknown.
  * Concurrency cap. AUTO_TRADE_MAX_POSITIONS would have blocked some of these entries on
    busy days. Bias: reduces trade count; effect on win rate unknown.
  * Costs. Neither brokerage, STT, exchange/SEBI fees, GST, stamp duty, nor market impact
    is modelled, and AUTO_TRADE_PAPER_SLIPPAGE is not applied here. Bias: strictly
    optimistic. An intraday equity round trip on ~Rs 10,000 costs roughly 0.05-0.1% of
    notional, which is larger than the average per-trade result measured above.
  * Unfinished trades. Alerts late in the session never get a +15/+30 min price, so they
    are excluded. Bias: unknown sign, small sample.
""")
    return 0


if __name__ == '__main__':
    sys.exit(main())
