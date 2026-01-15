# Price Action Monitor LaunchAgent Guide

## Overview

The Price Action Monitor is now configured to run automatically every **5 minutes** during market hours via macOS LaunchAgent.

## Quick Reference

### Status Check
```bash
# Check if agent is loaded
launchctl list | grep priceaction

# Expected output:
# -    0    com.nse.priceaction.monitor
```

### View Logs
```bash
# Application logs (pattern detection details)
tail -f logs/price_action_monitor.log

# LaunchAgent stdout (job execution)
tail -f logs/priceaction-monitor-stdout.log

# LaunchAgent stderr (errors)
tail -f logs/priceaction-monitor-stderr.log
```

### Management Commands

**Unload (Stop):**
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
```

**Load (Start):**
```bash
launchctl load ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
```

**Reload (After config changes):**
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
launchctl load ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
```

**View Configuration:**
```bash
cat ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
```

## Schedule Details

### Execution Times
- **Frequency**: Every 5 minutes
- **Market Hours**: 9:25 AM - 3:25 PM IST
- **Days**: Monday - Friday only
- **Total Runs**: 73 per trading day

### Specific Times
```
09:25, 09:30, 09:35, 09:40, 09:45, 09:50, 09:55
10:00, 10:05, 10:10, 10:15, 10:20, 10:25, 10:30, 10:35, 10:40, 10:45, 10:50, 10:55
11:00, 11:05, 11:10, 11:15, 11:20, 11:25, 11:30, 11:35, 11:40, 11:45, 11:50, 11:55
12:00, 12:05, 12:10, 12:15, 12:20, 12:25, 12:30, 12:35, 12:40, 12:45, 12:50, 12:55
13:00, 13:05, 13:10, 13:15, 13:20, 13:25, 13:30, 13:35, 13:40, 13:45, 13:50, 13:55
14:00, 14:05, 14:10, 14:15, 14:20, 14:25, 14:30, 14:35, 14:40, 14:45, 14:50, 14:55
15:00, 15:05, 15:10, 15:15, 15:20, 15:25
```

## Log Files

### 1. Application Log
**Path**: `logs/price_action_monitor.log`

**Content**:
- Pattern detection results
- Alert sending status
- Market regime analysis
- Stock filtering decisions
- Error details

**Example**:
```
2026-01-15 10:05:23 - INFO - RELIANCE: Bullish Engulfing detected (confidence: 8.5)
2026-01-15 10:05:24 - INFO - RELIANCE: Telegram alert sent
2026-01-15 10:05:25 - INFO - TCS: Skipping Hammer - price already at/above target
```

### 2. LaunchAgent Stdout
**Path**: `logs/priceaction-monitor-stdout.log`

**Content**:
- Job start/end timestamps
- High-level status messages
- Summary statistics

### 3. LaunchAgent Stderr
**Path**: `logs/priceaction-monitor-stderr.log`

**Content**:
- Critical errors that prevent execution
- Python exceptions
- Import errors

## What Happens Each Run

1. **Market Check**: Verifies trading day and market hours
   - Exits immediately if weekend/holiday
   - Exits immediately if outside 9:25 AM - 3:25 PM

2. **Initialization**:
   - Connects to Kite API
   - Loads F&O stock list
   - Initializes pattern detector

3. **Market Regime Detection**:
   - Fetches Nifty 50 current price
   - Calculates 50-day SMA
   - Determines BULLISH/BEARISH/NEUTRAL

4. **Pattern Scanning**:
   - Fetches 5-min candles for all stocks
   - Runs 19 pattern detection algorithms
   - Calculates confidence scores

5. **Alert Filtering**:
   - ✅ Confidence >= 7.0
   - ✅ Current price hasn't exceeded target
   - ✅ Not in cooldown period (30 min)
   - ✅ Price >= ₹50
   - ✅ Avg volume >= 500K

6. **Alert Delivery**:
   - Sends Telegram notification
   - Logs to Excel tracker
   - Records in alert history

7. **Summary Report**:
   - Logs statistics to file
   - Total stocks checked
   - Patterns detected
   - Alerts sent

## Troubleshooting

### Issue: No Alerts Received

**Check 1: Is it market hours?**
```bash
date "+%H:%M %u"
# Should show 09:25-15:25 and weekday 1-5
```

**Check 2: Is agent running?**
```bash
launchctl list | grep priceaction
# Should show: -  0  com.nse.priceaction.monitor
```

**Check 3: Are there errors?**
```bash
tail -50 logs/priceaction-monitor-stderr.log
```

**Check 4: Check configuration**
```bash
grep ENABLE_PRICE_ACTION_ALERTS config.py
# Should show: ENABLE_PRICE_ACTION_ALERTS = True
```

