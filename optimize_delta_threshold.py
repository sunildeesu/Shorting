#!/usr/bin/env python3
"""
Greeks Delta Threshold Optimizer

Tests multiple thresholds to find optimal balance between:
1. Neutral prediction accuracy (primary goal)
2. Overall accuracy (secondary goal)
3. Bullish/Bearish accuracy (must maintain high accuracy)
"""

import os
import sys
from datetime import datetime
from kiteconnect import KiteConnect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from backtest_greeks_daily_prediction import DailyGreeksBacktest


def optimize_threshold():
    """Test multiple thresholds and find optimal"""

    print("=" * 100)
    print("DELTA THRESHOLD OPTIMIZER - 1 MONTH BACKTEST")
    print("Testing thresholds from 0.100 to 0.350")
    print("Goal: Maximize Neutral accuracy while maintaining overall accuracy")
    print("=" * 100)

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Test these thresholds
    thresholds_to_test = [0.100, 0.125, 0.150, 0.175, 0.200, 0.225, 0.250, 0.275, 0.300, 0.325, 0.350]

    results = []

    for threshold in thresholds_to_test:
        print(f"\n{'=' * 100}")
        print(f"Testing Threshold: ±{threshold:.3f}")
        print(f"{'=' * 100}")

        # Create fresh backtest instance
        backtest = DailyGreeksBacktest(kite)

        # Run backtest with this threshold (suppress detailed output)
        backtest.run_backtest(days=22, include_today=True, threshold=threshold, verbose=False)

        # Extract results
        total = len(backtest.all_interval_results)

        # Overall accuracy
        delta_correct = sum(1 for r in backtest.all_interval_results if r['correct_delta'])
        overall_accuracy = (delta_correct / total) * 100

        # By prediction type
        bullish_pred = [r for r in backtest.all_interval_results if r['predicted_delta'] == 'Bullish']
        bullish_accuracy = 0
        if bullish_pred:
            bullish_correct = sum(1 for r in bullish_pred if r['correct_delta'])
            bullish_accuracy = (bullish_correct / len(bullish_pred)) * 100

        bearish_pred = [r for r in backtest.all_interval_results if r['predicted_delta'] == 'Bearish']
        bearish_accuracy = 0
        if bearish_pred:
            bearish_correct = sum(1 for r in bearish_pred if r['correct_delta'])
            bearish_accuracy = (bearish_correct / len(bearish_pred)) * 100

        neutral_pred = [r for r in backtest.all_interval_results if r['predicted_delta'] == 'Neutral']
        neutral_accuracy = 0
        if neutral_pred:
            neutral_correct = sum(1 for r in neutral_pred if r['correct_delta'])
            neutral_accuracy = (neutral_correct / len(neutral_pred)) * 100

        # Store results
        results.append({
            'threshold': threshold,
            'overall_accuracy': overall_accuracy,
            'bullish_count': len(bullish_pred),
            'bullish_accuracy': bullish_accuracy,
            'bearish_count': len(bearish_pred),
            'bearish_accuracy': bearish_accuracy,
            'neutral_count': len(neutral_pred),
            'neutral_accuracy': neutral_accuracy
        })

        print(f"\n📊 Threshold ±{threshold:.3f} Results:")
        print(f"   Overall: {overall_accuracy:.1f}%")
        print(f"   Bullish: {bullish_accuracy:.1f}% ({len(bullish_pred)} predictions)")
        print(f"   Bearish: {bearish_accuracy:.1f}% ({len(bearish_pred)} predictions)")
        print(f"   Neutral: {neutral_accuracy:.1f}% ({len(neutral_pred)} predictions)")

    # Print comparison table
    print(f"\n{'=' * 100}")
    print("THRESHOLD COMPARISON TABLE")
    print(f"{'=' * 100}")

    print(f"\n{'Threshold':<12} {'Overall':<10} {'Bullish':<15} {'Bearish':<15} {'Neutral':<15} {'Score':<10}")
    print(f"{'':12} {'Acc':<10} {'Count/Acc':<15} {'Count/Acc':<15} {'Count/Acc':<15} {'':10}")
    print("-" * 100)

    best_score = 0
    best_threshold = None

    for r in results:
        # Calculate composite score (prioritize neutral accuracy + overall accuracy)
        # Score = (Neutral Acc * 0.5) + (Overall Acc * 0.3) + (Bearish Acc * 0.2)
        score = (r['neutral_accuracy'] * 0.5) + (r['overall_accuracy'] * 0.3) + (r['bearish_accuracy'] * 0.2)

        print(f"±{r['threshold']:<11.3f} {r['overall_accuracy']:>6.1f}%    "
              f"{r['bullish_count']:>3}/{r['bullish_accuracy']:>5.1f}%     "
              f"{r['bearish_count']:>3}/{r['bearish_accuracy']:>5.1f}%     "
              f"{r['neutral_count']:>3}/{r['neutral_accuracy']:>5.1f}%     "
              f"{score:>6.1f}")

        if score > best_score:
            best_score = score
            best_threshold = r['threshold']

    print("-" * 100)

    # Highlight best threshold
    best = next(r for r in results if r['threshold'] == best_threshold)

    print(f"\n{'=' * 100}")
    print("🏆 OPTIMAL THRESHOLD FOUND")
    print(f"{'=' * 100}")

    print(f"\n✅ Best Threshold: ±{best_threshold:.3f}")
    print(f"\n   Overall Accuracy: {best['overall_accuracy']:.1f}%")
    print(f"   Bullish: {best['bullish_accuracy']:.1f}% ({best['bullish_count']} predictions)")
    print(f"   Bearish: {best['bearish_accuracy']:.1f}% ({best['bearish_count']} predictions)")
    print(f"   Neutral: {best['neutral_accuracy']:.1f}% ({best['neutral_count']} predictions)")
    print(f"   Composite Score: {best_score:.1f}")

    print(f"\n📋 Recommendation:")
    print(f"   Use threshold ±{best_threshold:.3f} for production")
    print(f"   This balances neutral detection with overall accuracy")

    # Detailed analysis
    print(f"\n📊 Detailed Analysis:")

    # Find best neutral accuracy
    best_neutral = max(results, key=lambda x: x['neutral_accuracy'])
    print(f"\n   Highest Neutral Accuracy: ±{best_neutral['threshold']:.3f} ({best_neutral['neutral_accuracy']:.1f}%)")
    print(f"      But overall accuracy: {best_neutral['overall_accuracy']:.1f}%")

    # Find best overall accuracy
    best_overall = max(results, key=lambda x: x['overall_accuracy'])
    print(f"\n   Highest Overall Accuracy: ±{best_overall['threshold']:.3f} ({best_overall['overall_accuracy']:.1f}%)")
    print(f"      But neutral accuracy: {best_overall['neutral_accuracy']:.1f}%")

    # Find best bearish accuracy
    best_bearish = max(results, key=lambda x: x['bearish_accuracy'])
    print(f"\n   Highest Bearish Accuracy: ±{best_bearish['threshold']:.3f} ({best_bearish['bearish_accuracy']:.1f}%)")
    print(f"      Bearish predictions: {best_bearish['bearish_count']}")

    print(f"\n{'=' * 100}")

    return best_threshold, results


def main():
    """Main entry point"""
    best_threshold, results = optimize_threshold()
    print(f"\n✅ Threshold optimization complete!")
    print(f"\n🎯 Recommended threshold for production: ±{best_threshold:.3f}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Optimization interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Optimization failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
