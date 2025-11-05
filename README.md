# NSE Stock Drop Monitor

Real-time monitoring system for NSE F&O stocks with Telegram alerts for significant price drops. Features three-tier detection (10-min drops, 30-min gradual drops, volume spikes), automatic token management, and runs every 5 minutes during market hours.

## 🚀 Quick Status Check

**Want to know if the system is running right now?**

```bash
./check_status.py
```

Shows everything: monitoring status, last run, market status, token validity, cron jobs, and any errors.

## Features

### Three-Tier Drop Detection

1. **10-Minute Drops** (≥2%) - Catches sudden price drops
2. **30-Minute Gradual Drops** (≥3%) - Detects slow bleeding
3. **Volume Spike Drops** (≥1.5% + 3x volume) - Identifies unusual trading activity

### Additional Features

- 📊 **191 NSE F&O Stocks** monitored in real-time
- 💊 **Pharma Stock Flagging** - Special alerts for pharmaceutical stocks
- 🔄 **7-Snapshot Sliding Window** - Accurate price history tracking
- 📱 **Telegram Alerts** - Instant notifications with detailed info
- ⏰ **Automatic Token Management** - Daily reminders and validation
- 🔍 **Historical Backtesting** - Validate detection logic on past data
- 📈 **Market Hours Aware** - Only runs during trading hours (9:30 AM - 3:25 PM IST)

## Quick Start

### Daily Routine (Every Morning Before 9:30 AM)

```bash
# 1. Refresh your Kite Connect token
./generate_kite_token.py

# 2. Check system status
./check_status.py
```

That's it! The monitoring runs automatically every 5 minutes during market hours.

### Common Commands

| Command | Purpose |
|---------|---------|
| `./check_status.py` | **Check if system is running** |
| `./generate_kite_token.py` | Refresh token (daily) |
| `./token_manager.py` | Check token expiry |
| `./start_monitoring.sh` | Install cron job (one-time) |
| `tail -f logs/stock_monitor.log` | View live logs |

### Documentation

- **[QUICK_START.md](QUICK_START.md)** - Essential commands and workflow
- **[TOKEN_MANAGEMENT.md](TOKEN_MANAGEMENT.md)** - Complete token guide
- **[TEST_RESULTS.md](TEST_RESULTS.md)** - System test results

## Prerequisites

- Python 3.8 or higher
- Kite Connect API credentials (Zerodha account)
- Telegram bot token and channel
- macOS or Linux
- Active internet connection during market hours

## Installation

### 1. Clone or Navigate to Project

```bash
cd /Users/sunildeesu/myProjects/ShortIndicator
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## Telegram Bot Setup

### Step 1: Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Start a chat and send `/newbot`
3. Follow the prompts:
   - Choose a name for your bot (e.g., "NSE Stock Monitor")
   - Choose a username (must end in 'bot', e.g., "nse_stock_alert_bot")
4. BotFather will give you a **Bot Token** - save this! It looks like:
   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz1234567890
   ```

### Step 2: Create a Telegram Channel

1. In Telegram, create a new channel:
   - Click on hamburger menu → "New Channel"
   - Name it (e.g., "NSE Stock Alerts")
   - Make it **Private** or **Public** (your choice)
2. Add your bot as an **administrator** to the channel:
   - Go to channel settings → Administrators → Add Administrator
   - Search for your bot's username and add it

### Step 3: Get Channel ID

**Method 1: Using Web Telegram**
1. Open https://web.telegram.org in your browser
2. Navigate to your channel
3. Look at the URL - it will be like: `https://web.telegram.org/k/#-1001234567890`
4. The channel ID is the number after `#` (including the minus sign): `-1001234567890`

**Method 2: Using API**
1. Send a message to your channel
2. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. Look for your channel in the JSON response - find the `"chat":{"id":...}` value

### Step 4: Configure Environment

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your credentials:
   ```bash
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz1234567890
   TELEGRAM_CHANNEL_ID=-1001234567890
   DROP_THRESHOLD_PERCENT=2.0
   ```

## Testing

### Test the Script Manually

```bash
# Activate virtual environment
source venv/bin/activate

# Run the monitor
python3 main.py
```

**Note:** The script will only monitor stocks if:
- Current day is Monday-Friday (trading day)
- Current time is between 9:30 AM - 3:25 PM IST

To test outside market hours, you can temporarily modify `market_utils.py` to always return `True` for `is_market_open()`.

### Send Test Telegram Message

```python
# In Python shell
from telegram_notifier import TelegramNotifier

notifier = TelegramNotifier()
notifier.send_test_message()
```

## Launchd Setup (Automated Scheduling)

### Step 1: Update Plist File

The `com.nse.stockmonitor.plist` file is already configured. Verify the paths are correct:

- Python path: `/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3`
- Script path: `/Users/sunildeesu/myProjects/ShortIndicator/main.py`
- Working directory: `/Users/sunildeesu/myProjects/ShortIndicator`

### Step 2: Install the Launch Agent

```bash
# Copy plist to LaunchAgents directory
cp com.nse.stockmonitor.plist ~/Library/LaunchAgents/

# Load the launch agent
launchctl load ~/Library/LaunchAgents/com.nse.stockmonitor.plist

# Verify it's loaded
launchctl list | grep nse.stockmonitor
```

