#!/usr/bin/env python3
"""
Run EOD Analysis for Specific Date
Allows running historical analysis for any given date
"""

import json
import logging
import time
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from kiteconnect import KiteConnect
import config
from eod_cache_manager import EODCacheManager
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


class EODAnalyzerForDate:
    """EOD analyzer that can run for specific historical dates"""

    def __init__(self):
        """Initialize EOD analyzer with all components"""
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Initialize components
        self.cache_manager = EODCacheManager()
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
        """Build mapping of stock symbol to instrument token"""
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
        token = self.instrument_tokens.get(symbol)
        if token is None:
            logger.warning(f"{symbol}: No instrument token found")
        return token

    def _fetch_historical_data_for_date(
        self,
        symbol: str,
        target_date: datetime,
        days_back: int = 30
    ) -> List[Dict]:
        """
        Fetch historical data ending on target_date

        Args:
            symbol: Stock symbol
            target_date: Date to fetch data up to
            days_back: Number of days of history to fetch

        Returns:
            List of OHLCV candles
        """
        token = self._get_instrument_token(symbol)
        if not token:
            return []

        try:
            from_date = target_date - timedelta(days=days_back + 10)  # Extra buffer
            to_date = target_date

            data = self.kite.historical_data(
                instrument_token=token,
                from_date=from_date,
                to_date=to_date,
                interval="day"
            )

            # Filter to get exactly up to target_date
            filtered_data = [
                candle for candle in data
                if candle['date'].date() <= target_date.date()
            ]

            # Get last 30 days
            return filtered_data[-30:] if len(filtered_data) > 30 else filtered_data

        except Exception as e:
            logger.error(f"{symbol}: Error fetching historical data - {e}")
            return []

    def _fetch_intraday_data_for_date(
        self,
        symbol: str,
        target_date: datetime
    ) -> List[Dict]:
        """
        Fetch intraday data for specific date

        Args:
            symbol: Stock symbol
            target_date: Date to fetch intraday data for

        Returns:
            List of 5-minute candles
        """
        token = self._get_instrument_token(symbol)
        if not token:
            return []

        try:
            # Fetch intraday data for the target date
            from_time = target_date.replace(hour=9, minute=15, second=0)
            to_time = target_date.replace(hour=15, minute=30, second=0)

            data = self.kite.historical_data(
                instrument_token=token,
                from_date=from_time,
                to_date=to_time,
                interval="5minute"
            )

            return data

        except Exception as e:
            logger.error(f"{symbol}: Error fetching intraday data - {e}")
            return []

    def run_analysis(self, target_date: datetime) -> str:
        """
        Run EOD analysis for specific date

        Args:
            target_date: Date to run analysis for

        Returns:
            Path to generated report
        """
        logger.info("="*80)
        logger.info(f"Starting EOD Stock Analysis for {target_date.strftime('%Y-%m-%d')}")
        logger.info("="*80)

        start_time = time.time()

        # Step 1: Fetch historical data for all stocks (needed for filtering)
        logger.info("Step 1: Fetching historical data for date filtering...")
        quote_data = {}

        for symbol in self.fo_stocks:
            token = self._get_instrument_token(symbol)
            if not token:
                continue

            try:
                # Fetch just the target date's data for filtering
                historical = self.kite.historical_data(
                    instrument_token=token,
                    from_date=target_date,
                    to_date=target_date,
                    interval="day"
                )

                if historical and len(historical) > 0:
                    candle = historical[0]
                    # Create quote-like structure
                    quote_key = f"NSE:{symbol}"
                    quote_data[quote_key] = {
                        'volume': candle['volume'],
                        'ohlc': {
                            'open': candle['open'],
                            'high': candle['high'],
                            'low': candle['low'],
                            'close': candle['close']
                        }
                    }

                time.sleep(0.1)  # Rate limiting

            except Exception as e:
                logger.error(f"{symbol}: Error fetching data - {e}")

        logger.info(f"Fetched data for {len(quote_data)} stocks")

        if not quote_data:
            logger.error("No data fetched. Aborting analysis.")
            return None

        # Step 2: Filter stocks using smart filtering
        logger.info("Step 2: Filtering active stocks...")
        filtered_stocks_with_prefix = self.stock_filter.filter_stocks(quote_data)

        # Strip NSE: prefix from filtered stocks
        filtered_stocks = [s.replace("NSE:", "") for s in filtered_stocks_with_prefix]

        logger.info(f"Filtered {len(self.fo_stocks)} → {len(filtered_stocks)} stocks "
                   f"({len(filtered_stocks)/len(self.fo_stocks)*100:.1f}% retention)")

        if not filtered_stocks:
            logger.warning("No stocks passed filtering.")
            filtered_stocks = []

        # Step 3: Fetch intraday data for filtered stocks
        logger.info("Step 3: Fetching intraday data for filtered stocks...")
        intraday_data_map = {}

        for symbol in filtered_stocks:
            intraday_data = self._fetch_intraday_data_for_date(symbol, target_date)
            intraday_data_map[symbol] = intraday_data
            time.sleep(0.1)  # Rate limiting

        logger.info(f"Fetched intraday data for {len(intraday_data_map)} stocks")

        # Step 4: Fetch 30-day historical data for filtered stocks
        logger.info("Step 4: Fetching 30-day historical data...")
        historical_data_map = {}

        for symbol in filtered_stocks:
            historical_data = self._fetch_historical_data_for_date(symbol, target_date, days_back=30)
            historical_data_map[symbol] = historical_data
            time.sleep(0.1)  # Rate limiting

        logger.info(f"Fetched historical data for {len(historical_data_map)} stocks")

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
            target_date
        )

        # Log summary
        elapsed_time = time.time() - start_time
        logger.info("="*80)
        logger.info(f"EOD Analysis Complete for {target_date.strftime('%Y-%m-%d')}!")
        logger.info(f"Report: {report_path}")
        logger.info(f"Time taken: {elapsed_time:.1f} seconds")
        logger.info("="*80)

        return report_path


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python run_eod_for_date.py YYYY-MM-DD")
        print("Example: python run_eod_for_date.py 2025-11-03")
        sys.exit(1)

    try:
        # Parse date from command line
        date_str = sys.argv[1]
        target_date = datetime.strptime(date_str, '%Y-%m-%d')

        # Run analysis
        analyzer = EODAnalyzerForDate()
        report_path = analyzer.run_analysis(target_date)

        if report_path:
            print(f"\n✅ EOD Analysis complete for {date_str}! Report saved to: {report_path}\n")
        else:
            print(f"\n❌ EOD Analysis failed for {date_str}. Check logs for details.\n")

    except ValueError:
        print("❌ Invalid date format. Use YYYY-MM-DD (e.g., 2025-11-03)")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error in EOD analysis: {e}", exc_info=True)
        print(f"\n❌ Fatal error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
