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
DROP_THRESHOLD_1MIN = float(os.getenv('DROP_THRESHOLD_1MIN', '0.50'))  # 0.50% drop in 1 minute (tuned from 0.75% - was too strict)
RISE_THRESHOLD_1MIN = float(os.getenv('RISE_THRESHOLD_1MIN', '0.50'))  # 0.50% rise in 1 minute (tuned from 0.75% - was too strict)

# Volume requirements for quality signals (percentage-based only)
VOLUME_SPIKE_MULTIPLIER_1MIN = float(os.getenv('VOLUME_SPIKE_MULTIPLIER_1MIN', '1.8'))  # 1.8x average (tuned from 2.5x - was too strict, missed real moves)
# NOTE: No MIN_VOLUME_1MIN absolute threshold - using only percentage-based multiplier
# Rationale: Different stocks have vastly different normal volumes (large-cap: 500K/min, small-cap: 5K/min)
# A 2.5x spike is significant regardless of absolute volume
MIN_AVG_DAILY_VOLUME_1MIN = int(os.getenv('MIN_AVG_DAILY_VOLUME_1MIN', '500000'))  # Only liquid stocks (daily avg filter)

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
QUOTE_CACHE_DB_FILE = 'data/unified_cache/quote_cache.db'  # SQLite database for quote cache
ENABLE_SQLITE_CACHE = os.getenv('ENABLE_SQLITE_CACHE', 'true').lower() == 'true'  # Enable SQLite storage
ENABLE_JSON_BACKUP = os.getenv('ENABLE_JSON_BACKUP', 'true').lower() == 'true'  # Keep JSON backup during transition

# SQLite Lock Contention Fixes
# Addressing database lock contention from multiple concurrent services (stock_monitor, atr_monitor, nifty_option_monitor)
# Critical collision times: Every 30 minutes during market hours (10:00, 10:30, 11:00, etc.) when 3 services access DBs simultaneously
SQLITE_TIMEOUT_SECONDS = int(os.getenv('SQLITE_TIMEOUT_SECONDS', '30'))  # Increased from 10s to handle API delays and lock contention
SQLITE_MAX_RETRIES = int(os.getenv('SQLITE_MAX_RETRIES', '3'))  # Retry with exponential backoff on lock timeout
SQLITE_RETRY_BASE_DELAY = float(os.getenv('SQLITE_RETRY_BASE_DELAY', '1.0'))  # Base delay for exponential backoff (1s, 2s, 4s)

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

# Sector EOD Report - Dropbox Upload Configuration
SECTOR_ENABLE_DROPBOX = os.getenv('SECTOR_ENABLE_DROPBOX', 'true').lower() == 'true'  # Enable/disable Dropbox upload
SECTOR_DROPBOX_TOKEN = os.getenv('SECTOR_DROPBOX_TOKEN', os.getenv('GREEKS_DIFF_DROPBOX_TOKEN', ''))  # Fallback to existing Greeks token
SECTOR_DROPBOX_FOLDER = os.getenv('SECTOR_DROPBOX_FOLDER', '/SectorAnalysis')  # Dropbox folder path

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

# ============================================
# NIFTY OPTIONS SELLING INDICATOR
# ============================================
# Intraday indicator analyzing Greeks (Delta, Theta, Gamma), VIX, market regime, and OI
# Entry signal: 10:00 AM (SELL/HOLD/AVOID)
# Exit monitoring: Every 15 minutes from 10:00 AM to 3:30 PM
# Provides exit signals if market conditions deteriorate after entry

ENABLE_NIFTY_OPTION_ANALYSIS = os.getenv('ENABLE_NIFTY_OPTION_ANALYSIS', 'true').lower() == 'true'
NIFTY_OPTION_ANALYSIS_TIME = "10:00"  # Initial entry analysis time
NIFTY_OPTION_MONITOR_INTERVAL = 15  # Check every 15 minutes for exit signals
NIFTY_OPTION_MONITOR_END_TIME = "15:25"  # Stop monitoring 5 min before market close
NIFTY_OPTION_REPORT_PATH = 'data/nifty_options/nifty_option_analysis.xlsx'
NIFTY_OPTION_POSITION_STATE_FILE = 'data/nifty_options/position_state.json'  # Track current position

# NIFTY instrument tokens
NIFTY_50_TOKEN = 256265  # NIFTY 50 Index
INDIA_VIX_TOKEN = 264969  # India VIX

# Expiry selection
NIFTY_OPTION_MIN_DAYS_TO_EXPIRY = 7  # Skip expiries < 7 days away (skip current week, trade next week+)
# This ensures we NEVER trade current week expiry, only next week and next-to-next week

# Scoring thresholds
NIFTY_OPTION_SELL_THRESHOLD = 70    # Score >= 70 = SELL signal
NIFTY_OPTION_HOLD_THRESHOLD = 40    # Score 40-69 = HOLD
# Score < 40 = AVOID

