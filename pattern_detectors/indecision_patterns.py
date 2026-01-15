"""
Indecision Patterns

Candlestick pattern detectors for indecision patterns
"""

from typing import Dict, List, Optional
from .base_pattern import BasePatternDetector


class DojiDetector(BasePatternDetector):
    """
    Doji Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class SpinningTopDetector(BasePatternDetector):
    """
    Spinning Top Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class LongLeggedDojiDetector(BasePatternDetector):
    """
    Long-Legged Doji Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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
