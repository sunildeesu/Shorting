# ATR Breakout System Guide

## Overview

The ATR (Average True Range) Breakout System is a volatility-based trading strategy used by hedge funds to identify high-probability breakout opportunities. This system uses ATR as a dynamic measure of market volatility to:

1. **Identify Entry Points**: Detect when price breaks above a volatility-adjusted level
2. **Filter Weak Signals**: Use volatility contraction as a quality filter
3. **Manage Risk**: Set adaptive stop losses based on current market volatility

## Strategy Background

This strategy is based on the principle that **volatility contraction often precedes volatility expansion**. When short-term volatility (ATR20) is lower than long-term volatility (ATR30), it indicates the market is "coiling up" before a potential breakout move.

Source: Hedge fund trading strategy shared on Twitter (@onlybreakouts)

---

## Core Strategy Components

### 1. ATR for Entries

**Entry Rule**: Buy when price crosses above `Open + (2.5 × ATR(20))`

- Uses today's open as the baseline
- Adds 2.5 times the 20-period ATR to set the breakout level
- This ensures entry only on significant price moves beyond normal volatility

**Example**:
```
Stock: RELIANCE
Today's Open: ₹2,340.00
ATR(20): ₹20.00
Entry Level: ₹2,340 + (2.5 × ₹20) = ₹2,390.00
```

When RELIANCE price crosses ₹2,390, a breakout signal is generated.

### 2. ATR as a Filter (Volatility Contraction)

**Filter Rule**: Only take entries when `ATR(20) < ATR(30)`

- Short-term volatility must be LOWER than long-term volatility
- Indicates volatility is contracting (market quieting down)
- This "coiling" pattern often precedes strong directional moves
- Filters out breakouts during high/random volatility periods

**Why This Works**:
- Markets alternate between expansion and contraction
- Contraction = accumulation/distribution phase
- Expansion = trending/breakout phase
- Entering during contraction increases probability of catching the expansion

### 3. ATR for Exits (Stop Loss)

**Stop Loss Rule**: `Entry Price - (0.5 × ATR(20))`

- Tight stop loss at 0.5× ATR below entry
- Adapts to current market volatility
- Smaller ATR = tighter stops
- Larger ATR = wider stops (accommodates normal price swings)

**Example**:
```
Entry Level: ₹2,390.00
ATR(20): ₹20.00
Stop Loss: ₹2,390 - (0.5 × ₹20) = ₹2,380.00
Risk: ₹10.00 (0.42%)
```

### 4. Friday Exit Rule

**Exit Rule**: Close ALL open positions before market close on Friday

- Avoids weekend gap risk
- Part of the original strategy code
- Can be toggled via `ATR_FRIDAY_EXIT` config parameter

---

## Configuration Parameters

All parameters can be configured in `config.py` or via environment variables:

```python
# ATR Periods
ATR_PERIOD_SHORT = 20      # Short-term ATR (for entries and stops)
ATR_PERIOD_LONG = 30       # Long-term ATR (for volatility filter)

# Entry/Exit Multipliers
ATR_ENTRY_MULTIPLIER = 2.5  # Entry: Open + (2.5 × ATR)
ATR_STOP_MULTIPLIER = 0.5   # Stop: Entry - (0.5 × ATR)

# Filters
ATR_FILTER_CONTRACTION = True   # Require ATR(20) < ATR(30)
ATR_FRIDAY_EXIT = True          # Close positions on Friday
ATR_MIN_VOLUME = 50             # Minimum daily volume (lakhs)

# Alerts
ENABLE_ATR_ALERTS = True        # Enable/disable ATR monitoring
```

### Environment Variables (.env)

You can override defaults using environment variables:

```bash
# .env file
ATR_PERIOD_SHORT=20
ATR_PERIOD_LONG=30
ATR_ENTRY_MULTIPLIER=2.5
ATR_STOP_MULTIPLIER=0.5
ATR_FILTER_CONTRACTION=true
ATR_FRIDAY_EXIT=true
ATR_MIN_VOLUME=50
ENABLE_ATR_ALERTS=true
```

