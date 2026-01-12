# Volume Profile Analyzer - Automation Setup

## Problem Solved

The volume profile analyzer was **NOT running automatically** despite being fully functional. It required manual execution every day.

**Root Cause**: No launchd automation configured - the tool only had a command-line interface.

---

## Solution Implemented

### Automated Daily Execution

✅ **Runs automatically once per day:**
- **3:25 PM**: End-of-day analysis (full market data 9:15 AM - 3:25 PM)

✅ **Only on market days** (Monday - Friday)

✅ **Zero manual intervention** required

✅ **Simple & efficient**: One report per day near market close

---

## Files Created

### 1. Launcher Script
**Path**: `/Users/sunildeesu/myProjects/ShortIndicator/start_volume_profile.sh`

**Purpose**: Wrapper script that:
- Checks if it's a weekday
- Determines execution time (3:00 PM or 3:15 PM)
- Logs all activities
- Executes volume_profile_analyzer.py

**Permissions**: Executable (`chmod +x`)

### 2. launchd Agent
**Path**: `/Users/sunildeesu/Library/LaunchAgents/com.shortindicator.volumeprofile.plist`

**Purpose**: macOS automation configuration

**Schedule**: 10 calendar intervals (2 times × 5 weekdays)
```xml
3:00 PM: Monday, Tuesday, Wednesday, Thursday, Friday
3:15 PM: Monday, Tuesday, Wednesday, Thursday, Friday
```

**Status**: ✅ Loaded and active

---

## How It Works

### Timeline

| Time | Action | What Happens |
|------|--------|--------------|
| **3:25 PM** | launchd triggers | `start_volume_profile.sh` runs |
| 3:25:05 | Analysis starts | Fetches 1-min candles (9:15 AM - 3:25 PM) - full day |
| 3:25:15 | Volume profile calc | Calculates POC, classifies P/B/BALANCED shapes |
| 3:25:25 | Report generated | Excel file: `volume_profile_eod_YYYY-MM-DD.xlsx` |
| 3:25:28 | **Dropbox upload** | **Uploads report to Dropbox ☁️** |
| 3:25:30 | Telegram sent | Alerts for high-confidence patterns |
| 3:26:00 | Complete | Process exits, ready for next day |

---

## Dropbox Cloud Backup ☁️

**NEW**: Reports are automatically uploaded to Dropbox after generation!

### Features

✅ **Automatic Upload**: Report uploaded immediately after generation
✅ **Shareable Links**: Access reports from any device (mobile, desktop, web)
✅ **Persistent Storage**: Reports remain in Dropbox indefinitely
✅ **Zero Manual Work**: Fully automated - no user action needed

### Setup Required

1. **Create Dropbox App**: https://www.dropbox.com/developers/apps
2. **Generate Access Token**: Copy the token (starts with `sl.`)
3. **Add to .env file**:
   ```bash
   VOLUME_PROFILE_DROPBOX_TOKEN=sl.BxxxxxxxxxxxxxxxxxxxA
   VOLUME_PROFILE_DROPBOX_FOLDER=/VolumeProfile
   ```
4. **Verify**: Reports will upload automatically from next run

### Access Reports

After each run, check logs for Dropbox link:
```bash
grep "Dropbox link:" logs/volume_profile_$(date +%Y%m%d).log
```

**Example output**:
```
✓ Dropbox link: https://www.dropbox.com/s/xxxxxxxx/volume_profile_3pm_20260110.xlsx?dl=1
```

Open this link from **any device** - no Dropbox account needed!

**Full setup guide**: See `VOLUME_PROFILE_DROPBOX_SETUP.md`

---

## What Gets Analyzed

### Stocks
- **209 F&O stocks** (all NSE Futures & Options instruments)
- Filtered: Price ≥ ₹50, not banned

### Patterns Detected

**P-SHAPE (Bullish - Strength at Highs)**
```
POC Position: ≥ 70% of day's range
Meaning: Price held near day high with heavy volume
Interpretation: Buyers in control, strength, continuation likely
Confidence: Based on volume concentration and POC position
```

