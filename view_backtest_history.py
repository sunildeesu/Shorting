#!/usr/bin/env python3
"""
View Backtest History - Query and Analyze Historical Backtest Data

Usage:
  python3 view_backtest_history.py --all-time
  python3 view_backtest_history.py --last-month
  python3 view_backtest_history.py --trends
  python3 view_backtest_history.py --losing-days

Author: Sunil Kumar Durganaik
"""

import argparse
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path

DB_PATH = "data/backtest_history.db"


def get_all_time_stats():
    """Get all-time backtest statistics"""
    if not Path(DB_PATH).exists():
        print("❌ No backtest history database found. Run weekly_backtest_runner.py first.")
        return

    conn = sqlite3.connect(DB_PATH)

    # Overall stats
    query = '''
        SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN net_pnl <= 0 THEN 1 ELSE 0 END) as losses,
            AVG(net_pnl) as avg_pnl,
            SUM(net_pnl) as total_pnl,
            MAX(net_pnl) as max_profit,
            MIN(net_pnl) as max_loss,
            MIN(trade_date) as first_trade,
            MAX(trade_date) as last_trade
        FROM backtest_trades
    '''

    df = pd.read_sql_query(query, conn)

    print("\n" + "=" * 80)
    print("ALL-TIME BACKTEST STATISTICS")
    print("=" * 80)

    total = int(df['total_trades'].iloc[0])
    wins = int(df['wins'].iloc[0])
    losses = int(df['losses'].iloc[0])
    win_rate = (wins / total * 100) if total > 0 else 0

    print(f"\nPeriod: {df['first_trade'].iloc[0]} to {df['last_trade'].iloc[0]}")
    print(f"\nTotal Trades: {total}")
    print(f"Winning Trades: {wins} ({win_rate:.1f}%)")
    print(f"Losing Trades: {losses} ({100-win_rate:.1f}%)")
    print(f"\nTotal P&L: ₹{df['total_pnl'].iloc[0]:,.2f}")
    print(f"Average P&L: ₹{df['avg_pnl'].iloc[0]:.2f}")
    print(f"Best Trade: ₹{df['max_profit'].iloc[0]:,.2f}")
    print(f"Worst Trade: ₹{df['max_loss'].iloc[0]:,.2f}")

    # Day of week analysis
    print("\n" + "-" * 80)
    print("DAY OF WEEK BREAKDOWN")
    print("-" * 80)

    query = '''
        SELECT
            day_of_week,
            COUNT(*) as trades,
            SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as wins,
            AVG(net_pnl) as avg_pnl,
            SUM(net_pnl) as total_pnl
        FROM backtest_trades
        GROUP BY day_of_week
        ORDER BY
            CASE day_of_week
                WHEN 'Monday' THEN 1
                WHEN 'Tuesday' THEN 2
                WHEN 'Wednesday' THEN 3
                WHEN 'Thursday' THEN 4
                WHEN 'Friday' THEN 5
            END
    '''

    day_df = pd.read_sql_query(query, conn)

    print(f"\n{'Day':<12} {'Trades':<8} {'Win Rate':<12} {'Avg P&L':<12} {'Total P&L':<12}")
    print("-" * 80)

    for _, row in day_df.iterrows():
        wr = (row['wins'] / row['trades'] * 100) if row['trades'] > 0 else 0
        print(f"{row['day_of_week']:<12} {int(row['trades']):<8} {wr:>5.1f}%{'':<6} ₹{row['avg_pnl']:>7.2f}{'':>4} ₹{row['total_pnl']:>8,.2f}")

    conn.close()

    print("\n" + "=" * 80)


def get_last_month_stats():
    """Get last month's statistics"""
    if not Path(DB_PATH).exists():
        print("❌ No backtest history database found.")
        return

    conn = sqlite3.connect(DB_PATH)

    one_month_ago = (datetime.now() - timedelta(days=30)).date()

    query = f'''
        SELECT *
        FROM backtest_trades
        WHERE trade_date >= '{one_month_ago}'
        ORDER BY trade_date DESC
    '''

    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print("❌ No trades in last month")
        return

    print("\n" + "=" * 80)
    print(f"LAST 30 DAYS BACKTEST RESULTS ({one_month_ago} onwards)")
    print("=" * 80)

    wins = len(df[df['net_pnl'] > 0])
    losses = len(df[df['net_pnl'] <= 0])
    total = len(df)
    win_rate = (wins / total * 100) if total > 0 else 0

    print(f"\nTotal Trades: {total}")
    print(f"Win Rate: {win_rate:.1f}% ({wins}/{total})")
    print(f"Total P&L: ₹{df['net_pnl'].sum():,.2f}")
    print(f"Avg P&L: ₹{df['net_pnl'].mean():.2f}")

    print("\n" + "-" * 80)
    print("RECENT TRADES")
    print("-" * 80)

    for _, row in df.head(10).iterrows():
        pnl_icon = "✅" if row['net_pnl'] > 0 else "❌"
        print(f"\n{row['trade_date']} ({row['day_of_week']})")
        print(f"  {pnl_icon} P&L: ₹{row['net_pnl']:.2f}")
        print(f"  NIFTY: {row['nifty_move_pct']:+.2f}% | DTE: {int(row['days_to_expiry'])}")

    print("\n" + "=" * 80)


