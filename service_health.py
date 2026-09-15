#!/usr/bin/env python3
"""
Service Health Tracker - Centralized health monitoring for all services.

Tracks errors, warnings, and metrics across all monitoring services:
- central_data_collector
- onemin_monitor
- stock_monitor
- nifty_option_analyzer
- sector_analyzer

Data is stored in SQLite for persistence and dashboard access.

Liveness is DERIVED, never stored. On 2026-08-31 six monitors died at ~11:16-11:19
and `service_heartbeats.status` still read 'running' eight hours later, because the
writer stored that string and nothing ever aged it. The rule now:

    age = now - last_heartbeat
    age <= STALE_FACTOR * interval   -> 'running'
    age <= DEAD_FACTOR  * interval   -> 'stale'
    otherwise                        -> 'dead'

where `interval` is the service's own heartbeat cadence from HEARTBEAT_INTERVAL_S
(discovered from the writers / launchd_agents; DEFAULT_HEARTBEAT_INTERVAL_S when a
service is not listed). `derive_status()` is the only place this rule lives; every
in-repo reader goes through it. The `status` column is retained for schema
compatibility but is written as NULL - a raw `SELECT status` can no longer claim
anything about liveness. `tests/test_service_health_liveness.py` pins this.

Author: Claude Code
Date: 2026-01-19
"""

import sqlite3
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import json

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = "data/service_health.db"

# Heartbeat cadence per service, in seconds. Sources: launchd_agents/*.plist
# StartInterval (cpr 60, candle/doublebottom 300), main.MONITOR_INTERVAL_SECONDS
# (stock_monitor 300; sector_analyzer heartbeats inside that same cycle),
# onemin_monitor_continuous (60), the price-action calendar (every 5 min), and the
# 16:00 daily double_bottom_position_tracker job.
HEARTBEAT_INTERVAL_S = {
    'cpr_first_touch_monitor': 60,
    'onemin_monitor': 60,
    'stock_monitor': 300,
    'sector_analyzer': 300,
    'candle_confirmation_monitor': 300,
    'double_bottom_support_monitor': 300,
    'price_action_monitor': 300,
    'double_bottom_position_tracker': 86400,
}
# Unknown services are assumed to beat every minute: an unlisted service is flagged
# early rather than reported running for longer than it is.
DEFAULT_HEARTBEAT_INTERVAL_S = 60
# Missed one beat with slack -> stale; missed several -> dead. For the 60 s services
# this is the 2 min / 5 min rule the dashboard has always used.
STALE_FACTOR = 2
DEAD_FACTOR = 5

HEARTBEAT_TS_FORMAT = '%Y-%m-%d %H:%M:%S'


def heartbeat_interval_s(service_name: str) -> int:
    """Expected seconds between heartbeats for a service."""
    return HEARTBEAT_INTERVAL_S.get(service_name, DEFAULT_HEARTBEAT_INTERVAL_S)


def derive_status(service_name: str, last_heartbeat: str, now: datetime = None) -> str:
    """
    The single authoritative liveness rule: 'running' / 'stale' / 'dead' from the
    age of `last_heartbeat` against the service's own cadence. Never reads the
    stored `status` column.
    """
    now = now or datetime.now()
    age_s = (now - datetime.strptime(last_heartbeat, HEARTBEAT_TS_FORMAT)).total_seconds()
    interval = heartbeat_interval_s(service_name)
    if age_s <= STALE_FACTOR * interval:
        return 'running'
    if age_s <= DEAD_FACTOR * interval:
        return 'stale'
    return 'dead'


