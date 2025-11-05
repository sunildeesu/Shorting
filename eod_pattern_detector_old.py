#!/usr/bin/env python3
"""
EOD Pattern Detector - Detects chart patterns on daily timeframe
Implements: Double Bottom, Double Top, Support/Resistance Breakouts
"""

from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class EODPatternDetector:
    """Detects chart patterns on daily timeframe"""

    def __init__(self, pattern_tolerance: float = 2.0):
        """
        Initialize pattern detector

        Args:
            pattern_tolerance: Price tolerance percentage for pattern matching (default: 2%)
        """
        self.pattern_tolerance = pattern_tolerance

    def detect_patterns(self, symbol: str, historical_data: List[Dict]) -> Dict:
        """
        Detect all chart patterns for a single stock

        Args:
            symbol: Stock symbol
            historical_data: 30-day daily OHLCV data from Kite API
                           [{date: datetime, open: float, high: float, low: float, close: float, volume: int}, ...]

        Returns:
            Dict with pattern detection results:
            {
                'symbol': str,
                'patterns_found': List[str],  # e.g., ['DOUBLE_BOTTOM', 'SUPPORT_BREAKOUT']
                'pattern_details': Dict,
                'has_patterns': bool
            }
        """
        if not historical_data or len(historical_data) < 10:
            logger.debug(f"{symbol}: Insufficient data for pattern detection")
            return self._empty_result(symbol)

        patterns_found = []
        pattern_details = {}

        # Detect Double Bottom
        double_bottom = self._detect_double_bottom(historical_data)
        if double_bottom:
            patterns_found.append('DOUBLE_BOTTOM')
            pattern_details['double_bottom'] = double_bottom

        # Detect Double Top
        double_top = self._detect_double_top(historical_data)
        if double_top:
            patterns_found.append('DOUBLE_TOP')
            pattern_details['double_top'] = double_top

        # Detect Support Breakout
        support_breakout = self._detect_support_breakout(historical_data)
        if support_breakout:
            patterns_found.append('SUPPORT_BREAKOUT')
            pattern_details['support_breakout'] = support_breakout

        # Detect Resistance Breakout
        resistance_breakout = self._detect_resistance_breakout(historical_data)
        if resistance_breakout:
            patterns_found.append('RESISTANCE_BREAKOUT')
            pattern_details['resistance_breakout'] = resistance_breakout

        if patterns_found:
            logger.info(f"{symbol}: Patterns detected - {', '.join(patterns_found)}")

        return {
            'symbol': symbol,
            'patterns_found': patterns_found,
            'pattern_details': pattern_details,
            'has_patterns': len(patterns_found) > 0
        }

    def _detect_double_bottom(self, data: List[Dict]) -> Optional[Dict]:
        """
        Detect Double Bottom pattern (bullish reversal)
        Two lows at similar levels with a peak in between
        Focus on RECENT patterns (last 15 days)

        Returns:
            Pattern details dict or None
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
                        # Calculate buy price and target
                        # Buy Price: Above the second low with 0.5% safety margin
                        buy_price = second_low[1] * 1.005

                        # Target: Pattern height projection (low to peak distance added to breakout level)
                        pattern_height = max_between - second_low[1]
                        target_price = max_between + pattern_height

                        return {
                            'first_low': first_low[1],
                            'second_low': second_low[1],
                            'peak_between': max_between,
                            'pattern_strength': 'Strong' if price_diff_pct < 1.0 else 'Moderate',
                            'current_price': current_price,
                            'buy_price': buy_price,
                            'target_price': target_price,
                            'pattern_type': 'BULLISH'
                        }

        return None

    def _detect_double_top(self, data: List[Dict]) -> Optional[Dict]:
        """
        Detect Double Top pattern (bearish reversal)
        Two highs at similar levels with a trough in between
        Focus on RECENT patterns (last 15 days)

        Returns:
            Pattern details dict or None
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
                        # Calculate short entry and target
                        # Short Entry: Below the second high with 0.5% safety margin
                        buy_price = second_high[1] * 0.995

                        # Target: Pattern height projection (high to trough distance subtracted from breakdown level)
                        pattern_height = second_high[1] - min_between
                        target_price = min_between - pattern_height

                        return {
                            'first_high': first_high[1],
                            'second_high': second_high[1],
                            'trough_between': min_between,
                            'pattern_strength': 'Strong' if price_diff_pct < 1.0 else 'Moderate',
                            'current_price': current_price,
                            'buy_price': buy_price,  # Short entry price
                            'target_price': target_price,
                            'pattern_type': 'BEARISH'
                        }

        return None

    def _detect_support_breakout(self, data: List[Dict]) -> Optional[Dict]:
        """
        Detect Support Breakout (bearish)
        Price breaking below recent support level with volume confirmation

        Returns:
            Pattern details dict or None
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
                # Calculate short entry and target for support breakout
                # Short Entry: Current price (already broken down)
                buy_price = current_price

                # Target: Support level minus the breakout distance (conservative)
                breakout_distance = support_level - current_low
                target_price = support_level - (breakout_distance * 2)  # 2x the breakout distance

                return {
                    'support_level': support_level,
                    'current_price': current_price,
                    'current_low': current_low,
                    'breakout_strength_pct': breakout_strength,
                    'signal': 'Bearish',
                    'buy_price': buy_price,  # Short entry
                    'target_price': target_price,
                    'pattern_type': 'BEARISH'
                }

        return None

    def _detect_resistance_breakout(self, data: List[Dict]) -> Optional[Dict]:
        """
        Detect Resistance Breakout (bullish)
        Price breaking above recent resistance level with volume confirmation

        Returns:
            Pattern details dict or None
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
                # Calculate buy price and target for resistance breakout
                # Buy Price: Current price (already broken out)
                buy_price = current_price

                # Target: Resistance level plus the breakout distance (conservative)
                breakout_distance = current_high - resistance_level
                target_price = resistance_level + (breakout_distance * 2)  # 2x the breakout distance

                return {
                    'resistance_level': resistance_level,
                    'current_price': current_price,
                    'current_high': current_high,
                    'breakout_strength_pct': breakout_strength,
                    'signal': 'Bullish',
                    'buy_price': buy_price,
                    'target_price': target_price,
                    'pattern_type': 'BULLISH'
                }

        return None

    def _empty_result(self, symbol: str) -> Dict:
        """Return empty result for stocks with no patterns"""
        return {
            'symbol': symbol,
            'patterns_found': [],
            'pattern_details': {},
            'has_patterns': False
        }

    def batch_detect(self, historical_data_map: Dict[str, List[Dict]]) -> List[Dict]:
        """
        Detect patterns for multiple stocks

        Args:
            historical_data_map: Dict mapping symbol to historical data

        Returns:
            List of pattern detection results for all stocks
        """
        results = []

        for symbol, historical_data in historical_data_map.items():
            result = self.detect_patterns(symbol, historical_data)
            results.append(result)

        # Log summary
        stocks_with_patterns = sum(1 for r in results if r['has_patterns'])
        total_patterns = sum(len(r['patterns_found']) for r in results)

        logger.info(
            f"Pattern detection complete: {len(results)} stocks analyzed, "
            f"{stocks_with_patterns} with patterns ({total_patterns} total patterns found)"
        )

        return results
