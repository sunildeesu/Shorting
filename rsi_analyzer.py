#!/usr/bin/env python3
"""
RSI Analyzer with Crossover Detection

Calculates multiple RSI periods and detects crossovers for momentum analysis.
Provides comprehensive RSI analysis including:
- RSI values for periods 9, 14, and 21
- Crossover status between all period combinations
- Recent crossover detection (within last N candles)
- Crossover strength (point separation)

Usage:
    from rsi_analyzer import calculate_rsi_with_crossovers

    rsi_analysis = calculate_rsi_with_crossovers(df)
    # Returns dict with RSI values and crossover analysis
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, List
import logging
import pandas_ta as ta

logger = logging.getLogger(__name__)


class RSIAnalyzer:
    """Analyzes RSI indicators and crossovers for trading signals."""

    def __init__(self, periods: List[int] = [9, 14, 21], crossover_lookback: int = 3):
        """
        Initialize RSI Analyzer.

        Args:
            periods: List of RSI periods to calculate (default: [9, 14, 21])
            crossover_lookback: Number of candles to look back for crossover detection
        """
        self.periods = sorted(periods)  # Ensure ascending order
        self.crossover_lookback = crossover_lookback

    def calculate_rsi_values(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Calculate RSI for all configured periods.

        Args:
            df: DataFrame with OHLCV data (must have 'close' column)

        Returns:
            Dict mapping period to RSI value, e.g., {'rsi_9': 45.2, 'rsi_14': 52.8, 'rsi_21': 58.3}
        """
        rsi_values = {}

        if 'close' not in df.columns:
            logger.error("DataFrame missing 'close' column for RSI calculation")
            return rsi_values

        for period in self.periods:
            try:
                # Calculate RSI using pandas-ta
                rsi_series = ta.rsi(close=df['close'], length=period)

                if rsi_series is not None and len(rsi_series) > 0:
                    # Get latest RSI value
                    latest_rsi = rsi_series.iloc[-1]

                    if pd.notna(latest_rsi):
                        rsi_values[f'rsi_{period}'] = round(float(latest_rsi), 2)
                    else:
                        logger.warning(f"RSI({period}) calculation returned NaN")
                        rsi_values[f'rsi_{period}'] = None
                else:
                    logger.warning(f"RSI({period}) calculation failed")
                    rsi_values[f'rsi_{period}'] = None

            except Exception as e:
                logger.error(f"Error calculating RSI({period}): {e}")
                rsi_values[f'rsi_{period}'] = None

        return rsi_values

    def detect_crossover(
        self,
        rsi_fast: pd.Series,
        rsi_slow: pd.Series,
        fast_period: int,
        slow_period: int
    ) -> Dict[str, any]:
        """
        Detect crossover between two RSI series.

        Args:
            rsi_fast: Faster RSI series (e.g., RSI(9))
            rsi_slow: Slower RSI series (e.g., RSI(14))
            fast_period: Period of faster RSI (for labeling)
            slow_period: Period of slower RSI (for labeling)

        Returns:
            Dict with crossover analysis:
            {
                'status': 'above' | 'below',
                'strength': float (positive if fast > slow, negative if fast < slow),
                'recent_cross': {
                    'occurred': bool,
                    'bars_ago': int | None,
                    'direction': 'bullish' | 'bearish' | None
                }
            }
        """
        crossover_info = {
            'status': None,
            'strength': None,
            'recent_cross': {
                'occurred': False,
                'bars_ago': None,
                'direction': None
            }
        }

        # Need at least lookback + 1 candles
        min_length = self.crossover_lookback + 1
        if len(rsi_fast) < min_length or len(rsi_slow) < min_length:
            logger.warning(f"Insufficient data for crossover detection: {len(rsi_fast)} candles")
            return crossover_info

        try:
            # Current status
            current_fast = rsi_fast.iloc[-1]
            current_slow = rsi_slow.iloc[-1]

            if pd.isna(current_fast) or pd.isna(current_slow):
                return crossover_info

            crossover_info['status'] = 'above' if current_fast > current_slow else 'below'
            crossover_info['strength'] = round(float(current_fast - current_slow), 2)

            # Detect recent crossover (within lookback period)
            for i in range(1, self.crossover_lookback + 1):
                if len(rsi_fast) <= i or len(rsi_slow) <= i:
                    break

                prev_fast = rsi_fast.iloc[-(i+1)]
                prev_slow = rsi_slow.iloc[-(i+1)]
                curr_fast = rsi_fast.iloc[-i]
                curr_slow = rsi_slow.iloc[-i]

                if pd.isna(prev_fast) or pd.isna(prev_slow) or pd.isna(curr_fast) or pd.isna(curr_slow):
                    continue

                # Bullish crossover: fast crossed above slow
                if prev_fast <= prev_slow and curr_fast > curr_slow:
                    crossover_info['recent_cross']['occurred'] = True
                    crossover_info['recent_cross']['bars_ago'] = i
                    crossover_info['recent_cross']['direction'] = 'bullish'
                    break  # Found most recent crossover

                # Bearish crossover: fast crossed below slow
                elif prev_fast >= prev_slow and curr_fast < curr_slow:
                    crossover_info['recent_cross']['occurred'] = True
                    crossover_info['recent_cross']['bars_ago'] = i
                    crossover_info['recent_cross']['direction'] = 'bearish'
                    break  # Found most recent crossover

        except Exception as e:
            logger.error(f"Error detecting crossover RSI({fast_period}) vs RSI({slow_period}): {e}")

        return crossover_info

    def analyze_all_crossovers(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """
        Analyze crossovers for all period combinations.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dict mapping crossover pair to analysis:
            {
                '9_14': {...},
                '9_21': {...},
                '14_21': {...}
            }
        """
        crossovers = {}

        # Calculate all RSI series first
        rsi_series = {}
        for period in self.periods:
            try:
                rsi_series[period] = ta.rsi(close=df['close'], length=period)
            except Exception as e:
                logger.error(f"Error calculating RSI series for period {period}: {e}")
                rsi_series[period] = None

        # Analyze all combinations (fast vs slow)
        for i, fast_period in enumerate(self.periods):
            for slow_period in self.periods[i+1:]:  # Only compare with slower periods
                pair_key = f'{fast_period}_{slow_period}'

                if rsi_series[fast_period] is None or rsi_series[slow_period] is None:
                    crossovers[pair_key] = {
                        'status': None,
                        'strength': None,
                        'recent_cross': {
                            'occurred': False,
                            'bars_ago': None,
                            'direction': None
                        }
                    }
                    continue

                crossovers[pair_key] = self.detect_crossover(
                    rsi_series[fast_period],
                    rsi_series[slow_period],
                    fast_period,
                    slow_period
                )

        return crossovers

    def get_comprehensive_analysis(self, df: pd.DataFrame) -> Dict[str, any]:
        """
        Get complete RSI analysis including values and crossovers.

        Args:
            df: DataFrame with OHLCV data (must have 'close' column)

        Returns:
            Comprehensive analysis dict:
            {
                'rsi_9': 45.2,
                'rsi_14': 52.8,
                'rsi_21': 58.3,
                'crossovers': {
                    '9_14': {...},
                    '9_21': {...},
                    '14_21': {...}
                },
                'summary': 'Bullish momentum' | 'Bearish momentum' | 'Neutral'
            }
        """
        # Calculate RSI values
        rsi_values = self.calculate_rsi_values(df)

        # Analyze crossovers
        crossovers = self.analyze_all_crossovers(df)

        # Generate summary
        summary = self._generate_summary(rsi_values, crossovers)

        return {
            **rsi_values,  # Include RSI values directly
            'crossovers': crossovers,
            'summary': summary
        }

    def _generate_summary(self, rsi_values: Dict, crossovers: Dict) -> str:
        """
        Generate a simple momentum summary based on RSI and crossovers.

        Args:
            rsi_values: Dict of RSI values
            crossovers: Dict of crossover analyses

        Returns:
            Summary string: 'Bullish momentum', 'Bearish momentum', or 'Neutral'
        """
        # Count bullish and bearish signals
        bullish_signals = 0
        bearish_signals = 0

        # Check recent crossovers
        for pair, crossover in crossovers.items():
            if crossover['recent_cross']['occurred']:
                if crossover['recent_cross']['direction'] == 'bullish':
                    bullish_signals += 1
                elif crossover['recent_cross']['direction'] == 'bearish':
                    bearish_signals += 1

        # Check current positions (fast above/below slow)
        for pair, crossover in crossovers.items():
            if crossover['status'] == 'above':
                bullish_signals += 0.5  # Weaker signal than recent crossover
            elif crossover['status'] == 'below':
                bearish_signals += 0.5

        # Determine summary
        if bullish_signals > bearish_signals:
            return 'Bullish momentum'
        elif bearish_signals > bullish_signals:
            return 'Bearish momentum'
        else:
            return 'Neutral'


# Convenience function for easy import
def calculate_rsi_with_crossovers(
    df: pd.DataFrame,
    periods: List[int] = [9, 14, 21],
    crossover_lookback: int = 3
) -> Dict[str, any]:
    """
    Calculate RSI and crossover analysis in one call.

    Args:
        df: DataFrame with OHLCV data
        periods: RSI periods to calculate (default: [9, 14, 21])
        crossover_lookback: Candles to check for recent crossovers (default: 3)

    Returns:
        Complete RSI analysis dict

    Example:
        >>> import pandas as pd
        >>> from rsi_analyzer import calculate_rsi_with_crossovers
        >>>
        >>> df = pd.DataFrame({
        ...     'close': [100, 102, 101, 103, 105, 104, 106, ...]
        ... })
        >>>
        >>> analysis = calculate_rsi_with_crossovers(df)
        >>> print(f"RSI(14): {analysis['rsi_14']}")
        >>> print(f"9 vs 14: {analysis['crossovers']['9_14']['status']}")
    """
    analyzer = RSIAnalyzer(periods=periods, crossover_lookback=crossover_lookback)
    return analyzer.get_comprehensive_analysis(df)


# Helper function to format crossover for display
def format_crossover_display(crossover_info: Dict, fast_period: int, slow_period: int) -> str:
    """
    Format crossover information for display in alerts.

    Args:
        crossover_info: Crossover analysis dict
        fast_period: Fast RSI period (e.g., 9)
        slow_period: Slow RSI period (e.g., 14)

    Returns:
        Formatted string, e.g., "9↑14 (+6.2)" or "9↓14 (-7.6)"
    """
    if crossover_info['status'] is None or crossover_info['strength'] is None:
        return f"{fast_period} vs {slow_period}: N/A"

    arrow = "↑" if crossover_info['status'] == 'above' else "↓"
    strength = crossover_info['strength']
    sign = "+" if strength >= 0 else ""

    return f"{fast_period}{arrow}{slow_period} ({sign}{strength})"


# Helper function to format recent crossover for display
def format_recent_crossover(crossover_info: Dict) -> str:
    """
    Format recent crossover information for display.

    Args:
        crossover_info: Crossover analysis dict

    Returns:
        Formatted string, e.g., "🟢 Bullish 2 bars ago" or "None"
    """
    recent = crossover_info.get('recent_cross', {})

    if not recent.get('occurred'):
        return "None"

    direction = recent['direction']
    bars_ago = recent['bars_ago']

    emoji = "🟢" if direction == 'bullish' else "🔴"
    direction_text = direction.capitalize()

    return f"{emoji} {direction_text} {bars_ago} bar{'s' if bars_ago > 1 else ''} ago"
