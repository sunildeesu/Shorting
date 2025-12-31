#!/usr/bin/env python3
"""
Unified Pattern Detector

Multi-timeframe pattern detection supporting both daily and hourly candles.
Used by pre-market analyzer for early pattern detection.

Patterns Supported:
1. Double Bottom (Bullish)
2. Resistance Breakout (Bullish)
3. Cup & Handle (Bullish)
4. Inverse Head & Shoulders (Bullish)
5. Bull Flag (Bullish)
6. Ascending Triangle (Bullish)
7. Falling Wedge (Bullish)

Author: Sunil Kumar Durganaik
"""

from typing import List, Dict, Optional
import logging
from eod_pattern_detector import EODPatternDetector
import pattern_utils as pu

logger = logging.getLogger(__name__)


class PatternDetector:
    """
    Unified pattern detector for daily and hourly timeframes.

    For daily patterns: Delegates to existing EODPatternDetector (battle-tested)
    For hourly patterns: Uses adjusted parameters for intraday detection
    """

    def __init__(
        self,
        timeframe: str = 'daily',
        pattern_tolerance: float = None,
        volume_confirmation: bool = True,
        min_confidence: float = 7.5,
        require_confirmation: bool = False
    ):
        """
        Initialize pattern detector with timeframe-specific configuration.

        Args:
            timeframe: 'daily' or 'hourly'
            pattern_tolerance: Price matching tolerance (auto-set based on timeframe if None)
            volume_confirmation: Require volume confirmation
            min_confidence: Minimum confidence score (0-10)
            require_confirmation: Require next-day confirmation (daily only)
        """
        self.timeframe = timeframe
        self.volume_confirmation = volume_confirmation
        self.min_confidence = min_confidence
        self.require_confirmation = require_confirmation and timeframe == 'daily'

        # Auto-configure parameters based on timeframe
        if pattern_tolerance is None:
            self.pattern_tolerance = 2.5 if timeframe == 'hourly' else 2.0
        else:
            self.pattern_tolerance = pattern_tolerance

        # Volume thresholds (hourly is more lenient)
        self.volume_threshold = 1.5 if timeframe == 'hourly' else 1.75

        # Minimum pattern heights (hourly patterns smaller)
        self.min_pattern_height_pct = 2.0 if timeframe == 'hourly' else 3.0

        # Target projection multiplier (hourly more conservative)
        self.target_multiplier = 0.8 if timeframe == 'hourly' else 1.0

        # Stop loss offset (hourly tighter)
        self.stop_loss_offset = 1.5 if timeframe == 'hourly' else 2.0

        # Lookback adjustments for hourly (30% of daily)
        self.lookback_multiplier = 0.3 if timeframe == 'hourly' else 1.0

        # For daily patterns, delegate to existing EODPatternDetector
        if timeframe == 'daily':
            self.daily_detector = EODPatternDetector(
                pattern_tolerance=self.pattern_tolerance,
                volume_confirmation=self.volume_confirmation,
                min_confidence=self.min_confidence,
                require_confirmation=self.require_confirmation
            )
        else:
            self.daily_detector = None

        logger.info(f"PatternDetector initialized: timeframe={timeframe}, "
                   f"tolerance={self.pattern_tolerance}%, "
                   f"volume_threshold={self.volume_threshold}x, "
                   f"min_height={self.min_pattern_height_pct}%")

    def detect_patterns(
        self,
        symbol: str,
        historical_data: List[Dict],
        market_regime: str = "NEUTRAL"
    ) -> Dict:
        """
        Detect chart patterns on historical data.

        Args:
            symbol: Stock symbol
            historical_data: OHLCV candles (daily or hourly based on timeframe)
            market_regime: 'BULLISH', 'BEARISH', or 'NEUTRAL'

        Returns:
            Detection result dict with all patterns found
        """
        if not pu.validate_ohlcv_data(historical_data, min_candles=10):
            logger.warning(f"{symbol}: Insufficient or invalid data for {self.timeframe} pattern detection")
            return self._empty_result(symbol, market_regime)

        # Delegate to appropriate detector
        if self.timeframe == 'daily':
            return self._detect_daily_patterns(symbol, historical_data, market_regime)
        else:
            return self._detect_hourly_patterns(symbol, historical_data, market_regime)

    def _detect_daily_patterns(
        self,
        symbol: str,
        historical_data: List[Dict],
        market_regime: str
    ) -> Dict:
        """
        Detect patterns on daily candles using EODPatternDetector.

        Args:
            symbol: Stock symbol
            historical_data: Daily OHLCV candles
            market_regime: Market regime

        Returns:
            Detection result dict
        """
        # Delegate to existing battle-tested detector
        return self.daily_detector.detect_patterns(symbol, historical_data, market_regime)

    def _detect_hourly_patterns(
        self,
        symbol: str,
        historical_data: List[Dict],
        market_regime: str
    ) -> Dict:
        """
        Detect patterns on hourly candles with adjusted parameters.

        Uses same 7 patterns as daily but adapted for hourly:
        - Adjusted lookback windows (45h, 60h, 75h instead of days)
        - Looser price tolerance (2.5% vs 2.0%)
        - Lower volume threshold (1.5x vs 1.75x)
        - Smaller min height (2% vs 3%)
        - Conservative targets (0.8x height vs 1.0x)
        - Tighter stops (1.5% vs 2.0%)

        Args:
            symbol: Stock symbol
            historical_data: Hourly OHLCV candles (10 days = ~70 hours)
            market_regime: Market regime

        Returns:
            Detection result dict
        """
        if not pu.validate_ohlcv_data(historical_data, min_candles=10):
            logger.warning(f"{symbol}: Insufficient hourly data for pattern detection")
            return self._empty_result(symbol, market_regime)

        patterns_found = []
        pattern_details = {}

        # Calculate average volume
        avg_volume = pu.calculate_avg_volume(historical_data)

        # Detect Double Bottom (Bullish) - 45-hour lookback
        double_bottom = self._detect_double_bottom_hourly(historical_data, avg_volume, market_regime)
        if double_bottom and double_bottom.get('confidence_score', 0) >= self.min_confidence:
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('DOUBLE_BOTTOM')
                pattern_details['double_bottom'] = double_bottom
            else:
                logger.debug(f"{symbol}: Double Bottom filtered (bearish market)")

        # Detect Resistance Breakout (Bullish) - 60-hour lookback
        resistance_breakout = self._detect_resistance_breakout_hourly(historical_data, avg_volume, market_regime)
        if resistance_breakout and resistance_breakout.get('confidence_score', 0) >= self.min_confidence:
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('RESISTANCE_BREAKOUT')
                pattern_details['resistance_breakout'] = resistance_breakout
            else:
                logger.debug(f"{symbol}: Resistance Breakout filtered (bearish market)")

        # Additional patterns (Phase 2.2): Cup & Handle, Inverse H&S, Bull Flag, Ascending Triangle, Falling Wedge
        # TODO: Implement remaining 5 patterns

        # Build result
        result = {
            'symbol': symbol,
            'patterns_found': patterns_found,
            'pattern_details': pattern_details,
            'has_patterns': len(patterns_found) > 0,
            'market_regime': market_regime,
            'timeframe': 'hourly'
        }

        if patterns_found:
            logger.info(f"{symbol}: Found {len(patterns_found)} hourly pattern(s): {', '.join(patterns_found)}")

        return result

    # ============================================================================
    # HOURLY PATTERN DETECTION METHODS
    # ============================================================================

    def _detect_double_bottom_hourly(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Double Bottom pattern on hourly candles.
        Two lows at similar levels with a peak in between.
        Lookback: 45 hours (adaptive based on available data).

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 10:
            return None

        # Hourly lookback: 45 hours (vs 15 days for daily)
        lookback = min(45, len(data))
        recent_data = data[-lookback:]

        # Find local minima (lows)
        local_minima = []
        for i in range(1, len(recent_data) - 1):
            if recent_data[i]['low'] < recent_data[i-1]['low'] and recent_data[i]['low'] < recent_data[i+1]['low']:
                local_minima.append((i, recent_data[i]['low']))

        if len(local_minima) < 2:
            return None

        # Check last two minima
        first_low = local_minima[-2]
        second_low = local_minima[-1]

        # Lows must be at similar levels (within hourly tolerance: 2.5%)
        price_diff_pct = abs(first_low[1] - second_low[1]) / first_low[1] * 100

        if price_diff_pct <= self.pattern_tolerance:
            # Check for peak between the lows
            between_data = recent_data[first_low[0]:second_low[0]+1]
            if between_data:
                max_between = max(candle['high'] for candle in between_data)
                # Peak should be at least 2% higher (vs 3% for daily - hourly patterns smaller)
                if max_between > first_low[1] * 1.02:
                    current_price = data[-1]['close']
                    if current_price >= second_low[1]:
                        # Volume confirmation
                        current_volume = data[-1]['volume']
                        volume_confirmed, volume_ratio = pu.check_volume_confirmation(
                            current_volume, avg_volume, self.volume_threshold, self.volume_confirmation
                        )

                        if self.volume_confirmation and not volume_confirmed:
                            logger.debug(f"Hourly Double Bottom rejected: Low volume ({volume_ratio:.2f}x)")
                            return None

                        # Calculate entry, target, stop
                        buy_price = second_low[1] * 1.005
                        pattern_height = max_between - second_low[1]
                        # Hourly: 0.8x height (vs 1.0x for daily)
                        target_price = max_between + (pattern_height * self.target_multiplier)

                        # Tighter stop for hourly: 1.5% below (vs 2% for daily)
                        stop_loss = second_low[1] * (1 - self.stop_loss_offset / 100)

                        # Calculate pattern height percentage
                        pattern_height_pct = pu.calculate_pattern_height_pct(
                            max_between, second_low[1], second_low[1]
                        )

                        # Calculate confidence score (with hourly timeframe)
                        confidence = pu.calculate_confidence_score(
                            price_match_pct=price_diff_pct,
                            volume_ratio=volume_ratio,
                            pattern_height_pct=pattern_height_pct,
                            pattern_type='BULLISH',
                            market_regime=market_regime,
                            timeframe='hourly'
                        )

                        return {
                            'first_low': first_low[1],
                            'second_low': second_low[1],
                            'peak_between': max_between,
                            'pattern_strength': 'Strong' if price_diff_pct < 1.5 else 'Moderate',
                            'current_price': current_price,
                            'buy_price': buy_price,
                            'target_price': target_price,
                            'stop_loss': stop_loss,
                            'pattern_type': 'BULLISH',
                            'volume_ratio': volume_ratio,
                            'confidence_score': confidence,
                            'timeframe': 'hourly'
                        }

        return None

    def _detect_resistance_breakout_hourly(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Resistance Breakout pattern on hourly candles.
        Price breaks above a well-established resistance level.
        Lookback: 60 hours (vs 20 days for daily).

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 15:
            return None

        # Hourly lookback: 60 hours (vs 20 days for daily)
        lookback = min(60, len(data))
        recent_data = data[-lookback:]

        # Find resistance level (multiple touches of similar highs)
        local_maxima = []
        for i in range(1, len(recent_data) - 1):
            if recent_data[i]['high'] > recent_data[i-1]['high'] and recent_data[i]['high'] > recent_data[i+1]['high']:
                local_maxima.append((i, recent_data[i]['high']))

        if len(local_maxima) < 2:
            return None

        # Check last 3-5 maxima for resistance cluster
        resistance_candidates = local_maxima[-5:] if len(local_maxima) >= 5 else local_maxima[-3:]

        # Find resistance level (average of similar highs)
        resistance_prices = [maxima[1] for maxima in resistance_candidates]
        resistance_level = sum(resistance_prices) / len(resistance_prices)

        # Check if highs are clustered (within tolerance)
        max_deviation = max(abs(price - resistance_level) / resistance_level * 100 for price in resistance_prices)

        if max_deviation <= self.pattern_tolerance:
            # Check if current price broke above resistance
            current_price = data[-1]['close']
            if current_price > resistance_level * 1.005:  # 0.5% above resistance
                # Volume confirmation
                current_volume = data[-1]['volume']
                volume_confirmed, volume_ratio = pu.check_volume_confirmation(
                    current_volume, avg_volume, self.volume_threshold, self.volume_confirmation
                )

                if self.volume_confirmation and not volume_confirmed:
                    logger.debug(f"Hourly Resistance Breakout rejected: Low volume ({volume_ratio:.2f}x)")
                    return None

                # Find support level (lowest low in lookback period)
                support_level = min(candle['low'] for candle in recent_data)

                # Calculate entry, target, stop
                buy_price = resistance_level * 1.005
                pattern_height = resistance_level - support_level
                # Hourly: 0.8x height (vs 1.0x for daily)
                target_price = resistance_level + (pattern_height * self.target_multiplier)

                # Tighter stop for hourly: 1.5% below resistance (vs 2% for daily)
                stop_loss = resistance_level * (1 - self.stop_loss_offset / 100)

                # Calculate pattern height percentage
                pattern_height_pct = pu.calculate_pattern_height_pct(
                    resistance_level, support_level, resistance_level
                )

                # Calculate confidence score (with hourly timeframe)
                confidence = pu.calculate_confidence_score(
                    price_match_pct=max_deviation,
                    volume_ratio=volume_ratio,
                    pattern_height_pct=pattern_height_pct,
                    pattern_type='BULLISH',
                    market_regime=market_regime,
                    timeframe='hourly'
                )

                return {
                    'resistance_level': resistance_level,
                    'support_level': support_level,
                    'breakout_price': current_price,
                    'pattern_strength': 'Strong' if max_deviation < 1.5 else 'Moderate',
                    'current_price': current_price,
                    'buy_price': buy_price,
                    'target_price': target_price,
                    'stop_loss': stop_loss,
                    'pattern_type': 'BULLISH',
                    'volume_ratio': volume_ratio,
                    'confidence_score': confidence,
                    'timeframe': 'hourly'
                }

        return None

    # ============================================================================
    # BATCH DETECTION
    # ============================================================================

    def batch_detect(
        self,
        symbols_data: Dict[str, List[Dict]],
        market_regime: str = "NEUTRAL"
    ) -> Dict[str, Dict]:
        """
        Batch detect patterns for multiple stocks.

        Args:
            symbols_data: Dict mapping symbols to historical data
            market_regime: Market regime

        Returns:
            Dict mapping symbols to detection results
        """
        results = {}

        for symbol, historical_data in symbols_data.items():
            try:
                result = self.detect_patterns(symbol, historical_data, market_regime)
                results[symbol] = result
            except Exception as e:
                logger.error(f"{symbol}: Error detecting patterns: {e}")
                results[symbol] = self._empty_result(symbol, market_regime)

        return results

    def _empty_result(self, symbol: str, market_regime: str = "NEUTRAL") -> Dict:
        """
        Return empty detection result.

        Args:
            symbol: Stock symbol
            market_regime: Market regime

        Returns:
            Empty result dict (matches EODPatternDetector structure)
        """
        return {
            'symbol': symbol,
            'patterns_found': [],
            'pattern_details': {},
            'has_patterns': False,
            'market_regime': market_regime,
            'timeframe': self.timeframe  # Extra field for timeframe tracking
        }

    def get_supported_patterns(self) -> List[str]:
        """
        Get list of supported pattern types.

        Returns:
            List of pattern names
        """
        return [
            'DOUBLE_BOTTOM',
            'RESISTANCE_BREAKOUT',
            'CUP_HANDLE',
            'INVERSE_HEAD_SHOULDERS',
            'BULL_FLAG',
            'ASCENDING_TRIANGLE',
            'FALLING_WEDGE'
        ]

    def get_config(self) -> Dict:
        """
        Get current detector configuration.

        Returns:
            Configuration dict
        """
        return {
            'timeframe': self.timeframe,
            'pattern_tolerance': self.pattern_tolerance,
            'volume_confirmation': self.volume_confirmation,
            'volume_threshold': self.volume_threshold,
            'min_confidence': self.min_confidence,
            'min_pattern_height_pct': self.min_pattern_height_pct,
            'target_multiplier': self.target_multiplier,
            'stop_loss_offset': self.stop_loss_offset,
            'lookback_multiplier': self.lookback_multiplier,
            'require_confirmation': self.require_confirmation
        }


def main():
    """Test/demonstration of PatternDetector"""
    print("=" * 60)
    print("PATTERN DETECTOR - TEST")
    print("=" * 60)

    # Test data (mock)
    from datetime import datetime, timedelta

    test_symbol = "RELIANCE"
    test_data_daily = []
    base_price = 2300

    # Generate 30 days of mock data
    for i in range(30):
        date = datetime.now() - timedelta(days=30-i)
        price_var = (i % 5) * 10  # Some variation
        test_data_daily.append({
            'date': date,
            'open': base_price + price_var,
            'high': base_price + price_var + 20,
            'low': base_price + price_var - 20,
            'close': base_price + price_var + 10,
            'volume': 1000000 + (i * 10000)
        })

    # Test daily detector
    print("\n1. Testing Daily Pattern Detector...")
    daily_detector = PatternDetector(timeframe='daily', min_confidence=7.0)
    daily_config = daily_detector.get_config()
    print(f"   Timeframe: {daily_config['timeframe']}")
    print(f"   Tolerance: {daily_config['pattern_tolerance']}%")
    print(f"   Volume Threshold: {daily_config['volume_threshold']}x")
    print(f"   Min Height: {daily_config['min_pattern_height_pct']}%")

    # Run detection
    result_daily = daily_detector.detect_patterns(test_symbol, test_data_daily, "BULLISH")
    print(f"   Patterns Found: {len(result_daily['patterns_found'])}")

    # Test hourly detector (not yet implemented)
    print("\n2. Testing Hourly Pattern Detector...")
    hourly_detector = PatternDetector(timeframe='hourly', min_confidence=7.0)
    hourly_config = hourly_detector.get_config()
    print(f"   Timeframe: {hourly_config['timeframe']}")
    print(f"   Tolerance: {hourly_config['pattern_tolerance']}%")
    print(f"   Volume Threshold: {hourly_config['volume_threshold']}x")
    print(f"   Min Height: {hourly_config['min_pattern_height_pct']}%")
    print(f"   Target Multiplier: {hourly_config['target_multiplier']}x")
    print(f"   Stop Loss Offset: {hourly_config['stop_loss_offset']}%")

    # Run detection (will return empty in Phase 1)
    result_hourly = hourly_detector.detect_patterns(test_symbol, test_data_daily, "BULLISH")
    print(f"   Patterns Found: {len(result_hourly['patterns_found'])} (Phase 2 TODO)")

    # Test supported patterns
    print("\n3. Supported Patterns:")
    for pattern in daily_detector.get_supported_patterns():
        formatted = pu.format_pattern_name(pattern)
        print(f"   - {formatted}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
