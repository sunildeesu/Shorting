# Kite Connect Token Management

This document explains how to manage your Kite Connect access token, which expires every 24 hours.

## Why Token Management is Needed

Zerodha's Kite Connect API requires you to generate a new access token daily for security reasons. The token expires after 24 hours and requires manual login with password + 2FA, so it **cannot be fully automated**. However, we've made the process as simple as possible.

## Quick Start - Daily Token Refresh

Every morning before 9:30 AM (market open), run:

```bash
./generate_kite_token.py
```

This will:
1. Open your browser for Kite login
2. Ask you to paste the request token
3. Generate a new 24-hour access token
4. Automatically update your `.env` file
5. Save token metadata for expiry tracking

**That's it!** Your monitoring system is now ready for the day.

## Automated Token Expiry Alerts

### Daily Reminder at 8:00 AM

Install the daily reminder service to get automatic alerts:

```bash
./setup_token_reminder.sh
```

This sets up a background job that:
- Runs every morning at 8:00 AM
- Checks if your token is expired or expiring soon
- Sends a Telegram alert if action is needed
- Logs results to `logs/token_reminder.log`

### Token Check at Startup

The monitoring system (`main.py`) automatically:
- Checks token validity before starting
- Exits with an error if token is expired
- Sends Telegram alert with instructions
- Warns you if token expires within 2 hours

## Manual Token Check

To check your current token status anytime:

```bash
./token_manager.py
```

or

```bash
./check_token.py
```

This will display:
- Token validity status
- Hours remaining until expiry
- Expiry timestamp
- Action required (if any)

## Token Management Files

### Core Files

- **`generate_kite_token.py`** - Main script to generate new tokens
- **`token_manager.py`** - Token lifecycle management library
- **`check_token.py`** - Standalone token checker (used by daily reminder)
- **`data/token_metadata.json`** - Stores token expiry information

### Automation Files

- **`com.nse.token.reminder.plist`** - Launchd job configuration
- **`setup_token_reminder.sh`** - Installation script for daily reminder

## How Token Validation Works

1. **Token Metadata Tracking**
   - When you generate a token, we save the timestamp
   - We calculate 24-hour expiry time
   - Stored in `data/token_metadata.json`

2. **Validation Checks**
   - First, checks metadata file for expiry time
   - If no metadata, tries API call to validate
   - If API call succeeds, assumes token is fresh (saves metadata)
   - If API call fails, token is invalid

3. **Alert System**
   - Expired tokens: Immediate Telegram alert
   - Expiring soon (< 2 hours): Warning alert
   - Valid tokens: No alert

## Daily Workflow

### Morning Routine (Before 9:30 AM)

1. **Check Telegram** - You'll get an 8:00 AM reminder if token needs refresh
2. **Run Token Generator** - `./generate_kite_token.py`
3. **Start Monitoring** - `./start_monitoring.sh` (token validated automatically)

### During Market Hours

- No manual intervention needed
- Monitoring runs every 5 minutes (via cron)
- Token validity checked at each startup

### End of Day

- Nothing to do!
- Token will expire overnight
- You'll get a reminder tomorrow morning

## Troubleshooting

### "Token has expired" Error

**Solution:**
```bash
./generate_kite_token.py
```

### "Token metadata not found" Warning

This happens if you manually edited `.env` without using `generate_kite_token.py`.

**Solution:** Token still works, but we don't know expiry time. Just run:
```bash
./generate_kite_token.py
```

### Daily Reminder Not Working

**Check if job is loaded:**
```bash
launchctl list | grep com.nse.token.reminder
```

**View logs:**
```bash
tail -f logs/token_reminder.log
tail -f logs/token_reminder_error.log
```

**Reinstall:**
```bash
./setup_token_reminder.sh
```

### Telegram Alerts Not Received

1. Verify Telegram credentials in `.env`
2. Test manually: `./check_token.py`
3. Check logs: `logs/token_reminder.log`

## Advanced Commands

### Uninstall Daily Reminder

```bash
launchctl unload ~/Library/LaunchAgents/com.nse.token.reminder.plist
rm ~/Library/LaunchAgents/com.nse.token.reminder.plist
```

### Test Daily Reminder Now

```bash
./check_token.py
```

### View Token Metadata

```bash
cat data/token_metadata.json | python3 -m json.tool
```

### Force Token Regeneration

Just run the generator again - it will overwrite the existing token:
```bash
./generate_kite_token.py
```

## Token Security

- **Never share your API Secret** - It's stored in `.env` (gitignored)
- **Never commit `.env` to git** - Contains sensitive credentials
- **Access token expires in 24 hours** - Automatically enforced by Zerodha
- **Request token is single-use** - Cannot be reused after generating access token

## Why Can't This Be Fully Automated?

Zerodha requires:
1. User login with password
2. Two-factor authentication (OTP/PIN)
3. Explicit consent for API access

This is a **security feature** to protect your trading account. No automated system should have your password and 2FA credentials.

## Summary

The token management system makes daily token refresh as painless as possible:

1. ✅ **Daily reminder at 8:00 AM** via Telegram
2. ✅ **One-command token refresh** with automatic .env update
3. ✅ **Automatic validation** at monitoring startup
4. ✅ **Clear error messages** with instructions
5. ✅ **Expiry tracking** with advance warnings

You just need to run one command each morning, and everything else is handled automatically!
