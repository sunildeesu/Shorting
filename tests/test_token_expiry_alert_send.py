#!/usr/bin/env python3
"""
Regression test: the token-expiry warning actually reaches Telegram.

On 2026-09-15 the Kite login automation failed all day and nobody was told. The
08:00 token reminder (token_manager.check_token_and_alert) and the 09:25
stock-monitor startup (main.check_kite_token) both build a `TelegramNotifier()` and
called `_send_message(warning)` on it - a method that lives on BaseNotifier, not on
the TelegramNotifier facade, so every send raised
`'TelegramNotifier' object has no attribute '_send_message'` inside a try/except
that logged and moved on. logs/token_reminder.log shows the same error back to
2026-06-11.

The contract pinned here: the facade exposes a public `send_message`, and the two
callers above deliver their warning through it to the main channel. Runs offline:
requests.post is mocked, no credentials are used.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_FAKE_CONFIG = dict(TELEGRAM_BOT_TOKEN='main-token',
                    TELEGRAM_CHANNEL_ID='-100main',
                    TELEGRAM_DEBUG_BOT_TOKEN='debug-token',
                    TELEGRAM_DEBUG_CHANNEL_ID='-100debug',
                    TELEGRAM_API_BASE='https://example.invalid',
                    DISCORD_WEBHOOK_URL='',
                    DISCORD_DEBUG_WEBHOOK_URL='')


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass


class TokenExpiryAlertSendTest(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.multiple('config', **_FAKE_CONFIG)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.post = mock.patch('telegram_notifiers.base_notifier.requests.post',
                               return_value=_FakeResponse()).start()
        self.addCleanup(mock.patch.stopall)

    def _sent_texts(self):
        return [call.kwargs['json']['text'] for call in self.post.call_args_list]

    def test_facade_send_message_reaches_main_channel(self):
        from telegram_notifier import TelegramNotifier
        self.assertTrue(TelegramNotifier().send_message('⚠️ token expires soon'))
        self.assertEqual(len(self.post.call_args_list), 1)
        payload = self.post.call_args.kwargs['json']
        self.assertEqual(payload['chat_id'], '-100main')
        self.assertIn('token expires soon', payload['text'])

    def test_token_reminder_delivers_warning(self):
        # The 08:00 launchd job: token_manager.check_token_and_alert()
        import token_manager
        fake_manager = mock.Mock()
        fake_manager.is_token_valid.return_value = (False, 'expired', 0)
        fake_manager.get_expiry_warning_message.return_value = '🚨 Kite token expired'
        with mock.patch.object(token_manager, 'TokenManager', return_value=fake_manager), \
             mock.patch('market_utils.is_trading_day', return_value=True):
            self.assertFalse(token_manager.check_token_and_alert())
        self.assertEqual(len(self._sent_texts()), 1)
        self.assertIn('Kite token expired', self._sent_texts()[0])

    def test_stock_monitor_startup_delivers_warning(self):
        # The 09:25 stock monitor: main.check_kite_token() on an invalid token
        import logging
        import main
        fake_manager = mock.Mock()
        fake_manager.is_token_valid.return_value = (False, 'expired', 0)
        fake_manager.get_expiry_warning_message.return_value = '🚨 Kite token expired'
        with mock.patch('token_manager.TokenManager', return_value=fake_manager), \
             mock.patch.object(main.config, 'DATA_SOURCE', 'kite'):
            self.assertFalse(main.check_kite_token(logging.getLogger('test')))
        self.assertEqual(len(self._sent_texts()), 1)
        self.assertIn('Kite token expired', self._sent_texts()[0])


if __name__ == '__main__':
    unittest.main()
