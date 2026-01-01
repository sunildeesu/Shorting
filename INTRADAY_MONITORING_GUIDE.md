# NIFTY Option Intraday Monitoring - Complete Guide

## Overview

The NIFTY Option Indicator now features **full intraday monitoring** with:
- Entry signals at 10:00 AM
- Exit monitoring every 15 minutes
- **ADD POSITION signals** throughout the day
- Multi-layer position management (up to 3 layers)
- Automatic state tracking and alerting

## How It Works

### 1. Entry Analysis (10:00 AM)

**Runs at**: 10:00 AM sharp

**Signals**:
- **SELL** (Score ≥ 70): Enter position immediately
- **HOLD** (Score 40-69): No entry, but monitor for late entry
- **AVOID** (Score < 40): No entry

**Actions**:
- SELL → Record Layer 1 entry + Send Telegram alert
- HOLD/AVOID → No position, but intraday monitoring continues

### 2. Intraday Monitoring (10:15 AM - 3:25 PM)

**Runs**: Every 15 minutes (10:15, 10:30, 10:45, 11:00, ..., 15:15)

**For Each Check**:
1. ✅ **Check EXIT conditions** (if position exists)
2. ✅ **Check ADD POSITION conditions** (if < max layers)

### 3. Exit Signal Logic

**Triggers exit if ANY of these conditions**:

| Condition | Threshold | Weight |
|-----------|-----------|--------|
| Score deterioration | Drop > 20 points from entry | 30 |
| Score in AVOID zone | Current score < 40 | 40 |
| VIX spike | VIX increase > 20% from entry | 35 |
| Regime change | NEUTRAL → BULLISH/BEARISH | 25 |
| Strong OI buildup | LONG_BUILDUP or SHORT_BUILDUP | 20 |
| Large NIFTY move | > 2% from entry | 15 |

**Exit Score Calculation**:
- Each trigger adds weight
- Exit Score ≥ 50 = EXIT_NOW (High urgency)
- Exit Score 30-49 = EXIT_NOW (Medium urgency)
- Exit Score 15-29 = CONSIDER_EXIT (Low urgency)
- Exit Score < 15 = HOLD_POSITION

### 4. Add Position Logic (NEW!)

**Triggers add position if**:

| Condition | Requirement | Confidence |
|-----------|-------------|------------|
| Score in SELL zone | Current score ≥ 70 | +40% |
| Score improvement | Score improved ≥ 10 points from last layer | +30% |
| Early opportunity | Layer 1 or 2 (prefer early adds) | +20% |
| Exceptional score | Score ≥ 80 | +10% |

**Add Signal Calculation**:
- Confidence ≥ 50% = ADD_POSITION (add immediately)
- Confidence 30-49% = CONSIDER_ADD (weak signal)
- Confidence < 30% = NO_ADD

**Additional Requirements**:
- Maximum layers: 3 (configurable)
- Minimum interval: 30 minutes between adds
- Can add after 10:00 AM even if no initial entry (late entry)

## Position Layering Strategy

### Example Scenario

```
10:00 AM - Entry Analysis
   Score: 62/100 → HOLD (no entry)

10:15 AM - Intraday Check #1
   Score: 75/100 → ADD_POSITION (late entry)
   Action: Enter Layer 1 (LATE ENTRY)
   Alert: "Late entry opportunity - Score improved to 75"

10:45 AM - Intraday Check #3
   Score: 78/100 (improved +3 from Layer 1)
   Confidence: 40% (score in SELL zone only)
   Action: NO_ADD (need ≥10 point improvement)

11:30 AM - Intraday Check #6
   Score: 85/100 (improved +10 from Layer 1)
   Confidence: 90% (SELL zone + improvement + exceptional)
   Action: ADD_POSITION (Layer 2)
   Alert: "Add Layer 2 - Score 85/100, improved 10 points"

12:15 AM - Intraday Check #9
   Score: 88/100 (improved +3 from Layer 2)
   Confidence: 70% (SELL zone + exceptional)
   Time since Layer 2: 45 minutes ✓
   Action: ADD_POSITION (Layer 3 - MAX)
   Alert: "Add Layer 3 (MAX) - Score 88/100"

13:00 PM - Intraday Check #12
   Score: 50/100 (dropped 38 points from Layer 3!)
   Exit Score: 70 (score drop + now in HOLD zone)
   Action: EXIT_NOW (Medium urgency)
   Alert: "EXIT ALL - Score dropped 38 points"
```

