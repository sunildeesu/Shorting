#!/usr/bin/env python3
"""
Greeks Difference Tracker - Daily Move Prediction

At each 15-minute interval, predict: Will TODAY move >40 points or <40 points?
- Neutral: Daily move <40 points
- Bullish: Daily move >40 points UP
- Bearish: Daily move >40 points DOWN
"""

import os
import sys
from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple
import pandas as pd
from kiteconnect import KiteConnect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from black_scholes_greeks import BlackScholesGreeks


class DailyGreeksBacktest:
    """Predict daily outcomes using intraday Greeks differences"""

    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self.bs_calculator = BlackScholesGreeks()
        self.daily_results = []
        self.all_interval_results = []
        self.vix_cache = {}
        self.threshold = 0.150  # Default threshold

    def get_trading_days(self, days_back: int = 7, include_today: bool = True) -> List[datetime]:
        """Get list of trading days"""
        trading_days = []
        current_date = datetime.now().date()

        if include_today and current_date.weekday() < 5:
            trading_days.append(current_date)

        for i in range(1, days_back + 10):
            date = current_date - timedelta(days=i)
            if date.weekday() >= 5:
                continue
            trading_days.append(date)
            if len(trading_days) >= days_back:
                break

        return sorted(trading_days)

    def fetch_india_vix(self, date: datetime) -> float:
        """Fetch India VIX"""
        date_key = date.strftime('%Y-%m-%d')
        if date_key in self.vix_cache:
            return self.vix_cache[date_key]

        try:
            vix_instrument_token = 264969
            from_date = datetime.combine(date, time(9, 15))
            to_date = datetime.combine(date, time(15, 30))

            vix_data = self.kite.historical_data(
                instrument_token=vix_instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval='15minute'
            )

            if not vix_data:
                return 0.10

            opening_vix = vix_data[0]['close']
            vix_decimal = opening_vix / 100.0
            self.vix_cache[date_key] = vix_decimal
            return vix_decimal

        except Exception as e:
            return 0.10

    def fetch_nifty_historical(self, date: datetime) -> pd.DataFrame:
        """Fetch NIFTY 15-minute data"""
        try:
            from_date = datetime.combine(date, time(9, 15))
            to_date = datetime.combine(date, time(15, 30))
            instrument_token = 256265

            historical_data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval='15minute'
            )

            if not historical_data:
                return pd.DataFrame()

            df = pd.DataFrame(historical_data)
            return df

        except Exception as e:
            return pd.DataFrame()

    def calculate_atm_strike(self, spot_price: float) -> int:
        """Calculate ATM strike"""
        return int(round(spot_price / 50.0) * 50)

    def get_option_expiry(self, date: datetime) -> datetime:
        """Get next week expiry"""
        days_ahead = 3 - date.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        expiry = date + timedelta(days=days_ahead)
        if (expiry - date).days < 7:
            expiry += timedelta(days=7)
        return expiry

    def calculate_greeks_for_strikes(
        self,
        spot: float,
        atm_strike: int,
        expiry: datetime,
        date: datetime,
        volatility: float
    ) -> Dict:
        """Calculate Greeks for strikes"""
        strikes_data = {}
        strike_offsets = [0, 50, 100, 150]

        days_to_expiry = (expiry - date).days
        time_to_expiry = max(0.02, days_to_expiry / 365.0)

        for offset in strike_offsets:
            ce_strike = atm_strike + offset
            ce_price = self.estimate_option_price(spot, ce_strike, time_to_expiry, 'CE', volatility)

            ce_greeks = self.bs_calculator.calculate_greeks_from_price(
                spot_price=spot,
                strike_price=ce_strike,
                time_to_expiry=time_to_expiry,
                option_price=ce_price,
                option_type='CE'
            )

            if offset == 0:
                pe_strike = atm_strike
            else:
                pe_strike = atm_strike - offset

            pe_price = self.estimate_option_price(spot, pe_strike, time_to_expiry, 'PE', volatility)

            pe_greeks = self.bs_calculator.calculate_greeks_from_price(
                spot_price=spot,
                strike_price=pe_strike,
                time_to_expiry=time_to_expiry,
                option_price=pe_price,
                option_type='PE'
            )

            strikes_data[ce_strike] = {
                'CE': ce_greeks,
                'PE': pe_greeks
            }

        return strikes_data

    def estimate_option_price(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,
        option_type: str,
        volatility: float
    ) -> float:
        """Estimate option price using Black-Scholes"""
        import math
        from scipy.stats import norm

        if time_to_expiry <= 0.001:
            if option_type == 'CE':
                return max(0.05, spot - strike)
            else:
                return max(0.05, strike - spot)

        d1 = (math.log(spot / strike) + (0.065 + 0.5 * volatility ** 2) * time_to_expiry) / (
            volatility * math.sqrt(time_to_expiry)
        )
        d2 = d1 - volatility * math.sqrt(time_to_expiry)

        if option_type == 'CE':
            price = spot * norm.cdf(d1) - strike * math.exp(-0.065 * time_to_expiry) * norm.cdf(d2)
        else:
            price = strike * math.exp(-0.065 * time_to_expiry) * norm.cdf(-d2) - spot * norm.cdf(-d1)

        return max(0.05, price)

    def calculate_differences(self, baseline: Dict, current: Dict) -> Dict:
        """Calculate Greeks differences"""
        differences = {}

        for strike in baseline.keys():
            if strike not in current:
                continue

            differences[strike] = {}

            for opt_type in ['CE', 'PE']:
                differences[strike][opt_type] = {
                    'delta': current[strike][opt_type]['delta'] - baseline[strike][opt_type]['delta'],
                    'theta': current[strike][opt_type]['theta'] - baseline[strike][opt_type]['theta'],
                    'vega': current[strike][opt_type]['vega'] - baseline[strike][opt_type]['vega']
                }

        return differences

    def aggregate_by_type(self, differences: Dict) -> Dict:
        """Aggregate differences by CE/PE"""
        ce_sums = {'delta_diff_sum': 0, 'theta_diff_sum': 0, 'vega_diff_sum': 0}
        pe_sums = {'delta_diff_sum': 0, 'theta_diff_sum': 0, 'vega_diff_sum': 0}

        for strike, data in differences.items():
            ce_sums['delta_diff_sum'] += data['CE']['delta']
            ce_sums['theta_diff_sum'] += data['CE']['theta']
            ce_sums['vega_diff_sum'] += data['CE']['vega']

            pe_sums['delta_diff_sum'] += data['PE']['delta']
            pe_sums['theta_diff_sum'] += data['PE']['theta']
            pe_sums['vega_diff_sum'] += data['PE']['vega']

        return {'CE': ce_sums, 'PE': pe_sums}

    def predict_daily_outcome_delta(self, aggregated: Dict, threshold: float = 0.150) -> str:
        """
        Predict DAILY outcome based on Delta differences

        Returns: 'Bullish' (>40 pts up), 'Bearish' (>40 pts down), 'Neutral' (<40 pts)
        """
        ce_delta = aggregated['CE']['delta_diff_sum']
        pe_delta = aggregated['PE']['delta_diff_sum']

        # Both deltas strongly positive → Bullish day expected
        if ce_delta > threshold and pe_delta > threshold:
            return 'Bullish'

        # Both deltas strongly negative → Bearish day expected
        if ce_delta < -threshold and pe_delta < -threshold:
            return 'Bearish'

        # Small delta changes → Neutral day (<40 pts)
        return 'Neutral'

    def predict_daily_outcome_vega(self, aggregated: Dict) -> str:
        """Vega-based prediction (for comparison)"""
        ce_vega = aggregated['CE']['vega_diff_sum']
        pe_vega = aggregated['PE']['vega_diff_sum']

        # High Vega = High uncertainty → Neutral
        if abs(ce_vega) > 10 or abs(pe_vega) > 10:
            return 'Neutral'

        # Rising Vega
        if ce_vega > 2 and pe_vega > 2:
            return 'Bullish'

        # Falling Vega
        if ce_vega < -2 and pe_vega < -2:
            return 'Bearish'

        return 'Neutral'

    def backtest_day(self, date: datetime, verbose: bool = True):
        """Backtest a single day - predict daily outcome from each interval"""
        if verbose:
            print(f"\n{'=' * 100}")
            print(f"📆 {date.strftime('%Y-%m-%d (%A)')}")
            print(f"{'=' * 100}")

        # Fetch NIFTY data
        nifty_data = self.fetch_nifty_historical(date)

        if nifty_data.empty or len(nifty_data) < 2:
            if verbose:
                print(f"⚠️  Skipping {date} - no data")
            return

        # Calculate ACTUAL DAILY OUTCOME
        opening_price = nifty_data.iloc[0]['close']
        closing_price = nifty_data.iloc[-1]['close']
        daily_move = closing_price - opening_price

        # Classify the day
        if abs(daily_move) < 40:
            actual_outcome = 'Neutral'
        elif daily_move > 0:
            actual_outcome = 'Bullish'
        else:
            actual_outcome = 'Bearish'

        if verbose:
            print(f"\n🎯 Daily Outcome:")
            print(f"   Open: {opening_price:.2f}")
            print(f"   Close: {closing_price:.2f}")
            print(f"   Move: {daily_move:+.2f} points")
            print(f"   Classification: {actual_outcome}")

        # Fetch VIX
        volatility = self.fetch_india_vix(date)
        if verbose:
            print(f"   India VIX: {volatility * 100:.2f}%")

        # Get expiry
        expiry = self.get_option_expiry(date)

        # Baseline (9:15 AM)
        baseline_spot = nifty_data.iloc[0]['close']
        baseline_atm = self.calculate_atm_strike(baseline_spot)

        baseline_greeks = self.calculate_greeks_for_strikes(
            spot=baseline_spot,
            atm_strike=baseline_atm,
            expiry=expiry,
            date=date,
            volatility=volatility
        )

        # Track predictions from each interval
        interval_predictions = []

        if verbose:
            print(f"\n📊 Predictions Throughout the Day:")
            print(f"\n   {'Time':<8} {'NIFTY':<10} {'CE Δ':<8} {'PE Δ':<8} {'Delta Pred':<12} {'Vega Pred':<12} {'Actual':<10} {'Δ✓':<4} {'V✓'}")
            print(f"   {'-' * 100}")

        for i in range(1, len(nifty_data)):
            current_candle = nifty_data.iloc[i]
            current_time = current_candle['date'].strftime('%H:%M')
            current_spot = current_candle['close']

            # Calculate current Greeks
            current_greeks = self.calculate_greeks_for_strikes(
                spot=current_spot,
                atm_strike=baseline_atm,
                expiry=expiry,
                date=date,
                volatility=volatility
            )

            # Calculate differences
            differences = self.calculate_differences(baseline_greeks, current_greeks)
            aggregated = self.aggregate_by_type(differences)

            # Predict daily outcome
            predicted_delta = self.predict_daily_outcome_delta(aggregated, threshold=self.threshold)
            predicted_vega = self.predict_daily_outcome_vega(aggregated)

            # Check if predictions match DAILY outcome
            correct_delta = (predicted_delta == actual_outcome)
            correct_vega = (predicted_vega == actual_outcome)

            delta_icon = '✅' if correct_delta else '❌'
            vega_icon = '✅' if correct_vega else '❌'

            if verbose:
                print(f"   {current_time:<8} {current_spot:<10.2f} "
                      f"{aggregated['CE']['delta_diff_sum']:+7.3f} {aggregated['PE']['delta_diff_sum']:+7.3f} "
                      f"{predicted_delta:<12} {predicted_vega:<12} "
                      f"{actual_outcome:<10} {delta_icon:<4} {vega_icon}")

            interval_predictions.append({
                'date': date,
                'time': current_time,
                'spot': current_spot,
                'ce_delta': aggregated['CE']['delta_diff_sum'],
                'pe_delta': aggregated['PE']['delta_diff_sum'],
                'ce_vega': aggregated['CE']['vega_diff_sum'],
                'pe_vega': aggregated['PE']['vega_diff_sum'],
                'predicted_delta': predicted_delta,
                'predicted_vega': predicted_vega,
                'actual_outcome': actual_outcome,
                'correct_delta': correct_delta,
                'correct_vega': correct_vega,
                'daily_move': daily_move
            })

        # Calculate accuracy for this day
        delta_correct = sum(1 for p in interval_predictions if p['correct_delta'])
        vega_correct = sum(1 for p in interval_predictions if p['correct_vega'])
        total = len(interval_predictions)

        if verbose:
            print(f"\n   Day Summary:")
            print(f"      Delta Accuracy: {delta_correct}/{total} = {delta_correct/total*100:.1f}%")
            print(f"      Vega Accuracy:  {vega_correct}/{total} = {vega_correct/total*100:.1f}%")

        # Store results
        self.all_interval_results.extend(interval_predictions)
        self.daily_results.append({
            'date': date,
            'daily_move': daily_move,
            'actual_outcome': actual_outcome,
            'delta_accuracy': delta_correct / total * 100,
            'vega_accuracy': vega_correct / total * 100
        })

    def run_backtest(self, days: int = 6, include_today: bool = True, threshold: float = 0.150, verbose: bool = True):
        """Run backtest for multiple days"""
        if verbose:
            print("=" * 100)
            print("GREEKS DAILY OUTCOME PREDICTION - BACKTEST")
            print("Predicting: Will TODAY move >40 points or <40 points?")
            print(f"Delta Threshold: ±{threshold:.3f}")
            print("=" * 100)

        # Store threshold for predictions
        self.threshold = threshold

        trading_days = self.get_trading_days(days, include_today=include_today)

        if verbose:
            print(f"\n📅 Backtesting {len(trading_days)} trading days:")
            for day in trading_days:
                is_today = (day == datetime.now().date())
                today_marker = " ← TODAY" if is_today else ""
                print(f"   - {day.strftime('%Y-%m-%d (%A)')}{today_marker}")

        # Backtest each day
        for date in trading_days:
            self.backtest_day(date, verbose=verbose)

        # Print overall summary
        if verbose:
            self.print_summary()

    def print_summary(self):
        """Print overall summary"""
        if not self.all_interval_results:
            print("\n❌ No results to summarize")
            return

        print(f"\n{'=' * 100}")
        print("📈 OVERALL SUMMARY - DAILY OUTCOME PREDICTIONS")
        print(f"{'=' * 100}")

        total_intervals = len(self.all_interval_results)

        # Overall accuracy
        delta_correct = sum(1 for r in self.all_interval_results if r['correct_delta'])
        vega_correct = sum(1 for r in self.all_interval_results if r['correct_vega'])

        print(f"\n🎯 Overall Accuracy (All Intervals):")
        print(f"   Total Predictions: {total_intervals}")
        print(f"\n   DELTA METHOD:")
        print(f"      Correct: {delta_correct}/{total_intervals}")
        print(f"      Accuracy: {delta_correct/total_intervals*100:.1f}%")
        print(f"\n   VEGA METHOD:")
        print(f"      Correct: {vega_correct}/{total_intervals}")
        print(f"      Accuracy: {vega_correct/total_intervals*100:.1f}%")
        print(f"\n   🏆 Winner: {'DELTA' if delta_correct > vega_correct else 'VEGA'} "
              f"(+{abs(delta_correct - vega_correct)} intervals)")

        # Per-day breakdown
        print(f"\n📊 Per-Day Breakdown:")
        print(f"\n   {'Date':<12} {'Move':<10} {'Actual':<10} {'Δ Acc':<10} {'V Acc':<10} {'Winner'}")
        print(f"   {'-' * 70}")

        for day in self.daily_results:
            winner = 'DELTA' if day['delta_accuracy'] > day['vega_accuracy'] else 'VEGA'
            if day['delta_accuracy'] == day['vega_accuracy']:
                winner = 'TIE'

            print(f"   {day['date'].strftime('%Y-%m-%d'):<12} {day['daily_move']:+9.2f} "
                  f"{day['actual_outcome']:<10} {day['delta_accuracy']:>6.1f}%   "
                  f"{day['vega_accuracy']:>6.1f}%   {winner}")

        # Breakdown by prediction type (Delta method)
        print(f"\n📊 DELTA Method - Breakdown:")

        bullish_pred = [r for r in self.all_interval_results if r['predicted_delta'] == 'Bullish']
        if bullish_pred:
            bullish_correct = sum(1 for r in bullish_pred if r['correct_delta'])
            print(f"   Bullish: {bullish_correct}/{len(bullish_pred)} ({bullish_correct/len(bullish_pred)*100:.1f}%)")

        bearish_pred = [r for r in self.all_interval_results if r['predicted_delta'] == 'Bearish']
        if bearish_pred:
            bearish_correct = sum(1 for r in bearish_pred if r['correct_delta'])
            print(f"   Bearish: {bearish_correct}/{len(bearish_pred)} ({bearish_correct/len(bearish_pred)*100:.1f}%)")

        neutral_pred = [r for r in self.all_interval_results if r['predicted_delta'] == 'Neutral']
        if neutral_pred:
            neutral_correct = sum(1 for r in neutral_pred if r['correct_delta'])
            print(f"   Neutral: {neutral_correct}/{len(neutral_pred)} ({neutral_correct/len(neutral_pred)*100:.1f}%)")

        print(f"\n{'=' * 100}")


def main():
    """Main entry point"""
    print("\nInitializing 1-month daily outcome backtest...")

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Create backtest
    backtest = DailyGreeksBacktest(kite)

    # Run 1-month backtest (approximately 22 trading days)
    backtest.run_backtest(days=22, include_today=True, threshold=0.150)

    print("\n✅ 1-month backtest complete!")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Backtest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
