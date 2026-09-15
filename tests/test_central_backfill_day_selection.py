#!/usr/bin/env python3
"""
Regression test: the central backfill judges each trading day on its own rows.

Before this, `get_trading_days_to_backfill()` compared every candidate day
against MAX(timestamp) over the whole stock_quotes table, so a day truncated by
a mid-session crash became invisible the moment a newer day landed - 2026-08-28
(last tick 15:02, 348 of 375 ticks) was never repaired once 08-31 existed.

Pinned here:

  * a truncated past day is selected even when a complete newer day exists;
  * a complete day (375 ticks, last tick 15:29) is skipped;
  * a day with no rows at all is selected;
  * --date forces a named day regardless of the completeness test;
  * re-running over a partially filled day adds only the missing ticks and
    never duplicates or overwrites rows the live collector already wrote.

Runs offline: a fake Kite client, no credentials, and a temporary database -
nothing touches data/central_quotes.db.
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, time as dt_time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import central_data_backfill as cdb
from central_quote_db import CentralQuoteDB

SYMBOLS = ['RELIANCE', 'TCS']
TOKENS = {'RELIANCE': 738561, 'TCS': 2953217}

TODAY = date(2026, 8, 31)      # Monday
FRIDAY = date(2026, 8, 28)     # the day the outage report found unrecoverable


class FakeKite:
    """Returns one bar per minute in [from_date, to_date) and records every call."""

    def __init__(self):
        self.calls = []

    def historical_data(self, instrument_token, from_date, to_date, interval):
        self.calls.append((instrument_token, from_date, to_date, interval))
        bars, t = [], from_date
        while t < to_date:
            bars.append({'date': t, 'open': 1.0, 'high': 2.0, 'low': 0.5,
                         'close': 100.0, 'volume': 10})
            t += timedelta(minutes=1)
        return bars


def session_minutes(day, until=None):
    """Timestamps for every minute from 09:15 up to and including `until` (default 15:29)."""
    t = datetime.combine(day, cdb.MARKET_START)
    end = datetime.combine(day, until or cdb.LAST_TICK_TIME)
    out = []
    while t <= end:
        out.append(t)
        t += timedelta(minutes=1)
    return out


class DaySelectionTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='central_backfill_test_')
        self.db = CentralQuoteDB(db_path=os.path.join(self.tmpdir, 'central_quotes.db'), mode='writer')
        self.kite = FakeKite()
        patches = [
            mock.patch.object(cdb, 'get_central_db_writer', return_value=self.db),
            mock.patch.object(cdb.CentralDataBackfill, '_load_stock_list', return_value=list(SYMBOLS)),
            mock.patch.object(cdb.CentralDataBackfill, '_load_instrument_tokens', return_value=dict(TOKENS)),
            mock.patch.object(cdb, 'is_nse_holiday', return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.backfill = cdb.CentralDataBackfill(self.kite)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # -- helpers -----------------------------------------------------------

    def write_live_day(self, day, until=None, price=50.0):
        """Simulate the live collector's rows: one per symbol per minute, as INSERT OR REPLACE would leave them."""
        cur = self.db.conn.cursor()
        for ts in session_minutes(day, until):
            for sym in SYMBOLS:
                cur.execute(
                    "INSERT OR REPLACE INTO stock_quotes "
                    "(symbol, timestamp, price, volume, oi, oi_day_high, oi_day_low, last_updated) "
                    "VALUES (?, ?, ?, 1, 0, 0, 0, ?)",
                    (sym, ts.strftime('%Y-%m-%d %H:%M:%S'), price, ts.strftime('%Y-%m-%d %H:%M:%S')))
        self.db.conn.commit()

    def rows(self, day):
        cur = self.db.conn.cursor()
        cur.execute("SELECT symbol, timestamp, price FROM stock_quotes WHERE timestamp LIKE ? ORDER BY 1, 2",
                    (day.strftime('%Y-%m-%d') + '%',))
        return cur.fetchall()

    # -- (a) truncated past day behind a complete newer day ----------------

    def test_truncated_past_day_is_selected_despite_complete_newer_day(self):
        self.write_live_day(FRIDAY, until=dt_time(15, 2))
        self.write_live_day(TODAY)
        ticks, last = self.backfill.get_day_coverage(FRIDAY)
        self.assertEqual((ticks, last.time()), (348, dt_time(15, 2)))

        selected = self.backfill.get_trading_days_to_backfill(days=2, today=TODAY)
        self.assertEqual(selected, [FRIDAY])

    # -- (b) complete day skipped -------------------------------------------

    def test_complete_day_is_skipped(self):
        self.write_live_day(FRIDAY)
        self.write_live_day(TODAY)
        self.assertEqual(self.backfill.get_day_coverage(TODAY)[0], cdb.EXPECTED_TICKS_PER_DAY)
        self.assertEqual(self.backfill.get_trading_days_to_backfill(days=2, today=TODAY), [])

    def test_day_ending_at_1529_but_missing_many_interior_ticks_is_incomplete(self):
        self.write_live_day(FRIDAY)
        cur = self.db.conn.cursor()
        cur.execute("DELETE FROM stock_quotes WHERE timestamp BETWEEN ? AND ?",
                    (f"{FRIDAY} 11:00:00", f"{FRIDAY} 11:30:00"))
        self.db.conn.commit()
        self.assertFalse(self.backfill.is_day_complete(FRIDAY))

    def test_day_short_by_one_tick_is_still_complete(self):
        self.write_live_day(FRIDAY)
        cur = self.db.conn.cursor()
        cur.execute("DELETE FROM stock_quotes WHERE timestamp = ?", (f"{FRIDAY} 11:00:00",))
        self.db.conn.commit()
        self.assertTrue(self.backfill.is_day_complete(FRIDAY))

    def test_day_with_no_rows_is_selected(self):
        self.write_live_day(TODAY)
        self.assertEqual(self.backfill.get_day_coverage(FRIDAY), (0, None))
        self.assertEqual(self.backfill.get_trading_days_to_backfill(days=2, today=TODAY), [FRIDAY])

    # -- (c) --date forces a named day --------------------------------------

    def test_forced_date_bypasses_completeness_and_hits_kite_for_that_day_only(self):
        self.write_live_day(FRIDAY)   # complete - the window scan would skip it
        self.write_live_day(TODAY)
        with mock.patch('time.sleep'):
            stats = self.backfill.run_backfill(dates=[FRIDAY])
        self.assertEqual(stats['days_backfilled'], 1)
        requested_days = {c[1].date() for c in self.kite.calls}
        self.assertEqual(requested_days, {FRIDAY})
        # NIFTY + VIX + one call per stock
        self.assertEqual(len(self.kite.calls), 2 + len(SYMBOLS))

    def test_cli_date_flag_is_repeatable_and_passed_through(self):
        seen = {}

        def fake_run(self_, days, dates):
            seen['days'], seen['dates'] = days, dates
            return {'days_backfilled': 0}

        fake_kite_cls = mock.MagicMock()
        fake_kite_cls.return_value.profile.return_value = {'user_name': 'test'}
        with mock.patch.object(cdb.CentralDataBackfill, 'run_backfill', fake_run), \
             mock.patch.object(cdb.CentralDataBackfill, '__init__', return_value=None), \
             mock.patch.dict(sys.modules, {'kiteconnect': mock.MagicMock(KiteConnect=fake_kite_cls)}), \
             mock.patch.object(cdb.logging, 'basicConfig'), \
             mock.patch.object(sys, 'argv', ['central_data_backfill.py', '--date', '2026-08-28', '--date', '2026-08-27']), \
             mock.patch('builtins.print'):
            cdb.run_backfill_standalone()
        self.assertEqual(seen['dates'], [date(2026, 8, 28), date(2026, 8, 27)])

    # -- (d) re-running over a partial day merges, never duplicates ---------

    def test_backfill_over_partial_day_adds_only_missing_ticks_and_keeps_live_rows(self):
        self.write_live_day(FRIDAY, until=dt_time(15, 2), price=50.0)
        self.write_live_day(TODAY)
        before = self.rows(FRIDAY)
        self.assertEqual(len(before), 348 * len(SYMBOLS))

        self.assertEqual(self.backfill.get_trading_days_to_backfill(days=2, today=TODAY), [FRIDAY])
        with mock.patch('time.sleep'):
            stats = self.backfill.run_backfill(dates=[FRIDAY])
        self.assertEqual(stats['stock_records'], (cdb.EXPECTED_TICKS_PER_DAY - 348) * len(SYMBOLS))

        after = self.rows(FRIDAY)
        self.assertEqual(len(after), cdb.EXPECTED_TICKS_PER_DAY * len(SYMBOLS))
        self.assertEqual(len(after), len(set((s, t) for s, t, _ in after)), "duplicate (symbol, timestamp) rows")
        # every live row survives untouched (price 50, not the fake Kite's 100)
        self.assertEqual([r for r in after if r[1] <= f"{FRIDAY} 15:02:00"], before)
        # the new rows are exactly the missing tail
        new_ts = sorted({t for _, t, _ in after} - {t for _, t, _ in before})
        self.assertEqual(new_ts[0], f"{FRIDAY} 15:03:00")
        self.assertEqual(new_ts[-1], f"{FRIDAY} 15:29:00")
        self.assertTrue(self.backfill.is_day_complete(FRIDAY))

        # a second pass over the now-complete day changes nothing
        with mock.patch('time.sleep'):
            stats = self.backfill.run_backfill(dates=[FRIDAY])
        self.assertEqual(stats['stock_records'], 0)
        self.assertEqual(self.rows(FRIDAY), after)


if __name__ == '__main__':
    unittest.main()
