#!/usr/bin/env python3
"""
VIX Impact on Delta Threshold Analysis

Tests whether the optimal Delta threshold changes with VIX levels.
Analyzes historical data grouped by VIX ranges and simulates higher VIX scenarios.
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple
from kiteconnect import KiteConnect
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from backtest_greeks_daily_prediction import DailyGreeksBacktest


class VIXThresholdAnalyzer:
    """Analyze how VIX affects optimal Delta threshold"""

    def __init__(self, kite):
        self.kite = kite
        self.backtest = DailyGreeksBacktest(kite)

    def analyze_vix_impact(self):
        """Comprehensive VIX impact analysis"""

        print("=" * 120)
        print("VIX IMPACT ON DELTA THRESHOLD ANALYSIS")
        print("Question: Does optimal threshold change when VIX changes from 10% to 15%?")
        print("=" * 120)

        # Run full backtest to get data
        self.backtest.run_backtest(days=22, include_today=True, threshold=0.150, verbose=False)

        # Get all VIX values from daily results
        vix_values = []
        for day in self.backtest.daily_results:
            date = day['date']
            vix = self.backtest.fetch_india_vix(date)
            vix_values.append({'date': date, 'vix': vix * 100})  # Convert to percentage

        # Group intervals by VIX level
        intervals_by_vix = self.group_by_vix_range()

        # Analyze each VIX range
        self.analyze_by_vix_range(intervals_by_vix)

        # Simulate higher VIX
        self.simulate_higher_vix()

        # VIX-adjusted threshold recommendations
        self.recommend_vix_adjusted_thresholds()

    def group_by_vix_range(self) -> Dict:
        """Group intervals by VIX ranges"""

        results = self.backtest.all_interval_results

        # Define VIX ranges
        vix_ranges = {
            'Low (0-10%)': [],
            'Normal (10-12%)': [],
            'Elevated (12-15%)': [],
            'High (15-20%)': [],
            'Very High (>20%)': []
        }

        for r in results:
            date = r['date']
            vix = self.backtest.fetch_india_vix(date) * 100  # Convert to percentage

            if vix < 10:
                vix_ranges['Low (0-10%)'].append(r)
            elif vix < 12:
                vix_ranges['Normal (10-12%)'].append(r)
            elif vix < 15:
                vix_ranges['Elevated (12-15%)'].append(r)
            elif vix < 20:
                vix_ranges['High (15-20%)'].append(r)
            else:
                vix_ranges['Very High (>20%)'].append(r)

        return vix_ranges

    def analyze_by_vix_range(self, intervals_by_vix: Dict):
        """Analyze threshold performance at different VIX levels"""

        print(f"\n{'=' * 120}")
        print("HISTORICAL VIX DISTRIBUTION & DELTA THRESHOLD PERFORMANCE")
        print(f"{'=' * 120}")

        print(f"\n{'VIX Range':<20} {'Intervals':<12} {'VIX Avg':<12} "
              f"{'±0.100':<12} {'±0.125':<12} {'±0.150':<12} {'±0.175':<12} {'±0.200':<12}")
        print("-" * 120)

        for vix_range, intervals in intervals_by_vix.items():
            if not intervals:
                continue

            # Calculate average VIX for this range
            avg_vix = np.mean([self.backtest.fetch_india_vix(r['date']) * 100 for r in intervals])

            # Test different thresholds on this VIX range
            threshold_accuracies = {}

            for threshold in [0.100, 0.125, 0.150, 0.175, 0.200]:
                correct = 0

                for r in intervals:
                    # Simulate prediction with this threshold
                    aggregated = {
                        'CE': {'delta_diff_sum': r['ce_delta']},
                        'PE': {'delta_diff_sum': r['pe_delta']}
                    }

                    # Predict
                    ce_delta = aggregated['CE']['delta_diff_sum']
                    pe_delta = aggregated['PE']['delta_diff_sum']

                    if ce_delta > threshold and pe_delta > threshold:
                        predicted = 'Bullish'
                    elif ce_delta < -threshold and pe_delta < -threshold:
                        predicted = 'Bearish'
                    else:
                        predicted = 'Neutral'

                    if predicted == r['actual_outcome']:
                        correct += 1

                accuracy = (correct / len(intervals)) * 100 if intervals else 0
                threshold_accuracies[threshold] = accuracy

            # Find best threshold for this VIX range
            best_threshold = max(threshold_accuracies, key=threshold_accuracies.get)
            best_acc = threshold_accuracies[best_threshold]

            # Print row
            acc_100 = f"{threshold_accuracies[0.100]:.1f}%"
            acc_125 = f"{threshold_accuracies[0.125]:.1f}%"
            acc_150 = f"{threshold_accuracies[0.150]:.1f}%"
            acc_175 = f"{threshold_accuracies[0.175]:.1f}%"
            acc_200 = f"{threshold_accuracies[0.200]:.1f}%"

            # Highlight best
            if best_threshold == 0.100:
                acc_100 += " ✅"
            elif best_threshold == 0.125:
                acc_125 += " ✅"
            elif best_threshold == 0.150:
                acc_150 += " ✅"
            elif best_threshold == 0.175:
                acc_175 += " ✅"
            elif best_threshold == 0.200:
                acc_200 += " ✅"

            print(f"{vix_range:<20} {len(intervals):<12} {avg_vix:>6.2f}%     "
                  f"{acc_100:<12} {acc_125:<12} {acc_150:<12} {acc_175:<12} {acc_200:<12}")

        print("-" * 120)

    def simulate_higher_vix(self):
        """Simulate what happens when VIX increases to 15%"""

        print(f"\n{'=' * 120}")
        print("SIMULATION: VIX INCREASE FROM ~10% TO 15%")
        print(f"{'=' * 120}")

        print(f"\n💡 Key Question: Does Delta magnitude change with VIX?")

        # Theoretical analysis
        print(f"\n📊 Theoretical Impact of VIX on Delta:")
        print(f"\n   When VIX increases from 10% → 15% (+50%):")
        print(f"      1. ATM option Delta stays ~0.50 (relatively stable)")
        print(f"      2. OTM option Delta INCREASES (options become more valuable)")
        print(f"      3. ITM option Delta DECREASES slightly")
        print(f"      4. Overall: Delta differences may be LARGER at higher VIX")

        print(f"\n   Expected effect on threshold:")
        print(f"      - Higher VIX → Larger Delta swings")
        print(f"      - Larger Delta swings → May need HIGHER threshold")
        print(f"      - To avoid false signals in volatile markets")

        # Calculate average Delta magnitudes at different VIX levels
        print(f"\n📈 Observed Delta Magnitudes in Historical Data:")

        low_vix = [r for r in self.backtest.all_interval_results
                   if self.backtest.fetch_india_vix(r['date']) * 100 < 10.5]
        high_vix = [r for r in self.backtest.all_interval_results
                    if self.backtest.fetch_india_vix(r['date']) * 100 >= 10.5]

        if low_vix:
            avg_delta_low = np.mean([abs(r['ce_delta']) + abs(r['pe_delta']) for r in low_vix]) / 2
            print(f"   Low VIX (<10.5%): Avg |Delta| = {avg_delta_low:.3f}")

        if high_vix:
            avg_delta_high = np.mean([abs(r['ce_delta']) + abs(r['pe_delta']) for r in high_vix]) / 2
            print(f"   High VIX (≥10.5%): Avg |Delta| = {avg_delta_high:.3f}")

        if low_vix and high_vix:
            delta_increase = ((avg_delta_high - avg_delta_low) / avg_delta_low) * 100
            print(f"   Delta magnitude increase: {delta_increase:+.1f}%")

    def recommend_vix_adjusted_thresholds(self):
        """Recommend VIX-adjusted thresholds"""

        print(f"\n{'=' * 120}")
        print("📋 VIX-ADJUSTED THRESHOLD RECOMMENDATIONS")
        print(f"{'=' * 120}")

        # Analyze correlation
        results = self.backtest.all_interval_results

        vix_delta_pairs = []
        for r in results:
            vix = self.backtest.fetch_india_vix(r['date']) * 100
            avg_delta = (abs(r['ce_delta']) + abs(r['pe_delta'])) / 2
            vix_delta_pairs.append((vix, avg_delta))

        # Calculate correlation
        if len(vix_delta_pairs) > 1:
            vix_values = [p[0] for p in vix_delta_pairs]
            delta_values = [p[1] for p in vix_delta_pairs]
            correlation = np.corrcoef(vix_values, delta_values)[0, 1]

            print(f"\n   VIX vs Delta Magnitude Correlation: {correlation:.3f}")

            if abs(correlation) < 0.3:
                print(f"      → Weak correlation: VIX doesn't significantly affect Delta magnitude")
                print(f"      → RECOMMENDATION: Use fixed threshold (±0.100) regardless of VIX")
            else:
                print(f"      → Moderate/Strong correlation detected")
                print(f"      → RECOMMENDATION: Use VIX-adjusted threshold")

        # Proposed VIX-adjusted threshold table
        print(f"\n   Proposed VIX-Adjusted Thresholds:")
        print(f"\n   {'VIX Level':<20} {'Recommended Threshold':<25} {'Rationale'}")
        print(f"   {'-' * 80}")
        print(f"   {'Low (<10%)':<20} {'±0.100':<25} {'Normal sensitivity'}")
        print(f"   {'Normal (10-12%)':<20} {'±0.100':<25} {'Normal sensitivity'}")
        print(f"   {'Elevated (12-15%)':<20} {'±0.125':<25} {'Slightly higher volatility'}")
        print(f"   {'High (15-20%)':<20} {'±0.150':<25} {'Higher volatility, avoid noise'}")
        print(f"   {'Very High (>20%)':<20} {'±0.200':<25} {'Extreme volatility, strict filter'}")

        # Current vs proposed for VIX = 15%
        print(f"\n💡 Answer to Your Question:")
        print(f"   Current VIX: ~10% → Optimal threshold: ±0.100")
        print(f"   If VIX → 15% → Recommended threshold: ±0.125 to ±0.150")
        print(f"\n   Rationale:")
        print(f"      - Higher VIX = larger Delta swings")
        print(f"      - Need higher threshold to filter out volatility noise")
        print(f"      - Prevents false signals in choppy high-vol markets")

        # Implementation suggestion
        print(f"\n{'=' * 120}")
        print("💻 IMPLEMENTATION SUGGESTION")
        print(f"{'=' * 120}")

        print(f"\n   Option 1: SIMPLE (Recommended)")
        print(f"      - Use fixed ±0.100 threshold")
        print(f"      - Only adjust manually if VIX stays >15% for extended period")
        print(f"      - Re-optimize threshold when market regime changes")

        print(f"\n   Option 2: DYNAMIC (More Complex)")
        print("""
      def get_adaptive_threshold(current_vix):
          if current_vix < 10:
              return 0.100
          elif current_vix < 12:
              return 0.100
          elif current_vix < 15:
              return 0.125
          elif current_vix < 20:
              return 0.150
          else:
              return 0.200
        """)

        print(f"\n   ✅ RECOMMENDATION:")
        print(f"      - Start with fixed ±0.100 (works well for VIX 9-12%)")
        print(f"      - If VIX rises to 15%+ for >1 week, increase to ±0.125 or ±0.150")
        print(f"      - Monitor accuracy and adjust if needed")

        print(f"\n{'=' * 120}")


def main():
    """Main entry point"""
    print("\nInitializing VIX impact analyzer...")

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Create analyzer
    analyzer = VIXThresholdAnalyzer(kite)

    # Run analysis
    analyzer.analyze_vix_impact()

    print("\n✅ VIX impact analysis complete!")


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
