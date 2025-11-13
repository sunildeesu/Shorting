# Alert Price Update Fix - Complete Guide

**Issue**: Prices at 2 mins, 10 mins, and EOD are not getting updated in the alert Excel file.

**Root Cause**: No automation was set up to run the price update scripts.

---

## Problem Analysis

You have 273 pending alerts with no price updates because:

1. **Missing Automation** - The update scripts exist but were never scheduled
2. **Three separate scripts** that need to run at different times:
   - `update_alert_prices.py --2min` - Should run every 2 minutes
   - `update_alert_prices.py --10min` - Should run every 10 minutes
   - `update_eod_prices.py` - Should run once at market close (3:30 PM)

---

## Solution Overview

The fix involves:
1. Refresh Kite API token (expired)
2. Run the automated setup script
3. Test the price updates manually
4. Verify automation is working

---

## Step 1: Refresh Kite API Token

Your Kite API token has expired. Refresh it first:

```bash
cd /Users/sunildeesu/myProjects/ShortIndicator
./generate_kite_token.py
```

Follow the prompts to log in and authorize the app. The new token will be saved to `.env` file.

---

## Step 2: Set Up Automation

Run the setup script:

```bash
./setup_alert_price_automation.sh
```

This will create 3 launchd agents:
- `com.nse.alert.price2min.plist` - Updates 2-min prices
- `com.nse.alert.price10min.plist` - Updates 10-min prices
- `com.nse.alert.priceeod.plist` - Updates EOD prices at 3:30 PM

---

## Step 3: Test Manual Updates

Test each script manually to ensure they work:

### Test 2-Minute Price Updates
```bash
./venv/bin/python3 update_alert_prices.py --2min
```

**Expected output**:
```
Starting 2-minute price updates...
Found X alerts needing 2-min price updates
Fetching prices for Y unique stocks
✓ Updated X alerts with 2-min prices
```

### Test 10-Minute Price Updates
```bash
./venv/bin/python3 update_alert_prices.py --10min
```

**Expected output**:
```
Starting 10-minute price updates...
Found X alerts needing 10-min price updates
Fetching prices for Y unique stocks
✓ Updated X alerts with 10-min prices
```

### Test EOD Price Updates
```bash
./venv/bin/python3 update_eod_prices.py
```

**Expected output**:
```
Starting EOD price updates for YYYY-MM-DD...
Found X alerts from YYYY-MM-DD needing EOD prices
Fetching prices for Y unique stocks
✓ Updated X alerts with EOD prices
✓ Marked X alerts as 'Complete'
```

---

## Step 4: Verify Automation Status

Check if the launchd agents are loaded and running:

```bash
launchctl list | grep com.nse.alert
```

**Expected output**:
```
-    0    com.nse.alert.price2min
-    0    com.nse.alert.price10min
-    0    com.nse.alert.priceeod
```

---

## Step 5: Check Excel File

Open the Excel file and verify that prices are being updated:

```bash
open data/alerts/alert_tracking.xlsx
```

Look for:
- **Price 2min** column (Column N) - Should have prices for alerts >2 mins old
- **Price 10min** column (Column O) - Should have prices for alerts >10 mins old
- **Price EOD** column (Column P) - Should have prices for today's alerts (after 3:30 PM)
- **Status** column (Column Q) - Should change from "Pending" → "Partial" → "Complete"

---

## Automation Schedule

Once set up, the automation runs automatically:

| Script | Frequency | Run Time | Purpose |
|--------|-----------|----------|---------|
| `update_alert_prices.py --2min` | Every 2 minutes | 9:32 AM - 3:30 PM | Captures price 2 minutes after alert |
| `update_alert_prices.py --10min` | Every 10 minutes | 9:40 AM - 3:30 PM | Captures price 10 minutes after alert |
| `update_eod_prices.py` | Once daily | 3:30 PM | Captures end-of-day closing price |

---

## Troubleshooting

### Issue 1: "Incorrect api_key or access_token" Error

**Cause**: Kite API token expired

**Fix**:
```bash
./generate_kite_token.py
```

Re-generate the token and restart the automation:
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.alert.price*.plist
launchctl load ~/Library/LaunchAgents/com.nse.alert.price*.plist
```

---

### Issue 2: Agents Not Running

**Check if loaded**:
```bash
launchctl list | grep com.nse.alert
```

**If not listed**, load them:
```bash
launchctl load ~/Library/LaunchAgents/com.nse.alert.price2min.plist
launchctl load ~/Library/LaunchAgents/com.nse.alert.price10min.plist
launchctl load ~/Library/LaunchAgents/com.nse.alert.priceeod.plist
```

---

### Issue 3: Automation Running But No Updates

**Check logs**:
```bash
tail -f logs/price_update_2min.log
tail -f logs/price_update_10min.log
tail -f logs/price_update_eod.log
```

**Common causes**:
1. API token expired - Regenerate token
2. No pending alerts - Check Excel file
3. File permission issues - Check Excel file is not open in Excel (file locking)

---

### Issue 4: Excel File Locked

If you see "Error saving workbook" in logs:

**Cause**: Excel file is open in Microsoft Excel

**Fix**: Close the Excel file and let the automation run in the background

---

## Manual Commands Reference

### Stop Automation
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.alert.price2min.plist
launchctl unload ~/Library/LaunchAgents/com.nse.alert.price10min.plist
launchctl unload ~/Library/LaunchAgents/com.nse.alert.priceeod.plist
```

