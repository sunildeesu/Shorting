#!/bin/bash

# Volume Profile Analyzer - Daily Launcher
# Runs at 3:25 PM on weekdays (near market close)

PROJECT_DIR="/Users/sunildeesu/myProjects/ShortIndicator"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
ANALYZER_SCRIPT="$PROJECT_DIR/volume_profile_analyzer.py"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/volume_profile_$(date +%Y%m%d).log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Log function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log "========================================="
log "VOLUME PROFILE ANALYZER - STARTING"
log "========================================="

# Check if weekday (1=Monday, 5=Friday)
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" -gt 5 ]; then
    log "❌ Today is weekend. Skipping."
    exit 0
fi

# Fixed execution time: 3:25 PM (end of day)
EXECUTION_TIME="3:25PM"

log "📊 Execution Time: $EXECUTION_TIME (End of Day)"
log "🚀 Running volume profile analyzer..."

# Change to project directory
cd "$PROJECT_DIR" || {
    log "❌ Failed to change to project directory"
    exit 1
}

# Execute analyzer
"$VENV_PYTHON" "$ANALYZER_SCRIPT" --execution-time "$EXECUTION_TIME" 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log "✅ Volume profile analysis completed successfully"
else
    log "❌ Volume profile analysis failed with exit code: $EXIT_CODE"
fi

log "========================================="
log "VOLUME PROFILE ANALYZER - FINISHED"
log "========================================="

exit $EXIT_CODE
