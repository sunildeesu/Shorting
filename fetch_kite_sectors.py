#!/usr/bin/env python3
"""
Fetch stock sector classifications from Kite Connect
Updates stock_sectors.json with Kite instrument data
"""

import json
import logging
from typing import Dict
from kiteconnect import KiteConnect
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class KiteSectorFetcher:
    """Fetches sector classifications from Kite Connect"""

    def __init__(self):
        if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
            raise ValueError("Kite API credentials not configured")

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

    def fetch_all_sectors(self, symbols: list) -> Dict[str, str]:
        """
        Fetch sector classifications for all symbols using Kite instruments

        Args:
            symbols: List of stock symbols

        Returns:
            Dict mapping symbol to sector
        """
        logger.info("Fetching instruments from Kite Connect...")

        try:
            # Fetch all NSE instruments
            instruments = self.kite.instruments("NSE")
            logger.info(f"Fetched {len(instruments)} NSE instruments")

            # Build mapping
            sector_map = {}

            for symbol in symbols:
                # Find instrument for this symbol
                matching = [inst for inst in instruments
                           if inst['tradingsymbol'] == symbol and inst['segment'] == 'NSE']

                if matching:
                    inst = matching[0]
                    name = inst.get('name', '')

                    # Kite doesn't directly provide sector, but we can infer from name
                    # or use a mapping based on common knowledge
                    sector = self._infer_sector_from_name(symbol, name)
                    sector_map[symbol] = sector

                    logger.info(f"  {symbol}: {name} → {sector}")
                else:
                    logger.warning(f"  {symbol}: Not found in instruments")
                    sector_map[symbol] = "UNKNOWN"

            return sector_map

        except Exception as e:
            logger.error(f"Error fetching from Kite: {e}")
            return {}

    def _infer_sector_from_name(self, symbol: str, name: str) -> str:
        """
        Infer sector from stock symbol and company name

        This is a fallback since Kite doesn't provide direct sector info.
        We'll use our existing manual mappings as the authoritative source.
        """
        # Load existing manual mapping
        try:
            with open('data/stock_sectors.json', 'r') as f:
                manual_mapping = json.load(f)
                if symbol in manual_mapping:
                    return manual_mapping[symbol]
        except:
            pass

        # Basic inference from name (very limited)
        name_lower = name.lower()

        if 'bank' in name_lower:
            return 'BANKING'
        elif 'pharma' in name_lower or 'health' in name_lower:
            return 'PHARMA'
        elif 'tech' in name_lower or 'infotech' in name_lower:
            return 'IT'
        elif any(word in name_lower for word in ['auto', 'motor', 'vehicle']):
            return 'AUTO'
        elif any(word in name_lower for word in ['oil', 'gas', 'power', 'energy']):
            return 'ENERGY'
        elif any(word in name_lower for word in ['metal', 'steel', 'coal']):
            return 'METAL'

        return 'UNKNOWN'


