# Greeks Difference Tracker - Quick Start Guide 🚀

## ✅ Setup Complete!

Your Greeks Difference Tracker is fully configured and ready to use!

## What It Does

Tracks intraday changes in option Greeks (Delta, Theta, Vega) by comparing live values against a 9:15 AM baseline.

**Daily Workflow:**
1. **9:15 AM** → Captures baseline Greeks for 8 strikes (4 CE + 4 PE)
2. **9:30 AM** → First update, uploads Excel to Dropbox, sends Telegram with link
3. **9:45 AM - 3:30 PM** → Updates Excel every 15 min (silent, no Telegram spam)
4. **End of day** → 25 rows of Greeks difference data

## How to Run

### Option 1: Automated Monitoring (Recommended)

Start before 9:15 AM on any trading day:

```bash
cd /Users/sunildeesu/myProjects/ShortIndicator
./venv/bin/python3 greeks_difference_tracker.py --monitor
```

This will:
- Capture baseline at 9:15 AM
- Update every 15 minutes automatically
- Run until 3:30 PM

### Option 2: Manual Commands

**Capture baseline (run at 9:15 AM):**
```bash
./venv/bin/python3 greeks_difference_tracker.py --capture-baseline
```

**Update differences (run every 15 min):**
```bash
./venv/bin/python3 greeks_difference_tracker.py --update
```

### Option 3: Cron Job (Set and Forget)

Add to crontab for daily automation:

```bash
crontab -e
```

Add these lines:
```bash
# Capture baseline at 9:15 AM (Mon-Fri)
15 9 * * 1-5 cd /Users/sunildeesu/myProjects/ShortIndicator && ./venv/bin/python3 greeks_difference_tracker.py --capture-baseline

# Update every 15 minutes from 9:15 AM to 3:30 PM (Mon-Fri)
*/15 9-15 * * 1-5 cd /Users/sunildeesu/myProjects/ShortIndicator && ./venv/bin/python3 greeks_difference_tracker.py --update
```

## What You'll Receive

### Telegram Message (9:30 AM - Once per day)

```
📊 GREEKS DIFFERENCE TRACKER - LIVE REPORT

🎯 Tracking Started: 9:15 AM
📅 Date: 2026-01-08

📄 Live Excel File (Dropbox):
https://www.dropbox.com/scl/fi/xxxx/greeks_diff_20260108.xlsx

⏰ Updates: Every 15 minutes (9:15 AM - 3:30 PM)
📊 Total Updates: 25 rows by end of day

💡 This file updates automatically throughout the day.
   Click the link from ANY device to see latest data!

🌐 Accessible from anywhere - no downloads needed!
```

### Excel Report

**Location:**
- Local: `data/greeks_difference_reports/2026/01/greeks_diff_20260108.xlsx`
- Cloud: Dropbox (link in Telegram)

**Structure:**

| Time  | NIFTY  | CE Δ Diff | CE Θ Diff | CE V Diff | PE Δ Diff | PE Θ Diff | PE V Diff |
|-------|--------|-----------|-----------|-----------|-----------|-----------|-----------|
| 09:15 | 23456  | 0.00      | 0.00      | 0.00      | 0.00      | 0.00      | 0.00      |
| 09:30 | 23465  | +0.05     | -0.80     | +2.10     | -0.04     | -0.60     | +1.50     |
| 09:45 | 23478  | +0.08     | -2.10     | +4.50     | -0.06     | -1.80     | +3.20     |
| ...   | ...    | ...       | ...       | ...       | ...       | ...       | ...       |
| 15:30 | 23512  | +0.12     | -8.50     | +12.30    | -0.10     | -7.20     | +10.50    |

**Formatting:**
- ✅ Green = Positive values
- 🔴 Red = Negative values
- 📊 Auto-updating in cloud every 15 min

## Interpreting the Data

