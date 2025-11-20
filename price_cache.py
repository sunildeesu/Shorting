import json
import os
from datetime import datetime
from typing import Dict, Optional, Tuple
import logging
import config

logger = logging.getLogger(__name__)

class PriceCache:
    """
    Manages price cache with last 7 snapshots for each stock (for 30-minute comparison).
    Also tracks volume data for volume spike detection.

    Structure: {
        "stock_symbol": {
            "current": {"price": float, "volume": int, "timestamp": str},
            "previous": {"price": float, "volume": int, "timestamp": str},   # 5 min ago
            "previous2": {"price": float, "volume": int, "timestamp": str},  # 10 min ago
            "previous3": {"price": float, "volume": int, "timestamp": str},  # 15 min ago
            "previous4": {"price": float, "volume": int, "timestamp": str},  # 20 min ago
            "previous5": {"price": float, "volume": int, "timestamp": str},  # 25 min ago
            "previous6": {"price": float, "volume": int, "timestamp": str}   # 30 min ago
        }
    }
    """

    def __init__(self):
        self.cache_file = config.PRICE_CACHE_FILE
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        """Load cache from file, create empty if doesn't exist"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_cache(self):
        """Save cache to file"""
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)

    def _is_same_day(self, timestamp1: str, timestamp2: str) -> bool:
        """
        Check if two timestamps are from the same calendar day

        Args:
            timestamp1: ISO format timestamp
            timestamp2: ISO format timestamp

        Returns:
            True if both timestamps are from the same day, False otherwise
        """
        try:
            dt1 = datetime.fromisoformat(timestamp1)
            dt2 = datetime.fromisoformat(timestamp2)
            return dt1.date() == dt2.date()
        except (ValueError, TypeError, AttributeError):
            # If parsing fails, assume different days to be safe
            return False

    def update_price(self, symbol: str, price: float, volume: int = 0, timestamp: str = None):
        """
        Update price and volume for a stock. Shifts all 7 snapshots.

        Args:
            symbol: Stock symbol
            price: Current price
            volume: Current trading volume
            timestamp: ISO format timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        if symbol not in self.cache:
            # First time seeing this stock
            self.cache[symbol] = {
                "current": {"price": price, "volume": volume, "timestamp": timestamp},
                "previous": None,
                "previous2": None,
                "previous3": None,
                "previous4": None,
                "previous5": None,
                "previous6": None
            }
        else:
            # Shift all snapshots: prev6 <- prev5 <- ... <- prev <- current <- new
            self.cache[symbol]["previous6"] = self.cache[symbol].get("previous5")
            self.cache[symbol]["previous5"] = self.cache[symbol].get("previous4")
            self.cache[symbol]["previous4"] = self.cache[symbol].get("previous3")
            self.cache[symbol]["previous3"] = self.cache[symbol].get("previous2")
            self.cache[symbol]["previous2"] = self.cache[symbol].get("previous")
            self.cache[symbol]["previous"] = self.cache[symbol]["current"]
            self.cache[symbol]["current"] = {"price": price, "volume": volume, "timestamp": timestamp}

        self._save_cache()

    def get_prices(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current and 10-minute-ago prices for a stock
        Only returns historical price if it's from the same day as current price

        Returns:
            Tuple of (current_price, price_10min_ago) or (None, None) if not found
            Returns (current_price, None) if historical price is from a different day
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous2 = self.cache[symbol].get("previous2")  # 10 minutes ago

        current_price = current["price"] if current else None

        # Validate same-day timestamps to prevent cross-day comparisons
        if current and previous2:
            current_timestamp = current.get("timestamp")
            previous2_timestamp = previous2.get("timestamp")

            if current_timestamp and previous2_timestamp:
                if self._is_same_day(current_timestamp, previous2_timestamp):
                    previous2_price = previous2["price"]
                else:
                    logger.debug(f"{symbol}: Skipping 10-min comparison - timestamps from different days")
                    previous2_price = None
            else:
                previous2_price = previous2["price"] if previous2 else None
        else:
            previous2_price = None

        return current_price, previous2_price

    def get_prices_5min(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current and 5-minute-ago prices for a stock (rapid detection)
        Only returns historical price if it's from the same day as current price

        Returns:
            Tuple of (current_price, price_5min_ago) or (None, None) if not found
            Returns (current_price, None) if historical price is from a different day
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous = self.cache[symbol].get("previous")  # 5 minutes ago

        current_price = current["price"] if current else None

        # Validate same-day timestamps to prevent cross-day comparisons
        if current and previous:
            current_timestamp = current.get("timestamp")
            previous_timestamp = previous.get("timestamp")

            if current_timestamp and previous_timestamp:
                if self._is_same_day(current_timestamp, previous_timestamp):
                    previous_price = previous["price"]
                else:
                    logger.debug(f"{symbol}: Skipping 5-min comparison - timestamps from different days")
                    previous_price = None
            else:
                previous_price = previous["price"] if previous else None
        else:
            previous_price = None

        return current_price, previous_price

    def get_price_30min(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current and 30-minute-ago prices for a stock
        Only returns historical price if it's from the same day as current price

        Returns:
            Tuple of (current_price, price_30min_ago) or (None, None) if not found
            Returns (current_price, None) if historical price is from a different day
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous6 = self.cache[symbol].get("previous6")  # 30 minutes ago

        current_price = current["price"] if current else None

        # Validate same-day timestamps to prevent cross-day comparisons
        if current and previous6:
            current_timestamp = current.get("timestamp")
            previous6_timestamp = previous6.get("timestamp")

            if current_timestamp and previous6_timestamp:
                if self._is_same_day(current_timestamp, previous6_timestamp):
                    previous6_price = previous6["price"]
                else:
                    logger.debug(f"{symbol}: Skipping 30-min comparison - timestamps from different days")
                    previous6_price = None
            else:
                previous6_price = previous6["price"] if previous6 else None
        else:
            previous6_price = None

        return current_price, previous6_price

    def get_volume_data(self, symbol: str) -> Dict:
        """
        Get volume data for a stock (DEPRECATED - use timeframe-specific methods)
        This method is kept for backward compatibility but returns averaged data

        Returns:
            Dict with current_volume, avg_volume, and volume_spike flag
        """
        if symbol not in self.cache:
            return {"current_volume": 0, "avg_volume": 0, "volume_spike": False}

        # Get all available volumes
        volumes = []
        for key in ["previous6", "previous5", "previous4", "previous3", "previous2", "previous"]:
            snapshot = self.cache[symbol].get(key)
            if snapshot and "volume" in snapshot:
                volumes.append(snapshot["volume"])

        current = self.cache[symbol].get("current")
        current_volume = current.get("volume", 0) if current else 0

        # Calculate average from historical volumes
        avg_volume = sum(volumes) / len(volumes) if volumes else 0

        # Volume spike if current > 3x average (and we have enough data)
        volume_spike = False
        if len(volumes) >= 3 and avg_volume > 0:
            volume_spike = current_volume > (avg_volume * 3)

        return {
            "current_volume": current_volume,
            "avg_volume": avg_volume,
            "volume_spike": volume_spike,
            "historical_count": len(volumes)
        }

    def get_volume_data_5min(self, symbol: str) -> Dict:
        """
        Get volume data for 5-minute comparison
        Compares current volume with volume from 5 minutes ago (previous)

        Returns:
            Dict with current_volume, previous_volume, volume_change, and volume_spike flag
        """
        if symbol not in self.cache:
            return {
                "current_volume": 0,
                "previous_volume": 0,
                "avg_volume": 0,
                "volume_change": 0,
                "volume_spike": False
            }

        current = self.cache[symbol].get("current")
        previous = self.cache[symbol].get("previous")  # 5 minutes ago

        current_volume = current.get("volume", 0) if current else 0
        previous_volume = previous.get("volume", 0) if previous else 0

        # Calculate volume change
        volume_change = current_volume - previous_volume if previous_volume > 0 else 0

        # Volume spike if current > 2.5x previous (5-min comparison uses lower multiplier)
        volume_spike = False
        if previous_volume > 0:
            volume_spike = current_volume > (previous_volume * 2.5)

        return {
            "current_volume": current_volume,
            "previous_volume": previous_volume,
            "avg_volume": previous_volume,  # For compatibility with alert formatting
            "volume_change": volume_change,
            "volume_spike": volume_spike
        }

    def get_volume_data_10min(self, symbol: str) -> Dict:
        """
        Get volume data for 10-minute comparison
        Compares current volume with average of previous 2 snapshots (10 min window)

        Returns:
            Dict with current_volume, avg_volume, volume_change, and volume_spike flag
        """
        if symbol not in self.cache:
            return {
                "current_volume": 0,
                "previous_volume": 0,
                "avg_volume": 0,
                "volume_change": 0,
                "volume_spike": False
            }

        current = self.cache[symbol].get("current")
        previous = self.cache[symbol].get("previous")    # 5 min ago
        previous2 = self.cache[symbol].get("previous2")  # 10 min ago

        current_volume = current.get("volume", 0) if current else 0

        # Calculate average from previous 2 snapshots (5-min and 10-min ago)
        volumes = []
        if previous and "volume" in previous:
            volumes.append(previous["volume"])
        if previous2 and "volume" in previous2:
            volumes.append(previous2["volume"])

        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        volume_change = current_volume - avg_volume if avg_volume > 0 else 0

        # Volume spike if current > 2.5x average (10-min uses 2.5x)
        volume_spike = False
        if len(volumes) >= 2 and avg_volume > 0:
            volume_spike = current_volume > (avg_volume * 2.5)

        return {
            "current_volume": current_volume,
            "previous_volume": volumes[0] if volumes else 0,
            "avg_volume": avg_volume,
            "volume_change": volume_change,
            "volume_spike": volume_spike
        }

    def get_volume_data_30min(self, symbol: str) -> Dict:
        """
        Get volume data for 30-minute comparison
        Compares current volume with average of previous 6 snapshots (30 min window)

        Returns:
            Dict with current_volume, avg_volume, volume_change, and volume_spike flag
        """
        if symbol not in self.cache:
            return {
                "current_volume": 0,
                "previous_volume": 0,
                "avg_volume": 0,
                "volume_change": 0,
                "volume_spike": False
            }

        current = self.cache[symbol].get("current")
        current_volume = current.get("volume", 0) if current else 0

        # Get all available volumes from last 30 minutes
        volumes = []
        for key in ["previous", "previous2", "previous3", "previous4", "previous5", "previous6"]:
            snapshot = self.cache[symbol].get(key)
            if snapshot and "volume" in snapshot:
                volumes.append(snapshot["volume"])

        # Calculate average from historical volumes
        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        volume_change = current_volume - avg_volume if avg_volume > 0 else 0

        # Volume spike if current > 2.5x average (30-min uses 2.5x for consistency)
        volume_spike = False
        if len(volumes) >= 3 and avg_volume > 0:
            volume_spike = current_volume > (avg_volume * 2.5)

        return {
            "current_volume": current_volume,
            "previous_volume": volumes[0] if volumes else 0,
            "avg_volume": avg_volume,
            "volume_change": volume_change,
            "volume_spike": volume_spike
        }

    def has_previous_price(self, symbol: str) -> bool:
        """Check if we have a 10-minute-ago price to compare against"""
        if symbol not in self.cache:
            return False
        return self.cache[symbol].get("previous2") is not None

    def has_30min_price(self, symbol: str) -> bool:
        """Check if we have a 30-minute-ago price to compare against"""
        if symbol not in self.cache:
            return False
        return self.cache[symbol].get("previous6") is not None

    def clear_cache(self):
        """Clear all cached data"""
        self.cache = {}
        self._save_cache()
