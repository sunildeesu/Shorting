# Pattern Detectors Module

Modular candlestick pattern detection system extracted from the monolithic `price_action_detector.py`.

## Structure

```
pattern_detectors/
├── base_pattern.py           # Base class with shared functionality (276 lines)
├── reversal_patterns.py      # 10 reversal patterns (1,362 lines)
├── continuation_patterns.py  # 4 continuation patterns (413 lines)
├── indecision_patterns.py    # 3 indecision patterns (445 lines)
├── multi_candle_patterns.py  # 2 multi-candle patterns (218 lines)
└── __init__.py               # Module exports (57 lines)
```

## Pattern Categories

### Reversal Patterns (10)
- **BullishEngulfingDetector** - Bullish reversal after downtrend
- **BearishEngulfingDetector** - Bearish reversal after uptrend
- **HammerDetector** - Bullish reversal with long lower wick
- **ShootingStarDetector** - Bearish reversal with long upper wick
- **InvertedHammerDetector** - Bullish reversal with long upper wick
- **HangingManDetector** - Bearish reversal with long lower wick
- **MorningStarDetector** - 3-candle bullish reversal
- **EveningStarDetector** - 3-candle bearish reversal
- **PiercingPatternDetector** - Bullish reversal pattern
- **DarkCloudCoverDetector** - Bearish reversal pattern

### Continuation Patterns (4)
- **BullishMarubozuDetector** - Strong bullish continuation
- **BearishMarubozuDetector** - Strong bearish continuation
- **RisingThreeMethodsDetector** - Bullish consolidation continuation
- **FallingThreeMethodsDetector** - Bearish consolidation continuation

### Indecision Patterns (3)
- **DojiDetector** - Market indecision/reversal
- **SpinningTopDetector** - Uncertainty/potential reversal
- **LongLeggedDojiDetector** - High volatility indecision

### Multi-Candle Patterns (2)
- **ThreeWhiteSoldiersDetector** - Strong bullish reversal
- **ThreeBlackCrowsDetector** - Strong bearish reversal

## Base Pattern Detector

All pattern detectors inherit from `BasePatternDetector` which provides:

### Shared Methods
- `calculate_atr()` - Average True Range calculation
- `calculate_body_score()` - Body size ratio confidence scoring
- `calculate_volume_score()` - Volume confirmation scoring
- `calculate_trend_score()` - Trend context scoring
- `calculate_position_score()` - Pattern position scoring
- `calculate_regime_score()` - Market regime bonus scoring
- `create_pattern_result()` - Standardized result creation

### Configuration
All detectors accept:
- `min_confidence` - Minimum confidence score (0-10)
- `atr_period` - ATR calculation period
- `atr_target_multiplier` - Target calculation multiplier
- `atr_stop_multiplier` - Stop loss calculation multiplier

## Usage

### Direct Usage (New Way)
```python
from pattern_detectors import BullishEngulfingDetector

detector = BullishEngulfingDetector(
    min_confidence=7.0,
    atr_period=14,
    atr_target_multiplier=2.0,
    atr_stop_multiplier=1.0
)

result = detector.detect(candles, market_regime='BULLISH', avg_volume=1000)
```

### Through PriceActionDetector (Backward Compatible)
```python
from price_action_detector import PriceActionDetector

detector = PriceActionDetector(min_confidence=7.0)
results = detector.detect_patterns(
    symbol='AAPL',
    candles=candles,
    market_regime='BULLISH',
    current_price=150.0,
    avg_volume=1000000
)
```

## Benefits of Refactoring

1. **Maintainability** - Each pattern is isolated in its own class
2. **Testability** - Individual patterns can be tested independently
3. **Extensibility** - New patterns can be added easily
4. **Readability** - Main file reduced from 2,521 to 236 lines (90% reduction)
5. **Reusability** - Patterns can be used individually or together
6. **Organization** - Patterns grouped by category/behavior

## Backward Compatibility

The refactoring maintains 100% backward compatibility:
- Same public API (`PriceActionDetector` class)
- Same constructor parameters
- Same `detect_patterns()` method signature
- Same result structure
- Same configuration options (disabled_patterns, etc.)

Existing code using `PriceActionDetector` will work without any changes.
