# 1-Minute Alert System Tuning Plan

## Problem Analysis

**Issue**: Zero alerts generated in 1 week of testing
**Root Cause**: Current filters are too restrictive - all stocks failing one or more layers

**Evidence**:
- `alert_history.json` shows ZERO alerts: `{"alerts": {}}`
- Logs show "Checked: 100 stocks" every cycle but no triggers
- All 6 filter layers must pass simultaneously - very strict

## Current Configuration (After Tuning)

```python
DROP_THRESHOLD_1MIN = 0.50%        # Price must drop 0.50% in 1 minute
RISE_THRESHOLD_1MIN = 0.50%        # Price must rise 0.50% in 1 minute
VOLUME_SPIKE_MULTIPLIER_1MIN = 2.5x  # Volume must be 2.5x average (percentage-based)
# NO MIN_VOLUME_1MIN - removed absolute minimum (was 40K-50K)
# Rationale: Different stocks have different volumes (large-cap: 500K/min, small-cap: 5K/min)
COOLDOWN_1MIN_ALERTS = 10 minutes  # 10-minute cooldown per stock
```

**6-Layer Filtering System** (After Tuning):
1. Price threshold (0.50% change) ✅ **TUNED**
2. Volume spike (2.5x average, percentage-based only) ✅ **TUNED - NO ABSOLUTE MINIMUM**
3. Quality filters (price >=50, liquidity >=500K daily avg)
4. Cooldown (10 minutes)
5. Cross-alert deduplication
6. Momentum confirmation (optional, for HIGH priority)

**Key Improvement - Percentage-Based Volume Filter**:
- **Removed** absolute minimum (was 40K-50K shares)
- **Using ONLY** 2.5x multiplier (percentage-based)
- **Rationale**: Different stocks have vastly different normal volumes:
  - RELIANCE: 500,000 shares/min normal (2.5x = 1.25M spike)
  - TCS: 50,000 shares/min normal (2.5x = 125K spike)
  - Small-cap: 5,000 shares/min normal (2.5x = 12.5K spike)
- A 2.5x spike is equally significant for all stock sizes
- Absolute minimums unfairly penalize smaller stocks

## Recommended Tuning Strategies

### Strategy 1: MODERATE Relaxation (✅ APPLIED - Current Config)

**Goal**: Get 5-10 quality alerts per day

```python
# Phase 1 Tuning (APPLIED)
DROP_THRESHOLD_1MIN = 0.50%        # Reduced from 0.75%
RISE_THRESHOLD_1MIN = 0.50%        # Reduced from 0.75%
VOLUME_SPIKE_MULTIPLIER_1MIN = 2.5x  # Reduced from 3.0x
# MIN_VOLUME_1MIN = REMOVED        # No absolute minimum (was 40K-50K)
```

**Rationale**:
- 0.50% in 1 minute is still significant (30% drop in 1 hour if sustained)
- 2.5x volume spike indicates unusual activity regardless of stock size
- Percentage-based volume filter is fair for all stocks (large-cap, mid-cap, small-cap)
- Removed absolute minimum volume - was unfairly filtering smaller stocks
- Other 4 layers still provide quality filtering

**Expected Impact**:
- 3-5x more stocks will meet price threshold
- 2x more stocks will meet volume threshold
- Combined: 6-10x more alerts (from 0 to 5-10 per day)

### Strategy 2: AGGRESSIVE Relaxation (If Strategy 1 Still Gets No Alerts)

**Goal**: Get 10-20 alerts per day, tune down later

```python
# Phase 2 Tuning (Apply if Phase 1 insufficient)
DROP_THRESHOLD_1MIN = 0.40%        # More relaxed
RISE_THRESHOLD_1MIN = 0.40%        # More relaxed
VOLUME_SPIKE_MULTIPLIER_1MIN = 2.0x  # More relaxed (minimum for "spike")
# MIN_VOLUME_1MIN = REMOVED        # Already removed - using percentage-based only
COOLDOWN_1MIN_ALERTS = 15 minutes  # Longer cooldown to reduce spam
```

