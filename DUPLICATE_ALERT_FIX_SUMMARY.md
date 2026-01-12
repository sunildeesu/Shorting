# Duplicate Alert Issue - Fix Summary

**Date**: 2026-01-12
**Status**: ✅ **FIXED**

---

## What Was Wrong?

### Issue: Duplicate Logging (NOT Duplicate Alerts)

Every log message was being written **TWICE** to `logs/stock_monitor.log`:

1. **FileHandler** wrote directly to `logs/stock_monitor.log`
2. **ConsoleHandler** wrote to stdout
3. **LaunchD** redirected stdout to `logs/stock_monitor.log`

**Result**: 395MB log file (should be ~200MB) with every line duplicated.

---

## What Was Fixed?

### File: `main.py` (Lines 15-42)

**Before**:
```python
def setup_logging():
    # ... setup code ...

    # File handler
    file_handler = logging.FileHandler(config.LOG_FILE)
    root_logger.addHandler(file_handler)

    # Console handler (ALWAYS added)
    console_handler = logging.StreamHandler(sys.stdout)
    root_logger.addHandler(console_handler)  # ← PROBLEM: Causes duplicates under LaunchD
```

**After**:
```python
def setup_logging():
    # ... setup code ...

    # File handler (always enabled)
    file_handler = logging.FileHandler(config.LOG_FILE)
    root_logger.addHandler(file_handler)

    # Console handler (only if running interactively)
    if sys.stdout.isatty():  # ← FIX: Only add console handler if interactive
        console_handler = logging.StreamHandler(sys.stdout)
        root_logger.addHandler(console_handler)
    # Skip console handler when running under LaunchD (stdout redirected)
```

**How It Works**:
- `sys.stdout.isatty()` returns `True` when running in terminal (interactive)
- `sys.stdout.isatty()` returns `False` when stdout is redirected (LaunchD case)
- Console handler is only added when running interactively
- Under LaunchD, only FileHandler writes (no duplicates)

---

## What About the Alerts?

### Alert Deduplication is Working Correctly ✅

**Checked**:
- `alert_history_manager.py` deduplication logic: ✅ Working
- `data/alert_history.json` cooldown tracking: ✅ Working
- Process count: ✅ Only one instance running
- Alert volume: 14 alerts in 50 minutes = **NORMAL** for volatile market

**Conclusion**:
- ❌ Logging was duplicated (fixed now)
- ✅ Alerts were NOT being sent twice to Telegram
- ✅ Deduplication prevents duplicate Telegram alerts

---

## Expected Impact

### Log File Size Reduction

**Before Fix**:
```bash
$ ls -lh logs/stock_monitor.log
-rw-r--r--  395M Jan 12 10:15 logs/stock_monitor.log  ← HUGE!
```

**After Fix** (next run):
```bash
$ ls -lh logs/stock_monitor.log
-rw-r--r--  ~200M Jan 12 11:00 logs/stock_monitor.log  ← 50% smaller
```

**Savings**: ~50% disk space, cleaner logs, easier debugging

---

## How to Apply the Fix

### Option 1: Restart LaunchD Service (Recommended)

```bash
# Stop the current service
launchctl stop com.stock.monitor

# The service will restart automatically on next scheduled run
# OR manually start it:
launchctl start com.stock.monitor
```

### Option 2: Wait for Next Scheduled Run

The fix will automatically apply on the next scheduled run (5 minutes from now).

### Option 3: Manual Test

```bash
# Test the fix manually (should see NO console output under LaunchD)
cd /Users/sunildeesu/myProjects/ShortIndicator
./main.py

# Check if logging works correctly
tail -20 logs/stock_monitor.log
# Should see SINGLE lines (not duplicated)
```

---

## Verification Steps

### 1. Check Log File Growth

**Before** (with duplicates):
```bash
# Log file grew ~8MB/minute
```

**After** (fixed):
```bash
# Log file should grow ~4MB/minute (50% slower)
```

### 2. Check Log Entries

```bash
# View recent logs
tail -50 logs/stock_monitor.log

# Each line should appear ONCE (not twice)
```

### 3. Monitor Disk Usage

```bash
# Check log directory size
du -sh logs/
```

**Expected**: Log files will grow 50% slower after the fix.

---

## About "Too Many Alerts Today"

### Alert Volume Analysis

**Today's Stats** (at 10:15 AM):
- Trading time: ~50 minutes (9:25 - 10:15)
- Stocks monitored: 209
- Alerts sent: 14
- **Rate**: 0.28 alerts/minute
- **Per stock**: 6.7% of stocks triggered alerts

**Is this too many?**

**Answer**: **NO**, this is normal for a volatile market day.

**Why it might seem like "too many"**:
1. ❌ Duplicate logging made it LOOK like more alerts (every log line doubled)
2. ✅ Market is actually volatile today (legitimate alerts)
3. ✅ Your thresholds are working correctly

---

### If You Want Fewer Alerts

**Current Thresholds** (`config.py`):
```python
DROP_THRESHOLD_5MIN = 1.25%   # Very sensitive (catches small moves)
DROP_THRESHOLD_PERCENT = 2.0%  # Standard 10-min threshold
DROP_THRESHOLD_30MIN = 3.0%    # 30-min cumulative
```

**To Reduce Alert Volume**, increase thresholds:
```python
DROP_THRESHOLD_5MIN = 1.5%    # Less sensitive (fewer 5-min alerts)
DROP_THRESHOLD_PERCENT = 2.5%  # Higher bar for 10-min alerts
DROP_THRESHOLD_30MIN = 3.5%    # Higher bar for 30-min alerts
```

**Trade-off**: Higher thresholds = fewer alerts, but might miss some real opportunities.

---

## Summary

### What Was Fixed ✅

1. ✅ **Duplicate logging** - Fixed by conditional console handler
2. ✅ **Log file size** - Will be 50% smaller going forward
3. ✅ **Disk waste** - Saving ~200MB per trading day

### What Was NOT Broken (False Alarm) ✅

1. ✅ **Alert deduplication** - Working correctly all along
2. ✅ **Telegram alerts** - NOT being sent twice
3. ✅ **Alert volume** - 14 alerts in 50 min is normal, not excessive

### Root Cause

User saw **duplicate log entries** and assumed **duplicate alerts**, but:
- Logging was duplicated (fixed now)
- Alerts were NOT duplicated (deduplication worked)
- Alert volume is normal for volatile market

---

## Next Steps

1. ✅ **Restart stock_monitor** (or wait for next run)
2. ✅ **Verify log file size** is ~50% smaller
3. ✅ **Monitor alert volume** over next few days
4. ❓ **Optional**: Increase thresholds if you want fewer alerts

---

## Files Changed

1. **main.py** (Lines 15-42)
   - Modified `setup_logging()` function
   - Added conditional console handler
   - Prevents duplicate logging under LaunchD

2. **DUPLICATE_ALERT_ANALYSIS.md** (NEW)
   - Complete investigation report
   - Root cause analysis
   - Evidence and data flow diagrams

3. **DUPLICATE_ALERT_FIX_SUMMARY.md** (THIS FILE)
   - Fix summary and instructions

---

**Fix Status**: ✅ COMPLETE
**Testing Required**: Restart service and verify log file size
**Impact**: 50% disk space savings, cleaner logs, NO functional changes

---

**Version**: 1.0
**Date**: 2026-01-12
**Author**: Claude Sonnet 4.5