### Step 3: Manage the Service

```bash
# Start the service
launchctl start com.nse.stockmonitor

# Stop the service
launchctl stop com.nse.stockmonitor

# Unload the service (to disable)
launchctl unload ~/Library/LaunchAgents/com.nse.stockmonitor.plist

# Reload after making changes
launchctl unload ~/Library/LaunchAgents/com.nse.stockmonitor.plist
launchctl load ~/Library/LaunchAgents/com.nse.stockmonitor.plist
```

## How It Works

### Price Tracking Logic

1. **First Run (9:30 AM):**
   - Fetches prices for all F&O stocks
   - Stores as "current" snapshot
   - No comparison yet (need 2 snapshots)

2. **Second Run (9:35 AM):**
   - Fetches new prices
   - Previous "current" becomes "previous"
   - New prices become "current"
   - Compares: If drop > 2%, sends alert

3. **Subsequent Runs (Every 5 min):**
   - Continues sliding window approach
   - Always compares last 2 snapshots
   - Sends alerts for any drops > threshold

### Alert Format

```
🔴 ALERT: Stock Drop Detected

📊 Stock: RELIANCE
📉 Drop: 2.45%
💰 Previous Price: ₹2,450.00
💸 Current Price: ₹2,390.00
📊 Change: ₹60.00
```

## Project Structure

```
ShortIndicator/
├── main.py                      # Entry point
├── stock_monitor.py             # Stock monitoring logic
├── price_cache.py               # Price storage (2-snapshot window)
├── telegram_notifier.py         # Telegram integration
├── market_utils.py              # Market hours/day validation
├── config.py                    # Configuration
├── fo_stocks.json               # F&O stock list
├── requirements.txt             # Python dependencies
├── com.nse.stockmonitor.plist  # Launchd configuration
├── .env                        # Environment variables (create this)
├── .env.example                # Environment template
├── data/
│   └── price_cache.json        # Cached prices (auto-generated)
└── logs/
    ├── stock_monitor.log       # Application logs
    ├── launchd-stdout.log      # Launchd output
    └── launchd-stderr.log      # Launchd errors
```

## Logs and Monitoring

### View Application Logs

```bash
# Real-time monitoring
tail -f logs/stock_monitor.log

# View recent logs
tail -100 logs/stock_monitor.log
```

### View Launchd Logs

```bash
# Standard output
tail -f logs/launchd-stdout.log

# Standard error
tail -f logs/launchd-stderr.log
```

## Configuration

### Adjust Drop Threshold

Edit `.env`:
```bash
DROP_THRESHOLD_PERCENT=3.0  # Alert for drops > 3%
```

### Modify Market Hours

Edit `config.py`:
```python
MARKET_START_HOUR = 9
MARKET_START_MINUTE = 30
MARKET_END_HOUR = 15
MARKET_END_MINUTE = 25
```

### Change Check Interval

Edit `com.nse.stockmonitor.plist`:
```xml
<key>StartInterval</key>
<integer>600</integer>  <!-- 10 minutes = 600 seconds -->
```

Then reload:
```bash
launchctl unload ~/Library/LaunchAgents/com.nse.stockmonitor.plist
launchctl load ~/Library/LaunchAgents/com.nse.stockmonitor.plist
```

## Troubleshooting

### No Alerts Received

1. Check if market is open:
   ```bash
   python3 -c "from market_utils import get_market_status; print(get_market_status())"
   ```

2. Verify Telegram credentials:
   ```bash
   cat .env
   ```

3. Test Telegram connection:
   ```python
   from telegram_notifier import TelegramNotifier
   TelegramNotifier().send_test_message()
   ```

### Launchd Not Running

1. Check if loaded:
   ```bash
   launchctl list | grep nse.stockmonitor
   ```

2. Check logs:
   ```bash
   tail -50 logs/launchd-stderr.log
   ```

3. Verify Python path:
   ```bash
   which python3  # Should match plist file
   ```

### Price Fetch Errors

- Yahoo Finance may have rate limits
- Check internet connection
- Verify stock symbols in `fo_stocks.json` have valid data

### Permission Issues

```bash
# Ensure logs directory is writable
chmod 755 logs/
chmod 755 data/

# Ensure script is executable
chmod +x main.py
```

## Limitations

- Only monitors on weekdays (does not account for NSE holidays like Diwali, Republic Day, etc.)
- Requires active internet connection
- Kite Connect API requires daily token refresh (valid for 24 hours)
- Monitors every 5 minutes, compares 10-minute intervals (needs 3 runs before first alert can trigger)

## Future Enhancements

- [ ] Add NSE holiday calendar integration
- [ ] Support custom stock lists via configuration
- [ ] Add support for percentage increase alerts
- [ ] Web dashboard for viewing alerts history
- [ ] Multi-threshold alerts (e.g., 2%, 5%, 10%)
- [ ] SMS alerts as backup to Telegram

## License

This project is for personal use. Use at your own risk. Not financial advice.

## Support

For issues or questions:
1. Check logs: `logs/stock_monitor.log`
2. Review this README
3. Test components individually (Telegram, price fetching, market hours)

---

**Built with Python, Yahoo Finance API, and Telegram Bot API**
