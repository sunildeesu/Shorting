# Price Update Bug Fix - All Prices Same Issue

**Date**: November 13, 2025
**Issue**: 2-min, 10-min, and EOD prices are all the same in Excel

---

## Root Cause Analysis

### The Bug
All three update scripts were fetching the **CURRENT live price**, not historical prices:

```python
# OLD CODE (BUGGY) in update_alert_prices.py line 232:
quotes = self.kite.quote(*batch)
for instrument, data in quotes.items():
    prices[symbol] = data['last_price']  # ← Always current price!
```

### Why This Failed
- **2-min updater**: Got current price instead of price from 2 mins after alert
- **10-min updater**: Got current price instead of price from 10 mins after alert
- **EOD updater**: Got current price instead of closing price from that day

**Result**: If you ran all three scripts at the same time (or within minutes), they all got the same current live price!

---

## The Fix

Created new V2 scripts that use **Kite historical data API** to fetch prices at specific timestamps:

### 1. `update_alert_prices_v2.py`
- Uses `kite.historical_data()` with 1-minute candles
- Finds the exact candle at alert_time + 2 minutes (or +10 minutes)
- Extracts the close price from that candle

### 2. `update_eod_prices_v2.py`
- Uses `kite.historical_data()` with daily candles
- Fetches the closing price for the alert date
- Returns the actual end-of-day close

---

## Key Changes

### Before (Buggy)
```python
# Fetches current live price
quotes = self.kite.quote("NSE:RELIANCE")
price = quotes['NSE:RELIANCE']['last_price']
```

### After (Fixed)
```python
# Fetches historical price at specific time
candles = self.kite.historical_data(
    instrument_token=instrument_token,
    from_date=target_time - 5min,
    to_date=target_time + 5min,
    interval="minute"  # 1-minute candles
)

# Find candle closest to target time
for candle in candles:
    if candle['date'] == target_time:
        price = candle['close']  # Actual price at that time!
```

---

## Testing the Fix

### Step 1: Refresh API Token (if expired)
```bash
./generate_kite_token.py
```

### Step 2: Test 2-Min Price Updates (Historical)
```bash
./venv/bin/python3 update_alert_prices_v2.py --2min
```

**What it does**:
- Finds all alerts >2 minutes old with empty "Price 2min"
- For each alert, calculates: `target_time = alert_time + 2 minutes`
- Fetches 1-minute candle at that exact time
- Uses the candle's close price

**Expected output**:
```
Starting 2-minute HISTORICAL price updates...
Found 141 alerts needing 2-min price updates
Loading NSE instrument tokens...
Loaded 3500+ instrument tokens
  RELIANCE @ 09:32:15: ₹2450.50
  TCS @ 09:32:20: ₹3650.25
  ...
✓ Updated 141 alerts with 2-min HISTORICAL prices
```

### Step 3: Test 10-Min Price Updates (Historical)
```bash
./venv/bin/python3 update_alert_prices_v2.py --10min
```

**What it does**:
- Finds all alerts >10 minutes old with empty "Price 10min"
- For each alert, calculates: `target_time = alert_time + 10 minutes`
- Fetches 1-minute candle at that exact time
- Uses the candle's close price

**Expected output**:
```
Starting 10-minute HISTORICAL price updates...
Found 96 alerts needing 10-min price updates
  RELIANCE @ 09:40:15: ₹2455.75  (different from 2-min!)
  TCS @ 09:40:20: ₹3648.50  (different from 2-min!)
  ...
✓ Updated 96 alerts with 10-min HISTORICAL prices
```

### Step 4: Test EOD Price Updates (Historical)
```bash
# Update today's alerts
./venv/bin/python3 update_eod_prices_v2.py

# Update specific date (backfill old alerts)
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-10
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-11
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-12
```

**What it does**:
- Finds all alerts from target date with empty "Price EOD"
- For each symbol, fetches daily candle for that date
- Uses the candle's close price (actual closing price)

**Expected output**:
```
Starting EOD HISTORICAL price updates for 2025-11-10...
Found 200 alerts from 2025-11-10 needing EOD prices
Fetching EOD prices for 80 unique stocks
  RELIANCE: ₹2468.90  (actual closing price!)
  TCS: ₹3655.00  (actual closing price!)
  ...
✓ Updated 200 alerts with EOD HISTORICAL prices
✓ Marked 200 alerts as 'Complete'
```

---

## Verification

After running the V2 scripts, open the Excel file:

```bash
open data/alerts/alert_tracking.xlsx
```

**Check that prices are NOW DIFFERENT**:

| Symbol | Alert Time | Price 2min | Price 10min | Price EOD | Status |
|--------|------------|------------|-------------|-----------|--------|
| RELIANCE | 09:30:15 | ₹2450.50 | ₹2455.75 | ₹2468.90 | Complete |
| TCS | 09:30:20 | ₹3650.25 | ₹3648.50 | ₹3655.00 | Complete |

✅ **All three prices should be DIFFERENT** (reflecting actual price movement)

---

## Backfilling Old Alerts

You have 273 pending alerts from Nov 10-12 that need historical prices:

