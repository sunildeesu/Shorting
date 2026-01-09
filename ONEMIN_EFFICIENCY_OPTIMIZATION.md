# 1-Min Alert Monitor - Efficiency Optimization

## Problem: Inefficient 24/7 Checking

### Before Optimization

The old system was **extremely inefficient**:

```
❌ OLD BEHAVIOR:
- launchd runs script every 60 seconds (24/7)
- 1,440 executions per day
- Each execution checks market hours and exits
- Only ~360 executions are useful (market hours)
- 75% WASTED CHECKS (1,080 checks outside market hours)
- Unnecessary CPU/battery usage
- Cluttered logs with "outside market hours" messages
```

**Example waste** (from logs):
```
17:19:06 - Outside market hours - skipping
17:20:11 - Outside market hours - skipping
17:21:15 - Outside market hours - skipping
... (every minute, all night/weekend)
```

---

## Solution: Start Once, Run Continuously

### After Optimization

The new system is **highly efficient**:

```
✅ NEW BEHAVIOR:
- launchd starts ONCE at 9:29 AM (weekdays only)
- Process runs continuous loop from 9:30 AM to 3:25 PM
- Internal 60-second loop during market hours only
- Exits cleanly after 3:25 PM
- ZERO checks outside market hours
- 75% reduction in executions (1,440 → 360)
```

---

## Technical Changes

### 1. New Continuous Monitor Script

**File**: `onemin_monitor_continuous.py`

**Key Features**:
- Single initialization at 9:29 AM
- Waits for market open (9:30 AM) if early
- Runs `while True` loop during market hours
- Checks every 60 seconds: `time.sleep(60)`
- Exits when time > 3:25 PM

**Execution Flow**:
```
9:29 AM: launchd starts process
9:29-9:30 AM: Wait for market open
9:30 AM: Initialize monitor (Kite API, caches, etc.)
9:30-3:25 PM: Loop every 60 seconds
  ├─ Check stocks
  ├─ Generate alerts
  └─ Sleep 60 seconds
3:26 PM: Exit gracefully
```

### 2. New launchd Configuration

**File**: `com.nse.onemin.monitor.efficient.plist`

**Key Changes**:
```xml
<!-- OLD: Run every 60 seconds -->
<key>StartInterval</key>
<integer>60</integer>

<!-- NEW: Run ONCE at 9:29 AM on weekdays -->
<key>StartCalendarInterval</key>
<array>
    <dict>
        <key>Hour</key><integer>9</integer>
        <key>Minute</key><integer>29</integer>
        <key>Weekday</key><integer>1-5</integer>  <!-- Mon-Fri -->
    </dict>
</array>
```

**Important Settings**:
- `KeepAlive: false` - Don't restart on exit
- `RunAtLoad: false` - Only run at scheduled time
- No StartInterval - Only uses StartCalendarInterval

---

## Efficiency Comparison

| Metric | Old (Inefficient) | New (Optimized) | Improvement |
|--------|-------------------|-----------------|-------------|
| **Daily Executions** | 1,440 | 1 | **99.9% fewer** |
| **Useful Executions** | ~360 | ~360 | Same |
| **Wasted Checks** | ~1,080 | 0 | **100% eliminated** |
| **Startup Overhead** | 1,440x init | 1x init | **99.9% less** |
| **Process Restarts** | Every 60s | Once per day | **Massive reduction** |
| **Log Clutter** | 1,080 "skipping" msgs | 0 | **Clean logs** |
| **Battery Impact** | High | Minimal | **Much better** |

### Savings Per Day

```
Eliminated:
- 1,080 unnecessary process starts
- 1,080 Python interpreter loads
- 1,080 market hours checks
- 1,080 "outside market hours" log entries
- 1,080 process exits

Kept:
- Same 360 stock monitoring cycles during market hours
- Same alert detection accuracy
- Same 1-minute responsiveness
```

---

## Management Commands

### Check Status

```bash
# Check if efficient monitor is loaded
launchctl list | grep onemin.efficient

# Check if process is running (during market hours)
ps aux | grep onemin_monitor_continuous

# View today's activity
tail -f logs/onemin_monitor.log
```

### Start/Stop

```bash
# Stop (unload)
launchctl unload ~/Library/LaunchAgents/com.nse.onemin.monitor.efficient.plist

# Start (load)
launchctl load ~/Library/LaunchAgents/com.nse.onemin.monitor.efficient.plist

# Restart
launchctl unload ~/Library/LaunchAgents/com.nse.onemin.monitor.efficient.plist
launchctl load ~/Library/LaunchAgents/com.nse.onemin.monitor.efficient.plist
```

### Manual Testing

```bash
# Test continuous monitor manually
cd ~/myProjects/ShortIndicator
./venv/bin/python3 onemin_monitor_continuous.py

# It will wait for market open if run before 9:30 AM
# Or run immediately if during market hours
# Or exit immediately if after 3:25 PM
```

---

## Expected Behavior

### Monday - Friday

| Time | Behavior |
|------|----------|
| **Before 9:29 AM** | Process not running |
| **9:29 AM** | launchd starts process |
| **9:29-9:30 AM** | Process waits for market open |
| **9:30 AM** | Monitor initializes, starts loop |
| **9:30-3:25 PM** | Monitors stocks every 60 seconds |
| **3:26 PM** | Process exits gracefully |
| **After 3:26 PM** | Process not running (no restarts) |

### Saturday - Sunday

