import json
import os
from datetime import datetime
from typing import Dict, Optional, Tuple
import config

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

        Returns:
            Tuple of (current_price, price_10min_ago) or (None, None) if not found
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous2 = self.cache[symbol].get("previous2")  # 10 minutes ago

        current_price = current["price"] if current else None
        previous2_price = previous2["price"] if previous2 else None

        return current_price, previous2_price

    def get_prices_5min(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current and 5-minute-ago prices for a stock (rapid detection)

        Returns:
            Tuple of (current_price, price_5min_ago) or (None, None) if not found
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous = self.cache[symbol].get("previous")  # 5 minutes ago

        current_price = current["price"] if current else None
        previous_price = previous["price"] if previous else None

        return current_price, previous_price

    def get_price_30min(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current and 30-minute-ago prices for a stock

        Returns:
            Tuple of (current_price, price_30min_ago) or (None, None) if not found
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous6 = self.cache[symbol].get("previous6")  # 30 minutes ago

        current_price = current["price"] if current else None
        previous6_price = previous6["price"] if previous6 else None

        return current_price, previous6_price

    def get_volume_data(self, symbol: str) -> Dict:
        """
        Get volume data for a stock

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
