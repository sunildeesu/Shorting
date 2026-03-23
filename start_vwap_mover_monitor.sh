#!/bin/bash
#
# VWAP Mover Monitor - Daily Launcher
# Starts at 9:12 AM on market working days (Mon-Fri, excluding NSE holidays)
# The script itself handles market-open gating via is_market_open()
#

PROJECT_DIR="/Users/sunildeesu/myProjects/ShortIndicator"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
MONITOR_SCRIPT="$PROJECT_DIR/vwap_mover_monitor.py"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/vwap_mover_monitor_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Weekend check (launchd fires Mon-Fri but double-check)
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" -gt 5 ]; then
    log "❌ Weekend (day $DAY_OF_WEEK) — skipping."
    exit 0
fi

log "=========================================="
log "🚀 Starting VWAP Mover Monitor"
log "=========================================="
log "Project : $PROJECT_DIR"
log "Python  : $VENV_PYTHON"
log "Script  : $MONITOR_SCRIPT"
log "Day     : $DAY_OF_WEEK (weekday)"
log ""

cd "$PROJECT_DIR"

if [ ! -f "$VENV_PYTHON" ]; then
    log "❌ Virtual environment not found at $VENV_PYTHON"
    exit 1
fi

if [ ! -f "$MONITOR_SCRIPT" ]; then
    log "❌ Monitor script not found at $MONITOR_SCRIPT"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
    log "⚠️  Warning: .env file not found. Credentials may be missing."
fi

# Kill any existing vwap_mover_monitor.py processes before starting
EXISTING_PIDS=$(pgrep -f "vwap_mover_monitor.py" 2>/dev/null)
if [ -n "$EXISTING_PIDS" ]; then
    log "⚠️  Found existing vwap_mover_monitor.py process(es): $EXISTING_PIDS — killing..."
    kill $EXISTING_PIDS 2>/dev/null
    sleep 2
    log "✓ Killed stale process(es)"
fi

log "✓ Launching VWAP Mover Monitor..."
log "✓ Alerts fire after 10:00 AM, monitor exits when market closes (3:30 PM)"
log ""

"$VENV_PYTHON" "$MONITOR_SCRIPT" 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=$?
log ""
log "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    log "✅ VWAP Mover Monitor completed successfully"
else
    log "❌ VWAP Mover Monitor exited with code: $EXIT_CODE"
fi
log "=========================================="

exit $EXIT_CODE
