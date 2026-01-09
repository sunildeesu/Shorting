#!/usr/bin/env python3
"""
Volume Profile Calculator
Calculates volume profiles from 1-minute candles and detects P-shaped and B-shaped distributions.

P-shaped profile: POC in top 30% of day's range (distribution at highs - bearish)
B-shaped profile: POC in bottom 30% of day's range (accumulation at lows - bullish)
"""

import logging
from typing import Dict, List, Tuple
import config

logger = logging.getLogger(__name__)


class VolumeProfileCalculator:
    """
    Calculate volume profile and detect P-shaped/B-shaped distributions.

    Volume Profile: Aggregates volume at each price level (not time-based).
    POC (Point of Control): Price level with highest volume.
    Value Area: Price range containing 70% of total volume.
    """

    def __init__(self,
                 poc_top_threshold: float = None,
                 poc_bottom_threshold: float = None):
        """
        Initialize volume profile calculator.

        Args:
            poc_top_threshold: POC >= this threshold = P-shape (default: 0.70)
            poc_bottom_threshold: POC <= this threshold = B-shape (default: 0.30)
        """
        self.poc_top_threshold = poc_top_threshold or config.VOLUME_PROFILE_POC_TOP_THRESHOLD
        self.poc_bottom_threshold = poc_bottom_threshold or config.VOLUME_PROFILE_POC_BOTTOM_THRESHOLD

        logger.info(f"Volume Profile Calculator initialized")
        logger.info(f"P-shape threshold: POC >= {self.poc_top_threshold * 100}%")
        logger.info(f"B-shape threshold: POC <= {self.poc_bottom_threshold * 100}%")

    def calculate_volume_profile(self, intraday_data: List[Dict]) -> Dict:
        """
        Calculate volume profile from 1-minute candles.

        Algorithm:
        1. Extract day's range (high, low)
        2. Bin prices into levels (adaptive tick size)
        3. Aggregate volume at each price level
        4. Find POC (price level with max volume)
        5. Calculate POC position: (POC - low) / (high - low)
        6. Calculate value area (70% volume range around POC)
        7. Classify as P-SHAPE/B-SHAPE/BALANCED
        8. Calculate confidence score (0-10)

        Args:
            intraday_data: List of 1-minute OHLCV candles

        Returns:
            {
                'poc_price': float,
                'poc_position': float (0.0-1.0),
                'value_area_high': float,
                'value_area_low': float,
                'day_high': float,
                'day_low': float,
                'day_range': float,
                'total_volume': int,
                'profile_shape': str ('P-SHAPE'|'B-SHAPE'|'BALANCED'|'FLAT'),
                'confidence': float (0-10),
                'volume_distribution': Dict[float, int]
            }
        """
        # Validate input
        if not intraday_data or len(intraday_data) < config.VOLUME_PROFILE_MIN_CANDLES:
            logger.warning(f"Insufficient data: {len(intraday_data) if intraday_data else 0} candles "
                         f"(need {config.VOLUME_PROFILE_MIN_CANDLES}+)")
            return self._empty_result()

        # Step 1: Extract day's range
        day_high = max(candle['high'] for candle in intraday_data)
        day_low = min(candle['low'] for candle in intraday_data)
        day_range = day_high - day_low

        # Check for flat day (no movement)
        if day_range < 0.01:
            logger.info(f"Flat day detected (range={day_range:.2f}), skipping profile calculation")
            return {
                'poc_price': day_high,
                'poc_position': 0.5,
                'value_area_high': day_high,
                'value_area_low': day_low,
                'day_high': day_high,
                'day_low': day_low,
                'day_range': day_range,
                'total_volume': sum(c['volume'] for c in intraday_data),
                'profile_shape': 'FLAT',
                'confidence': 0,
                'volume_distribution': {}
            }

        # Step 2: Calculate adaptive tick size
        tick_size = self._calculate_tick_size(day_range)

        # Step 3: Bin prices and aggregate volume
        volume_distribution = self._bin_prices(intraday_data, tick_size)

        if not volume_distribution:
            logger.warning("Failed to create volume distribution")
            return self._empty_result()

        # Step 4: Calculate total volume
        total_volume = sum(volume_distribution.values())

        if total_volume < 10000:  # Very low volume (suspicious)
            logger.warning(f"Very low total volume: {total_volume}")
            return self._empty_result()

        # Step 5: Find POC (Point of Control)
        poc_price = self._calculate_poc(volume_distribution)
        poc_volume = volume_distribution[poc_price]

        # Step 6: Calculate POC position in day's range
        poc_position = (poc_price - day_low) / day_range  # 0.0 to 1.0

        # Step 7: Calculate value area (70% volume)
        value_area_high, value_area_low = self._calculate_value_area(
            volume_distribution, poc_price, total_volume
        )

        # Step 8: Classify profile shape
        if poc_position >= self.poc_top_threshold:
            profile_shape = 'P-SHAPE'  # Distribution at highs (bearish)
        elif poc_position <= self.poc_bottom_threshold:
            profile_shape = 'B-SHAPE'  # Accumulation at lows (bullish)
        else:
            profile_shape = 'BALANCED'  # Neutral

        # Step 9: Calculate confidence score
        confidence = self._calculate_confidence(
            volume_distribution, poc_price, poc_volume, total_volume, poc_position, profile_shape
        )

        return {
            'poc_price': round(poc_price, 2),
            'poc_position': round(poc_position, 4),
            'value_area_high': round(value_area_high, 2),
            'value_area_low': round(value_area_low, 2),
            'day_high': round(day_high, 2),
            'day_low': round(day_low, 2),
            'day_range': round(day_range, 2),
            'total_volume': total_volume,
            'profile_shape': profile_shape,
            'confidence': round(confidence, 1),
            'volume_distribution': volume_distribution
        }

    def _calculate_tick_size(self, day_range: float) -> float:
        """
        Calculate adaptive tick size based on day's range.

        Strategy:
        - Small range stocks: 0.05 tick
        - Large range stocks: scale up to maintain ~100 bins

        Args:
            day_range: Day's high - low

        Returns:
            Tick size (float)
        """
        if not config.VOLUME_PROFILE_TICK_SIZE_AUTO:
            return 0.05  # Fixed tick size

        # Adaptive: aim for ~100 price bins
        # tick_size = max(0.05, day_range / 100)
        tick_size = max(0.05, round(day_range / 100, 2))

        return tick_size

    def _bin_prices(self, intraday_data: List[Dict], tick_size: float) -> Dict[float, int]:
        """
        Bin 1-minute candles into price levels and aggregate volume.

        Strategy:
        - For each candle, distribute volume across high-low range
        - If candle has range, distribute proportionally
        - If candle is flat (high=low), assign all volume to close price

        Args:
            intraday_data: List of 1-minute OHLCV candles
            tick_size: Price bin size

        Returns:
            Dict mapping price_level -> total_volume
        """
        volume_distribution = {}

        for candle in intraday_data:
            candle_high = candle['high']
            candle_low = candle['low']
            candle_close = candle['close']
            candle_volume = candle['volume']

            # Calculate candle range
            candle_range = candle_high - candle_low

            if candle_range == 0:
                # Flat candle - assign all volume to close price
                price_bin = round(candle_close / tick_size) * tick_size
                volume_distribution[price_bin] = volume_distribution.get(price_bin, 0) + candle_volume
            else:
                # Candle has range - distribute volume proportionally
                # Number of bins in this candle's range
                num_bins = max(1, int(candle_range / tick_size) + 1)
                volume_per_bin = candle_volume / num_bins

                # Iterate through price levels in candle range
                current_price = candle_low
                while current_price <= candle_high:
                    price_bin = round(current_price / tick_size) * tick_size
                    volume_distribution[price_bin] = volume_distribution.get(price_bin, 0) + volume_per_bin
                    current_price += tick_size

        return volume_distribution

    def _calculate_poc(self, volume_distribution: Dict[float, int]) -> float:
        """
        Find Point of Control (price level with highest volume).

        Args:
            volume_distribution: Dict mapping price -> volume

        Returns:
            POC price level
        """
        if not volume_distribution:
            return 0.0

        poc_price = max(volume_distribution, key=volume_distribution.get)
        return poc_price

    def _calculate_value_area(self,
                              volume_distribution: Dict[float, int],
                              poc_price: float,
                              total_volume: int) -> Tuple[float, float]:
        """
        Calculate value area (price range containing 70% of total volume).

        Algorithm:
        1. Start at POC
        2. Expand range up/down to include 70% of total volume
        3. Expand in direction with more volume at each step

        Args:
            volume_distribution: Dict mapping price -> volume
            poc_price: Point of Control price
            total_volume: Total volume for the day

        Returns:
            (value_area_high, value_area_low)
        """
        target_volume = total_volume * 0.70
        accumulated_volume = volume_distribution.get(poc_price, 0)

        # Sort price levels
        sorted_prices = sorted(volume_distribution.keys())

        # Find POC index
        try:
            poc_index = sorted_prices.index(poc_price)
        except ValueError:
            # POC not in sorted list (shouldn't happen)
            logger.warning(f"POC {poc_price} not found in volume distribution")
            return poc_price, poc_price

        # Expand from POC
        low_index = poc_index
        high_index = poc_index

        while accumulated_volume < target_volume:
            # Check if we can expand up or down
            can_expand_up = high_index < len(sorted_prices) - 1
            can_expand_down = low_index > 0

            if not can_expand_up and not can_expand_down:
                break  # Reached both ends

            # Determine which direction to expand
            volume_above = volume_distribution.get(sorted_prices[high_index + 1], 0) if can_expand_up else 0
            volume_below = volume_distribution.get(sorted_prices[low_index - 1], 0) if can_expand_down else 0

            if volume_above >= volume_below and can_expand_up:
                # Expand upward
                high_index += 1
                accumulated_volume += volume_above
            elif can_expand_down:
                # Expand downward
                low_index -= 1
                accumulated_volume += volume_below
            elif can_expand_up:
                # Can only expand up
                high_index += 1
                accumulated_volume += volume_above
            else:
                break

        value_area_high = sorted_prices[high_index]
        value_area_low = sorted_prices[low_index]

        return value_area_high, value_area_low

    def _calculate_confidence(self,
                             volume_distribution: Dict[float, int],
                             poc_price: float,
                             poc_volume: int,
                             total_volume: int,
                             poc_position: float,
                             profile_shape: str) -> float:
        """
        Calculate confidence score (0-10) for the profile classification.

        Confidence factors:
        1. POC volume concentration (higher = more confident)
        2. Distance from threshold boundaries (closer to edge = more confident)
        3. Single peak vs multi-peak distribution (single = more confident)

        Args:
            volume_distribution: Dict mapping price -> volume
            poc_price: Point of Control price
            poc_volume: Volume at POC
            total_volume: Total volume for the day
            poc_position: POC position (0.0-1.0)
            profile_shape: 'P-SHAPE', 'B-SHAPE', or 'BALANCED'

        Returns:
            Confidence score (0.0 to 10.0)
        """
        if profile_shape == 'BALANCED' or profile_shape == 'FLAT':
            return 0.0  # No confidence for balanced/flat profiles

        confidence = 0.0

        # Factor 1: POC concentration (0-4 points)
        # Higher concentration at POC = more confident
        poc_concentration = poc_volume / total_volume if total_volume > 0 else 0
        confidence += min(4.0, poc_concentration * 40)  # Max 4 points if 10%+ at POC

        # Factor 2: Distance from threshold (0-3 points)
        # Further from threshold boundaries = more confident
        if profile_shape == 'P-SHAPE':
            # POC >= 0.70, further from 0.70 = more confident
            distance_from_threshold = poc_position - self.poc_top_threshold
            confidence += min(3.0, distance_from_threshold * 10)  # Max 3 points if 0.30+ beyond threshold
        elif profile_shape == 'B-SHAPE':
            # POC <= 0.30, further from 0.30 = more confident
            distance_from_threshold = self.poc_bottom_threshold - poc_position
            confidence += min(3.0, distance_from_threshold * 10)  # Max 3 points if 0.30+ beyond threshold

        # Factor 3: Single peak vs multi-peak (0-3 points)
        # Single dominant peak = more confident
        sorted_volumes = sorted(volume_distribution.values(), reverse=True)
        if len(sorted_volumes) >= 2:
            second_highest = sorted_volumes[1]
            peak_dominance = (poc_volume - second_highest) / poc_volume if poc_volume > 0 else 0
            confidence += min(3.0, peak_dominance * 3)  # Max 3 points if POC is 100%+ higher than 2nd peak
        else:
            confidence += 3.0  # Single price level = maximum confidence

        return min(10.0, confidence)  # Cap at 10.0

    def _empty_result(self) -> Dict:
        """Return empty result for invalid data."""
        return {
            'poc_price': 0.0,
            'poc_position': 0.0,
            'value_area_high': 0.0,
            'value_area_low': 0.0,
            'day_high': 0.0,
            'day_low': 0.0,
            'day_range': 0.0,
            'total_volume': 0,
            'profile_shape': 'INVALID',
            'confidence': 0.0,
            'volume_distribution': {}
        }


