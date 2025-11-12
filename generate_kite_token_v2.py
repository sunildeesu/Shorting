#!/usr/bin/env python3
"""
Improved Kite Connect Token Generator

Fixes:
- Better URL parsing for request_token
- Validates token after generation
- Auto-loads credentials from .env
- Better error messages
"""

from kiteconnect import KiteConnect
import sys
import os
import re
from datetime import datetime, timedelta
import json

print("=" * 70)
print("Kite Connect Access Token Generator (v2 - Improved)")
print("=" * 70)

# Try to load credentials from .env
api_key = None
api_secret = None

if os.path.exists('.env'):
    print("\n✓ Found .env file, loading credentials...")
    with open('.env', 'r') as f:
        for line in f:
            if line.startswith('KITE_API_KEY='):
                api_key = line.split('=', 1)[1].strip()
            elif line.startswith('KITE_API_SECRET='):
                api_secret = line.split('=', 1)[1].strip()

# Prompt for missing credentials
if not api_key:
    api_key = input("\nEnter your Kite API Key: ").strip()
else:
    print(f"   API Key: {api_key}")
    use_key = input("   Use this API key? (y/n): ").strip().lower()
    if use_key != 'y':
        api_key = input("\nEnter your Kite API Key: ").strip()

if not api_secret:
    api_secret = input("Enter your Kite API Secret: ").strip()
else:
    print(f"   API Secret: {api_secret[:8]}...")
    use_secret = input("   Use this API secret? (y/n): ").strip().lower()
    if use_secret != 'y':
        api_secret = input("Enter your Kite API Secret: ").strip()

if not api_key or not api_secret:
    print("\n❌ ERROR: API Key and Secret are required!")
    sys.exit(1)

# Step 1: Generate login URL
print("\n" + "=" * 70)
print("STEP 1: Login to Kite")
print("=" * 70)

kite = KiteConnect(api_key=api_key)
login_url = kite.login_url()

print(f"\nOpen this URL in your browser:\n")
print(f"  {login_url}\n")
print("After logging in and authorizing, you'll be redirected to a URL like:")
print("  http://127.0.0.1/?request_token=XXXXX&action=login&status=success")
print("  OR")
print("  http://127.0.0.1:5000/?request_token=XXXXX&action=login&status=success")
print("\n" + "=" * 70)

# Step 2: Get redirect URL
redirect_input = input("\nPaste the FULL redirect URL here: ").strip()

if not redirect_input:
    print("\n❌ ERROR: URL is required!")
    sys.exit(1)

# Step 3: Extract request_token (improved parsing)
request_token = None

# Method 1: Parse as URL with query params
if "request_token=" in redirect_input:
    # Try regex extraction (most reliable)
    match = re.search(r'request_token=([^&\s]+)', redirect_input)
    if match:
        request_token = match.group(1)
        print(f"✓ Extracted request_token: {request_token[:10]}...")
    else:
        print("\n❌ ERROR: Could not extract request_token from URL!")
        print(f"   URL provided: {redirect_input}")
        sys.exit(1)
else:
    # Assume it's just the token
    request_token = redirect_input
    print(f"✓ Using request_token: {request_token[:10]}...")

if not request_token or len(request_token) < 10:
    print("\n❌ ERROR: Invalid request_token!")
    print(f"   Token: {request_token}")
    sys.exit(1)

# Step 4: Generate access token
print("\n" + "=" * 70)
print("STEP 2: Generating Access Token")
print("=" * 70)

try:
    print(f"\nCalling Kite API with request_token...")
    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]
    user_id = data["user_id"]

    print(f"\n✅ SUCCESS! Access Token Generated")
    print(f"   User ID: {user_id}")
    print(f"   Access Token: {access_token}")

except Exception as e:
    print(f"\n❌ ERROR: Failed to generate access token!")
    print(f"   Error: {e}")
    print(f"\n   Common causes:")
    print(f"   1. Request token already used (they're single-use only)")
    print(f"   2. Request token expired (they expire in ~2 minutes)")
    print(f"   3. Incorrect API key or secret")
    print(f"\n   Solution: Get a FRESH redirect URL by logging in again")
    sys.exit(1)

# Step 5: Validate token works
print("\n" + "=" * 70)
print("STEP 3: Validating Token")
print("=" * 70)

try:
    kite.set_access_token(access_token)
    profile = kite.profile()
    print(f"\n✅ Token validated successfully!")
    print(f"   User: {profile['user_name']}")
    print(f"   Email: {profile['email']}")

    # Test quote API
    quote = kite.quote(["NSE:RELIANCE"])
    reliance_price = quote["NSE:RELIANCE"]["last_price"]
    print(f"   API Test: RELIANCE @ ₹{reliance_price} ✓")

except Exception as e:
    print(f"\n⚠️  WARNING: Token generated but validation failed!")
    print(f"   Error: {e}")
    print(f"   The token may still work - proceeding to save it...")

# Step 6: Update .env file
print("\n" + "=" * 70)
print("STEP 4: Saving Token")
print("=" * 70)

env_path = '.env'

# Read existing .env
env_lines = []
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        env_lines = f.readlines()

# Update or add Kite credentials
kite_keys = {
    'KITE_API_KEY': api_key,
    'KITE_API_SECRET': api_secret,
    'KITE_ACCESS_TOKEN': access_token,
    'DATA_SOURCE': 'kite'
}

updated_keys = set()
for i, line in enumerate(env_lines):
    for key, value in kite_keys.items():
        if line.startswith(f"{key}="):
            env_lines[i] = f"{key}={value}\n"
            updated_keys.add(key)
            break

# Add missing keys
for key, value in kite_keys.items():
    if key not in updated_keys:
        env_lines.append(f"{key}={value}\n")

# Write back to .env
with open(env_path, 'w') as f:
    f.writelines(env_lines)

print(f"\n✅ .env file updated")

# Save token metadata
try:
    os.makedirs('data', exist_ok=True)
    metadata = {
        'access_token': access_token,
        'generated_at': datetime.now().isoformat(),
        'expires_at': (datetime.now() + timedelta(hours=24)).isoformat()
    }

    with open('data/token_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)

    expires_at = datetime.now() + timedelta(hours=24)
    print(f"✅ Token metadata saved")
    print(f"   Valid until: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")

except Exception as e:
    print(f"⚠️  Warning: Could not save token metadata: {e}")

# Step 7: Summary
print("\n" + "=" * 70)
print("✅ COMPLETE!")
print("=" * 70)
print(f"\nToken Details:")
print(f"  User ID: {user_id}")
print(f"  Access Token: {access_token}")
print(f"  Valid for: 24 hours")
print(f"\nThe token has been saved to .env and is ready to use!")
print(f"\nYou can now run:")
print(f"  ./venv/bin/python3 backtest_alerts_1month.py")
print("=" * 70)
