#!/usr/bin/env python3
"""
Background cleanup script for SQLite cache databases.

Purpose:
- Remove expired cache entries (older than 24 hours) to prevent database bloat
- Run VACUUM on Sundays to reclaim disk space
- Scheduled to run daily at 6:00 AM (no market activity)

Databases cleaned:
- data/unified_cache/quote_cache.db (quote cache entries)
- data/price_cache.db (price snapshots and daily volumes)

Usage:
    python cleanup_old_cache.py [--max-age-hours HOURS] [--force-vacuum]

Arguments:
    --max-age-hours HOURS    Maximum age of cache entries to keep (default: 24)
    --force-vacuum           Force VACUUM regardless of day of week
    --dry-run                Show what would be deleted without actually deleting

Schedule with cron:
    0 6 * * * cd /Users/sunildeesu/myProjects/ShortIndicator && python cleanup_old_cache.py >> logs/cleanup.log 2>&1
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).parent))

import config
from logger_config import setup_logger

logger = setup_logger('cleanup_old_cache')


def cleanup_quote_cache(db_file: str, max_age_hours: int = 24, dry_run: bool = False) -> dict:
    """
    Remove expired entries from quote cache database.

    Args:
        db_file: Path to quote_cache.db
        max_age_hours: Maximum age of entries to keep (default: 24 hours)
        dry_run: If True, only count what would be deleted

    Returns:
        Dictionary with cleanup statistics
    """
    if not os.path.exists(db_file):
        logger.warning(f"Database not found: {db_file}")
        return {'quotes_deleted': 0, 'metadata_deleted': 0}

    conn = sqlite3.connect(db_file, timeout=30)
    cutoff_time = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()

    try:
        # Count entries that will be deleted
        quote_count = conn.execute("""
            SELECT COUNT(*) FROM quote_cache
            WHERE cached_at < ?
        """, (cutoff_time,)).fetchone()[0]

        metadata_count = conn.execute("""
            SELECT COUNT(*) FROM cache_metadata
            WHERE key = 'last_refresh' AND value < ?
        """, (cutoff_time,)).fetchone()[0]

        if dry_run:
            logger.info(f"[DRY RUN] Would delete {quote_count} quote entries and {metadata_count} metadata entries")
            return {'quotes_deleted': quote_count, 'metadata_deleted': metadata_count}

        # Delete old quote cache entries
        conn.execute("""
            DELETE FROM quote_cache
            WHERE cached_at < ?
        """, (cutoff_time,))

        # Clean up old metadata entries
        conn.execute("""
            DELETE FROM cache_metadata
            WHERE key = 'last_refresh' AND value < ?
        """, (cutoff_time,))

        conn.commit()

        logger.info(f"Cleaned up {quote_count} quote entries and {metadata_count} metadata entries from quote_cache.db")

        return {'quotes_deleted': quote_count, 'metadata_deleted': metadata_count}

    except Exception as e:
        logger.error(f"Error cleaning quote cache: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def cleanup_price_cache(db_file: str, max_age_hours: int = 24, dry_run: bool = False) -> dict:
    """
    Remove expired entries from price cache database.

    Args:
        db_file: Path to price_cache.db
        max_age_hours: Maximum age of entries to keep (default: 24 hours)
        dry_run: If True, only count what would be deleted

    Returns:
        Dictionary with cleanup statistics
    """
    if not os.path.exists(db_file):
        logger.warning(f"Database not found: {db_file}")
        return {'snapshots_deleted': 0}

    conn = sqlite3.connect(db_file, timeout=30)
    cutoff_time = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()

    try:
        # Count entries that will be deleted
        snapshot_count = conn.execute("""
            SELECT COUNT(*) FROM price_snapshots
            WHERE timestamp < ?
        """, (cutoff_time,)).fetchone()[0]

        if dry_run:
            logger.info(f"[DRY RUN] Would delete {snapshot_count} price snapshot entries")
            return {'snapshots_deleted': snapshot_count}

        # Delete old price snapshots (keep avg_daily_volumes - they're not time-based)
        conn.execute("""
            DELETE FROM price_snapshots
            WHERE timestamp < ?
        """, (cutoff_time,))

        conn.commit()

        logger.info(f"Cleaned up {snapshot_count} price snapshot entries from price_cache.db")

        return {'snapshots_deleted': snapshot_count}

    except Exception as e:
        logger.error(f"Error cleaning price cache: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def vacuum_database(db_file: str, force: bool = False, dry_run: bool = False) -> dict:
    """
    Run VACUUM to reclaim disk space.

    By default, only runs on Sundays. Use force=True to run regardless of day.

    Args:
        db_file: Path to database file
        force: If True, run VACUUM regardless of day of week
        dry_run: If True, skip VACUUM

    Returns:
        Dictionary with VACUUM statistics
    """
    if not os.path.exists(db_file):
        logger.warning(f"Database not found: {db_file}")
        return {'vacuumed': False, 'reason': 'file_not_found'}

    # Check if today is Sunday (weekday 6) or force flag is set
    is_sunday = datetime.now().weekday() == 6

    if not force and not is_sunday:
        logger.info(f"Skipping VACUUM for {db_file} (not Sunday, use --force-vacuum to override)")
        return {'vacuumed': False, 'reason': 'not_sunday'}

    if dry_run:
        logger.info(f"[DRY RUN] Would VACUUM {db_file}")
        return {'vacuumed': False, 'reason': 'dry_run'}

    # Get file size before VACUUM
    size_before = os.path.getsize(db_file)

    conn = sqlite3.connect(db_file, timeout=30)

    try:
        logger.info(f"Running VACUUM on {db_file} (size: {size_before:,} bytes)...")
        conn.execute("VACUUM")
        conn.close()

        # Get file size after VACUUM
        size_after = os.path.getsize(db_file)
        space_saved = size_before - size_after

        logger.info(f"VACUUM completed on {db_file}. Space saved: {space_saved:,} bytes ({size_after:,} bytes remaining)")

        return {
            'vacuumed': True,
            'size_before': size_before,
            'size_after': size_after,
            'space_saved': space_saved
        }

    except Exception as e:
        logger.error(f"Error running VACUUM on {db_file}: {e}")
        conn.close()
        raise


def main():
    """Main cleanup routine"""
    parser = argparse.ArgumentParser(
        description='Clean up old entries from SQLite cache databases'
    )
    parser.add_argument(
        '--max-age-hours',
        type=int,
        default=24,
        help='Maximum age of cache entries to keep in hours (default: 24)'
    )
    parser.add_argument(
        '--force-vacuum',
        action='store_true',
        help='Force VACUUM regardless of day of week'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info(f"Starting cache cleanup routine (max age: {args.max_age_hours} hours)")
    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
    logger.info("=" * 80)

    # Database paths
    quote_cache_db = os.path.join(config.CACHE_DIR, 'quote_cache.db')
    price_cache_db = config.CACHE_FILE.replace('.json', '.db')

    total_deleted = 0
    total_space_saved = 0

    try:
        # Clean quote cache
        logger.info("\n--- Cleaning quote_cache.db ---")
        quote_stats = cleanup_quote_cache(quote_cache_db, args.max_age_hours, args.dry_run)
        total_deleted += quote_stats.get('quotes_deleted', 0) + quote_stats.get('metadata_deleted', 0)

        # Clean price cache
        logger.info("\n--- Cleaning price_cache.db ---")
        price_stats = cleanup_price_cache(price_cache_db, args.max_age_hours, args.dry_run)
        total_deleted += price_stats.get('snapshots_deleted', 0)

        # VACUUM databases (only on Sunday or if forced)
        logger.info("\n--- Running VACUUM ---")

        quote_vacuum = vacuum_database(quote_cache_db, args.force_vacuum, args.dry_run)
        if quote_vacuum.get('vacuumed'):
            total_space_saved += quote_vacuum.get('space_saved', 0)

        price_vacuum = vacuum_database(price_cache_db, args.force_vacuum, args.dry_run)
        if price_vacuum.get('vacuumed'):
            total_space_saved += price_vacuum.get('space_saved', 0)

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("CLEANUP SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total entries deleted: {total_deleted:,}")
        logger.info(f"Total disk space saved: {total_space_saved:,} bytes")
        logger.info(f"Cleanup completed successfully at {datetime.now().isoformat()}")
        logger.info("=" * 80)

        return 0

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
