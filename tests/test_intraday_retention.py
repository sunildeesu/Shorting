#!/usr/bin/env python3
"""
Regression test: intraday candle retention honours its configured value.

The central DB keeps 5-minute bars for chart-pattern work in a sibling project, so
cleanup_old_data() must delete exactly what INTRADAY_CANDLE_RETENTION_DAYS says and
nothing more. Two things are pinned:

  * the configured window is respected in both directions - a low value deletes old
    bars, and RAISING the value stops deleting bars a lower value used to delete;
  * the intraday window is independent of the quote-table window. stock/nifty/vix
    quotes are tick-level rows on a deliberate 1-day retention; widening the candle
    window must not widen theirs.

Also pinned: the shipped default keeps at least a year of bars, because a
pattern detector working on 5m/10m/15m/1h charts needs real history, and the
7-day default that preceded it left ~16 sessions.

Runs offline against a temporary database - nothing touches data/central_quotes.db.
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from central_quote_db import CentralQuoteDB

IST = timezone(timedelta(hours=5, minutes=30))


class IntradayRetentionTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='intraday_retention_test_')
        self.db_path = os.path.join(self.tmpdir, 'central_quotes.db')
        self.db = CentralQuoteDB(db_path=self.db_path, mode='writer')
        self.ages = (3, 10, 100, 400)
        self._seed()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed(self):
        """One 5-minute bar and one stock quote at each age, in days before now."""
        now = datetime.now(IST)
        self.db.store_intraday_candles_batch(
            {'RELIANCE': [{'date': now - timedelta(days=d), 'open': 1.0, 'high': 2.0,
                           'low': 0.5, 'close': 1.5, 'volume': 100}
                          for d in self.ages]},
            '5minute')
        cursor = self.db.conn.cursor()
        cursor.executemany(
            "INSERT INTO stock_quotes (symbol, timestamp, price, last_updated) "
            "VALUES (?, ?, ?, ?)",
            [('RELIANCE', (datetime.now() - timedelta(days=d)).strftime('%Y-%m-%d %H:%M:%S'),
              100.0, now.isoformat()) for d in self.ages])
        self.db.conn.commit()

    def _surviving_candle_ages(self):
        rows = self.db.conn.execute(
            "SELECT timestamp FROM intraday_candles").fetchall()
        now = datetime.now(IST)
        return sorted(round((now - datetime.fromisoformat(ts)).days) for (ts,) in rows)

    def _surviving_quote_count(self):
        return self.db.conn.execute("SELECT COUNT(*) FROM stock_quotes").fetchone()[0]

    def test_low_retention_deletes_older_bars(self):
        with mock.patch.object(config, 'INTRADAY_CANDLE_RETENTION_DAYS', 7):
            self.db.cleanup_old_data(days=1)
        self.assertEqual(self._surviving_candle_ages(), [3])

    def test_raised_retention_keeps_what_the_low_value_deleted(self):
        """The point of the change: a bigger window stops the rolling delete."""
        with mock.patch.object(config, 'INTRADAY_CANDLE_RETENTION_DAYS', 730):
            self.db.cleanup_old_data(days=1)
        self.assertEqual(self._surviving_candle_ages(), [3, 10, 100, 400])

    def test_retention_boundary_is_the_configured_value(self):
        """Not just "more" - the cut lands exactly where the config says."""
        with mock.patch.object(config, 'INTRADAY_CANDLE_RETENTION_DAYS', 200):
            self.db.cleanup_old_data(days=1)
        self.assertEqual(self._surviving_candle_ages(), [3, 10, 100])

    def test_quote_retention_is_unchanged_by_the_candle_window(self):
        """Tick-level quote rows stay on their own 1-day window."""
        with mock.patch.object(config, 'INTRADAY_CANDLE_RETENTION_DAYS', 730):
            self.db.cleanup_old_data(days=1)
        self.assertEqual(self._surviving_quote_count(), 0,
                         "quote tables must keep their 1-day retention")

    def test_shipped_default_keeps_at_least_a_year(self):
        self.assertGreaterEqual(
            config.INTRADAY_CANDLE_RETENTION_DAYS, 365,
            "pattern detection needs real history; see the config.py comment for the "
            "measured disk cost of this window")


if __name__ == '__main__':
    unittest.main(verbosity=2)
