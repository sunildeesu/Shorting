"""
Reversal Patterns

Candlestick pattern detectors for reversal patterns
"""

from typing import Dict, List, Optional
from .base_pattern import BasePatternDetector


class BullishEngulfingDetector(BasePatternDetector):
    """
    Bullish Engulfing Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class BearishEngulfingDetector(BasePatternDetector):
    """
    Bearish Engulfing Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class HammerDetector(BasePatternDetector):
    """
    Hammer Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class ShootingStarDetector(BasePatternDetector):
    """
    Shooting Star Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class InvertedHammerDetector(BasePatternDetector):
    """
    Inverted Hammer Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class HangingManDetector(BasePatternDetector):
    """
    Hanging Man Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class MorningStarDetector(BasePatternDetector):
    """
    Morning Star Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class EveningStarDetector(BasePatternDetector):
    """
    Evening Star Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class PiercingPatternDetector(BasePatternDetector):
    """
    Piercing Pattern Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class DarkCloudCoverDetector(BasePatternDetector):
    """
    Dark Cloud Cover Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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
