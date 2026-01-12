# Sentiment Analyzer for Indian Equity Markets - Design Document

**Created**: 2026-01-11
**Status**: Design Complete - Ready for Implementation
**Complexity**: ~1,400 lines of new code + 4 file modifications

---

## Quick Reference

**What**: Real-time sentiment analysis for Indian F&O stocks and market indices
**When**: Every 15 minutes during market hours (9:25 AM - 3:25 PM IST)
**Why**: Identify sentiment shifts that may precede price movements
**How**: NewsAPI + web scraping → VADER NLP → SQLite storage → Telegram alerts

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [F&O Stock Filtering](#fo-stock-filtering)
4. [NewsAPI Strategy](#newsapi-strategy)
5. [Sentiment Scoring](#sentiment-scoring)
6. [Alert Logic](#alert-logic)
7. [Data Storage](#data-storage)
8. [Integration Points](#integration-points)
9. [Error Handling](#error-handling)
10. [Telegram Alerts](#telegram-alerts)
11. [Verification Plan](#verification-plan)
12. [Implementation Checklist](#implementation-checklist)

---

## Overview

### Problem Statement
The existing trading system tracks price movements, volume profiles, and Greeks but lacks sentiment analysis from news sources. Market sentiment often shifts before prices move significantly, especially for F&O stocks affected by news events (earnings, regulatory changes, sector rotation).

### Solution
Build a sentiment analyzer that:
- Fetches news from NewsAPI (100 free requests/day) + web scraping fallback
- Analyzes sentiment using VADER NLP with Indian market lexicon tuning
- Tracks 30+ high-liquidity F&O stocks + overall market indices (Nifty, Bank Nifty)
- Sends Telegram alerts only on significant sentiment changes (>20 point shifts or sentiment flips)
- Runs every 15 minutes during market hours (~18 runs/day)

### User Decisions
- **Frequency**: Every 15 minutes (~18 runs/day)
- **News Sources**: NewsAPI (primary) + web scraping ET/Moneycontrol (fallback)
- **Alert Trigger**: Significant changes only (market shift >20 points OR sentiment flip positive↔negative)

---

## Architecture

### File Structure

**New Files (7)**:
```
sentiment_analyzer.py              # Main orchestrator (300-400 lines)
sentiment_news_fetcher.py          # NewsAPI + web scraping (250-300 lines)
sentiment_scorer.py                # VADER sentiment scoring (200-250 lines)
sentiment_storage.py               # SQLite persistence (200 lines)
sentiment_alert_manager.py         # Alert logic + cooldown (150-200 lines)
sentiment_service.sh               # Service control script (50 lines)
com.nse.sentiment.plist            # launchd scheduler (40 lines)
```

**Modified Files (4)**:
```
config.py                          # Add sentiment configuration section
telegram_notifier.py               # Add send_sentiment_alert() method
alert_excel_logger.py              # Add "Sentiment_alerts" sheet
.env.example                       # Document NEWSAPI_KEY
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│  launchd Scheduler (every 15 min during market hours)      │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  sentiment_analyzer.py (Main Orchestrator)                  │
│  - Check market hours (is_market_open())                    │
│  - Get top movers from UnifiedQuoteCache                    │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  sentiment_news_fetcher.py                                  │
│  ┌──────────────────────┐  ┌──────────────────────┐        │
│  │ NewsAPI (Primary)    │  │ Web Scraping (Backup)│        │
│  │ - 5-6 calls per run  │  │ - ET homepage        │        │
│  │ - 100 requests/day   │  │ - Moneycontrol RSS   │        │
│  └──────────┬───────────┘  └──────────┬───────────┘        │
│             │                          │                     │
│             └──────────┬───────────────┘                     │
│                        ▼                                     │
│              News Cache (24-hour TTL)                        │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  sentiment_scorer.py                                        │
│  - VADER NLP with Indian market lexicon                     │
│  - Score: 0-100 (0=bearish, 50=neutral, 100=bullish)        │
│  - Stock-level + Market-level aggregation                   │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  sentiment_storage.py                                       │
│  - SQLite database (sentiment_history.db)                   │
│  - JSON backup (sentiment_history.json)                     │
│  - Tables: stock_sentiment, market_sentiment, news_cache    │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  sentiment_alert_manager.py                                 │
│  - Detect: market shifts, sentiment flips, high-impact news │
│  - Cooldown: 30 minutes per stock (AlertHistoryManager)     │
│  - Priority: HIGH/NORMAL based on magnitude                 │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  telegram_notifier.send_sentiment_alert()                   │
│  + alert_excel_logger (Sentiment_alerts sheet)              │
└─────────────────────────────────────────────────────────────┘
```

---

## F&O Stock Filtering

### 3-Tier System (Optimize API Quota)

**Tier 1: Always Track (Top 30 Liquid Stocks - ~2 NewsAPI calls)**
```python
TIER_1_STOCKS = [
    'RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK', 'HDFC', 'BHARTIARTL',
    'SBIN', 'BAJFINANCE', 'ITC', 'KOTAKBANK', 'LT', 'ASIANPAINT', 'AXISBANK',
    'MARUTI', 'SUNPHARMA', 'TITAN', 'ULTRACEMCO', 'NESTLEIND', 'WIPRO',
    'HCLTECH', 'M&M', 'TATASTEEL', 'TECHM', 'ADANIPORTS', 'POWERGRID',
    'BAJAJFINSV', 'NTPC', 'JSWSTEEL', 'COALINDIA'
]
```
**Rationale**: High liquidity, most news coverage, significant market impact

**Tier 2: Conditional (Track if >1.5% move in last 15 min - ~1 NewsAPI call)**
- Query `UnifiedQuoteCache` for recent price changes
- Add to news query if significant movement detected
- Optimizes API quota by focusing on active stocks

**Tier 3: News-Triggered (Track only if mentioned in NewsAPI results)**
- Any stock mentioned in market overview query
- No additional API calls needed
- Catches unexpected news events for mid/small-cap F&O stocks

---

## NewsAPI Strategy

### Budget Management
- **Daily Quota**: 100 requests (NewsAPI free tier)
- **Runs per Day**: 18 (every 15 minutes, 9:25 AM - 3:25 PM)
- **Budget per Run**: 5-6 API calls maximum

### Query Execution Order

**Call 1: Overall Market News** (ALWAYS)
```python
query = "India stock market OR Nifty OR Sensex OR NSE"
params = {
    'q': query,
    'language': 'en',
    'sources': 'economic-times,the-hindu,business-standard',
    'sortBy': 'publishedAt',
    'pageSize': 20,
    'from': (now - 6 hours)  # Last 6 hours only
}
```
**Purpose**: Get overall market sentiment + catch any stocks mentioned

**Call 2: Top 5 Movers** (CONDITIONAL - if movers detected)
```python
top_movers = get_top_movers_from_cache()  # >2% price change
query = "RELIANCE OR TCS OR INFY OR HDFC OR ICICIBANK"  # Dynamic
```
**Purpose**: Track sentiment for stocks with significant price movements

**Call 3: Banking Stocks** (CONDITIONAL - if banks in top movers)
```python
query = "HDFC Bank OR ICICI Bank OR SBI OR Axis Bank"
```
**Purpose**: Bank Nifty sentiment (important index)

**Calls 4-6: Tier 1 Stocks in Batches** (Fill remaining quota)
```python
tier1_batches = [
    "RELIANCE OR TCS OR INFY OR HDFCBANK OR ICICIBANK OR HDFC OR BHARTIARTL OR SBIN OR BAJFINANCE OR ITC",
    "KOTAKBANK OR LT OR ASIANPAINT OR AXISBANK OR MARUTI OR SUNPHARMA OR TITAN OR ULTRACEMCO OR NESTLEIND OR WIPRO",
    "HCLTECH OR M&M OR TATASTEEL OR TECHM OR ADANIPORTS OR POWERGRID OR BAJAJFINSV OR NTPC OR JSWSTEEL OR COALINDIA"
]
```
**Purpose**: Ensure top 30 stocks always tracked

### Quota Tracking

**SQLite Table**: `api_quota`
```sql
CREATE TABLE api_quota (
    date TEXT PRIMARY KEY,        -- YYYY-MM-DD
    newsapi_calls INTEGER DEFAULT 0,
    last_reset TEXT
);
```

**Logic**:
```python
def check_quota():
    today = datetime.now(IST).strftime("%Y-%m-%d")
    used = db.execute("SELECT newsapi_calls FROM api_quota WHERE date=?", (today,))
    remaining = 100 - used

    if remaining < 5:
        logger.warning(f"NewsAPI quota low ({remaining} remaining) - switching to web scraping")
        return 0  # Force web scraping

    return min(remaining, 6)  # Max 6 calls per run
```

**Daily Reset**: Midnight IST (automatic - new date creates new row)

### Web Scraping Fallback

**Economic Times (BeautifulSoup)**
```python
url = 'https://economictimes.indiatimes.com/markets'
soup = BeautifulSoup(response.content, 'lxml')
articles = soup.find_all('article')  # Parse article tags
# Extract: headline, snippet, timestamp
```

**Moneycontrol RSS (feedparser)**
```python
rss_url = 'https://www.moneycontrol.com/rss/marketreports.xml'
feed = feedparser.parse(rss_url)
articles = [{'title': entry.title, 'link': entry.link} for entry in feed.entries]
```

**Trigger**:
- NewsAPI quota <5 remaining
- NewsAPI request fails (network, rate limit, etc.)

---

## Sentiment Scoring

### Library: VADER (Valence Aware Dictionary for Sentiment Reasoning)

**Why VADER?**
- ✅ Lightweight (no model download, instant startup)
- ✅ Rule-based (interpretable, customizable)
- ✅ Handles financial jargon ("bearish", "rally", "crash")
- ✅ Fast (no GPU needed, processes in milliseconds)
- ❌ FinBERT too slow (100MB+ model, 5-10 seconds per article)

### Indian Market Lexicon (Custom Additions)

```python
indian_market_lexicon = {
    # RBI & Monetary Policy
    'RBI': 0.0,                    # Neutral - depends on context
    'rate cut': 2.5,               # Very positive
    'rate hike': -2.5,             # Very negative
    'repo rate': 0.0,              # Neutral
    'liquidity': 1.0,              # Slightly positive

    # FII/DII Flows
    'FII': 1.5,                    # Positive (foreign investment)
    'DII': 1.0,                    # Positive (domestic investment)
    'FII outflow': -2.0,           # Negative
    'FII inflow': 2.0,             # Positive
    'foreign investors': 1.0,      # Slightly positive

    # Earnings
    'earnings beat': 3.0,          # Very positive
    'earnings miss': -3.0,         # Very negative
    'profit': 1.5,                 # Positive
    'loss': -2.0,                  # Negative
    'guidance': 0.5,               # Slightly positive
    'downgrade': -2.5,             # Negative
    'upgrade': 2.5,                # Positive

    # Corporate Actions
    'ban period': -2.5,            # Negative (F&O ban)
    'delisting': -3.5,             # Very negative
    'buyback': 2.0,                # Positive
    'bonus': 2.5,                  # Positive
    'split': 1.5,                  # Slightly positive
    'dividend': 1.5,               # Positive
    'merger': 1.0,                 # Slightly positive (depends on terms)

    # Negative Events
    'fraud': -3.5,                 # Very negative
    'scam': -3.5,                  # Very negative
    'investigation': -2.0,         # Negative
    'penalty': -2.0,               # Negative
    'lawsuit': -1.5,               # Slightly negative

    # Market Movements
    'rally': 2.0,                  # Positive
    'crash': -3.0,                 # Very negative
    'correction': -1.5,            # Slightly negative
    'breakout': 2.0,               # Positive
    'support': 1.0,                # Slightly positive
    'resistance': -0.5,            # Slightly negative
    'bullish': 2.0,                # Positive
    'bearish': -2.0,               # Negative
}
```

### Sentiment Calculation (0-100 Scale)

**Step 1: VADER Sentiment**
```python
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()
analyzer.lexicon.update(indian_market_lexicon)  # Add custom lexicon

# Get compound score (-1 to +1)
headline_sentiment = analyzer.polarity_scores(article['title'])
body_sentiment = analyzer.polarity_scores(article['content'][:500])  # First 500 chars
```

**Step 2: Weighted Average**
```python
# Weights: headline (60%), body (30%), volume (10%)
weighted_score = (headline_sentiment['compound'] * 0.6 +
                  body_sentiment['compound'] * 0.3)

# Volume multiplier (5+ articles amplify sentiment by 1.5x)
if article_count >= 5:
    volume_multiplier = min(1.0 + (article_count - 1) * 0.05, 1.5)
    weighted_score *= volume_multiplier
```

**Step 3: Convert to 0-100 Scale**
```python
sentiment_0_100 = (weighted_score + 1) * 50  # -1 to +1 → 0 to 100
```

**Interpretation**:
- **0-30**: Very Bearish (strong negative sentiment)
- **30-40**: Bearish (negative sentiment)
- **40-60**: Neutral (balanced or no clear direction)
- **60-70**: Bullish (positive sentiment)
- **70-100**: Very Bullish (strong positive sentiment)

### Stock-Level Aggregation

```python
def aggregate_stock_sentiment(stock: str, articles: List[Dict]) -> Dict:
    """
    Aggregate sentiment across multiple articles for a stock
    """
    if not articles:
        return {'score': 50, 'confidence': 0, 'article_count': 0}

    scores = [calculate_sentiment_score(a) for a in articles]

    return {
        'score': np.mean(scores),                    # Average sentiment
        'confidence': min(len(articles) * 15, 100),  # More articles = higher confidence
        'article_count': len(articles),
        'std_dev': np.std(scores),                   # Divergence in sentiment
        'sample_headlines': [a['title'] for a in articles[:3]]
    }
```

**Confidence Formula**: `min(article_count * 15, 100)`
- 1 article: 15% confidence
- 3 articles: 45% confidence
- 5 articles: 75% confidence
- 7+ articles: 100% confidence

### Market-Level Aggregation

**Nifty Sentiment**: Weighted average of top 30 stocks by market cap
```python
nifty_sentiment = sum(stock_sentiment[s]['score'] * market_cap[s] for s in tier1_stocks) / total_market_cap
```

**Bank Nifty Sentiment**: Average of banking stocks
```python
banking_stocks = ['HDFCBANK', 'ICICIBANK', 'SBIN', 'AXISBANK', 'KOTAKBANK']
banknifty_sentiment = np.mean([stock_sentiment[s]['score'] for s in banking_stocks])
```

---

## Alert Logic

### 3 Alert Conditions

**Condition 1: Market Sentiment Shift** (>20 Points)
```python
current_nifty = 35.7  # Current Nifty sentiment
previous_nifty = 58.2  # Previous run (15 min ago)
change = abs(current_nifty - previous_nifty)  # 22.5 points

if change > 20:
    send_alert(
        type='market_sentiment_shift',
        index='NIFTY',
        previous=58.2,
        current=35.7,
        change=-22.5,
        priority='HIGH' if change > 30 else 'NORMAL'
    )
```

**Alert Message**:
```
🔔🔔🔔 MARKET SENTIMENT ALERT 🔔🔔🔔
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Index: NIFTY 50
⏰ Time: 11:15 AM

📉 SENTIMENT SHIFT DETECTED
   Previous: 58.2 (Neutral-Bullish)
   Current: 35.7 (Bearish)
   Change: -22.5 points 🔴

📰 Based on 12 news articles (last 6 hours)

🔝 Top Headlines:
   • FII outflow hits ₹5,000 Cr as global markets tumble
   • RBI keeps rates unchanged, growth concerns persist
   • IT sector faces demand slowdown warnings

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ Sentiment Analyzer - 15-min updates
```

**Condition 2: Stock Sentiment Flip** (Bullish ↔ Bearish)
```python
previous_score = 68.5  # Bullish
current_score = 32.1   # Bearish

# Bullish → Bearish flip
if previous_score > 60 and current_score < 40:
    send_alert(
        type='sentiment_flip',
        direction='bullish_to_bearish',
        stock='RELIANCE',
        previous=68.5,
        current=32.1,
        change=-36.4,
        priority='HIGH' if article_count > 5 else 'NORMAL'
    )

# Bearish → Bullish flip
if previous_score < 40 and current_score > 60:
    send_alert(
        type='sentiment_flip',
        direction='bearish_to_bullish',
        stock='RELIANCE',
        previous=32.1,
        current=68.5,
        change=+36.4,
        priority='HIGH' if article_count > 5 else 'NORMAL'
    )
```

**Alert Message**:
```
🔴🔴 SENTIMENT FLIP ALERT 🔴🔴
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Stock: RELIANCE
⏰ Time: 02:30 PM

📉 BULLISH → BEARISH FLIP
   Previous: 68.5 (Bullish)
   Current: 32.1 (Bearish)
   Change: -36.4 points 🔴

📰 5 articles in last 6 hours
   Confidence: 75%

🔝 Top Headlines:
   • Reliance faces regulatory hurdles in telecom expansion
   • Profit margins under pressure as crude prices rise
   • Analysts downgrade on weak Q4 guidance

💰 Current Price: ₹2,450.30 (-1.2% today)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ Sentiment Analyzer - Real-time tracking
```

**Condition 3: High-Impact News** (3+ Articles + Extreme Sentiment)
```python
if article_count >= 3 and (sentiment_score > 70 or sentiment_score < 30):
    send_alert(
        type='high_impact_news',
        stock='SUNPHARMA',
        sentiment=78.3,
        article_count=5,
        headlines=sample_headlines,
        priority='NORMAL'
    )
```

**Alert Message**:
```
📰📰 HIGH-IMPACT NEWS ALERT 📰📰
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Stock: SUNPHARMA
⏰ Time: 01:45 PM

🔥 STRONG BULLISH SENTIMENT DETECTED
   Sentiment Score: 78.3 (Very Bullish)

📰 5 articles in last 6 hours
   Confidence: 75%

🔝 Top Headlines:
   • Sun Pharma gets USFDA approval for cancer drug
   • Q4 earnings beat estimates, margin expansion continues
   • Analysts upgrade target price by 15%

💰 Current Price: ₹1,125.50 (+2.3% today)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ Sentiment Analyzer - Real-time tracking
```

### Cooldown Management

**Pattern**: Reuse `AlertHistoryManager` from existing system

```python
# data/sentiment_alert_history.json
alert_manager = AlertHistoryManager(history_file="data/sentiment_alert_history.json")

# Check cooldown before sending
if alert_manager.should_send_alert(symbol="RELIANCE",
                                   alert_type="sentiment_flip",
                                   cooldown_minutes=30):
    send_telegram_alert(...)
```

**Cooldown Settings**:
- **Market sentiment shift**: 15 minutes (can happen multiple times if market volatile)
- **Stock sentiment flip**: 30 minutes (prevent spam for same stock)
- **High-impact news**: 30 minutes (prevent duplicate news alerts)

---

## Data Storage

### SQLite Schema (Primary Storage)

**File**: `data/sentiment_cache/sentiment_history.db`

**Table 1: stock_sentiment**
```sql
CREATE TABLE stock_sentiment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    sentiment_score REAL NOT NULL,        -- 0-100 scale
    article_count INTEGER NOT NULL,
    confidence REAL NOT NULL,             -- 0-100
    sample_headline_1 TEXT,
    sample_headline_2 TEXT,
    sample_headline_3 TEXT,
    change_from_previous REAL,            -- For alert detection
    UNIQUE(symbol, timestamp)
);

CREATE INDEX idx_stock_sentiment_symbol ON stock_sentiment(symbol);
CREATE INDEX idx_stock_sentiment_timestamp ON stock_sentiment(timestamp);
```

**Table 2: market_sentiment**
```sql
CREATE TABLE market_sentiment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    index_name TEXT NOT NULL,             -- 'NIFTY', 'BANKNIFTY', 'VIX'
    timestamp TEXT NOT NULL,
    sentiment_score REAL NOT NULL,        -- 0-100 scale
    article_count INTEGER NOT NULL,
    change_from_previous REAL,
    UNIQUE(index_name, timestamp)
);

CREATE INDEX idx_market_sentiment_index ON market_sentiment(index_name);
CREATE INDEX idx_market_sentiment_timestamp ON market_sentiment(timestamp);
```

**Table 3: news_cache** (24-hour deduplication)
```sql
CREATE TABLE news_cache (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL,                 -- 'newsapi', 'economictimes', 'moneycontrol'
    mentioned_stocks TEXT,                -- JSON array: ["RELIANCE", "TCS"]
    sentiment_score REAL
);

CREATE INDEX idx_news_cache_published_at ON news_cache(published_at);
CREATE INDEX idx_news_cache_fetched_at ON news_cache(fetched_at);
```

**Table 4: api_quota** (NewsAPI quota tracking)
```sql
CREATE TABLE api_quota (
    date TEXT PRIMARY KEY,                -- YYYY-MM-DD
    newsapi_calls INTEGER DEFAULT 0,
    last_reset TEXT
);
```

### JSON Backup (Fallback)

**File**: `data/sentiment_cache/sentiment_history.json`

```json
{
  "stocks": {
    "RELIANCE": {
      "2026-01-11T10:00:00": {
        "score": 72.5,
        "article_count": 3,
        "confidence": 45,
        "headlines": [
          "Reliance announces green energy investment",
          "Jio adds 10M subscribers in Q4",
          "Analysts upgrade RELIANCE to BUY"
        ],
        "change": +12.3
      }
    }
  },
  "market": {
    "NIFTY": {
      "2026-01-11T10:00:00": {
        "score": 58.3,
        "article_count": 12,
        "change": -5.7
      }
    }
  },
  "last_updated": "2026-01-11T10:15:00"
}
```

---

## Integration Points

### Reuse Existing Components

**1. market_utils.is_market_open()**
```python
from market_utils import is_market_open, get_market_status

if not is_market_open():
    logger.info("Market closed - skipping sentiment analysis")
    sys.exit(0)
```

**2. UnifiedQuoteCache** (Get top movers for tier 2 filtering)
```python
from unified_quote_cache import UnifiedQuoteCache

cache = UnifiedQuoteCache()
quotes = cache.get_or_fetch_quotes(tier1_stocks, kite_client)

# Calculate 15-min price changes
top_movers = [s for s, q in quotes.items() if abs(calculate_change(q)) > 2.0]
```

**3. AlertHistoryManager** (Cooldown management)
```python
from alert_history_manager import AlertHistoryManager

alert_manager = AlertHistoryManager(history_file="data/sentiment_alert_history.json")

if alert_manager.should_send_alert("RELIANCE", "sentiment_flip", cooldown_minutes=30):
    send_alert(...)
```

**4. TelegramNotifier** (Send alerts)
```python
from telegram_notifier import TelegramNotifier

telegram = TelegramNotifier()
telegram.send_sentiment_alert(
    alert_type='sentiment_flip',
    data={
        'symbol': 'RELIANCE',
        'previous_score': 68.5,
        'current_score': 32.1,
        'change': -36.4,
        'article_count': 5,
        'headlines': [...]
    },
    priority='HIGH'
)
```

**5. AlertExcelLogger** (Log to Excel)
```python
from alert_excel_logger import AlertExcelLogger

logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
logger.log_sentiment_alert(
    symbol='RELIANCE',
    alert_type='sentiment_flip',
    previous_score=68.5,
    current_score=32.1,
    change=-36.4,
    article_count=5,
    headlines=[...],
    telegram_sent=True
)
```

---

## Error Handling

### NewsAPI Failures

**Rate Limited**:
```python
try:
    articles = newsapi.get_everything(q=query, ...)
except NewsAPIException as e:
    if e.code == 'rateLimited':
        logger.warning("NewsAPI rate limited - switching to web scraping")
        articles = scrape_economic_times() + scrape_moneycontrol()
    else:
        raise
```

**Invalid API Key**:
```python
except NewsAPIException as e:
    if e.code == 'apiKeyInvalid':
        logger.error("NewsAPI key invalid - check .env file")
        sys.exit(1)
```

### Web Scraping Failures

**Primary Fallback**:
```python
try:
    articles = scrape_economic_times()
except requests.RequestException as e:
    logger.warning(f"ET scraping failed: {e}")
    try:
        articles = scrape_moneycontrol_rss()  # Secondary fallback
    except Exception as e2:
        logger.error(f"All news sources failed: {e2}")
        articles = []  # Graceful degradation
```

### Insufficient Data

**Skip Sentiment Analysis**:
```python
if len(articles) < 5:
    logger.warning(f"Only {len(articles)} articles fetched - insufficient data for reliable sentiment")
    sys.exit(0)  # Exit cleanly, don't send alerts
```

### SQLite Lock Handling

**Pattern from UnifiedQuoteCache**:
```python
try:
    db.execute("BEGIN IMMEDIATE")
    # ... database operations
    db.commit()
except sqlite3.OperationalError as e:
    if "locked" in str(e):
        logger.warning("Database locked - retrying in 2 seconds")
        time.sleep(2)
        retry_operation()  # Max 3 retries
    else:
        raise
```

### Market Closed

**Early Exit**:
```python
from market_utils import is_market_open, get_market_status

if not is_market_open():
    status = get_market_status()
    if not status['is_trading_day']:
        logger.info("Not a trading day - skipping sentiment analysis")
    else:
        logger.info("Outside market hours - skipping sentiment analysis")
    sys.exit(0)
```

---

## Telegram Alerts

### Message Templates

**Market Sentiment Shift**:
```python
def format_market_sentiment_shift(data):
    message = f"""
🔔🔔🔔 MARKET SENTIMENT ALERT 🔔🔔🔔
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Index: {data['index']}
⏰ Time: {data['time']}

📉 SENTIMENT SHIFT DETECTED
   Previous: {data['previous_score']} ({interpret_score(data['previous_score'])})
   Current: {data['current_score']} ({interpret_score(data['current_score'])})
   Change: {data['change']:+.1f} points {'🔴' if data['change'] < 0 else '🟢'}

📰 Based on {data['article_count']} news articles (last 6 hours)

🔝 Top Headlines:
   • {data['headline_1']}
   • {data['headline_2']}
   • {data['headline_3']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ Sentiment Analyzer - 15-min updates
    """
    return message
```

**Stock Sentiment Flip**:
```python
def format_sentiment_flip(data):
    message = f"""
{'🔴🔴' if data['direction'] == 'bullish_to_bearish' else '🟢🟢'} SENTIMENT FLIP ALERT {'🔴🔴' if data['direction'] == 'bullish_to_bearish' else '🟢🟢'}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Stock: {data['symbol']}
⏰ Time: {data['time']}

{'📉' if data['direction'] == 'bullish_to_bearish' else '📈'} {data['direction'].upper().replace('_', ' ')}
   Previous: {data['previous_score']} ({interpret_score(data['previous_score'])})
   Current: {data['current_score']} ({interpret_score(data['current_score'])})
   Change: {data['change']:+.1f} points {'🔴' if data['change'] < 0 else '🟢'}

📰 {data['article_count']} articles in last 6 hours
   Confidence: {data['confidence']}%

🔝 Top Headlines:
   • {data['headline_1']}
   • {data['headline_2']}
   • {data['headline_3']}

💰 Current Price: ₹{data['current_price']} ({data['price_change_pct']:+.1f}% today)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ Sentiment Analyzer - Real-time tracking
    """
    return message
```

**High-Impact News**:
```python
def format_high_impact_news(data):
    message = f"""
📰📰 HIGH-IMPACT NEWS ALERT 📰📰
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Stock: {data['symbol']}
⏰ Time: {data['time']}

🔥 {interpret_strong_sentiment(data['sentiment_score'])} SENTIMENT DETECTED
   Sentiment Score: {data['sentiment_score']} ({interpret_score(data['sentiment_score'])})

📰 {data['article_count']} articles in last 6 hours
   Confidence: {data['confidence']}%

🔝 Top Headlines:
   • {data['headline_1']}
   • {data['headline_2']}
   • {data['headline_3']}

💰 Current Price: ₹{data['current_price']} ({data['price_change_pct']:+.1f}% today)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ Sentiment Analyzer - Real-time tracking
    """
    return message

def interpret_strong_sentiment(score):
    if score > 70:
        return "STRONG BULLISH"
    elif score < 30:
        return "STRONG BEARISH"
    else:
        return "MODERATE"
```

---

## Verification Plan

### Phase 1: Manual Testing (Dry-Run Mode)

**Add dry-run flag**:
```python
# sentiment_analyzer.py
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Print alerts without sending')
    args = parser.parse_args()

    # Pass dry_run flag to alert manager
    run_sentiment_analysis(dry_run=args.dry_run)
```

**Manual execution**:
```bash
cd /Users/sunildeesu/myProjects/ShortIndicator
source venv/bin/activate
python sentiment_analyzer.py --dry-run
```

**Verify**:
- ✅ NewsAPI fetches articles successfully
- ✅ VADER sentiment scores are reasonable (compare with manual headline reading)
- ✅ SQLite database created with correct schema
- ✅ Data persisted correctly (check tables with SQLite browser)
- ✅ Alert conditions trigger properly (inject test data)
- ✅ No Telegram alerts sent (dry-run mode)
- ✅ Console output shows formatted alerts

### Phase 2: Integration Testing

**Test with real NewsAPI key**:
```bash
# Set NEWSAPI_KEY in .env
echo "NEWSAPI_KEY=your_actual_key" >> .env

# Run with limited quota to test fallback
python sentiment_analyzer.py
```

**Verify**:
- ✅ NewsAPI integration works (check logs for successful API calls)
- ✅ Web scraping fallback activates when quota low
- ✅ UnifiedQuoteCache integration (top movers detected)
- ✅ Market hours check (run outside market hours, should exit cleanly)
- ✅ Alert cooldown (manually trigger 2 alerts <30 min apart, verify 2nd blocked)
- ✅ Excel logging (check new "Sentiment_alerts" sheet created)

### Phase 3: Production Deployment

**Load launchd plist**:
```bash
# Copy plist to LaunchAgents
cp com.nse.sentiment.plist ~/Library/LaunchAgents/

# Load service
launchctl load ~/Library/LaunchAgents/com.nse.sentiment.plist

# Check status
launchctl list | grep sentiment
```

**Monitor logs**:
```bash
tail -f logs/sentiment_analyzer.log
```

**Verify**:
- ✅ First run executes after 15 minutes
- ✅ Subsequent runs every 15 minutes during market hours
- ✅ Telegram alerts appear in channel (if sentiment changes detected)
- ✅ Excel logging works (new rows added to "Sentiment_alerts" sheet)
- ✅ No errors in logs

### Phase 4: Validation (1-2 Days)

**Sentiment Accuracy**:
- Compare sentiment scores with manual reading of headlines
- Check if market reactions align with sentiment (bullish sentiment → price rise?)
- Validate Indian market lexicon (RBI, FII keywords detected properly?)

**Alert Quality**:
- No false positives (alerts for non-significant changes)
- No missed alerts (significant changes not detected)
- Alert frequency reasonable (5-10 alerts/day, not 50+)

**System Performance**:
- NewsAPI quota usage ≤100/day (check api_quota table)
- Script execution time <2 minutes per run
- No SQLite lock errors
- No memory leaks (check process memory after 24 hours)

**Key Metrics**:
```python
# Query SQLite for validation
SELECT
    COUNT(*) as total_runs,
    AVG(article_count) as avg_articles_per_run,
    COUNT(DISTINCT symbol) as stocks_tracked
FROM stock_sentiment
WHERE DATE(timestamp) = '2026-01-11';

# Check API quota usage
SELECT date, newsapi_calls
FROM api_quota
ORDER BY date DESC LIMIT 7;

# Alert frequency
SELECT
    alert_type,
    COUNT(*) as alert_count
FROM sentiment_alerts  # Excel sheet
WHERE DATE(timestamp) = '2026-01-11'
GROUP BY alert_type;
```

---

## Implementation Checklist

### Setup Phase
- [ ] Install dependencies: `pip install newsapi-python vaderSentiment beautifulsoup4 lxml feedparser`
- [ ] Get NewsAPI key from https://newsapi.org/ (free tier: 100 requests/day)
- [ ] Add `NEWSAPI_KEY=your_key` to `.env` file
- [ ] Update `.env.example` with `NEWSAPI_KEY=your_newsapi_key_here`

### Configuration Phase
- [ ] Add sentiment configuration section to `config.py`
  - NewsAPI settings (key, quota, calls per run)
  - Sentiment thresholds (market shift, flip thresholds, high-impact)
  - Cooldown settings (30 min per stock)
  - Tier 1 stocks list (top 30 F&O stocks)
  - Storage paths (DB, JSON backup, news cache, alert history)

### Core Components Phase
- [ ] Create `sentiment_scorer.py`
  - VADER initialization with Indian market lexicon
  - `calculate_sentiment_score(article)` function (0-100 scale)
  - `aggregate_stock_sentiment(stock, articles)` function
  - `aggregate_market_sentiment(stocks)` function

- [ ] Create `sentiment_storage.py`
  - SQLite schema creation (4 tables: stock_sentiment, market_sentiment, news_cache, api_quota)
  - `save_stock_sentiment(symbol, score, articles)` method
  - `save_market_sentiment(index, score, articles)` method
  - `get_previous_sentiment(symbol/index)` method for change detection
  - JSON backup logic (fallback if SQLite unavailable)
  - File locking (fcntl pattern from AlertHistoryManager)

### Data Fetching Phase
- [ ] Create `sentiment_news_fetcher.py`
  - NewsAPI integration with quota management
  - Query strategy: 5-6 API calls per run (market, movers, banking, tier1 batches)
  - Economic Times web scraping (BeautifulSoup)
  - Moneycontrol RSS parsing (feedparser)
  - News caching (24-hour TTL, SQLite news_cache table)
  - Quota tracking (api_quota table, daily reset at midnight IST)
  - Error handling (fallback to web scraping if NewsAPI fails)

### Alert Logic Phase
- [ ] Create `sentiment_alert_manager.py`
  - Import `AlertHistoryManager` for cooldown
  - Condition 1: Market sentiment shift (>20 points)
  - Condition 2: Stock sentiment flip (>60 to <40 or vice versa)
  - Condition 3: High-impact news (3+ articles, sentiment >70 or <30)
  - Priority calculation (HIGH/NORMAL based on magnitude)
  - `should_send_alert()` method with cooldown check (30 min)

### Main Orchestrator Phase
- [ ] Create `sentiment_analyzer.py`
  - Import all modules (fetcher, scorer, storage, alert_manager)
  - Check market hours (`is_market_open()`)
  - Get top movers from UnifiedQuoteCache
  - Fetch news (NewsAPI + fallback)
  - Calculate sentiment scores (stock-level + market-level)
  - Save to storage (SQLite + JSON backup)
  - Detect alert conditions
  - Send alerts (Telegram + Excel logging)
  - Add `--dry-run` flag for testing
  - Graceful error handling (exit cleanly if market closed or insufficient data)

### Integration Phase
- [ ] Modify `telegram_notifier.py`
  - Add `send_sentiment_alert(alert_type, data, priority)` method
  - Format message templates (market shift, sentiment flip, high-impact news)
  - Emoji indicators (🔴 bearish, 🟢 bullish)
  - Excel logging integration (call AlertExcelLogger)

- [ ] Modify `alert_excel_logger.py`
  - Add new sheet: "Sentiment_alerts"
  - Columns: Date, Time, Alert Type, Symbol/Index, Previous Score, Current Score, Change, Direction, Article Count, Confidence, Headline 1, Headline 2, Headline 3, Telegram Sent, Row ID
  - `log_sentiment_alert()` method

### Service Control Phase
- [ ] Create `sentiment_service.sh`
  - Pattern from `onemin_service.sh`
  - Commands: start, stop, restart, status
  - launchctl wrapper for `com.nse.sentiment.plist`
  - Logging: stdout/stderr to `logs/sentiment_analyzer.log`

- [ ] Create `com.nse.sentiment.plist`
  - Label: `com.nse.sentiment`
  - ProgramArguments: `/venv/bin/python3 sentiment_analyzer.py`
  - WorkingDirectory: `/Users/sunildeesu/myProjects/ShortIndicator`
  - StartInterval: 900 (15 minutes)
  - Logs: `logs/sentiment_analyzer.log`

### Testing Phase
- [ ] **Phase 1: Manual Dry-Run**
  - Run `python sentiment_analyzer.py --dry-run`
  - Verify NewsAPI fetches articles
  - Check VADER sentiment scores (manual comparison)
  - Verify SQLite database created and populated
  - Test alert conditions (inject test data)
  - Confirm no Telegram alerts sent

- [ ] **Phase 2: Integration Testing**
  - Test with real NewsAPI key
  - Verify web scraping fallback
  - Test UnifiedQuoteCache integration
  - Test market hours check (run outside market hours)
  - Test alert cooldown (2 alerts <30 min apart)
  - Verify Excel logging

- [ ] **Phase 3: Production Deployment**
  - Copy plist to `~/Library/LaunchAgents/`
  - Load service: `launchctl load ~/Library/LaunchAgents/com.nse.sentiment.plist`
  - Monitor logs: `tail -f logs/sentiment_analyzer.log`
  - Verify first run after 15 minutes
  - Check Telegram channel for alerts
  - Verify Excel sheet populated

- [ ] **Phase 4: Validation (1-2 Days)**
  - Compare sentiment scores with market reactions
  - Check for false positives/negatives
  - Monitor API quota usage (≤100/day)
  - Check script execution time (<2 min)
  - Validate alert frequency (5-10/day reasonable)

### Data Directory Setup
- [ ] Create directories:
  ```bash
  mkdir -p data/sentiment_cache
  mkdir -p logs
  ```

### Documentation Phase
- [ ] Update README.md with sentiment analyzer section
- [ ] Document NewsAPI setup (how to get API key)
- [ ] Add troubleshooting section (common errors, solutions)

---

## Dependencies (requirements.txt)

```txt
# Existing dependencies
requests==2.31.0
python-dotenv==1.0.0
openpyxl==3.1.2
# ... other existing dependencies

# New dependencies for sentiment analyzer
newsapi-python==0.2.7          # NewsAPI client
vaderSentiment==3.3.2          # Sentiment analysis (NLP)
beautifulsoup4==4.12.2         # Web scraping (ET)
lxml==4.9.3                    # HTML parsing (faster than html.parser)
feedparser==6.0.10             # RSS feed parsing (Moneycontrol)
```

**Installation**:
```bash
source venv/bin/activate
pip install newsapi-python vaderSentiment beautifulsoup4 lxml feedparser
pip freeze > requirements.txt  # Update requirements.txt
```

---

## Success Criteria

### Functional Requirements
- ✅ Sentiment analyzer runs every 15 minutes during market hours (9:25 AM - 3:25 PM IST)
- ✅ NewsAPI fetches news successfully (5-6 calls per run, ≤100/day total)
- ✅ Web scraping fallback activates when quota exhausted or NewsAPI fails
- ✅ VADER sentiment scores reflect news tone accurately (manual validation)
- ✅ SQLite database stores sentiment history with proper indexing
- ✅ Alert conditions detect significant changes accurately (no false positives)
- ✅ Telegram alerts formatted clearly with sentiment scores, headlines, emoji indicators
- ✅ Excel logging works (new "Sentiment_alerts" sheet populated)
- ✅ Alert cooldown prevents spam (30-min cooldown per stock enforced)
- ✅ Graceful error handling (NewsAPI failures, web scraping failures, market closed)

### Performance Requirements
- ✅ Script execution completes in <2 minutes per run (including API calls, sentiment calculation, storage)
- ✅ NewsAPI quota consumption ≤100 requests/day (18 runs × 5-6 calls = 90-108, close to limit)
- ✅ SQLite database size manageable (<100 MB after 1 month of data)
- ✅ No memory leaks (process memory stable after 24+ hours of operation)

### Integration Requirements
- ✅ System integrates seamlessly with existing infrastructure (TelegramNotifier, AlertHistoryManager, UnifiedQuoteCache, market_utils)
- ✅ Follows existing code patterns (file locking, error handling, logging conventions)
- ✅ No conflicts with other monitors (1-min alerts, 5-min alerts, volume profile)

### Alert Quality
- ✅ Alert frequency reasonable (5-10 alerts/day on average, not 50+)
- ✅ No false positives (alerts for non-significant sentiment changes)
- ✅ No missed alerts (significant sentiment shifts detected and reported)
- ✅ High-confidence alerts (only when article count ≥3 for stock flips, ≥12 for market shifts)

---

## Future Enhancements (Post-MVP)

**Enhancement 1: Sector Sentiment Tracking**
- Aggregate sentiment by sector (Banking, IT, Pharma, Auto, etc.)
- Alert on sector rotation signals (Banking sentiment ↑, IT sentiment ↓)

**Enhancement 2: Twitter/X Integration**
- Add social media sentiment from Twitter/X API (paid tier: $100/month)
- Track #Nifty, #BankNifty, stock-specific hashtags
- Combine with news sentiment for higher confidence

**Enhancement 3: Historical Sentiment vs. Price Correlation**
- Backtest sentiment scores against actual price movements
- Calculate correlation coefficient (sentiment lead time before price moves)
- Optimize alert thresholds based on historical accuracy

**Enhancement 4: Sentiment Dashboard**
- Web dashboard showing real-time sentiment heatmap
- Visualize sentiment trends over time (line charts)
- Compare sentiment vs. price movements

**Enhancement 5: Multi-Language Support**
- Parse Hindi news sources (Dainik Jagran, Amar Ujala)
- Translate to English before sentiment analysis
- Capture regional sentiment not covered by English media

---

## Conclusion

This design document provides a comprehensive blueprint for implementing a production-ready sentiment analyzer for Indian equity markets. The system:

- **Integrates seamlessly** with existing infrastructure (Telegram, Excel, caching, market hours)
- **Optimizes API usage** with 3-tier F&O stock filtering and quota management
- **Provides actionable insights** through crisp, well-formatted alerts (only on significant changes)
- **Handles errors gracefully** with fallback mechanisms (web scraping, JSON backup)
- **Follows best practices** from existing codebase (file locking, cooldown, logging)

**Estimated Development Time**: 2-3 days (8-10 hours of focused coding + 2-3 hours testing)

**When to Code**: When you're ready to implement, follow the **Implementation Checklist** section sequentially. Start with setup (dependencies, API key), then configuration, then core components (scorer, storage), then data fetching, then alerts, then integration, then service control, and finally testing.

---

**End of Design Document**

*For implementation assistance, refer to the detailed plan at `/Users/sunildeesu/.claude/plans/concurrent-seeking-fountain.md`*
