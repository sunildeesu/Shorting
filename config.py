import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')

# Market Configuration
MARKET_TIMEZONE = 'Asia/Kolkata'
MARKET_START_HOUR = 9
MARKET_START_MINUTE = 25  # Start monitoring at 9:25 AM (allow 10 min for market stabilization after 9:15 open)
MARKET_END_HOUR = 15
MARKET_END_MINUTE = 25

# Monitoring Configuration - Drop Detection
DROP_THRESHOLD_5MIN = float(os.getenv('DROP_THRESHOLD_5MIN', '1.25'))  # 5-minute rapid detection (new)
DROP_THRESHOLD_PERCENT = float(os.getenv('DROP_THRESHOLD_PERCENT', '2.0'))  # 10-minute threshold
DROP_THRESHOLD_30MIN = float(os.getenv('DROP_THRESHOLD_30MIN', '3.0'))  # 30-minute cumulative threshold
DROP_THRESHOLD_VOLUME_SPIKE = float(os.getenv('DROP_THRESHOLD_VOLUME_SPIKE', '1.2'))  # With volume spike (priority alert)

# Monitoring Configuration - Rise Detection
RISE_THRESHOLD_5MIN = float(os.getenv('RISE_THRESHOLD_5MIN', '1.25'))  # 5-minute rapid detection (new)
RISE_THRESHOLD_PERCENT = float(os.getenv('RISE_THRESHOLD_PERCENT', '2.0'))  # 10-minute threshold
RISE_THRESHOLD_30MIN = float(os.getenv('RISE_THRESHOLD_30MIN', '3.0'))  # 30-minute cumulative threshold
RISE_THRESHOLD_VOLUME_SPIKE = float(os.getenv('RISE_THRESHOLD_VOLUME_SPIKE', '1.2'))  # With volume spike (priority alert)
ENABLE_RISE_ALERTS = os.getenv('ENABLE_RISE_ALERTS', 'true').lower() == 'true'  # Toggle rise detection

# ============================================
# 1-MINUTE ALERT CONFIGURATION
# ============================================
# Ultra-fast detection system for rapid price movements (5x faster than 5-min alerts)
# Uses fresh API calls every minute for true 1-minute detection
# Monitors only high-liquidity stocks (500K+ avg daily volume)

ENABLE_1MIN_ALERTS = os.getenv('ENABLE_1MIN_ALERTS', 'true').lower() == 'true'  # Toggle 1-min monitoring
DROP_THRESHOLD_1MIN = float(os.getenv('DROP_THRESHOLD_1MIN', '0.75'))  # 0.75% drop in 1 minute (relaxed from 0.85%)
RISE_THRESHOLD_1MIN = float(os.getenv('RISE_THRESHOLD_1MIN', '0.75'))  # 0.75% rise in 1 minute (relaxed from 0.85%)

# Volume requirements for quality signals (relaxed for better alert coverage)
VOLUME_SPIKE_MULTIPLIER_1MIN = float(os.getenv('VOLUME_SPIKE_MULTIPLIER_1MIN', '3.0'))  # 3x average (relaxed from 5x for better coverage)
MIN_VOLUME_1MIN = int(os.getenv('MIN_VOLUME_1MIN', '50000'))  # Minimum 50K shares in 1-min window
MIN_AVG_DAILY_VOLUME_1MIN = int(os.getenv('MIN_AVG_DAILY_VOLUME_1MIN', '500000'))  # Only liquid stocks

# Tiered Priority System (configured in onemin_alert_detector.py)
# NORMAL Priority: Passes layers 1-5 (price, volume, quality, cooldown, deduplication)
# HIGH Priority: Passes layers 1-5 AND has momentum acceleration (30% faster than 4-min average)
# Note: Momentum threshold is hardcoded in onemin_alert_detector.py at 1.3x (30% acceleration)

