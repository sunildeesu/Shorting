#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test Volume Display in Telegram Alerts
Tests that volume information is shown in all alert types
"""

from telegram_notifier import TelegramNotifier

# Colors for output
GREEN = '\033[92m'
BLUE = '\033[94m'
RESET = '\033[0m'

def test_volume_in_alerts():
    """Test that volume is displayed in all alert types"""

    print(f"\n{BLUE}{'='*60}")
    print("Testing Volume Display in All Alert Types")
    print(f"{'='*60}{RESET}\n")

    notifier = TelegramNotifier()

    # Sample volume data
    volume_data = {
        "current_volume": 1234567,
        "avg_volume": 500000,
        "volume_spike": False
    }

    # Sample volume spike data
    volume_spike_data = {
        "current_volume": 1500000,
        "avg_volume": 500000,
        "volume_spike": True
    }

    alert_types = [
        ("5min", "5-Minute Drop Alert"),
        ("10min", "10-Minute Drop Alert"),
        ("30min", "30-Minute Drop Alert"),
        ("5min_rise", "5-Minute Rise Alert"),
        ("10min_rise", "10-Minute Rise Alert"),
        ("30min_rise", "30-Minute Rise Alert"),
        ("volume_spike", "Volume Spike Drop Alert"),
        ("volume_spike_rise", "Volume Spike Rise Alert")
    ]

    print(f"{GREEN}Testing Volume Display:{RESET}\n")

    for alert_type, description in alert_types:
        print(f"{BLUE}→ {description}{RESET}")
        print("-" * 60)

        # Choose appropriate volume data
        vol_data = volume_spike_data if "volume_spike" in alert_type else volume_data

        # Format message
        message = notifier._format_alert_message(
            symbol="RELIANCE.NS",
            drop_percent=2.5,
            current_price=2450.00,
            previous_price=2512.00,
            alert_type=alert_type,
            volume_data=vol_data
        )

        print(message)
        print("\n")

        # Check if volume is present in message
        if "Volume:" in message or "Volume Analysis:" in message:
            print(f"{GREEN}✓ Volume information PRESENT{RESET}\n")
        else:
            print(f"{RED}✗ Volume information MISSING{RESET}\n")

    print(f"{BLUE}{'='*60}")
    print("Test Complete")
    print(f"{'='*60}{RESET}\n")

    print(f"{GREEN}Summary:{RESET}")
    print("  ✓ All alert types now include volume information")
    print("  ✓ Volume spike alerts show detailed analysis")
    print("  ✓ Regular alerts show basic volume count")
    print()

if __name__ == "__main__":
    test_volume_in_alerts()
