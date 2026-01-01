# NIFTY Option Selling Indicator - User Guide

## Overview

The NIFTY Option Selling Indicator is a comprehensive tool that analyzes market conditions to determine whether it's a good day for NIFTY straddle/strangle option selling. It runs daily at 10:00 AM and provides:

- **SELL/HOLD/AVOID signal** with 0-100 confidence score
- **Detailed analysis** of Greeks (Theta, Gamma, Delta)
- **Market context** (VIX, market regime, OI patterns)
- **Strike recommendations** for both straddles and strangles
- **Risk assessment** and actionable recommendations
- **Telegram alerts** with formatted analysis
- **Excel reports** for historical tracking

## Test Results (2026-01-01)

✅ **All Core Tests Passed**
```
✅ Configuration Test PASSED
✅ Kite Connect Test PASSED
✅ Analyzer Test PASSED
✅ Excel Logger Test PASSED
✅ Monitor Scheduler Test PASSED
```

**Live Market Data Retrieved:**
- NIFTY Spot: ₹26,146.05
- India VIX: 9.23 (Excellent - very low volatility!)
- Market Regime: NEUTRAL (Best for option selling)
- Signal: HOLD (Score: 62.0/100)
- Expiries Analyzed: Jan 06, 2026 and Jan 13, 2026

## How It Works

### Scoring Algorithm

The indicator uses a weighted scoring system (0-100):

| Factor | Weight | What It Measures |
|--------|--------|------------------|
| **Theta** | 25% | Time decay - Higher is better (faster premium erosion) |
| **Gamma** | 25% | Position stability - Lower is better (less delta risk) |
| **VIX** | 30% | Volatility - Lower is better (stable market) |
| **Market Regime** | 10% | Trend direction - NEUTRAL is best for straddles |
| **OI Analysis** | 10% | Institutional positioning - Consolidation is better |

### Signal Interpretation

- **SELL (70-100)**: ✅ Excellent conditions for option selling
  - High theta decay
  - Low gamma risk
  - Low VIX
  - Favorable market conditions

- **HOLD (40-69)**: ⏸️ Mixed conditions, wait for better setup
  - Some favorable factors
  - Some risks present
  - Better to wait

- **AVOID (0-39)**: 🛑 Unfavorable conditions, high risk
  - High volatility
  - High gamma risk
  - Trending market
  - Strong directional bias

## Usage

### 1. Test the System

Run comprehensive tests:
```bash
./venv/bin/python3 test_nifty_options.py
```

This will verify:
- Configuration
- Kite Connect authentication
- NIFTY data fetching
- Greeks calculation
- Excel logging
- Telegram notifications
- Monitor scheduling

### 2. Manual Analysis (Run Once)

Run analysis immediately (ignores schedule):
```bash
./venv/bin/python3 nifty_option_monitor.py --test
```

Output includes:
- Current NIFTY spot price
- India VIX level
- Market regime classification
- OI pattern analysis
- Complete score breakdown
- Strike recommendations
- Risk factors

### 3. Scheduled Analysis (Daemon Mode)

Run as daemon for daily 10:00 AM analysis:
```bash
./venv/bin/python3 nifty_option_monitor.py --daemon
```

The daemon will:
- Check every 60 seconds
- Run analysis at 10:00 AM on trading days
- Skip weekends automatically
- Prevent duplicate runs on same day
- Send Telegram alerts
- Log to Excel

### 4. Configure Analysis Time

Edit `config.py` to change the analysis time:
```python
NIFTY_OPTION_ANALYSIS_TIME = "10:00"  # HH:MM format
```

You can set it to any time, e.g., "09:30", "14:00", etc.

### 5. Enable/Disable Feature

Toggle the feature in `config.py`:
```python
ENABLE_NIFTY_OPTION_ANALYSIS = True  # or False to disable
```

## Output Formats

### 1. Telegram Alert

Formatted HTML message with:
- Signal header (colored by signal type)
- Current NIFTY spot and VIX
- Expiry dates with days remaining
- Complete score breakdown with emojis
- Strike suggestions for both straddle and strangle
- Premium amounts and theta decay
- Risk factors
- Actionable recommendation

Example:
```
🟢 NIFTY OPTION SELLING SIGNAL 🟢
━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 01 Jan 2026 | ⏰ 10:00 AM

📊 SIGNAL: SELL ✅ (Score: 75.5/100)
💰 NIFTY Spot: ₹26,150.00

📅 EXPIRIES:
   • Next Week: 06 Jan 2026 (5 days)
   • Next-to-Next: 13 Jan 2026 (12 days)

📈 ANALYSIS BREAKDOWN:
   ⏰ Theta Score: 80.0/100 ✅
   📉 Gamma Score: 85.0/100 ✅
   🌊 VIX Score: 100.0/100 ✅ (VIX at 9.2)
   📊 Market Regime: 100.0/100 (NEUTRAL)
   🔄 OI Pattern: 70.0/100

💡 RECOMMENDATION:
   Excellent conditions for option selling

⚠️ RISK FACTORS:
   • No significant risks identified

📋 SUGGESTED STRADDLE (06 Jan):
   • Call Strike: 26150 CE (₹180)
   • Put Strike: 26150 PE (₹175)
   • Total Premium: ₹355
   • Daily Theta Decay: ₹45/day
```

