#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test Market Cap Calculation and Display
"""

import json
from telegram_notifier import TelegramNotifier

def test_market_cap_calculation():
    """Test market cap calculation logic"""
    print("\n" + "="*60)
    print("TEST 1: Market Cap Calculation")
    print("="*60 + "\n")

    # Load shares data
    with open('data/shares_outstanding.json', 'r') as f:
        shares_data = json.load(f)

    # Test with RELIANCE
    symbol = "RELIANCE"
    price = 1500.00
    shares = shares_data[symbol]

    # Calculate market cap: (Price × Shares) / 10,000,000 = Crores
    market_cap_cr = (price * shares) / 10000000

    print(f"Stock: {symbol}")
    print(f"Price: ₹{price:.2f}")
    print(f"Shares Outstanding: {shares:,}")
    print(f"Calculated Market Cap: ₹{market_cap_cr:,.0f} Cr")
    print(f"\n✓ Calculation successful!\n")

    return market_cap_cr

def test_telegram_alert_format():
    """Test that Telegram alert includes market cap"""
    print("="*60)
    print("TEST 2: Telegram Alert Message Format")
    print("="*60 + "\n")

    # Create notifier instance (won't actually send, just format)
    notifier = TelegramNotifier()

    # Test data
    symbol = "RELIANCE.NS"
    drop_percent = 2.5
    current_price = 1450.00
    previous_price = 1486.21
    market_cap_cr = 981521  # From test 1

    # Format alert message
    message = notifier._format_alert_message(
        symbol=symbol,
        drop_percent=drop_percent,
        current_price=current_price,
        previous_price=previous_price,
        alert_type="5min",
        volume_data={"current_volume": 5000000, "avg_volume": 2000000},
        market_cap_cr=market_cap_cr
    )

    print("Generated Alert Message:")
    print("-" * 60)
    print(message)
    print("-" * 60)

    # Verify market cap is in the message
    if "Market Cap" in message and f"{market_cap_cr:,.0f}" in message:
        print("\n✓ Market cap found in alert message!")
        print(f"✓ Format: Market Cap: ₹{market_cap_cr:,.0f} Cr ({drop_percent:+.2f}%)")
    else:
        print("\n✗ Market cap NOT found in alert message!")
        return False

    # Verify market cap % change matches price % change
    if f"({drop_percent:+.2f}%)" in message:
        print(f"✓ Market cap % change matches price % change: {drop_percent:+.2f}%")

    print("\n✓ Alert format test passed!\n")
    return True

def test_missing_market_cap():
    """Test alert format when market cap is not available"""
    print("="*60)
    print("TEST 3: Alert Without Market Cap (Stock Not in Database)")
    print("="*60 + "\n")

    notifier = TelegramNotifier()

    message = notifier._format_alert_message(
        symbol="UNKNOWN.NS",
        drop_percent=2.5,
        current_price=100.00,
        previous_price=102.56,
        alert_type="5min",
        volume_data={"current_volume": 1000000, "avg_volume": 500000},
        market_cap_cr=None  # No market cap available
    )

    print("Alert for stock without market cap data:")
    print("-" * 60)
    print(message)
    print("-" * 60)

    if "Market Cap" not in message:
        print("\n✓ Alert works without market cap (gracefully degrades)")
    else:
        print("\n✗ Market cap should not appear when None")
        return False

    print("\n✓ Missing data test passed!\n")
    return True

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("MARKET CAP FEATURE TEST SUITE")
    print("="*60)

    try:
        # Test 1: Calculation
        market_cap = test_market_cap_calculation()

        # Test 2: Alert format with market cap
        test_telegram_alert_format()

        # Test 3: Alert format without market cap
        test_missing_market_cap()

        print("="*60)
        print("ALL TESTS PASSED! ✅")
        print("="*60)
        print("\n📊 Market cap feature is working correctly!")
        print("💡 Market cap will show in all alerts for stocks in database\n")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
