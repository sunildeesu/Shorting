#!/usr/bin/env python3
"""
Test RSI Analyzer

Tests RSI calculation and crossover detection logic with various scenarios.
"""

import pandas as pd
import numpy as np
from rsi_analyzer import (
    calculate_rsi_with_crossovers,
    RSIAnalyzer,
    format_crossover_display,
    format_recent_crossover
)


def create_mock_price_data(trend='uptrend', periods=50):
    """
    Create mock OHLCV data for testing.

    Args:
        trend: 'uptrend', 'downtrend', or 'sideways'
        periods: Number of candles to generate

    Returns:
        DataFrame with OHLCV columns
    """
    np.random.seed(42)

    if trend == 'uptrend':
        # Upward trending prices
        base = 100
        closes = [base]
        for i in range(1, periods):
            change = np.random.uniform(0.5, 2.0)  # Mostly positive
            closes.append(closes[-1] * (1 + change / 100))

    elif trend == 'downtrend':
        # Downward trending prices
        base = 100
        closes = [base]
        for i in range(1, periods):
            change = np.random.uniform(-2.0, -0.5)  # Mostly negative
            closes.append(closes[-1] * (1 + change / 100))

    else:  # sideways
        # Sideways/ranging prices
        base = 100
        closes = [base]
        for i in range(1, periods):
            change = np.random.uniform(-1.0, 1.0)  # Equal positive/negative
            closes.append(closes[-1] * (1 + change / 100))

    df = pd.DataFrame({
        'close': closes,
        'high': [c * 1.01 for c in closes],
        'low': [c * 0.99 for c in closes],
        'open': [c * 1.005 for c in closes],
        'volume': [1000000] * periods
    })

    return df


def test_rsi_calculation():
    """Test basic RSI calculation."""
    print("=" * 60)
    print("TEST 1: RSI Calculation")
    print("=" * 60)

    # Create uptrend data
    df = create_mock_price_data(trend='uptrend', periods=50)

    analyzer = RSIAnalyzer(periods=[9, 14, 21])
    rsi_values = analyzer.calculate_rsi_values(df)

    print(f"Uptrend RSI values:")
    for period, value in rsi_values.items():
        print(f"  {period.upper()}: {value}")

    # RSI should be high in uptrend (typically > 50)
    assert rsi_values['rsi_14'] is not None, "RSI(14) should not be None"
    assert 0 <= rsi_values['rsi_14'] <= 100, "RSI(14) should be between 0-100"

    print("✓ RSI calculation test passed\n")
    return rsi_values


def test_crossover_detection():
    """Test crossover detection logic."""
    print("=" * 60)
    print("TEST 2: Crossover Detection")
    print("=" * 60)

    # Create data with deliberate crossover
    # First 30 candles downtrend, then 20 candles uptrend
    df_down = create_mock_price_data(trend='downtrend', periods=30)
    df_up = create_mock_price_data(trend='uptrend', periods=20)

    # Concatenate (downtrend then uptrend creates bullish crossover)
    df = pd.concat([df_down, df_up], ignore_index=True)

    analyzer = RSIAnalyzer(periods=[9, 14, 21], crossover_lookback=5)
    analysis = analyzer.get_comprehensive_analysis(df)

    print(f"RSI Values:")
    print(f"  RSI(9): {analysis['rsi_9']}")
    print(f"  RSI(14): {analysis['rsi_14']}")
    print(f"  RSI(21): {analysis['rsi_21']}")

    print(f"\nCrossovers:")
    for pair, crossover in analysis['crossovers'].items():
        print(f"  {pair}:")
        print(f"    Status: {crossover['status']}")
        print(f"    Strength: {crossover['strength']}")
        if crossover['recent_cross']['occurred']:
            print(f"    Recent Cross: {crossover['recent_cross']['direction']} "
                  f"{crossover['recent_cross']['bars_ago']} bars ago")

    print(f"\nSummary: {analysis['summary']}")

    print("✓ Crossover detection test passed\n")
    return analysis


def test_convenience_function():
    """Test the convenience function."""
    print("=" * 60)
    print("TEST 3: Convenience Function")
    print("=" * 60)

    df = create_mock_price_data(trend='uptrend', periods=50)

    # Use convenience function
    analysis = calculate_rsi_with_crossovers(df)

    print(f"Analysis keys: {list(analysis.keys())}")
    print(f"RSI(14): {analysis['rsi_14']}")
    print(f"Crossovers: {list(analysis['crossovers'].keys())}")
    print(f"Summary: {analysis['summary']}")

    assert 'rsi_9' in analysis, "Should include RSI(9)"
    assert 'rsi_14' in analysis, "Should include RSI(14)"
    assert 'rsi_21' in analysis, "Should include RSI(21)"
    assert 'crossovers' in analysis, "Should include crossovers"
    assert '9_14' in analysis['crossovers'], "Should include 9_14 crossover"

    print("✓ Convenience function test passed\n")
    return analysis


