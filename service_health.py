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

        # Table for service heartbeats
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_heartbeats (
                service_name TEXT PRIMARY KEY,
                last_heartbeat TEXT NOT NULL,
                status TEXT DEFAULT 'running',
                cycle_count INTEGER DEFAULT 0,
                last_cycle_duration_ms INTEGER
            )
        """)

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
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute("""
                INSERT INTO service_heartbeats (service_name, last_heartbeat, status, cycle_count, last_cycle_duration_ms)
                VALUES (?, ?, 'running', 1, ?)
                ON CONFLICT(service_name) DO UPDATE SET
                    last_heartbeat = excluded.last_heartbeat,
                    status = 'running',
                    cycle_count = cycle_count + 1,
                    last_cycle_duration_ms = excluded.last_cycle_duration_ms
            """, (service_name, now, cycle_duration_ms))

            conn.commit()

    def get_service_status(self) -> List[Dict]:
        """
        Get status of all services based on heartbeats.

        Returns:
            List of service status dicts
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT service_name, last_heartbeat, status, cycle_count, last_cycle_duration_ms
            FROM service_heartbeats
            ORDER BY service_name
        """)

        services = []
        now = datetime.now()

        for row in cursor.fetchall():
            last_heartbeat = datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')
            age_minutes = (now - last_heartbeat).total_seconds() / 60

            # Determine status based on heartbeat age
            if age_minutes > 5:
                status = "dead"
            elif age_minutes > 2:
                status = "stale"
            else:
                status = "healthy"

            services.append({
                'service_name': row[0],
                'last_heartbeat': row[1],
                'age_minutes': round(age_minutes, 1),
                'status': status,
                'cycle_count': row[3],
                'last_cycle_duration_ms': row[4]
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
            'healthy_services': status_counts.get('healthy', 0),
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
    print(f"  Services: {summary['healthy_services']}/{summary['total_services']} healthy")
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
        status_icon = {"healthy": "✅", "stale": "🟡", "dead": "🔴"}.get(svc['status'], "❓")
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