### 2. Excel Report

Monthly Excel files saved to `data/nifty_options/`:
- Filename: `nifty_options_YYYY-MM.xlsx`
- Color-coded signals (Green=SELL, Yellow=HOLD, Red=AVOID)
- All scores and metrics
- Strike prices and premiums
- Greeks values
- Recommendations and risk factors

Columns:
```
Date | Time | Signal | Total_Score | NIFTY_Spot | VIX | VIX_Score |
Market_Regime | Regime_Score | OI_Pattern | OI_Score |
Theta_Score | Gamma_Score | Best_Strategy | Expiry_1 |
Straddle_Premium | Straddle_Theta | Straddle_Gamma |
Strangle_Premium | Strangle_Theta | Strangle_Gamma |
Recommendation | Risk_Factors | Telegram_Sent
```

### 3. Console Output

Detailed logs showing:
- Step-by-step analysis progress
- Data fetching from Kite API
- Greeks calculation (API or Black-Scholes)
- Score calculations
- Final recommendation

## Greeks Calculation

### Primary Method: Kite API

The analyzer first attempts to get Greeks directly from Kite Connect API.

**Note**: As of 2026-01-01, Kite API does not provide Greeks in quote data.

### Fallback: Black-Scholes Approximation

If Greeks are not available from API, the system automatically calculates approximate Greeks using Black-Scholes model:

**Inputs:**
- Spot price (NIFTY current price)
- Strike price
- Time to expiry (in years)
- Risk-free rate (7% - India 10Y bond yield)
- Implied volatility (from option premium or VIX)

**Calculated Greeks:**
- **Delta**: Sensitivity to NIFTY price (0 to ±1)
- **Theta**: Daily time decay (negative for long positions)
- **Gamma**: Delta change per point move
- **Vega**: Sensitivity to IV change (per 1% IV move)

The approximation is accurate enough for option selling decisions, especially for ATM and near-ATM strikes.

## Strategy Recommendations

### When to Use STRADDLE

**Best When:**
- NIFTY exactly at round strike (26,000, 26,100, etc.)
- Market in tight range (low volatility)
- Expecting range-bound consolidation
- Higher premium collection needed

**Greeks Profile:**
- Higher absolute delta (cancels out for straddle)
- Higher theta decay (more premium to collect)
- Higher gamma risk (more adjustments needed)

### When to Use STRANGLE

**Best When:**
- NIFTY between strikes
- Want lower capital risk
- Willing to accept lower premium
- Expecting wider range consolidation

**Greeks Profile:**
- Lower absolute delta per leg
- Lower theta decay (less premium)
- Lower gamma risk (fewer adjustments)
- Wider breakeven range

## Risk Management

### Stop Loss Guidelines

The system doesn't provide stop loss, but here are best practices:

1. **Time-based**: Exit at 50% of max profit or after 50% of time
2. **Price-based**: Exit if NIFTY moves beyond strikes ± 1.5x premium
3. **Greeks-based**: Exit if delta exceeds ±0.3 (directional bias)

### Position Sizing

Recommended position sizing based on signal:

- **SELL Signal (70-100)**: 100% of allocated capital
- **HOLD Signal (40-69)**: 50% of allocated capital or skip
- **AVOID Signal (0-39)**: Do not enter

### Adjustment Triggers

Consider adjusting position when:
- NIFTY moves > 2% in one direction
- VIX spikes > 20% from entry
- Market regime changes (NEUTRAL → BULLISH/BEARISH)
- Days to expiry < 2 (gamma explosion risk)

## Configuration Reference

All configurable parameters in `config.py`:

```python
# Feature toggle
ENABLE_NIFTY_OPTION_ANALYSIS = True

# Scheduling
NIFTY_OPTION_ANALYSIS_TIME = "10:00"  # Daily analysis time

# Instrument tokens
NIFTY_50_TOKEN = 256265   # NIFTY 50 Index
INDIA_VIX_TOKEN = 264969  # India VIX

# Scoring thresholds
NIFTY_OPTION_SELL_THRESHOLD = 70    # Score >= 70 = SELL
NIFTY_OPTION_HOLD_THRESHOLD = 40    # Score 40-69 = HOLD

# VIX thresholds
VIX_EXCELLENT = 12.0      # VIX < 12 = 100 score
VIX_GOOD = 15.0           # VIX 12-15 = 75 score
VIX_MODERATE = 20.0       # VIX 15-20 = 40 score

# Greeks parameters
STRADDLE_DELTA_IDEAL = 0.5      # ATM delta
STRANGLE_DELTA_IDEAL = 0.35     # OTM delta
MIN_THETA_THRESHOLD = 20        # Min daily decay
MAX_GAMMA_THRESHOLD = 0.01      # Max gamma risk

# Scoring weights (must sum to 1.0)
THETA_WEIGHT = 0.25     # 25% weight
GAMMA_WEIGHT = 0.25     # 25% weight
VIX_WEIGHT = 0.30       # 30% weight
REGIME_WEIGHT = 0.10    # 10% weight
OI_WEIGHT = 0.10        # 10% weight
```

