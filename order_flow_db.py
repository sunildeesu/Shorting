#!/usr/bin/env python3
"""
Order Flow Database - SQLite store for real-time market depth and tick data.

CONCURRENCY DESIGN (mirrors central_quote_db.py):
- Writer mode: Single persistent connection (order_flow_monitor.py process)
- Reader mode: Thread-local connections for any additional readers
- WAL mode allows multiple concurrent readers + 1 writer

Tables:
- tick_snapshots: Raw WebSocket ticks (ring buffer, last 10 minutes)
- flow_metrics:   Computed order flow metrics per stock (updated every 30s)
- alert_history:  Alert cooldown tracking
- metadata:       Collector health and diagnostics
"""

import sqlite3
import logging
import os
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)

_thread_local = threading.local()


class OrderFlowDB:
    """
    SQLite WAL-mode database for order flow tick data and metrics.

    Writer mode: used by order_flow_monitor.py (owns the WebSocket writer thread).
    Reader mode: available for any other service that wants to read metrics.
    """

    def __init__(self, db_path: str = None, mode: str = "reader"):
        self.db_path = db_path or config.ORDER_FLOW_DB_FILE
        self.mode = mode
        self._writer_conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_database()

    # --------------------------------------------------------
    # Connection management
    # --------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        if self.mode == "writer":
            if self._writer_conn is None:
                self._writer_conn = self._create_writer_connection()
            return self._writer_conn
        else:
            if not hasattr(_thread_local, 'of_conn') or _thread_local.of_conn is None:
                _thread_local.of_conn = self._create_reader_connection()
            return _thread_local.of_conn

    def _create_writer_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        conn.row_factory = sqlite3.Row
        logger.info(f"OrderFlowDB writer connection: {self.db_path}")
        return conn

    def _create_reader_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-32000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA query_only=ON")
        conn.row_factory = sqlite3.Row
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_connection()

    # --------------------------------------------------------
    # Schema initialisation
    # --------------------------------------------------------

    def _init_database(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        self._create_tables(conn)
        conn.close()
        logger.info(f"OrderFlowDB initialised: {self.db_path} (mode={self.mode})")

    def _create_tables(self, conn: sqlite3.Connection):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tick_snapshots (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol            TEXT    NOT NULL,
                instrument_token  INTEGER NOT NULL,
                ts                TEXT    NOT NULL,
                asset_type        TEXT    DEFAULT 'CASH',  -- 'CASH' or 'FUT'
                last_price        REAL    DEFAULT 0,
                last_quantity     INTEGER DEFAULT 0,
                volume            INTEGER DEFAULT 0,
                buy_quantity      INTEGER DEFAULT 0,
                sell_quantity     INTEGER DEFAULT 0,
                best_bid          REAL    DEFAULT 0,
                best_ask          REAL    DEFAULT 0,
                bid_depth_total   INTEGER DEFAULT 0,
                ask_depth_total   INTEGER DEFAULT 0,
                bid_l1_qty        INTEGER DEFAULT 0,
                bid_l2_qty        INTEGER DEFAULT 0,
                bid_l3_qty        INTEGER DEFAULT 0,
                bid_l4_qty        INTEGER DEFAULT 0,
                bid_l5_qty        INTEGER DEFAULT 0,
                ask_l1_qty        INTEGER DEFAULT 0,
                ask_l2_qty        INTEGER DEFAULT 0,
                ask_l3_qty        INTEGER DEFAULT 0,
                ask_l4_qty        INTEGER DEFAULT 0,
                ask_l5_qty        INTEGER DEFAULT 0,
                bid_l1_price      REAL    DEFAULT 0,
                ask_l1_price      REAL    DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_tick_symbol_ts
                ON tick_snapshots(symbol, ts DESC);

            CREATE INDEX IF NOT EXISTS idx_tick_ts
                ON tick_snapshots(ts DESC);

            CREATE TABLE IF NOT EXISTS flow_metrics (
                symbol              TEXT PRIMARY KEY,
                ts                  TEXT,
                bai                 REAL DEFAULT 0,
                bai_prev            REAL DEFAULT 0,   -- BAI from previous cycle (for delta)
                bai_delta           REAL DEFAULT 0,   -- BAI(now) - BAI(prev): rate of change
                depth_ratio         REAL DEFAULT 0,
                volume_delta        INTEGER DEFAULT 0,
                buy_volume          INTEGER DEFAULT 0,
                sell_volume         INTEGER DEFAULT 0,
                cum_delta_pct       REAL DEFAULT 0,    -- (buy_vol_5m - sell_vol_5m) / (buy+sell): -1..+1, normalised across all stocks
                bid_l1_shrink_pct   REAL DEFAULT 0,   -- % drop in L1 bid qty vs window start
                tick_velocity       REAL DEFAULT 0,   -- avg |price change| per tick (momentum)
                price_change_pct    REAL DEFAULT 0,
                has_bid_wall        INTEGER DEFAULT 0,
                has_ask_wall        INTEGER DEFAULT 0,
                wall_ratio          REAL DEFAULT 0,
                wall_side           TEXT DEFAULT '',
                wall_price          REAL DEFAULT 0,
                wall_qty            INTEGER DEFAULT 0,
                absorption_signal   TEXT DEFAULT '',
                absorption_strength REAL DEFAULT 0,
                last_price          REAL DEFAULT 0,
                tick_count          INTEGER DEFAULT 0,
                -- Futures order flow (near-month contract, same underlying)
                fut_bai             REAL DEFAULT 0,
                fut_bai_prev        REAL DEFAULT 0,
                fut_bai_delta       REAL DEFAULT 0,
                fut_cum_delta_pct   REAL DEFAULT 0,
                fut_tick_velocity   REAL DEFAULT 0,
                fut_last_price      REAL DEFAULT 0,
                fut_tick_count      INTEGER DEFAULT 0,
                basis_pct           REAL DEFAULT 0   -- (fut_price - cash_price) / cash_price * 100
            );

            CREATE TABLE IF NOT EXISTS alert_history (
                symbol      TEXT NOT NULL,
                alert_type  TEXT NOT NULL,
                fired_at    TEXT NOT NULL,
                PRIMARY KEY (symbol, alert_type)
            );

            CREATE TABLE IF NOT EXISTS metadata (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.commit()

    # --------------------------------------------------------
    # WRITE operations (writer process only)
    # --------------------------------------------------------

    def store_tick_batch(self, ticks: List[dict]) -> None:
        """Bulk insert parsed ticks. Called from writer thread every 2 seconds."""
        if not ticks:
            return
        with self._lock:
            rows = []
            for t in ticks:
                rows.append((
                    t['symbol'], t['token'], t['ts'],
                    t.get('asset_type', 'CASH'),
                    t['last_price'], t['last_quantity'], t['volume'],
                    t['buy_quantity'], t['sell_quantity'],
                    t['best_bid'], t['best_ask'],
                    t['bid_depth_total'], t['ask_depth_total'],
                    t['bid_l1_qty'], t['bid_l2_qty'], t['bid_l3_qty'],
                    t['bid_l4_qty'], t['bid_l5_qty'],
                    t['ask_l1_qty'], t['ask_l2_qty'], t['ask_l3_qty'],
                    t['ask_l4_qty'], t['ask_l5_qty'],
                    t['bid_l1_price'], t['ask_l1_price'],
                ))
            self.conn.executemany("""
                INSERT INTO tick_snapshots (
                    symbol, instrument_token, ts, asset_type,
                    last_price, last_quantity, volume,
                    buy_quantity, sell_quantity,
                    best_bid, best_ask,
                    bid_depth_total, ask_depth_total,
                    bid_l1_qty, bid_l2_qty, bid_l3_qty, bid_l4_qty, bid_l5_qty,
                    ask_l1_qty, ask_l2_qty, ask_l3_qty, ask_l4_qty, ask_l5_qty,
                    bid_l1_price, ask_l1_price
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows)
            self.conn.commit()

    def upsert_flow_metrics_batch(self, metrics_list: List[dict]) -> None:
        """Bulk upsert computed metrics for all stocks."""
        if not metrics_list:
            return
        with self._lock:
            rows = []
            for m in metrics_list:
                rows.append((
                    m['symbol'], m['ts'],
                    m['bai'], m.get('bai_prev', 0), m.get('bai_delta', 0),
                    m['depth_ratio'],
                    m['volume_delta'], m['buy_volume'], m['sell_volume'],
                    m.get('cum_delta_pct', 0),
                    m.get('bid_l1_shrink_pct', 0), m.get('tick_velocity', 0),
                    m['price_change_pct'],
                    int(m['has_bid_wall']), int(m['has_ask_wall']),
                    m['wall_ratio'], m['wall_side'], m['wall_price'], m['wall_qty'],
                    m['absorption_signal'], m['absorption_strength'],
                    m['last_price'], m['tick_count'],
                    m.get('fut_bai', 0), m.get('fut_bai_prev', 0), m.get('fut_bai_delta', 0),
                    m.get('fut_cum_delta_pct', 0), m.get('fut_tick_velocity', 0),
                    m.get('fut_last_price', 0), m.get('fut_tick_count', 0),
                    m.get('basis_pct', 0),
                ))
            self.conn.executemany("""
                INSERT OR REPLACE INTO flow_metrics (
                    symbol, ts, bai, bai_prev, bai_delta, depth_ratio,
                    volume_delta, buy_volume, sell_volume,
                    cum_delta_pct, bid_l1_shrink_pct, tick_velocity,
                    price_change_pct,
                    has_bid_wall, has_ask_wall,
                    wall_ratio, wall_side, wall_price, wall_qty,
                    absorption_signal, absorption_strength,
                    last_price, tick_count,
                    fut_bai, fut_bai_prev, fut_bai_delta,
                    fut_cum_delta_pct, fut_tick_velocity,
                    fut_last_price, fut_tick_count,
                    basis_pct
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows)
            self.conn.commit()

    def record_alert(self, symbol: str, alert_type: str) -> None:
        """Record that an alert was fired (for cooldown tracking)."""
        with self._lock:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.conn.execute("""
                INSERT OR REPLACE INTO alert_history (symbol, alert_type, fired_at)
                VALUES (?, ?, ?)
            """, (symbol, alert_type, now_str))
            self.conn.commit()

    def cleanup_old_ticks(self, minutes: int = None) -> int:
        """Delete tick_snapshots older than N minutes. Returns deleted row count."""
        minutes = minutes or config.ORDER_FLOW_TICK_RETENTION_MINUTES
        with self._lock:
            cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
            cursor = self.conn.execute(
                "DELETE FROM tick_snapshots WHERE ts < ?", (cutoff,)
            )
            self.conn.commit()
            return cursor.rowcount

    def update_metadata(self, key: str, value: str) -> None:
        with self._lock:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.conn.execute("""
                INSERT OR REPLACE INTO metadata (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, now_str))
            self.conn.commit()

    # --------------------------------------------------------
    # READ operations
    # --------------------------------------------------------

    def get_all_ticks_since(self, seconds: int = None) -> Dict[str, Dict[str, List[dict]]]:
        """
        Return ticks for ALL symbols in last N seconds in a single query.
        Returns {symbol: {'CASH': [tick_dict,...], 'FUT': [tick_dict,...]}} ordered by ts ASC.
        """
        seconds = seconds or config.ORDER_FLOW_ANALYSIS_WINDOW
        cutoff = (datetime.now() - timedelta(seconds=seconds)).strftime('%Y-%m-%d %H:%M:%S')
        cursor = self.conn.execute("""
            SELECT symbol, asset_type, ts, last_price, last_quantity, volume,
                   buy_quantity, sell_quantity,
                   best_bid, best_ask,
                   bid_depth_total, ask_depth_total,
                   bid_l1_qty, bid_l2_qty, bid_l3_qty, bid_l4_qty, bid_l5_qty,
                   ask_l1_qty, ask_l2_qty, ask_l3_qty, ask_l4_qty, ask_l5_qty,
                   bid_l1_price, ask_l1_price
            FROM tick_snapshots
            WHERE ts >= ?
            ORDER BY symbol, asset_type, ts ASC
        """, (cutoff,))

        result: Dict[str, Dict[str, List[dict]]] = {}
        for row in cursor.fetchall():
            sym, asset_type = row[0], row[1]
            if sym not in result:
                result[sym] = {'CASH': [], 'FUT': []}
            result[sym][asset_type].append({
                'symbol': sym, 'ts': row[2],
                'last_price': row[3], 'last_quantity': row[4], 'volume': row[5],
                'buy_quantity': row[6], 'sell_quantity': row[7],
                'best_bid': row[8], 'best_ask': row[9],
                'bid_depth_total': row[10], 'ask_depth_total': row[11],
                'bid_l1_qty': row[12], 'bid_l2_qty': row[13], 'bid_l3_qty': row[14],
                'bid_l4_qty': row[15], 'bid_l5_qty': row[16],
                'ask_l1_qty': row[17], 'ask_l2_qty': row[18], 'ask_l3_qty': row[19],
                'ask_l4_qty': row[20], 'ask_l5_qty': row[21],
                'bid_l1_price': row[22], 'ask_l1_price': row[23],
            })
        return result

    def get_all_flow_metrics(self) -> Dict[str, dict]:
        """Return latest flow_metrics for all symbols as {symbol: metrics_dict}."""
        cursor = self.conn.execute("SELECT * FROM flow_metrics")
        result = {}
        for row in cursor.fetchall():
            d = dict(row)
            result[d['symbol']] = d
        return result

    def get_previous_bai_map(self) -> Tuple[Dict[str, float], Dict[str, float]]:
        """
        Return (cash_bai_map, fut_bai_map) from flow_metrics before this cycle's upsert.
        Used by analyzer to compute BAI delta for both cash and futures.
        """
        cursor = self.conn.execute("SELECT symbol, bai, fut_bai FROM flow_metrics")
        cash_map, fut_map = {}, {}
        for row in cursor.fetchall():
            cash_map[row[0]] = row[1]
            fut_map[row[0]]  = row[2]
        return cash_map, fut_map

    def get_cumulative_volume_stats(self, symbol: str, minutes: int = 5,
                                    asset_type: str = 'CASH') -> Tuple[int, int]:
        """
        Return (buy_vol, sell_vol) for executed trades over last N minutes.
        buy_vol:  sum of qty where last_price >= best_ask (buyer-initiated)
        sell_vol: sum of qty where last_price <= best_bid (seller-initiated)
        Caller computes pct = (buy - sell) / (buy + sell) for normalised comparison.
        asset_type: 'CASH' or 'FUT'
        """
        cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
        cursor = self.conn.execute("""
            SELECT SUM(CASE
                WHEN last_price >= best_ask AND best_ask > 0 AND last_quantity > 0 THEN last_quantity
                ELSE 0 END) as buy_vol,
                   SUM(CASE
                WHEN last_price <= best_bid AND best_bid > 0 AND last_quantity > 0 THEN last_quantity
                ELSE 0 END) as sell_vol
            FROM tick_snapshots
            WHERE symbol = ? AND ts >= ? AND asset_type = ?
        """, (symbol, cutoff, asset_type))
        row = cursor.fetchone()
        if row and row[0] is not None:
            return (row[0] or 0), (row[1] or 0)
        return 0, 0

    def was_alert_sent_recently(self, symbol: str, alert_type: str,
                                cooldown_minutes: int = None) -> bool:
        """Return True if this alert was fired within the cooldown window."""
        cooldown_minutes = cooldown_minutes or config.ORDER_FLOW_COOLDOWN_MINUTES
        cutoff = (datetime.now() - timedelta(minutes=cooldown_minutes)).strftime('%Y-%m-%d %H:%M:%S')
        cursor = self.conn.execute("""
            SELECT 1 FROM alert_history
            WHERE symbol = ? AND alert_type = ? AND fired_at >= ?
        """, (symbol, alert_type, cutoff))
        return cursor.fetchone() is not None

    def get_metadata(self, key: str) -> Optional[str]:
        cursor = self.conn.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def close(self):
        if self._writer_conn:
            self._writer_conn.close()
            self._writer_conn = None


# --------------------------------------------------------
# Singleton factory
# --------------------------------------------------------
_writer_instance: Optional[OrderFlowDB] = None
_reader_instance: Optional[OrderFlowDB] = None
_singleton_lock = threading.Lock()


def get_order_flow_db(mode: str = "reader") -> OrderFlowDB:
    """Singleton factory — separate instances for writer and reader."""
    global _writer_instance, _reader_instance
    with _singleton_lock:
        if mode == "writer":
            if _writer_instance is None:
                _writer_instance = OrderFlowDB(mode="writer")
            return _writer_instance
        else:
            if _reader_instance is None:
                _reader_instance = OrderFlowDB(mode="reader")
            return _reader_instance
