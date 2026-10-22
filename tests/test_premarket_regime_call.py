#!/usr/bin/env python3
"""
Regression test: the pre-market analysis gets past its market-regime step.

premarket_analyzer.run() called `self.regime_detector.detect_regime()`, a method
MarketRegimeDetector has never had (its API since 809599c is `get_market_regime()`).
Every 09:00 run of com.stockmonitor.premarket died at STEP 1 with
`'MarketRegimeDetector' object has no attribute 'detect_regime'` - logged in
logs/premarket_analyzer.log on 2026-10-15 and 2026-10-22.

The contract pinned here: run() drives the *real* MarketRegimeDetector (only the
broker is stubbed, so a renamed method fails here instead of hiding behind a Mock),
and the regime it classifies is the one the run carries forward. Runs offline: no
broker, no credentials, no network, nothing written under logs/ or data/.
"""

import logging
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# premarket_analyzer opens logs/premarket_analyzer.log at import time.
with mock.patch('logging.FileHandler', lambda *a, **kw: logging.NullHandler()):
    import premarket_analyzer
from eod_stock_filter import EODStockFilter
from market_regime_detector import MarketRegimeDetector


def nifty_candles(last_close, count=60, base=24000.0):
    """`count` flat daily closes at `base`, the last one at `last_close`."""
    start = datetime.now() - timedelta(days=count)
    candles = [{'date': start + timedelta(days=i), 'close': base} for i in range(count - 1)]
    candles.append({'date': datetime.now(), 'close': last_close})
    return candles


def bare_analyzer(kite):
    """A PreMarketAnalyzer wired to a stub broker, skipping the networked __init__."""
    analyzer = object.__new__(premarket_analyzer.PreMarketAnalyzer)
    analyzer.kite = kite
    analyzer.regime_detector = MarketRegimeDetector(kite)
    analyzer.stock_filter = EODStockFilter(volume_threshold_lakhs=50.0, price_change_threshold=1.5)
    analyzer.fo_stocks = ['RELIANCE']
    analyzer.instrument_tokens = {'RELIANCE': 738561}
    return analyzer


class PreMarketRegimeCallTest(unittest.TestCase):

    def run_analysis(self, last_close):
        kite = mock.Mock()
        kite.historical_data.return_value = nifty_candles(last_close)
        # One quiet stock, so the filter passes nothing and run() returns right
        # after the regime step without fetching any history.
        kite.quote.return_value = {
            'NSE:RELIANCE': {'volume': 100, 'ohlc': {'open': 1000.0, 'close': 1001.0}},
        }
        with mock.patch.object(premarket_analyzer.time, 'sleep'):
            result = bare_analyzer(kite).run()
        return kite, result

    def test_run_crosses_the_regime_step(self):
        kite, result = self.run_analysis(last_close=25000.0)  # ~4% above the 50-SMA

        self.assertTrue(result['success'], result.get('error'))
        self.assertEqual(result['market_regime'], 'BULLISH')
        self.assertEqual(kite.historical_data.call_args.kwargs['instrument_token'],
                         MarketRegimeDetector.NIFTY_50_TOKEN)
        kite.quote.assert_called_once()  # reached STEP 2

    def test_bearish_regime_is_carried_forward(self):
        _, result = self.run_analysis(last_close=23000.0)  # ~4% below the 50-SMA

        self.assertTrue(result['success'], result.get('error'))
        self.assertEqual(result['market_regime'], 'BEARISH')


if __name__ == '__main__':
    unittest.main()
