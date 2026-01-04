#!/usr/bin/env python3
"""
Weekly Backtest Runner - Automated Real Option Data Analysis

Runs every week to:
1. Backtest past 7 days with REAL option data
2. Append results to master database
3. Generate trend analysis
4. Send alerts if performance degrades

Author: Sunil Kumar Durganaik
Date: January 3, 2026
"""

import os
import sys
import logging
import sqlite3
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from kiteconnect import KiteConnect
from token_manager import TokenManager
from market_utils import is_nse_holiday
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WeeklyBacktestRunner:
    """Automated weekly backtest with historical tracking"""

    def __init__(self):
        """Initialize runner"""
        self.token_manager = TokenManager()
        self.kite = None
        self.db_path = "data/backtest_history.db"

        # Create data directory
        Path("data").mkdir(exist_ok=True)

        # Initialize database
        self._init_database()

    def _init_database(self):
        """Create SQLite database for storing backtest history"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backtest_date DATE NOT NULL,
                trade_date DATE NOT NULL,
                day_of_week TEXT,
                nifty_entry REAL,
                nifty_exit REAL,
                nifty_move REAL,
                nifty_move_pct REAL,
                atm_strike INTEGER,
                expiry DATE,
                days_to_expiry INTEGER,
                ce_symbol TEXT,
                pe_symbol TEXT,
                ce_entry REAL,
                pe_entry REAL,
                entry_straddle REAL,
                ce_exit REAL,
                pe_exit REAL,
                exit_straddle REAL,
                premium_collected REAL,
                premium_paid REAL,
                gross_pnl REAL,
                transaction_cost REAL,
                net_pnl REAL,
                data_source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create weekly summary table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weekly_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start DATE NOT NULL,
                week_end DATE NOT NULL,
                total_trades INTEGER,
                winning_trades INTEGER,
                losing_trades INTEGER,
                win_rate REAL,
                total_pnl REAL,
                avg_pnl REAL,
                max_profit REAL,
                max_loss REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()
        logger.info(f"✅ Database initialized: {self.db_path}")

    def initialize_kite(self) -> bool:
        """Initialize Kite Connect"""
        try:
            self.kite = KiteConnect(api_key=config.KITE_API_KEY)
            self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

            profile = self.kite.profile()
            logger.info(f"✅ Connected to Kite as: {profile.get('user_name', 'Unknown')}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Kite: {e}")
            return False

    def run_weekly_backtest(self) -> List[Dict]:
        """
        Run backtest for past 7 days

        Returns:
            List of trade results
        """
        logger.info("=" * 80)
        logger.info("WEEKLY BACKTEST - Past 7 Days with REAL Option Data")
        logger.info("=" * 80)

        # Import the real backtest class
        from backtest_real_option_data import RealOptionBacktest

        backtest = RealOptionBacktest()
        results = backtest.run_backtest(days_back=7)

        return results

    def save_to_database(self, results: List[Dict], backtest_date: datetime):
        """
        Save backtest results to database

        Args:
            results: List of trade results
            backtest_date: Date when backtest was run
        """
        if not results:
            logger.warning("No results to save")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Insert trades
        for result in results:
            cursor.execute('''
                INSERT INTO backtest_trades (
                    backtest_date, trade_date, day_of_week, nifty_entry, nifty_exit,
                    nifty_move, nifty_move_pct, atm_strike, expiry, days_to_expiry,
                    ce_symbol, pe_symbol, ce_entry, pe_entry, entry_straddle,
                    ce_exit, pe_exit, exit_straddle, premium_collected, premium_paid,
                    gross_pnl, transaction_cost, net_pnl, data_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                backtest_date.date(),
                result['date'],
                result['day_of_week'],
                result['nifty_entry'],
                result['nifty_exit'],
                result['nifty_move'],
                result['nifty_move_pct'],
                result['atm_strike'],
                result['expiry'],
                result['days_to_expiry'],
                result['ce_symbol'],
                result['pe_symbol'],
                result['ce_entry'],
                result['pe_entry'],
                result['entry_straddle'],
                result['ce_exit'],
                result['pe_exit'],
                result['exit_straddle'],
                result['premium_collected'],
                result['premium_paid'],
                result['gross_pnl'],
                result['transaction_cost'],
                result['net_pnl'],
                result['data_source']
            ))

        conn.commit()
        conn.close()

        logger.info(f"✅ Saved {len(results)} trades to database")

    def generate_weekly_summary(self, results: List[Dict]) -> Dict:
        """Generate summary for this week's backtest"""
        if not results:
            return {}

        df = pd.DataFrame(results)

        total_trades = len(df)
        winning_trades = len(df[df['net_pnl'] > 0])
        losing_trades = len(df[df['net_pnl'] <= 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        return {
            'week_start': results[0]['date'],
            'week_end': results[-1]['date'],
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_pnl': df['net_pnl'].sum(),
            'avg_pnl': df['net_pnl'].mean(),
            'max_profit': df['net_pnl'].max(),
            'max_loss': df['net_pnl'].min()
        }

    def save_weekly_summary(self, summary: Dict):
        """Save weekly summary to database"""
        if not summary:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO weekly_summaries (
                week_start, week_end, total_trades, winning_trades, losing_trades,
                win_rate, total_pnl, avg_pnl, max_profit, max_loss
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            summary['week_start'],
            summary['week_end'],
            summary['total_trades'],
            summary['winning_trades'],
            summary['losing_trades'],
            summary['win_rate'],
            summary['total_pnl'],
            summary['avg_pnl'],
            summary['max_profit'],
            summary['max_loss']
        ))

        conn.commit()
        conn.close()

        logger.info("✅ Saved weekly summary to database")

    def get_trend_analysis(self) -> Dict:
        """Analyze trends over all historical backtests"""
        conn = sqlite3.connect(self.db_path)

        # Get all-time stats
        query = '''
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN net_pnl <= 0 THEN 1 ELSE 0 END) as losses,
                AVG(net_pnl) as avg_pnl,
                SUM(net_pnl) as total_pnl,
                MAX(net_pnl) as max_profit,
                MIN(net_pnl) as max_loss
            FROM backtest_trades
        '''

        df = pd.read_sql_query(query, conn)

        all_time = {
            'total_trades': int(df['total_trades'].iloc[0]),
            'wins': int(df['wins'].iloc[0]),
            'losses': int(df['losses'].iloc[0]),
            'win_rate': (df['wins'].iloc[0] / df['total_trades'].iloc[0] * 100) if df['total_trades'].iloc[0] > 0 else 0,
            'avg_pnl': df['avg_pnl'].iloc[0],
            'total_pnl': df['total_pnl'].iloc[0],
            'max_profit': df['max_profit'].iloc[0],
            'max_loss': df['max_loss'].iloc[0]
        }

        # Get last 4 weeks trend
        query = '''
            SELECT week_start, week_end, win_rate, total_pnl, avg_pnl
            FROM weekly_summaries
            ORDER BY week_start DESC
            LIMIT 4
        '''

        weekly_trend = pd.read_sql_query(query, conn)

        conn.close()

        return {
            'all_time': all_time,
            'weekly_trend': weekly_trend
        }

    def generate_report(self, results: List[Dict], summary: Dict, trends: Dict):
        """Generate comprehensive weekly report"""
        report_dir = Path("data/weekly_reports")
        report_dir.mkdir(exist_ok=True)

        report_date = datetime.now().strftime('%Y-%m-%d')
        report_path = report_dir / f"weekly_backtest_{report_date}.md"

        with open(report_path, 'w') as f:
            f.write(f"# Weekly Backtest Report - {datetime.now().strftime('%B %d, %Y')}\n\n")
            f.write(f"**Period:** {summary['week_start']} to {summary['week_end']}\n")
            f.write(f"**Data Source:** REAL option prices from Kite Connect\n\n")

            f.write("---\n\n")
            f.write("## 📊 THIS WEEK'S PERFORMANCE\n\n")

            f.write(f"- **Total Trades:** {summary['total_trades']}\n")
            f.write(f"- **Winning Trades:** {summary['winning_trades']} ({summary['win_rate']:.1f}%)\n")
            f.write(f"- **Losing Trades:** {summary['losing_trades']}\n")
            f.write(f"- **Total P&L:** ₹{summary['total_pnl']:,.2f}\n")
            f.write(f"- **Average P&L:** ₹{summary['avg_pnl']:.2f}\n")
            f.write(f"- **Best Trade:** ₹{summary['max_profit']:,.2f}\n")
            f.write(f"- **Worst Trade:** ₹{summary['max_loss']:,.2f}\n\n")

            f.write("---\n\n")
            f.write("## 📈 ALL-TIME PERFORMANCE\n\n")

            all_time = trends['all_time']
            f.write(f"- **Total Trades (All Time):** {all_time['total_trades']}\n")
            f.write(f"- **Win Rate (All Time):** {all_time['win_rate']:.1f}%\n")
            f.write(f"- **Total P&L (All Time):** ₹{all_time['total_pnl']:,.2f}\n")
            f.write(f"- **Avg P&L (All Time):** ₹{all_time['avg_pnl']:.2f}\n\n")

            f.write("---\n\n")
            f.write("## 📅 4-WEEK TREND\n\n")

            if not trends['weekly_trend'].empty:
                f.write("| Week | Win Rate | Total P&L | Avg P&L |\n")
                f.write("|------|----------|-----------|----------|\n")

                for _, row in trends['weekly_trend'].iterrows():
                    f.write(f"| {row['week_start']} to {row['week_end']} | {row['win_rate']:.1f}% | ₹{row['total_pnl']:,.2f} | ₹{row['avg_pnl']:.2f} |\n")

            f.write("\n---\n\n")
            f.write("## 📋 THIS WEEK'S TRADES\n\n")

            for result in results:
                pnl_icon = "✅" if result['net_pnl'] > 0 else "❌"
                f.write(f"### {result['date']} ({result['day_of_week']})\n")
                f.write(f"**{pnl_icon} P&L: ₹{result['net_pnl']:.2f}**\n\n")
                f.write(f"- NIFTY: {result['nifty_entry']:.2f} → {result['nifty_exit']:.2f} ({result['nifty_move_pct']:+.2f}%)\n")
                f.write(f"- Strike: {result['atm_strike']} ({result['days_to_expiry']} DTE)\n")
                f.write(f"- Entry: ₹{result['entry_straddle']:.2f}, Exit: ₹{result['exit_straddle']:.2f}\n\n")

        logger.info(f"📄 Generated report: {report_path}")
        return report_path

    def send_alert(self, summary: Dict, trends: Dict, report_path: Path):
        """Send Telegram alert with weekly summary"""
        try:
            # Check if Telegram is configured
            if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHANNEL_ID:
                logger.warning("Telegram not configured, skipping alert")
                return

            all_time = trends['all_time']

            # Build message with PURPLE color badge and UNIQUE STYLE for backtest
            message = f"🟣🟣🟣 <b><u>WEEKLY BACKTEST REPORT</u></b> 🟣🟣🟣\n"
            message += "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n"
            message += f"<b>Period:</b> {summary['week_start']} to {summary['week_end']}\n"
            message += "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n\n"

            message += f"<b>THIS WEEK:</b>\n"
            message += f"   • Win Rate: <b>{summary['win_rate']:.1f}%</b>\n"
            message += f"   • Total P&L: <b>₹{summary['total_pnl']:,.2f}</b>\n"
            message += f"   • Avg P&L: ₹{summary['avg_pnl']:.2f}\n\n"

            message += f"<b>ALL TIME:</b>\n"
            message += f"   • Win Rate: <b>{all_time['win_rate']:.1f}%</b>\n"
            message += f"   • Total Trades: {all_time['total_trades']}\n"
            message += f"   • Cumulative P&L: <b>₹{all_time['total_pnl']:,.2f}</b>\n\n"

            # Alert if performance is degrading
            if summary['win_rate'] < 60:
                message += "⚠️ WARNING: Win rate below 60%!\n"

            if summary['total_pnl'] < -1000:
                message += "🚨 ALERT: Weekly loss >₹1000!\n"

            message += f"\nFull report: {report_path}"

            # Send message
            url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': config.TELEGRAM_CHANNEL_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, json=payload)
            response.raise_for_status()

            logger.info("✅ Telegram alert sent")

        except Exception as e:
            logger.warning(f"Failed to send Telegram alert: {e} (continuing anyway)")

    def run(self):
        """Run weekly backtest workflow"""
        logger.info("\n" + "=" * 80)
        logger.info("STARTING WEEKLY BACKTEST")
        logger.info("=" * 80)

        backtest_date = datetime.now()

        # Step 1: Run backtest
        logger.info("\nStep 1: Running backtest for past 7 days...")
        results = self.run_weekly_backtest()

        if not results:
            logger.error("No results from backtest")
            return

        # Step 2: Save to database
        logger.info("\nStep 2: Saving results to database...")
        self.save_to_database(results, backtest_date)

        # Step 3: Generate summary
        logger.info("\nStep 3: Generating weekly summary...")
        summary = self.generate_weekly_summary(results)
        self.save_weekly_summary(summary)

        # Step 4: Get trends
        logger.info("\nStep 4: Analyzing trends...")
        trends = self.get_trend_analysis()

        # Step 5: Generate report
        logger.info("\nStep 5: Generating report...")
        report_path = self.generate_report(results, summary, trends)

        # Step 6: Send alert
        logger.info("\nStep 6: Sending Telegram alert...")
        self.send_alert(summary, trends, report_path)

        logger.info("\n" + "=" * 80)
        logger.info("✅ WEEKLY BACKTEST COMPLETE")
        logger.info("=" * 80)

        # Print summary
        print("\n" + "=" * 80)
        print("WEEKLY SUMMARY")
        print("=" * 80)
        print(f"Period: {summary['week_start']} to {summary['week_end']}")
        print(f"Win Rate: {summary['win_rate']:.1f}% ({summary['winning_trades']}/{summary['total_trades']})")
        print(f"Total P&L: ₹{summary['total_pnl']:,.2f}")
        print(f"Avg P&L: ₹{summary['avg_pnl']:.2f}")
        print(f"\nAll-Time Win Rate: {trends['all_time']['win_rate']:.1f}%")
        print(f"All-Time Total P&L: ₹{trends['all_time']['total_pnl']:,.2f}")
        print("=" * 80)


def main():
    """Main entry point"""
    runner = WeeklyBacktestRunner()
    runner.run()


if __name__ == "__main__":
    main()
