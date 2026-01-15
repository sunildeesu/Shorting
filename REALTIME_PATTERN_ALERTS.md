# Real-Time Pattern Detection Alerts

## Overview

Pattern detection alerts are now sent **in real-time** during market hours (every 5 minutes) rather than at end-of-day. This ensures traders receive actionable alerts while the opportunity still exists.

## Key Improvements

### 1. Immediate Alert Delivery
- **Before**: EOD pattern alerts sent after market close (3:30 PM+)
- **After**: Alerts sent within 5 minutes of pattern formation during market hours (9:25 AM - 3:25 PM)

### 2. Current Price Validation
The system now includes current market price in every alert and validates:

**For Bullish Patterns:**
- ✅ Alert sent if current price < target (opportunity exists)
- ❌ Alert skipped if current price >= target (opportunity passed)

**For Bearish Patterns:**
- ✅ Alert sent if current price > target (opportunity exists)
- ❌ Alert skipped if current price <= target (opportunity passed)

### 3. Enhanced Alert Information

Each alert now shows:
```
💰 TRADE SETUP
   Current: ₹2,450.00 🔴
   Entry:   ₹2,445.50
   Target:  ₹2,475.00 (+1.2% from entry | +1.0% remaining)
   Stop:    ₹2,435.00 (-0.4%)
   R:R Ratio: 1:2.9
```

Key metrics:
- **Current Price**: Live market price at time of alert
- **Entry Price**: Recommended entry point
- **Target**: Price target with % from entry AND % remaining from current price
- **Stop Loss**: Risk management level
- **R:R Ratio**: Risk-reward ratio

## How It Works

### Monitoring Schedule
- **Frequency**: Every 5 minutes during market hours
- **Market Hours**: 9:25 AM - 3:25 PM IST
- **Timeframe**: 5-minute candlesticks
- **Lookback**: 50 candles (~4 hours of data)

### Pattern Detection Flow

1. **Market Regime Check**
   - Analyzes Nifty 50 vs 50-day SMA
   - Determines BULLISH/BEARISH/NEUTRAL regime
   - Filters patterns based on market alignment

2. **Pattern Detection**
   - Scans all F&O stocks (170+ stocks)
   - Detects 16+ candlestick patterns
   - Calculates confidence scores (0-10 scale)
   - Only alerts on patterns with confidence >= 7.0

3. **Target Validation** ⭐ NEW
   - Checks if current price has exceeded target
   - Skips alert if opportunity has passed
   - Ensures only actionable alerts are sent

4. **Cooldown Management**
   - 30-minute cooldown per stock/pattern
   - Prevents alert spam
   - Allows re-alert after significant time gap

5. **Multi-Channel Notification**
   - Telegram alert with full details
   - Excel log for tracking performance
   - Alert history management

## Configuration

Edit `config.py` to customize:

```python
# Enable/disable price action alerts
ENABLE_PRICE_ACTION_ALERTS = True

# Minimum confidence score to send alert
PRICE_ACTION_MIN_CONFIDENCE = 7.0

# Minimum price filter (skip penny stocks)
PRICE_ACTION_MIN_PRICE = 50

# Minimum average volume filter
PRICE_ACTION_MIN_AVG_VOLUME = 500000

# Cooldown period between alerts (minutes)
PRICE_ACTION_COOLDOWN = 30

# Number of historical candles to analyze
PRICE_ACTION_LOOKBACK_CANDLES = 50
```

## Running the Monitor

### Manual Execution
```bash
./venv/bin/python3 price_action_monitor.py
```

### Automated Execution (cron/launchd)

Set up to run every 5 minutes during market hours:

**Cron example:**
```cron
*/5 9-15 * * 1-5 cd /path/to/ShortIndicator && ./venv/bin/python3 price_action_monitor.py
```

**LaunchAgent example:**
```xml
<!-- Every 5 minutes during market hours -->
<key>StartCalendarInterval</key>
<array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>25</integer></dict>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
    <!-- ... every 5 minutes until 15:25 ... -->
</array>
```

## Alert Examples

### Bullish Engulfing (High Confidence)
```
🟢🟢🟢 PRICE ACTION ALERT 🟢🟢🟢
━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 BULLISH PATTERN 📈
━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Stock: RELIANCE
⏰ Time: 11:05 AM
🌐 Market: BULLISH

🎯 PATTERN DETECTED
   Pattern: Bullish Engulfing
   Type: 🟢 BULLISH
   Confidence: 8.5/10 🔥🔥
   Strong bullish engulfing (2.3x size) after 2.5% decline

💰 TRADE SETUP
   Current: ₹2,450.00 🔴
   Entry:   ₹2,445.50
   Target:  ₹2,475.00 (+1.2% from entry | +1.0% remaining)
   Stop:    ₹2,435.00 (-0.4%)
   R:R Ratio: 1:2.9

🔍 CONFIDENCE BREAKDOWN
   • Body Ratio: 2.5
   • Volume: 2.0
   • Trend: 2.0
   • Position: 2.0
   • Regime: 1.0
```

### Opportunity Already Passed (Skipped)
```
[LOG] RELIANCE: Skipping Bullish Engulfing - price already at/above target
      (current: ₹2,480.00, target: ₹2,475.00)
```

## Benefits

1. **Timely Alerts**: Receive alerts while patterns are fresh and actionable
2. **No Wasted Alerts**: Filters out opportunities that have already passed
3. **Clear Decision Making**: Shows exact distance to target from current price
4. **Risk Management**: R:R ratio helps evaluate trade quality
5. **Performance Tracking**: Excel logs enable backtest analysis

## Pattern Types Detected

### Reversal Patterns (10)
- Bullish Engulfing ⭐
- Bearish Engulfing
- Hammer
- Shooting Star
- Inverted Hammer
- Hanging Man
- Morning Star (3-candle)
- Evening Star (3-candle)
- Piercing Pattern
- Dark Cloud Cover

### Continuation Patterns (4)
- Bullish Marubozu
- Bearish Marubozu
- Rising Three Methods
- Falling Three Methods

### Indecision Patterns (3)
- Doji
- Spinning Top
- Long-Legged Doji

### Multi-Candle Patterns (2)
- Three White Soldiers
- Three Black Crows

**Total: 19 patterns**

## Logs & Monitoring

- **Log File**: `logs/price_action_monitor.log`
- **Excel Log**: `data/alerts.xlsx` (if enabled)
- **Alert History**: Managed in-memory with cooldown tracking

## Troubleshooting

### No Alerts Received
1. Check if `ENABLE_PRICE_ACTION_ALERTS=True` in config
2. Verify market hours (9:25 AM - 3:25 PM)
3. Check confidence threshold (default: 7.0)
4. Review log file for patterns detected but filtered

### Too Many Alerts
1. Increase `PRICE_ACTION_MIN_CONFIDENCE` (try 7.5 or 8.0)
2. Increase `PRICE_ACTION_COOLDOWN` (try 60 minutes)
3. Add stocks to disabled list

### Alerts for Passed Opportunities
- Should not happen after this update
- If it does, check logs for current_price vs target comparison

## Future Enhancements

Potential improvements:
- [ ] Multi-timeframe confirmation (15-min + 5-min)
- [ ] Volume profile integration
- [ ] Support/resistance level validation
- [ ] Backtested win-rate display per pattern
- [ ] Webhook support for trading platforms
- [ ] SMS alerts for high-confidence patterns

## Version History

- **v2.0** (2026-01-15): Added current price validation and real-time filtering
- **v1.0** (2026-01-02): Initial 5-minute pattern detection system

---

**Status**: ✅ Production Ready

Last Updated: January 15, 2026
