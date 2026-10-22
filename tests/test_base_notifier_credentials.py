#!/usr/bin/env python3
"""
Regression test: BaseNotifier's missing-credentials error names where it actually looked.

On 2026-08-10 the truncated .env (see credentials.py) made vwap_mover_monitor and
gap_orb_monitor die at 09:12 with "Telegram bot token and channel ID must be set in
.env file". Since the Keychain migration config reads both through
credentials.get_secret() - Keychain first, .env fallback - so that message sent anyone
debugging it to the wrong place. The contract pinned here:

  * a token that config got from get_secret() is enough; no .env value is needed;
  * when both sources are empty the error names the Keychain service and .env;
  * the error never carries a secret value.

Runs offline: config attributes are patched, the Keychain service is a throwaway name.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_notifiers.base_notifier import BaseNotifier


def _notifier(bot_token, channel_id):
    with mock.patch.multiple('config',
                             TELEGRAM_BOT_TOKEN=bot_token,
                             TELEGRAM_CHANNEL_ID=channel_id,
                             TELEGRAM_DEBUG_BOT_TOKEN=None,
                             TELEGRAM_DEBUG_CHANNEL_ID=None,
                             DISCORD_WEBHOOK_URL='',
                             DISCORD_DEBUG_WEBHOOK_URL=''):
        return BaseNotifier()


class BaseNotifierCredentialsTest(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {'SI_KEYCHAIN_SERVICE': 'si-test-throwaway'})
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID'):
            os.environ.pop(key, None)

    def test_keychain_sourced_credentials_need_no_env(self):
        notifier = _notifier('keychain-token', '-100keychain')
        self.assertEqual(notifier.bot_token, 'keychain-token')
        self.assertEqual(notifier.channel_id, '-100keychain')

    def test_missing_credentials_error_names_keychain_and_env(self):
        for token, channel in ((None, '-100only-channel'), ('only-token', None), (None, None)):
            with self.subTest(token=token, channel=channel):
                with self.assertRaises(ValueError) as ctx:
                    _notifier(token, channel)
                msg = str(ctx.exception)
                self.assertIn('Keychain', msg)
                self.assertIn('service=si-test-throwaway', msg)
                self.assertIn('.env', msg)
                self.assertNotIn('must be set in .env file', msg)
                for value in (token, channel):
                    if value:
                        self.assertNotIn(value, msg)


if __name__ == '__main__':
    unittest.main()
