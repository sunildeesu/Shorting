#!/usr/bin/env python3
"""
Sweep through different thresholds to find optimal early warning settings.
"""

import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import openpyxl
import config

def run_sweep():
    excel_path = config.ALERT_EXCEL_PATH
    db_path = "data/central_quotes.db"

    # Load 5-min alerts
    workbook = openpyxl.load_workbook(excel_path, read_only=True)
    sheet = workbook["5min_alerts"]
    cutoff_date = datetime.now() - timedelta(days=30)

    alerts = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        try:
            date_val = row[0]
            time_val = row[1]
            if isinstance(date_val, datetime):
                date_str = date_val.strftime("%Y-%m-%d")
            else:
                date_str = str(date_val)
            if isinstance(time_val, datetime):
                time_str = time_val.strftime("%H:%M:%S")
            else:
                time_str = str(time_val)
            try:
                alert_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            except:
                alert_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if alert_dt >= cutoff_date:
                alerts.append({
                    'datetime': alert_dt,
                    'symbol': str(row[2]),
                    'direction': str(row[3]).lower() if row[3] else 'drop',
                })
        except:
            continue
    workbook.close()

    print(f"Loaded {len(alerts)} 5-min alerts")

    # Connect to DB
    conn = sqlite3.connect(db_path)

    # Test different thresholds
    thresholds = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    lookbacks = [3, 4]

    print("\n" + "=" * 80)
    print("EARLY WARNING THRESHOLD SWEEP")
    print("=" * 80)
    print(f"{'Threshold':<12} {'Lookback':<10} {'TP':<8} {'FP':<8} {'Precision':<12} {'FP Rate':<12}")
    print("-" * 80)

    for lookback in lookbacks:
        for threshold in thresholds:
            tp = 0
            fp = 0

            # For each alert, check if early warning would have preceded it
            for alert in alerts:
                symbol = alert['symbol']
                alert_time = alert['datetime']
                direction = alert['direction']

                # Get data for preceding 10 minutes
                start_time = (alert_time - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
                end_time = alert_time.strftime('%Y-%m-%d %H:%M:%S')

                cursor = conn.cursor()
                cursor.execute("""
                    SELECT timestamp, price, volume
                    FROM stock_quotes
                    WHERE symbol = ?
                    AND timestamp >= ?
                    AND timestamp <= ?
                    ORDER BY timestamp ASC
                """, (symbol, start_time, end_time))

                data = cursor.fetchall()
                if len(data) < lookback + 1:
                    continue

                # Check if EW signal would fire at each minute before alert
                ew_would_fire = False
                for i in range(lookback, len(data) - 1):  # -1 to exclude alert time itself
                    current = data[i]
                    prev = data[i - lookback]

                    curr_price = current[1]
                    prev_price = prev[1]

                    if not curr_price or not prev_price or curr_price <= 0 or prev_price <= 0:
                        continue

                    if 'drop' in direction:
                        change = ((prev_price - curr_price) / prev_price) * 100
                    else:
                        change = ((curr_price - prev_price) / prev_price) * 100

                    if change >= threshold:
                        ew_would_fire = True
                        break

                if ew_would_fire:
                    tp += 1

            # Estimate false positives by sampling random periods
            # (Full scan takes too long, so we estimate)
            cursor.execute("""
                SELECT DISTINCT date(timestamp)
                FROM stock_quotes
                WHERE timestamp >= ?
                LIMIT 5
            """, (cutoff_date.strftime('%Y-%m-%d'),))

            sample_dates = [row[0] for row in cursor.fetchall()]
            sample_fp = 0
            sample_signals = 0

            for date_str in sample_dates[:3]:  # Sample 3 days
                cursor.execute("""
                    SELECT DISTINCT symbol
                    FROM stock_quotes
                    WHERE date(timestamp) = ?
                    LIMIT 50
                """, (date_str,))

                symbols = [row[0] for row in cursor.fetchall()]

                for sym in symbols[:30]:  # Sample 30 symbols per day
                    cursor.execute("""
                        SELECT timestamp, price, volume
                        FROM stock_quotes
                        WHERE symbol = ?
                        AND date(timestamp) = ?
                        AND time(timestamp) >= '09:25:00'
                        ORDER BY timestamp ASC
                    """, (sym, date_str))

                    sym_data = cursor.fetchall()
                    last_signal_idx = -100

                    for i in range(lookback, len(sym_data)):
                        if i - last_signal_idx < 15:  # Cooldown
                            continue

                        current = sym_data[i]
                        prev = sym_data[i - lookback]

                        curr_price = current[1]
                        prev_price = prev[1]

                        if not curr_price or not prev_price:
                            continue

                        drop_pct = ((prev_price - curr_price) / prev_price) * 100
                        rise_pct = ((curr_price - prev_price) / prev_price) * 100

                        if drop_pct >= threshold or rise_pct >= threshold:
                            sample_signals += 1
                            last_signal_idx = i

                            # Check if 5-min alert follows (simple check)
                            alert_follows = False
                            for j in range(1, 6):
                                if i + j >= len(sym_data) or i + j < 5:
                                    continue
                                fut = sym_data[i + j]
                                past = sym_data[i + j - 5]
                                if fut[1] and past[1]:
                                    d_pct = abs(past[1] - fut[1]) / past[1] * 100
                                    if d_pct >= 1.25:
                                        alert_follows = True
                                        break

                            if not alert_follows:
                                sample_fp += 1

            # Estimate total FP (scale up from sample)
            if sample_signals > 0:
                fp_rate_sample = sample_fp / sample_signals
                estimated_fp = int(fp_rate_sample * (sample_signals / 3 * 11))  # Scale to 11 days
            else:
                estimated_fp = 0
                fp_rate_sample = 0

            precision = tp / (tp + estimated_fp) if (tp + estimated_fp) > 0 else 0

            print(f"{threshold}%{'':<9} {lookback} min{'':<5} {tp:<8} ~{estimated_fp:<7} {precision:.1%}{'':<7} {fp_rate_sample:.1%}")

    conn.close()

    print("-" * 80)
    print("\nLegend:")
    print("  TP = True Positives (EW fired before actual 5-min alert)")
    print("  FP = False Positives (EW fired but no alert followed) - estimated from sample")
    print("  Precision = TP / (TP + FP)")
    print("  FP Rate = FP / Total Signals")
    print()

if __name__ == "__main__":
    run_sweep()
