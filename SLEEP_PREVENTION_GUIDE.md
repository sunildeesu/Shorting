# Sleep Prevention System for Market Hour Monitoring

## Problem
macOS cron jobs and LaunchAgents don't run when the system is asleep. This causes monitoring scripts to miss alerts during market hours if your Mac goes to sleep.

## Solution
Automated sleep prevention using `caffeinate` that runs during market hours (9:00 AM - 4:00 PM) **on trading days only** (excludes weekends AND NSE holidays).

---

## How It Works

A LaunchAgent (`com.nse.prevent.sleep.plist`) runs a wrapper script at 9:00 AM every weekday that:
1. Checks if it's a trading day using `market_utils.is_trading_day()` (checks NSE holiday calendar)
2. If it's a **trading day**: Starts `caffeinate` and keeps your Mac awake for 7 hours
3. If it's a **holiday/weekend**: Exits immediately without starting caffeinate

**What caffeinate does:**
- `-d`: Prevents display from sleeping
- `-i`: Prevents system from idle sleeping
- `-s`: Prevents sleep when on AC power

**Schedule:**
- Trigger: 9:00 AM (Mon-Fri)
- Holiday Check: Uses NSE holiday calendar from `market_utils.py`
- Duration: 7 hours (9:00 AM - 4:00 PM) on trading days only
- Auto-restarts: If crashed during market hours
- **Skips**: Weekends and NSE market holidays

---

## Check if Sleep Prevention is Active

### 1. Check if LaunchAgent is loaded
```bash
launchctl list | grep com.nse.prevent.sleep
```
**Expected output:**
```
-	0	com.nse.prevent.sleep
```
(0 = success, agent is loaded)

### 2. Check if caffeinate is running (during market hours)
```bash
ps aux | grep caffeinate | grep -v grep
```
**Expected output (if running):**
```
sunildeesu  12345   0.0  0.0  caffeinate -dis
```

### 3. Check if today was detected as trading day
```bash
tail -20 logs/caffeinate-control.log
```
**Expected output (on trading day):**
```
2025-12-24 09:00:05 - Trading day confirmed - starting caffeinate
```
**Expected output (on holiday/weekend):**
```
2025-12-24 09:00:05 - Not a trading day (weekend or NSE holiday) - caffeinate will NOT start
```

### 4. Check caffeinate logs
```bash
tail -20 logs/caffeinate-stdout.log
tail -20 logs/caffeinate-stderr.log
```

---

## Manual Control

### Start sleep prevention manually (outside market hours)
```bash
# Run until manually stopped (Ctrl+C)
caffeinate -dis

# Run for specific duration (e.g., 2 hours = 7200 seconds)
caffeinate -dis -t 7200
```

### Stop sleep prevention
```bash
# Find caffeinate process
ps aux | grep caffeinate | grep -v grep

# Kill the process (replace PID with actual number)
kill <PID>
```

### Reload the LaunchAgent (after config changes)
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.prevent.sleep.plist
launchctl load ~/Library/LaunchAgents/com.nse.prevent.sleep.plist
```

### Disable automatic sleep prevention
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.prevent.sleep.plist
```

### Re-enable automatic sleep prevention
```bash
launchctl load ~/Library/LaunchAgents/com.nse.prevent.sleep.plist
```

---

## Configuration

**Location:** `~/Library/LaunchAgents/com.nse.prevent.sleep.plist`

**Default Settings:**
- Start time: 9:00 AM
- Days: Monday - Friday
- Duration: 7 hours (25200 seconds)
- Auto-restart: Yes (if crashed)

**To modify start time:**
1. Edit the plist file
2. Change `<key>Hour</key>` and `<key>Minute</key>` values
3. Reload the agent (see commands above)

---

## Troubleshooting

### caffeinate not running during market hours
**Check if agent is loaded:**
```bash
launchctl list | grep com.nse.prevent.sleep
```

**If not loaded, load it:**
```bash
launchctl load ~/Library/LaunchAgents/com.nse.prevent.sleep.plist
```

### Mac still goes to sleep
**Possible reasons:**
1. caffeinate process crashed (check logs)
2. Battery power is low (caffeinate `-s` only works on AC power)
3. System Preferences override (check Energy Saver settings)

**Solution:**
- Plug in your Mac to AC power
- Check logs: `tail -50 logs/caffeinate-stderr.log`
- Manually restart: `launchctl unload ... && launchctl load ...`

### Monitoring scripts still not running
**Check cron job:**
```bash
crontab -l
```

**Check if stock_monitor.py is running:**
```bash
ps aux | grep stock_monitor | grep -v grep
```

**Check logs:**
```bash
tail -50 logs/stock_monitor.log
```

---

## Alternative: System Preferences Method

If automated solution doesn't work, manually change macOS settings:

1. **Open System Preferences → Energy Saver (or Battery)**
2. **Set "Turn display off after" to "Never"** (during market hours)
3. **Uncheck "Put hard disks to sleep when possible"**
4. **Check "Prevent computer from sleeping automatically when display is off"** (macOS 12.3+)

**Remember to revert these settings after market hours to save power!**

---

## Testing

**Test sleep prevention (run before 9:00 AM):**
```bash
# Manually start for 5 minutes (300 seconds)
caffeinate -dis -t 300 &

# Wait 30 seconds, then check activity
sleep 30
pmset -g assertions | grep -i caffeinate
```

**Expected output:**
```
pid 12345(caffeinate): [0x000a...] 00:04:30 NoIdleSleepAssertion named: "caffeinate command-line tool"
```

---

## Summary

✅ **Automated:** Runs every weekday at 9:00 AM (checks holiday calendar first)
✅ **Holiday Aware:** Automatically skips weekends and NSE market holidays
✅ **Duration:** 7 hours (covers market hours) on trading days only
✅ **Restart:** Auto-restarts if crashed
✅ **Low impact:** Background process, lowest priority
✅ **Logs:** Outputs saved to `logs/caffeinate-*.log` and `logs/caffeinate-control.log`

**Your monitoring scripts will now run reliably during market hours - and rest on holidays!**