### Delta Differences
- **CE Δ +ve** → Calls becoming more sensitive to price (bullish signal)
- **PE Δ -ve** → Puts becoming less sensitive (bullish signal)
- **CE Δ -ve** → Calls losing sensitivity (bearish signal)
- **PE Δ +ve** → Puts gaining sensitivity (bearish signal)

### Theta Differences
- **Negative** → Time decay accelerating (normal)
- **Positive** → Time decay slowing (unusual, volatility spike)

### Vega Differences
- **Both +ve** → Market expecting higher volatility
- **Both -ve** → Market expecting lower volatility
- **CE > PE** → Upside volatility expected
- **PE > CE** → Downside volatility expected

## Configuration

All settings in `config.py`:

```python
ENABLE_GREEKS_DIFF_TRACKER = True       # Enable/disable
GREEKS_UPDATE_INTERVAL_MINUTES = 15     # Update frequency
GREEKS_DIFF_STRIKE_OFFSETS = [0, 50, 100, 150]  # Strikes to track
GREEKS_DIFF_CLOUD_PROVIDER = 'dropbox'  # Cloud storage
```

Cloud settings in `.env`:

```bash
GREEKS_DIFF_CLOUD_PROVIDER=dropbox
GREEKS_DIFF_DROPBOX_TOKEN=sl.u.AGOWK2... (your token)
GREEKS_DIFF_ENABLE_TELEGRAM=true
```

## Troubleshooting

### "No baseline found"
**Solution:** Make sure you run at or after 9:15 AM, or run `--capture-baseline` manually first.

### "Insufficient baseline data"
**Cause:** Not enough strikes have valid Greeks (need 6+: 3 CE + 3 PE)
**Solution:**
- Check market is open
- Verify Kite API is working
- Check access token is valid

### "Dropbox upload failed"
**Check:**
- Dropbox token is valid and has correct permissions
- Internet connection is working
- Token has `files.content.write` and `sharing.write` scopes

### Excel not updating
**Check:**
- Baseline was captured at 9:15 AM
- Current time is between 9:15 AM and 3:30 PM
- It's a weekday (Monday-Friday)
- Scheduler is running

## Files Created

```
ShortIndicator/
├── greeks_difference_tracker.py   # Main module
├── config.py                       # Updated with new config
├── .env                           # Dropbox token added
├── test_dropbox.py                # Test script
├── GREEKS_TRACKER_SETUP.md        # Full setup guide
├── GREEKS_TRACKER_QUICKSTART.md   # This file
└── data/
    └── greeks_difference_reports/
        └── YYYY/
            └── MM/
                └── greeks_diff_YYYYMMDD.xlsx
```

## Example Daily Timeline

```
09:15 AM - Baseline captured (all diffs = 0.00)
09:30 AM - First update + Telegram sent ✉️
09:45 AM - Silent update (Excel + Dropbox)
10:00 AM - Silent update
10:15 AM - Silent update
...
15:30 PM - Final update (25th row)
```

**Total:** 1 Telegram message, 25 Excel updates, 25 Dropbox uploads

## Benefits

✅ **9:15 AM Baseline** → Eliminates VEGA decay problem
✅ **Multi-Device Access** → Dropbox link works on phone, tablet, desktop
✅ **Auto-Updates** → Same link always shows latest data
✅ **No Spam** → Only 1 Telegram message per day
✅ **Trend Analysis** → See how Greeks evolve intraday
✅ **Historical Data** → Files organized by year/month

## Support

For detailed setup instructions: See `GREEKS_TRACKER_SETUP.md`

For issues:
1. Check logs for error messages
2. Verify prerequisites (Python libs, API tokens)
3. Ensure market is open during testing

---

## 🎯 Ready to Start!

**Tomorrow morning:**
1. Start the monitor before 9:15 AM
2. Wait for Telegram message at 9:30 AM
3. Click the Dropbox link
4. Watch Greeks differences update every 15 minutes!

**Command:**
```bash
./venv/bin/python3 greeks_difference_tracker.py --monitor
```

Happy tracking! 📊📈
