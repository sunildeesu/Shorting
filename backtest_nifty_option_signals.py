#!/usr/bin/env python3
"""
Backtest NIFTY Option Selling Signals

Simulates running the analysis at 10 AM on each trading day
for the past month to see which days would have given SELL signals.

Validates the new hard veto filters against historical data.

Usage:
    python3 backtest_nifty_option_signals.py --days 30

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
from nifty_option_analyzer import NiftyOptionAnalyzer
from market_utils import is_trading_day, is_nse_holiday

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class NiftyOptionBacktest:
    """Backtest NIFTY option selling signals"""

    def __init__(self):
        """Initialize backtest with Kite connection"""
        self.token_manager = TokenManager()
        self.kite = None
        self.analyzer = None

    def _initialize_kite(self) -> bool:
        """Initialize Kite Connect"""
        try:
            is_valid, message, hours_remaining = self.token_manager.is_token_valid()
            if not is_valid:
                logger.error(f"Kite token invalid: {message}")
                return False

            self.kite = KiteConnect(api_key=config.KITE_API_KEY)
            self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

            profile = self.kite.profile()
            logger.info(f"Connected to Kite as: {profile.get('user_name', 'Unknown')}")

            self.analyzer = NiftyOptionAnalyzer(self.kite)
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Kite: {e}")
            return False

    def get_trading_days(self, lookback_days: int) -> List[datetime]:
        """
        Get list of trading days for backtest period

        Args:
            lookback_days: Number of calendar days to look back

        Returns:
            List of trading dates
        """
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=lookback_days)

        trading_days = []
        current_date = start_date

        while current_date <= end_date:
            # Check if it's a trading day (not weekend, not holiday)
            if current_date.weekday() < 5 and not is_nse_holiday(current_date):
                trading_days.append(current_date)

            current_date += timedelta(days=1)

        return trading_days

    def run_backtest(self, days: int = 30) -> pd.DataFrame:
        """
        Run backtest for specified number of days

        Args:
            days: Number of calendar days to backtest

        Returns:
            DataFrame with backtest results
        """
        if not self.kite or not self.analyzer:
            if not self._initialize_kite():
                logger.error("Cannot run backtest - Kite initialization failed")
                return pd.DataFrame()

        logger.info("=" * 80)
        logger.info(f"NIFTY OPTION SELLING BACKTEST - Last {days} Days")
        logger.info("=" * 80)

        # Get trading days
        trading_days = self.get_trading_days(days)
        logger.info(f"Found {len(trading_days)} trading days in period")

        results = []

        for i, test_date in enumerate(trading_days, 1):
            logger.info(f"\n[{i}/{len(trading_days)}] Testing: {test_date.strftime('%Y-%m-%d (%A)')}")

            try:
                # Run analysis for this date
                result = self.analyzer.analyze_option_selling_opportunity()

                # Extract key metrics
                signal = result.get('signal', 'ERROR')
                score = result.get('total_score', 0)
                vix = result.get('vix', 0)
                vix_trend = result.get('vix_trend', 0)
                iv_rank = result.get('iv_rank', 0)
                nifty_spot = result.get('nifty_spot', 0)
                veto_type = result.get('veto_type', None)
                recommendation = result.get('recommendation', '')
                risk_factors = result.get('risk_factors', [])

                # Get breakdown
                breakdown = result.get('breakdown', {})
                theta_score = breakdown.get('theta_score', 0)
                gamma_score = breakdown.get('gamma_score', 0)
                vega_score = breakdown.get('vega_score', 0)
                vix_score = breakdown.get('vix_score', 0)

                # Get market regime and OI
                market_regime = result.get('market_regime', 'UNKNOWN')
                oi_pattern = result.get('oi_analysis', {}).get('pattern', 'UNKNOWN')

                # Store result
                results.append({
                    'date': test_date,
                    'signal': signal,
                    'score': score,
                    'nifty_spot': nifty_spot,
                    'vix': vix,
                    'vix_trend': vix_trend,
                    'iv_rank': iv_rank,
                    'veto_type': veto_type,
                    'theta_score': theta_score,
                    'gamma_score': gamma_score,
                    'vega_score': vega_score,
                    'vix_score': vix_score,
                    'market_regime': market_regime,
                    'oi_pattern': oi_pattern,
                    'recommendation': recommendation,
                    'risk_factors': '; '.join(risk_factors) if risk_factors else ''
                })

                # Log result
                if signal == 'SELL':
                    logger.info(f"  ✅ SELL (Score: {score:.1f}/100)")
                elif signal == 'AVOID':
                    if veto_type:
                        logger.info(f"  🚫 AVOID (Veto: {veto_type})")
                    else:
                        logger.info(f"  ❌ AVOID (Score: {score:.1f}/100)")
                else:
                    logger.info(f"  ⏸️  {signal} (Score: {score:.1f}/100)")

                logger.info(f"  VIX: {vix:.2f} | IV Rank: {iv_rank:.1f}% | Regime: {market_regime}")

            except Exception as e:
                logger.error(f"  Error analyzing {test_date}: {e}")
                results.append({
                    'date': test_date,
                    'signal': 'ERROR',
                    'score': 0,
                    'error': str(e)
                })

        # Convert to DataFrame
        df = pd.DataFrame(results)

        return df

    def generate_report(self, df: pd.DataFrame) -> None:
        """
        Generate backtest report

        Args:
            df: DataFrame with backtest results
        """
        logger.info("\n" + "=" * 80)
        logger.info("BACKTEST SUMMARY")
        logger.info("=" * 80)

        # Overall stats
        total_days = len(df)
        sell_days = len(df[df['signal'] == 'SELL'])
        hold_days = len(df[df['signal'] == 'HOLD'])
        avoid_days = len(df[df['signal'] == 'AVOID'])
        error_days = len(df[df['signal'] == 'ERROR'])

        logger.info(f"\nTotal Trading Days: {total_days}")
        logger.info(f"SELL signals: {sell_days} ({sell_days/total_days*100:.1f}%)")
        logger.info(f"HOLD signals: {hold_days} ({hold_days/total_days*100:.1f}%)")
        logger.info(f"AVOID signals: {avoid_days} ({avoid_days/total_days*100:.1f}%)")
        if error_days > 0:
            logger.info(f"Errors: {error_days}")

        # SELL signal days
        if sell_days > 0:
            logger.info("\n" + "=" * 80)
            logger.info(f"SELL SIGNAL DAYS ({sell_days} days)")
            logger.info("=" * 80)

            sell_df = df[df['signal'] == 'SELL'].sort_values('date')
            for _, row in sell_df.iterrows():
                logger.info(f"\n📅 {row['date'].strftime('%Y-%m-%d (%A)')}")
                logger.info(f"  Score: {row['score']:.1f}/100")
                logger.info(f"  NIFTY: {row['nifty_spot']:.2f}")
                logger.info(f"  VIX: {row['vix']:.2f} (Trend: {row['vix_trend']:+.2f}, IV Rank: {row['iv_rank']:.1f}%)")
                logger.info(f"  Regime: {row['market_regime']} | OI: {row['oi_pattern']}")
                logger.info(f"  Scores: Theta {row['theta_score']:.0f} | Gamma {row['gamma_score']:.0f} | "
                          f"Vega {row['vega_score']:.0f} | VIX {row['vix_score']:.0f}")

        # AVOID signal days (with veto reasons)
        if avoid_days > 0:
            logger.info("\n" + "=" * 80)
            logger.info(f"AVOID SIGNAL DAYS ({avoid_days} days)")
            logger.info("=" * 80)

            avoid_df = df[df['signal'] == 'AVOID'].sort_values('date')

            # Group by veto type
            veto_counts = avoid_df['veto_type'].value_counts()
            logger.info("\nVeto Breakdown:")
            for veto_type, count in veto_counts.items():
                if pd.notna(veto_type):
                    logger.info(f"  {veto_type}: {count} days")
                else:
                    logger.info(f"  Low Score (no veto): {count} days")

            logger.info("\nDetailed AVOID Days:")
            for _, row in avoid_df.iterrows():
                logger.info(f"\n📅 {row['date'].strftime('%Y-%m-%d (%A)')}")
                if pd.notna(row.get('veto_type')):
                    logger.info(f"  🚫 VETO: {row['veto_type']}")
                else:
                    logger.info(f"  Score: {row['score']:.1f}/100 (Below threshold)")
                logger.info(f"  VIX: {row['vix']:.2f} | IV Rank: {row['iv_rank']:.1f}%")
                if row.get('risk_factors'):
                    logger.info(f"  Risk: {row['risk_factors']}")

        # IV Rank statistics
        logger.info("\n" + "=" * 80)
        logger.info("IV RANK STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Average IV Rank: {df['iv_rank'].mean():.1f}%")
        logger.info(f"Min IV Rank: {df['iv_rank'].min():.1f}% (on {df.loc[df['iv_rank'].idxmin(), 'date'].strftime('%Y-%m-%d')})")
        logger.info(f"Max IV Rank: {df['iv_rank'].max():.1f}% (on {df.loc[df['iv_rank'].idxmax(), 'date'].strftime('%Y-%m-%d')})")
        logger.info(f"Days with IV Rank < 15%: {len(df[df['iv_rank'] < 15])}")
        logger.info(f"Days with IV Rank < 25%: {len(df[df['iv_rank'] < 25])}")
        logger.info(f"Days with IV Rank > 50%: {len(df[df['iv_rank'] > 50])}")
        logger.info(f"Days with IV Rank > 75%: {len(df[df['iv_rank'] > 75])}")

        logger.info("\n" + "=" * 80)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Backtest NIFTY Option Selling Signals')
    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Number of calendar days to backtest (default: 30)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/backtests/nifty_option_signals_backtest.csv',
        help='Output CSV file path'
    )

    args = parser.parse_args()

    # Create backtest instance
    backtest = NiftyOptionBacktest()

    # Run backtest
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
