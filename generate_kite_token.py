#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""Generate Kite Connect access token - Run this daily before market hours"""

from kiteconnect import KiteConnect
import sys

import credentials

print("=" * 70)
print("Kite Connect Access Token Generator")
print("=" * 70)

# Get API credentials
api_key = input("\nEnter your Kite API Key: ").strip()
api_secret = input("Enter your Kite API Secret: ").strip()

if not api_key or not api_secret:
    print("\n❌ ERROR: API Key and Secret are required!")
    sys.exit(1)

# Step 1: Get login URL
kite = KiteConnect(api_key=api_key)
login_url = kite.login_url()

print("\n" + "=" * 70)
print("STEP 1: Login to Kite")
print("=" * 70)
print(f"\nVisit this URL and login with your Zerodha credentials:\n")
print(f"  {login_url}\n")
print("After logging in, you will be redirected to a URL like:")
print("  http://127.0.0.1:5000/?request_token=XXXXX&action=login&status=success")
print("\n" + "=" * 70)

redirect_input = input("\nPaste the FULL redirect URL (or just the request_token): ").strip()

if not redirect_input:
    print("\n❌ ERROR: Input is required!")
    sys.exit(1)

# Parse request_token from URL if full URL provided
request_token = redirect_input
if "request_token=" in redirect_input:
    # Extract request_token from URL
    import urllib.parse
    if "?" in redirect_input:
        query_string = redirect_input.split("?")[1]
        params = urllib.parse.parse_qs(query_string)
        if "request_token" in params:
            request_token = params["request_token"][0]
            print(f"✓ Extracted request_token: {request_token[:10]}...")
        else:
            print("\n❌ ERROR: Could not find request_token in URL!")
            sys.exit(1)
    else:
        # Try to extract from simple format
        parts = redirect_input.split("request_token=")
        if len(parts) > 1:
            request_token = parts[1].split("&")[0]
            print(f"✓ Extracted request_token: {request_token[:10]}...")

if not request_token:
    print("\n❌ ERROR: Request token is required!")
    sys.exit(1)

try:
    # Step 2: Generate access token
    print("\nGenerating access token...")
    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]
    user_id = data["user_id"]

    print("\n" + "=" * 70)
    print("✅ SUCCESS! Access Token Generated")
    print("=" * 70)
    print(f"\nUser ID: {user_id}")
    print(f"Access Token: {access_token}")
    print("\n" + "=" * 70)
    print("Add these lines to your .env file:")
    print("=" * 70)
    print(f"\nKITE_API_KEY={api_key}")
    print(f"KITE_API_SECRET={api_secret}")
    print(f"KITE_ACCESS_TOKEN={access_token}")
    print(f"DATA_SOURCE=kite")
    print("\n" + "=" * 70)
    print("⚠️  IMPORTANT NOTES:")
    print("=" * 70)
    print("1. This access token is valid for 24 hours only")
    print("2. Run this script every morning before 9:30 AM to refresh")
    print("3. Keep your API Secret secure and never share it")
    print("=" * 70)

    # Offer to update .env file automatically
    update_env = input("\nWould you like to update .env file automatically? (y/n): ").strip().lower()

    if update_env == 'y':
        # Secrets go to the Keychain. get_secret() prefers the Keychain, so a
        # manual refresh that only touched .env would leave the whole system
        # reading the stale Keychain token.
        for key, value in (('KITE_API_KEY', api_key),
                           ('KITE_API_SECRET', api_secret),
                           ('KITE_ACCESS_TOKEN', access_token)):
            credentials.set_secret(key, value)

        print("\n✅ Kite credentials stored in the Keychain")

        # Mirror into .env for the phase-1 fallback and the non-secret DATA_SOURCE.
        # Atomic (temp file + os.replace) - see credentials.update_env_atomic.
        if credentials.update_env_atomic({
            'KITE_API_KEY': api_key,
            'KITE_API_SECRET': api_secret,
            'KITE_ACCESS_TOKEN': access_token,
            'DATA_SOURCE': 'kite',
        }):
            print(f"\n✅ .env file updated successfully!")
        else:
            print("\n⚠️  No .env file found - copy .env.example to .env and add "
                  "DATA_SOURCE=kite. The secrets above are already in the Keychain.")

        # Save token metadata for expiry tracking
        try:
            from token_manager import TokenManager
            manager = TokenManager()
            manager.save_token_metadata(access_token)

            from datetime import datetime, timedelta
            expires_at = datetime.now() + timedelta(hours=24)
            print(f"✅ Token metadata saved")
            print(f"   Token valid until: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Remember to refresh token before this time!")
        except Exception as e:
            print(f"⚠️ Warning: Could not save token metadata: {e}")

        print("\nYou can now run: python3 test_kite.py")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    print("\nPossible issues:")
    print("  - Invalid request token (expired or incorrect)")
    print("  - Incorrect API key or secret")
    print("  - Network connectivity issue")
    sys.exit(1)
