#!/usr/bin/env python3
"""
Service Health Dashboard - Quick troubleshooting view of all services.

Run this script to see:
- Which services are running/dead
- Active errors and warnings
- Key metrics from each service
- Central database health

Usage:
    python3 health_dashboard.py           # One-time view
    python3 health_dashboard.py --watch   # Auto-refresh every 30s
    python3 health_dashboard.py --json    # Output as JSON

Author: Claude Code
Date: 2026-01-19
"""

import argparse
import json
import sys
import time
from datetime import datetime

from service_health import get_health_tracker
from central_quote_db import get_central_db


def get_central_db_status() -> dict:
    """Get central database health status"""
    try:
        db = get_central_db()
        health = db.get_data_health()
        is_fresh, age_minutes = db.is_data_fresh(max_age_minutes=2)

        return {
            'available': True,
            'is_fresh': is_fresh,
            'age_minutes': age_minutes,
            'unique_stocks': health.get('unique_stocks', 0),
            'collection_status': health.get('collection_status'),
            'last_collection_time': health.get('last_collection_time'),
            'health_alert': health.get('health_alert')
        }
    except Exception as e:
        return {
            'available': False,
            'error': str(e)
        }


def print_dashboard(data: dict, central_db: dict):
    """Print formatted dashboard to terminal"""

    # Clear screen (optional)
    print("\033[2J\033[H", end="")

    print("\n" + "=" * 75)
    print("                    SERVICE HEALTH DASHBOARD")
    print("=" * 75)
    print(f"  Timestamp: {data['timestamp']}")
    print("-" * 75)

    # Summary bar
    summary = data['summary']
    total = summary['total_services']
    healthy = summary['healthy_services']
    dead = summary['dead_services']
    stale = summary['stale_services']

    status_bar = ""
    if dead > 0:
        status_bar = f"🔴 {dead} DEAD"
    elif stale > 0:
        status_bar = f"🟡 {stale} STALE"
    elif healthy == total:
        status_bar = "✅ ALL HEALTHY"
    else:
        status_bar = f"⚠️ {healthy}/{total} healthy"

    error_bar = ""
    if summary['critical_errors'] > 0:
        error_bar += f" | 🔴 {summary['critical_errors']} critical"
    if summary['errors'] > 0:
        error_bar += f" | 🟠 {summary['errors']} errors"
    if summary['warnings'] > 0:
        error_bar += f" | 🟡 {summary['warnings']} warnings"
    if not error_bar:
        error_bar = " | ✅ No errors"

    print(f"\n  OVERVIEW: {status_bar}{error_bar}")

    # Central Database Status
    print("\n" + "-" * 75)
    print("  CENTRAL DATABASE (central_quotes.db)")
    print("-" * 75)

    if not central_db['available']:
        print(f"  🔴 UNAVAILABLE: {central_db.get('error', 'Unknown error')}")
    else:
        if central_db['is_fresh']:
            print(f"  ✅ Data is FRESH ({central_db['age_minutes']} min old)")
        else:
            print(f"  🔴 Data is STALE ({central_db['age_minutes']} min old)")

        print(f"     Stocks in DB: {central_db['unique_stocks']}")
        print(f"     Last collection: {central_db['last_collection_time'] or 'N/A'}")
        print(f"     Collection status: {central_db['collection_status'] or 'N/A'}")

        if central_db.get('health_alert'):
            print(f"     ⚠️ Alert: {central_db['health_alert']}")

    # Services Status
    print("\n" + "-" * 75)
    print("  SERVICES")
    print("-" * 75)

    if not data['services']:
        print("  (No services have reported yet)")
    else:
        for svc in data['services']:
            status = svc['status']
            name = svc['service_name']
            age = svc['age_minutes']
            cycles = svc['cycle_count']
            duration = svc.get('last_cycle_duration_ms')

            if status == 'healthy':
                icon = "✅"
            elif status == 'stale':
                icon = "🟡"
            else:
                icon = "🔴"

            duration_str = f", {duration}ms/cycle" if duration else ""
            print(f"  {icon} {name:25} {status:8} (last seen {age:.1f} min ago, {cycles} cycles{duration_str})")

    # Active Errors
    print("\n" + "-" * 75)
    print("  ACTIVE ERRORS")
    print("-" * 75)

    if not data['active_errors']:
        print("  ✅ No active errors")
    else:
        for err in data['active_errors']:
            sev = err['severity']
            if sev == 'critical':
                icon = "🔴"
            elif sev == 'error':
                icon = "🟠"
            else:
                icon = "🟡"

            print(f"\n  {icon} [{err['service_name']}] {err['error_type']} ({sev.upper()})")
            print(f"     {err['message']}")
            print(f"     Occurred {err['occurrence_count']}x (first: {err['first_seen']}, last: {err['last_seen']})")

            if err.get('details'):
                for k, v in err['details'].items():
                    print(f"     • {k}: {v}")

    # Key Metrics
    print("\n" + "-" * 75)
    print("  KEY METRICS")
    print("-" * 75)

    metrics = data['metrics']
    if not metrics:
        print("  (No metrics reported yet)")
    else:
        for svc_name, svc_metrics in sorted(metrics.items()):
            print(f"\n  {svc_name}:")
            for metric_name, metric_data in sorted(svc_metrics.items()):
                value = metric_data['value']
                ts = metric_data['timestamp']
                # Highlight important metrics
                if metric_name == 'data_source' and value == 'api_fallback':
                    print(f"    ⚠️ {metric_name}: {value} (at {ts})")
                else:
                    print(f"    • {metric_name}: {value}")

    # Troubleshooting tips
    print("\n" + "-" * 75)
    print("  TROUBLESHOOTING TIPS")
    print("-" * 75)

    tips = []

    # Check for dead services
    for svc in data['services']:
        if svc['status'] == 'dead':
            tips.append(f"• {svc['service_name']} is DEAD - check if LaunchAgent is running")

    # Check central DB
    if not central_db['available']:
        tips.append("• Central database unavailable - check data/central_quotes.db")
    elif not central_db['is_fresh']:
        tips.append("• Central database is STALE - is central_data_collector running?")
        tips.append("  Run: launchctl list | grep central_data")

    # Check for API fallback
    for svc_name, svc_metrics in metrics.items():
        if svc_metrics.get('data_source', {}).get('value') == 'api_fallback':
            tips.append(f"• {svc_name} is using API fallback - central_data_collector may be down")

    if not tips:
        print("  ✅ No issues detected")
    else:
        for tip in tips:
            print(f"  {tip}")

    print("\n" + "=" * 75)
    print("  Run 'python3 health_dashboard.py --watch' for auto-refresh")
    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Service Health Dashboard")
    parser.add_argument("--watch", "-w", action="store_true",
                       help="Auto-refresh every 30 seconds")
    parser.add_argument("--interval", "-i", type=int, default=30,
                       help="Refresh interval in seconds (default: 30)")
    parser.add_argument("--json", "-j", action="store_true",
                       help="Output as JSON")
    args = parser.parse_args()

    tracker = get_health_tracker()

    if args.watch:
        try:
            while True:
                data = tracker.get_dashboard_data()
                central_db = get_central_db_status()

                if args.json:
                    output = {**data, 'central_db': central_db}
                    print(json.dumps(output, indent=2))
                else:
                    print_dashboard(data, central_db)

                print(f"(Refreshing in {args.interval}s... Press Ctrl+C to stop)")
                time.sleep(args.interval)

        except KeyboardInterrupt:
            print("\nStopped.")
            sys.exit(0)
    else:
        data = tracker.get_dashboard_data()
        central_db = get_central_db_status()

        if args.json:
            output = {**data, 'central_db': central_db}
            print(json.dumps(output, indent=2))
        else:
            print_dashboard(data, central_db)


if __name__ == "__main__":
    main()
