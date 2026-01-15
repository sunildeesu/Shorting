"""
Continuation Patterns

Candlestick pattern detectors for continuation patterns
"""

from typing import Dict, List, Optional
from .base_pattern import BasePatternDetector


class BullishMarubozuDetector(BasePatternDetector):
    """
    Bullish Marubozu Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class BearishMarubozuDetector(BasePatternDetector):
    """
    Bearish Marubozu Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class RisingThreeMethodsDetector(BasePatternDetector):
    """
    Rising Three Methods Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class FallingThreeMethodsDetector(BasePatternDetector):
    """
    Falling Three Methods Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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
