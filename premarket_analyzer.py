#!/usr/bin/env python3
"""
Pre-Market Stock Analyzer - Main orchestrator for pre-market pattern analysis

Runs daily at 9:00 AM (before market open at 9:15 AM) to detect high-probability
chart patterns on both daily and hourly timeframes.

Workflow:
1. Detect market regime (Nifty 50 vs 50-day SMA)
2. Filter stocks (volume >50L OR price change >1.5%)
3. Fetch daily historical data (30 days, mostly cached)
4. Fetch hourly historical data (10 days, fresh API calls)
5. Detect patterns on both timeframes
6. Rank patterns using 5-factor scoring
7. Select top 1-3 patterns
8. Generate Excel report
9. Send Telegram alert

Author: Sunil Kumar Durganaik
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from kiteconnect import KiteConnect
import config
from unified_data_cache import UnifiedDataCache
from eod_stock_filter import EODStockFilter  # Reuse existing filter
from pattern_detector import PatternDetector
from premarket_priority_ranker import PreMarketPriorityRanker
from premarket_report_generator import PreMarketReportGenerator
from telegram_notifier import TelegramNotifier
from market_regime_detector import MarketRegimeDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/premarket_analyzer.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class PreMarketAnalyzer:
    """Main orchestrator for pre-market pattern analysis"""

    def __init__(self):
        """Initialize pre-market analyzer with all components"""
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Initialize components (using unified cache for cross-monitor sharing)
        self.cache_manager = UnifiedDataCache(cache_dir=config.HISTORICAL_CACHE_DIR)
        self.stock_filter = EODStockFilter(volume_threshold_lakhs=50.0, price_change_threshold=1.5)

        # Pattern detectors for both timeframes
        self.daily_detector = PatternDetector(
            timeframe='daily',
            pattern_tolerance=2.0,
            volume_confirmation=True,
            min_confidence=7.5,
            require_confirmation=False
        )

        self.hourly_detector = PatternDetector(
            timeframe='hourly',
            pattern_tolerance=2.5,
            volume_confirmation=True,
            min_confidence=7.5,
            require_confirmation=False  # No confirmation for hourly (intraday)
        )

        # Priority ranker
        self.priority_ranker = PreMarketPriorityRanker(
            max_alerts=3,
            min_priority_score=7.0,
            min_confidence=7.5,
            min_risk_reward=1.5
        )

        # Report generator
        self.report_generator = PreMarketReportGenerator()

        # Telegram notifier
        self.telegram_notifier = TelegramNotifier()

        # Market regime detector
        self.regime_detector = MarketRegimeDetector(self.kite)

        # Load F&O stock list
        self.fo_stocks = self._load_fo_stocks()

        # Build instrument token mapping
        self.instrument_tokens = self._build_instrument_token_map()

        logger.info(f"Pre-Market Analyzer initialized with {len(self.fo_stocks)} F&O stocks")

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

    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for a symbol"""
        return self.instrument_tokens.get(symbol)

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

    def _fetch_historical_data(self, symbol: str, days: int = 30) -> List[Dict]:
        """
        Fetch daily historical data with caching

        Args:
            symbol: Stock symbol
            days: Number of days to fetch (default: 30)

        Returns:
            List of daily OHLCV candles
        """
        # Check cache first
        data_type = f'historical_{days}d'
        cached_data = self.cache_manager.get_data(symbol, data_type)
        if cached_data:
            logger.debug(f"{symbol}: Using cached {days}-day data")
            return cached_data

        # Fetch from API
        try:
            instrument_token = self._get_instrument_token(symbol)
            if instrument_token is None:
                logger.warning(f"{symbol}: No instrument token found")
                return []

            # Calculate date range
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days + 5)  # Extra buffer

            # Fetch historical data
            logger.debug(f"{symbol}: Fetching {days}-day data from API")
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval='day'
            )

            # Cache the data
            if data:
                self.cache_manager.set_data(symbol, data, data_type)
                logger.debug(f"{symbol}: Cached {len(data)} daily candles")

            # Rate limiting
            time.sleep(config.REQUEST_DELAY_SECONDS)

            return data

        except Exception as e:
            logger.error(f"{symbol}: Error fetching {days}-day historical data: {e}")
            return []

    def _fetch_hourly_data(self, symbol: str, days: int = 10) -> List[Dict]:
        """
        Fetch hourly historical data with caching

        Args:
            symbol: Stock symbol
            days: Number of days to fetch (default: 10)

        Returns:
            List of hourly OHLCV candles
        """
        # Check cache first
        cached_data = self.cache_manager.get_hourly_data(symbol)
        if cached_data:
            logger.debug(f"{symbol}: Using cached hourly data")
            return cached_data

        # Fetch from API
        try:
            instrument_token = self._get_instrument_token(symbol)
            if instrument_token is None:
                logger.warning(f"{symbol}: No instrument token found")
                return []

            # Calculate date range (market hours only)
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days + 2)  # Extra buffer for weekends

            # Fetch hourly data
            logger.debug(f"{symbol}: Fetching {days}-day hourly data from API")
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval='60minute'
            )

            # Cache the data
            if data:
                self.cache_manager.set_hourly_data(symbol, data)
                logger.debug(f"{symbol}: Cached {len(data)} hourly candles")

            # Rate limiting
            time.sleep(config.REQUEST_DELAY_SECONDS)

            return data

        except Exception as e:
            logger.error(f"{symbol}: Error fetching hourly data: {e}")
            return []

    def run(self):
        """
        Main execution method - runs complete pre-market analysis

        Returns:
            Dict with analysis results
        """
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("PRE-MARKET ANALYSIS STARTING")
        logger.info(f"Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Market opens in: {(datetime.combine(datetime.now().date(), datetime.strptime('09:15', '%H:%M').time()) - datetime.now()).seconds // 60} minutes")
        logger.info("=" * 60)

        try:
            # Step 1: Detect market regime
            logger.info("\n[STEP 1/7] Detecting market regime...")
            market_regime = self.regime_detector.detect_regime()
            logger.info(f"Market regime: {market_regime}")

            # Step 2: Fetch batch quotes for all F&O stocks
            logger.info("\n[STEP 2/7] Fetching latest quotes...")
            quote_data = self._fetch_batch_quotes(self.fo_stocks)
            logger.info(f"Fetched quotes for {len(quote_data)} stocks")

            # Step 3: Filter active stocks
            logger.info("\n[STEP 3/7] Filtering active stocks...")
            filtered_stocks = self.stock_filter.filter_stocks(quote_data)
            logger.info(f"Filtered to {len(filtered_stocks)} active stocks")

            if not filtered_stocks:
                logger.warning("No stocks passed filter criteria!")
                return self._empty_result(market_regime)

            # Step 4: Fetch historical data (daily and hourly)
            logger.info("\n[STEP 4/7] Fetching historical data...")
            daily_data = {}
            hourly_data = {}

            for symbol in filtered_stocks:
                # Fetch daily (30 days)
                daily_hist = self._fetch_historical_data(symbol, days=30)
                if daily_hist:
                    daily_data[symbol] = daily_hist

                # Fetch hourly (10 days)
                hourly_hist = self._fetch_hourly_data(symbol, days=10)
                if hourly_hist:
                    hourly_data[symbol] = hourly_hist

            logger.info(f"Fetched daily data for {len(daily_data)} stocks")
            logger.info(f"Fetched hourly data for {len(hourly_data)} stocks")

            # Step 5: Detect patterns on daily timeframe
            logger.info("\n[STEP 5/7] Detecting daily patterns...")
            daily_results = self.daily_detector.batch_detect(daily_data, market_regime)
            daily_patterns_count = sum(1 for r in daily_results.values() if r.get('has_patterns', False))
            logger.info(f"Found patterns in {daily_patterns_count} stocks on daily timeframe")

            # Step 6: Detect patterns on hourly timeframe
            logger.info("\n[STEP 6/7] Detecting hourly patterns...")
            hourly_results = self.hourly_detector.batch_detect(hourly_data, market_regime)
            hourly_patterns_count = sum(1 for r in hourly_results.values() if r.get('has_patterns', False))
            logger.info(f"Found patterns in {hourly_patterns_count} stocks on hourly timeframe")

            # Step 7: Rank and select top patterns
            logger.info("\n[STEP 7/9] Ranking patterns and selecting top alerts...")
            top_patterns = self.priority_ranker.rank_patterns(daily_results, hourly_results)
            logger.info(f"Selected {len(top_patterns)} top pattern(s) for alerts")

            # Step 8: Generate Excel report
            logger.info("\n[STEP 8/9] Generating Excel report...")
            try:
                # Extract all patterns for "All Patterns" sheet
                all_daily_patterns = []
                for symbol, result in daily_results.items():
                    if result.get('has_patterns', False):
                        for pattern_key, details in result.get('pattern_details', {}).items():
                            all_daily_patterns.append({
                                'symbol': symbol,
                                'pattern_name': pattern_key.upper(),
                                'timeframe': 'daily',
                                'details': details,
                                'candles_ago': 0,
                                'market_regime': result.get('market_regime', 'NEUTRAL')
                            })

                all_hourly_patterns = []
                for symbol, result in hourly_results.items():
                    if result.get('has_patterns', False):
                        for pattern_key, details in result.get('pattern_details', {}).items():
                            all_hourly_patterns.append({
                                'symbol': symbol,
                                'pattern_name': pattern_key.upper(),
                                'timeframe': 'hourly',
                                'details': details,
                                'candles_ago': 0,
                                'market_regime': result.get('market_regime', 'NEUTRAL')
                            })

                report_path = self.report_generator.generate_report(
                    top_patterns=top_patterns,
                    all_daily_patterns=all_daily_patterns,
                    all_hourly_patterns=all_hourly_patterns,
                    market_regime=market_regime
                )
                logger.info(f"Report generated: {report_path}")
            except Exception as e:
                logger.error(f"Error generating report: {e}", exc_info=True)
                report_path = None

            # Step 9: Send Telegram alert
            logger.info("\n[STEP 9/9] Sending Telegram alert...")
            try:
                telegram_success = self.telegram_notifier.send_premarket_pattern_alert(
                    top_patterns=top_patterns,
                    market_regime=market_regime,
                    stocks_analyzed=len(filtered_stocks),
                    total_patterns_found=daily_patterns_count + hourly_patterns_count
                )
                if telegram_success:
                    logger.info("Telegram alert sent successfully!")
                else:
                    logger.warning("Failed to send Telegram alert")
            except Exception as e:
                logger.error(f"Error sending Telegram alert: {e}", exc_info=True)
                telegram_success = False

            # Execution summary
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            logger.info("\n" + "=" * 60)
            logger.info("PRE-MARKET ANALYSIS COMPLETE")
            logger.info(f"Execution time: {execution_time:.1f} seconds")
            logger.info(f"Stocks analyzed: {len(filtered_stocks)}")
            logger.info(f"Total patterns found: {daily_patterns_count + hourly_patterns_count}")
            logger.info(f"Top patterns selected: {len(top_patterns)}")
            logger.info(f"Report: {report_path if report_path else 'Failed to generate'}")
            logger.info(f"Telegram alert: {'Sent' if telegram_success else 'Failed'}")
            logger.info("=" * 60)

            return {
                'success': True,
                'market_regime': market_regime,
                'stocks_analyzed': len(filtered_stocks),
                'daily_patterns': daily_patterns_count,
                'hourly_patterns': hourly_patterns_count,
                'top_patterns': top_patterns,
                'report_path': report_path,
                'telegram_sent': telegram_success,
                'execution_time': execution_time
            }

        except Exception as e:
            logger.error(f"Error in pre-market analysis: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _empty_result(self, market_regime: str = "NEUTRAL") -> Dict:
        """Return empty result when no patterns found"""
        return {
            'success': True,
            'market_regime': market_regime,
            'stocks_analyzed': 0,
            'daily_patterns': 0,
            'hourly_patterns': 0,
            'top_patterns': [],
            'execution_time': 0
        }


def main():
    """Main entry point for pre-market analyzer"""
    analyzer = PreMarketAnalyzer()
    result = analyzer.run()

    if result['success']:
        logger.info("\nAnalysis completed successfully!")
        logger.info(f"Top {len(result['top_patterns'])} pattern(s) selected for alerts")
    else:
        logger.error(f"\nAnalysis failed: {result.get('error', 'Unknown error')}")


if __name__ == "__main__":
    main()
