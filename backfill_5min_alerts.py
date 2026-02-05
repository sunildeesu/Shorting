#!/usr/bin/env python3
"""
Backfill 5-Min Alerts from Historical Central DB Data

Scans historical data and finds all 5-min drops/rises that would have triggered alerts.
Logs them to the 5min_alerts Excel sheet.

Usage: python3 backfill_5min_alerts.py [--days 15] [--dry-run]
"""

import argparse
import logging
from datetime import datetime, timedelta
from collections import defaultdict

import config
from central_quote_db import get_central_db
from alert_excel_logger import AlertExcelLogger

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def backfill_alerts(days: int = 15, dry_run: bool = False):
    """
    Backfill 5-min alerts from historical data.

    Args:
        days: Number of days to look back
        dry_run: If True, don't write to Excel, just report what would be logged
    """
    db = get_central_db(mode='reader')
    excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH) if not dry_run else None

    # Thresholds from config
    drop_threshold = config.DROP_THRESHOLD_5MIN  # 1.25%
    rise_threshold = config.RISE_THRESHOLD_5MIN  # 1.25%
    cooldown_minutes = 10
    volume_spike_multiplier = 1.8  # Require current_volume > prev_volume * 1.8

    logger.info(f"Backfill settings: drop>={drop_threshold}%, rise>={rise_threshold}%, "
                f"volume_spike>={volume_spike_multiplier}x, cooldown={cooldown_minutes}min")
    logger.info(f"Dry run: {dry_run}")

    # Get all unique dates with data
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT DISTINCT DATE(timestamp) as dt
        FROM stock_quotes
        ORDER BY dt DESC
    ''')
    all_dates = [row[0] for row in cursor.fetchall()]

    logger.info(f"Found {len(all_dates)} dates with data: {all_dates}")

    # Stats
    total_drops = 0
    total_rises = 0
    alerts_by_date = defaultdict(lambda: {'drops': 0, 'rises': 0})

    for date_str in all_dates:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {date_str}")
        logger.info(f"{'='*60}")

        # Track cooldowns per stock for this day
        last_drop_alert = {}  # symbol -> timestamp
        last_rise_alert = {}  # symbol -> timestamp

        # Get all data for this date, ordered by time
        cursor.execute('''
            SELECT timestamp, symbol, price, volume
            FROM stock_quotes
            WHERE DATE(timestamp) = ?
            ORDER BY timestamp ASC
        ''', (date_str,))

        rows = cursor.fetchall()
        logger.info(f"  {len(rows)} records for this date")

        # Group by timestamp for efficient processing
        data_by_time = defaultdict(dict)
        for timestamp, symbol, price, volume in rows:
            data_by_time[timestamp][symbol] = {'price': price, 'volume': volume}

        timestamps = sorted(data_by_time.keys())
        logger.info(f"  {len(timestamps)} unique timestamps")

        if len(timestamps) < 6:
            logger.info(f"  Skipping - not enough timestamps for 5-min comparison")
            continue

        # For each timestamp, compare to ~5 minutes ago
        for i, current_ts in enumerate(timestamps):
            current_time = datetime.strptime(current_ts, '%Y-%m-%d %H:%M:%S')

            # Find timestamp ~5 minutes ago (within 4-6 minute window)
            target_time = current_time - timedelta(minutes=5)
            prev_ts = None

            for j in range(i-1, -1, -1):
                check_time = datetime.strptime(timestamps[j], '%Y-%m-%d %H:%M:%S')
                diff_minutes = (current_time - check_time).total_seconds() / 60

                if 4 <= diff_minutes <= 6:
                    prev_ts = timestamps[j]
                    break
                elif diff_minutes > 6:
                    break

            if not prev_ts:
                continue

            current_data = data_by_time[current_ts]
            prev_data = data_by_time[prev_ts]

            # Check each stock
            for symbol, quote in current_data.items():
                current_price = quote['price']
                current_volume = quote['volume']

                if symbol not in prev_data:
                    continue

                prev_price = prev_data[symbol]['price']
                prev_volume = prev_data[symbol]['volume']

                if not current_price or not prev_price or current_price <= 0 or prev_price <= 0:
                    continue

                # Check for VOLUME SPIKE first (required for all alerts)
                has_volume_spike = False
                volume_multiplier = 0
                if prev_volume and prev_volume > 0 and current_volume and current_volume > 0:
                    volume_multiplier = current_volume / prev_volume
                    has_volume_spike = current_volume > (prev_volume * volume_spike_multiplier)

                if not has_volume_spike:
                    # No volume spike - skip this stock
                    continue

                # Calculate drop
                drop_pct = ((prev_price - current_price) / prev_price) * 100

                # Check for DROP (volume spike already confirmed)
                if drop_pct >= drop_threshold:
                    # Check cooldown
                    last_alert = last_drop_alert.get(symbol)
                    if last_alert:
                        time_since = (current_time - last_alert).total_seconds() / 60
                        if time_since < cooldown_minutes:
                            continue  # Within cooldown

                    # Record alert
                    last_drop_alert[symbol] = current_time
                    total_drops += 1
                    alerts_by_date[date_str]['drops'] += 1

                    logger.info(f"    DROP: {symbol} {drop_pct:.2f}% (₹{prev_price:.2f} → ₹{current_price:.2f}) VOL:{volume_multiplier:.1f}x at {current_ts}")

                    if excel_logger:
                        volume_data = {'current_volume': current_volume, 'avg_volume': prev_volume, 'volume_spike': True}
                        excel_logger.log_alert(
                            symbol=symbol,
                            alert_type="5min",
                            drop_percent=drop_pct,
                            current_price=current_price,
                            previous_price=prev_price,
                            volume_data=volume_data,
                            market_cap_cr=None,
                            telegram_sent=False,  # Historical - not sent
                            timestamp=current_time
                        )

                # Check for RISE (volume spike already confirmed above)
                rise_pct = ((current_price - prev_price) / prev_price) * 100

                if rise_pct >= rise_threshold:
                    # Check cooldown
                    last_alert = last_rise_alert.get(symbol)
                    if last_alert:
                        time_since = (current_time - last_alert).total_seconds() / 60
                        if time_since < cooldown_minutes:
                            continue  # Within cooldown

                    # Record alert
                    last_rise_alert[symbol] = current_time
                    total_rises += 1
                    alerts_by_date[date_str]['rises'] += 1

                    logger.info(f"    RISE: {symbol} {rise_pct:.2f}% (₹{prev_price:.2f} → ₹{current_price:.2f}) VOL:{volume_multiplier:.1f}x at {current_ts}")

                    if excel_logger:
                        volume_data = {'current_volume': current_volume, 'avg_volume': prev_volume, 'volume_spike': True}
                        excel_logger.log_alert(
                            symbol=symbol,
                            alert_type="5min_rise",
                            drop_percent=rise_pct,
                            current_price=current_price,
                            previous_price=prev_price,
                            volume_data=volume_data,
                            market_cap_cr=None,
                            telegram_sent=False,  # Historical - not sent
                            timestamp=current_time
                        )

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("BACKFILL SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total DROP alerts: {total_drops}")
    logger.info(f"Total RISE alerts: {total_rises}")
    logger.info(f"\nBy date:")
    for date_str in sorted(alerts_by_date.keys()):
        stats = alerts_by_date[date_str]
        logger.info(f"  {date_str}: {stats['drops']} drops, {stats['rises']} rises")

    if dry_run:
        logger.info("\n[DRY RUN] No data written to Excel")
    else:
        logger.info(f"\nAlerts logged to: {config.ALERT_EXCEL_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Backfill 5-min alerts from historical data')
    parser.add_argument('--days', type=int, default=15, help='Number of days to look back')
    parser.add_argument('--dry-run', action='store_true', help='Report only, do not write to Excel')

    args = parser.parse_args()

    backfill_alerts(days=args.days, dry_run=args.dry_run)
