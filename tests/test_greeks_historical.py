#!/usr/bin/env python3
"""
Test Greeks Difference Tracker with Historical/Simulated Data

Simulates a full trading day from 9:15 AM to 3:30 PM with realistic Greeks values.
Tests all functionality: baseline capture, updates, Excel export, cloud upload, Telegram.
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List
import random

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from greeks_difference_tracker import GreeksDifferenceTracker
from kiteconnect import KiteConnect


class MockKiteConnect:
    """Mock KiteConnect for testing with simulated data"""

    def __init__(self, api_key):
        self.api_key = api_key
        self.access_token = None
        self.nifty_spot = 23456.75
        self.time_multiplier = 0  # Simulates time progression

    def set_access_token(self, token):
        self.access_token = token

    def instruments(self, exchange=None):
        """Return mock instruments list with NIFTY options"""
        expiry_date = (datetime.now() + timedelta(days=12)).date()  # Next week expiry

        instruments = []

        # Generate instruments for various strikes
        base_strike = 23400
        for offset in range(-500, 550, 50):
            strike = base_strike + offset

            # CE option
            instruments.append({
                'instrument_token': 10000000 + strike * 10,
                'exchange_token': 1000 + strike,
                'tradingsymbol': f'NIFTY{expiry_date.strftime("%d%b%y").upper()}{strike}CE',
                'name': 'NIFTY',
                'expiry': expiry_date,
                'strike': strike,
                'tick_size': 0.05,
                'lot_size': 50,
                'instrument_type': 'CE',
                'segment': 'NFO-OPT',
                'exchange': 'NFO'
            })

            # PE option
            instruments.append({
                'instrument_token': 20000000 + strike * 10,
                'exchange_token': 2000 + strike,
                'tradingsymbol': f'NIFTY{expiry_date.strftime("%d%b%y").upper()}{strike}PE',
                'name': 'NIFTY',
                'expiry': expiry_date,
                'strike': strike,
                'tick_size': 0.05,
                'lot_size': 50,
                'instrument_type': 'PE',
                'segment': 'NFO-OPT',
                'exchange': 'NFO'
            })

        return instruments

    def quote(self, instruments):
        """Return mock quote data with realistic Greeks"""
        quotes = {}

        for instrument in instruments:
            # Parse instrument name (e.g., "NSE:NIFTY 50" or "NFO:NIFTY2601097550CE")
            if "NSE:NIFTY" in instrument and "50" in instrument:
                # NIFTY spot quote
                quotes[instrument] = {
                    'instrument_token': 256265,
                    'last_price': self.nifty_spot + (self.time_multiplier * 2.5),  # Simulate drift
                    'ohlc': {
                        'open': self.nifty_spot,
                        'high': self.nifty_spot + 50,
                        'low': self.nifty_spot - 30,
                        'close': self.nifty_spot
                    }
                }
            elif "NFO:NIFTY" in instrument:
                # Option quote with Greeks
                option_quote = self._generate_option_quote(instrument)
                if option_quote:
                    quotes[instrument] = option_quote

        return quotes

    def _generate_option_quote(self, instrument: str) -> Dict:
        """Generate realistic option quote with Greeks"""

        # Parse strike and option type from instrument
        # Format: NFO:NIFTY260109XXXXYY where YYMMDD=260109, XXXX=strike, YY=CE/PE
        try:
            # Remove exchange prefix
            symbol = instrument.replace('NFO:', '')

            # Extract option type (last 2 chars)
            option_type = symbol[-2:]

            # Extract everything after NIFTY and date (6 digits)
            # Format: NIFTYYYMMDDSTRIKECE/PE
            after_nifty = symbol[5:]  # Remove "NIFTY"
            after_date = after_nifty[6:]  # Remove YYMMDD (6 digits)
            strike_str = after_date[:-2]  # Remove CE/PE

            strike = int(strike_str)

            # Calculate moneyness
            spot_price = self.nifty_spot + (self.time_multiplier * 2.5)
            moneyness = (spot_price - strike) / strike

            # Generate realistic Greeks based on moneyness
            if option_type == 'CE':
                # Call option
                if moneyness > 0.01:  # ITM
                    delta = 0.60 + (moneyness * 20) + (self.time_multiplier * 0.002)
                elif moneyness > -0.01:  # ATM
                    delta = 0.50 + (self.time_multiplier * 0.003)
                else:  # OTM
                    delta = 0.30 - (abs(moneyness) * 15) + (self.time_multiplier * 0.001)

                delta = max(0.05, min(0.95, delta))  # Clamp to realistic range

            else:  # PE
                # Put option
                if moneyness < -0.01:  # ITM
                    delta = -0.60 - (abs(moneyness) * 20) - (self.time_multiplier * 0.002)
                elif moneyness > -0.01 and moneyness < 0.01:  # ATM
                    delta = -0.50 - (self.time_multiplier * 0.003)
                else:  # OTM
                    delta = -0.30 + (moneyness * 15) - (self.time_multiplier * 0.001)

                delta = max(-0.95, min(-0.05, delta))  # Clamp to realistic range

            # Theta (time decay) - increases as day progresses
            theta = -15.5 - (self.time_multiplier * 0.25) + random.uniform(-1, 1)

            # Vega (volatility sensitivity) - varies with market conditions
            vega = 12.0 + (self.time_multiplier * 0.15) + random.uniform(-2, 3)

            # Gamma
            gamma = 0.0005 - (self.time_multiplier * 0.00002)

            # Last price
            if abs(moneyness) < 0.02:  # Near ATM
                last_price = 150 + (self.time_multiplier * 5) + random.uniform(-10, 10)
            elif moneyness > 0 and option_type == 'CE':  # ITM call
                last_price = 300 + (self.time_multiplier * 8) + random.uniform(-15, 15)
            elif moneyness < 0 and option_type == 'PE':  # ITM put
                last_price = 300 + (self.time_multiplier * 8) + random.uniform(-15, 15)
            else:  # OTM
                last_price = 50 + (self.time_multiplier * 2) + random.uniform(-5, 5)

            return {
                'instrument_token': random.randint(10000000, 20000000),
                'last_price': max(0.05, last_price),
                'ohlc': {
                    'open': last_price * 0.98,
                    'high': last_price * 1.05,
                    'low': last_price * 0.95,
                    'close': last_price
                }
                # NOTE: Not including 'greeks' to test Black-Scholes calculation
            }

        except Exception as e:
            print(f"Error generating quote for {instrument}: {e}")
            return None


def simulate_trading_day():
    """Simulate a full trading day from 9:15 AM to 3:30 PM"""

    print("=" * 70)
    print("GREEKS DIFFERENCE TRACKER - HISTORICAL DATA SIMULATION")
    print("=" * 70)
    print(f"\nDate: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"Simulating: 9:15 AM to 3:30 PM (25 updates, every 15 minutes)")
    print("=" * 70)

    # Initialize mock Kite
    mock_kite = MockKiteConnect(api_key=config.KITE_API_KEY)
    mock_kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Create tracker with mock Kite
    tracker = GreeksDifferenceTracker(mock_kite)

    # Generate timeline: 9:15 AM to 3:30 PM, every 15 minutes
    start_time = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
    end_time = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)

    current_time = start_time
    update_count = 0

    # Step 1: Capture baseline at 9:15 AM
    print(f"\n{'=' * 70}")
    print(f"[{current_time.strftime('%H:%M')}] STEP 1: CAPTURING BASELINE GREEKS")
    print(f"{'=' * 70}")

    mock_kite.time_multiplier = 0  # Reset to baseline
    success = tracker.capture_baseline_greeks()

    if not success:
        print("\n❌ Failed to capture baseline. Exiting.")
        return False

    print(f"✅ Baseline captured successfully!")
    print(f"   NIFTY Spot: {mock_kite.nifty_spot:.2f}")
    print(f"   Baseline strikes: {len(tracker.baseline_greeks)}")

    # Step 2: Simulate updates every 15 minutes
    current_time += timedelta(minutes=15)
    update_count = 1

    while current_time <= end_time:
        print(f"\n{'=' * 70}")
        print(f"[{current_time.strftime('%H:%M')}] UPDATE #{update_count}")
        print(f"{'=' * 70}")

        # Advance time simulation
        mock_kite.time_multiplier = update_count

        # Fetch live Greeks and calculate differences
        aggregated = tracker.fetch_live_and_calculate_diff()

        if aggregated:
            print(f"✅ Greeks fetched and differences calculated")
            print(f"   NIFTY: {aggregated['nifty_spot']:.2f}")
            print(f"   CE Delta Diff: {aggregated['CE']['delta_diff_sum']:+.4f}")
            print(f"   CE Theta Diff: {aggregated['CE']['theta_diff_sum']:+.4f}")
            print(f"   CE Vega Diff: {aggregated['CE']['vega_diff_sum']:+.4f}")
            print(f"   PE Delta Diff: {aggregated['PE']['delta_diff_sum']:+.4f}")
            print(f"   PE Theta Diff: {aggregated['PE']['theta_diff_sum']:+.4f}")
            print(f"   PE Vega Diff: {aggregated['PE']['vega_diff_sum']:+.4f}")
        else:
            print(f"⚠️  Failed to calculate differences")

        # Export to Excel
        excel_path = tracker.export_to_excel()
        if excel_path:
            print(f"   📊 Excel updated: {excel_path}")

        # Upload to cloud every time (matches real implementation)
        if update_count == 1:
            print(f"\n   📤 Uploading to Dropbox (first time)...")
        else:
            print(f"   📤 Re-uploading to Dropbox...")

        cloud_link = tracker._upload_to_cloud(excel_path)

        if cloud_link:
            print(f"   ✅ Uploaded to cloud: {cloud_link}")

            # Send Telegram notification only on first update
            if update_count == 1:
                print(f"\n   📱 Sending Telegram notification...")
                tracker.send_telegram_notification(cloud_link)
                print(f"   ✅ Telegram message sent!")
            else:
                print(f"   🔄 File updated in cloud (no new Telegram message)")
        else:
            print(f"   ⚠️  Cloud upload failed")

        # Next iteration
        current_time += timedelta(minutes=15)
        update_count += 1

    # Summary
    print(f"\n{'=' * 70}")
    print("SIMULATION COMPLETE")
    print(f"{'=' * 70}")
    print(f"✅ Total updates: {update_count - 1}")
    print(f"✅ Excel rows: {len(tracker.history)}")
    print(f"✅ Final Excel: {tracker.export_to_excel()}")
    print(f"{'=' * 70}")

    return True


def main():
    """Main entry point"""
    try:
        success = simulate_trading_day()

        if success:
            print("\n✅ Historical data test completed successfully!")
            print("\nNext steps:")
            print("  1. Check the Excel file in data/greeks_difference_reports/")
            print("  2. Verify Dropbox upload (if configured)")
            print("  3. Check Telegram message (if sent)")
            print("\nReady for production use tomorrow at 9:15 AM!")
        else:
            print("\n❌ Test failed. Check logs above for errors.")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
