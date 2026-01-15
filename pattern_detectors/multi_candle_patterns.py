"""
Multi-Candle Patterns

Candlestick pattern detectors for multi-candle patterns
"""

from typing import Dict, List, Optional
from .base_pattern import BasePatternDetector


class ThreeWhiteSoldiersDetector(BasePatternDetector):
    """
    Three White Soldiers Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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


class ThreeBlackCrowsDetector(BasePatternDetector):
    """
    Three Black Crows Pattern Detector
    """

    def detect(
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
        atr = self.calculate_atr(candles)

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
