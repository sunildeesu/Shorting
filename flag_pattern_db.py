#!/Users/sunilkumar/myProjects/ShortIndicator/venv/bin/python3
"""
Flag Pattern Database

SQLite storage for the flag pattern monitor. Manages three tables:
  stock_universe  — all stocks to scan, with Kite tokens and segment labels
  ohlcv_cache     — daily OHLCV candles (keyed by symbol+date, 24h cache)
  flag_detections — log of detected flag setups and alert outcomes

Follows the central_quote_db.py pattern: WAL mode, indexed, thread-safe.

Author: Sunil Kumar Durganaik
"""

import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class FlagPatternDB:
    """SQLite-backed store for flag pattern monitor data."""

    def __init__(self, db_path: str = "data/flag_pattern.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"FlagPatternDB ready: {db_path}")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-32000")  # 32 MB
        conn.execute("PRAGMA busy_timeout=10000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS stock_universe (
                    symbol           TEXT PRIMARY KEY,
                    name             TEXT,
                    instrument_token INTEGER NOT NULL,
                    segment          TEXT,
                    index_membership TEXT,
                    added_at         TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ohlcv_cache (
                    symbol    TEXT NOT NULL,
                    date      TEXT NOT NULL,
                    open      REAL,
                    high      REAL,
                    low       REAL,
                    close     REAL,
                    volume    INTEGER,
                    cached_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, date)
                );

                CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_date
                ON ohlcv_cache(symbol, date);

                CREATE TABLE IF NOT EXISTS flag_detections (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    detected_at        TEXT NOT NULL,
                    symbol             TEXT NOT NULL,
                    score              REAL,
                    pole_gain_pct      REAL,
                    pole_high          REAL,
                    pole_low           REAL,
                    pole_days          INTEGER,
                    pullback_depth_pct REAL,
                    flag_days          INTEGER,
                    volume_ratio       REAL,
                    breakout_level     REAL,
                    stop_loss          REAL,
                    current_price      REAL,
                    ema_20             REAL,
                    sma_50             REAL,
                    trend_aligned      INTEGER,
                    adx                REAL,
                    telegram_sent      INTEGER
                );
            """)

    # ------------------------------------------------------------------
    # Stock universe
    # ------------------------------------------------------------------

    def upsert_stock(
        self,
        symbol: str,
        name: str,
        token: int,
        segment: str,
        index_membership: Optional[str] = None,
    ):
        """Insert or update a stock in the universe table."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stock_universe
                    (symbol, name, instrument_token, segment, index_membership, added_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    instrument_token = excluded.instrument_token,
                    segment          = excluded.segment,
                    index_membership = CASE
                        WHEN excluded.index_membership IS NOT NULL
                        THEN excluded.index_membership
                        ELSE index_membership
                    END
                """,
                (symbol, name, token, segment, index_membership,
                 datetime.now().isoformat()),
            )

    def get_all_stocks(self, include_smallmid: bool = True) -> List[Dict]:
        """Return all stocks in the universe (optionally filtered to large_mid only)."""
        with self._connect() as conn:
            if include_smallmid:
                rows = conn.execute(
                    "SELECT * FROM stock_universe ORDER BY symbol"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM stock_universe WHERE segment = 'large_mid' ORDER BY symbol"
                ).fetchall()
        return [dict(r) for r in rows]

    def stock_count(self) -> Dict[str, int]:
        """Return {segment: count} breakdown."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT segment, COUNT(*) as cnt FROM stock_universe GROUP BY segment"
            ).fetchall()
        return {r["segment"]: r["cnt"] for r in rows}

    def total_stocks(self, include_smallmid: bool = True) -> int:
        with self._connect() as conn:
            if include_smallmid:
                row = conn.execute("SELECT COUNT(*) FROM stock_universe").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM stock_universe WHERE segment = 'large_mid'"
                ).fetchone()
        return row[0]

    # ------------------------------------------------------------------
    # OHLCV cache
    # ------------------------------------------------------------------

    def is_cache_fresh(self, symbol: str) -> bool:
        """True if the most recent cached date is today or yesterday."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(date) as latest FROM ohlcv_cache WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        if not row or not row["latest"]:
            return False
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        return row["latest"] >= yesterday

    def get_ohlcv(self, symbol: str, from_date: str) -> Optional[pd.DataFrame]:
        """Return cached OHLCV candles for symbol >= from_date, or None if not cached."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT date, open, high, low, close, volume
                   FROM ohlcv_cache
                   WHERE symbol = ? AND date >= ?
                   ORDER BY date ASC""",
                (symbol, from_date),
            ).fetchall()
        if not rows:
            return None
        df = pd.DataFrame([dict(r) for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        return df

    def upsert_ohlcv(self, symbol: str, df: pd.DataFrame):
        """Bulk insert/replace daily OHLCV candles for a symbol."""
        now = datetime.now().isoformat()
        rows = []
        for _, row in df.iterrows():
            dt = row["date"]
            date_str = (
                dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
            )
            rows.append(
                (
                    symbol,
                    date_str,
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    int(row["volume"]),
                    now,
                )
            )
        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO ohlcv_cache
                   (symbol, date, open, high, low, close, volume, cached_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

    # ------------------------------------------------------------------
    # Flag detections log
    # ------------------------------------------------------------------

    def log_detection(self, result: Dict, telegram_sent: bool):
        """Insert a flag detection record."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO flag_detections
                   (detected_at, symbol, score, pole_gain_pct, pole_high, pole_low,
                    pole_days, pullback_depth_pct, flag_days, volume_ratio,
                    breakout_level, stop_loss, current_price, ema_20, sma_50,
                    trend_aligned, adx, telegram_sent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().isoformat(),
                    result["symbol"],
                    result.get("score"),
                    result.get("pole_gain_pct"),
                    result.get("pole_high"),
                    result.get("pole_low"),
                    result.get("pole_days"),
                    result.get("pullback_depth_pct"),
                    result.get("flag_days"),
                    result.get("volume_ratio"),
                    result.get("breakout_level"),
                    result.get("stop_loss"),
                    result.get("current_price"),
                    result.get("ema_20"),
                    result.get("sma_50"),
                    1 if result.get("trend_aligned") else 0,
                    result.get("adx"),
                    1 if telegram_sent else 0,
                ),
            )

    def get_recent_detections(self, days: int = 7) -> List[Dict]:
        """Return all detections in the last N days, newest first."""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM flag_detections WHERE detected_at >= ? ORDER BY detected_at DESC",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]