# VIX thresholds for scoring
VIX_EXCELLENT = 12.0    # VIX < 12 = 100 score (very low volatility)
VIX_GOOD = 15.0         # VIX 12-15 = 75 score (normal range)
VIX_MODERATE = 20.0     # VIX 15-20 = 40 score (caution)
# VIX > 20 = 10 score (avoid option selling)

# VIX trend analysis (CRITICAL: VIX direction matters as much as level!)
VIX_TREND_LOOKBACK_DAYS = 3        # Compare current VIX to 3 days ago
VIX_TREND_RISING_THRESHOLD = 1.5   # VIX rising if +1.5 points from lookback
VIX_TREND_FALLING_THRESHOLD = -1.5 # VIX falling if -1.5 points from lookback
VIX_TREND_MAX_BONUS = 15           # Max bonus for falling VIX (good for sellers)
VIX_TREND_MAX_PENALTY = 20         # Max penalty for rising VIX (bad for sellers)

# IV Rank analysis (Historical volatility percentile)
IV_RANK_LOOKBACK_DAYS = 365        # Calculate IV Rank over 1 year of VIX history
IV_RANK_HIGH_THRESHOLD = 75        # IV Rank > 75% = High IV (excellent for selling)
IV_RANK_MODERATE_HIGH = 50         # IV Rank > 50% = Above average (good for selling)
IV_RANK_MODERATE_LOW = 25          # IV Rank > 25% = Below average (marginal for selling)
# IV Rank < 25% = Low IV (poor for selling - cheap premiums)

# CRITICAL: Hard veto thresholds (override all other signals)
IV_RANK_HARD_VETO_THRESHOLD = 15   # If IV Rank < 15%, force signal to AVOID (premiums too cheap)
# Rationale: IV Rank < 15% means VIX in bottom 15% of past year = extremely cheap premiums
# Even if all other conditions look good, risk/reward is poor when selling cheap options

# Realized vs Implied Volatility Filter
REALIZED_VOL_LOOKBACK_DAYS = 5     # Calculate realized volatility over last 5 days
REALIZED_VOL_MAX_MULTIPLIER = 1.2  # Realized vol should not exceed 1.2x implied vol
# If realized > 1.2x implied = market moving more than VIX suggests = dangerous for sellers

# Price Action Filter (Trending vs Range-bound)
PRICE_ACTION_LOOKBACK_DAYS = 5     # Analyze price action over last 5 days
TRENDING_THRESHOLD = 1.5           # If daily ranges avg > 1.5% = trending market (avoid)
CONSOLIDATION_THRESHOLD = 0.8      # If daily ranges avg < 0.8% = consolidation (ideal)

# Intraday Volatility Filter
INTRADAY_VOL_LOOKBACK_DAYS = 3     # Check recent intraday volatility (last 3 days)
INTRADAY_VOL_HIGH_THRESHOLD = 1.2  # If avg intraday range > 1.2% = too volatile (avoid)

# ============================================
# TIERED SIGNAL SYSTEM (Added: Jan 3, 2026)
# ============================================
# Replaces binary SELL/AVOID with quality-based tiers for more trading opportunities
# while maintaining risk discipline through position sizing

# Enable/disable tiered signals (set to False to revert to binary SELL/AVOID)
ENABLE_TIERED_SIGNALS = os.getenv('ENABLE_TIERED_SIGNALS', 'true').lower() == 'true'

# IV Rank Thresholds (percentage of 1-year range)
# Based on 6-month backtest: 27 days → 45 days tradeable (+67% increase)
IV_RANK_EXCELLENT = float(os.getenv('IV_RANK_EXCELLENT', '25'))    # >= 25% = SELL_STRONG
IV_RANK_GOOD = float(os.getenv('IV_RANK_GOOD', '15'))              # >= 15% = SELL_MODERATE
IV_RANK_MARGINAL = float(os.getenv('IV_RANK_MARGINAL', '10'))      # >= 10% = SELL_WEAK
# < 10% = AVOID (too cheap)

# Position Sizing by Tier (0.0 to 1.0)
# Smaller positions compensate for lower premium quality
POSITION_SIZE_STRONG = float(os.getenv('POSITION_SIZE_STRONG', '1.0'))      # 100% full position
POSITION_SIZE_MODERATE = float(os.getenv('POSITION_SIZE_MODERATE', '0.75')) # 75% reduced
POSITION_SIZE_WEAK = float(os.getenv('POSITION_SIZE_WEAK', '0.5'))          # 50% half position