# Alert management
COOLDOWN_1MIN_ALERTS = int(os.getenv('COOLDOWN_1MIN_ALERTS', '10'))  # 10-minute cooldown per stock
CHECK_INTERVAL_1MIN = 1  # Run every 1 minute
CACHE_MAX_AGE_1MIN = 90  # Allow 90s cache age for volume/OI data (price data always fresh)

CHECK_INTERVAL_MINUTES = 5

# Volume Spike Configuration
VOLUME_SPIKE_MULTIPLIER = float(os.getenv('VOLUME_SPIKE_MULTIPLIER', '2.5'))  # 2.5x average = spike (priority alert)
VOLUME_MIN_HISTORY = int(os.getenv('VOLUME_MIN_HISTORY', '3'))  # Min snapshots needed for avg

# ATR Breakout Configuration
# Strategy: Entry on breakout when volatility is contracting (ATR(20) < ATR(30))
ATR_PERIOD_SHORT = int(os.getenv('ATR_PERIOD_SHORT', '20'))  # Short-term ATR period
ATR_PERIOD_LONG = int(os.getenv('ATR_PERIOD_LONG', '30'))  # Long-term ATR period
ATR_ENTRY_MULTIPLIER = float(os.getenv('ATR_ENTRY_MULTIPLIER', '2.5'))  # Entry: Open + (2.5 × ATR) - ORIGINAL (proven profitable)
ATR_STOP_MULTIPLIER = float(os.getenv('ATR_STOP_MULTIPLIER', '0.5'))  # Stop: Entry - (0.5 × ATR)
ATR_FILTER_CONTRACTION = os.getenv('ATR_FILTER_CONTRACTION', 'true').lower() == 'true'  # Require ATR(20) < ATR(30)
ATR_FRIDAY_EXIT = os.getenv('ATR_FRIDAY_EXIT', 'true').lower() == 'true'  # Close positions on Friday
ATR_MIN_VOLUME = int(os.getenv('ATR_MIN_VOLUME', '50'))  # Minimum daily volume in lakhs

# ATR Volume Filter (DISABLED - backtest showed filters reduce performance)
ATR_VOLUME_FILTER = os.getenv('ATR_VOLUME_FILTER', 'false').lower() == 'true'  # DISABLED: volume confirmation hurt performance
ATR_VOLUME_MULTIPLIER = float(os.getenv('ATR_VOLUME_MULTIPLIER', '1.5'))  # Volume must be 1.5× average (not used when disabled)

# ATR Price Trend Filter (DISABLED - backtest showed filters reduce performance)
ATR_PRICE_FILTER = os.getenv('ATR_PRICE_FILTER', 'false').lower() == 'true'  # DISABLED: price filter hurt performance
ATR_PRICE_MA_PERIOD = int(os.getenv('ATR_PRICE_MA_PERIOD', '20'))  # Price must be above 20-day MA (not used when disabled)

ENABLE_ATR_ALERTS = os.getenv('ENABLE_ATR_ALERTS', 'true').lower() == 'true'  # Toggle ATR monitoring

# Unified Cache Configuration
# Shared caching across stock_monitor, atr_breakout_monitor, and eod_analyzer
ENABLE_UNIFIED_CACHE = os.getenv('ENABLE_UNIFIED_CACHE', 'true').lower() == 'true'  # Enable unified caching
QUOTE_CACHE_TTL_SECONDS = int(os.getenv('QUOTE_CACHE_TTL_SECONDS', '60'))  # Quote cache TTL (60 seconds)
HISTORICAL_CACHE_TTL_HOURS = int(os.getenv('HISTORICAL_CACHE_TTL_HOURS', '24'))  # Historical data cache TTL (24 hours)
INTRADAY_CACHE_TTL_HOURS = int(os.getenv('INTRADAY_CACHE_TTL_HOURS', '1'))  # Intraday data cache TTL (1 hour)

# Cache File Paths
UNIFIED_CACHE_DIR = 'data/unified_cache'
QUOTE_CACHE_FILE = f'{UNIFIED_CACHE_DIR}/quote_cache.json'
HISTORICAL_CACHE_DIR = UNIFIED_CACHE_DIR

