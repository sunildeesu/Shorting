#!/usr/bin/env python3
"""
Regression test: start_collector.sh backs off after a failed token refresh.

On 2026-09-15 the Zerodha account's 2FA had changed and NewsBase's token refresh
was rejected ("Invalid App Code. 3 attempt(s) remain before the account is
locked"). The collector watchdog runs start_collector.sh every 600 s, and it
re-ran the login on every cycle from 09:01 to 15:21 - 22+ rejected logins against
a deterministic failure. The contract pinned here:

  * a failed refresh writes data/.token_refresh_failed_<YYYYMMDD> and sends ONE
    Telegram alert;
  * while the marker exists, later cycles skip the refresh (one log line) and do
    not alert again;
  * a valid token (a manual generate_kite_token.py) starts the collector anyway
    and clears the marker.

Runs offline: the script is driven with SI_DIR/NB_DIR pointing at a temp tree whose
venv/bin/python3 are stubs, and pgrep is stubbed so a real collector on this
machine does not short-circuit the run.
"""

import datetime
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'start_collector.sh')

# Stands in for ShortIndicator's venv/bin/python3. The script feeds it a heredoc on
# stdin for the token check and for the alert, and a file path to exec the collector.
_SI_PYTHON = r'''#!/bin/bash
SI="$(cd "$(dirname "$0")/../.." && pwd)"
if [ "$1" = "-" ]; then
    script=$(cat)
    case "$script" in
        *kite.profile*) cat "$SI/token_status" ;;
        *TelegramNotifier*) echo "ALERT: $ALERT_TEXT" >> "$SI/alerts.log" ;;
        *) echo "unexpected stdin script" >&2; exit 99 ;;
    esac
else
    echo "exec $*" >> "$SI/collector.log"
fi
'''

# Stands in for NewsBase's venv/bin/python3 -m data_feeds.token_refresh.
_NB_PYTHON = r'''#!/bin/bash
NB="$(cd "$(dirname "$0")/../.." && pwd)"
echo "refresh $*" >> "$NB/refresh.log"
exit "$(cat "$NB/refresh_exit")"
'''


def _write_exec(path, body):
    with open(path, 'w') as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class StartCollectorBackoffTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='start_collector_test_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.si = os.path.join(self.tmp, 'si')
        self.nb = os.path.join(self.tmp, 'nb')
        for d in ('venv/bin', 'data', 'logs'):
            os.makedirs(os.path.join(self.si, d))
        os.makedirs(os.path.join(self.nb, 'venv/bin'))
        _write_exec(os.path.join(self.si, 'venv/bin/python3'), _SI_PYTHON)
        _write_exec(os.path.join(self.nb, 'venv/bin/python3'), _NB_PYTHON)
        # pgrep stub: no collector is running
        self.bin = os.path.join(self.tmp, 'bin')
        os.makedirs(self.bin)
        _write_exec(os.path.join(self.bin, 'pgrep'), '#!/bin/bash\nexit 1\n')
        self.marker = os.path.join(
            self.si, 'data',
            '.token_refresh_failed_' + datetime.date.today().strftime('%Y%m%d'))

    def _run(self, token_status, refresh_exit):
        with open(os.path.join(self.si, 'token_status'), 'w') as f:
            f.write(token_status + '\n')
        with open(os.path.join(self.nb, 'refresh_exit'), 'w') as f:
            f.write(str(refresh_exit) + '\n')
        env = dict(os.environ, SI_DIR=self.si, NB_DIR=self.nb,
                   PATH=self.bin + os.pathsep + os.environ.get('PATH', ''))
        return subprocess.run(['/bin/bash', SCRIPT], env=env,
                              capture_output=True, text=True)

    def _lines(self, name):
        """Entries in a stub log; alerts.log entries are multi-line, keyed by 'ALERT:'."""
        path = os.path.join(self.si if name != 'refresh.log' else self.nb, name)
        if not os.path.exists(path):
            return []
        with open(path) as f:
            lines = f.read().splitlines()
        if name == 'alerts.log':
            return [l for l in lines if l.startswith('ALERT:')]
        return lines

    def test_rejected_refresh_is_not_retried_until_the_token_is_fixed(self):
        # Cycle 1: token invalid, NewsBase refresh rejected -> marker + one alert
        result = self._run('invalid', 1)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(os.path.exists(self.marker))
        self.assertEqual(len(self._lines('refresh.log')), 1)
        alerts = self._lines('alerts.log')
        self.assertEqual(len(alerts), 1)
        self.assertIn('token refresh FAILED', alerts[0])
        self.assertEqual(self._lines('collector.log'), [])

        # Cycle 2 (600 s later): still invalid -> refresh skipped, no second alert
        result = self._run('invalid', 1)
        self.assertEqual(result.returncode, 1)
        self.assertIn('skipping refresh', result.stdout)
        self.assertEqual(len(self._lines('refresh.log')), 1)
        self.assertEqual(len(self._lines('alerts.log')), 1)
        self.assertEqual(self._lines('collector.log'), [])
        self.assertTrue(os.path.exists(self.marker))

        # Cycle 3: captain ran generate_kite_token.py -> collector starts, marker cleared
        result = self._run('valid', 1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self._lines('collector.log')), 1)
        self.assertIn('central_data_collector_continuous.py', self._lines('collector.log')[0])
        self.assertEqual(len(self._lines('refresh.log')), 1)
        self.assertEqual(len(self._lines('alerts.log')), 1)
        self.assertFalse(os.path.exists(self.marker))

    def test_successful_refresh_starts_collector_without_marker(self):
        # Existing behaviour: invalid token, refresh succeeds -> collector starts
        result = self._run('invalid', 0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self._lines('refresh.log')), 1)
        self.assertEqual(len(self._lines('collector.log')), 1)
        self.assertFalse(os.path.exists(self.marker))
        self.assertEqual(self._lines('alerts.log'), [])

    def test_valid_token_starts_collector_without_refresh(self):
        result = self._run('valid', 1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._lines('refresh.log'), [])
        self.assertEqual(len(self._lines('collector.log')), 1)


if __name__ == '__main__':
    unittest.main()