**B-SHAPE (Bearish - Weakness at Lows)**
```
POC Position: ≤ 30% of day's range
Meaning: Price held near day low with heavy volume
Interpretation: Sellers in control, weakness, continuation likely
Confidence: Based on volume concentration and POC position
```

**BALANCED (Neutral)**
```
POC Position: 31%-69% of day's range
Meaning: Volume spread across range
Interpretation: No clear bias
```

### Telegram Alerts

**Only sent for high-confidence patterns:**
- Minimum confidence: 7.5/10
- Minimum candles: 30 (30 minutes of data)
- Clear P-SHAPE or B-SHAPE classification

---

## Output Files

### Report Location
```
data/volume_profile_reports/YYYY/MM/volume_profile_eod_YYYY-MM-DD.xlsx
```

**Example**:
```
data/volume_profile_reports/2026/01/volume_profile_eod_2026-01-10.xlsx
```

**Note**: "eod" = End of Day (3:25 PM near market close)

### Excel Columns

| Column | Description |
|--------|-------------|
| **Symbol** | Stock symbol |
| **Profile Shape** | P-SHAPE / B-SHAPE / BALANCED |
| **Confidence** | 0-10 score |
| **POC Price** | Point of Control (max volume price) |
| **POC Position** | 0.0-1.0 (bottom to top of range) |
| **POC Volume** | Volume at POC level |
| **Total Volume** | Day's total volume |
| **Day High** | Highest price |
| **Day Low** | Lowest price |
| **Day Range** | High - Low |
| **Num Candles** | Number of 1-min candles analyzed |
| **Interpretation** | Bullish/Bearish/Neutral |

---

## Logs

### Daily Logs
**Path**: `logs/volume_profile_YYYYMMDD.log`

**Example**: `logs/volume_profile_20260110.log`

**Contains**:
- Execution start/end timestamps
- Number of stocks analyzed
- Patterns detected
- API calls made
- Cache hit/miss statistics
- Errors/warnings

### Standard Output/Error
**Stdout**: `logs/volumeprofile-stdout.log`
**Stderr**: `logs/volumeprofile-stderr.log`

---

## Management Commands

### Check Status
```bash
# Verify agent is loaded
launchctl list | grep volumeprofile
# Should show: -	0	com.shortindicator.volumeprofile

# Check if process is running (during 3:00-3:15 PM window)
ps aux | grep volume_profile_analyzer | grep -v grep

# View today's log
tail -f logs/volume_profile_$(date +%Y%m%d).log
```

### Restart Agent
```bash
# Unload
launchctl unload ~/Library/LaunchAgents/com.shortindicator.volumeprofile.plist

# Load
launchctl load ~/Library/LaunchAgents/com.shortindicator.volumeprofile.plist

# Verify
launchctl list | grep volumeprofile
```

### Manual Test Run
```bash
# Test 3:00 PM run
cd ~/myProjects/ShortIndicator
./start_volume_profile.sh

# Test with specific time
./venv/bin/python3 volume_profile_analyzer.py --execution-time 3:00PM
./venv/bin/python3 volume_profile_analyzer.py --execution-time 3:15PM
```

---

## Expected Behavior

### Monday - Friday

| Time | Expected Behavior |
|------|-------------------|
| **Before 3:25 PM** | Agent loaded, waiting for scheduled time |
| **3:25 PM** | Process starts, analyzes 209 stocks, generates report |
| **3:26 PM** | Process exits, report uploaded to Dropbox |
| **After 3:26 PM** | Report available locally and in Dropbox, agent waits for next day |

### Saturday - Sunday

- **No execution** (Weekday check in StartCalendarInterval)
- Zero CPU usage
- Zero log entries

### Holidays

- Process starts at 3:00 PM
- Holiday checker (if implemented) skips execution
- Otherwise, executes normally (user can review reports)

---

## Verification Checklist

After next market day (Monday-Friday at 3:00 PM or 3:15 PM), verify:

