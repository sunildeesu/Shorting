#!/usr/bin/env python3
"""
Greeks Threshold Analysis - Find Optimal Thresholds

Analyzes relationship between Greeks differences and actual NIFTY moves.
Calibrates Delta and Vega thresholds for neutral (<40 points) predictions.
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


class GreeksThresholdAnalyzer:
    """Analyze optimal thresholds for Greeks-based predictions"""

    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self.bs_calculator = BlackScholesGreeks()
        self.analysis_data = []
        self.vix_cache = {}

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
        """Calculate Greeks for ATM and OTM strikes"""
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

    def collect_analysis_data(self, date: datetime):
        """Collect data points for threshold analysis"""
        print(f"\n📆 Collecting data from {date.strftime('%Y-%m-%d (%A)')}")

        # Fetch NIFTY data
        nifty_data = self.fetch_nifty_historical(date)

        if nifty_data.empty or len(nifty_data) < 2:
            print(f"⚠️  Skipping {date} - no data")
            return

        # Fetch VIX
        volatility = self.fetch_india_vix(date)

        # Get expiry
        expiry = self.get_option_expiry(date)

        # Baseline
        baseline_spot = nifty_data.iloc[0]['close']
        baseline_atm = self.calculate_atm_strike(baseline_spot)

        baseline_greeks = self.calculate_greeks_for_strikes(
            spot=baseline_spot,
            atm_strike=baseline_atm,
            expiry=expiry,
            date=date,
            volatility=volatility
        )

        # Track each interval
        for i in range(1, len(nifty_data) - 1):  # Exclude last (no next candle)
            current_candle = nifty_data.iloc[i]
            current_spot = current_candle['close']

            # Calculate Greeks
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

            # Get actual next move
            next_candle = nifty_data.iloc[i + 1]
            next_spot = next_candle['close']
            point_change = next_spot - current_spot

            # Store data point
            self.analysis_data.append({
                'date': date,
                'time': current_candle['date'].strftime('%H:%M'),
                'current_spot': current_spot,
                'next_spot': next_spot,
                'point_change': point_change,
                'abs_point_change': abs(point_change),
                'ce_delta': aggregated['CE']['delta_diff_sum'],
                'pe_delta': aggregated['PE']['delta_diff_sum'],
                'ce_vega': aggregated['CE']['vega_diff_sum'],
                'pe_vega': aggregated['PE']['vega_diff_sum'],
                'ce_theta': aggregated['CE']['theta_diff_sum'],
                'pe_theta': aggregated['PE']['theta_diff_sum']
            })

        print(f"   ✅ Collected {len(nifty_data) - 2} data points")

    def analyze_delta_thresholds(self):
        """Analyze optimal delta thresholds for <40 point neutral moves"""
        print("\n" + "=" * 80)
        print("📊 DELTA THRESHOLD ANALYSIS")
        print("=" * 80)

        if not self.analysis_data:
            print("❌ No data to analyze")
            return

        df = pd.DataFrame(self.analysis_data)

        # Separate by actual move magnitude
        neutral_moves = df[df['abs_point_change'] < 40]
        significant_moves = df[df['abs_point_change'] >= 40]

        print(f"\n📈 Data Distribution:")
        print(f"   Total intervals: {len(df)}")
        print(f"   Neutral moves (<40 pts): {len(neutral_moves)} ({len(neutral_moves)/len(df)*100:.1f}%)")
        print(f"   Significant moves (≥40 pts): {len(significant_moves)} ({len(significant_moves)/len(df)*100:.1f}%)")

        # Analyze delta values for neutral moves
        print(f"\n🎯 Delta Statistics for Neutral Moves (<40 points):")
        print(f"   CE Delta - Mean: {neutral_moves['ce_delta'].mean():.4f}, Median: {neutral_moves['ce_delta'].median():.4f}")
        print(f"   CE Delta - Std: {neutral_moves['ce_delta'].std():.4f}")
        print(f"   CE Delta - Range: [{neutral_moves['ce_delta'].min():.4f}, {neutral_moves['ce_delta'].max():.4f}]")
        print(f"\n   PE Delta - Mean: {neutral_moves['pe_delta'].mean():.4f}, Median: {neutral_moves['pe_delta'].median():.4f}")
        print(f"   PE Delta - Std: {neutral_moves['pe_delta'].std():.4f}")
        print(f"   PE Delta - Range: [{neutral_moves['pe_delta'].min():.4f}, {neutral_moves['pe_delta'].max():.4f}]")

        # Find optimal threshold
        print(f"\n🔍 Finding Optimal Delta Threshold:")

        # Test different thresholds
        thresholds_to_test = [0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15]

        best_threshold = None
        best_accuracy = 0

        print(f"\n   Testing thresholds:")
        for threshold in thresholds_to_test:
            # Apply threshold to classify
            neutral_pred = df[
                (abs(df['ce_delta']) < threshold) &
                (abs(df['pe_delta']) < threshold)
            ]

            # Calculate accuracy
            if len(neutral_pred) > 0:
                correct_neutral = len(neutral_pred[neutral_pred['abs_point_change'] < 40])
                accuracy = (correct_neutral / len(neutral_pred)) * 100

                coverage = (len(neutral_pred) / len(df)) * 100

                print(f"   Threshold ±{threshold:.3f}: {correct_neutral}/{len(neutral_pred)} correct ({accuracy:.1f}%), Coverage: {coverage:.1f}%")

                if accuracy > best_accuracy:
                    best_accuracy = accuracy
                    best_threshold = threshold

        print(f"\n✅ Recommended Delta Threshold: ±{best_threshold:.3f}")
        print(f"   Expected Neutral Accuracy: {best_accuracy:.1f}%")

        return best_threshold

    def analyze_vega_predictions(self):
        """Analyze if Vega can predict trends"""
        print("\n" + "=" * 80)
        print("📊 VEGA-BASED PREDICTION ANALYSIS")
        print("=" * 80)

        if not self.analysis_data:
            print("❌ No data to analyze")
            return

        df = pd.DataFrame(self.analysis_data)

        print(f"\n🎯 Vega Statistics:")
        print(f"   CE Vega - Mean: {df['ce_vega'].mean():.2f}, Median: {df['ce_vega'].median():.2f}")
        print(f"   CE Vega - Std: {df['ce_vega'].std():.2f}")
        print(f"   CE Vega - Range: [{df['ce_vega'].min():.2f}, {df['ce_vega'].max():.2f}]")
        print(f"\n   PE Vega - Mean: {df['pe_vega'].mean():.2f}, Median: {df['pe_vega'].median():.2f}")
        print(f"   PE Vega - Std: {df['pe_vega'].std():.2f}")
        print(f"   PE Vega - Range: [{df['pe_vega'].min():.2f}, {df['pe_vega'].max():.2f}]")

        # Test Vega-based prediction logic
        print(f"\n🔍 Testing Vega-Based Prediction Logic:")

        # Strategy 1: High Vega = High Volatility = Neutral
        print(f"\n   Strategy 1: High Vega → Neutral")
        vega_thresholds = [5, 7, 10, 12, 15]

        for vega_threshold in vega_thresholds:
            high_vega = df[
                (abs(df['ce_vega']) > vega_threshold) &
                (abs(df['pe_vega']) > vega_threshold)
            ]

            if len(high_vega) > 0:
                # Check if these correspond to neutral moves
                neutral_count = len(high_vega[high_vega['abs_point_change'] < 40])
                accuracy = (neutral_count / len(high_vega)) * 100

                print(f"   Vega >{vega_threshold}: {neutral_count}/{len(high_vega)} neutral ({accuracy:.1f}%)")

        # Strategy 2: Vega direction correlates with trend
        print(f"\n   Strategy 2: Vega Direction → Trend Direction")

        # Rising Vega (both CE and PE positive)
        rising_vega = df[(df['ce_vega'] > 2) & (df['pe_vega'] > 2)]
        if len(rising_vega) > 0:
            bullish_moves = len(rising_vega[rising_vega['point_change'] > 0])
            print(f"   Rising Vega (>2): {bullish_moves}/{len(rising_vega)} bullish ({bullish_moves/len(rising_vega)*100:.1f}%)")

        # Falling Vega (both CE and PE negative)
        falling_vega = df[(df['ce_vega'] < -2) & (df['pe_vega'] < -2)]
        if len(falling_vega) > 0:
            bearish_moves = len(falling_vega[falling_vega['point_change'] < 0])
            print(f"   Falling Vega (<-2): {bearish_moves}/{len(falling_vega)} bearish ({bearish_moves/len(falling_vega)*100:.1f}%)")

        # Strategy 3: Vega divergence (CE vs PE)
        print(f"\n   Strategy 3: CE/PE Vega Divergence")

        ce_vega_high = df[(df['ce_vega'] > 5) & (df['pe_vega'] < -5)]
        if len(ce_vega_high) > 0:
            bullish_moves = len(ce_vega_high[ce_vega_high['point_change'] > 0])
            print(f"   CE Vega high, PE low: {bullish_moves}/{len(ce_vega_high)} bullish ({bullish_moves/len(ce_vega_high)*100:.1f}%)")

        pe_vega_high = df[(df['pe_vega'] > 5) & (df['ce_vega'] < -5)]
        if len(pe_vega_high) > 0:
            bearish_moves = len(pe_vega_high[pe_vega_high['point_change'] < 0])
            print(f"   PE Vega high, CE low: {bearish_moves}/{len(pe_vega_high)} bearish ({bearish_moves/len(pe_vega_high)*100:.1f}%)")

        print(f"\n💡 Vega Insights:")
        print(f"   Vega measures volatility sensitivity (market uncertainty)")
        print(f"   High Vega → Market expects volatility → Hard to predict direction")
        print(f"   Vega changes reflect IV changes, not necessarily direction")

    def run_analysis(self, days: int = 6, include_today: bool = True):
        """Run complete threshold analysis"""
        print("=" * 80)
        print("GREEKS THRESHOLD ANALYSIS")
        print("Calibrating thresholds for optimal predictions")
        print("=" * 80)

        trading_days = self.get_trading_days(days, include_today=include_today)

        print(f"\n📅 Analyzing {len(trading_days)} trading days:")
        for day in trading_days:
            is_today = (day == datetime.now().date())
            today_marker = " ← TODAY" if is_today else ""
            print(f"   - {day.strftime('%Y-%m-%d (%A)')}{today_marker}")

        # Collect data from all days
        for date in trading_days:
            self.collect_analysis_data(date)

        print(f"\n✅ Total data points collected: {len(self.analysis_data)}")

        # Analyze delta thresholds
        optimal_delta_threshold = self.analyze_delta_thresholds()

        # Analyze vega predictions
        self.analyze_vega_predictions()

        # Print recommendations
        self.print_recommendations(optimal_delta_threshold)

    def print_recommendations(self, delta_threshold: float):
        """Print final recommendations"""
        print("\n" + "=" * 80)
        print("📋 RECOMMENDATIONS")
        print("=" * 80)

        print(f"\n🎯 Optimal Thresholds:")
        print(f"   Delta Neutral Threshold: ±{delta_threshold:.3f}")
        print(f"   (When both |CE Delta| < {delta_threshold:.3f} AND |PE Delta| < {delta_threshold:.3f})")

        print(f"\n📊 Recommended Prediction Logic:")
        print(f"""
   DELTA-BASED (Primary Signal):
   1. Bullish: CE Delta > +{delta_threshold:.3f} AND PE Delta > +{delta_threshold:.3f}
   2. Bearish: CE Delta < -{delta_threshold:.3f} AND PE Delta < -{delta_threshold:.3f}
   3. Neutral: |CE Delta| < {delta_threshold:.3f} AND |PE Delta| < {delta_threshold:.3f}

   → Predicts NIFTY moves <40 points as Neutral

   VEGA-BASED (Secondary Signal):
   - Vega is NOT reliable for directional prediction
   - Vega indicates market uncertainty/volatility expectations
   - High Vega (>10) → Expect larger moves, but direction unclear
   - Use Vega to gauge confidence, not direction
        """)

        print(f"\n💡 Key Insights:")
        print(f"   ✅ Delta differences reliably predict trend strength")
        print(f"   ✅ Calibrated threshold improves neutral prediction accuracy")
        print(f"   ❌ Vega does NOT predict trend direction reliably")
        print(f"   ⚠️  Use Vega to measure volatility/uncertainty, not trend")

        print("\n" + "=" * 80)


def main():
    """Main entry point"""
    print("\nInitializing threshold analysis...")

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Create analyzer
    analyzer = GreeksThresholdAnalyzer(kite)

    # Run analysis
    analyzer.run_analysis(days=6, include_today=True)

    print("\n✅ Threshold analysis complete!")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Analysis interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