## Configuration

### Position Sizing & Layering

```python
# Maximum layers (1 = no adds, 3 = up to 2 additional entries)
NIFTY_OPTION_MAX_LAYERS = 3

# Add position thresholds
NIFTY_OPTION_ADD_SCORE_THRESHOLD = 70  # Must be in SELL zone
NIFTY_OPTION_ADD_SCORE_IMPROVEMENT = 10  # 10+ point improvement
NIFTY_OPTION_ADD_MIN_INTERVAL = 30  # 30 minutes between adds

# Allow late entry after 10:00 AM if conditions improve
NIFTY_OPTION_ADD_AFTER_NO_ENTRY = True
```

### Exit Thresholds

```python
NIFTY_OPTION_EXIT_SCORE_DROP = 20  # Exit if score drops >20 points
NIFTY_OPTION_EXIT_VIX_SPIKE = 20.0  # Exit if VIX +20%
NIFTY_OPTION_EXIT_SCORE_THRESHOLD = 40  # Exit if score < 40
NIFTY_OPTION_EXIT_ON_REGIME_CHANGE = True
NIFTY_OPTION_EXIT_ON_STRONG_OI_BUILDUP = True
```

## Position State Tracking

### State File: `data/nifty_options/position_state.json`

```json
{
  "status": "ENTERED",
  "layers": [
    {
      "layer_number": 1,
      "timestamp": "2026-01-01T10:15:00",
      "score": 75.0,
      "nifty_spot": 26150.0,
      "vix": 9.5,
      "strategy": "straddle",
      "strikes": {"call": 26150, "put": 26150},
      "premium": 350.0
    },
    {
      "layer_number": 2,
      "timestamp": "2026-01-01T11:30:00",
      "score": 85.0,
      "nifty_spot": 26180.0,
      "vix": 9.2,
      "strategy": "straddle",
      "strikes": {"call": 26200, "put": 26200},
      "premium": 320.0
    }
  ],
  "entry_timestamp": "2026-01-01T10:15:00",
  "entry_score": 75.0,
  "last_check_timestamp": "2026-01-01T12:00:00",
  "last_check_score": 82.0
}
```

## Telegram Alerts

### Entry Alert (10:00 AM)
```
🟢 NIFTY OPTION SELLING SIGNAL 🟢
━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 01 Jan 2026 | ⏰ 10:00 AM

📊 SIGNAL: SELL ✅ (Score: 75.0/100)
💰 NIFTY Spot: ₹26,150.00

[Full analysis breakdown...]
```

### Add Position Alert (Intraday)
```
📈 ADD TO POSITION - Layer 2 📈
━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ 01 Jan 2026 | 11:30 AM

✅ ADD SIGNAL (Confidence: 90%)
💰 Current Score: 85.0/100
📊 Improvement: +10.0 points from Layer 1

🔢 Position Summary:
   • Total Layers: 2/3
   • Layer 1: 75.0/100 at 10:15 AM
   • Layer 2: 85.0/100 at 11:30 AM (NEW)

📋 Layer 2 Strikes:
   • Call: 26200 CE (₹165)
   • Put: 26200 PE (₹155)
   • Total Premium: ₹320
```

