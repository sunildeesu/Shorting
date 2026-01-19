#!/usr/bin/env python3
"""
Central Quote Database - Unified Data Store
Stores real-time quotes for all F&O stocks, NIFTY, and VIX
All monitoring services read from this central database

Author: Claude Sonnet 4.5
Date: 2026-01-19
"""

import sqlite3
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import config

logger = logging.getLogger(__name__)


class CentralQuoteDB:
    """
    Centralized quote database for all monitoring services.
    Single source of truth for real-time market data.
    """

    def __init__(self, db_path: str = "data/central_quotes.db"):
        """
        Initialize central quote database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.conn = None

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # Initialize database
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with optimized settings"""
        try:
            self.conn = sqlite3.connect(
                self.db_path,
                timeout=config.SQLITE_TIMEOUT_SECONDS,
                check_same_thread=False  # Allow multi-threaded access
            )

            # Enable WAL mode for concurrent reads/writes
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            self.conn.execute("PRAGMA temp_store=MEMORY")
            self.conn.execute("PRAGMA busy_timeout=30000")  # 30 second busy timeout

            # Create tables
            self._create_tables()

            logger.info(f"Central quote database initialized: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def _create_tables(self):
        """Create database tables and indexes"""
        cursor = self.conn.cursor()

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

        self.conn.commit()
        logger.info("Database tables and indexes created successfully")

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


# Singleton instance
_db_instance = None


def get_central_db() -> CentralQuoteDB:
    """
    Get singleton instance of central quote database.

    Returns:
        CentralQuoteDB instance
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = CentralQuoteDB()
    return _db_instance
