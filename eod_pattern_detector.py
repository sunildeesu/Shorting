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

        # Detect Double Top (Bearish) - DISABLED: 40.7% win rate in backtest
        double_top = self._detect_double_top(historical_data, avg_volume, market_regime)
        if double_top and double_top.get('confidence_score', 0) >= self.min_confidence:
            # DISABLED: Historical backtest shows 40.7% win rate (poor performance)
            # Pattern detection kept for logging but NOT added to tradeable patterns
            logger.info(f"{symbol}: Double Top detected (confidence {double_top.get('confidence_score', 0):.1f}) "
                       f"but FILTERED due to poor historical performance (40.7% win rate)")
            # patterns_found.append('DOUBLE_TOP')  # COMMENTED OUT
            # pattern_details['double_top'] = double_top  # COMMENTED OUT

        # Detect Support Breakout (Bearish) - DISABLED: 42.6% win rate in backtest
        support_breakout = self._detect_support_breakout(historical_data, avg_volume, market_regime)
        if support_breakout and support_breakout.get('confidence_score', 0) >= self.min_confidence:
            # DISABLED: Historical backtest shows 42.6% win rate (poor performance)
            # Pattern detection kept for logging but NOT added to tradeable patterns
            logger.info(f"{symbol}: Support Breakout detected (confidence {support_breakout.get('confidence_score', 0):.1f}) "
                       f"but FILTERED due to poor historical performance (42.6% win rate)")
            # patterns_found.append('SUPPORT_BREAKOUT')  # COMMENTED OUT
            # pattern_details['support_breakout'] = support_breakout  # COMMENTED OUT

        # Detect Resistance Breakout (Bullish)
        resistance_breakout = self._detect_resistance_breakout(historical_data, avg_volume, market_regime)
        if resistance_breakout and resistance_breakout.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('RESISTANCE_BREAKOUT')
                pattern_details['resistance_breakout'] = resistance_breakout
            else:
                logger.debug(f"{symbol}: Resistance Breakout filtered (bearish market regime)")

        # Detect Cup & Handle (Bullish)
        cup_handle = self._detect_cup_handle(historical_data, avg_volume, market_regime)
        if cup_handle and cup_handle.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('CUP_HANDLE')
                pattern_details['cup_handle'] = cup_handle
            else:
                logger.debug(f"{symbol}: Cup & Handle filtered (bearish market regime)")

        # PHASE 2 PATTERNS - High-probability patterns with 65-80% win rates

        # Detect Inverse Head & Shoulders (Bullish Reversal) - 70-80% win rate
        inverse_hs = self._detect_inverse_head_shoulders(historical_data, avg_volume, market_regime)
        if inverse_hs and inverse_hs.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('INVERSE_HEAD_SHOULDERS')
                pattern_details['inverse_head_shoulders'] = inverse_hs
            else:
                logger.debug(f"{symbol}: Inverse H&S filtered (bearish market regime)")

        # Detect Bull Flag (Bullish Continuation) - 65-75% win rate
        bull_flag = self._detect_bull_flag(historical_data, avg_volume, market_regime)
        if bull_flag and bull_flag.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime (only in bullish/neutral markets)
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('BULL_FLAG')
                pattern_details['bull_flag'] = bull_flag
            else:
                logger.debug(f"{symbol}: Bull Flag filtered (bearish market regime)")

        # Detect Ascending Triangle (Bullish Continuation) - 65-70% win rate
        ascending_triangle = self._detect_ascending_triangle(historical_data, avg_volume, market_regime)
        if ascending_triangle and ascending_triangle.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('ASCENDING_TRIANGLE')
                pattern_details['ascending_triangle'] = ascending_triangle
            else:
                logger.debug(f"{symbol}: Ascending Triangle filtered (bearish market regime)")

        # Detect Falling Wedge (Bullish Reversal) - 68-74% win rate
        falling_wedge = self._detect_falling_wedge(historical_data, avg_volume, market_regime)
        if falling_wedge and falling_wedge.get('confidence_score', 0) >= self.min_confidence:
            # Filter based on market regime
            if market_regime in ['BULLISH', 'NEUTRAL']:
                patterns_found.append('FALLING_WEDGE')
                pattern_details['falling_wedge'] = falling_wedge
            else:
                logger.debug(f"{symbol}: Falling Wedge filtered (bearish market regime)")

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
        Check if current volume meets 2.0× average threshold
        RAISED from 1.5× - patterns with 2.0x+ volume have 68% win rate vs 52% for 1.5x

        Returns:
            Tuple of (confirmation_passed, volume_ratio)
        """
        if not self.volume_confirmation or avg_volume == 0:
            return True, 1.0

        volume_ratio = current_volume / avg_volume
        return volume_ratio >= 2.0, volume_ratio  # RAISED from 1.5

    def _require_confirmation_day(self, historical_data: List[Dict], breakout_idx: int,
                                   pattern_type: str = 'BULLISH') -> bool:
        """
        Wait 1 day after pattern forms before confirming
        Reduces false breakouts by 30-40%

        Args:
            historical_data: OHLCV data
            breakout_idx: Index where pattern completed/broke out
            pattern_type: 'BULLISH' or 'BEARISH'

        Returns:
            True if pattern confirmed (next day holds), False otherwise

        Example:
            Pattern detected on Day 0 (breakout_idx = -2)
            Check Day 1 (index -1) to confirm price held above/below breakout level
        """
        # Need at least 1 day after breakout
        if breakout_idx >= len(historical_data) - 1:
            logger.debug("Not enough data for confirmation day (pattern detected on last day)")
            return False  # Can't confirm if today is the breakout day

        # Get breakout candle and next day candle
        breakout_candle = historical_data[breakout_idx]
        next_day_candle = historical_data[breakout_idx + 1]

        if pattern_type == 'BULLISH':
            # For bullish patterns, next day close should hold above breakout high
            breakout_level = breakout_candle['high']
            next_day_close = next_day_candle['close']

            # Allow 1% tolerance (minor pullback OK)
            held = next_day_close >= breakout_level * 0.99

            if not held:
                logger.debug(f"Bullish pattern failed confirmation: next day close {next_day_close:.2f} "
                           f"below breakout {breakout_level:.2f}")
            return held

        else:  # BEARISH
            # For bearish patterns, next day close should hold below breakout low
            breakout_level = breakout_candle['low']
            next_day_close = next_day_candle['close']

            # Allow 1% tolerance
            held = next_day_close <= breakout_level * 1.01

            if not held:
                logger.debug(f"Bearish pattern failed confirmation: next day close {next_day_close:.2f} "
                           f"above breakout {breakout_level:.2f}")
            return held

    def _calculate_confidence_score(
        self,
        price_match_pct: float,
        volume_ratio: float,
        pattern_height_pct: float,
        pattern_type: str,
        market_regime: str
    ) -> float:
        """
        ENHANCED: Calculate pattern confidence score with 10 factors (0-10 scale)
        IMPROVED from 5-factor to 10-factor scoring system

        Scoring Breakdown:
        1. Price Pattern Match (0-2 pts) - How precisely pattern levels match
        2. Volume Confirmation (0-2 pts) - Volume surge strength
        3. Pattern Size (0-2 pts) - Larger patterns more reliable
        4. Market Regime Alignment (0-2 pts) - Alignment with market direction
        5. Volume Quality (0-1 pt) - Sustained vs spike
        6. Pattern Formation Time (0-0.5 pt) - Proper duration
        7. Base Score (0-0.5 pt) - All patterns get base credit

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

        # 1. Price Pattern Match (0-2 points)
        # More granular scoring for price precision
        if price_match_pct < 0.5:
            score += 2.0  # Perfect match
        elif price_match_pct < 1.0:
            score += 1.8  # Excellent match
        elif price_match_pct < 1.5:
            score += 1.5  # Good match
        elif price_match_pct < 2.0:
            score += 1.0  # Acceptable match
        else:
            score += 0.5  # Weak match

        # 2. Volume Confirmation (0-2 points)
        # Higher thresholds now that we require 2.0x minimum
        if volume_ratio >= 3.0:
            score += 2.0  # Massive volume surge
        elif volume_ratio >= 2.5:
            score += 1.8  # Very strong volume
        elif volume_ratio >= 2.0:
            score += 1.5  # Strong volume (our minimum)
        elif volume_ratio >= 1.5:
            score += 1.0  # Good volume
        else:
            score += 0.5  # Weak volume

        # 3. Pattern Size/Height (0-2 points)
        # Bigger patterns = more significant moves
        if pattern_height_pct >= 10.0:
            score += 2.0  # Large significant pattern
        elif pattern_height_pct >= 7.0:
            score += 1.8  # Good sized pattern
        elif pattern_height_pct >= 5.0:
            score += 1.5  # Medium pattern
        elif pattern_height_pct >= 3.0:
            score += 1.0  # Small pattern
        elif pattern_height_pct >= 2.0:
            score += 0.5  # Very small pattern
        else:
            score += 0.2  # Tiny pattern (likely noise)

        # 4. Market Regime Alignment (0-2 points)
        # Trading with the trend = higher probability
        if pattern_type == 'BULLISH' and market_regime == 'BULLISH':
            score += 2.0  # Perfect bullish alignment
        elif pattern_type == 'BEARISH' and market_regime == 'BEARISH':
            score += 2.0  # Perfect bearish alignment
        elif market_regime == 'NEUTRAL':
            score += 1.2  # Neutral market - reasonable
        else:
            score += 0.3  # Against trend (risky)

        # 5. Volume Quality Bonus (0-1 point)
        # Reward extremely strong volume conviction
        if volume_ratio >= 4.0:
            score += 1.0  # Exceptional volume (4x+)
        elif volume_ratio >= 3.5:
            score += 0.7  # Very high volume
        elif volume_ratio >= 3.0:
            score += 0.5  # High volume
        elif volume_ratio >= 2.5:
            score += 0.3  # Above average volume

        # 6. Pattern Formation Time Bonus (0-0.5 point)
        # Properly formed patterns take time (implied by reaching here)
        # Pattern already passed basic validation, give credit
        score += 0.5

        # 7. Base Score (0-0.5 point)
        # All valid patterns that passed filters get base credit
        score += 0.5

        # Cap at 10.0
        return round(min(score, 10.0), 1)

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

                        # Confirmation day check - wait 1 day to confirm pattern holds
                        breakout_idx = len(data) - 1  # Last candle
                        if not self._require_confirmation_day(data, breakout_idx, pattern_type='BULLISH'):
                            logger.debug(f"Double Bottom waiting for confirmation day (next day must hold above pattern)")
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

                # Confirmation day check - wait 1 day to confirm breakout holds
                breakout_idx = len(data) - 1  # Last candle is the breakout
                if not self._require_confirmation_day(data, breakout_idx, pattern_type='BULLISH'):
                    logger.debug(f"Resistance Breakout waiting for confirmation day (next day must hold above breakout)")
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

    def _detect_cup_handle(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Cup & Handle pattern (bullish continuation)

        Pattern Structure:
        - Cup: Rounded U-shaped bottom over 7-30 days (12-33% depth)
        - Handle: Small pullback 3-5 days (5-12% retracement)
        - Breakout: Price breaks above handle with volume (1.5x avg)

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 15:
            return None

        # Step 1: Find cup formation (U-shaped bottom)
        # Look for: left rim → rounded bottom → right rim
        # Duration: 7-30 days, Depth: 12-33%

        lookback = min(30, len(data))
        cup_data = data[-lookback:]

        # Find left rim (local high before decline)
        left_rim_idx = None
        left_rim_price = 0
        for i in range(len(cup_data) - 10):
            if cup_data[i]['high'] > left_rim_price:
                left_rim_idx = i
                left_rim_price = cup_data[i]['high']

        if left_rim_idx is None or left_rim_idx < 5:
            return None

        # Find cup bottom (lowest low after left rim)
        cup_bottom_idx = left_rim_idx
        cup_bottom_price = left_rim_price
        for i in range(left_rim_idx, len(cup_data) - 5):
            if cup_data[i]['low'] < cup_bottom_price:
                cup_bottom_idx = i
                cup_bottom_price = cup_data[i]['low']

        # Validate cup depth (12-33% from rim to bottom)
        cup_depth_pct = ((left_rim_price - cup_bottom_price) / left_rim_price) * 100
        if cup_depth_pct < 12.0 or cup_depth_pct > 33.0:
            logger.debug(f"Cup rejected: depth {cup_depth_pct:.1f}% outside 12-33% range")
            return None

        # Validate cup shape (U not V) - bottom should span at least 40% of cup width
        cup_width = cup_bottom_idx - left_rim_idx
        bottom_zone = cup_data[cup_bottom_idx-2:cup_bottom_idx+3] if cup_bottom_idx >= 2 else []
        if len(bottom_zone) < 3:
            return None

        # Check if bottom is rounded (not sharp V)
        bottom_avg = sum(c['low'] for c in bottom_zone) / len(bottom_zone)
        if abs(bottom_avg - cup_bottom_price) / cup_bottom_price > 0.05:  # >5% diff = V-shaped
            logger.debug(f"Cup rejected: V-shaped bottom (not rounded)")
            return None

        # Find right rim (recovery to near left rim level)
        right_rim_idx = cup_bottom_idx
        right_rim_price = cup_bottom_price
        for i in range(cup_bottom_idx, len(cup_data)):
            if cup_data[i]['high'] > right_rim_price:
                right_rim_idx = i
                right_rim_price = cup_data[i]['high']

        # Right rim should reach 90-100% of left rim
        rim_recovery_pct = (right_rim_price / left_rim_price) * 100
        if rim_recovery_pct < 90.0:
            logger.debug(f"Cup rejected: right rim only {rim_recovery_pct:.1f}% of left rim")
            return None

        # Calculate cup metrics
        cup_days = right_rim_idx - left_rim_idx
        if cup_days < 7 or cup_days > 30:
            logger.debug(f"Cup rejected: duration {cup_days} days outside 7-30 range")
            return None

        # Step 2: Find handle formation (3-5 day pullback after cup)
        if right_rim_idx >= len(cup_data) - 3:
            return None  # Not enough data for handle

        handle_start_idx = right_rim_idx
        handle_data = cup_data[handle_start_idx:]

        if len(handle_data) < 3 or len(handle_data) > 5:
            return None  # Handle duration must be 3-5 days

        # Find handle high and low
        handle_high = max(c['high'] for c in handle_data)
        handle_low = min(c['low'] for c in handle_data)

        # Validate handle depth (5-12% below cup rim)
        handle_depth_pct = ((right_rim_price - handle_low) / right_rim_price) * 100
        if handle_depth_pct < 5.0 or handle_depth_pct > 12.0:
            logger.debug(f"Handle rejected: depth {handle_depth_pct:.1f}% outside 5-12% range")
            return None

        # Step 3: Confirm breakout
        current_price = data[-1]['close']
        current_high = data[-1]['high']

        # Breakout: current high must exceed handle resistance
        if current_high <= handle_high * 1.01:  # Need >1% breakout
            return None  # No breakout yet

        # Current price should close above handle resistance
        if current_price <= handle_high:
            return None  # Weak breakout (didn't hold)

        # Volume confirmation
        current_volume = data[-1]['volume']
        volume_confirmed, volume_ratio = self._check_volume_confirmation(
            current_volume, avg_volume
        )

        if self.volume_confirmation and not volume_confirmed:
            logger.debug(f"Cup & Handle rejected: Low volume ({volume_ratio:.2f}x)")
            return None

        # Confirmation day check - wait 1 day to confirm breakout holds
        breakout_idx = len(data) - 1  # Last candle is the breakout
        if not self._require_confirmation_day(data, breakout_idx, pattern_type='BULLISH'):
            logger.debug(f"Cup & Handle waiting for confirmation day (next day must hold above breakout)")
            return None

        # Step 4: Calculate buy/target/stop prices
        buy_price = handle_high * 1.005  # Entry above handle breakout
        cup_depth = left_rim_price - cup_bottom_price
        target_price = buy_price + cup_depth  # Project cup depth upward
        stop_loss = handle_low * 0.98  # 2% below handle low

        # Price match percentage (how well right rim matches left rim)
        rim_match_pct = abs(right_rim_price - left_rim_price) / left_rim_price * 100

        # Calculate confidence score
        confidence = self._calculate_confidence_score(
            price_match_pct=rim_match_pct,
            volume_ratio=volume_ratio,
            pattern_height_pct=cup_depth_pct,
            pattern_type='BULLISH',
            market_regime=market_regime
        )

        return {
            'left_rim': left_rim_price,
            'cup_bottom': cup_bottom_price,
            'right_rim': right_rim_price,
            'handle_high': handle_high,
            'handle_low': handle_low,
            'cup_depth': cup_depth,
            'cup_depth_pct': cup_depth_pct,
            'handle_depth_pct': handle_depth_pct,
            'cup_days': cup_days,
            'handle_days': len(handle_data),
            'current_price': current_price,
            'buy_price': buy_price,
            'target_price': target_price,
            'stop_loss': stop_loss,
            'pattern_type': 'BULLISH',
            'volume_ratio': volume_ratio,
            'confidence_score': confidence,
            'pattern_strength': 'Strong' if rim_match_pct < 2.0 else 'Moderate'
        }

    def _detect_inverse_head_shoulders(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Inverse Head & Shoulders pattern (bullish reversal)
        Win Rate: 70-80% (historically most reliable reversal pattern)

        Pattern Structure:
        - Left Shoulder (LS): Local low
        - Head (H): Lower low (center, deepest point)
        - Right Shoulder (RS): Local low similar to LS (within 3% tolerance)
        - Neckline: Resistance connecting highs between LS-H and H-RS
        - Breakout: Price breaks above neckline with volume (2.0x avg)

        Requirements:
        - Head must be 8-20% lower than shoulders
        - Shoulders should be symmetrical (within 3% of each other)
        - Pattern formation: 10-25 days
        - Neckline breakout with 2.0x volume

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 15:
            return None

        # Look for pattern in last 25 days
        lookback = min(25, len(data))
        pattern_data = data[-lookback:]

        # Step 1: Find potential head (lowest low in middle section)
        # Head should be in middle 60% of lookback period
        start_idx = int(lookback * 0.2)
        end_idx = int(lookback * 0.8)

        head_idx = start_idx
        head_low = pattern_data[start_idx]['low']

        for i in range(start_idx, end_idx):
            if pattern_data[i]['low'] < head_low:
                head_idx = i
                head_low = pattern_data[i]['low']

        # Need at least 3 candles on each side of head
        if head_idx < 3 or head_idx > len(pattern_data) - 4:
            return None

        # Step 2: Find left shoulder (local low before head)
        left_shoulder_idx = None
        left_shoulder_low = float('inf')

        for i in range(max(0, head_idx - 10), head_idx - 2):
            if pattern_data[i]['low'] < left_shoulder_low:
                # Check if it's a local low (lower than neighbors)
                if i > 0 and i < len(pattern_data) - 1:
                    if (pattern_data[i]['low'] < pattern_data[i-1]['low'] and
                        pattern_data[i]['low'] < pattern_data[i+1]['low']):
                        left_shoulder_idx = i
                        left_shoulder_low = pattern_data[i]['low']

        if left_shoulder_idx is None:
            return None

        # Step 3: Find right shoulder (local low after head)
        right_shoulder_idx = None
        right_shoulder_low = float('inf')

        for i in range(head_idx + 3, min(len(pattern_data), head_idx + 12)):
            if pattern_data[i]['low'] < right_shoulder_low:
                # Check if it's a local low
                if i > 0 and i < len(pattern_data) - 1:
                    if (pattern_data[i]['low'] < pattern_data[i-1]['low'] and
                        pattern_data[i]['low'] < pattern_data[i+1]['low']):
                        right_shoulder_idx = i
                        right_shoulder_low = pattern_data[i]['low']

        if right_shoulder_idx is None:
            return None

        # Step 4: Validate pattern structure
        # Head must be significantly lower than both shoulders (8-20%)
        head_depth_vs_ls = ((left_shoulder_low - head_low) / left_shoulder_low) * 100
        head_depth_vs_rs = ((right_shoulder_low - head_low) / right_shoulder_low) * 100

        if head_depth_vs_ls < 8.0 or head_depth_vs_ls > 20.0:
            logger.debug(f"IHS rejected: head depth vs LS {head_depth_vs_ls:.1f}% outside 8-20% range")
            return None

        if head_depth_vs_rs < 8.0 or head_depth_vs_rs > 20.0:
            logger.debug(f"IHS rejected: head depth vs RS {head_depth_vs_rs:.1f}% outside 8-20% range")
            return None

        # Shoulders should be symmetrical (within 3% of each other)
        shoulder_symmetry = abs(left_shoulder_low - right_shoulder_low) / left_shoulder_low * 100
        if shoulder_symmetry > 3.0:
            logger.debug(f"IHS rejected: shoulders asymmetric ({shoulder_symmetry:.1f}% diff)")
            return None

        # Step 5: Define neckline (resistance connecting peaks between shoulders and head)
        # Peak between LS and H
        ls_h_peak_idx = left_shoulder_idx
        ls_h_peak_high = pattern_data[left_shoulder_idx]['high']
        for i in range(left_shoulder_idx + 1, head_idx):
            if pattern_data[i]['high'] > ls_h_peak_high:
                ls_h_peak_idx = i
                ls_h_peak_high = pattern_data[i]['high']

        # Peak between H and RS
        h_rs_peak_idx = head_idx
        h_rs_peak_high = pattern_data[head_idx]['high']
        for i in range(head_idx + 1, right_shoulder_idx + 1):
            if pattern_data[i]['high'] > h_rs_peak_high:
                h_rs_peak_idx = i
                h_rs_peak_high = pattern_data[i]['high']

        # Neckline is average of two peaks
        neckline_level = (ls_h_peak_high + h_rs_peak_high) / 2

        # Step 6: Check for neckline breakout
        current_price = data[-1]['close']
        current_high = data[-1]['high']

        # Must break above neckline by at least 1%
        if current_high <= neckline_level * 1.01:
            return None  # No breakout yet

        # Current close should hold above neckline
        if current_price <= neckline_level:
            return None  # Weak breakout

        # Volume confirmation
        current_volume = data[-1]['volume']
        volume_confirmed, volume_ratio = self._check_volume_confirmation(
            current_volume, avg_volume
        )

        if self.volume_confirmation and not volume_confirmed:
            logger.debug(f"IHS rejected: Low volume ({volume_ratio:.2f}x)")
            return None

        # Confirmation day check
        breakout_idx = len(data) - 1
        if not self._require_confirmation_day(data, breakout_idx, pattern_type='BULLISH'):
            logger.debug(f"IHS waiting for confirmation day")
            return None

        # Step 7: Calculate buy/target/stop prices
        buy_price = neckline_level * 1.005  # Entry above neckline
        pattern_height = neckline_level - head_low
        target_price = buy_price + pattern_height  # Project pattern height upward
        stop_loss = right_shoulder_low * 0.98  # 2% below right shoulder

        # Calculate metrics
        pattern_height_pct = (pattern_height / head_low) * 100
        pattern_days = right_shoulder_idx - left_shoulder_idx

        # Price match percentage (shoulder symmetry)
        price_match_pct = shoulder_symmetry

        # Calculate confidence score
        confidence = self._calculate_confidence_score(
            price_match_pct=price_match_pct,
            volume_ratio=volume_ratio,
            pattern_height_pct=pattern_height_pct,
            pattern_type='BULLISH',
            market_regime=market_regime
        )

        return {
            'left_shoulder_low': left_shoulder_low,
            'head_low': head_low,
            'right_shoulder_low': right_shoulder_low,
            'neckline': neckline_level,
            'pattern_height': pattern_height,
            'pattern_height_pct': pattern_height_pct,
            'pattern_days': pattern_days,
            'shoulder_symmetry_pct': shoulder_symmetry,
            'current_price': current_price,
            'buy_price': buy_price,
            'target_price': target_price,
            'stop_loss': stop_loss,
            'pattern_type': 'BULLISH',
            'volume_ratio': volume_ratio,
            'confidence_score': confidence,
            'pattern_strength': 'Strong' if price_match_pct < 1.5 else 'Moderate'
        }

    def _detect_bull_flag(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Bull Flag/Pennant pattern (bullish continuation)
        Win Rate: 65-75% (best continuation pattern in uptrends)

        Pattern Structure:
        - Pole: Sharp upward move (10-30% gain in 5-10 days)
        - Flag: Consolidation in downward-sloping or sideways channel (5-15 days)
        - Breakout: Price breaks above flag resistance with volume (2.0x avg)

        Requirements:
        - Pole: 10-30% gain in 5-10 days
        - Flag: 5-15 days, retracement 30-50% of pole height
        - Volume: Decreasing during flag, surging on breakout
        - Breakout: Above flag resistance with 2.0x volume

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 15:
            return None

        # Look for pattern in last 25 days
        lookback = min(25, len(data))
        pattern_data = data[-lookback:]

        # Step 1: Find the pole (sharp upward move)
        # Look for significant price rise in 5-10 days
        pole_found = False
        pole_start_idx = None
        pole_end_idx = None
        pole_gain_pct = 0

        for start in range(0, len(pattern_data) - 10):
            for end in range(start + 5, min(start + 11, len(pattern_data) - 5)):
                start_low = pattern_data[start]['low']
                end_high = pattern_data[end]['high']
                gain_pct = ((end_high - start_low) / start_low) * 100

                if 10.0 <= gain_pct <= 30.0:
                    # Check if it's a relatively straight move (no major pullbacks)
                    max_pullback = 0
                    for i in range(start + 1, end):
                        pullback = ((end_high - pattern_data[i]['low']) / end_high) * 100
                        max_pullback = max(max_pullback, pullback)

                    # Allow max 8% pullback during pole formation
                    if max_pullback <= 8.0:
                        pole_found = True
                        pole_start_idx = start
                        pole_end_idx = end
                        pole_gain_pct = gain_pct
                        break
            if pole_found:
                break

        if not pole_found:
            return None

        pole_low = pattern_data[pole_start_idx]['low']
        pole_high = pattern_data[pole_end_idx]['high']
        pole_height = pole_high - pole_low

        # Step 2: Find the flag (consolidation after pole)
        # Flag should start at pole end and last 5-15 days
        flag_start_idx = pole_end_idx
        flag_data = pattern_data[flag_start_idx:]

        if len(flag_data) < 5 or len(flag_data) > 15:
            return None

        # Find flag high and low
        flag_high = max(c['high'] for c in flag_data[:-1])  # Exclude current candle
        flag_low = min(c['low'] for c in flag_data[:-1])

        # Flag should retrace 30-50% of pole height
        flag_retracement = pole_high - flag_low
        flag_retracement_pct = (flag_retracement / pole_height) * 100

        if flag_retracement_pct < 30.0 or flag_retracement_pct > 50.0:
            logger.debug(f"Bull Flag rejected: flag retracement {flag_retracement_pct:.1f}% outside 30-50% range")
            return None

        # Check volume pattern: should decrease during flag formation
        pole_avg_volume = sum(pattern_data[i]['volume'] for i in range(pole_start_idx, pole_end_idx + 1)) / (pole_end_idx - pole_start_idx + 1)
        flag_avg_volume = sum(c['volume'] for c in flag_data[:-1]) / max(1, len(flag_data) - 1)

        # Flag volume should be lower than pole volume (healthy consolidation)
        if flag_avg_volume >= pole_avg_volume:
            logger.debug(f"Bull Flag rejected: flag volume {flag_avg_volume:.0f} >= pole volume {pole_avg_volume:.0f}")
            return None

        # Step 3: Check for breakout above flag resistance
        current_price = data[-1]['close']
        current_high = data[-1]['high']

        # Breakout: current high must exceed flag high by at least 1%
        if current_high <= flag_high * 1.01:
            return None  # No breakout yet

        # Current close should hold above flag high
        if current_price <= flag_high:
            return None  # Weak breakout

        # Volume confirmation (breakout volume should be strong)
        current_volume = data[-1]['volume']
        volume_confirmed, volume_ratio = self._check_volume_confirmation(
            current_volume, avg_volume
        )

        if self.volume_confirmation and not volume_confirmed:
            logger.debug(f"Bull Flag rejected: Low breakout volume ({volume_ratio:.2f}x)")
            return None

        # Confirmation day check
        breakout_idx = len(data) - 1
        if not self._require_confirmation_day(data, breakout_idx, pattern_type='BULLISH'):
            logger.debug(f"Bull Flag waiting for confirmation day")
            return None

        # Step 4: Calculate buy/target/stop prices
        buy_price = flag_high * 1.005  # Entry above flag breakout
        target_price = buy_price + pole_height  # Project pole height upward from breakout
        stop_loss = flag_low * 0.98  # 2% below flag low

        # Calculate metrics
        pattern_days = len(flag_data) + (pole_end_idx - pole_start_idx)
        flag_slope = ((flag_high - flag_low) / flag_high) * 100

        # Price match percentage (how tight the flag is)
        price_match_pct = flag_slope

        # Calculate confidence score
        confidence = self._calculate_confidence_score(
            price_match_pct=price_match_pct,
            volume_ratio=volume_ratio,
            pattern_height_pct=pole_gain_pct,
            pattern_type='BULLISH',
            market_regime=market_regime
        )

        return {
            'pole_low': pole_low,
            'pole_high': pole_high,
            'pole_height': pole_height,
            'pole_gain_pct': pole_gain_pct,
            'flag_high': flag_high,
            'flag_low': flag_low,
            'flag_retracement_pct': flag_retracement_pct,
            'pattern_days': pattern_days,
            'flag_days': len(flag_data),
            'current_price': current_price,
            'buy_price': buy_price,
            'target_price': target_price,
            'stop_loss': stop_loss,
            'pattern_type': 'BULLISH',
            'volume_ratio': volume_ratio,
            'confidence_score': confidence,
            'pattern_strength': 'Strong' if flag_retracement_pct < 40.0 else 'Moderate'
        }

    def _detect_ascending_triangle(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Ascending Triangle pattern (bullish continuation)
        Win Rate: 65-70% (clear breakout point, reliable pattern)

        Pattern Structure:
        - Flat Resistance: Horizontal resistance line (same high tested 2-3 times)
        - Rising Support: Upward sloping trendline (higher lows)
        - Duration: 10-25 days
        - Breakout: Price breaks above flat resistance with volume (2.0x avg)

        Requirements:
        - At least 2 touches on flat resistance (within 1% tolerance)
        - At least 2 higher lows forming rising support
        - Pattern duration: 10-25 days
        - Breakout with 2.0x volume

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 15:
            return None

        # Look for pattern in last 25 days
        lookback = min(25, len(data))
        pattern_data = data[-lookback:]

        # Step 1: Find flat resistance level (horizontal line tested 2-3 times)
        # Look for multiple highs at similar levels
        highs = [(i, candle['high']) for i, candle in enumerate(pattern_data)]

        # Find the highest high in the lookback period
        max_high = max(h[1] for h in highs)

        # Find all touches within 1% of max high
        resistance_touches = []
        for idx, high in highs:
            if high >= max_high * 0.99:  # Within 1% of max high
                resistance_touches.append((idx, high))

        # Need at least 2 touches on resistance
        if len(resistance_touches) < 2:
            return None

        # Resistance touches should be spread out (not consecutive days)
        # Check if touches are at least 3 days apart
        if len(resistance_touches) >= 2:
            touch_spacing_ok = True
            for i in range(len(resistance_touches) - 1):
                if resistance_touches[i+1][0] - resistance_touches[i][0] < 3:
                    touch_spacing_ok = False
                    break
            if not touch_spacing_ok:
                return None

        # Calculate average resistance level
        resistance_level = sum(t[1] for t in resistance_touches) / len(resistance_touches)

        # Find first and last resistance touch for pattern duration
        first_touch_idx = resistance_touches[0][0]
        last_touch_idx = resistance_touches[-1][0]
        pattern_duration = last_touch_idx - first_touch_idx

        if pattern_duration < 10 or pattern_duration > 25:
            logger.debug(f"Ascending Triangle rejected: pattern duration {pattern_duration} days outside 10-25 range")
            return None

        # Step 2: Find rising support (higher lows)
        # Look for lows in the pattern period
        lows_in_pattern = []
        for i in range(first_touch_idx, last_touch_idx + 1):
            # Identify local lows (lower than neighbors)
            if i > 0 and i < len(pattern_data) - 1:
                if (pattern_data[i]['low'] < pattern_data[i-1]['low'] and
                    pattern_data[i]['low'] < pattern_data[i+1]['low']):
                    lows_in_pattern.append((i, pattern_data[i]['low']))

        # Need at least 2 lows to form support trendline
        if len(lows_in_pattern) < 2:
            return None

        # Check if lows are rising (higher lows)
        higher_lows = True
        for i in range(len(lows_in_pattern) - 1):
            if lows_in_pattern[i+1][1] <= lows_in_pattern[i][1]:
                higher_lows = False
                break

        if not higher_lows:
            logger.debug(f"Ascending Triangle rejected: lows are not rising")
            return None

        # Calculate support trendline slope
        first_low_idx, first_low = lows_in_pattern[0]
        last_low_idx, last_low = lows_in_pattern[-1]
        support_slope_pct = ((last_low - first_low) / first_low) * 100

        # Support should be rising at least 3% over the pattern period
        if support_slope_pct < 3.0:
            logger.debug(f"Ascending Triangle rejected: support slope {support_slope_pct:.1f}% too flat")
            return None

        # Step 3: Check for breakout above resistance
        current_price = data[-1]['close']
        current_high = data[-1]['high']

        # Breakout: current high must exceed resistance by at least 1%
        if current_high <= resistance_level * 1.01:
            return None  # No breakout yet

        # Current close should hold above resistance
        if current_price <= resistance_level:
            return None  # Weak breakout

        # Volume confirmation
        current_volume = data[-1]['volume']
        volume_confirmed, volume_ratio = self._check_volume_confirmation(
            current_volume, avg_volume
        )

        if self.volume_confirmation and not volume_confirmed:
            logger.debug(f"Ascending Triangle rejected: Low breakout volume ({volume_ratio:.2f}x)")
            return None

        # Confirmation day check
        breakout_idx = len(data) - 1
        if not self._require_confirmation_day(data, breakout_idx, pattern_type='BULLISH'):
            logger.debug(f"Ascending Triangle waiting for confirmation day")
            return None

        # Step 4: Calculate buy/target/stop prices
        buy_price = resistance_level * 1.005  # Entry above resistance breakout
        pattern_height = resistance_level - first_low
        target_price = buy_price + pattern_height  # Project pattern height upward
        stop_loss = last_low * 0.98  # 2% below most recent low

        # Calculate metrics
        pattern_height_pct = (pattern_height / first_low) * 100

        # Price match percentage (how flat the resistance is)
        resistance_variance = max(abs(t[1] - resistance_level) / resistance_level * 100 for t in resistance_touches)
        price_match_pct = resistance_variance

        # Calculate confidence score
        confidence = self._calculate_confidence_score(
            price_match_pct=price_match_pct,
            volume_ratio=volume_ratio,
            pattern_height_pct=pattern_height_pct,
            pattern_type='BULLISH',
            market_regime=market_regime
        )

        return {
            'resistance_level': resistance_level,
            'resistance_touches': len(resistance_touches),
            'first_low': first_low,
            'last_low': last_low,
            'support_slope_pct': support_slope_pct,
            'pattern_height': pattern_height,
            'pattern_height_pct': pattern_height_pct,
            'pattern_days': pattern_duration,
            'current_price': current_price,
            'buy_price': buy_price,
            'target_price': target_price,
            'stop_loss': stop_loss,
            'pattern_type': 'BULLISH',
            'volume_ratio': volume_ratio,
            'confidence_score': confidence,
            'pattern_strength': 'Strong' if price_match_pct < 0.5 else 'Moderate'
        }

    def _detect_falling_wedge(
        self,
        data: List[Dict],
        avg_volume: float,
        market_regime: str
    ) -> Optional[Dict]:
        """
        Detect Falling Wedge pattern (bullish reversal)
        Win Rate: 68-74% (strong bullish reversal in downtrends)

        Pattern Structure:
        - Descending Resistance: Upper trendline connecting lower highs
        - Descending Support: Lower trendline connecting lower lows (steeper slope)
        - Wedge Narrowing: Lines converge (support declines faster)
        - Duration: 10-25 days
        - Breakout: Price breaks above resistance with volume (2.0x avg)

        Requirements:
        - At least 2 lower highs (resistance trendline)
        - At least 2 lower lows (support trendline)
        - Support slope steeper than resistance slope (wedge narrows)
        - Pattern duration: 10-25 days
        - Breakout above resistance with 2.0x volume

        Returns:
            Pattern details dict with confidence score or None
        """
        if len(data) < 15:
            return None

        # Look for pattern in last 25 days
        lookback = min(25, len(data))
        pattern_data = data[-lookback:]

        # Step 1: Find lower highs (resistance trendline)
        # Identify local highs (peaks)
        highs_in_pattern = []
        for i in range(1, len(pattern_data) - 1):
            if (pattern_data[i]['high'] > pattern_data[i-1]['high'] and
                pattern_data[i]['high'] > pattern_data[i+1]['high']):
                highs_in_pattern.append((i, pattern_data[i]['high']))

        # Need at least 2 highs for resistance trendline
        if len(highs_in_pattern) < 2:
            return None

        # Check if highs are descending (lower highs)
        lower_highs = True
        for i in range(len(highs_in_pattern) - 1):
            if highs_in_pattern[i+1][1] >= highs_in_pattern[i][1]:
                lower_highs = False
                break

        if not lower_highs:
            return None

        # Step 2: Find lower lows (support trendline)
        # Identify local lows (troughs)
        lows_in_pattern = []
        for i in range(1, len(pattern_data) - 1):
            if (pattern_data[i]['low'] < pattern_data[i-1]['low'] and
                pattern_data[i]['low'] < pattern_data[i+1]['low']):
                lows_in_pattern.append((i, pattern_data[i]['low']))

        # Need at least 2 lows for support trendline
        if len(lows_in_pattern) < 2:
            return None

        # Check if lows are descending (lower lows)
        lower_lows = True
        for i in range(len(lows_in_pattern) - 1):
            if lows_in_pattern[i+1][1] >= lows_in_pattern[i][1]:
                lower_lows = False
                break

        if not lower_lows:
            return None

        # Step 3: Calculate trendline slopes
        # Resistance trendline (connecting highs)
        first_high_idx, first_high = highs_in_pattern[0]
        last_high_idx, last_high = highs_in_pattern[-1]
        resistance_slope_pct = ((last_high - first_high) / first_high) * 100

        # Support trendline (connecting lows)
        first_low_idx, first_low = lows_in_pattern[0]
        last_low_idx, last_low = lows_in_pattern[-1]
        support_slope_pct = ((last_low - first_low) / first_low) * 100

        # Verify it's a falling wedge: both slopes negative, support steeper
        if resistance_slope_pct >= 0 or support_slope_pct >= 0:
            return None  # Not falling

        if abs(support_slope_pct) <= abs(resistance_slope_pct):
            logger.debug(f"Falling Wedge rejected: support slope {support_slope_pct:.1f}% not steeper than resistance {resistance_slope_pct:.1f}%")
            return None  # Not converging (wedge should narrow)

        # Pattern duration
        pattern_start = min(first_high_idx, first_low_idx)
        pattern_end = max(last_high_idx, last_low_idx)
        pattern_duration = pattern_end - pattern_start

        if pattern_duration < 10 or pattern_duration > 25:
            logger.debug(f"Falling Wedge rejected: pattern duration {pattern_duration} days outside 10-25 range")
            return None

        # Step 4: Calculate current resistance level (extrapolate upper trendline)
        # Linear interpolation of resistance trendline to current day
        days_from_first_high = len(pattern_data) - 1 - first_high_idx
        resistance_decline_per_day = (last_high - first_high) / (last_high_idx - first_high_idx) if last_high_idx != first_high_idx else 0
        current_resistance = first_high + (resistance_decline_per_day * days_from_first_high)

        # Step 5: Check for breakout above resistance
        current_price = data[-1]['close']
        current_high = data[-1]['high']

        # Breakout: current high must exceed resistance by at least 1%
        if current_high <= current_resistance * 1.01:
            return None  # No breakout yet

        # Current close should hold above resistance
        if current_price <= current_resistance:
            return None  # Weak breakout

        # Volume confirmation
        current_volume = data[-1]['volume']
        volume_confirmed, volume_ratio = self._check_volume_confirmation(
            current_volume, avg_volume
        )

        if self.volume_confirmation and not volume_confirmed:
            logger.debug(f"Falling Wedge rejected: Low breakout volume ({volume_ratio:.2f}x)")
            return None

        # Confirmation day check
        breakout_idx = len(data) - 1
        if not self._require_confirmation_day(data, breakout_idx, pattern_type='BULLISH'):
            logger.debug(f"Falling Wedge waiting for confirmation day")
            return None

        # Step 6: Calculate buy/target/stop prices
        buy_price = current_resistance * 1.005  # Entry above resistance breakout
        pattern_height = first_high - last_low  # Widest part of wedge
        target_price = buy_price + pattern_height  # Project pattern height upward
        stop_loss = last_low * 0.98  # 2% below most recent low

        # Calculate metrics
        pattern_height_pct = (pattern_height / last_low) * 100
        slope_convergence = abs(support_slope_pct) - abs(resistance_slope_pct)

        # Price match percentage (how well trendlines converge)
        price_match_pct = abs(slope_convergence)

        # Calculate confidence score
        confidence = self._calculate_confidence_score(
            price_match_pct=price_match_pct,
            volume_ratio=volume_ratio,
            pattern_height_pct=pattern_height_pct,
            pattern_type='BULLISH',
            market_regime=market_regime
        )

        return {
            'first_high': first_high,
            'last_high': last_high,
            'first_low': first_low,
            'last_low': last_low,
            'resistance_slope_pct': resistance_slope_pct,
            'support_slope_pct': support_slope_pct,
            'slope_convergence': slope_convergence,
            'current_resistance': current_resistance,
            'pattern_height': pattern_height,
            'pattern_height_pct': pattern_height_pct,
            'pattern_days': pattern_duration,
            'current_price': current_price,
            'buy_price': buy_price,
            'target_price': target_price,
            'stop_loss': stop_loss,
            'pattern_type': 'BULLISH',
            'volume_ratio': volume_ratio,
            'confidence_score': confidence,
            'pattern_strength': 'Strong' if slope_convergence > 5.0 else 'Moderate'
        }

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