# Pharma stocks - good indicator for shorting opportunities (driven by negative news)
# Updated 2025-11-03: Removed stocks delisted from F&O (LALPATHLAB, METROPOLIS, ABBOTINDIA, SANOFI, GLAXO)
PHARMA_STOCKS = {
    'SUNPHARMA', 'DRREDDY', 'CIPLA', 'DIVISLAB', 'APOLLOHOSP',
    'AUROPHARMA', 'LUPIN', 'TORNTPHARM', 'BIOCON', 'ALKEM', 'ZYDUSLIFE'
}

# Demo Mode Configuration
DEMO_MODE = os.getenv('DEMO_MODE', 'false').lower() == 'true'

# Data Source Configuration
DATA_SOURCE = os.getenv('DATA_SOURCE', 'nsepy').lower()  # Options: 'nsepy', 'yahoo', or 'kite'

# Kite Connect Configuration
KITE_API_KEY = os.getenv('KITE_API_KEY')
KITE_API_SECRET = os.getenv('KITE_API_SECRET')
KITE_ACCESS_TOKEN = os.getenv('KITE_ACCESS_TOKEN')

# Rate Limiting Configuration
# Kite Connect allows 3 requests/second for quote API
# Using 0.4s delay = 2.5 req/sec (safe margin below 3 req/sec limit)
REQUEST_DELAY_SECONDS = float(os.getenv('REQUEST_DELAY_SECONDS', '0.4'))  # Delay between requests (optimized for Kite)
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))  # Max retry attempts per stock
RETRY_DELAY_SECONDS = float(os.getenv('RETRY_DELAY_SECONDS', '2.0'))  # Delay before retry

# File Paths
STOCK_LIST_FILE = 'fo_stocks.json'
PRICE_CACHE_FILE = 'data/price_cache.json'
LOG_FILE = 'logs/stock_monitor.log'

# SQLite Cache Configuration
# Migrating from JSON to SQLite for 100x better performance and concurrency safety
PRICE_CACHE_DB_FILE = 'data/price_cache.db'  # SQLite database for price cache
ENABLE_SQLITE_CACHE = os.getenv('ENABLE_SQLITE_CACHE', 'true').lower() == 'true'  # Enable SQLite storage
ENABLE_JSON_BACKUP = os.getenv('ENABLE_JSON_BACKUP', 'true').lower() == 'true'  # Keep JSON backup during transition

# Alert Excel Logging Configuration
ALERT_EXCEL_PATH = 'data/alerts/alert_tracking.xlsx'
ENABLE_EXCEL_LOGGING = os.getenv('ENABLE_EXCEL_LOGGING', 'true').lower() == 'true'

# Yahoo Finance Configuration
YAHOO_FINANCE_SUFFIX = '.NS'  # NSE stocks suffix for Yahoo Finance

# RSI (Relative Strength Index) Configuration
# RSI is calculated to provide momentum analysis alongside price alerts
ENABLE_RSI = os.getenv('ENABLE_RSI', 'true').lower() == 'true'  # Toggle RSI calculation
RSI_PERIODS = [9, 14, 21]  # Calculate RSI for multiple periods (fast, standard, slow)
RSI_MIN_DATA_DAYS = int(os.getenv('RSI_MIN_DATA_DAYS', '30'))  # Minimum historical data needed (days)
RSI_CROSSOVER_LOOKBACK = int(os.getenv('RSI_CROSSOVER_LOOKBACK', '3'))  # Detect crossovers in last N candles

