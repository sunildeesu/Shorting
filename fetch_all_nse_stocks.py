#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Fetch All NSE Stocks with Market Cap > ₹10,000 Cr

One-time setup script to generate the stock universe for value screener.
Fetches all NSE instruments, calculates market caps, and filters by threshold.

Generates 3 output files:
1. data/all_nse_stocks.json - Stock symbols (565 stocks)
2. data/all_instrument_tokens.json - Kite instrument tokens
3. data/all_shares_outstanding.json - Shares outstanding for market cap calculation

Author: Sunil Kumar Durganaik
"""

import json
import os
import time
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from kiteconnect import KiteConnect

import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/fetch_all_nse_stocks.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class NSEStockFetcher:
    """Fetches all NSE stocks and filters by market cap"""

    def __init__(self, market_cap_threshold_cr: float = 10000):
        """
        Initialize NSE stock fetcher

        Args:
            market_cap_threshold_cr: Minimum market cap in crores (default: 10,000)
        """
        self.market_cap_threshold = market_cap_threshold_cr

        # Initialize Kite Connect
        if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
            raise ValueError("Kite Connect requires KITE_API_KEY and KITE_ACCESS_TOKEN")

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
        logger.info("Kite Connect initialized")

    def fetch_all_nse_instruments(self) -> List[Dict]:
        """
        Fetch all NSE instruments from Kite API

        Returns:
            List of instrument dicts (filtered for equity only, valid symbols)
        """
        logger.info("Fetching all NSE instruments from Kite...")

        try:
            # Fetch all NSE instruments
            all_instruments = self.kite.instruments("NSE")
            logger.info(f"Fetched {len(all_instruments)} total NSE instruments")

            # Filter for equity stocks only (exclude indices, commodities, etc.)
            equity_stocks = []
            for inst in all_instruments:
                if inst['segment'] != 'NSE' or inst['instrument_type'] != 'EQ':
                    continue

                symbol = inst['tradingsymbol']

                # Skip invalid symbols (special characters, numbers, etc.)
                # Valid symbols: uppercase letters, hyphens, ampersands only
                if not symbol or len(symbol) < 2:
                    continue

                # Skip symbols with numbers at start (likely invalid)
                if symbol[0].isdigit():
                    continue

                # Skip symbols with too many special characters
                special_count = sum(1 for c in symbol if not c.isalnum())
                if special_count > 2:  # Allow up to 2 special chars (e.g., M&M, BAJAJ-AUTO)
                    continue

                # Skip DVR (Differential Voting Rights) stocks
                if 'DVR' in symbol:
                    continue

                equity_stocks.append(inst)

            logger.info(f"Filtered to {len(equity_stocks)} valid equity stocks")

            return equity_stocks

        except Exception as e:
            logger.error(f"Failed to fetch NSE instruments: {e}")
            raise

    def fetch_market_cap_yahoo(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetch market cap and shares outstanding from Yahoo Finance

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")

        Returns:
            Tuple of (market_cap_cr, shares_outstanding) or (None, None) if failed
        """
        try:
            import yfinance as yf

            ticker = yf.Ticker(f"{symbol}.NS")
            info = ticker.info

            # Get shares outstanding and current price
            shares = info.get('sharesOutstanding')
            price = info.get('currentPrice') or info.get('regularMarketPrice')

            if shares and price:
                market_cap_cr = (price * shares) / 10_000_000  # Convert to crores
                return market_cap_cr, shares

            return None, None

        except Exception as e:
            logger.debug(f"{symbol}: Yahoo Finance failed: {e}")
            return None, None

    def fetch_market_cap_screener(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetch market cap and shares outstanding from Screener.in (fallback)

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")

        Returns:
            Tuple of (market_cap_cr, shares_outstanding) or (None, None) if failed
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }

            # Try original symbol first, then variations if it fails
            symbols_to_try = [symbol]

            # If symbol has suffix (e.g., "SANWARIA-BZ"), try without suffix
            if '-' in symbol:
                base_symbol = symbol.split('-')[0]
                symbols_to_try.append(base_symbol)

            response = None
            successful_symbol = None

            for try_symbol in symbols_to_try:
                url = f"https://www.screener.in/company/{try_symbol}/"
                response = requests.get(url, headers=headers, timeout=10)

                if response.status_code == 200:
                    successful_symbol = try_symbol
                    break

            if not response or response.status_code != 200:
                return None, None

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find market cap in the page
            market_cap_text = None
            for li in soup.find_all('li', class_='flex'):
                span = li.find('span', class_='name')
                if span and 'Market Cap' in span.text:
                    value_span = li.find('span', class_='number')
                    if value_span:
                        market_cap_text = value_span.text.strip()
                        break

            if not market_cap_text:
                return None, None

            # Parse market cap (e.g., "₹ 1,57,000 Cr.")
            market_cap_str = market_cap_text.replace('₹', '').replace('Cr.', '').replace(',', '').strip()
            market_cap_cr = float(market_cap_str)

            # Get current price (second 'number' span element, first is market cap)
            number_spans = soup.find_all('span', class_='number')
            if len(number_spans) < 2:
                return market_cap_cr, None

            price = float(number_spans[1].text.replace(',', '').strip())
            shares = (market_cap_cr * 10_000_000) / price

            return market_cap_cr, shares

        except Exception as e:
            logger.debug(f"{symbol}: Screener.in failed: {e}")
            return None, None

    def fetch_market_cap(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetch market cap using Screener.in (primary source, more reliable for NSE stocks)

        Args:
            symbol: Stock symbol

        Returns:
            Tuple of (market_cap_cr, shares_outstanding)
        """
        # Use Screener.in as primary source (better for Indian stocks)
        market_cap, shares = self.fetch_market_cap_screener(symbol)
        if market_cap:
            logger.debug(f"{symbol}: Market cap ₹{market_cap:,.0f} Cr (Screener.in)")
            return market_cap, shares

        logger.warning(f"{symbol}: Failed to fetch market cap from Screener.in")
        return None, None

    def load_progress(self) -> Dict:
        """Load progress from checkpoint file"""
        progress_file = 'data/fetch_progress.json'
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r') as f:
                    return json.load(f)
            except:
                return {'processed_stocks': [], 'all_stocks_data': []}
        return {'processed_stocks': [], 'all_stocks_data': []}

    def save_progress(self, processed_stocks: List[str], all_stocks_data: List[Dict]):
        """Save progress to checkpoint file"""
        progress_file = 'data/fetch_progress.json'
        try:
            with open(progress_file, 'w') as f:
                json.dump({
                    'processed_stocks': processed_stocks,
                    'all_stocks_data': all_stocks_data,
                    'last_updated': datetime.now().isoformat()
                }, f)
        except Exception as e:
            logger.error(f"Failed to save progress: {e}")

    def process_all_stocks(self, equity_stocks: List[Dict]) -> Tuple[List[Dict], Dict, Dict]:
        """
        Process all stocks: fetch market caps and filter by threshold
        Supports resume from checkpoint if interrupted

        Args:
            equity_stocks: List of equity instrument dicts from Kite

        Returns:
            Tuple of (filtered_stocks, instrument_tokens, shares_outstanding)
        """
        # Load progress if exists
        progress = self.load_progress()
        processed_symbols = set(progress.get('processed_stocks', []))
        all_stocks_data = progress.get('all_stocks_data', [])

        total_stocks = len(equity_stocks)
        already_processed = len(processed_symbols)

        if already_processed > 0:
            logger.info(f"Resuming from checkpoint: {already_processed} stocks already processed")

        logger.info(f"Processing {total_stocks} equity stocks...")
        logger.info(f"Remaining: {total_stocks - already_processed} stocks")
        logger.info("This will take ~2-3 hours (fetching market cap from Screener.in)")
        logger.info("Rate limit: 4 seconds between requests (respectful crawling)")
        logger.info("")

        for idx, inst in enumerate(equity_stocks, 1):
            symbol = inst['tradingsymbol']

            # Skip if already processed
            if symbol in processed_symbols:
                continue

            # Progress update every 50 stocks
            if idx % 50 == 0:
                success_count = len(all_stocks_data)
                logger.info(f"Progress: {idx}/{total_stocks} ({idx/total_stocks*100:.1f}%) | Success: {success_count}")

            # Fetch market cap
            market_cap_cr, shares = self.fetch_market_cap(symbol)

            # Mark as processed
            processed_symbols.add(symbol)

            if market_cap_cr is None:
                logger.debug(f"[{idx}/{total_stocks}] {symbol}: No market cap data")
            else:
                all_stocks_data.append({
                    'symbol': symbol,
                    'name': inst['name'],
                    'instrument_token': inst['instrument_token'],
                    'market_cap_cr': market_cap_cr,
                    'shares_outstanding': shares
                })
                logger.debug(f"[{idx}/{total_stocks}] {symbol}: ₹{market_cap_cr:,.0f} Cr")

            # Save progress every 100 stocks
            if idx % 100 == 0:
                self.save_progress(list(processed_symbols), all_stocks_data)
                logger.info(f"✓ Checkpoint saved ({len(all_stocks_data)} stocks with data)")

            # Rate limiting (4 seconds for Screener.in)
            time.sleep(4)

        # Final save
        self.save_progress(list(processed_symbols), all_stocks_data)

        logger.info(f"\nFetched market cap for {len(all_stocks_data)}/{total_stocks} stocks")

        # Filter by market cap threshold
        filtered_stocks = [
            stock for stock in all_stocks_data
            if stock['market_cap_cr'] >= self.market_cap_threshold
        ]

        logger.info(f"Filtered to {len(filtered_stocks)} stocks with market cap > ₹{self.market_cap_threshold:,.0f} Cr")

        # Prepare output dictionaries
        instrument_tokens = {stock['symbol']: stock['instrument_token'] for stock in filtered_stocks}
        shares_outstanding = {stock['symbol']: stock['shares_outstanding'] for stock in filtered_stocks if stock['shares_outstanding']}

        # Clean up checkpoint file
        progress_file = 'data/fetch_progress.json'
        if os.path.exists(progress_file):
            os.remove(progress_file)
            logger.info("✓ Checkpoint file cleaned up")

        return filtered_stocks, instrument_tokens, shares_outstanding

    def save_output_files(self, filtered_stocks: List[Dict], instrument_tokens: Dict, shares_outstanding: Dict):
        """
        Save output JSON files

        Args:
            filtered_stocks: List of filtered stock dicts
            instrument_tokens: Dict of symbol -> instrument_token
            shares_outstanding: Dict of symbol -> shares_outstanding
        """
        # 1. Save stock list (symbols only)
        stock_symbols = [stock['symbol'] for stock in filtered_stocks]
        stock_list_file = 'data/all_nse_stocks.json'

        with open(stock_list_file, 'w') as f:
            json.dump({'stocks': stock_symbols, 'count': len(stock_symbols), 'generated_at': datetime.now().isoformat()}, f, indent=2)
        logger.info(f"✓ Saved {len(stock_symbols)} stock symbols to: {stock_list_file}")

        # 2. Save instrument tokens
        tokens_file = 'data/all_instrument_tokens.json'
        with open(tokens_file, 'w') as f:
            json.dump(instrument_tokens, f, indent=2)
        logger.info(f"✓ Saved {len(instrument_tokens)} instrument tokens to: {tokens_file}")

        # 3. Save shares outstanding
        shares_file = 'data/all_shares_outstanding.json'
        with open(shares_file, 'w') as f:
            json.dump(shares_outstanding, f, indent=2)
        logger.info(f"✓ Saved {len(shares_outstanding)} shares outstanding to: {shares_file}")

        # 4. Save detailed data (with market caps, for reference)
        details_file = 'data/all_nse_stocks_detailed.json'
        with open(details_file, 'w') as f:
            json.dump({
                'threshold_cr': self.market_cap_threshold,
                'count': len(filtered_stocks),
                'generated_at': datetime.now().isoformat(),
                'stocks': filtered_stocks
            }, f, indent=2)
        logger.info(f"✓ Saved detailed stock data to: {details_file}")

    def run(self):
        """Main execution method"""
        start_time = time.time()

        logger.info("=" * 80)
        logger.info("NSE STOCK UNIVERSE FETCHER")
        logger.info("=" * 80)
        logger.info(f"Market cap threshold: ₹{self.market_cap_threshold:,.0f} Cr")
        logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("")

        # Step 1: Fetch all NSE instruments
        equity_stocks = self.fetch_all_nse_instruments()

        # Step 2: Process all stocks (fetch market caps)
        filtered_stocks, instrument_tokens, shares_outstanding = self.process_all_stocks(equity_stocks)

        # Step 3: Save output files
        self.save_output_files(filtered_stocks, instrument_tokens, shares_outstanding)

        # Summary
        elapsed_time = time.time() - start_time
        logger.info("")
        logger.info("=" * 80)
        logger.info("SETUP COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Total NSE equity stocks: {len(equity_stocks)}")
        logger.info(f"Stocks with market cap > ₹{self.market_cap_threshold:,.0f} Cr: {len(filtered_stocks)}")
        logger.info(f"Execution time: {elapsed_time/60:.1f} minutes")
        logger.info("")
        logger.info("Output files:")
        logger.info("  1. data/all_nse_stocks.json (stock symbols)")
        logger.info("  2. data/all_instrument_tokens.json (Kite tokens)")
        logger.info("  3. data/all_shares_outstanding.json (shares data)")
        logger.info("  4. data/all_nse_stocks_detailed.json (full data with market caps)")
        logger.info("")
        logger.info("You can now run stock_value_screener.py to screen these stocks!")
        logger.info("=" * 80)


def main():
    """Main entry point"""
    try:
        fetcher = NSEStockFetcher(market_cap_threshold_cr=10000)
        fetcher.run()
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
