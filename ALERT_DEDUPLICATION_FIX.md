# Alert Deduplication Fix

## Problem

30-minute gradual fall and rise alerts were being sent every 5 minutes instead of just once.

### Root Cause

When a stock's price remained in a drop/rise condition (e.g., 3% drop over 30 minutes), the condition would stay true for multiple monitoring cycles. Since the monitoring runs every 5 minutes, the same alert would be sent repeatedly:

```
9:00 AM - Stock drops 3% → Alert sent ✅
9:05 AM - Stock still down 3% → Alert sent again ❌ (duplicate)
9:10 AM - Stock still down 3% → Alert sent again ❌ (duplicate)
9:15 AM - Stock still down 3% → Alert sent again ❌ (duplicate)
```

This resulted in spam alerts for the same price movement.

## Solution

Implemented an alert deduplication mechanism with cooldown periods:

### 1. Alert History Tracking

Added `alert_history` dictionary in `StockMonitor.__init__()`:

```python
# Alert tracking for deduplication
# Format: {(symbol, alert_type): timestamp}
self.alert_history = {}
```

Tracks when each alert type was last sent for each stock.

### 2. Deduplication Logic

Created `should_send_alert()` helper method in stock_monitor.py:472:

```python
def should_send_alert(self, symbol: str, alert_type: str, cooldown_minutes: int = 30) -> bool:
    """
    Check if an alert should be sent based on deduplication rules
    Prevents sending duplicate alerts for same stock/alert_type within cooldown period

    Args:
        symbol: Stock symbol
        alert_type: Type of alert (10min, 30min, 10min_rise, 30min_rise, etc.)
        cooldown_minutes: Cooldown period in minutes (default 30)

    Returns:
        True if alert should be sent, False if it's a duplicate
    """
```

**How it works:**
- Checks if the same `(symbol, alert_type)` was alerted recently
- If yes and within cooldown period → Skip (duplicate)
- If no or cooldown expired → Send and record timestamp

### 3. Integration

Updated both `check_stock_for_drop()` and `check_stock_for_rise()` methods:

**For 30-minute drops** (stock_monitor.py:554):
```python
if drop_30min >= config.DROP_THRESHOLD_30MIN:
    # Check if we should send this alert (deduplication)
    if self.should_send_alert(symbol, "30min", cooldown_minutes=30):
        logger.info(f"DROP DETECTED [30MIN]...")
        success = self.telegram.send_alert(...)
```

**For 30-minute rises** (stock_monitor.py:637):
```python
if rise_30min >= config.RISE_THRESHOLD_30MIN:
    # Check if we should send this alert (deduplication)
    if self.should_send_alert(symbol, "30min_rise", cooldown_minutes=30):
        logger.info(f"RISE DETECTED [30MIN]...")
        success = self.telegram.send_alert(...)
```

## Behavior

### Before Fix
```
9:00 AM - RELIANCE drops 3.2% over 30 mins → Alert sent ✅
9:05 AM - RELIANCE still down 3.1% → Alert sent ❌ (spam)
9:10 AM - RELIANCE still down 3.0% → Alert sent ❌ (spam)
9:15 AM - RELIANCE still down 2.9% → No alert (below threshold)
9:35 AM - RELIANCE drops 3.5% over 30 mins → Alert sent ✅ (new condition)
```

### After Fix
```
9:00 AM - RELIANCE drops 3.2% over 30 mins → Alert sent ✅
9:05 AM - RELIANCE still down 3.1% → Skipped (within 30min cooldown)
9:10 AM - RELIANCE still down 3.0% → Skipped (within 30min cooldown)
9:15 AM - RELIANCE still down 2.9% → No alert (below threshold)
9:35 AM - RELIANCE drops 3.5% over 30 mins → Alert sent ✅ (cooldown expired)
```

## Deduplication Rules

| Alert Type | Cooldown Period | Behavior |
|------------|----------------|----------|
| **10min drop** | None | Always sent (rapid movement) |
| **30min drop** | 30 minutes | Deduplicated ✅ |
| **10min rise** | None | Always sent (rapid movement) |
| **30min rise** | 30 minutes | Deduplicated ✅ |
| **Volume spike drop** | None | Always sent (unusual activity) |
| **Volume spike rise** | None | Always sent (unusual activity) |

