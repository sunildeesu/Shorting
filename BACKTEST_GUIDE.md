# Alert System Backtesting Guide

This guide explains how to run a 1-month backtest of the alert system to populate historical alerts into the Excel tracking file.

## What the Backtest Does

The backtest script will:

1. **Fetch Historical Data**: Downloads 5-minute intraday candles for the past 30 days
2. **Detect Alerts**: Applies the same alert detection logic used in live monitoring
3. **Track Price Movements**: Calculates actual prices at 2min, 10min, and EOD after each alert
4. **Log to Excel**: Populates the Excel file with all historical alerts and their outcomes
5. **Generate Statistics**: Provides success rate and performance metrics

## Prerequisites

### 1. Valid Kite Access Token

**IMPORTANT**: The backtest requires a valid Kite API token. If your token is expired:

```bash
# Refresh your Kite token first
./venv/bin/python3 generate_kite_token.py
```

Follow the prompts to:
- Open the Kite login URL
- Log in to Kite
- Copy the access token
- Token will be saved automatically

### 2. Clear Existing Test Data (Optional)

If you want a fresh start, remove the test data:

```bash
# Backup current Excel file (if you want to keep test data)
mv data/alerts/alert_tracking.xlsx data/alerts/alert_tracking_test_backup.xlsx

# Or just delete it for a fresh start
rm data/alerts/alert_tracking.xlsx
```

## Running the Backtest

### Basic Usage (30 days)

```bash
./venv/bin/python3 backtest_alerts_1month.py
```

This will:
- Backtest the past 30 days
- Analyze first 20 stocks (for speed)
- Take approximately 10-15 minutes

### Custom Time Period

```bash
# Backtest last 7 days only
./venv/bin/python3 backtest_alerts_1month.py --days 7

# Backtest last 60 days
./venv/bin/python3 backtest_alerts_1month.py --days 60
```

## Configuration

### Stocks to Backtest

By default, the script backtests the **first 20 stocks** from `fo_stocks.json` for speed.

To backtest ALL 210 stocks, edit `backtest_alerts_1month.py` line 92:

```python
# Before (fast, 20 stocks):
return data['stocks'][:20]

# After (complete, all stocks):
return data['stocks']
```

**Note**: Backtesting all stocks will take **1-2 hours** due to API rate limits.

### Alert Criteria

The backtest uses the same criteria from `config.py`:

```python
DROP_THRESHOLD_5MIN = 1.25%       # 5-minute rapid drop
DROP_THRESHOLD_PERCENT = 2.0%     # 10-minute standard drop
DROP_THRESHOLD_30MIN = 3.0%       # 30-minute cumulative drop
DROP_THRESHOLD_VOLUME_SPIKE = 1.2%   # With volume spike
VOLUME_SPIKE_MULTIPLIER = 2.5x    # Volume multiplier
```

## Expected Output

### Console Output

```
================================================================================
ALERT BACKTEST - 1 MONTH
================================================================================

Backtest Period: 2025-10-10 to 2025-11-09
Stocks to analyze: 20

Alert Criteria:
  5-min drop:      1.25%
  10-min drop:     2.00%
  30-min drop:     3.00%
  Volume spike:    1.20% + 2.5x volume

============================================================
Backtesting: RELIANCE
============================================================
Fetched 2847 candles for RELIANCE
Found 12 alerts for RELIANCE
  ✓ 5min         | 2025-11-01 10:25:00 | ₹1456.20 → ₹1454.80
  ✓ 10min        | 2025-11-01 14:50:00 | ₹1460.30 → ₹1458.90
  ... (more alerts)

[Processing continues for each stock...]

================================================================================
BACKTEST SUMMARY
================================================================================

Total Alerts Found: 245

Alerts by Type:
  5min           :   78 ( 31.8%)
  10min          :   95 ( 38.8%)
  30min          :   52 ( 21.2%)
  volume_spike   :   20 (  8.2%)

Top 10 Most Active Stocks:
  RELIANCE    :  18 alerts
  TATASTEEL   :  15 alerts
  HDFCBANK    :  14 alerts
  ... (more stocks)

Prediction Accuracy:
  Successful: 156 ( 63.7%)  ← Price continued in alert direction
  Failed:      89 ( 36.3%)  ← Price reversed

Excel File: data/alerts/alert_tracking.xlsx
================================================================================

✅ Backtest completed successfully!
📊 View results: open data/alerts/alert_tracking.xlsx
```

### Excel File Output

After the backtest, your Excel file will contain:

- **Hundreds of historical alerts** across 4 sheets
- **Complete price tracking** (2min, 10min, EOD)
- **All Status = "Complete"** (since we have EOD data)
- **Real historical data** showing actual outcomes