```bash
# 1. Agent is loaded
launchctl list | grep volumeprofile
# Should show: -	0	com.shortindicator.volumeprofile

# 2. Report was generated
ls -lh data/volume_profile_reports/$(date +%Y)/$(date +%m)/ | grep $(date +%Y-%m-%d)
# Should show: volume_profile_eod_YYYY-MM-DD.xlsx

# 3. Logs exist
ls -lh logs/ | grep volume_profile_$(date +%Y%m%d)
# Should show: volume_profile_YYYYMMDD.log

# 4. Check execution in logs
grep "VOLUME PROFILE ANALYZER - STARTING" logs/volume_profile_$(date +%Y%m%d).log
# Should show 1 entry (3:25 PM)

# 5. Verify pattern detection
grep "SHAPE detected" logs/volume_profile_$(date +%Y%m%d).log | wc -l
# Should show multiple matches
```

---

## Troubleshooting

### Agent Not Starting

**Check if loaded**:
```bash
launchctl list | grep volumeprofile
```

If missing:
```bash
launchctl load ~/Library/LaunchAgents/com.shortindicator.volumeprofile.plist
```

**Check plist syntax**:
```bash
plutil -lint ~/Library/LaunchAgents/com.shortindicator.volumeprofile.plist
# Should show: OK
```

### No Reports Generated

**Check logs for errors**:
```bash
tail -50 logs/volumeprofile-stderr.log
tail -50 logs/volume_profile_$(date +%Y%m%d).log
```

**Common issues**:
1. Kite API token expired → Run `./generate_kite_token.py`
2. Missing .env file → Check environment variables
3. Cache database locked → Delete `data/price_cache.db` and restart

### Process Running Outside 3:00-3:15 PM Window

This should **NEVER** happen with the new system. If it does:
```bash
# Check which agent is loaded
launchctl list | grep volume

# Ensure correct plist
cat ~/Library/LaunchAgents/com.shortindicator.volumeprofile.plist | grep -A5 "StartCalendarInterval"
# Should show Hour:15, Minute:0 and Minute:15
```

---

## Performance Characteristics

### API Calls Per Day

**Single End-of-Day Run** (Current Implementation):
- 3:25 PM: 209 stocks × 1 API call = 209 calls
- **Total**: ~209 calls/day
- **Benefit**: Simple, efficient, complete market data

### Execution Time

| Phase | Duration |
|-------|----------|
| Data Fetching | 15-30 seconds |
| Volume Profile Calculation | 10-20 seconds |
| Excel Report Generation | 5-10 seconds |
| Telegram Notification | 2-5 seconds |
| **Total** | **30-65 seconds** |

### Resource Usage

- **CPU**: Moderate during execution (30-60 seconds)
- **Memory**: ~100-200 MB
- **Disk**: 500 KB - 1 MB per report
- **Network**: 209-310 API calls/day

---

## Integration with Other Systems

### Unified Data Cache

Volume profile analyzer uses `unified_data_cache.py`:
- 15-minute TTL for intraday data
- Shared cache with 1-min alert system
- Reduces redundant API calls

### Telegram Notifier

Uses `telegram_notifier.py` for alerts:
- Only high-confidence patterns (≥7.5/10)
- Formatted with pattern interpretation
- File attachments (Excel reports)

### Token Manager

Uses `token_manager.py` for Kite API:
- Auto-refreshes tokens
- Handles authentication
- Manages session

---

## Summary

### Problem
Volume profile tool existed but **wasn't running automatically** - required manual execution every day.

### Solution
✅ Created `start_volume_profile.sh` launcher script
✅ Created `com.shortindicator.volumeprofile.plist` launchd agent
✅ Configured to run at 3:25 PM on weekdays
✅ Loaded and verified agent
✅ Zero manual intervention required

### Expected Outcome
- **1 Excel report per day** (3:25 PM - end of day)
- **Telegram alerts** for high-confidence patterns
- **Complete market data** (9:15 AM - 3:25 PM)
- **Fully automated** - runs Monday-Friday without user action
- **Simple & efficient** - one comprehensive report

---

**The volume profile analyzer will now run automatically every trading day!** 📊
