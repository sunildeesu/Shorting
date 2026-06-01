#!/bin/bash
# Wrapper for central_data_collector_continuous.py
# Validates Kite token before starting. If invalid, refreshes via NewsBase token_refresh.

SI_DIR="/Users/sunilkumar/myProjects/ShortIndicator"
NB_DIR="/Users/sunilkumar/myProjects/NewsBase"
LOG="$SI_DIR/logs/central-collector-stderr.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - start_collector - $1" | tee -a "$LOG"
}

# Ensure only one instance runs at a time
if pgrep -f "central_data_collector_continuous.py" > /dev/null; then
    log "Already running — exiting"
    exit 0
fi

cd "$SI_DIR"

# Check token validity
TOKEN_STATUS=$("$SI_DIR/venv/bin/python3" - <<'EOF' 2>/dev/null
import sys
sys.path.insert(0, '.')
import config
from kiteconnect import KiteConnect
try:
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)
    kite.profile()
    print("valid")
except Exception:
    print("invalid")
EOF
)

if [ "$TOKEN_STATUS" != "valid" ]; then
    log "Token invalid — refreshing via NewsBase..."
    cd "$NB_DIR"
    if "$NB_DIR/venv/bin/python3" -m data_feeds.token_refresh >> "$LOG" 2>&1; then
        log "Token refresh successful"
    else
        log "Token refresh FAILED — cannot start collector"
        exit 1
    fi
    cd "$SI_DIR"
else
    log "Token valid"
fi

log "Starting central data collector..."
exec "$SI_DIR/venv/bin/python3" "$SI_DIR/central_data_collector_continuous.py"
