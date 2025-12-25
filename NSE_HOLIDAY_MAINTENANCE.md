# NSE Holiday List Maintenance Guide

## Overview
The system uses an annually updated holiday list to determine trading days. This list must be updated before the start of each year to ensure accurate holiday detection.

---

## Critical Dates

| Action | When | Why |
|--------|------|-----|
| Check for 2026 holidays | **December 2025** | NSE publishes next year's list in Dec |
| Add 2026 holidays | **Before Jan 1, 2026** | System won't recognize 2026 holidays otherwise |
| Verify after update | **Immediately** | Ensure no syntax errors |

---

## Quick Check

Run this command to check holiday list status:

```bash
./venv/bin/python3 update_nse_holidays.py
```

**Expected Output (when up-to-date):**
```
✅ All good! Holiday lists are up-to-date.
```

**Expected Output (when update needed):**
```
⚠️ WARNING: NSE holiday list for 2026 not yet added!
⚠️ Update needed to ensure correct holiday detection.
```

---

## How to Update Holiday List

### Step 1: Get NSE's Official Holiday List

Visit: **https://www.nseindia.com/regulations/trading-holidays**

Look for "Trading Holidays" or "List of Trading Holidays" for the next year.

### Step 2: Edit market_utils.py

Open the file:
```bash
nano market_utils.py
# or use your preferred editor
```

Find the `NSE_HOLIDAYS` dictionary (around line 12):

```python
NSE_HOLIDAYS = {
    2025: [
        date(2025, 1, 26),   # Republic Day
        date(2025, 3, 14),   # Holi
        # ... existing 2025 holidays ...
    ],
    # TODO: Add 2026 holidays when NSE publishes the list
}
```

### Step 3: Add Next Year's Holidays

Add a new entry for the next year:

```python
NSE_HOLIDAYS = {
    2025: [
        date(2025, 1, 26),   # Republic Day
        # ... existing 2025 holidays ...
    ],
    2026: [  # ← ADD THIS BLOCK
        date(2026, 1, 26),   # Republic Day
        date(2026, 3, 3),    # Holi (example - verify actual date!)
        date(2026, 3, 21),   # Id-Ul-Fitr (example)
        date(2026, 3, 30),   # Mahavir Jayanti (example)
        # ... add all 2026 holidays from NSE website ...
        date(2026, 12, 25),  # Christmas
    ],
}
```

**Important:**
- Use exact dates from NSE's official list
- Include comments with holiday names
- Use `date(YYYY, M, D)` format (no leading zeros needed)
- List in chronological order for readability

### Step 4: Verify the Update

```bash
# Check syntax and status
./venv/bin/python3 update_nse_holidays.py

# Should show:
# 2025: ✅ Available
# 2026: ✅ Available
# ✅ All good! Holiday lists are up-to-date.
```

### Step 5: Test with a Specific Date

```bash
./venv/bin/python3 -c "
from market_utils import is_nse_holiday
from datetime import date

# Test a known 2026 holiday (e.g., Republic Day)
print('Jan 26, 2026 is holiday:', is_nse_holiday(date(2026, 1, 26)))

# Test a regular day (should be False)
print('Jan 27, 2026 is holiday:', is_nse_holiday(date(2026, 1, 27)))
"
```

**Expected output:**
```
Jan 26, 2026 is holiday: True
Jan 27, 2026 is holiday: False
```

### Step 6: Commit Changes

```bash
git add market_utils.py
git commit -m "Add NSE holidays for 2026"
git push
```

---

## What Happens If You Forget?

### Scenario 1: It's January 1, 2026, and 2026 holidays are NOT added

**Impact:**
- System logs warning: "NSE holiday list for 2026 not available"
- **Assumes all days are trading days** (holidays treated as trading days)
- Monitoring scripts will run on holidays
- Sleep prevention will activate on holidays
- Alerts may be sent on holidays (when market is actually closed)

**Recovery:**
1. Add 2026 holidays immediately (follow steps above)
2. No restart needed - changes take effect on next run

### Scenario 2: It's November/December 2025, and 2026 holidays are NOT added

**Impact:**
- System logs warning: "NSE holiday list for 2026 not yet added"
- Script `update_nse_holidays.py` exits with code 1
- **No immediate impact** (2025 holidays still work)