# Premium Quality Labels (for display/reporting)
PREMIUM_QUALITY_EXCELLENT = "EXCELLENT (100% of fair value or better)"
PREMIUM_QUALITY_GOOD = "GOOD (85-90% of fair value)"
PREMIUM_QUALITY_MARGINAL = "BELOW AVERAGE (75-80% of fair value)"
PREMIUM_QUALITY_POOR = "CHEAP (< 70% of fair value)"

# Note: IV_RANK_HARD_VETO_THRESHOLD (line 239) is superseded by IV_RANK_MARGINAL
# when ENABLE_TIERED_SIGNALS=True. Kept for backwards compatibility.

# Greeks analysis parameters
STRADDLE_DELTA_IDEAL = 0.5      # ATM options (delta ~±0.5)
STRANGLE_DELTA_IDEAL = 0.35     # OTM options (delta ~±0.3 to ±0.4)
MIN_THETA_THRESHOLD = 20        # Minimum daily theta decay
MAX_GAMMA_THRESHOLD = 0.01      # Maximum acceptable gamma
MAX_VEGA_THRESHOLD = 150        # Maximum acceptable vega (VIX sensitivity)

# Scoring weights (must sum to 1.0) - Updated to include Vega
THETA_WEIGHT = 0.20     # 20% weight for theta decay (reduced from 25%)
GAMMA_WEIGHT = 0.20     # 20% weight for gamma stability (reduced from 25%)
VEGA_WEIGHT = 0.15      # 15% weight for vega exposure (NEW - VIX sensitivity)
VIX_WEIGHT = 0.25       # 25% weight for VIX level (reduced from 30%)
REGIME_WEIGHT = 0.10    # 10% weight for market regime
OI_WEIGHT = 0.10        # 10% weight for OI analysis
# Total = 1.00 (Theta + Gamma + Vega + VIX + Regime + OI)

# Exit signal thresholds (for intraday monitoring)
NIFTY_OPTION_EXIT_SCORE_DROP = 20      # Exit if score drops >20 points from entry
NIFTY_OPTION_EXIT_VIX_SPIKE_PCT = 10.0 # Exit if VIX increases >10% from entry (reduced from 20%)
NIFTY_OPTION_EXIT_VIX_SPIKE_POINTS = 2.0  # OR exit if VIX increases >2 points (for low VIX environments)
NIFTY_OPTION_EXIT_SCORE_THRESHOLD = 40  # Exit if score falls below 40 (AVOID zone)
NIFTY_OPTION_EXIT_ON_REGIME_CHANGE = True  # Exit if regime changes from NEUTRAL
NIFTY_OPTION_EXIT_ON_STRONG_OI_BUILDUP = True  # Exit on LONG_BUILDUP/SHORT_BUILDUP

# CRITICAL: Points-based exit for option selling (50-100 point moves are significant!)
NIFTY_OPTION_EXIT_POINTS_MOVE = 100    # Exit if NIFTY moves >100 points from entry (for ATM option sellers)
NIFTY_OPTION_EXIT_PCT_MOVE = 1.0       # OR exit if >1.0% move (reduced from hardcoded 2.0%)
# Note: For ATM straddle/strangle, even 50-100 point moves are significant
# The 2% threshold was too lenient (524 points = disaster for option sellers)

# Position sizing and layering (add positions intraday)
NIFTY_OPTION_MAX_LAYERS = 3            # Maximum number of position layers (1 = no adds, 3 = initial + 2 adds)
NIFTY_OPTION_ADD_SCORE_THRESHOLD = 70  # Add position if score >= 70 (SELL zone)
NIFTY_OPTION_ADD_SCORE_IMPROVEMENT = 10  # Add if score improves by 10+ points from last layer
NIFTY_OPTION_ADD_MIN_INTERVAL = 30     # Minimum 30 minutes between position adds
NIFTY_OPTION_ADD_AFTER_NO_ENTRY = True  # Allow first entry after 10:00 if initial signal was HOLD

# ============================================
# VOLUME PROFILE ANALYZER CONFIGURATION
# ============================================
# End-of-day volume profile analysis (3:00 PM and 3:15 PM)
# Detects P-shaped (distribution) and B-shaped (accumulation) profiles

ENABLE_VOLUME_PROFILE = os.getenv('ENABLE_VOLUME_PROFILE', 'true').lower() == 'true'
VOLUME_PROFILE_POC_TOP_THRESHOLD = float(os.getenv('VOLUME_PROFILE_POC_TOP_THRESHOLD', '0.70'))  # P-shape threshold (POC >= 70%)
VOLUME_PROFILE_POC_BOTTOM_THRESHOLD = float(os.getenv('VOLUME_PROFILE_POC_BOTTOM_THRESHOLD', '0.30'))  # B-shape threshold (POC <= 30%)
VOLUME_PROFILE_MIN_CONFIDENCE = float(os.getenv('VOLUME_PROFILE_MIN_CONFIDENCE', '7.5'))  # Minimum confidence for Telegram alerts
VOLUME_PROFILE_MIN_CANDLES = int(os.getenv('VOLUME_PROFILE_MIN_CANDLES', '30'))  # Minimum 1-min candles required (30 min of data)
VOLUME_PROFILE_TICK_SIZE_AUTO = os.getenv('VOLUME_PROFILE_TICK_SIZE_AUTO', 'true').lower() == 'true'  # Use adaptive tick size
VOLUME_PROFILE_REPORT_DIR = 'data/volume_profile_reports'  # Report output directory