### Exit Alert (Intraday)
```
🚨 EXIT POSITION NOW 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ 01 Jan 2026 | 13:00 PM

❌ EXIT SIGNAL (Urgency: HIGH)
Exit Score: 70/100

⚠️ Exit Triggers:
   • Score dropped 38 points (Layer 3: 88 → current: 50)
   • Score below threshold (50 < 60)

📊 Position Summary:
   • Total Layers: 3
   • Entry Score: 75.0/100
   • Current Score: 50.0/100
   • Duration: 2h 45m

💡 Recommendation:
Exit position immediately - Market conditions deteriorated
```

### Late Entry Alert
```
📈 LATE ENTRY OPPORTUNITY 📈
━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ 01 Jan 2026 | 10:45 AM

✅ Entry signal after 10:00 AM
Initial 10:00 AM Signal: HOLD (62/100)
Current Score: 75.0/100 ✅

💡 Conditions improved significantly
Entering Layer 1 now...
```

## Usage

### Run Daemon (Recommended)

```bash
./venv/bin/python3 nifty_option_monitor.py --daemon
```

**What happens**:
- 10:00 AM: Entry analysis
- 10:15 AM: First intraday check (exit + add)
- 10:30 AM: Second intraday check
- ... (every 15 minutes)
- 15:15 PM: Last check before market close

### Manual Test

```bash
./venv/bin/python3 nifty_option_monitor.py --test
```

**Behavior**:
- Before 10:00 AM → Runs entry analysis
- After 10:00 AM → Runs intraday monitoring

### Reset Position State

```bash
./venv/bin/python3 nifty_option_monitor.py --reset
```

## Multi-Layer Position Management

### Benefits

1. **Scale into winners**: Add when score improves
2. **Reduce risk**: Small initial position, add if conditions strengthen
3. **Miss recovery**: Enter late if 10:00 AM signal was HOLD but improves
4. **Profit taking**: Exit all layers simultaneously when conditions deteriorate

### Strategy Recommendations

**Conservative (MAX_LAYERS = 1)**:
- Single entry at 10:00 AM
- All-or-nothing approach
- Lower capital efficiency
- Simpler management

**Moderate (MAX_LAYERS = 2)**:
- Initial entry + 1 add
- Scale in if score improves ≥10 points
- Balanced risk/reward
- **Recommended for most traders**

**Aggressive (MAX_LAYERS = 3)**:
- Initial + up to 2 adds
- Maximum capital deployment
- Highest profit potential
- More complex management
- Requires active monitoring

### Position Sizing Example

**Capital**: ₹1,00,000
**MAX_LAYERS**: 3
**Per Layer**: ₹33,333

| Time | Action | Score | Layer | Capital Used | Total Position |
|------|--------|-------|-------|--------------|----------------|
| 10:00 AM | HOLD | 65 | - | ₹0 | ₹0 |
| 10:30 AM | ADD (Late) | 75 | 1 | ₹33,333 | ₹33,333 |
| 11:15 AM | ADD | 82 | 2 | ₹33,333 | ₹66,666 |
| 12:00 PM | ADD | 88 | 3 | ₹33,333 | ₹1,00,000 |
| 13:30 PM | EXIT | 48 | ALL | -₹1,00,000 | ₹0 |

## Advanced Features

### 1. Position State Persistence

State survives:
- Script restarts
- System reboots (if daemon)
- Network interruptions

Resets automatically:
- New trading day (after 9:00 AM)
- Manual reset command

### 2. Duplicate Prevention

- Entry: Only once per day at 10:00 AM
- Add: Minimum 30-minute intervals
- Exit: Only when position exists
- Checks: Maximum once per 15-minute window

### 3. Confidence Scoring

Each add position signal includes confidence level:
- Helps prioritize adds
- Allows manual override on low confidence
- Logged for backtesting analysis

### 4. Late Entry Support

If 10:00 AM signal is HOLD but conditions improve:
- System treats first add as "Layer 1 (LATE ENTRY)"
- Marks clearly in alerts and logs
- Same monitoring as regular entry

## Monitoring Dashboard

### Real-time Status

The daemon logs position status every 5 minutes:

