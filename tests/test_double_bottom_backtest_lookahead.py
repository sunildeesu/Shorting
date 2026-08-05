#!/usr/bin/env python3
"""
Regression test: the double-bottom backtest's entry logic cannot see same-day or future data.

backtest_double_bottom_portfolio.build_table() decides on which (symbol, day) pairs the live
monitor would have fired. Three look-ahead biases were found in it by
audit_double_bottom_backtest.py and corrected; together they had inflated the published
3-year return from +83% to +296%. Each is pinned here so it cannot come back:

  L1  the trend gate must not use day i's CLOSE, nor an SMA/ATR window containing day i
  L2  level detection must not see day i's bar at all
  L3  a day whose price sliced through support must still produce a signal, not vanish

The contract the tests enforce is that a row for day i depends only on
  * bars [0, i-1]                     -- history
  * day i's own open / high / low     -- the intraday path, which live sees as it happens
and on NOTHING else: not day i's close, not any bar after i.

Runs offline on synthetic candles: no cached data file, no broker, no credentials.
"""

import os
import sys
import types
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The backtest module imports the broker SDK at module scope but only constructs a client
# inside fetch_candles(), which these tests never call. Stub it if it is not installed.
try:
    import kiteconnect  # noqa: F401
except ImportError:                                          # pragma: no cover
    _stub = types.ModuleType('kiteconnect')
    _stub.KiteConnect = type('KiteConnect', (object,), {})
    sys.modules['kiteconnect'] = _stub

import config
import backtest_double_bottom_portfolio as backtest
from double_bottom_support_monitor import find_double_bottom_setups, atr_percent, sma

BUILD_KWARGS = dict(refresh=True)   # never read or write the shared table pickle


LEVEL = 100.0          # the support level the synthetic series is built around
SIGNAL_INDEX = 140     # bar the retest lands on, given the layout in make_series()


def make_series():
    """
    A synthetic symbol engineered so that exactly one retest signal exists, at SIGNAL_INDEX.

    Laid out to satisfy every live filter at once, which is fiddly enough to be worth
    spelling out (all prices as multiples of LEVEL):

      90 bars   monotonic rise 0.60 -> 0.71   pre-history; a strictly rising series has no
                                              swing lows, so it contributes no setups
      then the 50-bar detection window the signal day sees, cd[i-50 : i]:
        13 bars rise 0.72 -> 0.94             low enough to drag the 50-SMA under the entry
         4 bars pop to 1.03                   price clears the touch band
         1 bar  dip, low 1.002                touch 1
         4 bars pop to ~1.04                  clears the band again (touches must be separate)
         1 bar  dip, low 1.004                touch 2
         4 bars pop to ~1.05                  clears
         1 bar  dip, low 1.000                touch 3 - and the LEVEL itself: strictly the
                                              lowest low, so it is the one unbroken setup
        13 bars rally to 1.125                the middle peak of the W (>= MIN_RALLY_PCT)
         9 bars drift 1.115 -> 1.025          stays clear of the band, so no earlier signal
      1 bar     the retest: opens 1.012, dips to 0.999, closes 1.010
      3 bars    rally away, so no later bar signals either
    """
    candles = []
    start = datetime(2024, 1, 1)

    def push(o, h, l, c):
        candles.append({'date': (start + timedelta(days=len(candles))).strftime('%Y-%m-%d'),
                        'open': o * LEVEL, 'high': h * LEVEL,
                        'low': l * LEVEL, 'close': c * LEVEL})

    def ramp(n, first, last, spread=0.008):
        for k in range(n):
            c = first + (last - first) * k / max(1, n - 1)
            push(c - spread / 2, c + spread, c - spread, c)

    ramp(90, 0.600, 0.710)                     # pre-history
    ramp(13, 0.720, 0.940)                     # window starts here
    ramp(4, 0.970, 1.030)
    push(1.020, 1.025, 1.002, 1.020)           # touch 1
    ramp(4, 1.030, 1.040)
    push(1.030, 1.045, 1.004, 1.020)           # touch 2
    ramp(4, 1.040, 1.050)
    push(1.005, 1.020, 1.000, 1.016)           # touch 3 == the level, closes in upper half
    ramp(13, 1.030, 1.120)                     # the intervening rally
    ramp(9, 1.115, 1.025)                      # drift back toward the level
    push(1.012, 1.015, 0.999, 1.010)           # <- the retest (SIGNAL_INDEX)
    ramp(3, 1.040, 1.080)                      # away again

    return candles, LEVEL


class LookaheadContractTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.candles, cls.level = make_series()
        cls.data = {'SYNTH': cls.candles}
        cls.rows = backtest.build_table(cls.data, **BUILD_KWARGS)

    def test_fixture_produces_exactly_the_one_expected_signal(self):
        """
        Guards every other test in this class.

        The fixture is deterministic, so "no signal" means the fixture broke, not that
        there is nothing to check — without this the whole suite would pass vacuously.
        """
        self.assertEqual([r['i'] for r in self.rows], [SIGNAL_INDEX])
        self.assertAlmostEqual(self.rows[0]['level'], LEVEL, places=9)
        self.assertEqual(self.rows[0]['touches'], config.DOUBLE_BOTTOM_MIN_TOUCHES)

    # -- helpers ---------------------------------------------------------------------

    @staticmethod
    def key(rows):
        """Row identity + every decided field, so a silent change in any of them fails."""
        return sorted((r['symbol'], r['i'], round(r['entry_price'], 6), round(r['level'], 6),
                       r['strength'], r['touches'], round(r['rally'], 6),
                       round(r['atr_pct'], 6) if r['atr_pct'] is not None else None)
                      for r in rows)

    def rebuild(self, mutate):
        """Deep-copy the candles, apply mutate(candles), rebuild the table."""
        candles = [dict(c) for c in self.candles]
        mutate(candles)
        return backtest.build_table({'SYNTH': candles}, **BUILD_KWARGS)

    # -- L2 / future data ------------------------------------------------------------

    def test_bars_after_the_signal_day_cannot_change_it(self):
        """Every bar strictly after day i is unknowable at decision time."""
        signal_i = min(r['i'] for r in self.rows)

        def wreck_the_future(candles):
            for j in range(signal_i + 1, len(candles)):
                candles[j].update(open=1.0, high=1.0, low=1.0, close=1.0)

        after = [r for r in self.rebuild(wreck_the_future) if r['i'] <= signal_i]
        before = [r for r in self.rows if r['i'] <= signal_i]
        self.assertEqual(self.key(before), self.key(after),
                         "a bar after the signal day changed the signal — look-ahead (L2)")

    def test_level_detection_never_sees_the_signal_day(self):
        """
        The level/strength/touches on a row must be reproducible from history alone.

        This is the direct statement of L2: rebuilding the setups from bars [i-lookback, i-1]
        must yield the very level the row was written from.
        """
        lookback = config.DOUBLE_BOTTOM_LOOKBACK_DAYS
        for r in self.rows:
            i = r['i']
            setups = find_double_bottom_setups(
                self.candles[i - lookback:i],
                min_rally_pct=config.DOUBLE_BOTTOM_MIN_RALLY_PCT,
                pivot_bars=config.DOUBLE_BOTTOM_PIVOT_BARS,
                min_days_ago=config.DOUBLE_BOTTOM_MIN_DAYS_AGO,
                max_days_ago=config.DOUBLE_BOTTOM_MAX_DAYS_AGO,
                min_strength=config.DOUBLE_BOTTOM_MIN_STRENGTH,
                touch_tolerance_pct=config.DOUBLE_BOTTOM_TOUCH_TOLERANCE_PCT,
            )
            match = next((s for s in setups if abs(s['level'] - r['level']) < 1e-9), None)
            self.assertIsNotNone(
                match, f"row at i={i} used a level no history-only scan produces (L2)")
            self.assertEqual((match['strength'], match['touches']),
                             (r['strength'], r['touches']),
                             f"row at i={i} scored its level using day i's own bar (L2)")

    # -- L1 / same-day close ---------------------------------------------------------

    def test_signal_day_close_cannot_change_the_signal(self):
        """
        The close is hours away when the monitor fires, so it must not be an input.

        Slamming the close to the day's low is the case the old code got wrong: it dropped
        the day because close <= SMA, keeping only the dips that recovered into the bell.
        """
        signal_i = min(r['i'] for r in self.rows)
        for label, pick in (('close at the low', lambda c: c['low']),
                            ('close at the high', lambda c: c['high'])):
            with self.subTest(label):
                # Only day i's close is forced; earlier closes are legitimate history and
                # later rows are allowed to depend on them, so the comparison stops at i.
                def move_signal_day_close(candles):
                    candles[signal_i]['close'] = pick(candles[signal_i])

                after = [r for r in self.rebuild(move_signal_day_close) if r['i'] <= signal_i]
                before = [r for r in self.rows if r['i'] <= signal_i]
                self.assertEqual(
                    self.key(before), self.key(after),
                    f"day i's close ({label}) changed the signal — look-ahead (L1)")

    def test_indicators_use_completed_bars_only(self):
        """ATR and the trend SMA must be computable without day i (L1)."""
        for r in self.rows:
            i = r['i']
            window = self.candles[max(0, i - backtest.INDICATOR_BARS):i]
            self.assertEqual(r['atr_pct'],
                             atr_percent(window, config.DOUBLE_BOTTOM_ATR_PERIOD),
                             f"row at i={i} sized its stop with day i's own range (L1)")
            trend = sma(window, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD)
            if config.DOUBLE_BOTTOM_REQUIRE_UPTREND:
                self.assertIsNotNone(trend)
                self.assertGreater(r['entry_price'], trend,
                                   f"row at i={i} passed the trend gate on the wrong price")

    # -- L3 / deleted breakdown days --------------------------------------------------

    def test_a_breakdown_day_still_produces_a_signal(self):
        """
        Price slicing down through support must not delete the day.

        Live, the alert fires the first tick price is inside the band; where it ends up is
        the trade's problem, not a reason the trade never happened. The old trigger required
        the day's final low to sit inside the band, which erased exactly the worst losses.
        """
        signal_i = min(r['i'] for r in self.rows)
        original = next(r for r in self.rows if r['i'] == signal_i)

        def slice_through_support(candles):
            c = dict(candles[signal_i])
            c['low'] = original['level'] * 0.90       # 10% below the level: a real breakdown
            c['close'] = original['level'] * 0.91
            candles[signal_i] = c

        after = self.rebuild(slice_through_support)
        row = next((r for r in after if r['i'] == signal_i), None)
        self.assertIsNotNone(row, "a breakdown through support deleted the signal (L3)")
        self.assertAlmostEqual(row['entry_price'], original['entry_price'], places=9,
                               msg="the breakdown changed the fill price it should not have")

    def test_entry_price_is_the_first_band_price_the_path_reaches(self):
        """The fill is decided by open/high/low only — never by the close."""
        prox = config.DOUBLE_BOTTOM_PROXIMITY_PCT
        max_below = config.DOUBLE_BOTTOM_MAX_BELOW_PCT
        for r in self.rows:
            b = self.candles[r['i']]
            top = r['level'] * (1 + prox / 100)
            bottom = r['level'] * (1 - min(prox, max_below) / 100)
            expected = top if b['open'] > top else (bottom if b['open'] < bottom else b['open'])
            self.assertAlmostEqual(r['entry_price'], expected, places=9,
                                   msg=f"row at i={r['i']} did not fill at the band edge "
                                       f"its path first reached")
            self.assertLessEqual(b['low'], top, "signal fired on a day that never reached the band")
            self.assertGreaterEqual(b['high'], bottom, "signal fired below a broken band")


class TableCacheKeyTest(unittest.TestCase):
    """The table pickle must not survive a change to the detection logic."""

    def test_logic_version_is_part_of_the_cache_key(self):
        data = {'SYNTH': make_series()[0]}
        original = backtest.TABLE_LOGIC_VERSION
        key_now = backtest._params_key(data)
        try:
            backtest.TABLE_LOGIC_VERSION = original + 1
            self.assertNotEqual(key_now, backtest._params_key(data),
                                "a table built by older detection logic would be reused")
        finally:
            backtest.TABLE_LOGIC_VERSION = original


if __name__ == '__main__':
    unittest.main(verbosity=2)
