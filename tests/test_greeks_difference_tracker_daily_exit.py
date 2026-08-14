#!/usr/bin/env python3
"""
Regression tests for two related lifecycle bugs in greeks_difference_tracker.py.

Bug 1 (si-greeks-monitor-exit-at-close): start_monitoring()'s main loop only ever
broke on KeyboardInterrupt - any other exception was logged and swallowed, and
outside market hours it just slept forever. There was no path where the process
voluntarily exited, so a previous day's process blocked launchd's daily restart
(KeepAlive: false - if the old process is still alive, launchd never starts a
fresh one). _shutdown_reason()/_shutdown() follow the pattern pinned for the
sibling monitor in tests/test_vwap_mover_monitor_daily_exit.py.

Bug 2 (si-greeks-vix-threshold-restore): current_vix/current_threshold were only
ever set correctly inside capture_baseline_greeks(), which runs once at 9:15 AM.
A restart after 9:15 restored baseline_greeks/history/telegram_sent from cache via
_load_baseline_from_cache() but never touched current_vix or current_threshold, so
predict_daily_outcome() ran the rest of the day on the __init__ default (10%)
instead of the volatility-adaptive band computed from the day's actual VIX.

Runs offline: no Kite, no cache files, no Telegram, no credentials.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import greeks_difference_tracker as gdt
from greeks_difference_tracker import GreeksDifferenceTracker

TODAY = datetime.now().strftime('%Y-%m-%d')
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')


class FakeClock:
    """Stands in for the module's `datetime`; only `.now()` is used by the code under test."""

    def __init__(self, hhmm, date_str=TODAY):
        self.now_dt = datetime.strptime(f"{date_str} {hhmm}", "%Y-%m-%d %H:%M")

    def now(self):
        return self.now_dt


class FakeNotifier:
    def __init__(self, raise_on_send=False):
        self.debug_messages = []
        self.raise_on_send = raise_on_send

    def send_debug(self, message):
        if self.raise_on_send:
            raise RuntimeError("telegram down")
        self.debug_messages.append(message)
        return True


class FakeCache:
    """Stands in for UnifiedDataCache - same get_data/set_data shape, in-memory."""

    def __init__(self):
        self.store = {}

    def set_data(self, key, data, data_type='historical_30d'):
        self.store[(key, data_type)] = data

    def get_data(self, key, data_type='historical_30d'):
        return self.store.get((key, data_type))


def make_tracker(**state):
    """A tracker with only the attributes the code under test touches - __init__
    hits Kite, UnifiedDataCache, Telegram and the API coordinator."""
    t = object.__new__(GreeksDifferenceTracker)
    t.market_start = gdt.config.GREEKS_MARKET_START
    t.market_end = gdt.config.GREEKS_MARKET_END
    t.baseline_greeks = {}
    t.history = []
    t.telegram_sent = False
    t.current_vix = 0.10
    t.current_threshold = 0.100
    t.telegram = FakeNotifier()
    t.cache = FakeCache()
    for k, v in state.items():
        setattr(t, k, v)
    return t


def baseline_for(date_str):
    return {
        'timestamp': f"{date_str}T09:15:00",
        'nifty_spot': 24800,
        'atm_strike': 24800,
        'expiry': '2026-08-14',
        'strikes': {
            24800: {
                'CE': {'delta': 0.5, 'theta': -1.0, 'vega': 2.0},
                'PE': {'delta': -0.5, 'theta': -1.0, 'vega': 2.0},
            }
        },
    }


class ShutdownReasonTests(unittest.TestCase):
    """_shutdown_reason() is the whole exit decision - test it directly."""

    def reason_at(self, hhmm, **state):
        tracker = make_tracker(**state)
        with mock.patch.object(gdt, 'datetime', FakeClock(hhmm)):
            return tracker._shutdown_reason()

    def test_no_exit_during_market_hours_before_day_done(self):
        self.assertIsNone(self.reason_at(
            "11:30", baseline_greeks=baseline_for(TODAY), telegram_sent=True,
        ))

    def test_no_exit_before_market_end_even_with_report_already_sent(self):
        self.assertIsNone(self.reason_at(
            "15:00", baseline_greeks=baseline_for(TODAY), telegram_sent=True,
        ))

    def test_exits_naturally_once_report_sent_and_market_closed(self):
        reason = self.reason_at(
            gdt.config.GREEKS_MARKET_END,
            baseline_greeks=baseline_for(TODAY), telegram_sent=True,
        )
        self.assertIsNotNone(reason)
        self.assertIn("day's work complete", reason)

    def test_backstop_fires_at_market_close_when_natural_condition_never_met(self):
        # Deliberately construct a day where the natural condition never happens
        # (baseline never captured, report never sent - e.g. a total API outage
        # from 9:15 onward). The process must still not survive past market close.
        reason = self.reason_at(
            gdt.config.GREEKS_MARKET_END,
            baseline_greeks={}, telegram_sent=False,
        )
        self.assertIsNotNone(reason)
        self.assertIn("market closed", reason)
        self.assertNotIn("day's work complete", reason)


