# Daily Alert Price Update Automation

**Simple once-daily automation** that runs at 3:45 PM (after market close) to update all alert prices.

---

## What It Does

Every day at **3:45 PM**, the automation runs three updates in sequence:

1. **2-min prices** - Fetches historical prices from 2 minutes after each alert
2. **10-min prices** - Fetches historical prices from 10 minutes after each alert
3. **EOD prices** - Fetches closing prices for today's alerts

**Why 3:45 PM?**
- Market closes at 3:30 PM
- Gives 15 minutes for settlement
- All alerts from the day are old enough (>2 mins, >10 mins)
- Can fetch today's closing prices

---

## How It Works

### Single Script Runs Daily
```bash
daily_alert_price_update.sh
```

**What it does**:
```
1. Update 2-min prices (historical API) → All pending alerts
2. Update 10-min prices (historical API) → All pending alerts
3. Update EOD prices (historical API) → Today's alerts only
```

### Uses Historical Data API
- **Not** current live prices
- Fetches actual price at the specific time
- Example for alert at 09:30:15:
  - 2-min: Gets candle at 09:32:15 → actual price then
  - 10-min: Gets candle at 09:40:15 → actual price then
  - EOD: Gets daily close → actual closing price

---

## Setup (Already Done)

The automation is now active:

✅ Script created: `daily_alert_price_update.sh`
✅ LaunchAgent created: `com.nse.alert.daily.update.plist`
✅ Scheduled: Daily at 3:45 PM
✅ Loaded and running

---

## Manual Commands

### Test the Daily Update Now
```bash
./daily_alert_price_update.sh
```

This runs all three updates in sequence.

### Run Individual Updates
```bash
# Only 2-min prices
./venv/bin/python3 update_alert_prices_v2.py --2min

# Only 10-min prices
./venv/bin/python3 update_alert_prices_v2.py --10min

# Only EOD prices for today
./venv/bin/python3 update_eod_prices_v2.py

# EOD prices for specific date
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-12
```

---

## Check Automation Status

### Verify It's Running
```bash
launchctl list | grep com.nse.alert.daily
```

**Expected output**:
```
-    0    com.nse.alert.daily.update
```

### Check Logs
```bash
# View today's log
tail -f logs/daily_price_update.log

# Check for errors
tail -f logs/daily_price_update_error.log
```

### See Next Run Time
```bash
launchctl print gui/$(id -u)/com.nse.alert.daily.update
```

---

## Stop/Start Automation

### Stop (Disable)
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.alert.daily.update.plist
```

### Start (Enable)
```bash
launchctl load ~/Library/LaunchAgents/com.nse.alert.daily.update.plist
```

---

## What Happens Each Day

### Timeline

**During Market Hours (9:30 AM - 3:30 PM)**:
- Stock monitors generate alerts
- Alerts logged to Excel with Status = "Pending"
- Price columns are empty

**At 3:45 PM (Automation Runs)**:
- Step 1: Update 2-min prices
  - Finds all alerts with empty "Price 2min"
  - For each alert, calculates target time (alert_time + 2 min)
  - Fetches historical 1-min candle at that time
  - Updates Excel with close price
  - Status changes to "Partial"

- Step 2: Update 10-min prices
  - Finds all alerts with empty "Price 10min"
  - For each alert, calculates target time (alert_time + 10 min)
  - Fetches historical 1-min candle at that time
  - Updates Excel with close price
  - Status remains "Partial"

- Step 3: Update EOD prices
  - Finds all alerts from today with empty "Price EOD"
  - Groups by symbol (minimize API calls)
  - Fetches daily candle for today
  - Updates Excel with closing price
  - Status changes to "Complete"

**Result**: All today's alerts have complete price tracking by 3:46 PM

---

## Performance

### API Calls Per Day

Assuming 100 alerts per day:

| Update | API Calls | Time |
|--------|-----------|------|
| 2-min prices | ~100 (1 per alert) | 15 seconds |
| 10-min prices | ~100 (1 per alert) | 15 seconds |
| EOD prices | ~40 (1 per unique symbol) | 5 seconds |
| **Total** | **~240** | **~35 seconds** |

With rate limiting (0.1s delay), total time is about 35-40 seconds.

### Efficiency vs Old Approach

**Old approach** (every 2/10 mins during market hours):
- 2-min updater: 180 runs/day × API calls = thousands
- 10-min updater: 36 runs/day × API calls = hundreds
- Total: 5000+ API calls/day

**New approach** (once daily at 3:45 PM):
- All updates: 1 run/day × 240 calls = 240
- Total: 240 API calls/day

**Savings: 95% fewer API calls!**

---

## Troubleshooting

### Issue 1: Automation Didn't Run

**Check if loaded**:
```bash
launchctl list | grep com.nse.alert.daily
```

If not listed:
```bash
launchctl load ~/Library/LaunchAgents/com.nse.alert.daily.update.plist
```

---

### Issue 2: API Token Expired

**Symptom**: Logs show "Incorrect api_key or access_token"

**Fix**:
```bash
./generate_kite_token.py
```

Refresh token and it will work tomorrow.

---

### Issue 3: No Updates Happening

**Check logs**:
```bash
tail -50 logs/daily_price_update.log
```

**Common causes**:
1. No new alerts today (nothing to update)
2. All alerts already have prices (already updated)
3. Excel file is open (file locking)

---

### Issue 4: Missed Yesterday's Alerts

If automation failed yesterday, manually run for that date:

```bash
# Backfill missing EOD for yesterday
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-12
```

The 2-min and 10-min prices will be filled the next time you run the daily update (it processes ALL pending alerts, not just today's).

---

## Log File Location

All output goes to:
```
logs/daily_price_update.log
logs/daily_price_update_error.log
```

**Log rotation**: Logs append daily. Clean them monthly:
```bash
# Archive old logs
mv logs/daily_price_update.log logs/daily_price_update_$(date +%Y%m).log

