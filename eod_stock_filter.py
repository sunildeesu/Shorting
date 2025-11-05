#!/usr/bin/env python3
"""
EOD Stock Filter - Smart filtering to reduce API calls
Filters 210 F&O stocks down to 40-60 active stocks based on volume and price movement
"""

from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


class EODStockFilter:
    """Filters stocks to analyze based on activity criteria"""

    def __init__(self, volume_threshold_lakhs: float = 50.0, price_change_threshold: float = 1.5):
        """
        Initialize stock filter

        Args:
            volume_threshold_lakhs: Minimum volume in lakhs (default: 50)
            price_change_threshold: Minimum price change percentage (default: 1.5%)
        """
        self.volume_threshold = volume_threshold_lakhs * 100000  # Convert to actual volume
        self.price_change_threshold = price_change_threshold

    def filter_stocks(self, quote_data: Dict[str, Dict]) -> List[str]:
        """
        Filter stocks based on volume and price movement

        Args:
            quote_data: Dict of stock quotes from Kite API
                       {symbol: {'volume': 1000000, 'ohlc': {'close': 100, 'open': 98}, ...}}

        Returns:
            List of filtered stock symbols that meet criteria
        """
        filtered_stocks = []
        stats = {
            'total': len(quote_data),
            'volume_filtered': 0,
            'change_filtered': 0,
            'both_filtered': 0
        }

        for symbol, quote in quote_data.items():
            # Skip if missing data
            if not quote or 'volume' not in quote or 'ohlc' not in quote:
                logger.debug(f"{symbol}: Skipping (missing data)")
                continue

            volume = quote.get('volume', 0)
            ohlc = quote.get('ohlc', {})
            open_price = ohlc.get('open', 0)
            close_price = ohlc.get('close', 0)

            # Skip if invalid prices
            if open_price <= 0 or close_price <= 0:
                logger.debug(f"{symbol}: Skipping (invalid prices)")
                continue

            # Calculate price change percentage
            price_change_pct = abs((close_price - open_price) / open_price * 100)

            # Check filtering criteria
            volume_condition = volume >= self.volume_threshold
            change_condition = price_change_pct >= self.price_change_threshold

            if volume_condition or change_condition:
                filtered_stocks.append(symbol)

                # Update stats
                if volume_condition and change_condition:
                    stats['both_filtered'] += 1
                elif volume_condition:
                    stats['volume_filtered'] += 1
                else:
                    stats['change_filtered'] += 1

                logger.debug(
                    f"{symbol}: Included (vol={volume/100000:.1f}L, "
                    f"change={price_change_pct:.2f}%)"
                )

        # Log filtering summary
        logger.info(
            f"Stock filtering complete: {stats['total']} → {len(filtered_stocks)} stocks "
            f"({len(filtered_stocks)/stats['total']*100:.1f}% retention)"
        )
        logger.info(
            f"  By volume only: {stats['volume_filtered']}, "
            f"By change only: {stats['change_filtered']}, "
            f"Both: {stats['both_filtered']}"
        )

        return filtered_stocks

    def get_filtering_stats(self, quote_data: Dict[str, Dict]) -> Dict:
        """
        Get detailed filtering statistics without actually filtering

        Args:
            quote_data: Dict of stock quotes

        Returns:
            Dict with filtering statistics
        """
        total_stocks = len(quote_data)
        volume_stocks = 0
        change_stocks = 0
        both_stocks = 0
        low_activity_stocks = 0

        for symbol, quote in quote_data.items():
            if not quote or 'volume' not in quote or 'ohlc' not in quote:
                continue

            volume = quote.get('volume', 0)
            ohlc = quote.get('ohlc', {})
            open_price = ohlc.get('open', 0)
            close_price = ohlc.get('close', 0)

            if open_price <= 0 or close_price <= 0:
                continue

            price_change_pct = abs((close_price - open_price) / open_price * 100)

            volume_condition = volume >= self.volume_threshold
            change_condition = price_change_pct >= self.price_change_threshold

            if volume_condition and change_condition:
                both_stocks += 1
            elif volume_condition:
                volume_stocks += 1
            elif change_condition:
                change_stocks += 1
            else:
                low_activity_stocks += 1

        filtered_total = volume_stocks + change_stocks + both_stocks

        return {
            'total_stocks': total_stocks,
            'filtered_stocks': filtered_total,
            'reduction_percent': (1 - filtered_total/total_stocks) * 100 if total_stocks > 0 else 0,
            'by_volume_only': volume_stocks,
            'by_change_only': change_stocks,
            'by_both': both_stocks,
            'low_activity': low_activity_stocks,
            'volume_threshold_lakhs': self.volume_threshold / 100000,
            'change_threshold_percent': self.price_change_threshold
        }
