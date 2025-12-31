#!/usr/bin/env python3
"""
Pattern Detection Utility Functions

Shared utility functions for pattern detection across daily and hourly timeframes.
Used by pattern_detector.py, premarket_analyzer.py, and eod_pattern_detector.py.

Author: Sunil Kumar Durganaik
"""

from typing import List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)


def calculate_avg_volume(data: List[Dict]) -> float:
    """
    Calculate average volume from OHLCV data.

    Args:
        data: List of OHLCV candles

    Returns:
        Average volume across all candles
    """
    if not data:
        return 0

    volumes = [candle.get('volume', 0) for candle in data]
    return sum(volumes) / len(volumes) if volumes else 0


def check_volume_confirmation(
    current_volume: int,
    avg_volume: float,
    volume_threshold: float = 1.75,
    require_confirmation: bool = True
) -> Tuple[bool, float]:
    """
    Check if current volume meets threshold for pattern confirmation.

    Args:
        current_volume: Current candle volume
        avg_volume: Average volume from historical data
        volume_threshold: Multiplier threshold (default 1.75x for daily, 1.5x for hourly)
        require_confirmation: Whether to enforce volume requirement

    Returns:
        Tuple of (confirmation_passed, volume_ratio)
    """
    if not require_confirmation or avg_volume == 0:
        return True, 1.0

    volume_ratio = current_volume / avg_volume
    return volume_ratio >= volume_threshold, volume_ratio


def calculate_confidence_score(
    price_match_pct: float,
    volume_ratio: float,
    pattern_height_pct: float,
    pattern_type: str,
    market_regime: str,
    timeframe: str = 'daily'
) -> float:
    """
    Calculate pattern confidence score with 7 factors (0-10 scale).

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
        timeframe: 'daily' or 'hourly' (affects scoring thresholds)

    Returns:
        Confidence score from 0-10
    """
    score = 0.0

    # Adjust thresholds based on timeframe
    # Hourly patterns: looser price match, tighter volume, smaller heights
    if timeframe == 'hourly':
        price_thresholds = [0.8, 1.5, 2.5, 3.5]  # Looser than daily
        volume_thresholds = [2.5, 2.0, 1.5, 1.2]  # Tighter than daily
        height_thresholds = [7.0, 5.0, 3.0, 2.0, 1.0]  # Smaller than daily
    else:  # daily
        price_thresholds = [0.5, 1.0, 1.5, 2.0]
        volume_thresholds = [3.0, 2.5, 2.0, 1.5]
        height_thresholds = [10.0, 7.0, 5.0, 3.0, 2.0]

    # 1. Price Pattern Match (0-2 points)
    if price_match_pct < price_thresholds[0]:
        score += 2.0  # Perfect/Excellent match
    elif price_match_pct < price_thresholds[1]:
        score += 1.8  # Very good match
    elif price_match_pct < price_thresholds[2]:
        score += 1.5  # Good match
    elif price_match_pct < price_thresholds[3]:
        score += 1.0  # Acceptable match
    else:
        score += 0.5  # Weak match

    # 2. Volume Confirmation (0-2 points)
    if volume_ratio >= volume_thresholds[0]:
        score += 2.0  # Massive volume surge
    elif volume_ratio >= volume_thresholds[1]:
        score += 1.8  # Very strong volume
    elif volume_ratio >= volume_thresholds[2]:
        score += 1.5  # Strong volume
    elif volume_ratio >= volume_thresholds[3]:
        score += 1.0  # Good volume
    else:
        score += 0.5  # Weak volume

    # 3. Pattern Size/Height (0-2 points)
    if pattern_height_pct >= height_thresholds[0]:
        score += 2.0  # Large significant pattern
    elif pattern_height_pct >= height_thresholds[1]:
        score += 1.8  # Good sized pattern
    elif pattern_height_pct >= height_thresholds[2]:
        score += 1.5  # Medium pattern
    elif pattern_height_pct >= height_thresholds[3]:
        score += 1.0  # Small pattern
    elif pattern_height_pct >= height_thresholds[4]:
        score += 0.5  # Very small pattern
    else:
        score += 0.2  # Tiny pattern (likely noise)

    # 4. Market Regime Alignment (0-2 points)
    if pattern_type == 'BULLISH' and market_regime == 'BULLISH':
        score += 2.0  # Perfect bullish alignment
    elif pattern_type == 'BEARISH' and market_regime == 'BEARISH':
        score += 2.0  # Perfect bearish alignment
    elif market_regime == 'NEUTRAL':
        score += 1.2  # Neutral market - reasonable
    else:
        score += 0.3  # Against trend (risky)

    # 5. Volume Quality Bonus (0-1 point)
    if volume_ratio >= 4.0:
        score += 1.0  # Exceptional volume (4x+)
    elif volume_ratio >= 3.5:
        score += 0.7  # Very high volume
    elif volume_ratio >= 3.0:
        score += 0.5  # High volume
    elif volume_ratio >= 2.5:
        score += 0.3  # Above average volume

    # 6. Pattern Formation Time Bonus (0-0.5 point)
    # Pattern already passed basic validation, give credit
    score += 0.5

    # 7. Base Score (0-0.5 point)
    # All valid patterns that passed filters get base credit
    score += 0.5

    # Cap at 10.0
    return round(min(score, 10.0), 1)


def calculate_risk_reward_ratio(
    entry_price: float,
    target_price: float,
    stop_loss: float
) -> float:
    """
    Calculate risk-reward ratio for a trade setup.

    Args:
        entry_price: Entry price
        target_price: Target price
        stop_loss: Stop loss price

    Returns:
        Risk-reward ratio (e.g., 1:3 returns 3.0)
    """
    if entry_price == 0 or entry_price == stop_loss:
        return 0.0

    reward = abs(target_price - entry_price)
    risk = abs(entry_price - stop_loss)

    if risk == 0:
        return 0.0

    return reward / risk


