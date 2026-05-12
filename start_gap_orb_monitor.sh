#!/bin/bash
#
# Gap-and-Go ORB Monitor - Daily Launcher
# Starts at 9:12 AM on market working days (Mon-Fri)
# Monitor exits itself at 11:10 AM after EOD summary.
#

PROJECT_DIR="/Users/sunildeesu/myProjects/ShortIndicator"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
MONITOR_SCRIPT="$PROJECT_DIR/gap_orb_monitor.py"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/gap_orb_monitor_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Weekend check (launchd fires Mon-Fri but double-check)
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" -gt 5 ]; then
    log "Weekend (day $DAY_OF_WEEK) — skipping."
    exit 0
fi

log "=========================================="
log "Starting Gap-and-Go ORB Monitor"
log "=========================================="
log "Project : $PROJECT_DIR"
log "Python  : $VENV_PYTHON"
log "Script  : $MONITOR_SCRIPT"

cd "$PROJECT_DIR"

if [ ! -f "$VENV_PYTHON" ]; then
    log "Virtual environment not found at $VENV_PYTHON"
    exit 1
fi

if [ ! -f "$MONITOR_SCRIPT" ]; then
    log "Monitor script not found at $MONITOR_SCRIPT"
    exit 1
fi

# Kill any stale gap_orb_monitor.py processes
EXISTING_PIDS=$(pgrep -f "gap_orb_monitor.py" 2>/dev/null)
if [ -n "$EXISTING_PIDS" ]; then
    log "Found stale gap_orb_monitor.py process(es): $EXISTING_PIDS — killing..."
    kill $EXISTING_PIDS 2>/dev/null
    sleep 2
fi

log "Launching Gap ORB Monitor (exits at ~11:10 AM)..."
log ""

"$VENV_PYTHON" "$MONITOR_SCRIPT" 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=$?
log ""
log "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    log "Gap ORB Monitor completed successfully"
else
    log "Gap ORB Monitor exited with code: $EXIT_CODE"
fi
log "=========================================="

exit $EXIT_CODE
