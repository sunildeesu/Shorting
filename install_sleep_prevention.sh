#!/bin/bash
# Install/Update Sleep Prevention LaunchAgent

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SOURCE="$SCRIPT_DIR/launchd_agents/com.nse.prevent.sleep.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.nse.prevent.sleep.plist"

echo "=========================================="
echo "Sleep Prevention LaunchAgent Installer"
echo "=========================================="
echo ""

# Check if source plist exists
if [ ! -f "$PLIST_SOURCE" ]; then
    echo "❌ Error: Source plist not found at $PLIST_SOURCE"
    exit 1
fi

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$HOME/Library/LaunchAgents"

# Check if already installed
if [ -f "$PLIST_DEST" ]; then
    echo "⚠️  LaunchAgent already installed. Updating..."

    # Unload existing agent
    echo "   Unloading existing agent..."
    launchctl unload "$PLIST_DEST" 2>/dev/null
fi

# Copy plist file
echo "📋 Copying plist file..."
cp "$PLIST_SOURCE" "$PLIST_DEST"

# Set proper permissions
chmod 644 "$PLIST_DEST"

# Load the agent
echo "🚀 Loading LaunchAgent..."
launchctl load "$PLIST_DEST"

# Verify installation
if launchctl list | grep -q "com.nse.prevent.sleep"; then
    echo ""
    echo "✅ Sleep prevention LaunchAgent installed successfully!"
    echo ""
    echo "📋 Details:"
    echo "   - Trigger: 9:00 AM (Mon-Fri)"
    echo "   - Holiday Check: Uses NSE holiday calendar"
    echo "   - Duration: 7 hours (until 4:00 PM) on trading days only"
    echo "   - Prevents: Display sleep, idle sleep, AC sleep"
    echo ""
    echo "🔍 Verification:"
    echo "   Check status:     launchctl list | grep prevent.sleep"
    echo "   Check process:    ps aux | grep caffeinate"
    echo "   Check decision:   tail -20 logs/caffeinate-control.log"
    echo "   Check caffeinate: tail -f logs/caffeinate-stdout.log"
    echo ""
    echo "📖 Full documentation: SLEEP_PREVENTION_GUIDE.md"
else
    echo ""
    echo "❌ Error: LaunchAgent failed to load"
    echo "   Check logs: tail -20 logs/caffeinate-stderr.log"
    exit 1
fi