def get_trends():
    """Show weekly trends"""
    if not Path(DB_PATH).exists():
        print("❌ No backtest history database found.")
        return

    conn = sqlite3.connect(DB_PATH)

    query = '''
        SELECT *
        FROM weekly_summaries
        ORDER BY week_start DESC
        LIMIT 10
    '''

    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print("❌ No weekly summaries found")
        return

    print("\n" + "=" * 80)
    print("WEEKLY PERFORMANCE TRENDS")
    print("=" * 80)

    print(f"\n{'Week':<22} {'Trades':<8} {'Win Rate':<12} {'Avg P&L':<12} {'Total P&L':<12}")
    print("-" * 80)

    for _, row in df.iterrows():
        week = f"{row['week_start']} to {row['week_end']}"
        print(f"{week:<22} {int(row['total_trades']):<8} {row['win_rate']:>5.1f}%{'':<6} ₹{row['avg_pnl']:>7.2f}{'':>4} ₹{row['total_pnl']:>8,.2f}")

    print("\n" + "=" * 80)


def get_losing_days():
    """Analyze all losing days"""
    if not Path(DB_PATH).exists():
        print("❌ No backtest history database found.")
        return

    conn = sqlite3.connect(DB_PATH)

    query = '''
        SELECT *
        FROM backtest_trades
        WHERE net_pnl <= 0
        ORDER BY net_pnl ASC
    '''

    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print("✅ No losing days! (This is unlikely - check data)")
        return

    print("\n" + "=" * 80)
    print(f"LOSING DAYS ANALYSIS ({len(df)} days)")
    print("=" * 80)

    print(f"\nTotal Losses: ₹{df['net_pnl'].sum():,.2f}")
    print(f"Average Loss: ₹{df['net_pnl'].mean():.2f}")
    print(f"Worst Loss: ₹{df['net_pnl'].min():,.2f}")

    # Analyze patterns
    print("\n" + "-" * 80)
    print("LOSS PATTERNS")
    print("-" * 80)

    print(f"\nAverage NIFTY move on losing days: {df['nifty_move_pct'].abs().mean():.2f}%")
    print(f"Average DTE on losing days: {df['days_to_expiry'].mean():.1f}")

    # Day of week
    print("\nLosses by day of week:")
    for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        day_losses = df[df['day_of_week'] == day]
        if not day_losses.empty:
            print(f"  {day}: {len(day_losses)} days, Total: ₹{day_losses['net_pnl'].sum():.2f}")

    print("\n" + "-" * 80)
    print("TOP 10 WORST LOSING DAYS")
    print("-" * 80)

    for i, (_, row) in enumerate(df.head(10).iterrows(), 1):
        print(f"\n{i}. {row['trade_date']} ({row['day_of_week']})")
        print(f"   Loss: ₹{row['net_pnl']:.2f}")
        print(f"   NIFTY Move: {row['nifty_move_pct']:+.2f}%")
        print(f"   DTE: {int(row['days_to_expiry'])}")
        print(f"   Entry: ₹{row['entry_straddle']:.2f} → Exit: ₹{row['exit_straddle']:.2f}")

    print("\n" + "=" * 80)


def export_to_csv():
    """Export all data to CSV"""
    if not Path(DB_PATH).exists():
        print("❌ No backtest history database found.")
        return

    conn = sqlite3.connect(DB_PATH)

    # Export trades
    df_trades = pd.read_sql_query('SELECT * FROM backtest_trades ORDER BY trade_date DESC', conn)
    output_file = "data/backtest_history_export.csv"
    df_trades.to_csv(output_file, index=False)

    print(f"✅ Exported {len(df_trades)} trades to {output_file}")

    conn.close()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='View Backtest History')
    parser.add_argument('--all-time', action='store_true', help='Show all-time statistics')
    parser.add_argument('--last-month', action='store_true', help='Show last month statistics')
    parser.add_argument('--trends', action='store_true', help='Show weekly trends')
    parser.add_argument('--losing-days', action='store_true', help='Analyze losing days')
    parser.add_argument('--export', action='store_true', help='Export data to CSV')

    args = parser.parse_args()

    # If no arguments, show all-time by default
    if not any(vars(args).values()):
        get_all_time_stats()
        return

    if args.all_time:
        get_all_time_stats()

    if args.last_month:
        get_last_month_stats()

    if args.trends:
        get_trends()

    if args.losing_days:
        get_losing_days()

    if args.export:
        export_to_csv()


if __name__ == "__main__":
    main()
