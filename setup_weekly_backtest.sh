#!/bin/bash
# Setup Weekly Backtest Automation
# Runs every Friday at 4:00 PM (after market hours)

echo "====================================================================="
echo "Setting up Weekly Backtest Automation"
echo "====================================================================="

# Get the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Project directory: $PROJECT_DIR"

# Create launchd plist for macOS
PLIST_FILE="$HOME/Library/LaunchAgents/com.sunildeesu.weeklybacktest.plist"

echo ""
echo "Creating launchd configuration..."

cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sunildeesu.weeklybacktest</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT_DIR/venv/bin/python3</string>
        <string>$PROJECT_DIR/weekly_backtest_runner.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>5</integer>
        <key>Hour</key>
        <integer>16</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/weekly_backtest.log</string>

    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/weekly_backtest_error.log</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

echo "✅ Created plist file: $PLIST_FILE"

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"
echo "✅ Created logs directory"

# Load the plist
launchctl unload "$PLIST_FILE" 2>/dev/null
launchctl load "$PLIST_FILE"

if [ $? -eq 0 ]; then
    echo "✅ Successfully loaded weekly backtest automation"
    echo ""
    echo "Configuration:"
    echo "  - Runs: Every Friday at 4:00 PM (after market hours)"
    echo "  - Script: $PROJECT_DIR/weekly_backtest_runner.py"
    echo "  - Logs: $PROJECT_DIR/logs/weekly_backtest.log"
    echo ""
    echo "To test manually, run:"
    echo "  ./venv/bin/python3 weekly_backtest_runner.py"
    echo ""
    echo "To check status:"
    echo "  launchctl list | grep weeklybacktest"
    echo ""
    echo "To unload (disable):"
    echo "  launchctl unload $PLIST_FILE"
else
    echo "❌ Failed to load automation"
    exit 1
fi

echo "====================================================================="
echo "Setup Complete!"
echo "====================================================================="
