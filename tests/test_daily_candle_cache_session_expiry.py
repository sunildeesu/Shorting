#!/usr/bin/env python3
"""
Regression test: a daily candle cached during a session never outlives that session.

On 2026-08-31, 192 of 193 symbols in data/unified_cache/historical_50d.json were
written at 09:25-09:27 - each holding that day's ten-minute-old partial bar as a
completed daily candle (median volume 7.3% of the prior day). The flat 24h TTL kept
them "fresh" until 09:25 the next morning, past the 09:12 launch of the monitors
that compute ATR from this cache; DALBHARAT's 1.4% bar sat there for three days.

The contract pinned here, for every daily-candle type in UnifiedDataCache:

  * an entry written before the 15:30 NSE close is invalid from that close on;
  * an entry written after the close is valid until the NEXT day's close;
  * weekends and holidays are not special-cased: an entry from Friday evening is
    gone by Monday morning, exactly as historical_data_cache already behaved;
  * historical_data_cache._is_cache_valid gives the same answer for the same
    write/read times - both caches share market_utils.is_daily_candle_cache_valid;
  * intraday types still age out by TTL.

Runs offline with a frozen clock: temporary cache dirs, no Kite, no credentials.
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_utils
import unified_data_cache
from unified_data_cache import UnifiedDataCache

DAILY_TYPES = sorted(UnifiedDataCache.SESSION_BOUND_TYPES)
CANDLES = [{'date': '2026-08-28T00:00:00', 'open': 1, 'high': 2, 'low': 1, 'close': 2, 'volume': 100}]


class FrozenDatetime(datetime):
    """datetime whose now() is whatever the test last set."""
    frozen = None

    @classmethod
    def now(cls, tz=None):
        return cls.frozen


def at(*args):
    return datetime(*args)


class SessionExpiryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='udc_session_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for module in (market_utils, unified_data_cache):
            patcher = mock.patch.object(module, 'datetime', FrozenDatetime)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cache = UnifiedDataCache(cache_dir=self.tmp)

    def write(self, when, data_type):
        FrozenDatetime.frozen = when
        self.cache.set_data('SYM', CANDLES, data_type)

    def read(self, when, data_type):
        FrozenDatetime.frozen = when
        return self.cache.get_data('SYM', data_type)

    def assert_lifetime(self, written, alive, dead, data_type):
        """Entry written at `written` is served at every `alive` time and gone at `dead`."""
        for when in alive:
            self.write(written, data_type)
            self.assertIsNotNone(self.read(when, data_type),
                                 f"{data_type} written {written:%a %d %H:%M} should be valid at {when:%a %d %H:%M}")
        for when in dead:
            self.write(written, data_type)
            self.assertIsNone(self.read(when, data_type),
                              f"{data_type} written {written:%a %d %H:%M} must be expired at {when:%a %d %H:%M}")

    # (a) the 2026-08-31 shape: cached in the first minutes of the session
    def test_entry_cached_during_session_dies_at_that_close(self):
        for data_type in DAILY_TYPES:
            self.assert_lifetime(
                written=at(2026, 8, 31, 9, 25),
                alive=[at(2026, 8, 31, 9, 26), at(2026, 8, 31, 15, 29)],
                dead=[at(2026, 8, 31, 15, 30), at(2026, 8, 31, 15, 31),
                      at(2026, 9, 1, 9, 12)],   # the monitors' launch next morning
                data_type=data_type,
            )

    def test_expired_entry_is_dropped_from_the_file(self):
        self.write(at(2026, 8, 31, 9, 26), 'historical_50d')
        self.assertIsNone(self.read(at(2026, 9, 1, 9, 12), 'historical_50d'))
        reloaded = UnifiedDataCache(cache_dir=self.tmp)
        self.assertNotIn('SYM', reloaded.caches['historical_50d'])

    # (b) cached after the close: complete bars, good until the next close
    def test_entry_cached_after_close_lives_until_next_close(self):
        for data_type in DAILY_TYPES:
            self.assert_lifetime(
                written=at(2026, 8, 31, 16, 0),
                alive=[at(2026, 8, 31, 23, 59), at(2026, 9, 1, 9, 0),
                       at(2026, 9, 1, 9, 12), at(2026, 9, 1, 15, 29)],
                dead=[at(2026, 9, 1, 15, 31), at(2026, 9, 2, 9, 0)],
                data_type=data_type,
            )

    # (c) weekend / holiday: no special casing, same outcome as historical_data_cache
    def test_friday_evening_entry_is_gone_by_monday_morning(self):
        self.assert_lifetime(
            written=at(2026, 8, 28, 16, 0),            # Friday after close
            alive=[at(2026, 8, 29, 10, 0)],            # Saturday morning
            dead=[at(2026, 8, 29, 15, 31),             # Saturday "close" - one redundant refetch, never a partial bar
                  at(2026, 8, 30, 12, 0),              # Sunday
                  at(2026, 8, 31, 9, 12)],             # Monday launch
            data_type='historical_50d',
        )

    def test_dalbharat_partial_friday_bar_does_not_survive_the_weekend(self):
        self.assert_lifetime(
            written=at(2026, 8, 28, 9, 26),            # the entry that sat in the cache for three days
            alive=[at(2026, 8, 28, 15, 0)],
            dead=[at(2026, 8, 28, 15, 31), at(2026, 8, 31, 9, 12)],
            data_type='historical_50d',
        )

    def test_holiday_is_not_bridged(self):
        # 2026-09-14 (Mon) is Ganesh Chaturthi. An entry from the Friday before is not
        # stretched across it, and one written on the holiday itself dies at its 15:30.
        self.assert_lifetime(
            written=at(2026, 9, 11, 16, 0),
            alive=[at(2026, 9, 12, 9, 0)],
            dead=[at(2026, 9, 14, 9, 0), at(2026, 9, 15, 9, 12)],
            data_type='historical_50d',
        )
        self.assert_lifetime(
            written=at(2026, 9, 14, 10, 0),
            alive=[at(2026, 9, 14, 15, 0)],
            dead=[at(2026, 9, 14, 15, 31), at(2026, 9, 15, 9, 12)],
            data_type='historical_50d',
        )

    def test_intraday_types_still_age_by_ttl(self):
        # hourly_10d has a 6h TTL: crossing the close is not what expires it.
        self.assert_lifetime(
            written=at(2026, 8, 31, 10, 0),
            alive=[at(2026, 8, 31, 15, 31)],
            dead=[at(2026, 8, 31, 16, 1)],
            data_type='hourly_10d',
        )

    def test_clear_expired_and_stats_use_the_same_rule(self):
        self.write(at(2026, 8, 31, 9, 26), 'historical_50d')
        FrozenDatetime.frozen = at(2026, 9, 1, 9, 12)
        self.assertEqual(self.cache.get_cache_stats('historical_50d')['expired_stocks'], 1)
        self.assertEqual(self.cache.clear_expired('historical_50d'), 1)


class SharedWithHistoricalDataCacheTest(unittest.TestCase):
    """Both caches must answer identically for the same write time and read time."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hdc_session_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = mock.patch.object(market_utils, 'datetime', FrozenDatetime)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_same_verdict_in_both_caches(self):
        from historical_data_cache import HistoricalDataCache
        hdc = HistoricalDataCache(cache_dir=self.tmp)
        cases = [
            (at(2026, 8, 31, 9, 26), at(2026, 8, 31, 12, 0)),
            (at(2026, 8, 31, 9, 26), at(2026, 8, 31, 15, 31)),
            (at(2026, 8, 31, 9, 26), at(2026, 9, 1, 9, 12)),
            (at(2026, 8, 31, 16, 0), at(2026, 9, 1, 9, 12)),
            (at(2026, 8, 31, 16, 0), at(2026, 9, 1, 15, 31)),
            (at(2026, 8, 28, 16, 0), at(2026, 8, 31, 9, 12)),
        ]
        for written, now in cases:
            path = Path(self.tmp) / 'entry.json'
            path.write_text('[]')
            os.utime(path, (written.timestamp(), written.timestamp()))
            FrozenDatetime.frozen = now
            self.assertEqual(
                hdc._is_cache_valid(path),
                market_utils.is_daily_candle_cache_valid(written, now),
                f"caches disagree for written {written} read {now}")


if __name__ == '__main__':
    unittest.main()
