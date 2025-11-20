#!/usr/bin/env python3
"""
Fetch sector classifications from NSE Sectoral Indices
A stock can belong to multiple sectors based on index membership
"""

import json
import requests
import time
import logging
from typing import Dict, List, Set
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NSEIndexFetcher:
    """Fetches stock-to-sector mappings from NSE sectoral indices"""

    def __init__(self):
        self.base_url = "https://www.nseindiaapis.com/api/equity-stockIndices"
        self.session = requests.Session()

        # Headers to mimic browser
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.nseindia.com/',
            'Origin': 'https://www.nseindia.com',
        }

    def get_nse_indices(self) -> List[str]:
        """
        Get list of NSE sectoral indices to fetch

        Returns:
            List of index names
        """
        return [
            'NIFTY BANK',
            'NIFTY AUTO',
            'NIFTY FINANCIAL SERVICES',
            'NIFTY FMCG',
            'NIFTY IT',
            'NIFTY MEDIA',
            'NIFTY METAL',
            'NIFTY PHARMA',
            'NIFTY PSU BANK',
            'NIFTY PRIVATE BANK',
            'NIFTY REALTY',
            'NIFTY ENERGY',
            'NIFTY INFRASTRUCTURE',
            'NIFTY HEALTHCARE',
            'NIFTY CONSUMPTION',
            'NIFTY OIL & GAS',
            'NIFTY COMMODITIES',
            'NIFTY INDIA DEFENCE',
        ]

    def fetch_index_constituents(self, index_name: str) -> Set[str]:
        """
        Fetch constituent stocks of an NSE index

        Args:
            index_name: Name of the index (e.g., 'NIFTY BANK')

        Returns:
            Set of stock symbols in the index
        """
        try:
            # NSE index API endpoint
            url = f"https://www.nseindia.com/api/equity-stockIndices?index={index_name.replace(' ', '%20')}"

            response = self.session.get(url, headers=self.headers, timeout=15)

            if response.status_code == 200:
                data = response.json()
                stocks = set()

                # Extract stocks from data
                if 'data' in data:
                    for item in data['data']:
                        symbol = item.get('symbol', '')
                        if symbol and symbol != index_name:  # Exclude index itself
                            stocks.add(symbol)

                logger.info(f"  {index_name}: {len(stocks)} stocks")
                return stocks
            else:
                logger.warning(f"  {index_name}: HTTP {response.status_code}")
                return set()

        except Exception as e:
            logger.warning(f"  {index_name}: Error - {e}")
            return set()

    def fetch_all_sector_mappings(self) -> Dict[str, List[str]]:
        """
        Fetch all sector mappings from NSE indices

        Returns:
            Dict mapping stock symbol to list of sectors
        """
        logger.info("Fetching NSE Sectoral Indices...")
        logger.info("="*80)

        # Map index names to our sector names
        index_to_sector = {
            'NIFTY BANK': 'BANKING',
            'NIFTY PSU BANK': 'BANKING',
            'NIFTY PRIVATE BANK': 'BANKING',
            'NIFTY AUTO': 'AUTO',
            'NIFTY FINANCIAL SERVICES': 'FINANCIAL_SERVICES',
            'NIFTY FMCG': 'FMCG',
            'NIFTY IT': 'IT',
            'NIFTY MEDIA': 'SERVICES',
            'NIFTY METAL': 'METAL',
            'NIFTY PHARMA': 'PHARMA',
            'NIFTY HEALTHCARE': 'PHARMA',
            'NIFTY REALTY': 'REALTY',
            'NIFTY ENERGY': 'ENERGY',
            'NIFTY OIL & GAS': 'ENERGY',
            'NIFTY INFRASTRUCTURE': 'INFRASTRUCTURE',
            'NIFTY CONSUMPTION': 'FMCG',
            'NIFTY COMMODITIES': 'METAL',
            'NIFTY INDIA DEFENCE': 'DEFENSE',
        }

        # Stock to sectors mapping
        stock_sectors = defaultdict(set)

        # Fetch each index
        for index_name in self.get_nse_indices():
            logger.info(f"\nFetching: {index_name}")

            constituents = self.fetch_index_constituents(index_name)

            if constituents:
                sector = index_to_sector.get(index_name, index_name.replace('NIFTY ', ''))

                for stock in constituents:
                    stock_sectors[stock].add(sector)

            time.sleep(2)  # Rate limiting

        # Convert sets to sorted lists
        result = {stock: sorted(list(sectors)) for stock, sectors in stock_sectors.items()}

        logger.info("\n" + "="*80)
        logger.info(f"Total stocks mapped: {len(result)}")

        # Show multi-sector stocks
        multi_sector_stocks = {k: v for k, v in result.items() if len(v) > 1}
        logger.info(f"Stocks in multiple sectors: {len(multi_sector_stocks)}")

        if multi_sector_stocks:
            logger.info("\nSample multi-sector stocks:")
            for stock, sectors in sorted(multi_sector_stocks.items())[:10]:
                logger.info(f"  {stock}: {', '.join(sectors)}")

        return result


