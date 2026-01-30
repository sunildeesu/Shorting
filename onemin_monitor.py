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
from api_coordinator import get_api_coordinator
from alert_history_manager import AlertHistoryManager
from central_quote_db import get_central_db
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

        # Initialize API Coordinator (Tier 2 optimization - centralized quote management)
        self.coordinator = get_api_coordinator(kite=self.kite)
        logger.info("API Coordinator enabled (shared cache + smart batching)")

        # Initialize Central Quote Database (Tier 3 - single source of truth)
        self.central_db = get_central_db()
        logger.info("Central Quote Database enabled (reads from central_quotes.db)")

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

        DATA ACCURACY FIRST: Will NOT silently fall back to all stocks if
        volume data is missing. Instead, logs a warning and continues with
        available data.

        Returns:
            List of eligible stock symbols

        Raises:
            RuntimeError: If stock list file cannot be loaded
        """
        # Load all F&O stocks - FAIL if stock list is unavailable
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                all_stocks = json.load(f)['stocks']
        except Exception as e:
            error_msg = f"CRITICAL: Failed to load stock list from {config.STOCK_LIST_FILE}: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        if not all_stocks:
            error_msg = "CRITICAL: Stock list is empty"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Filter for liquid stocks only
        eligible = []
        stocks_without_volume_data = []

        for symbol in all_stocks:
            # Get avg daily volume from price cache
            avg_volume = self.price_cache.get_avg_daily_volume(symbol)

            if avg_volume is None:
                stocks_without_volume_data.append(symbol)
            elif avg_volume >= config.MIN_AVG_DAILY_VOLUME_1MIN:
                eligible.append(symbol)

        # Log volume data coverage
        coverage_pct = ((len(all_stocks) - len(stocks_without_volume_data)) / len(all_stocks)) * 100

        if stocks_without_volume_data:
            logger.warning(f"Volume data MISSING for {len(stocks_without_volume_data)} stocks "
                          f"({100-coverage_pct:.1f}% missing)")
            if len(stocks_without_volume_data) <= 10:
                logger.warning(f"Stocks without volume data: {stocks_without_volume_data}")

        # DATA ACCURACY: Do NOT silently fall back to all stocks
        # If no eligible stocks, that's a data quality issue that should be visible
        if not eligible:
            if stocks_without_volume_data:
                logger.error(f"NO eligible stocks found - {len(stocks_without_volume_data)} stocks lack volume data")
                logger.error("This indicates volume data has not been collected yet")
                logger.error("Run stock_monitor.py first to collect volume data, or check price_cache.db")
            else:
                logger.error("NO eligible stocks found - all stocks below liquidity threshold")

            # Return empty list - don't silently monitor everything
            # This makes the data quality issue VISIBLE
            return []

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
        import time
        from service_health import get_health_tracker

        cycle_start = time.time()
        health = get_health_tracker()

        logger.info("=" * 80)
        logger.info(f"1-MIN MONITOR - Starting cycle at {datetime.now().strftime('%H:%M:%S')}")
        logger.info("=" * 80)

        # DEBUG: Log cache statistics
        self._log_cache_stats()

        stats = {
            'total_checked': 0,
            'alerts_sent': 0,
            'drop_alerts': 0,
            'rise_alerts': 0,
            'errors': 0
        }

        # DATA ACCURACY FIRST: Let data quality exceptions propagate
        # Do NOT wrap data fetching in try/except that silently continues
        # If data is bad, we want the monitor to FAIL VISIBLY

        # Fetch FRESH prices (no cache for price data - must be current)
        # This will raise RuntimeError if data is stale or unavailable
        logger.info(f"Fetching fresh prices for {len(self.stocks)} stocks...")
        price_data = self._fetch_fresh_prices()
        logger.info(f"Received price data for {len(price_data)} stocks")

        # DEBUG: Track stocks with price movements for sample analysis
        stocks_with_movements = []

        # Check each stock - per-stock errors are isolated but logged
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

                # DEBUG: Track price movements for sample analysis
                change_pct = abs(((current_price - price_1min_ago) / price_1min_ago) * 100)
                if change_pct >= 0.3:  # Track movements >= 0.3% (lower than alert threshold)
                    stocks_with_movements.append((symbol, change_pct, current_price, price_1min_ago))

                # Get price from 5 minutes ago (for momentum confirmation)
                _, price_5min_ago = self.price_cache.get_prices_5min(symbol)

                # Check for 1-min drop
                drop_priority = self.detector.check_for_drop_1min(symbol, current_price, price_1min_ago,
                                                      current_volume, oi, price_5min_ago)
                if drop_priority:
                    change_pct = self.detector.get_drop_percentage(current_price, price_1min_ago)
                    priority_icon = "🔥" if drop_priority == "HIGH" else "🔴"
                    logger.info(f"{priority_icon} {symbol}: DROP detected - {change_pct:.2f}% in 1 minute [{drop_priority}]")

                    # Get and increment alert count for today (with direction)
                    alert_count = self.alert_history.increment_alert_count(symbol, direction="drop")
                    direction_arrows = self.alert_history.get_direction_arrows(symbol)

                    self._send_alert(symbol, "drop", current_price, price_1min_ago,
                                    current_volume, oi, priority=drop_priority, alert_count=alert_count,
                                    direction_arrows=direction_arrows)
                    stats['alerts_sent'] += 1
                    stats['drop_alerts'] += 1

                # Check for 1-min rise (if enabled)
                elif config.ENABLE_RISE_ALERTS:
                    rise_priority = self.detector.check_for_rise_1min(symbol, current_price, price_1min_ago,
                                                        current_volume, oi, price_5min_ago)
                    if rise_priority:
                        change_pct = self.detector.get_rise_percentage(current_price, price_1min_ago)
                        priority_icon = "🔥" if rise_priority == "HIGH" else "🟢"
                        logger.info(f"{priority_icon} {symbol}: RISE detected - {change_pct:.2f}% in 1 minute [{rise_priority}]")

                        # Get and increment alert count for today (with direction)
                        alert_count = self.alert_history.increment_alert_count(symbol, direction="rise")
                        direction_arrows = self.alert_history.get_direction_arrows(symbol)

                        self._send_alert(symbol, "rise", current_price, price_1min_ago,
                                        current_volume, oi, priority=rise_priority, alert_count=alert_count,
                                        direction_arrows=direction_arrows)
                        stats['alerts_sent'] += 1
                        stats['rise_alerts'] += 1

            except Exception as e:
                # Per-stock errors are logged but don't stop the whole monitor
                logger.error(f"{symbol}: Error processing - {e}")
                stats['errors'] += 1

        # DEBUG: Log sample price movements (even if they didn't trigger alerts)
        if stocks_with_movements:
            stocks_with_movements.sort(key=lambda x: x[1], reverse=True)  # Sort by change %
            logger.info(f"[MOVEMENTS] Found {len(stocks_with_movements)} stocks with >=0.3% price change")
            for symbol, change_pct, curr_price, prev_price in stocks_with_movements[:3]:
                direction = "UP" if curr_price > prev_price else "DOWN"
                logger.info(f"[MOVEMENTS] {symbol}: {change_pct:.2f}% {direction} (₹{prev_price:.2f} → ₹{curr_price:.2f})")
        else:
            logger.info(f"[MOVEMENTS] No stocks with >=0.3% price change this minute")

        # Print summary
        logger.info("=" * 80)
        logger.info(f"1-MIN MONITOR - Cycle complete")
        logger.info(f"  Checked: {stats['total_checked']} stocks")
        logger.info(f"  Alerts: {stats['alerts_sent']} ({stats['drop_alerts']} drops, {stats['rise_alerts']} rises)")
        logger.info(f"  Errors: {stats['errors']}")
        logger.info("=" * 80)

        # Report health metrics
        cycle_duration_ms = int((time.time() - cycle_start) * 1000)
        health.heartbeat("onemin_monitor", cycle_duration_ms)
        health.report_metric("onemin_monitor", "last_cycle_stocks_checked", stats['total_checked'])
        health.report_metric("onemin_monitor", "last_cycle_alerts_sent", stats['alerts_sent'])
        health.report_metric("onemin_monitor", "last_cycle_errors", stats['errors'])
        health.report_metric("onemin_monitor", "last_cycle_duration_ms", cycle_duration_ms)

        return stats

    def _fetch_fresh_prices(self) -> Dict:
        """
        Fetch FRESH prices from Central Quote Database.
        MIGRATED: Now reads from central_quotes.db instead of making API calls.
        The central_data_collector populates this database every minute.

        DATA ACCURACY FIRST: Reports issues prominently but falls back to API if needed.
        All issues are tracked in service_health for dashboard visibility.

        Returns:
            Dict of {symbol: {price, volume, oi, timestamp}}
        """
        from service_health import get_health_tracker

        if not self.stocks:
            return {}

        health = get_health_tracker()

        # CRITICAL: Check data freshness BEFORE using it
        is_fresh, age_minutes = self.central_db.is_data_fresh(max_age_minutes=2)

        # Track central DB health
        if age_minutes is None:
            # No data at all in central database
            error_msg = "No data in central database - is central_data_collector running?"
            logger.error(f"CENTRAL_DB_FAILURE: {error_msg}")
            health.report_error("onemin_monitor", "central_db_empty", error_msg)
            health.report_metric("onemin_monitor", "data_source", "api_fallback")

            logger.warning("Falling back to direct API calls...")
            return self._fetch_fresh_prices_from_api()

        if not is_fresh:
            # Data is stale
            error_msg = f"Central database data is STALE ({age_minutes} minutes old, max allowed: 2 min)"
            logger.error(f"CENTRAL_DB_STALE: {error_msg}")
            health.report_error("onemin_monitor", "central_db_stale", error_msg,
                              details={"age_minutes": age_minutes})
            health.report_metric("onemin_monitor", "data_source", "api_fallback")

            logger.warning("Falling back to direct API calls...")
            return self._fetch_fresh_prices_from_api()

        # Central DB is fresh - use it
        logger.info(f"Data freshness check PASSED: {age_minutes} minute(s) old")
        health.report_metric("onemin_monitor", "data_source", "central_db")
        health.report_metric("onemin_monitor", "central_db_age_minutes", age_minutes)

        price_data = {}

        # Read latest quotes from central database (ZERO API calls!)
        db_quotes = self.central_db.get_latest_stock_quotes(symbols=self.stocks)

        if not db_quotes:
            # This shouldn't happen if data freshness check passed
            error_msg = "No quotes returned from central database despite freshness check passing"
            logger.error(f"CENTRAL_DB_FAILURE: {error_msg}")
            health.report_error("onemin_monitor", "central_db_no_quotes", error_msg)
            health.report_metric("onemin_monitor", "data_source", "api_fallback")

            logger.warning("Falling back to direct API calls...")
            return self._fetch_fresh_prices_from_api()

        # Validate quote coverage
        coverage_pct = (len(db_quotes) / len(self.stocks)) * 100
        health.report_metric("onemin_monitor", "quote_coverage_pct", round(coverage_pct, 1))

        if coverage_pct < 90:
            # Less than 90% of requested stocks have quotes - data quality issue
            error_msg = f"Low quote coverage - only {len(db_quotes)}/{len(self.stocks)} stocks ({coverage_pct:.1f}%)"
            logger.warning(f"CENTRAL_DB_DEGRADED: {error_msg}")
            health.report_error("onemin_monitor", "low_quote_coverage", error_msg,
                              details={"coverage_pct": coverage_pct})
            # Continue with what we have - don't fallback for partial data

        # Convert to expected format with validation
        invalid_quotes = 0
        for symbol, quote in db_quotes.items():
            price = quote.get('price', 0)

            # Validate price is non-zero
            if price <= 0:
                logger.warning(f"{symbol}: Invalid price ({price}) - skipping")
                invalid_quotes += 1
                continue

            price_data[symbol] = {
                'price': price,
                'volume': quote.get('volume', 0),
                'oi': quote.get('oi', 0),
                'timestamp': quote.get('timestamp', datetime.now().isoformat())
            }

        if invalid_quotes > 0:
            logger.warning(f"Skipped {invalid_quotes} quotes with invalid prices")
            health.report_metric("onemin_monitor", "invalid_quotes", invalid_quotes)

        logger.info(f"Read {len(price_data)} valid quotes from central database (0 API calls)")
        health.report_metric("onemin_monitor", "quotes_fetched", len(price_data))
        health.clear_error("onemin_monitor", "central_db_empty")
        health.clear_error("onemin_monitor", "central_db_stale")

        return price_data

    def _fetch_fresh_prices_from_api(self) -> Dict:
        """
        FALLBACK: Fetch prices from Kite API when central DB is unavailable.
        Uses batch API for efficiency (100 stocks per call).

        NOTE: This is a fallback - central_data_collector should be running.
        All API fallback usage is tracked in service_health for visibility.

        Returns:
            Dict of {symbol: {price, volume, oi, timestamp}}
        """
        from service_health import get_health_tracker
        health = get_health_tracker()

        logger.warning("=" * 60)
        logger.warning("API FALLBACK MODE - central_data_collector may not be running!")
        logger.warning("=" * 60)

        health.report_error("onemin_monitor", "api_fallback_used",
                          "Using direct API calls instead of central database",
                          severity="warning")
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

            # Fetch quotes in batches of 200 (Kite API limit is 500, using 200 for optimal performance)
            # Use API coordinator for smart batching (Tier 2 optimization)
            batch_size = 200
            for i in range(0, len(instruments), batch_size):
                batch = instruments[i:i + batch_size]

                logger.debug(f"Fetching batch {i//batch_size + 1} ({len(batch)} instruments)...")
                # Note: coordinator.get_multiple_instruments() bypasses cache for non-NSE instruments
                quotes = self.coordinator.get_multiple_instruments(
                    instruments=batch,
                    use_cache=False  # Always fetch fresh for 1-min alerts
                )

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
            logger.error(f"Failed to fetch prices from Kite API: {e}")

        return price_data

    def _send_alert(self, symbol: str, direction: str, current_price: float,
                    prev_price: float, current_volume: int, oi: float, priority: str = "NORMAL",
                    alert_count: int = None, direction_arrows: str = None):
        """
        Send 1-min alert via Telegram and log to Excel.

        Args:
            symbol: Stock symbol
            direction: "drop" or "rise"
            current_price: Current price
            prev_price: Price from 1 minute ago
            current_volume: Current trading volume
            oi: Open interest
            priority: "HIGH" or "NORMAL"
            alert_count: Count of how many times this stock has alerted today
            direction_arrows: Direction history arrows (e.g., "↓ ↑ ↓")
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
                oi_analysis=oi_analysis,
                priority=priority,
                alert_count=alert_count,
                direction_arrows=direction_arrows
            )
        except Exception as e:
            logger.error(f"{symbol}: Failed to send Telegram alert - {e}")
            telegram_sent = False

        # Log to Excel
        try:
            self.excel_logger.log_alert(
                symbol=symbol,
                alert_type=f"1min-{priority}",  # e.g., "1min-HIGH" or "1min-NORMAL"
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

    def _log_cache_stats(self):
        """Log cache statistics to diagnose alert detection issues"""
        try:
            # Count stocks with various snapshot levels
            stocks_with_current = 0
            stocks_with_1min_history = 0
            stocks_with_5min_history = 0

            for symbol in self.stocks:
                if symbol in self.price_cache.cache:
                    cache_data = self.price_cache.cache[symbol]
                    if cache_data.get('current'):
                        stocks_with_current += 1
                    if cache_data.get('previous_1min'):
                        stocks_with_1min_history += 1
                    if cache_data.get('previous'):  # 5-min snapshot
                        stocks_with_5min_history += 1

            logger.info(f"[CACHE STATS] Stocks in cache: {len(self.price_cache.cache)}")
            logger.info(f"[CACHE STATS] With current snapshot: {stocks_with_current}/{len(self.stocks)}")
            logger.info(f"[CACHE STATS] With 1-min history: {stocks_with_1min_history}/{len(self.stocks)}")
            logger.info(f"[CACHE STATS] With 5-min history: {stocks_with_5min_history}/{len(self.stocks)}")

            # Show sample stocks with full data (for detailed debugging)
            sample_stocks = []
            for symbol in self.stocks[:5]:  # First 5 stocks
                if symbol in self.price_cache.cache:
                    cache_data = self.price_cache.cache[symbol]
                    has_current = cache_data.get('current') is not None
                    has_1min = cache_data.get('previous_1min') is not None
                    has_5min = cache_data.get('previous') is not None
                    sample_stocks.append(f"{symbol}(C:{has_current},1m:{has_1min},5m:{has_5min})")

            if sample_stocks:
                logger.info(f"[CACHE SAMPLE] First 5 stocks: {', '.join(sample_stocks)}")

        except Exception as e:
            logger.error(f"Error logging cache stats: {e}")


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
