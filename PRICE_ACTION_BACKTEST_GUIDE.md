# Price Action Pattern Backtesting Guide

## Overview
This guide explains how to backtest the 19 candlestick patterns on historical 5-minute data to validate performance before going live.

## Quick Start

### 1. Basic Backtest (Last 30 Days, All Stocks)
```bash
./backtest_price_action.py
```

### 2. Quick Test (10 stocks, 7 days)
```bash
./backtest_price_action.py --days 7 --stocks 10
```

### 3. Comprehensive Test (60 days, all stocks)
```bash
./backtest_price_action.py --days 60
```

### 4. Test Different Confidence Thresholds
```bash
# Test with confidence >= 8.0
./backtest_price_action.py --min-confidence 8.0

# Test with confidence >= 6.5
./backtest_price_action.py --min-confidence 6.5
```

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--days` | 30 | Lookback period (max 60 for 5-min data) |
| `--stocks` | All (~210) | Limit stocks for faster testing |
| `--min-confidence` | 7.0 | Minimum confidence score to test |

## What It Tests

### Pattern Detection
- Scans each 5-minute candle for all 19 patterns
- Applies confidence scoring (0-10 scale)
- Filters by minimum confidence threshold
- Tracks market regime (Nifty 50 vs 50-day SMA)

### Trade Simulation
For each detected pattern:
1. **Entry**: Checks if entry price was triggered (within 2 candles)
2. **Exit**: Tracks which came first:
   - Target hit ✅
   - Stop loss hit ❌
   - Time exit (after 20 candles / 100 minutes)
3. **P&L**: Calculates percentage gain/loss
4. **R:R**: Calculates risk:reward achieved

### Metrics Calculated
- **Win Rate %**: (Wins / Total Trades) × 100
- **Average R:R**: Average risk:reward achieved
- **Average P&L %**: Average percentage gain/loss
- **Target Hit %**: How often target was reached
- **Stop Hit %**: How often stop was hit

## Output Reports

### Excel File Location
```
data/backtests/price_action_backtest_YYYYMMDD_HHMMSS.xlsx
```

### Report Sheets

#### 1. All_Trades
Every single trade with:
- Symbol, Date, Pattern
- Type (bullish/bearish/neutral)
- Confidence score
- Market regime
- Entry/Exit prices
- Exit reason (TARGET_HIT, STOP_HIT, TIME_EXIT)
- P&L %, R:R achieved
- Win/Loss

#### 2. Pattern_Summary
Overall statistics by pattern:
- Total trades
- Win/Loss counts
- Win Rate %
- Avg R:R achieved
- Avg P&L %
- Target Hit %
- Stop Hit %

**Sorted by Win Rate (highest first)**

#### 3. By_Confidence
Win rates broken down by confidence score:
- Pattern + Confidence level
- Total trades at that confidence
- Win rate at that confidence
- Validates if higher confidence = better performance

#### 4. By_Regime
Win rates by market regime:
- Pattern + Regime (BULLISH/BEARISH/NEUTRAL)
- Shows if patterns perform better in certain market conditions

## Interpreting Results

### What to Look For

#### ✅ Good Patterns (Use Live)
- **Win Rate**: >=55%
- **Avg R:R**: >=1.0
- **Target Hit %**: >=40%
- **Sample Size**: >=20 trades

#### ⚠️ Marginal Patterns (Use with Caution)
- **Win Rate**: 45-55%
- **Avg R:R**: 0.7-1.0
- Review by confidence/regime for specific conditions

#### ❌ Poor Patterns (Avoid or Refine)
- **Win Rate**: <45%
- **Avg R:R**: <0.7
- Consider increasing min confidence or filtering

### Confidence Score Validation
Check "By_Confidence" sheet:
- **Expected**: Higher confidence = Higher win rate
- **Example**:
  - Confidence 7: 50% win rate
  - Confidence 8: 60% win rate
  - Confidence 9: 70% win rate

If this holds true → Confidence scoring works well ✅

### Market Regime Impact
Check "By_Regime" sheet:
- **Bullish Patterns**: Should perform better in BULLISH regime
- **Bearish Patterns**: Should perform better in BEARISH regime
- **Neutral Patterns**: Should work in all regimes

## Example Backtest Workflow

### Step 1: Quick Test (Validate Setup)
```bash
# Test 5 stocks for 7 days
./backtest_price_action.py --days 7 --stocks 5
```
**Expected**: ~50-200 patterns detected, report generated in <5 minutes

### Step 2: Medium Test (Initial Validation)
```bash
# Test 20 stocks for 14 days
./backtest_price_action.py --days 14 --stocks 20
```
**Expected**: ~500-1000 patterns, ~15 minutes

### Step 3: Full Backtest (Production Validation)
```bash
# All stocks, 30 days
./backtest_price_action.py --days 30
```
**Expected**: ~2000-5000 patterns, ~60-90 minutes

### Step 4: Review Results
1. Open Excel report
2. Check Pattern_Summary sheet
3. Identify top 5-10 patterns
4. Review confidence/regime breakdowns
5. Adjust min_confidence if needed

### Step 5: Confidence Tuning
```bash
# If overall win rate is low, increase threshold
./backtest_price_action.py --days 30 --min-confidence 8.0

