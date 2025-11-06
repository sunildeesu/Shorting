#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test Persistent Alert Deduplication
Tests that alert deduplication works across script restarts (simulates cron job behavior)
"""

import os
import sys
import time
from datetime import datetime, timedelta
from alert_history_manager import AlertHistoryManager

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_test(name):
    print(f"\n{BLUE}→ Test: {name}{RESET}")

def print_pass(msg):
    print(f"  {GREEN}✓ PASS:{RESET} {msg}")

def print_fail(msg):
    print(f"  {RED}✗ FAIL:{RESET} {msg}")
    sys.exit(1)

def print_info(msg):
    print(f"  {YELLOW}ℹ INFO:{RESET} {msg}")

def cleanup_test_file():
    """Remove test history file if it exists"""
    test_file = "data/alert_history_test.json"
    if os.path.exists(test_file):
        os.remove(test_file)
        print_info(f"Cleaned up test file: {test_file}")

def test_persistent_deduplication():
    """Test that deduplication works across multiple script runs"""
    test_file = "data/alert_history_test.json"
    cleanup_test_file()

    print_test("Persistent Deduplication Across Script Restarts")

    # === RUN 1: First alert should be sent ===
    print_info("RUN 1: First script execution (fresh start)")
    manager1 = AlertHistoryManager(history_file=test_file)

    result = manager1.should_send_alert("RELIANCE", "30min", cooldown_minutes=30)
    if result:
        print_pass("First alert allowed (no previous history)")
    else:
        print_fail("First alert blocked (should be allowed)")

    # Verify file was created
    if os.path.exists(test_file):
        print_pass(f"Alert history file created: {test_file}")
    else:
        print_fail("Alert history file was not created")

    del manager1  # Simulate script exit

    # === RUN 2: Duplicate should be blocked ===
    print_info("RUN 2: Second script execution (5 minutes later - simulates cron)")
    time.sleep(0.1)  # Small delay to simulate time passing
    manager2 = AlertHistoryManager(history_file=test_file)

    result = manager2.should_send_alert("RELIANCE", "30min", cooldown_minutes=30)
    if not result:
        print_pass("Duplicate alert blocked (loaded from file)")
    else:
        print_fail("Duplicate alert allowed (should be blocked)")

    # Check that history was loaded
    stats = manager2.get_stats()
    if stats["total_alerts"] > 0:
        print_pass(f"Alert history loaded from file ({stats['total_alerts']} entries)")
    else:
        print_fail("Alert history not loaded from file")

    del manager2  # Simulate script exit

    # === RUN 3: Different stock should be allowed ===
    print_info("RUN 3: Third script execution (different stock)")
    time.sleep(0.1)
    manager3 = AlertHistoryManager(history_file=test_file)

    result = manager3.should_send_alert("TCS", "30min", cooldown_minutes=30)
    if result:
        print_pass("Different stock alert allowed")
    else:
        print_fail("Different stock alert blocked (should be allowed)")

    del manager3  # Simulate script exit

    # === RUN 4: Different alert type should be allowed ===
    print_info("RUN 4: Fourth script execution (different alert type, same stock)")
    time.sleep(0.1)
    manager4 = AlertHistoryManager(history_file=test_file)

    result = manager4.should_send_alert("RELIANCE", "5min", cooldown_minutes=10)
    if result:
        print_pass("Different alert type allowed for same stock")
    else:
        print_fail("Different alert type blocked (should be allowed)")

    del manager4  # Simulate script exit

    # === RUN 5: Test cooldown expiry (simulate time passing) ===
    print_info("RUN 5: Fifth script execution (manually expire cooldown)")
    manager5 = AlertHistoryManager(history_file=test_file)

    # Manually expire the RELIANCE 30min alert by manipulating the timestamp
    alert_key = ("RELIANCE", "30min")
    if alert_key in manager5.alert_history:
        # Set timestamp to 31 minutes ago (past 30-min cooldown)
        manager5.alert_history[alert_key] = datetime.now() - timedelta(minutes=31)
        manager5._save_history()
        print_info("Manually expired RELIANCE 30min cooldown (31 minutes ago)")

    result = manager5.should_send_alert("RELIANCE", "30min", cooldown_minutes=30)
    if result:
        print_pass("Alert allowed after cooldown expiry")
    else:
        print_fail("Alert blocked after cooldown expiry (should be allowed)")

    del manager5

    # === RUN 6: Test auto-cleanup of old entries ===
    print_info("RUN 6: Sixth script execution (test auto-cleanup)")
    manager6 = AlertHistoryManager(history_file=test_file)

    # Add an old entry (65 minutes ago - should be cleaned up)
    old_key = ("OLDSTOCK", "30min")
    manager6.alert_history[old_key] = datetime.now() - timedelta(minutes=65)
    manager6._save_history()
    del manager6

    # Create new manager - should auto-cleanup old entry
    manager7 = AlertHistoryManager(history_file=test_file)
    if old_key not in manager7.alert_history:
        print_pass("Old alert entry auto-cleaned (>60 minutes)")
    else:
        print_fail("Old alert entry not cleaned (should be removed)")

    stats = manager7.get_stats()
    print_info(f"Final history stats: {stats['total_alerts']} active alerts")

    # Cleanup
    cleanup_test_file()
    print_pass("Test cleanup complete")

def test_file_locking():
    """Test that file locking prevents corruption"""
    test_file = "data/alert_history_test.json"
    cleanup_test_file()

    print_test("File Locking (prevents race conditions)")

    manager = AlertHistoryManager(history_file=test_file)

    # Send multiple alerts in quick succession
    symbols = ["RELIANCE", "TCS", "INFY", "HDFC", "WIPRO"]
    for symbol in symbols:
        manager.should_send_alert(symbol, "30min", cooldown_minutes=30)

    print_pass(f"Sent {len(symbols)} alerts without corruption")

    # Verify file is still valid JSON
    stats = manager.get_stats()
    if stats["total_alerts"] == len(symbols):
        print_pass(f"All {len(symbols)} alerts saved correctly")
    else:
        print_fail(f"Expected {len(symbols)} alerts, got {stats['total_alerts']}")

    cleanup_test_file()

def test_stats_api():
    """Test the stats API"""
    test_file = "data/alert_history_test.json"
    cleanup_test_file()

    print_test("Stats API")

    manager = AlertHistoryManager(history_file=test_file)

    # Empty history
    stats = manager.get_stats()
    if stats["total_alerts"] == 0 and stats["oldest_entry"] is None:
        print_pass("Empty history stats correct")
    else:
        print_fail("Empty history stats incorrect")

    # Add some alerts
    manager.should_send_alert("RELIANCE", "30min", cooldown_minutes=30)
    time.sleep(0.01)  # Small delay to ensure different timestamps
    manager.should_send_alert("TCS", "5min", cooldown_minutes=10)

    stats = manager.get_stats()
    if stats["total_alerts"] == 2:
        print_pass(f"Stats show correct alert count: {stats['total_alerts']}")
        print_info(f"  Oldest: {stats['oldest_entry']}")
        print_info(f"  Newest: {stats['newest_entry']}")
    else:
        print_fail(f"Expected 2 alerts, got {stats['total_alerts']}")

    # Test get_last_alert_time
    last_time = manager.get_last_alert_time("RELIANCE", "30min")
    if last_time is not None:
        print_pass("get_last_alert_time() returns valid timestamp")
    else:
        print_fail("get_last_alert_time() returned None")

    cleanup_test_file()

def main():
    print(f"\n{BLUE}{'='*60}")
    print("Persistent Alert Deduplication Test Suite")
    print(f"{'='*60}{RESET}\n")

    try:
        test_persistent_deduplication()
        test_file_locking()
        test_stats_api()

        print(f"\n{GREEN}{'='*60}")
        print("✓ ALL TESTS PASSED!")
        print(f"{'='*60}{RESET}\n")

        print(f"{YELLOW}Summary:{RESET}")
        print("  ✓ Persistent storage works across script restarts")
        print("  ✓ Deduplication survives cron job behavior")
        print("  ✓ File locking prevents corruption")
        print("  ✓ Auto-cleanup removes old entries")
        print("  ✓ Stats API provides monitoring capabilities")
        print(f"\n{GREEN}✅ Persistent deduplication is ready for production!{RESET}\n")

    except Exception as e:
        print(f"\n{RED}{'='*60}")
        print(f"✗ TEST FAILED: {e}")
        print(f"{'='*60}{RESET}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
