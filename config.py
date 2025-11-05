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
MARKET_START_MINUTE = 30
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

CHECK_INTERVAL_MINUTES = 5

# Volume Spike Configuration
VOLUME_SPIKE_MULTIPLIER = float(os.getenv('VOLUME_SPIKE_MULTIPLIER', '2.5'))  # 2.5x average = spike (priority alert)
VOLUME_MIN_HISTORY = int(os.getenv('VOLUME_MIN_HISTORY', '3'))  # Min snapshots needed for avg

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

# Yahoo Finance Configuration
YAHOO_FINANCE_SUFFIX = '.NS'  # NSE stocks suffix for Yahoo Finance
