# Greeks Difference Tracker - Setup Guide

## Overview

The Greeks Difference Tracker monitors intraday changes in option Greeks (Delta, Theta, Vega) by comparing live values against a 9:15 AM baseline. It generates formatted Excel reports and uploads them to cloud storage for multi-device access.

## What It Does

1. **9:15 AM**: Captures baseline Greeks for ATM and OTM strikes
2. **Every 15 minutes (9:30 AM - 3:30 PM)**:
   - Fetches current Greeks
   - Calculates differences from baseline
   - Updates Excel report
   - Uploads to Google Drive/Dropbox
3. **9:30 AM (first update)**: Sends ONE Telegram message with cloud link
4. **Result**: 25 rows of data by end of day, accessible from any device

## Prerequisites

### 1. Python Dependencies

Install required libraries:

```bash
# Core dependencies (should already be installed)
pip install kiteconnect openpyxl schedule

# For Google Drive (recommended)
pip install google-auth google-auth-oauthlib google-api-python-client

# Alternative: For Dropbox
pip install dropbox
```

### 2. Google Drive Setup (Recommended)

#### Step 1: Create Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., "Greeks Tracker")
3. Enable the **Google Drive API**

#### Step 2: Create Service Account
1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **Service Account**
3. Name it (e.g., "greeks-tracker-service")
4. Click **Create and Continue**
5. Skip optional steps (no roles needed)
6. Click **Done**

#### Step 3: Generate Credentials JSON
1. Click on the service account you just created
2. Go to **Keys** tab
3. Click **Add Key** → **Create new key**
4. Choose **JSON** format
5. Download the file

#### Step 4: Save Credentials
1. Create a `credentials` directory in your project:
   ```bash
   mkdir -p /Users/sunildeesu/myProjects/ShortIndicator/credentials
   ```
2. Move the downloaded JSON file:
   ```bash
   mv ~/Downloads/your-project-xxxxx.json /Users/sunildeesu/myProjects/ShortIndicator/credentials/google_drive_credentials.json
   ```

