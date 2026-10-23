#!/usr/bin/env python3
"""
Regression test: collector_watchdog.sh never kills a collector before the open, and
only ever restarts the collector through its launchd job.

On Fri 2026-10-23 the com.nse.central.collector job started the collector at 09:05
and it was waiting for the 09:15 open. At 09:07 the watchdog read yesterday's last
quote from stock_quotes (63513 s old), called it stale, pkill'ed the healthy collector
and ran start_collector.sh itself - a copy outside the job, so the dashboard showed
the job DEAD while it collected. The contract pinned here:

  * before 09:15 + 300 s a running collector is left alone, however old the last quote;
  * in session, stale data or an absent collector -> `launchctl kickstart -k` of the
    job, in the system domain (via `sudo -n`) when the LaunchDaemon plist exists,
    otherwise gui/<uid>;
  * a refused kickstart logs, sends ONE Telegram alert per day, and starts nothing
    (no pkill, no start_collector.sh).

Runs offline: SI_DIR points at a temp tree, the clock is pinned with
WATCHDOG_NOW_EPOCH, and pgrep/sqlite3/sudo/launchctl/pkill are stubs.
"""

import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'collector_watchdog.sh')

YESTERDAY_LAST_QUOTE = '2026-10-22 15:28:00'

# Every stub appends "<name> <args>" to $CALLS so a test can see what was run.
_PGREP = r'''#!/bin/bash
echo "pgrep $*" >> "$CALLS"
for p in $RUNNING; do
    [ "${@: -1}" = "$p" ] && exit 0
done
exit 1
'''
_SQLITE3 = '#!/bin/bash\necho "$LAST_TS"\n'
_LAUNCHCTL = '#!/bin/bash\necho "launchctl $*" >> "$CALLS"\nexit "${KICKSTART_EXIT:-0}"\n'
_SUDO = '#!/bin/bash\necho "sudo $*" >> "$CALLS"\n[ "$1" = "-n" ] && shift\nexec "$@"\n'
_PKILL = '#!/bin/bash\necho "pkill $*" >> "$CALLS"\n'
# Stands in for ShortIndicator's venv/bin/python3 running the TelegramNotifier heredoc.
_SI_PYTHON = r'''#!/bin/bash
script=$(cat)
case "$script" in
    *TelegramNotifier*) echo "ALERT: $ALERT_TEXT" >> "$CALLS" ;;
    *) exit 99 ;;
esac
'''


