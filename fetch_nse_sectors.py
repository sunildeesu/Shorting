#!/usr/bin/env python3
"""
Fetch stock sector classifications from NSE
Updates stock_sectors.json with official NSE sector mappings
"""

import json
import requests
import time
import logging
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NSESectorFetcher:
    """Fetches sector classifications from NSE"""

    def __init__(self):
        self.base_url = "https://www.nseindia.com"
        self.session = requests.Session()

        # NSE requires headers to prevent blocking
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        self.session.headers.update(self.headers)

    def _get_cookies(self):
        """Get cookies from NSE homepage"""
        try:
            response = self.session.get(self.base_url, timeout=10)
            return True
        except Exception as e:
            logger.error(f"Failed to get NSE cookies: {e}")
            return False

    def fetch_stock_info(self, symbol: str) -> Optional[Dict]:
        """
        Fetch stock information including sector from NSE

        Args:
            symbol: Stock symbol (without .NS suffix)

        Returns:
            Dict with stock info including sector, or None if failed
        """
        try:
            # Get cookies first
            if not hasattr(self, '_cookies_fetched'):
                self._get_cookies()
                self._cookies_fetched = True
                time.sleep(1)

            # NSE API endpoint for stock quote
            url = f"{self.base_url}/api/quote-equity?symbol={symbol}"

            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()

                # Extract sector information
                info = data.get('info', {})
                industry = data.get('industryInfo', {})
                metadata = data.get('metadata', {})

                sector = (
                    info.get('sector') or
                    industry.get('sector') or
                    metadata.get('industry') or
                    'UNKNOWN'
                )

                return {
                    'symbol': symbol,
                    'sector': sector,
                    'industry': info.get('industry', ''),
                    'company_name': info.get('companyName', ''),
                }
            else:
                logger.warning(f"{symbol}: HTTP {response.status_code}")
                return None

        except Exception as e:
            logger.warning(f"{symbol}: Error fetching - {e}")
            return None

    def fetch_all_sectors(self, symbols: list) -> Dict[str, str]:
        """
        Fetch sector classifications for all symbols

        Args:
            symbols: List of stock symbols

        Returns:
            Dict mapping symbol to sector
        """
        sector_map = {}
        total = len(symbols)

        logger.info(f"Fetching sector data for {total} stocks from NSE...")

        for idx, symbol in enumerate(symbols, 1):
            logger.info(f"[{idx}/{total}] Fetching {symbol}...")

            info = self.fetch_stock_info(symbol)

            if info:
                sector = info['sector']
                industry = info['industry']

                # Normalize sector names to match our classification
                normalized_sector = self._normalize_sector(sector, industry)

                sector_map[symbol] = normalized_sector
                logger.info(f"  ✓ {symbol}: {sector} → {normalized_sector}")
            else:
                logger.warning(f"  ✗ {symbol}: Failed to fetch")
                sector_map[symbol] = "UNKNOWN"

            # Rate limiting - NSE blocks rapid requests
            time.sleep(2)

        return sector_map

    def _normalize_sector(self, nse_sector: str, industry: str = '') -> str:
        """
        Normalize NSE sector names to our sector classification

        Args:
            nse_sector: Sector name from NSE
            industry: Industry name for additional context

        Returns:
            Normalized sector name matching our classification
        """
        nse_sector = nse_sector.upper()
        industry = industry.upper()

        # Mapping from NSE sectors to our sectors
        sector_mapping = {
            # Banking & Financial Services
            'FINANCIAL SERVICES': 'FINANCIAL_SERVICES',
            'BANK': 'BANKING',
            'BANKING': 'BANKING',
            'FINANCE': 'FINANCIAL_SERVICES',

            # Technology
            'INFORMATION TECHNOLOGY': 'IT',
            'IT': 'IT',
            'SOFTWARE': 'IT',

            # Pharma & Healthcare
            'PHARMACEUTICAL': 'PHARMA',
            'PHARMA': 'PHARMA',
            'HEALTHCARE': 'PHARMA',
            'HOSPITAL': 'PHARMA',

            # Auto
            'AUTOMOBILE': 'AUTO',
            'AUTO': 'AUTO',
            'AUTO COMPONENTS': 'AUTO',

            # Energy
            'OIL & GAS': 'ENERGY',
            'ENERGY': 'ENERGY',
            'POWER': 'ENERGY',

            # Metal
            'METAL': 'METAL',
            'METALS': 'METAL',
            'MINING': 'METAL',
            'STEEL': 'METAL',

            # Infrastructure & Construction
            'CONSTRUCTION': 'INFRASTRUCTURE',
            'INFRASTRUCTURE': 'INFRASTRUCTURE',
            'CEMENT': 'INFRASTRUCTURE',

            # Capital Goods
            'CAPITAL GOODS': 'CAPITAL_GOODS',
            'ENGINEERING': 'CAPITAL_GOODS',
            'INDUSTRIAL MANUFACTURING': 'CAPITAL_GOODS',

            # FMCG
            'FMCG': 'FMCG',
            'CONSUMER GOODS': 'FMCG',
            'FOOD PRODUCTS': 'FMCG',
            'PERSONAL CARE': 'FMCG',

            # Consumer Durables
            'CONSUMER DURABLES': 'CONSUMER_DURABLES',
            'CONSUMER ELECTRONICS': 'CONSUMER_DURABLES',
            'HOUSEHOLD APPLIANCES': 'CONSUMER_DURABLES',

            # Telecom
            'TELECOM': 'TELECOM',
            'TELECOMMUNICATION': 'TELECOM',

            # Realty
            'REAL ESTATE': 'REALTY',
            'REALTY': 'REALTY',

            # Services
            'SERVICES': 'SERVICES',
            'MEDIA': 'SERVICES',
            'ENTERTAINMENT': 'SERVICES',
            'HOSPITALITY': 'SERVICES',
            'AVIATION': 'SERVICES',
        }

        # Check for exact matches first
        for nse_name, our_sector in sector_mapping.items():
            if nse_name in nse_sector or nse_name in industry:
                return our_sector

        # Special case for Defense stocks
        defense_keywords = ['DEFENSE', 'DEFENCE', 'AEROSPACE', 'EXPLOSIVES']
        for keyword in defense_keywords:
            if keyword in nse_sector or keyword in industry:
                return 'DEFENSE'

        # If no match found, return as-is
        logger.warning(f"Unknown sector: {nse_sector} / {industry}")
        return nse_sector.replace(' ', '_')


