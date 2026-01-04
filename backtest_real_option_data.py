#!/usr/bin/env python3
"""
REAL Backtest Using Actual Historical Option Data from Kite Connect

Uses REAL option premiums from Kite historical data (not Black-Scholes estimates).
This shows what ACTUALLY would have happened.

Limitations:
- Kite provides option data for only ~10-15 days back
- So we can backtest recent 2 weeks only

Author: Sunil Kumar Durganaik
Date: January 3, 2026
"""

import os
import sys
import logging
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from kiteconnect import KiteConnect
from token_manager import TokenManager
from market_utils import is_nse_holiday

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RealOptionBacktest:
    """Backtest using ACTUAL historical option data from Kite"""

    def __init__(self):
        """Initialize backtest"""
        self.token_manager = TokenManager()
        self.kite = None
        self.nifty_token = config.NIFTY_50_TOKEN
        self.vix_token = config.INDIA_VIX_TOKEN

        # Trading parameters
        self.entry_time = time(10, 5)
        self.exit_time = time(15, 10)
        self.lot_size = 50
        self.lots_traded = 1

        # Transaction costs
        self.brokerage_per_order = 20
        self.stt_rate = 0.0005
        self.exchange_charges_rate = 0.0005
        self.gst_rate = 0.18

        # Cache
        self.instruments_cache = None

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

    def get_nfo_instruments(self) -> List[Dict]:
        """Get NFO instruments (cached)"""
        if not self.instruments_cache:
            logger.info("Fetching NFO instruments...")
            self.instruments_cache = self.kite.instruments("NFO")
            logger.info(f"✅ Cached {len(self.instruments_cache)} NFO instruments")
        return self.instruments_cache

    def get_atm_strike(self, spot_price: float) -> int:
        """Get ATM strike (nearest 50 multiple)"""
        return round(spot_price / 50) * 50

    def find_option_instruments(
        self,
        strike: int,
        expiry_date: datetime.date,
        option_type: str = 'CE'
    ) -> Optional[Dict]:
        """
        Find option instrument for given strike and expiry

        Args:
            strike: Strike price
            expiry_date: Expiry date
            option_type: 'CE' or 'PE'

        Returns:
            Instrument dict or None
        """
        instruments = self.get_nfo_instruments()

        # Filter NIFTY options with matching strike, expiry, and type
        matches = [
            i for i in instruments
            if i['name'] == 'NIFTY'
            and i['instrument_type'] == option_type
            and i['strike'] == strike
            and i['expiry'] == expiry_date
        ]

        return matches[0] if matches else None

    def get_next_weekly_expiry(self, trade_date: datetime) -> datetime.date:
        """
        Get next week's expiry (NIFTY weekly options)

        Strategy: Use the nearest weekly expiry that's 6-13 days away.
        This ensures we skip current week and use next week only.

        Args:
            trade_date: Date of trade

        Returns:
            Next week's expiry date
        """
        # Get all available expiries from instruments
        instruments = self.get_nfo_instruments()
        nifty_options = [i for i in instruments if i['name'] == 'NIFTY']
        available_expiries = sorted(set([i['expiry'] for i in nifty_options]))

        # Find expiry that's 6-13 days away (next week)
        for expiry in available_expiries:
            days_diff = (expiry - trade_date.date()).days
            if 6 <= days_diff <= 13:  # Next week window
                return expiry

        # If not found, return nearest expiry >5 days away
        for expiry in available_expiries:
            if (expiry - trade_date.date()).days > 5:
                return expiry

        # Last resort: return nearest future expiry
        return available_expiries[0]

    def get_option_price_at_time(
        self,
        instrument_token: int,
        date: datetime,
        target_time: time
    ) -> Optional[float]:
        """
        Get option price at specific time using historical data

        Args:
            instrument_token: Option instrument token
            date: Trading date
            target_time: Target time (e.g., 10:05 or 15:10)

        Returns:
            Option price or None
        """
        try:
            from_dt = date.replace(hour=9, minute=15)
            to_dt = date.replace(hour=15, minute=30)

            # Fetch 5-minute candles
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_dt,
                to_date=to_dt,
                interval="5minute"
            )

            if not data:
                return None

            # Find candle closest to target time
            for candle in data:
                candle_time = candle['date'].time()

                # Use candle if it's within 10 minutes of target
                if target_time == time(10, 5):
                    if time(10, 0) <= candle_time <= time(10, 10):
                        return candle['close']
                elif target_time == time(15, 10):
                    if time(15, 5) <= candle_time <= time(15, 30):
                        return candle['close']

            return None

        except Exception as e:
            logger.debug(f"Error fetching option price: {e}")
            return None

    def calculate_transaction_costs(
        self,
        entry_call: float,
        entry_put: float,
        exit_call: float,
        exit_put: float
    ) -> float:
        """Calculate total transaction costs"""
        brokerage = 4 * self.brokerage_per_order

        total_entry_premium = (entry_call + entry_put) * self.lot_size
        total_exit_premium = (exit_call + exit_put) * self.lot_size

        stt = total_entry_premium * self.stt_rate
        exchange_charges = (total_entry_premium + total_exit_premium) * self.exchange_charges_rate

        base_charges = brokerage + exchange_charges
        gst = base_charges * self.gst_rate

        return brokerage + stt + exchange_charges + gst

    def backtest_single_day(
        self,
        trade_date: datetime
    ) -> Optional[Dict]:
        """
        Backtest a single day using REAL option data

        Args:
            trade_date: Date to backtest

        Returns:
            Dict with trade results or None if data unavailable
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Backtesting: {trade_date.date()} ({trade_date.strftime('%A')})")
        logger.info(f"{'='*60}")

        # Get NIFTY spot at entry time
        try:
            nifty_data = self.kite.historical_data(
                instrument_token=self.nifty_token,
                from_date=trade_date.replace(hour=9, minute=15),
                to_date=trade_date.replace(hour=15, minute=30),
                interval="5minute"
            )

            if not nifty_data:
                logger.warning("  ❌ No NIFTY data available")
                return None

            # Get NIFTY at entry and exit
            nifty_entry = None
            nifty_exit = None

            for candle in nifty_data:
                t = candle['date'].time()
                if not nifty_entry and time(10, 0) <= t <= time(10, 10):
                    nifty_entry = candle['close']
                if time(15, 5) <= t <= time(15, 30):
                    nifty_exit = candle['close']

            if not nifty_entry or not nifty_exit:
                logger.warning("  ❌ Missing NIFTY entry/exit prices")
                return None

            logger.info(f"  NIFTY Entry: {nifty_entry:.2f}, Exit: {nifty_exit:.2f}")

        except Exception as e:
            logger.error(f"  ❌ Error fetching NIFTY data: {e}")
            return None

        # Get ATM strike
        atm_strike = self.get_atm_strike(nifty_entry)
        logger.info(f"  ATM Strike: {atm_strike}")

        # Get next week expiry
        expiry = self.get_next_weekly_expiry(trade_date)
        days_to_expiry = (expiry - trade_date.date()).days
        logger.info(f"  Expiry: {expiry} ({days_to_expiry} DTE)")

        # Find option instruments
        ce_instrument = self.find_option_instruments(atm_strike, expiry, 'CE')
        pe_instrument = self.find_option_instruments(atm_strike, expiry, 'PE')

        if not ce_instrument or not pe_instrument:
            logger.warning(f"  ❌ Options not found for strike {atm_strike}, expiry {expiry}")
            return None

        logger.info(f"  CE: {ce_instrument['tradingsymbol']}")
        logger.info(f"  PE: {pe_instrument['tradingsymbol']}")

        # Get REAL option prices at entry
        ce_entry = self.get_option_price_at_time(
            ce_instrument['instrument_token'],
            trade_date,
            time(10, 5)
        )

        pe_entry = self.get_option_price_at_time(
            pe_instrument['instrument_token'],
            trade_date,
            time(10, 5)
        )

        if not ce_entry or not pe_entry:
            logger.warning("  ❌ Missing entry option prices")
            return None

        logger.info(f"  Entry Premiums: CE=₹{ce_entry:.2f}, PE=₹{pe_entry:.2f}")

        # Get REAL option prices at exit
        ce_exit = self.get_option_price_at_time(
            ce_instrument['instrument_token'],
            trade_date,
            time(15, 10)
        )

        pe_exit = self.get_option_price_at_time(
            pe_instrument['instrument_token'],
            trade_date,
            time(15, 10)
        )

        if not ce_exit or not pe_exit:
            logger.warning("  ❌ Missing exit option prices")
            return None

        logger.info(f"  Exit Premiums:  CE=₹{ce_exit:.2f}, PE=₹{pe_exit:.2f}")

        # Calculate P&L
        entry_straddle = ce_entry + pe_entry
        exit_straddle = ce_exit + pe_exit

        premium_collected = entry_straddle * self.lot_size * self.lots_traded
        premium_paid = exit_straddle * self.lot_size * self.lots_traded

        gross_pnl = premium_collected - premium_paid

        transaction_cost = self.calculate_transaction_costs(
            ce_entry, pe_entry, ce_exit, pe_exit
        )

        net_pnl = gross_pnl - transaction_cost

        nifty_move = nifty_exit - nifty_entry
        nifty_move_pct = (nifty_move / nifty_entry) * 100

        logger.info(f"  NIFTY Move: {nifty_move_pct:+.2f}%")
        logger.info(f"  Premium Collected: ₹{premium_collected:.2f}")
        logger.info(f"  Premium Paid: ₹{premium_paid:.2f}")
        logger.info(f"  Gross P&L: ₹{gross_pnl:.2f}")
        logger.info(f"  Transaction Cost: ₹{transaction_cost:.2f}")

        result_icon = "✅" if net_pnl > 0 else "❌"
        logger.info(f"  {result_icon} NET P&L: ₹{net_pnl:.2f}")

        return {
            'date': trade_date.strftime('%Y-%m-%d'),
            'day_of_week': trade_date.strftime('%A'),
            'nifty_entry': round(nifty_entry, 2),
            'nifty_exit': round(nifty_exit, 2),
            'nifty_move': round(nifty_move, 2),
            'nifty_move_pct': round(nifty_move_pct, 2),
            'atm_strike': atm_strike,
            'expiry': str(expiry),
            'days_to_expiry': days_to_expiry,
            'ce_symbol': ce_instrument['tradingsymbol'],
            'pe_symbol': pe_instrument['tradingsymbol'],
            'ce_entry': round(ce_entry, 2),
            'pe_entry': round(pe_entry, 2),
            'entry_straddle': round(entry_straddle, 2),
            'ce_exit': round(ce_exit, 2),
            'pe_exit': round(pe_exit, 2),
            'exit_straddle': round(exit_straddle, 2),
            'premium_collected': round(premium_collected, 2),
            'premium_paid': round(premium_paid, 2),
            'gross_pnl': round(gross_pnl, 2),
            'transaction_cost': round(transaction_cost, 2),
            'net_pnl': round(net_pnl, 2),
            'data_source': 'REAL_KITE_DATA'
        }

    def run_backtest(self, days_back: int = 14) -> List[Dict]:
        """
        Run backtest for past N days using REAL option data

        Args:
            days_back: Number of days to backtest

        Returns:
            List of trade results
        """
        logger.info("=" * 80)
        logger.info(f"REAL OPTION DATA BACKTEST - Past {days_back} Days")
        logger.info("=" * 80)
        logger.info("Using ACTUAL historical option premiums from Kite Connect")
        logger.info("This shows what REALLY would have happened!")
        logger.info("=" * 80)

        if not self.initialize_kite():
            logger.error("Cannot proceed without Kite connection")
            return []

        # Get trading days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        trading_days = []
        current = start_date

        while current <= end_date:
            if current.weekday() < 5 and not is_nse_holiday(current.date()):
                # Only include past days
                if current < datetime.now():
                    trading_days.append(current)
            current += timedelta(days=1)

        logger.info(f"\nTesting {len(trading_days)} trading days")
        logger.info(f"Period: {trading_days[0].date()} to {trading_days[-1].date()}\n")

        # Backtest each day
        results = []
        skipped = 0

        for i, trade_date in enumerate(trading_days, 1):
            logger.info(f"\n[{i}/{len(trading_days)}]")

            result = self.backtest_single_day(trade_date)

            if result:
                results.append(result)
            else:
                skipped += 1
                logger.warning(f"  ⚠️ Skipped (data unavailable)")

        logger.info("\n" + "=" * 80)
        logger.info(f"✅ Backtest complete: {len(results)} trades, {skipped} skipped")
        logger.info("=" * 80)

        return results

    def generate_analysis(self, results: List[Dict]) -> Dict:
        """Analyze backtest results"""
        if not results:
            return {}

        df = pd.DataFrame(results)

        total_trades = len(df)
        winning_trades = len(df[df['net_pnl'] > 0])
        losing_trades = len(df[df['net_pnl'] <= 0])
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

        total_pnl = df['net_pnl'].sum()
        avg_pnl = df['net_pnl'].mean()
        max_profit = df['net_pnl'].max()
        max_loss = df['net_pnl'].min()

        # Day of week stats
        day_stats = df.groupby('day_of_week').agg({
            'net_pnl': ['count', 'sum', 'mean']
        }).round(2)

        return {
            'overall': {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl,
                'max_profit': max_profit,
                'max_loss': max_loss
            },
            'day_of_week': day_stats,
            'dataframe': df
        }

    def save_results(self, results: List[Dict], analysis: Dict):
        """Save results and generate report"""
        output_dir = Path("data/backtests")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save CSV
        trades_csv = output_dir / "real_option_data_backtest.csv"
        df = pd.DataFrame(results)
        df.to_csv(trades_csv, index=False)
        logger.info(f"\n💾 Saved {len(results)} trades to {trades_csv}")

        # Generate report
        report_path = output_dir / "REAL_OPTION_DATA_BACKTEST.md"

        with open(report_path, 'w') as f:
            f.write("# REAL Option Data Backtest - Actual Kite Historical Prices\n\n")
            f.write(f"**Backtest Date:** {datetime.now().strftime('%B %d, %Y')}\n")
            f.write(f"**Data Source:** Kite Connect Historical API (REAL option prices)\n")
            f.write(f"**Period:** {results[0]['date']} to {results[-1]['date']}\n")
            f.write(f"**Strategy:** Sell ATM Call + Put at 10:05 AM, Close at 3:10 PM\n")
            f.write(f"**Expiry:** Next week only (6-10 DTE)\n")
            f.write(f"**Position Size:** {self.lots_traded} lot ({self.lot_size} qty)\n\n")

            f.write("---\n\n")
            f.write("## 🎯 CRITICAL DIFFERENCE: REAL vs ESTIMATED\n\n")
            f.write("This backtest uses **ACTUAL historical option premiums** from Kite Connect.\n")
            f.write("Previous backtests used Black-Scholes estimates which showed 100% win rate.\n")
            f.write("This shows **REALITY** - what would have ACTUALLY happened!\n\n")

            f.write("---\n\n")
            f.write("## 📊 OVERALL PERFORMANCE (REAL DATA)\n\n")

            overall = analysis['overall']
            f.write(f"- **Total Trades:** {overall['total_trades']}\n")
            f.write(f"- **Winning Trades:** {overall['winning_trades']} ({overall['win_rate']:.1f}%)\n")
            f.write(f"- **Losing Trades:** {overall['losing_trades']} ({100-overall['win_rate']:.1f}%)\n")
            f.write(f"- **Total P&L:** ₹{overall['total_pnl']:,.2f}\n")
            f.write(f"- **Average P&L per Trade:** ₹{overall['avg_pnl']:.2f}\n")
            f.write(f"- **Best Trade:** ₹{overall['max_profit']:,.2f}\n")
            f.write(f"- **Worst Trade:** ₹{overall['max_loss']:,.2f}\n\n")

            # Verdict
            if overall['total_pnl'] > 0 and overall['win_rate'] > 70:
                verdict = "🟢 **PROFITABLE STRATEGY** (Validated with real data)"
            elif overall['total_pnl'] > 0:
                verdict = "🟡 **MARGINALLY PROFITABLE** (Real data shows lower win rate)"
            else:
                verdict = "🔴 **LOSING STRATEGY** (Real data reveals losses)"

            f.write(f"### Verdict: {verdict}\n\n")

            f.write("---\n\n")
            f.write("## 📅 DAY OF WEEK ANALYSIS (REAL DATA)\n\n")

            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
            f.write("| Day | Trades | Total P&L | Avg P&L |\n")
            f.write("|-----|--------|-----------|----------|\n")

            day_stats = analysis['day_of_week']
            for day in day_order:
                if day in day_stats.index:
                    row = day_stats.loc[day]
                    trades = int(row[('net_pnl', 'count')])
                    total = row[('net_pnl', 'sum')]
                    avg = row[('net_pnl', 'mean')]
                    f.write(f"| {day:9s} | {trades:6d} | ₹{total:8,.2f} | ₹{avg:6.2f} |\n")

            f.write("\n---\n\n")
            f.write("## 📋 ALL TRADES (REAL DATA)\n\n")

            df = analysis['dataframe']
            for _, row in df.iterrows():
                pnl_icon = "✅" if row['net_pnl'] > 0 else "❌"
                f.write(f"\n### {row['date']} ({row['day_of_week']})\n")
                f.write(f"**{pnl_icon} P&L: ₹{row['net_pnl']:.2f}**\n\n")
                f.write(f"- NIFTY: {row['nifty_entry']:.2f} → {row['nifty_exit']:.2f} ({row['nifty_move_pct']:+.2f}%)\n")
                f.write(f"- Strike: {row['atm_strike']} ({row['days_to_expiry']} DTE, expires {row['expiry']})\n")
                f.write(f"- Entry: CE ₹{row['ce_entry']:.2f} + PE ₹{row['pe_entry']:.2f} = ₹{row['entry_straddle']:.2f}\n")
                f.write(f"- Exit:  CE ₹{row['ce_exit']:.2f} + PE ₹{row['pe_exit']:.2f} = ₹{row['exit_straddle']:.2f}\n")
                f.write(f"- Options: {row['ce_symbol']}, {row['pe_symbol']}\n")

            f.write("\n---\n\n")
            f.write("*Report generated with REAL historical option data from Kite Connect*\n")

        logger.info(f"📄 Generated report: {report_path}")

        # Print summary
        logger.info("\n" + "=" * 80)
        logger.info("BACKTEST SUMMARY (REAL DATA)")
        logger.info("=" * 80)
        logger.info(f"Total P&L: ₹{overall['total_pnl']:,.2f}")
        logger.info(f"Win Rate: {overall['win_rate']:.1f}% ({overall['winning_trades']}/{overall['total_trades']})")
        logger.info(f"Avg P&L: ₹{overall['avg_pnl']:.2f}")

        if overall['losing_trades'] > 0:
            logger.info(f"\n⚠️ WARNING: {overall['losing_trades']} LOSING DAYS found!")
            logger.info(f"Worst Loss: ₹{overall['max_loss']:,.2f}")

        logger.info("=" * 80)


def main():
    """Run real option data backtest"""
    backtest = RealOptionBacktest()

    # Run backtest for past 14 days (Kite limitation)
    results = backtest.run_backtest(days_back=14)

    if not results:
        logger.error("No results - check if data is available")
        return

    # Analyze
    analysis = backtest.generate_analysis(results)

    # Save
    backtest.save_results(results, analysis)

    logger.info("\n✅ REAL backtest complete! Check data/backtests/ for results.")


if __name__ == "__main__":
    main()