def _write_exec(path, body):
    with open(path, 'w') as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def _ist_epoch(ts):
    out = subprocess.run(['/bin/date', '-j', '-f', '%Y-%m-%d %H:%M:%S', ts, '+%s'],
                         env=dict(os.environ, TZ='Asia/Kolkata'),
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


class CollectorWatchdogTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='collector_watchdog_test_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.si = os.path.join(self.tmp, 'si')
        for d in ('venv/bin', 'data', 'logs'):
            os.makedirs(os.path.join(self.si, d))
        _write_exec(os.path.join(self.si, 'venv/bin/python3'), _SI_PYTHON)
        # Must never be run by the watchdog
        _write_exec(os.path.join(self.si, 'start_collector.sh'),
                    '#!/bin/bash\necho "start_collector.sh" >> "$CALLS"\n')
        self.bin = os.path.join(self.tmp, 'bin')
        os.makedirs(self.bin)
        for name, body in (('pgrep', _PGREP), ('sqlite3', _SQLITE3), ('sudo', _SUDO),
                           ('launchctl', _LAUNCHCTL), ('pkill', _PKILL)):
            _write_exec(os.path.join(self.bin, name), body)
        self.calls = os.path.join(self.tmp, 'calls.log')
        self.daemon_plist = os.path.join(self.tmp, 'LaunchDaemons',
                                         'com.nse.central.collector.plist')

    def _run(self, now, running=('central_data_collector_continuous.py',),
             last_ts=YESTERDAY_LAST_QUOTE, kickstart_exit=0, daemon=False):
        if daemon:
            os.makedirs(os.path.dirname(self.daemon_plist), exist_ok=True)
            open(self.daemon_plist, 'w').close()
        env = dict(os.environ, SI_DIR=self.si, CALLS=self.calls,
                   WATCHDOG_NOW_EPOCH=_ist_epoch(now), RUNNING=' '.join(running),
                   LAST_TS=last_ts, KICKSTART_EXIT=str(kickstart_exit),
                   DAEMON_PLIST=self.daemon_plist,
                   LAUNCHCTL=os.path.join(self.bin, 'launchctl'),
                   PATH=self.bin + os.pathsep + os.environ.get('PATH', ''))
        return subprocess.run(['/bin/bash', SCRIPT], env=env,
                              capture_output=True, text=True)

    def _calls(self, prefix):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls) as f:
            return [l for l in f.read().splitlines() if l.startswith(prefix)]

    def _assert_no_untracked_start(self):
        self.assertEqual(self._calls('pkill'), [])
        self.assertEqual(self._calls('start_collector.sh'), [])

    def test_preopen_stale_data_leaves_running_collector_alone(self):
        # The 2026-10-23 incident: 09:07, collector waiting for the open
        for now in ('2026-10-23 09:07:00', '2026-10-23 09:15:00', '2026-10-23 09:19:59'):
            result = self._run(now)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self._calls('launchctl'), [], now)
            self.assertNotIn('stale', result.stdout, now)
            self._assert_no_untracked_start()

    def test_fresh_in_session_data_is_left_alone(self):
        result = self._run('2026-10-23 11:00:00', last_ts='2026-10-23 10:58:00')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self._calls('launchctl'), [])

    def test_in_session_stale_data_kickstarts_gui_job(self):
        result = self._run('2026-10-23 09:20:00')  # no quote since the 09:15 open
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('stale for 300s', result.stdout)
        self.assertEqual(self._calls('launchctl'),
                         [f'launchctl kickstart -k gui/{os.getuid()}/com.nse.central.collector'])
        self.assertEqual(self._calls('sudo'), [])
        self._assert_no_untracked_start()

    def test_in_session_stale_data_kickstarts_system_job_via_sudo(self):
        result = self._run('2026-10-23 11:00:00', last_ts='2026-10-23 10:50:00',
                           daemon=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        launchctl = os.path.join(self.bin, 'launchctl')
        self.assertEqual(self._calls('sudo'),
                         [f'sudo -n {launchctl} kickstart -k system/com.nse.central.collector'])
        self.assertEqual(self._calls('launchctl'),
                         ['launchctl kickstart -k system/com.nse.central.collector'])
        self._assert_no_untracked_start()

    def test_absent_collector_in_session_kickstarts_job(self):
        result = self._run('2026-10-23 10:00:00', running=())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('not running', result.stdout)
        self.assertEqual(self._calls('launchctl'),
                         [f'launchctl kickstart -k gui/{os.getuid()}/com.nse.central.collector'])
        self._assert_no_untracked_start()

    def test_job_still_in_start_collector_is_not_killed(self):
        # The job's wrapper is mid token check/refresh; kickstart -k would kill it
        result = self._run('2026-10-23 09:06:00', running=('start_collector.sh',))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self._calls('launchctl'), [])

    def test_refused_kickstart_alerts_once_a_day_and_starts_nothing(self):
        for now in ('2026-10-23 10:00:00', '2026-10-23 10:10:00'):
            result = self._run(now, running=(), kickstart_exit=1, daemon=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('FAILED', result.stdout)
            self._assert_no_untracked_start()
        self.assertEqual(len(self._calls('sudo')), 2)
        alerts = self._calls('ALERT:')
        self.assertEqual(len(alerts), 1)
        self.assertIn('manual restart', alerts[0])

        # Next trading day: alerts again
        self._run('2026-10-26 10:00:00', running=(), kickstart_exit=1, daemon=True)
        self.assertEqual(len(self._calls('ALERT:')), 2)

    def test_outside_window_does_nothing(self):
        for now in ('2026-10-23 08:59:00', '2026-10-23 15:31:00', '2026-10-24 10:00:00'):
            self._run(now, running=())
        self.assertEqual(self._calls('launchctl'), [])
        self.assertEqual(self._calls('pgrep'), [])


if __name__ == '__main__':
    unittest.main()