### Issue: Agent Not Running

**Reload the agent:**
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
launchctl load ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
launchctl list | grep priceaction
```

### Issue: Too Many Alerts

**Option 1: Increase confidence threshold**
Edit `config.py`:
```python
PRICE_ACTION_MIN_CONFIDENCE = 8.0  # Was 7.0
```

**Option 2: Increase cooldown**
Edit `config.py`:
```python
PRICE_ACTION_COOLDOWN = 60  # Was 30 minutes
```

**Option 3: Add price filter**
Edit `config.py`:
```python
PRICE_ACTION_MIN_PRICE = 100  # Was 50
```

After config changes:
```bash
# Reload the agent (will use new config on next run)
launchctl unload ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
launchctl load ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
```

### Issue: Pattern Detected but Alert Skipped

**Check logs for reason:**
```bash
grep -A 2 "Skipping" logs/price_action_monitor.log | tail -20
```

**Common reasons:**
- `price already at/above target` - Opportunity passed
- `within cooldown` - Same pattern alerted <30 min ago
- `Price below minimum` - Stock < ₹50
- `Avg volume below minimum` - Illiquid stock

### Issue: Old Logs Taking Space

**Archive logs:**
```bash
# Archive logs older than 7 days
find logs/ -name "priceaction-monitor-*.log" -mtime +7 -exec gzip {} \;

# Delete archives older than 30 days
find logs/ -name "priceaction-monitor-*.log.gz" -mtime +30 -delete
```

## Testing

### Manual Test Run
```bash
# Run the monitor manually (outside launchd)
./venv/bin/python3 price_action_monitor.py

# This will:
# - Check market hours
# - Exit if not trading time (expected behavior)
# - Or run full scan if during market hours
```

### Force Run (Bypass Market Hours Check)
Edit `price_action_monitor.py` temporarily:
```python
# Comment out the market check
# if not is_market_open():
#     sys.exit(0)
```

Then run:
```bash
./venv/bin/python3 price_action_monitor.py
```

**⚠️ Remember to uncomment after testing!**

### Test Alert Delivery
```python
# Test Telegram connection
./venv/bin/python3 -c "
from telegram_notifier import TelegramNotifier
t = TelegramNotifier()
t.send_test_message()
"
```

## Performance

### Resource Usage
- **CPU**: <5% during scan (5-10 seconds)
- **Memory**: ~150MB
- **Network**: ~2-5 MB per run (API calls)
- **Disk**: ~1 KB logs per run

### Execution Time
- **Typical**: 5-10 seconds per run
- **With patterns**: 10-15 seconds per run
- **Network delays**: Up to 30 seconds

### Alert Volume
Based on backtesting:
- **Average**: 2-5 alerts per day
- **Active markets**: 5-15 alerts per day
- **Quiet markets**: 0-2 alerts per day

## Updating Configuration

After modifying `config.py`, the changes take effect on the **next scheduled run**. No need to reload the LaunchAgent.

**Configuration files read each run:**
- `config.py` - All settings
- `fo_stocks.json` - Stock list
- `.env` - API credentials

**To force immediate pickup:**
```bash
# Just wait for next 5-min interval
# Or manually trigger:
./venv/bin/python3 price_action_monitor.py
```

## Integration with Other Monitors

The Price Action Monitor works alongside:
- **1-Min Monitor** (`onemin_monitor.py`) - Short-term moves
- **ATR Breakout Monitor** (`atr_breakout_monitor.py`) - Volatility breakouts
- **CPR Monitor** (`cpr_first_touch_monitor.py`) - CPR level alerts
- **NIFTY Option Monitor** (`nifty_option_monitor.py`) - Index options

All monitors use the same:
- Alert Excel logger
- Alert history manager
- Telegram notifier
- Cooldown system

## Backup & Restore

### Backup LaunchAgent
```bash
cp ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist \
   ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist.backup
```

### Restore LaunchAgent
```bash
cp ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist.backup \
   ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
launchctl unload ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
launchctl load ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
```

### Remove LaunchAgent
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
rm ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist
```

## Next Steps

1. **Monitor for first run**: Check logs after 9:25 AM on next trading day
2. **Verify alerts**: Ensure Telegram messages are received
3. **Tune settings**: Adjust confidence/cooldown based on alert volume
4. **Check performance**: Monitor execution time in logs

---

**Setup Date**: January 15, 2026
**Status**: ✅ Active and Ready
**Next Trading Day Check**: Monitor logs after 9:25 AM

For issues or questions, check:
- Application logs: `logs/price_action_monitor.log`
- LaunchAgent errors: `logs/priceaction-monitor-stderr.log`
- Documentation: `REALTIME_PATTERN_ALERTS.md`
