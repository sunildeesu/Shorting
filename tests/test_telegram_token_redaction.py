#!/usr/bin/env python3
"""
Regression test: a failed Telegram send must not write the bot token to a log.

The Bot API URL carries the token in its path, and requests puts that URL into
the text of every connection error ("Max retries exceeded with url:
/bot<id>:<secret>/sendMessage") and HTTPError; urllib3 logs it again at DEBUG.
`logger.error(f"...: {e}")` therefore leaked both bot tokens into ten deployed
log files (2026-10). The contract pinned here:

  * a real connection failure through BaseNotifier (main and debug channel)
    logs the failure but no token, at any level, including urllib3's lines;
  * an HTTPError's "for url: ..." text is masked the same way;
  * scripts/redact_telegram_tokens_in_logs.py masks every token in a file,
    reports the count, changes nothing under --dry-run, and never prints a token.

Runs offline: the "API" is a closed localhost port, credentials are fake.
"""

import contextlib
import io
import logging
import os
import socket
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import telegram_redaction
from telegram_notifiers.base_notifier import BaseNotifier

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import redact_telegram_tokens_in_logs as scrub

MAIN_TOKEN = '1234567890:AAFakeMainTokenSecret_abc-DEF123456'
DEBUG_TOKEN = '9876543210:AAFakeDebugTokenSecret_xyz-UVW654321'
SECRETS = ('AAFakeMainTokenSecret', 'AAFakeDebugTokenSecret')


def _bytes(path) -> bytes:
    with open(path, 'rb') as f:
        return f.read()


def _closed_port() -> int:
    """A localhost port nothing listens on, so connect() is refused immediately."""
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _make_notifier(api_base: str) -> BaseNotifier:
    with mock.patch.multiple('config',
                             TELEGRAM_BOT_TOKEN=MAIN_TOKEN,
                             TELEGRAM_CHANNEL_ID='-100main',
                             TELEGRAM_DEBUG_BOT_TOKEN=DEBUG_TOKEN,
                             TELEGRAM_DEBUG_CHANNEL_ID='-100debug',
                             TELEGRAM_API_BASE=api_base,
                             DISCORD_WEBHOOK_URL='',
                             DISCORD_DEBUG_WEBHOOK_URL=''):
        return BaseNotifier()


