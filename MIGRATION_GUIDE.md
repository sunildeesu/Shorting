# Migration Guide: Moving to a New Computer

This guide will help you set up the NSE Stock Monitor on a new computer using Git.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Step-by-Step Migration](#step-by-step-migration)
- [Post-Migration Setup](#post-migration-setup)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Software Requirements

1. **Python 3.8 or higher**
   ```bash
   python3 --version  # Should show 3.8+
   ```

2. **Git**
   ```bash
   git --version  # Should show git version
   ```

3. **pip (Python package manager)**
   ```bash
   pip3 --version
   ```

4. **macOS/Linux** (The automation scripts use bash and launchd/cron)

### Required Credentials (Have these ready)

1. **Telegram Bot Token** - From @BotFather on Telegram
2. **Telegram Channel ID** - Your private channel ID (e.g., -1001234567890)
3. **Kite Connect Credentials** (if using Kite as data source):
   - API Key
   - API Secret
   - Access Token (needs daily refresh)

---

## Step-by-Step Migration

### 1. Clone the Repository

```bash
# Navigate to your projects directory
cd ~/myProjects  # or wherever you want to install

# Clone the repository
git clone https://github.com/sunildeesu/Shorting.git ShortIndicator

# Navigate to the project directory
cd ShortIndicator
```

### 2. Create Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# You should see (venv) in your prompt
```

### 3. Install Dependencies

```bash
# Install all required Python packages
pip install -r requirements.txt

# Verify installation
pip list
```

**Expected packages:**
- nsepy==0.8
- yfinance==0.2.38
- kiteconnect==5.0.1
- requests==2.31.0
- pytz==2024.1
- pandas==2.2.1
- pandas-ta==0.4.71b0
- python-dotenv==1.0.1
- openpyxl==3.1.2

### 4. Create Environment Configuration

```bash
# Copy the example .env file
cp .env.example .env

# Edit the .env file with your credentials
nano .env  # or use your preferred editor (vim, code, etc.)
```

**Required configuration in `.env`:**
```bash
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz1234567890
TELEGRAM_CHANNEL_ID=-1001234567890

# Drop threshold (2% by default)
DROP_THRESHOLD_PERCENT=2.0

# Data Source: nsepy, yahoo, or kite
DATA_SOURCE=nsepy

# Kite Connect (only needed if DATA_SOURCE=kite)
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here
KITE_ACCESS_TOKEN=your_access_token_here

# Optional: Rate limiting
REQUEST_DELAY_SECONDS=1.0
MAX_RETRIES=3
RETRY_DELAY_SECONDS=2.0

# Optional: Enable RSI analysis
ENABLE_RSI=true

# Optional: Enable Sector Analysis
ENABLE_SECTOR_ANALYSIS=true
ENABLE_SECTOR_CONTEXT_IN_ALERTS=true
ENABLE_SECTOR_EOD_REPORT=true
```

### 5. Create Required Directories

The following directories are gitignored but needed at runtime:

```bash
# Create data subdirectories (if they don't exist)
mkdir -p data/eod_cache
mkdir -p data/eod_reports
mkdir -p data/alerts
mkdir -p data/backtest_results
mkdir -p data/test_cache
mkdir -p data/unified_cache
mkdir -p data/sector_eod_reports
mkdir -p data/sector_snapshots

# Create logs directory (if it doesn't exist)
mkdir -p logs
```

### 6. Verify File Permissions

```bash
# Ensure directories are writable
chmod 755 data/
chmod 755 logs/

# Make Python scripts executable
chmod +x main.py
chmod +x generate_kite_token.py
chmod +x check_status.py
chmod +x start_monitoring.sh
chmod +x eod_analyzer.py
```

---

## Post-Migration Setup

### 1. Test Telegram Connection

```bash
# Activate virtual environment (if not already active)
source venv/bin/activate

# Test Telegram notification
python3 -c "
from telegram_notifier import TelegramNotifier
notifier = TelegramNotifier()
result = notifier.send_test_message()
print('✅ Telegram test successful!' if result else '❌ Telegram test failed!')
"
```

**Expected:** You should receive a test message in your Telegram channel.

### 2. Test Market Status Check

```bash
python3 -c "
from market_utils import get_market_status
status = get_market_status()
print(f'Market Status: {status}')
"
```

### 3. Generate Kite Token (if using Kite as data source)

```bash
# This opens a browser for Kite login
./generate_kite_token.py

# Follow the prompts to authenticate with Zerodha
```

### 4. Run Manual Test

```bash
# Run the monitor once manually
python3 main.py

# Check the logs
tail -50 logs/stock_monitor.log
```

**Note:** If market is closed, it will exit immediately. You can temporarily modify `market_utils.py` to test outside market hours.

### 5. Set Up Automation (Optional)

#### For macOS (launchd):

```bash
# Update the plist file with your new paths
# Edit: ~/Library/LaunchAgents/com.nse.stockmonitor.plist

# Find and replace the paths in the plist:
# - Python path: /path/to/your/ShortIndicator/venv/bin/python3
# - Script path: /path/to/your/ShortIndicator/main.py
# - Working directory: /path/to/your/ShortIndicator

# Copy plist to LaunchAgents
cp com.nse.stockmonitor.plist ~/Library/LaunchAgents/

# Load the launch agent
launchctl load ~/Library/LaunchAgents/com.nse.stockmonitor.plist

# Verify it's loaded
launchctl list | grep nse.stockmonitor
```

#### For Linux (cron):

```bash
# Use the provided script
./start_monitoring.sh

# Or manually add to crontab:
crontab -e

# Add this line (runs every 5 minutes):
*/5 * * * * cd /path/to/ShortIndicator && ./venv/bin/python3 main.py >> logs/cron.log 2>&1
```

### 6. Set Up EOD Analyzer (Optional)

The EOD analyzer runs daily at 4:00 PM to analyze patterns and generate reports.

```bash
# Test EOD analyzer manually
./eod_analyzer.py

# For automation, use the provided script:
./start_eod_analyzer.sh
```

---

## Post-Setup Verification

### Check System Status

```bash
./check_status.py
```

**Expected output:**
```
=== NSE Stock Monitor Status ===

✅ System Status: Running
✅ Market Status: Open
✅ Token Status: Valid (expires in 8h 23m)
✅ Cron Job: Active
✅ Last Run: 2 minutes ago

No errors found.
```

### Monitor Real-Time Logs

```bash
# Watch the monitor logs in real-time
tail -f logs/stock_monitor.log

# Watch EOD analyzer logs
tail -f logs/eod_analyzer.log

# Watch alert updates
tail -f logs/alert_excel_updates.log
```

### Test Alert Generation

To verify the entire pipeline works:

1. Wait for market hours (9:30 AM - 3:25 PM IST on weekdays)
2. The monitor runs automatically every 5 minutes
3. If any stock drops ≥2%, you'll receive a Telegram alert
4. Check `data/alerts/alert_tracking.xlsx` for alert history

---

## Important Files to Keep Track Of

### Generated at Runtime (not in Git)

These files are created automatically but gitignored:

1. **`.env`** - Your credentials (NEVER commit this!)
2. **`data/price_cache.json`** - Price history (auto-generated)
3. **`data/alert_history.json`** - Alert deduplication
4. **`data/instrument_tokens.json`** - Kite token mappings
5. **`data/token_metadata.json`** - Token expiry tracking
6. **`data/sector_analysis_cache.json`** - Sector metrics
7. **`logs/*.log`** - All log files

### Configuration Files (in Git)

1. **`data/stock_sectors.json`** - Stock-to-sector mappings (209 stocks, 15 sectors)
2. **`data/stock_sectors_multi.json`** - Multi-sector reference from NSE
3. **`data/shares_outstanding.json`** - Market cap calculations
4. **`data/nse_indices/*.csv`** - NSE sectoral index constituents
5. **`fo_stocks.json`** - F&O stock list (191 stocks)

---

## Troubleshooting

### Issue: Telegram alerts not working

**Solution:**
```bash
# 1. Verify .env credentials
cat .env | grep TELEGRAM

# 2. Test Telegram connection
python3 -c "from telegram_notifier import TelegramNotifier; TelegramNotifier().send_test_message()"

# 3. Check if bot is admin in channel
# Go to Telegram channel → Settings → Administrators → Verify bot is listed
```

### Issue: "No module named 'xyz'"

**Solution:**
```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Issue: Kite token expired

**Solution:**
```bash
# Refresh token (needs to be done daily before market opens)
./generate_kite_token.py

# Check token status
./token_manager.py
```

### Issue: Launchd/cron not running

**macOS (launchd):**
```bash
# Check if loaded
launchctl list | grep nse.stockmonitor

# Check logs
tail -50 ~/Library/Logs/com.nse.stockmonitor.log

# Reload
launchctl unload ~/Library/LaunchAgents/com.nse.stockmonitor.plist
launchctl load ~/Library/LaunchAgents/com.nse.stockmonitor.plist
```

**Linux (cron):**
```bash
# Check crontab
crontab -l

# Check cron logs
tail -50 logs/cron.log
```

### Issue: Permission denied errors

**Solution:**
```bash
# Fix directory permissions
chmod 755 data/ logs/

# Fix script permissions
chmod +x *.py *.sh
```

### Issue: "Market is closed" message

This is normal! The monitor only runs during:
- Monday to Friday (excludes weekends)
- 9:30 AM to 3:25 PM IST
- Does NOT check for NSE holidays (Diwali, Republic Day, etc.)

To test outside market hours, temporarily modify `config.py`:
```python
# For testing only - comment this out after testing
MARKET_START_HOUR = 0
MARKET_END_HOUR = 23
```

---

## Updating the Code

When you want to pull latest changes from the repository:

```bash
# Save any local changes first
git stash

# Pull latest code
git pull origin main

# Restore your changes (if any)
git stash pop

# Update dependencies (if requirements.txt changed)
pip install -r requirements.txt

# Restart automation
launchctl unload ~/Library/LaunchAgents/com.nse.stockmonitor.plist
launchctl load ~/Library/LaunchAgents/com.nse.stockmonitor.plist
```

---

## Daily Routine (Every Trading Day)

```bash
# 1. Before 9:30 AM - Refresh Kite token (if using Kite)
./generate_kite_token.py

# 2. Check system status
./check_status.py

# 3. Monitor logs (optional)
tail -f logs/stock_monitor.log
```

That's it! The system runs automatically throughout the trading day.

---

## Additional Resources

- **README.md** - Full project documentation
- **QUICK_START.md** - Essential commands and workflow
- **TOKEN_MANAGEMENT.md** - Complete Kite token management guide
- **SECTOR_EOD_REPORT_GUIDE.md** - Sector analysis documentation
- **TEST_RESULTS.md** - System test results and backtesting

---

## Security Considerations

1. **Never commit `.env` file** - Contains sensitive credentials
2. **Never share your Telegram bot token** - Anyone with it can send messages
3. **Never share Kite API credentials** - They have access to your trading account
4. **Keep `data/alerts/*.xlsx` private** - Contains your trading patterns
5. **Use strong passwords** for Zerodha account

---

## Need Help?

1. Check the logs: `logs/stock_monitor.log`
2. Run status check: `./check_status.py`
3. Review this guide and README.md
4. Test individual components (Telegram, market status, price fetching)

---

**Built with Python, NSE API, Kite Connect, and Telegram Bot API**

*Last Updated: November 2025*
