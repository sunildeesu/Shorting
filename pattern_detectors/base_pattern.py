"""
Base Pattern Detector

Provides common functionality for all candlestick pattern detectors.
"""

from typing import Dict, List, Optional


class BasePatternDetector:
    """
    Base class for candlestick pattern detectors

    Provides shared functionality:
    - ATR calculation
    - Confidence scoring helpers
    - Standard return structure
    """

    def __init__(
        self,
        min_confidence: float,
        atr_period: int,
        atr_target_multiplier: float,
        atr_stop_multiplier: float
    ):
        """
        Initialize base detector

        Args:
            min_confidence: Minimum confidence score (0-10) to return pattern
            atr_period: Period for ATR calculation
            atr_target_multiplier: ATR multiplier for targets
            atr_stop_multiplier: ATR multiplier for stops
        """
        self.min_confidence = min_confidence
        self.atr_period = atr_period
        self.atr_target_multiplier = atr_target_multiplier
        self.atr_stop_multiplier = atr_stop_multiplier

    def calculate_atr(self, candles: List[Dict], period: int = None) -> float:
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

    def calculate_body_score(self, body_ratio: float) -> float:
        """
        Calculate confidence score based on body size ratio (0-2.5)

        Args:
            body_ratio: Ratio of current body to previous body

        Returns:
            Score from 0-2.5
        """
        if body_ratio >= 2.0:
            return 2.5
        elif body_ratio >= 1.5:
            return 2.0
        elif body_ratio >= 1.2:
            return 1.5
        else:
            return 1.0

    def calculate_volume_score(self, volume_ratio: float) -> float:
        """
        Calculate confidence score based on volume confirmation (0-2.5)

        Args:
            volume_ratio: Ratio of current volume to average volume

        Returns:
            Score from 0-2.5
        """
        if volume_ratio >= 2.0:
            return 2.5
        elif volume_ratio >= 1.5:
            return 2.0
        elif volume_ratio >= 1.2:
            return 1.5
        else:
            return 1.0

    def calculate_trend_score(self, trend_change: float, is_bullish_pattern: bool) -> float:
        """
        Calculate confidence score based on trend context (0-2.0)

        Args:
            trend_change: Percentage change over lookback period
            is_bullish_pattern: True for bullish patterns, False for bearish

        Returns:
            Score from 0-2.0
        """
        # For bullish patterns, we want to see a downtrend (negative trend_change)
        # For bearish patterns, we want to see an uptrend (positive trend_change)
        if is_bullish_pattern:
            if trend_change <= -3.0:
                return 2.0  # Strong downtrend
            elif trend_change <= -1.5:
                return 1.5  # Moderate downtrend
            elif trend_change <= -0.5:
                return 1.0  # Weak downtrend
            else:
                return 0.5  # Sideways/uptrend
        else:  # Bearish pattern
            if trend_change >= 3.0:
                return 2.0  # Strong uptrend
            elif trend_change >= 1.5:
                return 1.5  # Moderate uptrend
            elif trend_change >= 0.5:
                return 1.0  # Weak uptrend
            else:
                return 0.5  # Sideways/downtrend

    def calculate_position_score(self, current_price: float, extreme_price: float, is_bullish_pattern: bool) -> float:
        """
        Calculate confidence score based on pattern position (0-2.0)

        Args:
            current_price: Current candle price (low for bullish, high for bearish)
            extreme_price: Recent extreme (min low for bullish, max high for bearish)
            is_bullish_pattern: True for bullish patterns, False for bearish

        Returns:
            Score from 0-2.0
        """
        if is_bullish_pattern:
            # For bullish patterns, check if near recent lows
            if current_price <= extreme_price * 1.005:  # Within 0.5% of low
                return 2.0
            elif current_price <= extreme_price * 1.01:  # Within 1% of low
                return 1.5
            else:
                return 1.0
        else:  # Bearish pattern
            # For bearish patterns, check if near recent highs
            if current_price >= extreme_price * 0.995:  # Within 0.5% of high
                return 2.0
            elif current_price >= extreme_price * 0.99:  # Within 1% of high
                return 1.5
            else:
                return 1.0

    def calculate_regime_score(self, market_regime: str, is_bullish_pattern: bool) -> float:
        """
        Calculate confidence score based on market regime (0-1.0)

        Args:
            market_regime: 'BULLISH', 'BEARISH', or 'NEUTRAL'
            is_bullish_pattern: True for bullish patterns, False for bearish

        Returns:
            Score from 0-1.0
        """
        if is_bullish_pattern:
            if market_regime == 'BULLISH':
                return 1.0
            elif market_regime == 'NEUTRAL':
                return 0.5
            else:
                return 0.0
        else:  # Bearish pattern
            if market_regime == 'BEARISH':
                return 1.0
            elif market_regime == 'NEUTRAL':
                return 0.5
            else:
                return 0.0

    def create_pattern_result(
        self,
        pattern_name: str,
        pattern_type: str,
        confidence: float,
        entry_price: float,
        target: float,
        stop_loss: float,
        volume_ratio: float,
        description: str,
        candle_data: Dict,
        confidence_breakdown: Dict
    ) -> Optional[Dict]:
        """
        Create standardized pattern result dictionary

        Args:
            pattern_name: Name of the pattern
            pattern_type: 'bullish', 'bearish', or 'neutral'
            confidence: Total confidence score (0-10)
            entry_price: Entry price for the trade
            target: Target price
            stop_loss: Stop loss price
            volume_ratio: Current volume / average volume
            description: Pattern description
            candle_data: Dict containing candle OHLCV data
            confidence_breakdown: Dict with score components

        Returns:
            Pattern details dict or None if below minimum confidence
        """
        # Round confidence to 1 decimal place and cap at 10.0
        confidence = round(min(confidence, 10.0), 1)

        # Only return if meets minimum threshold
        if confidence < self.min_confidence:
            return None

        return {
            'pattern_name': pattern_name,
            'type': pattern_type,
            'confidence_score': confidence,
            'entry_price': entry_price,
            'target': target,
            'stop_loss': stop_loss,
            'volume_ratio': volume_ratio,
            'pattern_description': description,
            'candle_data': candle_data,
            'confidence_breakdown': confidence_breakdown
        }

    def detect(
        self,
        candles: List[Dict],
        market_regime: str,
        avg_volume: float
    ) -> Optional[Dict]:
        """
        Abstract method to be implemented by subclasses

        Args:
            candles: List of OHLCV candle dicts (sorted oldest to newest)
            market_regime: 'BULLISH', 'BEARISH', or 'NEUTRAL'
            avg_volume: Average volume for volume spike detection

        Returns:
            Pattern details dict or None
        """
        raise NotImplementedError("Subclasses must implement detect()")