**Rationale**:
- 0.40% is borderline but with 5 other filters, quality should be OK
- 2.0x volume spike is minimum for "unusual activity"
- Percentage-based volume is fair for all stock sizes
- 15-min cooldown prevents spam from same stock
- Can tighten later based on alert quality

### Strategy 3: TIERED Approach (Most Flexible)

**Goal**: Different thresholds for different priority levels

```python
# HIGH Priority (original thresholds - very rare but very valuable)
HIGH_PRIORITY_THRESHOLD = 0.75%
HIGH_PRIORITY_VOLUME = 3.0x

# NORMAL Priority (relaxed thresholds - more frequent)
NORMAL_PRIORITY_THRESHOLD = 0.50%
NORMAL_PRIORITY_VOLUME = 2.0x

# Send both to Telegram but with different icons/formatting
```

**Implementation**:
- HIGH priority: 🚨 emoji, "URGENT" tag
- NORMAL priority: 📊 emoji, "ALERT" tag
- User can filter by priority in Telegram

## Testing Plan

### Step 1: Apply Strategy 1 (Moderate Relaxation)

```bash
# Edit config.py
DROP_THRESHOLD_1MIN = 0.50
RISE_THRESHOLD_1MIN = 0.50
VOLUME_SPIKE_MULTIPLIER_1MIN = 2.5
MIN_VOLUME_1MIN = 40000
```

### Step 2: Monitor for 2-3 Days

**Success Criteria**:
- 5-10 alerts per day = GOOD (apply tuning complete)
- 1-4 alerts per day = BORDERLINE (consider Strategy 2)
- 0 alerts per day = FAIL (must apply Strategy 2)

**Quality Checks**:
- Are alerts actionable? (real price moves, not noise)
- Are you getting alerts from quality stocks (not penny stocks)
- Is volume confirmation working? (no low-volume fake moves)

### Step 3: Fine-Tune Based on Results

**If too many alerts (>20/day)**:
- Increase thresholds slightly (0.50% → 0.55%)
- Increase volume multiplier (2.5x → 2.75x)
- Reduce cooldown spam

**If too few alerts (<3/day)**:
- Decrease thresholds (0.50% → 0.45%)
- Decrease volume multiplier (2.5x → 2.0x)
- Check that service is running during market hours

**If alert quality is poor**:
- Add RSI filter (only alert if RSI < 40 for drops, >60 for rises)
- Add price range filter (only stocks in ₹100-2000 range)
- Add sector filter (avoid volatile small-cap sectors)

## Diagnostic Commands

### 1. Check if monitor is running

```bash
# Check service status
launchctl list | grep onemin

# Check recent logs
tail -50 logs/onemin_monitor.log

# Verify it runs during market hours
grep "Checked:" logs/onemin_monitor.log | tail -20
```

### 2. Run diagnostic script (during market hours)

```bash
# This shows exactly what's being filtered and why
./venv/bin/python3 diagnose_1min_filters.py
```

Output will show:
- How many stocks fail at each filter layer
- Current price changes vs threshold
- Current volume spikes vs threshold
- Specific recommendations

### 3. Check alert history

```bash
# See how many alerts were sent
cat data/alert_history.json | python3 -m json.tool

# Check Excel log
open data/alerts/alert_tracking.xlsx
```

### 4. Test with sample stock manually

```python
# Test TCS manually to see filter results
./venv/bin/python3 -c "
from onemin_monitor import OneMinMonitor
monitor = OneMinMonitor()
# This will show DEBUG logs for why TCS passes/fails filters
"
```

## Implementation Steps

### Step 1: Backup Current Config

```bash
cp config.py config.py.backup
```

### Step 2: Apply Strategy 1 Tuning

