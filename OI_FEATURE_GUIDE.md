# OI (Open Interest) Analysis Feature Guide

## Overview

The OI (Open Interest) Analysis feature helps distinguish between **strong price moves** (backed by fresh institutional positions) and **weak price moves** (caused by position unwinding). This provides critical context for trading decisions.

**Key Benefit:** ZERO additional API calls - OI data is already included in Kite quote API responses!

## What is Open Interest?

Open Interest (OI) represents the total number of outstanding derivative contracts (futures/options) that have not been settled. Rising OI indicates fresh positions building, while falling OI indicates position unwinding.

## The 4 OI Patterns

The system classifies price+OI movements into 4 distinct patterns:

### 1. **LONG BUILDUP** 🟢
- **Pattern:** Price ↑ + OI ↑
- **Signal:** BULLISH
- **Interpretation:** Fresh buying with institutional support
- **Meaning:** Strong bullish momentum - institutions are building long positions
- **Action:** High confidence buy signal

### 2. **SHORT BUILDUP** 🔴
- **Pattern:** Price ↓ + OI ↑
- **Signal:** BEARISH
- **Interpretation:** Fresh selling with institutional participation
- **Meaning:** Strong bearish momentum - institutions are building short positions
- **Action:** High confidence sell signal (or avoid buying)

### 3. **SHORT COVERING** 🟡
- **Pattern:** Price ↑ + OI ↓
- **Signal:** WEAK_BULLISH
- **Interpretation:** Short covering - likely to reverse
- **Meaning:** Weak rally without institutional support
- **Action:** Exercise caution - rally may not sustain

### 4. **LONG UNWINDING** 🟠
- **Pattern:** Price ↓ + OI ↓
- **Signal:** WEAK_BEARISH
- **Interpretation:** Long unwinding - likely to reverse
- **Meaning:** Weak fall without fresh selling pressure
- **Action:** May find support soon - not a strong sell signal

## OI Change Strength Levels

The system categorizes OI changes into 4 strength levels:

| Strength | OI Change | Confidence | Description |
|----------|-----------|------------|-------------|
| **VERY_STRONG** | ≥15% | Very High | Exceptional institutional activity |
| **STRONG** | ≥10% | High | Strong institutional interest |
| **SIGNIFICANT** | ≥5% | Medium | Notable OI movement |
| **MINIMAL** | <5% | Low | Small OI change (ignored in analysis) |

## Priority Levels

The system assigns priority to alerts based on pattern + OI strength:

| Priority | Conditions | Description |
|----------|-----------|-------------|
| **HIGH** | Very Strong OI (≥15%) + Moderate price move (≥2%) | Immediate attention required |
| **HIGH** | LONG/SHORT BUILDUP + Strong OI (≥10%) | Fresh institutional positions |
| **MEDIUM** | Strong/Very Strong OI change | Significant institutional activity |
| **MEDIUM** | BUILDUP patterns + Significant OI (≥5%) | Moderate institutional interest |
| **LOW** | All other combinations | Normal market activity |

## Configuration

All OI settings are in `config.py`:

```python
# Enable/Disable OI Analysis
ENABLE_OI_ANALYSIS = True  # Set to False to disable

# OI Change Thresholds (in percentage)
OI_SIGNIFICANT_THRESHOLD = 5.0   # 5% change - worth noting
OI_STRONG_THRESHOLD = 10.0       # 10% change - strong signal
OI_VERY_STRONG_THRESHOLD = 15.0  # 15% change - very strong signal

# Cache location for OI history
OI_CACHE_FILE = 'data/oi_cache/oi_history.json'
```

You can also set these via environment variables:
```bash
export ENABLE_OI_ANALYSIS=true
export OI_SIGNIFICANT_THRESHOLD=5.0
export OI_STRONG_THRESHOLD=10.0
export OI_VERY_STRONG_THRESHOLD=15.0
```

## How It Works

### 1. Data Collection (ZERO API calls)
- OI data (`oi`, `oi_day_high`, `oi_day_low`) is already in Kite quote API responses
- No additional API calls needed!

### 2. OI Change Calculation (Day-Start Comparison)
- System tracks day-start OI (first OI of trading session) in `data/oi_cache/oi_history.json`
- **Calculates OI change % from day-start (market open), not previous 5-minute snapshot**
- Shows cumulative institutional positioning throughout the trading session
- Automatically resets at market open (9:15 AM) each trading day
- **More meaningful than minute-by-minute comparison:** OI builds gradually over hours

### 3. Pattern Classification
- Combines price change direction + OI change direction
- Assigns pattern (LONG_BUILDUP, SHORT_BUILDUP, etc.)
- Determines signal strength and priority

