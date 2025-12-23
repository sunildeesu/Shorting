#!/usr/bin/env python3
"""
1-Minute Ultra-Fast Alert Monitor
Detects rapid price movements before 5-min alerts trigger

Features:
- TRUE 1-minute detection with fresh API calls every minute
- Monitors only liquid stocks (500K+ avg daily volume)
- 5-layer filtering for high-quality alerts
- Independent from 5-min monitor (no cache dependency)
- 10-minute cooldown per stock
"""

import json
import logging
import os
import sys
from datetime import datetime, time
from typing import Dict, List, Optional
from kiteconnect import KiteConnect

import config
from price_cache import PriceCache
from unified_quote_cache import UnifiedQuoteCache
from alert_history_manager import AlertHistoryManager
from alert_excel_logger import AlertExcelLogger
from telegram_notifier import TelegramNotifier
from onemin_alert_detector import OneMinAlertDetector
from market_utils import is_market_open, get_market_status

# Optional features
try:
    from rsi_analyzer import calculate_rsi_with_crossovers
    from unified_data_cache import UnifiedDataCache
    RSI_AVAILABLE = True
except ImportError:
    RSI_AVAILABLE = False

try:
    from oi_analyzer import get_oi_analyzer
    from futures_mapper import get_futures_mapper
    OI_AVAILABLE = True
