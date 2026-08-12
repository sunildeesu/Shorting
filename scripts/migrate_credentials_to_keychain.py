#!/usr/bin/env python3
"""
Copy the secrets in `.env` into the macOS Keychain. Run once, by hand.

    ./venv/bin/python3 scripts/migrate_credentials_to_keychain.py --dry-run
    ./venv/bin/python3 scripts/migrate_credentials_to_keychain.py

This is phase 1 of the migration: it COPIES, it does not remove anything from
`.env`. Code reads the Keychain first and falls back to `.env`, so nothing breaks
if a Keychain lookup misbehaves. Phase 2 - stripping the secrets out of `.env`
and deleting the fallback in credentials.py - happens only after a full trading
day has run clean, and is not automated here.

Secret values are never printed. Output reports key names and outcomes only.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import dotenv_values

import credentials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', default='.env',
                        help="Source .env (default: .env in the current directory)")
    parser.add_argument('--dry-run', action='store_true',
                        help="Report what would be stored, write nothing")
    parser.add_argument('--service', default=None,
                        help="Keychain service name (default: %s)"
                             % credentials.KEYCHAIN_SERVICE)
    args = parser.parse_args()

    if args.service:
        os.environ['SI_KEYCHAIN_SERVICE'] = args.service
    service = os.environ.get('SI_KEYCHAIN_SERVICE', credentials.KEYCHAIN_SERVICE)

    if not os.path.exists(args.env_file):
        print(f"ERROR: {args.env_file} not found. Run from the project root.")
        return 1

    values = dotenv_values(args.env_file)

    print(f"Source:           {args.env_file}")
    print(f"Keychain service: {service}")
    print(f"Mode:             {'dry run (no writes)' if args.dry_run else 'writing'}")
    print("-" * 62)

    stored = skipped = failed = 0
    for key in credentials.SECRET_KEYS:
        value = values.get(key)
        if not value:
            print(f"  {key:<26} absent from .env - skipped")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  {key:<26} present - would store")
            stored += 1
            continue

        try:
            credentials.set_secret(key, value)
        except credentials.CredentialError as e:
            print(f"  {key:<26} FAILED: {e}")
            failed += 1
        else:
            print(f"  {key:<26} stored in Keychain")
            stored += 1

    print("-" * 62)
    print(f"{stored} stored, {skipped} absent, {failed} failed")

    if failed:
        return 1

    if not args.dry_run:
        print("\nVerifying by presence (values are never read back here):")
        missing = [k for k in credentials.SECRET_KEYS
                   if values.get(k) and not credentials.has_secret(k)]
        if missing:
            print(f"  MISSING from Keychain: {', '.join(missing)}")
            return 1
        print("  all migrated keys present")
        print("\nPhase 1 done. Leave the secrets in .env until a full trading day "
              "has run clean on the Keychain path.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
