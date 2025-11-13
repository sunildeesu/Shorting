# Fix Wrong Alert Prices - Complete Recovery Guide

**Issue**: Excel is filled with WRONG data (all prices the same) and marked Complete/Partial

**Problem**: Update scripts skip rows that already have data, so the wrong prices stay

---

## Solution Overview

3-step process to fix the wrong data:

1. **RESET** - Clear wrong prices and reset status to "Pending"
2. **REFRESH** - Get new Kite API token
3. **REPOPULATE** - Run V2 scripts to fill with correct historical data

---

## Step 1: Check Current Status

First, see what you're working with:

```bash
./venv/bin/python3 reset_alert_prices.py --summary
```

**Expected output**:
```
CURRENT ALERT STATUS SUMMARY
============================================================
  5min_alerts: 141 alerts
  10min_alerts: 96 alerts
  30min_alerts: 34 alerts
  Volume_Spike_alerts: 2 alerts

Total Alerts: 273
  - Complete: 100
  - Partial: 150
  - Pending: 23
============================================================
```

This shows you have wrong data that needs clearing.

---

## Step 2: Reset Wrong Data

You have two options:

### Option A: Reset ALL Alerts (Recommended)

If all your data is wrong, reset everything:

```bash
./venv/bin/python3 reset_alert_prices.py --all
```

**What it does**:
- Clears all Price 2min, Price 10min, Price EOD columns
- Removes color formatting
- Resets Status to "Pending" for all rows
- Saves the Excel file

**Confirmation prompt**:
```
⚠️  WARNING: This will CLEAR all price data (2-min, 10-min, EOD)
⚠️  and reset status to 'Pending' for the selected alerts.

🔴 You are about to reset ALL alerts in the workbook!

Are you sure you want to continue? (yes/no):
```

Type `yes` to proceed.

**Output**:
```
  5min_alerts: Reset 141 alerts
  10min_alerts: Reset 96 alerts
  30min_alerts: Reset 34 alerts
  Volume_Spike_alerts: Reset 2 alerts
✓ Successfully reset 273 alerts

RESET COMPLETE: 273 alerts reset
```

### Option B: Reset Specific Dates Only

If only certain dates have wrong data:

```bash
# Reset single date
./venv/bin/python3 reset_alert_prices.py --date 2025-11-10

# Reset multiple dates
./venv/bin/python3 reset_alert_prices.py --date 2025-11-10 --date 2025-11-11 --date 2025-11-12
```

**What it does**:
- Only resets alerts from specified dates
- Leaves other dates untouched

---

## Step 3: Verify Reset

Check that the reset worked:

```bash
./venv/bin/python3 reset_alert_prices.py --summary
```

**Expected output**:
```
Total Alerts: 273
  - Complete: 0      ← Should be 0 now!
  - Partial: 0       ← Should be 0 now!
  - Pending: 273     ← All should be Pending!
```

Or manually open Excel:
```bash
open data/alerts/alert_tracking.xlsx
```

**Check that**:
- Price 2min column (N) is EMPTY
- Price 10min column (O) is EMPTY
- Price EOD column (P) is EMPTY
- Status column (Q) shows "Pending"

---

## Step 4: Refresh Kite API Token

Before repopulating, refresh your token:

```bash
./generate_kite_token.py
```

Follow the prompts to log in. The new token will be saved to `.env`.

---

## Step 5: Repopulate with Correct Historical Data

Now run the V2 scripts to populate with CORRECT prices:

### 5a. Update 2-Minute Prices (Historical)

```bash
./venv/bin/python3 update_alert_prices_v2.py --2min
```

**What happens**:
- Loads instrument tokens (3500+)
- Finds all alerts with empty "Price 2min"
- For each alert: calculates `alert_time + 2 minutes`
- Fetches 1-minute historical candle at that time
- Updates Excel with the candle's close price

**Expected output**:
```
Loading NSE instrument tokens...
Loaded 3578 instrument tokens
Found 273 alerts needing 2-min price updates
  RELIANCE @ 09:32:15: ₹2450.50
  TCS @ 09:32:20: ₹3650.25
  INFY @ 09:32:25: ₹1585.75
  ...
✓ Updated 273 alerts with 2-min HISTORICAL prices
```

**Time**: ~30 seconds for 273 alerts (with rate limiting)

### 5b. Update 10-Minute Prices (Historical)

```bash
./venv/bin/python3 update_alert_prices_v2.py --10min
```