class ServiceHealthTracker:
    """
    Centralized health tracking for all monitoring services.

    Features:
    - Track errors with severity levels
    - Track metrics (data source, latency, counts, etc.)
    - Automatic cleanup of old data
    - Thread-safe operations
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """
        Initialize health tracker.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = None

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # Initialize database
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection"""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                timeout=10,
                check_same_thread=False
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_database(self):
        """Initialize database schema"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Table for tracking errors
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                error_type TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT DEFAULT 'error',
                details TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                occurrence_count INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                UNIQUE(service_name, error_type)
            )
        """)

        # Table for tracking metrics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                UNIQUE(service_name, metric_name)
            )
        """)

        # Table for service heartbeats. `status` is kept only so older schemas and
        # in-flight writers stay compatible; it is written NULL and never read -
        # liveness comes from derive_status(). Rows left over from the old writer
        # still say 'running', so blank them once here.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_heartbeats (
                service_name TEXT PRIMARY KEY,
                last_heartbeat TEXT NOT NULL,
                status TEXT,
                cycle_count INTEGER DEFAULT 0,
                last_cycle_duration_ms INTEGER
            )
        """)
        cursor.execute("UPDATE service_heartbeats SET status = NULL WHERE status IS NOT NULL")

        # Table for historical error log (for trends)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                error_type TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        # Indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_errors_service
            ON service_errors(service_name, is_active)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_service
            ON service_metrics(service_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_timestamp
            ON error_history(timestamp DESC)
        """)

        conn.commit()
        logger.debug(f"Service health database initialized: {self.db_path}")

    # ============================================
    # ERROR TRACKING
    # ============================================

    def report_error(self, service_name: str, error_type: str, message: str,
                    severity: str = "error", details: Dict = None):
        """
        Report an error from a service.

        Args:
            service_name: Name of the service (e.g., "onemin_monitor")
            error_type: Type of error (e.g., "central_db_stale")
            message: Human-readable error message
            severity: "error", "warning", or "critical"
            details: Optional dict with additional details
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            details_json = json.dumps(details) if details else None

            # Upsert error (update if exists, insert if not)
            cursor.execute("""
                INSERT INTO service_errors
                (service_name, error_type, message, severity, details, first_seen, last_seen, occurrence_count, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)
                ON CONFLICT(service_name, error_type) DO UPDATE SET
                    message = excluded.message,
                    severity = excluded.severity,
                    details = excluded.details,
                    last_seen = excluded.last_seen,
                    occurrence_count = occurrence_count + 1,
                    is_active = 1
            """, (service_name, error_type, message, severity, details_json, now, now))

            # Also log to history for trends
            cursor.execute("""
                INSERT INTO error_history (service_name, error_type, message, severity, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (service_name, error_type, message, severity, now))

            conn.commit()

            # Log based on severity
            if severity == "critical":
                logger.critical(f"[HEALTH] {service_name}/{error_type}: {message}")
            elif severity == "error":
                logger.error(f"[HEALTH] {service_name}/{error_type}: {message}")
            else:
                logger.warning(f"[HEALTH] {service_name}/{error_type}: {message}")

    def clear_error(self, service_name: str, error_type: str):
        """
        Clear an error (mark as resolved).

        Args:
            service_name: Name of the service
            error_type: Type of error to clear
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE service_errors
                SET is_active = 0
                WHERE service_name = ? AND error_type = ?
            """, (service_name, error_type))

            conn.commit()

    def get_active_errors(self, service_name: str = None) -> List[Dict]:
        """
        Get all active errors, optionally filtered by service.

        Args:
            service_name: Optional service name to filter by

        Returns:
            List of error dicts
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if service_name:
            cursor.execute("""
                SELECT service_name, error_type, message, severity, details,
                       first_seen, last_seen, occurrence_count
                FROM service_errors
                WHERE is_active = 1 AND service_name = ?
                ORDER BY last_seen DESC
            """, (service_name,))
        else:
            cursor.execute("""
                SELECT service_name, error_type, message, severity, details,
                       first_seen, last_seen, occurrence_count
                FROM service_errors
                WHERE is_active = 1
                ORDER BY severity DESC, last_seen DESC
            """)

        errors = []
        for row in cursor.fetchall():
            errors.append({
                'service_name': row[0],
                'error_type': row[1],
                'message': row[2],
                'severity': row[3],
                'details': json.loads(row[4]) if row[4] else None,
                'first_seen': row[5],
                'last_seen': row[6],
                'occurrence_count': row[7]
            })

        return errors

    # ============================================
    # METRIC TRACKING
    # ============================================

    def report_metric(self, service_name: str, metric_name: str, value: Any):
        """
        Report a metric from a service.

        Args:
            service_name: Name of the service
            metric_name: Name of the metric (e.g., "data_source", "quotes_fetched")
            value: Metric value (will be converted to string)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute("""
                INSERT INTO service_metrics (service_name, metric_name, metric_value, timestamp)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(service_name, metric_name) DO UPDATE SET
                    metric_value = excluded.metric_value,
                    timestamp = excluded.timestamp
            """, (service_name, metric_name, str(value), now))

            conn.commit()

    def get_metrics(self, service_name: str = None) -> Dict[str, Dict[str, Any]]:
        """
        Get all metrics, optionally filtered by service.

        Args:
            service_name: Optional service name to filter by

        Returns:
            Dict of {service_name: {metric_name: value}}
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if service_name:
            cursor.execute("""
                SELECT service_name, metric_name, metric_value, timestamp
                FROM service_metrics
                WHERE service_name = ?
            """, (service_name,))
        else:
            cursor.execute("""
                SELECT service_name, metric_name, metric_value, timestamp
                FROM service_metrics
            """)

        metrics = {}
        for row in cursor.fetchall():
            svc = row[0]
            if svc not in metrics:
                metrics[svc] = {}
            metrics[svc][row[1]] = {
                'value': row[2],
                'timestamp': row[3]
            }

        return metrics

    # ============================================
    # HEARTBEAT TRACKING
    # ============================================

    def heartbeat(self, service_name: str, cycle_duration_ms: int = None):
        """
        Record a heartbeat from a service.

        Args:
            service_name: Name of the service
            cycle_duration_ms: Optional duration of last cycle in milliseconds
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().strftime(HEARTBEAT_TS_FORMAT)

            cursor.execute("""
                INSERT INTO service_heartbeats (service_name, last_heartbeat, status, cycle_count, last_cycle_duration_ms)
                VALUES (?, ?, NULL, 1, ?)
                ON CONFLICT(service_name) DO UPDATE SET
                    last_heartbeat = excluded.last_heartbeat,
                    status = NULL,
                    cycle_count = cycle_count + 1,
                    last_cycle_duration_ms = excluded.last_cycle_duration_ms
            """, (service_name, now, cycle_duration_ms))

            conn.commit()

    def get_service_status(self, now: datetime = None) -> List[Dict]:
        """
        Get status of all services, derived from heartbeat age via derive_status().
        The stored `status` column is deliberately not selected.

        Returns:
            List of service status dicts
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT service_name, last_heartbeat, cycle_count, last_cycle_duration_ms
            FROM service_heartbeats
            ORDER BY service_name
        """)

        services = []
        now = now or datetime.now()

        for row in cursor.fetchall():
            last_heartbeat = datetime.strptime(row[1], HEARTBEAT_TS_FORMAT)
            age_minutes = (now - last_heartbeat).total_seconds() / 60

            services.append({
                'service_name': row[0],
                'last_heartbeat': row[1],
                'age_minutes': round(age_minutes, 1),
                'status': derive_status(row[0], row[1], now),
                'interval_s': heartbeat_interval_s(row[0]),
                'cycle_count': row[2],
                'last_cycle_duration_ms': row[3]
            })

        return services

    # ============================================
    # DASHBOARD DATA
    # ============================================

    def get_dashboard_data(self) -> Dict:
        """
        Get all data needed for the troubleshooting dashboard.

        Returns:
            Dict with services, errors, and metrics
        """
        return {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'services': self.get_service_status(),
            'active_errors': self.get_active_errors(),
            'metrics': self.get_metrics(),
            'summary': self._get_summary()
        }

    def _get_summary(self) -> Dict:
        """Get summary statistics"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Count active errors by severity
        cursor.execute("""
            SELECT severity, COUNT(*)
            FROM service_errors
            WHERE is_active = 1
            GROUP BY severity
        """)
        error_counts = {row[0]: row[1] for row in cursor.fetchall()}

        # Count services by status
        services = self.get_service_status()
        status_counts = {}
        for svc in services:
            status = svc['status']
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            'total_services': len(services),
            'running_services': status_counts.get('running', 0),
            'stale_services': status_counts.get('stale', 0),
            'dead_services': status_counts.get('dead', 0),
            'critical_errors': error_counts.get('critical', 0),
            'errors': error_counts.get('error', 0),
            'warnings': error_counts.get('warning', 0)
        }

    # ============================================
    # MAINTENANCE
    # ============================================

    def cleanup_old_data(self, days: int = 7):
        """
        Clean up old data to prevent database bloat.

        Args:
            days: Keep data from last N days
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

            # Clean old history
            cursor.execute("DELETE FROM error_history WHERE timestamp < ?", (cutoff,))
            deleted = cursor.rowcount

            # Clean resolved errors older than cutoff
            cursor.execute("""
                DELETE FROM service_errors
                WHERE is_active = 0 AND last_seen < ?
            """, (cutoff,))
            deleted += cursor.rowcount

            conn.commit()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old health records")

    def close(self):
        """Close database connection"""
        if self._conn:
            self._conn.close()
            self._conn = None


