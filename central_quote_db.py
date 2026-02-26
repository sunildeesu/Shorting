#!/usr/bin/env python3
"""
Central Quote Database - Unified Data Store
Stores real-time quotes for all F&O stocks, NIFTY, and VIX
All monitoring services read from this central database

CONCURRENCY DESIGN:
- Writer (Central Collector): Single persistent connection with WAL mode
- Readers (All Services): Separate connections per service, read-only mode
- WAL mode allows multiple concurrent readers + 1 writer
- Each service gets its own connection to avoid blocking

Author: Claude Sonnet 4.5
Date: 2026-01-19
"""

import sqlite3
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import config

logger = logging.getLogger(__name__)

# Thread-local storage for reader connections
_thread_local = threading.local()


class CentralQuoteDB:
    """
    Centralized quote database for all monitoring services.
    Single source of truth for real-time market data.

    CONCURRENCY MODEL:
    - Writer mode: Single persistent connection for central collector
    - Reader mode: Thread-local connections for each reading service
    - WAL mode allows 1 writer + unlimited concurrent readers
    """

    def __init__(self, db_path: str = "data/central_quotes.db", mode: str = "reader"):
        """
        Initialize central quote database.

        Args:
            db_path: Path to SQLite database file
            mode: "writer" for central collector, "reader" for services
        """
        self.db_path = db_path
        self.mode = mode
        self._writer_conn = None  # Persistent connection for writer
        self._lock = threading.Lock()  # Lock for writer operations

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # Initialize database (create tables if needed)
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection optimized for the current mode.

        - Writer mode: Returns persistent connection
        - Reader mode: Returns thread-local connection (each thread gets its own)

        Returns:
            sqlite3.Connection optimized for the mode
        """
        if self.mode == "writer":
            # Writer uses persistent connection
            if self._writer_conn is None:
                self._writer_conn = self._create_writer_connection()
            return self._writer_conn
        else:
            # Reader uses thread-local connection (avoids blocking other readers)
            if not hasattr(_thread_local, 'conn') or _thread_local.conn is None:
                _thread_local.conn = self._create_reader_connection()
            return _thread_local.conn

    def _create_writer_connection(self) -> sqlite3.Connection:
        """Create optimized connection for writer (central collector)"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=config.SQLITE_TIMEOUT_SECONDS,
            check_same_thread=False
        )

        # Writer-optimized settings
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA busy_timeout=30000")  # 30 second busy timeout
        conn.execute("PRAGMA wal_autocheckpoint=1000")  # Checkpoint every 1000 pages

        logger.info(f"Writer connection created: {self.db_path}")
        return conn

    def _create_reader_connection(self) -> sqlite3.Connection:
        """Create optimized connection for reader (monitoring services)"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=config.SQLITE_TIMEOUT_SECONDS,
            check_same_thread=False
        )

        # Reader-optimized settings
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-32000")  # 32MB cache (smaller for readers)
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA busy_timeout=5000")  # 5 second busy timeout (readers shouldn't wait long)
        conn.execute("PRAGMA query_only=ON")  # Read-only mode (prevents accidental writes)
        conn.execute("PRAGMA read_uncommitted=ON")  # Allow reading uncommitted data (faster)

        logger.debug(f"Reader connection created for thread {threading.current_thread().name}")
        return conn

    def _init_database(self):
        """Initialize SQLite database with optimized settings"""
        try:
            # Use a temporary connection to create tables
            conn = sqlite3.connect(
                self.db_path,
                timeout=config.SQLITE_TIMEOUT_SECONDS
            )

            # Enable WAL mode for concurrent reads/writes
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")

            # Create tables
            self._create_tables_with_conn(conn)
            conn.close()

            logger.info(f"Central quote database initialized: {self.db_path} (mode={self.mode})")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    @property
    def conn(self):
        """Property for backward compatibility - returns appropriate connection"""
        return self._get_connection()

    def _create_tables_with_conn(self, conn: sqlite3.Connection):
        """Create database tables and indexes using provided connection"""
        cursor = conn.cursor()

        # Table 1: F&O Stock Quotes (real-time equity + futures data)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_quotes (
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                price REAL NOT NULL,
                volume INTEGER,
                oi INTEGER DEFAULT 0,
                oi_day_high INTEGER DEFAULT 0,
                oi_day_low INTEGER DEFAULT 0,
                last_updated TEXT NOT NULL,
                PRIMARY KEY (symbol, timestamp)
            )
        """)

        # Index for fast time-series queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_stock_timestamp
            ON stock_quotes(symbol, timestamp DESC)
        """)

        # Index for latest price lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_stock_latest
            ON stock_quotes(symbol, last_updated DESC)
        """)

        # Table 2: NIFTY Spot Quotes (1-minute NIFTY 50 data)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nifty_quotes (
                timestamp TEXT PRIMARY KEY,
                price REAL NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                volume INTEGER,
                last_updated TEXT NOT NULL
            )
        """)

        # Index for time-series queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_nifty_timestamp
            ON nifty_quotes(timestamp DESC)
        """)

        # Table 3: India VIX Quotes (1-minute VIX data)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vix_quotes (
                timestamp TEXT PRIMARY KEY,
                vix_value REAL NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                last_updated TEXT NOT NULL
            )
        """)

        # Index for time-series queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_vix_timestamp
            ON vix_quotes(timestamp DESC)
        """)

        # Table 4: Metadata (track collector health, last update times)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.commit()
        logger.info("Database tables and indexes created successfully")

    def _create_tables(self):
        """Create database tables and indexes (backward compatibility)"""
        self._create_tables_with_conn(self.conn)

    # ============================================
    # WRITE OPERATIONS (Central Collector Only)
    # ============================================

    def store_stock_quotes(self, quotes: Dict[str, Dict], timestamp: datetime):
        """
        Store F&O stock quotes (bulk insert for efficiency).

        Args:
            quotes: Dict of {symbol: {price, volume, oi, oi_day_high, oi_day_low}}
            timestamp: Data timestamp (minute-level precision)
        """
        if not quotes:
            return

        cursor = self.conn.cursor()
        ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')  # Round to minute
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Bulk insert
        rows = []
        for symbol, data in quotes.items():
            rows.append((
                symbol,
                ts_str,
                data.get('price', 0),
                data.get('volume', 0),
                data.get('oi', 0),
                data.get('oi_day_high', 0),
                data.get('oi_day_low', 0),
                now_str
            ))

        cursor.executemany("""
            INSERT OR REPLACE INTO stock_quotes
            (symbol, timestamp, price, volume, oi, oi_day_high, oi_day_low, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)

        self.conn.commit()
        logger.info(f"Stored {len(rows)} stock quotes at {ts_str}")

    def store_nifty_quote(self, price: float, ohlc: Dict, timestamp: datetime):
        """
        Store NIFTY spot quote.

        Args:
            price: Current NIFTY price
            ohlc: Dict with 'open', 'high', 'low', 'volume'
            timestamp: Data timestamp
        """
        cursor = self.conn.cursor()
        ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute("""
            INSERT OR REPLACE INTO nifty_quotes
            (timestamp, price, open, high, low, volume, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            ts_str,
            price,
            ohlc.get('open', price),
            ohlc.get('high', price),
            ohlc.get('low', price),
            ohlc.get('volume', 0),
            now_str
        ))

        self.conn.commit()
        logger.debug(f"Stored NIFTY quote at {ts_str}: ₹{price:.2f}")

    def store_vix_quote(self, vix_value: float, ohlc: Dict, timestamp: datetime):
        """
        Store India VIX quote.

        Args:
            vix_value: Current VIX value
            ohlc: Dict with 'open', 'high', 'low'
            timestamp: Data timestamp
        """
        cursor = self.conn.cursor()
        ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute("""
            INSERT OR REPLACE INTO vix_quotes
            (timestamp, vix_value, open, high, low, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ts_str,
            vix_value,
            ohlc.get('open', vix_value),
            ohlc.get('high', vix_value),
            ohlc.get('low', vix_value),
            now_str
        ))

        self.conn.commit()
        logger.debug(f"Stored VIX quote at {ts_str}: {vix_value:.2f}")

    def update_metadata(self, key: str, value: str):
        """
        Update metadata (e.g., last_collection_time).

        Args:
            key: Metadata key
            value: Metadata value
        """
        cursor = self.conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute("""
            INSERT OR REPLACE INTO metadata (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value, now_str))

        self.conn.commit()

    # ============================================
    # READ OPERATIONS (All Monitoring Services)
    # ============================================

    def get_latest_stock_quotes(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict]:
        """
        Get latest quotes for stocks (most recent timestamp).

        Args:
            symbols: List of symbols (None = all stocks)

        Returns:
            Dict of {symbol: {price, volume, oi, timestamp}}
        """
        cursor = self.conn.cursor()

        if symbols:
            placeholders = ','.join('?' * len(symbols))
            query = f"""
                SELECT symbol, timestamp, price, volume, oi, oi_day_high, oi_day_low
                FROM stock_quotes
                WHERE symbol IN ({placeholders})
                AND timestamp = (
                    SELECT MAX(timestamp)
                    FROM stock_quotes sq2
                    WHERE sq2.symbol = stock_quotes.symbol
                )
            """
            cursor.execute(query, symbols)
        else:
            cursor.execute("""
                SELECT symbol, timestamp, price, volume, oi, oi_day_high, oi_day_low
                FROM stock_quotes
                WHERE timestamp = (
                    SELECT MAX(timestamp)
                    FROM stock_quotes sq2
                    WHERE sq2.symbol = stock_quotes.symbol
                )
            """)

        quotes = {}
        for row in cursor.fetchall():
            symbol, timestamp, price, volume, oi, oi_high, oi_low = row
            quotes[symbol] = {
                'price': price,
                'volume': volume,
                'oi': oi,
                'oi_day_high': oi_high,
                'oi_day_low': oi_low,
                'timestamp': timestamp
            }

        return quotes

    def get_stock_history(self, symbol: str, minutes: int = 30) -> List[Dict]:
        """
        Get historical quotes for a stock (last N minutes).

        Args:
            symbol: Stock symbol
            minutes: Number of minutes to look back

        Returns:
            List of {timestamp, price, volume, oi} ordered by timestamp ASC
        """
        cursor = self.conn.cursor()
        cutoff = datetime.now() - timedelta(minutes=minutes)
        cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:00')

        cursor.execute("""
            SELECT timestamp, price, volume, oi
            FROM stock_quotes
            WHERE symbol = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (symbol, cutoff_str))

        history = []
        for row in cursor.fetchall():
            history.append({
                'timestamp': row[0],
                'price': row[1],
                'volume': row[2],
                'oi': row[3]
            })

        return history

    def get_stock_price_at(self, symbol: str, minutes_ago: int) -> Optional[float]:
        """
        Get stock price N minutes ago.

        Args:
            symbol: Stock symbol
            minutes_ago: How many minutes back (1, 5, 10, 30)

        Returns:
            Price at that time, or None if not found
        """
        target_time = datetime.now() - timedelta(minutes=minutes_ago)
        # Round to nearest minute
        target_str = target_time.strftime('%Y-%m-%d %H:%M:00')

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT price FROM stock_quotes
            WHERE symbol = ? AND timestamp = ?
        """, (symbol, target_str))

        row = cursor.fetchone()
        return row[0] if row else None

    def get_stock_price_at_time(self, symbol: str, timestamp_str: str) -> Optional[float]:
        """
        Get stock price at an absolute timestamp.

        Unlike get_stock_price_at(minutes_ago) which is relative to now,
        this queries by an absolute timestamp string.

        Args:
            symbol: Stock symbol
            timestamp_str: Timestamp in format 'YYYY-MM-DD HH:MM:00'

        Returns:
            Price at that time, or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT price FROM stock_quotes
            WHERE symbol = ? AND timestamp = ?
        """, (symbol, timestamp_str))

        row = cursor.fetchone()
        return row[0] if row else None

    def get_stock_prices_at_batch(self, symbols: List[str], minutes_ago: int) -> Dict[str, float]:
        """
        Get prices for multiple stocks N minutes ago in ONE query.

        ~5ms for 209 stocks vs 500ms for 209 individual queries.
        Used by RapidDropDetector for fast 5-minute drop detection.

        Args:
            symbols: List of stock symbols
            minutes_ago: How many minutes back (e.g., 5 for 5-min detection)

        Returns:
            Dict mapping symbol to price, e.g., {'RELIANCE': 2450.50, 'TCS': 3800.25}
            Symbols not found are omitted from result.
        """
        if not symbols:
            return {}

        target_time = datetime.now() - timedelta(minutes=minutes_ago)
        target_str = target_time.strftime('%Y-%m-%d %H:%M:00')

        cursor = self.conn.cursor()

        # Build parameterized query for all symbols in one shot
        placeholders = ','.join('?' * len(symbols))
        query = f"""
            SELECT symbol, price
            FROM stock_quotes
            WHERE symbol IN ({placeholders})
            AND timestamp = ?
        """

        # Execute with symbols + target timestamp
        params = list(symbols) + [target_str]
        cursor.execute(query, params)

        # Build result dict
        result = {}
        for row in cursor.fetchall():
            symbol, price = row
            if price and price > 0:
                result[symbol] = price

        return result

    def get_stock_quotes_at_batch(self, symbols: List[str], minutes_ago: int) -> Dict[str, Dict]:
        """
        Get price AND volume for multiple stocks N minutes ago in ONE query.

        Used by RapidAlertDetector for volume spike detection.

        Args:
            symbols: List of stock symbols
            minutes_ago: How many minutes back (e.g., 5 for 5-min detection)

        Returns:
            Dict mapping symbol to {price, volume}, e.g.,
            {'RELIANCE': {'price': 2450.50, 'volume': 125000}, ...}
            Symbols not found are omitted from result.
        """
        if not symbols:
            return {}

        target_time = datetime.now() - timedelta(minutes=minutes_ago)
        target_str = target_time.strftime('%Y-%m-%d %H:%M:00')

        cursor = self.conn.cursor()

        # Build parameterized query for all symbols in one shot
        placeholders = ','.join('?' * len(symbols))
        query = f"""
            SELECT symbol, price, volume
            FROM stock_quotes
            WHERE symbol IN ({placeholders})
            AND timestamp = ?
        """

        # Execute with symbols + target timestamp
        params = list(symbols) + [target_str]
        cursor.execute(query, params)

        # Build result dict
        result = {}
        for row in cursor.fetchall():
            symbol, price, volume = row
            if price and price > 0:
                result[symbol] = {'price': price, 'volume': volume or 0}

        return result

    def get_stock_day_open_prices_batch(self, symbols: List[str]) -> Dict[str, float]:
        """
        Get the first recorded price of the day for multiple stocks in ONE query.
        Used for calculating full-day price change in EOD reports.

        Args:
            symbols: List of stock symbols

        Returns:
            Dict mapping symbol to opening price, e.g., {'RELIANCE': 2450.50, ...}
        """
        if not symbols:
            return {}

        today_str = datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.cursor()

        placeholders = ','.join('?' * len(symbols))
        query = f"""
            SELECT sq.symbol, sq.price
            FROM stock_quotes sq
            INNER JOIN (
                SELECT symbol, MIN(timestamp) as first_ts
                FROM stock_quotes
                WHERE symbol IN ({placeholders})
                AND timestamp >= ?
                GROUP BY symbol
            ) first ON sq.symbol = first.symbol AND sq.timestamp = first.first_ts
        """

        params = list(symbols) + [today_str]
        cursor.execute(query, params)

        result = {}
        for row in cursor.fetchall():
            symbol, price = row
            if price and price > 0:
                result[symbol] = price

        return result

    def get_stock_day_aggregates_batch(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Get day aggregates for multiple stocks in ONE query.
        Returns total_volume, day_high, day_low, candle_count per stock for today.

        Args:
            symbols: List of stock symbols

        Returns:
            Dict mapping symbol to {total_volume, day_high, day_low, candle_count}
        """
        if not symbols:
            return {}

        today_str = datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.cursor()

        placeholders = ','.join('?' * len(symbols))
        query = f"""
            SELECT symbol, MAX(volume) as total_volume, MAX(price) as day_high,
                   MIN(price) as day_low, COUNT(*) as candle_count
            FROM stock_quotes
            WHERE symbol IN ({placeholders})
            AND timestamp >= ?
            GROUP BY symbol
        """

        params = list(symbols) + [today_str]
        cursor.execute(query, params)

        result = {}
        for row in cursor.fetchall():
            symbol, total_volume, day_high, day_low, candle_count = row
            result[symbol] = {
                'total_volume': total_volume or 0,
                'day_high': day_high or 0,
                'day_low': day_low or 0,
                'candle_count': candle_count or 0
            }

        return result

    def get_stock_history_since_batch(self, symbols: List[str], since_time_str: str) -> Dict[str, List[Dict]]:
        """
        Get minute-by-minute history for multiple stocks since a given time in ONE query.
        Avoids N+1 queries (one get_stock_history() per stock).

        Args:
            symbols: List of stock symbols
            since_time_str: Time string in format 'YYYY-MM-DD HH:MM:00'

        Returns:
            Dict mapping symbol to list of {timestamp, price, volume}
        """
        if not symbols:
            return {}

        cursor = self.conn.cursor()

        placeholders = ','.join('?' * len(symbols))
        query = f"""
            SELECT symbol, timestamp, price, volume
            FROM stock_quotes
            WHERE symbol IN ({placeholders})
            AND timestamp >= ?
            ORDER BY symbol, timestamp ASC
        """

        params = list(symbols) + [since_time_str]
        cursor.execute(query, params)

        result: Dict[str, List[Dict]] = {}
        for row in cursor.fetchall():
            symbol, timestamp, price, volume = row
            if symbol not in result:
                result[symbol] = []
            result[symbol].append({
                'timestamp': timestamp,
                'price': price,
                'volume': volume or 0
            })

        return result

    def get_nifty_history_since(self, since_time_str: str) -> List[Dict]:
        """
        Get NIFTY historical data since a given time.

        Args:
            since_time_str: Time string in format 'YYYY-MM-DD HH:MM:00'

        Returns:
            List of {timestamp, price, volume} ordered by timestamp ASC
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT timestamp, price, volume
            FROM nifty_quotes
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """, (since_time_str,))

        history = []
        for row in cursor.fetchall():
            history.append({
                'timestamp': row[0],
                'price': row[1],
                'volume': row[2]
            })

        return history

    def get_nifty_latest(self) -> Optional[Dict]:
        """
        Get latest NIFTY quote.

        Returns:
            Dict with {price, open, high, low, volume, timestamp}
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT timestamp, price, open, high, low, volume
            FROM nifty_quotes
            ORDER BY timestamp DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        if row:
            return {
                'timestamp': row[0],
                'price': row[1],
                'open': row[2],
                'high': row[3],
                'low': row[4],
                'volume': row[5]
            }
        return None

    def get_nifty_history(self, minutes: int = 30) -> List[Dict]:
        """
        Get NIFTY historical data (last N minutes).

        Args:
            minutes: Number of minutes to look back

        Returns:
            List of quotes ordered by timestamp ASC
        """
        cursor = self.conn.cursor()
        cutoff = datetime.now() - timedelta(minutes=minutes)
        cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:00')

        cursor.execute("""
            SELECT timestamp, price, open, high, low, volume
            FROM nifty_quotes
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """, (cutoff_str,))

        history = []
        for row in cursor.fetchall():
            history.append({
                'timestamp': row[0],
                'price': row[1],
                'open': row[2],
                'high': row[3],
                'low': row[4],
                'volume': row[5]
            })

        return history

    def get_vix_latest(self) -> Optional[Dict]:
        """
        Get latest VIX quote.

        Returns:
            Dict with {vix_value, open, high, low, timestamp}
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT timestamp, vix_value, open, high, low
            FROM vix_quotes
            ORDER BY timestamp DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        if row:
            return {
                'timestamp': row[0],
                'vix_value': row[1],
                'open': row[2],
                'high': row[3],
                'low': row[4]
            }
        return None

    def get_vix_history(self, minutes: int = 30) -> List[Dict]:
        """
        Get VIX historical data (last N minutes).

        Args:
            minutes: Number of minutes to look back

        Returns:
            List of quotes ordered by timestamp ASC
        """
        cursor = self.conn.cursor()
        cutoff = datetime.now() - timedelta(minutes=minutes)
        cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:00')

        cursor.execute("""
            SELECT timestamp, vix_value, open, high, low
            FROM vix_quotes
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """, (cutoff_str,))

        history = []
        for row in cursor.fetchall():
            history.append({
                'timestamp': row[0],
                'vix_value': row[1],
                'open': row[2],
                'high': row[3],
                'low': row[4]
            })

        return history

    def get_metadata(self, key: str) -> Optional[str]:
        """
        Get metadata value.

        Args:
            key: Metadata key

        Returns:
            Value or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def is_data_fresh(self, max_age_minutes: int = 2) -> Tuple[bool, Optional[int]]:
        """
        Check if data is fresh (not stale).

        IMPORTANT: Services should call this before using data to ensure accuracy.

        Args:
            max_age_minutes: Maximum acceptable age in minutes (default: 2)

        Returns:
            Tuple of (is_fresh: bool, age_minutes: int or None)
            - is_fresh: True if data was updated within max_age_minutes
            - age_minutes: How old the data is, or None if no data
        """
        cursor = self.conn.cursor()

        # Check last stock update time
        cursor.execute("SELECT MAX(last_updated) FROM stock_quotes")
        row = cursor.fetchone()

        if not row or not row[0]:
            return False, None

        try:
            last_update = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            age = datetime.now() - last_update
            age_minutes = int(age.total_seconds() / 60)

            is_fresh = age_minutes <= max_age_minutes
            return is_fresh, age_minutes

        except Exception as e:
            logger.error(f"Error checking data freshness: {e}")
            return False, None

    def get_data_health(self) -> Dict:
        """
        Get comprehensive data health status.

        Returns:
            Dict with health metrics for monitoring
        """
        cursor = self.conn.cursor()

        health = {
            'is_healthy': False,
            'stock_data_age_minutes': None,
            'nifty_data_age_minutes': None,
            'vix_data_age_minutes': None,
            'collection_status': None,
            'last_collection_time': None,
            'health_alert': None,
            'unique_stocks': 0
        }

        try:
            # Get stock data age
            cursor.execute("SELECT MAX(last_updated) FROM stock_quotes")
            row = cursor.fetchone()
            if row and row[0]:
                last_update = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                health['stock_data_age_minutes'] = int((datetime.now() - last_update).total_seconds() / 60)

            # Get NIFTY data age
            cursor.execute("SELECT MAX(last_updated) FROM nifty_quotes")
            row = cursor.fetchone()
            if row and row[0]:
                last_update = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                health['nifty_data_age_minutes'] = int((datetime.now() - last_update).total_seconds() / 60)

            # Get VIX data age
            cursor.execute("SELECT MAX(last_updated) FROM vix_quotes")
            row = cursor.fetchone()
            if row and row[0]:
                last_update = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                health['vix_data_age_minutes'] = int((datetime.now() - last_update).total_seconds() / 60)

            # Get metadata
            health['collection_status'] = self.get_metadata('collection_status')
            health['last_collection_time'] = self.get_metadata('last_collection_time')
            health['health_alert'] = self.get_metadata('health_alert')

            # Get stock count
            cursor.execute("SELECT COUNT(DISTINCT symbol) FROM stock_quotes")
            health['unique_stocks'] = cursor.fetchone()[0]

            # Determine overall health (data < 3 minutes old and status is success)
            stock_fresh = health['stock_data_age_minutes'] is not None and health['stock_data_age_minutes'] <= 3
            status_ok = health['collection_status'] == 'success'
            health['is_healthy'] = stock_fresh and status_ok

        except Exception as e:
            logger.error(f"Error getting data health: {e}")

        return health

    # ============================================
    # MAINTENANCE OPERATIONS
    # ============================================

    def cleanup_old_data(self, days: int = 1):
        """
        Delete data older than N days to prevent database bloat.

        Args:
            days: Keep data from last N days
        """
        cursor = self.conn.cursor()
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:00')

        # Clean stock quotes
        cursor.execute("DELETE FROM stock_quotes WHERE timestamp < ?", (cutoff_str,))
        deleted_stocks = cursor.rowcount

        # Clean NIFTY quotes
        cursor.execute("DELETE FROM nifty_quotes WHERE timestamp < ?", (cutoff_str,))
        deleted_nifty = cursor.rowcount

        # Clean VIX quotes
        cursor.execute("DELETE FROM vix_quotes WHERE timestamp < ?", (cutoff_str,))
        deleted_vix = cursor.rowcount

        self.conn.commit()

        # Vacuum to reclaim space
        cursor.execute("VACUUM")

        logger.info(f"Cleanup complete: Deleted {deleted_stocks} stock quotes, "
                   f"{deleted_nifty} NIFTY quotes, {deleted_vix} VIX quotes older than {days} day(s)")

    def get_database_stats(self) -> Dict:
        """
        Get database statistics for monitoring.

        Returns:
            Dict with table counts, last update times, etc.
        """
        cursor = self.conn.cursor()

        # Count rows
        cursor.execute("SELECT COUNT(DISTINCT symbol) FROM stock_quotes")
        stock_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM nifty_quotes")
        nifty_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM vix_quotes")
        vix_count = cursor.fetchone()[0]

        # Last update times
        cursor.execute("SELECT MAX(last_updated) FROM stock_quotes")
        last_stock_update = cursor.fetchone()[0]

        cursor.execute("SELECT MAX(last_updated) FROM nifty_quotes")
        last_nifty_update = cursor.fetchone()[0]

        cursor.execute("SELECT MAX(last_updated) FROM vix_quotes")
        last_vix_update = cursor.fetchone()[0]

        return {
            'unique_stocks': stock_count,
            'nifty_records': nifty_count,
            'vix_records': vix_count,
            'last_stock_update': last_stock_update,
            'last_nifty_update': last_nifty_update,
            'last_vix_update': last_vix_update
        }

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")


# Singleton instances (separate for writer and reader)
_writer_instance = None
_reader_instance = None
_instance_lock = threading.Lock()


def get_central_db(mode: str = "reader") -> CentralQuoteDB:
    """
    Get singleton instance of central quote database.

    Args:
        mode: "writer" for central collector, "reader" for services (default)

    Returns:
        CentralQuoteDB instance optimized for the mode

    Usage:
        # For services (readers) - default
        db = get_central_db()

        # For central collector (writer)
        db = get_central_db(mode="writer")
    """
    global _writer_instance, _reader_instance

    with _instance_lock:
        if mode == "writer":
            if _writer_instance is None:
                _writer_instance = CentralQuoteDB(mode="writer")
            return _writer_instance
        else:
            if _reader_instance is None:
                _reader_instance = CentralQuoteDB(mode="reader")
            return _reader_instance


def get_central_db_writer() -> CentralQuoteDB:
    """
    Convenience function to get writer instance.
    Use this in central_data_collector.py

    Returns:
        CentralQuoteDB instance in writer mode
    """
    return get_central_db(mode="writer")


def get_central_db_reader() -> CentralQuoteDB:
    """
    Convenience function to get reader instance.
    Use this in all monitoring services.

    Returns:
        CentralQuoteDB instance in reader mode
    """
    return get_central_db(mode="reader")
