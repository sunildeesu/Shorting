# ATR Breakout Monitor - Automation Guide

**Status:** ✅ ACTIVE - Running every 30 minutes during market hours

---

## 📅 Schedule

The ATR breakout monitor runs automatically:

**Frequency:** Every 30 minutes
**Days:** Monday - Friday (trading days only)
**Time:** 9:30 AM - 3:00 PM IST

### Exact Run Times (12 runs per day):
```
9:30 AM   - Market open scan
10:00 AM  - Early morning scan
10:30 AM
11:00 AM
11:30 AM
12:00 PM  - Midday scan
12:30 PM
1:00 PM
1:30 PM
2:00 PM
2:30 PM
3:00 PM   - Pre-close scan (last run)
```

**Note:** Stops at 3:00 PM (30 minutes before market close at 3:30 PM)

---

## 🎯 What Happens Automatically

Every 30 minutes:

1. **Scans 191 F&O stocks** for ATR breakout signals
2. **Uses unified cache** (shares data with stock_monitor if running)
3. **Sends Telegram alerts** when breakouts detected
4. **Logs to Excel** at `data/alerts/alert_tracking.xlsx`
5. **Friday exit reminder** (if enabled)

### Expected API Usage

- **Per run:** ~4-54 API calls (4 if cache hit, 54 if cache miss)
- **Per day:** ~300-600 calls (12 runs × 25-50 calls average)
- **Cache benefit:** Saves 4 calls/run when stock_monitor runs within 60s

---

## 📊 Monitoring the Automation

### Check if it's running:
```bash
launchctl list | grep com.nse.atr.monitor
```

**Output:**
- First column `-` = Not currently running (waiting for next scheduled time)
- Second column `0` = Last exit code (0 = success)
- Third column = Job name

### View logs:
```bash
# Standard output (scan results)
tail -f logs/atr-monitor-stdout.log

# Errors (if any)
tail -f logs/atr-monitor-stderr.log

# View last run
tail -100 logs/atr-monitor-stdout.log
```

### Check next scheduled run:
```bash
# Currently running jobs
launchctl list | grep com.nse

# Or check system log
log show --predicate 'subsystem == "com.apple.launchd"' --last 1h | grep atr
```

---

## 🎛️ Managing the Automation

### Stop (disable) the automation:
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.atr.monitor.plist
```

### Start (re-enable) the automation:
```bash
launchctl load ~/Library/LaunchAgents/com.nse.atr.monitor.plist
```

### Restart after changes:
```bash
# Unload, make changes, then reload
launchctl unload ~/Library/LaunchAgents/com.nse.atr.monitor.plist

# Make your changes to the plist file, then:
cp com.nse.atr.monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.nse.atr.monitor.plist
```

### Check status:
```bash
launchctl list | grep atr
```

### Manual run (anytime):
```bash
# Run manually without waiting for schedule
./atr_breakout_monitor.py
```

---

## ⚙️ Configuration

### Change run frequency:

**To run every 15 minutes instead:**
You'd need to add more time entries in the plist file (24 runs/day).

**To run every hour instead:**
Remove half the time entries (6 runs/day: 9:30, 10:30, 11:30, 12:30, 1:30, 2:30).

### Adjust ATR parameters:

Edit `.env` file:
```bash
# ATR Strategy
ATR_ENTRY_MULTIPLIER=2.5     # Lower = more signals
ATR_STOP_MULTIPLIER=0.5      # Higher = wider stops
ATR_MIN_VOLUME=50            # Lower = more candidates

# Filters
ATR_FILTER_CONTRACTION=true  # Set false to disable volatility filter
ENABLE_ATR_ALERTS=true       # Set false to disable Telegram alerts
```

After changing `.env`, the automation will use new settings on next run (no restart needed).

---

## 📧 Notifications

### Telegram Alerts

**When you'll receive alerts:**
- ATR breakout detected (price crosses entry level)
- Volatility filter passed (ATR(20) < ATR(30))
- Once per stock per day (no spam)

**Alert includes:**
- Entry level, current price, stop loss
- ATR analysis and volatility status
- Risk management details (R:R ratio)
- Market cap and volume

### Friday Exit Reminder

If `ATR_FRIDAY_EXIT=true`, you'll receive a reminder to close positions on Fridays.

---

## 🔍 Troubleshooting

### Automation not running?

**1. Check if loaded:**
```bash
launchctl list | grep atr
```
If not listed, load it:
```bash
launchctl load ~/Library/LaunchAgents/com.nse.atr.monitor.plist
```

**2. Check logs for errors:**
```bash
tail -50 logs/atr-monitor-stderr.log
```

**3. Verify Kite token is valid:**
```bash
# Generate fresh token
./venv/bin/python3 generate_kite_token.py
```

**4. Test manual run:**
```bash
./atr_breakout_monitor.py
```
If manual works but automation doesn't, check permissions on log files.

---

### Logs not being created?

```bash
# Create logs directory if missing
mkdir -p logs