# Create fresh log
touch logs/daily_price_update.log
```

---

## Example Log Output

```
=======================================================================
Daily Alert Price Update - 2025-11-13 15:45:00
=======================================================================

Step 1: Updating 2-minute historical prices...
-----------------------------------------------------------------------
Loading NSE instrument tokens...
Loaded 8543 instrument tokens
Found 95 alerts needing 2-min price updates
  RELIANCE @ 09:32:15: ₹2450.50
  TCS @ 09:32:20: ₹3650.25
  ...
✓ Updated 95 alerts with 2-min HISTORICAL prices

Step 2: Updating 10-minute historical prices...
-----------------------------------------------------------------------
Found 95 alerts needing 10-min price updates
  RELIANCE @ 09:40:15: ₹2455.75
  TCS @ 09:40:20: ₹3648.50
  ...
✓ Updated 95 alerts with 10-min HISTORICAL prices

Step 3: Updating EOD closing prices for 2025-11-13...
-----------------------------------------------------------------------
Found 95 alerts from 2025-11-13 needing EOD prices
Fetching EOD prices for 35 unique stocks
  RELIANCE: ₹2468.90
  TCS: ₹3655.00
  ...
✓ Updated 95 alerts with EOD HISTORICAL prices
✓ Marked 95 alerts as 'Complete'

=======================================================================
Daily Alert Price Update Complete - 2025-11-13 15:45:35
=======================================================================
```

---

## Benefits of This Approach

### 1. Simple
- One script runs once per day
- No complex scheduling
- Easy to understand and maintain

### 2. Efficient
- 95% fewer API calls vs real-time updates
- Batches all updates together
- Uses historical API (accurate prices)

### 3. Reliable
- Runs after market close (no missing data)
- All alerts aged enough (>2 min, >10 min)
- Can backfill missed days easily

### 4. Accurate
- Uses historical data API
- Gets actual price at specific time
- Not dependent on when script runs

### 5. Low Maintenance
- Set and forget
- Only need to refresh token monthly
- Logs show what happened

---

## Backfilling Old Alerts

If you have old alerts without prices, run the daily script manually:

```bash
# This will fill ALL pending 2-min and 10-min prices
./daily_alert_price_update.sh
```

Then manually run EOD for each missing date:
```bash
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-10
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-11
# etc...
```

---

## Monthly Maintenance

### Token Refresh (Required)

Kite tokens expire after ~30 days. Refresh monthly:

```bash
./generate_kite_token.py
```

Set a calendar reminder for the 1st of each month.

### Log Cleanup (Optional)

Archive old logs monthly:

```bash
# Keep last 3 months, delete older
find logs/ -name "daily_price_update_*.log" -mtime +90 -delete
```

---

## Files Created

- `daily_alert_price_update.sh` - Main daily script
- `~/Library/LaunchAgents/com.nse.alert.daily.update.plist` - Automation config
- `logs/daily_price_update.log` - Daily run logs
- `logs/daily_price_update_error.log` - Error logs

---

## Summary

### What You Get

✅ **Automated**: Runs daily at 3:45 PM
✅ **Complete**: Updates all three price columns
✅ **Accurate**: Uses historical data API
✅ **Efficient**: 95% fewer API calls
✅ **Simple**: One script, one schedule
✅ **Reliable**: After market close, no missing data

### What You Need to Do

1. **Nothing** - Automation runs daily
2. **Monthly**: Refresh Kite token (1st of month)
3. **If needed**: Check logs occasionally

### Zero Ongoing Effort

Set it and forget it! The automation handles everything daily.
