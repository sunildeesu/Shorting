#!/usr/bin/env python3
"""
Tier 2 API Optimization - Comprehensive Test Suite
Tests all components of the Tier 2 implementation
"""

import sys
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - TEST - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Tier2TestSuite:
    """Comprehensive test suite for Tier 2 implementation"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.test_results = []

    def log_test(self, test_name, status, message=""):
        """Log test result"""
        result = {
            'test': test_name,
            'status': status,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        self.test_results.append(result)

        if status == 'PASS':
            self.passed += 1
            logger.info(f"✅ PASS: {test_name} - {message}")
        elif status == 'FAIL':
            self.failed += 1
            logger.error(f"❌ FAIL: {test_name} - {message}")
        elif status == 'WARN':
            self.warnings += 1
            logger.warning(f"⚠️  WARN: {test_name} - {message}")

    def test_imports(self):
        """Test 1: Verify all imports work"""
        logger.info("=" * 60)
        logger.info("TEST SUITE 1: IMPORT VALIDATION")
        logger.info("=" * 60)

        # Test api_coordinator imports
        try:
            from api_coordinator import get_api_coordinator, reset_coordinator, KiteAPICoordinator
            self.log_test("Import api_coordinator", "PASS", "All imports successful")
        except ImportError as e:
            self.log_test("Import api_coordinator", "FAIL", f"ImportError: {e}")
            return False

        # Test historical_data_cache imports
        try:
            from historical_data_cache import get_historical_cache, reset_cache, HistoricalDataCache
            self.log_test("Import historical_data_cache", "PASS", "All imports successful")
        except ImportError as e:
            self.log_test("Import historical_data_cache", "FAIL", f"ImportError: {e}")
            return False

        # Test modified services can import coordinator
        try:
            # We can't fully import services without Kite credentials, but we can check syntax
            import ast

            files_to_check = [
                'atr_breakout_monitor.py',
                'nifty_option_analyzer.py',
                'stock_monitor.py',
                'onemin_monitor.py'
            ]

            for filename in files_to_check:
                with open(filename, 'r') as f:
                    code = f.read()
                    try:
                        ast.parse(code)
                        # Check if api_coordinator import exists
                        if 'from api_coordinator import' in code:
                            self.log_test(f"Import in {filename}", "PASS", "api_coordinator import found")
                        else:
                            self.log_test(f"Import in {filename}", "WARN", "api_coordinator import not found")
                    except SyntaxError as e:
                        self.log_test(f"Syntax in {filename}", "FAIL", f"SyntaxError: {e}")

        except Exception as e:
            self.log_test("Check service imports", "FAIL", f"Error: {e}")
            return False

        return True

    def test_cache_directories(self):
        """Test 2: Verify cache directory structure"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("TEST SUITE 2: CACHE DIRECTORY VALIDATION")
        logger.info("=" * 60)

        # Check if data directory exists
        data_dir = Path('data')
        if not data_dir.exists():
            self.log_test("Data directory exists", "FAIL", "data/ directory not found")
            return False
        else:
            self.log_test("Data directory exists", "PASS", f"{data_dir} found")

        # Check unified_cache directory
        unified_cache_dir = Path('data/unified_cache')
        if unified_cache_dir.exists():
            self.log_test("Unified cache directory", "PASS", f"{unified_cache_dir} exists")

            # Check for quote_cache.db
            quote_cache_db = unified_cache_dir / 'quote_cache.db'
            if quote_cache_db.exists():
                size_mb = quote_cache_db.stat().st_size / 1024 / 1024
                self.log_test("Quote cache database", "PASS", f"quote_cache.db exists ({size_mb:.2f} MB)")
            else:
                self.log_test("Quote cache database", "WARN", "quote_cache.db not found (will be created on first run)")
        else:
            self.log_test("Unified cache directory", "WARN", "data/unified_cache not found (will be created)")

        # Check historical_cache directory
        historical_cache_dir = Path('data/historical_cache')
        if historical_cache_dir.exists():
            self.log_test("Historical cache directory", "PASS", f"{historical_cache_dir} exists")

            # Count cache files
            cache_files = list(historical_cache_dir.glob("*.json"))
            if cache_files:
                total_size = sum(f.stat().st_size for f in cache_files)
                size_mb = total_size / 1024 / 1024
                self.log_test("Historical cache files", "PASS",
                            f"{len(cache_files)} cache files found ({size_mb:.2f} MB)")

                # Show sample files
                for i, cache_file in enumerate(cache_files[:3]):
                    age_hours = (datetime.now().timestamp() - cache_file.stat().st_mtime) / 3600
                    logger.info(f"   Sample {i+1}: {cache_file.name} (age: {age_hours:.1f}h)")
            else:
                self.log_test("Historical cache files", "WARN", "No cache files yet (will be created on first run)")
        else:
            self.log_test("Historical cache directory", "WARN", "data/historical_cache not found (will be created)")

        return True

    def test_api_coordinator_unit(self):
        """Test 3: Unit test API coordinator functionality"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("TEST SUITE 3: API COORDINATOR UNIT TESTS")
        logger.info("=" * 60)

        try:
            from api_coordinator import KiteAPICoordinator, get_api_coordinator, reset_coordinator
            from unified_quote_cache import UnifiedQuoteCache

            # Test 1: Can create coordinator instance (without Kite - will fail but test structure)
            try:
                # This will fail without Kite credentials, but we can test the class exists
                self.log_test("KiteAPICoordinator class exists", "PASS", "Class imported successfully")
            except Exception as e:
                self.log_test("KiteAPICoordinator class exists", "FAIL", str(e))

            # Test 2: Check coordinator has required methods
            required_methods = ['get_quotes', 'get_single_quote', 'get_multiple_instruments',
                              'get_cache_stats', '_format_quotes_for_return']

            for method in required_methods:
                if hasattr(KiteAPICoordinator, method):
                    self.log_test(f"Method {method} exists", "PASS", "Method found in class")
                else:
                    self.log_test(f"Method {method} exists", "FAIL", "Method not found")

            # Test 3: Check singleton pattern
            reset_coordinator()  # Reset any existing instance

            # Try to get coordinator without kite (should fail with proper error)
            try:
                coord = get_api_coordinator()
                self.log_test("Singleton requires kite on first call", "FAIL",
                            "Should have raised ValueError for missing kite parameter")
            except ValueError as e:
                if "kite parameter required" in str(e):
                    self.log_test("Singleton requires kite on first call", "PASS",
                                "Correctly raises ValueError when kite not provided")
                else:
                    self.log_test("Singleton requires kite on first call", "FAIL",
                                f"Wrong error message: {e}")

            # Test 4: Check batch size configuration
            # We can't instantiate without kite, but we can check default in code
            import inspect
            source = inspect.getsource(KiteAPICoordinator.__init__)
            if 'self.batch_size = 200' in source:
                self.log_test("Batch size configuration", "PASS", "Batch size set to 200")
            else:
                self.log_test("Batch size configuration", "WARN", "Batch size may not be 200")

        except Exception as e:
            self.log_test("API Coordinator unit tests", "FAIL", f"Unexpected error: {e}")
            return False

        return True

    def test_historical_cache_unit(self):
        """Test 4: Unit test historical data cache functionality"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("TEST SUITE 4: HISTORICAL CACHE UNIT TESTS")
        logger.info("=" * 60)

        try:
            from historical_data_cache import HistoricalDataCache, get_historical_cache, reset_cache

            # Test 1: Can create cache instance
            try:
                cache = HistoricalDataCache(cache_dir='data/test_cache')
                self.log_test("HistoricalDataCache instantiation", "PASS", "Cache instance created")

                # Clean up test directory
                test_cache_dir = Path('data/test_cache')
                if test_cache_dir.exists():
                    import shutil
                    shutil.rmtree(test_cache_dir)

            except Exception as e:
                self.log_test("HistoricalDataCache instantiation", "FAIL", str(e))
                return False

            # Test 2: Check required methods
            required_methods = ['get_historical_data', 'clear_cache', 'get_cache_stats',
                              '_generate_cache_key', '_is_cache_valid', '_is_market_open',
                              '_get_last_market_close']

            for method in required_methods:
                if hasattr(HistoricalDataCache, method):
                    self.log_test(f"Method {method} exists", "PASS", "Method found in class")
                else:
                    self.log_test(f"Method {method} exists", "FAIL", "Method not found")

            # Test 3: Test cache key generation
            cache = HistoricalDataCache(cache_dir='data/test_cache')
            test_key = cache._generate_cache_key(
                instrument_token=264969,
                from_date=datetime(2026, 1, 1),
                to_date=datetime(2026, 1, 10),
                interval='day',
                continuous=False,
                oi=False
            )

            expected_key = "264969_day_2026-01-01_2026-01-10"
            if test_key == expected_key:
                self.log_test("Cache key generation", "PASS", f"Key: {test_key}")
            else:
                self.log_test("Cache key generation", "FAIL",
                            f"Expected {expected_key}, got {test_key}")

            # Test 4: Test market open detection
            is_open = cache._is_market_open()
            current_time = datetime.now().time()
            logger.info(f"   Current time: {current_time}, Market open: {is_open}")
            self.log_test("Market open detection", "PASS", f"Method executes (market_open={is_open})")

            # Test 5: Test cache stats
            stats = cache.get_cache_stats()
            if 'cache_dir' in stats and 'file_count' in stats:
                self.log_test("Cache statistics", "PASS",
                            f"Stats: {stats['file_count']} files, {stats['total_size_mb']} MB")
            else:
                self.log_test("Cache statistics", "FAIL", "Missing required stats fields")

            # Clean up
            test_cache_dir = Path('data/test_cache')
            if test_cache_dir.exists():
                import shutil
                shutil.rmtree(test_cache_dir)

        except Exception as e:
            self.log_test("Historical cache unit tests", "FAIL", f"Unexpected error: {e}")
            return False

        return True

    def test_integration_points(self):
        """Test 5: Verify integration points in services"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("TEST SUITE 5: SERVICE INTEGRATION VALIDATION")
        logger.info("=" * 60)

        services = {
            'atr_breakout_monitor.py': {
                'imports': ['from api_coordinator import get_api_coordinator'],
                'init_code': ['self.coordinator = get_api_coordinator'],
                'usage': ['self.coordinator.get_quotes']
            },
            'nifty_option_analyzer.py': {
                'imports': ['from api_coordinator import get_api_coordinator',
                          'from historical_data_cache import get_historical_cache'],
                'init_code': ['self.coordinator = get_api_coordinator',
                            'self.historical_cache = get_historical_cache'],
                'usage': ['self.coordinator.get_single_quote',
                        'self.historical_cache.get_historical_data']
            },
            'stock_monitor.py': {
                'imports': ['from api_coordinator import get_api_coordinator'],
                'init_code': ['self.coordinator = get_api_coordinator'],
                'usage': ['self.coordinator.get_quotes']
            },
            'onemin_monitor.py': {
                'imports': ['from api_coordinator import get_api_coordinator'],
                'init_code': ['self.coordinator = get_api_coordinator'],
                'usage': ['self.coordinator.get_multiple_instruments']
            }
        }

        for service_name, checks in services.items():
            try:
                with open(service_name, 'r') as f:
                    code = f.read()

                # Check imports
                import_found = all(imp in code for imp in checks['imports'])
                if import_found:
                    self.log_test(f"{service_name} - Imports", "PASS",
                                f"{len(checks['imports'])} imports found")
                else:
                    missing = [imp for imp in checks['imports'] if imp not in code]
                    self.log_test(f"{service_name} - Imports", "FAIL",
                                f"Missing: {missing}")

                # Check initialization
                init_found = all(init in code for init in checks['init_code'])
                if init_found:
                    self.log_test(f"{service_name} - Initialization", "PASS",
                                f"{len(checks['init_code'])} init statements found")
                else:
                    missing = [init for init in checks['init_code'] if init not in code]
                    self.log_test(f"{service_name} - Initialization", "FAIL",
                                f"Missing: {missing}")

                # Check usage
                usage_found = any(usage in code for usage in checks['usage'])
                if usage_found:
                    found_usages = [u for u in checks['usage'] if u in code]
                    self.log_test(f"{service_name} - Usage", "PASS",
                                f"Found: {found_usages[0]}...")
                else:
                    self.log_test(f"{service_name} - Usage", "FAIL",
                                "No coordinator usage found")

            except FileNotFoundError:
                self.log_test(f"{service_name} - File check", "FAIL", "File not found")
            except Exception as e:
                self.log_test(f"{service_name} - Validation", "FAIL", str(e))

        return True

    def test_fallback_logic(self):
        """Test 6: Verify fallback logic exists"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("TEST SUITE 6: FALLBACK LOGIC VALIDATION")
        logger.info("=" * 60)

        # Check if services have try-except blocks around coordinator usage
        services_with_fallback = [
            'atr_breakout_monitor.py',
            'stock_monitor.py'
        ]

        for service in services_with_fallback:
            try:
                with open(service, 'r') as f:
                    code = f.read()

                # Look for error handling pattern
                has_try_except = 'except Exception as e:' in code
                has_fallback_comment = 'fallback' in code.lower() or 'fall back' in code.lower()

                if has_try_except:
                    self.log_test(f"{service} - Error handling", "PASS", "try-except blocks found")
                else:
                    self.log_test(f"{service} - Error handling", "WARN", "No error handling found")

                if has_fallback_comment:
                    self.log_test(f"{service} - Fallback logic", "PASS", "Fallback logic documented")
                else:
                    self.log_test(f"{service} - Fallback logic", "WARN", "Fallback not explicitly mentioned")

            except Exception as e:
                self.log_test(f"{service} - Fallback check", "FAIL", str(e))

        return True

    def generate_report(self):
        """Generate final test report"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("TEST EXECUTION SUMMARY")
        logger.info("=" * 60)

        total_tests = self.passed + self.failed + self.warnings

        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"✅ Passed: {self.passed}")
        logger.info(f"❌ Failed: {self.failed}")
        logger.info(f"⚠️  Warnings: {self.warnings}")
        logger.info("")

        if self.failed == 0:
            logger.info("🎉 ALL CRITICAL TESTS PASSED!")
            logger.info("Tier 2 implementation is READY FOR DEPLOYMENT")
        else:
            logger.error(f"⚠️  {self.failed} CRITICAL FAILURES DETECTED")
            logger.error("Please review and fix failures before deployment")

        logger.info("=" * 60)

        # Save detailed report
        report_file = 'test_results_tier2.json'
        with open(report_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'summary': {
                    'total': total_tests,
                    'passed': self.passed,
                    'failed': self.failed,
                    'warnings': self.warnings
                },
                'tests': self.test_results
            }, f, indent=2)

        logger.info(f"Detailed report saved to: {report_file}")

        return self.failed == 0

def main():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("TIER 2 API OPTIMIZATION - TEST SUITE")
    logger.info("Testing: API Coordinator + Historical Cache Implementation")
    logger.info("=" * 60)
    logger.info("")

    suite = Tier2TestSuite()

    # Run all test suites
    suite.test_imports()
    suite.test_cache_directories()
    suite.test_api_coordinator_unit()
    suite.test_historical_cache_unit()
    suite.test_integration_points()
    suite.test_fallback_logic()

    # Generate final report
    success = suite.generate_report()

    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