# Set proper permissions
chmod 755 logs
```

---

### Getting too many/few alerts?

**Too many alerts:**
- Increase `ATR_ENTRY_MULTIPLIER` (e.g., from 2.5 to 3.0)
- Increase `ATR_MIN_VOLUME` (e.g., from 50 to 100)
- Enable `ATR_FILTER_CONTRACTION=true`

**Too few alerts:**
- Decrease `ATR_ENTRY_MULTIPLIER` (e.g., from 2.5 to 2.0)
- Decrease `ATR_MIN_VOLUME` (e.g., from 50 to 30)
- Disable `ATR_FILTER_CONTRACTION=false`

---

### Want to pause temporarily?

```bash
# Stop automation
launchctl unload ~/Library/LaunchAgents/com.nse.atr.monitor.plist

# Can still run manually when needed
./atr_breakout_monitor.py

# Resume automation later
launchctl load ~/Library/LaunchAgents/com.nse.atr.monitor.plist
```

---

## 📈 Performance & Cost

### API Usage

**Per day (automated):**
- 12 runs × ~25-50 calls = 300-600 API calls
- With cache sharing: ~200-400 calls (stock_monitor shares quotes)

**Kite limits:**
- Quote API: 3 requests/second
- Historical API: 3 requests/second
- We use 0.4s delay (well within limits)

### Cache Benefits

**Unified cache automatically:**
- Saves 4 calls when stock_monitor runs within 60s
- Reuses historical data from previous runs (24h cache)
- Reduces daily API usage by ~100-200 calls

### Excel Log Size

The Excel log grows by ~3-10 rows per day (depends on breakouts found).
- Average: 5 rows/day
- Monthly: ~100-150 rows
- Yearly: ~1,200-1,800 rows

Clean up periodically:
```bash
# Backup and clear Excel log
cp data/alerts/alert_tracking.xlsx data/alerts/alert_tracking_backup_$(date +%Y%m%d).xlsx
```

---

## 🚀 Quick Commands Reference

```bash
# Check status
launchctl list | grep atr

# View live logs
tail -f logs/atr-monitor-stdout.log

# Stop automation
launchctl unload ~/Library/LaunchAgents/com.nse.atr.monitor.plist

# Start automation
launchctl load ~/Library/LaunchAgents/com.nse.atr.monitor.plist

# Manual run
./atr_breakout_monitor.py

# View last scan results
tail -200 logs/atr-monitor-stdout.log | grep "FINAL SUMMARY" -A 20

# Check for breakouts found today
tail -1000 logs/atr-monitor-stdout.log | grep "ATR BREAKOUT DETECTED"
```

---

## 📋 Current Setup Summary

**Status:** ✅ Active
**Schedule:** Every 30 minutes (9:30 AM - 3:00 PM, Mon-Fri)
**Runs per day:** 12
**API calls per day:** ~300-600
**Alerts:** Telegram + Excel
**Cache:** Enabled (unified with stock_monitor)
**Friday exit:** Enabled

**Log files:**
- `logs/atr-monitor-stdout.log` (scan results)
- `logs/atr-monitor-stderr.log` (errors)

**Excel log:**
- `data/alerts/alert_tracking.xlsx` (ATR_Breakout_alerts sheet)

**Config file:**
- `.env` (ATR parameters, API keys)

---

## 📚 Related Guides

- **ATR Strategy Details:** See `atr_breakout_monitor.py` header comments
- **Unified Cache System:** See `UNIFIED_CACHE_INTEGRATION_SUMMARY.md`
- **Alert Tracking:** See `ALERT_TRACKING_GUIDE.md`

---

**Automation setup:** 2025-11-12
**Last updated:** 2025-11-12
**Status:** Production ready ✅