## Files Created

1. **nifty_option_analyzer.py** (765 lines)
   - Core analysis engine
   - NIFTY/VIX data fetching
   - Greeks extraction/calculation
   - Scoring algorithm
   - Recommendation generation

2. **nifty_option_logger.py** (257 lines)
   - Excel report generation
   - Monthly file organization
   - Historical data retrieval

3. **nifty_option_monitor.py** (312 lines)
   - Daily scheduler
   - Daemon mode
   - Token validation
   - Telegram/Excel integration

4. **telegram_notifier.py** (Extended)
   - Added `send_nifty_option_analysis()` method
   - Added `_format_nifty_option_message()` formatter
   - HTML formatting with emojis

5. **config.py** (Extended)
   - Added NIFTY options configuration section
   - 19 new configuration parameters

6. **test_nifty_options.py** (395 lines)
   - Comprehensive test suite
   - 6 different test scenarios
   - Interactive Telegram test

## Integration with Existing System

The NIFTY Option Indicator integrates seamlessly with existing components:

- **TokenManager**: Validates Kite token before analysis
- **MarketRegimeDetector**: Provides market regime (BULLISH/BEARISH/NEUTRAL)
- **OIAnalyzer**: Analyzes NIFTY futures OI patterns
- **TelegramNotifier**: Sends formatted alerts
- **UnifiedQuoteCache**: Caches quote data to reduce API calls

Zero changes were needed to existing components - only extensions were added.

## Automation Setup

### Run Daily at 10:00 AM (macOS)

Create a launchd plist file:
```bash
nano ~/Library/LaunchAgents/com.nifty.option.monitor.plist
```

Content:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nifty.option.monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3</string>
        <string>/Users/sunildeesu/myProjects/ShortIndicator/nifty_option_monitor.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>10</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/nifty_option_monitor.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/sunildeesu/myProjects/ShortIndicator/logs/nifty_option_monitor_error.log</string>
</dict>
</plist>
```

Load the plist:
```bash
launchctl load ~/Library/LaunchAgents/com.nifty.option.monitor.plist
```

### Run Daily at 10:00 AM (Linux)

Add to crontab:
```bash
crontab -e
```

Add line:
```
0 10 * * 1-5 cd /path/to/ShortIndicator && ./venv/bin/python3 nifty_option_monitor.py >> logs/nifty_option_monitor.log 2>&1
```

## Troubleshooting

### Issue: "Kite token invalid"

**Solution**: Refresh Kite token
```bash
python3 generate_kite_token.py
```

### Issue: "Insufficient Nifty data"

**Cause**: Market closed or API rate limit

**Solution**:
- Wait for market hours
- Check Kite API status
- Verify token has not expired

### Issue: "Greeks not available in API"

**This is expected** - Kite API doesn't provide Greeks.

The system automatically falls back to Black-Scholes approximation.

### Issue: "No expiries found"

**Cause**: Market holiday or NFO instruments not loaded

**Solution**:
- Check if today is a trading day
- Verify NFO instruments API is working
- Check logs for API errors

## Performance & API Usage

### API Calls Per Analysis

- NIFTY spot price: 1 call
- India VIX: 1 call
- NIFTY futures (OI): 1 call
- Market regime (historical): 1 call
- NFO instruments: 1 call (cached for 1 hour)
- Option quotes: 8 calls (4 per expiry × 2 expiries)

**Total: ~13 API calls per analysis** (once per day)

### Rate Limits

Kite Connect allows 3 requests/second for quote API.

The analyzer adds small delays between calls to stay within limits.

### Caching

- NFO instruments: Cached for 1 hour
- Market regime: Cached for 6 hours
- OI analysis: Day-start OI cached until next trading day

## Future Enhancements

Potential features for future versions:

1. **Backtesting Module**: Historical signal accuracy
2. **Position Sizing**: Risk-based lot calculation
3. **Adjustment Alerts**: When to adjust positions
4. **IV Rank**: Historical IV percentile tracking
5. **Iron Condor**: Additional strategy analysis
6. **Intraday Updates**: Real-time score monitoring
7. **Mobile App**: Push notifications
8. **Web Dashboard**: Visual analytics

## Support & Feedback

For issues or feature requests:
1. Check logs in `logs/nifty_option_monitor.log`
2. Run test suite: `./venv/bin/python3 test_nifty_options.py`
3. Review this guide for common issues

## Disclaimer

⚠️ **Important**: This indicator is for educational and informational purposes only.

- Options trading involves substantial risk
- Past performance does not guarantee future results
- Always use proper risk management
- Consult a financial advisor before trading
- The author is not responsible for any trading losses

Trade at your own risk!

---

**Author**: Sunil Kumar Durganaik
**Version**: 1.0
**Last Updated**: January 1, 2026
**Status**: ✅ Tested and Production Ready
