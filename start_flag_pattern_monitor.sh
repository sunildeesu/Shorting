#!/bin/bash
#
# Bull Flag Pattern Monitor — EOD Launcher
# Run once after market close (3:30 PM IST) on trading days.
# Scans ~565 NSE stocks for Stage 3 flag setups on daily charts.
#

PROJECT_DIR="/Users/sunilkumar/myProjects/ShortIndicator"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
MONITOR_SCRIPT="$PROJECT_DIR/flag_pattern_monitor.py"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/flag_pattern_monitor_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Skip weekends
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" -gt 5 ]; then
    log "Weekend (day $DAY_OF_WEEK) — skipping."
    exit 0
fi

log "=========================================="
log "Starting Bull Flag Pattern Monitor (EOD)"
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

# Kill any stale flag_pattern_monitor.py processes
EXISTING_PIDS=$(pgrep -f "flag_pattern_monitor.py" 2>/dev/null)
if [ -n "$EXISTING_PIDS" ]; then
    log "Found stale process(es): $EXISTING_PIDS — killing..."
    kill $EXISTING_PIDS 2>/dev/null
    sleep 2
fi

log "Launching Flag Pattern Monitor..."
log ""

"$VENV_PYTHON" "$MONITOR_SCRIPT" 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=$?
log ""
log "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    log "Flag Pattern Monitor completed successfully"
else
    log "Flag Pattern Monitor exited with code: $EXIT_CODE"
fi
log "=========================================="

exit $EXIT_CODE
