#!/usr/bin/env python3
"""
Regression test: secrets come from the Keychain, and no writer can ever leave
the shared secrets file empty.

On 2026-08-09 08:55:02 two token-refresh processes raced on `.env`.
`TokenManager.update_env_file` truncated the file (`open(path,'w')`) before
writing it back; the two writers landed 514 microseconds apart, one read inside
the other's truncate window, and the file came back as a single
`KITE_ACCESS_TOKEN=` line - 22 settings gone, including the Telegram tokens that
would have raised the alarm. Twelve services were down for 90 minutes of live
trading.

The contract pinned here:

  * a secret in the Keychain is served from the Keychain;
  * a secret missing from the Keychain falls back to .env AND warns, so the
    phase-1 fallback is never silent;
  * a secret in neither raises CredentialError naming the KEY, never a value -
    and no accessor ever puts a value in a log or an exception;
  * update_env_atomic() never exposes a partial or empty file to a concurrent
    reader, while the truncate-then-write algorithm it replaced does. Both are
    run through the SAME harness so the atomic result is a real difference and
    not an artefact of a weak test;
  * concurrent writers each land their own key without losing the other's.

Everything runs against a throwaway Keychain service and temp files. The
captain's real credentials and deployed .env are never touched: the Keychain
service name is randomised per run and deleted in tearDown.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import credentials


# 22 settings, matching the file that was destroyed - one of them the token.
_ENV_KEYS = [f'SETTING_{i:02d}' for i in range(21)] + ['KITE_ACCESS_TOKEN']


def _write_env(path):
    with open(path, 'w') as f:
        for key in _ENV_KEYS:
            f.write(f'{key}=original\n')


def _key_count(path):
    """Number of KEY=VALUE lines currently in the file."""
    try:
        with open(path) as f:
            return sum(1 for line in f if '=' in line)
    except FileNotFoundError:
        return 0


class KeychainAccessorTest(unittest.TestCase):
    """get_secret / set_secret against a throwaway Keychain service."""

    def setUp(self):
        # Randomised so a crashed earlier run can never collide, and so nothing
        # here can address the real "ShortIndicator" service.
        self.service = f'ShortIndicatorTest-{uuid.uuid4().hex[:12]}'
        os.environ['SI_KEYCHAIN_SERVICE'] = self.service
        self.key = 'TEST_KITE_ACCESS_TOKEN'
        credentials._warned_keys.clear()
        self.addCleanup(credentials._warned_keys.clear)

    def tearDown(self):
        credentials.delete_secret(self.key)
        os.environ.pop('SI_KEYCHAIN_SERVICE', None)
        # Nothing may survive under the throwaway service.
        self.assertFalse(
            subprocess.run(
                ['/usr/bin/security', 'find-generic-password', '-s', self.service],
                capture_output=True, text=True,
            ).returncode == 0,
            "throwaway Keychain service was not cleaned up",
        )

    def test_secret_in_keychain_is_served_from_keychain(self):
        credentials.set_secret(self.key, 'from-keychain')
        # .env holds a different value; the Keychain must win.
        with mock.patch.dict(os.environ, {self.key: 'from-dotenv'}):
            self.assertEqual(credentials.get_secret(self.key), 'from-keychain')

    def test_keychain_value_survives_special_characters(self):
        # Telegram tokens contain ':' and '-'; API secrets can contain anything.
        awkward = "a:b-c_d/e+f=g$h'i\"j k"
        credentials.set_secret(self.key, awkward)
        self.assertEqual(credentials.get_secret(self.key), awkward)

    def test_missing_from_keychain_falls_back_to_env_and_warns(self):
        with mock.patch.dict(os.environ, {self.key: 'from-dotenv'}):
            with self.assertLogs('credentials', level='WARNING') as logs:
                self.assertEqual(credentials.get_secret(self.key), 'from-dotenv')
        joined = '\n'.join(logs.output)
        self.assertIn(self.key, joined)
        self.assertNotIn('from-dotenv', joined, "fallback warning leaked the value")

    def test_missing_from_both_raises_naming_the_key_only(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ['SI_KEYCHAIN_SERVICE'] = self.service
            with self.assertRaises(credentials.CredentialError) as ctx:
                credentials.get_secret(self.key, required=True)
        message = str(ctx.exception)
        self.assertIn(self.key, message)
        self.assertIn(self.service, message)

    def test_missing_from_both_returns_none_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ['SI_KEYCHAIN_SERVICE'] = self.service
            self.assertIsNone(credentials.get_secret(self.key))

    def test_failed_keychain_write_error_omits_the_value(self):
        # An unwritable service name makes `security` fail; the value must not
        # appear in the exception text that callers log.
        secret = 'super-secret-value-9f3a'
        with mock.patch('subprocess.run') as run:
            run.return_value = mock.Mock(returncode=1, stderr='SecKeychainItemCreate failed')
            with self.assertRaises(credentials.CredentialError) as ctx:
                credentials.set_secret(self.key, secret)
        self.assertNotIn(secret, str(ctx.exception))
        self.assertIn(self.key, str(ctx.exception))

    def test_keychain_timeout_degrades_to_env_instead_of_hanging(self):
        # A locked keychain makes `security` wait on a GUI prompt no launchd job
        # can answer. Every monitor imports config at startup, so a hang here
        # would be a silent outage - it must degrade to the fallback.
        with mock.patch('subprocess.run',
                        side_effect=subprocess.TimeoutExpired('security', 10)):
            with mock.patch.dict(os.environ, {self.key: 'from-dotenv'}):
                with self.assertLogs('credentials', level='ERROR'):
                    self.assertEqual(credentials.get_secret(self.key), 'from-dotenv')

    def test_empty_value_is_refused(self):
        # An empty secret is what a corrupted .env yields; storing it would make
        # the Keychain authoritative for nothing.
        with self.assertRaises(credentials.CredentialError):
            credentials.set_secret(self.key, '')

    def test_has_secret_reports_presence(self):
        self.assertFalse(credentials.has_secret(self.key))
        credentials.set_secret(self.key, 'present')
        self.assertTrue(credentials.has_secret(self.key))


# A writer run as a separate process, so the race is a real one between
# processes rather than an interleaving invented inside one interpreter.
#
# ALGORITHM is either the pre-incident truncate-then-write or the atomic
# replacement. Both take the same PAUSE between "the old content is no longer
# the only copy" and "the new content is in place", so the two are compared
# under identical timing - the only difference is whether the target path is
# ever observable in a partial state.
_WRITER = textwrap.dedent("""
    import os, sys, time, tempfile
    algorithm, path, token, pause = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])

    with open(path) as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if line.startswith('KITE_ACCESS_TOKEN='):
            lines[i] = 'KITE_ACCESS_TOKEN=%s\\n' % token
            break

    if algorithm == 'legacy':
        with open(path, 'w') as f:      # truncates to zero HERE
            time.sleep(pause)
            f.writelines(lines)
    else:
        sys.path.insert(0, os.environ['SI_REPO_ROOT'])
        import credentials
        real_replace = os.replace
        def delayed_replace(src, dst):
            time.sleep(pause)
            real_replace(src, dst)
        os.replace = delayed_replace
        credentials.update_env_atomic({'KITE_ACCESS_TOKEN': token}, env_path=path)