**What happens**:
- Same process but for `alert_time + 10 minutes`
- Fetches historical candles from 10 minutes after each alert

**Expected output**:
```
Found 273 alerts needing 10-min price updates
  RELIANCE @ 09:40:15: ₹2455.75  (different from 2-min!)
  TCS @ 09:40:20: ₹3648.50  (different from 2-min!)
  ...
✓ Updated 273 alerts with 10-min HISTORICAL prices
```

**Time**: ~30 seconds for 273 alerts

### 5c. Update EOD Prices (Historical)

Update each date separately:

```bash
# Update Nov 10
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-10

# Update Nov 11
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-11

# Update Nov 12
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-12

# Update today (if needed)
./venv/bin/python3 update_eod_prices_v2.py
```

**What happens**:
- Finds all alerts from that date with empty "Price EOD"
- Groups by symbol (minimize API calls)
- Fetches daily candle for that date
- Uses the candle's close price (actual EOD)

**Expected output**:
```
Starting EOD HISTORICAL price updates for 2025-11-10...
Found 200 alerts from 2025-11-10 needing EOD prices
Fetching EOD prices for 80 unique stocks
  RELIANCE: ₹2468.90  (actual closing!)
  TCS: ₹3655.00  (actual closing!)
  ...
✓ Updated 200 alerts with EOD HISTORICAL prices
✓ Marked 200 alerts as 'Complete'
```

**Time**: ~10 seconds per date

---

## Step 6: Verify Correct Data

Open Excel to verify prices are now DIFFERENT:

```bash
open data/alerts/alert_tracking.xlsx
```

**Check a few rows**:

| Symbol | Date | Time | Alert Price | Price 2min | Price 10min | Price EOD | Status |
|--------|------|------|-------------|------------|-------------|-----------|--------|
| RELIANCE | 2025-11-10 | 09:30:15 | ₹2448.25 | ₹2450.50 | ₹2455.75 | ₹2468.90 | Complete |
| TCS | 2025-11-10 | 09:30:20 | ₹3652.00 | ₹3650.25 | ₹3648.50 | ₹3655.00 | Complete |

✅ **All three prices should be DIFFERENT**
✅ **Prices should reflect actual movement over time**
✅ **Status should be "Complete"**

---

## Verification Checklist

Run through this checklist to ensure everything is fixed:

### Before Fix
- [ ] All prices are the same (₹2470.00, ₹2470.00, ₹2470.00)
- [ ] Status is "Complete" or "Partial" with wrong data
- [ ] Color coding doesn't make sense

### After Reset
- [ ] All price columns are EMPTY
- [ ] Status is "Pending"
- [ ] No color formatting

### After Repopulate
- [ ] Price 2min has values from 2 mins after alert
- [ ] Price 10min has DIFFERENT values from 10 mins after alert
- [ ] Price EOD has DIFFERENT values (closing prices)
- [ ] Status is "Complete"
- [ ] Color coding makes sense (green = good, red = bad)

---

## Troubleshooting

### Issue 1: Reset Script Says "0 alerts reset"

**Cause**: Excel file is open in Excel (file locking)

**Fix**: Close Excel and run reset again

---

### Issue 2: V2 Scripts Get Same Prices Again

**Possible causes**:

#### A. Running too soon after alerts
If you run the updates immediately, live price and 2-min price will be similar.

**Fix**: Wait 10+ minutes after alerts before running updates

#### B. Using old scripts by mistake
Check you're using V2 scripts, not old ones.

**Fix**: Verify script names:
```bash
ls -l update_*_v2.py
```

Should show:
- `update_alert_prices_v2.py`
- `update_eod_prices_v2.py`

#### C. Historical data not available
For very old alerts, historical data might be unavailable.

**Fix**: Check logs for errors:
```bash
tail -50 logs/alert_excel_updates.log
```

---

### Issue 3: "Instrument token not found"

**Cause**: Symbol is delisted or misspelled

**Fix**: Check symbol name in Excel. If delisted, manually mark as Complete.

---

### Issue 4: "No candle data returned"

**Cause**: Trying to fetch data for weekends/holidays

**Fix**: Historical data is not available for non-trading days. This is expected.

---

### Issue 5: API Rate Limiting Errors

**Error**: `Too many requests`

**Fix**: Scripts already have 0.1s delays. If you still hit limits, increase delay:

Edit `update_alert_prices_v2.py` line ~217:
```python
time.sleep(0.2)  # Changed from 0.1 to 0.2
```

---