def normalize_volume_ratio(volume_ratio: float, min_threshold: float = 1.75, max_threshold: float = 5.0) -> float:
    """
    Normalize volume ratio to 0-1 scale for priority scoring.

    Args:
        volume_ratio: Current volume / average volume
        min_threshold: Minimum acceptable ratio (default 1.75)
        max_threshold: Maximum expected ratio (default 5.0)

    Returns:
        Normalized score from 0-1
    """
    if volume_ratio < min_threshold:
        return 0.0
    elif volume_ratio > max_threshold:
        return 1.0
    else:
        return (volume_ratio - min_threshold) / (max_threshold - min_threshold)


def calculate_freshness_score(candles_ago: int, max_age: int = 5) -> float:
    """
    Calculate freshness score based on how recently pattern formed.

    Args:
        candles_ago: Number of candles since pattern completed (0 = most recent candle)
        max_age: Maximum age to consider (default 5 candles)

    Returns:
        Freshness score from 0-1 (1 = most fresh, 0 = stale)
    """
    if candles_ago == 0:
        return 1.0
    elif candles_ago <= max_age:
        return 1.0 - (candles_ago / (max_age * 2))  # Linear decay
    else:
        return 0.0


def get_timeframe_bonus(timeframe: str) -> float:
    """
    Get priority bonus based on timeframe.

    Daily patterns are generally more reliable than hourly,
    so they get a slight priority boost.

    Args:
        timeframe: 'daily' or 'hourly'

    Returns:
        Bonus score from 0-1
    """
    return 1.0 if timeframe == 'daily' else 0.7


def format_pattern_name(pattern_name: str) -> str:
    """
    Format pattern name for display.

    Args:
        pattern_name: Pattern name in SNAKE_CASE

    Returns:
        Formatted name (e.g., "DOUBLE_BOTTOM" -> "Double Bottom")
    """
    return pattern_name.replace('_', ' ').title()


def calculate_pattern_height_pct(high: float, low: float, reference_price: float) -> float:
    """
    Calculate pattern height as percentage of reference price.

    Args:
        high: Pattern high
        low: Pattern low
        reference_price: Reference price (usually current price or breakout price)

    Returns:
        Pattern height as percentage
    """
    if reference_price == 0:
        return 0.0

    height = abs(high - low)
    return (height / reference_price) * 100


def validate_ohlcv_data(data: List[Dict], min_candles: int = 1) -> bool:
    """
    Validate OHLCV data structure and minimum requirements.

    Args:
        data: List of OHLCV candles
        min_candles: Minimum number of candles required

    Returns:
        True if data is valid, False otherwise
    """
    if not data or len(data) < min_candles:
        return False

    # Check first candle has required fields
    required_fields = ['open', 'high', 'low', 'close', 'volume']
    first_candle = data[0]

    return all(field in first_candle for field in required_fields)


def get_candle_range(candle: Dict) -> float:
    """
    Get price range (high - low) of a candle.

    Args:
        candle: OHLCV candle dict

    Returns:
        Price range
    """
    return candle['high'] - candle['low']


def is_bullish_candle(candle: Dict) -> bool:
    """
    Check if candle is bullish (close > open).

    Args:
        candle: OHLCV candle dict

    Returns:
        True if bullish, False otherwise
    """
    return candle['close'] > candle['open']


def is_bearish_candle(candle: Dict) -> bool:
    """
    Check if candle is bearish (close < open).

    Args:
        candle: OHLCV candle dict

    Returns:
        True if bearish, False otherwise
    """
    return candle['close'] < candle['open']


if __name__ == "__main__":
    # Test utilities
    print("=" * 60)
    print("PATTERN UTILITIES - TEST")
    print("=" * 60)

    # Test calculate_avg_volume
    test_data = [
        {'volume': 1000000},
        {'volume': 1200000},
        {'volume': 900000}
    ]
    avg_vol = calculate_avg_volume(test_data)
    print(f"\n1. Average Volume: {avg_vol:,.0f}")

    # Test volume confirmation
    confirmed, ratio = check_volume_confirmation(2000000, avg_vol, 1.75)
    print(f"2. Volume Confirmation: {confirmed} (ratio: {ratio:.2f}x)")

    # Test confidence score (daily)
    score_daily = calculate_confidence_score(
        price_match_pct=1.2,
        volume_ratio=2.5,
        pattern_height_pct=5.0,
        pattern_type='BULLISH',
        market_regime='BULLISH',
        timeframe='daily'
    )
    print(f"3. Confidence Score (daily): {score_daily}/10")

    # Test confidence score (hourly)
    score_hourly = calculate_confidence_score(
        price_match_pct=1.8,
        volume_ratio=1.8,
        pattern_height_pct=3.0,
        pattern_type='BULLISH',
        market_regime='BULLISH',
        timeframe='hourly'
    )
    print(f"4. Confidence Score (hourly): {score_hourly}/10")

    # Test R:R ratio
    rr = calculate_risk_reward_ratio(100, 110, 97)
    print(f"5. Risk-Reward Ratio: 1:{rr:.1f}")

    # Test freshness score
    fresh = calculate_freshness_score(0)
    stale = calculate_freshness_score(10)
    print(f"6. Freshness Score: Fresh={fresh:.2f}, Stale={stale:.2f}")

    # Test pattern name formatting
    formatted = format_pattern_name("DOUBLE_BOTTOM")
    print(f"7. Formatted Pattern: {formatted}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
