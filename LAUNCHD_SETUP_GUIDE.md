# NIFTY Option Monitor - launchd Automation Setup

## Overview

This guide explains how to set up automatic startup of the NIFTY Option Monitor using macOS launchd. Once configured, the monitor will automatically start at 9:15 AM on weekdays and run in daemon mode throughout market hours.

## Prerequisites

- macOS system with launchd support
- NIFTY Option Monitor successfully tested in daemon mode
- Valid Kite Connect token (refreshed daily)

## Installation Steps

### Step 1: Create Logs Directory

Ensure the logs directory exists:

```bash
mkdir -p /Users/sunildeesu/myProjects/ShortIndicator/logs
```

### Step 2: Copy plist to LaunchAgents

Copy the configuration file to your user's LaunchAgents directory:

```bash
cp /Users/sunildeesu/myProjects/ShortIndicator/com.nifty.option.monitor.plist ~/Library/LaunchAgents/
```

### Step 3: Set Correct Permissions

```bash
chmod 644 ~/Library/LaunchAgents/com.nifty.option.monitor.plist
```

### Step 4: Load the Service

Load the service into launchd:

```bash
launchctl load ~/Library/LaunchAgents/com.nifty.option.monitor.plist
```

### Step 5: Verify Installation

Check if the service is loaded:

```bash
launchctl list | grep nifty.option.monitor
```

You should see output like:
```
-	0	com.nifty.option.monitor
```

## Testing

### Test Immediate Start (Optional)

To test the service without waiting for 9:15 AM:

```bash
launchctl start com.nifty.option.monitor
```

**Note**: This will start the daemon immediately, regardless of time. Use for testing only.

### Monitor Logs in Real-Time

Watch the output log:
```bash
tail -f /Users/sunildeesu/myProjects/ShortIndicator/logs/nifty_option_monitor.log
```

Watch the error log:
```bash
tail -f /Users/sunildeesu/myProjects/ShortIndicator/logs/nifty_option_monitor_error.log
```

## Schedule

The monitor will automatically start at:
- **Time**: 9:15 AM
- **Days**: Monday through Friday (weekdays only)
- **Mode**: Daemon (continuous monitoring)

### What Happens at Startup

1. **9:15 AM**: Service starts, waits for 10:00 AM
2. **10:00 AM**: Entry analysis runs (SELL/HOLD/AVOID signal)
3. **10:15 AM - 3:25 PM**: Intraday monitoring every 15 minutes
   - Exit signal checks (if position exists)
   - Add position checks (if < max layers)
4. **After 3:25 PM**: Daemon continues running but no more checks until next day
5. **Next Day 9:15 AM**: Automatically restarts fresh

## Daily Token Refresh

**IMPORTANT**: Kite Connect tokens expire daily. You must refresh the token before 9:15 AM each trading day.

### Option 1: Manual Refresh (Current Setup)

Run this before market open daily:
```bash
cd /Users/sunildeesu/myProjects/ShortIndicator
./venv/bin/python3 generate_kite_token.py
```

### Option 2: Automated Token Refresh (Recommended)

Create a separate launchd job to refresh token at 8:30 AM:

```bash
# Create token refresh plist
cat > ~/Library/LaunchAgents/com.kite.token.refresh.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kite.token.refresh</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3</string>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/generate_kite_token.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator</string>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/token_refresh.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/token_refresh_error.log</string>
</dict>
</plist>
EOF

# Load token refresh service
launchctl load ~/Library/LaunchAgents/com.kite.token.refresh.plist
```

## Management Commands

### Check Status

```bash
launchctl list | grep nifty.option.monitor
```

### View Recent Logs

```bash
# Last 50 lines of output log
tail -50 /Users/sunildeesu/myProjects/ShortIndicator/logs/nifty_option_monitor.log

# Last 50 lines of error log
tail -50 /Users/sunildeesu/myProjects/ShortIndicator/logs/nifty_option_monitor_error.log
```

### Stop the Service

```bash
launchctl stop com.nifty.option.monitor
```

**Note**: This only stops the current running instance. It will restart at next scheduled time (9:15 AM).

### Unload the Service (Disable Completely)

```bash
launchctl unload ~/Library/LaunchAgents/com.nifty.option.monitor.plist
```

### Reload After Configuration Changes

If you modify the plist file:

```bash
launchctl unload ~/Library/LaunchAgents/com.nifty.option.monitor.plist
cp /Users/sunildeesu/myProjects/ShortIndicator/com.nifty.option.monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.nifty.option.monitor.plist
```

## Troubleshooting

### Service Not Starting

**Check if loaded**:
```bash
launchctl list | grep nifty
```

**Check system logs**:
```bash
log show --predicate 'subsystem == "com.apple.launchd"' --last 10m | grep nifty
```

**Verify plist syntax**:
```bash
plutil -lint ~/Library/LaunchAgents/com.nifty.option.monitor.plist
```

### No Logs Being Generated

**Check permissions**:
```bash
ls -la /Users/sunildeesu/myProjects/ShortIndicator/logs/
```

**Create logs directory if missing**:
```bash
mkdir -p /Users/sunildeesu/myProjects/ShortIndicator/logs
```

### Python/Script Errors

**Test manually first**:
```bash
cd /Users/sunildeesu/myProjects/ShortIndicator
./venv/bin/python3 nifty_option_monitor.py --daemon
```

