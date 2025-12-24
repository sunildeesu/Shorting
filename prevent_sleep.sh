#!/bin/bash
# Prevent Mac from sleeping during market hours (9:00 AM - 4:00 PM IST on weekdays)
# This ensures all monitoring scripts run without interruption

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/prevent_sleep.log"
PID_FILE="$SCRIPT_DIR/data/caffeinate.pid"

# Create directories if they don't exist
mkdir -p "$SCRIPT_DIR/logs"
mkdir -p "$SCRIPT_DIR/data"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Check if it's a weekday (Monday=1, Friday=5)
day_of_week=$(date +%u)
if [ "$day_of_week" -gt 5 ]; then
    log "Weekend detected - not preventing sleep"
    exit 0
fi

# Check if it's market hours (9:00 AM - 4:00 PM)
current_hour=$(date +%H)
if [ "$current_hour" -lt 9 ] || [ "$current_hour" -ge 16 ]; then
    log "Outside market hours ($current_hour:00) - not preventing sleep"

    # If caffeinate is running, kill it
    if [ -f "$PID_FILE" ]; then
        caffeinate_pid=$(cat "$PID_FILE")
        if ps -p "$caffeinate_pid" > /dev/null 2>&1; then
            log "Stopping caffeinate (PID: $caffeinate_pid)"
            kill "$caffeinate_pid" 2>/dev/null
            rm -f "$PID_FILE"
        fi
    fi
    exit 0
fi

# Check if caffeinate is already running
if [ -f "$PID_FILE" ]; then
    caffeinate_pid=$(cat "$PID_FILE")
    if ps -p "$caffeinate_pid" > /dev/null 2>&1; then
        log "Caffeinate already running (PID: $caffeinate_pid)"
        exit 0
    else
        log "Stale PID file found, removing..."
        rm -f "$PID_FILE"
    fi
fi

# Start caffeinate to prevent sleep
log "Starting caffeinate to prevent sleep during market hours"

# caffeinate options:
# -d: Prevent display from sleeping
# -i: Prevent system from idle sleeping
# -s: Prevent system from sleeping when on AC power
caffeinate -dis &
caffeinate_pid=$!

echo "$caffeinate_pid" > "$PID_FILE"
log "Caffeinate started (PID: $caffeinate_pid)"
log "System will not sleep until 4:00 PM or script is stopped"
