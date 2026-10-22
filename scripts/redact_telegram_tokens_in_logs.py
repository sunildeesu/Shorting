#!/usr/bin/env python3
"""Mask Telegram bot tokens in existing log files, in place.

Logs written before `telegram_redaction` existed carry `bot<id>:<secret>` in
connection-error and urllib3 DEBUG lines. This rewrites each given file with
every token replaced by `bot<REDACTED>` and prints a per-file count. It never
prints a token or a matching line.

    python scripts/redact_telegram_tokens_in_logs.py --dry-run logs/*.log
    python scripts/redact_telegram_tokens_in_logs.py logs/*.log

A file is rewritten via a temp file + os.replace, keeping its permissions, so a
crash mid-run leaves either the old or the new file. A process that holds the
log open keeps appending to the old inode; stop such writers first (or
re-run afterwards) if they may still log tokens.
"""
import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_redaction import REDACTED, TOKEN_RE


def redact_file(path: str, dry_run: bool) -> int:
    """Return the number of tokens in `path`; rewrite it masked unless dry_run."""
    with open(path, 'rb') as f:
        data = f.read()
    # Logs are mostly UTF-8 but not guaranteed; surrogateescape round-trips any byte.
    text = data.decode('utf-8', errors='surrogateescape')
    new_text, count = TOKEN_RE.subn(REDACTED, text)
    if count and not dry_run:
        mode = os.stat(path).st_mode
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)),
                                   prefix='.redact-')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(new_text.encode('utf-8', errors='surrogateescape'))
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
    return count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('files', nargs='+', help='log files to rewrite in place')
    parser.add_argument('--dry-run', action='store_true',
                        help='report counts only; change nothing')
    args = parser.parse_args(argv)

    total = 0
    failed = False
    for path in args.files:
        try:
            count = redact_file(path, args.dry_run)
        except OSError as e:
            print(f"{path}: ERROR {e.strerror}", file=sys.stderr)
            failed = True
            continue
        total += count
        verb = 'would redact' if args.dry_run else 'redacted'
        print(f"{path}: {verb} {count}")
    print(f"TOTAL: {'would redact' if args.dry_run else 'redacted'} {total}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
