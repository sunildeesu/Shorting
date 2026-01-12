#!/usr/bin/env python3
"""
Volume Profile Analyzer - Main Orchestrator
Runs at 3:25 PM daily (near market close) to detect P-shaped and B-shaped volume profiles for F&O stocks.

P-shaped: Price held at highs (bullish strength/continuation signal)
B-shaped: Price held at lows (bearish weakness/continuation signal)
"""

import json
import logging
import time
import argparse
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Optional
from kiteconnect import KiteConnect
import config
from unified_data_cache import UnifiedDataCache
from volume_profile_calculator import VolumeProfileCalculator
from volume_profile_report_generator import VolumeProfileReportGenerator
from telegram_notifier import TelegramNotifier
from market_utils import is_trading_day, get_current_ist_time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/volume_profile.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class VolumeProfileAnalyzer:
    """Main orchestrator for volume profile analysis"""

    def __init__(self, execution_time: str = "3:25PM"):
        """
        Initialize volume profile analyzer.

        Args:
            execution_time: "3:25PM" (end of day analysis)
        """
        self.execution_time = execution_time
        logger.info(f"="*70)
        logger.info(f"Volume Profile Analyzer - {execution_time} Execution")
        logger.info(f"="*70)

        # Initialize Kite Connect
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Initialize components
        self.cache_manager = UnifiedDataCache(cache_dir=config.UNIFIED_CACHE_DIR)
        self.profile_calculator = VolumeProfileCalculator()
        self.report_generator = VolumeProfileReportGenerator()
        self.telegram = TelegramNotifier()

        # Load F&O stock list
        self.fo_stocks = self._load_fo_stocks()

        # Build instrument token mapping
        self.instrument_tokens = self._build_instrument_token_map()

        logger.info(f"Initialized with {len(self.fo_stocks)} F&O stocks")
        logger.info(f"Execution time: {execution_time}")

    def _load_fo_stocks(self) -> List[str]:
        """Load F&O stock list from file"""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                data = json.load(f)
                return data['stocks']
        except Exception as e:
            logger.error(f"Error loading F&O stocks: {e}")
            return []

    def _build_instrument_token_map(self) -> Dict[str, int]:
        """
        Build mapping of stock symbol to instrument token.

        Returns:
            Dict mapping symbol to instrument_token
        """
        logger.info("Building instrument token map from Kite API...")

        try:
            instruments = self.kite.instruments("NSE")
            token_map = {}

            for instrument in instruments:
                if instrument['segment'] == 'NSE' and instrument['tradingsymbol'] in self.fo_stocks:
                    token_map[instrument['tradingsymbol']] = instrument['instrument_token']

            logger.info(f"Built token map for {len(token_map)} stocks")
            return token_map

        except Exception as e:
            logger.error(f"Error building instrument token map: {e}")
            return {}

    def _fetch_intraday_1min_data(self, symbol: str) -> List[Dict]:
        """
        Fetch 1-minute intraday candles for today from 9:15 AM to current time.

        Args:
            symbol: Stock symbol

        Returns:
            List of 1-minute OHLCV candles
        """
        if symbol not in self.instrument_tokens:
            logger.warning(f"{symbol}: Instrument token not found")
            return []

        try:
            instrument_token = self.instrument_tokens[symbol]
            today = datetime.now().date()
            current_time = get_current_ist_time()

            # Time range: 9:15 AM to current time (3:00 PM or 3:15 PM)
            from_date = datetime.combine(today, dt_time(9, 15))
            to_date = current_time

            # Fetch 1-minute candles
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="minute"
            )

            if not data:
                logger.warning(f"{symbol}: No intraday data returned")
                return []

            logger.debug(f"{symbol}: Fetched {len(data)} 1-min candles")
            return data

        except Exception as e:
            logger.error(f"{symbol}: Error fetching 1-min data - {e}")
            return []

    def _fetch_with_cache(self, symbol: str) -> List[Dict]:
        """
        Fetch 1-min data with intelligent caching for two execution windows.

        Strategy:
        - 3:00 PM: Fetch full data (9:15 AM - 3:00 PM), cache with 15-min TTL
        - 3:15 PM: Check cache (still valid), only fetch delta if needed

        Args:
            symbol: Stock symbol

        Returns:
            List of 1-minute candles
        """
        # Check cache first
        cached_data = self.cache_manager.get_data(symbol, 'intraday_1min')

        if cached_data and self.execution_time == "3:15PM":
            # Cache hit at 3:15 PM - reuse cached data from 3:00 PM run
            logger.debug(f"{symbol}: Using cached 1-min data")
            return cached_data

        # Fetch fresh data
        data = self._fetch_intraday_1min_data(symbol)

        if data:
            # Cache for 15 minutes
            self.cache_manager.set_data(symbol, data, 'intraday_1min')

        return data

    def _analyze_stock(self, symbol: str, intraday_data: List[Dict]) -> Dict:
        """
        Calculate volume profile for a single stock.

        Args:
            symbol: Stock symbol
            intraday_data: List of 1-minute candles

        Returns:
            Volume profile result dict
        """
        try:
            profile = self.profile_calculator.calculate_volume_profile(intraday_data)

            return {
                'symbol': symbol,
                'success': True,
                **profile
            }
        except Exception as e:
            logger.error(f"{symbol}: Volume profile calculation failed - {e}", exc_info=True)
            return {
                'symbol': symbol,
                'success': False,
                'error': str(e),
                'profile_shape': 'ERROR',
                'confidence': 0.0
            }

    def _batch_analyze(self, symbols: List[str]) -> List[Dict]:
        """
        Batch analyze volume profiles for all stocks with rate limiting.

        Args:
            symbols: List of stock symbols

        Returns:
            List of volume profile results
        """
        results = []
        total = len(symbols)

        logger.info(f"Starting batch analysis of {total} stocks...")

        for i, symbol in enumerate(symbols, 1):
            try:
                # Fetch 1-min data (with caching)
                intraday_data = self._fetch_with_cache(symbol)

                if not intraday_data:
                    logger.warning(f"{symbol}: No data available, skipping")
                    continue

                # Calculate volume profile
                result = self._analyze_stock(symbol, intraday_data)
                results.append(result)

                # Progress logging
                if i % 50 == 0:
                    logger.info(f"Progress: {i}/{total} stocks analyzed")

                # Rate limiting (0.25s delay to stay under Kite API limits)
                time.sleep(config.REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"{symbol}: Error in batch analysis - {e}")
                continue

        logger.info(f"Batch analysis complete: {len(results)} stocks analyzed")
        return results

    def _upload_to_dropbox(self, excel_path: str) -> Optional[str]:
        """
        Upload Excel report to Dropbox and return shareable link.

        Args:
            excel_path: Local path to Excel file

        Returns:
            Shareable Dropbox link, or None if error/disabled
        """
        if not config.VOLUME_PROFILE_ENABLE_DROPBOX:
            logger.info("Dropbox upload disabled in config")
            return None

        try:
            # Import Dropbox dependencies
            import dropbox
            from dropbox.files import WriteMode

            logger.info("Uploading volume profile report to Dropbox...")

            # Authenticate
            token = config.VOLUME_PROFILE_DROPBOX_TOKEN
            if not token:
                logger.error("Dropbox token not configured (VOLUME_PROFILE_DROPBOX_TOKEN)")
                return None

            dbx = dropbox.Dropbox(token)

            # File path in Dropbox (preserve execution time in filename)
            file_basename = excel_path.split('/')[-1]  # Get filename from path
            dropbox_path = f"{config.VOLUME_PROFILE_DROPBOX_FOLDER}/{file_basename}"

            # Upload file (overwrite if exists)
            with open(excel_path, 'rb') as f:
                dbx.files_upload(
                    f.read(),
                    dropbox_path,
                    mode=WriteMode.overwrite
                )

            logger.info(f"✓ Uploaded to Dropbox: {dropbox_path}")

            # Create or get shareable link
            try:
                # Try to get existing link
                links = dbx.sharing_list_shared_links(path=dropbox_path)
                if links.links:
                    link_url = links.links[0].url
                else:
                    # Create new link
                    link = dbx.sharing_create_shared_link_with_settings(dropbox_path)
                    link_url = link.url

                # Convert to direct download link (optional, for easier viewing)
                shareable_link = link_url.replace('?dl=0', '?dl=1')
                logger.info(f"✓ Dropbox link: {shareable_link}")
                return shareable_link

            except dropbox.exceptions.ApiError as e:
                if 'shared_link_already_exists' in str(e):
                    # Link already exists, retrieve it
                    links = dbx.sharing_list_shared_links(path=dropbox_path)
                    if links.links:
                        link_url = links.links[0].url
                        shareable_link = link_url.replace('?dl=0', '?dl=1')
                        logger.info(f"✓ Existing Dropbox link: {shareable_link}")
                        return shareable_link
                raise

        except ImportError as e:
            logger.error(f"Dropbox library not installed: {e}")
            logger.error("Install: pip install dropbox")
            return None
        except Exception as e:
            logger.error(f"Error uploading to Dropbox: {e}", exc_info=True)
            return None

    def run_analysis(self) -> Optional[str]:
        """
        Main analysis pipeline:
        1. Check if trading day (skip weekends/holidays)
        2. Fetch 1-min data for all 212 stocks (with caching)
        3. Calculate volume profiles
        4. Filter high-confidence P/B shapes (confidence >= 7.5)
        5. Generate Excel report
        6. Send Telegram alerts

        Returns:
            Report file path or None if skipped
        """
        # Check if enabled
        if not config.ENABLE_VOLUME_PROFILE:
            logger.info("Volume profile analysis is disabled in config")
            return None

        # Check if trading day
        if not is_trading_day():
            logger.info("Not a trading day (weekend/holiday) - skipping analysis")
            return None

        # Verify execution time window (should be 3:00-3:15 PM)
        current_time = get_current_ist_time()
        current_hour = current_time.hour
        current_minute = current_time.minute

        if not (current_hour == 15 and 0 <= current_minute <= 30):
            logger.warning(f"Outside execution window (3:00-3:30 PM). Current time: {current_time.strftime('%H:%M')}")
            # Continue anyway for manual testing

        logger.info(f"Starting volume profile analysis at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Step 1: Batch analyze all stocks
        all_results = self._batch_analyze(self.fo_stocks)

        if not all_results:
            logger.warning("No results from analysis")
            return None

        # Step 2: Filter successful analyses
        successful_results = [r for r in all_results if r.get('success', False)]
        logger.info(f"Successful analyses: {len(successful_results)}/{len(all_results)}")

        # Step 3: Classify by shape
        p_shaped = [r for r in successful_results if r['profile_shape'] == 'P-SHAPE']
        b_shaped = [r for r in successful_results if r['profile_shape'] == 'B-SHAPE']
        balanced = [r for r in successful_results if r['profile_shape'] == 'BALANCED']

        logger.info(f"Profile classification:")
        logger.info(f"  P-SHAPE (distribution): {len(p_shaped)}")
        logger.info(f"  B-SHAPE (accumulation): {len(b_shaped)}")
        logger.info(f"  BALANCED: {len(balanced)}")

        # Step 4: Filter high-confidence patterns
        high_conf_p = [r for r in p_shaped if r['confidence'] >= config.VOLUME_PROFILE_MIN_CONFIDENCE]
        high_conf_b = [r for r in b_shaped if r['confidence'] >= config.VOLUME_PROFILE_MIN_CONFIDENCE]

        logger.info(f"High-confidence patterns (>= {config.VOLUME_PROFILE_MIN_CONFIDENCE}):")
        logger.info(f"  P-SHAPE: {len(high_conf_p)}")
        logger.info(f"  B-SHAPE: {len(high_conf_b)}")

        # Step 5: Generate Excel report
        try:
            report_path = self.report_generator.generate_report(
                profile_results=successful_results,
                analysis_time=current_time,
                execution_window=self.execution_time
            )
            logger.info(f"Excel report generated: {report_path}")
        except Exception as e:
            logger.error(f"Failed to generate Excel report: {e}", exc_info=True)
            report_path = None

        # Step 5.1: Upload report to Dropbox
        dropbox_link = None
        if report_path:
            try:
                dropbox_link = self._upload_to_dropbox(report_path)
                if dropbox_link:
                    logger.info(f"Report uploaded to Dropbox: {dropbox_link}")
            except Exception as e:
                logger.error(f"Failed to upload to Dropbox: {e}", exc_info=True)

        # Step 6: Send Telegram alerts (only if high-confidence patterns found)
        try:
            if high_conf_p or high_conf_b:
                telegram_sent = self.telegram.send_volume_profile_summary(
                    profile_results=successful_results,
                    analysis_time=current_time,
                    execution_window=self.execution_time
                )
                if telegram_sent:
                    logger.info("Telegram alert sent successfully")
                else:
                    logger.info("Telegram alert skipped (no high-confidence patterns)")
            else:
                logger.info("No high-confidence patterns to alert")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}", exc_info=True)

        logger.info(f"="*70)
        logger.info(f"Volume Profile Analysis Complete - {self.execution_time}")
        logger.info(f"="*70)

        return report_path


def main():
    """Main entry point with command-line argument support"""
    parser = argparse.ArgumentParser(description='Volume Profile Analyzer')
    parser.add_argument('--execution-time', default='3:25PM',
                       help='Execution time: 3:25PM (end of day)')

    args = parser.parse_args()

    try:
        analyzer = VolumeProfileAnalyzer(execution_time=args.execution_time)
        report_path = analyzer.run_analysis()

        if report_path:
            print(f"\n✅ Analysis complete. Report: {report_path}\n")
        else:
            print(f"\n❌ Analysis skipped or failed.\n")

    except Exception as e:
        logger.error(f"Fatal error in volume profile analyzer: {e}", exc_info=True)
        print(f"\n❌ Fatal error: {e}\n")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