def fetch_from_moneycontrol():
    """
    Alternative: Fetch sector data from Moneycontrol
    Uses company info pages which include sector classification
    """
    import requests
    from bs4 import BeautifulSoup

    logger.info("Fetching sector data from Moneycontrol...")

    # This is a more reliable alternative if NSE blocks us
    # Moneycontrol has sector information on each stock page
    # Format: https://www.moneycontrol.com/india/stockpricequote/[sector]/[company]/[code]

    # For now, we'll implement the index-based approach first
    pass


def load_fo_stocks() -> List[str]:
    """Load F&O stock list"""
    try:
        with open('fo_stocks.json', 'r') as f:
            data = json.load(f)
            return data['stocks']
    except Exception as e:
        logger.error(f"Error loading F&O stocks: {e}")
        return []


def filter_fo_stocks(all_mappings: Dict[str, List[str]], fo_stocks: List[str]) -> Dict[str, List[str]]:
    """
    Filter sector mappings to only include F&O stocks

    Args:
        all_mappings: All stock-to-sector mappings
        fo_stocks: List of F&O stocks

    Returns:
        Filtered mappings for F&O stocks only
    """
    filtered = {}

    for stock in fo_stocks:
        if stock in all_mappings:
            filtered[stock] = all_mappings[stock]
        else:
            logger.warning(f"{stock}: Not found in any NSE index")
            filtered[stock] = ["UNKNOWN"]

    return filtered


def save_multi_sector_mapping(mappings: Dict[str, List[str]], output_file: str = 'data/stock_sectors_multi.json'):
    """Save multi-sector mapping to JSON file"""
    try:
        with open(output_file, 'w') as f:
            json.dump(mappings, f, indent=2, sort_keys=True)
        logger.info(f"\n✓ Multi-sector mapping saved to {output_file}")
        return True
    except Exception as e:
        logger.error(f"Error saving mapping: {e}")
        return False


def analyze_sector_distribution(mappings: Dict[str, List[str]]):
    """Analyze and display sector distribution"""
    logger.info("\n" + "="*80)
    logger.info("SECTOR DISTRIBUTION ANALYSIS")
    logger.info("="*80)

    # Count stocks per sector (including overlaps)
    sector_counts = defaultdict(int)
    for sectors in mappings.values():
        for sector in sectors:
            sector_counts[sector] += 1

    logger.info("\nStocks per Sector:")
    for sector, count in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {sector:<25} {count:3} stocks")

    # Multi-sector distribution
    multi_sector_count = defaultdict(int)
    for sectors in mappings.values():
        count = len(sectors)
        multi_sector_count[count] += 1

    logger.info("\nSector Membership Distribution:")
    for count, stocks in sorted(multi_sector_count.items()):
        logger.info(f"  {count} sector(s): {stocks:3} stocks")

    # Show stocks in most sectors
    most_sectors = sorted(
        [(stock, sectors) for stock, sectors in mappings.items()],
        key=lambda x: len(x[1]),
        reverse=True
    )[:10]

    logger.info("\nTop 10 stocks with most sector memberships:")
    for stock, sectors in most_sectors:
        logger.info(f"  {stock}: {len(sectors)} sectors - {', '.join(sectors)}")