```bash
# Edit config.py
nano config.py

# Find these lines and update values:
DROP_THRESHOLD_1MIN = 0.50  # Changed from 0.75
RISE_THRESHOLD_1MIN = 0.50  # Changed from 0.75
VOLUME_SPIKE_MULTIPLIER_1MIN = 2.5  # Changed from 3.0
MIN_VOLUME_1MIN = 40000  # Changed from 50000
```

### Step 3: Restart 1-Min Monitor Service

```bash
# Stop current service
launchctl unload ~/Library/LaunchAgents/com.onemin.monitor.plist

# Start with new config
launchctl load ~/Library/LaunchAgents/com.onemin.monitor.plist

# Verify it's running
launchctl list | grep onemin
```

### Step 4: Monitor Results

```bash
# Watch logs in real-time (during market hours)
tail -f logs/onemin_monitor.log

# Check for alerts
cat data/alert_history.json

# Check Telegram for alert notifications
```

## Expected Timeline

**Day 1**: Apply Strategy 1, restart service, monitor logs
**Day 2-3**: Collect data, count alerts, assess quality
**Day 4**: Review results, decide if additional tuning needed
**Day 5**: Apply Strategy 2 if needed, or fine-tune Strategy 1
**Week 2**: System should be generating consistent quality alerts

## Success Metrics

**Target**: 5-10 actionable alerts per day

**Quality Indicators**:
- Alert triggers before 5-min alerts (ultra-fast detection ✓)
- Price continues in alert direction for 5+ minutes (prediction ✓)
- Volume confirms the move (not fake spikes ✗)
- Alerts from liquid, quality stocks only (no penny stocks ✗)

**Red Flags**:
- Too many alerts from same stock (tighten cooldown)
- Alerts on low-volume moves (increase volume threshold)
- False breakouts that reverse immediately (add momentum filter)
- Alerts from penny stocks (increase min price to ₹100)

## Rollback Plan

If tuning creates too many low-quality alerts:

```bash
# Restore original config
cp config.py.backup config.py

# Restart service
launchctl unload ~/Library/LaunchAgents/com.onemin.monitor.plist
launchctl load ~/Library/LaunchAgents/com.onemin.monitor.plist
```

## Advanced Tuning (After Basic Tuning Works)

Once getting 5-10 alerts/day, can add additional filters:

1. **RSI Filter**: Only alert if RSI confirms (RSI <30 for drops, >70 for rises)
2. **ATR Filter**: Require move > 2x ATR (filters noise in low-volatility stocks)
3. **Sector Filter**: Weight different sectors differently
4. **Time Filter**: Avoid first 15 min (volatile) and last 15 min (squaring off)
5. **Gap Filter**: Don't alert on gap-up/gap-down (wait for intraday move)

## Questions to Answer During Testing

1. **Are alerts timely?** (Do they trigger before big moves happen?)
2. **Are alerts accurate?** (Do prices continue in alert direction?)
3. **Are alerts actionable?** (Enough liquidity to actually trade?)
4. **Are there false positives?** (Fake breakouts, low-volume spikes?)
5. **Are there false negatives?** (Missing obvious big moves?)

## Comparison with Other Alert Systems

| System | Threshold | Frequency | Use Case |
|--------|-----------|-----------|----------|
| 5-min | 1.5% in 5 min | 10-20/day | Confirmed moves |
| 1-min (current) | 0.75% in 1 min | 0/day | **TOO STRICT** |
| 1-min (Strategy 1) | 0.50% in 1 min | 5-10/day | Ultra-fast detection |
| 1-min (Strategy 2) | 0.40% in 1 min | 10-20/day | More coverage |

## Next Steps

1. ✅ Created diagnostic script: `diagnose_1min_filters.py`
2. ⏳ **Apply Strategy 1 tuning** (reduce thresholds)
3. ⏳ **Test for 2-3 days** during market hours
4. ⏳ **Review results** and fine-tune
5. ⏳ **Document optimal parameters** for production use

---

**Note**: The fundamental problem is clear - current thresholds are too strict. Strategy 1 is a safe starting point that should generate alerts while maintaining quality. Monitor closely and iterate.
