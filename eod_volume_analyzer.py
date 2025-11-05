#!/usr/bin/env python3
"""
EOD Volume Analyzer - Detects volume spikes in last 15-min and 30-min of trading
Compares end-of-day volume activity to daily average
"""

from typing import Dict, List, Tuple, Optional
from datetime import datetime, time
import logging

logger = logging.getLogger(__name__)


class EODVolumeAnalyzer:
    """Analyzes volume spikes at end of trading day"""

    def __init__(self, spike_threshold: float = 1.5):
        """
        Initialize volume analyzer

        Args:
            spike_threshold: Volume multiplier to consider a spike (default: 1.5x)
        """
        self.spike_threshold = spike_threshold
        # NSE trading hours: 9:15 AM - 3:30 PM (375 minutes)
        self.market_open = time(9, 15)
        self.market_close = time(15, 30)
        self.trading_minutes = 375

    def analyze_eod_volume(
        self,
        symbol: str,
        intraday_data: List[Dict],
        historical_data: List[Dict]
    ) -> Dict:
        """
        Analyze end-of-day volume for a single stock

        Args:
            symbol: Stock symbol
            intraday_data: Today's 15-minute interval data from Kite API
                          [{date: datetime, volume: int, ...}, ...]
            historical_data: 30-day daily data from Kite API
                           [{date: datetime, volume: int, ...}, ...]

        Returns:
            Dict with volume analysis results:
            {
                'symbol': str,
                'has_spike_15min': bool,
                'has_spike_30min': bool,
                'volume_15min': int,
                'volume_30min': int,
                'avg_15min_volume': float,
                'avg_30min_volume': float,
                'spike_ratio_15min': float,
                'spike_ratio_30min': float
            }
        """
        # Calculate average daily volume from historical data
        avg_daily_volume = self._calculate_avg_volume(historical_data)

        if avg_daily_volume == 0:
            logger.warning(f"{symbol}: No historical volume data")
            return self._empty_result(symbol)

        # Extract last 15-min and 30-min volumes from intraday data
        volume_15min = self._get_last_n_minutes_volume(intraday_data, 15)
        volume_30min = self._get_last_n_minutes_volume(intraday_data, 30)

        # Calculate expected volumes for 15-min and 30-min periods
        # Average volume per minute = avg_daily_volume / trading_minutes
        avg_volume_per_minute = avg_daily_volume / self.trading_minutes
        avg_15min_volume = avg_volume_per_minute * 15
        avg_30min_volume = avg_volume_per_minute * 30

        # Calculate spike ratios
        spike_ratio_15min = volume_15min / avg_15min_volume if avg_15min_volume > 0 else 0
        spike_ratio_30min = volume_30min / avg_30min_volume if avg_30min_volume > 0 else 0

        # Detect spikes
        has_spike_15min = spike_ratio_15min >= self.spike_threshold
        has_spike_30min = spike_ratio_30min >= self.spike_threshold

        result = {
            'symbol': symbol,
            'has_spike_15min': has_spike_15min,
            'has_spike_30min': has_spike_30min,
            'volume_15min': volume_15min,
            'volume_30min': volume_30min,
            'avg_15min_volume': avg_15min_volume,
            'avg_30min_volume': avg_30min_volume,
            'spike_ratio_15min': spike_ratio_15min,
            'spike_ratio_30min': spike_ratio_30min,
            'avg_daily_volume': avg_daily_volume
        }

        if has_spike_15min or has_spike_30min:
            logger.info(
                f"{symbol}: EOD volume spike detected! "
                f"15min: {spike_ratio_15min:.2f}x, 30min: {spike_ratio_30min:.2f}x"
            )

        return result

    def _calculate_avg_volume(self, historical_data: List[Dict]) -> float:
        """
        Calculate average daily volume from historical data

        Args:
            historical_data: List of daily OHLCV dicts

        Returns:
            Average daily volume
        """
        if not historical_data:
            return 0.0

        volumes = [candle.get('volume', 0) for candle in historical_data]
        valid_volumes = [v for v in volumes if v > 0]

        if not valid_volumes:
            return 0.0

        return sum(valid_volumes) / len(valid_volumes)

    def _get_last_n_minutes_volume(self, intraday_data: List[Dict], minutes: int) -> int:
        """
        Get total volume for last N minutes of trading

        Args:
            intraday_data: Today's 15-minute interval data
            minutes: Number of minutes to look back (15 or 30)

        Returns:
            Total volume in last N minutes
        """
        if not intraday_data:
            return 0

        # Sort by date (most recent last)
        sorted_data = sorted(intraday_data, key=lambda x: x.get('date', datetime.min))

        # Calculate how many 15-minute candles we need
        # For 15 minutes: 1 candle, For 30 minutes: 2 candles
        num_candles = minutes // 15

        if num_candles == 0:
            num_candles = 1

        # Get last N candles
        last_candles = sorted_data[-num_candles:] if len(sorted_data) >= num_candles else sorted_data

        # Sum volumes
        total_volume = sum(candle.get('volume', 0) for candle in last_candles)

        return total_volume

    def _empty_result(self, symbol: str) -> Dict:
        """Return empty result for stocks with no data"""
        return {
            'symbol': symbol,
            'has_spike_15min': False,
            'has_spike_30min': False,
            'volume_15min': 0,
            'volume_30min': 0,
            'avg_15min_volume': 0,
            'avg_30min_volume': 0,
            'spike_ratio_15min': 0,
            'spike_ratio_30min': 0,
            'avg_daily_volume': 0
        }

    def batch_analyze(
        self,
        intraday_data_map: Dict[str, List[Dict]],
        historical_data_map: Dict[str, List[Dict]]
    ) -> List[Dict]:
        """
        Analyze volume for multiple stocks

        Args:
            intraday_data_map: Dict mapping symbol to intraday data
            historical_data_map: Dict mapping symbol to historical data

        Returns:
            List of volume analysis results for all stocks
        """
        results = []

        for symbol in intraday_data_map.keys():
            intraday_data = intraday_data_map.get(symbol, [])
            historical_data = historical_data_map.get(symbol, [])

            result = self.analyze_eod_volume(symbol, intraday_data, historical_data)
            results.append(result)

        # Log summary
        spike_15min_count = sum(1 for r in results if r['has_spike_15min'])
        spike_30min_count = sum(1 for r in results if r['has_spike_30min'])

        logger.info(
            f"Volume analysis complete: {len(results)} stocks analyzed, "
            f"{spike_15min_count} with 15-min spikes, {spike_30min_count} with 30-min spikes"
        )

        return results