**Action:**
- Add 2026 holidays before January 1, 2026

---

## Automation Reminder

Add a calendar reminder:

**Event:** "Update NSE Holiday List for Next Year"
**Date:** December 15 (every year)
**Recurrence:** Yearly
**Alert:** 1 week before
**Notes:**
```
1. Run: ./venv/bin/python3 update_nse_holidays.py
2. Visit: https://www.nseindia.com/regulations/trading-holidays
3. Update market_utils.py with next year's holidays
4. Test and commit
```

---

## Example Holiday List Template

Copy this template when adding a new year:

```python
2027: [
    date(2027, 1, 26),   # Republic Day
    date(2027, 3, XX),   # Holi (check NSE list)
    date(2027, 3, XX),   # Id-Ul-Fitr (check NSE list)
    date(2027, 4, XX),   # Mahavir Jayanti
    date(2027, 4, 14),   # Dr. Ambedkar Jayanti
    date(2027, 4, XX),   # Good Friday (check NSE list)
    date(2027, 5, 1),    # Maharashtra Day
    date(2027, 6, XX),   # Id-Ul-Adha (check NSE list)
    date(2027, 8, 15),   # Independence Day
    date(2027, 8, XX),   # Ganesh Chaturthi (check NSE list)
    date(2027, 10, 2),   # Mahatma Gandhi Jayanti
    date(2027, 10, XX),  # Dussehra (check NSE list)
    date(2027, 11, XX),  # Diwali (Laxmi Pujan) (check NSE list)
    date(2027, 11, XX),  # Diwali-Balipratipada (check NSE list)
    date(2027, 11, XX),  # Gurunanak Jayanti (check NSE list)
    date(2027, 12, 25),  # Christmas
],
```

---

## Common Holidays (Approximate - Always Verify!)

Some holidays are fixed, others change every year:

**Fixed Dates:**
- Republic Day: January 26
- Maharashtra Day: May 1
- Independence Day: August 15
- Gandhi Jayanti: October 2
- Christmas: December 25
- Dr. Ambedkar Jayanti: April 14

**Variable Dates (check NSE list):**
- Holi (Feb/Mar - changes yearly)
- Id-Ul-Fitr (Islamic calendar - changes yearly)
- Mahavir Jayanti (Mar/Apr - changes yearly)
- Good Friday (Mar/Apr - changes yearly)
- Id-Ul-Adha (Islamic calendar - changes yearly)
- Ganesh Chaturthi (Aug/Sep - changes yearly)
- Dussehra (Sep/Oct - changes yearly)
- Diwali (Oct/Nov - changes yearly)
- Gurunanak Jayanti (Nov - changes yearly)

---

## Troubleshooting

### Issue: Script shows "CRITICAL: NSE holiday list for 2026 is MISSING"

**Fix:** Add 2026 holidays to `market_utils.py` immediately

### Issue: Added holidays but script still shows warning

**Check:**
1. Syntax errors in Python dict (missing commas, brackets)
2. Year number correct (2026, not 2025)
3. Proper indentation
4. File saved

**Test:**
```bash
python3 -m py_compile market_utils.py
# Should show no errors
```

### Issue: Holiday detection not working

**Debug:**
```bash
./venv/bin/python3 -c "
from market_utils import is_nse_holiday, NSE_HOLIDAYS
from datetime import date
print('Available years:', sorted(NSE_HOLIDAYS.keys()))
print('Testing date:', date(2026, 1, 26))
print('Is holiday:', is_nse_holiday(date(2026, 1, 26)))
"
```

---

## Files Involved

| File | Purpose |
|------|---------|
| `market_utils.py` | Contains NSE_HOLIDAYS dict (UPDATE HERE) |
| `update_nse_holidays.py` | Checker script (run to verify) |
| `NSE_HOLIDAY_MAINTENANCE.md` | This guide |

---

## Summary Checklist

- [ ] Set annual reminder for December 15
- [ ] When NSE publishes next year's list, update `market_utils.py`
- [ ] Run `update_nse_holidays.py` to verify
- [ ] Test with specific dates
- [ ] Commit and push changes
- [ ] Done before January 1st

**Remember:** It's better to update early (December) than to forget and scramble on January 1st!