**Rationale:**
- **10-minute alerts**: Indicate rapid movements, should be sent immediately
- **30-minute alerts**: Indicate gradual trends, should only be sent once
- **Volume spike alerts**: Indicate unusual activity, should be sent immediately

## Key Features

### 1. Separate Tracking per Stock
Different stocks are tracked independently:
```
RELIANCE 30min drop → Cooldown active
TCS 30min drop → Can still be sent ✅
```

### 2. Separate Tracking per Alert Type
Different alert types for same stock are tracked separately:
```
RELIANCE 30min drop → Cooldown active
RELIANCE 30min rise → Can still be sent ✅
```

### 3. Automatic Cooldown Expiry
After cooldown period (30 minutes), the alert can be sent again if condition persists:
```
9:00 AM - Alert sent
9:30 AM - Cooldown expires
9:30 AM - Alert can be sent again if condition still true
```

### 4. In-Memory Tracking
Alert history is stored in memory during the monitoring session. Resets on script restart (which is fine since monitoring runs continuously via cron).

## Testing

All deduplication tests passed successfully:

```bash
./venv/bin/python3 test_deduplication.py
```

**Test Coverage:**
- ✅ First alert should be sent
- ✅ Immediate duplicate should be blocked
- ✅ Different alert type for same stock should be allowed
- ✅ Same alert type for different stock should be allowed
- ✅ Alert after cooldown period should be sent
- ✅ Alert just before cooldown expiry should be blocked

## Files Modified

1. **stock_monitor.py**
   - Line 30-32: Added `alert_history` dictionary
   - Line 472-503: Added `should_send_alert()` helper method
   - Line 554: Added deduplication check for 30-minute drops
   - Line 637: Added deduplication check for 30-minute rises

2. **test_deduplication.py** (new)
   - Comprehensive test suite for deduplication logic

## Impact

### User Experience
- ✅ **No more spam alerts** for gradual 30-minute movements
- ✅ **Still get rapid alerts** for 10-minute movements (unchanged)
- ✅ **Still get volume spike alerts** (unchanged)
- ✅ **Cleaner Telegram notifications**

### System Performance
- Minimal impact (simple dictionary lookup)
- Memory usage negligible (one timestamp per alert type per stock)

## Monitoring

### Debug Logs

When a duplicate is detected, you'll see in logs:
```
RELIANCE: Skipping duplicate 30min alert (sent 5.0min ago)
```

### Alert Logs

When an alert is sent, normal logging continues:
```
DROP DETECTED [30MIN]: RELIANCE dropped 3.2% (₹2500.00 → ₹2420.00)
```

## Configuration

No configuration changes needed. The deduplication is automatic and uses sensible defaults:
- **Cooldown period**: 30 minutes (matches the alert timeframe)
- **Applies to**: 30-minute drop and rise alerts only
- **Does not apply to**: 10-minute alerts, volume spike alerts

## Future Enhancements

Possible improvements (not currently implemented):

1. **Persistent storage**: Save alert history to file to survive script restarts
2. **Configurable cooldowns**: Allow per-alert-type cooldown configuration in .env
3. **Alert escalation**: Send reminder after 60 minutes if condition persists
4. **Adaptive cooldowns**: Shorter cooldown during high volatility periods

## Rollback

If issues arise, the deduplication can be disabled by removing the `should_send_alert()` checks:

```python
# In check_stock_for_drop() line 554
if drop_30min >= config.DROP_THRESHOLD_30MIN:
    # Remove this line:
    # if self.should_send_alert(symbol, "30min", cooldown_minutes=30):

    logger.info(f"DROP DETECTED [30MIN]...")
    success = self.telegram.send_alert(...)
```

---

**Implementation Date**: 2025-11-03
**Issue**: 30-minute alerts sent every 5 minutes (spam)
**Fix**: Alert deduplication with 30-minute cooldown
**Status**: ✅ Tested and deployed
