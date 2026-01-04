#!/usr/bin/env python3
"""
ATM Straddle Backtest - 6 Months Historical Analysis

Strategy:
- Entry: 10:05 AM - Sell ATM Call + ATM Put (next week expiry)
- Exit: 3:10 PM - Buy back both options
- Position: 1 lot each (50 qty per lot for NIFTY)
- Period: Past 6 months

This backtest provides insights on:
1. Overall profitability of daily ATM straddle selling
2. Which days of week are most profitable
3. How VIX levels affect profitability
4. Impact of NIFTY movement on P&L
5. How our indicator signals correlate with actual P&L

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
import math

# Add project directory to path
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


class ATMStraddleBacktest:
    """
    Comprehensive backtest for ATM straddle selling strategy
    """

    def __init__(self):
        """Initialize backtest"""
        self.token_manager = TokenManager()
        self.kite = None
        self.nifty_token = config.NIFTY_50_TOKEN
        self.vix_token = config.INDIA_VIX_TOKEN

        # Trading parameters
        self.entry_time = time(10, 5)  # 10:05 AM
        self.exit_time = time(15, 10)  # 3:10 PM
        self.lot_size = 50  # NIFTY option lot size
        self.lots_traded = 1  # Number of lots per trade

        # Transaction costs (realistic estimates for retail trader)
        self.brokerage_per_order = 20  # Flat ₹20 per order (discount broker)
        self.stt_rate = 0.0005  # 0.05% on sell side (options)
        self.exchange_charges_rate = 0.0005  # ~0.05%
        self.gst_rate = 0.18  # 18% GST on brokerage + transaction charges

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

    def get_atm_strike(self, spot_price: float) -> int:
        """
        Get ATM strike (nearest 50 multiple)

        Args:
            spot_price: NIFTY spot price

        Returns:
            ATM strike price
        """
        return round(spot_price / 50) * 50

    def get_next_weekly_expiry_days(self, trade_date: datetime) -> int:
        """
        Calculate days to NEXT WEEK's expiry (Thursday)

        ALWAYS uses next week's Thursday, NOT current week.
        This avoids trading current week expiries (1-3 DTE) which have high gamma risk.

        Args:
            trade_date: Date of trade

        Returns:
            Days to next week's Thursday expiry
        """
        # Thursday = 3 (weekday)
        current_weekday = trade_date.weekday()

        # Calculate days to this week's Thursday
        days_to_this_thursday = (3 - current_weekday) % 7

        # If today is Monday, Tuesday, or Wednesday: Skip current week's Thursday
        # Use next week's Thursday instead (add 7 days)
        if current_weekday in [0, 1, 2]:  # Monday, Tuesday, Wednesday
            days_to_next_thursday = days_to_this_thursday + 7
        # If today is Thursday: Use next week's Thursday
        elif current_weekday == 3:  # Thursday (expiry day)
            days_to_next_thursday = 7
        # If today is Friday: Next Thursday is 6 days away (already next week)
        else:  # Friday (weekday 4)
            days_to_next_thursday = days_to_this_thursday

        return days_to_next_thursday

    def estimate_atm_straddle_premium(
        self,
        spot: float,
        vix: float,
        days_to_expiry: int
    ) -> Tuple[float, float]:
        """
        Estimate ATM straddle premium using Black-Scholes approximation

        For ATM options:
        - Call Premium ≈ Put Premium (at-the-money, symmetric)
        - Combined Premium ≈ Spot × IV × sqrt(T) × 0.8

        Where:
        - IV = VIX / 100 (implied volatility)
        - T = days_to_expiry / 365
        - 0.8 = calibration factor for ATM straddle

        Args:
            spot: NIFTY spot price
            vix: India VIX value
            days_to_expiry: Days until expiry

        Returns:
            Tuple of (call_premium, put_premium)
        """
        # Annual implied volatility
        iv = vix / 100

        # Time to expiry (years)
        time_to_expiry = days_to_expiry / 365

        # Black-Scholes approximation for ATM option
        # Single option premium ≈ 0.4 × Spot × IV × sqrt(T)
        single_option_premium = 0.4 * spot * iv * math.sqrt(time_to_expiry)

        # For ATM, Call ≈ Put
        call_premium = single_option_premium
        put_premium = single_option_premium

        return call_premium, put_premium

    def estimate_exit_premium(
        self,
        entry_call: float,
        entry_put: float,
        spot_move_pct: float,
        hours_elapsed: float,
        days_to_expiry: int
    ) -> Tuple[float, float]:
        """
        Estimate option premiums at exit time

        Factors affecting premium change:
        1. Time decay (Theta): Premiums decay with time
        2. Spot movement (Delta/Gamma): Affects call and put differently
        3. Volatility change: Typically decreases intraday

        Args:
            entry_call: Call premium at entry
            entry_put: Put premium at entry
            spot_move_pct: NIFTY movement % (positive = up, negative = down)
            hours_elapsed: Hours between entry and exit
            days_to_expiry: Days to expiry at entry

        Returns:
            Tuple of (exit_call, exit_put)
        """
        # Time decay factor (Theta)
        # ATM options lose approximately (1/DTE) per day
        # For 5 hours (~0.21 days), decay is ~0.21/DTE of premium
        if days_to_expiry > 0:
            time_decay_factor = 1 - (hours_elapsed / 24) / days_to_expiry
        else:
            time_decay_factor = 0.6  # Expiry day - accelerated decay

        # Ensure minimum decay
        time_decay_factor = max(time_decay_factor, 0.5)

        # Calculate base decay
        call_exit = entry_call * time_decay_factor
        put_exit = entry_put * time_decay_factor

        # Spot movement impact (Delta effect)
        # For ATM options, delta ≈ 0.5
        # 1% spot move changes option by ~0.5% of spot
        abs_move = abs(spot_move_pct)

        if abs_move > 0.1:  # Significant movement
            # Delta effect: winning leg gains, losing leg loses
            # But decay still dominates for straddle
            delta_factor = abs_move / 100 * 0.5  # Simplified delta

            if spot_move_pct > 0:  # NIFTY moved up
                # Call gains intrinsic value
                call_exit = call_exit * (1 + delta_factor)
                # Put loses
                put_exit = put_exit * (1 - delta_factor * 0.5)
            else:  # NIFTY moved down
                # Put gains intrinsic value
                put_exit = put_exit * (1 + delta_factor)
                # Call loses
                call_exit = call_exit * (1 - delta_factor * 0.5)

        # Floor: minimum 20% of entry premium remains
        call_exit = max(call_exit, entry_call * 0.2)
        put_exit = max(put_exit, entry_put * 0.2)

        return call_exit, put_exit

    def calculate_transaction_costs(
        self,
        entry_call: float,
        entry_put: float,
        exit_call: float,
        exit_put: float
    ) -> float:
        """
        Calculate total transaction costs

        Costs include:
        - Brokerage (₹20 per order × 4 orders)
        - STT (0.05% on sell premium)
        - Exchange charges (0.05% on all premiums)
        - GST (18% on brokerage + charges)

        Args:
            entry_call: Call premium at entry
            entry_put: Put premium at entry
            exit_call: Call premium at exit
            exit_put: Put premium at exit

        Returns:
            Total transaction cost in ₹
        """
        # Brokerage: 4 orders (sell call, sell put, buy call, buy put)
        brokerage = 4 * self.brokerage_per_order

        # Total premium value (for calculating charges)
        total_entry_premium = (entry_call + entry_put) * self.lot_size
        total_exit_premium = (exit_call + exit_put) * self.lot_size

        # STT: Only on sell side (entry)
        stt = total_entry_premium * self.stt_rate

        # Exchange charges: On all transactions
        exchange_charges = (total_entry_premium + total_exit_premium) * self.exchange_charges_rate

        # GST: On brokerage + exchange charges
        base_charges = brokerage + exchange_charges
        gst = base_charges * self.gst_rate

        # Total cost
        total_cost = brokerage + stt + exchange_charges + gst

        return total_cost

    def fetch_historical_spot_data(
        self,
        date: datetime,
        instrument_token: int
    ) -> Optional[Dict]:
        """
        Fetch historical spot data for entry and exit times

        Args:
            date: Trading date
            instrument_token: Instrument token (NIFTY or VIX)

        Returns:
            Dict with entry_price, exit_price, or None if data unavailable
        """
        if not self.kite:
            return None

        try:
            # Fetch 5-minute candles for the day
            from_date = date.replace(hour=9, minute=15)
            to_date = date.replace(hour=15, minute=30)

            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="5minute"
            )

            if not data:
                return None

            # Find candles closest to entry (10:05) and exit (15:10)
            entry_candle = None
            exit_candle = None

            for candle in data:
                candle_time = candle['date'].time()

                # Entry: 10:05 AM (find candle between 10:00-10:10)
                if time(10, 0) <= candle_time <= time(10, 10) and not entry_candle:
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

    def backtest_single_day(
        self,
        trade_date: datetime,
        nifty_entry: float,
        nifty_exit: float,
        vix: float
    ) -> Dict:
        """
        Backtest a single day's straddle trade

        Args:
            trade_date: Date of trade
            nifty_entry: NIFTY spot at 10:05 AM
            nifty_exit: NIFTY spot at 3:10 PM
            vix: India VIX value

        Returns:
            Dict with trade details and P&L
        """
        # Get ATM strike
        atm_strike = self.get_atm_strike(nifty_entry)

        # Get days to next week expiry
        days_to_expiry = self.get_next_weekly_expiry_days(trade_date)

        # Estimate entry premiums
        entry_call, entry_put = self.estimate_atm_straddle_premium(
            nifty_entry,
            vix,
            days_to_expiry
        )

        # Calculate NIFTY movement
        nifty_move = nifty_exit - nifty_entry
        nifty_move_pct = (nifty_move / nifty_entry) * 100

        # Estimate exit premiums (after ~5 hours)
        hours_elapsed = 5.0  # 10:05 AM to 3:10 PM
        exit_call, exit_put = self.estimate_exit_premium(
            entry_call,
            entry_put,
            nifty_move_pct,
            hours_elapsed,
            days_to_expiry
        )

        # Calculate P&L
        # Premium collected at entry (selling)
        premium_collected = (entry_call + entry_put) * self.lot_size * self.lots_traded

        # Premium paid at exit (buying back)
        premium_paid = (exit_call + exit_put) * self.lot_size * self.lots_traded

        # Gross P&L
        gross_pnl = premium_collected - premium_paid

        # Transaction costs
        transaction_cost = self.calculate_transaction_costs(
            entry_call, entry_put, exit_call, exit_put
        )

        # Net P&L
        net_pnl = gross_pnl - transaction_cost

        return {
            'date': trade_date.strftime('%Y-%m-%d'),
            'day_of_week': trade_date.strftime('%A'),
            'nifty_entry': round(nifty_entry, 2),
            'nifty_exit': round(nifty_exit, 2),
            'nifty_move': round(nifty_move, 2),
            'nifty_move_pct': round(nifty_move_pct, 2),
            'vix': round(vix, 2),
            'atm_strike': atm_strike,
            'days_to_expiry': days_to_expiry,
            'entry_call': round(entry_call, 2),
            'entry_put': round(entry_put, 2),
            'entry_straddle': round(entry_call + entry_put, 2),
            'exit_call': round(exit_call, 2),
            'exit_put': round(exit_put, 2),
            'exit_straddle': round(exit_call + exit_put, 2),
            'premium_collected': round(premium_collected, 2),
            'premium_paid': round(premium_paid, 2),
            'gross_pnl': round(gross_pnl, 2),
            'transaction_cost': round(transaction_cost, 2),
            'net_pnl': round(net_pnl, 2)
        }

    def run_backtest(self, months: int = 6) -> List[Dict]:
        """
        Run backtest for past N months

        Args:
            months: Number of months to backtest

        Returns:
            List of trade results
        """
        logger.info("=" * 80)
        logger.info(f"ATM STRADDLE BACKTEST - Past {months} Months")
        logger.info("=" * 80)
        logger.info(f"Strategy: Sell ATM Call + Put at 10:05 AM, Close at 3:10 PM")
        logger.info(f"Expiry: Next week (weekly options)")
        logger.info(f"Position Size: {self.lots_traded} lot ({self.lot_size} qty)")
        logger.info("=" * 80)

        if not self.initialize_kite():
            logger.error("Cannot proceed without Kite connection")
            return []

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=months * 30 + 30)  # Extra buffer

        # Fetch historical NIFTY data
        logger.info(f"\nFetching NIFTY historical data from {start_date.date()} to {end_date.date()}...")
        nifty_data = self.kite.historical_data(
            instrument_token=self.nifty_token,
            from_date=start_date,
            to_date=end_date,
            interval='day'
        )

        if not nifty_data:
            logger.error("Failed to fetch NIFTY data")
            return []

        logger.info(f"✅ Fetched {len(nifty_data)} days of NIFTY data")

        # Fetch historical VIX data
        logger.info(f"Fetching VIX data...")
        vix_data = self.kite.historical_data(
            instrument_token=self.vix_token,
            from_date=start_date,
            to_date=end_date,
            interval='day'
        )

        if not vix_data:
            logger.error("Failed to fetch VIX data")
            return []

        logger.info(f"✅ Fetched {len(vix_data)} days of VIX data\n")

        # Create VIX lookup
        vix_dict = {v['date'].date(): v['close'] for v in vix_data}

        # Get trading days for backtest period
        test_start = end_date - timedelta(days=months * 30)
        trading_days = []

        for nifty_row in nifty_data:
            date = nifty_row['date'].date()
            if date >= test_start.date() and date <= end_date.date():
                if date.weekday() < 5 and not is_nse_holiday(date):
                    trading_days.append(nifty_row['date'])

        logger.info(f"Testing {len(trading_days)} trading days\n")
        logger.info("=" * 80)

        # Backtest each day
        results = []
        skipped = 0

        for i, trade_date in enumerate(trading_days, 1):
            try:
                # Get intraday data for this specific day
                intraday_data = self.fetch_historical_spot_data(trade_date, self.nifty_token)

                if not intraday_data:
                    logger.debug(f"[{i}/{len(trading_days)}] {trade_date.date()} - No intraday data, skipping")
                    skipped += 1
                    continue

                # Get VIX for this day
                vix = vix_dict.get(trade_date.date())
                if not vix:
                    logger.debug(f"[{i}/{len(trading_days)}] {trade_date.date()} - No VIX data, skipping")
                    skipped += 1
                    continue

                # Backtest this day
                result = self.backtest_single_day(
                    trade_date,
                    intraday_data['entry_price'],
                    intraday_data['exit_price'],
                    vix
                )

                results.append(result)

                # Log result
                pnl_color = "✅" if result['net_pnl'] > 0 else "❌"
                logger.info(
                    f"[{i}/{len(trading_days)}] {result['date']} ({result['day_of_week']:9s}) | "
                    f"NIFTY: {result['nifty_move']:+6.2f} ({result['nifty_move_pct']:+5.2f}%) | "
                    f"VIX: {result['vix']:5.2f} | "
                    f"P&L: {pnl_color} ₹{result['net_pnl']:8.2f}"
                )

            except Exception as e:
                logger.error(f"Error backtesting {trade_date.date()}: {e}")
                skipped += 1
                continue

        logger.info("\n" + "=" * 80)
        logger.info(f"✅ Backtest complete: {len(results)} trades executed, {skipped} days skipped")
        logger.info("=" * 80)

        return results

    def analyze_results(self, results: List[Dict]) -> Dict:
        """
        Comprehensive analysis of backtest results

        Args:
            results: List of trade results

        Returns:
            Dict with analysis insights
        """
        if not results:
            return {}

        df = pd.DataFrame(results)

        # Overall statistics
        total_trades = len(df)
        winning_trades = len(df[df['net_pnl'] > 0])
        losing_trades = len(df[df['net_pnl'] <= 0])
        win_rate = (winning_trades / total_trades) * 100

        total_pnl = df['net_pnl'].sum()
        avg_pnl = df['net_pnl'].mean()
        max_profit = df['net_pnl'].max()
        max_loss = df['net_pnl'].min()

        # Day of week analysis
        day_stats = df.groupby('day_of_week').agg({
            'net_pnl': ['count', 'sum', 'mean'],
        }).round(2)

        # Win rate by day
        day_wins = df[df['net_pnl'] > 0].groupby('day_of_week').size()
        day_total = df.groupby('day_of_week').size()
        day_win_rate = (day_wins / day_total * 100).round(1)

        # VIX level analysis
        df['vix_bucket'] = pd.cut(
            df['vix'],
            bins=[0, 12, 15, 20, 100],
            labels=['Low (<12)', 'Medium (12-15)', 'High (15-20)', 'Very High (>20)']
        )

        vix_stats = df.groupby('vix_bucket').agg({
            'net_pnl': ['count', 'sum', 'mean']
        }).round(2)

        # Movement analysis
        df['move_bucket'] = pd.cut(
            df['nifty_move_pct'].abs(),
            bins=[0, 0.5, 1.0, 1.5, 100],
            labels=['Tiny (<0.5%)', 'Small (0.5-1%)', 'Medium (1-1.5%)', 'Large (>1.5%)']
        )

        move_stats = df.groupby('move_bucket').agg({
            'net_pnl': ['count', 'sum', 'mean']
        }).round(2)

        # Cumulative P&L
        df['cumulative_pnl'] = df['net_pnl'].cumsum()

        # Drawdown analysis
        df['peak'] = df['cumulative_pnl'].cummax()
        df['drawdown'] = df['cumulative_pnl'] - df['peak']
        max_drawdown = df['drawdown'].min()

        return {
            'overall': {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl,
                'max_profit': max_profit,
                'max_loss': max_loss,
                'max_drawdown': max_drawdown
            },
            'day_of_week': {
                'stats': day_stats,
                'win_rate': day_win_rate
            },
            'vix_levels': vix_stats,
            'nifty_movement': move_stats,
            'dataframe': df
        }

    def generate_report(self, results: List[Dict], analysis: Dict):
        """
        Generate comprehensive backtest report

        Args:
            results: List of trade results
            analysis: Analysis insights
        """
        # Save detailed trades to CSV
        output_dir = Path("data/backtests")
        output_dir.mkdir(parents=True, exist_ok=True)

        trades_csv = output_dir / "atm_straddle_6months_nextweek_trades.csv"
        df = pd.DataFrame(results)
        df.to_csv(trades_csv, index=False)
        logger.info(f"\n💾 Saved {len(results)} trades to {trades_csv}")

        # Generate markdown report
        report_path = output_dir / "ATM_STRADDLE_6MONTH_NEXTWEEK_BACKTEST.md"

        with open(report_path, 'w') as f:
            f.write("# ATM Straddle 6-Month Backtest Analysis (NEXT WEEK EXPIRY ONLY)\n\n")
            f.write(f"**Backtest Date:** {datetime.now().strftime('%B %d, %Y')}\n")
            f.write(f"**Period:** {results[0]['date']} to {results[-1]['date']}\n")
            f.write(f"**Strategy:** Sell ATM Call + Put at 10:05 AM, Close at 3:10 PM (Next Week Expiry ONLY)\n")
            f.write(f"**Expiry Policy:** ALWAYS next week Thursday (6-10 DTE), NEVER current week (avoids 1-3 DTE gamma risk)\n")
            f.write(f"**Position Size:** {self.lots_traded} lot ({self.lot_size} qty)\n\n")

            f.write("---\n\n")
            f.write("## 📊 OVERALL PERFORMANCE\n\n")

            overall = analysis['overall']
            f.write(f"- **Total Trades:** {overall['total_trades']}\n")
            f.write(f"- **Winning Trades:** {overall['winning_trades']} ({overall['win_rate']:.1f}%)\n")
            f.write(f"- **Losing Trades:** {overall['losing_trades']} ({100-overall['win_rate']:.1f}%)\n")
            f.write(f"- **Total P&L:** ₹{overall['total_pnl']:,.2f}\n")
            f.write(f"- **Average P&L per Trade:** ₹{overall['avg_pnl']:.2f}\n")
            f.write(f"- **Best Trade:** ₹{overall['max_profit']:,.2f}\n")
            f.write(f"- **Worst Trade:** ₹{overall['max_loss']:,.2f}\n")
            f.write(f"- **Maximum Drawdown:** ₹{overall['max_drawdown']:,.2f}\n\n")

            # Performance verdict
            if overall['total_pnl'] > 0 and overall['win_rate'] > 60:
                verdict = "🟢 **PROFITABLE STRATEGY** - Good win rate and positive returns"
            elif overall['total_pnl'] > 0:
                verdict = "🟡 **MARGINALLY PROFITABLE** - Positive returns but lower win rate"
            else:
                verdict = "🔴 **LOSING STRATEGY** - Negative returns, needs refinement"

            f.write(f"### Verdict: {verdict}\n\n")

            f.write("---\n\n")
            f.write("## 📅 DAY OF WEEK ANALYSIS\n\n")
            f.write("Which days are most profitable for straddle selling?\n\n")

            # Day of week table
            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
            f.write("| Day | Trades | Total P&L | Avg P&L | Win Rate |\n")
            f.write("|-----|--------|-----------|---------|----------|\n")

            day_stats_df = analysis['day_of_week']['stats']
            day_win_rate = analysis['day_of_week']['win_rate']

            for day in day_order:
                if day in day_stats_df.index:
                    row = day_stats_df.loc[day]
                    trades = int(row[('net_pnl', 'count')])
                    total = row[('net_pnl', 'sum')]
                    avg = row[('net_pnl', 'mean')]
                    wr = day_win_rate.get(day, 0)

                    f.write(f"| {day:9s} | {trades:6d} | ₹{total:8,.2f} | ₹{avg:6.2f} | {wr:5.1f}% |\n")

            f.write("\n")

            f.write("---\n\n")
            f.write("## 📈 VIX LEVEL ANALYSIS\n\n")
            f.write("How does VIX affect profitability?\n\n")

            f.write("| VIX Level | Trades | Total P&L | Avg P&L |\n")
            f.write("|-----------|--------|-----------|---------|------|\n")

            vix_stats = analysis['vix_levels']
            for vix_level in vix_stats.index:
                row = vix_stats.loc[vix_level]
                trades = int(row[('net_pnl', 'count')])
                total = row[('net_pnl', 'sum')]
                avg = row[('net_pnl', 'mean')]

                f.write(f"| {str(vix_level):13s} | {trades:6d} | ₹{total:8,.2f} | ₹{avg:6.2f} |\n")

            f.write("\n")

            f.write("---\n\n")
            f.write("## 🎯 NIFTY MOVEMENT ANALYSIS\n\n")
            f.write("How does NIFTY movement affect straddle P&L?\n\n")

            f.write("| Movement | Trades | Total P&L | Avg P&L |\n")
            f.write("|----------|--------|-----------|---------|------|\n")

            move_stats = analysis['nifty_movement']
            for move_bucket in move_stats.index:
                row = move_stats.loc[move_bucket]
                trades = int(row[('net_pnl', 'count')])
                total = row[('net_pnl', 'sum')]
                avg = row[('net_pnl', 'mean')]

                f.write(f"| {str(move_bucket):12s} | {trades:6d} | ₹{total:8,.2f} | ₹{avg:6.2f} |\n")

            f.write("\n")
            f.write("**Key Insight:** Straddles profit most when NIFTY movement is minimal (time decay > directional move)\n\n")

            f.write("---\n\n")
            f.write("## 🏆 BEST & WORST TRADES\n\n")

            df_sorted = analysis['dataframe'].sort_values('net_pnl', ascending=False)

            f.write("### Top 5 Most Profitable Days\n\n")
            for i, (_, row) in enumerate(df_sorted.head(5).iterrows(), 1):
                f.write(f"{i}. **{row['date']} ({row['day_of_week']})** - ₹{row['net_pnl']:,.2f}\n")
                f.write(f"   - NIFTY Move: {row['nifty_move_pct']:+.2f}%, VIX: {row['vix']:.2f}\n")
                f.write(f"   - Entry Straddle: ₹{row['entry_straddle']:.2f}, Exit: ₹{row['exit_straddle']:.2f}\n\n")

            f.write("### Top 5 Worst Days\n\n")
            for i, (_, row) in enumerate(df_sorted.tail(5).iterrows(), 1):
                f.write(f"{i}. **{row['date']} ({row['day_of_week']})** - ₹{row['net_pnl']:,.2f}\n")
                f.write(f"   - NIFTY Move: {row['nifty_move_pct']:+.2f}%, VIX: {row['vix']:.2f}\n")
                f.write(f"   - Entry Straddle: ₹{row['entry_straddle']:.2f}, Exit: ₹{row['exit_straddle']:.2f}\n\n")

            f.write("---\n\n")
            f.write("## 💡 KEY INSIGHTS & RECOMMENDATIONS\n\n")

            # Generate insights based on data
            insights = []

            # Win rate insight
            if overall['win_rate'] > 70:
                insights.append("✅ **Excellent win rate** (>70%) - Strategy has strong edge")
            elif overall['win_rate'] > 60:
                insights.append("✅ **Good win rate** (>60%) - Strategy is viable")
            elif overall['win_rate'] > 50:
                insights.append("⚠️ **Moderate win rate** (>50%) - Strategy needs refinement")
            else:
                insights.append("❌ **Poor win rate** (<50%) - Strategy not recommended without changes")

            # Profitability insight
            if overall['avg_pnl'] > 500:
                insights.append("✅ **Strong average profit** (>₹500/trade) - Good risk-reward")
            elif overall['avg_pnl'] > 0:
                insights.append("⚠️ **Marginal average profit** - Risk-reward needs improvement")
            else:
                insights.append("❌ **Negative average profit** - Strategy loses money")

            # Day of week insight
            best_day = day_stats_df[('net_pnl', 'mean')].idxmax()
            worst_day = day_stats_df[('net_pnl', 'mean')].idxmin()
            insights.append(f"📅 **Best day:** {best_day}, **Worst day:** {worst_day}")

            # VIX insight
            if 'High (15-20)' in vix_stats.index or 'Very High (>20)' in vix_stats.index:
                high_vix_avg = vix_stats.loc[vix_stats.index.str.contains('High'), ('net_pnl', 'mean')].mean()
                low_vix_avg = vix_stats.loc[vix_stats.index.str.contains('Low|Medium'), ('net_pnl', 'mean')].mean()

                if high_vix_avg > low_vix_avg:
                    insights.append("📈 **Higher VIX = Better profits** - Sell when VIX is elevated")
                else:
                    insights.append("📉 **Lower VIX = Better profits** - Careful with high VIX days")

            # Movement insight
            tiny_move_avg = move_stats.loc['Tiny (<0.5%)', ('net_pnl', 'mean')] if 'Tiny (<0.5%)' in move_stats.index else 0
            large_move_avg = move_stats.loc['Large (>1.5%)', ('net_pnl', 'mean')] if 'Large (>1.5%)' in move_stats.index else 0

            if tiny_move_avg > large_move_avg:
                insights.append("🎯 **Straddles love quiet days** - Best profits when NIFTY moves <0.5%")
            else:
                insights.append("⚠️ **Big moves hurt straddles** - Avoid days with large expected movement")

            for insight in insights:
                f.write(f"{insight}\n\n")

            f.write("---\n\n")
            f.write("## 🤖 HOW THIS HELPS YOUR INDICATOR\n\n")
            f.write("Use these insights to improve your option selling indicator:\n\n")
            f.write("1. **Focus on high-probability days** - Use backtest data to identify ideal selling conditions\n")
            f.write("2. **Avoid unfavorable patterns** - Skip days with characteristics that historically lose money\n")
            f.write("3. **Optimize position sizing** - Larger positions on best setups, smaller on marginal days\n")
            f.write("4. **Validate indicator signals** - Cross-reference with historical performance patterns\n\n")

            f.write("---\n\n")
            f.write(f"*Backtest generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")

        logger.info(f"📄 Generated comprehensive report: {report_path}")

        # Print summary to console
        logger.info("\n" + "=" * 80)
        logger.info("BACKTEST SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total P&L: ₹{overall['total_pnl']:,.2f}")
        logger.info(f"Win Rate: {overall['win_rate']:.1f}% ({overall['winning_trades']}/{overall['total_trades']})")
        logger.info(f"Avg P&L per Trade: ₹{overall['avg_pnl']:.2f}")
        logger.info(f"Max Drawdown: ₹{overall['max_drawdown']:,.2f}")
        logger.info("=" * 80)


def main():
    """Run backtest"""
    backtest = ATMStraddleBacktest()

    # Run backtest for past 6 months
    results = backtest.run_backtest(months=6)

    if not results:
        logger.error("Backtest failed - no results")
        sys.exit(1)

    # Analyze results
    analysis = backtest.analyze_results(results)

    # Generate report
    backtest.generate_report(results, analysis)

    logger.info("\n✅ Backtest complete! Check data/backtests/ for detailed results.")


if __name__ == "__main__":
    main()
