#!/usr/bin/env python3
"""
Historical Backtest for NIFTY Option Selling Signals

Uses ACTUAL historical data for each day (not live quotes).
Properly calculates IV Rank as it would have been on each specific day.

Usage:
    python3 backtest_nifty_historical.py --days 180

Author: Sunil Kumar Durganaik
"""

import sys
import logging
import argparse
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
from typing import List, Dict
import pandas as pd

import config
from token_manager import TokenManager
from market_utils import is_nse_holiday

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class HistoricalBacktest:
    """Historical backtest using actual historical data"""

    def __init__(self):
        """Initialize backtest"""
        self.token_manager = TokenManager()
        self.kite = None

    def _initialize_kite(self) -> bool:
        """Initialize Kite Connect"""
        try:
            # Just try to connect - don't check expiry for backtest
            self.kite = KiteConnect(api_key=config.KITE_API_KEY)
            self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

            profile = self.kite.profile()
            logger.info(f"Connected to Kite as: {profile.get('user_name', 'Unknown')}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Kite: {e}")
            return False

    def get_historical_vix(self, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """
        Fetch historical VIX data

        Returns:
            DataFrame with date and VIX close prices
        """
        try:
            vix_data = self.kite.historical_data(
                instrument_token=config.INDIA_VIX_TOKEN,
                from_date=start_date,
                to_date=end_date,
                interval='day'
            )

            df = pd.DataFrame(vix_data)
            df['date'] = pd.to_datetime(df['date']).dt.date
            return df[['date', 'close']].rename(columns={'close': 'vix'})

        except Exception as e:
            logger.error(f"Error fetching historical VIX: {e}")
            return pd.DataFrame()

    def calculate_iv_rank(self, current_vix: float, historical_vix: List[float]) -> float:
        """
        Calculate IV Rank (percentile)

        Args:
            current_vix: VIX on the day being tested
            historical_vix: List of VIX values for past year

        Returns:
            IV Rank as percentage (0-100)
        """
        if not historical_vix or len(historical_vix) < 100:
            return 50.0  # Default to neutral

        values_below = sum(1 for v in historical_vix if v < current_vix)
        iv_rank = (values_below / len(historical_vix)) * 100
        return iv_rank

    def run_backtest(self, days: int = 30) -> pd.DataFrame:
        """
        Run historical backtest

        Args:
            days: Number of calendar days to backtest

        Returns:
            DataFrame with results
        """
        if not self.kite:
            if not self._initialize_kite():
                logger.error("Cannot run backtest - Kite initialization failed")
                return pd.DataFrame()

        logger.info("=" * 80)
        logger.info(f"HISTORICAL BACKTEST - Last {days} Days")
        logger.info("=" * 80)

        # Fetch all VIX data needed (backtest period + 1 year lookback for IV Rank)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days + 400)  # Extra for lookback

        logger.info(f"Fetching VIX data from {start_date.date()} to {end_date.date()}...")
        vix_df = self.get_historical_vix(start_date, end_date)

        if vix_df.empty:
            logger.error("Failed to fetch VIX data")
            return pd.DataFrame()

        logger.info(f"Fetched {len(vix_df)} days of VIX data")

        # Get trading days to test
        test_start = end_date - timedelta(days=days)
        trading_days = []
        current = test_start.date()

        while current <= end_date.date():
            if current.weekday() < 5 and not is_nse_holiday(current):
                trading_days.append(current)
            current += timedelta(days=1)

        logger.info(f"Testing {len(trading_days)} trading days")

        results = []

        for i, test_date in enumerate(trading_days, 1):
            logger.info(f"\n[{i}/{len(trading_days)}] Testing: {test_date.strftime('%Y-%m-%d (%A)')}")

            try:
                # Get VIX on this specific day
                vix_row = vix_df[vix_df['date'] == test_date]

                if vix_row.empty:
                    logger.warning(f"  No VIX data for {test_date}, skipping")
                    continue

                current_vix = vix_row.iloc[0]['vix']

                # Get 1-year historical VIX for IV Rank calculation
                lookback_start = test_date - timedelta(days=365)
                historical_vix_df = vix_df[(vix_df['date'] >= lookback_start) & (vix_df['date'] < test_date)]
                historical_vix = historical_vix_df['vix'].tolist()

                # Calculate IV Rank as it would have been on that day
                iv_rank = self.calculate_iv_rank(current_vix, historical_vix)

                # Determine signal based on IV Rank hard veto
                if iv_rank < config.IV_RANK_HARD_VETO_THRESHOLD:
                    signal = 'AVOID'
                    veto_type = 'IV_RANK_TOO_LOW'
                    score = 0
                else:
                    # Would need full analysis - for now mark as potential SELL
                    signal = 'POTENTIAL_SELL'
                    veto_type = None
                    score = 75  # Approximate

                # Get VIX stats
                vix_min = min(historical_vix) if historical_vix else current_vix
                vix_max = max(historical_vix) if historical_vix else current_vix
                vix_median = sorted(historical_vix)[len(historical_vix)//2] if historical_vix else current_vix

                results.append({
                    'date': test_date,
                    'vix': current_vix,
                    'iv_rank': iv_rank,
                    'vix_1y_min': vix_min,
                    'vix_1y_max': vix_max,
                    'vix_1y_median': vix_median,
                    'signal': signal,
                    'veto_type': veto_type,
                    'score': score
                })

                # Log result
                if signal == 'AVOID':
                    logger.info(f"  🚫 AVOID - IV Rank {iv_rank:.1f}% < {config.IV_RANK_HARD_VETO_THRESHOLD}% (VIX {current_vix:.2f})")
                else:
                    logger.info(f"  ✅ POTENTIAL_SELL - IV Rank {iv_rank:.1f}% (VIX {current_vix:.2f})")

            except Exception as e:
                logger.error(f"  Error analyzing {test_date}: {e}")
                continue

        df = pd.DataFrame(results)
        return df

    def generate_report(self, df: pd.DataFrame) -> None:
        """Generate backtest report"""
        logger.info("\n" + "=" * 80)
        logger.info("BACKTEST SUMMARY")
        logger.info("=" * 80)

        total_days = len(df)
        avoid_days = len(df[df['signal'] == 'AVOID'])
        potential_sell_days = len(df[df['signal'] == 'POTENTIAL_SELL'])

        logger.info(f"\nTotal Trading Days: {total_days}")
        logger.info(f"AVOID signals: {avoid_days} ({avoid_days/total_days*100:.1f}%)")
        logger.info(f"POTENTIAL SELL signals: {potential_sell_days} ({potential_sell_days/total_days*100:.1f}%)")

        # IV Rank statistics
        logger.info("\n" + "=" * 80)
        logger.info("IV RANK STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Average IV Rank: {df['iv_rank'].mean():.1f}%")
        logger.info(f"Min IV Rank: {df['iv_rank'].min():.1f}% (on {df.loc[df['iv_rank'].idxmin(), 'date']})")
        logger.info(f"Max IV Rank: {df['iv_rank'].max():.1f}% (on {df.loc[df['iv_rank'].idxmax(), 'date']})")

        logger.info(f"\nDays with IV Rank < 15%: {len(df[df['iv_rank'] < 15])}")
        logger.info(f"Days with IV Rank 15-25%: {len(df[(df['iv_rank'] >= 15) & (df['iv_rank'] < 25)])}")
        logger.info(f"Days with IV Rank 25-50%: {len(df[(df['iv_rank'] >= 25) & (df['iv_rank'] < 50)])}")
        logger.info(f"Days with IV Rank > 50%: {len(df[df['iv_rank'] >= 50])}")
        logger.info(f"Days with IV Rank > 75%: {len(df[df['iv_rank'] >= 75])}")

        # Show POTENTIAL SELL days
        if potential_sell_days > 0:
            logger.info("\n" + "=" * 80)
            logger.info(f"POTENTIAL SELL DAYS ({potential_sell_days} days)")
            logger.info("=" * 80)

            sell_df = df[df['signal'] == 'POTENTIAL_SELL'].sort_values('date')
            for _, row in sell_df.iterrows():
                logger.info(f"\n📅 {row['date'].strftime('%Y-%m-%d (%A)')}")
                logger.info(f"  VIX: {row['vix']:.2f}")
                logger.info(f"  IV Rank: {row['iv_rank']:.1f}%")
                logger.info(f"  1Y VIX Range: {row['vix_1y_min']:.2f} - {row['vix_1y_max']:.2f} (median: {row['vix_1y_median']:.2f})")

        logger.info("\n" + "=" * 80)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Historical Backtest for NIFTY Options')
    parser.add_argument('--days', type=int, default=180, help='Days to backtest (default: 180)')
    parser.add_argument('--output', type=str, default='data/backtests/nifty_historical_backtest.csv',
                       help='Output CSV file')

    args = parser.parse_args()

    backtest = HistoricalBacktest()
    results_df = backtest.run_backtest(days=args.days)

    if results_df.empty:
        logger.error("Backtest failed - no results")
        sys.exit(1)

    # Generate report
    backtest.generate_report(results_df)

    # Save to CSV
    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    results_df.to_csv(args.output, index=False)
    logger.info(f"\n✅ Results saved to: {args.output}")

    sys.exit(0)


if __name__ == "__main__":
    main()
