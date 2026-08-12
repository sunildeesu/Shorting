#!/usr/bin/env python3
"""
Backfill 5-minute intraday candles into a central_quotes.db from Kite.

    python backfill_intraday_candles.py --db /path/to/copy.db --dry-run
    python backfill_intraday_candles.py --db /path/to/copy.db --days 365

There is **no default --db**, so no run can write to the live database by accident.

Fetching goes through the same authoritative call the collector uses,
`kite.historical_data(token, from, to, '5minute')` (central_data_collector.py
`refresh_intraday_candles`); storage goes through the same
`CentralQuoteDB.store_intraday_candles_batch`. This script only decides *which
windows to ask for* - it adds no second fetcher and no schema of its own.

MEASURED LIMITS (RELIANCE, 2026-08-11, read-only probe - not quoted from a docstring):
  * One request may span at most **100 days** for `5minute`. Asking for 200 days
    fails with `InputException: interval exceeds max limit: 100 days`.
  * Depth is *not* the 60 days the repo's older docstrings claim: 5-minute bars
    came back for 2016-10-03, the oldest window probed. Depth is not the binding
    constraint; the 100-day request span is.
  * Kite publishes the tail of a session late. Sessions older than ~8 trading days
    return the full 75 bars (09:15..15:25); the most recent sessions stop at 15:10.
    So a day fetched today can still be short three bars, and the same day fetched
    a fortnight later is complete - which is why chunks are only marked settled
    once they are PROVISIONAL_DAYS old (see below).

RESUME / IDEMPOTENCE
Work is split into calendar quarters (<= 92 days, so always inside the 100-day
limit) whose labels do not move when --days changes. A completed (symbol, quarter)
fetch is recorded in a JSON ledger beside the database, `<db>.backfill.json`, and
a re-run makes no request for it. Rows themselves are written with the existing
INSERT OR REPLACE, so even a chunk that is fetched twice stores once.

A quarter is marked settled only when it ended more than PROVISIONAL_DAYS ago;
until then it is re-fetched on every run, which is what repairs the late tail bars
described above.

INTERRUPT SAFETY
Each (symbol, quarter) is one short write transaction followed by an atomic ledger
rewrite. Killing the run mid-way leaves whole committed chunks and a ledger that is
never ahead of the database - at worst one chunk is fetched again next time.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

import config
from central_quote_db import CentralQuoteDB

logger = logging.getLogger(__name__)

#: A full NSE equity session is 09:15..15:25 inclusive at 5-minute resolution.
BARS_PER_SESSION = 75

#: NSE trades ~250 of the 365 calendar days in a year.
TRADING_DAY_FRACTION = 250 / 365

#: Bytes per intraday_candles row including both indexes, measured 2026-08-11 with
#: dbstat on the live database (57,876,480 bytes / 228,507 rows). Also in config.py.
BYTES_PER_ROW = 253

#: A quarter is only recorded as settled once it is this old, because Kite backfills
#: the last bars of a session days after the close (see the module docstring).
PROVISIONAL_DAYS = 14

MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0


def quarters_between(start: date, end: date) -> List[Tuple[str, date, date]]:
    """Split the range covering [start, end] into whole calendar quarters.

    Returns (label, from_date, to_date) oldest first. A quarter is at most 92 days,
    comfortably inside Kite's measured 100-day-per-request limit for '5minute'.

    The first quarter is deliberately NOT clipped to `start`: a ledger entry records
    a quarter label, so the label has to mean the whole quarter or a later run with a
    bigger --days would skip a window it only ever fetched part of. The run therefore
    reaches up to a quarter further back than asked. Only the last quarter is clipped,
    at `end`, and that one is never settled (see PROVISIONAL_DAYS).
    """
    out = []
    year, q = start.year, (start.month - 1) // 3 + 1
    while True:
        q_start = date(year, 3 * (q - 1) + 1, 1)
        q_end = date(year + (q == 4), 3 * q % 12 + 1, 1) - timedelta(days=1)
        if q_start > end:
            break
        out.append((f"{year}Q{q}", q_start, min(q_end, end)))
        year, q = (year + 1, 1) if q == 4 else (year, q + 1)
    return out


class IntradayBackfill:
    """Fetch historical 5-minute bars for many symbols into one central_quotes.db."""

    def __init__(self, kite, db: CentralQuoteDB, tokens: Dict[str, int],
                 ledger_path: str, interval: str = None,
                 min_interval: float = None, today: date = None):
        """
        Args:
            kite: authenticated KiteConnect (or anything exposing historical_data);
                  None is allowed for planning only
            db: CentralQuoteDB opened in writer mode on the TARGET database;
                None is allowed for planning only
            tokens: {symbol: instrument_token}
            ledger_path: JSON file recording settled (symbol, quarter) fetches
            interval: candle interval, default config.INTRADAY_CANDLE_INTERVAL
            min_interval: minimum seconds between requests
            today: reference date for the provisional window (tests inject it)
        """
        self.kite = kite
        self.db = db
        self.tokens = tokens
        self.ledger_path = ledger_path
        self.interval = interval or config.INTRADAY_CANDLE_INTERVAL
        self.min_interval = (config.REQUEST_DELAY_SECONDS
                             if min_interval is None else min_interval)
        self.today = today or date.today()
        self.ledger = self._load_ledger()
        self._last_request = 0.0

    # ---- ledger -------------------------------------------------------------

    def _load_ledger(self) -> Dict[str, set]:
        try:
            with open(self.ledger_path) as f:
                raw = json.load(f)
        except (FileNotFoundError, ValueError):
            return {}
        if raw.get('interval') != self.interval:
            return {}
        return {sym: set(qs) for sym, qs in raw.get('settled', {}).items()}

    def _save_ledger(self):
        """Rewrite the ledger atomically, so an interrupted run never truncates it."""
        tmp = self.ledger_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({
                'interval': self.interval,
                'settled': {s: sorted(q) for s, q in sorted(self.ledger.items())},
            }, f, indent=1)
        os.replace(tmp, self.ledger_path)

    def _is_settled(self, symbol: str, label: str) -> bool:
        return label in self.ledger.get(symbol, ())

    # ---- planning -----------------------------------------------------------

    def plan(self, symbols: List[str], days: int) -> List[Tuple[str, str, date, date]]:
        """Return the (symbol, quarter_label, from, to) chunks that still need a request."""
        chunks = quarters_between(self.today - timedelta(days=days), self.today)
        return [(sym, label, frm, to)
                for sym in symbols if sym in self.tokens
                for label, frm, to in chunks
                if not self._is_settled(sym, label)]

    # ---- fetching -----------------------------------------------------------

    def _throttle(self):
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _fetch(self, token: int, frm: date, to: date) -> Optional[List[Dict]]:
        """One rate-limited historical_data call with bounded retries.

        Returns None when every attempt failed, so the caller leaves the chunk
        unsettled and the next run retries it. Token errors abort the run.
        """
        delay = INITIAL_RETRY_DELAY
        for attempt in range(MAX_RETRIES):
            self._throttle()
            try:
                return self.kite.historical_data(token, frm, to, self.interval)
            except TokenException:
                raise
            except Exception as e:
                logger.warning("fetch %s..%s attempt %d/%d failed: %s",
                               frm, to, attempt + 1, MAX_RETRIES, e)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
        return None

    def run(self, symbols: List[str], days: int) -> Dict[str, int]:
        """Fetch and store every outstanding chunk. Returns run statistics."""
        todo = self.plan(symbols, days)
        stats = {'chunks': len(todo), 'fetched': 0, 'failed': 0, 'rows': 0}
        started = time.monotonic()

        for i, (symbol, label, frm, to) in enumerate(todo, start=1):
            bars = self._fetch(self.tokens[symbol], frm, to)
            if bars is None:
                stats['failed'] += 1
                continue
            stats['fetched'] += 1
            if bars:
                stats['rows'] += self.db.store_intraday_candles_batch(
                    {symbol: bars}, self.interval)
            # Settle only once Kite has stopped adding late bars to this window.
            if to < self.today - timedelta(days=PROVISIONAL_DAYS):
                self.ledger.setdefault(symbol, set()).add(label)
                self._save_ledger()
            if i % 100 == 0:
                elapsed = time.monotonic() - started
                logger.info("progress %d/%d (%.0f%%), %.0f min elapsed, ~%.0f min left",
                            i, len(todo), 100 * i / len(todo), elapsed / 60,
                            (len(todo) - i) * elapsed / i / 60)

        logger.info("done: %(fetched)d chunks fetched, %(failed)d failed, %(rows)d rows",
                    stats)
        return stats


def _load_symbols_and_tokens() -> Tuple[List[str], Dict[str, int]]:
    """F&O universe and instrument tokens, from the same files the collector reads."""
    with open(config.STOCK_LIST_FILE) as f:
        symbols = [s.replace('.NS', '') for s in json.load(f)['stocks']]
    with open('data/instrument_tokens.json') as f:
        tokens = json.load(f)
    return symbols, tokens


def _print_plan(args, symbols, tokens, backfill, chunks):
    covered = quarters_between(backfill.today - timedelta(days=args.days), backfill.today)
    days_covered = sum((to - frm).days + 1 for _, _, frm, to in chunks)
    rows = int(days_covered * TRADING_DAY_FRACTION * BARS_PER_SESSION)
    seconds = len(chunks) * (backfill.min_interval + 0.25)  # +0.25s observed latency
    print(f"target db       {args.db}")
    print(f"ledger          {backfill.ledger_path}")
    print(f"interval        {backfill.interval}")
    print(f"symbols         {len([s for s in symbols if s in tokens])} "
          f"of {len(symbols)} requested have an instrument token")
    print(f"date range      {covered[0][1]} .. {covered[-1][2]} "
          f"(whole quarters covering the last {args.days} days)")
    print(f"requests        {len(chunks)} (calendar quarters, <= 92 days each; "
          f"already-settled chunks cost none)")
    print(f"min interval    {backfill.min_interval}s between requests")
    print(f"est. runtime    {seconds / 60:.0f} min")
    print(f"est. rows       ~{rows:,} fetched -> at most ~{rows * BYTES_PER_ROW / 1e6:,.0f} MB "
          f"incl. indexes ({BYTES_PER_ROW} bytes/row, measured); rows already stored "
          f"are overwritten in place and add nothing")
    print("DRY RUN - no request made, nothing written.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--db', required=True,
                   help='target central_quotes.db. Required: there is deliberately '
                        'no default, so no run can hit the live database by accident.')
    p.add_argument('--days', type=int, default=365,
                   help='how far back to backfill, in calendar days (default 365)')
    p.add_argument('--symbols', help='comma-separated subset, for a trial run')
    p.add_argument('--min-interval', type=float, default=config.REQUEST_DELAY_SECONDS,
                   help=f'seconds between Kite requests '
                        f'(default {config.REQUEST_DELAY_SECONDS}, ~2.5/s)')
    p.add_argument('--dry-run', action='store_true',
                   help='print the plan and exit, making no request and no write')
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    symbols, tokens = _load_symbols_and_tokens()
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(',')}
        symbols = [s for s in symbols if s in wanted]

    if args.dry_run:
        # No KiteConnect and no CentralQuoteDB: a dry run must not open, create or
        # touch the target database at all.
        backfill = IntradayBackfill(None, None, tokens, args.db + '.backfill.json',
                                    min_interval=args.min_interval)
        _print_plan(args, symbols, tokens, backfill,
                    backfill.plan(symbols, args.days))
        return 0

    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    db = CentralQuoteDB(db_path=args.db, mode='writer')
    backfill = IntradayBackfill(kite, db, tokens, args.db + '.backfill.json',
                                min_interval=args.min_interval)
    try:
        backfill.run(symbols, args.days)
    except TokenException as e:
        logger.error("Kite token rejected, stopping: %s", e)
        return 2
    except KeyboardInterrupt:
        logger.warning("interrupted - committed chunks are kept, re-run to continue")
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
