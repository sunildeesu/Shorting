#!/usr/bin/env python3
"""
Enhanced EOD Pattern Detector - Detects chart patterns with confidence scoring
Implements: Volume confirmation, Market regime filtering, Confidence scoring
"""

from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class EODPatternDetector:
    """Detects chart patterns on daily timeframe with confidence scoring"""

    def __init__(
        self,
        pattern_tolerance: float = 2.0,
        volume_confirmation: bool = True,
        min_confidence: float = 7.0
    ):
        """
        Initialize pattern detector

        Args:
            pattern_tolerance: Price tolerance percentage for pattern matching (default: 2%)
            volume_confirmation: Require 1.5× average volume on pattern completion (default: True)
            min_confidence: Minimum confidence score to report pattern (default: 7.0/10)
        """
        self.pattern_tolerance = pattern_tolerance
        self.volume_confirmation = volume_confirmation
        self.min_confidence = min_confidence

    def detect_patterns(
        self,
        symbol: str,
        historical_data: List[Dict],
        market_regime: str = "NEUTRAL"
    ) -> Dict:
        """
        Detect all chart patterns for a single stock

        Args:
            symbol: Stock symbol
            historical_data: 30-day daily OHLCV data from Kite API
                           [{date: datetime, open: float, high: float, low: float, close: float, volume: int}, ...]
            market_regime: Current market regime ('BULLISH', 'BEARISH', 'NEUTRAL')

        Returns:
            Dict with pattern detection results:
            {
                'symbol': str,
                'patterns_found': List[str],
                'pattern_details': Dict,
                'has_patterns': bool,
                'market_regime': str
            }
        """
        if not historical_data or len(historical_data) < 10:
            logger.debug(f"{symbol}: Insufficient data for pattern detection")
            return self._empty_result(symbol, market_regime)

        patterns_found = []
        pattern_details = {}

        # Calculate average volume for confirmation
        avg_volume = self._calculate_avg_volume(historical_data)

        # Detect Double Bottom (Bullish)
        double_bottom = self._detect_double_bottom(historical_data, avg_volume, market_regime)
        if double_bottom and double_bottom.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('DOUBLE_BOTTOM')
                pattern_details['double_bottom'] = double_bottom
            else:
                logger.debug(f"{symbol}: Double Bottom filtered (bearish market regime)")

        # Detect Double Top (Bearish)
        double_top = self._detect_double_top(historical_data, avg_volume, market_regime)
        if double_top and double_top.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime
            if market_regime in ['BEARISH', 'NEUTRAL']:
                patterns_found.append('DOUBLE_TOP')
                pattern_details['double_top'] = double_top
            else:
                logger.debug(f"{symbol}: Double Top filtered (bullish market regime)")

        # Detect Support Breakout (Bearish)
        support_breakout = self._detect_support_breakout(historical_data, avg_volume, market_regime)
        if support_breakout and support_breakout.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime
            if market_regime in ['BEARISH', 'NEUTRAL']:
                patterns_found.append('SUPPORT_BREAKOUT')
                pattern_details['support_breakout'] = support_breakout
            else:
                logger.debug(f"{symbol}: Support Breakout filtered (bullish market regime)")

        # Detect Resistance Breakout (Bullish)
        resistance_breakout = self._detect_resistance_breakout(historical_data, avg_volume, market_regime)
        if resistance_breakout and resistance_breakout.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('RESISTANCE_BREAKOUT')
                pattern_details['resistance_breakout'] = resistance_breakout
            else:
                logger.debug(f"{symbol}: Resistance Breakout filtered (bearish market regime)")

        if patterns_found:
            # Log with confidence scores
            pattern_info = []
            for pattern in patterns_found:
                pattern_key = pattern.lower()
                confidence = pattern_details.get(pattern_key, {}).get('confidence_score', 0)
                pattern_info.append(f"{pattern}({confidence:.1f}/10)")
            logger.info(f"{symbol}: Patterns detected - {', '.join(pattern_info)}")

        return {
            'symbol': symbol,
            'patterns_found': patterns_found,
            'pattern_details': pattern_details,
            'has_patterns': len(patterns_found) > 0,
            'market_regime': market_regime
        }

    def _calculate_avg_volume(self, data: List[Dict]) -> float:
        """Calculate 30-day average volume"""
        if not data:
            return 0

        volumes = [candle.get('volume', 0) for candle in data]
        return sum(volumes) / len(volumes) if volumes else 0

    def _check_volume_confirmation(self, current_volume: int, avg_volume: float) -> Tuple[bool, float]:
        """
        Check if current volume meets 1.5× average threshold

        Returns:
            Tuple of (confirmation_passed, volume_ratio)
        """
        if not self.volume_confirmation or avg_volume == 0:
            return True, 1.0

        volume_ratio = current_volume / avg_volume
        return volume_ratio >= 1.5, volume_ratio

    def _calculate_confidence_score(
        self,
        price_match_pct: float,
        volume_ratio: float,
        pattern_height_pct: float,
        pattern_type: str,
        market_regime: str
    ) -> float:
        """
        Calculate pattern confidence score (0-10)

        Scoring Factors:
        - Price levels match exactly (20%): +2 if <1% diff
        - Volume on completion day (20%): +2 if >1.5× avg
        - Market regime alignment (20%): +2 if aligned
        - Pattern height/significance (30%): +3 if >5%
        - Base score (10%): +1 for all valid patterns

        Args:
            price_match_pct: Price difference percentage for pattern levels
            volume_ratio: Current volume / average volume
            pattern_height_pct: Pattern height as percentage of price
            pattern_type: 'BULLISH' or 'BEARISH'
            market_regime: 'BULLISH', 'BEARISH', or 'NEUTRAL'

        Returns:
            Confidence score from 0-10
        """
        score = 0.0

        # 1. Price Match Quality (20% = 2 points)
        if price_match_pct < 0.5:
            score += 2.0  # Excellent match
        elif price_match_pct < 1.0:
            score += 1.5  # Good match
        elif price_match_pct < 1.5:
            score += 1.0  # Acceptable match
        else:
            score += 0.5  # Weak match

        # 2. Volume Confirmation (20% = 2 points)
        if volume_ratio >= 2.0:
            score += 2.0  # Strong volume
        elif volume_ratio >= 1.5:
            score += 1.5  # Good volume
        elif volume_ratio >= 1.2:
            score += 1.0  # Moderate volume
        else:
            score += 0.0  # Weak volume

        # 3. Market Regime Alignment (20% = 2 points)
        if pattern_type == 'BULLISH' and market_regime == 'BULLISH':
            score += 2.0  # Perfect alignment
        elif pattern_type == 'BEARISH' and market_regime == 'BEARISH':
            score += 2.0  # Perfect alignment
        elif market_regime == 'NEUTRAL':
            score += 1.0  # Neutral market - partial credit
        else:
            score += 0.0  # Misalignment (pattern against trend)

        # 4. Pattern Height/Significance (30% = 3 points)
        if pattern_height_pct >= 7.0:
            score += 3.0  # Large significant pattern
        elif pattern_height_pct >= 5.0:
            score += 2.5  # Good pattern
        elif pattern_height_pct >= 3.0:
            score += 2.0  # Moderate pattern
        elif pattern_height_pct >= 2.0:
            score += 1.0  # Small pattern
        else:
            score += 0.0  # Too small, likely noise

        # 5. Base Score (10% = 1 point)
        score += 1.0  # All valid patterns get base credit

        return round(score, 1)

    def _detect_double_bottom(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Double Bottom pattern (bullish reversal)
        Two lows at similar levels with a peak in between
        Focus on RECENT patterns (last 15 days)

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 10:
            return None

        # Focus on recent data (last 15 days or available data)
        lookback = min(15, len(data))
        recent_data = data[-lookback:]

        # Find local minima (lows) in recent data
        local_minima = []
        for i in range(1, len(recent_data) - 1):
            if recent_data[i]['low'] < recent_data[i-1]['low'] and recent_data[i]['low'] < recent_data[i+1]['low']:
                local_minima.append((i, recent_data[i]['low']))

        # Need at least 2 local minima
        if len(local_minima) < 2:
            return None

        # Check ONLY the last two minima for double bottom pattern
        first_low = local_minima[-2]
        second_low = local_minima[-1]

        # Lows must be at similar levels (within tolerance)
        price_diff_pct = abs(first_low[1] - second_low[1]) / first_low[1] * 100

        if price_diff_pct <= self.pattern_tolerance:
            # Check if there's a peak between the two lows
            between_data = recent_data[first_low[0]:second_low[0]+1]
            if between_data:
                max_between = max(candle['high'] for candle in between_data)
                # Peak should be at least 3% higher than lows (more strict)
                if max_between > first_low[1] * 1.03:
                    # Current price should be above the second low (potential breakout)
                    current_price = data[-1]['close']
                    if current_price >= second_low[1]:
                        # Volume confirmation
                        current_volume = data[-1]['volume']
                        volume_confirmed, volume_ratio = self._check_volume_confirmation(
                            current_volume, avg_volume
                        )

                        # Skip if volume confirmation fails
                        if self.volume_confirmation and not volume_confirmed:
                            logger.debug(f"Double Bottom rejected: Low volume ({volume_ratio:.2f}x)")
                            return None

                        # Calculate buy price and target
                        buy_price = second_low[1] * 1.005
                        pattern_height = max_between - second_low[1]
                        target_price = max_between + pattern_height

                        # Calculate stop loss (2% below second low)
                        stop_loss = second_low[1] * 0.98

                        # Calculate pattern height percentage
                        pattern_height_pct = (pattern_height / second_low[1]) * 100

                        # Calculate confidence score
                        confidence = self._calculate_confidence_score(
                            price_match_pct=price_diff_pct,
                            volume_ratio=volume_ratio,
                            pattern_height_pct=pattern_height_pct,
                            pattern_type='BULLISH',
                            market_regime=market_regime
                        )

                        return {
                            'first_low': first_low[1],
                            'second_low': second_low[1],
                            'peak_between': max_between,
                            'pattern_strength': 'Strong' if price_diff_pct < 1.0 else 'Moderate',
                            'current_price': current_price,
                            'buy_price': buy_price,
                            'target_price': target_price,
                            'stop_loss': stop_loss,
                            'pattern_type': 'BULLISH',
                            'volume_ratio': volume_ratio,
                            'confidence_score': confidence
                        }

        return None

    def _detect_double_top(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Double Top pattern (bearish reversal)
        Two highs at similar levels with a trough in between
        Focus on RECENT patterns (last 15 days)

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 10:
            return None

        # Focus on recent data (last 15 days or available data)
        lookback = min(15, len(data))
        recent_data = data[-lookback:]

        # Find local maxima (highs) in recent data
        local_maxima = []
        for i in range(1, len(recent_data) - 1):
            if recent_data[i]['high'] > recent_data[i-1]['high'] and recent_data[i]['high'] > recent_data[i+1]['high']:
                local_maxima.append((i, recent_data[i]['high']))

        # Need at least 2 local maxima
        if len(local_maxima) < 2:
            return None

        # Check ONLY the last two maxima for double top pattern
        first_high = local_maxima[-2]
        second_high = local_maxima[-1]

        # Highs must be at similar levels (within tolerance)
        price_diff_pct = abs(first_high[1] - second_high[1]) / first_high[1] * 100

        if price_diff_pct <= self.pattern_tolerance:
            # Check if there's a trough between the two highs
            between_data = recent_data[first_high[0]:second_high[0]+1]
            if between_data:
                min_between = min(candle['low'] for candle in between_data)
                # Trough should be at least 3% lower than highs (more strict)
                if min_between < first_high[1] * 0.97:
                    # Current price should be below the second high (potential breakdown)
                    current_price = data[-1]['close']
                    if current_price <= second_high[1]:
                        # Volume confirmation
                        current_volume = data[-1]['volume']
                        volume_confirmed, volume_ratio = self._check_volume_confirmation(
                            current_volume, avg_volume
                        )

                        # Skip if volume confirmation fails
                        if self.volume_confirmation and not volume_confirmed:
                            logger.debug(f"Double Top rejected: Low volume ({volume_ratio:.2f}x)")
                            return None

                        # Calculate short entry and target
                        buy_price = second_high[1] * 0.995
                        pattern_height = second_high[1] - min_between
                        target_price = min_between - pattern_height

                        # Calculate stop loss (2% above second high)
                        stop_loss = second_high[1] * 1.02

                        # Calculate pattern height percentage
                        pattern_height_pct = (pattern_height / second_high[1]) * 100

                        # Calculate confidence score
                        confidence = self._calculate_confidence_score(
                            price_match_pct=price_diff_pct,
                            volume_ratio=volume_ratio,
                            pattern_height_pct=pattern_height_pct,
                            pattern_type='BEARISH',
                            market_regime=market_regime
                        )

                        return {
                            'first_high': first_high[1],
                            'second_high': second_high[1],
                            'trough_between': min_between,
                            'pattern_strength': 'Strong' if price_diff_pct < 1.0 else 'Moderate',
                            'current_price': current_price,
                            'buy_price': buy_price,
                            'target_price': target_price,
                            'stop_loss': stop_loss,
                            'pattern_type': 'BEARISH',
                            'volume_ratio': volume_ratio,
                            'confidence_score': confidence
                        }

        return None

    def _detect_support_breakout(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Support Breakout (bearish)
        Price breaking below recent support level with volume confirmation

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 15:
            return None

        # Calculate recent support (lowest low in last 10-20 days, excluding last 2 days)
        lookback_period = min(20, len(data) - 3)
        recent_data = data[-lookback_period-3:-2]  # Exclude last 2 days to find established support

        if not recent_data:
            return None

        support_level = min(candle['low'] for candle in recent_data)
        current_price = data[-1]['close']
        current_low = data[-1]['low']

        # Breakout must be at least 1% below support (not just noise)
        if current_low < support_level * 0.99:
            breakout_strength = (support_level - current_low) / support_level * 100

            # Additional validation: current price should also be below support
            if current_price < support_level:
                # Volume confirmation
                current_volume = data[-1]['volume']
                volume_confirmed, volume_ratio = self._check_volume_confirmation(
                    current_volume, avg_volume
                )

                # Skip if volume confirmation fails
                if self.volume_confirmation and not volume_confirmed:
                    logger.debug(f"Support Breakout rejected: Low volume ({volume_ratio:.2f}x)")
                    return None

                # Calculate short entry and target
                buy_price = current_price
                breakout_distance = support_level - current_low
                target_price = support_level - (breakout_distance * 2)

                # Calculate stop loss (2% above support level)
                stop_loss = support_level * 1.02

                # Calculate pattern height percentage
                pattern_height_pct = breakout_strength

                # Calculate confidence score
                confidence = self._calculate_confidence_score(
                    price_match_pct=0.0,  # Exact breakout, perfect match
                    volume_ratio=volume_ratio,
                    pattern_height_pct=pattern_height_pct,
                    pattern_type='BEARISH',
                    market_regime=market_regime
                )

                return {
                    'support_level': support_level,
                    'current_price': current_price,
                    'current_low': current_low,
                    'breakout_strength_pct': breakout_strength,
                    'signal': 'Bearish',
                    'buy_price': buy_price,
                    'target_price': target_price,
                    'stop_loss': stop_loss,
                    'pattern_type': 'BEARISH',
                    'volume_ratio': volume_ratio,
                    'confidence_score': confidence
                }

        return None

    def _detect_resistance_breakout(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Resistance Breakout (bullish)
        Price breaking above recent resistance level with volume confirmation

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 15:
            return None

        # Calculate recent resistance (highest high in last 10-20 days, excluding last 2 days)
        lookback_period = min(20, len(data) - 3)
        recent_data = data[-lookback_period-3:-2]  # Exclude last 2 days to find established resistance

        if not recent_data:
            return None

        resistance_level = max(candle['high'] for candle in recent_data)
        current_price = data[-1]['close']
        current_high = data[-1]['high']

        # Breakout must be at least 1% above resistance (not just noise)
        if current_high > resistance_level * 1.01:
            breakout_strength = (current_high - resistance_level) / resistance_level * 100

            # Additional validation: current price should also be above resistance
            if current_price > resistance_level:
                # Volume confirmation
                current_volume = data[-1]['volume']
                volume_confirmed, volume_ratio = self._check_volume_confirmation(
                    current_volume, avg_volume
                )

                # Skip if volume confirmation fails
                if self.volume_confirmation and not volume_confirmed:
                    logger.debug(f"Resistance Breakout rejected: Low volume ({volume_ratio:.2f}x)")
                    return None

                # Calculate buy price and target
                buy_price = current_price
                breakout_distance = current_high - resistance_level
                target_price = resistance_level + (breakout_distance * 2)

                # Calculate stop loss (2% below resistance level)
                stop_loss = resistance_level * 0.98

                # Calculate pattern height percentage
                pattern_height_pct = breakout_strength

                # Calculate confidence score
                confidence = self._calculate_confidence_score(
                    price_match_pct=0.0,  # Exact breakout, perfect match
                    volume_ratio=volume_ratio,
                    pattern_height_pct=pattern_height_pct,
                    pattern_type='BULLISH',
                    market_regime=market_regime
                )

                return {
                    'resistance_level': resistance_level,
                    'current_price': current_price,
                    'current_high': current_high,
                    'breakout_strength_pct': breakout_strength,
                    'signal': 'Bullish',
                    'buy_price': buy_price,
                    'target_price': target_price,
                    'stop_loss': stop_loss,
                    'pattern_type': 'BULLISH',
                    'volume_ratio': volume_ratio,
                    'confidence_score': confidence
                }

        return None

    def _empty_result(self, symbol: str, market_regime: str = "NEUTRAL") -> Dict:
        """Return empty result for stocks with no patterns"""
        return {
            'symbol': symbol,
            'patterns_found': [],
            'pattern_details': {},
            'has_patterns': False,
            'market_regime': market_regime
        }

    def batch_detect(
        self,
        historical_data_map: Dict[str, List[Dict]],
        market_regime: str = "NEUTRAL"
    ) -> List[Dict]:
        """
        Detect patterns for multiple stocks

        Args:
            historical_data_map: Dict mapping symbol to historical data
            market_regime: Current market regime ('BULLISH', 'BEARISH', 'NEUTRAL')

        Returns:
            List of pattern detection results for all stocks
        """
        results = []

        for symbol, historical_data in historical_data_map.items():
            result = self.detect_patterns(symbol, historical_data, market_regime)
            results.append(result)

        # Log summary
        stocks_with_patterns = sum(1 for r in results if r['has_patterns'])
        total_patterns = sum(len(r['patterns_found']) for r in results)

        logger.info(
            f"Pattern detection complete: {len(results)} stocks analyzed, "
            f"{stocks_with_patterns} with patterns ({total_patterns} total patterns found) "
            f"[Market: {market_regime}]"
        )

        return results