### 4. Alert Enhancement
- **OI analysis added to ALL alerts** (5-min, 10-min, 30-min, volume spike)
- Logged to Excel with 6 new columns
- Shows institutional context for every F&O stock alert

## Telegram Alert Format

OI information appears in ALL alerts for F&O stocks:

```
🔥 OI ANALYSIS: 🔥
   🟢 Pattern: Long Buildup
   🔥🔥 OI Change: +12.50% (STRONG)
   🟢 Signal: BULLISH
   💡 Meaning: Fresh buying - Strong bullish momentum
   ⚠️ PRIORITY: HIGH - Fresh positions building!
```

## Excel Tracking

The system logs 6 new OI columns to `data/alerts/alert_tracking.xlsx`:

| Column | Description | Example |
|--------|-------------|---------|
| **OI Current** | Current open interest value | 1,150,000 |
| **OI Change %** | OI change from previous snapshot | 12.50 |
| **OI Pattern** | Pattern classification | LONG_BUILDUP |
| **OI Signal** | Trading signal | BULLISH |
| **OI Strength** | OI change strength | STRONG |
| **OI Priority** | Alert priority level | HIGH |

## Files Modified

### Core Implementation
- **`oi_analyzer.py`** - Main OI analysis logic (NEW)
- **`stock_monitor.py`** - Integration with monitoring system
- **`telegram_notifier.py`** - OI section in Telegram alerts
- **`alert_excel_logger.py`** - OI columns in Excel tracking
- **`config.py`** - OI configuration settings

### Data Structure Changes
- **`fetch_all_prices_batch()`** - Returns dict instead of tuple:
  ```python
  # Old: {symbol: (price, volume)}
  # New: {symbol: {'price': x, 'volume': y, 'oi': z, ...}}
  ```

## Testing

Run the integration test to verify everything works:

```bash
./test_oi_integration.py
```

Expected output:
```
✅ PASS: OI Analyzer
✅ PASS: Excel Logger Headers
✅ PASS: Method Signature
✅ PASS: Config Settings

Result: 4/4 tests passed
🎉 ALL TESTS PASSED! OI integration is working correctly.
```

## Example Scenarios

### Scenario 1: Strong Bullish Move
```
Stock: RELIANCE
Price Change: +2.5% (₹2,500 → ₹2,563)
OI Change: +15% (1M → 1.15M)

Result:
- Pattern: LONG_BUILDUP
- Signal: BULLISH
- Strength: VERY_STRONG
- Priority: HIGH
- Action: High confidence buy - institutions building longs
```

### Scenario 2: Weak Rally (Beware!)
```
Stock: TCS
Price Change: +1.8% (₹3,500 → ₹3,563)
OI Change: -12% (800K → 704K)

Result:
- Pattern: SHORT_COVERING
- Signal: WEAK_BULLISH
- Strength: STRONG
- Priority: MEDIUM
- Action: Caution - likely short covering, may reverse
```

### Scenario 3: Strong Bearish Move
```
Stock: INFY
Price Change: -2.2% (₹1,500 → ₹1,467)
OI Change: +11% (900K → 999K)

Result:
- Pattern: SHORT_BUILDUP
- Signal: BEARISH
- Strength: STRONG
- Priority: HIGH
- Action: Strong sell signal - institutions building shorts
```

## Performance Impact

**ZERO** - OI analysis adds negligible overhead:
- No additional API calls (data already in quotes)
- Minimal CPU for pattern classification
- Minimal disk usage (~1KB per stock in OI cache)
- Analysis runs only when OI data is available (F&O stocks)

## Limitations

1. **F&O Stocks Only** - OI is only available for stocks with futures/options
2. **First Alert of Day** - First alert won't have OI data (needs day-start reference)
3. **Intraday Only** - OI change resets each trading day at market open
4. **Kite Only** - Requires Kite data source (OI not in Yahoo/NSEpy)

## Troubleshooting

### OI Analysis Not Showing

1. Check if OI analysis is enabled:
   ```python
   # config.py
   ENABLE_OI_ANALYSIS = True
   ```

2. Verify stock has F&O (OI data):
   - Only F&O stocks have OI data
   - Check if current_oi > 0 in quote data

3. Check if it's the first alert of the day:
   - First alert establishes day-start OI baseline
   - Subsequent alerts will show OI change from day-start

### Excel Columns Misaligned

Delete `data/alerts/alert_tracking.xlsx` and let system recreate it with updated headers.

### OI Cache Issues

Clear the OI cache:
```bash
rm -rf data/oi_cache/
```

## Author

Sunil Kumar Durganaik

## Version History

- **v1.0** (Dec 2024) - Initial OI analysis implementation
  - 4 pattern classifications
  - 4 strength levels
  - 3 priority levels
  - Zero additional API calls
  - Excel tracking with 6 columns
  - Telegram alert integration