def load_fo_stocks() -> list:
    """Load F&O stock list"""
    try:
        with open('fo_stocks.json', 'r') as f:
            data = json.load(f)
            return data['stocks']
    except Exception as e:
        logger.error(f"Error loading F&O stocks: {e}")
        return []


def save_sector_mapping(sector_map: Dict[str, str], output_file: str = 'data/stock_sectors_nse.json'):
    """Save sector mapping to JSON file"""
    try:
        with open(output_file, 'w') as f:
            json.dump(sector_map, f, indent=2, sort_keys=True)
        logger.info(f"Sector mapping saved to {output_file}")
        return True
    except Exception as e:
        logger.error(f"Error saving sector mapping: {e}")
        return False


def compare_mappings(old_file: str, new_file: str):
    """Compare old and new sector mappings"""
    try:
        with open(old_file, 'r') as f:
            old_map = json.load(f)

        with open(new_file, 'r') as f:
            new_map = json.load(f)

        logger.info("\n" + "="*80)
        logger.info("COMPARISON: Manual vs NSE Sector Mappings")
        logger.info("="*80)

        differences = []
        for symbol in sorted(old_map.keys()):
            old_sector = old_map.get(symbol, 'MISSING')
            new_sector = new_map.get(symbol, 'MISSING')

            if old_sector != new_sector:
                differences.append((symbol, old_sector, new_sector))

        if differences:
            logger.info(f"\nFound {len(differences)} differences:\n")
            logger.info(f"{'Symbol':<15} {'Manual':<25} {'NSE':<25}")
            logger.info("-" * 65)
            for symbol, old, new in differences:
                logger.info(f"{symbol:<15} {old:<25} {new:<25}")
        else:
            logger.info("\n✓ No differences found - mappings match!")

        logger.info("\n" + "="*80)

    except Exception as e:
        logger.error(f"Error comparing mappings: {e}")


def main():
    """Main execution"""
    logger.info("NSE Sector Fetcher")
    logger.info("="*80)

    # Load F&O stocks
    fo_stocks = load_fo_stocks()
    if not fo_stocks:
        logger.error("No F&O stocks loaded. Exiting.")
        return

    logger.info(f"Loaded {len(fo_stocks)} F&O stocks")

    # Fetch sectors from NSE
    fetcher = NSESectorFetcher()
    sector_map = fetcher.fetch_all_sectors(fo_stocks)

    # Save to file
    output_file = 'data/stock_sectors_nse.json'
    if save_sector_mapping(sector_map, output_file):
        logger.info(f"\n✓ Sector mapping fetched and saved!")
        logger.info(f"  File: {output_file}")
        logger.info(f"  Stocks: {len(sector_map)}")

        # Count stocks per sector
        sector_counts = {}
        for sector in sector_map.values():
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

        logger.info(f"\nSector Distribution:")
        for sector, count in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {sector:<25} {count:3} stocks")

        # Compare with existing mapping
        if input("\nCompare with existing manual mapping? (y/n): ").lower() == 'y':
            compare_mappings('data/stock_sectors.json', output_file)

        # Ask to replace
        if input("\nReplace stock_sectors.json with NSE data? (y/n): ").lower() == 'y':
            import shutil
            shutil.copy('data/stock_sectors.json', 'data/stock_sectors_manual_backup.json')
            shutil.copy(output_file, 'data/stock_sectors.json')
            logger.info("✓ Replaced stock_sectors.json with NSE data")
            logger.info("✓ Backup saved to stock_sectors_manual_backup.json")

    logger.info("\n" + "="*80)
    logger.info("Done!")


if __name__ == "__main__":
    main()