class ShutdownNotificationTests(unittest.TestCase):
    """_shutdown() must notify, and must not let a notification failure block exit."""

    def test_shutdown_sends_debug_notification(self):
        tracker = make_tracker()
        tracker._shutdown("test reason")
        self.assertEqual(len(tracker.telegram.debug_messages), 1)
        self.assertIn("test reason", tracker.telegram.debug_messages[0])

    def test_shutdown_does_not_raise_if_notification_fails(self):
        tracker = make_tracker(telegram=FakeNotifier(raise_on_send=True))
        try:
            tracker._shutdown("test reason")
        except Exception as exc:
            self.fail(f"_shutdown raised despite notification failure: {exc}")


class VixPersistenceTests(unittest.TestCase):
    """current_vix must survive a mid-day restart, sourced only from same-day cache."""

    def test_save_then_load_round_trips_vix(self):
        with mock.patch.object(gdt, 'datetime', FakeClock("09:15")):
            tracker = make_tracker(baseline_greeks=baseline_for(TODAY), current_vix=0.17)
            tracker._save_baseline_to_cache()

            fresh = make_tracker(cache=tracker.cache)
            loaded = fresh._load_baseline_from_cache()

        self.assertTrue(loaded)
        self.assertAlmostEqual(fresh.current_vix, 0.17)

    def test_restart_recomputes_threshold_from_saved_vix_not_init_default(self):
        # The actual regression test for the reported bug: a mid-day restart used
        # to run the rest of the day on the __init__ default (0.100) because the
        # threshold was never cached or restored alongside the baseline. This
        # would have failed before the fix (restarted.current_threshold stayed
        # 0.100 after _load_baseline_from_cache()).
        with mock.patch.object(gdt, 'datetime', FakeClock("09:15")):
            tracker = make_tracker(baseline_greeks=baseline_for(TODAY), current_vix=0.17)
            tracker._save_baseline_to_cache()

        restarted = make_tracker(cache=tracker.cache)
        self.assertEqual(restarted.current_threshold, 0.100)  # sanity: __init__ default

        with mock.patch.object(gdt, 'datetime', FakeClock("11:00")):
            loaded = restarted._load_baseline_from_cache()

        self.assertTrue(loaded)
        expected = restarted._get_vix_adaptive_threshold(0.17)
        self.assertEqual(restarted.current_threshold, expected)
        self.assertNotEqual(restarted.current_threshold, 0.100)

    def test_stale_baseline_in_cache_does_not_restore_vix(self):
        # _load_baseline_from_cache()'s own staleness guard (baseline captured on a
        # previous trading day) already discards baseline/history/telegram_sent -
        # confirm it covers current_vix too, so a restart can never adopt yesterday's
        # volatility regime.
        tracker = make_tracker(current_vix=0.10, current_threshold=0.100)
        with mock.patch.object(gdt, 'datetime', FakeClock("09:16")):
            key = tracker._baseline_cache_key()
        tracker.cache.store[(key, 'greeks_diff')] = [{
            'baseline': baseline_for(YESTERDAY),
            'history': [],
            'telegram_sent': True,
            'current_vix': 0.30,
        }]

        with mock.patch.object(gdt, 'datetime', FakeClock("09:16")):
            loaded = tracker._load_baseline_from_cache()

        self.assertFalse(loaded)
        self.assertEqual(tracker.current_vix, 0.10)
        self.assertEqual(tracker.current_threshold, 0.100)


if __name__ == '__main__':
    unittest.main(verbosity=2)
