#!/bin/bash
# collector_watchdog.sh
# Runs every 10 minutes via launchd. Restarts the collector job if market is open and
# the collector is not running, or is running but its quotes have gone stale.
#
# Two rules, both from 2026-10-23, when at 09:07 this script judged yesterday's last
# quote (63513 s old) as "stale", pkill'ed the healthy collector the 09:05 job had just
# started, and ran start_collector.sh itself - a copy outside the job, so the dashboard
# showed com.nse.central.collector DEAD while it collected:
#   * Staleness is measured from max(last quote, 09:15 open), so no quote can be
#     overdue before 09:15 + STALE_AFTER_S (09:20); before that a running collector
#     is left alone.
#   * The collector is only ever (re)started through its launchd job (kickstart).
#     If that is refused, log it, alert Telegram once a day, and start nothing.
# tests/test_collector_watchdog.py pins this.

export TZ="Asia/Kolkata"

SI_DIR="${SI_DIR:-/Users/sunilkumar/myProjects/ShortIndicator}"
LOG="$SI_DIR/logs/collector-watchdog.log"
DB="$SI_DIR/data/central_quotes.db"
JOB_LABEL="com.nse.central.collector"
DAEMON_PLIST="${DAEMON_PLIST:-/Library/LaunchDaemons/$JOB_LABEL.plist}"
LAUNCHCTL="${LAUNCHCTL:-/bin/launchctl}"
STALE_AFTER_S=300

NOW_EPOCH="${WATCHDOG_NOW_EPOCH:-$(date '+%s')}"
DOW=$(date -r "$NOW_EPOCH" '+%u')    # 1=Mon ... 7=Sun
HHMM=$(date -r "$NOW_EPOCH" '+%H%M') # e.g. 0905
TODAY=$(date -r "$NOW_EPOCH" '+%Y-%m-%d')
RESTART_FAILED_MARKER="$SI_DIR/data/.collector_restart_failed_$(date -r "$NOW_EPOCH" '+%Y%m%d')"

log() {
    echo "$(date -r "$NOW_EPOCH" '+%Y-%m-%d %H:%M:%S') - watchdog - $1" | tee -a "$LOG"
}

# Restart the collector's own launchd job; never spawn a copy outside it.
kickstart_collector() {
    local target out
    if [ -e "$DAEMON_PLIST" ]; then
        # System-domain daemon: needs the kickstart-only sudoers rule for this user.
        target="system/$JOB_LABEL"
        out=$(sudo -n "$LAUNCHCTL" kickstart -k "$target" 2>&1)
    else
        target="gui/$(id -u)/$JOB_LABEL"
        out=$("$LAUNCHCTL" kickstart -k "$target" 2>&1)
    fi
    local rc=$?
    if [ "$rc" -eq 0 ]; then
        log "Kickstarted $target"
        return 0
    fi
    log "ERROR: kickstart -k $target FAILED (exit $rc): $out - collector NOT restarted, needs a manual restart"
    if [ ! -e "$RESTART_FAILED_MARKER" ]; then
        touch "$RESTART_FAILED_MARKER"
        ( cd "$SI_DIR" && ALERT_TEXT="🚨 <b>Collector needs a manual restart</b>
collector_watchdog could not restart $target: kickstart failed (exit $rc).
$1
See logs/collector-watchdog.log. No further alert today." \
            "$SI_DIR/venv/bin/python3" - <<'EOF' >> "$LOG" 2>&1
import os, sys
sys.path.insert(0, '.')
from telegram_notifier import TelegramNotifier
TelegramNotifier().send_message(os.environ['ALERT_TEXT'])
EOF
        )
    fi
    return 1
}

# Only act on weekdays between 9:00 AM and 3:30 PM IST
if [ "$DOW" -gt 5 ] || [ "$HHMM" -lt "0900" ] || [ "$HHMM" -gt "1530" ]; then
    exit 0
fi

if pgrep -f "central_data_collector_continuous.py" > /dev/null; then
    # Process is alive — but check if data is stale (stuck/broken collector)
    LAST_TS=$(sqlite3 "$DB" "SELECT MAX(timestamp) FROM stock_quotes;" 2>/dev/null)
    if [ -z "$LAST_TS" ]; then
        exit 0  # can't read DB, assume OK
    fi
    LAST_EPOCH=$(date -j -f "%Y-%m-%d %H:%M:%S" "$LAST_TS" "+%s" 2>/dev/null)
    OPEN_EPOCH=$(date -j -f "%Y-%m-%d %H:%M:%S" "$TODAY 09:15:00" "+%s")
    if [ -z "$LAST_EPOCH" ] || [ "$LAST_EPOCH" -lt "$OPEN_EPOCH" ]; then
        LAST_EPOCH=$OPEN_EPOCH  # no quote is due before the open
    fi
    AGE=$(( NOW_EPOCH - LAST_EPOCH ))
    if [ "$AGE" -lt "$STALE_AFTER_S" ]; then
        exit 0  # data is fresh, or it is too soon after the open to tell
    fi
    log "Data stale for ${AGE}s (last quote $LAST_TS) — restarting collector job..."
    kickstart_collector "Collector was running but its last quote ($LAST_TS) is ${AGE}s overdue."
    exit $?
fi

# The job's own start_collector.sh may still be checking/refreshing the token before
# it execs the collector; kickstart -k would kill it mid-login.
if pgrep -f "start_collector.sh" > /dev/null; then
    exit 0
fi

log "Collector not running during market hours — kickstarting collector job..."
kickstart_collector "Collector was not running during market hours."