---

## Installation & Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

New dependencies added:
- `pandas-ta==0.3.14b0` - For ATR calculation
- `openpyxl==3.1.2` - For Excel logging

### 2. Configure API Access

Ensure your `.env` file has Kite Connect credentials:

```bash
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
KITE_ACCESS_TOKEN=your_access_token
```

### 3. Prepare Data Files

The system requires:
- `fo_stocks.json` - List of F&O stocks to scan
- `data/instrument_tokens.json` - Kite instrument tokens (auto-generated on first run)
- `data/shares_outstanding.json` - For market cap calculation (optional)

---

## Usage

### Command Line

**Basic Run**:
```bash
python3 atr_breakout_monitor.py
```

**Make Executable**:
```bash
chmod +x atr_breakout_monitor.py
./atr_breakout_monitor.py
```

### Scheduled Execution (Cron)

Run daily after market open (e.g., 9:45 AM):

```bash
# Edit crontab
crontab -e

# Add this line (runs at 9:45 AM on weekdays)
45 9 * * 1-5 cd /path/to/ShortIndicator && ./atr_breakout_monitor.py >> logs/atr_monitor.log 2>&1
```

Run multiple times during the day:
```bash
# 9:45 AM, 11:00 AM, 1:00 PM, 2:30 PM
45 9,11,13 * * 1-5 cd /path/to/ShortIndicator && ./atr_breakout_monitor.py >> logs/atr_monitor.log 2>&1
30 14 * * 1-5 cd /path/to/ShortIndicator && ./atr_breakout_monitor.py >> logs/atr_monitor.log 2>&1
```

---

## How It Works

### Workflow

```
1. Load F&O Stocks (191 stocks)
   ↓
2. For each stock:
   ├─ Fetch 60 days of daily candles (OHLCV)
   ├─ Calculate ATR(20) and ATR(30)
   ├─ Calculate Entry Level: Open + 2.5×ATR(20)
   ├─ Get current market price
   └─ Check breakout conditions
   ↓
3. Breakout Detected if:
   ├─ Current Price >= Entry Level
   └─ ATR(20) < ATR(30) [if filter enabled]
   ↓
4. Send Alert:
   ├─ Telegram notification with full details
   └─ Log to Excel (data/alerts/alert_tracking.xlsx)
   ↓
5. Track Alert History:
   └─ Prevent duplicate alerts (1 per stock per day)
```

### Sample Output

```
============================================================
ATR BREAKOUT MONITOR - STARTING
============================================================
Date: 2025-11-12 10:30:15
Day of Week: Tuesday
Stocks to scan: 191
ATR Config: Short=20, Long=30
Entry Multiplier: 2.5x
Stop Multiplier: 0.5x
Volatility Filter: ENABLED
Friday Exit Rule: ENABLED
============================================================

[1/191] Analyzing RELIANCE...
[2/191] Analyzing TCS...
[3/191] Analyzing INFY...
...
[45/191] Analyzing TATAMOTORS...
TATAMOTORS: ✅ ATR BREAKOUT DETECTED!
TATAMOTORS: ATR breakout alert sent successfully
...
============================================================
SCAN COMPLETE
Total signals found: 3

Breakout Signals:
  - TATAMOTORS: ₹945.50 (Entry: ₹940.00, SL: ₹935.00)
  - BAJFINANCE: ₹6,520.00 (Entry: ₹6,500.00, SL: ₹6,480.00)
  - AXISBANK: ₹1,085.00 (Entry: ₹1,080.00, SL: ₹1,075.00)
============================================================
```

---

## Telegram Alert Format

When a breakout is detected, you receive a detailed Telegram alert:

