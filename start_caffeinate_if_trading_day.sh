#!/bin/bash
# Start caffeinate only if it's a trading day (not weekend, not NSE holiday)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/caffeinate-control.log"

# Create log directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/logs"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "Caffeinate Control - Checking if trading day"

# Check if it's a trading day using Python market_utils
cd "$SCRIPT_DIR"

IS_TRADING_DAY=$("$SCRIPT_DIR/venv/bin/python3" -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from market_utils import is_trading_day
print('true' if is_trading_day() else 'false')
" 2>/dev/null)

if [ "$IS_TRADING_DAY" != "true" ]; then
    log "Not a trading day (weekend or NSE holiday) - caffeinate will NOT start"
    log "=========================================="
    exit 0
fi

log "Trading day confirmed - starting caffeinate until 6:30 PM"

# Start caffeinate in background
# -d: Prevent display from sleeping
# -i: Prevent system from idle sleeping
# -s: Prevent system from sleeping when on AC power
/usr/bin/caffeinate -dis &
CAFFEINATE_PID=$!

log "Caffeinate started with PID: $CAFFEINATE_PID"
log "Will stop automatically at 6:30 PM"

# Function to check if we should stop
should_stop() {
    CURRENT_HOUR=$(date +%H)
    CURRENT_MIN=$(date +%M)

    # Stop if time >= 18:30 (6:30 PM)
    if [ "$CURRENT_HOUR" -gt 18 ]; then
        return 0  # Stop
    elif [ "$CURRENT_HOUR" -eq 18 ] && [ "$CURRENT_MIN" -ge 30 ]; then
        return 0  # Stop
    else
        return 1  # Continue
    fi
}

# Monitor loop - check every minute
while true; do
    # Check if caffeinate is still running
    if ! ps -p $CAFFEINATE_PID > /dev/null 2>&1; then
        log "Caffeinate process ended unexpectedly"
        break
    fi

    # Check if we should stop
    if should_stop; then
        log "Time is now $(date '+%H:%M') - stopping caffeinate"
        kill $CAFFEINATE_PID 2>/dev/null
        log "✅ Caffeinate stopped successfully"
        log "=========================================="
        break
    fi

    # Wait 60 seconds before next check
    sleep 60
done

exit 0
