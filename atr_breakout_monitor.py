#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
ATR Breakout Monitor
Based on hedge fund strategy using Average True Range for breakout detection

Strategy:
1. Entry: Price crosses above Open + (2.5 × ATR(20))
2. Filter: ATR(20) < ATR(30) - volatility contracting (quiet before breakout)
3. Stop Loss: Entry - (0.5 × ATR(20)) - tight ATR-based stop
4. Exit: Friday close rule

Author: Sunil Kumar Durganaik
"""

import json
import logging
import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional
import time
import pandas as pd
import pandas_ta as ta
from kiteconnect import KiteConnect

import config
from telegram_notifier import TelegramNotifier
from alert_history_manager import AlertHistoryManager
from alert_excel_logger import AlertExcelLogger
from unified_quote_cache import UnifiedQuoteCache
from unified_data_cache import UnifiedDataCache
from rsi_analyzer import calculate_rsi_with_crossovers
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ATRBreakoutMonitor:
    """Monitors F&O stocks for ATR-based breakout signals"""

    def __init__(self):
        """Initialize the ATR breakout monitor"""
        # Initialize Kite Connect
        if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
            raise ValueError("Kite Connect requires KITE_API_KEY and KITE_ACCESS_TOKEN in .env file")

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
        logger.info("Kite Connect initialized successfully")

        # Load stock list and instrument tokens
        self.stocks = self._load_stock_list()
        self.instrument_tokens = self._load_instrument_tokens()

        # Initialize notification and tracking
        self.telegram = TelegramNotifier()
        self.alert_history = AlertHistoryManager()

        # Initialize Excel logger
        self.excel_logger = None
        if config.ENABLE_EXCEL_LOGGING:
            try:
                self.excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
                logger.info("Excel logging enabled for ATR breakouts")
            except Exception as e:
                logger.error(f"Failed to initialize Excel logger: {e}")
                self.excel_logger = None

        # Initialize unified caches (shared with stock_monitor and eod_analyzer)
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
                logger.info("Unified cache enabled (quote + data cache)")
            except Exception as e:
                logger.error(f"Failed to initialize unified cache: {e}")
                self.quote_cache = None
                self.data_cache = None

        # Load shares outstanding for market cap calculation
        self.shares_outstanding = self._load_shares_outstanding()

        logger.info(f"ATR Breakout Monitor initialized for {len(self.stocks)} F&O stocks")

    def _load_stock_list(self) -> List[str]:
        """Load F&O stock list from JSON file"""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                data = json.load(f)
                return data['stocks']
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

    def _load_instrument_tokens(self) -> Dict[str, int]:
        """Load instrument tokens for Kite API"""
        tokens_file = "data/instrument_tokens.json"
        try:
            if os.path.exists(tokens_file):
                with open(tokens_file, 'r') as f:
                    return json.load(f)
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
            for inst in instruments:
                if inst['tradingsymbol'] in self.stocks:
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

    def _load_shares_outstanding(self) -> Dict[str, int]:
        """Load shares outstanding data for market cap calculation"""
        shares_file = "data/shares_outstanding.json"
        try:
            if os.path.exists(shares_file):
                with open(shares_file, 'r') as f:
                    return json.load(f)
            else:
                logger.warning(f"Shares outstanding file not found: {shares_file}")
                return {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load shares outstanding: {e}")
            return {}

    def calculate_atr(self, df: pd.DataFrame, period: int = 20) -> Optional[float]:
        """
        Calculate ATR using pandas-ta

        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
            period: ATR period (default 20)

        Returns:
            Latest ATR value or None if calculation fails
        """
        try:
            # Ensure we have enough data
            if len(df) < period:
                logger.debug(f"Insufficient data for ATR({period}): {len(df)} candles")
                return None

            # Calculate ATR using pandas-ta
            atr_series = ta.atr(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                length=period
            )

            # Return the latest ATR value
            if atr_series is not None and not atr_series.empty:
                return atr_series.iloc[-1]

            return None
        except Exception as e:
            logger.error(f"Failed to calculate ATR({period}): {e}")
            return None

    def fetch_historical_data(
        self,
        symbol: str,
        days_back: int = 50,
        interval: str = "day"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical data from Kite

        Args:
            symbol: Stock symbol
            days_back: Number of days of historical data
            interval: Candle interval (day, 5minute, 15minute, etc.)

        Returns:
            DataFrame with OHLCV data or None
        """
        try:
            # Get instrument token
            if symbol not in self.instrument_tokens:
                logger.warning(f"{symbol}: No instrument token found")
                return None

            token = self.instrument_tokens[symbol]

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
                logger.warning(f"{symbol}: No historical data returned")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(data)

            # Ensure column names are lowercase
            df.columns = df.columns.str.lower()

            logger.debug(f"{symbol}: Fetched {len(df)} candles ({interval})")
            return df

        except Exception as e:
            logger.error(f"{symbol}: Failed to fetch historical data: {e}")
            return None

    def fetch_all_quotes_batch(self) -> Dict[str, Dict]:
        """
        Fetch quotes for all F&O stocks using batch API (OPTIMIZED)
        Now uses UnifiedQuoteCache to share with stock_monitor!

        Returns:
            Dictionary mapping instrument (NSE:SYMBOL) to quote data
        """
        # Try unified cache first
        if self.quote_cache and config.ENABLE_UNIFIED_CACHE:
            try:
                logger.info(f"Checking unified quote cache...")
                quotes_dict = self.quote_cache.get_or_fetch_quotes(
                    self.stocks,
                    self.kite,
                    batch_size=50
                )

                logger.info(f"Quote fetch complete: {len(quotes_dict)} stocks retrieved (via cache)")
                return quotes_dict

            except Exception as e:
                logger.error(f"Unified cache error, falling back to direct fetch: {e}")
                # Fall through to original implementation below

        # Original implementation (fallback)
        quote_data = {}
        batch_size = 50  # Kite supports up to 500, but 50 is safer
        total_batches = (len(self.stocks) + batch_size - 1) // batch_size

        logger.info(f"Fetching quotes for {len(self.stocks)} stocks in {total_batches} batch(es)...")

        for i in range(0, len(self.stocks), batch_size):
            batch = self.stocks[i:i + batch_size]
            batch_index = (i // batch_size) + 1

            # Format as NSE:SYMBOL for Kite API
            instruments = [f"NSE:{symbol}" for symbol in batch]

            try:
                logger.info(f"Batch {batch_index}/{total_batches}: Fetching {len(batch)} stocks...")

                # SINGLE API CALL FOR ENTIRE BATCH!
                quotes = self.kite.quote(*instruments)
                quote_data.update(quotes)

                logger.info(f"Batch {batch_index}/{total_batches}: ✓ Fetched {len(quotes)} quotes")

                # Rate limiting between batches
                if batch_index < total_batches:
                    time.sleep(config.REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"Batch {batch_index}/{total_batches}: Failed to fetch quotes: {e}")
                continue

        logger.info(f"Quote fetch complete: {len(quote_data)} stocks retrieved")
        return quote_data

    def filter_candidates(self, quote_data: Dict[str, Dict]) -> List[Tuple[str, Dict]]:
        """
        Filter stocks worth analyzing based on volume and price movement
        This reduces expensive historical API calls from 191 to ~40-60

        Args:
            quote_data: Quote data from batch fetch

        Returns:
            List of (symbol, quote) tuples for promising candidates
        """
        candidates = []

        for instrument, quote in quote_data.items():
            symbol = instrument.replace("NSE:", "")

            try:
                # Extract data
                volume = quote.get('volume', 0)
                volume_lakhs = volume / 100000
                ohlc = quote.get('ohlc', {})
                open_price = ohlc.get('open', 0)
                last_price = quote.get('last_price', 0)

                if not open_price or not last_price:
                    continue

                # Calculate intraday change
                price_change_percent = ((last_price - open_price) / open_price) * 100

                # Filter criteria (similar to your EOD analyzer):
                # 1. High volume (>50L shares) OR
                # 2. Significant price movement (>1% from open)
                # This catches stocks likely to have ATR breakouts

                if volume_lakhs > config.ATR_MIN_VOLUME or abs(price_change_percent) > 1.0:
                    candidates.append((symbol, quote))
                    logger.debug(f"{symbol}: Candidate (Vol: {volume_lakhs:.1f}L, Change: {price_change_percent:+.2f}%)")

            except Exception as e:
                logger.error(f"{symbol}: Error filtering: {e}")
                continue

        logger.info(f"Filtered {len(candidates)} candidates from {len(quote_data)} stocks "
                   f"({len(candidates)/len(quote_data)*100:.1f}%)")
        return candidates

    def calculate_market_cap(self, symbol: str, price: float) -> Optional[float]:
        """Calculate market cap in crores"""
        if symbol not in self.shares_outstanding:
            return None

        shares = self.shares_outstanding[symbol]
        market_cap_cr = (price * shares) / 10000000  # Convert to crores
        return market_cap_cr

    def analyze_stock(self, symbol: str, quote: Dict) -> Optional[Dict]:
        """
        Analyze a single stock for ATR breakout signal
        Now uses UnifiedDataCache to share with eod_analyzer!

        Args:
            symbol: Stock symbol
            quote: Quote data from batch fetch (contains current price, OHLC, volume)

        Returns:
            Dictionary with analysis results or None
        """
        try:
            # Try unified data cache first (50-day data, enough for ATR(30))
            df = None
            if self.data_cache and config.ENABLE_UNIFIED_CACHE:
                try:
                    cached_data = self.data_cache.get_atr_data(symbol)
                    if cached_data:
                        df = pd.DataFrame(cached_data)
                        df.columns = df.columns.str.lower()
                        logger.debug(f"{symbol}: Using cached historical data ({len(df)} candles)")
                except Exception as e:
                    logger.debug(f"{symbol}: Cache error: {e}, fetching fresh data")

            # Cache miss or error - fetch from API
            if df is None:
                df = self.fetch_historical_data(symbol, days_back=60, interval="day")

                # Cache it for next time (if we have data cache)
                if df is not None and self.data_cache and config.ENABLE_UNIFIED_CACHE:
                    try:
                        # Convert DataFrame to list of dicts for caching
                        cache_data = df.to_dict('records')
                        self.data_cache.set_atr_data(symbol, cache_data)
                        logger.debug(f"{symbol}: Cached historical data ({len(df)} candles)")
                    except Exception as e:
                        logger.debug(f"{symbol}: Failed to cache data: {e}")

            if df is None or len(df) < config.ATR_PERIOD_LONG:
                logger.debug(f"{symbol}: Insufficient data")
                return None

            # Calculate ATR(20) and ATR(30)
            atr_20 = self.calculate_atr(df, period=config.ATR_PERIOD_SHORT)
            atr_30 = self.calculate_atr(df, period=config.ATR_PERIOD_LONG)

            if atr_20 is None or atr_30 is None:
                logger.debug(f"{symbol}: ATR calculation failed")
                return None

            # Calculate RSI with crossover analysis (if enabled)
            rsi_analysis = None
            if config.ENABLE_RSI:
                try:
                    rsi_analysis = calculate_rsi_with_crossovers(
                        df,
                        periods=config.RSI_PERIODS,
                        crossover_lookback=config.RSI_CROSSOVER_LOOKBACK
                    )
                    logger.debug(f"{symbol}: RSI(14)={rsi_analysis.get('rsi_14')}, Summary={rsi_analysis.get('summary')}")
                except Exception as e:
                    logger.warning(f"{symbol}: RSI calculation failed: {e}")
                    rsi_analysis = None

            # Get today's open and current price from quote data (NO EXTRA API CALL!)
            ohlc = quote.get('ohlc', {})
            today_open = ohlc.get('open', df['open'].iloc[-1])  # Fallback to historical if needed
            current_price = quote.get('last_price')

            if current_price is None:
                logger.debug(f"{symbol}: No current price in quote data")
                return None

            # Calculate entry level: Open + (2.5 × ATR(20))
            entry_level = today_open + (config.ATR_ENTRY_MULTIPLIER * atr_20)

            # Calculate stop loss: Entry - (0.5 × ATR(20))
            stop_loss = entry_level - (config.ATR_STOP_MULTIPLIER * atr_20)

            # Check volatility filter: ATR(20) < ATR(30) (contracting volatility)
            volatility_filter_passed = atr_20 < atr_30 if config.ATR_FILTER_CONTRACTION else True

            # NEW: Calculate 20-day MA for price trend filter
            price_filter_passed = True
            ma_20 = None
            if config.ATR_PRICE_FILTER and len(df) >= config.ATR_PRICE_MA_PERIOD:
                ma_20 = df['close'].tail(config.ATR_PRICE_MA_PERIOD).mean()
                price_filter_passed = current_price > ma_20
                logger.debug(f"{symbol}: Price filter - Current: {current_price:.2f}, MA(20): {ma_20:.2f}, Passed: {price_filter_passed}")

            # NEW: Calculate average volume for volume confirmation filter
            volume_filter_passed = True
            avg_volume = None
            current_volume = quote.get('volume', 0)
            if config.ATR_VOLUME_FILTER and len(df) >= 20:
                avg_volume = df['volume'].tail(20).mean()
                volume_filter_passed = current_volume >= (avg_volume * config.ATR_VOLUME_MULTIPLIER)
                logger.debug(f"{symbol}: Volume filter - Current: {current_volume/100000:.1f}L, Avg: {avg_volume/100000:.1f}L, Required: {avg_volume*config.ATR_VOLUME_MULTIPLIER/100000:.1f}L, Passed: {volume_filter_passed}")

            # Check if price has broken out AND all filters pass
            is_breakout = (current_price >= entry_level and
                          volatility_filter_passed and
                          price_filter_passed and
                          volume_filter_passed)

            # Calculate additional metrics
            breakout_distance = current_price - entry_level
            breakout_percent = (breakout_distance / today_open) * 100
            risk_amount = entry_level - stop_loss
            risk_percent = (risk_amount / entry_level) * 100

            # Get volume from quote data (NO EXTRA API CALL!)
            volume = quote.get('volume', df['volume'].iloc[-1])  # Fallback to historical if needed

            # Calculate market cap
            market_cap_cr = self.calculate_market_cap(symbol, current_price)

            # Get day of week (0=Monday, 4=Friday)
            day_of_week = datetime.now().weekday()
            is_friday = day_of_week == 4

            return {
                'symbol': symbol,
                'today_open': today_open,
                'current_price': current_price,
                'entry_level': entry_level,
                'stop_loss': stop_loss,
                'atr_20': atr_20,
                'atr_30': atr_30,
                'volatility_filter_passed': volatility_filter_passed,
                'price_filter_passed': price_filter_passed,
                'volume_filter_passed': volume_filter_passed,
                'ma_20': ma_20,
                'avg_volume': avg_volume,
                'is_breakout': is_breakout,
                'breakout_distance': breakout_distance,
                'breakout_percent': breakout_percent,
                'risk_amount': risk_amount,
                'risk_percent': risk_percent,
                'volume': volume,
                'market_cap_cr': market_cap_cr,
                'day_of_week': day_of_week,
                'is_friday': is_friday,
                'rsi_analysis': rsi_analysis  # RSI with crossover analysis
            }

        except Exception as e:
            logger.error(f"{symbol}: Analysis failed: {e}")
            return None

    def send_atr_alert(self, analysis: Dict) -> bool:
        """Send ATR breakout alert via Telegram and log to Excel"""
        try:
            symbol = analysis['symbol']

            # Check if alert was already sent today
            if not self.alert_history.should_send_alert(symbol, "atr_breakout", cooldown_minutes=1440):
                logger.debug(f"{symbol}: ATR alert already sent today")
                return False

            # Format message
            message = self._format_atr_alert_message(analysis)

            # Send to Telegram
            url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': config.TELEGRAM_CHANNEL_ID,
                'text': message,
                'parse_mode': 'HTML'
            }

            response = requests.post(url, json=payload)
            telegram_success = response.status_code == 200

            if telegram_success:
                logger.info(f"{symbol}: ATR breakout alert sent successfully")
                self.alert_history.record_alert(symbol, "atr_breakout")
            else:
                logger.error(f"{symbol}: Failed to send alert: {response.text}")

            # Log to Excel if enabled
            if self.excel_logger:
                try:
                    self.excel_logger.log_atr_breakout(
                        symbol=symbol,
                        today_open=analysis['today_open'],
                        entry_level=analysis['entry_level'],
                        current_price=analysis['current_price'],
                        breakout_distance=analysis['breakout_distance'],
                        atr_20=analysis['atr_20'],
                        atr_30=analysis['atr_30'],
                        volatility_filter_passed=analysis['volatility_filter_passed'],
                        stop_loss=analysis['stop_loss'],
                        risk_amount=analysis['risk_amount'],
                        risk_percent=analysis['risk_percent'] / 100,  # Convert to decimal for percentage format
                        volume=int(analysis['volume']),
                        market_cap_cr=analysis['market_cap_cr'],
                        telegram_sent=telegram_success,
                        rsi_analysis=analysis.get('rsi_analysis')
                    )
                except Exception as e:
                    logger.error(f"Failed to log ATR breakout to Excel: {e}")

            return telegram_success

        except Exception as e:
            logger.error(f"Failed to send ATR alert: {e}")
            return False

    def _format_atr_alert_message(self, analysis: Dict) -> str:
        """Format ATR breakout alert message for Telegram"""
        symbol = analysis['symbol']
        today_open = analysis['today_open']
        current_price = analysis['current_price']
        entry_level = analysis['entry_level']
        stop_loss = analysis['stop_loss']
        atr_20 = analysis['atr_20']
        atr_30 = analysis['atr_30']
        volatility_filter = "✅ PASSED" if analysis['volatility_filter_passed'] else "❌ FAILED"
        breakout_distance = analysis['breakout_distance']
        risk_amount = analysis['risk_amount']
        risk_percent = analysis['risk_percent']
        market_cap_cr = analysis['market_cap_cr']
        volume = analysis['volume']
        is_friday = analysis['is_friday']

        # Format volume in lakhs
        volume_lakhs = volume / 100000

        # Build message
        message = "🎯🎯🎯 ATR BREAKOUT SIGNAL 🎯🎯🎯\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "⚡ VOLATILITY CONTRACTION BREAKOUT ⚡\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        message += f"📊 Stock: <b>{symbol}</b>\n"
        if market_cap_cr:
            message += f"💰 Market Cap: ₹{market_cap_cr:,.0f} Cr\n"
        message += "\n"

        message += "📈 <b>Breakout Details:</b>\n"
        message += f"   Today's Open: ₹{today_open:.2f}\n"
        message += f"   Entry Level: ₹{entry_level:.2f} (O + {config.ATR_ENTRY_MULTIPLIER}×ATR)\n"
        message += f"   Current Price: <b>₹{current_price:.2f}</b> ✅\n"
        message += f"   Breakout: +₹{breakout_distance:.2f} above entry\n"
        message += "\n"

        message += "📊 <b>ATR Analysis:</b>\n"
        message += f"   ATR(20): ₹{atr_20:.2f}\n"
        message += f"   ATR(30): ₹{atr_30:.2f}\n"
        message += f"   Volatility Filter: {volatility_filter}\n"
        if analysis['volatility_filter_passed']:
            message += "   💡 Volatility contracting (ATR20 < ATR30)\n"
        message += "\n"

        # NEW: Show all filter statuses
        message += "🔍 <b>Quality Filters (NEW):</b>\n"
        price_filter = "✅ PASSED" if analysis['price_filter_passed'] else "❌ FAILED"
        volume_filter = "✅ PASSED" if analysis['volume_filter_passed'] else "❌ FAILED"
        message += f"   Price Trend: {price_filter}"
        if analysis['ma_20']:
            message += f" (>${analysis['ma_20']:.2f} MA20)"
        message += "\n"
        message += f"   Volume Confirm: {volume_filter}"
        if analysis['avg_volume']:
            vol_multiplier = volume / analysis['avg_volume']
            message += f" ({vol_multiplier:.1f}× avg)"
        message += "\n"
        message += "\n"

        message += "🛡️ <b>Risk Management:</b>\n"
        message += f"   Stop Loss: ₹{stop_loss:.2f}\n"
        message += f"   Risk: ₹{risk_amount:.2f} ({risk_percent:.2f}%)\n"
        message += f"   R:R Ratio: 1:2 (₹{risk_amount * 2:.2f} target)\n"
        message += "\n"

        message += "📊 <b>Volume:</b>\n"
        message += f"   Today: {volume_lakhs:.2f}L shares\n"
        message += "\n"

        # RSI Momentum Analysis
        rsi_analysis = analysis.get('rsi_analysis')
        if rsi_analysis:
            message += "📊 <b>RSI Momentum Analysis:</b>\n"

            # RSI Values
            rsi_9 = rsi_analysis.get('rsi_9')
            rsi_14 = rsi_analysis.get('rsi_14')
            rsi_21 = rsi_analysis.get('rsi_21')

            if rsi_9 is not None or rsi_14 is not None or rsi_21 is not None:
                message += "   <b>RSI Values:</b>\n"

                if rsi_9 is not None:
                    emoji = "🔥" if rsi_9 > 70 else "❄️" if rsi_9 < 30 else "📊"
                    message += f"      {emoji} RSI(9): {rsi_9:.2f}\n"

                if rsi_14 is not None:
                    emoji = "🔥" if rsi_14 > 70 else "❄️" if rsi_14 < 30 else "📊"
                    message += f"      {emoji} RSI(14): {rsi_14:.2f}\n"

                if rsi_21 is not None:
                    emoji = "🔥" if rsi_21 > 70 else "❄️" if rsi_21 < 30 else "📊"
                    message += f"      {emoji} RSI(21): {rsi_21:.2f}\n"

            # RSI Crossovers
            crossovers = rsi_analysis.get('crossovers', {})
            if crossovers:
                message += "   <b>Crossovers:</b>\n"
                for pair, crossover_data in crossovers.items():
                    if crossover_data.get('status') and crossover_data.get('strength') is not None:
                        fast, slow = pair.split('_')
                        arrow = "↑" if crossover_data['status'] == 'above' else "↓"
                        strength = crossover_data['strength']
                        sign = "+" if strength >= 0 else ""
                        message += f"      • RSI({fast}){arrow}RSI({slow}): {sign}{strength:.2f}\n"

            # Recent Crossovers
            recent_crosses = []
            for pair, crossover_data in crossovers.items():
                recent = crossover_data.get('recent_cross', {})
                if recent.get('occurred'):
                    bars_ago = recent.get('bars_ago', 0)
                    direction = recent.get('direction', '').capitalize()
                    emoji = "🟢" if direction == 'Bullish' else "🔴"
                    fast, slow = pair.split('_')
                    recent_crosses.append(f"{emoji} RSI({fast})×RSI({slow}) {direction} {bars_ago}d ago")

            if recent_crosses:
                message += "   <b>Recent Crosses:</b>\n"
                for cross in recent_crosses:
                    message += f"      • {cross}\n"

            # Overall Summary
            summary = rsi_analysis.get('summary', '')
            if summary:
                emoji = "🟢" if 'Bullish' in summary else "🔴" if 'Bearish' in summary else "⚪"
                message += f"   <b>Summary:</b> {emoji} {summary}\n"

            message += "\n"

        # Friday exit warning
        if is_friday and config.ATR_FRIDAY_EXIT:
            message += "⚠️ <b>FRIDAY EXIT RULE ACTIVE</b> ⚠️\n"
            message += "   Close all positions before market close!\n"
            message += "\n"

        message += f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

        return message

    def send_friday_exit_reminder(self):
        """Send reminder to close ATR positions on Friday"""
        try:
            message = "⚠️⚠️⚠️ FRIDAY EXIT REMINDER ⚠️⚠️⚠️\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            message += "🔔 <b>ATR Breakout Strategy</b>\n\n"
            message += "Today is Friday. As per the ATR strategy rules:\n"
            message += "📌 Close ALL open ATR breakout positions before market close\n\n"
            message += "This is part of the weekly exit rule to avoid weekend risk.\n\n"
            message += f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}\n"

            url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': config.TELEGRAM_CHANNEL_ID,
                'text': message,
                'parse_mode': 'HTML'
            }

            response = requests.post(url, json=payload)
            if response.status_code == 200:
                logger.info("Friday exit reminder sent successfully")
            else:
                logger.error(f"Failed to send Friday reminder: {response.text}")

        except Exception as e:
            logger.error(f"Failed to send Friday exit reminder: {e}")

    def scan_all_stocks(self) -> List[Dict]:
        """
        Scan all F&O stocks for ATR breakout signals (OPTIMIZED BATCH WORKFLOW)

        Workflow:
        1. Batch fetch all quotes (4 API calls instead of 191)
        2. Filter promising candidates (~40-60 stocks)
        3. Fetch historical data only for candidates (~40-60 calls instead of 191)
        4. Analyze and send alerts

        Returns:
            List of stocks with breakout signals
        """
        breakout_signals = []

        logger.info("=" * 60)
        logger.info("OPTIMIZED SCAN WORKFLOW")
        logger.info("=" * 60)

        # Step 1: Batch fetch all quotes (4 API calls for 191 stocks!)
        logger.info("\nStep 1: Batch fetching quotes...")
        quote_data = self.fetch_all_quotes_batch()

        if not quote_data:
            logger.error("No quote data fetched. Aborting scan.")
            return breakout_signals

        # Step 2: Filter promising candidates
        logger.info("\nStep 2: Filtering candidates...")
        candidates = self.filter_candidates(quote_data)

        if not candidates:
            logger.warning("No candidates after filtering. Try adjusting filter criteria.")
            return breakout_signals

        logger.info(f"\nStep 3: Analyzing {len(candidates)} candidates for ATR breakouts...")
        logger.info("=" * 60)

        # Step 3: Analyze filtered candidates
        for idx, (symbol, quote) in enumerate(candidates, 1):
            try:
                logger.info(f"[{idx}/{len(candidates)}] Analyzing {symbol}...")

                # Analyze with pre-fetched quote data (no extra API calls!)
                analysis = self.analyze_stock(symbol, quote)

                if analysis is None:
                    continue

                # Check if this is a valid breakout signal
                if analysis['is_breakout'] and analysis['volatility_filter_passed']:
                    logger.info(f"{symbol}: ✅ ATR BREAKOUT DETECTED!")
                    breakout_signals.append(analysis)

                    # Send alert if enabled
                    if config.ENABLE_ATR_ALERTS:
                        self.send_atr_alert(analysis)

                # Rate limiting (for historical data API calls)
                time.sleep(config.REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"{symbol}: Error during analysis: {e}")
                continue

        logger.info("=" * 60)
        logger.info(f"Scan complete. Found {len(breakout_signals)} ATR breakout signals")
        logger.info("=" * 60)
        return breakout_signals

    def run(self):
        """Main execution method"""
        start_time = time.time()

        logger.info("=" * 60)
        logger.info("ATR BREAKOUT MONITOR - OPTIMIZED VERSION")
        logger.info("=" * 60)
        logger.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Day of Week: {datetime.now().strftime('%A')}")
        logger.info(f"Stocks to scan: {len(self.stocks)}")
        logger.info("")
        logger.info("ATR Configuration:")
        logger.info(f"  Short Period (ATR): {config.ATR_PERIOD_SHORT}")
        logger.info(f"  Long Period (ATR): {config.ATR_PERIOD_LONG}")
        logger.info(f"  Entry Multiplier: {config.ATR_ENTRY_MULTIPLIER}x ATR")
        logger.info(f"  Stop Multiplier: {config.ATR_STOP_MULTIPLIER}x ATR")
        logger.info(f"  Volatility Filter: {'ENABLED' if config.ATR_FILTER_CONTRACTION else 'DISABLED'} (ATR20 < ATR30)")
        logger.info(f"  Friday Exit Rule: {'ENABLED' if config.ATR_FRIDAY_EXIT else 'DISABLED'}")
        logger.info(f"  Min Volume Filter: {config.ATR_MIN_VOLUME}L shares")
        logger.info("")
        logger.info("API Optimization:")
        logger.info(f"  ✓ Batch quote fetching (4 calls instead of 191)")
        logger.info(f"  ✓ Smart filtering before historical calls")
        logger.info(f"  ✓ Expected API calls: ~50 (vs 382 unoptimized)")
        logger.info(f"  ✓ Expected time: ~20-30 sec (vs 2.5 min unoptimized)")
        logger.info("=" * 60)

        # Check if it's Friday and send reminder
        if datetime.now().weekday() == 4 and config.ATR_FRIDAY_EXIT:
            logger.info("Today is Friday - sending exit reminder")
            self.send_friday_exit_reminder()

        # Scan all stocks
        breakout_signals = self.scan_all_stocks()

        # Calculate elapsed time
        elapsed_time = time.time() - start_time

        # Summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("FINAL SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Execution Time: {elapsed_time:.1f} seconds")
        logger.info(f"Total Stocks Scanned: {len(self.stocks)}")
        logger.info(f"Breakout Signals Found: {len(breakout_signals)}")

        if breakout_signals:
            logger.info("")
            logger.info("ATR Breakout Signals:")
            for idx, signal in enumerate(breakout_signals, 1):
                logger.info(f"  {idx}. {signal['symbol']}")
                logger.info(f"     Current: ₹{signal['current_price']:.2f} | "
                          f"Entry: ₹{signal['entry_level']:.2f} | "
                          f"Stop: ₹{signal['stop_loss']:.2f}")
                logger.info(f"     ATR(20): ₹{signal['atr_20']:.2f} | "
                          f"ATR(30): ₹{signal['atr_30']:.2f} | "
                          f"Risk: {signal['risk_percent']:.2f}%")
        else:
            logger.info("")
            logger.info("No ATR breakout signals detected.")
            logger.info("This is normal - breakouts are relatively rare events.")

        logger.info("=" * 60)
        logger.info(f"✓ Scan completed successfully in {elapsed_time:.1f}s")
        logger.info("=" * 60)


def main():
    """Main entry point"""
    try:
        monitor = ATRBreakoutMonitor()
        monitor.run()
    except KeyboardInterrupt:
        logger.info("\nShutdown requested by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