```
🎯🎯🎯 ATR BREAKOUT SIGNAL 🎯🎯🎯
━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ VOLATILITY CONTRACTION BREAKOUT ⚡
━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Stock: RELIANCE
💰 Market Cap: ₹12,345 Cr

📈 Breakout Details:
   Today's Open: ₹2,340.00
   Entry Level: ₹2,390.00 (O + 2.5×ATR)
   Current Price: ₹2,395.50 ✅
   Breakout: +₹5.50 above entry

📊 ATR Analysis:
   ATR(20): ₹20.00
   ATR(30): ₹22.50
   Filter Status: ✅ PASSED
   💡 Volatility contracting (ATR20 < ATR30)

🛡️ Risk Management:
   Stop Loss: ₹2,385.00
   Risk: ₹10.50 (0.44%)
   R:R Ratio: 1:2 (₹21.00 target)

📊 Volume:
   Today: 125.50L shares

⏰ Time: 2025-11-12 10:30:15
```

### Friday Exit Reminder

On Fridays, you'll receive an additional reminder:

```
⚠️⚠️⚠️ FRIDAY EXIT REMINDER ⚠️⚠️⚠️
━━━━━━━━━━━━━━━━━━━━━━━━━━

🔔 ATR Breakout Strategy

Today is Friday. As per the ATR strategy rules:
📌 Close ALL open ATR breakout positions before market close

This is part of the weekly exit rule to avoid weekend risk.

⏰ Time: 14:30:00
```

---

## Excel Logging

All ATR breakout alerts are logged to: `data/alerts/alert_tracking.xlsx`

### Sheet: ATR_Breakout_alerts

**Columns** (22 total):
1. Date
2. Time
3. Symbol
4. Open
5. Entry Level
6. Current Price
7. Breakout Distance
8. ATR(20)
9. ATR(30)
10. Volatility Filter (PASSED/FAILED)
11. Stop Loss
12. Risk Amount
13. Risk %
14. Volume
15. Market Cap (Cr)
16. Telegram Sent
17. Price 2min (updated later)
18. Price 10min (updated later)
19. Price EOD (updated later)
20. Status (Pending/Partial/Complete)
21. Row ID (unique identifier)
22. Day of Week

### Price Tracking

You can use the existing price update scripts to track trade performance:

```bash
# Update prices 2 minutes after alert
python3 update_alert_prices.py

# Update EOD prices
python3 update_eod_prices.py
```

These will populate columns 17-19 for performance tracking.

---

## Trading the Strategy

### Entry Checklist

✅ **Before Taking Entry**:
1. Verify volatility filter passed (ATR20 < ATR30)
2. Confirm price is above entry level
3. Check day of week (avoid Friday entries if possible)
4. Verify volume is adequate (>50L shares)
5. Set stop loss immediately at Entry - 0.5×ATR

✅ **Position Sizing**:
- Risk per trade should be 0.5-1% of capital
- Calculate position size based on stop loss distance
- Example: ₹1L capital, 1% risk = ₹1,000 max loss
- If stop loss is ₹10, buy 100 shares (₹1,000 / ₹10)

### Risk Management Rules

1. **Always use stop loss**: Entry - (0.5 × ATR20)
2. **Never move stop loss lower**: Only trail stops upward
3. **Friday exit rule**: Close all positions before weekend
4. **No averaging down**: One entry per signal
5. **Target**: Aim for 1:2 risk-reward (2× the stop loss distance)

### Common Mistakes to Avoid

❌ **Don't**:
- Ignore the volatility filter (ATR20 < ATR30)
- Enter without setting stop loss
- Hold positions over the weekend
- Take multiple entries in the same stock
- Ignore high-volume requirement

✅ **Do**:
- Wait for both conditions (breakout + filter)
- Set stop loss immediately after entry
- Close positions on Friday
- Track trades in Excel for review
- Respect the 0.5× ATR stop loss distance

---

## Performance Tracking

### Recommended Metrics

Track these metrics in your Excel sheet:

