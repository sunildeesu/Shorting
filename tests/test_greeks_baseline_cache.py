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
from datetime import datetime

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


class GreeksBaselineCacheTest(unittest.TestCase):

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp(prefix='greeks_cache_test_')
        self.addCleanup(shutil.rmtree, self.cache_dir, True)

    def _tracker(self):
        """Tracker with only the state the cache methods touch (no broker)"""
        tracker = GreeksDifferenceTracker.__new__(GreeksDifferenceTracker)
        tracker.cache = UnifiedDataCache(cache_dir=self.cache_dir)
        tracker.baseline_greeks = {}
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


if __name__ == '__main__':
    unittest.main()
