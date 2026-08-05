#!/usr/bin/env python3
"""
Regression test for the Greeks baseline cache round-trip.

The 9:15 AM baseline is written to UnifiedDataCache and read back when the
tracker restarts mid-day. That path was broken because 'greeks_diff' was never
a registered cache data type, so the write was discarded and every later read
logged "No baseline found. Run capture_baseline_greeks() first."

Runs without broker credentials: only the cache write/read methods are exercised.
"""

import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The tracker pulls in broker/notifier modules that are not needed - and must not
# be used - for the cache path. Stub only the ones that are unavailable.
for _name in ['kiteconnect', 'schedule', 'telegram_notifier',
              'black_scholes_greeks', 'api_coordinator']:
    try:
        __import__(_name)
    except ImportError:
        _stub = types.ModuleType(_name)
        _stub.__getattr__ = lambda attr: type(attr, (object,), {})
        sys.modules[_name] = _stub

import config
from unified_data_cache import UnifiedDataCache
from greeks_difference_tracker import GreeksDifferenceTracker


def make_baseline(timestamp=None):
    """A baseline shaped exactly like capture_baseline_greeks() builds it"""
    return {
        'timestamp': timestamp or datetime.now().isoformat(),
        'nifty_spot': 24012.5,
        'atm_strike': 24000,
        'expiry': '2026-08-13',
        'strikes': {
            24000: {'CE': {'delta': 0.51, 'theta': -8.2, 'vega': 12.1},
                    'PE': {'delta': -0.49, 'theta': -7.9, 'vega': 12.0}},
            24050: {'CE': {'delta': 0.44, 'theta': -8.0, 'vega': 11.8},
                    'PE': {'delta': -0.56, 'theta': -8.1, 'vega': 11.9}},
        }
    }


def make_aggregated(nifty, delta):
    """An aggregated snapshot shaped like fetch_live_and_calculate_diff() builds it"""
    return {
        'nifty_spot': nifty,
        'CE': {'delta_diff_sum': delta, 'theta_diff_sum': -1.0, 'vega_diff_sum': 0.5},
        'PE': {'delta_diff_sum': -delta, 'theta_diff_sum': -1.1, 'vega_diff_sum': 0.4}
    }


class RecordingTelegram:
    """Stands in for TelegramNotifier - records instead of sending"""

    def __init__(self):
        self.messages = []

    def _send_message(self, message):
        self.messages.append(message)


