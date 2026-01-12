# Volume Profile - Dropbox Upload Setup Guide

## Overview

The volume profile analyzer now automatically uploads Excel reports to Dropbox after generation. This allows you to access reports from any device via a shareable link.

---

## Features

✅ **Automatic Upload**: Report uploaded immediately after generation
✅ **End-of-Day Report**: Single comprehensive report at 3:25 PM
✅ **Persistent Links**: Shareable links remain valid indefinitely
✅ **Overwrite Protection**: Same-day reports overwrite previous versions
✅ **Zero Manual Work**: Runs automatically via launchd

---

## Setup Instructions

### Step 1: Create Dropbox App

1. Go to https://www.dropbox.com/developers/apps
2. Click "Create app"
3. Choose:
   - **API**: Scoped access
   - **Access type**: Full Dropbox (or App folder if you prefer restricted access)
   - **App name**: `VolumeProfileReports` (or any name you like)
4. Click "Create app"

### Step 2: Generate Access Token

1. In your new app's settings page, scroll to "OAuth 2"
2. Under "Generated access token", click "Generate"
3. Copy the token (starts with `sl.`)
4. **IMPORTANT**: Save this token securely - it won't be shown again!

**Example token format**:
```
sl.BxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxA
```

### Step 3: Configure Environment Variable

Add the Dropbox token to your `.env` file:

```bash
# Edit .env file
nano /Users/sunildeesu/myProjects/ShortIndicator/.env

# Add this line (replace with your actual token):
VOLUME_PROFILE_DROPBOX_TOKEN=sl.BxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxA

# Optional: Change folder path (default is /VolumeProfile)
VOLUME_PROFILE_DROPBOX_FOLDER=/TradingReports/VolumeProfile

# Optional: Disable Dropbox upload
VOLUME_PROFILE_ENABLE_DROPBOX=true  # Set to 'false' to disable
```

**Save and exit** (Ctrl+O, Enter, Ctrl+X in nano)

### Step 4: Create Dropbox Folder (Optional)

If you specified a custom folder path, create it in Dropbox:

```bash
# Option 1: Via Dropbox web interface
# - Go to https://www.dropbox.com
# - Create folder: VolumeProfile (or your custom path)

# Option 2: Folder will be auto-created on first upload
# - No manual action needed
```

### Step 5: Verify Configuration

Test the upload manually:

```bash
cd /Users/sunildeesu/myProjects/ShortIndicator

# Test with 3:00 PM execution
./venv/bin/python3 volume_profile_analyzer.py --execution-time 3:00PM

# Check logs for upload confirmation
tail -50 logs/volume_profile.log | grep -i dropbox
```

**Expected output**:
```
2026-01-10 15:00:25 - Uploading volume profile report to Dropbox...
2026-01-10 15:00:27 - ✓ Uploaded to Dropbox: /VolumeProfile/volume_profile_3pm_20260110.xlsx
2026-01-10 15:00:28 - ✓ Dropbox link: https://www.dropbox.com/s/xxxxxxxx/volume_profile_3pm_20260110.xlsx?dl=1
2026-01-10 15:00:28 - Report uploaded to Dropbox: https://www.dropbox.com/s/xxxxxxxx/...
```

---

## File Structure in Dropbox

### Default Organization

```
/VolumeProfile/
├── volume_profile_eod_2026-01-10.xlsx
├── volume_profile_eod_2026-01-09.xlsx
├── volume_profile_eod_2026-01-08.xlsx
└── ... (all historical reports)
```

**Note**: "eod" = End of Day (3:25 PM)

### Custom Organization (Optional)

You can organize by date using custom folder paths:

```bash
# In .env file:
VOLUME_PROFILE_DROPBOX_FOLDER=/TradingReports/$(date +%Y)/$(date +%m)

# Results in:
/TradingReports/2026/01/volume_profile_3pm_20260110.xlsx
```

**Note**: Dynamic paths require modifying `volume_profile_analyzer.py` code

---

## Accessing Reports

### From Any Device

1. Check logs for Dropbox link:
   ```bash
   grep "Dropbox link:" logs/volume_profile_$(date +%Y%m%d).log
   ```

2. Copy the link (format: `https://www.dropbox.com/s/xxxxx/...?dl=1`)

3. Open link in:
   - **Desktop**: Browser (Chrome, Safari, etc.)
   - **Mobile**: Dropbox app or browser
   - **Tablet**: Dropbox app or browser

### Direct Download

Links with `?dl=1` suffix trigger direct download (no Dropbox login required)

### Sharing Links

Share the Dropbox link with others:
- Links are public (no Dropbox account needed)
- Recipients can view/download the Excel file
- Perfect for team collaboration

---

## Automated Daily Workflow

### Timeline

| Time | Action | Result |
|------|--------|--------|
| **3:25 PM** | Analyzer runs | `volume_profile_eod_YYYY-MM-DD.xlsx` uploaded to Dropbox |
| **3:26 PM** | Upload complete | Shareable link logged |

### No Manual Intervention

Once configured:
- ✅ Report auto-uploaded every trading day at 3:25 PM
- ✅ Links remain valid indefinitely
- ✅ Same-day reports overwrite (not duplicate)
- ✅ Access from any device anytime
- ✅ Complete end-of-day market data (9:15 AM - 3:25 PM)

---

## Troubleshooting

### Upload Fails: "Dropbox token not configured"

**Cause**: Token not set in `.env` file

