#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test OI Integration - Verify OI analysis flows through the entire pipeline
"""

import sys
sys.path.insert(0, '.')

from oi_analyzer import get_oi_analyzer
from alert_excel_logger import AlertExcelLogger
from datetime import datetime

def test_oi_analyzer():
    """Test OI analyzer basic functionality"""
    print("=" * 80)
    print("TEST 1: OI Analyzer Basic Functionality")
    print("=" * 80)

    analyzer = get_oi_analyzer()

    # Simulate RELIANCE with long buildup
    analyzer.update_oi("RELIANCE", 1000000)
    result = analyzer.analyze_oi_change(
        symbol="RELIANCE",
        current_oi=1150000,
        price_change_pct=2.5,
        oi_day_high=1200000,
        oi_day_low=950000
    )

    if result:
        print(f"✅ Pattern: {result['pattern']}")
        print(f"✅ Signal: {result['signal']}")
        print(f"✅ OI Change: {result['oi_change_pct']:.2f}%")
        print(f"✅ Strength: {result['strength']}")
        print(f"✅ Priority: {result['priority']}")
        print(f"✅ At Day High: {result['at_day_high']}")
        print(f"✅ At Day Low: {result['at_day_low']}")
        return True
    else:
        print("❌ No OI analysis result")
        return False


def test_excel_logger_with_oi():
    """Test Excel logger with OI data"""
    print("\n" + "=" * 80)
    print("TEST 2: Excel Logger with OI Data")
    print("=" * 80)

    # Verify headers have OI columns
    headers = AlertExcelLogger.HEADERS
    oi_columns = [
        "OI Current", "OI Change %", "OI Pattern",
        "OI Signal", "OI Strength", "OI Priority"
    ]

    all_present = all(col in headers for col in oi_columns)

    if all_present:
        print(f"✅ All {len(oi_columns)} OI columns present in headers")
        print(f"   Total header columns: {len(headers)}")
        return True
    else:
        print("❌ Missing OI columns in headers")
        missing = [col for col in oi_columns if col not in headers]
        print(f"   Missing: {missing}")
        return False


def test_method_signature():
    """Test log_alert method signature includes oi_analysis"""
    print("\n" + "=" * 80)
    print("TEST 3: Method Signature Check")
    print("=" * 80)

    import inspect
    sig = inspect.signature(AlertExcelLogger.log_alert)
    params = list(sig.parameters.keys())

    if 'oi_analysis' in params:
        print(f"✅ log_alert method has oi_analysis parameter")
        print(f"   Parameters: {', '.join(params)}")
        return True
    else:
        print("❌ log_alert method missing oi_analysis parameter")
        print(f"   Current parameters: {', '.join(params)}")
        return False


def test_config_settings():
    """Test OI config settings"""
    print("\n" + "=" * 80)
    print("TEST 4: Config Settings")
    print("=" * 80)

    import config

    required_settings = [
        'ENABLE_OI_ANALYSIS',
        'OI_SIGNIFICANT_THRESHOLD',
        'OI_STRONG_THRESHOLD',
        'OI_VERY_STRONG_THRESHOLD',
        'OI_CACHE_FILE'
    ]

    all_present = all(hasattr(config, setting) for setting in required_settings)

    if all_present:
        print(f"✅ All OI config settings present")
        print(f"   ENABLE_OI_ANALYSIS: {config.ENABLE_OI_ANALYSIS}")
        print(f"   OI_SIGNIFICANT_THRESHOLD: {config.OI_SIGNIFICANT_THRESHOLD}%")
        print(f"   OI_STRONG_THRESHOLD: {config.OI_STRONG_THRESHOLD}%")
        print(f"   OI_VERY_STRONG_THRESHOLD: {config.OI_VERY_STRONG_THRESHOLD}%")
        print(f"   OI_CACHE_FILE: {config.OI_CACHE_FILE}")
        return True
    else:
        print("❌ Missing OI config settings")
        missing = [s for s in required_settings if not hasattr(config, s)]
        print(f"   Missing: {missing}")
        return False


if __name__ == "__main__":
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "OI INTEGRATION TEST SUITE" + " " * 33 + "║")
    print("╚" + "=" * 78 + "╝")
    print()

    tests = [
        ("OI Analyzer", test_oi_analyzer),
        ("Excel Logger Headers", test_excel_logger_with_oi),
        ("Method Signature", test_method_signature),
        ("Config Settings", test_config_settings)
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} FAILED with exception: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print()
    print(f"Result: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED! OI integration is working correctly.")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review the errors above.")
        sys.exit(1)
