#!/usr/bin/env python3
"""
Comprehensive test for NIFTY Option Signal Accuracy

Tests:
1. Option premium accuracy from API
2. Greeks calculations
3. Scoring calculations
4. Strike selection
5. Symbol construction
6. Telegram message data accuracy

Author: Sunil Kumar Durganaik
"""

import sys
from datetime import datetime
from kiteconnect import KiteConnect
import config
from token_manager import TokenManager
from nifty_option_analyzer import NiftyOptionAnalyzer
from telegram_notifier import TelegramNotifier
import json

class SignalAccuracyTest:
    """Test suite for signal accuracy"""

    def __init__(self):
        self.token_manager = TokenManager()
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
        self.analyzer = NiftyOptionAnalyzer(self.kite)
        self.errors = []
        self.warnings = []
        self.passed = []

    def log_error(self, test_name, message):
        """Log test error"""
        self.errors.append(f"❌ {test_name}: {message}")
        print(f"❌ {test_name}: {message}")

    def log_warning(self, test_name, message):
        """Log test warning"""
        self.warnings.append(f"⚠️  {test_name}: {message}")
        print(f"⚠️  {test_name}: {message}")

    def log_pass(self, test_name, message=""):
        """Log test pass"""
        msg = f"✅ {test_name}" + (f": {message}" if message else "")
        self.passed.append(msg)
        print(msg)

    def test_nifty_spot_price(self):
        """Test 1: Verify NIFTY spot price"""
        print("\n" + "="*70)
        print("TEST 1: NIFTY Spot Price Accuracy")
        print("="*70)

        try:
            # Get from analyzer
            analysis = self.analyzer.analyze_option_selling_opportunity()
            analyzer_spot = analysis.get('nifty_spot', 0)

            # Get directly from API
            quote = self.kite.quote(['NSE:NIFTY 50'])
            api_spot = quote['NSE:NIFTY 50']['last_price']

            print(f"Analyzer NIFTY Spot: ₹{analyzer_spot:,.2f}")
            print(f"Direct API NIFTY Spot: ₹{api_spot:,.2f}")

            # They should match exactly
            if analyzer_spot == api_spot:
                self.log_pass("NIFTY Spot Price", f"Matches exactly: ₹{api_spot:,.2f}")
            else:
                diff = abs(analyzer_spot - api_spot)
                if diff < 1:
                    self.log_warning("NIFTY Spot Price", f"Minor difference: ₹{diff:.2f}")
                else:
                    self.log_error("NIFTY Spot Price", f"Mismatch: Analyzer={analyzer_spot}, API={api_spot}")

            return analyzer_spot, analysis

        except Exception as e:
            self.log_error("NIFTY Spot Price", str(e))
            return None, None

    def test_india_vix(self):
        """Test 2: Verify India VIX"""
        print("\n" + "="*70)
        print("TEST 2: India VIX Accuracy")
        print("="*70)

        try:
            # Get from analyzer
            analysis = self.analyzer.analyze_option_selling_opportunity()
            analyzer_vix = analysis.get('vix', 0)

            # Get directly from API
            quote = self.kite.quote(['NSE:INDIA VIX'])
            api_vix = quote['NSE:INDIA VIX']['last_price']

            print(f"Analyzer VIX: {analyzer_vix:.2f}")
            print(f"Direct API VIX: {api_vix:.2f}")

            if analyzer_vix == api_vix:
                self.log_pass("India VIX", f"Matches exactly: {api_vix:.2f}")
            else:
                diff = abs(analyzer_vix - api_vix)
                if diff < 0.1:
                    self.log_warning("India VIX", f"Minor difference: {diff:.2f}")
                else:
                    self.log_error("India VIX", f"Mismatch: Analyzer={analyzer_vix}, API={api_vix}")

        except Exception as e:
            self.log_error("India VIX", str(e))

    def test_atm_strike_calculation(self, nifty_spot):
        """Test 3: Verify ATM strike calculation"""
        print("\n" + "="*70)
        print("TEST 3: ATM Strike Calculation")
        print("="*70)

        if not nifty_spot:
            self.log_error("ATM Strike", "NIFTY spot not available")
            return None

        # Calculate expected ATM
        expected_atm = round(nifty_spot / 50) * 50

        print(f"NIFTY Spot: ₹{nifty_spot:,.2f}")
        print(f"Expected ATM Strike: {expected_atm}")

        # Get from analysis
        analysis = self.analyzer.analyze_option_selling_opportunity()
        expiry_analyses = analysis.get('expiry_analyses', [])

        if expiry_analyses:
            first_expiry = expiry_analyses[0]
            straddle = first_expiry.get('straddle', {})
            strikes = straddle.get('strikes', {})
            actual_atm = strikes.get('call', 0)

            print(f"Analyzer ATM Strike: {actual_atm}")

            if actual_atm == expected_atm:
                self.log_pass("ATM Strike Calculation", f"Correct: {actual_atm}")
                return actual_atm
            else:
                self.log_error("ATM Strike Calculation", f"Expected {expected_atm}, got {actual_atm}")
                return actual_atm
        else:
            self.log_error("ATM Strike Calculation", "No expiry analyses found")
            return None

    def test_option_symbol_construction(self, atm_strike):
        """Test 4: Verify option symbol construction"""
        print("\n" + "="*70)
        print("TEST 4: Option Symbol Construction")
        print("="*70)

        if not atm_strike:
            self.log_error("Option Symbol", "ATM strike not available")
            return

        try:
            # Get expiries from analyzer
            analysis = self.analyzer.analyze_option_selling_opportunity()
            expiry_analyses = analysis.get('expiry_analyses', [])

            if not expiry_analyses:
                self.log_error("Option Symbol", "No expiries found")
                return

            first_expiry = expiry_analyses[0]
            expiry_date = first_expiry.get('expiry_date')

            if isinstance(expiry_date, str):
                expiry_dt = datetime.fromisoformat(expiry_date)
            else:
                expiry_dt = expiry_date

            # Construct expected symbol
            year_short = str(expiry_dt.year)[-2:]
            month = str(expiry_dt.month)
            day = str(expiry_dt.day).zfill(2)
            expected_symbol = f"NIFTY{year_short}{month}{day}{atm_strike}CE"

            print(f"Expiry Date: {expiry_dt.date()}")
            print(f"Expected Symbol: NFO:{expected_symbol}")

            # Try to fetch this symbol
            try:
                quote = self.kite.quote([f"NFO:{expected_symbol}"])
                if f"NFO:{expected_symbol}" in quote:
                    premium = quote[f"NFO:{expected_symbol}"]["last_price"]
                    self.log_pass("Option Symbol Construction", f"{expected_symbol} exists, premium: ₹{premium}")
                else:
                    self.log_error("Option Symbol Construction", f"Symbol {expected_symbol} not found in quote")
            except Exception as e:
                self.log_error("Option Symbol Construction", f"Failed to fetch {expected_symbol}: {str(e)}")

        except Exception as e:
            self.log_error("Option Symbol Construction", str(e))

    def test_option_premiums(self, atm_strike):
        """Test 5: Verify option premiums match API"""
        print("\n" + "="*70)
        print("TEST 5: Option Premium Accuracy")
        print("="*70)

        if not atm_strike:
            self.log_error("Option Premiums", "ATM strike not available")
            return

        try:
            # Get from analyzer
            analysis = self.analyzer.analyze_option_selling_opportunity()
            expiry_analyses = analysis.get('expiry_analyses', [])

            if not expiry_analyses:
                self.log_error("Option Premiums", "No expiry analyses")
                return

            first_expiry = expiry_analyses[0]
            straddle = first_expiry.get('straddle', {})

            analyzer_call_premium = straddle.get('call_premium', 0)
            analyzer_put_premium = straddle.get('put_premium', 0)
            analyzer_total = straddle.get('total_premium', 0)

            # Get directly from API
            expiry_date = first_expiry.get('expiry_date')
            if isinstance(expiry_date, str):
                expiry_dt = datetime.fromisoformat(expiry_date)
            else:
                expiry_dt = expiry_date

            year_short = str(expiry_dt.year)[-2:]
            month = str(expiry_dt.month)
            day = str(expiry_dt.day).zfill(2)

            call_symbol = f"NFO:NIFTY{year_short}{month}{day}{atm_strike}CE"
            put_symbol = f"NFO:NIFTY{year_short}{month}{day}{atm_strike}PE"

            quotes = self.kite.quote([call_symbol, put_symbol])

            api_call_premium = quotes[call_symbol]['last_price']
            api_put_premium = quotes[put_symbol]['last_price']
            api_total = api_call_premium + api_put_premium

            print(f"\nCall Option ({atm_strike} CE):")
            print(f"  Analyzer: ₹{analyzer_call_premium:.2f}")
            print(f"  Direct API: ₹{api_call_premium:.2f}")

            print(f"\nPut Option ({atm_strike} PE):")
            print(f"  Analyzer: ₹{analyzer_put_premium:.2f}")
            print(f"  Direct API: ₹{api_put_premium:.2f}")

            print(f"\nTotal Straddle Premium:")
            print(f"  Analyzer: ₹{analyzer_total:.2f}")
            print(f"  Direct API: ₹{api_total:.2f}")

            # Check if they match (allow small difference due to timing)
            call_diff = abs(analyzer_call_premium - api_call_premium)
            put_diff = abs(analyzer_put_premium - api_put_premium)
            total_diff = abs(analyzer_total - api_total)

            if call_diff < 1 and put_diff < 1 and total_diff < 2:
                self.log_pass("Option Premiums", f"All premiums accurate (diff < ₹2)")
            else:
                if call_diff >= 1:
                    self.log_error("Option Premiums", f"Call premium diff: ₹{call_diff:.2f}")
                if put_diff >= 1:
                    self.log_error("Option Premiums", f"Put premium diff: ₹{put_diff:.2f}")
                if total_diff >= 2:
                    self.log_error("Option Premiums", f"Total premium diff: ₹{total_diff:.2f}")

        except Exception as e:
            self.log_error("Option Premiums", str(e))

    def test_score_calculation(self):
        """Test 6: Verify score calculation"""
        print("\n" + "="*70)
        print("TEST 6: Score Calculation Accuracy")
        print("="*70)

        try:
            analysis = self.analyzer.analyze_option_selling_opportunity()

            total_score = analysis.get('total_score', 0)
            breakdown = analysis.get('breakdown', {})

            theta_score = breakdown.get('theta_score', 0)
            gamma_score = breakdown.get('gamma_score', 0)
            vix_score = breakdown.get('vix_score', 0)
            regime_score = breakdown.get('regime_score', 0)
            oi_score = breakdown.get('oi_score', 0)

            # Calculate expected total (weights from analyzer)
            expected_total = (
                theta_score * 0.25 +
                gamma_score * 0.25 +
                vix_score * 0.30 +
                regime_score * 0.10 +
                oi_score * 0.10
            )

            print(f"\nScore Breakdown:")
            print(f"  Theta Score: {theta_score:.1f}/100 (weight 25%)")
            print(f"  Gamma Score: {gamma_score:.1f}/100 (weight 25%)")
            print(f"  VIX Score: {vix_score:.1f}/100 (weight 30%)")
            print(f"  Regime Score: {regime_score:.1f}/100 (weight 10%)")
            print(f"  OI Score: {oi_score:.1f}/100 (weight 10%)")
            print(f"\nCalculated Total: {expected_total:.1f}/100")
            print(f"Analyzer Total: {total_score:.1f}/100")

            diff = abs(expected_total - total_score)

            if diff < 0.1:
                self.log_pass("Score Calculation", f"Weighted average correct: {total_score:.1f}/100")
            else:
                self.log_error("Score Calculation", f"Mismatch: Expected {expected_total:.1f}, got {total_score:.1f}")

            # Verify signal mapping
            signal = analysis.get('signal', '')
            expected_signal = 'SELL' if total_score >= 70 else ('HOLD' if total_score >= 40 else 'AVOID')

            print(f"\nSignal: {signal}")
            print(f"Expected Signal (score {total_score:.1f}): {expected_signal}")

            if signal == expected_signal:
                self.log_pass("Signal Mapping", f"{signal} is correct for score {total_score:.1f}")
            else:
                self.log_error("Signal Mapping", f"Expected {expected_signal}, got {signal}")

        except Exception as e:
            self.log_error("Score Calculation", str(e))

    def test_greeks_calculation(self):
        """Test 7: Verify Greeks calculations"""
        print("\n" + "="*70)
        print("TEST 7: Greeks Calculation")
        print("="*70)

        try:
            analysis = self.analyzer.analyze_option_selling_opportunity()
            expiry_analyses = analysis.get('expiry_analyses', [])

            if not expiry_analyses:
                self.log_error("Greeks Calculation", "No expiry analyses")
                return

            first_expiry = expiry_analyses[0]
            straddle = first_expiry.get('straddle', {})
            greeks = straddle.get('greeks', {})

            theta = greeks.get('theta', 0)
            gamma = greeks.get('gamma', 0)
            delta = greeks.get('delta', 0)

            print(f"\nStraddle Greeks (Combined):")
            print(f"  Delta: {delta:.4f}")
            print(f"  Theta: {theta:.2f} (₹ per day)")
            print(f"  Gamma: {gamma:.4f}")

            # Sanity checks
            issues = []

            # Theta should be negative for short positions
            if theta >= 0:
                issues.append("Theta should be negative for time decay")

            # Gamma should be positive
            if gamma <= 0:
                issues.append("Gamma should be positive")

            # Delta should be close to 0 for ATM straddle
            if abs(delta) > 0.2:
                issues.append(f"Delta {delta:.4f} seems too high for ATM straddle")

            # Theta magnitude check (typical range for weekly: -20 to -80)
            if abs(theta) < 10:
                issues.append(f"Theta {theta:.2f} seems too low")
            elif abs(theta) > 100:
                issues.append(f"Theta {theta:.2f} seems too high")

            if issues:
                for issue in issues:
                    self.log_warning("Greeks Sanity Check", issue)
            else:
                self.log_pass("Greeks Sanity Check", "All Greeks in expected ranges")

        except Exception as e:
            self.log_error("Greeks Calculation", str(e))

    def test_telegram_message_accuracy(self):
        """Test 8: Verify Telegram message data matches analysis"""
        print("\n" + "="*70)
        print("TEST 8: Telegram Message Data Accuracy")
        print("="*70)

        try:
            # Get analysis
            analysis = self.analyzer.analyze_option_selling_opportunity()

            # Generate Telegram message (but don't send)
            telegram = TelegramNotifier()
            message = telegram._format_nifty_option_message(analysis)

            # Extract data from analysis
            signal = analysis.get('signal', '')
            total_score = analysis.get('total_score', 0)
            nifty_spot = analysis.get('nifty_spot', 0)
            vix = analysis.get('vix', 0)

            expiry_analyses = analysis.get('expiry_analyses', [])
            if expiry_analyses:
                first_expiry = expiry_analyses[0]
                straddle = first_expiry.get('straddle', {})
                strikes = straddle.get('strikes', {})
                call_premium = straddle.get('call_premium', 0)
                put_premium = straddle.get('put_premium', 0)
                total_premium = straddle.get('total_premium', 0)

            print(f"\nVerifying data in Telegram message:")

            # Check if key data is in message
            checks = {
                f"SIGNAL: {signal}": signal in message,
                f"Score: {total_score:.1f}": f"{total_score:.1f}" in message,
                f"NIFTY Spot: ₹{nifty_spot:,.2f}": str(int(nifty_spot)) in message,
                f"Strike: {strikes.get('call')}": str(strikes.get('call', 0)) in message,
                f"Total Premium: ₹{total_premium:.0f}": str(int(total_premium)) in message,
            }

            all_passed = True
            for check, result in checks.items():
                if result:
                    print(f"  ✅ {check}")
                else:
                    print(f"  ❌ {check} - NOT FOUND IN MESSAGE")
                    all_passed = False

            if all_passed:
                self.log_pass("Telegram Message", "All key data present and accurate")
            else:
                self.log_error("Telegram Message", "Some data missing or incorrect")

            print(f"\nMessage length: {len(message)} characters")

        except Exception as e:
            self.log_error("Telegram Message", str(e))

    def test_expiry_dates(self):
        """Test 9: Verify expiry date accuracy"""
        print("\n" + "="*70)
        print("TEST 9: Expiry Date Accuracy")
        print("="*70)

        try:
            analysis = self.analyzer.analyze_option_selling_opportunity()
            expiry_analyses = analysis.get('expiry_analyses', [])

            if not expiry_analyses:
                self.log_error("Expiry Dates", "No expiry analyses found")
                return

            print(f"\nFound {len(expiry_analyses)} expiries:")

            for i, exp_analysis in enumerate(expiry_analyses, 1):
                expiry_date = exp_analysis.get('expiry_date')
                days_to_expiry = exp_analysis.get('days_to_expiry', 0)

                if isinstance(expiry_date, str):
                    expiry_dt = datetime.fromisoformat(expiry_date)
                else:
                    expiry_dt = expiry_date

                # Calculate expected days
                expected_days = (expiry_dt.date() - datetime.now().date()).days

                print(f"\n  Expiry {i}: {expiry_dt.date()}")
                print(f"    Analyzer days: {days_to_expiry}")
                print(f"    Calculated days: {expected_days}")

                if days_to_expiry == expected_days:
                    self.log_pass(f"Expiry {i} Days", f"{days_to_expiry} days correct")
                else:
                    self.log_error(f"Expiry {i} Days", f"Expected {expected_days}, got {days_to_expiry}")

                # Verify it's a weekly/monthly expiry (Thursday)
                if expiry_dt.weekday() == 3:  # Thursday
                    self.log_pass(f"Expiry {i} Day", "Thursday (correct)")
                else:
                    self.log_warning(f"Expiry {i} Day", f"Not Thursday (weekday {expiry_dt.weekday()})")

        except Exception as e:
            self.log_error("Expiry Dates", str(e))

    def run_all_tests(self):
        """Run all tests"""
        print("\n" + "="*70)
        print("NIFTY OPTION SIGNAL ACCURACY TEST SUITE")
        print("="*70)
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Run tests in sequence
        nifty_spot, analysis = self.test_nifty_spot_price()
        self.test_india_vix()
        atm_strike = self.test_atm_strike_calculation(nifty_spot)
        self.test_option_symbol_construction(atm_strike)
        self.test_option_premiums(atm_strike)
        self.test_score_calculation()
        self.test_greeks_calculation()
        self.test_expiry_dates()
        self.test_telegram_message_accuracy()

        # Print summary
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)

        print(f"\n✅ PASSED: {len(self.passed)}")
        for p in self.passed:
            print(f"  {p}")

        if self.warnings:
            print(f"\n⚠️  WARNINGS: {len(self.warnings)}")
            for w in self.warnings:
                print(f"  {w}")

        if self.errors:
            print(f"\n❌ ERRORS: {len(self.errors)}")
            for e in self.errors:
                print(f"  {e}")

        print("\n" + "="*70)
        if self.errors:
            print("OVERALL RESULT: ❌ FAILED - Issues need to be fixed")
            return False
        elif self.warnings:
            print("OVERALL RESULT: ⚠️  PASSED WITH WARNINGS - Review recommended")
            return True
        else:
            print("OVERALL RESULT: ✅ ALL TESTS PASSED")
            return True


def main():
    """Main entry point"""
    tester = SignalAccuracyTest()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
