#!/usr/bin/env python3
"""
Manage tracked double-bottom positions.

The monitor opens a tracked position whenever it alerts, and that position holds one of
the DOUBLE_BOTTOM_MAX_SLOTS slots until the tracker exits it. If you did not actually
take a signalled trade, or your fill differed from the alert price, the tracked state
needs correcting by hand — otherwise a phantom position blocks real entries or the
tracker manages the wrong levels.

    list                          show open positions, free slots, closed-trade record
    drop SYMBOL                   remove a signal you never took (frees the slot, NOT
                                  recorded as a trade — keeps the win record honest)
    close SYMBOL --price P        record a manual exit you actually made
    entry SYMBOL --price P        correct the fill price (recomputes stop and target)

Examples:
    venv/bin/python3 manage_double_bottom_positions.py list
    venv/bin/python3 manage_double_bottom_positions.py drop AMBER
    venv/bin/python3 manage_double_bottom_positions.py close TCS --price 4120.50
    venv/bin/python3 manage_double_bottom_positions.py entry TCS --price 4008.00

Author: Claude Code
Date: 2026-07-23
"""

import argparse
import sys
from datetime import datetime

import config
import double_bottom_positions as positions
from double_bottom_support_monitor import stop_distance_pct


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ('y', 'yes')
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _find_open(symbol: str):
    pos = next((p for p in positions.open_positions() if p['symbol'] == symbol), None)
    if not pos:
        open_syms = [p['symbol'] for p in positions.open_positions()]
        print(f"No open position for {symbol}."
              + (f" Open: {', '.join(open_syms)}" if open_syms else " Nothing is open."))
    return pos


def cmd_list(args) -> int:
    data = positions.load()
    open_pos, closed = data['open'], data['closed']

    print(f"\nOPEN POSITIONS — {len(open_pos)} of {config.DOUBLE_BOTTOM_MAX_SLOTS} slots used, "
          f"{positions.slots_free()} free")
    if not open_pos:
        print("  (none)")
    else:
        print(f"  {'symbol':<12}{'entered':<12}{'entry':>10}{'stop':>10}{'arms at':>10}"
              f"{'state':>10}{'strength':>9}")
        for p in open_pos:
            armed = p.get('armed')
            stop = p.get('current_stop', p['stop_price'])
            state = 'LOCKED' if armed else 'open'
            print(f"  {p['symbol']:<12}{p['entry_date']:<12}{p['entry_price']:>10.2f}"
                  f"{stop:>10.2f}{p['target_price']:>10.2f}{state:>10}"
                  f"{p.get('strength', 0):>8.1f}")
            if armed:
                print(f"  {'':<12}└─ locked & trailing "
                      f"{config.DOUBLE_BOTTOM_TRAIL_PCT:.1f}% below high "
                      f"{p.get('high_water', 0):.2f}")

    print(f"\nCLOSED TRADES — {len(closed)}")
    if closed:
        wins = [p for p in closed if p['pnl_pct'] > 0]
        total = sum(p['pnl_pct'] for p in closed)
        for p in closed[-args.last:]:
            print(f"  {p['symbol']:<12}{p['entry_date']} -> {p.get('exit_date', '?')}"
                  f"  {p.get('exit_reason', '?'):<8}{p['pnl_pct']:+8.2f}%")
        print(f"  win rate {len(wins)/len(closed)*100:.1f}%, "
              f"avg {total/len(closed):+.2f}%, sum {total:+.1f}%")
    else:
        print("  (none)")
    print()
    return 0


def cmd_drop(args) -> int:
    pos = _find_open(args.symbol)
    if not pos:
        return 1
    print(f"\n  {args.symbol}: entered {pos['entry_date']} at {pos['entry_price']:.2f}")
    print("  This frees the slot and does NOT record a trade "
          "(use `close` if you were really in it).")
    if not _confirm(f"Drop {args.symbol}?", args.yes):
        print("Cancelled.")
        return 1
    positions.drop(args.symbol)
    print(f"Dropped {args.symbol}. Slots free: {positions.slots_free()}"
          f"/{config.DOUBLE_BOTTOM_MAX_SLOTS}")
    return 0


