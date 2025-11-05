#!/bin/bash
# Start NSE Stock Monitoring - Installs cron job to run every 5 minutes

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MAIN_SCRIPT="$SCRIPT_DIR/main.py"
LOG_FILE="$SCRIPT_DIR/logs/stock_monitor.log"

echo "============================================================"
echo "NSE Stock Monitor - Setup"
echo "============================================================"
echo ""

# Check if main.py exists
if [ ! -f "$MAIN_SCRIPT" ]; then
    echo "❌ Error: main.py not found at $MAIN_SCRIPT"
    exit 1
fi

# Check if main.py is executable
if [ ! -x "$MAIN_SCRIPT" ]; then
    echo "📝 Making main.py executable..."
    chmod +x "$MAIN_SCRIPT"
fi

# Create logs directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/logs"
mkdir -p "$SCRIPT_DIR/data"

echo "📋 Current monitoring setup:"
echo ""

# Check if cron job already exists
CRON_ENTRY="*/5 9-15 * * 1-5 cd $SCRIPT_DIR && $MAIN_SCRIPT >> $LOG_FILE 2>&1"
EXISTING_CRON=$(crontab -l 2>/dev/null | grep -F "main.py")

if [ -n "$EXISTING_CRON" ]; then
    echo "✅ Cron job already installed:"
    echo "   $EXISTING_CRON"
    echo ""
    echo "Do you want to reinstall it? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo ""
        echo "Keeping existing cron job. Exiting."
        exit 0
    fi
    echo ""
    echo "🔄 Removing old cron job..."
    # Remove existing cron job
    (crontab -l 2>/dev/null | grep -vF "main.py") | crontab -
fi

# Install new cron job
echo "📥 Installing cron job..."
echo "   Schedule: Every 5 minutes during market hours (9:00-15:59)"
echo "   Days: Monday-Friday (trading days)"
echo ""

# Add new cron job
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

# Verify installation
if crontab -l 2>/dev/null | grep -qF "main.py"; then
    echo "✅ Cron job installed successfully!"
    echo ""
    echo "============================================================"
    echo "Monitoring Schedule"
    echo "============================================================"
    echo "Frequency: Every 5 minutes"
    echo "Hours: 9:00 AM - 3:59 PM"
    echo "Days: Monday - Friday"
    echo ""
    echo "The system will automatically:"
    echo "  ✓ Check if market is open"
    echo "  ✓ Validate Kite Connect token"
    echo "  ✓ Monitor 191 F&O stocks"
    echo "  ✓ Send Telegram alerts for drops"
    echo ""
    echo "============================================================"
    echo "Useful Commands"
    echo "============================================================"
    echo "  Check status:        ./check_status.py"
    echo "  View live logs:      tail -f logs/stock_monitor.log"
    echo "  View cron job:       crontab -l | grep main.py"
    echo "  Test manually:       ./main.py"
    echo "  Uninstall:           crontab -l | grep -v main.py | crontab -"
    echo ""
    echo "============================================================"
    echo "Next Steps"
    echo "============================================================"
    echo "1. Ensure token is valid: ./token_manager.py"
    echo "2. Check system status:   ./check_status.py"
    echo "3. Wait for market hours or test manually: ./main.py"
    echo ""
    echo "Monitoring will start automatically during next market hours!"
    echo "============================================================"
else
    echo "❌ Failed to install cron job"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check if cron is enabled on your system"
    echo "  2. Try running: crontab -l"
    echo "  3. Check system logs for cron errors"
    exit 1
fi
