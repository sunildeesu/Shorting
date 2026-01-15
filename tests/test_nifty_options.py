#!/usr/bin/env python3
"""
Test NIFTY Option Selling Indicator

Tests all components:
1. Configuration
2. NIFTY Option Analyzer
3. Telegram notification
4. Excel logging
5. Monitor scheduler

Usage:
    python3 test_nifty_options.py
"""

import sys
import logging
from datetime import datetime
from kiteconnect import KiteConnect

import config
from token_manager import TokenManager
from nifty_option_analyzer import NiftyOptionAnalyzer
from nifty_option_logger import NiftyOptionLogger
from telegram_notifier import TelegramNotifier
from nifty_option_monitor import NiftyOptionMonitor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_configuration():
    """Test 1: Verify configuration"""
    print("\n" + "=" * 70)
    print("TEST 1: Configuration")
    print("=" * 70)

    try:
        assert hasattr(config, 'ENABLE_NIFTY_OPTION_ANALYSIS'), "Missing ENABLE_NIFTY_OPTION_ANALYSIS"
        assert hasattr(config, 'NIFTY_OPTION_ANALYSIS_TIME'), "Missing NIFTY_OPTION_ANALYSIS_TIME"
        assert hasattr(config, 'NIFTY_50_TOKEN'), "Missing NIFTY_50_TOKEN"
        assert hasattr(config, 'INDIA_VIX_TOKEN'), "Missing INDIA_VIX_TOKEN"
        assert hasattr(config, 'THETA_WEIGHT'), "Missing THETA_WEIGHT"
        assert hasattr(config, 'GAMMA_WEIGHT'), "Missing GAMMA_WEIGHT"
        assert hasattr(config, 'VIX_WEIGHT'), "Missing VIX_WEIGHT"

        print(f"✅ ENABLE_NIFTY_OPTION_ANALYSIS: {config.ENABLE_NIFTY_OPTION_ANALYSIS}")
        print(f"✅ NIFTY_OPTION_ANALYSIS_TIME: {config.NIFTY_OPTION_ANALYSIS_TIME}")
        print(f"✅ NIFTY_50_TOKEN: {config.NIFTY_50_TOKEN}")
        print(f"✅ INDIA_VIX_TOKEN: {config.INDIA_VIX_TOKEN}")
        print(f"✅ Scoring Weights: Theta={config.THETA_WEIGHT}, Gamma={config.GAMMA_WEIGHT}, VIX={config.VIX_WEIGHT}")
        print(f"✅ Thresholds: SELL>={config.NIFTY_OPTION_SELL_THRESHOLD}, HOLD>={config.NIFTY_OPTION_HOLD_THRESHOLD}")

        print("\n✅ Configuration Test PASSED")
        return True

    except AssertionError as e:
        print(f"\n❌ Configuration Test FAILED: {e}")
        return False


def test_kite_connection():
    """Test 2: Kite Connect authentication"""
    print("\n" + "=" * 70)
    print("TEST 2: Kite Connect Authentication")
    print("=" * 70)

    try:
        # Check token validity
        manager = TokenManager()
        is_valid, message, hours_remaining = manager.is_token_valid()

        print(f"Token Status: {message}")
        print(f"Hours Remaining: {hours_remaining:.1f}")

        if not is_valid:
            print("\n❌ Kite Connect Test FAILED: Token invalid")
            print("Please run: python3 generate_kite_token.py")
            return False

        # Test connection
        kite = KiteConnect(api_key=config.KITE_API_KEY)
        kite.set_access_token(config.KITE_ACCESS_TOKEN)

        profile = kite.profile()
        print(f"✅ Connected as: {profile.get('user_name', 'Unknown')}")
        print(f"✅ User ID: {profile.get('user_id', 'Unknown')}")

        print("\n✅ Kite Connect Test PASSED")
        return kite

    except Exception as e:
        print(f"\n❌ Kite Connect Test FAILED: {e}")
        return None


