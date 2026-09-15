#!/bin/bash
# Wrapper for central_data_collector_continuous.py
# Validates Kite token before starting. If invalid, refreshes via NewsBase token_refresh.
#
# A failed refresh is remembered for the rest of the day in $REFRESH_FAILED_MARKER
# so the 600 s watchdog does not re-run the login every cycle: on 2026-09-15 a
# deterministic 2FA rejection was retried 22+ times, each one a wasted login and a
# step towards the broker locking the account. A valid token (e.g. after a manual
# `python3 generate_kite_token.py`) always starts the collector and clears the marker.
# tests/test_start_collector_backoff.py pins this.

SI_DIR="${SI_DIR:-/Users/sunilkumar/myProjects/ShortIndicator}"
NB_DIR="${NB_DIR:-/Users/sunilkumar/myProjects/NewsBase}"
LOG="$SI_DIR/logs/central-collector-stderr.log"
REFRESH_FAILED_MARKER="$SI_DIR/data/.token_refresh_failed_$(date '+%Y%m%d')"

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
    if [ -e "$REFRESH_FAILED_MARKER" ]; then
        log "Token invalid — refresh already failed today ($REFRESH_FAILED_MARKER exists); skipping refresh until tomorrow or a manual generate_kite_token.py"
        exit 1
    fi
    log "Token invalid — refreshing via NewsBase..."
    cd "$NB_DIR"
    if "$NB_DIR/venv/bin/python3" -m data_feeds.token_refresh >> "$LOG" 2>&1; then
        log "Token refresh successful"
    else
        log "Token refresh FAILED — cannot start collector; wrote $REFRESH_FAILED_MARKER, no further refresh attempts today"
        touch "$REFRESH_FAILED_MARKER"
        cd "$SI_DIR"
        ALERT_TEXT="🚨 <b>Kite token refresh FAILED</b>
Collector cannot start. NewsBase token_refresh was rejected (see logs/central-collector-stderr.log).
No further automatic refresh today — fix the login and run: python3 generate_kite_token.py" \
            "$SI_DIR/venv/bin/python3" - <<'EOF' >> "$LOG" 2>&1
import os, sys
sys.path.insert(0, '.')
from telegram_notifier import TelegramNotifier
TelegramNotifier().send_message(os.environ['ALERT_TEXT'])
EOF
        exit 1
    fi
    cd "$SI_DIR"
else
    log "Token valid"
    rm -f "$REFRESH_FAILED_MARKER"
fi

log "Starting central data collector..."
exec "$SI_DIR/venv/bin/python3" "$SI_DIR/central_data_collector_continuous.py"
