#!/bin/bash
# Setup Daily Token Reminder
# This script installs a launchd job that checks token validity every day at 8:00 AM

PLIST_SOURCE="com.nse.token.reminder.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.nse.token.reminder.plist"

echo "============================================================"
echo "Kite Connect Token Reminder - Installation"
echo "============================================================"
echo ""

# Check if plist file exists
if [ ! -f "$PLIST_SOURCE" ]; then
    echo "❌ Error: $PLIST_SOURCE not found"
    exit 1
fi

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$HOME/Library/LaunchAgents"

# Copy plist file
echo "📋 Copying plist file to LaunchAgents..."
cp "$PLIST_SOURCE" "$PLIST_DEST"

# Unload existing job (if any)
echo "🔄 Unloading existing job (if any)..."
launchctl unload "$PLIST_DEST" 2>/dev/null || true

# Load the job
echo "✅ Loading new job..."
launchctl load "$PLIST_DEST"

# Check if loaded successfully
if launchctl list | grep -q "com.nse.token.reminder"; then
    echo ""
    echo "============================================================"
    echo "✅ Installation Successful!"
    echo "============================================================"
    echo ""
    echo "The daily token reminder is now active."
    echo "It will run every day at 8:00 AM to check token validity."
    echo ""
    echo "Useful Commands:"
    echo "  - Test now:        python3 check_token.py"
    echo "  - Check status:    launchctl list | grep com.nse.token.reminder"
    echo "  - View logs:       tail -f logs/token_reminder.log"
    echo "  - Uninstall:       launchctl unload ~/Library/LaunchAgents/com.nse.token.reminder.plist"
    echo "                     rm ~/Library/LaunchAgents/com.nse.token.reminder.plist"
    echo ""
    echo "============================================================"
else
    echo ""
    echo "❌ Installation failed. Check logs for errors."
    exit 1
fi