# If too few patterns, decrease threshold
./backtest_price_action.py --days 30 --min-confidence 6.5
```

## Sample Output

```
================================================================================
BACKTEST SUMMARY
================================================================================
Total Patterns Tested: 2,347
Overall Win Rate: 58.3%

Top 5 Patterns by Win Rate:
Pattern                    Total Trades  Wins  Losses  Win Rate %  Avg R:R  Avg P&L %
Bullish Engulfing                   287   183     104        63.8     1.23       0.87
Three White Soldiers                 94    61      33        64.9     1.15       0.92
Morning Star                        142    88      54        62.0     1.08       0.76
Hammer                              198   113      85        57.1     1.02       0.54
Piercing Pattern                    156    87      69        55.8     0.98       0.48

================================================================================
Full report: data/backtests/price_action_backtest_20251227_143022.xlsx
================================================================================
```

## Troubleshooting

### "Insufficient data" warnings
- **Cause**: Stock may not have 5-min history
- **Solution**: Use shorter --days period or skip that stock

### "Failed to fetch Nifty data"
- **Cause**: Network/API issue
- **Solution**: Retry or check Kite token

### Very few patterns detected
- **Cause**: min-confidence too high
- **Solution**: Lower --min-confidence (try 6.5 or 6.0)

### Backtest taking too long
- **Cause**: Too many stocks × too many days
- **Solution**: Use --stocks to limit, or reduce --days

## Next Steps After Backtest

### If Results Are Good (Win Rate >55%)
1. ✅ Review top patterns in Pattern_Summary
2. ✅ Note optimal confidence threshold
3. ✅ Check regime preferences
4. ✅ Enable those patterns in live monitor
5. ✅ Set PRICE_ACTION_MIN_CONFIDENCE accordingly

### If Results Are Mixed (Win Rate 45-55%)
1. ⚠️ Filter by confidence (use only 8.0+)
2. ⚠️ Filter by regime (match pattern to regime)
3. ⚠️ Test with shorter timeframe (15-min instead of 5-min)
4. ⚠️ Review individual pattern logic

### If Results Are Poor (Win Rate <45%)
1. ❌ Increase min confidence to 8.0+
2. ❌ Disable poorly performing patterns
3. ❌ Review pattern detection logic
4. ❌ Consider alternative entry/exit rules

## Tips for Better Results

1. **Run multiple confidence levels**: Compare 6.5, 7.0, 7.5, 8.0
2. **Focus on high-volume stocks**: Add volume filter in backtest
3. **Test different periods**: Bull market vs Bear market periods
4. **Review individual trades**: Check All_Trades sheet for patterns
5. **Compare with existing alerts**: See how it compares to 1-min/ATR alerts

## Integration with Live Monitor

After backtesting, update `config.py`:

```python
# Based on backtest results:
PRICE_ACTION_MIN_CONFIDENCE = 7.5  # Adjust based on win rate
ENABLE_PRICE_ACTION_ALERTS = True   # Enable after validation

# Optional: Disable poor performing patterns by modifying detector
```

## Questions to Answer with Backtest

1. ✅ Do patterns work profitably on 5-min timeframe?
2. ✅ Which patterns have highest win rates?
3. ✅ Does confidence scoring correlate with success?
4. ✅ Do patterns perform better in aligned regimes?
5. ✅ What's the optimal confidence threshold?
6. ✅ How many alerts to expect per day?
7. ✅ Average R:R achieved vs theoretical R:R?
8. ✅ Hit rate on targets vs stops?

## Ready to Run!

```bash
# Start with quick test
./backtest_price_action.py --days 7 --stocks 10

# Then full test
./backtest_price_action.py --days 30

# Review results and go live!
```