class GreeksBaselineCacheTest(unittest.TestCase):

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp(prefix='greeks_cache_test_')
        self.addCleanup(shutil.rmtree, self.cache_dir, True)

    def _tracker(self):
        """Tracker with only the state the cache methods touch (no broker)"""
        tracker = GreeksDifferenceTracker.__new__(GreeksDifferenceTracker)
        tracker.cache = UnifiedDataCache(cache_dir=self.cache_dir)
        tracker.baseline_greeks = {}
        tracker.history = []
        tracker.telegram_sent = False
        tracker.cloud_link = None
        tracker.telegram = RecordingTelegram()
        return tracker

    def _stub_market_inputs(self, tracker):
        """Let the 9:15 capture run without a broker - data shaped like the live feed"""
        tracker.strike_offsets = config.GREEKS_DIFF_STRIKE_OFFSETS
        tracker._get_spot_indices_batch = lambda: {'nifty_spot': 24012.5,
                                                   'india_vix': 0.11}
        tracker._get_next_expiries = lambda count=1: [datetime(2026, 8, 13)]
        tracker._fetch_greeks_for_strikes = lambda expiry, strikes: {
            strike: {'CE': {'delta': 0.5, 'theta': -8.0, 'vega': 12.0},
                     'PE': {'delta': -0.5, 'theta': -8.0, 'vega': 12.0}}
            for strike in strikes
        }

    def _morning_tracker(self):
        """Tracker that captured the 9:15 baseline and ran two 15-minute updates"""
        tracker = self._tracker()
        tracker.baseline_greeks = make_baseline()
        tracker.history = [{'time': '09:15', 'nifty': 24012.5, 'CE_delta': 0.00,
                            'CE_theta': 0.00, 'CE_vega': 0.00, 'PE_delta': 0.00,
                            'PE_theta': 0.00, 'PE_vega': 0.00}]
        tracker._save_baseline_to_cache()

        tracker._append_to_history(make_aggregated(24050.0, 0.12))
        tracker._append_to_history(make_aggregated(24075.0, 0.19))
        return tracker

    def test_baseline_survives_a_restart(self):
        writer = self._tracker()
        writer.baseline_greeks = make_baseline()
        writer._save_baseline_to_cache()

        # Fresh tracker + fresh cache instance = the restart the operator sees
        reader = self._tracker()
        self.assertTrue(reader._load_baseline_from_cache(),
                        "baseline written at 9:15 could not be read back")
        self.assertEqual(reader.baseline_greeks, writer.baseline_greeks)

    def test_strike_keys_stay_integers_across_the_round_trip(self):
        writer = self._tracker()
        writer.baseline_greeks = make_baseline()
        writer._save_baseline_to_cache()

        reader = self._tracker()
        reader._load_baseline_from_cache()

        # fetch_live_and_calculate_diff() feeds these keys straight back into
        # the strike list, so JSON's string keys would corrupt the comparison
        self.assertEqual(sorted(reader.baseline_greeks['strikes'].keys()),
                         [24000, 24050])

    def test_missing_baseline_reports_absence(self):
        self.assertFalse(self._tracker()._load_baseline_from_cache())

    def test_greeks_diff_is_a_registered_cache_type(self):
        cache = UnifiedDataCache(cache_dir=self.cache_dir)
        key = config.GREEKS_BASELINE_CACHE_KEY.format(date='20260804')

        cache.set_data(key, [{'nifty_spot': 24000}], 'greeks_diff')

        self.assertEqual(cache.get_data(key, 'greeks_diff'),
                         [{'nifty_spot': 24000}])

    def test_restart_recovers_the_full_days_history(self):
        morning = self._morning_tracker()

        # Mid-day restart: a fresh process with empty in-memory state
        restarted = self._tracker()
        self.assertTrue(restarted._load_baseline_from_cache())

        # Excel is rewritten from self.history under the fixed daily filename,
        # so a truncated series would overwrite the morning's rows in Drive
        self.assertEqual(restarted.history, morning.history)
        self.assertEqual(restarted.history[0]['time'], '09:15')

    def test_restart_does_not_resend_the_report(self):
        morning = self._morning_tracker()
        self.assertTrue(morning.send_telegram_notification('https://drive/report'))

        restarted = self._tracker()
        restarted._load_baseline_from_cache()

        self.assertTrue(restarted.telegram_sent)
        self.assertFalse(restarted.send_telegram_notification('https://drive/report'))
        self.assertEqual(restarted.telegram.messages, [])

    def test_yesterdays_state_is_not_treated_as_todays(self):
        stale_key = config.GREEKS_BASELINE_CACHE_KEY.format(
            date=(datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
        )
        cache = UnifiedDataCache(cache_dir=self.cache_dir)
        cache.set_data(stale_key, [{'baseline': make_baseline(),
                                    'history': [{'time': '09:15'}],
                                    'telegram_sent': True}], 'greeks_diff')

        today = self._tracker()
        self.assertFalse(today._load_baseline_from_cache())
        self.assertEqual(today.history, [])
        self.assertFalse(today.telegram_sent)

    def test_state_carried_across_midnight_is_not_saved_as_todays(self):
        # A process launched yesterday never exits, and today's 9:15 capture
        # failed - so it still holds yesterday's baseline and rows in memory
        crossed_midnight = self._tracker()
        crossed_midnight.baseline_greeks = make_baseline(
            timestamp=(datetime.now() - timedelta(days=1)).isoformat()
        )
        crossed_midnight.history = [{'time': '09:15', 'nifty': 23900.0}]

        crossed_midnight._append_to_history(make_aggregated(24050.0, 0.12))

        restarted = self._tracker()
        self.assertFalse(restarted._load_baseline_from_cache())
        self.assertEqual(restarted.history, [])

    def test_previous_day_state_under_todays_key_is_rejected(self):
        cache = UnifiedDataCache(cache_dir=self.cache_dir)
        cache.set_data(self._tracker()._baseline_cache_key(), [{
            'baseline': make_baseline(
                timestamp=(datetime.now() - timedelta(days=1)).isoformat()
            ),
            'history': [{'time': '09:15', 'nifty': 23900.0}],
            'telegram_sent': True
        }], 'greeks_diff')

        today = self._tracker()
        self.assertFalse(today._load_baseline_from_cache())
        self.assertEqual(today.baseline_greeks, {})
        self.assertEqual(today.history, [])
        self.assertFalse(today.telegram_sent)

    def test_stale_in_memory_baseline_is_treated_as_absent(self):
        # A process launched yesterday never exits, and today's 9:15 capture
        # failed - the drift must not be measured against yesterday's baseline
        crossed_midnight = self._tracker()
        crossed_midnight.baseline_greeks = make_baseline(
            timestamp=(datetime.now() - timedelta(days=1)).isoformat()
        )
        crossed_midnight.history = [{'time': '09:15', 'nifty': 23900.0}]
        crossed_midnight.telegram_sent = True
        crossed_midnight.cloud_link = 'https://drive/yesterday'

        self.assertIsNone(crossed_midnight.fetch_live_and_calculate_diff())
        self.assertEqual(crossed_midnight.baseline_greeks, {})
        self.assertEqual(crossed_midnight.history, [])
        self.assertFalse(crossed_midnight.telegram_sent)
        self.assertIsNone(crossed_midnight.cloud_link)

    def test_day_rollover_with_a_failed_capture_publishes_nothing(self):
        crossed_midnight = self._tracker()
        crossed_midnight.baseline_greeks = make_baseline(
            timestamp=(datetime.now() - timedelta(days=1)).isoformat()
        )
        crossed_midnight.history = [{'time': '09:15', 'nifty': 23900.0},
                                    {'time': '15:15', 'nifty': 23940.0}]
        crossed_midnight.telegram_sent = True

        exported = []
        crossed_midnight.export_to_excel = lambda: exported.append(
            list(crossed_midnight.history))

        crossed_midnight._scheduled_update()

        # Excel is written under today's fixed daily filename and synced to Drive,
        # so exporting at all here would publish yesterday's rows as today's
        self.assertEqual(exported, [])
        self.assertEqual(crossed_midnight.telegram.messages, [])
        self.assertEqual(crossed_midnight.history, [])
        self.assertEqual(crossed_midnight.baseline_greeks, {})

    def test_new_trading_day_sends_its_own_report(self):
        # Yesterday's process sent its report and is still running today
        tracker = self._tracker()
        tracker.baseline_greeks = make_baseline(
            timestamp=(datetime.now() - timedelta(days=1)).isoformat()
        )
        tracker.history = [{'time': '09:15', 'nifty': 23900.0}]
        tracker.telegram_sent = True
        tracker.cloud_link = 'https://drive/yesterday'
        self._stub_market_inputs(tracker)

        self.assertTrue(tracker.capture_baseline_greeks())
        self.assertFalse(tracker.telegram_sent)
        self.assertIsNone(tracker.cloud_link)

        # A restart before 9:30 must not inherit yesterday's suppression either
        restarted = self._tracker()
        self.assertTrue(restarted._load_baseline_from_cache())
        self.assertFalse(restarted.telegram_sent)

        self.assertTrue(restarted.send_telegram_notification('https://drive/today'))
        self.assertEqual(len(restarted.telegram.messages), 1)


if __name__ == '__main__':
    unittest.main()
