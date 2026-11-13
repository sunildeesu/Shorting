#!/usr/bin/env python3
"""
Regression test: the 09:00 pre-market summary reaches Telegram with its patterns.

premarket_analyzer.run() STEP 9 calls
`telegram_notifier.send_premarket_pattern_alert(top_patterns=..., market_regime=...,
stocks_analyzed=..., total_patterns_found=...)` - the summary signature that
PatternAlertNotifier implements. The TelegramNotifier facade was rewritten in
c5c9bd2 (2026-01-15) with a per-symbol signature (symbol, pattern_name, ...) that
matches neither side, so every run raised
`TypeError: ... got an unexpected keyword argument 'top_patterns'` inside a
try/except that logged and moved on. It stayed hidden while run() died at STEP 1
(fixed in 2507c5e, 2026-10-22); from 2026-10-23 every run reached STEP 9 and lost
the message.

The contract pinned here: run() drives the real ranker and the real TelegramNotifier
facade, and the ranked patterns arrive in the main-channel message. Only the
broker, the pattern detectors, the Excel writer and requests.post are stubbed. Runs
offline: no credentials, no network, nothing written under logs/ or data/.
"""

import logging
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# premarket_analyzer opens logs/premarket_analyzer.log at import time.
with mock.patch('logging.FileHandler', lambda *a, **kw: logging.NullHandler()):
    import premarket_analyzer
from eod_stock_filter import EODStockFilter
from premarket_priority_ranker import PreMarketPriorityRanker

_FAKE_CONFIG = dict(TELEGRAM_BOT_TOKEN='main-token',
                    TELEGRAM_CHANNEL_ID='-100main',
                    TELEGRAM_DEBUG_BOT_TOKEN='debug-token',
                    TELEGRAM_DEBUG_CHANNEL_ID='-100debug',
                    TELEGRAM_API_BASE='https://example.invalid',
                    DISCORD_WEBHOOK_URL='',
                    DISCORD_DEBUG_WEBHOOK_URL='')

SYMBOL = 'NSE:RELIANCE'

DAILY_RESULTS = {
    SYMBOL: {
        'symbol': SYMBOL,
        'has_patterns': True,
        'market_regime': 'BULLISH',
        'patterns_found': ['DOUBLE_BOTTOM'],
        'pattern_details': {
            'double_bottom': {
                'confidence_score': 8.5,
                'buy_price': 1400.0,
                'target_price': 1480.0,
                'stop_loss': 1380.0,
                'volume_ratio': 2.4,
                'pattern_type': 'BULLISH',
            }
        },
    }
}


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass


class PreMarketTelegramSummaryTest(unittest.TestCase):

    def setUp(self):
        mock.patch.multiple('config', **_FAKE_CONFIG).start()
        self.post = mock.patch('telegram_notifiers.base_notifier.requests.post',
                               return_value=_FakeResponse()).start()
        mock.patch.object(premarket_analyzer.time, 'sleep').start()
        self.addCleanup(mock.patch.stopall)

    def _analyzer(self):
        """A PreMarketAnalyzer with stubbed broker/detectors, skipping the networked __init__."""
        from telegram_notifier import TelegramNotifier

        analyzer = object.__new__(premarket_analyzer.PreMarketAnalyzer)
        analyzer.kite = mock.Mock()
        analyzer.kite.quote.return_value = {
            SYMBOL: {'volume': 10_000_000, 'ohlc': {'open': 1350.0, 'close': 1400.0}},
        }
        analyzer.fo_stocks = ['RELIANCE']
        analyzer.regime_detector = mock.Mock(get_market_regime=mock.Mock(return_value='BULLISH'))
        analyzer.stock_filter = EODStockFilter(volume_threshold_lakhs=50.0, price_change_threshold=1.5)
        analyzer._fetch_historical_data = mock.Mock(return_value=[{'close': 1400.0}])
        analyzer._fetch_hourly_data = mock.Mock(return_value=[])
        analyzer.daily_detector = mock.Mock(batch_detect=mock.Mock(return_value=DAILY_RESULTS))
        analyzer.hourly_detector = mock.Mock(batch_detect=mock.Mock(return_value={}))
        analyzer.priority_ranker = PreMarketPriorityRanker(
            max_alerts=3, min_priority_score=7.0, min_confidence=7.5, min_risk_reward=1.5)
        analyzer.report_generator = mock.Mock(generate_report=mock.Mock(return_value='report.xlsx'))
        analyzer.telegram_notifier = TelegramNotifier()
        return analyzer

    def test_run_sends_the_ranked_summary(self):
        with self.assertNoLogs(premarket_analyzer.logger, level='ERROR'):
            result = self._analyzer().run()

        self.assertTrue(result['success'], result.get('error'))
        self.assertEqual(len(result['top_patterns']), 1)

        self.assertEqual(self.post.call_count, 1)
        payload = self.post.call_args.kwargs['json']
        self.assertEqual(payload['chat_id'], '-100main')
        text = payload['text']
        self.assertIn('PRE-MARKET PATTERN ALERT', text)
        self.assertIn('Market Regime:</b> BULLISH', text)
        self.assertIn(f'{SYMBOL} - ', text)
        self.assertIn('Entry:  ₹1400.00', text)
        self.assertIn('Target: ₹1480.00', text)
        self.assertIn('Stop:   ₹1380.00', text)

    def test_facade_forwards_the_summary_arguments(self):
        from telegram_notifier import TelegramNotifier
        notifier = TelegramNotifier()
        with mock.patch.object(notifier.pattern_alerts, 'send_premarket_pattern_alert',
                               return_value=True) as inner:
            self.assertTrue(notifier.send_premarket_pattern_alert(
                top_patterns=[{'symbol': 'X'}], market_regime='BEARISH',
                stocks_analyzed=12, total_patterns_found=4))
        inner.assert_called_once_with(top_patterns=[{'symbol': 'X'}], market_regime='BEARISH',
                                      stocks_analyzed=12, total_patterns_found=4)


if __name__ == '__main__':
    unittest.main()