def test_analyzer(kite):
    """Test 3: NIFTY Option Analyzer"""
    print("\n" + "=" * 70)
    print("TEST 3: NIFTY Option Analyzer")
    print("=" * 70)

    try:
        analyzer = NiftyOptionAnalyzer(kite)
        print("✅ Analyzer initialized")

        # Run analysis
        print("\n🔍 Running NIFTY option analysis...")
        result = analyzer.analyze_option_selling_opportunity()

        # Check for errors
        if 'error' in result:
            print(f"\n❌ Analyzer Test FAILED: {result['error']}")
            return None

        # Display results
        print("\n📊 ANALYSIS RESULTS:")
        print(f"  Signal: {result.get('signal', 'UNKNOWN')}")
        print(f"  Total Score: {result.get('total_score', 0):.1f}/100")
        print(f"  NIFTY Spot: ₹{result.get('nifty_spot', 0):,.2f}")
        print(f"  VIX: {result.get('vix', 0):.2f}")
        print(f"  Market Regime: {result.get('market_regime', 'UNKNOWN')}")
        print(f"  Best Strategy: {result.get('best_strategy', 'N/A').upper()}")

        print("\n📈 Score Breakdown:")
        breakdown = result.get('breakdown', {})
        print(f"  Theta Score: {breakdown.get('theta_score', 0):.1f}/100")
        print(f"  Gamma Score: {breakdown.get('gamma_score', 0):.1f}/100")
        print(f"  VIX Score: {breakdown.get('vix_score', 0):.1f}/100")
        print(f"  Regime Score: {breakdown.get('regime_score', 0):.1f}/100")
        print(f"  OI Score: {breakdown.get('oi_score', 0):.1f}/100")

        print(f"\n💡 Recommendation: {result.get('recommendation', '')}")

        print("\n⚠️ Risk Factors:")
        for risk in result.get('risk_factors', []):
            print(f"  • {risk}")

        # Check expiry analyses
        expiry_analyses = result.get('expiry_analyses', [])
        if expiry_analyses:
            print(f"\n📅 Expiries Analyzed: {len(expiry_analyses)}")
            for i, exp_data in enumerate(expiry_analyses, 1):
                expiry = exp_data.get('expiry_date')
                days = exp_data.get('days_to_expiry', 0)
                if expiry:
                    print(f"  {i}. {expiry.strftime('%Y-%m-%d')} ({days} days)")

        print("\n✅ Analyzer Test PASSED")
        return result

    except Exception as e:
        print(f"\n❌ Analyzer Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_excel_logger(analysis_result):
    """Test 4: Excel Logger"""
    print("\n" + "=" * 70)
    print("TEST 4: Excel Logger")
    print("=" * 70)

    try:
        logger_instance = NiftyOptionLogger()
        print("✅ Excel logger initialized")

        # Log analysis
        success = logger_instance.log_analysis(
            analysis_data=analysis_result,
            telegram_sent=False
        )

        if not success:
            print("\n❌ Excel Logger Test FAILED: Could not log analysis")
            return False

        print("✅ Analysis logged to Excel")

        # Get recent analyses
        recent = logger_instance.get_recent_analyses(days=7)
        print(f"✅ Retrieved {len(recent)} recent analyses")

        if recent:
            print("\n📊 Most Recent Analysis:")
            latest = recent[0]
            print(f"  Date: {latest.get('date')}")
            print(f"  Signal: {latest.get('signal')}")
            print(f"  Score: {latest.get('score'):.1f}")

        print("\n✅ Excel Logger Test PASSED")
        return True

    except Exception as e:
        print(f"\n❌ Excel Logger Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_telegram_notifier(analysis_result):
    """Test 5: Telegram Notifier"""
    print("\n" + "=" * 70)
    print("TEST 5: Telegram Notifier")
    print("=" * 70)

    try:
        telegram = TelegramNotifier()
        print("✅ Telegram notifier initialized")

        # Format message (don't send yet)
        message = telegram._format_nifty_option_message(analysis_result)
        print("\n📱 Formatted Telegram Message:")
        print("-" * 70)
        # Remove HTML tags for display
        display_msg = message.replace('<b>', '').replace('</b>', '')
        print(display_msg[:500] + "..." if len(display_msg) > 500 else display_msg)
        print("-" * 70)

        # Ask user if they want to send
        response = input("\n📤 Send this message to Telegram? (y/n): ")

        if response.lower() == 'y':
            success = telegram.send_nifty_option_analysis(analysis_result)
            if success:
                print("✅ Telegram message sent successfully")
            else:
                print("⚠️ Failed to send Telegram message")
        else:
            print("⏭️ Skipped sending Telegram message")

        print("\n✅ Telegram Notifier Test PASSED")
        return True

    except Exception as e:
        print(f"\n❌ Telegram Notifier Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_monitor():
    """Test 6: Monitor Scheduler"""
    print("\n" + "=" * 70)
    print("TEST 6: Monitor Scheduler")
    print("=" * 70)

    try:
        monitor = NiftyOptionMonitor()
        print("✅ Monitor initialized")

        print(f"✅ Analysis Time: {monitor.analysis_time}")
        print(f"✅ Trading Day Check: {monitor._is_trading_day()}")

        print("\n✅ Monitor Scheduler Test PASSED")
        return True

    except Exception as e:
        print(f"\n❌ Monitor Scheduler Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("NIFTY OPTION SELLING INDICATOR - COMPREHENSIVE TEST")
    print("=" * 70)
    print(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {
        'configuration': False,
        'kite_connection': False,
        'analyzer': False,
        'excel_logger': False,
        'telegram_notifier': False,
        'monitor': False
    }

    # Test 1: Configuration
    results['configuration'] = test_configuration()
    if not results['configuration']:
        print("\n⚠️ Configuration test failed. Fix configuration before proceeding.")
        return results

    # Test 2: Kite Connection
    kite = test_kite_connection()
    results['kite_connection'] = (kite is not None)
    if not results['kite_connection']:
        print("\n⚠️ Kite connection failed. Cannot proceed with remaining tests.")
        return results

    # Test 3: Analyzer
    analysis_result = test_analyzer(kite)
    results['analyzer'] = (analysis_result is not None)
    if not results['analyzer']:
        print("\n⚠️ Analyzer test failed. Cannot test logging/notification.")
        return results

    # Test 4: Excel Logger
    results['excel_logger'] = test_excel_logger(analysis_result)

    # Test 5: Telegram Notifier
    results['telegram_notifier'] = test_telegram_notifier(analysis_result)

    # Test 6: Monitor
    results['monitor'] = test_monitor()

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name.replace('_', ' ').title()}: {status}")

    all_passed = all(results.values())
    print("\n" + "=" * 70)
    if all_passed:
        print("🎉 ALL TESTS PASSED! NIFTY Option Indicator is ready to use.")
        print("\nUsage:")
        print("  • python3 nifty_option_monitor.py --test    # Run analysis now")
        print("  • python3 nifty_option_monitor.py --daemon  # Run as daemon (daily at 10:00 AM)")
    else:
        print("⚠️ SOME TESTS FAILED. Please review errors above.")
    print("=" * 70)

    return results


if __name__ == "__main__":
    try:
        results = run_all_tests()
        sys.exit(0 if all(results.values()) else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