""")

# Samples the file continuously and reports the fewest keys it ever saw.
_READER = textwrap.dedent("""
    import sys, time
    path, deadline = sys.argv[1], time.time() + float(sys.argv[2])
    fewest = 10**9
    while time.time() < deadline:
        try:
            with open(path) as f:
                fewest = min(fewest, sum(1 for line in f if '=' in line))
        except FileNotFoundError:
            fewest = 0
    print(fewest)
""")


class EnvWriteAtomicityTest(unittest.TestCase):
    """The regression test for the 2026-08-09 loss itself."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env_path = os.path.join(self.tmpdir.name, '.env')
        _write_env(self.env_path)
        self.repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _fewest_keys_seen_during(self, algorithm, pause=0.30):
        """Run one writer while a reader samples, return the reader's minimum."""
        env = dict(os.environ, SI_REPO_ROOT=self.repo_root)
        reader = subprocess.Popen(
            [sys.executable, '-c', _READER, self.env_path, str(pause * 3)],
            stdout=subprocess.PIPE, text=True, env=env,
        )
        subprocess.run(
            [sys.executable, '-c', _WRITER, algorithm, self.env_path, 'newtoken', str(pause)],
            check=True, env=env,
        )
        out, _ = reader.communicate(timeout=30)
        return int(out.strip())

    def test_harness_detects_the_pre_incident_algorithm(self):
        """
        Not a tautology check: proves the reader below can actually catch a
        truncate window. The old algorithm exposes an empty file, so the reader
        must observe zero keys.
        """
        self.assertEqual(self._fewest_keys_seen_during('legacy'), 0)

    def test_atomic_write_never_exposes_a_partial_file(self):
        """Same harness, same pause - the reader must never see fewer than 22."""
        self.assertEqual(self._fewest_keys_seen_during('atomic'), len(_ENV_KEYS))
        self.assertEqual(_key_count(self.env_path), len(_ENV_KEYS))

    def test_concurrent_writers_do_not_destroy_the_file(self):
        """
        The incident shape with no artificial pause: several real writers hitting
        the same file at once. Every one of the 22 settings must survive.
        """
        env = dict(os.environ, SI_REPO_ROOT=self.repo_root)
        writers = [
            subprocess.Popen(
                [sys.executable, '-c', _WRITER, 'atomic', self.env_path, f'token{i}', '0'],
                env=env,
            )
            for i in range(8)
        ]
        for w in writers:
            self.assertEqual(w.wait(timeout=30), 0)

        with open(self.env_path) as f:
            body = f.read()
        for key in _ENV_KEYS:
            self.assertIn(f'{key}=', body)
        self.assertEqual(_key_count(self.env_path), len(_ENV_KEYS))

    def test_writes_other_keys_leaves_the_rest_untouched(self):
        credentials.update_env_atomic({'KITE_ACCESS_TOKEN': 'abc'}, env_path=self.env_path)
        with open(self.env_path) as f:
            lines = [line.strip() for line in f]
        self.assertIn('KITE_ACCESS_TOKEN=abc', lines)
        self.assertEqual(sum(1 for line in lines if line.endswith('=original')), 21)

    def test_missing_file_is_not_created(self):
        """
        A one-line .env conjured from nothing IS the incident's artefact.
        update_env_atomic refuses rather than inventing a file.
        """
        absent = os.path.join(self.tmpdir.name, 'nope.env')
        self.assertFalse(credentials.update_env_atomic({'A': 'b'}, env_path=absent))
        self.assertFalse(os.path.exists(absent))

    def test_no_temp_files_are_left_behind(self):
        credentials.update_env_atomic({'KITE_ACCESS_TOKEN': 'abc'}, env_path=self.env_path)
        leftovers = [n for n in os.listdir(self.tmpdir.name) if n != '.env']
        self.assertEqual(leftovers, [])

    def test_file_mode_is_preserved(self):
        os.chmod(self.env_path, 0o600)
        credentials.update_env_atomic({'KITE_ACCESS_TOKEN': 'abc'}, env_path=self.env_path)
        self.assertEqual(os.stat(self.env_path).st_mode & 0o777, 0o600)


