#!/bin/bash
# 1-Minute Alert Monitor Service Manager
# Manages the launchd service for 1-minute alert monitoring

PLIST_FILE="$HOME/Library/LaunchAgents/com.nse.onemin.monitor.plist"
SERVICE_NAME="com.nse.onemin.monitor"

case "$1" in
    start)
        echo "Starting 1-min alert monitor service..."
        launchctl load "$PLIST_FILE"
        echo "✓ Service started (runs every 60 seconds)"
        echo "  Check status with: $0 status"
        ;;

    stop)
        echo "Stopping 1-min alert monitor service..."
        launchctl unload "$PLIST_FILE"
        echo "✓ Service stopped"
        ;;

    restart)
        echo "Restarting 1-min alert monitor service..."
        launchctl unload "$PLIST_FILE" 2>/dev/null
        sleep 1
        launchctl load "$PLIST_FILE"
        echo "✓ Service restarted"
        ;;

    status)
        echo "Checking 1-min alert monitor service status..."
        if launchctl list | grep -q "$SERVICE_NAME"; then
            echo "✓ Service is RUNNING"
            launchctl list | grep "$SERVICE_NAME"
        else
            echo "✗ Service is NOT running"
        fi
        ;;

    logs)
        echo "Showing recent logs (last 50 lines)..."
        echo "--- STDOUT ---"
        tail -50 logs/onemin-stdout.log 2>/dev/null || echo "No stdout logs yet"
        echo ""
        echo "--- STDERR ---"
        tail -50 logs/onemin-stderr.log 2>/dev/null || echo "No stderr logs yet"
        ;;

    tail)
        echo "Tailing logs (press Ctrl+C to exit)..."
        tail -f logs/onemin-stdout.log logs/onemin-stderr.log
        ;;

    enable)
        echo "Enabling 1-min alerts in config..."
        if grep -q "^ENABLE_1MIN_ALERTS=" .env 2>/dev/null; then
            sed -i '' 's/^ENABLE_1MIN_ALERTS=.*/ENABLE_1MIN_ALERTS=true/' .env
        else
            echo "ENABLE_1MIN_ALERTS=true" >> .env
        fi
        echo "✓ 1-min alerts enabled"
        echo "  Restart service to apply: $0 restart"
        ;;

    disable)
        echo "Disabling 1-min alerts in config..."
        if grep -q "^ENABLE_1MIN_ALERTS=" .env 2>/dev/null; then
            sed -i '' 's/^ENABLE_1MIN_ALERTS=.*/ENABLE_1MIN_ALERTS=false/' .env
        else
            echo "ENABLE_1MIN_ALERTS=false" >> .env
        fi
        echo "✓ 1-min alerts disabled"
        echo "  Restart service to apply: $0 restart"
        ;;

    *)
        echo "1-Minute Alert Monitor Service Manager"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs|tail|enable|disable}"
        echo ""
        echo "Commands:"
        echo "  start    - Start the 1-min monitor service (runs every 60 seconds)"
        echo "  stop     - Stop the 1-min monitor service"
        echo "  restart  - Restart the service"
        echo "  status   - Check if service is running"
        echo "  logs     - Show recent logs (last 50 lines)"
        echo "  tail     - Tail logs in real-time"
        echo "  enable   - Enable 1-min alerts in config (.env)"
        echo "  disable  - Disable 1-min alerts in config (.env)"
        echo ""
        echo "Examples:"
        echo "  $0 start        # Start the service"
        echo "  $0 status       # Check status"
        echo "  $0 logs         # View recent logs"
        echo "  $0 tail         # Watch logs live"
        echo "  $0 disable      # Turn off 1-min alerts"
        exit 1
        ;;
esac
