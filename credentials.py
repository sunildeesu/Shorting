"""
Single place anything in this repo asks for a secret.

Secrets live in the macOS login Keychain as generic passwords:

    service = SI_KEYCHAIN_SERVICE ("ShortIndicator")
    account = the key name        ("KITE_API_KEY")

`/usr/bin/security` serves these non-interactively to a background launchd job -
no prompt, no unlocked-GUI requirement - which is what the 08:55 token refresh needs.

Why this module exists
----------------------
On Sunday 2026-08-09 08:55:02 two token-refresh processes raced on the shared
plaintext `.env`. `TokenManager.update_env_file` did a non-atomic read-modify-write
(`open(path,'w')` truncates to zero *before* writing); one process read inside the
other's truncate window and wrote back a single line, destroying 22 settings -
including both Telegram tokens, so the alerting that should have screamed was
itself dead. Twelve services were down for the first 90 minutes of Monday's session.

Two fixes, both here: secrets move off disk into the Keychain, and every remaining
`.env` write goes through `update_env_atomic()` (temp file + fsync + os.replace),
so a concurrent reader sees the whole old file or the whole new one, never nothing.

TEMPORARY .env FALLBACK
-----------------------
`get_secret()` reads the Keychain first and falls back to `.env` with a warning.
That fallback was phase-1 scaffolding, but boot-time LaunchDaemons cannot read the
login Keychain at all (`security` exits 36, "User interaction is not allowed"), and
they get their secrets from `.env` through it. Removing it (phase 2) is on hold
while they depend on it.

The fallback warns once per process, not once per key: the first key served from
`.env` logs why the Keychain missed and names, in that one line, every secret
`.env` holds. A secret in neither store is logged at ERROR every time it is
asked for.

Never log, print or raise a secret *value*. Errors name the key only.
"""

import logging
import os
import subprocess
import tempfile

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Keychain generic-password service. SI_KEYCHAIN_SERVICE overrides it so tests
# can point at a throwaway service and never touch the real credentials.
KEYCHAIN_SERVICE = 'ShortIndicator'

# A locked keychain makes `security` block on an interactive unlock prompt. Cap
# it so a monitor degrades to the .env fallback instead of hanging at startup.
KEYCHAIN_TIMEOUT_SECONDS = 10

# The secrets this project owns. Order is the order the migration script reports.
# KITE_ACCESS_TOKEN is deliberately absent: its single store is `.env` (config.py
# reads it with os.getenv), because the boot-time LaunchDaemon refresher cannot write
# the login Keychain, so a Keychain copy goes stale and shadows the fresh token.
# KITE_USER_ID / KITE_PASSWORD / KITE_TOTP_KEY have no consumer in this repo -
# they are read by NewsBase's data_feeds/token_refresh.py out of this same shared
# `.env`. They are listed (and migrated) so that repo's sibling task has them
# available in the Keychain.
SECRET_KEYS = (
    'KITE_API_KEY',
    'KITE_API_SECRET',
    'KITE_USER_ID',
    'KITE_PASSWORD',
    'KITE_TOTP_KEY',
    'TELEGRAM_BOT_TOKEN',
    'TELEGRAM_CHANNEL_ID',
    'TELEGRAM_DEBUG_BOT_TOKEN',
    'TELEGRAM_DEBUG_CHANNEL_ID',
)

# Same relative-'.env'-from-CWD convention as config.py: scripts run from the
# project root. Loading here keeps this module usable without importing config.
load_dotenv()

# `security` exits 44 (errSecItemNotFound) when no item matches. That is a real
# miss when the login Keychain is searchable, but a system-domain LaunchDaemon
# gets 44 for keys that ARE in the login Keychain too (probe, 2026-10-22), so the
# two cannot be told apart from the exit status. Any other failure means the
# Keychain itself could not be read here (36 = errSecInteractionNotAllowed).
_ITEM_NOT_FOUND_EXIT = 44

# Keys already named in a fallback log line - config.py is imported by nearly
# every script, so the fallback warns once per process.
_warned_keys = set()
_fallback_reported = False


class CredentialError(Exception):
    """A required secret could not be found. Names the key, never the value."""


def _keychain_service():
    """Read the service name at call time so tests can repoint it."""
    return os.getenv('SI_KEYCHAIN_SERVICE', KEYCHAIN_SERVICE)


