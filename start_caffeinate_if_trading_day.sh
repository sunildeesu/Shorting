#!/bin/bash
# Start caffeinate only if it's a trading day (not weekend, not NSE holiday)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/caffeinate-control.log"

# Create log directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/logs"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "Caffeinate Control - Checking if trading day"

# Check if it's a trading day using Python market_utils
cd "$SCRIPT_DIR"

IS_TRADING_DAY=$("$SCRIPT_DIR/venv/bin/python3" -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from market_utils import is_trading_day
print('true' if is_trading_day() else 'false')
" 2>/dev/null)

if [ "$IS_TRADING_DAY" != "true" ]; then
    log "Not a trading day (weekend or NSE holiday) - caffeinate will NOT start"
    log "=========================================="
    exit 0
fi

log "Trading day confirmed - starting caffeinate"

# Start caffeinate
# -d: Prevent display from sleeping
# -i: Prevent system from idle sleeping
# -s: Prevent system from sleeping when on AC power
exec /usr/bin/caffeinate -dis
