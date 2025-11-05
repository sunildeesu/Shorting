#!/bin/bash

# EOD Stock Analyzer - Run daily after market close
# This script is designed to be run via cron at 3:30 PM daily

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Change to the project directory
cd "$SCRIPT_DIR" || exit 1

# Ensure logs directory exists
mkdir -p logs

# Run the EOD analyzer using the virtual environment Python
./venv/bin/python3 eod_analyzer.py

# Exit with the same status code as the Python script
exit $?
