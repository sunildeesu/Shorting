"""
Price Action Pattern Detector

Detects candlestick patterns on 5-minute timeframes with confidence scoring.
Supports 15-20 patterns across reversal, continuation, indecision, and multi-candle categories.

Features:
- Multi-factor confidence scoring (0-10 scale)
- Market regime integration
- Volume analysis
- Entry/target/stop loss calculations
"""

import logging
from typing import Dict, List, Optional

from pattern_detectors import (
    # Reversal patterns
    BullishEngulfingDetector,
    BearishEngulfingDetector,
    HammerDetector,
    ShootingStarDetector,
    InvertedHammerDetector,
    HangingManDetector,
    MorningStarDetector,
    EveningStarDetector,
    PiercingPatternDetector,
    DarkCloudCoverDetector,
    # Indecision patterns
    DojiDetector,
    SpinningTopDetector,
    LongLeggedDojiDetector,
    # Continuation patterns
    BullishMarubozuDetector,
    BearishMarubozuDetector,
    RisingThreeMethodsDetector,
    FallingThreeMethodsDetector,
    # Multi-candle patterns
    ThreeWhiteSoldiersDetector,
    ThreeBlackCrowsDetector,
)

logger = logging.getLogger(__name__)


class PriceActionDetector:
    """
    Detects candlestick patterns on 5-minute timeframe with confidence scoring

    Features:
    - 19 pattern detection methods across 4 categories
    - 0-10 confidence scoring with multiple factors
    - Market regime filtering
    - Volume analysis (bonus, not mandatory)
    - Modular pattern detector architecture
    """

    def __init__(
        self,
        min_confidence: float = 7.0,
        lookback_candles: int = 50,
        atr_period: int = 14,
        atr_target_multiplier: float = 2.0,
        atr_stop_multiplier: float = 1.0,
        disabled_patterns: List[str] = None
    ):
        """
        Initialize detector

        Args:
            min_confidence: Minimum confidence score (0-10) to return pattern
            lookback_candles: Number of historical candles to analyze
            atr_period: Period for ATR calculation (default: 14)
            atr_target_multiplier: ATR multiplier for targets (default: 2.0)
            atr_stop_multiplier: ATR multiplier for stops (default: 1.0)
            disabled_patterns: List of pattern names to disable (e.g., ['Hammer', 'Hanging Man'])
        """
        self.min_confidence = min_confidence
        self.lookback_candles = lookback_candles
        self.atr_period = atr_period
        self.atr_target_multiplier = atr_target_multiplier
        self.atr_stop_multiplier = atr_stop_multiplier

        # Disable poorly performing patterns by default
        if disabled_patterns is None:
            disabled_patterns = ['Dark Cloud Cover', 'Hanging Man', 'Hammer']
        self.disabled_patterns = disabled_patterns

        # Initialize all pattern detectors
        self._init_pattern_detectors()

    def _init_pattern_detectors(self):
        """Initialize all pattern detector instances"""
        # Common parameters for all detectors
        detector_params = {
            'min_confidence': self.min_confidence,
            'atr_period': self.atr_period,
            'atr_target_multiplier': self.atr_target_multiplier,
            'atr_stop_multiplier': self.atr_stop_multiplier,
        }

        # Create detector instances
        # Reversal patterns
        self.bullish_engulfing = BullishEngulfingDetector(**detector_params)
        self.bearish_engulfing = BearishEngulfingDetector(**detector_params)
        self.hammer = HammerDetector(**detector_params)
        self.shooting_star = ShootingStarDetector(**detector_params)
        self.inverted_hammer = InvertedHammerDetector(**detector_params)
        self.hanging_man = HangingManDetector(**detector_params)
        self.morning_star = MorningStarDetector(**detector_params)
        self.evening_star = EveningStarDetector(**detector_params)
        self.piercing_pattern = PiercingPatternDetector(**detector_params)
        self.dark_cloud_cover = DarkCloudCoverDetector(**detector_params)

        # Indecision patterns
        self.doji = DojiDetector(**detector_params)
        self.spinning_top = SpinningTopDetector(**detector_params)
        self.long_legged_doji = LongLeggedDojiDetector(**detector_params)

        # Continuation patterns
        self.bullish_marubozu = BullishMarubozuDetector(**detector_params)
        self.bearish_marubozu = BearishMarubozuDetector(**detector_params)
        self.rising_three_methods = RisingThreeMethodsDetector(**detector_params)
        self.falling_three_methods = FallingThreeMethodsDetector(**detector_params)

        # Multi-candle patterns
        self.three_white_soldiers = ThreeWhiteSoldiersDetector(**detector_params)
        self.three_black_crows = ThreeBlackCrowsDetector(**detector_params)

        # List of all detector instances
        self.pattern_detectors = [
            # Reversal patterns
            self.bullish_engulfing,
            self.bearish_engulfing,
            self.hammer,
            self.shooting_star,
            self.inverted_hammer,
            self.hanging_man,
            self.morning_star,
            self.evening_star,
            self.piercing_pattern,
            self.dark_cloud_cover,
            # Indecision patterns
            self.doji,
            self.spinning_top,
            self.long_legged_doji,
            # Continuation patterns
            self.bullish_marubozu,
            self.bearish_marubozu,
            self.rising_three_methods,
            self.falling_three_methods,
            # Multi-candle patterns
            self.three_white_soldiers,
            self.three_black_crows,
        ]

    def detect_patterns(
        self,
        symbol: str,
        candles: List[Dict],
        market_regime: str,
        current_price: float,
        avg_volume: float
    ) -> Dict:
        """
        Main detection method - scans for all candlestick patterns

        Args:
            symbol: Stock symbol
            candles: List of OHLCV candle dicts (sorted oldest to newest)
            market_regime: 'BULLISH', 'BEARISH', or 'NEUTRAL'
            current_price: Current stock price
            avg_volume: Average volume for volume spike detection

        Returns:
            Dict with pattern detection results:
            {
                'symbol': str,
                'has_patterns': bool,
                'patterns_found': List[str],
                'market_regime': str,
                'pattern_details': {
                    'pattern_key': {
                        'pattern_name': str,
                        'type': 'bullish|bearish|neutral',
                        'confidence_score': float (0-10),
                        'entry_price': float,
                        'target': float,
                        'stop_loss': float,
                        'volume_ratio': float,
                        'pattern_description': str,
                        'candle_data': Dict,
                        'confidence_breakdown': Dict
                    }
                }
            }
        """
        result = {
            'symbol': symbol,
            'has_patterns': False,
            'patterns_found': [],
            'market_regime': market_regime,
            'pattern_details': {}
        }

        # Need minimum candles for analysis
        if len(candles) < 12:
            logger.debug(f"{symbol}: Insufficient candle data ({len(candles)} candles)")
            return result

        # Run all pattern detections
        for detector in self.pattern_detectors:
            try:
                pattern_data = detector.detect(candles, market_regime, avg_volume)

                if pattern_data and pattern_data['confidence_score'] >= self.min_confidence:
                    pattern_name = pattern_data['pattern_name']

                    # Skip disabled patterns
                    if pattern_name in self.disabled_patterns:
                        logger.debug(f"{symbol}: Skipping disabled pattern {pattern_name}")
                        continue

                    pattern_key = pattern_name.lower().replace(' ', '_')

                    result['patterns_found'].append(pattern_name)
                    result['pattern_details'][pattern_key] = pattern_data
                    result['has_patterns'] = True

                    logger.info(f"{symbol}: Detected {pattern_name} (confidence: {pattern_data['confidence_score']:.1f})")

            except Exception as e:
                detector_name = detector.__class__.__name__
                logger.error(f"{symbol}: Error in {detector_name}: {e}", exc_info=True)

        return result