def compare_with_current_mapping(multi_sector_file: str):
    """Compare multi-sector mapping with current single-sector mapping"""
    try:
        # Load current single-sector mapping
        with open('data/stock_sectors.json', 'r') as f:
            single_mapping = json.load(f)

        # Load multi-sector mapping
        with open(multi_sector_file, 'r') as f:
            multi_mapping = json.load(f)

        logger.info("\n" + "="*80)
        logger.info("COMPARISON: Current vs NSE Index-Based Mapping")
        logger.info("="*80)

        mismatches = []

        for stock in sorted(single_mapping.keys()):
            current_sector = single_mapping[stock]
            nse_sectors = multi_mapping.get(stock, [])

            # Check if current sector is in NSE sectors
            if current_sector not in nse_sectors and nse_sectors != ["UNKNOWN"]:
                mismatches.append((stock, current_sector, nse_sectors))

        if mismatches:
            logger.info(f"\nFound {len(mismatches)} potential misclassifications:\n")
            logger.info(f"{'Stock':<15} {'Current':<20} {'NSE Indices':<50}")
            logger.info("-" * 85)

            for stock, current, nse in mismatches[:20]:  # Show first 20
                nse_str = ', '.join(nse)
                logger.info(f"{stock:<15} {current:<20} {nse_str:<50}")

            if len(mismatches) > 20:
                logger.info(f"\n... and {len(mismatches) - 20} more")
        else:
            logger.info("\n✓ All current mappings match NSE index memberships!")

    except Exception as e:
        logger.error(f"Error comparing mappings: {e}")


def main():
    """Main execution"""
    logger.info("NSE Index-Based Sector Fetcher")
    logger.info("Fetches multi-sector memberships from NSE sectoral indices")
    logger.info("="*80)

    # Fetch from NSE indices
    fetcher = NSEIndexFetcher()
    all_mappings = fetcher.fetch_all_sector_mappings()

    if not all_mappings:
        logger.error("Failed to fetch sector mappings from NSE")
        return

    # Load F&O stocks
    fo_stocks = load_fo_stocks()
    if not fo_stocks:
        logger.error("Failed to load F&O stocks")
        return

    # Filter to F&O stocks only
    fo_mappings = filter_fo_stocks(all_mappings, fo_stocks)

    # Save multi-sector mapping
    output_file = 'data/stock_sectors_multi.json'
    if not save_multi_sector_mapping(fo_mappings, output_file):
        return

    # Analyze distribution
    analyze_sector_distribution(fo_mappings)

    # Compare with current single-sector mapping
    compare_with_current_mapping(output_file)

    # Ask user what to do
    print("\n" + "="*80)
    print("OPTIONS:")
    print("1. Keep current single-sector mapping (stock_sectors.json)")
    print("2. Use multi-sector mapping for future analysis")
    print("3. Show detailed comparison")
    print("\nNote: Multi-sector support requires code changes to sector_analyzer.py")

    choice = input("\nEnter choice (1/2/3): ").strip()

    if choice == '3':
        # Show detailed comparison for specific stocks
        print("\nEnter stock symbols to compare (comma-separated, or 'all'): ", end='')
        stocks_input = input().strip()

        if stocks_input.lower() == 'all':
            stocks_to_check = fo_stocks
        else:
            stocks_to_check = [s.strip() for s in stocks_input.split(',')]

        with open('data/stock_sectors.json', 'r') as f:
            single = json.load(f)

        print(f"\n{'Stock':<15} {'Current':<20} {'NSE Indices'}")
        print("-" * 70)

        for stock in stocks_to_check:
            current = single.get(stock, 'NOT MAPPED')
            nse = ', '.join(fo_mappings.get(stock, ['NOT FOUND']))
            print(f"{stock:<15} {current:<20} {nse}")

    elif choice == '2':
        print("\n⚠️  Multi-sector support requires updating:")
        print("  - sector_analyzer.py (to handle list of sectors)")
        print("  - sector_manager.py (to support multi-sector queries)")
        print("  - Reports and alerts (to show all sectors)")
        print("\nWould you like me to implement multi-sector support? (y/n): ", end='')

        if input().strip().lower() == 'y':
            print("\n✓ Multi-sector data saved to:", output_file)
            print("  I can now update the codebase to support multiple sectors per stock.")
        else:
            print("\n✓ Multi-sector data saved for reference")
            print("  You can use it later when needed")

    logger.info("\n" + "="*80)
    logger.info("Done!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\nAborted by user")
    except Exception as e:
        logger.error(f"\nError: {e}", exc_info=True)
