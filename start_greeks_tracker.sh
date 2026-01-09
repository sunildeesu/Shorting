#!/bin/bash
#
# Greeks Difference Tracker - Daily Launcher
# Automatically runs at 9:14 AM on weekdays
# Continues until 3:30 PM market close
#

set -e

# Configuration
PROJECT_DIR="/Users/sunildeesu/myProjects/ShortIndicator"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
TRACKER_SCRIPT="$PROJECT_DIR/greeks_difference_tracker.py"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/greeks_tracker_$(date +%Y%m%d).log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Check if it's a weekday (Monday=1, Sunday=7)
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" -gt 5 ]; then
    log "❌ Today is weekend (day $DAY_OF_WEEK). Skipping Greeks tracker."
    exit 0
fi

log "=========================================="
log "🚀 Starting Greeks Difference Tracker"
log "=========================================="
log "Project: $PROJECT_DIR"
log "Python: $VENV_PYTHON"
log "Day of week: $DAY_OF_WEEK (weekday)"
log ""

# Change to project directory
cd "$PROJECT_DIR"

# Check if virtual environment exists
if [ ! -f "$VENV_PYTHON" ]; then
    log "❌ Virtual environment not found at $VENV_PYTHON"
    exit 1
fi

# Check if tracker script exists
if [ ! -f "$TRACKER_SCRIPT" ]; then
    log "❌ Tracker script not found at $TRACKER_SCRIPT"
    exit 1
fi

# Check if .env file exists (for Kite credentials)
if [ ! -f "$PROJECT_DIR/.env" ]; then
    log "⚠️  Warning: .env file not found. Make sure credentials are configured."
fi

# Run the tracker
log "✓ Launching Greeks Difference Tracker..."
log "✓ Tracker will run from 9:15 AM to 3:30 PM"
log "✓ Updates every 15 minutes"
log ""

# Execute tracker with --monitor flag (runs from 9:15 AM to 3:30 PM automatically)
"$VENV_PYTHON" "$TRACKER_SCRIPT" --monitor 2>&1 | tee -a "$LOG_FILE"

# Capture exit code
EXIT_CODE=$?

log ""
log "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    log "✅ Greeks tracker completed successfully"
else
    log "❌ Greeks tracker exited with error code: $EXIT_CODE"
fi
log "=========================================="

exit $EXIT_CODE