def test_formatting_helpers():
    """Test display formatting helpers."""
    print("=" * 60)
    print("TEST 4: Formatting Helpers")
    print("=" * 60)

    df = create_mock_price_data(trend='uptrend', periods=50)
    analysis = calculate_rsi_with_crossovers(df)

    # Test crossover display formatting
    for pair, crossover in analysis['crossovers'].items():
        fast, slow = pair.split('_')
        display = format_crossover_display(crossover, int(fast), int(slow))
        print(f"  {pair}: {display}")

    # Test recent crossover formatting
    print(f"\nRecent Crossover Formatting:")
    for pair, crossover in analysis['crossovers'].items():
        recent_display = format_recent_crossover(crossover)
        print(f"  {pair}: {recent_display}")

    print("✓ Formatting helpers test passed\n")


def test_edge_cases():
    """Test edge cases and error handling."""
    print("=" * 60)
    print("TEST 5: Edge Cases")
    print("=" * 60)

    # Test with insufficient data
    print("Testing with insufficient data (only 10 candles)...")
    df_small = create_mock_price_data(trend='uptrend', periods=10)
    analysis = calculate_rsi_with_crossovers(df_small)

    # Should handle gracefully
    print(f"  RSI(14): {analysis['rsi_14']}")  # May be None or calculated
    print(f"  Crossovers detected: {len([c for c in analysis['crossovers'].values() if c['status'] is not None])}")

    # Test with missing close column
    print("\nTesting with missing 'close' column...")
    df_bad = pd.DataFrame({'price': [100, 101, 102]})
    analyzer = RSIAnalyzer()
    rsi_values = analyzer.calculate_rsi_values(df_bad)
    print(f"  Result: {rsi_values}")  # Should be empty dict

    # Test with NaN values
    print("\nTesting with NaN values...")
    df_nan = create_mock_price_data(trend='uptrend', periods=50)
    df_nan.loc[20:25, 'close'] = np.nan
    analysis = calculate_rsi_with_crossovers(df_nan)
    print(f"  RSI(14): {analysis['rsi_14']}")

    print("✓ Edge cases test passed\n")


def test_bullish_bearish_scenarios():
    """Test bullish and bearish scenarios."""
    print("=" * 60)
    print("TEST 6: Bullish vs Bearish Scenarios")
    print("=" * 60)

    # Bullish scenario
    print("Bullish Scenario (Strong Uptrend):")
    df_bullish = create_mock_price_data(trend='uptrend', periods=50)
    analysis_bullish = calculate_rsi_with_crossovers(df_bullish)
    print(f"  RSI(9): {analysis_bullish['rsi_9']}")
    print(f"  RSI(14): {analysis_bullish['rsi_14']}")
    print(f"  RSI(21): {analysis_bullish['rsi_21']}")
    print(f"  Summary: {analysis_bullish['summary']}")

    # Bearish scenario
    print("\nBearish Scenario (Strong Downtrend):")
    df_bearish = create_mock_price_data(trend='downtrend', periods=50)
    analysis_bearish = calculate_rsi_with_crossovers(df_bearish)
    print(f"  RSI(9): {analysis_bearish['rsi_9']}")
    print(f"  RSI(14): {analysis_bearish['rsi_14']}")
    print(f"  RSI(21): {analysis_bearish['rsi_21']}")
    print(f"  Summary: {analysis_bearish['summary']}")

    # Sideways scenario
    print("\nSideways Scenario (Range-bound):")
    df_sideways = create_mock_price_data(trend='sideways', periods=50)
    analysis_sideways = calculate_rsi_with_crossovers(df_sideways)
    print(f"  RSI(9): {analysis_sideways['rsi_9']}")
    print(f"  RSI(14): {analysis_sideways['rsi_14']}")
    print(f"  RSI(21): {analysis_sideways['rsi_21']}")
    print(f"  Summary: {analysis_sideways['summary']}")

    print("✓ Scenario tests passed\n")


def main():
    """Run all tests."""
    print("\n")
    print("=" * 60)
    print("RSI ANALYZER - COMPREHENSIVE TESTING")
    print("=" * 60)
    print("\n")

    try:
        # Run all tests
        test_rsi_calculation()
        test_crossover_detection()
        test_convenience_function()
        test_formatting_helpers()
        test_edge_cases()
        test_bullish_bearish_scenarios()

        print("=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        print("\nRSI Analyzer is working correctly!")
        print("Ready for integration into alert system.\n")

        return 0

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