# OI (Open Interest) Analysis Configuration
# Analyze OI changes to distinguish strong moves from weak moves (ZERO additional API calls - already in quotes)
ENABLE_OI_ANALYSIS = os.getenv('ENABLE_OI_ANALYSIS', 'true').lower() == 'true'  # Toggle OI analysis
OI_SIGNIFICANT_THRESHOLD = float(os.getenv('OI_SIGNIFICANT_THRESHOLD', '5.0'))  # 5% OI change = significant
OI_STRONG_THRESHOLD = float(os.getenv('OI_STRONG_THRESHOLD', '10.0'))  # 10% OI change = strong signal
OI_VERY_STRONG_THRESHOLD = float(os.getenv('OI_VERY_STRONG_THRESHOLD', '15.0'))  # 15% OI change = very strong signal
OI_CACHE_FILE = 'data/oi_cache/oi_history.json'  # OI history cache for tracking changes

# Futures Mapping Configuration (for OI data fetching)
# Enable fetching futures OI data alongside equity prices for accurate OI analysis
ENABLE_FUTURES_OI = os.getenv('ENABLE_FUTURES_OI', 'true').lower() == 'true'  # Toggle futures OI fetching
FUTURES_MAPPING_FILE = 'data/futures_mapping.json'  # Cache file for equity → futures mapping
FUTURES_REFRESH_TIME = "09:15"  # Daily refresh at market open to detect expiry rollovers

# Sector Analysis Configuration
# Analyze sector performance and fund flow using existing price cache data (ZERO additional API calls)
ENABLE_SECTOR_ANALYSIS = os.getenv('ENABLE_SECTOR_ANALYSIS', 'true').lower() == 'true'  # Toggle sector analysis
SECTOR_ROTATION_THRESHOLD = float(os.getenv('SECTOR_ROTATION_THRESHOLD', '2.0'))  # % differential to trigger rotation alert
SECTOR_SNAPSHOT_TIMES = ["09:30", "12:30", "15:15"]  # 3x daily snapshots (market open, mid-day, pre-close)
MIN_SECTOR_STOCKS = int(os.getenv('MIN_SECTOR_STOCKS', '3'))  # Minimum stocks needed for valid sector analysis
ENABLE_SECTOR_CONTEXT_IN_ALERTS = os.getenv('ENABLE_SECTOR_CONTEXT_IN_ALERTS', 'true').lower() == 'true'  # Add sector info to stock alerts
ENABLE_SECTOR_EOD_REPORT = os.getenv('ENABLE_SECTOR_EOD_REPORT', 'true').lower() == 'true'  # Generate Excel report at EOD (3:25 PM)

# ============================================
# PRICE ACTION ALERT CONFIGURATION
# ============================================
# 5-minute candlestick pattern detection with confidence scoring

ENABLE_PRICE_ACTION_ALERTS = os.getenv('ENABLE_PRICE_ACTION_ALERTS', 'true').lower() == 'true'
PRICE_ACTION_TIMEFRAME = '5minute'  # Timeframe for pattern detection
PRICE_ACTION_MIN_CONFIDENCE = float(os.getenv('PRICE_ACTION_MIN_CONFIDENCE', '7.0'))  # Minimum 7.0/10
PRICE_ACTION_LOOKBACK_CANDLES = int(os.getenv('PRICE_ACTION_LOOKBACK_CANDLES', '50'))  # Candles to analyze
PRICE_ACTION_COOLDOWN = int(os.getenv('PRICE_ACTION_COOLDOWN', '30'))  # 30-min cooldown per stock/pattern

# Price and liquidity filters
PRICE_ACTION_MIN_PRICE = float(os.getenv('PRICE_ACTION_MIN_PRICE', '50.0'))  # Min ₹50
PRICE_ACTION_MIN_AVG_VOLUME = int(os.getenv('PRICE_ACTION_MIN_AVG_VOLUME', '500000'))  # Min 500K avg volume

# Market regime parameters
PRICE_ACTION_USE_MARKET_REGIME = os.getenv('PRICE_ACTION_USE_MARKET_REGIME', 'true').lower() == 'true'
PRICE_ACTION_REGIME_SMA_PERIOD = int(os.getenv('PRICE_ACTION_REGIME_SMA_PERIOD', '50'))  # 50-day SMA for Nifty
