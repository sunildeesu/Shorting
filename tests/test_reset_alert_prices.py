#!/usr/bin/env python3
"""
Test script for reset_alert_prices.py column references
Validates that the script uses correct column numbers after RSI integration
"""

import re

print("=" * 60)
print("TESTING reset_alert_prices.py COLUMN REFERENCES")
print("=" * 60)

# Read the file
with open('reset_alert_prices.py', 'r') as f:
    content = f.read()

# Expected column mappings after RSI integration
expected_standard = {
    'price_2min_col': 22,  # Column V
    'price_10min_col': 23,  # Column W
    'price_eod_col': 24,    # Column X
    'status_col': 25        # Column Y
}

expected_atr = {
    'price_2min_col': 25,  # Column Y
    'price_10min_col': 26,  # Column Z
    'price_eod_col': 27,    # Column AA
    'status_col': 28        # Column AB
}

print("\n✓ Checking Standard Sheets Column References:")
print("  (5min_alerts, 10min_alerts, 30min_alerts, Volume_Spike_alerts)")
print()

# Check for standard sheet definitions (should appear 3 times: reset_all, reset_by_date, show_summary)
standard_matches = re.findall(r'else:\s+price_2min_col = (\d+).*?price_10min_col = (\d+).*?price_eod_col = (\d+).*?status_col = (\d+)', content, re.DOTALL)

if len(standard_matches) >= 2:  # At least in reset_all and reset_by_date
    for i, match in enumerate(standard_matches[:2], 1):
        price_2min, price_10min, price_eod, status = map(int, match)
        print(f"  Instance {i}:")
        print(f"    Price 2min:  Column {price_2min:2d} (V/22)  {'✓' if price_2min == 22 else '✗ WRONG'}")
        print(f"    Price 10min: Column {price_10min:2d} (W/23)  {'✓' if price_10min == 23 else '✗ WRONG'}")
        print(f"    Price EOD:   Column {price_eod:2d} (X/24)  {'✓' if price_eod == 24 else '✗ WRONG'}")
        print(f"    Status:      Column {status:2d} (Y/25)  {'✓' if status == 25 else '✗ WRONG'}")
        print()
else:
    print("  ✗ FAILED: Standard sheet column definitions not found")

print("\n✓ Checking ATR Sheet Column References:")
print("  (ATR_Breakout_alerts)")
print()

# Check for ATR sheet definitions
atr_matches = re.findall(r'if sheet_name == "ATR_Breakout_alerts":\s+price_2min_col = (\d+).*?price_10min_col = (\d+).*?price_eod_col = (\d+).*?status_col = (\d+)', content, re.DOTALL)

if len(atr_matches) >= 2:  # At least in reset_all and reset_by_date
    for i, match in enumerate(atr_matches[:2], 1):
        price_2min, price_10min, price_eod, status = map(int, match)
        print(f"  Instance {i}:")
        print(f"    Price 2min:  Column {price_2min:2d} (Y/25)  {'✓' if price_2min == 25 else '✗ WRONG'}")
        print(f"    Price 10min: Column {price_10min:2d} (Z/26)  {'✓' if price_10min == 26 else '✗ WRONG'}")
        print(f"    Price EOD:   Column {price_eod:2d} (AA/27) {'✓' if price_eod == 27 else '✗ WRONG'}")
        print(f"    Status:      Column {status:2d} (AB/28) {'✓' if status == 28 else '✗ WRONG'}")
        print()
else:
    print("  ✗ FAILED: ATR sheet column definitions not found")

# Check for old hardcoded column numbers (should not exist)
print("\n✓ Checking for Old Hardcoded Column References:")
old_patterns = [
    (r'column=14', 'column=14 (old Price 2min)'),
    (r'column=15', 'column=15 (old Price 10min)'),
    (r'column=16', 'column=16 (old Price EOD)'),
    (r'column=17', 'column=17 (old Status)'),
]

found_old = False
for pattern, description in old_patterns:
    # Exclude comment lines
    matches = re.findall(f'^[^#]*{pattern}', content, re.MULTILINE)
    if matches:
        print(f"  ✗ Found old reference: {description}")
        found_old = True

if not found_old:
    print("  ✓ No old hardcoded column numbers found")

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

all_correct = (
    len(standard_matches) >= 2 and
    all(int(m[0]) == 22 and int(m[1]) == 23 and int(m[2]) == 24 and int(m[3]) == 25 for m in standard_matches[:2]) and
    len(atr_matches) >= 2 and
    all(int(m[0]) == 25 and int(m[1]) == 26 and int(m[2]) == 27 and int(m[3]) == 28 for m in atr_matches[:2]) and
    not found_old
)

if all_correct:
    print("✓ ALL TESTS PASSED")
    print("\nreset_alert_prices.py is correctly updated for RSI integration!")
    print("Safe to use for resetting alert prices.")
else:
    print("✗ SOME TESTS FAILED")
    print("\nPlease review the column references above.")

print("=" * 60)
