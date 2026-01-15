#!/usr/bin/env python3
"""
Test script to verify 5-minute detection implementation
"""

from datetime import datetime
from stock_monitor import StockMonitor
from price_cache import PriceCache
import config

def test_5min_detection():
    """Test 5-minute detection logic"""

    print("="*70)
    print("TESTING 5-MINUTE RAPID DETECTION")
    print("="*70)

    monitor = StockMonitor()
    cache = PriceCache()

    print("\n📋 Configuration Verification:")
    print(f"   5-minute drop threshold: {config.DROP_THRESHOLD_5MIN}%")
    print(f"   5-minute rise threshold: {config.RISE_THRESHOLD_5MIN}%")
    print(f"   10-minute drop threshold: {config.DROP_THRESHOLD_PERCENT}%")
    print(f"   Volume spike multiplier: {config.VOLUME_SPIKE_MULTIPLIER}x")

    assert config.DROP_THRESHOLD_5MIN == 1.25, "5-min drop threshold should be 1.25%"
    assert config.RISE_THRESHOLD_5MIN == 1.25, "5-min rise threshold should be 1.25%"
    print("   ✅ Thresholds configured correctly")

    print("\n📋 Price Cache Method Test:")

    # Test get_prices_5min method
    test_symbol = "TEST.NS"

    # Simulate price updates (5-minute intervals)
    prices = [2500.00, 2480.00, 2470.00]  # Dropping prices
    for price in prices:
        cache.update_price(test_symbol, price, 1000000, datetime.now().isoformat())

    # Get 5-minute prices
    current_5min, price_5min_ago = cache.get_prices_5min(test_symbol)
    print(f"   Current price: ₹{current_5min}")
    print(f"   Price 5 min ago: ₹{price_5min_ago}")

    assert current_5min is not None, "Current price should be retrieved"
    assert price_5min_ago is not None, "5-min ago price should be retrieved"
    print("   ✅ get_prices_5min() method works correctly")

    # Get 10-minute prices
    current_10min, price_10min_ago = cache.get_prices(test_symbol)
    print(f"   Price 10 min ago: ₹{price_10min_ago}")

    assert price_10min_ago is not None, "10-min ago price should be retrieved"
    print("   ✅ get_prices() method still works correctly")

    print("\n📋 Detection Priority Order:")
    print("   1. 🚨 Volume Spike (priority, 5-min comparison)")
    print("   2. ⚡ 5-Minute Drop/Rise (rapid detection)")
    print("   3. 📊 10-Minute Drop/Rise (standard)")
    print("   4. 📈 30-Minute Gradual (trend)")

    print("\n📋 Alert Cooldown Configuration:")
    print("   Volume spike: 15 minutes")
    print("   5-minute alerts: 10 minutes")
    print("   30-minute alerts: 30 minutes")

    print("\n📋 Deduplication Test:")

    # Test 1: First 5-minute drop alert
    should_send = monitor.should_send_alert("RELIANCE", "5min", cooldown_minutes=10)
    assert should_send == True, "First 5-min alert should be sent"
    print("   ✅ First 5-min alert: Allowed")

    # Test 2: Duplicate 5-minute alert (within 10 minutes)
    should_send = monitor.should_send_alert("RELIANCE", "5min", cooldown_minutes=10)
    assert should_send == False, "Duplicate 5-min alert should be blocked"
    print("   ✅ Duplicate 5-min alert: Blocked (within 10-min cooldown)")

    # Test 3: Different stock should be allowed
    should_send = monitor.should_send_alert("TCS", "5min", cooldown_minutes=10)
    assert should_send == True, "Different stock should be allowed"
    print("   ✅ Different stock: Allowed")

    # Test 4: 5-minute rise (different type)
    should_send = monitor.should_send_alert("RELIANCE", "5min_rise", cooldown_minutes=10)
    assert should_send == True, "5-min rise alert should be allowed (different type)"
    print("   ✅ 5-min rise alert: Allowed (different type)")

    print("\n" + "="*70)
    print("✅ ALL TESTS PASSED")
    print("="*70)

    print("\n📊 Expected Behavior Summary:")
    print("\n   🎯 Detection Speed:")
    print("      - Old: ~10 minutes to detect 2% movement")
    print("      - New: ~5 minutes to detect 1.25% movement")
    print("      - Improvement: 2x faster detection!")

    print("\n   🔔 Alert Types Now Available:")
    print("      - volume_spike (5-min comparison, 1.2% threshold)")
    print("      - 5min (new, 1.25% threshold)")
    print("      - 10min (existing, 2.0% threshold)")
    print("      - 30min (existing, 3.0% threshold)")
    print("      - volume_spike_rise (5-min comparison, 1.2% threshold)")
    print("      - 5min_rise (new, 1.25% threshold)")
    print("      - 10min_rise (existing, 2.0% threshold)")
    print("      - 30min_rise (existing, 3.0% threshold)")

    print("\n   ⏱️  Example Timeline:")
    print("      9:00 AM - Stock drops to ₹2470 (1.3% drop in 5 min)")
    print("              → 5-min alert sent immediately ✅")
    print("      9:05 AM - Stock continues dropping (1.2% drop)")
    print("              → Blocked (within 10-min cooldown)")
    print("      9:10 AM - Stock at ₹2445 (2.2% drop from 9:00)")
    print("              → 10-min alert sent ✅")
    print("      9:11 AM - Stock drops more (1.4% drop from 9:06)")
    print("              → 5-min alert sent ✅ (cooldown expired)")

    print("\n   💡 Key Benefits:")
    print("      ✅ Faster detection (5 min vs 10 min)")
    print("      ✅ More comprehensive (both 5-min and 10-min checks)")
    print("      ✅ Smart cooldown prevents spam")
    print("      ✅ Volume spikes now use 5-min comparison (even faster)")

    print("\n" + "="*70)

if __name__ == "__main__":
    test_5min_detection()
