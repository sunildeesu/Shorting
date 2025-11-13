#!/usr/bin/env python3
"""
EOD Stock Analyzer - Main orchestrator for end-of-day analysis
Runs daily after market close to detect volume spikes and chart patterns
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from kiteconnect import KiteConnect
import config
from unified_data_cache import UnifiedDataCache
from eod_stock_filter import EODStockFilter
from eod_volume_analyzer import EODVolumeAnalyzer
from eod_pattern_detector import EODPatternDetector
from eod_report_generator import EODReportGenerator
from market_regime_detector import MarketRegimeDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/eod_analyzer.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class EODAnalyzer:
    """Main orchestrator for end-of-day stock analysis"""

    def __init__(self):
        """Initialize EOD analyzer with all components"""
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Initialize components (using unified cache for cross-monitor sharing)
        self.cache_manager = UnifiedDataCache(cache_dir=config.HISTORICAL_CACHE_DIR)
        self.stock_filter = EODStockFilter(volume_threshold_lakhs=50.0, price_change_threshold=1.5)
        self.volume_analyzer = EODVolumeAnalyzer(spike_threshold=1.5)
        self.pattern_detector = EODPatternDetector(
            pattern_tolerance=2.0,
            volume_confirmation=True,
            min_confidence=7.0
        )
        self.report_generator = EODReportGenerator()
        self.regime_detector = MarketRegimeDetector(self.kite)

        # Load F&O stock list
        self.fo_stocks = self._load_fo_stocks()

        # Build instrument token mapping
        self.instrument_tokens = self._build_instrument_token_map()

        logger.info(f"EOD Analyzer initialized with {len(self.fo_stocks)} F&O stocks")

    def _load_fo_stocks(self) -> List[str]:
        """Load F&O stock list from file"""
        try:
            with open('fo_stocks.json', 'r') as f:
                data = json.load(f)
                return data['stocks']
        except Exception as e:
            logger.error(f"Error loading F&O stocks: {e}")
            return []

    def _build_instrument_token_map(self) -> Dict[str, int]:
        """
        Build mapping of stock symbol to instrument token

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

    def _fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Fetch batch quote data for stocks

        Args:
            symbols: List of stock symbols

        Returns:
            Dict mapping symbol to quote data
        """
        logger.info(f"Fetching quotes for {len(symbols)} stocks...")

        quote_data = {}
        batch_size = 50  # Safe batch size for Kite API

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            # Format as NSE:SYMBOL for Kite API
            instruments = [f"NSE:{symbol}" for symbol in batch]

            try:
                # Unpack instruments list with *
                quotes = self.kite.quote(*instruments)
                quote_data.update(quotes)
                logger.debug(f"Fetched batch {i//batch_size + 1}: {len(batch)} stocks")

                # Rate limiting
                time.sleep(config.REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"Error fetching quotes for batch {i//batch_size + 1}: {e}")

        logger.info(f"Fetched quotes for {len(quote_data)} stocks")
        return quote_data

    def _fetch_intraday_data(self, symbol: str) -> List[Dict]:
        """
        Fetch today's intraday data (15-minute intervals)

        Args:
            symbol: Stock symbol

        Returns:
            List of 15-minute OHLCV candles for today
        """
        try:
            # Get instrument token
            instrument_token = self._get_instrument_token(symbol)
            if instrument_token is None:
                return []

            # Get today's date range
            today = datetime.now().date()
            from_date = datetime.combine(today, datetime.min.time())
            to_date = datetime.combine(today, datetime.max.time())

            # Fetch 15-minute candles
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="15minute"
            )

            return data

        except Exception as e:
            logger.error(f"{symbol}: Error fetching intraday data - {e}")
            return []

    def _fetch_historical_data(self, symbol: str, use_cache: bool = True) -> List[Dict]:
        """
        Fetch 30-day historical data with caching

        Args:
            symbol: Stock symbol
            use_cache: Whether to use cached data (default: True)

        Returns:
            List of daily OHLCV candles for last 30 days
        """
        # Check cache first
        if use_cache:
            cached_data = self.cache_manager.get_historical_data(symbol)
            if cached_data is not None:
                return cached_data

        # Fetch from API
        try:
            # Get instrument token
            instrument_token = self._get_instrument_token(symbol)
            if instrument_token is None:
                return []

            # Get 30-day date range
            to_date = datetime.now().date()
            from_date = to_date - timedelta(days=30)

            from_datetime = datetime.combine(from_date, datetime.min.time())
            to_datetime = datetime.combine(to_date, datetime.max.time())

            # Fetch daily candles
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_datetime,
                to_date=to_datetime,
                interval="day"
            )

            # Cache the data
            self.cache_manager.set_historical_data(symbol, data)

            return data

        except Exception as e:
            logger.error(f"{symbol}: Error fetching historical data - {e}")
            return []

    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        """
        Get instrument token for a symbol

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")

        Returns:
            Instrument token or None if not found
        """
        token = self.instrument_tokens.get(symbol)
        if token is None:
            logger.warning(f"{symbol}: No instrument token found")
        return token

    def run_analysis(self) -> str:
        """
        Run complete EOD analysis

        Returns:
            Path to generated report
        """
        logger.info("="*80)
        logger.info("Starting EOD Stock Analysis")
        logger.info("="*80)

        start_time = time.time()

        # Step 1: Fetch batch quotes for all F&O stocks
        logger.info("Step 1: Fetching batch quotes...")
        quote_data = self._fetch_batch_quotes(self.fo_stocks)

        if not quote_data:
            logger.error("No quote data fetched. Aborting analysis.")
            return None

        # Step 2: Filter stocks using smart filtering
        logger.info("Step 2: Filtering active stocks...")
        filtered_stocks_with_prefix = self.stock_filter.filter_stocks(quote_data)

        # Strip NSE: prefix from filtered stocks
        filtered_stocks = [s.replace("NSE:", "") for s in filtered_stocks_with_prefix]

        logger.info(f"Filtered {len(self.fo_stocks)} → {len(filtered_stocks)} stocks "
                   f"({len(filtered_stocks)/len(self.fo_stocks)*100:.1f}% retention)")

        if not filtered_stocks:
            logger.warning("No stocks passed filtering. Generating empty report.")
            filtered_stocks = []  # Will generate report with no findings

        # Step 3: Fetch intraday data for filtered stocks
        logger.info("Step 3: Fetching intraday data for filtered stocks...")
        intraday_data_map = {}

        for symbol in filtered_stocks:
            intraday_data = self._fetch_intraday_data(symbol)
            intraday_data_map[symbol] = intraday_data
            time.sleep(config.REQUEST_DELAY_SECONDS)  # Rate limiting

        logger.info(f"Fetched intraday data for {len(intraday_data_map)} stocks")

        # Step 4: Fetch/cache 30-day historical data for filtered stocks
        logger.info("Step 4: Fetching historical data (with caching)...")
        historical_data_map = {}

        for symbol in filtered_stocks:
            historical_data = self._fetch_historical_data(symbol, use_cache=True)
            historical_data_map[symbol] = historical_data
            time.sleep(config.REQUEST_DELAY_SECONDS)  # Rate limiting

        logger.info(f"Fetched/cached historical data for {len(historical_data_map)} stocks")

        # Step 5: Run volume analysis
        logger.info("Step 5: Running volume analysis...")
        volume_results = self.volume_analyzer.batch_analyze(intraday_data_map, historical_data_map)

        # Step 6: Detect market regime
        logger.info("Step 6: Detecting market regime...")
        market_regime = self.regime_detector.get_market_regime()
        regime_details = self.regime_detector.get_regime_details()
        logger.info(f"Market Regime: {market_regime} "
                   f"(Nifty: {regime_details.get('current_price', 0):.2f}, "
                   f"50-SMA: {regime_details.get('sma_50', 0):.2f}, "
                   f"Diff: {regime_details.get('diff_pct', 0):+.2f}%)")

        # Step 7: Run pattern detection with market regime
        logger.info("Step 7: Running pattern detection...")
        pattern_results = self.pattern_detector.batch_detect(historical_data_map, market_regime)

        # Step 8: Generate Excel report
        logger.info("Step 8: Generating Excel report...")
        report_path = self.report_generator.generate_report(
            volume_results,
            pattern_results,
            quote_data,
            historical_data_map,
            datetime.now()
        )

        # Clean up expired cache entries
        self.cache_manager.clear_expired()

        # Log summary
        elapsed_time = time.time() - start_time
        logger.info("="*80)
        logger.info("EOD Analysis Complete!")
        logger.info(f"Report: {report_path}")
        logger.info(f"Time taken: {elapsed_time:.1f} seconds")
        logger.info(f"API calls made: ~{len(filtered_stocks) * 2 + len(self.fo_stocks)//50}")
        logger.info("="*80)

        return report_path


def main():
    """Main entry point"""
    try:
        analyzer = EODAnalyzer()
        report_path = analyzer.run_analysis()

        if report_path:
            print(f"\n✅ EOD Analysis complete! Report saved to: {report_path}\n")
        else:
            print(f"\n❌ EOD Analysis failed. Check logs for details.\n")

    except Exception as e:
        logger.error(f"Fatal error in EOD analysis: {e}", exc_info=True)
        print(f"\n❌ Fatal error: {e}\n")


if __name__ == "__main__":
    main()
