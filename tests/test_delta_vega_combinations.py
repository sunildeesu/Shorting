#!/usr/bin/env python3
"""
Delta + Vega Combination Strategies

Tests multiple strategies for combining Delta and Vega to improve predictions:
1. Vega as Confidence Filter
2. Vega as Signal Enhancer
3. Vega Divergence (CE vs PE)
4. Adaptive Delta Threshold based on Vega
5. Weighted Combination
"""

import os
import sys
from datetime import datetime, timedelta, time
from typing import Dict, List
from kiteconnect import KiteConnect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from backtest_greeks_daily_prediction import DailyGreeksBacktest


class DeltaVegaCombinationTester(DailyGreeksBacktest):
    """Extended backtest with Delta+Vega combination strategies"""

    def predict_strategy_1_confidence_filter(self, aggregated: Dict, delta_threshold: float = 0.150) -> str:
        """
        Strategy 1: Vega as Confidence Filter

        Logic:
        - Use Delta for direction (primary signal)
        - If Vega too high (>10) → Market too uncertain, predict Neutral
        - Filters out Delta signals when volatility is too high
        """
        ce_delta = aggregated['CE']['delta_diff_sum']
        pe_delta = aggregated['PE']['delta_diff_sum']
        ce_vega = aggregated['CE']['vega_diff_sum']
        pe_vega = aggregated['PE']['vega_diff_sum']

        # Check if Vega indicates high uncertainty
        if abs(ce_vega) > 10 or abs(pe_vega) > 10:
            return 'Neutral'  # Too volatile, don't trust Delta signal

        # Otherwise use Delta
        if ce_delta > delta_threshold and pe_delta > delta_threshold:
            return 'Bullish'
        elif ce_delta < -delta_threshold and pe_delta < -delta_threshold:
            return 'Bearish'
        else:
            return 'Neutral'

    def predict_strategy_2_signal_enhancer(self, aggregated: Dict, delta_threshold: float = 0.150) -> str:
        """
        Strategy 2: Vega as Signal Enhancer

        Logic:
        - Require BOTH Delta AND Vega to agree on direction
        - Rising Vega + Bullish Delta = confirmed bullish
        - Falling Vega + Bearish Delta = confirmed bearish
        """
        ce_delta = aggregated['CE']['delta_diff_sum']
        pe_delta = aggregated['PE']['delta_diff_sum']
        ce_vega = aggregated['CE']['vega_diff_sum']
        pe_vega = aggregated['PE']['vega_diff_sum']

        # Bullish: Delta bullish AND Vega rising (both CE & PE)
        if ce_delta > delta_threshold and pe_delta > delta_threshold:
            if ce_vega > 1 and pe_vega > 1:  # Vega also rising
                return 'Bullish'

        # Bearish: Delta bearish AND Vega falling (both CE & PE)
        elif ce_delta < -delta_threshold and pe_delta < -delta_threshold:
            if ce_vega < -1 and pe_vega < -1:  # Vega also falling
                return 'Bearish'

        return 'Neutral'

    def predict_strategy_3_vega_divergence(self, aggregated: Dict, delta_threshold: float = 0.150) -> str:
        """
        Strategy 3: CE/PE Vega Divergence

        Logic:
        - Look at CE Vega vs PE Vega divergence
        - CE Vega rising >> PE Vega = calls getting expensive = bullish
        - PE Vega rising >> CE Vega = puts getting expensive = bearish
        - Combine with Delta confirmation
        """
        ce_delta = aggregated['CE']['delta_diff_sum']
        pe_delta = aggregated['PE']['delta_diff_sum']
        ce_vega = aggregated['CE']['vega_diff_sum']
        pe_vega = aggregated['PE']['vega_diff_sum']

        vega_divergence = ce_vega - pe_vega

        # Bullish: Delta bullish AND CE Vega > PE Vega (calls more expensive)
        if ce_delta > delta_threshold and pe_delta > delta_threshold:
            if vega_divergence > 2:  # CE Vega significantly higher
                return 'Bullish'

        # Bearish: Delta bearish AND PE Vega > CE Vega (puts more expensive)
        elif ce_delta < -delta_threshold and pe_delta < -delta_threshold:
            if vega_divergence < -2:  # PE Vega significantly higher
                return 'Bearish'

        return 'Neutral'

    def predict_strategy_4_adaptive_threshold(self, aggregated: Dict) -> str:
        """
        Strategy 4: Adaptive Delta Threshold based on Vega

        Logic:
        - High Vega → Require stronger Delta signal (higher threshold)
        - Low Vega → Accept weaker Delta signal (lower threshold)
        - Adapts to market volatility
        """
        ce_delta = aggregated['CE']['delta_diff_sum']
        pe_delta = aggregated['PE']['delta_diff_sum']
        ce_vega = aggregated['CE']['vega_diff_sum']
        pe_vega = aggregated['PE']['vega_diff_sum']

        # Calculate average absolute Vega
        avg_vega = (abs(ce_vega) + abs(pe_vega)) / 2

        # Adaptive threshold: higher Vega = higher threshold needed
        if avg_vega > 8:
            threshold = 0.250  # Very high Vega, need very strong Delta
        elif avg_vega > 5:
            threshold = 0.175  # High Vega, need strong Delta
        elif avg_vega > 2:
            threshold = 0.125  # Moderate Vega, normal threshold
        else:
            threshold = 0.100  # Low Vega, accept weaker signals

        # Use adaptive threshold
        if ce_delta > threshold and pe_delta > threshold:
            return 'Bullish'
        elif ce_delta < -threshold and pe_delta < -threshold:
            return 'Bearish'
        else:
            return 'Neutral'

    def predict_strategy_5_weighted_score(self, aggregated: Dict, delta_threshold: float = 0.150) -> str:
        """
        Strategy 5: Weighted Combination Score

        Logic:
        - Calculate weighted score from Delta (70%) + Vega (30%)
        - Combine both signals with weights
        """
        ce_delta = aggregated['CE']['delta_diff_sum']
        pe_delta = aggregated['PE']['delta_diff_sum']
        ce_vega = aggregated['CE']['vega_diff_sum']
        pe_vega = aggregated['PE']['vega_diff_sum']

        # Delta score (70% weight)
        delta_score = (ce_delta + pe_delta) / 2

        # Vega score (30% weight) - normalized
        vega_score = (ce_vega + pe_vega) / 20  # Scale down Vega

        # Combined score
        combined_score = (delta_score * 0.7) + (vega_score * 0.3)

        # Threshold for combined score
        if combined_score > 0.100:
            return 'Bullish'
        elif combined_score < -0.100:
            return 'Bearish'
        else:
            return 'Neutral'

    def test_all_strategies(self, days: int = 22):
        """Test all combination strategies"""

        print("=" * 120)
        print("DELTA + VEGA COMBINATION STRATEGIES - COMPREHENSIVE TEST")
        print("Testing 5 different combination approaches")
        print("=" * 120)

        # Run backtest to get data
        self.run_backtest(days=days, include_today=True, threshold=0.150, verbose=False)

        results = self.all_interval_results
        total = len(results)

        print(f"\n📊 Testing on {total} intervals from {days} trading days")

        # Test each strategy
        strategies = {
            'Delta Only (±0.150)': None,  # Baseline
            'Delta Only (±0.100)': None,  # Optimal threshold
            'Strategy 1: Vega Confidence Filter': self.predict_strategy_1_confidence_filter,
            'Strategy 2: Vega Signal Enhancer': self.predict_strategy_2_signal_enhancer,
            'Strategy 3: CE/PE Vega Divergence': self.predict_strategy_3_vega_divergence,
            'Strategy 4: Adaptive Threshold': self.predict_strategy_4_adaptive_threshold,
            'Strategy 5: Weighted Combination': self.predict_strategy_5_weighted_score
        }

        strategy_results = {}

        for strategy_name, strategy_func in strategies.items():
            correct_count = 0
            predictions = {'Bullish': 0, 'Bearish': 0, 'Neutral': 0}
            accuracies_by_type = {'Bullish': [], 'Bearish': [], 'Neutral': []}

            for r in results:
                if strategy_name == 'Delta Only (±0.150)':
                    # Use existing Delta prediction with 0.150
                    predicted = r['predicted_delta']
                elif strategy_name == 'Delta Only (±0.100)':
                    # Recalculate with 0.100 threshold
                    aggregated = {
                        'CE': {'delta_diff_sum': r['ce_delta'], 'vega_diff_sum': r.get('ce_vega', 0)},
                        'PE': {'delta_diff_sum': r['pe_delta'], 'vega_diff_sum': r.get('pe_vega', 0)}
                    }
                    predicted = self.predict_daily_outcome_delta(aggregated, threshold=0.100)
                else:
                    # Use combination strategy
                    aggregated = {
                        'CE': {'delta_diff_sum': r['ce_delta'], 'vega_diff_sum': r.get('ce_vega', 0)},
                        'PE': {'delta_diff_sum': r['pe_delta'], 'vega_diff_sum': r.get('pe_vega', 0)}
                    }
                    predicted = strategy_func(aggregated)

                actual = r['actual_outcome']
                correct = (predicted == actual)

                if correct:
                    correct_count += 1

                predictions[predicted] += 1
                accuracies_by_type[actual].append(correct)

            # Calculate metrics
            overall_accuracy = (correct_count / total) * 100

            # By type accuracies
            bullish_acc = (sum(accuracies_by_type['Bullish']) / len(accuracies_by_type['Bullish']) * 100) if accuracies_by_type['Bullish'] else 0
            bearish_acc = (sum(accuracies_by_type['Bearish']) / len(accuracies_by_type['Bearish']) * 100) if accuracies_by_type['Bearish'] else 0
            neutral_acc = (sum(accuracies_by_type['Neutral']) / len(accuracies_by_type['Neutral']) * 100) if accuracies_by_type['Neutral'] else 0

            strategy_results[strategy_name] = {
                'overall_accuracy': overall_accuracy,
                'correct': correct_count,
                'total': total,
                'predictions': predictions,
                'bullish_acc': bullish_acc,
                'bearish_acc': bearish_acc,
                'neutral_acc': neutral_acc
            }

        # Print results table
        self.print_strategy_comparison(strategy_results)

        return strategy_results

    def print_strategy_comparison(self, results: Dict):
        """Print comparison table"""

        print(f"\n{'=' * 120}")
        print("STRATEGY COMPARISON TABLE")
        print(f"{'=' * 120}")

        print(f"\n{'Strategy':<40} {'Overall':<12} {'Bullish':<12} {'Bearish':<12} {'Neutral':<12} {'Predictions (B/Be/N)'}")
        print(f"{'':40} {'Acc':<12} {'Acc':<12} {'Acc':<12} {'Acc':<12} {''}")
        print("-" * 120)

        # Sort by overall accuracy
        sorted_results = sorted(results.items(), key=lambda x: x[1]['overall_accuracy'], reverse=True)

        best_overall = max(results.values(), key=lambda x: x['overall_accuracy'])
        best_neutral = max(results.values(), key=lambda x: x['neutral_acc'])

        for strategy_name, metrics in sorted_results:
            overall_marker = " 🏆" if metrics['overall_accuracy'] == best_overall['overall_accuracy'] else ""
            neutral_marker = " ⭐" if metrics['neutral_acc'] == best_neutral['neutral_acc'] else ""

            print(f"{strategy_name:<40} "
                  f"{metrics['overall_accuracy']:>6.1f}%{overall_marker:<6} "
                  f"{metrics['bullish_acc']:>6.1f}%     "
                  f"{metrics['bearish_acc']:>6.1f}%     "
                  f"{metrics['neutral_acc']:>6.1f}%{neutral_marker:<6} "
                  f"{metrics['predictions']['Bullish']:>3}/"
                  f"{metrics['predictions']['Bearish']:>3}/"
                  f"{metrics['predictions']['Neutral']:>3}")

        print("-" * 120)

        # Highlight best strategies
        print(f"\n🏆 Best Overall Accuracy: {sorted_results[0][0]} ({sorted_results[0][1]['overall_accuracy']:.1f}%)")
        print(f"⭐ Best Neutral Accuracy: {max(results.items(), key=lambda x: x[1]['neutral_acc'])[0]} "
              f"({max(results.values(), key=lambda x: x['neutral_acc'])['neutral_acc']:.1f}%)")

        # Analysis
        print(f"\n{'=' * 120}")
        print("📊 ANALYSIS")
        print(f"{'=' * 120}")

        delta_only_150 = results.get('Delta Only (±0.150)', {})
        delta_only_100 = results.get('Delta Only (±0.100)', {})

        print(f"\n   Baseline (Delta Only ±0.150): {delta_only_150.get('overall_accuracy', 0):.1f}%")
        print(f"   Optimal (Delta Only ±0.100):  {delta_only_100.get('overall_accuracy', 0):.1f}%")

        # Check if any combination beat Delta-only
        best_combo = sorted_results[0]
        best_combo_name = best_combo[0]
        best_combo_acc = best_combo[1]['overall_accuracy']

        delta_best = max(delta_only_150.get('overall_accuracy', 0), delta_only_100.get('overall_accuracy', 0))

        if best_combo_acc > delta_best and 'Delta Only' not in best_combo_name:
            improvement = best_combo_acc - delta_best
            print(f"\n   ✅ WINNER: {best_combo_name}")
            print(f"      Improvement over Delta-only: +{improvement:.1f}%")
            print(f"      Combined approach is better!")
        else:
            print(f"\n   ⚠️  No combination strategy beats Delta-only")
            print(f"      Delta-only (±0.100) remains the best approach")

        print(f"\n{'=' * 120}")


def main():
    """Main entry point"""
    print("\nInitializing Delta+Vega combination tester...")

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Create tester
    tester = DeltaVegaCombinationTester(kite)

    # Test all strategies
    results = tester.test_all_strategies(days=22)

    print("\n✅ Combination strategy testing complete!")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Testing interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Testing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
