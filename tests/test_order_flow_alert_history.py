#!/usr/bin/env python3
"""
Regression test: an order flow alert must leave a permanent record, without breaking
the cooldown that suppresses the next one.

alert_history is a COOLDOWN table - PRIMARY KEY (symbol, alert_type) written with
INSERT OR REPLACE - so only the last fire per pair ever survived. The subsystem had
been discarding its own evidence since inception: a study of these signals in August
2026 found 892 last-fire rows where 1,554 alerts had actually fired, and had to
reconstruct the real history from application logs instead.

The contract pinned here:
  * every fire appends one row to alert_log, so the same (symbol, alert_type) firing
    twice leaves TWO rows;
  * alert_history still keeps exactly one row per pair, and was_alert_sent_recently()
    still reports the second fire as inside the cooldown window;
  * the append is best-effort: if alert_log cannot be written, the cooldown row is
    still committed, because an uncooled alert re-fires every cycle.

Runs offline against a temporary database file - nothing touches data/.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from order_flow_db import OrderFlowDB


class OrderFlowAlertHistoryTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='order_flow_db_test_')
        self.db_path = os.path.join(self.tmpdir, 'order_flow.db')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

        self.db = OrderFlowDB(db_path=self.db_path, mode="writer")
        self.addCleanup(self.db.close)
        # A test that wrote to the deployed database would corrupt live cooldown state.
        self.assertTrue(self.db.db_path.startswith(self.tmpdir))
        self.assertNotEqual(self.db.db_path, config.ORDER_FLOW_DB_FILE)

    def rows(self, table):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                f"SELECT symbol, alert_type, fired_at FROM {table} ORDER BY rowid"
            ).fetchall()
        finally:
            conn.close()

    def test_repeat_alert_appends_history_and_still_cools_down(self):
        self.db.record_alert('RELIANCE', 'BEARISH')
        self.assertTrue(self.db.was_alert_sent_recently('RELIANCE', 'BEARISH'))

        # Same pair fires again - what INSERT OR REPLACE used to erase.
        self.db.record_alert('RELIANCE', 'BEARISH')

        log = self.rows('alert_log')
        self.assertEqual(len(log), 2, "both fires must survive in alert_log")
        self.assertEqual([r[:2] for r in log],
                         [('RELIANCE', 'BEARISH'), ('RELIANCE', 'BEARISH')])

        # ...while the cooldown table keeps doing its one-row-per-pair job.
        cooldown = self.rows('alert_history')
        self.assertEqual(len(cooldown), 1, "cooldown must stay one row per pair")
        self.assertTrue(self.db.was_alert_sent_recently('RELIANCE', 'BEARISH'),
                        "the second fire must still be suppressed by cooldown")

    def test_history_outlives_the_cooldown_window(self):
        """The point of the log: evidence must survive after cooldown has expired."""
        self.db.record_alert('TCS', 'ABSORPTION')

        stale = (datetime.now() - timedelta(minutes=config.ORDER_FLOW_COOLDOWN_MINUTES + 5)
                 ).strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE alert_history SET fired_at = ?", (stale,))
        conn.execute("UPDATE alert_log SET fired_at = ?", (stale,))
        conn.commit()
        conn.close()

        self.assertFalse(self.db.was_alert_sent_recently('TCS', 'ABSORPTION'),
                         "an expired cooldown must let the alert fire again")

        self.db.record_alert('TCS', 'ABSORPTION')

        log = self.rows('alert_log')
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0][2], stale,
                         "the old fire's timestamp must not be rewritten")

    def test_other_pairs_are_not_disturbed(self):
        self.db.record_alert('INFY', 'BEARISH')
        self.db.record_alert('INFY', 'ABSORPTION')
        self.db.record_alert('WIPRO', 'BEARISH')
        self.db.record_alert('INFY', 'BEARISH')

        self.assertEqual(len(self.rows('alert_log')), 4)
        self.assertEqual(len(self.rows('alert_history')), 3)
        self.assertTrue(self.db.was_alert_sent_recently('WIPRO', 'BEARISH'))
        self.assertFalse(self.db.was_alert_sent_recently('WIPRO', 'ABSORPTION'))

    def test_log_failure_cannot_break_the_cooldown(self):
        """
        Record-keeping is best-effort; suppression is not.

        Simulated by removing alert_log, which is the one way this can happen in
        production: code deployed against a database whose schema predates the table.
        """
        self.db.conn.execute("DROP TABLE alert_log")
        self.db.conn.commit()

        self.db.record_alert('HDFCBANK', 'BULLISH')

        self.assertTrue(self.db.was_alert_sent_recently('HDFCBANK', 'BULLISH'),
                        "a failed append must not leave the alert uncooled")
        self.assertEqual(len(self.rows('alert_history')), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
