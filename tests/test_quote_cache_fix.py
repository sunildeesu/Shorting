#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Test the fixed UnifiedQuoteCache with datetime serialization
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unified_quote_cache import UnifiedQuoteCache
from kiteconnect import KiteConnect
import config

def test_quote_cache():
    """Test quote cache with datetime serialization fix"""
    print("="*80)
    print("TESTING UNIFIED QUOTE CACHE FIX")
    print("="*80)

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Test with a few stocks
    test_stocks = ['RELIANCE', 'TCS', 'INFY']

    # Initialize cache
    cache = UnifiedQuoteCache(cache_file="data/unified_cache/test_quote_cache.json", ttl_seconds=60)

    print(f"\n1. Fetching quotes for {len(test_stocks)} stocks...")
    try:
        quotes = cache.get_or_fetch_quotes(test_stocks, kite)
        print(f"   ✓ Successfully fetched {len(quotes)} quotes")

        # Show sample quote
        if quotes:
            sample_key = list(quotes.keys())[0]
            sample_quote = quotes[sample_key]
            print(f"\n2. Sample quote for {sample_key}:")
            print(f"   Last Price: ₹{sample_quote['last_price']}")
            print(f"   Volume: {sample_quote['volume']:,}")

        print("\n3. Testing cache save/load...")
        # The cache should have been saved automatically
        stats = cache.get_cache_stats()
        print(f"   Cache status: {stats['status']}")
        print(f"   Stocks cached: {stats['stocks_cached']}")
        print(f"   Age: {stats['age_seconds']:.1f}s")

        print("\n✅ SUCCESS - Quote cache working correctly with datetime serialization!")

    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "="*80)
    return True


if __name__ == "__main__":
    success = test_quote_cache()
    sys.exit(0 if success else 1)