## Analysis & Insights

### Key Metrics to Analyze

Open the Excel file and analyze:

#### 1. Alert Type Effectiveness

```
Filter by Alert Type → Calculate average EOD return

Example findings:
- 5min alerts: Often catch early moves, -2.1% avg EOD return
- 10min alerts: More stable, -1.5% avg EOD return
- 30min alerts: Larger moves, -3.2% avg EOD return
- Volume spikes: Highest conviction, -2.8% avg EOD return
```

#### 2. Stock-Specific Patterns

```
Filter by Symbol → See which stocks have most alerts

High-alert stocks may indicate:
- Higher volatility (good for trading)
- Trending stocks (directional moves)
- Choppy stocks (many false alerts)
```

#### 3. Time-of-Day Analysis

```
Sort by Time → Group by time buckets

Example insights:
- Morning (9:30-11:00): Most volatile, many alerts
- Midday (11:00-14:00): Fewer alerts, consolidation
- Afternoon (14:00-15:25): End-of-day moves, volume surges
```

#### 4. Success Rate by Type

```
For each alert:
Success = EOD price moved further in alert direction
Fail = EOD price reversed

Calculate:
Success Rate = Successful / Total
```

## Performance & Timing

### Speed Estimates

| Stocks | Days | Estimated Time | API Calls |
|--------|------|----------------|-----------|
| 20 | 7 | 3-5 min | ~140 |
| 20 | 30 | 10-15 min | ~600 |
| 50 | 30 | 25-35 min | ~1500 |
| 210 (all) | 30 | 90-120 min | ~6300 |

### Rate Limiting

- Kite allows **3 requests/second**
- Script uses **0.4s delay** (2.5 req/sec safety margin)
- Historical data API is rate-limited separately

### Optimization Tips

1. **Start small**: Test with 20 stocks first
2. **Shorter periods**: Use `--days 7` for quick tests
3. **Run overnight**: For full 210-stock backtest

## Troubleshooting

### Issue: Kite Token Expired

```
Error: Incorrect `api_key` or `access_token`
```

**Solution**: Refresh your token
```bash
./venv/bin/python3 generate_kite_token.py
```

### Issue: No Data Returned

```
Warning: No data available for SYMBOL
```

**Causes**:
- Stock may not have traded during period
- Instrument token not found
- Weekend/holiday (no market data)

**Solution**: Normal behavior, script will continue

### Issue: Rate Limit Exceeded

```
Error: Too many requests
```

**Solution**: The script already has delays. If this happens:
1. Stop the script (Ctrl+C)
2. Wait 1-2 minutes
3. Re-run (it will continue from where it failed)

### Issue: Excel File Locked

```
Error: Permission denied
```

**Solution**: Close Excel before running the backtest

## Logs

All backtest activity is logged to:

```bash
# View live logs
tail -f logs/alert_backtest.log

# View summary
cat logs/alert_backtest.log | grep "SUMMARY" -A 20
```

## After Backtesting

### 1. Review Results

```bash
# Open Excel file
open data/alerts/alert_tracking.xlsx

# Review logs
open logs/alert_backtest.log
```

### 2. Analyze Performance

Use Excel to:
- Calculate average returns by alert type
- Identify best-performing patterns
- Find optimal holding periods
- Determine which stocks to focus on

### 3. Adjust Criteria (Optional)

Based on backtest results, you may want to adjust thresholds in `config.py`:

```python
# Example: If 5min alerts have too many false signals
DROP_THRESHOLD_5MIN = 1.5  # Increase from 1.25 to reduce noise

# Example: If volume spikes are rare but accurate
VOLUME_SPIKE_MULTIPLIER = 2.0  # Decrease from 2.5 to get more signals
```

Then re-run the backtest to validate changes.

## Next Steps

After completing the 1-month backtest:

1. ✅ **Review historical performance**
2. ✅ **Adjust alert criteria** if needed
3. ✅ **Start live monitoring** with confidence
4. ✅ **Compare live alerts** to historical patterns

The system is now ready for production with validated historical performance data!

---

## Quick Command Reference

```bash
# Refresh Kite token
./venv/bin/python3 generate_kite_token.py

# Run 30-day backtest (20 stocks)
./venv/bin/python3 backtest_alerts_1month.py

# Run 7-day backtest (faster)
./venv/bin/python3 backtest_alerts_1month.py --days 7

# Run 60-day backtest (more data)
./venv/bin/python3 backtest_alerts_1month.py --days 60

# View logs
tail -f logs/alert_backtest.log

# Open results
open data/alerts/alert_tracking.xlsx
```