except ImportError:
    OI_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/onemin_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class OneMinMonitor:
    """1-minute monitoring system for ultra-fast alerts"""

    def __init__(self):
        """Initialize 1-min monitor with all required components"""

        # Feature flag check
        if not config.ENABLE_1MIN_ALERTS:
            logger.info("1-min alerts disabled in config (ENABLE_1MIN_ALERTS=false)")
            sys.exit(0)

        # Market check (trading day + market hours)
        if not is_market_open():
            status = get_market_status()
            if not status['is_trading_day']:
                logger.info(f"Not a trading day (weekend/holiday) - skipping")
            else:
                logger.info(f"Outside market hours (9:30 AM - 3:25 PM) - skipping")
            sys.exit(0)

        # Initialize Kite Connect
        logger.info("Initializing Kite Connect...")
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Initialize core components
        logger.info("Initializing core components...")
        self.price_cache = PriceCache()
        self.alert_history = AlertHistoryManager()
        self.excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
        self.telegram = TelegramNotifier()

        # Initialize alert detector
        self.detector = OneMinAlertDetector(
            price_cache=self.price_cache,
            alert_history=self.alert_history
        )

        # Initialize optional features
        self._init_optional_features()

        # Load eligible stocks (liquid stocks only)
        self.stocks = self._load_eligible_stocks()
        logger.info(f"Monitoring {len(self.stocks)} liquid stocks for 1-min alerts")

    def _init_optional_features(self):
        """Initialize optional features (RSI, OI, etc.)"""

        # Initialize unified quote cache for metadata (volume history, OI)
        # Note: Price data is always fetched fresh (no cache)
        self.quote_cache = None
        if config.ENABLE_UNIFIED_CACHE:
            try:
                self.quote_cache = UnifiedQuoteCache(
                    cache_file=config.QUOTE_CACHE_FILE,
                    ttl_seconds=config.CACHE_MAX_AGE_1MIN
                )
                logger.info("Quote cache enabled (for volume/OI metadata)")
            except Exception as e:
                logger.error(f"Failed to initialize quote cache: {e}")

        # Initialize unified data cache for RSI calculation
        self.data_cache = None
        if RSI_AVAILABLE and config.ENABLE_RSI:
            try:
                from unified_data_cache import UnifiedDataCache
                self.data_cache = UnifiedDataCache(
                    cache_dir=config.HISTORICAL_CACHE_DIR
                )
                logger.info("Data cache enabled (for RSI calculation)")
            except Exception as e:
                logger.error(f"Failed to initialize data cache: {e}")

        # Initialize OI analyzer
        self.oi_analyzer = None
        self.futures_mapper = None
        if OI_AVAILABLE and config.ENABLE_OI_ANALYSIS:
            try:
                self.oi_analyzer = get_oi_analyzer()
                logger.info("OI analysis enabled")

                # Initialize futures mapper for OI data
                if config.ENABLE_FUTURES_OI:
                    self.futures_mapper = get_futures_mapper(
                        cache_file=config.FUTURES_MAPPING_FILE
                    )
                    logger.info("Futures mapper enabled")
            except Exception as e:
                logger.error(f"Failed to initialize OI features: {e}")

    # Market check is now handled by market_utils.is_market_open()
    # which checks for weekends, NSE holidays, and market hours (9:30 AM - 3:25 PM)

    def _load_eligible_stocks(self) -> List[str]:
        """
        Load stocks eligible for 1-min monitoring (liquid stocks only).
        Only monitors stocks with >= 500K average daily volume.

        Returns:
            List of eligible stock symbols
        """
        # Load all F&O stocks
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                all_stocks = json.load(f)['stocks']
        except Exception as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

        # Filter for liquid stocks only
        eligible = []
        for symbol in all_stocks:
            # Get avg daily volume from price cache
            avg_volume = self.price_cache.get_avg_daily_volume(symbol)

            if avg_volume and avg_volume >= config.MIN_AVG_DAILY_VOLUME_1MIN:
                eligible.append(symbol)

        # If no stocks have volume data yet, include all stocks
        # (volume filtering will happen during first few runs as data accumulates)
        if not eligible:
            logger.warning("No stocks with volume data yet - monitoring all stocks")
            logger.warning("Volume filtering will activate as data accumulates")
            eligible = all_stocks[:100]  # Limit to first 100 for initial runs

        logger.info(f"Liquidity filter: {len(eligible)}/{len(all_stocks)} stocks qualify "
                   f"(>={config.MIN_AVG_DAILY_VOLUME_1MIN:,} avg daily volume)")

        return eligible

    def monitor(self) -> Dict:
        """
        Main monitoring function - runs every minute.
        Fetches FRESH price data and checks for 1-min alerts.

        Returns:
            Statistics dict with alert counts
        """
        logger.info("=" * 80)
        logger.info(f"1-MIN MONITOR - Starting cycle at {datetime.now().strftime('%H:%M:%S')}")
        logger.info("=" * 80)

        stats = {
            'total_checked': 0,
            'alerts_sent': 0,
            'drop_alerts': 0,
            'rise_alerts': 0,
            'errors': 0
        }

        try:
            # Fetch FRESH prices (no cache for price data - must be current)
            logger.info(f"Fetching fresh prices for {len(self.stocks)} stocks...")
            price_data = self._fetch_fresh_prices()
            logger.info(f"Received price data for {len(price_data)} stocks")

            # Check each stock
            for symbol in self.stocks:
                stats['total_checked'] += 1

                if symbol not in price_data:
                    logger.debug(f"{symbol}: No price data available")
                    continue

                try:
                    # Extract quote data
                    quote = price_data[symbol]
                    current_price = quote.get('price', 0)
                    current_volume = quote.get('volume', 0)
                    oi = quote.get('oi', 0)

                    if current_price == 0:
                        logger.debug(f"{symbol}: Invalid price (0)")
                        continue

                    # Update price cache (1-min granularity)
                    self.price_cache.update_price_1min(symbol, current_price, current_volume)

                    # Get price from 1 minute ago
                    price_1min_ago = self.price_cache.get_price_1min_ago(symbol)
                    if not price_1min_ago:
                        logger.debug(f"{symbol}: No previous 1-min price for comparison")
                        continue  # Need at least 1 previous snapshot

                    # Check for 1-min drop
                    if self.detector.check_for_drop_1min(symbol, current_price, price_1min_ago,
                                                          current_volume, oi):
                        change_pct = self.detector.get_drop_percentage(current_price, price_1min_ago)
                        logger.info(f"🔴 {symbol}: DROP detected - {change_pct:.2f}% in 1 minute")

                        self._send_alert(symbol, "drop", current_price, price_1min_ago,
                                        current_volume, oi)
                        stats['alerts_sent'] += 1
                        stats['drop_alerts'] += 1

                    # Check for 1-min rise (if enabled)
                    elif config.ENABLE_RISE_ALERTS and \
                         self.detector.check_for_rise_1min(symbol, current_price, price_1min_ago,
                                                            current_volume, oi):
                        change_pct = self.detector.get_rise_percentage(current_price, price_1min_ago)
                        logger.info(f"🟢 {symbol}: RISE detected - {change_pct:.2f}% in 1 minute")

                        self._send_alert(symbol, "rise", current_price, price_1min_ago,
                                        current_volume, oi)
                        stats['alerts_sent'] += 1
                        stats['rise_alerts'] += 1

                except Exception as e:
                    logger.error(f"{symbol}: Error processing - {e}")
                    stats['errors'] += 1

        except Exception as e:
            logger.error(f"Fatal error in monitor cycle: {e}", exc_info=True)
            stats['errors'] += 1

        # Print summary
        logger.info("=" * 80)
        logger.info(f"1-MIN MONITOR - Cycle complete")
        logger.info(f"  Checked: {stats['total_checked']} stocks")
        logger.info(f"  Alerts: {stats['alerts_sent']} ({stats['drop_alerts']} drops, {stats['rise_alerts']} rises)")
        logger.info(f"  Errors: {stats['errors']}")
        logger.info("=" * 80)

        return stats

    def _fetch_fresh_prices(self) -> Dict:
        """
        Fetch FRESH prices from Kite API (no cache for price data).
        Uses batch API for efficiency (100 stocks per call).

        Returns:
            Dict of {symbol: {price, volume, oi, timestamp}}
        """
        if not self.stocks:
            return {}

        price_data = {}

        try:
            # Prepare instrument symbols for Kite batch API
            # Format: NSE:SYMBOL or NFO:SYMBOL (for futures OI)
            instruments = []
            symbol_map = {}  # Map Kite instrument to our symbol

            for symbol in self.stocks:
                # Equity quote
                kite_symbol = f"NSE:{symbol}"
                instruments.append(kite_symbol)
                symbol_map[kite_symbol] = symbol

                # Futures quote (if OI enabled)
                if self.futures_mapper and config.ENABLE_FUTURES_OI:
                    futures_symbol = self.futures_mapper.get_futures_symbol(symbol)
                    if futures_symbol:
                        futures_kite_symbol = f"NFO:{futures_symbol}"
                        instruments.append(futures_kite_symbol)
                        symbol_map[futures_kite_symbol] = symbol

            # Fetch quotes in batches of 100 (Kite API limit is 500, but 100 is safer)
            batch_size = 100
            for i in range(0, len(instruments), batch_size):
                batch = instruments[i:i + batch_size]

                logger.debug(f"Fetching batch {i//batch_size + 1} ({len(batch)} instruments)...")
                quotes = self.kite.quote(batch)

                # Parse quotes
                for kite_symbol, quote in quotes.items():
                    symbol = symbol_map.get(kite_symbol)
                    if not symbol:
                        continue

                    # Check if this is equity or futures quote
                    if kite_symbol.startswith("NSE:"):
                        # Equity quote - extract price and volume
                        if symbol not in price_data:
                            price_data[symbol] = {}

                        price_data[symbol]['price'] = quote.get('last_price', 0)
                        price_data[symbol]['volume'] = quote.get('volume', 0)
                        price_data[symbol]['timestamp'] = datetime.now().isoformat()

                    elif kite_symbol.startswith("NFO:"):
                        # Futures quote - extract OI
                        if symbol not in price_data:
                            price_data[symbol] = {}

                        price_data[symbol]['oi'] = quote.get('oi', 0)

        except Exception as e:
            logger.error(f"Failed to fetch prices from Kite: {e}")

        return price_data

    def _send_alert(self, symbol: str, direction: str, current_price: float,
                    prev_price: float, current_volume: int, oi: float):
        """
        Send 1-min alert via Telegram and log to Excel.

        Args:
            symbol: Stock symbol
            direction: "drop" or "rise"
            current_price: Current price
            prev_price: Price from 1 minute ago
            current_volume: Current trading volume
            oi: Open interest
        """
        change_pct = abs(((current_price - prev_price) / prev_price) * 100)

        # Get additional context
        rsi_analysis = self._get_rsi(symbol) if RSI_AVAILABLE and config.ENABLE_RSI else None
        oi_analysis = self._get_oi_analysis(symbol, oi, change_pct) if oi > 0 else None
        volume_data = self._get_volume_data(symbol, current_volume)
        market_cap = self._get_market_cap(symbol)

        # Send Telegram alert
        try:
            telegram_sent = self.telegram.send_1min_alert(
                symbol=symbol,
                direction=direction,
                current_price=current_price,
                previous_price=prev_price,
                change_percent=change_pct,
                volume_data=volume_data,
                market_cap_cr=market_cap,
                rsi_analysis=rsi_analysis,
                oi_analysis=oi_analysis
            )
        except Exception as e:
            logger.error(f"{symbol}: Failed to send Telegram alert - {e}")
            telegram_sent = False

        # Log to Excel
        try:
            self.excel_logger.log_alert(
                symbol=symbol,
                alert_type="1min",
                drop_percent=change_pct if direction == "drop" else -change_pct,
                current_price=current_price,
                previous_price=prev_price,
                volume_data=volume_data,
                market_cap_cr=market_cap,
                telegram_sent=telegram_sent,
                rsi_analysis=rsi_analysis,
                oi_analysis=oi_analysis
            )
        except Exception as e:
            logger.error(f"{symbol}: Failed to log to Excel - {e}")

        # Update alert history (cooldown tracking)
        # Note: should_send_alert() is already called in detector, but record it here too
        self.alert_history.should_send_alert(symbol, "1min",
                                             cooldown_minutes=config.COOLDOWN_1MIN_ALERTS)

    def _get_rsi(self, symbol: str) -> Optional[Dict]:
        """Get RSI analysis for symbol"""
        if not RSI_AVAILABLE or not self.data_cache:
            return None

        try:
            # Get historical data from cache
            historical_data = self.data_cache.get_historical_data(
                symbol=symbol,
                kite_client=self.kite,
                days=config.RSI_MIN_DATA_DAYS
            )

            if historical_data is not None:
                return calculate_rsi_with_crossovers(historical_data)
        except Exception as e:
            logger.debug(f"{symbol}: RSI calculation failed - {e}")

        return None

    def _get_oi_analysis(self, symbol: str, oi: float, price_change: float) -> Optional[Dict]:
        """Get OI analysis for symbol"""
        if not OI_AVAILABLE or not self.oi_analyzer:
            return None

        try:
            return self.oi_analyzer.analyze_oi(symbol, oi, price_change)
        except Exception as e:
            logger.debug(f"{symbol}: OI analysis failed - {e}")

        return None

    def _get_volume_data(self, symbol: str, current_volume: int) -> Dict:
        """Get volume data from price cache"""
        volume_data = self.price_cache.get_volume_data_1min(symbol)
        volume_data['spike_multiplier'] = (current_volume / volume_data['avg_volume']
                                           if volume_data['avg_volume'] > 0 else 0)
        return volume_data

    def _get_market_cap(self, symbol: str) -> float:
        """Get market cap (placeholder - implement if needed)"""
        # TODO: Implement market cap calculation
        return 0.0


def main():
    """Main entry point"""
    try:
        monitor = OneMinMonitor()
        monitor.monitor()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
