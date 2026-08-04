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


def make_baseline():
    """A baseline shaped exactly like capture_baseline_greeks() builds it"""
    return {
        'timestamp': datetime.now().isoformat(),
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
        tracker.telegram = RecordingTelegram()
        return tracker

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


if __name__ == '__main__':
    unittest.main()
