#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test Suite for Short Screening Functionality

Tests the short selling screening logic including:
- Short entry signal detection
- Stop loss/target calculations (inverted)
- Price criteria (near highs)
- Fundamental decline detection

Author: Sunil Kumar Durganaik
"""

import sys
import pandas as pd
import numpy as np
from trend_analyzer import TrendAnalyzer

def test_short_entry_signal_detection():
    """Test that short entry signals are detected correctly"""
    print("\n" + "="*80)
    print("TEST 1: SHORT ENTRY SIGNAL DETECTION")
    print("="*80)

    # Create downtrend data
    dates = pd.date_range(end='2024-12-01', periods=200, freq='D')

    # Simulated downtrend: Starts at 500, declines to 400
    np.random.seed(42)
    # Use negative drift to create consistent downtrend
    close_prices = 500 + np.cumsum(np.random.randn(200) * 1.5 - 0.5)  # -0.5 drift = downtrend

    df = pd.DataFrame({
        'date': dates,
        'open': close_prices + np.random.rand(200) * 2,
        'high': close_prices + np.random.rand(200) * 3,
        'low': close_prices - np.random.rand(200) * 3,
        'close': close_prices,
        'volume': np.random.randint(1000000, 5000000, 200)
    })

    analyzer = TrendAnalyzer(df, symbol="TEST_SHORT")
    short_analysis = analyzer.get_short_comprehensive_analysis()

    print(f"\nTrend Status: {short_analysis['trend_status']}")
    print(f"Trend Score: {short_analysis['trend_score']}/10")
    print(f"Entry Signal: {short_analysis['entry_signal']}")
    print(f"Entry Type: {short_analysis['entry_type']}")
    print(f"Entry Score: {short_analysis['entry_score']}")

    # Validate
    passed = True
    if short_analysis['trend_score'] > 0:
        print("\n❌ FAILED: Downtrend should have negative score")
        passed = False
    if short_analysis['entry_signal'] not in ['SHORT', 'WAIT', 'AVOID']:
        print(f"\n❌ FAILED: Invalid entry signal: {short_analysis['entry_signal']}")
        passed = False

    if passed:
        print("\n✅ PASSED: Short entry signal detection working correctly")

    return passed


def test_short_stop_loss_calculation():
    """Test that stop loss is ABOVE entry for shorts"""
    print("\n" + "="*80)
    print("TEST 2: SHORT STOP LOSS CALCULATION (MUST BE ABOVE ENTRY)")
    print("="*80)

    # Create simple downtrend data
    dates = pd.date_range(end='2024-12-01', periods=100, freq='D')
    np.random.seed(43)
    # Negative drift = downtrend
    close_prices = 500 + np.cumsum(np.random.randn(100) * 1.5 - 0.5)

    df = pd.DataFrame({
        'date': dates,
        'open': close_prices,
        'high': close_prices + 5,
        'low': close_prices - 5,
        'close': close_prices,
        'volume': np.random.randint(1000000, 3000000, 100)
    })

    analyzer = TrendAnalyzer(df, symbol="TEST_STOP")
    short_analysis = analyzer.get_short_comprehensive_analysis()

    entry = short_analysis['entry_price']
    stop_loss = short_analysis['stop_loss']
    target_1 = short_analysis['target_1']
    target_2 = short_analysis['target_2']
    entry_signal = short_analysis['entry_signal']

    print(f"\nEntry Signal: {entry_signal}")
    print(f"Entry Price: ₹{entry:.2f}")
    print(f"Stop Loss:   ₹{stop_loss:.2f} ({short_analysis['stop_loss_pct']:.2f}%)")
    print(f"Target 1:    ₹{target_1:.2f} ({short_analysis['target_1_pct']:.2f}%)")
    print(f"Target 2:    ₹{target_2:.2f} ({short_analysis['target_2_pct']:.2f}%)")

    # Validate - if no entry signal, use current price for validation
    if entry == 0:
        entry = short_analysis['current_price']
        print(f"\nNo entry signal, using current price (₹{entry:.2f}) for validation")

    passed = True
    if stop_loss <= entry:
        print(f"\n❌ FAILED: Stop loss (₹{stop_loss:.2f}) must be ABOVE entry (₹{entry:.2f}) for shorts!")
        passed = False
    if target_1 >= entry:
        print(f"\n❌ FAILED: Target 1 (₹{target_1:.2f}) must be BELOW entry (₹{entry:.2f}) for shorts!")
        passed = False
    if target_2 >= entry:
        print(f"\n❌ FAILED: Target 2 (₹{target_2:.2f}) must be BELOW entry (₹{entry:.2f}) for shorts!")
        passed = False
    if target_2 >= target_1:
        print(f"\n❌ FAILED: Target 2 (₹{target_2:.2f}) must be BELOW Target 1 (₹{target_1:.2f})!")
        passed = False

    if passed:
        print("\n✅ PASSED: Stop loss/targets correctly positioned for SHORT positions")

    return passed


def test_short_position_sizing():
    """Test that position sizing works for shorts with stop ABOVE entry"""
    print("\n" + "="*80)
    print("TEST 3: SHORT POSITION SIZING")
    print("="*80)

    # Create downtrend data
    dates = pd.date_range(end='2024-12-01', periods=100, freq='D')
    np.random.seed(44)
    # Negative drift = downtrend
    close_prices = 500 + np.cumsum(np.random.randn(100) * 1.5 - 0.5)

    df = pd.DataFrame({
        'date': dates,
        'open': close_prices,
        'high': close_prices + 5,
        'low': close_prices - 5,
        'close': close_prices,
        'volume': np.random.randint(1000000, 3000000, 100)
    })

    analyzer = TrendAnalyzer(df, symbol="TEST_POS")
    short_analysis = analyzer.get_short_comprehensive_analysis(account_size=1000000, risk_pct=2.0)

    position_size = short_analysis['position_size']
    position_value = short_analysis['position_value']
    entry_signal = short_analysis['entry_signal']

    print(f"\nAccount Size: ₹10,00,000")
    print(f"Risk: 2%")
    print(f"Entry Signal: {entry_signal}")
    print(f"Position Size: {position_size} shares")
    print(f"Position Value: ₹{position_value:,.0f}")
    print(f"Max Allowed: ₹50,000 (5% for shorts)")

    # Validate - position size can be 0 if no entry signal
    passed = True
    if entry_signal == 'SHORT':
        if position_size <= 0:
            print("\n❌ FAILED: Position size must be positive when SHORT signal exists")
            passed = False
    elif position_size == 0:
        print("\n✓ Position size is 0 (no SHORT signal) - this is expected")
        passed = True  # This is correct behavior

    if position_value > 50000:  # 5% max for shorts
        print(f"\n❌ FAILED: Position value (₹{position_value:,.0f}) exceeds 5% limit (₹50,000)")
        passed = False

    if passed:
        print("\n✅ PASSED: Position sizing working correctly for shorts")

    return passed


def test_check_short_fundamental_criteria():
    """Test fundamental decline detection"""
    print("\n" + "="*80)
    print("TEST 4: FUNDAMENTAL DECLINE DETECTION")
    print("="*80)

    from stock_value_screener import StockValueScreener

    # Mock growth metrics with decline
    growth_metrics = {
        'yoy_revenue_avg': -10.5,
        'yoy_pat_avg': -8.3,
        'qoq_revenue_avg': -5.2,
        'qoq_pat_avg': -6.1,
        'yoy_rev_detail': [-12, -9, -10],  # 3 negative quarters
        'yoy_pat_detail': [-8, -7, -9]     # 3 negative quarters
    }

    screener = StockValueScreener()
    has_decline, decline_type = screener.check_short_fundamental_criteria(growth_metrics)

    print(f"\nYoY Revenue Avg: {growth_metrics['yoy_revenue_avg']:.1f}%")
    print(f"YoY PAT Avg: {growth_metrics['yoy_pat_avg']:.1f}%")
    print(f"Recent YoY quarters: {growth_metrics['yoy_rev_detail']}")
    print(f"\nHas Decline: {has_decline}")
    print(f"Decline Type: {decline_type}")

    # Validate
    passed = True
    if not has_decline:
        print("\n❌ FAILED: Should detect decline when all quarters are negative")
        passed = False
    if decline_type != "YoY Decline":
        print(f"\n❌ FAILED: Should detect 'YoY Decline', got '{decline_type}'")
        passed = False

    if passed:
        print("\n✅ PASSED: Fundamental decline detection working correctly")

    return passed


def main():
    """Run all tests"""
    print("="*80)
    print("SHORT SCREENING TEST SUITE")
    print("="*80)

    tests = [
        test_short_entry_signal_detection,
        test_short_stop_loss_calculation,
        test_short_position_sizing,
        test_check_short_fundamental_criteria
    ]

    results = []
    for test in tests:
        try:
            passed = test()
            results.append(passed)
        except Exception as e:
            print(f"\n❌ TEST FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    passed_count = sum(results)
    total_count = len(results)

    for i, (test, passed) in enumerate(zip(tests, results), 1):
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"Test {i}: {test.__name__:<45} {status}")

    print("="*80)
    print(f"Results: {passed_count}/{total_count} tests passed")
    print("="*80)

    if all(results):
        print("\n✅ ALL TESTS PASSED - Short screening logic working correctly!")
        return 0
    else:
        print(f"\n❌ {total_count - passed_count} TEST(S) FAILED - Fix issues before using in production")
        return 1


if __name__ == "__main__":
    sys.exit(main())
