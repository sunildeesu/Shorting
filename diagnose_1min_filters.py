#!/usr/bin/env python3
"""
Diagnostic script to analyze why 1-min alerts aren't triggering
Analyzes recent price data and shows what's being filtered at each layer
"""

import sys
import logging
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
import config
from price_cache import PriceCache
from alert_history_manager import AlertHistoryManager
from onemin_alert_detector import OneMinAlertDetector

# Enable DEBUG logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Run diagnostic analysis"""
    print("=" * 80)
    print("1-MINUTE ALERT FILTER DIAGNOSTIC")
    print("=" * 80)
    print()

    # Show current thresholds
    print("Current Configuration:")
    print(f"  Price threshold: {config.DROP_THRESHOLD_1MIN}% / {config.RISE_THRESHOLD_1MIN}%")
    print(f"  Volume multiplier: {config.VOLUME_SPIKE_MULTIPLIER_1MIN}x average")
    print(f"  Minimum volume: {config.MIN_VOLUME_1MIN:,} shares")
    print(f"  Cooldown: {config.COOLDOWN_1MIN_ALERTS} minutes")
    print()

    # Initialize Kite
    print("Initializing Kite Connect...")
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Initialize components
    price_cache = PriceCache()
    alert_history = AlertHistoryManager()
    detector = OneMinAlertDetector(price_cache, alert_history)

    # Get sample stocks
    with open('data/fo_stocks.json', 'r') as f:
        stocks_data = json.load(f)

    symbols = [stock['symbol'] for stock in stocks_data if stock.get('avg_daily_volume', 0) >= 500000][:20]

    print(f"Testing {len(symbols)} liquid stocks...")
    print()

    # Fetch current prices
    instruments = [f"NSE:{s}" for s in symbols]
    quotes = kite.quote(instruments)

    # Statistics
    stats = {
        'total_checked': 0,
        'failed_price_threshold': 0,
        'failed_volume_spike': 0,
        'failed_quality': 0,
        'failed_cooldown': 0,
        'failed_cross_alert': 0,
        'passed_normal': 0,
        'passed_high': 0,
        'price_changes': [],
        'volume_ratios': []
    }

    print("Analyzing stocks...")
    print("-" * 80)

    for symbol in symbols:
        instrument = f"NSE:{symbol}"
        if instrument not in quotes:
            continue

        quote = quotes[instrument]
        current_price = quote['last_price']
        current_volume = quote['volume']

        # Get historical price (simulate 1-min ago)
        price_1min_ago = quote.get('ohlc', {}).get('open', current_price)

        # Calculate change
        if price_1min_ago > 0:
            change_pct = ((current_price - price_1min_ago) / price_1min_ago) * 100
        else:
            change_pct = 0

        stats['total_checked'] += 1
        stats['price_changes'].append(abs(change_pct))

        # Update cache
        price_cache.update_price(symbol, current_price, current_volume, 0)

        # Get volume data
        volume_data = price_cache.get_volume_data_1min(symbol)
        avg_volume = volume_data.get('avg_volume', 0)

        if avg_volume > 0:
            volume_ratio = current_volume / avg_volume
            stats['volume_ratios'].append(volume_ratio)
        else:
            volume_ratio = 0

        # Test filters
        failed_at = None

        # Layer 1: Price threshold
        if abs(change_pct) < config.DROP_THRESHOLD_1MIN:
            failed_at = 'PRICE_THRESHOLD'
            stats['failed_price_threshold'] += 1

        # Layer 2: Volume spike
        elif not (current_volume >= config.VOLUME_SPIKE_MULTIPLIER_1MIN * avg_volume and
                  current_volume >= config.MIN_VOLUME_1MIN):
            failed_at = 'VOLUME_SPIKE'
            stats['failed_volume_spike'] += 1

        # Layer 3: Quality
        elif current_price < 50:
            failed_at = 'QUALITY'
            stats['failed_quality'] += 1

        else:
            stats['passed_normal'] += 1
            failed_at = 'PASSED'

        # Show details for interesting stocks
        if abs(change_pct) > 0.5 or failed_at == 'PASSED':
            print(f"{symbol:15s} | Price: ₹{current_price:8.2f} | Change: {change_pct:+6.2f}% | "
                  f"Vol: {current_volume:,} (avg: {avg_volume:,}, ratio: {volume_ratio:.1f}x) | "
                  f"Status: {failed_at}")

    print("-" * 80)
    print()

    # Summary statistics
    print("DIAGNOSTIC SUMMARY:")
    print("=" * 80)
    print(f"Total stocks checked: {stats['total_checked']}")
    print()

    print("Filtering Results:")
    print(f"  ❌ Failed Layer 1 (Price Threshold): {stats['failed_price_threshold']} "
          f"({stats['failed_price_threshold']/stats['total_checked']*100:.1f}%)")
    print(f"  ❌ Failed Layer 2 (Volume Spike): {stats['failed_volume_spike']} "
          f"({stats['failed_volume_spike']/stats['total_checked']*100:.1f}%)")
    print(f"  ❌ Failed Layer 3 (Quality): {stats['failed_quality']} "
          f"({stats['failed_quality']/stats['total_checked']*100:.1f}%)")
    print(f"  ✅ Passed All Layers: {stats['passed_normal']} "
          f"({stats['passed_normal']/stats['total_checked']*100:.1f}%)")
    print()

    # Price change statistics
    if stats['price_changes']:
        avg_change = sum(stats['price_changes']) / len(stats['price_changes'])
        max_change = max(stats['price_changes'])
        print(f"Price Changes:")
        print(f"  Average: {avg_change:.3f}%")
        print(f"  Maximum: {max_change:.3f}%")
        print(f"  Threshold: {config.DROP_THRESHOLD_1MIN}%")
        print(f"  → {sum(1 for c in stats['price_changes'] if c >= config.DROP_THRESHOLD_1MIN)} stocks met threshold")
    print()

    # Volume statistics
    if stats['volume_ratios']:
        avg_ratio = sum(stats['volume_ratios']) / len(stats['volume_ratios'])
        max_ratio = max(stats['volume_ratios'])
        print(f"Volume Ratios:")
        print(f"  Average: {avg_ratio:.2f}x")
        print(f"  Maximum: {max_ratio:.2f}x")
        print(f"  Required: {config.VOLUME_SPIKE_MULTIPLIER_1MIN}x")
        print(f"  → {sum(1 for r in stats['volume_ratios'] if r >= config.VOLUME_SPIKE_MULTIPLIER_1MIN)} stocks met threshold")
    print()

    # Recommendations
    print("=" * 80)
    print("RECOMMENDATIONS:")
    print("=" * 80)

    if stats['failed_price_threshold'] > stats['total_checked'] * 0.8:
        print("⚠️  80%+ stocks failing PRICE THRESHOLD")
        print(f"   Current: {config.DROP_THRESHOLD_1MIN}%")
        print(f"   Suggested: Reduce to 0.5% or 0.6% for more alerts")
        print()

    if stats['failed_volume_spike'] > stats['total_checked'] * 0.5:
        print("⚠️  50%+ stocks failing VOLUME SPIKE")
        print(f"   Current: {config.VOLUME_SPIKE_MULTIPLIER_1MIN}x average")
        print(f"   Suggested: Reduce to 2.0x or 2.5x for more alerts")
        print()

    if stats['passed_normal'] == 0:
        print("🚨 CRITICAL: ZERO stocks passing all filters!")
        print("   This explains why you're getting no alerts.")
        print()
        print("   Quick Fix Options:")
        print("   1. Reduce DROP_THRESHOLD_1MIN from 0.75% to 0.5%")
        print("   2. Reduce VOLUME_SPIKE_MULTIPLIER_1MIN from 3.0x to 2.0x")
        print("   3. Reduce MIN_VOLUME_1MIN from 50,000 to 30,000")
        print()

    print("=" * 80)

if __name__ == "__main__":
    import json
    main()