if __name__ == "__main__":
    # Test with sample data
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Sample 1-minute candles (simulating P-shaped profile)
    # Distribution at highs (POC should be high)
    sample_data = []
    for i in range(60):
        if i < 20:
            # Early accumulation (low volume at low prices)
            candle = {'high': 100 + i*0.5, 'low': 100 + i*0.5 - 0.3,
                     'close': 100 + i*0.5, 'volume': 10000}
        elif i < 40:
            # Mid-day rise (moderate volume)
            candle = {'high': 110 + (i-20)*0.8, 'low': 110 + (i-20)*0.8 - 0.5,
                     'close': 110 + (i-20)*0.8, 'volume': 20000}
        else:
            # Late distribution (high volume at highs - P-shape)
            candle = {'high': 126 + (i-40)*0.3, 'low': 126 + (i-40)*0.3 - 0.4,
                     'close': 126 + (i-40)*0.3, 'volume': 50000}
        sample_data.append(candle)

    calc = VolumeProfileCalculator()
    result = calc.calculate_volume_profile(sample_data)

    print("\n" + "="*70)
    print("VOLUME PROFILE ANALYSIS - TEST")
    print("="*70)
    print(f"Profile Shape: {result['profile_shape']}")
    print(f"Confidence: {result['confidence']}/10")
    print(f"POC Price: ₹{result['poc_price']}")
    print(f"POC Position: {result['poc_position']*100:.1f}% of day's range")
    print(f"Day Range: ₹{result['day_low']} - ₹{result['day_high']} (₹{result['day_range']})")
    print(f"Value Area: ₹{result['value_area_low']} - ₹{result['value_area_high']}")
    print(f"Total Volume: {result['total_volume']:,}")
    print("="*70)
