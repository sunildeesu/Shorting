import json
import logging
import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional
import time
import random
import pandas as pd
from price_cache import PriceCache
from telegram_notifier import TelegramNotifier
from alert_history_manager import AlertHistoryManager
from unified_quote_cache import UnifiedQuoteCache
from unified_data_cache import UnifiedDataCache
from rsi_analyzer import calculate_rsi_with_crossovers
import config

# Import data source libraries based on configuration
if not config.DEMO_MODE:
    if config.DATA_SOURCE == 'yahoo':
        import yfinance as yf
    elif config.DATA_SOURCE == 'kite':
        from kiteconnect import KiteConnect
    else:  # nsepy
        from nsepy import get_quote

logger = logging.getLogger(__name__)

class StockMonitor:
    """Monitors NSE F&O stocks for significant price drops"""

    def __init__(self):
        self.price_cache = PriceCache()
        self.telegram = TelegramNotifier()
        self.stocks = self._load_stock_list()

        # Alert tracking for deduplication (PERSISTENT - survives script restarts)
        self.alert_history_manager = AlertHistoryManager()

        # Load shares outstanding for market cap calculation
        self.shares_outstanding = self._load_shares_outstanding()

        # Initialize unified quote cache (if enabled)
        self.quote_cache = None
        self.data_cache = None
        if config.ENABLE_UNIFIED_CACHE:
            try:
                self.quote_cache = UnifiedQuoteCache(
                    cache_file=config.QUOTE_CACHE_FILE,
                    ttl_seconds=config.QUOTE_CACHE_TTL_SECONDS
                )
                self.data_cache = UnifiedDataCache(
                    cache_dir=config.HISTORICAL_CACHE_DIR
                )
                logger.info(f"Unified cache enabled (quote + data cache)")
            except Exception as e:
                logger.error(f"Failed to initialize unified cache: {e}")
                self.quote_cache = None
                self.data_cache = None

        # Initialize Kite Connect if using kite data source
        if not config.DEMO_MODE and config.DATA_SOURCE == 'kite':
            if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
                raise ValueError("Kite Connect requires KITE_API_KEY and KITE_ACCESS_TOKEN in .env file")
            self.kite = KiteConnect(api_key=config.KITE_API_KEY)
            self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
            logger.info("Kite Connect initialized successfully")

            # Load instrument tokens for historical data fetching
            self.instrument_tokens = self._load_instrument_tokens()
        else:
            self.instrument_tokens = {}

    def _load_stock_list(self) -> List[str]:
        """Load F&O stock list from JSON file"""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                data = json.load(f)
                stocks = data['stocks']

                # Add .NS suffix for Yahoo Finance
                if config.DATA_SOURCE == 'yahoo':
                    return [f"{symbol}{config.YAHOO_FINANCE_SUFFIX}" for symbol in stocks]
                else:
                    # NSEpy uses raw NSE symbols (no suffix)
                    return stocks
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

    def _load_shares_outstanding(self) -> Dict[str, int]:
        """Load shares outstanding data from JSON file for market cap calculation"""
        shares_file = "data/shares_outstanding.json"
        try:
            if os.path.exists(shares_file):
                with open(shares_file, 'r') as f:
                    shares_data = json.load(f)
                    logger.info(f"Loaded shares outstanding for {len(shares_data)} stocks")
                    return shares_data
            else:
                logger.warning(f"Shares outstanding file not found: {shares_file}")
                logger.warning("Market cap will not be calculated in alerts")
                return {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load shares outstanding: {e}")
            return {}

    def _load_instrument_tokens(self) -> Dict[str, int]:
        """Load instrument tokens for Kite API historical data fetching"""
        tokens_file = "data/instrument_tokens.json"
        try:
            if os.path.exists(tokens_file):
                with open(tokens_file, 'r') as f:
                    tokens = json.load(f)
                    logger.info(f"Loaded {len(tokens)} instrument tokens")
                    return tokens
            else:
                logger.warning(f"Instrument tokens file not found: {tokens_file}")
                logger.warning("Will attempt to fetch instrument tokens from Kite")
                return self._fetch_instrument_tokens()
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load instrument tokens: {e}")
            return {}

    def _fetch_instrument_tokens(self) -> Dict[str, int]:
        """Fetch instrument tokens from Kite instruments dump"""
        try:
            instruments = self.kite.instruments("NSE")
            token_map = {}
            # Remove .NS suffix from stock symbols for matching
            clean_stocks = [s.replace('.NS', '') for s in self.stocks]

            for inst in instruments:
                if inst['tradingsymbol'] in clean_stocks:
                    token_map[inst['tradingsymbol']] = inst['instrument_token']

            # Save for future use
            os.makedirs("data", exist_ok=True)
            with open("data/instrument_tokens.json", 'w') as f:
                json.dump(token_map, f, indent=2)

            logger.info(f"Fetched and saved {len(token_map)} instrument tokens")
            return token_map
        except Exception as e:
            logger.error(f"Failed to fetch instrument tokens: {e}")
            return {}

    def fetch_historical_data(
        self,
        symbol: str,
        days_back: int = 50,
        interval: str = "day"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical data from Kite for RSI calculation

        Args:
            symbol: Stock symbol (with or without .NS suffix)
            days_back: Number of days of historical data (default: 50 for RSI)
            interval: Candle interval (day, 5minute, 15minute, etc.)

        Returns:
            DataFrame with OHLCV data or None
        """
        # Remove .NS suffix for Kite API
        clean_symbol = symbol.replace('.NS', '')

        try:
            # Get instrument token
            if clean_symbol not in self.instrument_tokens:
                logger.debug(f"{symbol}: No instrument token found for historical data")
                return None

            token = self.instrument_tokens[clean_symbol]

            # Calculate date range
            to_date = datetime.now().date()
            from_date = to_date - timedelta(days=days_back)

            # Fetch data from Kite
            data = self.kite.historical_data(
                instrument_token=token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )

            if not data:
                logger.debug(f"{symbol}: No historical data returned")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(data)

            # Ensure column names are lowercase
            df.columns = df.columns.str.lower()

            logger.debug(f"{symbol}: Fetched {len(df)} candles ({interval})")
            return df

        except Exception as e:
            logger.debug(f"{symbol}: Failed to fetch historical data: {e}")
            return None

    def _calculate_rsi_for_stock(
        self,
        symbol: str,
        current_price: float,
        current_volume: int = 0
    ) -> Optional[Dict]:
        """
        Calculate RSI analysis for a stock using cached historical data + today's price

        Args:
            symbol: Stock symbol (with or without .NS suffix)
            current_price: Current intraday price
            current_volume: Current trading volume

        Returns:
            RSI analysis dictionary or None if calculation fails
        """
        if not config.ENABLE_RSI:
            return None

        clean_symbol = symbol.replace('.NS', '')

        try:
            # Try unified data cache first (50-day data from ATR monitor)
            df = None
            if self.data_cache and config.ENABLE_UNIFIED_CACHE:
                try:
                    cached_data = self.data_cache.get_atr_data(clean_symbol)
                    if cached_data:
                        df = pd.DataFrame(cached_data)
                        df.columns = df.columns.str.lower()
                        logger.debug(f"{symbol}: Using cached historical data ({len(df)} candles)")
                except Exception as e:
                    logger.debug(f"{symbol}: Cache error: {e}, fetching fresh data")

            # Cache miss or error - fetch from API (fallback)
            if df is None:
                df = self.fetch_historical_data(clean_symbol, days_back=50, interval="day")

                # Cache it for next time
                if df is not None and self.data_cache and config.ENABLE_UNIFIED_CACHE:
                    try:
                        cache_data = df.to_dict('records')
                        self.data_cache.set_atr_data(clean_symbol, cache_data)
                        logger.debug(f"{symbol}: Cached historical data ({len(df)} candles)")
                    except Exception as e:
                        logger.debug(f"{symbol}: Failed to cache data: {e}")

            if df is None or len(df) < config.RSI_MIN_DATA_DAYS:
                logger.debug(f"{symbol}: Insufficient historical data for RSI (need {config.RSI_MIN_DATA_DAYS} days)")
                return None

            # Append today's current price as latest candle for real-time RSI
            today_candle = pd.DataFrame([{
                'close': current_price,
                'high': current_price,  # Approximate (real high might be higher)
                'low': current_price,   # Approximate (real low might be lower)
                'open': current_price,  # Approximate
                'volume': current_volume
            }])
            df = pd.concat([df, today_candle], ignore_index=True)

            # Calculate RSI with crossovers
            rsi_analysis = calculate_rsi_with_crossovers(
                df,
                periods=config.RSI_PERIODS,
                crossover_lookback=config.RSI_CROSSOVER_LOOKBACK
            )

            logger.debug(f"{symbol}: RSI(14)={rsi_analysis.get('rsi_14')}, Summary={rsi_analysis.get('summary')}")
            return rsi_analysis

        except Exception as e:
            logger.warning(f"{symbol}: RSI calculation failed: {e}")
            return None

    def calculate_market_cap(self, symbol: str, current_price: float) -> Tuple[float, float]:
        """
        Calculate market cap and its change

        Args:
            symbol: Stock symbol (with or without .NS suffix)
            current_price: Current price

        Returns:
            Tuple of (market_cap_crores, market_cap_change_percent)
            Returns (None, None) if shares data not available
        """
        # Remove .NS suffix if present
        clean_symbol = symbol.replace('.NS', '')

        if clean_symbol not in self.shares_outstanding:
            return None, None

        shares = self.shares_outstanding[clean_symbol]
        # Market Cap (Crores) = Price × Shares / 10000000 (1 crore)
        market_cap_cr = (current_price * shares) / 10000000

        return market_cap_cr, None  # percent change will be calculated from price change

    def generate_mock_prices(self) -> Dict[str, float]:
        """
        Generate mock price data for demo/testing mode
        Simulates realistic stock prices with some stocks showing drops > 2%

        Returns:
            Dictionary mapping symbol to mock price
        """
        prices = {}
        logger.info(f"DEMO MODE: Generating mock prices for {len(self.stocks)} stocks...")

        # Use first 20 stocks for demo to speed up testing
        demo_stocks = self.stocks[:20]

        # Force first 2-3 stocks to drop >2% for demo purposes (if they have previous prices)
        forced_drop_count = 0

        for idx, symbol in enumerate(demo_stocks, 1):
            # Generate base price between 500-3000
            base_price = random.uniform(500, 3000)

            # Get previous price from cache if exists
            _, previous_price = self.price_cache.get_prices(symbol)

            if previous_price is None:
                # First run - just use base price
                current_price = base_price
            else:
                # Force first 2-3 stocks to drop if they have previous prices
                if forced_drop_count < 3 and idx <= 5:
                    # Guaranteed significant drop (2.5% to 4%)
                    change_percent = random.uniform(-2.5, -4)
                    forced_drop_count += 1
                    logger.info(f"DEMO: Forcing {symbol} to drop {abs(change_percent):.2f}%")
                else:
                    # Normal random behavior
                    rand = random.random()
                    if rand < 0.85:
                        # Small change
                        change_percent = random.uniform(-1, 1)
                    elif rand < 0.95:
                        # Moderate drop
                        change_percent = random.uniform(-1, -2)
                    else:
                        # Significant drop (will trigger alert)
                        change_percent = random.uniform(-2.5, -5)

                current_price = previous_price * (1 + change_percent / 100)

            prices[symbol] = round(current_price, 2)
            logger.debug(f"{symbol}: ₹{current_price:.2f}")

        logger.info(f"DEMO MODE: Generated {len(prices)} mock prices")
        return prices

    def fetch_price_yahoo(self, symbol: str) -> float:
        """
        Fetch price from Yahoo Finance for a single stock

        Args:
            symbol: Stock symbol with .NS suffix (e.g., RELIANCE.NS)

        Returns:
            Stock price or None if fetch fails
        """
        try:
            ticker = yf.Ticker(symbol)

            # Try method 1: fast_info (fastest)
            try:
                fast_info = ticker.fast_info
                if hasattr(fast_info, 'last_price') and fast_info.last_price:
                    price = float(fast_info.last_price)
                    if price > 0:
                        return price
            except:
                pass

            # Try method 2: history (1 day)
            try:
                hist = ticker.history(period="1d")
                if not hist.empty:
                    price = float(hist['Close'].iloc[-1])
                    if price > 0:
                        return price
            except:
                pass

            # Try method 3: info (slowest, most comprehensive)
            try:
                info = ticker.info
                if info:
                    price = info.get('currentPrice') or info.get('regularMarketPrice')
                    if price and price > 0:
                        return float(price)
            except:
                pass

            return None

        except Exception as e:
            logger.debug(f"{symbol}: Yahoo Finance error - {str(e)[:100]}")
            return None

    def fetch_price_nsepy(self, symbol: str) -> float:
        """
        Fetch price from NSEpy for a single stock

        Args:
            symbol: Stock symbol without .NS suffix (e.g., RELIANCE)

        Returns:
            Stock price or None if fetch fails
        """
        try:
            # Fetch quote data from NSE
            quote = get_quote(symbol)

            # Get last traded price (most current price)
            if hasattr(quote, 'lastPrice') and quote.lastPrice:
                price = float(quote.lastPrice)
                if price > 0:
                    return price

            # Fallback to close price if lastPrice not available
            if hasattr(quote, 'closePrice') and quote.closePrice:
                price = float(quote.closePrice)
                if price > 0:
                    return price

            logger.warning(f"{symbol}: No valid price data in response")
            return None

        except Exception as e:
            # Let the retry logic handle the exception
            raise

    def fetch_price_kite(self, symbol: str) -> Tuple[float, int]:
        """
        Fetch price and volume from Kite Connect for a single stock

        Args:
            symbol: Stock symbol (e.g., RELIANCE)

        Returns:
            Tuple of (price, volume) or (None, 0) if fetch fails
        """
        try:
            # Kite Connect uses instrument token or trading symbol
            # Format: NSE:SYMBOL for equity
            instrument = f"NSE:{symbol}"

            # Get full quote (includes LTP and volume)
            quote = self.kite.quote(instrument)

            if quote and instrument in quote:
                quote_data = quote[instrument]
                ltp = quote_data.get('last_price')
                volume = quote_data.get('volume', 0)

                if ltp and ltp > 0:
                    return float(ltp), int(volume)

            logger.warning(f"{symbol}: No valid price data from Kite Connect")
            return None, 0

        except Exception as e:
            # Let the retry logic handle the exception
            raise

    def fetch_stock_price_with_retry(self, symbol: str) -> Tuple[float, int]:
        """
        Fetch price and volume for a single stock with retry logic and exponential backoff
        Uses Yahoo Finance or NSEpy based on DATA_SOURCE configuration

        Args:
            symbol: Stock symbol (with or without .NS suffix depending on data source)

        Returns:
            Tuple of (price, volume) or (None, 0) if all retries fail
        """
        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                # Fetch price based on configured data source
                if config.DATA_SOURCE == 'yahoo':
                    price = self.fetch_price_yahoo(symbol)
                    if price:
                        return price, 0  # Yahoo doesn't provide volume in this implementation
                    else:
                        logger.warning(f"{symbol}: No valid price from Yahoo Finance")
                        return None, 0
                elif config.DATA_SOURCE == 'kite':
                    price, volume = self.fetch_price_kite(symbol)
                    if price:
                        return price, volume
                    else:
                        logger.warning(f"{symbol}: No valid price from Kite Connect")
                        return None, 0
                else:  # nsepy
                    price = self.fetch_price_nsepy(symbol)
                    if price:
                        return price, 0  # NSEpy doesn't provide volume in this implementation

            except Exception as e:
                error_msg = str(e)

                # Check if it's an SSL error
                if 'SSL' in error_msg or 'ssl' in error_msg.lower():
                    logger.error(f"{symbol}: SSL connection error - skipping (attempt {attempt}/{config.MAX_RETRIES})")
                    if attempt < config.MAX_RETRIES:
                        # Exponential backoff: 2, 4, 8 seconds
                        backoff_delay = config.RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                        logger.debug(f"Waiting {backoff_delay}s before retry...")
                        time.sleep(backoff_delay)
                        continue
                    else:
                        return None, 0

                # Check if it's a connection/network error
                elif 'Connection' in error_msg or 'timeout' in error_msg.lower():
                    logger.error(f"{symbol}: Network error - {error_msg} (attempt {attempt}/{config.MAX_RETRIES})")
                    if attempt < config.MAX_RETRIES:
                        backoff_delay = config.RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                        logger.debug(f"Waiting {backoff_delay}s before retry...")
                        time.sleep(backoff_delay)
                        continue
                    else:
                        return None, 0

                # Other errors - log and skip
                else:
                    logger.error(f"{symbol}: Error fetching price - {error_msg}")
                    return None, 0

        return None, 0

    def fetch_all_prices_batch_kite_optimized(self) -> Dict[str, Tuple[float, int]]:
        """
        Fetch prices using Kite's batch quote API with unified cache (OPTIMIZED)
        Supports up to 500 instruments per call, using batches of 50 for safety

        Uses UnifiedQuoteCache to prevent duplicate API calls within TTL window.
        This reduces API calls from 191 to ~4 per run (98% reduction!)

        Returns:
            Dictionary mapping symbol to (price, volume) tuple
        """
        price_data = {}

        # Try to use unified quote cache if enabled
        if self.quote_cache and config.ENABLE_UNIFIED_CACHE:
            try:
                # Get quotes from cache or fetch fresh
                quotes_dict = self.quote_cache.get_or_fetch_quotes(
                    self.stocks,
                    self.kite,
                    batch_size=50
                )

                # Convert to price_data format: {symbol: (price, volume)}
                for instrument, quote_data in quotes_dict.items():
                    symbol = instrument.replace("NSE:", "").replace(".NS", "")
                    ltp = quote_data.get('last_price')
                    volume = quote_data.get('volume', 0)

                    if ltp and ltp > 0:
                        price_data[symbol] = (float(ltp), int(volume))

                logger.info(f"Successfully fetched prices for {len(price_data)}/{len(self.stocks)} stocks")
                return price_data

            except Exception as e:
                logger.error(f"Unified cache error, falling back to direct fetch: {e}")
                # Fall through to original implementation

        # FALLBACK: Original implementation (if cache disabled or failed)
        BATCH_SIZE = 50  # Conservative batch size (Kite supports up to 500)
        failed_batches = []
        start_time = time.time()

        total_batches = (len(self.stocks) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"Fetching prices for {len(self.stocks)} stocks using Kite Connect BATCH API...")
        logger.info(f"Using {total_batches} batches of {BATCH_SIZE} stocks (optimized from {len(self.stocks)} individual calls)")

        # Split stocks into batches
        for batch_num in range(0, len(self.stocks), BATCH_SIZE):
            batch_index = batch_num // BATCH_SIZE + 1
            batch = self.stocks[batch_num:batch_num + BATCH_SIZE]
            instruments = [f"NSE:{symbol}" for symbol in batch]

            try:
                logger.debug(f"Batch {batch_index}/{total_batches}: Fetching {len(batch)} stocks in one API call...")

                # SINGLE API CALL FOR ENTIRE BATCH!
                quotes = self.kite.quote(*instruments)

                # Parse results
                batch_success = 0
                for instrument, quote_data in quotes.items():
                    symbol = instrument.replace("NSE:", "").replace(".NS", "")
                    ltp = quote_data.get('last_price')
                    volume = quote_data.get('volume', 0)

                    if ltp and ltp > 0:
                        price_data[symbol] = (float(ltp), int(volume))
                        batch_success += 1
                        logger.debug(f"  {symbol}: ₹{ltp:.2f}, vol:{volume:,}")
                    else:
                        logger.warning(f"  {symbol}: Invalid price data")

                # Progress logging
                elapsed = time.time() - start_time
                logger.info(f"Batch {batch_index}/{total_batches} complete: "
                           f"{batch_success}/{len(batch)} stocks successful | "
                           f"Total: {len(price_data)}/{len(self.stocks)} | "
                           f"Elapsed: {elapsed:.1f}s")

                # Rate limiting between batches (not between individual stocks!)
                if batch_index < total_batches:
                    time.sleep(config.REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"Batch {batch_index}/{total_batches} FAILED: {e}")
                failed_batches.extend(batch)

        elapsed_total = time.time() - start_time
        api_calls_saved = len(self.stocks) - total_batches
        logger.info(f"Batch fetch complete in {elapsed_total:.1f}s")
        logger.info(f"API calls: {total_batches} (saved {api_calls_saved} calls vs sequential!)")
        logger.info(f"Successfully fetched prices for {len(price_data)}/{len(self.stocks)} stocks")

        # Retry failed batches individually
        if failed_batches:
            logger.warning(f"Retrying {len(failed_batches)} stocks from failed batches individually...")
            for symbol in failed_batches:
                try:
                    price, volume = self.fetch_stock_price_with_retry(symbol)
                    if price is not None:
                        price_data[symbol] = (price, volume)
                        logger.debug(f"  Retry success: {symbol}: ₹{price:.2f}")
                except Exception as e:
                    logger.error(f"  Retry failed for {symbol}: {e}")

        return price_data

    def fetch_all_prices_batch_sequential(self) -> Dict[str, Tuple[float, int]]:
        """
        Fetch prices sequentially (one by one) - FALLBACK for Yahoo/NSEpy
        This is the OLD method, kept for compatibility with non-Kite data sources

        Returns:
            Dictionary mapping symbol to (price, volume) tuple
        """
        price_data = {}
        failed_stocks = []
        start_time = time.time()

        if config.DATA_SOURCE == 'yahoo':
            data_source_name = "Yahoo Finance"
        else:
            data_source_name = "NSEpy"

        logger.info(f"Fetching prices for {len(self.stocks)} stocks using {data_source_name} (sequential)...")
        logger.info(f"Rate limit: {config.REQUEST_DELAY_SECONDS}s between requests, {config.MAX_RETRIES} retries per stock")

        for idx, symbol in enumerate(self.stocks, 1):
            # Fetch price and volume with retry logic
            price, volume = self.fetch_stock_price_with_retry(symbol)

            if price is not None:
                price_data[symbol] = (price, volume)
                logger.debug(f"{symbol}: ₹{price:.2f}, vol:{volume:,}")
            else:
                failed_stocks.append(symbol)

            # Progress logging every 20 stocks
            if idx % 20 == 0:
                elapsed = time.time() - start_time
                success_rate = (len(price_data) / idx) * 100
                logger.info(f"Progress: {idx}/{len(self.stocks)} stocks processed | "
                           f"Success: {len(price_data)} ({success_rate:.1f}%) | "
                           f"Failed: {len(failed_stocks)} | "
                           f"Elapsed: {elapsed:.1f}s")

            # Rate limiting - delay between requests (except for last stock)
            if idx < len(self.stocks):
                time.sleep(config.REQUEST_DELAY_SECONDS)

        elapsed_total = time.time() - start_time
        logger.info(f"Price fetching complete in {elapsed_total:.1f}s")
        logger.info(f"Successfully fetched prices for {len(price_data)}/{len(self.stocks)} stocks")

        if failed_stocks:
            logger.warning(f"Failed to fetch {len(failed_stocks)} stocks: {', '.join(failed_stocks[:10])}"
                          f"{'...' if len(failed_stocks) > 10 else ''}")

        return price_data

    def fetch_all_prices_batch(self) -> Dict[str, Tuple[float, int]]:
        """
        Fetch current prices and volumes for all stocks
        Uses optimized batch API for Kite, sequential for others

        Returns:
            Dictionary mapping symbol to (price, volume) tuple
        """
        if config.DEMO_MODE:
            # Convert mock prices to (price, volume) tuples
            mock_prices = self.generate_mock_prices()
            return {symbol: (price, 0) for symbol, price in mock_prices.items()}

        # Use optimized batch method for Kite Connect
        if config.DATA_SOURCE == 'kite':
            return self.fetch_all_prices_batch_kite_optimized()

        # Use sequential method for Yahoo Finance / NSEpy
        return self.fetch_all_prices_batch_sequential()

    def calculate_drop_percentage(self, current_price: float, previous_price: float) -> float:
        """
        Calculate percentage drop from previous to current price

        Returns:
            Positive percentage if price dropped, negative if price increased
        """
        if previous_price == 0:
            return 0.0
        change_percent = ((previous_price - current_price) / previous_price) * 100
        return change_percent

    def calculate_rise_percentage(self, current_price: float, previous_price: float) -> float:
        """
        Calculate percentage rise from previous to current price

        Returns:
            Positive percentage if price increased, negative if price dropped
        """
        if previous_price == 0:
            return 0.0
        change_percent = ((current_price - previous_price) / previous_price) * 100
        return change_percent

    def should_send_alert(self, symbol: str, alert_type: str, cooldown_minutes: int = 30) -> bool:
        """
        Check if an alert should be sent based on deduplication rules
        Prevents sending duplicate alerts for the same stock and alert type within cooldown period
        Uses persistent storage to survive script restarts

        Args:
            symbol: Stock symbol
            alert_type: Type of alert (10min, 30min, 10min_rise, 30min_rise, etc.)
            cooldown_minutes: Cooldown period in minutes (default 30)

        Returns:
            True if alert should be sent, False if it's a duplicate
        """
        # Delegate to persistent alert history manager
        return self.alert_history_manager.should_send_alert(symbol, alert_type, cooldown_minutes)

    def check_stock_for_drop(
        self,
        symbol: str,
        current_price: float,
        current_volume: int = 0,
        rsi_analysis: Optional[Dict] = None
    ) -> bool:
        """
        Check a single stock for significant drops using multiple detection methods (PRIORITY ORDER):
        1. Volume spike with drop (≥1.2% + 2.5x volume, 5-min) - PRIORITY ALERT (checked first)
        2. 5-minute rapid drop (≥1.25%) - RAPID DETECTION (new)
        3. 10-minute interval drop (≥2%)
        4. 30-minute cumulative drop (≥3%)

        Args:
            symbol: Stock symbol with .NS suffix
            current_price: Current price of the stock
            current_volume: Current trading volume
            rsi_analysis: Optional RSI analysis dictionary with RSI values and crossovers

        Returns:
            True if any alert was sent, False otherwise
        """
        display_symbol = symbol.replace('.NS', '')
        is_pharma = display_symbol in config.PHARMA_STOCKS
        pharma_tag = " [PHARMA - SHORTING OPPORTUNITY]" if is_pharma else ""

        # Get historical prices
        _, price_5min_ago = self.price_cache.get_prices_5min(symbol)  # 5-minute rapid detection
        _, price_10min_ago = self.price_cache.get_prices(symbol)
        _, price_30min_ago = self.price_cache.get_price_30min(symbol)

        # Update cache with current price and volume
        timestamp = datetime.now().isoformat()
        self.price_cache.update_price(symbol, current_price, current_volume, timestamp)

        # Calculate market cap if shares data available
        market_cap_cr, _ = self.calculate_market_cap(symbol, current_price)

        alert_sent = False

        # === CHECK 1: Volume Spike with Drop (PRIORITY ALERT - checked first, 5-min comparison) ===
        volume_data = self.price_cache.get_volume_data(symbol)

        if volume_data["volume_spike"] and price_5min_ago is not None:
            drop_5min = self.calculate_drop_percentage(current_price, price_5min_ago)

            # Lower threshold for volume spikes (1.2% with 2.5x volume, 5-min comparison for faster detection)
            if drop_5min >= config.DROP_THRESHOLD_VOLUME_SPIKE:
                # Check if we should send this alert (15-minute cooldown for priority alerts)
                if self.should_send_alert(symbol, "volume_spike", cooldown_minutes=15):
                    spike_ratio = volume_data["current_volume"] / volume_data["avg_volume"]
                    logger.info(f"🚨 PRIORITY: VOLUME SPIKE DROP{pharma_tag}: {symbol} dropped {drop_5min:.2f}% "
                               f"with {spike_ratio:.1f}x volume spike (5-min) "
                               f"(₹{price_5min_ago:.2f} → ₹{current_price:.2f})")

                    success = self.telegram.send_alert(
                        symbol, drop_5min, current_price, price_5min_ago,
                        alert_type="volume_spike",
                        volume_data=volume_data,
                        market_cap_cr=market_cap_cr,
                        rsi_analysis=rsi_analysis
                    )
                    alert_sent = alert_sent or success

        # === CHECK 2: 5-Minute Drop (Rapid Detection) ===
        if price_5min_ago is not None:
            drop_5min = self.calculate_drop_percentage(current_price, price_5min_ago)

            if drop_5min >= config.DROP_THRESHOLD_5MIN:
                # Check if we should send this alert (10-minute cooldown for rapid alerts)
                if self.should_send_alert(symbol, "5min", cooldown_minutes=10):
                    logger.info(f"DROP DETECTED [5MIN]{pharma_tag}: {symbol} dropped {drop_5min:.2f}% "
                               f"(₹{price_5min_ago:.2f} → ₹{current_price:.2f})")

                    success = self.telegram.send_alert(
                        symbol, drop_5min, current_price, price_5min_ago,
                        alert_type="5min",
                        volume_data=volume_data,
                        market_cap_cr=market_cap_cr,
                        rsi_analysis=rsi_analysis
                    )
                    alert_sent = alert_sent or success

        # === CHECK 3: 10-Minute Drop (Standard Alert) ===
        if price_10min_ago is not None:
            drop_10min = self.calculate_drop_percentage(current_price, price_10min_ago)

            if drop_10min >= config.DROP_THRESHOLD_PERCENT:
                logger.info(f"DROP DETECTED [10MIN]{pharma_tag}: {symbol} dropped {drop_10min:.2f}% "
                           f"(₹{price_10min_ago:.2f} → ₹{current_price:.2f})")

                success = self.telegram.send_alert(
                    symbol, drop_10min, current_price, price_10min_ago,
                    alert_type="10min",
                    volume_data=volume_data,
                    market_cap_cr=market_cap_cr,
                    rsi_analysis=rsi_analysis
                )
                alert_sent = alert_sent or success

        # === CHECK 4: 30-Minute Cumulative Drop (Gradual Decline) ===
        if price_30min_ago is not None:
            drop_30min = self.calculate_drop_percentage(current_price, price_30min_ago)

            if drop_30min >= config.DROP_THRESHOLD_30MIN:
                # Check if we should send this alert (deduplication)
                if self.should_send_alert(symbol, "30min", cooldown_minutes=30):
                    logger.info(f"DROP DETECTED [30MIN]{pharma_tag}: {symbol} dropped {drop_30min:.2f}% "
                               f"(₹{price_30min_ago:.2f} → ₹{current_price:.2f})")

                    success = self.telegram.send_alert(
                        symbol, drop_30min, current_price, price_30min_ago,
                        alert_type="30min",
                        volume_data=volume_data,
                        market_cap_cr=market_cap_cr,
                        rsi_analysis=rsi_analysis
                    )
                    alert_sent = alert_sent or success

        # Debug logging if no alerts
        if not alert_sent and price_10min_ago is not None:
            drop_10min = self.calculate_drop_percentage(current_price, price_10min_ago)
            logger.debug(f"{symbol}: 10min:{drop_10min:+.2f}%, vol:{current_volume:,} (no alerts)")

        return alert_sent

    def check_stock_for_rise(
        self,
        symbol: str,
        current_price: float,
        current_volume: int = 0,
        rsi_analysis: Optional[Dict] = None
    ) -> bool:
        """
        Check a single stock for significant rises using multiple detection methods (PRIORITY ORDER):
        1. Volume spike with rise (≥1.2% + 2.5x volume, 5-min) - PRIORITY ALERT (checked first)
        2. 5-minute rapid rise (≥1.25%) - RAPID DETECTION (new)
        3. 10-minute interval rise (≥2%)
        4. 30-minute cumulative rise (≥3%)

        Args:
            symbol: Stock symbol with .NS suffix
            current_price: Current price of the stock
            current_volume: Current trading volume
            rsi_analysis: Optional RSI analysis dictionary with RSI values and crossovers

        Returns:
            True if any alert was sent, False otherwise
        """
        if not config.ENABLE_RISE_ALERTS:
            return False

        display_symbol = symbol.replace('.NS', '')

        # Get historical prices (already updated in check_stock_for_drop)
        _, price_5min_ago = self.price_cache.get_prices_5min(symbol)  # 5-minute rapid detection
        _, price_10min_ago = self.price_cache.get_prices(symbol)
        _, price_30min_ago = self.price_cache.get_price_30min(symbol)

        # Calculate market cap if shares data available (same as in check_stock_for_drop)
        market_cap_cr, _ = self.calculate_market_cap(symbol, current_price)

        alert_sent = False

        # === CHECK 1: Volume Spike with Rise (PRIORITY ALERT - checked first, 5-min comparison) ===
        volume_data = self.price_cache.get_volume_data(symbol)

        if volume_data["volume_spike"] and price_5min_ago is not None:
            rise_5min = self.calculate_rise_percentage(current_price, price_5min_ago)

            # Lower threshold for volume spikes (1.2% with 2.5x volume, 5-min comparison for faster detection)
            if rise_5min >= config.RISE_THRESHOLD_VOLUME_SPIKE:
                # Check if we should send this alert (15-minute cooldown for priority alerts)
                if self.should_send_alert(symbol, "volume_spike_rise", cooldown_minutes=15):
                    spike_ratio = volume_data["current_volume"] / volume_data["avg_volume"]
                    logger.info(f"🚨 PRIORITY: VOLUME SPIKE RISE: {symbol} rose {rise_5min:.2f}% "
                               f"with {spike_ratio:.1f}x volume spike (5-min) "
                               f"(₹{price_5min_ago:.2f} → ₹{current_price:.2f})")

                    success = self.telegram.send_alert(
                        symbol, rise_5min, current_price, price_5min_ago,
                        alert_type="volume_spike_rise",
                        volume_data=volume_data,
                        market_cap_cr=market_cap_cr,
                        rsi_analysis=rsi_analysis
                    )
                    alert_sent = alert_sent or success

        # === CHECK 2: 5-Minute Rise (Rapid Detection) ===
        if price_5min_ago is not None:
            rise_5min = self.calculate_rise_percentage(current_price, price_5min_ago)

            if rise_5min >= config.RISE_THRESHOLD_5MIN:
                # Check if we should send this alert (10-minute cooldown for rapid alerts)
                if self.should_send_alert(symbol, "5min_rise", cooldown_minutes=10):
                    logger.info(f"RISE DETECTED [5MIN]: {symbol} rose {rise_5min:.2f}% "
                               f"(₹{price_5min_ago:.2f} → ₹{current_price:.2f})")

                    success = self.telegram.send_alert(
                        symbol, rise_5min, current_price, price_5min_ago,
                        alert_type="5min_rise",
                        volume_data=volume_data,
                        market_cap_cr=market_cap_cr,
                        rsi_analysis=rsi_analysis
                    )
                    alert_sent = alert_sent or success

        # === CHECK 3: 10-Minute Rise (Standard Alert) ===
        if price_10min_ago is not None:
            rise_10min = self.calculate_rise_percentage(current_price, price_10min_ago)

            if rise_10min >= config.RISE_THRESHOLD_PERCENT:
                logger.info(f"RISE DETECTED [10MIN]: {symbol} rose {rise_10min:.2f}% "
                           f"(₹{price_10min_ago:.2f} → ₹{current_price:.2f})")

                success = self.telegram.send_alert(
                    symbol, rise_10min, current_price, price_10min_ago,
                    alert_type="10min_rise",
                    volume_data=volume_data,
                    market_cap_cr=market_cap_cr,
                    rsi_analysis=rsi_analysis
                )
                alert_sent = alert_sent or success

        # === CHECK 4: 30-Minute Cumulative Rise (Gradual Increase) ===
        if price_30min_ago is not None:
            rise_30min = self.calculate_rise_percentage(current_price, price_30min_ago)

            if rise_30min >= config.RISE_THRESHOLD_30MIN:
                # Check if we should send this alert (deduplication)
                if self.should_send_alert(symbol, "30min_rise", cooldown_minutes=30):
                    logger.info(f"RISE DETECTED [30MIN]: {symbol} rose {rise_30min:.2f}% "
                               f"(₹{price_30min_ago:.2f} → ₹{current_price:.2f})")

                    success = self.telegram.send_alert(
                        symbol, rise_30min, current_price, price_30min_ago,
                        alert_type="30min_rise",
                        volume_data=volume_data,
                        market_cap_cr=market_cap_cr,
                        rsi_analysis=rsi_analysis
                    )
                    alert_sent = alert_sent or success

        return alert_sent

    def monitor_all_stocks(self) -> Dict[str, int]:
        """
        Monitor all F&O stocks and send alerts for significant drops and rises

        Returns:
            Dictionary with stats: total, checked, drop_alerts, rise_alerts, alerts_sent, errors
        """
        stats = {
            "total": len(self.stocks),
            "checked": 0,
            "drop_alerts": 0,
            "rise_alerts": 0,
            "alerts_sent": 0,
            "errors": 0
        }

        detection_methods = []
        if config.ENABLE_RISE_ALERTS:
            detection_methods.append("rises")
        detection_methods.append("drops")

        logger.info(f"Starting to monitor {stats['total']} stocks for {' and '.join(detection_methods)}...")

        # Fetch all prices and volumes in batches
        price_data = self.fetch_all_prices_batch()

        # Check each stock for drops and rises
        for symbol, (current_price, current_volume) in price_data.items():
            try:
                # Calculate RSI once for this stock (if enabled)
                rsi_analysis = None
                if config.ENABLE_RSI:
                    rsi_analysis = self._calculate_rsi_for_stock(symbol, current_price, current_volume)

                # Check for drops (pass RSI analysis)
                drop_alert_sent = self.check_stock_for_drop(symbol, current_price, current_volume, rsi_analysis)

                # Check for rises (if enabled, pass RSI analysis)
                rise_alert_sent = False
                if config.ENABLE_RISE_ALERTS:
                    rise_alert_sent = self.check_stock_for_rise(symbol, current_price, current_volume, rsi_analysis)

                stats["checked"] += 1
                if drop_alert_sent:
                    stats["drop_alerts"] += 1
                    stats["alerts_sent"] += 1
                if rise_alert_sent:
                    stats["rise_alerts"] += 1
                    stats["alerts_sent"] += 1

            except Exception as e:
                logger.error(f"Error checking {symbol}: {e}")
                stats["errors"] += 1

        # Count stocks that failed to fetch
        stats["errors"] += (stats["total"] - len(price_data))

        logger.info(f"Monitoring complete. Checked: {stats['checked']}, "
                   f"Drop alerts: {stats['drop_alerts']}, Rise alerts: {stats['rise_alerts']}, "
                   f"Total alerts: {stats['alerts_sent']}, Errors: {stats['errors']}")

        return stats