# Singleton instance
_tracker_instance = None
_tracker_lock = threading.Lock()


def get_health_tracker(db_path: str = DEFAULT_DB_PATH) -> ServiceHealthTracker:
    """
    Get singleton instance of health tracker.

    Args:
        db_path: Path to database (only used on first call)

    Returns:
        ServiceHealthTracker instance
    """
    global _tracker_instance

    with _tracker_lock:
        if _tracker_instance is None:
            _tracker_instance = ServiceHealthTracker(db_path)
        return _tracker_instance


# CLI for quick status check
if __name__ == "__main__":
    import sys

    tracker = get_health_tracker()
    data = tracker.get_dashboard_data()

    print("\n" + "=" * 70)
    print("SERVICE HEALTH DASHBOARD")
    print("=" * 70)
    print(f"Timestamp: {data['timestamp']}")

    # Summary
    summary = data['summary']
    print(f"\nSummary:")
    print(f"  Services: {summary['running_services']}/{summary['total_services']} running")
    if summary['dead_services'] > 0:
        print(f"  ⚠️  {summary['dead_services']} service(s) NOT RUNNING")
    if summary['critical_errors'] > 0:
        print(f"  🔴 {summary['critical_errors']} critical error(s)")
    if summary['errors'] > 0:
        print(f"  🟠 {summary['errors']} error(s)")
    if summary['warnings'] > 0:
        print(f"  🟡 {summary['warnings']} warning(s)")

    # Services
    print(f"\nServices:")
    for svc in data['services']:
        status_icon = {"running": "✅", "stale": "🟡", "dead": "🔴"}.get(svc['status'], "❓")
        print(f"  {status_icon} {svc['service_name']}: {svc['status']} "
              f"(last seen {svc['age_minutes']} min ago, {svc['cycle_count']} cycles)")

    # Active Errors
    if data['active_errors']:
        print(f"\nActive Errors:")
        for err in data['active_errors']:
            severity_icon = {"critical": "🔴", "error": "🟠", "warning": "🟡"}.get(err['severity'], "❓")
            print(f"  {severity_icon} [{err['service_name']}] {err['error_type']}")
            print(f"     {err['message']}")
            print(f"     (occurred {err['occurrence_count']}x, last: {err['last_seen']})")
    else:
        print(f"\n✅ No active errors")

    # Key Metrics
    print(f"\nKey Metrics:")
    for svc_name, metrics in data['metrics'].items():
        print(f"  {svc_name}:")
        for metric_name, metric_data in metrics.items():
            print(f"    {metric_name}: {metric_data['value']}")

    print("\n" + "=" * 70)
