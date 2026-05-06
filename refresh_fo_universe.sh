#!/bin/bash
# F&O Universe Refresh — Weekly launcher (Mondays 9:00 AM via launchd)
# Updates fo_stocks.json and futures_mapping.json from Kite NFO instruments.

set -e

PROJECT_DIR="/Users/sunildeesu/myProjects/ShortIndicator"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
SCRIPT="$PROJECT_DIR/refresh_fo_universe.py"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/refresh_fo_universe_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

# Skip weekends (shouldn't happen with weekly launchd, but guard anyway)
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" -gt 5 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Weekend — skipping" >> "$LOG_FILE"
    exit 0
fi

cd "$PROJECT_DIR"
"$VENV_PYTHON" "$SCRIPT" 2>&1 | tee -a "$LOG_FILE"
