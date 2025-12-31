import json
import os
import sqlite3
import shutil
from datetime import datetime
from typing import Dict, Optional, Tuple
import logging
import config

logger = logging.getLogger(__name__)

class PriceCache:
    """
    Manages price cache with last 7 snapshots for each stock (for 30-minute comparison).
    Also tracks volume data for volume spike detection.

    Structure: {
        "stock_symbol": {
            "current": {"price": float, "volume": int, "timestamp": str},
            "previous_1min": {"price": float, "volume": int, "timestamp": str},  # 1 min ago (for 1-min alerts)
            "previous": {"price": float, "volume": int, "timestamp": str},   # 5 min ago
            "previous2": {"price": float, "volume": int, "timestamp": str},  # 10 min ago
            "previous3": {"price": float, "volume": int, "timestamp": str},  # 15 min ago
            "previous4": {"price": float, "volume": int, "timestamp": str},  # 20 min ago
            "previous5": {"price": float, "volume": int, "timestamp": str},  # 25 min ago
            "previous6": {"price": float, "volume": int, "timestamp": str},  # 30 min ago
            "avg_daily_volume": int  # Average daily volume for liquidity filtering
        }
    }
    """

    def __init__(self):
        self.cache_file = config.PRICE_CACHE_FILE
        self.db_file = config.PRICE_CACHE_DB_FILE
        self.use_sqlite = config.ENABLE_SQLITE_CACHE
        self.db_conn = None

        # Initialize SQLite database
        if self.use_sqlite:
            self._init_database()

        self.cache = self._load_cache()

    def _init_database(self):
        """Initialize SQLite database with WAL mode and optimizations"""
        try:
            # Create data directory if needed
            os.makedirs(os.path.dirname(self.db_file), exist_ok=True)

            # Connect with check_same_thread=False (we control thread safety)
            self.db_conn = sqlite3.connect(
                self.db_file,
                check_same_thread=False,  # We'll handle thread safety
                timeout=10.0  # Wait up to 10s for locks
            )

            # Enable WAL mode (allows concurrent reads during writes)
            self.db_conn.execute("PRAGMA journal_mode=WAL")

            # Performance optimizations
            self.db_conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes, still safe with WAL
            self.db_conn.execute("PRAGMA cache_size=-32000")   # 32MB cache
            self.db_conn.execute("PRAGMA temp_store=MEMORY")   # Use RAM for temp tables

            # Create tables if not exist
            self._create_tables()

            logger.info(f"SQLite database initialized: {self.db_file}")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")
            self.db_conn = None
            self.use_sqlite = False

    def _create_tables(self):
        """Create SQLite tables and indexes if they don't exist"""
        try:
            # Create snapshots table
            self.db_conn.execute("""
                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    snapshot_type TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume INTEGER NOT NULL DEFAULT 0,
                    timestamp TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, snapshot_type)
                )
            """)

            # Create avg daily volumes table
            self.db_conn.execute("""
                CREATE TABLE IF NOT EXISTS avg_daily_volumes (
                    symbol TEXT PRIMARY KEY,
                    avg_daily_volume INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create schema version table
            self.db_conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Insert schema version if not exists
            self.db_conn.execute("""
                INSERT OR IGNORE INTO schema_version (version) VALUES (1)
            """)

            # Create indexes
            self.db_conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshots_symbol
                ON price_snapshots(symbol)
            """)

            self.db_conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_type
                ON price_snapshots(symbol, snapshot_type)
            """)

            self.db_conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
                ON price_snapshots(timestamp)
            """)

            # Commit schema changes
            self.db_conn.commit()

            logger.info("SQLite schema initialized")
        except Exception as e:
            logger.error(f"Failed to create SQLite tables: {e}")
            raise

    def _load_from_sqlite(self) -> Dict:
        """Load all data from SQLite into in-memory dict"""
        if not self.db_conn:
            logger.warning("SQLite not initialized")
            return {}

        cache = {}

        try:
            # Load all snapshots
            cursor = self.db_conn.execute("""
                SELECT symbol, snapshot_type, price, volume, timestamp
                FROM price_snapshots
                ORDER BY symbol, snapshot_type
            """)

            for row in cursor:
                symbol, snapshot_type, price, volume, timestamp = row

                # Initialize symbol dict if needed
                if symbol not in cache:
                    cache[symbol] = {
                        "current": None,
                        "previous_1min": None,
                        "previous": None,
                        "previous2": None,
                        "previous3": None,
                        "previous4": None,
                        "previous5": None,
                        "previous6": None
                    }

                # Populate snapshot
                cache[symbol][snapshot_type] = {
                    "price": price,
                    "volume": volume,
                    "timestamp": timestamp
                }

            # Load avg daily volumes
            cursor = self.db_conn.execute("""
                SELECT symbol, avg_daily_volume
                FROM avg_daily_volumes
            """)

            for row in cursor:
                symbol, avg_daily_volume = row

                # Initialize symbol dict if needed
                if symbol not in cache:
                    cache[symbol] = {
                        "current": None,
                        "previous_1min": None,
                        "previous": None,
                        "previous2": None,
                        "previous3": None,
                        "previous4": None,
                        "previous5": None,
                        "previous6": None
                    }

                cache[symbol]["avg_daily_volume"] = avg_daily_volume

            logger.info(f"Loaded {len(cache)} stocks from SQLite")
            return cache

        except sqlite3.Error as e:
            logger.error(f"Failed to load from SQLite: {e}")
            return {}

    def _save_to_sqlite(self):
        """Save in-memory cache to SQLite database using transactions"""
        if not self.db_conn:
            logger.warning("SQLite not initialized, skipping save")
            return

        try:
            # Start transaction
            self.db_conn.execute("BEGIN IMMEDIATE")

            # Clear existing data (full replace strategy - simpler than delta)
            self.db_conn.execute("DELETE FROM price_snapshots")
            self.db_conn.execute("DELETE FROM avg_daily_volumes")

            # Prepare snapshot rows for bulk insert
            snapshot_rows = []
            volume_rows = []

            for symbol, data in self.cache.items():
                # Collect all snapshots for this symbol
                for snapshot_type in ['current', 'previous_1min', 'previous',
                                      'previous2', 'previous3', 'previous4',
                                      'previous5', 'previous6']:
                    snapshot = data.get(snapshot_type)
                    if snapshot and isinstance(snapshot, dict):
                        snapshot_rows.append((
                            symbol,
                            snapshot_type,
                            snapshot.get('price', 0.0),
                            snapshot.get('volume', 0),
                            snapshot.get('timestamp', datetime.now().isoformat())
                        ))

                # Collect avg daily volume
                if 'avg_daily_volume' in data:
                    volume_rows.append((symbol, data['avg_daily_volume']))

            # Bulk insert (much faster than individual inserts)
            if snapshot_rows:
                self.db_conn.executemany("""
                    INSERT INTO price_snapshots
                    (symbol, snapshot_type, price, volume, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, snapshot_rows)

            if volume_rows:
                self.db_conn.executemany("""
                    INSERT INTO avg_daily_volumes (symbol, avg_daily_volume)
                    VALUES (?, ?)
                """, volume_rows)

            # Commit transaction (atomic)
            self.db_conn.commit()

        except sqlite3.Error as e:
            # Rollback on any error
            self.db_conn.rollback()
            logger.error(f"SQLite save failed: {e}")
            raise
        except Exception as e:
            self.db_conn.rollback()
            logger.error(f"Unexpected error during SQLite save: {e}")
            raise

    def _migrate_json_to_sqlite(self, json_cache: Dict):
        """
        One-time migration from JSON to SQLite.
        Called automatically on first run if SQLite is empty.
        """
        logger.info(f"Migrating {len(json_cache)} stocks from JSON to SQLite...")

        try:
            # Start transaction
            self.db_conn.execute("BEGIN TRANSACTION")

            migrated_stocks = 0
            migrated_snapshots = 0

            for symbol, data in json_cache.items():
                # Migrate snapshots
                for snapshot_type in ['current', 'previous_1min', 'previous',
                                      'previous2', 'previous3', 'previous4',
                                      'previous5', 'previous6']:
                    snapshot = data.get(snapshot_type)
                    if snapshot and isinstance(snapshot, dict):
                        self.db_conn.execute("""
                            INSERT OR REPLACE INTO price_snapshots
                            (symbol, snapshot_type, price, volume, timestamp)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            symbol,
                            snapshot_type,
                            snapshot.get('price', 0.0),
                            snapshot.get('volume', 0),
                            snapshot.get('timestamp', datetime.now().isoformat())
                        ))
                        migrated_snapshots += 1

                # Migrate avg_daily_volume
                if 'avg_daily_volume' in data:
                    self.db_conn.execute("""
                        INSERT OR REPLACE INTO avg_daily_volumes
                        (symbol, avg_daily_volume)
                        VALUES (?, ?)
                    """, (symbol, data['avg_daily_volume']))

                migrated_stocks += 1

            # Commit transaction
            self.db_conn.commit()

            logger.info(f"Migration complete: {migrated_stocks} stocks, "
                       f"{migrated_snapshots} snapshots")

            # Create JSON backup after successful migration
            backup_file = self.cache_file + ".pre_sqlite_backup"
            shutil.copy2(self.cache_file, backup_file)
            logger.info(f"JSON backup created: {backup_file}")

        except Exception as e:
            self.db_conn.rollback()
            logger.error(f"Migration failed: {e}")
            raise

    def _load_cache(self) -> Dict:
        """Load cache from SQLite, fallback to JSON, migrate if needed"""

        # Try SQLite first
        if self.use_sqlite and self.db_conn:
            try:
                cache = self._load_from_sqlite()
                if cache:
                    logger.info(f"Loaded {len(cache)} stocks from SQLite")
                    return cache
            except Exception as e:
                logger.warning(f"Failed to load from SQLite: {e}")

        # Fallback to JSON
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    cache = json.load(f)
                logger.info(f"Loaded {len(cache)} stocks from JSON")

                # Auto-migrate JSON to SQLite (one-time)
                if self.use_sqlite and self.db_conn and cache:
                    logger.info("Auto-migrating JSON data to SQLite...")
                    self._migrate_json_to_sqlite(cache)

                return cache
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load from JSON: {e}")

        # Empty cache
        logger.info("Starting with empty cache")
        return {}

    def _save_cache(self):
        """Save cache to storage (SQLite primary, JSON backup)"""

        # Save to SQLite (primary)
        if self.use_sqlite and self.db_conn:
            try:
                self._save_to_sqlite()
            except Exception as e:
                logger.error(f"SQLite save failed: {e}")
                # Continue to JSON backup

        # Save to JSON (backup - can be disabled after SQLite is proven stable)
        if config.ENABLE_JSON_BACKUP:
            try:
                os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
                with open(self.cache_file, 'w') as f:
                    json.dump(self.cache, f, indent=2)
            except Exception as e:
                logger.error(f"JSON save failed: {e}")

    def _is_same_day(self, timestamp1: str, timestamp2: str) -> bool:
        """
        Check if two timestamps are from the same calendar day

        Args:
            timestamp1: ISO format timestamp
            timestamp2: ISO format timestamp

        Returns:
            True if both timestamps are from the same day, False otherwise
        """
        try:
            dt1 = datetime.fromisoformat(timestamp1)
            dt2 = datetime.fromisoformat(timestamp2)
            return dt1.date() == dt2.date()
        except (ValueError, TypeError, AttributeError):
            # If parsing fails, assume different days to be safe
            return False

    def update_price(self, symbol: str, price: float, volume: int = 0, timestamp: str = None):
        """
        Update price and volume for a stock. Shifts all 7 snapshots.

        Args:
            symbol: Stock symbol
            price: Current price
            volume: Current trading volume
            timestamp: ISO format timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        if symbol not in self.cache:
            # First time seeing this stock
            self.cache[symbol] = {
                "current": {"price": price, "volume": volume, "timestamp": timestamp},
                "previous": None,
                "previous2": None,
                "previous3": None,
                "previous4": None,
                "previous5": None,
                "previous6": None
            }
        else:
            # Shift all snapshots: prev6 <- prev5 <- ... <- prev <- current <- new
            self.cache[symbol]["previous6"] = self.cache[symbol].get("previous5")
            self.cache[symbol]["previous5"] = self.cache[symbol].get("previous4")
            self.cache[symbol]["previous4"] = self.cache[symbol].get("previous3")
            self.cache[symbol]["previous3"] = self.cache[symbol].get("previous2")
            self.cache[symbol]["previous2"] = self.cache[symbol].get("previous")
            self.cache[symbol]["previous"] = self.cache[symbol]["current"]
            self.cache[symbol]["current"] = {"price": price, "volume": volume, "timestamp": timestamp}

        self._save_cache()

    def update_price_1min(self, symbol: str, price: float, volume: int = 0, timestamp: str = None):
        """
        Update price and volume for 1-minute monitoring (separate from 5-min updates).
        This method only updates current and previous_1min snapshots.
        Does NOT shift the 5-minute snapshots (previous, previous2, etc.)

        Args:
            symbol: Stock symbol
            price: Current price
            volume: Current trading volume
            timestamp: ISO format timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        if symbol not in self.cache:
            # First time seeing this stock - initialize all fields
            self.cache[symbol] = {
                "current": {"price": price, "volume": volume, "timestamp": timestamp},
                "previous_1min": None,
                "previous": None,
                "previous2": None,
                "previous3": None,
                "previous4": None,
                "previous5": None,
                "previous6": None
            }
        else:
            # Save current as previous_1min, then update current
            self.cache[symbol]["previous_1min"] = self.cache[symbol]["current"]
            self.cache[symbol]["current"] = {"price": price, "volume": volume, "timestamp": timestamp}

        self._save_cache()

    def get_price_1min_ago(self, symbol: str) -> Optional[float]:
        """
        Get price from 1 minute ago for 1-min alert detection.
        Only returns price if it's from the same day AND within 2 minutes.

        Returns:
            Price from 1 minute ago, or None if not available
        """
        if symbol not in self.cache:
            return None

        current = self.cache[symbol].get("current")
        previous_1min = self.cache[symbol].get("previous_1min")

        if not current or not previous_1min:
            return None

        # Validate timestamps: must be same day AND within 2 minutes
        current_timestamp = current.get("timestamp")
        previous_timestamp = previous_1min.get("timestamp")

        if current_timestamp and previous_timestamp:
            # Check if same day
            if not self._is_same_day(current_timestamp, previous_timestamp):
                logger.debug(f"{symbol}: Skipping 1-min comparison - timestamps from different days")
                return None

            # Check if within 2 minutes (allowing 1 min tolerance)
            try:
                from datetime import datetime
                current_dt = datetime.fromisoformat(current_timestamp)
                previous_dt = datetime.fromisoformat(previous_timestamp)
                time_diff_seconds = (current_dt - previous_dt).total_seconds()

                if time_diff_seconds > 120:  # > 2 minutes
                    logger.debug(f"{symbol}: Skipping 1-min comparison - timestamps {time_diff_seconds:.1f}s apart (> 120s threshold)")
                    return None
                elif time_diff_seconds < 30:  # < 30 seconds
                    logger.debug(f"{symbol}: Skipping 1-min comparison - timestamps {time_diff_seconds:.1f}s apart (< 30s threshold)")
                    return None

                return previous_1min.get("price")
            except Exception as e:
                logger.warning(f"{symbol}: Error parsing timestamps for 1-min comparison: {e}")
                return None

        return None

    def get_prices_1min(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current and 1-minute-ago prices for a stock.
        Only returns historical price if it's from the same day as current price.

        Returns:
            Tuple of (current_price, price_1min_ago) or (None, None) if not found
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous_1min = self.cache[symbol].get("previous_1min")

        current_price = current.get("price") if current else None

        # Validate same-day timestamps
        if current and previous_1min:
            current_timestamp = current.get("timestamp")
            previous_timestamp = previous_1min.get("timestamp")

            if current_timestamp and previous_timestamp:
                if self._is_same_day(current_timestamp, previous_timestamp):
                    previous_price = previous_1min.get("price")
                else:
                    logger.debug(f"{symbol}: Skipping 1-min comparison - timestamps from different days")
                    previous_price = None
            else:
                previous_price = previous_1min.get("price") if previous_1min else None
        else:
            previous_price = None

        return current_price, previous_price

    def get_volume_data_1min(self, symbol: str) -> Dict:
        """
        Get volume data for 1-minute comparison.
        Compares current volume with volume from 1 minute ago.
        Only compares volumes from the same day (prevents cross-day comparisons).

        Returns:
            Dict with current_volume, previous_volume, avg_volume, volume_change, and volume_spike flag
        """
        if symbol not in self.cache:
            return {
                "current_volume": 0,
                "previous_volume": 0,
                "avg_volume": 0,
                "volume_change": 0,
                "volume_spike": False
            }

        current = self.cache[symbol].get("current")
        previous_1min = self.cache[symbol].get("previous_1min")

        current_volume = current.get("volume", 0) if current else 0
        previous_volume = 0

        # Validate same-day timestamps
        if current and previous_1min:
            current_timestamp = current.get("timestamp")
            previous_timestamp = previous_1min.get("timestamp")

            if current_timestamp and previous_timestamp:
                if self._is_same_day(current_timestamp, previous_timestamp):
                    previous_volume = previous_1min.get("volume", 0)
                else:
                    logger.debug(f"{symbol}: Skipping 1-min volume comparison - timestamps from different days")

        # Calculate volume change
        volume_change = current_volume - previous_volume if previous_volume > 0 else 0

        # Volume spike if current > 3.0x previous (1-min uses stricter multiplier)
        volume_spike = False
        if previous_volume > 0:
            volume_spike = current_volume > (previous_volume * config.VOLUME_SPIKE_MULTIPLIER_1MIN)

        return {
            "current_volume": current_volume,
            "previous_volume": previous_volume,
            "avg_volume": previous_volume,  # For compatibility with alert formatting
            "volume_change": volume_change,
            "volume_spike": volume_spike
        }

    def set_avg_daily_volume(self, symbol: str, avg_daily_volume: int):
        """
        Set average daily volume for a stock (for liquidity filtering).

        Args:
            symbol: Stock symbol
            avg_daily_volume: Average daily volume
        """
        if symbol not in self.cache:
            self.cache[symbol] = {
                "current": None,
                "previous_1min": None,
                "previous": None,
                "previous2": None,
                "previous3": None,
                "previous4": None,
                "previous5": None,
                "previous6": None
            }

        self.cache[symbol]["avg_daily_volume"] = avg_daily_volume
        self._save_cache()

    def get_avg_daily_volume(self, symbol: str) -> Optional[int]:
        """
        Get average daily volume for a stock (for liquidity filtering).

        Returns:
            Average daily volume, or None if not available
        """
        if symbol not in self.cache:
            return None

        return self.cache[symbol].get("avg_daily_volume")

    def get_prices(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current and 10-minute-ago prices for a stock
        Only returns historical price if it's from the same day AND within 12 minutes

        Returns:
            Tuple of (current_price, price_10min_ago) or (None, None) if not found
            Returns (current_price, None) if timestamps are too far apart
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous2 = self.cache[symbol].get("previous2")  # 10 minutes ago

        current_price = current["price"] if current else None

        # Validate timestamps: must be same day AND within 12 minutes
        if current and previous2:
            current_timestamp = current.get("timestamp")
            previous2_timestamp = previous2.get("timestamp")

            if current_timestamp and previous2_timestamp:
                # Check if same day
                if not self._is_same_day(current_timestamp, previous2_timestamp):
                    logger.debug(f"{symbol}: Skipping 10-min comparison - timestamps from different days")
                    return current_price, None

                # Check if within 12 minutes (allowing 2 min tolerance)
                try:
                    from datetime import datetime
                    current_dt = datetime.fromisoformat(current_timestamp)
                    previous2_dt = datetime.fromisoformat(previous2_timestamp)
                    time_diff_minutes = (current_dt - previous2_dt).total_seconds() / 60

                    if time_diff_minutes > 12:
                        logger.debug(f"{symbol}: Skipping 10-min comparison - timestamps {time_diff_minutes:.1f} min apart (> 12 min threshold)")
                        return current_price, None
                    elif time_diff_minutes < 8:
                        logger.debug(f"{symbol}: Skipping 10-min comparison - timestamps {time_diff_minutes:.1f} min apart (< 8 min threshold)")
                        return current_price, None

                    previous2_price = previous2["price"]
                except Exception as e:
                    logger.warning(f"{symbol}: Error parsing timestamps for 10-min comparison: {e}")
                    previous2_price = None
            else:
                previous2_price = previous2["price"] if previous2 else None
        else:
            previous2_price = None

        return current_price, previous2_price

    def get_prices_5min(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current and 5-minute-ago prices for a stock (rapid detection)
        Only returns historical price if it's from the same day AND within 7 minutes

        Returns:
            Tuple of (current_price, price_5min_ago) or (None, None) if not found
            Returns (current_price, None) if timestamps are too far apart
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous = self.cache[symbol].get("previous")  # 5 minutes ago

        current_price = current["price"] if current else None

        # Validate timestamps: must be same day AND within 7 minutes
        if current and previous:
            current_timestamp = current.get("timestamp")
            previous_timestamp = previous.get("timestamp")

            if current_timestamp and previous_timestamp:
                # Check if same day
                if not self._is_same_day(current_timestamp, previous_timestamp):
                    logger.debug(f"{symbol}: Skipping 5-min comparison - timestamps from different days")
                    return current_price, None

                # Check if within 7 minutes (allowing 2 min tolerance for gaps)
                try:
                    from datetime import datetime
                    current_dt = datetime.fromisoformat(current_timestamp)
                    previous_dt = datetime.fromisoformat(previous_timestamp)
                    time_diff_minutes = (current_dt - previous_dt).total_seconds() / 60

                    if time_diff_minutes > 7:
                        logger.debug(f"{symbol}: Skipping 5-min comparison - timestamps {time_diff_minutes:.1f} min apart (> 7 min threshold)")
                        return current_price, None
                    elif time_diff_minutes < 3:
                        logger.debug(f"{symbol}: Skipping 5-min comparison - timestamps {time_diff_minutes:.1f} min apart (< 3 min threshold)")
                        return current_price, None

                    previous_price = previous["price"]
                except Exception as e:
                    logger.warning(f"{symbol}: Error parsing timestamps for 5-min comparison: {e}")
                    previous_price = None
            else:
                previous_price = previous["price"] if previous else None
        else:
            previous_price = None

        return current_price, previous_price

    def get_price_30min(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get current and 30-minute-ago prices for a stock
        Only returns historical price if it's from the same day AND within 35 minutes

        Returns:
            Tuple of (current_price, price_30min_ago) or (None, None) if not found
            Returns (current_price, None) if timestamps are too far apart
        """
        if symbol not in self.cache:
            return None, None

        current = self.cache[symbol].get("current")
        previous6 = self.cache[symbol].get("previous6")  # 30 minutes ago

        current_price = current["price"] if current else None

        # Validate timestamps: must be same day AND within 35 minutes
        if current and previous6:
            current_timestamp = current.get("timestamp")
            previous6_timestamp = previous6.get("timestamp")

            if current_timestamp and previous6_timestamp:
                # Check if same day
                if not self._is_same_day(current_timestamp, previous6_timestamp):
                    logger.debug(f"{symbol}: Skipping 30-min comparison - timestamps from different days")
                    return current_price, None

                # Check if within 35 minutes (allowing 5 min tolerance)
                try:
                    from datetime import datetime
                    current_dt = datetime.fromisoformat(current_timestamp)
                    previous6_dt = datetime.fromisoformat(previous6_timestamp)
                    time_diff_minutes = (current_dt - previous6_dt).total_seconds() / 60

                    if time_diff_minutes > 35:
                        logger.debug(f"{symbol}: Skipping 30-min comparison - timestamps {time_diff_minutes:.1f} min apart (> 35 min threshold)")
                        return current_price, None
                    elif time_diff_minutes < 25:
                        logger.debug(f"{symbol}: Skipping 30-min comparison - timestamps {time_diff_minutes:.1f} min apart (< 25 min threshold)")
                        return current_price, None

                    previous6_price = previous6["price"]
                except Exception as e:
                    logger.warning(f"{symbol}: Error parsing timestamps for 30-min comparison: {e}")
                    previous6_price = None
            else:
                previous6_price = previous6["price"] if previous6 else None
        else:
            previous6_price = None

        return current_price, previous6_price

    def get_volume_data(self, symbol: str) -> Dict:
        """
        Get volume data for a stock (DEPRECATED - use timeframe-specific methods)
        This method is kept for backward compatibility but returns averaged data

        Returns:
            Dict with current_volume, avg_volume, and volume_spike flag
        """
        if symbol not in self.cache:
            return {"current_volume": 0, "avg_volume": 0, "volume_spike": False}

        # Get all available volumes
        volumes = []
        for key in ["previous6", "previous5", "previous4", "previous3", "previous2", "previous"]:
            snapshot = self.cache[symbol].get(key)
            if snapshot and "volume" in snapshot:
                volumes.append(snapshot["volume"])

        current = self.cache[symbol].get("current")
        current_volume = current.get("volume", 0) if current else 0

        # Calculate average from historical volumes
        avg_volume = sum(volumes) / len(volumes) if volumes else 0

        # Volume spike if current > 3x average (and we have enough data)
        volume_spike = False
        if len(volumes) >= 3 and avg_volume > 0:
            volume_spike = current_volume > (avg_volume * 3)

        return {
            "current_volume": current_volume,
            "avg_volume": avg_volume,
            "volume_spike": volume_spike,
            "historical_count": len(volumes)
        }

    def get_volume_data_5min(self, symbol: str) -> Dict:
        """
        Get volume data for 5-minute comparison
        Compares current volume with volume from 5 minutes ago (previous)
        Only compares volumes from the same day (prevents cross-day comparisons)

        Returns:
            Dict with current_volume, previous_volume, volume_change, and volume_spike flag
        """
        if symbol not in self.cache:
            return {
                "current_volume": 0,
                "previous_volume": 0,
                "avg_volume": 0,
                "volume_change": 0,
                "volume_spike": False
            }

        current = self.cache[symbol].get("current")
        previous = self.cache[symbol].get("previous")  # 5 minutes ago

        current_volume = current.get("volume", 0) if current else 0
        previous_volume = 0

        # Validate same-day timestamps to prevent cross-day volume comparisons
        if current and previous:
            current_timestamp = current.get("timestamp")
            previous_timestamp = previous.get("timestamp")

            if current_timestamp and previous_timestamp:
                if self._is_same_day(current_timestamp, previous_timestamp):
                    previous_volume = previous.get("volume", 0)
                else:
                    logger.debug(f"{symbol}: Skipping 5-min volume comparison - timestamps from different days")

        # Calculate volume change
        volume_change = current_volume - previous_volume if previous_volume > 0 else 0

        # Volume spike if current > 2.5x previous (5-min comparison uses lower multiplier)
        volume_spike = False
        if previous_volume > 0:
            volume_spike = current_volume > (previous_volume * 2.5)

        return {
            "current_volume": current_volume,
            "previous_volume": previous_volume,
            "avg_volume": previous_volume,  # For compatibility with alert formatting
            "volume_change": volume_change,
            "volume_spike": volume_spike
        }

    def get_volume_data_10min(self, symbol: str) -> Dict:
        """
        Get volume data for 10-minute comparison
        Compares current volume with average of previous 2 snapshots (10 min window)
        Only compares volumes from the same day (prevents cross-day comparisons)

        Returns:
            Dict with current_volume, avg_volume, volume_change, and volume_spike flag
        """
        if symbol not in self.cache:
            return {
                "current_volume": 0,
                "previous_volume": 0,
                "avg_volume": 0,
                "volume_change": 0,
                "volume_spike": False
            }

        current = self.cache[symbol].get("current")
        previous = self.cache[symbol].get("previous")    # 5 min ago
        previous2 = self.cache[symbol].get("previous2")  # 10 min ago

        current_volume = current.get("volume", 0) if current else 0

        # Calculate average from previous 2 snapshots (5-min and 10-min ago)
        # Only include volumes from the same day as current
        volumes = []
        if current and previous and "volume" in previous:
            current_timestamp = current.get("timestamp")
            previous_timestamp = previous.get("timestamp")
            if current_timestamp and previous_timestamp:
                if self._is_same_day(current_timestamp, previous_timestamp):
                    volumes.append(previous["volume"])
                else:
                    logger.debug(f"{symbol}: Skipping previous volume - different day")

        if current and previous2 and "volume" in previous2:
            current_timestamp = current.get("timestamp")
            previous2_timestamp = previous2.get("timestamp")
            if current_timestamp and previous2_timestamp:
                if self._is_same_day(current_timestamp, previous2_timestamp):
                    volumes.append(previous2["volume"])
                else:
                    logger.debug(f"{symbol}: Skipping previous2 volume - different day")

        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        volume_change = current_volume - avg_volume if avg_volume > 0 else 0

        # Volume spike if current > 2.5x average (10-min uses 2.5x)
        volume_spike = False
        if len(volumes) >= 2 and avg_volume > 0:
            volume_spike = current_volume > (avg_volume * 2.5)

        return {
            "current_volume": current_volume,
            "previous_volume": volumes[0] if volumes else 0,
            "avg_volume": avg_volume,
            "volume_change": volume_change,
            "volume_spike": volume_spike
        }

    def get_volume_data_30min(self, symbol: str) -> Dict:
        """
        Get volume data for 30-minute comparison
        Compares current volume with average of previous 6 snapshots (30 min window)
        Only compares volumes from the same day (prevents cross-day comparisons)

        Returns:
            Dict with current_volume, avg_volume, volume_change, and volume_spike flag
        """
        if symbol not in self.cache:
            return {
                "current_volume": 0,
                "previous_volume": 0,
                "avg_volume": 0,
                "volume_change": 0,
                "volume_spike": False
            }

        current = self.cache[symbol].get("current")
        current_volume = current.get("volume", 0) if current else 0

        # Get all available volumes from last 30 minutes
        # Only include volumes from the same day as current
        volumes = []
        for key in ["previous", "previous2", "previous3", "previous4", "previous5", "previous6"]:
            snapshot = self.cache[symbol].get(key)
            if current and snapshot and "volume" in snapshot:
                current_timestamp = current.get("timestamp")
                snapshot_timestamp = snapshot.get("timestamp")
                if current_timestamp and snapshot_timestamp:
                    if self._is_same_day(current_timestamp, snapshot_timestamp):
                        volumes.append(snapshot["volume"])
                    else:
                        logger.debug(f"{symbol}: Skipping {key} volume - different day")

        # Calculate average from historical volumes
        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        volume_change = current_volume - avg_volume if avg_volume > 0 else 0

        # Volume spike if current > 2.5x average (30-min uses 2.5x for consistency)
        volume_spike = False
        if len(volumes) >= 3 and avg_volume > 0:
            volume_spike = current_volume > (avg_volume * 2.5)

        return {
            "current_volume": current_volume,
            "previous_volume": volumes[0] if volumes else 0,
            "avg_volume": avg_volume,
            "volume_change": volume_change,
            "volume_spike": volume_spike
        }

    def has_previous_price(self, symbol: str) -> bool:
        """Check if we have a 10-minute-ago price to compare against"""
        if symbol not in self.cache:
            return False
        return self.cache[symbol].get("previous2") is not None

    def has_30min_price(self, symbol: str) -> bool:
        """Check if we have a 30-minute-ago price to compare against"""
        if symbol not in self.cache:
            return False
        return self.cache[symbol].get("previous6") is not None

    def clear_cache(self):
        """Clear all cached data"""
        self.cache = {}
        self._save_cache()