class _Capture(logging.Handler):
    """Collects fully formatted output, as a FileHandler would write it."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.setFormatter(logging.Formatter('%(name)s - %(levelname)s - %(message)s'))
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


class NotifierLogsNoTokenTest(unittest.TestCase):

    def setUp(self):
        self.capture = _Capture()
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(self.capture)
        root.setLevel(logging.DEBUG)  # the deployed monitors log urllib3 at DEBUG
        self.addCleanup(root.removeHandler, self.capture)
        self.addCleanup(root.setLevel, old_level)

    def _assert_no_token(self):
        text = '\n'.join(self.capture.lines)
        for secret in SECRETS:
            self.assertNotIn(secret, text)

    def test_connection_error_logs_failure_without_token(self):
        notifier = _make_notifier(f'http://127.0.0.1:{_closed_port()}')
        self.assertFalse(notifier._send_to('-100main', 'hello'))
        self.assertFalse(notifier.send_debug('hello'))

        errors = [l for l in self.capture.lines if ' - ERROR - ' in l]
        self.assertEqual(len(errors), 2, self.capture.lines)
        # The failure is still diagnosable: the redacted URL is in the line.
        for line in errors:
            self.assertIn('bot<REDACTED>/sendMessage', line)
        self._assert_no_token()

    def test_unredacted_message_would_have_leaked(self):
        # Proves the harness: the pre-fix logging of `{e}` carries the token.
        notifier = _make_notifier(f'http://127.0.0.1:{_closed_port()}')
        try:
            requests.post(f'{notifier.base_url}/sendMessage', json={}, timeout=5)
        except requests.exceptions.RequestException as e:
            self.assertIn(SECRETS[0], str(e))
            self.assertNotIn(SECRETS[0], telegram_redaction.redact(e))
        else:
            self.fail('expected a connection error')

    def test_http_error_url_is_masked(self):
        notifier = _make_notifier('https://api.telegram.org')
        err = requests.exceptions.HTTPError(
            f'429 Client Error: Too Many Requests for url: {notifier.debug_base_url}/sendMessage')
        with mock.patch('telegram_notifiers.base_notifier.requests.post', side_effect=err):
            notifier.send_debug('hello')
        self.assertTrue(any('Too Many Requests' in l for l in self.capture.lines))
        self._assert_no_token()

    def test_urllib3_debug_line_is_masked(self):
        logging.getLogger('urllib3.connectionpool').debug(
            '%s://%s:%s "%s %s %s" %s %s', 'https', 'api.telegram.org', 443,
            'POST', f'/bot{MAIN_TOKEN}/sendMessage', 'HTTP/1.1', 200, 0)
        self.assertEqual(len(self.capture.lines), 1)
        self.assertIn('/bot<REDACTED>/sendMessage', self.capture.lines[0])
        self._assert_no_token()


class ScrubScriptTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def _write(self, name, text):
        path = os.path.join(self.dir.name, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def _run(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = scrub.main(list(args))
        return rc, out.getvalue()

    def _files(self):
        leaky = self._write('leaky.log', (
            "2026-10-01 - ERROR - Failed: Max retries exceeded with url: "
            f"/bot{MAIN_TOKEN}/sendMessage (Caused by ...)\n"
            "2026-10-01 - INFO - ₹ unrelated line, café\n"
            f'urllib3 - DEBUG - "POST /r/x/bot{DEBUG_TOKEN}/sendMessage HTTP/1.1" 200\n'
            f"two on one line bot{MAIN_TOKEN} and bot{DEBUG_TOKEN}\n"))
        clean = self._write('clean.log', "nothing secret here\nrobot 12:30 bot\n")
        return leaky, clean

    def test_dry_run_counts_and_changes_nothing(self):
        leaky, clean = self._files()
        before = _bytes(leaky)
        rc, out = self._run('--dry-run', leaky, clean)
        self.assertEqual(rc, 0)
        self.assertIn(f'{leaky}: would redact 4', out)
        self.assertIn(f'{clean}: would redact 0', out)
        self.assertIn('TOTAL: would redact 4', out)
        self.assertEqual(_bytes(leaky), before)
        for secret in SECRETS:
            self.assertNotIn(secret, out)

    def test_rewrite_masks_every_token_and_keeps_the_rest(self):
        leaky, clean = self._files()
        os.chmod(leaky, 0o640)
        clean_before = _bytes(clean)
        rc, out = self._run(leaky, clean)
        self.assertEqual(rc, 0)
        self.assertIn(f'{leaky}: redacted 4', out)
        for secret in SECRETS:
            self.assertNotIn(secret, out)

        text = _bytes(leaky).decode('utf-8')
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        self.assertEqual(text.count('bot<REDACTED>'), 4)
        self.assertIn('₹ unrelated line, café', text)
        self.assertIn('/bot<REDACTED>/sendMessage (Caused by ...)', text)
        self.assertEqual(os.stat(leaky).st_mode & 0o777, 0o640)
        self.assertEqual(_bytes(clean), clean_before)
        self.assertEqual(sorted(os.listdir(self.dir.name)), ['clean.log', 'leaky.log'])

        # Idempotent: a second run finds nothing.
        rc, out = self._run('--dry-run', leaky)
        self.assertIn('TOTAL: would redact 0', out)

    def test_non_utf8_bytes_survive(self):
        path = os.path.join(self.dir.name, 'bin.log')
        with open(path, 'wb') as f:
            f.write(b'\xff\xfe raw ' + f'bot{MAIN_TOKEN}'.encode() + b' \x80end\n')
        self._run(path)
        self.assertEqual(_bytes(path), b'\xff\xfe raw bot<REDACTED> \x80end\n')

    def test_missing_file_reports_error_and_continues(self):
        leaky, _ = self._files()
        rc, out = self._run(os.path.join(self.dir.name, 'nope.log'), leaky)
        self.assertEqual(rc, 1)
        self.assertIn(f'{leaky}: redacted 4', out)


if __name__ == '__main__':
    unittest.main()