```
[10:05] No position today
[10:10] No position today
[10:15] Position ACTIVE: SELL (75.0/100) at 2026-01-01T10:15:00
[10:20] Position ACTIVE: SELL (75.0/100) at 2026-01-01T10:15:00
[10:35] Position ACTIVE: 2 layers
[11:35] Position ACTIVE: 3 layers (MAX)
[13:05] Position EXITED: Score dropped 38 points at 2026-01-01T13:00:00
```

### Position Summary

Get status anytime:
```python
from position_state_manager import PositionStateManager

manager = PositionStateManager()
print(manager.get_status_summary())
# Output: "Position ACTIVE: 2 layers - SELL (75.0/100) at 10:15 AM"

print(f"Layers: {manager.get_layer_count()}/3")
print(f"Can add: {manager.can_add_layer(max_layers=3, min_interval_minutes=30)}")
```

## Risk Management

### Layer Sizing Rules

**Equal Sizing** (Default):
- Layer 1: 33.3% of capital
- Layer 2: 33.3% of capital
- Layer 3: 33.3% of capital

**Pyramiding** (Aggressive):
- Layer 1: 50% of capital (larger initial)
- Layer 2: 30% of capital
- Layer 3: 20% of capital

**Anti-Pyramiding** (Conservative):
- Layer 1: 20% of capital (small test)
- Layer 2: 30% of capital
- Layer 3: 50% of capital (add more if working)

### Exit Discipline

**All layers exit together**:
- No partial exits
- Simplifies management
- Clear risk/reward

**Override exit signals**:
- Manual review recommended for CONSIDER_EXIT
- Must exit on EXIT_NOW signals
- Track override performance

## Excel Tracking

### Entry Log
- Date, Time, Signal, Score
- Layer number (1, 2, or 3)
- Strikes, Premium, Greeks
- Late entry flag

### Exit Log
- Exit time, Reason, Urgency
- Score change from entry
- VIX change, NIFTY move
- Estimated P&L

### Performance Tracking
- Win rate by layer count
- Average score at entry/exit
- Time in position
- Best/worst add timing

## Troubleshooting

### Issue: "Cannot add layer: Already at max 3 layers"

**Cause**: Position fully deployed

**Solution**:
- Wait for exit signal
- Or increase MAX_LAYERS in config (not recommended > 3)

### Issue: "Cannot add layer: Only 15 min since last"

**Cause**: Too soon after last add

**Solution**:
- Wait for MIN_INTERVAL to pass (30 minutes)
- Or reduce MIN_INTERVAL in config (risky)

### Issue: "No add signal - Conditions not favorable"

**Cause**: Score hasn't improved enough or below threshold

**Details**:
- Need score ≥ 70 (SELL zone)
- Need ≥10 point improvement from last layer
- Check current score in logs

## Performance Metrics

Track these metrics for optimization:

1. **Layer efficiency**: Win rate by number of layers
2. **Add timing**: Average score improvement at each add
3. **Exit accuracy**: False exits vs real deteriorations
4. **Late entry success**: Performance of late vs on-time entries

## Best Practices

1. **Start conservative**: Use MAX_LAYERS=2 initially
2. **Monitor actively**: Don't rely 100% on automation
3. **Review alerts**: Understand why adds/exits triggered
4. **Track performance**: Use Excel logs for analysis
5. **Adjust thresholds**: Tune based on your risk tolerance

## Summary

The intraday monitoring system provides:

✅ **Automated entry** at 10:00 AM
✅ **Late entry** if conditions improve
✅ **Multi-layer scaling** (up to 3 entries)
✅ **Exit protection** every 15 minutes
✅ **Telegram alerts** for all signals
✅ **Excel tracking** for performance analysis
✅ **State persistence** across restarts

**Net result**: Professional-grade intraday option selling system with intelligent position management!

---

**Version**: 2.0 (Intraday Monitoring + Multi-Layer)
**Last Updated**: January 1, 2026
**Status**: Production Ready
