#!/usr/bin/env python3
"""
Regression test: futures_bid_ask_detector's message must say what it measures.

Investigation si-futures-bidask-alert-correctness found the alert's arithmetic
correct but its label wrong: it sums all 5 depth levels per side and calls the
result "Bid"/"Ask" with no qualifier, while a reader naturally checks it against
top-of-book. The fix (this file's companion change) keeps the comparison and
ranking byte-for-byte unchanged and instead:

  1. prints top-of-book (L1) alongside the 5-level sums,
  2. prints what share of the 5-level bid sits in a single level (concentration),
  3. excludes index symbols (e.g. NIFTYNXT50) from the "stocks" universe,
  4. rebuilds the instrument list when the input stock universe changes.

Runs offline: no broker, no network, no credentials.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from futures_bid_ask_detector import FuturesBidAskDetector, _INDEX_SYMBOLS


def make_mapper(mapping):
    mapper = MagicMock()
    mapper.get_futures_symbol.side_effect = lambda sym: mapping.get(sym)
    return mapper


def depth_quote(buy_levels, sell_levels, ltp=100.0):
    return {
        'depth': {
            'buy': [{'quantity': q} for q in buy_levels],
            'sell': [{'quantity': q} for q in sell_levels],
        },
        'last_price': ltp,
    }


# NHPC worked example from the investigation report, 2026-08-10 13:09:55 IST
NHPC_BUY = [13900, 13900, 6950, 6950, 284950]
NHPC_SELL = [27800, 6950, 6950, 6950, 6950]


class PrintedL1MatchesComputedTest(unittest.TestCase):
    """The printed L1 bid/ask are the same quantities run() computed, not recomputed."""

    def setUp(self):
        self.notifier = MagicMock()
        self.mapper = make_mapper({'NHPC': 'NHPC26AUGFUT'})
        self.detector = FuturesBidAskDetector(MagicMock(), self.mapper, self.notifier)
        self.detector.kite.quote.return_value = {
            'NFO:NHPC26AUGFUT': depth_quote(NHPC_BUY, NHPC_SELL, ltp=76.9),
        }

    def test_l1_in_message_matches_top_of_book(self):
        stats = self.detector.run(['NHPC'])
        row = stats['top5'][0]
        self.assertEqual(row['l1_bid'], 13900)
        self.assertEqual(row['l1_ask'], 27800)
        self.assertEqual(row['bid_qty'], sum(NHPC_BUY))
        self.assertEqual(row['ask_qty'], sum(NHPC_SELL))

        message = self.detector._format(stats['top5'], stats['scanned'], stats['bid_dominant'])
        self.assertIn(f"L1 {row['l1_bid']:,} / {row['l1_ask']:,}", message)
        self.assertIn(f"5-lvl {row['bid_qty']:,} / {row['ask_qty']:,}", message)

    def test_comparison_and_ranking_unchanged(self):
        # bid_qty > ask_qty on the summed 5 levels -- guard and ratio must be untouched
        stats = self.detector.run(['NHPC'])
        row = stats['top5'][0]
        self.assertGreater(row['bid_qty'], row['ask_qty'])
        self.assertAlmostEqual(row['ratio'], sum(NHPC_BUY) / sum(NHPC_SELL))


class ConcentrationTest(unittest.TestCase):
    """Concentration = top single level's share of the 5-level bid total."""

    def setUp(self):
        self.notifier = MagicMock()
        self.mapper = make_mapper({'NHPC': 'NHPC26AUGFUT'})
        self.detector = FuturesBidAskDetector(MagicMock(), self.mapper, self.notifier)

    def test_concentration_matches_hand_computed_value(self):
        self.detector.kite.quote.return_value = {
            'NFO:NHPC26AUGFUT': depth_quote(NHPC_BUY, NHPC_SELL, ltp=76.9),
        }
        stats = self.detector.run(['NHPC'])
        row = stats['top5'][0]
        expected = max(NHPC_BUY) / sum(NHPC_BUY) * 100
        self.assertAlmostEqual(row['concentration'], expected)
        self.assertAlmostEqual(row['concentration'], 87.2, places=1)

        message = self.detector._format(stats['top5'], stats['scanned'], stats['bid_dominant'])
        self.assertIn(f"top level = {row['concentration']:.0f}% of bid", message)

    def test_concentration_on_evenly_spread_book(self):
        # 5 equal levels: top level is exactly 20% of the total
        self.detector.kite.quote.return_value = {
            'NFO:NHPC26AUGFUT': depth_quote([100, 100, 100, 100, 100], [50, 50, 50, 50, 50]),
        }
        stats = self.detector.run(['NHPC'])
        row = stats['top5'][0]
        self.assertAlmostEqual(row['concentration'], 20.0)


