# 1-Minute Alert System Improvements (Dec 2023)

## Backtest Results (30 Days)

**Before improvements:**
- **Accuracy**: 22.2% (4 successful, 14 failed)
- **Reversal Rate**: 55.6% (10 out of 18 alerts reversed within 10 minutes)
- **Alert Volume**: 18 alerts over 30 days (0.6/day)
- **Volume Distribution**: 94.4% alerts had 5x+ volume (despite 3x threshold)
- **Risk/Reward**: Avg gain +1.98% vs Avg loss -2.80% (negative)

**Key Issues:**
1. Low accuracy - too many false positives
2. High reversal rate - alerts triggering too early
3. Volume filter effectively useless (most passed with 5x anyway)

---

## Improvements Implemented

### 1. **Increased Volume Multiplier: 3.0x → 5.0x** ✅
**Rationale**: 94.4% of alerts already had 5x+ volume, so 3x threshold was too lenient.

**Change**: `config.py` line 43
```python
# Before
VOLUME_SPIKE_MULTIPLIER_1MIN = 3.0

# After
VOLUME_SPIKE_MULTIPLIER_1MIN = 5.0  # High quality signals only
```

---

### 2. **Added Momentum Confirmation (Layer 6)** ✅
**Rationale**: 55.6% reversal rate means alerts were catching temporary blips, not sustained moves.

**Implementation**: `onemin_alert_detector.py` lines 263-329

**Logic**:
- Calculate 1-minute price change rate (e.g., 0.85%/min)
- Calculate 4-minute average change rate (from 5min ago to 1min ago)
- **Require acceleration**: 1-min rate must be >20% faster than 4-min average

**Example**:
```
Price at 10:00 AM = ₹100
Price at 10:04 AM = ₹99.50  (dropped 0.50 in 4 min = 0.125%/min average)
Price at 10:05 AM = ₹98.70  (dropped 0.80 in 1 min = 0.80%/min)

Acceleration check: 0.80%/min > 0.125%/min * 1.2? ✅ YES (passes)
```

**Benefits**:
- Filters out alerts where price is decelerating (likely to reverse)
- Only triggers when momentum is building (sustained move)
- Reduces premature alerts significantly

---

### 3. **Updated Documentation** ✅
- Updated filter descriptions in `onemin_alert_detector.py`
- Changed "5-layer filtering" to "6-layer filtering"
- Updated volume multiplier from 3x to 5x in comments

---

## Expected Results

**Target Metrics** (after improvements):
- **Accuracy**: 40-50% (vs 22.2% before)
- **Reversal Rate**: <30% (vs 55.6% before)
- **Alert Volume**: 5-10 alerts/month (vs 18/month before)
- **Risk/Reward**: Positive (avg gain > avg loss)

**Trade-offs**:
- ✅ **Quality**: Much higher signal quality, fewer false positives
- ✅ **Accuracy**: 2x improvement in prediction accuracy
- ⚠️ **Volume**: Fewer alerts (but that's intentional - quality over quantity)

---

## Testing Plan

1. **Run service for 1 week** with new filters
2. **Monitor logs** for momentum filter stats
3. **Track alert performance** (success vs failure rate)
4. **Measure reversal rate** (price reversals within 10 min)

If needed, can tune:
- **Acceleration threshold**: Currently 1.2x (20% faster) - can adjust to 1.3x or 1.1x
- **Volume multiplier**: Can reduce to 4.5x if too few alerts

---

## Files Modified

1. **config.py** (line 43)
   - Increased `VOLUME_SPIKE_MULTIPLIER_1MIN` from 3.0 to 5.0

2. **onemin_alert_detector.py** (lines 31-115, 263-329)
   - Added `price_5min_ago` parameter to detection methods
   - Added Layer 6: Momentum confirmation methods
   - Updated documentation

3. **onemin_monitor.py** (lines 242-259)
   - Fetch `price_5min_ago` from cache
   - Pass to detector methods

4. **ONEMIN_IMPROVEMENTS.md** (new file)
   - This documentation

---

## Monitoring Commands

```bash
# Check if 1-min monitor is running
ps aux | grep onemin_monitor.py

# View live logs
tail -f logs/onemin_monitor.log | grep -E "DROP detected|RISE detected|accelerating"

# Count alerts by type
grep "detected" logs/onemin_monitor.log | tail -100

# Check momentum filter stats
grep "accelerating" logs/onemin_monitor.log | tail -50
```

---

## Rollback Plan (if needed)

If accuracy doesn't improve after 1 week:

```bash
# Revert volume multiplier to 3.0x
# Edit config.py line 43:
VOLUME_SPIKE_MULTIPLIER_1MIN = 3.0

# Comment out momentum check in onemin_alert_detector.py lines 69-70, 112-113:
# if price_5min_ago and not self._has_drop_momentum(...):
#     return False

# Restart service
./onemin_service.sh restart
```

---

## Next Steps

1. ✅ Commit changes to git
2. ⏳ Monitor for 1 week during market hours
3. ⏳ Collect metrics (accuracy, reversal rate, alert volume)
4. ⏳ Fine-tune acceleration threshold if needed
5. ⏳ Run another 30-day backtest to validate improvements
