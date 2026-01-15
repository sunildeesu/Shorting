#!/bin/bash
#
# Setup Price Action Monitor LaunchAgent
#
# Creates a LaunchAgent to run price_action_monitor.py every 5 minutes
# during market hours (9:25 AM - 3:25 PM) on weekdays
#

set -e

PROJECT_DIR="/Users/sunildeesu/myProjects/ShortIndicator"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.nse.priceaction.monitor.plist"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "=========================================="
echo "Price Action Monitor LaunchAgent Setup"
echo "=========================================="
echo ""

# Create LaunchAgents directory if needed
mkdir -p "$LAUNCH_AGENTS_DIR"

# Create the plist file
echo "Creating $PLIST_NAME..."
cat > "$PLIST_PATH" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Job Label -->
    <key>Label</key>
    <string>com.nse.priceaction.monitor</string>

    <!-- Program to run -->
    <key>ProgramArguments</key>
    <array>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3</string>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/price_action_monitor.py</string>
    </array>

    <!-- Working Directory -->
    <key>WorkingDirectory</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator</string>

    <!-- Run every 5 minutes during market hours (9:25 AM - 3:25 PM) on weekdays -->
    <!-- Total: 73 runs per day (from 9:25 to 15:25) -->
    <key>StartCalendarInterval</key>
    <array>
PLIST_EOF

# Generate schedule entries for every 5 minutes from 9:25 to 15:25
# Monday = 1, Tuesday = 2, Wednesday = 3, Thursday = 4, Friday = 5
for weekday in 1 2 3 4 5; do
    for hour in 9 10 11 12 13 14 15; do
        for minute in 0 5 10 15 20 25 30 35 40 45 50 55; do
            # Skip times before 9:25
            if [ $hour -eq 9 ] && [ $minute -lt 25 ]; then
                continue
            fi
            # Skip times after 15:25
            if [ $hour -eq 15 ] && [ $minute -gt 25 ]; then
                continue
            fi

            # Add entry
            cat >> "$PLIST_PATH" << ENTRY_EOF
        <!-- $(date -j -f "%H %M" "$hour $minute" "+%I:%M %p" 2>/dev/null || echo "$hour:$minute") on weekday $weekday -->
        <dict>
            <key>Weekday</key>
            <integer>$weekday</integer>
            <key>Hour</key>
            <integer>$hour</integer>
            <key>Minute</key>
            <integer>$minute</integer>
        </dict>
ENTRY_EOF
        done
    done
done

# Complete the plist file
cat >> "$PLIST_PATH" << 'PLIST_END'
    </array>

    <!-- Standard Output/Error Logs -->
    <key>StandardOutPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/priceaction-monitor-stdout.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/priceaction-monitor-stderr.log</string>

    <!-- Don't run on load (only at scheduled times) -->
    <key>RunAtLoad</key>
    <false/>

    <!-- Don't keep alive (run once per schedule) -->
    <key>KeepAlive</key>
    <false/>

    <!-- Environment Variables -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <!-- Process Type -->
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
PLIST_END

echo "✓ Created $PLIST_PATH"
echo ""

# Count schedule entries
SCHEDULE_COUNT=$(grep -c "<key>Weekday</key>" "$PLIST_PATH")
echo "✓ Configured $SCHEDULE_COUNT schedule entries (73 runs per weekday)"
echo ""

# Load the agent
echo "Loading LaunchAgent..."
if launchctl list | grep -q "com.nse.priceaction.monitor"; then
    echo "  Unloading existing agent..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi

launchctl load "$PLIST_PATH"
echo "✓ LaunchAgent loaded successfully"
echo ""

# Verify it's loaded
if launchctl list | grep -q "com.nse.priceaction.monitor"; then
    echo "✓ Verified: Agent is running"
else
    echo "⚠️  Warning: Agent may not be loaded correctly"
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Schedule: Every 5 minutes during market hours"
echo "  • Runs from 9:25 AM to 3:25 PM"
echo "  • Monday - Friday only"
echo "  • 73 runs per trading day"
echo ""
echo "Log files:"
echo "  • stdout: logs/priceaction-monitor-stdout.log"
echo "  • stderr: logs/priceaction-monitor-stderr.log"
echo "  • app log: logs/price_action_monitor.log"
echo ""
echo "Management commands:"
echo "  • Check status:  launchctl list | grep priceaction"
echo "  • View logs:     tail -f logs/priceaction-monitor-stdout.log"
echo "  • Unload agent:  launchctl unload ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist"
echo "  • Reload agent:  launchctl load ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist"
echo ""
echo "Next scheduled run:"
launchctl list com.nse.priceaction.monitor 2>/dev/null | grep -E "PID|Label" || echo "  (Check logs after first scheduled time)"
echo ""
