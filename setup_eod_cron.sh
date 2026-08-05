#!/bin/bash
# Setup EOD Analysis Cron Job
# Runs daily at 4:00 PM (after market close)
#
# ############################################################################
# DO NOT RUN THIS. The EOD analyzer is PAUSED ON PURPOSE (2026-08-05).
#
# The captain stopped it to improve it and will re-enable it themselves. The
# launchd job com.stockmonitor.eod is installed-but-unloaded by choice, and the
# crontab entry this script installs is intentionally absent — `crontab -l`
# reports "no crontab for sunilkumar". Running this script re-enables the EOD
# analyzer and reverses that decision.
#
# The script is kept, not deleted, because the job is coming back. See
# launchd_agents/README.md -> "Paused jobs — stopped on purpose, will return".
#
# To run the analyzer once by hand (which is fine), use ./start_eod_analyzer.sh
# — that does not schedule anything.
# ############################################################################

set -e

cat <<'PAUSED' >&2
==================================================
REFUSING TO INSTALL: the EOD analyzer is paused on purpose.

Scheduling it is the captain's decision alone. See
launchd_agents/README.md -> "Paused jobs — stopped on purpose, will return".

To run the analyzer once by hand: ./start_eod_analyzer.sh
==================================================
PAUSED
exit 1

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CRON_JOB="0 16 * * 1-5 cd $SCRIPT_DIR && $SCRIPT_DIR/start_eod_analyzer.sh >> $SCRIPT_DIR/logs/eod_cron.log 2>&1"

echo "=================================================="
echo "EOD Analysis Cron Job Setup"
echo "=================================================="
echo ""
echo "This will install a cron job that runs at 4:00 PM"
echo "on weekdays to perform end-of-day analysis."
echo ""

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "start_eod_analyzer.sh"; then
    echo "⚠️  EOD cron job already exists!"
    echo ""
    echo "Current EOD cron job:"
    crontab -l | grep "start_eod_analyzer.sh"
    echo ""
    read -p "Do you want to replace it? (y/N): " confirm
    if [[ ! $confirm =~ ^[Yy]$ ]]; then
        echo "❌ Installation cancelled."
        exit 1
    fi
    # Remove old job
    crontab -l | grep -v "start_eod_analyzer.sh" | crontab -
fi

# Make scripts executable
chmod +x "$SCRIPT_DIR/start_eod_analyzer.sh"
chmod +x "$SCRIPT_DIR/eod_analyzer.py"

# Add new cron job
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo ""
echo "✅ EOD Analysis cron job installed successfully!"
echo ""
echo "Schedule: 4:00 PM on weekdays (Mon-Fri)"
echo "Log file: $SCRIPT_DIR/logs/eod_cron.log"
echo ""
echo "Current crontab:"
echo "=================================================="
crontab -l
echo "=================================================="
echo ""
echo "📊 Reports will be generated at:"
echo "   $SCRIPT_DIR/data/eod_reports/YYYY/MM/"
echo ""
echo "Next run: Tomorrow at 4:00 PM (if weekday)"
echo ""
echo "To verify it's running, check tomorrow at 4:00 PM:"
echo "   tail -f logs/eod_cron.log"
echo ""
