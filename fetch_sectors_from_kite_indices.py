#!/usr/bin/env python3
"""
Fetch sector memberships using Kite Connect
Maps stocks to sectors based on their presence in Nifty sectoral indices
"""

import json
import logging
from typing import Dict, List, Set
from collections import defaultdict
from kiteconnect import KiteConnect
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_nifty_index_instruments(kite: KiteConnect) -> Dict[str, List[str]]:
    """
    Get all instruments and map stocks to indices based on instrument data

    Returns:
        Dict mapping index names to list of stock symbols
    """
    logger.info("Fetching all instruments from Kite...")

    try:
        # Fetch all instruments
        instruments = kite.instruments()

        # Nifty sectoral indices
        sectoral_indices = {
            'NIFTY BANK': 'BANKING',
            'NIFTY AUTO': 'AUTO',
            'NIFTY FIN SERVICE': 'FINANCIAL_SERVICES',
            'NIFTY FMCG': 'FMCG',
            'NIFTY IT': 'IT',
            'NIFTY MEDIA': 'SERVICES',
            'NIFTY METAL': 'METAL',
            'NIFTY PHARMA': 'PHARMA',
            'NIFTY PSU BANK': 'BANKING',
            'NIFTY PVT BANK': 'BANKING',
            'NIFTY REALTY': 'REALTY',
            'NIFTY ENERGY': 'ENERGY',
            'NIFTY INFRA': 'INFRASTRUCTURE',
            'NIFTY HEALTHCARE': 'PHARMA',
            'NIFTY CONSR DURBL': 'CONSUMER_DURABLES',
            'NIFTY OIL AND GAS': 'ENERGY',
            'NIFTY COMMODITIES': 'METAL',
        }

        # Map stocks to sectors
        stock_sectors = defaultdict(set)

        # Process instruments
        for inst in instruments:
            # Look for index instruments (they contain constituent info)
            if inst['exchange'] == 'NSE' and inst['segment'] == 'INDICES':
                name = inst['tradingsymbol']

                # Check if this is a sectoral index we care about
                for index_name, sector in sectoral_indices.items():
                    if index_name in name:
                        logger.info(f"Found index: {name} → {sector}")

        # Alternative: Use NSE equity instruments and classify manually
        logger.info("\nClassifying NSE equity instruments...")

        equity_instruments = [inst for inst in instruments
                             if inst['exchange'] == 'NSE' and inst['segment'] == 'NSE']

        logger.info(f"Found {len(equity_instruments)} NSE equity instruments")

        # For each stock, we'll need to classify based on name or use existing mapping
        # Since Kite doesn't provide direct index membership, let's use a hybrid approach

        return stock_sectors

    except Exception as e:
        logger.error(f"Error fetching instruments: {e}")
        return {}


def download_nse_index_files_manually():
    """
    Guide to manually download NSE index composition files
    """
    logger.info("="*80)
    logger.info("MANUAL DOWNLOAD GUIDE - NSE Index Compositions")
    logger.info("="*80)

    indices_info = [
        ("Nifty Bank", "https://www.niftyindices.com/IndexConstituent/ind_niftybanklist.csv"),
        ("Nifty Auto", "https://www.niftyindices.com/IndexConstituent/ind_niftyautolist.csv"),
        ("Nifty Financial Services", "https://www.niftyindices.com/IndexConstituent/ind_niftyfinancelist.csv"),
        ("Nifty FMCG", "https://www.niftyindices.com/IndexConstituent/ind_niftyfmcglist.csv"),
        ("Nifty IT", "https://www.niftyindices.com/IndexConstituent/ind_niftyitlist.csv"),
        ("Nifty Media", "https://www.niftyindices.com/IndexConstituent/ind_niftymedialist.csv"),
        ("Nifty Metal", "https://www.niftyindices.com/IndexConstituent/ind_niftymetallist.csv"),
        ("Nifty Pharma", "https://www.niftyindices.com/IndexConstituent/ind_niftypharmalist.csv"),
        ("Nifty Realty", "https://www.niftyindices.com/IndexConstituent/ind_niftyrealtylist.csv"),
        ("Nifty Energy", "https://www.niftyindices.com/IndexConstituent/ind_niftyenergylist.csv"),
        ("Nifty Infrastructure", "https://www.niftyindices.com/IndexConstituent/ind_niftyinfralist.csv"),
        ("Nifty India Defence", "https://www.niftyindices.com/IndexConstituent/ind_niftyindiadefencelist.csv"),
    ]

    print("\nPlease download these CSVs manually from:")
    print("https://www.niftyindices.com/reports/index-constituents")
    print("\nOr use these direct links:\n")

    for name, url in indices_info:
        print(f"{name}:")
        print(f"  {url}\n")

    print("Save all files to: data/nse_indices/")
    print("\nAfter downloading, run: ./venv/bin/python3 parse_nse_index_csvs.py")


def parse_index_csv(filepath: str) -> Set[str]:
    """Parse NSE index CSV file to extract stock symbols"""
    import csv

    stocks = set()

    try:
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Symbol is usually in 'Symbol' column
                symbol = row.get('Symbol', '').strip()
                if symbol:
                    stocks.add(symbol)

        return stocks

    except Exception as e:
        logger.error(f"Error parsing {filepath}: {e}")
        return set()


