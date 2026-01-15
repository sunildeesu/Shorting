#!/bin/bash
#
# Daily Alert Price Update Script
#
# Runs once daily at 3:45 PM (after market close) to update:
# - 2-min historical prices for all pending alerts
# - 10-min historical prices for all pending alerts
# - EOD closing prices for today's alerts
#
# Uses historical data API to fetch actual prices at correct times.
#

set -e

PROJECT_DIR="/Users/sunildeesu/myProjects/ShortIndicator"
cd "$PROJECT_DIR"

echo "======================================================================="
echo "Daily Alert Price Update - $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================="
echo ""

# Activate virtual environment
source venv/bin/activate

# Get today's date
TODAY=$(date '+%Y-%m-%d')

echo "Step 1: Updating 2-minute historical prices..."
echo "-----------------------------------------------------------------------"
./venv/bin/python3 update_alert_prices.py --2min
echo ""

echo "Step 2: Updating 10-minute historical prices..."
echo "-----------------------------------------------------------------------"
./venv/bin/python3 update_alert_prices.py --10min
echo ""

echo "Step 3: Updating EOD closing prices for $TODAY..."
echo "-----------------------------------------------------------------------"
./venv/bin/python3 update_eod_prices.py --date "$TODAY"
echo ""

echo "======================================================================="
echo "Daily Alert Price Update Complete - $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================="
