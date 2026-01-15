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
from datetime import datetime

logger = logging.getLogger(__name__)


class PriceActionDetector:
    """
    Detects candlestick patterns on 5-minute timeframe with confidence scoring

    Features:
    - 15-20 pattern detection methods
    - 0-10 confidence scoring with multiple factors
    - Market regime filtering
    - Volume analysis (bonus, not mandatory)
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

        # List of all pattern detection methods
        pattern_methods = [
            # Reversal patterns
            self._detect_bullish_engulfing,
            self._detect_bearish_engulfing,
            self._detect_hammer,
            self._detect_shooting_star,
            self._detect_inverted_hammer,
            self._detect_hanging_man,
            self._detect_morning_star,
            self._detect_evening_star,
            self._detect_piercing_pattern,
            self._detect_dark_cloud_cover,
            # Indecision patterns
            self._detect_doji,
            self._detect_spinning_top,
            self._detect_long_legged_doji,
            # Continuation patterns
            self._detect_bullish_marubozu,
            self._detect_bearish_marubozu,
            self._detect_rising_three_methods,
            self._detect_falling_three_methods,
            # Multi-candle formations
            self._detect_three_white_soldiers,
            self._detect_three_black_crows,
        ]

        # Run all pattern detections
        for method in pattern_methods:
            try:
                pattern_data = method(candles, market_regime, avg_volume)

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
                logger.error(f"{symbol}: Error in {method.__name__}: {e}", exc_info=True)

        return result

    def _calculate_atr(self, candles: List[Dict], period: int = None) -> float:
        """
        Calculate Average True Range (ATR) for volatility-based targets/stops

        Args:
            candles: List of OHLCV candle dicts
            period: ATR period (uses self.atr_period if not specified)

        Returns:
            ATR value
        """
        if period is None:
            period = self.atr_period

        if len(candles) < period + 1:
            # Not enough data, use simple range
            recent_candles = candles[-min(5, len(candles)):]
            ranges = [c['high'] - c['low'] for c in recent_candles]
            return sum(ranges) / len(ranges)

        # Calculate True Range for each candle
        true_ranges = []
        for i in range(len(candles) - period, len(candles)):
            high = candles[i]['high']
            low = candles[i]['low']
            prev_close = candles[i-1]['close'] if i > 0 else candles[i]['close']

            # True Range = max of:
            # 1. Current high - current low
            # 2. Abs(current high - previous close)
            # 3. Abs(current low - previous close)
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)

        # ATR is the average of True Ranges
        atr = sum(true_ranges) / len(true_ranges)
        return atr

    # ============================================
    # REVERSAL PATTERNS
    # ============================================

    def _detect_bullish_engulfing(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Bullish Engulfing: Strong bullish reversal pattern

        Rules:
        1. Candle[-2]: Red/bearish (close < open)
        2. Candle[-1]: Green/bullish (close > open)
        3. Candle[-1] body completely engulfs candle[-2] body
        4. Candle[-1].open <= Candle[-2].close
        5. Candle[-1].close >= Candle[-2].open

        Confidence Scoring (0-10):
        - Body size ratio (0-2.5): Larger engulfing body = higher confidence
        - Volume confirmation (0-2.5): Current volume vs average
        - Previous trend context (0-2.0): Engulfing after downtrend = stronger
        - Pattern position (0-2.0): Near support/key level = stronger
        - Market regime bonus (0-1.0)

        Returns:
            Pattern details dict or None
        """
        if len(candles) < 12:
            return None

        prev_candle = candles[-2]
        curr_candle = candles[-1]

        # Rule 1: Previous candle is bearish
        if prev_candle['close'] >= prev_candle['open']:
            return None

        # Rule 2: Current candle is bullish
        if curr_candle['close'] <= curr_candle['open']:
            return None

        # Rule 3-5: Engulfing body check
        prev_body_top = max(prev_candle['open'], prev_candle['close'])
        prev_body_bottom = min(prev_candle['open'], prev_candle['close'])
        curr_body_top = max(curr_candle['open'], curr_candle['close'])
        curr_body_bottom = min(curr_candle['open'], curr_candle['close'])

        if not (curr_body_bottom <= prev_body_bottom and
                curr_body_top >= prev_body_top):
            return None

        # Calculate confidence components

        # 1. Body size ratio (0-2.5)
        prev_body = abs(prev_candle['close'] - prev_candle['open'])
        curr_body = abs(curr_candle['close'] - curr_candle['open'])

        if prev_body == 0:
            return None  # Avoid division by zero

        body_ratio = curr_body / prev_body
        if body_ratio >= 2.0:
            body_score = 2.5
        elif body_ratio >= 1.5:
            body_score = 2.0
        elif body_ratio >= 1.2:
            body_score = 1.5
        else:
            body_score = 1.0

        # 2. Volume confirmation (0-2.5)
        current_volume = curr_candle['volume']
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        if volume_ratio >= 2.0:
            volume_score = 2.5
        elif volume_ratio >= 1.5:
            volume_score = 2.0
        elif volume_ratio >= 1.2:
            volume_score = 1.5
        else:
            volume_score = 1.0

        # 3. Previous trend context (0-2.0)
        lookback = min(10, len(candles) - 2)
        start_candle = candles[-lookback-2]
        trend_change = ((prev_candle['close'] - start_candle['close']) /
                        start_candle['close'] * 100)

        if trend_change <= -3.0:
            trend_score = 2.0  # Strong downtrend
        elif trend_change <= -1.5:
            trend_score = 1.5  # Moderate downtrend
        elif trend_change <= -0.5:
            trend_score = 1.0  # Weak downtrend
        else:
            trend_score = 0.5  # Sideways/uptrend

        # 4. Pattern position (0-2.0)
        recent_lows = [c['low'] for c in candles[-6:-1]]
        min_low = min(recent_lows)

        if curr_candle['low'] <= min_low * 1.005:  # Within 0.5% of low
            position_score = 2.0
        elif curr_candle['low'] <= min_low * 1.01:  # Within 1% of low
            position_score = 1.5
        else:
            position_score = 1.0

        # 5. Market regime bonus (0-1.0)
        if market_regime == 'BULLISH':
            regime_score = 1.0
        elif market_regime == 'NEUTRAL':
            regime_score = 0.5
        else:
            regime_score = 0.0

        # Total confidence score
        confidence = body_score + volume_score + trend_score + position_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        # Only return if meets minimum threshold
        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Calculate entry, target, stop loss using ATR
        entry_price = curr_candle['close'] * 1.001  # 0.1% above close
        target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['low'] * 0.995  # Pattern-based stop (below low)

        return {
            'pattern_name': 'Bullish Engulfing',
            'type': 'bullish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Bullish engulfing ({body_ratio:.1f}x size) after {abs(trend_change):.1f}% decline',
            'candle_data': {
                'prev_candle': {
                    'open': prev_candle['open'],
                    'high': prev_candle['high'],
                    'low': prev_candle['low'],
                    'close': prev_candle['close'],
                    'volume': prev_candle['volume']
                },
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume']
                }
            },
            'confidence_breakdown': {
                'body_ratio': body_score,
                'volume': volume_score,
                'trend': trend_score,
                'position': position_score,
                'regime': regime_score
            }
        }

    def _detect_bearish_engulfing(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Bearish Engulfing: Strong bearish reversal pattern

        Rules:
        1. Candle[-2]: Green/bullish (close > open)
        2. Candle[-1]: Red/bearish (close < open)
        3. Candle[-1] body completely engulfs candle[-2] body

        Returns:
            Pattern details dict or None
        """
        if len(candles) < 12:
            return None

        prev_candle = candles[-2]
        curr_candle = candles[-1]

        # Rule 1: Previous candle is bullish
        if prev_candle['close'] <= prev_candle['open']:
            return None

        # Rule 2: Current candle is bearish
        if curr_candle['close'] >= curr_candle['open']:
            return None

        # Rule 3: Engulfing body check
        prev_body_top = max(prev_candle['open'], prev_candle['close'])
        prev_body_bottom = min(prev_candle['open'], prev_candle['close'])
        curr_body_top = max(curr_candle['open'], curr_candle['close'])
        curr_body_bottom = min(curr_candle['open'], curr_candle['close'])

        if not (curr_body_bottom <= prev_body_bottom and
                curr_body_top >= prev_body_top):
            return None

        # Calculate confidence components
        prev_body = abs(prev_candle['close'] - prev_candle['open'])
        curr_body = abs(curr_candle['close'] - curr_candle['open'])

        if prev_body == 0:
            return None

        body_ratio = curr_body / prev_body
        if body_ratio >= 2.0:
            body_score = 2.5
        elif body_ratio >= 1.5:
            body_score = 2.0
        elif body_ratio >= 1.2:
            body_score = 1.5
        else:
            body_score = 1.0

        # Volume
        current_volume = curr_candle['volume']
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        if volume_ratio >= 2.0:
            volume_score = 2.5
        elif volume_ratio >= 1.5:
            volume_score = 2.0
        elif volume_ratio >= 1.2:
            volume_score = 1.5
        else:
            volume_score = 1.0

        # Previous uptrend check
        lookback = min(10, len(candles) - 2)
        start_candle = candles[-lookback-2]
        trend_change = ((prev_candle['close'] - start_candle['close']) /
                        start_candle['close'] * 100)

        if trend_change >= 3.0:
            trend_score = 2.0
        elif trend_change >= 1.5:
            trend_score = 1.5
        elif trend_change >= 0.5:
            trend_score = 1.0
        else:
            trend_score = 0.5

        # Position (near recent high)
        recent_highs = [c['high'] for c in candles[-6:-1]]
        max_high = max(recent_highs)

        if curr_candle['high'] >= max_high * 0.995:
            position_score = 2.0
        elif curr_candle['high'] >= max_high * 0.99:
            position_score = 1.5
        else:
            position_score = 1.0

        # Market regime
        if market_regime == 'BEARISH':
            regime_score = 1.0
        elif market_regime == 'NEUTRAL':
            regime_score = 0.5
        else:
            regime_score = 0.0

        # Total confidence
        confidence = body_score + volume_score + trend_score + position_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop (bearish pattern) using ATR
        entry_price = curr_candle['close'] * 0.999  # 0.1% below close
        target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['high'] * 1.005  # Pattern-based stop (above high)

        return {
            'pattern_name': 'Bearish Engulfing',
            'type': 'bearish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Bearish engulfing ({body_ratio:.1f}x size) after {trend_change:.1f}% rise',
            'candle_data': {
                'prev_candle': {
                    'open': prev_candle['open'],
                    'high': prev_candle['high'],
                    'low': prev_candle['low'],
                    'close': prev_candle['close'],
                    'volume': prev_candle['volume']
                },
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume']
                }
            },
            'confidence_breakdown': {
                'body_ratio': body_score,
                'volume': volume_score,
                'trend': trend_score,
                'position': position_score,
                'regime': regime_score
            }
        }

    def _detect_hammer(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Hammer: Bullish reversal pattern (long lower wick, small body at top)

        Rules:
        1. Lower wick >= 2x body size
        2. Upper wick <= 0.3x body size (small or none)
        3. Body should be in upper 1/3 of candle range
        4. Appears after downtrend

        Confidence Scoring (0-10):
        - Wick-to-body ratio (0-2.5)
        - Body position (0-2.0)
        - Volume confirmation (0-2.0)
        - Previous downtrend (0-2.5)
        - Market regime bonus (0-1.0)

        Returns:
            Pattern details dict or None
        """
        if len(candles) < 10:
            return None

        curr_candle = candles[-1]

        # Calculate body and wicks
        body_top = max(curr_candle['open'], curr_candle['close'])
        body_bottom = min(curr_candle['open'], curr_candle['close'])
        body_size = abs(curr_candle['close'] - curr_candle['open'])

        lower_wick = body_bottom - curr_candle['low']
        upper_wick = curr_candle['high'] - body_top
        total_range = curr_candle['high'] - curr_candle['low']

        # Avoid tiny candles (noise)
        if total_range < curr_candle['close'] * 0.002:  # <0.2% range
            return None

        # Rule 1: Lower wick >= 2x body
        if lower_wick < body_size * 2.0:
            return None

        # Rule 2: Upper wick <= 0.3x body (very small)
        if upper_wick > body_size * 0.3:
            return None

        # Rule 3: Body in upper 1/3 of range
        body_mid = (body_top + body_bottom) / 2
        range_position = (body_mid - curr_candle['low']) / total_range

        if range_position < 0.67:  # Body not in upper third
            return None

        # Confidence scoring

        # 1. Wick-to-body ratio (0-2.5)
        if body_size == 0:
            wick_ratio = 10  # Doji with long wick
        else:
            wick_ratio = lower_wick / body_size

        if wick_ratio >= 3.0:
            wick_score = 2.5
        elif wick_ratio >= 2.5:
            wick_score = 2.0
        elif wick_ratio >= 2.0:
            wick_score = 1.5
        else:
            wick_score = 1.0

        # 2. Body position in range (0-2.0)
        if range_position >= 0.80:
            position_score = 2.0
        elif range_position >= 0.67:
            position_score = 1.5
        else:
            position_score = 1.0

        # 3. Volume confirmation (0-2.0)
        current_volume = curr_candle['volume']
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        if volume_ratio >= 1.5:
            volume_score = 2.0
        elif volume_ratio >= 1.2:
            volume_score = 1.5
        else:
            volume_score = 1.0

        # 4. Previous downtrend (0-2.5)
        lookback = min(8, len(candles) - 1)
        start_candle = candles[-lookback-1]
        trend_change = ((curr_candle['close'] - start_candle['close']) /
                        start_candle['close'] * 100)

        if trend_change <= -2.0:
            trend_score = 2.5
        elif trend_change <= -1.0:
            trend_score = 2.0
        elif trend_change <= -0.5:
            trend_score = 1.5
        else:
            trend_score = 1.0

        # 5. Market regime (0-1.0)
        if market_regime == 'BULLISH':
            regime_score = 1.0
        elif market_regime == 'NEUTRAL':
            regime_score = 0.5
        else:
            regime_score = 0.0

        # Total confidence
        confidence = wick_score + position_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = curr_candle['high'] * 1.002  # Above high
        target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['low'] * 0.997  # Pattern-based stop (below low)

        return {
            'pattern_name': 'Hammer',
            'type': 'bullish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Hammer ({wick_ratio:.1f}x wick) after {abs(trend_change):.1f}% decline',
            'candle_data': {
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume'],
                    'lower_wick': lower_wick,
                    'upper_wick': upper_wick,
                    'body_size': body_size
                }
            },
            'confidence_breakdown': {
                'wick_ratio': wick_score,
                'position': position_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_shooting_star(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Shooting Star: Bearish reversal pattern (long upper wick, small body at bottom)

        Rules:
        1. Upper wick >= 2x body size
        2. Lower wick <= 0.3x body size (small or none)
        3. Body should be in lower 1/3 of candle range
        4. Appears after uptrend

        Returns:
            Pattern details dict or None
        """
        if len(candles) < 10:
            return None

        curr_candle = candles[-1]

        # Calculate body and wicks
        body_top = max(curr_candle['open'], curr_candle['close'])
        body_bottom = min(curr_candle['open'], curr_candle['close'])
        body_size = abs(curr_candle['close'] - curr_candle['open'])

        upper_wick = curr_candle['high'] - body_top
        lower_wick = body_bottom - curr_candle['low']
        total_range = curr_candle['high'] - curr_candle['low']

        # Avoid tiny candles
        if total_range < curr_candle['close'] * 0.002:
            return None

        # Rule 1: Upper wick >= 2x body
        if upper_wick < body_size * 2.0:
            return None

        # Rule 2: Lower wick <= 0.3x body
        if lower_wick > body_size * 0.3:
            return None

        # Rule 3: Body in lower 1/3 of range
        body_mid = (body_top + body_bottom) / 2
        range_position = (body_mid - curr_candle['low']) / total_range

        if range_position > 0.33:
            return None

        # Confidence scoring

        # 1. Wick-to-body ratio
        if body_size == 0:
            wick_ratio = 10
        else:
            wick_ratio = upper_wick / body_size

        if wick_ratio >= 3.0:
            wick_score = 2.5
        elif wick_ratio >= 2.5:
            wick_score = 2.0
        elif wick_ratio >= 2.0:
            wick_score = 1.5
        else:
            wick_score = 1.0

        # 2. Body position
        if range_position <= 0.20:
            position_score = 2.0
        elif range_position <= 0.33:
            position_score = 1.5
        else:
            position_score = 1.0

        # 3. Volume
        current_volume = curr_candle['volume']
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        if volume_ratio >= 1.5:
            volume_score = 2.0
        elif volume_ratio >= 1.2:
            volume_score = 1.5
        else:
            volume_score = 1.0

        # 4. Previous uptrend
        lookback = min(8, len(candles) - 1)
        start_candle = candles[-lookback-1]
        trend_change = ((curr_candle['close'] - start_candle['close']) /
                        start_candle['close'] * 100)

        if trend_change >= 2.0:
            trend_score = 2.5
        elif trend_change >= 1.0:
            trend_score = 2.0
        elif trend_change >= 0.5:
            trend_score = 1.5
        else:
            trend_score = 1.0

        # 5. Market regime
        if market_regime == 'BEARISH':
            regime_score = 1.0
        elif market_regime == 'NEUTRAL':
            regime_score = 0.5
        else:
            regime_score = 0.0

        # Total confidence
        confidence = wick_score + position_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop (bearish) using ATR
        entry_price = curr_candle['low'] * 0.998
        target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['high'] * 1.003  # Pattern-based stop (above high)

        return {
            'pattern_name': 'Shooting Star',
            'type': 'bearish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Shooting Star ({wick_ratio:.1f}x wick) after {trend_change:.1f}% rise',
            'candle_data': {
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume'],
                    'upper_wick': upper_wick,
                    'lower_wick': lower_wick,
                    'body_size': body_size
                }
            },
            'confidence_breakdown': {
                'wick_ratio': wick_score,
                'position': position_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_doji(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Doji: Indecision pattern (open ≈ close, small body, long wicks)

        Rules:
        1. Body size <= 0.1% of candle range (essentially no body)
        2. Total range >= 0.3% of price (not a flat line)
        3. Wicks on both sides present

        Signal interpretation:
        - After uptrend: Potential bearish reversal
        - After downtrend: Potential bullish reversal
        - Mid-trend: Continuation or consolidation

        Returns:
            Pattern details dict or None
        """
        if len(candles) < 8:
            return None

        curr_candle = candles[-1]

        # Calculate components
        body_size = abs(curr_candle['close'] - curr_candle['open'])
        total_range = curr_candle['high'] - curr_candle['low']

        # Rule 1: Very small body (<0.1% of range)
        if total_range == 0:
            return None

        body_to_range_ratio = body_size / total_range

        if body_to_range_ratio > 0.1:  # Body too large
            return None

        # Rule 2: Minimum range (not a flat line)
        min_range = curr_candle['close'] * 0.003  # 0.3% of price
        if total_range < min_range:
            return None

        # Rule 3: Wicks present
        body_top = max(curr_candle['open'], curr_candle['close'])
        body_bottom = min(curr_candle['open'], curr_candle['close'])
        upper_wick = curr_candle['high'] - body_top
        lower_wick = body_bottom - curr_candle['low']

        if upper_wick < total_range * 0.1 or lower_wick < total_range * 0.1:
            return None  # Need wicks on both sides

        # Determine signal type based on trend context
        lookback = min(10, len(candles) - 1)
        start_candle = candles[-lookback-1]
        trend_change = ((curr_candle['close'] - start_candle['close']) /
                        start_candle['close'] * 100)

        if trend_change >= 1.5:
            signal_type = 'bearish'  # Doji after uptrend
            pattern_description = f'Doji after {trend_change:.1f}% uptrend (potential reversal down)'
        elif trend_change <= -1.5:
            signal_type = 'bullish'  # Doji after downtrend
            pattern_description = f'Doji after {abs(trend_change):.1f}% downtrend (potential reversal up)'
        else:
            signal_type = 'neutral'  # Doji in consolidation
            pattern_description = 'Doji in sideways market (indecision)'

        # Confidence scoring

        # 1. Body smallness (0-2.0)
        if body_to_range_ratio <= 0.05:
            body_score = 2.0
        elif body_to_range_ratio <= 0.1:
            body_score = 1.5
        else:
            body_score = 1.0

        # 2. Wick balance (0-2.0)
        if lower_wick == 0:
            wick_ratio = 999
        else:
            wick_ratio = upper_wick / lower_wick

        if 0.8 <= wick_ratio <= 1.2:
            wick_balance_score = 2.0
        elif 0.6 <= wick_ratio <= 1.4:
            wick_balance_score = 1.5
        else:
            wick_balance_score = 1.0

        # 3. Volume confirmation (0-2.0)
        current_volume = curr_candle['volume']
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        if volume_ratio >= 1.5:
            volume_score = 2.0
        elif volume_ratio >= 1.2:
            volume_score = 1.5
        else:
            volume_score = 1.0

        # 4. Trend strength (0-3.0)
        if abs(trend_change) >= 3.0:
            trend_score = 3.0  # Strong trend reversal
        elif abs(trend_change) >= 1.5:
            trend_score = 2.5
        elif abs(trend_change) >= 0.5:
            trend_score = 2.0
        else:
            trend_score = 1.0

        # 5. Market regime (0-1.0)
        if signal_type == 'bullish' and market_regime == 'BULLISH':
            regime_score = 1.0
        elif signal_type == 'bearish' and market_regime == 'BEARISH':
            regime_score = 1.0
        elif market_regime == 'NEUTRAL':
            regime_score = 0.5
        else:
            regime_score = 0.0

        # Total confidence
        confidence = body_score + wick_balance_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop (depends on signal type) using ATR
        if signal_type == 'bullish':
            entry_price = curr_candle['high'] * 1.002
            target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based
            stop_loss = curr_candle['low'] * 0.997  # Pattern-based stop (below low)
        elif signal_type == 'bearish':
            entry_price = curr_candle['low'] * 0.998
            target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based
            stop_loss = curr_candle['high'] * 1.003  # Pattern-based stop (above high)
        else:
            # Neutral - wait for breakout
            entry_price = curr_candle['close']
            target = None
            stop_loss = None

        return {
            'pattern_name': 'Doji',
            'type': signal_type,
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': pattern_description,
            'candle_data': {
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume'],
                    'upper_wick': upper_wick,
                    'lower_wick': lower_wick,
                    'body_size': body_size,
                    'wick_balance': wick_ratio
                }
            },
            'confidence_breakdown': {
                'body_purity': body_score,
                'wick_balance': wick_balance_score,
                'volume': volume_score,
                'trend_strength': trend_score,
                'regime': regime_score
            }
        }

    def _detect_inverted_hammer(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Inverted Hammer: Bullish reversal (long upper wick, small body at bottom)
        Similar to Shooting Star but appears after downtrend (bullish reversal)
        """
        if len(candles) < 10:
            return None

        curr_candle = candles[-1]

        body_top = max(curr_candle['open'], curr_candle['close'])
        body_bottom = min(curr_candle['open'], curr_candle['close'])
        body_size = abs(curr_candle['close'] - curr_candle['open'])
        upper_wick = curr_candle['high'] - body_top
        lower_wick = body_bottom - curr_candle['low']
        total_range = curr_candle['high'] - curr_candle['low']

        if total_range < curr_candle['close'] * 0.002:
            return None

        # Upper wick >= 2x body
        if upper_wick < body_size * 2.0:
            return None

        # Lower wick <= 0.3x body
        if lower_wick > body_size * 0.3:
            return None

        # Body in lower 1/3
        body_mid = (body_top + body_bottom) / 2
        range_position = (body_mid - curr_candle['low']) / total_range
        if range_position > 0.33:
            return None

        # Must appear after downtrend
        lookback = min(8, len(candles) - 1)
        start_candle = candles[-lookback-1]
        trend_change = ((curr_candle['close'] - start_candle['close']) / start_candle['close'] * 100)

        if trend_change >= 0:  # Not after downtrend
            return None

        # Confidence scoring
        wick_ratio = upper_wick / body_size if body_size > 0 else 10
        wick_score = 2.5 if wick_ratio >= 3.0 else 2.0 if wick_ratio >= 2.5 else 1.5

        position_score = 2.0 if range_position <= 0.20 else 1.5

        volume_ratio = curr_candle['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.0 if volume_ratio >= 1.5 else 1.5 if volume_ratio >= 1.2 else 1.0

        trend_score = 2.5 if trend_change <= -2.0 else 2.0 if trend_change <= -1.0 else 1.5

        regime_score = 1.0 if market_regime == 'BULLISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = wick_score + position_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        
        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = curr_candle['high'] * 1.002
        target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['low'] * 0.997  # Pattern-based stop (below low)

        return {
            'pattern_name': 'Inverted Hammer',
            'type': 'bullish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Inverted Hammer ({wick_ratio:.1f}x wick) after {abs(trend_change):.1f}% decline',
            'candle_data': {
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume'],
                    'upper_wick': upper_wick,
                    'lower_wick': lower_wick,
                    'body_size': body_size
                }
            },
            'confidence_breakdown': {
                'wick_ratio': wick_score,
                'position': position_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_hanging_man(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Hanging Man: Bearish reversal (long lower wick, small body at top)
        Similar to Hammer but appears after uptrend (bearish reversal)
        """
        if len(candles) < 10:
            return None

        curr_candle = candles[-1]

        body_top = max(curr_candle['open'], curr_candle['close'])
        body_bottom = min(curr_candle['open'], curr_candle['close'])
        body_size = abs(curr_candle['close'] - curr_candle['open'])
        lower_wick = body_bottom - curr_candle['low']
        upper_wick = curr_candle['high'] - body_top
        total_range = curr_candle['high'] - curr_candle['low']

        if total_range < curr_candle['close'] * 0.002:
            return None

        # Lower wick >= 2x body
        if lower_wick < body_size * 2.0:
            return None

        # Upper wick <= 0.3x body
        if upper_wick > body_size * 0.3:
            return None

        # Body in upper 1/3
        body_mid = (body_top + body_bottom) / 2
        range_position = (body_mid - curr_candle['low']) / total_range
        if range_position < 0.67:
            return None

        # Must appear after uptrend
        lookback = min(8, len(candles) - 1)
        start_candle = candles[-lookback-1]
        trend_change = ((curr_candle['close'] - start_candle['close']) / start_candle['close'] * 100)

        if trend_change <= 0:  # Not after uptrend
            return None

        # Confidence scoring
        wick_ratio = lower_wick / body_size if body_size > 0 else 10
        wick_score = 2.5 if wick_ratio >= 3.0 else 2.0 if wick_ratio >= 2.5 else 1.5

        position_score = 2.0 if range_position >= 0.80 else 1.5

        volume_ratio = curr_candle['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.0 if volume_ratio >= 1.5 else 1.5 if volume_ratio >= 1.2 else 1.0

        trend_score = 2.5 if trend_change >= 2.0 else 2.0 if trend_change >= 1.0 else 1.5

        regime_score = 1.0 if market_regime == 'BEARISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = wick_score + position_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        
        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = curr_candle['low'] * 0.998
        target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['high'] * 1.003  # Pattern-based stop (above high)

        return {
            'pattern_name': 'Hanging Man',
            'type': 'bearish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Hanging Man ({wick_ratio:.1f}x wick) after {trend_change:.1f}% rise',
            'candle_data': {
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume'],
                    'lower_wick': lower_wick,
                    'upper_wick': upper_wick,
                    'body_size': body_size
                }
            },
            'confidence_breakdown': {
                'wick_ratio': wick_score,
                'position': position_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    # ============================================
    # MULTI-CANDLE REVERSAL PATTERNS
    # ============================================

    def _detect_morning_star(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Morning Star: 3-candle bullish reversal pattern

        Rules:
        1. Candle 1: Long bearish candle
        2. Candle 2: Small body (star), gaps down
        3. Candle 3: Long bullish candle, closes well into candle 1's body
        """
        if len(candles) < 12:
            return None

        c1 = candles[-3]  # First bearish candle
        c2 = candles[-2]  # Star (small body)
        c3 = candles[-1]  # Third bullish candle

        # Candle 1: Bearish
        if c1['close'] >= c1['open']:
            return None

        c1_body = abs(c1['close'] - c1['open'])
        c2_body = abs(c2['close'] - c2['open'])
        c3_body = abs(c3['close'] - c3['open'])

        # Candle 1 should be substantial
        c1_range = c1['high'] - c1['low']
        if c1_body < c1_range * 0.6:  # Body >= 60% of range
            return None

        # Candle 2: Small body (star)
        c2_range = c2['high'] - c2['low']
        if c2_range == 0:
            return None
        if c2_body > c1_body * 0.3:  # Star body < 30% of first candle
            return None

        # Candle 3: Bullish
        if c3['close'] <= c3['open']:
            return None

        # Candle 3 should close well into candle 1's body
        c1_mid = (c1['open'] + c1['close']) / 2
        if c3['close'] < c1_mid:
            return None

        # Check downtrend before pattern
        lookback = min(10, len(candles) - 3)
        start_candle = candles[-lookback-3]
        trend_change = ((c1['close'] - start_candle['close']) / start_candle['close'] * 100)

        # Confidence scoring
        penetration = (c3['close'] - c1['close']) / c1_body
        penetration_score = 2.5 if penetration >= 0.7 else 2.0 if penetration >= 0.5 else 1.5

        star_size = c2_body / c1_body
        star_score = 2.0 if star_size <= 0.15 else 1.5 if star_size <= 0.25 else 1.0

        volume_ratio = c3['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.5 if volume_ratio >= 2.0 else 2.0 if volume_ratio >= 1.5 else 1.0

        trend_score = 2.0 if trend_change <= -2.0 else 1.5 if trend_change <= -1.0 else 1.0

        regime_score = 1.0 if market_regime == 'BULLISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = penetration_score + star_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = c3['close'] * 1.001
        target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = c2['low'] * 0.997  # Pattern-based stop (below middle candle low)
        stop_loss = c2['low'] * 0.997

        return {
            'pattern_name': 'Morning Star',
            'type': 'bullish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Morning Star (3-candle) after {abs(trend_change):.1f}% decline',
            'candle_data': {
                'curr_candle': {
                    'open': c3['open'],
                    'high': c3['high'],
                    'low': c3['low'],
                    'close': c3['close'],
                    'volume': c3['volume']
                },
                'prev_candle': {
                    'open': c1['open'],
                    'high': c1['high'],
                    'low': c1['low'],
                    'close': c1['close'],
                    'volume': c1['volume']
                }
            },
            'confidence_breakdown': {
                'penetration': penetration_score,
                'star_size': star_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_evening_star(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Evening Star: 3-candle bearish reversal pattern

        Rules:
        1. Candle 1: Long bullish candle
        2. Candle 2: Small body (star), gaps up
        3. Candle 3: Long bearish candle, closes well into candle 1's body
        """
        if len(candles) < 12:
            return None

        c1 = candles[-3]
        c2 = candles[-2]
        c3 = candles[-1]

        # Candle 1: Bullish
        if c1['close'] <= c1['open']:
            return None

        c1_body = abs(c1['close'] - c1['open'])
        c2_body = abs(c2['close'] - c2['open'])
        c3_body = abs(c3['close'] - c3['open'])

        c1_range = c1['high'] - c1['low']
        if c1_body < c1_range * 0.6:
            return None

        # Candle 2: Small body
        c2_range = c2['high'] - c2['low']
        if c2_range == 0:
            return None
        if c2_body > c1_body * 0.3:
            return None

        # Candle 3: Bearish
        if c3['close'] >= c3['open']:
            return None

        # Candle 3 closes well into candle 1's body
        c1_mid = (c1['open'] + c1['close']) / 2
        if c3['close'] > c1_mid:
            return None

        # Check uptrend
        lookback = min(10, len(candles) - 3)
        start_candle = candles[-lookback-3]
        trend_change = ((c1['close'] - start_candle['close']) / start_candle['close'] * 100)

        # Confidence scoring
        penetration = (c1['close'] - c3['close']) / c1_body
        penetration_score = 2.5 if penetration >= 0.7 else 2.0 if penetration >= 0.5 else 1.5

        star_size = c2_body / c1_body
        star_score = 2.0 if star_size <= 0.15 else 1.5 if star_size <= 0.25 else 1.0

        volume_ratio = c3['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.5 if volume_ratio >= 2.0 else 2.0 if volume_ratio >= 1.5 else 1.0

        trend_score = 2.0 if trend_change >= 2.0 else 1.5 if trend_change >= 1.0 else 1.0

        regime_score = 1.0 if market_regime == 'BEARISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = penetration_score + star_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = c3['close'] * 0.999
        target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = c2['high'] * 1.003  # Pattern-based stop (above middle candle high)
        stop_loss = c2['high'] * 1.003

        return {
            'pattern_name': 'Evening Star',
            'type': 'bearish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Evening Star (3-candle) after {trend_change:.1f}% rise',
            'candle_data': {
                'curr_candle': {
                    'open': c3['open'],
                    'high': c3['high'],
                    'low': c3['low'],
                    'close': c3['close'],
                    'volume': c3['volume']
                },
                'prev_candle': {
                    'open': c1['open'],
                    'high': c1['high'],
                    'low': c1['low'],
                    'close': c1['close'],
                    'volume': c1['volume']
                }
            },
            'confidence_breakdown': {
                'penetration': penetration_score,
                'star_size': star_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_piercing_pattern(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Piercing Pattern: 2-candle bullish reversal

        Rules:
        1. Candle 1: Long bearish candle
        2. Candle 2: Bullish candle opens below prev low, closes above prev midpoint
        """
        if len(candles) < 10:
            return None

        c1 = candles[-2]
        c2 = candles[-1]

        # Candle 1: Bearish
        if c1['close'] >= c1['open']:
            return None

        c1_body = abs(c1['close'] - c1['open'])

        # Candle 2: Bullish
        if c2['close'] <= c2['open']:
            return None

        # Candle 2 opens below candle 1 low
        if c2['open'] >= c1['low']:
            return None

        # Candle 2 closes above candle 1 midpoint
        c1_mid = (c1['open'] + c1['close']) / 2
        if c2['close'] <= c1_mid:
            return None

        # Check downtrend
        lookback = min(10, len(candles) - 2)
        start_candle = candles[-lookback-2]
        trend_change = ((c1['close'] - start_candle['close']) / start_candle['close'] * 100)

        # Confidence scoring
        penetration = (c2['close'] - c1['close']) / c1_body
        penetration_score = 2.5 if penetration >= 0.7 else 2.0 if penetration >= 0.5 else 1.5

        gap_size = (c1['low'] - c2['open']) / c1['close'] * 100
        gap_score = 2.0 if gap_size >= 0.5 else 1.5 if gap_size >= 0.2 else 1.0

        volume_ratio = c2['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.5 if volume_ratio >= 2.0 else 2.0 if volume_ratio >= 1.5 else 1.0

        trend_score = 2.0 if trend_change <= -2.0 else 1.5 if trend_change <= -1.0 else 1.0

        regime_score = 1.0 if market_regime == 'BULLISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = penetration_score + gap_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        
        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = c2['close'] * 1.001
        target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['low'] * 0.997  # Pattern-based stop (below low)

        return {
            'pattern_name': 'Piercing Pattern',
            'type': 'bullish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Piercing Pattern ({penetration:.1%} penetration) after {abs(trend_change):.1f}% decline',
            'candle_data': {
                'prev_candle': {
                    'open': c1['open'],
                    'high': c1['high'],
                    'low': c1['low'],
                    'close': c1['close'],
                    'volume': c1['volume']
                },
                'curr_candle': {
                    'open': c2['open'],
                    'high': c2['high'],
                    'low': c2['low'],
                    'close': c2['close'],
                    'volume': c2['volume']
                }
            },
            'confidence_breakdown': {
                'penetration': penetration_score,
                'gap': gap_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_dark_cloud_cover(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Dark Cloud Cover: 2-candle bearish reversal

        Rules:
        1. Candle 1: Long bullish candle
        2. Candle 2: Bearish candle opens above prev high, closes below prev midpoint
        """
        if len(candles) < 10:
            return None

        c1 = candles[-2]
        c2 = candles[-1]

        # Candle 1: Bullish
        if c1['close'] <= c1['open']:
            return None

        c1_body = abs(c1['close'] - c1['open'])

        # Candle 2: Bearish
        if c2['close'] >= c2['open']:
            return None

        # Candle 2 opens above candle 1 high
        if c2['open'] <= c1['high']:
            return None

        # Candle 2 closes below candle 1 midpoint
        c1_mid = (c1['open'] + c1['close']) / 2
        if c2['close'] >= c1_mid:
            return None

        # Check uptrend
        lookback = min(10, len(candles) - 2)
        start_candle = candles[-lookback-2]
        trend_change = ((c1['close'] - start_candle['close']) / start_candle['close'] * 100)

        # Confidence scoring
        penetration = (c1['close'] - c2['close']) / c1_body
        penetration_score = 2.5 if penetration >= 0.7 else 2.0 if penetration >= 0.5 else 1.5

        gap_size = (c2['open'] - c1['high']) / c1['close'] * 100
        gap_score = 2.0 if gap_size >= 0.5 else 1.5 if gap_size >= 0.2 else 1.0

        volume_ratio = c2['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.5 if volume_ratio >= 2.0 else 2.0 if volume_ratio >= 1.5 else 1.0

        trend_score = 2.0 if trend_change >= 2.0 else 1.5 if trend_change >= 1.0 else 1.0

        regime_score = 1.0 if market_regime == 'BEARISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = penetration_score + gap_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        
        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = c2['close'] * 0.999
        target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['high'] * 1.003  # Pattern-based stop (above high)

        return {
            'pattern_name': 'Dark Cloud Cover',
            'type': 'bearish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Dark Cloud Cover ({penetration:.1%} penetration) after {trend_change:.1f}% rise',
            'candle_data': {
                'prev_candle': {
                    'open': c1['open'],
                    'high': c1['high'],
                    'low': c1['low'],
                    'close': c1['close'],
                    'volume': c1['volume']
                },
                'curr_candle': {
                    'open': c2['open'],
                    'high': c2['high'],
                    'low': c2['low'],
                    'close': c2['close'],
                    'volume': c2['volume']
                }
            },
            'confidence_breakdown': {
                'penetration': penetration_score,
                'gap': gap_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    # ============================================
    # INDECISION PATTERNS (Additional)
    # ============================================

    def _detect_spinning_top(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Spinning Top: Indecision pattern with small body and long wicks on both sides
        """
        if len(candles) < 8:
            return None

        curr_candle = candles[-1]

        body_size = abs(curr_candle['close'] - curr_candle['open'])
        total_range = curr_candle['high'] - curr_candle['low']

        if total_range == 0:
            return None

        # Small body (10-30% of range)
        body_ratio = body_size / total_range
        if body_ratio < 0.1 or body_ratio > 0.3:
            return None

        # Long wicks on both sides
        body_top = max(curr_candle['open'], curr_candle['close'])
        body_bottom = min(curr_candle['open'], curr_candle['close'])
        upper_wick = curr_candle['high'] - body_top
        lower_wick = body_bottom - curr_candle['low']

        # Both wicks should be substantial
        if upper_wick < body_size or lower_wick < body_size:
            return None

        # Trend context
        lookback = min(10, len(candles) - 1)
        start_candle = candles[-lookback-1]
        trend_change = ((curr_candle['close'] - start_candle['close']) / start_candle['close'] * 100)

        if abs(trend_change) >= 1.5:
            signal_type = 'bearish' if trend_change > 0 else 'bullish'
            pattern_desc = f'Spinning Top after {abs(trend_change):.1f}% {"rise" if trend_change > 0 else "decline"} (potential reversal)'
        else:
            signal_type = 'neutral'
            pattern_desc = 'Spinning Top in consolidation (indecision)'

        # Confidence
        body_score = 2.0 if 0.15 <= body_ratio <= 0.25 else 1.5

        wick_balance = upper_wick / lower_wick if lower_wick > 0 else 999
        wick_score = 2.0 if 0.7 <= wick_balance <= 1.3 else 1.5

        volume_ratio = curr_candle['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.0 if volume_ratio >= 1.5 else 1.5 if volume_ratio >= 1.2 else 1.0

        trend_score = 2.5 if abs(trend_change) >= 2.0 else 2.0 if abs(trend_change) >= 1.0 else 1.0

        if signal_type == 'bullish' and market_regime == 'BULLISH':
            regime_score = 1.0
        elif signal_type == 'bearish' and market_regime == 'BEARISH':
            regime_score = 1.0
        else:
            regime_score = 0.5

        confidence = body_score + wick_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        if signal_type == 'bullish':
            entry_price = curr_candle['high'] * 1.002
            target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based
            stop_loss = curr_candle['low'] * 0.997  # Pattern-based stop (below low)
        elif signal_type == 'bearish':
            entry_price = curr_candle['low'] * 0.998
            target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based
            stop_loss = curr_candle['high'] * 1.003  # Pattern-based stop (above high)
        else:
            entry_price = curr_candle['close']
            target = None
            stop_loss = None

        return {
            'pattern_name': 'Spinning Top',
            'type': signal_type,
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': pattern_desc,
            'candle_data': {
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume'],
                    'upper_wick': upper_wick,
                    'lower_wick': lower_wick,
                    'body_size': body_size
                }
            },
            'confidence_breakdown': {
                'body_size': body_score,
                'wick_balance': wick_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_long_legged_doji(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Long-Legged Doji: Strong indecision with very long wicks and tiny body
        """
        if len(candles) < 8:
            return None

        curr_candle = candles[-1]

        body_size = abs(curr_candle['close'] - curr_candle['open'])
        total_range = curr_candle['high'] - curr_candle['low']

        if total_range == 0:
            return None

        # Very small body (<5% of range)
        body_ratio = body_size / total_range
        if body_ratio > 0.05:
            return None

        # Both wicks must be very long
        body_top = max(curr_candle['open'], curr_candle['close'])
        body_bottom = min(curr_candle['open'], curr_candle['close'])
        upper_wick = curr_candle['high'] - body_top
        lower_wick = body_bottom - curr_candle['low']

        # Each wick >= 40% of range
        if upper_wick < total_range * 0.4 or lower_wick < total_range * 0.4:
            return None

        # Trend context
        lookback = min(10, len(candles) - 1)
        start_candle = candles[-lookback-1]
        trend_change = ((curr_candle['close'] - start_candle['close']) / start_candle['close'] * 100)

        if trend_change >= 2.0:
            signal_type = 'bearish'
            pattern_desc = f'Long-Legged Doji after {trend_change:.1f}% rise (strong reversal signal)'
        elif trend_change <= -2.0:
            signal_type = 'bullish'
            pattern_desc = f'Long-Legged Doji after {abs(trend_change):.1f}% decline (strong reversal signal)'
        else:
            signal_type = 'neutral'
            pattern_desc = 'Long-Legged Doji (extreme indecision)'

        # Confidence
        body_score = 2.5 if body_ratio <= 0.03 else 2.0

        wick_balance = upper_wick / lower_wick if lower_wick > 0 else 999
        wick_score = 2.0 if 0.8 <= wick_balance <= 1.2 else 1.5

        volume_ratio = curr_candle['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.5 if volume_ratio >= 2.0 else 2.0 if volume_ratio >= 1.5 else 1.5

        trend_score = 3.0 if abs(trend_change) >= 3.0 else 2.5 if abs(trend_change) >= 2.0 else 1.5

        if signal_type == 'bullish' and market_regime == 'BULLISH':
            regime_score = 1.0
        elif signal_type == 'bearish' and market_regime == 'BEARISH':
            regime_score = 1.0
        else:
            regime_score = 0.5

        confidence = body_score + wick_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR (use higher multiplier for Long-Legged Doji)
        if signal_type == 'bullish':
            entry_price = curr_candle['high'] * 1.002
            target = entry_price + (atr * self.atr_target_multiplier * 1.5)  # 1.5x for strong signal
            stop_loss = curr_candle['low'] * 0.997  # Pattern-based stop (below low)
        elif signal_type == 'bearish':
            entry_price = curr_candle['low'] * 0.998
            target = entry_price - (atr * self.atr_target_multiplier * 1.5)  # 1.5x for strong signal
            stop_loss = curr_candle['high'] * 1.003  # Pattern-based stop (above high)
        else:
            entry_price = curr_candle['close']
            target = None
            stop_loss = None

        return {
            'pattern_name': 'Long-Legged Doji',
            'type': signal_type,
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': pattern_desc,
            'candle_data': {
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume'],
                    'upper_wick': upper_wick,
                    'lower_wick': lower_wick,
                    'body_size': body_size
                }
            },
            'confidence_breakdown': {
                'body_purity': body_score,
                'wick_balance': wick_score,
                'volume': volume_score,
                'trend_strength': trend_score,
                'regime': regime_score
            }
        }

    # ============================================
    # CONTINUATION PATTERNS
    # ============================================

    def _detect_bullish_marubozu(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Bullish Marubozu: Strong bullish continuation (no wicks, long bullish body)
        """
        if len(candles) < 8:
            return None

        curr_candle = candles[-1]

        # Bullish candle
        if curr_candle['close'] <= curr_candle['open']:
            return None

        body_size = abs(curr_candle['close'] - curr_candle['open'])
        total_range = curr_candle['high'] - curr_candle['low']

        if total_range == 0:
            return None

        # Body should be >= 95% of range (minimal wicks)
        body_ratio = body_size / total_range
        if body_ratio < 0.95:
            return None

        # Check uptrend
        lookback = min(8, len(candles) - 1)
        start_candle = candles[-lookback-1]
        trend_change = ((curr_candle['close'] - start_candle['close']) / start_candle['close'] * 100)

        # Confidence
        body_score = 2.5 if body_ratio >= 0.98 else 2.0

        candle_size = total_range / curr_candle['close'] * 100
        size_score = 2.5 if candle_size >= 2.0 else 2.0 if candle_size >= 1.0 else 1.5

        volume_ratio = curr_candle['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.5 if volume_ratio >= 2.0 else 2.0 if volume_ratio >= 1.5 else 1.5

        trend_score = 2.0 if trend_change >= 1.0 else 1.5 if trend_change >= 0.5 else 1.0

        regime_score = 1.0 if market_regime == 'BULLISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = body_score + size_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        
        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = curr_candle['close'] * 1.001
        target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['low'] * 0.997  # Pattern-based stop (below low)

        return {
            'pattern_name': 'Bullish Marubozu',
            'type': 'bullish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Bullish Marubozu ({candle_size:.1f}% range) - strong continuation',
            'candle_data': {
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume'],
                    'body_size': body_size
                }
            },
            'confidence_breakdown': {
                'body_completeness': body_score,
                'candle_size': size_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_bearish_marubozu(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Bearish Marubozu: Strong bearish continuation (no wicks, long bearish body)
        """
        if len(candles) < 8:
            return None

        curr_candle = candles[-1]

        # Bearish candle
        if curr_candle['close'] >= curr_candle['open']:
            return None

        body_size = abs(curr_candle['close'] - curr_candle['open'])
        total_range = curr_candle['high'] - curr_candle['low']

        if total_range == 0:
            return None

        # Body >= 95% of range
        body_ratio = body_size / total_range
        if body_ratio < 0.95:
            return None

        # Check downtrend
        lookback = min(8, len(candles) - 1)
        start_candle = candles[-lookback-1]
        trend_change = ((curr_candle['close'] - start_candle['close']) / start_candle['close'] * 100)

        # Confidence
        body_score = 2.5 if body_ratio >= 0.98 else 2.0

        candle_size = total_range / curr_candle['close'] * 100
        size_score = 2.5 if candle_size >= 2.0 else 2.0 if candle_size >= 1.0 else 1.5

        volume_ratio = curr_candle['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.5 if volume_ratio >= 2.0 else 2.0 if volume_ratio >= 1.5 else 1.5

        trend_score = 2.0 if trend_change <= -1.0 else 1.5 if trend_change <= -0.5 else 1.0

        regime_score = 1.0 if market_regime == 'BEARISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = body_score + size_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        
        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = curr_candle['close'] * 0.999
        target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['open'] * 0.998  # Pattern-based stop (below open)

        return {
            'pattern_name': 'Bearish Marubozu',
            'type': 'bearish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Bearish Marubozu ({candle_size:.1f}% range) - strong continuation',
            'candle_data': {
                'curr_candle': {
                    'open': curr_candle['open'],
                    'high': curr_candle['high'],
                    'low': curr_candle['low'],
                    'close': curr_candle['close'],
                    'volume': curr_candle['volume'],
                    'body_size': body_size
                }
            },
            'confidence_breakdown': {
                'body_completeness': body_score,
                'candle_size': size_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_rising_three_methods(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Rising Three Methods: 5-candle bullish continuation pattern
        Long bullish, 3 small bearish consolidation, then long bullish
        """
        if len(candles) < 12:
            return None

        c1 = candles[-5]  # First long bullish
        c2 = candles[-4]  # Small consolidation
        c3 = candles[-3]  # Small consolidation
        c4 = candles[-2]  # Small consolidation
        c5 = candles[-1]  # Final long bullish

        # C1: Long bullish
        if c1['close'] <= c1['open']:
            return None

        c1_body = abs(c1['close'] - c1['open'])

        # C2-C4: Small bearish/consolidation within C1's range
        for c in [c2, c3, c4]:
            # Should be small
            if abs(c['close'] - c['open']) > c1_body * 0.4:
                return None
            # Should stay within C1's range
            if c['high'] > c1['high'] or c['low'] < c1['low']:
                return None

        # C5: Long bullish, closes above C1
        if c5['close'] <= c5['open']:
            return None
        if c5['close'] <= c1['close']:
            return None

        c5_body = abs(c5['close'] - c5['open'])

        # Confidence
        consolidation_size = max(abs(c['close'] - c['open']) for c in [c2, c3, c4])
        consolidation_score = 2.5 if consolidation_size < c1_body * 0.2 else 2.0 if consolidation_size < c1_body * 0.3 else 1.5

        breakout = (c5['close'] - c1['close']) / c1_body
        breakout_score = 2.5 if breakout >= 0.5 else 2.0 if breakout >= 0.3 else 1.5

        volume_ratio = c5['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.0 if volume_ratio >= 1.5 else 1.5 if volume_ratio >= 1.2 else 1.0

        # Check uptrend before pattern
        lookback = min(10, len(candles) - 5)
        start_candle = candles[-lookback-5]
        trend_change = ((c1['close'] - start_candle['close']) / start_candle['close'] * 100)
        trend_score = 2.0 if trend_change >= 1.5 else 1.5 if trend_change >= 0.5 else 1.0

        regime_score = 1.0 if market_regime == 'BULLISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = consolidation_score + breakout_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = c5['close'] * 1.001
        target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = curr_candle['open'] * 1.002  # Pattern-based stop (above open)
        stop_loss = min(c2['low'], c3['low'], c4['low']) * 0.997

        return {
            'pattern_name': 'Rising Three Methods',
            'type': 'bullish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Rising Three Methods (5-candle continuation) with {breakout:.1%} breakout',
            'candle_data': {
                'curr_candle': {
                    'open': c5['open'],
                    'high': c5['high'],
                    'low': c5['low'],
                    'close': c5['close'],
                    'volume': c5['volume']
                }
            },
            'confidence_breakdown': {
                'consolidation': consolidation_score,
                'breakout': breakout_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_falling_three_methods(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Falling Three Methods: 5-candle bearish continuation pattern
        Long bearish, 3 small bullish consolidation, then long bearish
        """
        if len(candles) < 12:
            return None

        c1 = candles[-5]
        c2 = candles[-4]
        c3 = candles[-3]
        c4 = candles[-2]
        c5 = candles[-1]

        # C1: Long bearish
        if c1['close'] >= c1['open']:
            return None

        c1_body = abs(c1['close'] - c1['open'])

        # C2-C4: Small bullish/consolidation within C1's range
        for c in [c2, c3, c4]:
            if abs(c['close'] - c['open']) > c1_body * 0.4:
                return None
            if c['high'] > c1['high'] or c['low'] < c1['low']:
                return None

        # C5: Long bearish, closes below C1
        if c5['close'] >= c5['open']:
            return None
        if c5['close'] >= c1['close']:
            return None

        c5_body = abs(c5['close'] - c5['open'])

        # Confidence
        consolidation_size = max(abs(c['close'] - c['open']) for c in [c2, c3, c4])
        consolidation_score = 2.5 if consolidation_size < c1_body * 0.2 else 2.0 if consolidation_size < c1_body * 0.3 else 1.5

        breakout = (c1['close'] - c5['close']) / c1_body
        breakout_score = 2.5 if breakout >= 0.5 else 2.0 if breakout >= 0.3 else 1.5

        volume_ratio = c5['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.0 if volume_ratio >= 1.5 else 1.5 if volume_ratio >= 1.2 else 1.0

        lookback = min(10, len(candles) - 5)
        start_candle = candles[-lookback-5]
        trend_change = ((c1['close'] - start_candle['close']) / start_candle['close'] * 100)
        trend_score = 2.0 if trend_change <= -1.5 else 1.5 if trend_change <= -0.5 else 1.0

        regime_score = 1.0 if market_regime == 'BEARISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = consolidation_score + breakout_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = c5['close'] * 0.999
        target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = min(c2['low'], c3['low'], c4['low']) * 0.997  # Pattern-based stop
        stop_loss = max(c2['high'], c3['high'], c4['high']) * 1.003

        return {
            'pattern_name': 'Falling Three Methods',
            'type': 'bearish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Falling Three Methods (5-candle continuation) with {breakout:.1%} breakdown',
            'candle_data': {
                'curr_candle': {
                    'open': c5['open'],
                    'high': c5['high'],
                    'low': c5['low'],
                    'close': c5['close'],
                    'volume': c5['volume']
                }
            },
            'confidence_breakdown': {
                'consolidation': consolidation_score,
                'breakout': breakout_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    # ============================================
    # MULTI-CANDLE FORMATIONS
    # ============================================

    def _detect_three_white_soldiers(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Three White Soldiers: 3 consecutive long bullish candles (strong bullish)
        """
        if len(candles) < 10:
            return None

        c1 = candles[-3]
        c2 = candles[-2]
        c3 = candles[-1]

        # All three must be bullish
        if c1['close'] <= c1['open'] or c2['close'] <= c2['open'] or c3['close'] <= c3['open']:
            return None

        # Each closes higher than previous
        if c2['close'] <= c1['close'] or c3['close'] <= c2['close']:
            return None

        # Each opens within previous body
        if c2['open'] < c1['open'] or c2['open'] > c1['close']:
            return None
        if c3['open'] < c2['open'] or c3['open'] > c2['close']:
            return None

        # All should have small wicks
        for c in [c1, c2, c3]:
            body = abs(c['close'] - c['open'])
            total_range = c['high'] - c['low']
            if total_range == 0:
                return None
            if body < total_range * 0.7:  # Body >= 70% of range
                return None

        # Confidence
        avg_body = (abs(c1['close'] - c1['open']) + abs(c2['close'] - c2['open']) + abs(c3['close'] - c3['open'])) / 3
        strength = (c3['close'] - c1['open']) / c1['open'] * 100
        strength_score = 2.5 if strength >= 3.0 else 2.0 if strength >= 2.0 else 1.5

        consistency = min(abs(c2['close'] - c2['open']), abs(c3['close'] - c3['open'])) / abs(c1['close'] - c1['open'])
        consistency_score = 2.5 if consistency >= 0.8 else 2.0 if consistency >= 0.6 else 1.5

        volume_ratio = c3['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.5 if volume_ratio >= 1.5 else 2.0 if volume_ratio >= 1.2 else 1.5

        # Check prior downtrend or consolidation
        lookback = min(10, len(candles) - 3)
        start_candle = candles[-lookback-3]
        trend_change = ((c1['open'] - start_candle['close']) / start_candle['close'] * 100)
        trend_score = 2.5 if trend_change <= -1.0 else 2.0 if trend_change <= 0 else 1.5

        regime_score = 1.0 if market_regime == 'BULLISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = strength_score + consistency_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = c3['close'] * 1.001
        target = entry_price + (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = max(c2['high'], c3['high'], c4['high']) * 1.003  # Pattern-based stop
        stop_loss = c1['low'] * 0.997

        return {
            'pattern_name': 'Three White Soldiers',
            'type': 'bullish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Three White Soldiers ({strength:.1f}% advance) - strong bullish',
            'candle_data': {
                'curr_candle': {
                    'open': c3['open'],
                    'high': c3['high'],
                    'low': c3['low'],
                    'close': c3['close'],
                    'volume': c3['volume']
                }
            },
            'confidence_breakdown': {
                'strength': strength_score,
                'consistency': consistency_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }

    def _detect_three_black_crows(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Three Black Crows: 3 consecutive long bearish candles (strong bearish)
        """
        if len(candles) < 10:
            return None

        c1 = candles[-3]
        c2 = candles[-2]
        c3 = candles[-1]

        # All three must be bearish
        if c1['close'] >= c1['open'] or c2['close'] >= c2['open'] or c3['close'] >= c3['open']:
            return None

        # Each closes lower than previous
        if c2['close'] >= c1['close'] or c3['close'] >= c2['close']:
            return None

        # Each opens within previous body
        if c2['open'] > c1['open'] or c2['open'] < c1['close']:
            return None
        if c3['open'] > c2['open'] or c3['open'] < c2['close']:
            return None

        # All should have small wicks
        for c in [c1, c2, c3]:
            body = abs(c['close'] - c['open'])
            total_range = c['high'] - c['low']
            if total_range == 0:
                return None
            if body < total_range * 0.7:
                return None

        # Confidence
        strength = (c1['open'] - c3['close']) / c1['open'] * 100
        strength_score = 2.5 if strength >= 3.0 else 2.0 if strength >= 2.0 else 1.5

        consistency = min(abs(c2['close'] - c2['open']), abs(c3['close'] - c3['open'])) / abs(c1['close'] - c1['open'])
        consistency_score = 2.5 if consistency >= 0.8 else 2.0 if consistency >= 0.6 else 1.5

        volume_ratio = c3['volume'] / avg_volume if avg_volume > 0 else 1.0
        volume_score = 2.5 if volume_ratio >= 1.5 else 2.0 if volume_ratio >= 1.2 else 1.5

        lookback = min(10, len(candles) - 3)
        start_candle = candles[-lookback-3]
        trend_change = ((c1['open'] - start_candle['close']) / start_candle['close'] * 100)
        trend_score = 2.5 if trend_change >= 1.0 else 2.0 if trend_change >= 0 else 1.5

        regime_score = 1.0 if market_regime == 'BEARISH' else 0.5 if market_regime == 'NEUTRAL' else 0.0

        confidence = strength_score + consistency_score + volume_score + trend_score + regime_score
        confidence = round(min(confidence, 10.0), 1)

        if confidence < self.min_confidence:
            return None

        # Calculate ATR for volatility-based targets/stops
        atr = self._calculate_atr(candles)

        # Entry/target/stop using ATR
        entry_price = c3['close'] * 0.999
        target = entry_price - (atr * self.atr_target_multiplier)  # ATR-based target
        stop_loss = c1['low'] * 0.997  # Pattern-based stop (below first candle low)
        stop_loss = c1['high'] * 1.003

        return {
            'pattern_name': 'Three Black Crows',
            'type': 'bearish',
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': f'Three Black Crows ({strength:.1f}% decline) - strong bearish',
            'candle_data': {
                'curr_candle': {
                    'open': c3['open'],
                    'high': c3['high'],
                    'low': c3['low'],
                    'close': c3['close'],
                    'volume': c3['volume']
                }
            },
            'confidence_breakdown': {
                'strength': strength_score,
                'consistency': consistency_score,
                'volume': volume_score,
                'trend': trend_score,
                'regime': regime_score
            }
        }
