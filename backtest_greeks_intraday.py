#!/usr/bin/env python3
"""
Greeks Difference Tracker - Intraday Backtest (15-minute intervals)

Tests if Greeks differences can predict intraday moves (not just EOD).
Tracks every 15-minute interval and validates prediction accuracy.
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


class IntradayGreeksBacktest:
    """Backtest Greeks differences with 15-minute intraday intervals"""

    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self.bs_calculator = BlackScholesGreeks()
        self.results = []
        self.vix_cache = {}

    def get_trading_days(self, days_back: int = 7, include_today: bool = True) -> List[datetime]:
        """Get list of trading days"""
        trading_days = []
        current_date = datetime.now().date()

        # Include today if it's a weekday and include_today is True
        if include_today and current_date.weekday() < 5:
            trading_days.append(current_date)

        # Add past days
        for i in range(1, days_back + 10):
            date = current_date - timedelta(days=i)
            if date.weekday() >= 5:  # Skip weekends
                continue
            trading_days.append(date)
            if len(trading_days) >= days_back:
                break

        return sorted(trading_days)

    def fetch_india_vix(self, date: datetime) -> float:
        """Fetch India VIX for a specific date"""
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
        """Fetch NIFTY 15-minute data for a specific date"""
        try:
            from_date = datetime.combine(date, time(9, 15))
            to_date = datetime.combine(date, time(15, 30))
            instrument_token = 256265  # NIFTY 50

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
            print(f"❌ Error fetching NIFTY data for {date}: {e}")
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
        """Calculate Greeks for ATM and OTM strikes"""
        strikes_data = {}
        strike_offsets = [0, 50, 100, 150]

        days_to_expiry = (expiry - date).days
        time_to_expiry = max(0.02, days_to_expiry / 365.0)

        for offset in strike_offsets:
            # CE strikes
            ce_strike = atm_strike + offset
            ce_price = self.estimate_option_price(spot, ce_strike, time_to_expiry, 'CE', volatility)

            ce_greeks = self.bs_calculator.calculate_greeks_from_price(
                spot_price=spot,
                strike_price=ce_strike,
                time_to_expiry=time_to_expiry,
                option_price=ce_price,
                option_type='CE'
            )

            # PE strikes
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

    def predict_direction_delta(self, aggregated: Dict, threshold: float = 0.150) -> str:
        """
        Predict direction based on Delta differences (PRIMARY METHOD)

        Calibrated threshold (±0.150) predicts <40 point NIFTY moves as Neutral
        """
        ce_delta = aggregated['CE']['delta_diff_sum']
        pe_delta = aggregated['PE']['delta_diff_sum']

        # Both deltas increase → Bullish
        if ce_delta > threshold and pe_delta > threshold:
            return 'Bullish'

        # Both deltas decrease → Bearish
        if ce_delta < -threshold and pe_delta < -threshold:
            return 'Bearish'

        # Small delta changes → Neutral (<40 point moves expected)
        return 'Neutral'

    def predict_direction_vega(self, aggregated: Dict) -> str:
        """
        Predict direction based on Vega differences (EXPERIMENTAL)

        Note: Analysis shows Vega does NOT reliably predict direction.
        Included for comparison purposes only.
        """
        ce_vega = aggregated['CE']['vega_diff_sum']
        pe_vega = aggregated['PE']['vega_diff_sum']

        # High Vega = High uncertainty → Neutral
        if abs(ce_vega) > 10 or abs(pe_vega) > 10:
            return 'Neutral (High Vol)'

        # Rising Vega → Uncertain direction
        if ce_vega > 2 and pe_vega > 2:
            return 'Bullish'

        # Falling Vega → Uncertain direction
        if ce_vega < -2 and pe_vega < -2:
            return 'Bearish'

        return 'Neutral'

    def predict_direction(self, aggregated: Dict) -> str:
        """Legacy method - calls delta-based prediction"""
        return self.predict_direction_delta(aggregated)

    def backtest_intraday(self, date: datetime):
        """Backtest a single day with 15-minute intervals"""
        print(f"\n{'=' * 80}")
        print(f"📆 {date.strftime('%Y-%m-%d (%A)')}")
        print(f"{'=' * 80}")

        # Fetch NIFTY data
        nifty_data = self.fetch_nifty_historical(date)

        if nifty_data.empty or len(nifty_data) < 2:
            print(f"⚠️  Skipping {date} - no data available")
            return

        # Fetch VIX
        volatility = self.fetch_india_vix(date)
        print(f"India VIX: {volatility * 100:.2f}%")

        # Get expiry
        expiry = self.get_option_expiry(date)

        # Baseline (9:15 AM - first candle)
        baseline_spot = nifty_data.iloc[0]['close']
        baseline_atm = self.calculate_atm_strike(baseline_spot)

        baseline_greeks = self.calculate_greeks_for_strikes(
            spot=baseline_spot,
            atm_strike=baseline_atm,
            expiry=expiry,
            date=date,
            volatility=volatility
        )

        print(f"\n🎯 Baseline (9:15 AM):")
        print(f"   NIFTY: {baseline_spot:.2f}")
        print(f"   ATM: {baseline_atm}")

        # Track each 15-minute interval
        interval_results = []

        for i in range(1, len(nifty_data)):
            current_candle = nifty_data.iloc[i]
            current_time = current_candle['date'].strftime('%H:%M')
            current_spot = current_candle['close']

            # Calculate Greeks for current interval
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

            # Predict using both methods
            predicted_delta = self.predict_direction_delta(aggregated, threshold=0.150)
            predicted_vega = self.predict_direction_vega(aggregated)

            # Determine actual next move (if not last candle)
            if i < len(nifty_data) - 1:
                next_candle = nifty_data.iloc[i + 1]
                next_spot = next_candle['close']
                price_change = next_spot - current_spot
                abs_change = abs(price_change)

                # Actual classification
                if abs_change < 40:
                    actual = 'Neutral'
                elif price_change > 0:
                    actual = 'Bullish'
                else:
                    actual = 'Bearish'

                # Check if predictions match (handle "Neutral (High Vol)" variant)
                correct_delta = (predicted_delta.startswith('Bullish') and actual == 'Bullish') or \
                               (predicted_delta.startswith('Bearish') and actual == 'Bearish') or \
                               (predicted_delta.startswith('Neutral') and actual == 'Neutral')

                correct_vega = (predicted_vega.startswith('Bullish') and actual == 'Bullish') or \
                              (predicted_vega.startswith('Bearish') and actual == 'Bearish') or \
                              (predicted_vega.startswith('Neutral') and actual == 'Neutral')
            else:
                # Last candle - no next move to compare
                actual = 'N/A'
                correct_delta = None
                correct_vega = None
                price_change = 0
                abs_change = 0

            interval_results.append({
                'time': current_time,
                'spot': current_spot,
                'ce_delta': aggregated['CE']['delta_diff_sum'],
                'ce_theta': aggregated['CE']['theta_diff_sum'],
                'ce_vega': aggregated['CE']['vega_diff_sum'],
                'pe_delta': aggregated['PE']['delta_diff_sum'],
                'pe_theta': aggregated['PE']['theta_diff_sum'],
                'pe_vega': aggregated['PE']['vega_diff_sum'],
                'predicted_delta': predicted_delta,
                'predicted_vega': predicted_vega,
                'actual': actual,
                'correct_delta': correct_delta,
                'correct_vega': correct_vega,
                'price_change': price_change,
                'abs_change': abs_change
            })

        # Print interval summary with comparison
        print(f"\n📊 Intraday Results - Delta vs Vega Predictions:")
        print(f"\n   {'Time':<8} {'NIFTY':<10} {'Pts':<6} {'CE Δ':<8} {'PE Δ':<8} {'Delta Pred':<12} {'Vega Pred':<18} {'Actual':<10} {'Δ✓':<4} {'V✓'}")
        print(f"   {'-' * 110}")

        for r in interval_results:
            if r['correct_delta'] is not None:
                delta_icon = '✅' if r['correct_delta'] else '❌'
                vega_icon = '✅' if r['correct_vega'] else '❌'
                print(f"   {r['time']:<8} {r['spot']:<10.2f} {r['price_change']:+5.1f} "
                      f"{r['ce_delta']:+7.3f} {r['pe_delta']:+7.3f} "
                      f"{r['predicted_delta']:<12} {r['predicted_vega']:<18} "
                      f"{r['actual']:<10} {delta_icon:<4} {vega_icon}")

        # Calculate accuracy for this day
        valid_predictions = [r for r in interval_results if r['correct_delta'] is not None]
        if valid_predictions:
            # Delta accuracy
            correct_delta = sum(1 for r in valid_predictions if r['correct_delta'])
            accuracy_delta = (correct_delta / len(valid_predictions)) * 100

            # Vega accuracy
            correct_vega = sum(1 for r in valid_predictions if r['correct_vega'])
            accuracy_vega = (correct_vega / len(valid_predictions)) * 100

            print(f"\n   Day Accuracy:")
            print(f"      Delta Method: {correct_delta}/{len(valid_predictions)} = {accuracy_delta:.1f}%")
            print(f"      Vega Method:  {correct_vega}/{len(valid_predictions)} = {accuracy_vega:.1f}%")
            print(f"      Difference:   {accuracy_delta - accuracy_vega:+.1f}%")

            # Store results (use delta as primary)
            self.results.extend(valid_predictions)

    def run_backtest(self, days: int = 6, include_today: bool = True):
        """Run intraday backtest for multiple days"""
        print("=" * 80)
        print("GREEKS DIFFERENCE TRACKER - INTRADAY BACKTEST")
        print("Comparing Delta (±0.150) vs Vega Predictions")
        print("Neutral = <40 point NIFTY moves")
        print("=" * 80)

        trading_days = self.get_trading_days(days, include_today=include_today)

        print(f"\n📅 Backtesting {len(trading_days)} trading days:")
        for day in trading_days:
            is_today = (day == datetime.now().date())
            today_marker = " ← TODAY" if is_today else ""
            print(f"   - {day.strftime('%Y-%m-%d (%A)')}{today_marker}")

        # Backtest each day
        for date in trading_days:
            self.backtest_intraday(date)

        # Print overall summary
        self.print_summary()

    def print_summary(self):
        """Print overall backtest summary comparing Delta vs Vega"""
        if not self.results:
            print("\n❌ No results to summarize")
            return

        print(f"\n{'=' * 80}")
        print("📈 OVERALL BACKTEST SUMMARY - DELTA VS VEGA COMPARISON")
        print(f"{'=' * 80}")

        total = len(self.results)

        # Delta method accuracy
        correct_delta = sum(1 for r in self.results if r['correct_delta'])
        accuracy_delta = (correct_delta / total) * 100 if total > 0 else 0

        # Vega method accuracy
        correct_vega = sum(1 for r in self.results if r['correct_vega'])
        accuracy_vega = (correct_vega / total) * 100 if total > 0 else 0

        print(f"\n🎯 Overall Accuracy Comparison:")
        print(f"   Total 15-min Intervals: {total}")
        print(f"\n   DELTA METHOD (Threshold ±0.150):")
        print(f"      Correct: {correct_delta}/{total}")
        print(f"      Accuracy: {accuracy_delta:.1f}%")
        print(f"\n   VEGA METHOD (Experimental):")
        print(f"      Correct: {correct_vega}/{total}")
        print(f"      Accuracy: {accuracy_vega:.1f}%")
        print(f"\n   🏆 Winner: {'DELTA' if accuracy_delta > accuracy_vega else 'VEGA'} (+{abs(accuracy_delta - accuracy_vega):.1f}%)")

        # Delta breakdown
        print(f"\n📊 DELTA Method - Breakdown by Prediction:")

        bullish_delta = [r for r in self.results if r['predicted_delta'].startswith('Bullish')]
        if bullish_delta:
            bullish_correct = sum(1 for r in bullish_delta if r['correct_delta'])
            print(f"   Bullish: {bullish_correct}/{len(bullish_delta)} ({(bullish_correct/len(bullish_delta)*100):.1f}%)")

        bearish_delta = [r for r in self.results if r['predicted_delta'].startswith('Bearish')]
        if bearish_delta:
            bearish_correct = sum(1 for r in bearish_delta if r['correct_delta'])
            print(f"   Bearish: {bearish_correct}/{len(bearish_delta)} ({(bearish_correct/len(bearish_delta)*100):.1f}%)")

        neutral_delta = [r for r in self.results if r['predicted_delta'] == 'Neutral']
        if neutral_delta:
            neutral_correct = sum(1 for r in neutral_delta if r['correct_delta'])
            print(f"   Neutral: {neutral_correct}/{len(neutral_delta)} ({(neutral_correct/len(neutral_delta)*100):.1f}%)")

        # Vega breakdown
        print(f"\n📊 VEGA Method - Breakdown by Prediction:")

        bullish_vega = [r for r in self.results if r['predicted_vega'].startswith('Bullish')]
        if bullish_vega:
            bullish_correct = sum(1 for r in bullish_vega if r['correct_vega'])
            print(f"   Bullish: {bullish_correct}/{len(bullish_vega)} ({(bullish_correct/len(bullish_vega)*100):.1f}%)")

        bearish_vega = [r for r in self.results if r['predicted_vega'].startswith('Bearish')]
        if bearish_vega:
            bearish_correct = sum(1 for r in bearish_vega if r['correct_vega'])
            print(f"   Bearish: {bearish_correct}/{len(bearish_vega)} ({(bearish_correct/len(bearish_vega)*100):.1f}%)")

        neutral_vega = [r for r in self.results if r['predicted_vega'].startswith('Neutral')]
        if neutral_vega:
            neutral_correct = sum(1 for r in neutral_vega if r['correct_vega'])
            print(f"   Neutral: {neutral_correct}/{len(neutral_vega)} ({(neutral_correct/len(neutral_vega)*100):.1f}%)")

        # Neutral moves analysis
        print(f"\n📍 Neutral Moves (<40 points) - Key Metric:")
        neutral_moves = [r for r in self.results if r['abs_change'] < 40]
        if neutral_moves:
            delta_neutral_correct = sum(1 for r in neutral_moves if r['predicted_delta'] == 'Neutral')
            vega_neutral_correct = sum(1 for r in neutral_moves if r['predicted_vega'].startswith('Neutral'))

            print(f"   Total neutral moves: {len(neutral_moves)} ({len(neutral_moves)/total*100:.1f}%)")
            print(f"   Delta caught as Neutral: {delta_neutral_correct}/{len(neutral_moves)} ({delta_neutral_correct/len(neutral_moves)*100:.1f}%)")
            print(f"   Vega caught as Neutral: {vega_neutral_correct}/{len(neutral_moves)} ({vega_neutral_correct/len(neutral_moves)*100:.1f}%)")

        print(f"\n{'=' * 80}")


def main():
    """Main entry point"""
    print("\nInitializing intraday backtest...")

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Create backtest
    backtest = IntradayGreeksBacktest(kite)

    # Run 1-week intraday backtest (includes today)
    backtest.run_backtest(days=6, include_today=True)

    print("\n✅ Intraday backtest complete!")


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