class MissingDepthDoesNotCrashTest(unittest.TestCase):
    """A stale/expired contract with no depth (or empty levels) is skipped, not scored."""

    def setUp(self):
        self.notifier = MagicMock()
        self.mapper = make_mapper({'NHPC': 'NHPC26AUGFUT', 'RELIANCE': 'RELIANCE26AUGFUT'})
        self.detector = FuturesBidAskDetector(MagicMock(), self.mapper, self.notifier)

    def test_no_depth_key_is_skipped(self):
        self.detector.kite.quote.return_value = {
            'NFO:NHPC26AUGFUT': {'last_price': 76.9},  # no 'depth' at all
            'NFO:RELIANCE26AUGFUT': depth_quote(NHPC_BUY, NHPC_SELL),
        }
        stats = self.detector.run(['NHPC', 'RELIANCE'])
        self.assertEqual(stats['bid_dominant'], 1)
        self.assertEqual(stats['top5'][0]['symbol'], 'RELIANCE')

    def test_empty_buy_sell_lists_are_skipped(self):
        self.detector.kite.quote.return_value = {
            'NFO:NHPC26AUGFUT': depth_quote([], [], ltp=76.9),
            'NFO:RELIANCE26AUGFUT': depth_quote(NHPC_BUY, NHPC_SELL),
        }
        stats = self.detector.run(['NHPC', 'RELIANCE'])
        self.assertEqual(stats['bid_dominant'], 1)
        self.assertEqual(stats['top5'][0]['symbol'], 'RELIANCE')


class IndexExclusionTest(unittest.TestCase):
    """Index symbols reachable through the same 'stocks' list are never scanned."""

    def test_niftynxt50_rejected(self):
        self.assertIn('NIFTYNXT50', _INDEX_SYMBOLS)

    def test_ordinary_equity_symbol_accepted(self):
        self.assertNotIn('NHPC', _INDEX_SYMBOLS)
        self.assertNotIn('RELIANCE', _INDEX_SYMBOLS)

    def test_index_symbol_excluded_from_instrument_list(self):
        mapper = make_mapper({'NHPC': 'NHPC26AUGFUT', 'NIFTYNXT50': 'NIFTYNXT5026AUGFUT'})
        detector = FuturesBidAskDetector(MagicMock(), mapper, MagicMock())
        detector._build_instrument_list(['NHPC', 'NIFTYNXT50'])
        self.assertEqual(detector._instruments, ['NFO:NHPC26AUGFUT'])
        self.assertNotIn('NFO:NIFTYNXT5026AUGFUT', detector._instruments)
        mapper.get_futures_symbol.assert_any_call('NHPC')
        self.assertNotIn('NIFTYNXT50', [c.args[0] for c in mapper.get_futures_symbol.call_args_list])


class InstrumentListRebuildTest(unittest.TestCase):
    """_instruments rebuilds when the input universe changes, not on every call."""

    def setUp(self):
        self.mapper = make_mapper({'NHPC': 'NHPC26AUGFUT', 'RELIANCE': 'RELIANCE26AUGFUT'})
        self.detector = FuturesBidAskDetector(MagicMock(), self.mapper, MagicMock())

    def test_rebuilds_on_universe_change(self):
        self.detector._build_instrument_list(['NHPC'])
        self.assertEqual(self.detector._instruments, ['NFO:NHPC26AUGFUT'])

        self.detector._build_instrument_list(['NHPC', 'RELIANCE'])
        self.assertEqual(
            self.detector._instruments, ['NFO:NHPC26AUGFUT', 'NFO:RELIANCE26AUGFUT']
        )

    def test_run_triggers_rebuild_only_when_stocks_list_changes(self):
        self.detector.kite.quote.return_value = {}
        self.detector.run(['NHPC'])
        first_build = self.detector._instruments
        self.assertEqual(first_build, ['NFO:NHPC26AUGFUT'])

        # unchanged universe -- no rebuild, same list object contents
        self.detector.run(['NHPC'])
        self.assertEqual(self.detector._instruments, ['NFO:NHPC26AUGFUT'])
        self.assertEqual(self.mapper.get_futures_symbol.call_count, 1)

        # changed universe -- rebuild happens, mapper consulted again
        self.detector.run(['NHPC', 'RELIANCE'])
        self.assertEqual(
            self.detector._instruments, ['NFO:NHPC26AUGFUT', 'NFO:RELIANCE26AUGFUT']
        )
        self.assertEqual(self.mapper.get_futures_symbol.call_count, 3)


if __name__ == '__main__':
    unittest.main()