## Complete Command Sequence

Here's the entire process in order:

```bash
# 0. Check current status
./venv/bin/python3 reset_alert_prices.py --summary

# 1. Reset all wrong data
./venv/bin/python3 reset_alert_prices.py --all
# Type "yes" when prompted

# 2. Verify reset worked
./venv/bin/python3 reset_alert_prices.py --summary
# Should show all Pending

# 3. Refresh API token
./generate_kite_token.py

# 4. Update 2-min prices
./venv/bin/python3 update_alert_prices_v2.py --2min

# 5. Update 10-min prices
./venv/bin/python3 update_alert_prices_v2.py --10min

# 6. Update EOD prices for each date
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-10
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-11
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-12

# 7. Verify in Excel
open data/alerts/alert_tracking.xlsx
```

**Total time**: ~2-3 minutes for 273 alerts

---

## What Each Script Does

### reset_alert_prices.py
```
Action: Clear wrong data
Input: Excel file with wrong prices
Output: Empty price columns, Status = "Pending"
Time: <1 second
```

### update_alert_prices_v2.py --2min
```
Action: Fetch 2-min historical prices
Input: Alerts with empty "Price 2min"
API Calls: 273 (one per alert)
Output: Price 2min filled, Status = "Partial"
Time: ~30 seconds
```

### update_alert_prices_v2.py --10min
```
Action: Fetch 10-min historical prices
Input: Alerts with empty "Price 10min"
API Calls: 273 (one per alert)
Output: Price 10min filled, Status = "Partial"
Time: ~30 seconds
```

### update_eod_prices_v2.py --date
```
Action: Fetch EOD closing prices
Input: Alerts from specific date with empty "Price EOD"
API Calls: ~80 (one per unique symbol)
Output: Price EOD filled, Status = "Complete"
Time: ~10 seconds per date
```

---

## Files Involved

### Scripts
- `reset_alert_prices.py` - Clear wrong data
- `update_alert_prices_v2.py` - Populate correct 2-min/10-min prices
- `update_eod_prices_v2.py` - Populate correct EOD prices

### Data Files
- `data/alerts/alert_tracking.xlsx` - Excel file with alerts
- `.env` - Kite API credentials

### Logs
- `logs/alert_excel_updates.log` - All update operations

---

## Understanding the Fix

### Why Prices Were All the Same

**Old scripts** (buggy):
```python
# At 3:00 PM - Run 2-min updater
current_price = kite.quote("RELIANCE")['last_price']  # ₹2470.00

# At 3:01 PM - Run 10-min updater
current_price = kite.quote("RELIANCE")['last_price']  # ₹2470.50

# At 3:30 PM - Run EOD updater
current_price = kite.quote("RELIANCE")['last_price']  # ₹2468.90

# All prices within 30 minutes → nearly identical!
```

### Why New Prices Are Different

**New scripts** (fixed):
```python
# For alert at 09:30:15

# 2-min updater
target = alert_time + 2min = 09:32:15
candles = kite.historical_data(from=09:27, to=09:37, interval="minute")
price_2min = candles[09:32]['close']  # ₹2450.50 (actual price at 09:32!)

# 10-min updater
target = alert_time + 10min = 09:40:15
candles = kite.historical_data(from=09:35, to=09:45, interval="minute")
price_10min = candles[09:40]['close']  # ₹2455.75 (actual price at 09:40!)

# EOD updater
target_date = 2025-11-10
candles = kite.historical_data(from=2025-11-09, to=2025-11-11, interval="day")
price_eod = candles[2025-11-10]['close']  # ₹2468.90 (actual closing!)

# Each price from different time → correctly different!
```

---

## Summary

### Problem
✗ Excel filled with wrong data (all same prices)
✗ Status marked Complete/Partial, blocking updates
✗ Update scripts skip rows with data

### Solution
1. ✓ Reset: Clear wrong data, set Status to "Pending"
2. ✓ Refresh: Get new API token
3. ✓ Repopulate: Run V2 scripts with historical data API

### Result
✓ Price 2min: Actual price 2 minutes after alert
✓ Price 10min: Actual price 10 minutes after alert
✓ Price EOD: Actual closing price from that day
✓ All three prices DIFFERENT (reflecting real movement)
✓ Status properly managed (Pending → Partial → Complete)

### Time Required
- Reset: <1 second
- Repopulate: ~2-3 minutes total
- Manual verification: 1 minute

**Total: ~5 minutes to fix all 273 alerts**