def fetch_from_screener():
    """
    Alternative: Fetch sector data from Screener.in
    This is more reliable than NSE direct access
    """
    import requests
    from bs4 import BeautifulSoup

    logger.info("Fetching sector data from Screener.in...")

    sector_map = {}

    # Load F&O stocks
    with open('fo_stocks.json', 'r') as f:
        fo_stocks = json.load(f)['stocks']

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    for idx, symbol in enumerate(fo_stocks, 1):
        try:
            url = f"https://www.screener.in/company/{symbol}/"
            response = session.get(url, timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # Find sector in the page
                # Screener shows: "Sector: XYZ"
                sector_elem = soup.find('a', {'href': lambda x: x and '/screens/' in x})
                if sector_elem:
                    sector_text = sector_elem.text.strip()
                    normalized_sector = normalize_sector_name(sector_text)
                    sector_map[symbol] = normalized_sector
                    logger.info(f"[{idx}/{len(fo_stocks)}] {symbol}: {sector_text} → {normalized_sector}")
                else:
                    logger.warning(f"[{idx}/{len(fo_stocks)}] {symbol}: Sector not found")
                    sector_map[symbol] = "UNKNOWN"
            else:
                logger.warning(f"[{idx}/{len(fo_stocks)}] {symbol}: HTTP {response.status_code}")
                sector_map[symbol] = "UNKNOWN"

            import time
            time.sleep(2)  # Rate limiting

        except Exception as e:
            logger.error(f"[{idx}/{len(fo_stocks)}] {symbol}: Error - {e}")
            sector_map[symbol] = "UNKNOWN"

    return sector_map


def normalize_sector_name(screener_sector: str) -> str:
    """
    Normalize Screener.in sector names to our classification

    Args:
        screener_sector: Sector name from Screener.in

    Returns:
        Normalized sector name
    """
    screener_sector = screener_sector.upper()

    mapping = {
        'BANKS': 'BANKING',
        'FINANCE': 'FINANCIAL_SERVICES',
        'NBFC': 'FINANCIAL_SERVICES',
        'INSURANCE': 'FINANCIAL_SERVICES',

        'IT SERVICES': 'IT',
        'IT - SOFTWARE': 'IT',
        'COMPUTERS - SOFTWARE': 'IT',

        'PHARMACEUTICALS': 'PHARMA',
        'HOSPITALS': 'PHARMA',
        'HEALTHCARE': 'PHARMA',

        'AUTOMOBILES': 'AUTO',
        'AUTO ANCILLARIES': 'AUTO',
        'AUTO COMPONENTS': 'AUTO',

        'OIL & GAS': 'ENERGY',
        'POWER': 'ENERGY',
        'REFINERIES': 'ENERGY',

        'METALS': 'METAL',
        'STEEL': 'METAL',
        'MINING': 'METAL',
        'ALUMINIUM': 'METAL',

        'CONSTRUCTION': 'INFRASTRUCTURE',
        'CEMENT': 'INFRASTRUCTURE',
        'REAL ESTATE': 'REALTY',

        'CAPITAL GOODS': 'CAPITAL_GOODS',
        'ENGINEERING': 'CAPITAL_GOODS',
        'INDUSTRIAL PRODUCTS': 'CAPITAL_GOODS',

        'FMCG': 'FMCG',
        'CONSUMER GOODS': 'FMCG',
        'FOOD PRODUCTS': 'FMCG',

        'CONSUMER DURABLES': 'CONSUMER_DURABLES',
        'HOME APPLIANCES': 'CONSUMER_DURABLES',

        'TELECOM': 'TELECOM',
        'TELECOMMUNICATIONS': 'TELECOM',

        'MEDIA': 'SERVICES',
        'ENTERTAINMENT': 'SERVICES',
        'AVIATION': 'SERVICES',
        'LOGISTICS': 'SERVICES',
    }

    # Check for defense keywords
    if any(word in screener_sector for word in ['DEFENSE', 'DEFENCE', 'AEROSPACE']):
        return 'DEFENSE'

    # Check mapping
    for screener_name, our_sector in mapping.items():
        if screener_name in screener_sector:
            return our_sector

    # Return as-is if no match
    return screener_sector.replace(' ', '_').replace('-', '_')


def main():
    """Main execution"""
    logger.info("Sector Data Fetcher")
    logger.info("="*80)

    print("\nChoose data source:")
    print("1. Screener.in (Recommended - most reliable)")
    print("2. Kite Connect (Limited sector info)")

    choice = input("\nEnter choice (1/2): ").strip()

    if choice == '1':
        sector_map = fetch_from_screener()
    elif choice == '2':
        fetcher = KiteSectorFetcher()
        with open('fo_stocks.json', 'r') as f:
            fo_stocks = json.load(f)['stocks']
        sector_map = fetcher.fetch_all_sectors(fo_stocks)
    else:
        logger.error("Invalid choice")
        return

    if not sector_map:
        logger.error("No sector data fetched")
        return

    # Save to file
    output_file = 'data/stock_sectors_fetched.json'
    with open(output_file, 'w') as f:
        json.dump(sector_map, f, indent=2, sort_keys=True)

    logger.info(f"\n✓ Sector data saved to {output_file}")

    # Count stocks per sector
    sector_counts = {}
    for sector in sector_map.values():
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    logger.info(f"\nSector Distribution:")
    for sector, count in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {sector:<25} {count:3} stocks")

    # Compare with existing
    print("\nCompare with existing manual mapping? (y/n): ", end='')
    if input().lower() == 'y':
        from fetch_nse_sectors import compare_mappings
        compare_mappings('data/stock_sectors.json', output_file)

    # Ask to replace
    print("\nReplace stock_sectors.json with fetched data? (y/n): ", end='')
    if input().lower() == 'y':
        import shutil
        shutil.copy('data/stock_sectors.json', 'data/stock_sectors_manual_backup.json')
        shutil.copy(output_file, 'data/stock_sectors.json')
        logger.info("✓ Replaced stock_sectors.json")
        logger.info("✓ Backup saved to stock_sectors_manual_backup.json")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nAborted by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
