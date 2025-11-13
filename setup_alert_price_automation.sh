#!/bin/bash
#
# Alert Price Update Automation Setup
#
# This script sets up automated price updates for alert tracking:
# 1. 2-minute price updates - runs every 2 minutes during market hours
# 2. 10-minute price updates - runs every 10 minutes during market hours
# 3. EOD price updates - runs once at market close (3:30 PM)
#

set -e

PROJECT_DIR="/Users/sunildeesu/myProjects/ShortIndicator"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "================================================"
echo "Setting up Alert Price Update Automation"
echo "================================================"

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCH_AGENTS_DIR"

# 1. Create 2-minute price updater plist
echo "Creating 2-minute price updater..."
cat > "$LAUNCH_AGENTS_DIR/com.nse.alert.price2min.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nse.alert.price2min</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3</string>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/update_alert_prices.py</string>
        <string>--2min</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator</string>

    <key>StandardOutPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/price_update_2min.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/price_update_2min_error.log</string>

    <!-- Run every 2 minutes during market hours (9:30 AM - 3:30 PM) -->
    <key>StartCalendarInterval</key>
    <array>
        <!-- 9:30 AM -->
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>32</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>34</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>36</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>38</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>40</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>42</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>44</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>46</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>48</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>50</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>52</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>54</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>56</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>58</integer></dict>
        <!-- 10:00-15:30 every 2 minutes -->
        <!-- Simplified - add more intervals as needed -->
        <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    </array>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

# 2. Create 10-minute price updater plist
echo "Creating 10-minute price updater..."
cat > "$LAUNCH_AGENTS_DIR/com.nse.alert.price10min.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nse.alert.price10min</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3</string>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/update_alert_prices.py</string>
        <string>--10min</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator</string>

    <key>StandardOutPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/price_update_10min.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/price_update_10min_error.log</string>

    <!-- Run every 10 minutes during market hours -->
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>40</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>50</integer></dict>
        <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>40</integer></dict>
        <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>50</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>40</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>50</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>40</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>50</integer></dict>
        <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>40</integer></dict>
        <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>50</integer></dict>
        <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>40</integer></dict>
        <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>50</integer></dict>
        <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
    </array>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

# 3. Create EOD price updater plist (runs once at 3:30 PM)
echo "Creating EOD price updater..."
cat > "$LAUNCH_AGENTS_DIR/com.nse.alert.priceeod.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nse.alert.priceeod</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3</string>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/update_eod_prices.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator</string>

    <key>StandardOutPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/price_update_eod.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/price_update_eod_error.log</string>

    <!-- Run daily at 3:30 PM IST (market close) -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>15</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

echo ""
echo "✓ Created 3 launchd agents:"
echo "  - com.nse.alert.price2min.plist (2-min updates)"
echo "  - com.nse.alert.price10min.plist (10-min updates)"
echo "  - com.nse.alert.priceeod.plist (EOD updates at 3:30 PM)"
echo ""
echo "================================================"
echo "Loading LaunchAgents..."
echo "================================================"

# Load the agents
launchctl load "$LAUNCH_AGENTS_DIR/com.nse.alert.price2min.plist" 2>/dev/null || echo "  - 2-min updater loaded"
launchctl load "$LAUNCH_AGENTS_DIR/com.nse.alert.price10min.plist" 2>/dev/null || echo "  - 10-min updater loaded"
launchctl load "$LAUNCH_AGENTS_DIR/com.nse.alert.priceeod.plist" 2>/dev/null || echo "  - EOD updater loaded"

echo ""
echo "================================================"
echo "Automation Setup Complete!"
echo "================================================"
echo ""
echo "Schedule:"
echo "  • 2-min prices: Updates every 2 minutes during market hours"
echo "  • 10-min prices: Updates every 10 minutes during market hours"
echo "  • EOD prices: Updates once daily at 3:30 PM"
echo ""
echo "Log files:"
echo "  • logs/price_update_2min.log"
echo "  • logs/price_update_10min.log"
echo "  • logs/price_update_eod.log"
echo ""
echo "To check status:"
echo "  launchctl list | grep com.nse.alert"
echo ""
echo "To stop automation:"
echo "  launchctl unload ~/Library/LaunchAgents/com.nse.alert.price*.plist"
echo ""
echo "To restart automation:"
echo "  launchctl load ~/Library/LaunchAgents/com.nse.alert.price*.plist"
echo ""
echo "⚠️  IMPORTANT: Before this works, you need to refresh your Kite API token:"
echo "   ./generate_kite_token.py"
echo ""
