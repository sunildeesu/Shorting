#!/usr/bin/env python3
"""
Regression test: vwap_mover_monitor.run() must end the process when the trading day is over.

The loop used to be an unconditional `while True` — on a closed market it logged, slept 60s
and continued forever. The deployed process therefore ran for 49 consecutive days, which also
meant the 9:12 launcher could never start a fresh one (and its kill-stale-process branch never
ran). run() now returns once _shutdown_reason() fires.

The contract pinned here:
  * NO exit before the day's work is done — the process starts at 9:12, ten minutes before
    is_market_open() turns true, so "market is closed" alone must never end it.
  * exit once EOD_SUMMARY_TIME has passed, the summary is sent, and no trade is still open.
  * a still-open trade or an unsent summary holds the process, but MARKET_CLOSE_TIME is a
    hard backstop so a Telegram outage cannot resurrect the forever-loop.

Runs offline against a fake clock: no DB, no broker, no Telegram, no credentials, and
nothing is written under data/.
"""

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vwap_mover_monitor as vmm
from vwap_mover_monitor import VWAPMoverMonitor

TODAY = datetime.now().strftime('%Y-%m-%d')


class FakeClock:
    """Stands in for the module's `datetime`; sleep() and tick() move it forward."""

    def __init__(self, hhmm):
        self.now_dt = datetime.strptime(f"{TODAY} {hhmm}", "%Y-%m-%d %H:%M")

    def now(self):
        return self.now_dt

    def advance(self, seconds):
        self.now_dt = self.now_dt + vmm.timedelta(seconds=seconds)


class FakeDB:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeNotifier:
    def __init__(self):
        self.debug_messages = []

    def send_debug(self, message):
        self.debug_messages.append(message)
        return True

    def _send_message(self, message):
        self.debug_messages.append(message)
        return True


def make_monitor(**state):
    """A monitor with only the attributes the run loop touches — __init__ hits DB+Telegram."""
    m = object.__new__(VWAPMoverMonitor)
    m.db = FakeDB()
    m.notifier = FakeNotifier()
    m.current_date = TODAY
    m.prev_close = {'RELIANCE': 100.0}
    m.active_trades = {}
    m.day_trade_log = []
    m.eod_summary_sent = False
    for k, v in state.items():
        setattr(m, k, v)
    return m


class ShutdownReasonTests(unittest.TestCase):
    """_shutdown_reason() is the whole exit decision — test it directly."""

    def reason_at(self, hhmm, **state):
        monitor = make_monitor(**state)
        with mock.patch.object(vmm, 'datetime', FakeClock(hhmm)):
            return monitor._shutdown_reason()

    def test_no_exit_at_launch_before_market_opens(self):
        # 9:12 launch: is_market_open() is false until 9:25. Exiting here would make the
        # monitor die every morning before it did any work.
        self.assertIsNone(self.reason_at("09:12"))

    def test_no_exit_during_the_trading_day(self):
        self.assertIsNone(self.reason_at("11:30"))

    def test_no_exit_while_summary_still_unsent(self):
        # Past EOD_SUMMARY_TIME but the summary has not gone out yet (e.g. send failed
        # and is being retried) — the day's work is not finished.
        self.assertIsNone(self.reason_at(vmm.EOD_SUMMARY_TIME, eod_summary_sent=False))

    def test_no_exit_while_a_trade_is_still_open(self):
        self.assertIsNone(self.reason_at(
            vmm.EOD_SUMMARY_TIME,
            eod_summary_sent=True,
            active_trades={'RELIANCE': object()},
        ))

    def test_exits_once_summary_sent_and_no_open_trades(self):
        reason = self.reason_at(vmm.EOD_SUMMARY_TIME, eod_summary_sent=True)
        self.assertIsNotNone(reason)
        self.assertIn("day's work complete", reason)

    def test_market_close_backstop_when_summary_never_sent(self):
        # Telegram outage: eod_summary_sent stays False all afternoon. The process must
        # still not survive the day.
        reason = self.reason_at(
            vmm.MARKET_CLOSE_TIME,
            eod_summary_sent=False,
            active_trades={'RELIANCE': object()},
        )
        self.assertIsNotNone(reason)
        self.assertIn("market closed", reason)

    def test_market_close_backstop_is_the_is_market_open_window_end(self):
        # If config's window moves, the backstop must move with it.
        import config
        self.assertEqual(
            vmm.MARKET_CLOSE_TIME,
            f"{config.MARKET_END_HOUR:02d}:{config.MARKET_END_MINUTE:02d}",
        )
        self.assertLess(vmm.EOD_SUMMARY_TIME, vmm.MARKET_CLOSE_TIME)


class RunLoopTerminationTests(unittest.TestCase):
    """Drive the real run() loop with a fake clock and assert it actually returns."""

    def drive(self, monitor, start_hhmm, market_open, max_iterations=600):
        """Run the loop; sleep() advances the clock. Returns the clock at exit."""
        clock = FakeClock(start_hhmm)
        iterations = {'n': 0}

        def fake_sleep(seconds):
            iterations['n'] += 1
            if iterations['n'] > max_iterations:
                raise AssertionError(
                    f"run() did not exit after {max_iterations} loops "
                    f"(clock at {clock.now_dt:%H:%M}) — the forever-loop is back"
                )
            clock.advance(max(seconds, 1))

        monitor._load_prev_close = lambda: None
        with mock.patch.object(vmm, 'datetime', clock), \
             mock.patch.object(vmm, 'is_market_open', market_open), \
             mock.patch.object(vmm.time, 'sleep', fake_sleep):
            monitor.run()
        return clock

    def test_exits_after_the_eod_summary_on_a_normal_trading_day(self):
        monitor = make_monitor()

        def fake_cycle():
            # Stands in for _run_cycle(): the real one sends the EOD summary via
            # _maybe_send_eod_summary() once EOD_SUMMARY_TIME has passed.
            if vmm.datetime.now().strftime("%H:%M") >= vmm.EOD_SUMMARY_TIME:
                monitor.eod_summary_sent = True

        monitor._run_cycle = fake_cycle
        clock = self.drive(monitor, "12:55", market_open=lambda: True)

        self.assertEqual(clock.now_dt.strftime("%H:%M"), vmm.EOD_SUMMARY_TIME)
        self.assertTrue(monitor.db.closed, "DB connection was not closed on exit")
        self.assertTrue(any("Exiting for the Day" in m for m in monitor.notifier.debug_messages))

    def test_does_not_exit_at_the_912_launch_and_uses_the_real_summary_path(self):
        # Market never opens (holiday, or the 9:12-to-9:25 pre-open window). The loop must
        # keep running past 9:12 and exit only when the real _maybe_send_eod_summary()
        # marks the empty day done at EOD_SUMMARY_TIME.
        monitor = make_monitor()
        monitor._run_cycle = lambda: self.fail("_run_cycle ran while the market was closed")

        clock = self.drive(monitor, "09:12", market_open=lambda: False)

        self.assertEqual(clock.now_dt.strftime("%H:%M"), vmm.EOD_SUMMARY_TIME)
        self.assertTrue(monitor.eod_summary_sent)
        self.assertTrue(monitor.db.closed)

    def test_run_aborts_when_no_prev_close(self):
        # Pre-existing guard: run() sys.exit(1)s before the loop if prev_close is empty.
        monitor = make_monitor(prev_close={})
        with self.assertRaises(SystemExit):
            self.drive(monitor, "09:12", market_open=lambda: False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