def cmd_close(args) -> int:
    pos = _find_open(args.symbol)
    if not pos:
        return 1
    pnl = (args.price - pos['entry_price']) / pos['entry_price'] * 100
    date = args.date or datetime.now().strftime('%Y-%m-%d')
    print(f"\n  {args.symbol}: entry {pos['entry_price']:.2f} -> exit {args.price:.2f} "
          f"on {date}  ({pnl:+.2f}%)")
    print("  This IS recorded in the closed-trade record.")
    if not _confirm(f"Close {args.symbol}?", args.yes):
        print("Cancelled.")
        return 1
    positions.close(args.symbol, date, args.price, args.reason)
    print(f"Closed {args.symbol} at {pnl:+.2f}%. Slots free: {positions.slots_free()}"
          f"/{config.DOUBLE_BOTTOM_MAX_SLOTS}")
    return 0


def cmd_entry(args) -> int:
    pos = _find_open(args.symbol)
    if not pos:
        return 1
    # Stop and target hang off the entry price, so they must move with it or the tracker
    # manages levels that belong to a fill you never got.
    stop_pct = pos.get('stop_pct') or stop_distance_pct(pos.get('atr_pct'))
    new_stop = args.price * (1 - stop_pct / 100)
    new_target = args.price * (1 + config.DOUBLE_BOTTOM_TARGET_PCT / 100)
    print(f"\n  {args.symbol} entry {pos['entry_price']:.2f} -> {args.price:.2f}")
    print(f"    stop    {pos['stop_price']:.2f} -> {new_stop:.2f}  (-{stop_pct:.1f}%)")
    print(f"    arms at {pos['target_price']:.2f} -> {new_target:.2f}  "
          f"(+{config.DOUBLE_BOTTOM_TARGET_PCT:.1f}%)")
    if pos.get('armed'):
        print("    NOTE: position is already armed; the tracker recomputes the trail from "
              "price history on its next run.")
    if not _confirm(f"Update {args.symbol}?", args.yes):
        print("Cancelled.")
        return 1
    positions.update(args.symbol, entry_price=args.price, stop_price=new_stop,
                     stop_pct=stop_pct, target_price=new_target)
    print(f"Updated {args.symbol}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--file', help='override the positions file (for testing)')
    sub = ap.add_subparsers(dest='command')

    p_list = sub.add_parser('list', help='show open positions and the closed-trade record')
    p_list.add_argument('--last', type=int, default=10, help='closed trades to show')
    p_list.set_defaults(func=cmd_list)

    p_drop = sub.add_parser('drop', help='remove a signal you never took (frees the slot)')
    p_drop.add_argument('symbol')
    p_drop.add_argument('-y', '--yes', action='store_true')
    p_drop.set_defaults(func=cmd_drop)

    p_close = sub.add_parser('close', help='record a manual exit you actually made')
    p_close.add_argument('symbol')
    p_close.add_argument('--price', type=float, required=True)
    p_close.add_argument('--date', help='exit date YYYY-MM-DD (default: today)')
    p_close.add_argument('--reason', default='manual')
    p_close.add_argument('-y', '--yes', action='store_true')
    p_close.set_defaults(func=cmd_close)

    p_entry = sub.add_parser('entry', help='correct the fill price (recomputes stop/target)')
    p_entry.add_argument('symbol')
    p_entry.add_argument('--price', type=float, required=True)
    p_entry.add_argument('-y', '--yes', action='store_true')
    p_entry.set_defaults(func=cmd_entry)

    args = ap.parse_args()
    if args.file:
        config.DOUBLE_BOTTOM_POSITIONS_FILE = args.file
    if not args.command:
        args.func, args.last = cmd_list, 10
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