**Fix**:
```bash
# Check if token is set
grep VOLUME_PROFILE_DROPBOX_TOKEN .env

# If missing, add it:
echo "VOLUME_PROFILE_DROPBOX_TOKEN=sl.BxxxxxxxxxxxA" >> .env
```

### Upload Fails: "Invalid access token"

**Cause**: Token expired or revoked

**Fix**:
1. Go to https://www.dropbox.com/developers/apps
2. Select your app
3. Regenerate access token
4. Update `.env` file with new token

### Upload Succeeds But Link Not Working

**Cause**: Shareable link not created

**Fix**:
- Link creation might have failed
- Check if file exists in Dropbox web interface
- Manually create shareable link from Dropbox

### "Dropbox upload disabled in config"

**Cause**: `VOLUME_PROFILE_ENABLE_DROPBOX` set to `false`

**Fix**:
```bash
# Edit .env file
nano .env

# Change to:
VOLUME_PROFILE_ENABLE_DROPBOX=true
```

### ImportError: No module named 'dropbox'

**Cause**: Dropbox library not installed

**Fix**:
```bash
cd /Users/sunildeesu/myProjects/ShortIndicator
./venv/bin/pip install dropbox
```

---

## Security Considerations

### Token Security

**DO NOT**:
- ❌ Commit `.env` file to Git (already in .gitignore)
- ❌ Share token publicly
- ❌ Hardcode token in scripts

**DO**:
- ✅ Store token in `.env` file only
- ✅ Use environment variables
- ✅ Regenerate token if compromised

### Access Control

**Dropbox App Permissions**:
- App has full access to files it creates
- Can't access other files (unless you chose "Full Dropbox" access)
- Revoke access anytime from Dropbox settings

**Shareable Links**:
- Public links are accessible to anyone with the URL
- No Dropbox login required
- Consider using password-protected links for sensitive data

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VOLUME_PROFILE_ENABLE_DROPBOX` | `true` | Enable/disable Dropbox upload |
| `VOLUME_PROFILE_DROPBOX_TOKEN` | (empty) | Dropbox access token (required) |
| `VOLUME_PROFILE_DROPBOX_FOLDER` | `/VolumeProfile` | Dropbox folder path |

### config.py Settings

```python
# Line 339-342
VOLUME_PROFILE_ENABLE_DROPBOX = os.getenv('VOLUME_PROFILE_ENABLE_DROPBOX', 'true').lower() == 'true'
VOLUME_PROFILE_DROPBOX_TOKEN = os.getenv('VOLUME_PROFILE_DROPBOX_TOKEN', '')
VOLUME_PROFILE_DROPBOX_FOLDER = os.getenv('VOLUME_PROFILE_DROPBOX_FOLDER', '/VolumeProfile')
```

---

## Testing

### Manual Test

```bash
# Test end-of-day run with Dropbox upload
cd /Users/sunildeesu/myProjects/ShortIndicator
./venv/bin/python3 volume_profile_analyzer.py --execution-time 3:25PM

# Check if report uploaded
tail -100 logs/volume_profile.log | grep -A3 "Dropbox"
```

**Expected output**:
```
Uploading volume profile report to Dropbox...
✓ Uploaded to Dropbox: /VolumeProfile/volume_profile_eod_2026-01-10.xlsx
✓ Dropbox link: https://www.dropbox.com/s/xxxxxxxx/volume_profile_eod_2026-01-10.xlsx?dl=1
Report uploaded to Dropbox: https://www.dropbox.com/s/xxxxxxxx/...
```

### Verify in Dropbox

1. Go to https://www.dropbox.com
2. Navigate to `/VolumeProfile/` folder
3. Check for report: `volume_profile_3pm_YYYYMMDD.xlsx`
4. Click "Share" → "Create link" (if not already created)
5. Copy link and test in browser

---

## Advanced Usage

### Include Dropbox Link in Telegram Alerts

Modify `telegram_notifier.py` to include Dropbox link in volume profile alerts:

```python
# In send_volume_profile_summary() method:
if dropbox_link:
    message += f"\n\n📁 Dropbox Report: {dropbox_link}"
```

### Custom Folder Structure

Organize by year/month:

```python
# In volume_profile_analyzer.py, modify _upload_to_dropbox():
from datetime import datetime

# Line 280: Change dropbox_path
dropbox_folder = config.VOLUME_PROFILE_DROPBOX_FOLDER
year_month = datetime.now().strftime('%Y/%m')
dropbox_path = f"{dropbox_folder}/{year_month}/{file_basename}"
```

### Batch Upload Historical Reports

Upload all local reports to Dropbox:

```bash
# Create script: upload_historical_reports.py
python3 upload_historical_reports.py --source data/volume_profile_reports/
```

---

## Summary

### What's Configured

✅ **Dropbox upload enabled** in `config.py`
✅ **Upload method added** to `volume_profile_analyzer.py`
✅ **Automatic trigger** after report generation
✅ **launchd automation** runs at 3:00 PM and 3:15 PM daily

### What You Need to Do

1. Create Dropbox app and generate access token
2. Add `VOLUME_PROFILE_DROPBOX_TOKEN` to `.env` file
3. Test manually once
4. Verify logs show successful upload
5. Access reports from Dropbox on any device

### Expected Outcome

- **1 report per day** automatically uploaded to Dropbox at 3:25 PM
- **Shareable link** logged for easy access
- **Complete market data** (9:15 AM - 3:25 PM)
- **No manual work** - fully automated
- **Access from anywhere** - mobile, desktop, web

---

**Volume profile reports are now backed up to Dropbox and accessible from any device!** 📊☁️