# Dropbox Upload for Volume Profile Reports
VOLUME_PROFILE_ENABLE_DROPBOX = os.getenv('VOLUME_PROFILE_ENABLE_DROPBOX', 'true').lower() == 'true'  # Auto-upload to Dropbox
VOLUME_PROFILE_DROPBOX_TOKEN = os.getenv('VOLUME_PROFILE_DROPBOX_TOKEN', '')  # Dropbox access token
VOLUME_PROFILE_DROPBOX_FOLDER = os.getenv('VOLUME_PROFILE_DROPBOX_FOLDER', '/VolumeProfile')  # Dropbox folder path

# ============================================
# GREEKS DIFFERENCE TRACKER CONFIGURATION
# ============================================
# Intraday Greeks change analysis: tracks Delta, Theta, Vega changes
# from 9:15 AM baseline throughout the day (every 15 minutes)

ENABLE_GREEKS_DIFF_TRACKER = os.getenv('ENABLE_GREEKS_DIFF_TRACKER', 'true').lower() == 'true'

# Timing
GREEKS_BASELINE_TIME = "09:15"  # Market open - capture baseline Greeks
GREEKS_UPDATE_INTERVAL_MINUTES = 15  # Update frequency (9:15 AM to 3:30 PM)
GREEKS_MARKET_START = "09:15"
GREEKS_MARKET_END = "15:30"

# Strike configuration (ATM ± offsets)
GREEKS_DIFF_STRIKE_OFFSETS = [0, 50, 100, 150]  # ATM, ATM+50, ATM+100, ATM+150

# Expiry (use next week only - consistent with NIFTY options config)
GREEKS_DIFF_EXPIRY_TYPE = "next_week"  # Always use next week expiry
GREEKS_DIFF_MIN_VALID_STRIKES = 6  # Minimum valid strikes required (3 CE + 3 PE)

# Output
GREEKS_DIFF_REPORT_DIR = 'data/greeks_difference_reports'
GREEKS_DIFF_ENABLE_TELEGRAM = os.getenv('GREEKS_DIFF_ENABLE_TELEGRAM', 'true').lower() == 'true'
GREEKS_DIFF_TELEGRAM_ONCE_ONLY = True  # Send only 1 Telegram message at first update (9:30 AM)

# Cloud Storage (Google Drive / Dropbox)
GREEKS_DIFF_CLOUD_PROVIDER = os.getenv('GREEKS_DIFF_CLOUD_PROVIDER', 'google_drive')  # 'google_drive' or 'dropbox'
GREEKS_DIFF_GOOGLE_DRIVE_FOLDER_ID = os.getenv('GREEKS_DIFF_GOOGLE_DRIVE_FOLDER_ID', '')  # Google Drive folder ID
GREEKS_DIFF_GOOGLE_CREDENTIALS_PATH = os.getenv('GREEKS_DIFF_GOOGLE_CREDENTIALS_PATH', 'credentials/google_drive_credentials.json')
GREEKS_DIFF_DROPBOX_TOKEN = os.getenv('GREEKS_DIFF_DROPBOX_TOKEN', '')  # Dropbox access token

# Storage
GREEKS_BASELINE_CACHE_KEY = 'greeks_baseline_{date}'  # Persists for the day

# ============================================
# CPR FIRST TOUCH ALERT CONFIGURATION
# ============================================
# Monitors NIFTY CPR (Central Pivot Range) levels and alerts on first touch
# Detects when price crosses TC (Top Central) or BC (Bottom Central) for first time each day
# Shares 1-minute NIFTY data with nifty_option_analyzer.py via unified_quote_cache

# Enable/Disable CPR monitoring
ENABLE_CPR_ALERTS = os.getenv('ENABLE_CPR_ALERTS', 'true').lower() == 'true'

# Cooldown period (once per day = 1440 minutes)
CPR_COOLDOWN_MINUTES = int(os.getenv('CPR_COOLDOWN_MINUTES', '1440'))  # 24 hours

# Dry-run mode (testing without sending Telegram alerts)
CPR_DRY_RUN_MODE = os.getenv('CPR_DRY_RUN_MODE', 'false').lower() == 'true'

# State file (persistent storage for position tracking)
CPR_STATE_FILE = 'data/cpr_state.json'
