#!/usr/bin/env python3
"""
Regression test: the intraday candle backfill is resumable, idempotent and
safe to interrupt.

The contract pinned here:

  * every planned request spans at most 100 days - Kite's measured limit for
    '5minute' (`InputException: interval exceeds max limit: 100 days`, probed
    against the real API on 2026-08-11);
  * running twice stores the same rows once, and the second run makes NO request
    for a window the first run already settled;
  * a run that dies mid-way leaves a consistent database: whole committed chunks,
    a ledger that is never ahead of the database, and a re-run that finishes the
    job and lands on exactly the row set an uninterrupted run produces;
  * a window Kite has not finished publishing (the last PROVISIONAL_DAYS) is never
    settled, so re-runs repair the three tail bars Kite adds to a session days
    after the close;
  * --dry-run makes no request and creates no database.

Runs offline: a fake Kite client, no credentials, and a temporary database -
nothing touches data/central_quotes.db.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backfill_intraday_candles as bic
from central_quote_db import CentralQuoteDB

IST = timezone(timedelta(hours=5, minutes=30))

TODAY = date(2026, 8, 11)
SYMBOLS = ['RELIANCE', 'TCS']
TOKENS = {'RELIANCE': 738561, 'TCS': 2953217}


class FakeKite:
    """Returns one bar per weekday in the requested window and records every call."""

    def __init__(self, fail_after=None):
        self.calls = []
        self.fail_after = fail_after

    def historical_data(self, token, frm, to, interval):
        self.calls.append((token, frm, to, interval))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise KeyboardInterrupt('simulated Ctrl-C mid-run')
        bars, day = [], frm
        while day <= to:
            if day.weekday() < 5:
                bars.append({
                    'date': datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST),
                    'open': 1.0, 'high': 2.0, 'low': 0.5, 'close': 1.5, 'volume': 10,
                })
            day += timedelta(days=1)
        return bars


class BackfillTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='intraday_backfill_test_')
        self.db_path = os.path.join(self.tmpdir, 'central_quotes.db')
        self.ledger_path = self.db_path + '.backfill.json'
        self.db = CentralQuoteDB(db_path=self.db_path, mode='writer')

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _backfill(self, kite):
        return bic.IntradayBackfill(kite, self.db, TOKENS, self.ledger_path,
                                    interval='5minute', min_interval=0, today=TODAY)

    def _rows(self):
        return self.db.conn.execute(
            "SELECT symbol, timestamp FROM intraday_candles ORDER BY symbol, timestamp"
        ).fetchall()


class RequestSpanTest(BackfillTestCase):

    def test_no_planned_request_exceeds_kites_100_day_limit(self):
        plan = self._backfill(FakeKite()).plan(SYMBOLS, days=1200)
        self.assertTrue(plan)
        for symbol, label, frm, to in plan:
            self.assertLessEqual(
                (to - frm).days + 1, 100,
                f"{symbol} {label} spans {(to - frm).days + 1} days; Kite rejects "
                f"more than 100 for 5minute")

    def test_plan_covers_the_whole_requested_range_without_gaps(self):
        start = TODAY - timedelta(days=400)
        chunks = bic.quarters_between(start, TODAY)
        self.assertLessEqual(chunks[0][1], start, "requested range not covered")
        self.assertEqual(chunks[-1][2], TODAY)
        for earlier, later in zip(chunks, chunks[1:]):
            self.assertEqual(later[1] - earlier[2], timedelta(days=1))

    def test_only_the_last_chunk_is_a_partial_quarter(self):
        """A ledger entry names a quarter, so every settled chunk must be a whole one."""
        chunks = bic.quarters_between(TODAY - timedelta(days=400), TODAY)
        for label, frm, _ in chunks:
            self.assertEqual((frm.month - 1) % 3, 0,
                             f"{label} starts mid-quarter at {frm}; a later run with a "
                             f"bigger --days would skip the part it never fetched")
            self.assertEqual(frm.day, 1)


class IdempotenceTest(BackfillTestCase):

    def test_running_twice_stores_the_same_rows_once(self):
        kite = FakeKite()
        first = self._backfill(kite).run(SYMBOLS, days=365)
        after_first = self._rows()

        second_kite = FakeKite()
        second = self._backfill(second_kite).run(SYMBOLS, days=365)

        self.assertEqual(self._rows(), after_first, "re-run changed the stored rows")
        self.assertEqual(len(after_first), len(set(after_first)), "duplicate rows")
        self.assertGreater(first['fetched'], second['fetched'],
                           "second run re-fetched everything; resume did nothing")
        # Only the unsettled tail may be requested again.
        for token, frm, to, _ in second_kite.calls:
            self.assertGreaterEqual(
                to, TODAY - timedelta(days=bic.PROVISIONAL_DAYS),
                "a settled window was requested again")

    def test_settled_windows_are_recorded_in_the_ledger(self):
        self._backfill(FakeKite()).run(SYMBOLS, days=365)
        with open(self.ledger_path) as f:
            ledger = json.load(f)
        self.assertEqual(ledger['interval'], '5minute')
        self.assertEqual(sorted(ledger['settled']), sorted(SYMBOLS))
        # The quarter still inside the provisional window is deliberately absent.
        self.assertNotIn('2026Q3', ledger['settled']['RELIANCE'])

    def test_a_ledger_for_another_interval_is_ignored(self):
        with open(self.ledger_path, 'w') as f:
            json.dump({'interval': '15minute',
                       'settled': {'RELIANCE': ['2026Q1']}}, f)
        self.assertEqual(self._backfill(FakeKite()).ledger, {})


class InterruptionTest(BackfillTestCase):

    def test_interrupted_run_leaves_a_consistent_database(self):
        kite = FakeKite(fail_after=3)
        with self.assertRaises(KeyboardInterrupt):
            self._backfill(kite).run(SYMBOLS, days=365)

        partial = self._rows()
        self.assertTrue(partial, "nothing was committed before the interruption")
        self.assertEqual(len(partial), len(set(partial)))

        # The ledger never claims more than the database actually holds.
        with open(self.ledger_path) as f:
            settled = json.load(f)['settled']
        stored_quarters = {
            (sym, f"{ts[:4]}Q{(int(ts[5:7]) - 1) // 3 + 1}") for sym, ts in partial}
        for sym, quarters in settled.items():
            for q in quarters:
                self.assertIn((sym, q), stored_quarters,
                              f"ledger settled {sym} {q} with no rows to show for it")

    def test_resuming_after_an_interruption_reaches_the_clean_end_state(self):
        with self.assertRaises(KeyboardInterrupt):
            self._backfill(FakeKite(fail_after=3)).run(SYMBOLS, days=365)
        self._backfill(FakeKite()).run(SYMBOLS, days=365)
        resumed = self._rows()

        reference = os.path.join(self.tmpdir, 'reference.db')
        clean_db = CentralQuoteDB(db_path=reference, mode='writer')
        try:
            bic.IntradayBackfill(FakeKite(), clean_db, TOKENS,
                                 reference + '.backfill.json', interval='5minute',
                                 min_interval=0, today=TODAY).run(SYMBOLS, days=365)
            expected = clean_db.conn.execute(
                "SELECT symbol, timestamp FROM intraday_candles "
                "ORDER BY symbol, timestamp").fetchall()
        finally:
            clean_db.close()

        self.assertEqual(resumed, expected)

    def test_a_failed_fetch_leaves_the_window_unsettled(self):
        """Transient failures must be retried by the next run, not silently dropped."""
        kite = FakeKite()
        kite.historical_data = mock.Mock(side_effect=RuntimeError('boom'))
        with mock.patch.object(bic.time, 'sleep'):  # skip the retry backoff
            stats = self._backfill(kite).run(SYMBOLS, days=365)
        self.assertEqual(stats['fetched'], 0)
        self.assertEqual(stats['failed'], stats['chunks'])
        self.assertFalse(os.path.exists(self.ledger_path))


class DryRunTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='intraday_backfill_dryrun_')
        self.db_path = os.path.join(self.tmpdir, 'does_not_exist.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dry_run_makes_no_request_and_creates_no_database(self):
        argv = ['backfill_intraday_candles.py', '--db', self.db_path, '--dry-run']
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', argv), \
             mock.patch.object(bic, '_load_symbols_and_tokens',
                               return_value=(SYMBOLS, TOKENS)), \
             mock.patch.object(bic, 'KiteConnect') as kite_cls, \
             mock.patch.object(bic, 'CentralQuoteDB') as db_cls, \
             redirect_stdout(out):
            self.assertEqual(bic.main(), 0)

        kite_cls.assert_not_called()
        db_cls.assert_not_called()
        self.assertFalse(os.path.exists(self.db_path))
        self.assertFalse(os.listdir(self.tmpdir))

        plan = out.getvalue()
        for field in ('target db', 'symbols', 'date range', 'requests',
                      'est. runtime', 'est. rows'):
            self.assertIn(field, plan)
        self.assertIn('DRY RUN', plan)

    def test_db_argument_has_no_default(self):
        """No run may reach the live database by omitting an argument."""
        with mock.patch.object(sys, 'argv', ['backfill_intraday_candles.py']), \
             mock.patch.object(sys, 'stderr', io.StringIO()):
            with self.assertRaises(SystemExit):
                bic.main()


if __name__ == '__main__':
    unittest.main(verbosity=2)
