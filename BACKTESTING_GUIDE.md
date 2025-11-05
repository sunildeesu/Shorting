# Historical Backtesting Guide

## Overview

The backtesting script analyzes historical 5-minute candle data to find all occurrences when stocks dropped more than 2% in 10-minute intervals (comparing prices 10 minutes apart, same as live monitoring).

## Features

✅ **Historical Analysis**: Analyze past data to see when drops occurred
✅ **Date Range Selection**: Choose any date range for analysis
✅ **10-Minute Intervals**: Compares 10-min apart prices (matches live monitoring logic)
✅ **Same-Day Filter**: Excludes overnight gaps to show only intraday drops
✅ **Detailed Reports**: CSV export + summary statistics
✅ **Top Drops**: See largest and most recent drops

## Usage

### Quick Start (Last 7 Days)

```bash
# Run with default date range (last 7 days)
./venv/bin/python3 backtest_historical.py
# Press 'y' when prompted
```

### Custom Date Range

```bash
./venv/bin/python3 backtest_historical.py
# Press 'n' when prompted
# Enter start date: 2025-10-01
# Enter end date: 2025-10-30
```

## Output

### 1. Console Report

Shows:
- **Total drops found**
- **Drops by stock** (count, average, maximum)
- **Top 10 largest drops**
- **Most recent drops**

Example:
```
Total drops found: 1

Drops by Stock:
           drop_percent
                  count  mean   max
symbol
HINDUNILVR            1  3.33  3.33

Top 10 Largest Drops:
  2025-10-24 09:15:00+05:30 | HINDUNILVR | 3.33% drop | ₹2602.50 → ₹2515.80
```

### 2. CSV File (`backtest_results.csv`)

Columns:
- `symbol`: Stock symbol
- `timestamp`: When the drop occurred
- `prev_time`: Previous 5-min candle timestamp
- `prev_price`: Previous price
- `curr_price`: Current price
- `drop_percent`: Drop percentage
- `volume`: Trading volume

## Configuration

### Number of Stocks

By default, the script analyzes the **first 10 stocks** for quick testing.

To analyze more stocks, edit `backtest_historical.py`:

```python
# Line 33
return data['stocks'][:10]  # Change to [:50] or remove [:10] for all
```

### Drop Threshold

Uses the same threshold as live monitoring (2.0% by default).

To change, edit `.env`:
```bash
DROP_THRESHOLD_PERCENT=3.0  # Analyze 3%+ drops instead
```

## Performance

| Stocks | Days | Approx Time |
|--------|------|-------------|
| 10 | 7 | ~10 seconds |
| 50 | 7 | ~50 seconds |
| 191 | 7 | ~3 minutes |
| 10 | 30 | ~40 seconds |
| 191 | 30 | ~12 minutes |

**Note**: Kite Connect rate limits apply (3 requests/second)

## Use Cases

### 1. Validate System Logic
```bash
# Test last 7 days to see if any drops were detected
./venv/bin/python3 backtest_historical.py
```

### 2. Find High-Volatility Stocks
Analyze which stocks have the most frequent drops:
```python
# After running backtest, analyze backtest_results.csv
import pandas as pd
df = pd.read_csv('backtest_results.csv')
print(df['symbol'].value_counts())
```

### 3. Identify Best Trading Times
Find what time of day drops occur most frequently:
```python
df = pd.read_csv('backtest_results.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])
df['hour'] = df['timestamp'].dt.hour
print(df['hour'].value_counts())
```

### 4. Backtest Strategy Performance
Calculate how many drops you would have caught:
```python
df = pd.read_csv('backtest_results.csv')
print(f"Total opportunities: {len(df)}")
print(f"Average drop: {df['drop_percent'].mean():.2f}%")
print(f"Max drop: {df['drop_percent'].max():.2f}%")
```

## Analyze Results

### Load CSV in Python
```python
import pandas as pd

# Load results
df = pd.read_csv('backtest_results.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Stocks with most drops
print(df['symbol'].value_counts())

# Average drop by stock
print(df.groupby('symbol')['drop_percent'].mean().sort_values(ascending=False))

# Drops by day of week
df['day_name'] = df['timestamp'].dt.day_name()
print(df['day_name'].value_counts())

# Drops by time of day
df['hour'] = df['timestamp'].dt.hour
print(df.groupby('hour').size())
```

### Load CSV in Excel
1. Open `backtest_results.csv` in Excel
2. Use filters to sort by drop_percent
3. Create pivot tables for analysis

## Limitations

1. **Market Hours Only**: Only includes data during 9:15 AM - 3:30 PM IST
2. **Trading Days Only**: Excludes weekends and holidays
3. **Instrument Availability**: Some stocks may not have historical data
4. **Rate Limits**: Kite Connect has API rate limits
5. **Access Token**: Must be valid (24-hour validity)

## Troubleshooting

### "Instrument token not found"
Some stock symbols may have changed. Check NSE website for correct symbol.

### "No data returned"
- Market might have been closed on those dates
- Stock might not have been traded
- Try a different date range

### "Access token expired"
```bash
# Generate new token
./venv/bin/python3 generate_kite_token.py
# Then run backtest again
```

## Examples

### Example 1: Last Month Analysis
```bash
# Analyze entire October 2025
# Start: 2025-10-01, End: 2025-10-31
./venv/bin/python3 backtest_historical.py
```

### Example 2: Specific Event Analysis
```bash
# Analyze around a specific date (e.g., result day, budget day)
# Start: 2025-10-23, End: 2025-10-25
./venv/bin/python3 backtest_historical.py
```

### Example 3: Year-to-Date Analysis
```bash
# Analyze from Jan 1 to today
# Start: 2025-01-01, End: 2025-10-30
./venv/bin/python3 backtest_historical.py
```

## Advanced: Batch Analysis

To analyze multiple date ranges:

```python
from backtest_historical import HistoricalBacktest
from datetime import datetime
import pandas as pd

backtester = HistoricalBacktest()
all_results = []

# Analyze each month
months = [
    ("2025-01-01", "2025-01-31"),
    ("2025-02-01", "2025-02-28"),
    ("2025-03-01", "2025-03-31"),
]

for start, end in months:
    results = backtester.run_backtest(start, end)
    all_results.append(results)

# Combine all results
combined = pd.concat(all_results)
combined.to_csv('year_analysis.csv', index=False)
```

---

**Tip**: Start with a small date range (7 days) and few stocks (10) to test, then scale up!