1. **Win Rate**: % of trades hitting 1:2 target before stop
2. **Average R:R**: Actual reward:risk ratio achieved
3. **Best Performing Days**: Which days generate best signals
4. **Filter Impact**: Win rate with filter ON vs OFF
5. **Stock Performance**: Which F&O stocks work best

### Sample Analysis Queries

```python
# Calculate win rate from Excel data
# Column S (Price EOD) vs Column E (Entry Level) and Column K (Stop Loss)

If EOD Price > Entry + (2 × Risk): WIN
If EOD Price < Stop Loss: LOSS
Otherwise: Scratch/Small Win
```

---

## Troubleshooting

### Common Issues

**1. "No instrument tokens found"**
- Solution: Delete `data/instrument_tokens.json` and rerun
- Script will auto-fetch from Kite instruments dump

**2. "Insufficient data for ATR calculation"**
- Cause: Stock has less than 30 days of trading history
- Solution: Stock will be skipped automatically

**3. "Access token expired"**
- Solution: Generate fresh access token using `generate_kite_token.py`
- Update `.env` file with new token

**4. "No breakout signals found"**
- Normal: Breakouts are relatively rare (1-5% of stocks on any given day)
- If persistent: Check if volatility filter is too strict

**5. Excel file locked**
- Cause: File open in Excel or another process
- Solution: Close Excel and try again

### Debug Mode

Enable detailed logging:

```python
# In atr_breakout_monitor.py, change:
logging.basicConfig(level=logging.DEBUG)  # Instead of INFO
```

This will show:
- ATR values for each stock
- Entry level calculations
- Filter pass/fail reasons
- API request details

---

## Strategy Variations

### Aggressive (More Signals)

```python
ATR_ENTRY_MULTIPLIER = 2.0  # Lower threshold (more breakouts)
ATR_FILTER_CONTRACTION = False  # Disable filter
ATR_STOP_MULTIPLIER = 0.5  # Keep tight stops
```

### Conservative (Fewer, Higher Quality Signals)

```python
ATR_ENTRY_MULTIPLIER = 3.0  # Higher threshold (stronger breakouts)
ATR_FILTER_CONTRACTION = True  # Enable filter
ATR_STOP_MULTIPLIER = 0.75  # Wider stops
ATR_MIN_VOLUME = 100  # Higher volume requirement
```

### Intraday (Use 5-minute candles)

Modify `fetch_historical_data()` to use intraday data:

```python
df = self.fetch_historical_data(symbol, days_back=10, interval="5minute")
```

Note: This requires adjusting ATR periods (e.g., ATR(50) for 5min = roughly 4 hours of data)

---

## References

### Original Strategy Code (EasyLanguage)

```
if market position =0
    And AvgTrueRange(20) < AvgTrueRange(30)
then begin
    Buy next bar at OpenD(0) + (AvgTrueRange(20) * 2.5) stop;
end;

if marketposition = 1 then begin
    setstoploss(Bigpointvalue * (AvgTrueRange(20) * 0.5) );
    if dayweek(date) = 5 then setexitonclose;
end;
```

### Key Insights from the Strategy

1. **Entry Timing**: "next bar" = wait for price to actually break the level
2. **No Position Sizing in Code**: Assumes fixed size, we add volume filters
3. **Friday Exit**: Built into original strategy for good reason
4. **Stop Loss Multiplier**: 0.5× is aggressive but keeps risk tight

---

## Support & Feedback

- **Issues**: Report bugs or feature requests via GitHub Issues
- **Questions**: Check existing documentation first
- **Improvements**: Pull requests welcome!

---

## License

This strategy implementation is part of the ShortIndicator project.
Original strategy concept from hedge fund trading practices.

---

## Changelog

### v1.0.0 (2025-11-12)
- Initial implementation of ATR Breakout System
- Support for 191 F&O stocks
- Telegram alerts with detailed breakdown
- Excel logging with 22 columns
- Volatility contraction filter
- Friday exit rule
- Configurable parameters
- Alert deduplication (1 per day per stock)

---

**Happy Trading! 📈🎯**
