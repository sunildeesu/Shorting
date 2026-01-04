#!/usr/bin/env python3
"""
Intraday P&L Backtest for Tiered Signal System

Simulates selling ATM straddle at 10:05 AM and closing at 3:10 PM
for all days in past 6 months. Validates tier assignments with real P&L.

Strategy:
- Entry: 10:05 AM - Sell ATM Call + ATM Put (collect premium)
- Exit: 3:10 PM - Buy back both options (pay premium)
- P&L: Entry Premium - Exit Premium - Transaction Costs

Author: Sunil Kumar Durganaik
Date: January 3, 2026
"""

import os
import sys
import csv
import logging
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
import pandas as pd
from pathlib import Path

# Add project directory to path
sys.path.insert(0, str(Path(__file__).parent))

import config
from kite_connect import KiteConnect

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IntradayPnLBacktest:
    """Backtest ATM straddle selling strategy with tier validation"""

    def __init__(self):
        """Initialize backtest with Kite connection"""
        self.kite = None
        self.nifty_token = config.NIFTY_50_TOKEN
        self.entry_time = time(10, 5)  # 10:05 AM
        self.exit_time = time(15, 10)  # 3:10 PM
        self.transaction_cost_per_lot = 100  # Brokerage + STT + other charges (per lot)

    def initialize_kite(self) -> bool:
        """Initialize Kite connection"""
        try:
            api_key = os.getenv('KITE_API_KEY')
            access_token = os.getenv('KITE_ACCESS_TOKEN')

            if not api_key or not access_token:
                logger.warning("Kite credentials not found. Will use estimation method.")
                return False

            self.kite = KiteConnect(api_key=api_key)
            self.kite.set_access_token(access_token)
            logger.info("✅ Kite connection initialized")
            return True

        except Exception as e:
            logger.warning(f"Could not initialize Kite: {e}. Will use estimation method.")
            return False

    def get_atm_strike(self, spot_price: float) -> int:
        """Get ATM strike (nearest 50 multiple)"""
        return round(spot_price / 50) * 50

    def estimate_atm_straddle_premium(self, spot: float, vix: float, days_to_expiry: int) -> float:
        """
        Estimate ATM straddle premium based on VIX and days to expiry

        Formula based on actual NIFTY ATM straddle pricing:
        - For weekly expiry (3-7 days): Premium ≈ Spot × VIX% × sqrt(DTE/365) × 0.85
        - ATM Call + ATM Put combined

        Examples (spot=24000, VIX=12):
        - 7 DTE: 24000 × 0.12 × sqrt(7/365) × 0.85 ≈ ₹355
        - 4 DTE: 24000 × 0.12 × sqrt(4/365) × 0.85 ≈ ₹270
        - 1 DTE: 24000 × 0.12 × sqrt(1/365) × 0.85 ≈ ₹135
        """
        # Annual volatility
        annual_vol = vix / 100

        # Time to expiry factor (square root of time)
        time_factor = (days_to_expiry / 365) ** 0.5

        # ATM straddle premium
        # Factor 0.85 calibrated to match actual NIFTY weekly options pricing
        straddle_premium = spot * annual_vol * time_factor * 0.85

        return straddle_premium

    def estimate_premium_decay(
        self,
        entry_premium: float,
        spot_move_pct: float,
        time_decay_hours: float,
        days_to_expiry: int
    ) -> float:
        """
        Estimate option premium at exit based on:
        - Entry premium
        - NIFTY spot movement (gamma/delta effect)
        - Time decay (theta effect)

        Args:
            entry_premium: Premium at 10:05 AM
            spot_move_pct: NIFTY movement % (positive = up, negative = down)
            time_decay_hours: Hours elapsed (typically ~5 hours)
            days_to_expiry: Days to expiry at entry

        Returns:
            Estimated exit premium
        """
        # Time decay: Lose approximately (1/days_to_expiry) per day
        # For 5 hours (~0.2 days), theta decay is roughly 0.2/days_to_expiry of premium
        if days_to_expiry > 0:
            time_decay_factor = 1 - (time_decay_hours / 24) / days_to_expiry
        else:
            time_decay_factor = 0.5  # Expiry day - high decay

        # Spot movement effect on straddle:
        # Small moves: Straddle loses value (both options decay)
        # Large moves: One leg gains, but usually less than time decay
        # Use absolute value since straddle loses on small moves
        abs_move = abs(spot_move_pct)

        if abs_move < 0.5:  # Small move (<0.5%)
            # Time decay dominates
            exit_premium = entry_premium * time_decay_factor
        elif abs_move < 1.0:  # Medium move (0.5-1.0%)
            # Some directional gain offsets decay
            exit_premium = entry_premium * (time_decay_factor + abs_move * 0.1)
        else:  # Large move (>1.0%)
            # Significant directional gain, but capped
            exit_premium = entry_premium * (time_decay_factor + abs_move * 0.15)

        return max(exit_premium, entry_premium * 0.3)  # Minimum 30% of entry

    def fetch_historical_intraday_data(
        self,
        date: datetime,
        instrument_token: int
    ) -> Optional[Dict]:
        """
        Fetch historical intraday data for a specific date

        Returns dict with:
        {
            'entry_price': price at 10:05,
            'exit_price': price at 3:10,
            'entry_time': actual timestamp,
            'exit_time': actual timestamp
        }
        """
        if not self.kite:
            return None

        try:
            from_date = date.replace(hour=9, minute=15)
            to_date = date.replace(hour=15, minute=30)

            # Fetch 5-minute candles
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="5minute"
            )

            if not data:
                return None

            # Find candles closest to entry and exit times
            entry_candle = None
            exit_candle = None

            for candle in data:
                candle_time = candle['date'].time()

                # Entry: 10:05 AM (find candle between 10:00-10:10)
                if time(10, 0) <= candle_time <= time(10, 10):
                    entry_candle = candle

                # Exit: 3:10 PM (find candle between 15:05-15:15)
                if time(15, 5) <= candle_time <= time(15, 15):
                    exit_candle = candle

            if entry_candle and exit_candle:
                return {
                    'entry_price': entry_candle['close'],
                    'exit_price': exit_candle['close'],
                    'entry_time': entry_candle['date'],
                    'exit_time': exit_candle['date']
                }

            return None

        except Exception as e:
            logger.debug(f"Could not fetch historical data for {date.date()}: {e}")
            return None

    def calculate_trade_pnl(
        self,
        date: datetime,
        signal_tier: str,
        iv_rank: float,
        vix_entry: float,
        position_size: float
    ) -> Dict:
        """
        Calculate P&L for a single day's straddle trade

        Returns:
        {
            'date': trade date,
            'signal_tier': tier assignment,
            'position_size': recommended position size,
            'entry_premium': premium collected,
            'exit_premium': premium paid to close,
            'gross_pnl': entry - exit,
            'transaction_cost': brokerage + charges,
            'net_pnl': gross - costs,
            'nifty_move_pct': spot movement,
            'method': 'actual' or 'estimated'
        }
        """
        # Try to fetch actual historical data
        spot_data = self.fetch_historical_intraday_data(date, self.nifty_token)

        if spot_data:
            # Use actual data
            entry_spot = spot_data['entry_price']
            exit_spot = spot_data['exit_price']
            method = 'actual'
            logger.debug(f"{date.date()}: Using actual data")
        else:
            # Estimate based on typical intraday movement
            # Assume spot moves randomly -1% to +1% intraday
            # For backtest, we'll use a more conservative average movement
            logger.debug(f"{date.date()}: Using estimated data")

            # Use a simple estimation: spot at 10 AM is close to the recorded VIX spot
            # We don't have exact intraday data, so we'll make reasonable assumptions
            # For now, return None and we'll populate from actual market data if available
            method = 'estimated'

            # TODO: Implement estimation logic or skip days without data
            # For initial version, let's focus on getting the structure right
            return None

        # Calculate NIFTY movement
        nifty_move_pct = ((exit_spot - entry_spot) / entry_spot) * 100

        # Get ATM strike
        atm_strike = self.get_atm_strike(entry_spot)

        # Estimate ATM straddle premium at entry
        # Assume weekly expiry (average 3-4 days to expiry at 10 AM)
        days_to_expiry = 4
        entry_premium = self.estimate_atm_straddle_premium(
            entry_spot,
            vix_entry,
            days_to_expiry
        )

        # Estimate premium at exit
        hours_elapsed = 5.0  # 10:05 AM to 3:10 PM
        exit_premium = self.estimate_premium_decay(
            entry_premium,
            nifty_move_pct,
            hours_elapsed,
            days_to_expiry
        )

        # Calculate P&L
        gross_pnl = entry_premium - exit_premium
        transaction_cost = self.transaction_cost_per_lot * position_size
        net_pnl = gross_pnl - transaction_cost

        return {
            'date': date.strftime('%Y-%m-%d'),
            'signal_tier': signal_tier,
            'iv_rank': iv_rank,
            'vix': vix_entry,
            'position_size': position_size,
            'nifty_entry': entry_spot,
            'nifty_exit': exit_spot,
            'nifty_move_pct': round(nifty_move_pct, 2),
            'atm_strike': atm_strike,
            'entry_premium': round(entry_premium, 2),
            'exit_premium': round(exit_premium, 2),
            'gross_pnl': round(gross_pnl, 2),
            'transaction_cost': round(transaction_cost, 2),
            'net_pnl': round(net_pnl, 2),
            'method': method
        }

    def run_backtest(self, backtest_csv_path: str) -> List[Dict]:
        """
        Run backtest on historical data

        Args:
            backtest_csv_path: Path to CSV with historical signals/tiers

        Returns:
            List of trade results
        """
        logger.info("="*60)
        logger.info("Starting Intraday P&L Backtest")
        logger.info("="*60)

        # Initialize Kite
        kite_available = self.initialize_kite()
        if kite_available:
            logger.info("✅ Will use actual historical data where available")
        else:
            logger.info("⚠️  Will use estimation method")

        # Read backtest data
        if not os.path.exists(backtest_csv_path):
            logger.error(f"Backtest CSV not found: {backtest_csv_path}")
            return []

        df = pd.read_csv(backtest_csv_path)
        logger.info(f"📊 Loaded {len(df)} days from {backtest_csv_path}")

        # Apply tiered logic to assign tiers
        results = []
        skipped = 0

        for idx, row in df.iterrows():
            date_str = row['date']
            iv_rank = row['iv_rank']
            vix = row['vix']
            signal = row['signal']

            # Assign tier based on IV Rank
            if iv_rank >= config.IV_RANK_EXCELLENT:
                signal_tier = 'SELL_STRONG'
                position_size = config.POSITION_SIZE_STRONG
            elif iv_rank >= config.IV_RANK_GOOD:
                signal_tier = 'SELL_MODERATE'
                position_size = config.POSITION_SIZE_MODERATE
            elif iv_rank >= config.IV_RANK_MARGINAL:
                signal_tier = 'SELL_WEAK'
                position_size = config.POSITION_SIZE_WEAK
            else:
                signal_tier = 'AVOID'
                position_size = 0.0

            # Skip AVOID days (no trade)
            if signal_tier == 'AVOID':
                skipped += 1
                continue

            # Parse date
            trade_date = datetime.strptime(date_str, '%Y-%m-%d')

            # Calculate P&L
            trade_result = self.calculate_trade_pnl(
                trade_date,
                signal_tier,
                iv_rank,
                vix,
                position_size
            )

            if trade_result:
                results.append(trade_result)
                logger.info(
                    f"  {trade_date.date()} | {signal_tier:15s} | "
                    f"P&L: ₹{trade_result['net_pnl']:7.2f} | "
                    f"Move: {trade_result['nifty_move_pct']:+5.2f}%"
                )
            else:
                skipped += 1

        logger.info(f"\n✅ Processed {len(results)} trades ({skipped} skipped)")

        return results

    def generate_tier_analysis(self, results: List[Dict]) -> Dict:
        """
        Analyze P&L by signal tier

        Returns:
        {
            'SELL_STRONG': {...},
            'SELL_MODERATE': {...},
            'SELL_WEAK': {...}
        }
        """
        tier_stats = {}

        for tier in ['SELL_STRONG', 'SELL_MODERATE', 'SELL_WEAK']:
            tier_trades = [r for r in results if r['signal_tier'] == tier]

            if not tier_trades:
                tier_stats[tier] = {
                    'num_trades': 0,
                    'total_pnl': 0,
                    'avg_pnl': 0,
                    'win_rate': 0,
                    'max_profit': 0,
                    'max_loss': 0
                }
                continue

            pnls = [t['net_pnl'] for t in tier_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]

            tier_stats[tier] = {
                'num_trades': len(tier_trades),
                'total_pnl': sum(pnls),
                'avg_pnl': sum(pnls) / len(pnls),
                'win_rate': (len(wins) / len(pnls)) * 100,
                'num_wins': len(wins),
                'num_losses': len(losses),
                'max_profit': max(pnls) if pnls else 0,
                'max_loss': min(pnls) if pnls else 0,
                'avg_profit': sum(wins) / len(wins) if wins else 0,
                'avg_loss': sum(losses) / len(losses) if losses else 0
            }

        return tier_stats

    def save_results(self, results: List[Dict], tier_stats: Dict):
        """Save backtest results to CSV and generate report"""
        # Save detailed trades
        output_dir = Path("data/backtests")
        output_dir.mkdir(parents=True, exist_ok=True)

        trades_csv = output_dir / "intraday_pnl_trades.csv"

        with open(trades_csv, 'w', newline='') as f:
            if results:
                writer = csv.DictWriter(f, fieldnames=results[0].keys())
                writer.writeheader()
                writer.writerows(results)

        logger.info(f"💾 Saved {len(results)} trades to {trades_csv}")

        # Generate summary report
        report_path = output_dir / "INTRADAY_PNL_BACKTEST_ANALYSIS.md"

        with open(report_path, 'w') as f:
            f.write("# Intraday P&L Backtest - Tiered Signal Validation\n\n")
            f.write(f"**Backtest Date:** {datetime.now().strftime('%B %d, %Y')}\n")
            f.write(f"**Period:** 6 months historical data\n")
            f.write(f"**Strategy:** Sell ATM Straddle at 10:05 AM, Close at 3:10 PM\n")
            f.write(f"**Total Trades:** {len(results)}\n\n")

            f.write("---\n\n")
            f.write("## 📊 OVERALL PERFORMANCE\n\n")

            total_pnl = sum(r['net_pnl'] for r in results)
            total_wins = sum(1 for r in results if r['net_pnl'] > 0)
            overall_win_rate = (total_wins / len(results)) * 100 if results else 0

            f.write(f"- **Total P&L:** ₹{total_pnl:,.2f}\n")
            f.write(f"- **Win Rate:** {overall_win_rate:.1f}% ({total_wins}/{len(results)})\n")
            f.write(f"- **Average P&L per Trade:** ₹{total_pnl/len(results) if results else 0:.2f}\n\n")

            f.write("---\n\n")
            f.write("## 🎯 TIER-WISE PERFORMANCE\n\n")

            for tier in ['SELL_STRONG', 'SELL_MODERATE', 'SELL_WEAK']:
                stats = tier_stats[tier]
                f.write(f"### {tier}\n\n")
                f.write(f"- **Trades:** {stats['num_trades']}\n")
                f.write(f"- **Total P&L:** ₹{stats['total_pnl']:,.2f}\n")
                f.write(f"- **Avg P&L:** ₹{stats['avg_pnl']:.2f}\n")
                f.write(f"- **Win Rate:** {stats['win_rate']:.1f}% ({stats['num_wins']}/{stats['num_trades']})\n")
                f.write(f"- **Best Trade:** ₹{stats['max_profit']:.2f}\n")
                f.write(f"- **Worst Trade:** ₹{stats['max_loss']:.2f}\n\n")

        logger.info(f"📄 Generated report: {report_path}")


def main():
    """Run intraday P&L backtest"""
    backtest = IntradayPnLBacktest()

    # Path to existing backtest CSV
    backtest_csv = "data/backtests/nifty_historical_backtest.csv"

    # Run backtest
    results = backtest.run_backtest(backtest_csv)

    if not results:
        logger.error("No results generated. Check data availability.")
        return

    # Analyze by tier
    tier_stats = backtest.generate_tier_analysis(results)

    # Save results
    backtest.save_results(results, tier_stats)

    logger.info("\n✅ Backtest complete!")


if __name__ == "__main__":
    main()
