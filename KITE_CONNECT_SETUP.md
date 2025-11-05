# Kite Connect Setup Guide

This guide will help you set up Kite Connect from Zerodha to fetch real-time NSE stock prices.

## Prerequisites

1. **Zerodha Trading Account**: You must have an active Zerodha trading account
2. **Kite Connect Subscription**: Subscribe to Kite Connect API from Zerodha
   - Cost: ₹2,000/month (as of 2025)
   - Includes access to live market data and trading APIs

## Step 1: Create Kite Connect App

1. Go to [https://developers.kite.trade/](https://developers.kite.trade/)
2. Log in with your Zerodha credentials
3. Click on **"Create New App"**
4. Fill in the app details:
   - **App Name**: NSE Stock Monitor (or any name you prefer)
   - **Redirect URL**: `http://127.0.0.1:5000` (for local testing)
   - **Description**: Stock drop monitoring system
5. Click **"Create"**
6. You will receive:
   - **API Key** (e.g., `abc123xyz456`)
   - **API Secret** (e.g., `def789ghi012`)

## Step 2: Generate Access Token

The access token is valid for 1 day and needs to be regenerated daily. There are two methods:

### Method A: Manual Generation (Quick Start)

1. Go to [https://kite.trade/connect/login?api_key=YOUR_API_KEY](https://kite.trade/connect/login?api_key=YOUR_API_KEY)
   - Replace `YOUR_API_KEY` with your actual API key
2. Log in with your Zerodha credentials
3. Authorize the app
4. You'll be redirected to: `http://127.0.0.1:5000/?request_token=XXXXXX&action=login&status=success`
5. Copy the `request_token` from the URL
6. Use this Python script to generate the access token:

```python
from kiteconnect import KiteConnect

api_key = "YOUR_API_KEY"
api_secret = "YOUR_API_SECRET"
request_token = "REQUEST_TOKEN_FROM_URL"

kite = KiteConnect(api_key=api_key)
data = kite.generate_session(request_token, api_secret=api_secret)

print("Access Token:", data["access_token"])
```

### Method B: Automated Generation (Recommended for Production)

Create an `generate_access_token.py` script:

```python
#!/usr/bin/env python3
"""Generate Kite Connect access token"""

from kiteconnect import KiteConnect
import config

api_key = config.KITE_API_KEY
api_secret = config.KITE_API_SECRET

# Step 1: Get login URL
kite = KiteConnect(api_key=api_key)
login_url = kite.login_url()

print("=" * 60)
print("Kite Connect Token Generation")
print("=" * 60)
print(f"\n1. Visit this URL and login:\n{login_url}\n")
print("2. After login, you'll be redirected to a URL like:")
print("   http://127.0.0.1:5000/?request_token=XXXXX&action=login&status=success")
print("\n3. Copy the 'request_token' value from that URL")
print("=" * 60)

request_token = input("\nEnter the request_token: ").strip()

try:
    # Step 2: Generate access token
    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]

    print("\n" + "=" * 60)
    print("✅ SUCCESS!")
    print("=" * 60)
    print(f"\nAccess Token: {access_token}")
    print("\nAdd this to your .env file:")
    print(f"KITE_ACCESS_TOKEN={access_token}")
    print("\n⚠️  Note: This token is valid for 1 day only")
    print("=" * 60)

except Exception as e:
    print(f"\n❌ ERROR: {e}")
```

## Step 3: Configure .env File

Add these lines to your `.env` file:

```bash
# Data Source
DATA_SOURCE=kite

# Kite Connect API Credentials
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here
KITE_ACCESS_TOKEN=your_access_token_here

# Rate Limiting (Kite Connect allows 3 requests/second)
REQUEST_DELAY_SECONDS=0.4  # ~2.5 requests per second
MAX_RETRIES=3
RETRY_DELAY_SECONDS=2.0
```

## Step 4: Test Connection

Run the test script:

```bash
python3 test_kite.py
```

## Kite Connect Rate Limits

- **3 requests per second** for quote/LTP APIs
- **1 request per second** for order placement
- **10 requests per second** for historical data

**Recommended Settings:**
- `REQUEST_DELAY_SECONDS=0.4` (allows ~2.5 req/sec, safe margin)
- For 191 stocks: ~76 seconds (~1.3 minutes) per run

## Daily Token Refresh

Since access tokens expire after 24 hours, you have two options:

### Option 1: Manual Refresh
Run the token generation script every morning before market hours:
```bash
python3 generate_access_token.py
```

### Option 2: Automated Refresh
Create a launchd job that runs at 9:00 AM daily to refresh the token (advanced setup).

## Troubleshooting

### Error: "TokenException: Incorrect API key or secret"
- Double-check your API key and secret from Kite Connect dashboard
- Ensure no extra spaces in .env file

### Error: "TokenException: Invalid access token"
- Token has expired (24-hour validity)
- Generate a new access token

### Error: "NetworkException"
- Check internet connectivity
- Verify firewall isn't blocking connections to api.kite.trade

### Error: "InputException: Invalid instrument"
- Verify stock symbol is correct (use NSE:SYMBOL format)
- Ensure stock is trading and not suspended

## Cost Breakdown

| Item | Cost |
|------|------|
| Kite Connect API Subscription | ₹2,000/month |
| Zerodha Trading Account | Free (₹300 one-time) |

**Total**: ₹2,000/month

## Advantages of Kite Connect

✅ **Reliable**: Direct data from Zerodha/NSE
✅ **Fast**: Low latency, real-time data
✅ **Official API**: No scraping, no SSL issues
✅ **High rate limits**: 3 req/sec for quotes
✅ **Comprehensive**: Access to full market data
✅ **Well-documented**: Excellent API documentation

## Support

- **Kite Connect Docs**: https://kite.trade/docs/connect/v3/
- **API Forum**: https://forum.kite.trade/
- **Support Email**: kitesupport@zerodha.com

---

**Next Steps:**
1. Create your Kite Connect app
2. Generate access token
3. Update .env file
4. Run `python3 test_kite.py` to verify setup
5. Start monitoring: `python3 main.py`