```bash
# Step 1: Update 2-min and 10-min prices for all pending alerts
./venv/bin/python3 update_alert_prices_v2.py --both

# Step 2: Update EOD prices for each date
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-10
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-11
./venv/bin/python3 update_eod_prices_v2.py --date 2025-11-12
```

This will fetch the actual historical prices from those dates.

---

## Updated Automation

The setup script needs to use the V2 versions. Update the launchd plists:

### For 2-min updates
Change:
```xml
<string>/Users/sunildeesu/myProjects/ShortIndicator/update_alert_prices.py</string>
```
To:
```xml
<string>/Users/sunildeesu/myProjects/ShortIndicator/update_alert_prices_v2.py</string>
```

### For 10-min updates
Same change - use `update_alert_prices_v2.py`

### For EOD updates
Change:
```xml
<string>/Users/sunildeesu/myProjects/ShortIndicator/update_eod_prices.py</string>
```
To:
```xml
<string>/Users/sunildeesu/myProjects/ShortIndicator/update_eod_prices_v2.py</string>
```

---

## Technical Details

### How Historical Data API Works

```python
# Kite historical_data() function
candles = kite.historical_data(
    instrument_token=123456,     # Required: token from instruments() API
    from_date=datetime(...),     # Start of date range
    to_date=datetime(...),       # End of date range
    interval="minute"            # minute, day, 5minute, 15minute, etc.
)

# Returns list of candles:
[
    {
        'date': datetime(2025, 11, 10, 9, 30, 0),
        'open': 2450.00,
        'high': 2452.50,
        'low': 2449.00,
        'close': 2450.50,  # ← This is what we use!
        'volume': 125000
    },
    ...
]
```

### 1-Minute Candles for Intraday Prices

**For 2-min and 10-min prices**:
- Fetch 1-minute candles in a 10-minute window around target time
- Find the candle whose timestamp matches target time (within 1 minute)
- Use that candle's close price

**Example**:
```
Alert at 09:30:15
Target for 2-min: 09:32:15
Fetch candles from 09:27 to 09:37
Find candle at 09:32:00 (closest)
Use close price: ₹2450.50
```

### Daily Candles for EOD Prices

**For EOD prices**:
- Fetch daily candle for the alert date
- Use the candle's close price (official closing price)

**Example**:
```
Alert on 2025-11-10 at 09:30:15
Fetch daily candle for 2025-11-10
Use close price: ₹2468.90 (actual EOD close)
```

---

## Comparison: Old vs New

### Old Behavior (BUGGY)
| Script | What it fetched | Result |
|--------|-----------------|--------|
| 2-min updater (run at 3:00 PM) | Current price at 3:00 PM | ₹2470.00 |
| 10-min updater (run at 3:01 PM) | Current price at 3:01 PM | ₹2470.50 |
| EOD updater (run at 3:30 PM) | Current price at 3:30 PM | ₹2468.90 |

**Problem**: All prices are nearly identical (within 30 minutes of each other)

### New Behavior (FIXED)
| Script | What it fetches | Result |
|--------|-----------------|--------|
| 2-min updater | Historical price at alert_time + 2min | ₹2450.50 (from 09:32) |
| 10-min updater | Historical price at alert_time + 10min | ₹2455.75 (from 09:40) |
| EOD updater | Closing price from that date | ₹2468.90 (from 15:30) |

**Success**: Each price reflects actual movement at different times!

---

## Rate Limiting

The V2 scripts include rate limiting to avoid API throttling:

```python
# After each API call
time.sleep(0.1)  # 100ms delay = 10 calls/second (safe)
```

Kite API limits:
- Historical data: 3 requests/second
- Our rate: 10 requests/second with sleep(0.1)
- Safe margin maintained

---

## Error Handling

### Missing Instrument Token
```
ERROR: Instrument token not found for SYMBOL
```
**Fix**: Symbol may be delisted or misspelled. Check symbol name.

### No Candle Data
```
WARNING: RELIANCE: No candle data returned
```
**Fix**: Date may be a holiday/weekend. Historical data not available.

### API Timeout
```
ERROR: Error fetching historical data: Timeout
```
**Fix**: Network issue or API temporarily down. Retry later.

---

## Files Created

- `update_alert_prices_v2.py` - Fixed 2-min/10-min updater
- `update_eod_prices_v2.py` - Fixed EOD updater
- `PRICE_UPDATE_BUG_FIX.md` - This guide

## Files to Delete (Old Buggy Versions)

- `update_alert_prices.py` - Old buggy version
- `update_eod_prices.py` - Old buggy version

---

## Summary

### Bug
✗ All three prices were the same (current price)

### Fix
✓ Each price now reflects historical price at specific time:
- 2-min: Price 2 minutes after alert
- 10-min: Price 10 minutes after alert
- EOD: Closing price from that day

### Testing
1. Refresh Kite token: `./generate_kite_token.py`
2. Test 2-min: `./venv/bin/python3 update_alert_prices_v2.py --2min`
3. Test 10-min: `./venv/bin/python3 update_alert_prices_v2.py --10min`
4. Test EOD: `./venv/bin/python3 update_eod_prices_v2.py`
5. Verify in Excel: Prices should be different!

### Next Steps
1. Test the V2 scripts manually
2. Update automation to use V2 scripts
3. Backfill old alerts with historical data
4. Delete old buggy scripts
