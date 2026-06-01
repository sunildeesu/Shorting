#!/bin/bash
# collector_watchdog.sh
# Runs every 10 minutes via launchd. Starts the collector if market is open and it's not running.

export TZ="Asia/Kolkata"

SI_DIR="/Users/sunilkumar/myProjects/ShortIndicator"
LOG="$SI_DIR/logs/collector-watchdog.log"

DOW=$(date +%u)    # 1=Mon ... 7=Sun
HHMM=$(date +%H%M) # e.g. 0905

# Only act on weekdays between 9:00 AM and 3:30 PM IST
if [ "$DOW" -gt 5 ] || [ "$HHMM" -lt "0900" ] || [ "$HHMM" -gt "1530" ]; then
    exit 0
fi

DB="$SI_DIR/data/central_quotes.db"

# Check if collector is already running
if ps aux | grep -v grep | grep -q "central_data_collector_continuous.py"; then
    # Process is alive — but check if data is stale (stuck/broken collector)
    LAST_TS=$(sqlite3 "$DB" "SELECT MAX(timestamp) FROM stock_quotes;" 2>/dev/null)
    if [ -n "$LAST_TS" ]; then
        LAST_EPOCH=$(date -j -f "%Y-%m-%d %H:%M:%S" "$LAST_TS" "+%s" 2>/dev/null)
        NOW_EPOCH=$(date "+%s")
        AGE=$(( NOW_EPOCH - LAST_EPOCH ))
        if [ "$AGE" -lt 300 ]; then
            exit 0  # data is fresh, all good
        fi
        echo "$(date '+%Y-%m-%d %H:%M:%S') - watchdog - Data stale for ${AGE}s — killing and restarting collector..." | tee -a "$LOG"
        pkill -f "central_data_collector_continuous.py"
        sleep 2
    else
        exit 0  # can't read DB, assume OK
    fi
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - watchdog - Collector not running during market hours — starting..." | tee -a "$LOG"
bash "$SI_DIR/start_collector.sh"