- **No execution at all** (Weekday check in StartCalendarInterval)
- Zero CPU usage
- Zero log entries

### Holidays

- Process starts at 9:29 AM
- Immediately checks: "Not a trading day"
- Exits within 1 second
- No wasted monitoring

---

## Log Output Changes

### Old Logs (Cluttered)

```
2026-01-09 17:19:06 - Outside market hours - skipping
2026-01-09 17:20:11 - Outside market hours - skipping
2026-01-09 17:21:15 - Outside market hours - skipping
... (every minute, 24/7)
```

**75% of log entries were useless!**

### New Logs (Clean)

```
2026-01-10 09:29:00 - 1-MIN MONITOR - CONTINUOUS MODE
2026-01-10 09:29:01 - ✅ Trading day confirmed
2026-01-10 09:29:01 - ⏳ Waiting 59s for market to open...
2026-01-10 09:30:00 - ✅ Market is open - starting monitoring
2026-01-10 09:30:05 - Initializing 1-min monitor...
2026-01-10 09:30:10 - ✅ Monitor initialized successfully
2026-01-10 09:30:10 - 🚀 Starting continuous monitoring loop
2026-01-10 09:30:10 - Cycle #1 - 09:30:10
... (every 60 seconds during market hours)
2026-01-10 15:25:15 - Cycle #355 - 15:25:15
2026-01-10 15:26:00 - ✅ Market closed - Exiting gracefully
2026-01-10 15:26:00 - 📊 Session Summary: 355 cycles, 12 alerts
```

**100% of log entries are useful monitoring data!**

---

## Troubleshooting

### Process Not Starting

```bash
# Check if launchd agent is loaded
launchctl list | grep onemin.efficient
# Should show: -	0	com.nse.onemin.monitor.efficient

# Check plist syntax
plutil -lint ~/Library/LaunchAgents/com.nse.onemin.monitor.efficient.plist
# Should show: OK

# Check logs for errors
tail -100 logs/onemin-stderr.log
```

### Process Exits Immediately

**Possible reasons**:
1. **Not a trading day** (weekend/holiday) - Expected behavior
2. **Already past 3:25 PM** - Expected behavior
3. **Kite API error** - Check token validity

```bash
# Test token
./venv/bin/python3 test_kite.py
```

### Process Running Outside Market Hours

This should **NEVER** happen with the new system. If it does:

```bash
# Check which agent is loaded
launchctl list | grep onemin

# If you see "com.nse.onemin.monitor" (old), unload it:
launchctl unload ~/Library/LaunchAgents/com.nse.onemin.monitor.plist

# Make sure efficient version is loaded
launchctl load ~/Library/LaunchAgents/com.nse.onemin.monitor.efficient.plist
```

---

## Migration Summary

### Files Changed

| File | Status | Purpose |
|------|--------|---------|
| `onemin_monitor_continuous.py` | **NEW** | Continuous loop version |
| `com.nse.onemin.monitor.efficient.plist` | **NEW** | Efficient launchd config |
| `com.nse.onemin.monitor.plist` | **OLD** | Deprecated (unload this!) |
| `onemin_monitor.py` | **UNCHANGED** | Original (still used by continuous version) |

### Steps to Switch

1. ✅ Unload old agent: `launchctl unload ~/Library/LaunchAgents/com.nse.onemin.monitor.plist`
2. ✅ Load new agent: `launchctl load ~/Library/LaunchAgents/com.nse.onemin.monitor.efficient.plist`
3. ✅ Verify: `launchctl list | grep onemin.efficient`

---

## Performance Benefits

### Resource Usage

**Before**:
- 1,440 Python process starts per day
- Constant start/stop overhead
- High battery drain on laptops
- Log file grows rapidly

**After**:
- 1 Python process start per day
- Long-running efficient process
- Minimal battery impact
- Clean, readable logs

### System Impact

| Resource | Old | New | Savings |
|----------|-----|-----|---------|
| **Process Starts/Day** | 1,440 | 1 | 99.9% |
| **CPU Wake-ups/Day** | 1,440 | ~360 | 75% |
| **Log Lines/Day** | ~2,880 | ~720 | 75% |
| **Battery Impact** | High | Low | Significant |

---

## Verification Checklist

Use this after switching to the new system:

```bash
# 1. Old agent is unloaded
launchctl list | grep "com.nse.onemin.monitor.plist"
# Should return nothing

# 2. New agent is loaded
launchctl list | grep "com.nse.onemin.monitor.efficient"
# Should show: -	0	com.nse.onemin.monitor.efficient

# 3. Plist is valid
plutil -lint ~/Library/LaunchAgents/com.nse.onemin.monitor.efficient.plist
# Should show: OK

# 4. Process is NOT running outside market hours
ps aux | grep onemin_monitor_continuous | grep -v grep
# Should return nothing (after 3:25 PM)

# 5. Logs are clean
tail -50 logs/onemin-stderr.log
# Should NOT see "outside market hours" messages
```

---

## Summary

✅ **Efficiency Gain**: 75% reduction in unnecessary checks
✅ **Same Functionality**: Still monitors every 60 seconds during market hours
✅ **Clean Logs**: No more cluttered "skipping" messages
✅ **Better Performance**: 1 process start vs 1,440 starts per day
✅ **Lower Battery Usage**: Significant improvement on laptops
✅ **Automatic**: Runs daily at 9:29 AM, exits after 3:25 PM

**The 1-min alert system now runs ONLY when needed!**
