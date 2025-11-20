"""
Sector Manager - Load and query stock sector classifications
Provides fast lookup of sector mappings without repeated file I/O
"""

import json
import os
import logging
from typing import Optional, List, Dict, Set
from collections import defaultdict

logger = logging.getLogger(__name__)

class SectorManager:
    """Manages stock-to-sector mappings with in-memory caching"""

    def __init__(self, sectors_file: str = "data/stock_sectors.json"):
        """
        Initialize sector manager with sector mappings

        Args:
            sectors_file: Path to JSON file containing stock-to-sector mappings
        """
        self.sectors_file = sectors_file
        self.stock_to_sector: Dict[str, str] = {}
        self.sector_to_stocks: Dict[str, Set[str]] = defaultdict(set)
        self.all_sectors: Set[str] = set()

        # Load mappings on initialization
        self._load_sectors()

    def _load_sectors(self):
        """Load sector mappings from JSON file"""
        try:
            if not os.path.exists(self.sectors_file):
                logger.error(f"Sector mappings file not found: {self.sectors_file}")
                return

            with open(self.sectors_file, 'r') as f:
                self.stock_to_sector = json.load(f)

            # Build reverse mapping (sector -> stocks)
            for stock, sector in self.stock_to_sector.items():
                self.sector_to_stocks[sector].add(stock)
                self.all_sectors.add(sector)

            logger.info(f"Loaded {len(self.stock_to_sector)} stock-to-sector mappings")
            logger.info(f"Total sectors: {len(self.all_sectors)}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in sector mappings file: {e}")
        except Exception as e:
            logger.error(f"Error loading sector mappings: {e}")

    def get_sector(self, symbol: str) -> Optional[str]:
        """
        Get the sector for a given stock symbol

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")

        Returns:
            Sector name or None if not found
        """
        return self.stock_to_sector.get(symbol)

    def get_stocks_in_sector(self, sector: str) -> List[str]:
        """
        Get all stocks in a given sector

        Args:
            sector: Sector name (e.g., "BANKING")

        Returns:
            List of stock symbols in the sector
        """
        return list(self.sector_to_stocks.get(sector, set()))

    def get_all_sectors(self) -> List[str]:
        """
        Get list of all sectors

        Returns:
            List of sector names
        """
        return sorted(list(self.all_sectors))

    def get_sector_count(self, sector: str) -> int:
        """
        Get number of stocks in a sector

        Args:
            sector: Sector name

        Returns:
            Number of stocks in the sector
        """
        return len(self.sector_to_stocks.get(sector, set()))

    def get_sector_stats(self) -> Dict[str, int]:
        """
        Get statistics about all sectors

        Returns:
            Dict mapping sector names to stock counts
        """
        return {sector: len(stocks) for sector, stocks in self.sector_to_stocks.items()}

    def is_valid_sector(self, sector: str) -> bool:
        """
        Check if a sector exists

        Args:
            sector: Sector name

        Returns:
            True if sector exists, False otherwise
        """
        return sector in self.all_sectors

    def reload(self):
        """Reload sector mappings from file"""
        self.stock_to_sector.clear()
        self.sector_to_stocks.clear()
        self.all_sectors.clear()
        self._load_sectors()

# Global singleton instance
_sector_manager_instance: Optional[SectorManager] = None

def get_sector_manager() -> SectorManager:
    """
    Get singleton instance of SectorManager

    Returns:
        SectorManager instance
    """
    global _sector_manager_instance
    if _sector_manager_instance is None:
        _sector_manager_instance = SectorManager()
    return _sector_manager_instance