class TokenManagerWritePathTest(unittest.TestCase):
    """update_env_file stores the token in the Keychain, atomically."""

    def setUp(self):
        self.service = f'ShortIndicatorTest-{uuid.uuid4().hex[:12]}'
        os.environ['SI_KEYCHAIN_SERVICE'] = self.service
        self.addCleanup(lambda: os.environ.pop('SI_KEYCHAIN_SERVICE', None))
        self.addCleanup(credentials.delete_secret, 'KITE_ACCESS_TOKEN')

        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env_path = os.path.join(self.tmpdir.name, '.env')
        _write_env(self.env_path)

    def _update(self, token):
        """Call TokenManager.update_env_file without constructing a KiteConnect."""
        import token_manager
        manager = token_manager.TokenManager.__new__(token_manager.TokenManager)
        # update_env_file uses a relative '.env', the same way NewsBase invokes
        # it after chdir'ing to SI_PATH.
        cwd = os.getcwd()
        os.chdir(self.tmpdir.name)
        try:
            return token_manager.TokenManager.update_env_file(manager, token)
        finally:
            os.chdir(cwd)

    def test_token_lands_in_the_keychain_and_in_env(self):
        self.assertTrue(self._update('fresh-token'))
        self.assertEqual(credentials.get_secret('KITE_ACCESS_TOKEN'), 'fresh-token')
        with open(self.env_path) as f:
            self.assertIn('KITE_ACCESS_TOKEN=fresh-token', f.read())
        # The other 21 settings are still there.
        self.assertEqual(_key_count(self.env_path), len(_ENV_KEYS))

    def test_succeeds_when_env_is_absent(self):
        """Post-phase-2 shape: no .env, Keychain write alone is enough."""
        os.unlink(self.env_path)
        self.assertTrue(self._update('keychain-only'))
        self.assertEqual(credentials.get_secret('KITE_ACCESS_TOKEN', env_fallback=False),
                         'keychain-only')

    def test_reports_failure_when_neither_store_accepts_the_token(self):
        os.unlink(self.env_path)
        with mock.patch.object(credentials, 'set_secret',
                               side_effect=credentials.CredentialError('nope')):
            self.assertFalse(self._update('doomed'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
