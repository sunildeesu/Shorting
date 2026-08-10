#!/usr/bin/env python3
"""
Regression test: every alert leaving this repo names the service that produced it.

On 2026-08-10 twelve services failed at once and the failure was only noticed as an
absence of messages: the alerts themselves were indistinguishable, so a silent monitor
looked exactly like a quiet one. The contract pinned here:

  * every message sent through BaseNotifier - main channel, debug channel and Discord -
    carries a "[ShortIndicator - <service>]" footer;
  * two different services produce two different footers;
  * the service name is HTML-escaped, so a name containing < > & cannot break a
    parse_mode=HTML send;
  * stamping is idempotent, so send_debug()'s fallback to the main channel does not
    append the footer twice.

Runs offline: requests.post is mocked, no credentials are used and nothing is written.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alert_provenance
from telegram_notifiers.base_notifier import BaseNotifier


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass


def _make_notifier():
    """A BaseNotifier with fake credentials - never touches config or the network."""
    with mock.patch.multiple('config',
                             TELEGRAM_BOT_TOKEN='main-token',
                             TELEGRAM_CHANNEL_ID='-100main',
                             TELEGRAM_DEBUG_BOT_TOKEN='debug-token',
                             TELEGRAM_DEBUG_CHANNEL_ID='-100debug',
                             TELEGRAM_API_BASE='https://example.invalid',
                             DISCORD_WEBHOOK_URL='',
                             DISCORD_DEBUG_WEBHOOK_URL=''):
        return BaseNotifier()


class AlertProvenanceTest(unittest.TestCase):

    def setUp(self):
        self.addCleanup(alert_provenance.set_service, None)

    def _sent_texts(self, send):
        """Run `send` with requests.post mocked; return every 'text' payload sent."""
        with mock.patch('telegram_notifiers.base_notifier.requests.post',
                        return_value=_FakeResponse()) as post:
            send()
        return [call.kwargs['json'].get('text') for call in post.call_args_list
                if 'text' in call.kwargs.get('json', {})]

    def test_main_channel_alert_names_the_service(self):
        alert_provenance.set_service('stock_monitor')
        notifier = _make_notifier()
        texts = self._sent_texts(lambda: notifier._send_message('🔻 RELIANCE down 2.1%'))

        self.assertEqual(len(texts), 1)
        self.assertIn('🔻 RELIANCE down 2.1%', texts[0])
        self.assertIn('[ShortIndicator · stock_monitor]', texts[0])

    def test_debug_channel_alert_names_the_service(self):
        alert_provenance.set_service('order_flow_monitor')
        notifier = _make_notifier()
        texts = self._sent_texts(lambda: notifier.send_debug('Service started'))

        self.assertEqual(len(texts), 1)
        self.assertIn('[ShortIndicator · order_flow_monitor]', texts[0])

    def test_two_services_are_distinguishable(self):
        notifier = _make_notifier()

        alert_provenance.set_service('stock_monitor')
        first = self._sent_texts(lambda: notifier._send_message('same body'))[0]
        alert_provenance.set_service('onemin_monitor')
        second = self._sent_texts(lambda: notifier._send_message('same body'))[0]

        self.assertNotEqual(first, second)
        self.assertIn('stock_monitor]', first)
        self.assertIn('onemin_monitor]', second)

    def test_html_special_characters_in_service_name_are_escaped(self):
        alert_provenance.set_service('a<b>&"c"')
        notifier = _make_notifier()
        text = self._sent_texts(lambda: notifier._send_message('body'))[0]

        # The raw name must not reach Telegram as markup; only the footer's own
        # <i> tags may remain unescaped.
        self.assertNotIn('<b>', text)
        self.assertIn('a&lt;b&gt;&amp;&quot;c&quot;', text)
        self.assertTrue(text.endswith('</i>'))

    def test_stamping_is_idempotent(self):
        alert_provenance.set_service('stock_monitor')
        once = alert_provenance.stamp('body')
        self.assertEqual(alert_provenance.stamp(once), once)

    def test_service_defaults_to_the_entry_point_script(self):
        alert_provenance.set_service(None)
        with mock.patch.object(sys, 'argv', ['/opt/app/atr_breakout_monitor.py', '--live']):
            self.assertEqual(alert_provenance.get_service(), 'atr_breakout_monitor')

    def test_discord_message_carries_the_service(self):
        alert_provenance.set_service('gap_orb_monitor')
        notifier = _make_notifier()
        with mock.patch('telegram_notifiers.base_notifier.requests.post',
                        return_value=_FakeResponse()) as post:
            notifier._send_to_discord('https://example.invalid/webhook', '<b>Gap up</b>')
        description = post.call_args.kwargs['json']['embeds'][0]['description']
        self.assertIn('[ShortIndicator · gap_orb_monitor]', description)


if __name__ == '__main__':
    unittest.main()