def parse_all_index_csvs() -> Dict[str, List[str]]:
    """
    Parse all downloaded NSE index CSV files

    Returns:
        Dict mapping stock symbols to list of sectors
    """
    import os
    import glob

    indices_dir = "data/nse_indices"

    if not os.path.exists(indices_dir):
        logger.error(f"Directory {indices_dir} not found!")
        logger.error("Please download NSE index CSV files first")
        download_nse_index_files_manually()
        return {}

    # Map CSV filenames to sectors
    file_to_sector = {
        'niftybanklist.csv': 'BANKING',
        'niftyautolist.csv': 'AUTO',
        'niftyfinancelist.csv': 'FINANCIAL_SERVICES',
        'niftyfmcglist.csv': 'FMCG',
        'niftyitlist.csv': 'IT',
        'niftymedialist.csv': 'SERVICES',
        'niftymetallist.csv': 'METAL',
        'niftypharmalist.csv': 'PHARMA',
        'niftyrealtylist.csv': 'REALTY',
        'niftyenergylist.csv': 'ENERGY',
        'niftyinfralist.csv': 'INFRASTRUCTURE',
        'niftyindiadefencelist.csv': 'DEFENSE',
    }

    stock_sectors = defaultdict(set)

    # Parse each CSV file
    csv_files = glob.glob(os.path.join(indices_dir, "*.csv"))

    if not csv_files:
        logger.warning(f"No CSV files found in {indices_dir}")
        download_nse_index_files_manually()
        return {}

    logger.info(f"Found {len(csv_files)} CSV files")

    for filepath in csv_files:
        filename = os.path.basename(filepath).lower()

        # Find matching sector
        sector = None
        for pattern, sec in file_to_sector.items():
            if pattern in filename:
                sector = sec
                break

        if not sector:
            logger.warning(f"Unknown file: {filename}")
            continue

        # Parse CSV
        stocks = parse_index_csv(filepath)

        if stocks:
            logger.info(f"{os.path.basename(filepath)}: {len(stocks)} stocks → {sector}")

            for stock in stocks:
                stock_sectors[stock].add(sector)

    # Convert sets to sorted lists
    result = {stock: sorted(list(sectors)) for stock, sectors in stock_sectors.items()}

    return result


def main():
    """Main execution"""
    logger.info("Sector Fetcher - NSE Index Based (Multi-Sector Support)")
    logger.info("="*80)

    print("\nOptions:")
    print("1. Parse downloaded NSE index CSV files")
    print("2. Show download guide for NSE index files")
    print("3. Use existing single-sector mapping")

    choice = input("\nEnter choice (1/2/3): ").strip()

    if choice == '2':
        download_nse_index_files_manually()
        return

    elif choice == '1':
        # Parse CSV files
        stock_sectors = parse_all_index_csvs()

        if not stock_sectors:
            return

        # Load F&O stocks
        with open('fo_stocks.json', 'r') as f:
            fo_stocks = json.load(f)['stocks']

        # Filter to F&O stocks
        fo_mappings = {}
        for stock in fo_stocks:
            if stock in stock_sectors:
                fo_mappings[stock] = stock_sectors[stock]
            else:
                logger.warning(f"{stock}: Not found in any NSE index")
                fo_mappings[stock] = ["UNKNOWN"]

        # Save multi-sector mapping
        output_file = 'data/stock_sectors_multi.json'
        with open(output_file, 'w') as f:
            json.dump(fo_mappings, f, indent=2, sort_keys=True)

        logger.info(f"\n✓ Multi-sector mapping saved to {output_file}")

        # Analyze
        sector_counts = defaultdict(int)
        for sectors in fo_mappings.values():
            for sector in sectors:
                sector_counts[sector] += 1

        logger.info("\nSector Distribution:")
        for sector, count in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {sector:<25} {count:3} stocks")

        # Multi-sector stocks
        multi = {k: v for k, v in fo_mappings.items() if len(v) > 1}
        logger.info(f"\n✓ Stocks in multiple sectors: {len(multi)}")

        if multi:
            logger.info("\nSample multi-sector stocks:")
            for stock, sectors in sorted(multi.items())[:15]:
                logger.info(f"  {stock:<15} → {', '.join(sectors)}")

        # Compare with current
        print("\nCompare with current single-sector mapping? (y/n): ", end='')
        if input().lower() == 'y':
            with open('data/stock_sectors.json', 'r') as f:
                current = json.load(f)

            mismatches = []
            for stock in sorted(current.keys()):
                cur_sector = current[stock]
                nse_sectors = fo_mappings.get(stock, [])

                if cur_sector not in nse_sectors and nse_sectors != ["UNKNOWN"]:
                    mismatches.append((stock, cur_sector, nse_sectors))

            if mismatches:
                print(f"\nFound {len(mismatches)} potential issues:\n")
                print(f"{'Stock':<15} {'Current':<20} {'NSE Indices'}")
                print("-" * 70)

                for stock, current_s, nse_s in mismatches[:25]:
                    nse_str = ', '.join(nse_s)
                    print(f"{stock:<15} {current_s:<20} {nse_str}")

    elif choice == '3':
        logger.info("Keeping existing single-sector mapping")

    logger.info("\n" + "="*80)
    logger.info("Done!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\nAborted by user")