#### Step 5: Create Google Drive Folder (Optional)
1. Go to [Google Drive](https://drive.google.com/)
2. Create a new folder (e.g., "Greeks Reports")
3. Right-click → **Share** → Add the service account email (from credentials JSON)
4. Give it **Editor** permission
5. Copy the folder ID from the URL:
   ```
   https://drive.google.com/drive/folders/FOLDER_ID_HERE
   ```

#### Step 6: Configure Environment
Add to your `.env` file:
```bash
# Google Drive Configuration
GREEKS_DIFF_CLOUD_PROVIDER=google_drive
GREEKS_DIFF_GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here
GREEKS_DIFF_GOOGLE_CREDENTIALS_PATH=credentials/google_drive_credentials.json
```

### 3. Alternative: Dropbox Setup

If you prefer Dropbox:

#### Step 1: Create Dropbox App
1. Go to [Dropbox App Console](https://www.dropbox.com/developers/apps)
2. Click **Create app**
3. Choose:
   - **Scoped access**
   - **Full Dropbox** access
   - Name your app (e.g., "Greeks Tracker")

#### Step 2: Generate Access Token
1. Go to your app's **Settings** tab
2. Scroll to **OAuth 2**
3. Click **Generate** under "Generated access token"
4. Copy the token

#### Step 3: Configure Environment
Add to your `.env` file:
```bash
# Dropbox Configuration
GREEKS_DIFF_CLOUD_PROVIDER=dropbox
GREEKS_DIFF_DROPBOX_TOKEN=your_dropbox_token_here
```

## Usage

### Option 1: Automated Monitoring (Recommended)

Start the tracker in monitoring mode - it will automatically:
- Capture baseline at 9:15 AM
- Update every 15 minutes throughout the day

```bash
python greeks_difference_tracker.py --monitor
```

**Note**: Run this before 9:15 AM to ensure baseline capture.

### Option 2: Manual Execution

#### Capture Baseline (9:15 AM)
```bash
python greeks_difference_tracker.py --capture-baseline
```

#### Update Differences (Every 15 min)
```bash
python greeks_difference_tracker.py --update
```

### Option 3: Cron Job

Add to crontab for automated daily execution:

```bash
crontab -e
```

Add these lines:
```bash
# Capture baseline at 9:15 AM (Mon-Fri)
15 9 * * 1-5 cd /Users/sunildeesu/myProjects/ShortIndicator && python greeks_difference_tracker.py --capture-baseline

# Update every 15 minutes from 9:15 AM to 3:30 PM (Mon-Fri)
*/15 9-15 * * 1-5 cd /Users/sunildeesu/myProjects/ShortIndicator && python greeks_difference_tracker.py --update
```

## Output

### Excel Report

**Location**: `data/greeks_difference_reports/YYYY/MM/greeks_diff_YYYYMMDD.xlsx`

**Example**: `data/greeks_difference_reports/2026/01/greeks_diff_20260107.xlsx`

**Structure**:

| Time  | NIFTY  | CE Δ Diff | CE Θ Diff | CE V Diff | PE Δ Diff | PE Θ Diff | PE V Diff |
|-------|--------|-----------|-----------|-----------|-----------|-----------|-----------|
| 09:15 | 23456  | 0.00      | 0.00      | 0.00      | 0.00      | 0.00      | 0.00      |
| 09:30 | 23465  | +0.05     | -0.80     | +2.10     | -0.04     | -0.60     | +1.50     |
| 09:45 | 23478  | +0.08     | -2.10     | +4.50     | -0.06     | -1.80     | +3.20     |
| ...   | ...    | ...       | ...       | ...       | ...       | ...       | ...       |

**Formatting**:
- Green text = Positive values
- Red text = Negative values
- All cells bordered
- Top row frozen
- 2 decimal places

### Telegram Notification

**Sent once at 9:30 AM**:

```
📊 GREEKS DIFFERENCE TRACKER - LIVE REPORT

🎯 Tracking Started: 9:15 AM
📅 Date: 2026-01-07

📄 Live Excel File (Google Drive):
https://drive.google.com/file/d/XXXXXXXXXXXX/view?usp=sharing

⏰ Updates: Every 15 minutes (9:15 AM - 3:30 PM)
📊 Total Updates: 25 rows by end of day

💡 This file updates automatically in the cloud throughout the day.
   Click the link from ANY device (mobile/desktop) to see the latest Greeks differences!

🌐 Accessible from anywhere - no downloads needed!
```

### Cloud Storage

- **File name**: `greeks_diff_YYYYMMDD.xlsx`
- **Updates**: Every 15 minutes (same file, overwritten)
- **Access**: Click link from any device to see latest data
- **No downloads**: View directly in browser or download if needed

## Configuration

All settings are in `config.py`. Key parameters:

```python
# Enable/disable tracker
ENABLE_GREEKS_DIFF_TRACKER = True

# Timing
GREEKS_BASELINE_TIME = "09:15"  # Market open
GREEKS_UPDATE_INTERVAL_MINUTES = 15  # Every 15 min

# Strikes analyzed
GREEKS_DIFF_STRIKE_OFFSETS = [0, 50, 100, 150]  # ATM, ATM±50/100/150

# Cloud provider
GREEKS_DIFF_CLOUD_PROVIDER = 'google_drive'  # or 'dropbox'
```

## Troubleshooting

### 1. "Google Drive credentials not found"

**Solution**: Ensure credentials JSON file exists at the configured path:
```bash
ls -la credentials/google_drive_credentials.json
```

If missing, follow Google Drive setup steps above.

### 2. "No valid expiries found"

**Cause**: Trading on a day when next week expiry is < 7 days away.

**Solution**: The tracker automatically filters for expiries > 7 days. This is by design to avoid current week expiry.

### 3. "Insufficient baseline data"

**Cause**: Not enough strikes have valid Greeks data (need 6+ strikes: 3 CE + 3 PE).

**Solution**:
- Check if market is open and Kite API is responding
- Verify KITE_ACCESS_TOKEN is valid
- Check logs for specific strike failures

### 4. "Google Drive upload failed"

**Check**:
1. Service account email has access to the folder
2. Folder ID is correct
3. Internet connection is working
4. Google Drive API is enabled

**Fallback**: If cloud upload fails, the local Excel file is still created and updated.

### 5. "Telegram not sent"

**Check**:
1. `GREEKS_DIFF_ENABLE_TELEGRAM = True` in config
2. `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` are set in `.env`
3. Telegram bot has permission to post in the channel

### 6. Excel file not updating

**Check**:
1. Baseline was captured at 9:15 AM
2. Scheduler is running (`--monitor` mode)
3. Current time is between 9:15 AM and 3:30 PM
4. It's a weekday (Monday-Friday)

## Interpreting the Data

### Delta Differences

- **CE Delta +ve**: Call delta increasing → bullish price movement
- **PE Delta -ve**: Put delta decreasing (becoming less negative) → bullish price movement
- **CE Delta -ve**: Call delta decreasing → bearish price movement
- **PE Delta +ve**: Put delta increasing (becoming more negative) → bearish price movement

### Theta Differences

- **Negative values**: Theta decay accelerating (normal intraday behavior)
- **Positive values**: Theta decay slowing (unusual, may indicate volatility spike)

### Vega Differences

- **CE Vega +ve**: Call options gaining volatility sensitivity → expecting upward vol
- **PE Vega +ve**: Put options gaining volatility sensitivity → expecting downward vol
- **Both +ve**: Overall market expecting higher volatility
- **Both -ve**: Overall market expecting lower volatility

## Example Day Timeline

```
09:15 AM - Baseline captured (all diffs = 0.00)
09:30 AM - First update + Telegram sent with cloud link
09:45 AM - Silent update (Excel + cloud update)
10:00 AM - Silent update
...
15:30 PM - Final update (25th row)
```

**Total**: 1 Telegram message, 25 Excel updates, 25 cloud uploads

## Benefits

1. **9:15 AM Baseline**: Eliminates VEGA decay problem by using fixed reference
2. **Multi-Device Access**: Cloud storage works on mobile, tablet, desktop
3. **Auto-Updates**: Same link always shows latest data
4. **No Spam**: Only 1 Telegram message per day
5. **Trend Analysis**: See how Greeks evolve throughout the trading day
6. **Historical Data**: Excel files organized by year/month

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review logs for detailed error messages
3. Verify all prerequisites are met
4. Ensure market is open and APIs are responding

---

**Happy Tracking!** 📊
