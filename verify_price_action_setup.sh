#!/bin/bash
#
# Verify Price Action Monitor Setup
#

echo "=========================================="
echo "Price Action Monitor - Setup Verification"
echo "=========================================="
echo ""

PASS=0
FAIL=0

# Check 1: LaunchAgent plist exists
echo -n "1. LaunchAgent plist file exists... "
if [ -f ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist ]; then
    echo "✓ PASS"
    ((PASS++))
else
    echo "✗ FAIL"
    ((FAIL++))
fi

# Check 2: LaunchAgent is loaded
echo -n "2. LaunchAgent is loaded... "
if launchctl list | grep -q "com.nse.priceaction.monitor"; then
    echo "✓ PASS"
    ((PASS++))
else
    echo "✗ FAIL (run: launchctl load ~/Library/LaunchAgents/com.nse.priceaction.monitor.plist)"
    ((FAIL++))
fi

# Check 3: Python script exists
echo -n "3. price_action_monitor.py exists... "
if [ -f price_action_monitor.py ]; then
    echo "✓ PASS"
    ((PASS++))
else
    echo "✗ FAIL"
    ((FAIL++))
fi

# Check 4: Python script is executable or can be run
echo -n "4. Python script can be executed... "
if [ -x price_action_monitor.py ] || [ -f price_action_monitor.py ]; then
    echo "✓ PASS"
    ((PASS++))
else
    echo "✗ FAIL"
    ((FAIL++))
fi

# Check 5: Virtual environment exists
echo -n "5. Virtual environment exists... "
if [ -d venv ] && [ -f venv/bin/python3 ]; then
    echo "✓ PASS"
    ((PASS++))
else
    echo "✗ FAIL"
    ((FAIL++))
fi

# Check 6: Log directory exists
echo -n "6. Logs directory exists... "
if [ -d logs ]; then
    echo "✓ PASS"
    ((PASS++))
else
    echo "✗ FAIL (run: mkdir -p logs)"
    ((FAIL++))
fi

# Check 7: Config file exists
echo -n "7. config.py exists... "
if [ -f config.py ]; then
    echo "✓ PASS"
    ((PASS++))
else
    echo "✗ FAIL"
    ((FAIL++))
fi

# Check 8: Stock list exists
echo -n "8. fo_stocks.json exists... "
if [ -f fo_stocks.json ]; then
    echo "✓ PASS"
    ((PASS++))
else
    echo "✗ FAIL"
    ((FAIL++))
fi

# Check 9: Price action alerts enabled
echo -n "9. ENABLE_PRICE_ACTION_ALERTS setting... "
if grep -q "ENABLE_PRICE_ACTION_ALERTS" config.py 2>/dev/null; then
    # Check if the default is 'true' or if enabled
    if grep "ENABLE_PRICE_ACTION_ALERTS" config.py | grep -q "'true'"; then
        echo "✓ PASS (enabled by default)"
        ((PASS++))
    elif grep "ENABLE_PRICE_ACTION_ALERTS" config.py | grep -q "True"; then
        echo "✓ PASS (explicitly enabled)"
        ((PASS++))
    else
        echo "⚠ WARNING (may be disabled)"
        ((FAIL++))
    fi
else
    echo "✗ FAIL (setting not found)"
    ((FAIL++))
fi

# Check 10: Can import required modules
echo -n "10. Required Python modules available... "
if ./venv/bin/python3 -c "from telegram_notifier import TelegramNotifier; from price_action_detector import PriceActionDetector" 2>/dev/null; then
    echo "✓ PASS"
    ((PASS++))
else
    echo "✗ FAIL (check imports)"
    ((FAIL++))
fi

echo ""
echo "=========================================="
echo "Results: $PASS passed, $FAIL failed"
echo "=========================================="
echo ""

if [ $FAIL -eq 0 ]; then
    echo "✅ All checks passed! Setup is complete and ready."
    echo ""
    echo "Next steps:"
    echo "  1. Wait for next trading day (Mon-Fri)"
    echo "  2. Monitor will run automatically at 9:25 AM"
    echo "  3. Check logs: tail -f logs/price_action_monitor.log"
    echo "  4. Watch for Telegram alerts"
    exit 0
else
    echo "⚠️  Some checks failed. Please review and fix issues above."
    exit 1
fi