If this works but launchd doesn't, check:
- PATH environment variables in plist
- Working directory is correct
- Python virtual environment path is absolute

### Token Expired Errors

**Symptoms**: Logs show "Token expired" or authentication errors

**Solution**:
```bash
cd /Users/sunildeesu/myProjects/ShortIndicator
./venv/bin/python3 generate_kite_token.py
```

Then restart the service:
```bash
launchctl stop com.nifty.option.monitor
launchctl start com.nifty.option.monitor
```

### Monitor Stuck/Not Responding

**Check if process is running**:
```bash
ps aux | grep nifty_option_monitor
```

**Force stop**:
```bash
launchctl stop com.nifty.option.monitor
# Or kill the process
pkill -f nifty_option_monitor.py
```

**Restart**:
```bash
launchctl start com.nifty.option.monitor
```

## Position State Management

The monitor maintains position state in:
```
/Users/sunildeesu/myProjects/ShortIndicator/data/nifty_options/position_state.json
```

### View Current Position State

```bash
cat /Users/sunildeesu/myProjects/ShortIndicator/data/nifty_options/position_state.json | python3 -m json.tool
```

### Reset Position State Manually

```bash
cd /Users/sunildeesu/myProjects/ShortIndicator
./venv/bin/python3 nifty_option_monitor.py --reset
```

## Monitoring Dashboard

### Real-Time Status Check

Create an alias for quick status check:

```bash
# Add to ~/.zshrc or ~/.bashrc
alias nifty-status='tail -20 /Users/sunildeesu/myProjects/ShortIndicator/logs/nifty_option_monitor.log'
alias nifty-errors='tail -20 /Users/sunildeesu/myProjects/ShortIndicator/logs/nifty_option_monitor_error.log'
alias nifty-position='cat /Users/sunildeesu/myProjects/ShortIndicator/data/nifty_options/position_state.json | python3 -m json.tool'
```

Then simply run:
```bash
nifty-status
nifty-errors
nifty-position
```

## Advanced Configuration

### Change Schedule Time

Edit the plist file and modify the `StartCalendarInterval`:

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>9</integer>  <!-- Change this -->
    <key>Minute</key>
    <integer>15</integer>  <!-- Change this -->
    <key>Weekday</key>
    <integer>1</integer>  <!-- 1=Monday, 5=Friday -->
</dict>
```

Then reload:
```bash
launchctl unload ~/Library/LaunchAgents/com.nifty.option.monitor.plist
launchctl load ~/Library/LaunchAgents/com.nifty.option.monitor.plist
```

### Enable/Disable Auto-Restart

By default, the service auto-restarts if it crashes. To disable:

Edit plist and change:
```xml
<key>KeepAlive</key>
<false/>  <!-- Don't restart at all -->
```

Or keep smart restart (restarts only on unexpected exits):
```xml
<key>KeepAlive</key>
<dict>
    <key>SuccessfulExit</key>
    <false/>  <!-- Don't restart on clean exit -->
</dict>
```

## Monitoring Best Practices

1. **Check logs daily**: Review logs each morning before market open
2. **Verify token**: Ensure Kite token is valid before 9:15 AM
3. **Monitor position state**: Check position state file during trading hours
4. **Review Telegram alerts**: Ensure you receive entry/exit/add alerts
5. **Weekly cleanup**: Archive old logs weekly to save disk space

## Log Rotation (Optional)

Create a log rotation script to prevent logs from growing too large:

```bash
cat > /Users/sunildeesu/myProjects/ShortIndicator/rotate_logs.sh <<'EOF'
#!/bin/bash
LOG_DIR="/Users/sunildeesu/myProjects/ShortIndicator/logs"
ARCHIVE_DIR="$LOG_DIR/archive"
mkdir -p "$ARCHIVE_DIR"

# Rotate if log > 10MB
for log in nifty_option_monitor.log nifty_option_monitor_error.log; do
    if [ -f "$LOG_DIR/$log" ]; then
        SIZE=$(stat -f%z "$LOG_DIR/$log")
        if [ $SIZE -gt 10485760 ]; then
            mv "$LOG_DIR/$log" "$ARCHIVE_DIR/$log.$(date +%Y%m%d_%H%M%S)"
            touch "$LOG_DIR/$log"
        fi
    fi
done
EOF

chmod +x /Users/sunildeesu/myProjects/ShortIndicator/rotate_logs.sh
```

Add to crontab to run daily at midnight:
```bash
0 0 * * * /Users/sunildeesu/myProjects/ShortIndicator/rotate_logs.sh
```

## Summary

Once configured, the NIFTY Option Monitor will:

✅ **Auto-start** at 9:15 AM on weekdays
✅ **Run entry analysis** at 10:00 AM
✅ **Monitor every 15 minutes** from 10:15 AM to 3:25 PM
✅ **Generate exit signals** when conditions deteriorate
✅ **Suggest add positions** when conditions improve
✅ **Send Telegram alerts** for all signals
✅ **Log to Excel** for tracking and backtesting
✅ **Auto-restart** if it crashes unexpectedly
✅ **Reset state** automatically each new trading day

**Next Steps**:
1. Run installation steps above
2. Set up daily token refresh (manual or automated)
3. Monitor logs for the first few days
4. Review Telegram alerts during trading hours
5. Check Excel reports for historical tracking

---

**Version**: 1.0 (Intraday Monitoring with launchd)
**Last Updated**: January 1, 2026
**Status**: Production Ready
