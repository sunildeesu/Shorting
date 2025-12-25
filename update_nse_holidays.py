#!/usr/bin/env python3
"""
Helper script to check NSE holiday list status and guide updates

Usage:
  python3 update_nse_holidays.py
"""

import sys
from datetime import datetime
from market_utils import check_holiday_list_status, NSE_HOLIDAYS, get_current_ist_time

def main():
    print("=" * 70)
    print("NSE Holiday List Status Checker")
    print("=" * 70)
    print()

    # Check status
    status = check_holiday_list_status()
    current_time = get_current_ist_time()
    current_year = current_time.year
    next_year = current_year + 1

    # Display current status
    print(f"📅 Current Date: {current_time.strftime('%d %B %Y (%A)')}")
    print()

    print("Holiday List Availability:")
    print(f"  {current_year}: {'✅ Available' if status['current_year_available'] else '❌ MISSING'}")
    print(f"  {next_year}: {'✅ Available' if status['next_year_available'] else '⚠️  Not yet added'}")
    print()

    # Show available years
    available_years = sorted(NSE_HOLIDAYS.keys())
    print(f"Years with holiday lists: {', '.join(map(str, available_years))}")
    print()

    # Show warnings
    if status['needs_update']:
        print("⚠️  ACTION REQUIRED:")
        print("-" * 70)
        print(status['warning_message'])
        print("-" * 70)
        print()

    # Show current year holidays
    if current_year in NSE_HOLIDAYS:
        holidays = NSE_HOLIDAYS[current_year]
        remaining_holidays = [h for h in holidays if h >= current_time.date()]

        print(f"📋 {current_year} NSE Holidays ({len(holidays)} total, {len(remaining_holidays)} remaining):")
        print("-" * 70)

        for holiday in holidays:
            is_past = holiday < current_time.date()
            status_icon = "✓" if is_past else "•"
            date_str = holiday.strftime("%d %b %Y (%a)")

            # Try to get holiday name from comments (basic parsing)
            print(f"  {status_icon} {date_str}")

        print()

    # Instructions for updating
    if not status['current_year_available'] or (current_time.month >= 11 and not status['next_year_available']):
        print("📝 How to Update Holiday List:")
        print("-" * 70)
        print("1. Visit: https://www.nseindia.com/regulations/trading-holidays")
        print(f"2. Find the holiday list for {next_year if status['current_year_available'] else current_year}")
        print("3. Edit market_utils.py")
        print("4. Add entries to NSE_HOLIDAYS dictionary:")
        print()
        print(f"   NSE_HOLIDAYS = {{")
        print(f"       {current_year}: [")
        print(f"           date({current_year}, 1, 26),  # Republic Day")
        print(f"           date({current_year}, 3, 14),  # Holi")
        print(f"           # ... add all holidays ...")
        print(f"       ],")
        if current_time.month >= 11:
            print(f"       {next_year}: [  # ADD THIS")
            print(f"           date({next_year}, 1, 26),  # Republic Day")
            print(f"           # ... add {next_year} holidays ...")
            print(f"       ],")
        print(f"   }}")
        print()
        print("5. Test: python3 update_nse_holidays.py")
        print("6. Commit: git add market_utils.py && git commit -m 'Update NSE holidays for {}'".format(
            next_year if status['current_year_available'] else current_year))
        print("-" * 70)
        print()

    # Summary
    if not status['needs_update']:
        print("✅ All good! Holiday lists are up-to-date.")
    else:
        print("⚠️  Update needed to ensure correct holiday detection.")

    print()
    print("=" * 70)

    # Exit code
    sys.exit(1 if status['needs_update'] else 0)

if __name__ == "__main__":
    main()
