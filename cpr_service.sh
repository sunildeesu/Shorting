#!/bin/bash
# CPR First Touch Monitor Service Manager
# Manages the launchd service for CPR first touch alert monitoring

PLIST_FILE="$HOME/Library/LaunchAgents/com.nse.cpr.monitor.plist"
SERVICE_NAME="com.nse.cpr.monitor"

case "$1" in
    start)
        echo "Starting CPR first touch monitor service..."
        launchctl load "$PLIST_FILE"
        echo "✓ Service started (runs every 60 seconds)"
        echo "  Check status with: $0 status"
        ;;

    stop)
        echo "Stopping CPR first touch monitor service..."
        launchctl unload "$PLIST_FILE"
        echo "✓ Service stopped"
        ;;

    restart)
        echo "Restarting CPR first touch monitor service..."
        launchctl unload "$PLIST_FILE" 2>/dev/null
        sleep 1
        launchctl load "$PLIST_FILE"
        echo "✓ Service restarted"
        ;;

    status)
        echo "Checking CPR first touch monitor service status..."
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
        tail -50 logs/cpr-stdout.log 2>/dev/null || echo "No stdout logs yet"
        echo ""
        echo "--- STDERR ---"
        tail -50 logs/cpr-stderr.log 2>/dev/null || echo "No stderr logs yet"
        ;;

    tail)
        echo "Tailing logs (press Ctrl+C to exit)..."
        tail -f logs/cpr-stdout.log logs/cpr-stderr.log
        ;;

    enable)
        echo "Enabling CPR alerts in config..."
        if grep -q "^ENABLE_CPR_ALERTS=" .env 2>/dev/null; then
            sed -i '' 's/^ENABLE_CPR_ALERTS=.*/ENABLE_CPR_ALERTS=true/' .env
        else
            echo "ENABLE_CPR_ALERTS=true" >> .env
        fi
        echo "✓ CPR alerts enabled"
        echo "  Restart service to apply: $0 restart"
        ;;

    disable)
        echo "Disabling CPR alerts in config..."
        if grep -q "^ENABLE_CPR_ALERTS=" .env 2>/dev/null; then
            sed -i '' 's/^ENABLE_CPR_ALERTS=.*/ENABLE_CPR_ALERTS=false/' .env
        else
            echo "ENABLE_CPR_ALERTS=false" >> .env
        fi
        echo "✓ CPR alerts disabled"
        echo "  Restart service to apply: $0 restart"
        ;;

    dry-run)
        echo "Enabling dry-run mode (testing without alerts)..."
        if grep -q "^CPR_DRY_RUN_MODE=" .env 2>/dev/null; then
            sed -i '' 's/^CPR_DRY_RUN_MODE=.*/CPR_DRY_RUN_MODE=true/' .env
        else
            echo "CPR_DRY_RUN_MODE=true" >> .env
        fi
        echo "✓ Dry-run mode enabled (no Telegram alerts will be sent)"
        echo "  Restart service to apply: $0 restart"
        ;;

    production)
        echo "Disabling dry-run mode (production mode)..."
        if grep -q "^CPR_DRY_RUN_MODE=" .env 2>/dev/null; then
            sed -i '' 's/^CPR_DRY_RUN_MODE=.*/CPR_DRY_RUN_MODE=false/' .env
        else
            echo "CPR_DRY_RUN_MODE=false" >> .env
        fi
        echo "✓ Production mode enabled (Telegram alerts will be sent)"
        echo "  Restart service to apply: $0 restart"
        ;;

    state)
        echo "CPR State File:"
        if [ -f data/cpr_state.json ]; then
            python3 -m json.tool data/cpr_state.json 2>/dev/null || cat data/cpr_state.json
        else
            echo "No state file found (will be created on first run)"
        fi
        ;;

    *)
        echo "CPR First Touch Monitor Service Manager"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs|tail|enable|disable|dry-run|production|state}"
        echo ""
        echo "Service Commands:"
        echo "  start       - Start the CPR monitor service (runs every 60 seconds)"
        echo "  stop        - Stop the CPR monitor service"
        echo "  restart     - Restart the service"
        echo "  status      - Check if service is running"
        echo ""
        echo "Logging Commands:"
        echo "  logs        - Show recent logs (last 50 lines)"
        echo "  tail        - Tail logs in real-time"
        echo "  state       - View current CPR state file"
        echo ""
        echo "Configuration Commands:"
        echo "  enable      - Enable CPR alerts in config (.env)"
        echo "  disable     - Disable CPR alerts in config (.env)"
        echo "  dry-run     - Enable dry-run mode (testing without alerts)"
        echo "  production  - Disable dry-run mode (enable alerts)"
        echo ""
        echo "Examples:"
        echo "  $0 start           # Start the service"
        echo "  $0 status          # Check status"
        echo "  $0 logs            # View recent logs"
        echo "  $0 tail            # Watch logs live"
        echo "  $0 state           # View CPR state"
        echo "  $0 dry-run         # Test without sending alerts"
        echo "  $0 production      # Enable alert sending"
        exit 1
        ;;
esac
