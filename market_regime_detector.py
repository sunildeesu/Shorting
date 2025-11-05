#!/usr/bin/env python3
"""
Market Regime Detector - Determines overall market trend
Uses Nifty 50 index with 50-day SMA for regime classification
"""

from datetime import datetime, timedelta
from typing import Dict, Optional
import logging
from kiteconnect import KiteConnect

logger = logging.getLogger(__name__)


class MarketRegimeDetector:
    """Detects market regime (bullish/bearish) using Nifty 50"""

    # Nifty 50 instrument token for Kite API
    NIFTY_50_TOKEN = 256265  # NSE:NIFTY 50

    def __init__(self, kite: KiteConnect):
        """
        Initialize market regime detector

        Args:
            kite: Authenticated KiteConnect instance
        """
        self.kite = kite
        self._cached_regime = None
        self._cache_timestamp = None
        self._cache_validity = timedelta(hours=6)  # Cache for 6 hours

    def get_market_regime(self) -> str:
        """
        Get current market regime

        Returns:
            'BULLISH', 'BEARISH', or 'NEUTRAL'
        """
        # Check cache validity
        if self._is_cache_valid():
            logger.debug(f"Using cached market regime: {self._cached_regime}")
            return self._cached_regime

        try:
            # Fetch Nifty 50 historical data (60 days for 50-day SMA calculation)
            to_date = datetime.now()
            from_date = to_date - timedelta(days=70)  # Extra buffer for weekends/holidays

            logger.info("Fetching Nifty 50 data for market regime detection...")
            historical_data = self.kite.historical_data(
                instrument_token=self.NIFTY_50_TOKEN,
                from_date=from_date,
                to_date=to_date,
                interval="day"
            )

            if not historical_data or len(historical_data) < 50:
                logger.warning("Insufficient Nifty data, defaulting to NEUTRAL regime")
                return "NEUTRAL"

            # Calculate 50-day SMA
            recent_50_days = historical_data[-50:]
            sma_50 = sum(candle['close'] for candle in recent_50_days) / 50

            # Get current price
            current_price = historical_data[-1]['close']

            # Determine regime
            regime = self._classify_regime(current_price, sma_50)

            # Cache the result
            self._cached_regime = regime
            self._cache_timestamp = datetime.now()

            logger.info(f"Market Regime: {regime} (Nifty: {current_price:.2f}, 50-SMA: {sma_50:.2f})")

            return regime

        except Exception as e:
            logger.error(f"Error detecting market regime: {e}")
            return "NEUTRAL"  # Default to neutral on error

    def _classify_regime(self, current_price: float, sma_50: float) -> str:
        """
        Classify market regime based on price vs SMA

        Args:
            current_price: Current Nifty price
            sma_50: 50-day simple moving average

        Returns:
            'BULLISH', 'BEARISH', or 'NEUTRAL'
        """
        # Calculate percentage difference
        diff_pct = ((current_price - sma_50) / sma_50) * 100

        # Classification thresholds
        if diff_pct > 2.0:
            return "BULLISH"  # Price >2% above SMA - strong uptrend
        elif diff_pct < -2.0:
            return "BEARISH"  # Price >2% below SMA - strong downtrend
        else:
            return "NEUTRAL"  # Price within ±2% of SMA - sideways/choppy

    def _is_cache_valid(self) -> bool:
        """Check if cached regime is still valid"""
        if self._cached_regime is None or self._cache_timestamp is None:
            return False

        age = datetime.now() - self._cache_timestamp
        return age < self._cache_validity

    def get_regime_details(self) -> Dict:
        """
        Get detailed market regime information

        Returns:
            Dict with regime, current price, SMA, and diff percentage
        """
        try:
            # Fetch recent data
            to_date = datetime.now()
            from_date = to_date - timedelta(days=70)

            historical_data = self.kite.historical_data(
                instrument_token=self.NIFTY_50_TOKEN,
                from_date=from_date,
                to_date=to_date,
                interval="day"
            )

            if not historical_data or len(historical_data) < 50:
                return {
                    'regime': 'NEUTRAL',
                    'current_price': 0,
                    'sma_50': 0,
                    'diff_pct': 0,
                    'error': 'Insufficient data'
                }

            # Calculate metrics
            recent_50_days = historical_data[-50:]
            sma_50 = sum(candle['close'] for candle in recent_50_days) / 50
            current_price = historical_data[-1]['close']
            diff_pct = ((current_price - sma_50) / sma_50) * 100
            regime = self._classify_regime(current_price, sma_50)

            return {
                'regime': regime,
                'current_price': current_price,
                'sma_50': sma_50,
                'diff_pct': diff_pct,
                'price_above_sma': current_price > sma_50
            }

        except Exception as e:
            logger.error(f"Error getting regime details: {e}")
            return {
                'regime': 'NEUTRAL',
                'current_price': 0,
                'sma_50': 0,
                'diff_pct': 0,
                'error': str(e)
            }

    def clear_cache(self):
        """Clear cached regime data"""
        self._cached_regime = None
        self._cache_timestamp = None
        logger.debug("Market regime cache cleared")
