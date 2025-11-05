#!/usr/bin/env python3
"""
Test script to verify alert deduplication logic
"""

from datetime import datetime, timedelta
from stock_monitor import StockMonitor

def test_alert_deduplication():
    """Test that 30-minute alerts are deduplicated correctly"""

    print("="*60)
    print("TESTING ALERT DEDUPLICATION")
    print("="*60)

    monitor = StockMonitor()

    test_symbol = "RELIANCE"

    # Test 1: First alert should be sent
    print("\n📌 Test 1: First 30min alert should be sent")
    should_send = monitor.should_send_alert(test_symbol, "30min", cooldown_minutes=30)
    assert should_send == True, "First alert should be sent"
    print(f"✅ Result: {should_send} (PASS)")

    # Test 2: Immediate duplicate should be blocked
    print("\n📌 Test 2: Immediate duplicate should be blocked")
    should_send = monitor.should_send_alert(test_symbol, "30min", cooldown_minutes=30)
    assert should_send == False, "Duplicate alert should be blocked"
    print(f"✅ Result: {should_send} (PASS)")

    # Test 3: Different alert type for same stock should be allowed
    print("\n📌 Test 3: Different alert type (30min_rise) should be allowed")
    should_send = monitor.should_send_alert(test_symbol, "30min_rise", cooldown_minutes=30)
    assert should_send == True, "Different alert type should be allowed"
    print(f"✅ Result: {should_send} (PASS)")

    # Test 4: Same alert type for different stock should be allowed
    print("\n📌 Test 4: Same alert type for different stock should be allowed")
    should_send = monitor.should_send_alert("TCS", "30min", cooldown_minutes=30)
    assert should_send == True, "Different stock should be allowed"
    print(f"✅ Result: {should_send} (PASS)")

    # Test 5: Simulate cooldown expiry
    print("\n📌 Test 5: Alert after cooldown period should be sent")
    # Manually set the alert history to 31 minutes ago
    alert_key = (test_symbol, "30min")
    monitor.alert_history[alert_key] = datetime.now() - timedelta(minutes=31)

    should_send = monitor.should_send_alert(test_symbol, "30min", cooldown_minutes=30)
    assert should_send == True, "Alert after cooldown should be sent"
    print(f"✅ Result: {should_send} (PASS)")

    # Test 6: Alert just before cooldown expiry should be blocked
    print("\n📌 Test 6: Alert just before cooldown expiry should be blocked")
    alert_key = (test_symbol, "30min")
    monitor.alert_history[alert_key] = datetime.now() - timedelta(minutes=29)

    should_send = monitor.should_send_alert(test_symbol, "30min", cooldown_minutes=30)
    assert should_send == False, "Alert before cooldown should be blocked"
    print(f"✅ Result: {should_send} (PASS)")

    print("\n" + "="*60)
    print("✅ ALL TESTS PASSED")
    print("="*60)
    print("\nDeduplication Logic:")
    print("- 30-minute alerts will only be sent once per stock")
    print("- Cooldown period: 30 minutes")
    print("- Different alert types (30min vs 30min_rise) are tracked separately")
    print("- Different stocks are tracked separately")
    print("\nThis prevents the same alert from being sent every 5 minutes!")
    print("="*60)

if __name__ == "__main__":
    test_alert_deduplication()