def _security(*args, timeout=KEYCHAIN_TIMEOUT_SECONDS):
    """
    Run `security` and return its CompletedProcess, or None if it hung.

    A locked keychain makes `security` wait on a GUI unlock that no launchd job
    can answer. Hanging a monitor is worse than missing a secret, so a timeout
    becomes a miss and the caller falls back.
    """
    try:
        return subprocess.run(['/usr/bin/security', *args],
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error("`security %s` timed out after %ss - keychain may be locked",
                     args[0], timeout)
        return None


def get_secret(name, required=False, env_fallback=True):
    """
    Return the secret `name`, from the Keychain if present, else from `.env`.

    required=True raises CredentialError when neither source has it, so a caller
    that cannot function without the secret fails loudly instead of proceeding
    with None. Default is False to match the `os.getenv()` behaviour config.py
    has always had.
    """
    result = _security('find-generic-password', '-a', name, '-s', _keychain_service(), '-w')
    # Never surface result.stdout on the failure path - on success it *is* the secret.
    if result is not None and result.returncode == 0:
        value = result.stdout.rstrip('\n')
        if value:
            return value

    if env_fallback:
        value = os.getenv(name)
        if value:
            _warn_env_fallback(name, result)
            return value

    message = (f"Secret '{name}' not found in Keychain (service={_keychain_service()})"
               + (" or .env" if env_fallback else ""))
    if required:
        raise CredentialError(message)
    logger.error(message)
    return None


def _keychain_miss_reason(result):
    """Why `security` did not supply a value - never mentions its output."""
    if result is None:
        return "Keychain timed out"
    if result.returncode == 0:
        return "Keychain item is empty"
    if result.returncode == _ITEM_NOT_FOUND_EXIT:
        return ("not found in Keychain - either missing, or this context cannot "
                "see the login Keychain (e.g. a LaunchDaemon)")
    return f"Keychain unavailable in this context (security exit {result.returncode})"


def _warn_env_fallback(name, result):
    """Warn once per process that secrets come from .env, naming them all."""
    global _fallback_reported
    if name in _warned_keys:
        return

    if _fallback_reported:
        # Not a SECRET_KEYS entry, so the first line could not name it.
        _warned_keys.add(name)
        logger.info("%s also served from .env", name)
        return

    # A miss here is almost always a property of the context, so every secret
    # will miss the same way: name them all now rather than one line per key.
    _fallback_reported = True
    keys = [name] + [k for k in SECRET_KEYS if k != name and os.getenv(k)]
    _warned_keys.update(keys)
    logger.warning("%s (service=%s); using .env for %s",
                   _keychain_miss_reason(result), _keychain_service(), ', '.join(keys))


def set_secret(name, value):
    """
    Store `name` in the Keychain, replacing any existing entry (-U).

    The Keychain write is transactional, so unlike the `.env` read-modify-write
    that caused the 2026-08-09 loss there is no window in which a concurrent
    reader sees a partial or empty store.

    The value is passed as an argv element - the form verified to work
    non-interactively under launchd - so it is briefly visible in `ps` on this
    single-user machine. `security` offers no stdin mode for `-w`.
    """
    if not value:
        raise CredentialError(f"Refusing to store an empty value for '{name}'")

    result = _security('add-generic-password',
                       '-a', name, '-s', _keychain_service(), '-w', value, '-U')
    if result is None:
        raise CredentialError(f"Keychain write for '{name}' timed out")
    if result.returncode != 0:
        # stderr from `security` reports the failure reason, not the value.
        raise CredentialError(
            f"Keychain write failed for '{name}': {result.stderr.strip()}"
        )


def delete_secret(name):
    """Remove `name` from the Keychain. Returns True if an entry was removed."""
    result = _security('delete-generic-password', '-a', name, '-s', _keychain_service())
    return result is not None and result.returncode == 0


def has_secret(name):
    """True if `name` is in the Keychain. Tests presence without reading the value."""
    result = _security('find-generic-password', '-a', name, '-s', _keychain_service())
    return result is not None and result.returncode == 0


def update_env_atomic(updates, env_path='.env'):
    """
    Apply {key: value} to `env_path` without ever exposing a partial file.

    Writes a temp file in the same directory, flushes and fsyncs it, then
    os.replace()s it over the target. A concurrent reader sees either the whole
    old file or the whole new one - the failure mode that destroyed 22 settings
    on 2026-08-09 cannot occur through this path.

    Returns True on success, False if the file does not exist.
    """
    if not os.path.exists(env_path):
        logger.error("%s not found - nothing updated", env_path)
        return False

    with open(env_path, 'r') as f:
        lines = f.readlines()

    remaining = dict(updates)
    for i, line in enumerate(lines):
        for key in list(remaining):
            if line.startswith(f'{key}='):
                lines[i] = f'{key}={remaining.pop(key)}\n'
                break

    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    for key, value in remaining.items():
        lines.append(f'{key}={value}\n')

    mode = os.stat(env_path).st_mode & 0o777
    directory = os.path.dirname(os.path.abspath(env_path))
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix='.env.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, env_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return True
