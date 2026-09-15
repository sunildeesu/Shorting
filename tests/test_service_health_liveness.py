#!/usr/bin/env python3
"""
Regression test: service liveness is derived from heartbeat age, never stored.

On 2026-08-31 six monitors died at ~11:16-11:19 and `service_heartbeats.status`
still read 'running' eight hours later, because heartbeat() stored that string and
nothing aged it. The contract pinned here:

  (a) a row whose last_heartbeat is older than its dead threshold reads 'dead'
      regardless of what the status column says;
  (b) a fresh row reads 'running';
  (c) the threshold is per service - a 5-minute monitor is not 'dead' at 6 minutes,
      a 1-minute one is - and unknown services get the documented default;
  (d) the writer no longer stores 'running', and rows left by the old writer are
      blanked, so raw SQL cannot present the column as truth either.

Runs offline against a temporary SQLite file; no Kite, no network.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import service_health
from service_health import (ServiceHealthTracker, derive_status, heartbeat_interval_s,
                            HEARTBEAT_INTERVAL_S, DEFAULT_HEARTBEAT_INTERVAL_S,
                            STALE_FACTOR, DEAD_FACTOR, HEARTBEAT_TS_FORMAT)

NOW = datetime(2026, 8, 31, 19, 30, 0)


def _ts(age_seconds):
    return (NOW - timedelta(seconds=age_seconds)).strftime(HEARTBEAT_TS_FORMAT)


class DeriveStatusTest(unittest.TestCase):

    def test_old_heartbeat_is_dead(self):
        # The report's frozen rows: 11:16-11:19 read at 19:30.
        self.assertEqual(derive_status('stock_monitor', '2026-08-31 11:16:46', NOW), 'dead')
        self.assertEqual(derive_status('cpr_first_touch_monitor', '2026-08-31 11:19:33', NOW), 'dead')

    def test_fresh_heartbeat_is_running(self):
        for svc in HEARTBEAT_INTERVAL_S:
            self.assertEqual(derive_status(svc, _ts(5), NOW), 'running', svc)

    def test_threshold_respects_per_service_interval(self):
        # 6 minutes old: dead for a 1-minute monitor, still running for a 5-minute one.
        self.assertEqual(heartbeat_interval_s('onemin_monitor'), 60)
        self.assertEqual(heartbeat_interval_s('candle_confirmation_monitor'), 300)
        self.assertEqual(derive_status('onemin_monitor', _ts(360), NOW), 'dead')
        self.assertEqual(derive_status('candle_confirmation_monitor', _ts(360), NOW), 'running')
        # A once-a-day job is not dead the same afternoon.
        self.assertEqual(derive_status('double_bottom_position_tracker', _ts(6 * 3600), NOW), 'running')

    def test_stale_band_is_between_factors(self):
        for svc, interval in HEARTBEAT_INTERVAL_S.items():
            self.assertEqual(derive_status(svc, _ts(STALE_FACTOR * interval), NOW), 'running', svc)
            self.assertEqual(derive_status(svc, _ts(STALE_FACTOR * interval + 1), NOW), 'stale', svc)
            self.assertEqual(derive_status(svc, _ts(DEAD_FACTOR * interval), NOW), 'stale', svc)
            self.assertEqual(derive_status(svc, _ts(DEAD_FACTOR * interval + 1), NOW), 'dead', svc)

    def test_unknown_service_uses_documented_default(self):
        self.assertEqual(heartbeat_interval_s('never_heard_of_it'), DEFAULT_HEARTBEAT_INTERVAL_S)
        self.assertEqual(derive_status('never_heard_of_it',
                                       _ts(DEAD_FACTOR * DEFAULT_HEARTBEAT_INTERVAL_S + 1), NOW), 'dead')


class TrackerReadsDerivedStatusTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'service_health.db')

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_old_schema(self, rows):
        # Exactly what the pre-fix writer left behind: status literally 'running'.
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE service_heartbeats (
                service_name TEXT PRIMARY KEY,
                last_heartbeat TEXT NOT NULL,
                status TEXT DEFAULT 'running',
                cycle_count INTEGER DEFAULT 0,
                last_cycle_duration_ms INTEGER
            )""")
        conn.executemany(
            "INSERT INTO service_heartbeats VALUES (?, ?, 'running', 10, 100)", rows)
        conn.commit()
        conn.close()

    def test_stored_running_string_is_ignored(self):
        self._seed_old_schema([
            ('stock_monitor', '2026-08-31 11:16:46'),
            ('onemin_monitor', '2026-08-31 11:19:20'),
            ('candle_confirmation_monitor', _ts(30)),
        ])
        tracker = ServiceHealthTracker(self.db_path)
        by_name = {s['service_name']: s for s in tracker.get_service_status(now=NOW)}
        self.assertEqual(by_name['stock_monitor']['status'], 'dead')
        self.assertEqual(by_name['onemin_monitor']['status'], 'dead')
        self.assertEqual(by_name['candle_confirmation_monitor']['status'], 'running')
        self.assertEqual(by_name['candle_confirmation_monitor']['interval_s'], 300)
        summary = tracker.get_dashboard_data()['summary']
        self.assertEqual(summary['total_services'], 3)
        self.assertNotIn('healthy_services', summary)
        tracker.close()

    def test_column_is_never_running_after_write(self):
        self._seed_old_schema([('stock_monitor', '2026-08-31 11:16:46')])
        tracker = ServiceHealthTracker(self.db_path)   # init blanks leftovers
        tracker.heartbeat('onemin_monitor', 42)         # new writer stores NULL
        tracker.heartbeat('onemin_monitor', 43)         # ...on the update path too
        tracker.close()
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT service_name, status, cycle_count FROM service_heartbeats ORDER BY 1").fetchall()
        conn.close()
        self.assertEqual(rows, [('onemin_monitor', None, 2), ('stock_monitor', None, 10)])

    def test_fresh_heartbeat_reads_running_against_wall_clock(self):
        tracker = ServiceHealthTracker(self.db_path)
        tracker.heartbeat('cpr_first_touch_monitor', 5)
        [svc] = tracker.get_service_status()
        self.assertEqual(svc['status'], 'running')
        tracker.close()


if __name__ == '__main__':
    unittest.main()
