#!/usr/bin/env python3
"""
Exit-code contract for check_token.py (launchd job com.nse.token.reminder, 08:00).

The job runs before the 08:55 token refresh, so on a normal morning the token
has expired and the job sends its Telegram reminder. That used to exit 1, and
the Market Ops Dashboard showed the job as CRASHED every day (2026-10-23).

Pinned here: an expired token whose alert was delivered exits 0, a valid token
exits 0, and only real failures - Telegram not delivering, or the check itself
raising - exit non-zero. Runs offline: TokenManager and TelegramNotifier are mocked.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import check_token
import token_manager


class CheckTokenExitCodeTest(unittest.TestCase):

    def _run(self, is_valid, warning, sent=True, check_error=None):
        manager = mock.Mock()
        if check_error:
            manager.is_token_valid.side_effect = check_error
        manager.is_token_valid.return_value = (is_valid, 'msg', 0)
        manager.get_expiry_warning_message.return_value = warning
        notifier = mock.Mock()
        notifier.send_message.return_value = sent
        with mock.patch.object(token_manager, 'TokenManager', return_value=manager), \
             mock.patch('market_utils.is_trading_day', return_value=True), \
             mock.patch('telegram_notifier.TelegramNotifier', return_value=notifier):
            return check_token.main(), notifier

    def test_expired_token_with_alert_sent_exits_0(self):
        code, notifier = self._run(False, '🚨 Kite token expired')
        self.assertEqual(code, 0)
        notifier.send_message.assert_called_once_with('🚨 Kite token expired')

    def test_valid_token_exits_0(self):
        code, notifier = self._run(True, None)
        self.assertEqual(code, 0)
        notifier.send_message.assert_not_called()

    def test_telegram_send_failing_exits_nonzero(self):
        code, _ = self._run(False, '🚨 Kite token expired', sent=False)
        self.assertNotEqual(code, 0)

    def test_check_erroring_exits_nonzero(self):
        code, _ = self._run(False, None, check_error=OSError('metadata unreadable'))
        self.assertNotEqual(code, 0)


if __name__ == '__main__':
    unittest.main()