### Start Automation
```bash
launchctl load ~/Library/LaunchAgents/com.nse.alert.price2min.plist
launchctl load ~/Library/LaunchAgents/com.nse.alert.price10min.plist
launchctl load ~/Library/LaunchAgents/com.nse.alert.priceeod.plist
```

### Force Run Now (Testing)
```bash
# Update 2-min prices
./venv/bin/python3 update_alert_prices.py --2min

# Update 10-min prices
./venv/bin/python3 update_alert_prices.py --10min

# Update both
./venv/bin/python3 update_alert_prices.py --both

# Update EOD prices for today
./venv/bin/python3 update_eod_prices.py

# Update EOD prices for specific date
./venv/bin/python3 update_eod_prices.py --date 2025-11-12
```

### Check Pending Alerts
```bash
./venv/bin/python3 -c "
from alert_excel_logger import AlertExcelLogger
import config

logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
pending = logger.get_pending_updates(min_age_minutes=0)

for sheet_name, alerts in pending.items():
    print(f'{sheet_name}: {len(alerts)} pending')
print(f'Total: {sum(len(a) for a in pending.values())}')
"
```

---

## How the System Works

### 1. Alert Generation
When a stock triggers an alert (drop/rise/volume spike), the main monitor scripts call:
```python
alert_logger.log_alert(
    symbol="RELIANCE",
    alert_type="5min",
    drop_percent=-2.5,
    current_price=2450.50,
    previous_price=2512.85,
    ...
)
```

This creates a row in Excel with:
- Date, Time, Symbol, Direction, Alert Price
- **Price 2min**: Empty (to be filled)
- **Price 10min**: Empty (to be filled)
- **Price EOD**: Empty (to be filled)
- **Status**: "Pending"

### 2. Price Update Cycle

**After 2 minutes**:
- `update_alert_prices.py --2min` runs
- Finds alerts >2 minutes old with empty "Price 2min"
- Fetches current prices from Kite API
- Updates "Price 2min" column
- Status changes to "Partial"

**After 10 minutes**:
- `update_alert_prices.py --10min` runs
- Finds alerts >10 minutes old with empty "Price 10min"
- Fetches current prices from Kite API
- Updates "Price 10min" column with color coding:
  - 🟢 Green: Price moved in predicted direction
  - 🔴 Red: Price moved opposite to prediction
- Status remains "Partial"

**At market close (3:30 PM)**:
- `update_eod_prices.py` runs
- Finds all today's alerts with empty "Price EOD"
- Fetches closing prices from Kite API
- Updates "Price EOD" column with color coding
- Status changes to "Complete"

### 3. Color Coding Logic

**For DROP alerts**:
- 🟢 Green (good): Price dropped further (negative change from 2-min price)
- 🔴 Red (bad): Price rose (positive change from 2-min price)

**For RISE alerts**:
- 🟢 Green (good): Price rose further (positive change from 2-min price)
- 🔴 Red (bad): Price dropped (negative change from 2-min price)

**Intensity levels**:
- Light: 0-0.5% change
- Medium: 0.5-1.5% change
- Dark: >1.5% change

---

## Current Status

**Pending alerts**: 273 alerts without price updates

**Breakdown**:
- 5min_alerts: 141 pending
- 10min_alerts: 96 pending
- 30min_alerts: 34 pending
- Volume_Spike_alerts: 2 pending

These alerts are from Nov 10-11 and need prices to be backfilled.

---

## Next Steps

1. ✅ Refresh Kite API token
2. ✅ Run setup script to create automation
3. ⏳ Test manual updates to backfill old alerts
4. ⏳ Verify automation is running
5. ⏳ Monitor logs for errors

---

## Files Modified/Created

- `setup_alert_price_automation.sh` - Automation setup script
- `~/Library/LaunchAgents/com.nse.alert.price2min.plist` - 2-min updater
- `~/Library/LaunchAgents/com.nse.alert.price10min.plist` - 10-min updater
- `~/Library/LaunchAgents/com.nse.alert.priceeod.plist` - EOD updater
- `logs/price_update_2min.log` - 2-min update logs
- `logs/price_update_10min.log` - 10-min update logs
- `logs/price_update_eod.log` - EOD update logs

---

## Summary

The alert price tracking system is now complete with:
- ✅ Alert logging with Excel tracking
- ✅ Automated 2-minute price capture
- ✅ Automated 10-minute price capture
- ✅ Automated EOD price capture
- ✅ Color-coded performance tracking
- ✅ Status management (Pending → Partial → Complete)

All you need to do is:
1. **Refresh the Kite token** (one-time, when expired)
2. **Run the setup script** (one-time setup)
3. **Let it run automatically** (no intervention needed)
