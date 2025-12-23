#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
OI Analyzer - Analyze Open Interest changes for F&O stocks

Compares current OI to day-start (market open) OI to show cumulative institutional positioning.

Classifies price+OI movements into 4 patterns:
1. Long Buildup (Price ↑ + OI ↑): Fresh buying, strong bullish momentum
2. Short Buildup (Price ↓ + OI ↑): Fresh selling, strong bearish momentum
3. Short Covering (Price ↑ + OI ↓): Weak rally, likely to reverse
4. Long Unwinding (Price ↓ + OI ↓): Weak fall, likely to reverse

Author: Sunil Kumar Durganaik
"""

from typing import Dict, Optional
from datetime import datetime
import json
import os


class OIAnalyzer:
    """Analyzes Open Interest patterns by comparing to day-start OI"""

    # OI change thresholds (in percentage)
    OI_SIGNIFICANT_CHANGE = 5.0   # 5% change - worth noting
    OI_STRONG_CHANGE = 10.0       # 10% change - strong signal
    OI_VERY_STRONG_CHANGE = 15.0  # 15% change - very strong signal

    # Price change thresholds (in percentage)
    PRICE_SMALL_CHANGE = 1.0      # 1% - small move
    PRICE_MODERATE_CHANGE = 2.0   # 2% - moderate move
    PRICE_LARGE_CHANGE = 3.0      # 3% - large move

    def __init__(self, cache_file: str = "data/oi_cache/oi_history.json"):
        """Initialize OI analyzer with day-start tracking"""
        self.cache_file = cache_file
        self.oi_history = self._load_oi_history()

        # Ensure cache directory exists
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)

    def _load_oi_history(self) -> Dict:
        """Load OI history from cache file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load OI history: {e}")
                return {}
        return {}

    def _save_oi_history(self):
        """Save OI history to cache file"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.oi_history, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save OI history: {e}")

    def _is_new_trading_day(self, last_timestamp: str) -> bool:
        """
        Check if we're in a new trading day compared to last update

        Args:
            last_timestamp: ISO timestamp of last update

        Returns:
            True if new trading day, False otherwise
        """
        try:
            last_dt = datetime.fromisoformat(last_timestamp)
            now = datetime.now()

            # Different date = new day
            if last_dt.date() != now.date():
                return True

            # Same date but before 9:15 AM (market open) = new day
            # This handles the case where we run before market opens
            if now.hour < 9 or (now.hour == 9 and now.minute < 15):
                return True

            return False
        except:
            return True  # If error, treat as new day

    def update_oi(self, symbol: str, current_oi: float, timestamp: str = None):
        """
        Update OI tracking for a symbol
        Sets day_start_oi on first update of the day

        Args:
            symbol: Stock symbol
            current_oi: Current open interest value
            timestamp: ISO format timestamp (default: now)
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        # Initialize symbol if first time
        if symbol not in self.oi_history:
            self.oi_history[symbol] = {
                'day_start_oi': current_oi,
                'day_start_timestamp': timestamp,
                'current_oi': current_oi,
                'last_updated': timestamp
            }
            self._save_oi_history()
            return

        symbol_data = self.oi_history[symbol]

        # Check if new trading day
        if self._is_new_trading_day(symbol_data['last_updated']):
            # Reset for new day
            symbol_data['day_start_oi'] = current_oi
            symbol_data['day_start_timestamp'] = timestamp

        # Update current values
        symbol_data['current_oi'] = current_oi
        symbol_data['last_updated'] = timestamp

        self._save_oi_history()

    def get_oi_change_from_day_start(self, symbol: str, current_oi: float) -> Optional[float]:
        """
        Calculate OI change percentage from day-start (market open)

        Args:
            symbol: Stock symbol
            current_oi: Current OI value

        Returns:
            OI change percentage from day start, or None if no day-start data
        """
        if symbol not in self.oi_history:
            return None

        day_start_oi = self.oi_history[symbol].get('day_start_oi', 0)

        if day_start_oi == 0:
            return None

        oi_change_pct = ((current_oi - day_start_oi) / day_start_oi) * 100
        return round(oi_change_pct, 2)

    def classify_oi_pattern(self, price_change_pct: float, oi_change_pct: float) -> Dict:
        """
        Classify price+OI movement into one of 4 patterns

        Args:
            price_change_pct: Price change percentage (positive = up, negative = down)
            oi_change_pct: OI change percentage (positive = increasing, negative = decreasing)

        Returns:
            Dict with pattern, signal, and interpretation
        """
        price_up = price_change_pct > 0
        oi_up = oi_change_pct > 0

        if price_up and oi_up:
            # Price UP + OI UP = Long Buildup
            return {
                'pattern': 'LONG_BUILDUP',
                'signal': 'BULLISH',
                'interpretation': 'Fresh buying - Strong bullish momentum',
                'confidence': 'HIGH' if abs(oi_change_pct) >= self.OI_STRONG_CHANGE else 'MEDIUM'
            }

        elif not price_up and oi_up:
            # Price DOWN + OI UP = Short Buildup
            return {
                'pattern': 'SHORT_BUILDUP',
                'signal': 'BEARISH',
                'interpretation': 'Fresh selling - Strong bearish momentum',
                'confidence': 'HIGH' if abs(oi_change_pct) >= self.OI_STRONG_CHANGE else 'MEDIUM'
            }

        elif price_up and not oi_up:
            # Price UP + OI DOWN = Short Covering
            return {
                'pattern': 'SHORT_COVERING',
                'signal': 'WEAK_BULLISH',
                'interpretation': 'Short covering - Weak rally, may reverse',
                'confidence': 'MEDIUM' if abs(oi_change_pct) >= self.OI_STRONG_CHANGE else 'LOW'
            }

        else:
            # Price DOWN + OI DOWN = Long Unwinding
            return {
                'pattern': 'LONG_UNWINDING',
                'signal': 'WEAK_BEARISH',
                'interpretation': 'Long unwinding - Weak fall, may reverse',
                'confidence': 'MEDIUM' if abs(oi_change_pct) >= self.OI_STRONG_CHANGE else 'LOW'
            }

    def calculate_strength(self, oi_change_pct: float) -> str:
        """
        Calculate OI change strength based on thresholds

        Args:
            oi_change_pct: OI change percentage

        Returns:
            Strength level: VERY_STRONG, STRONG, SIGNIFICANT, or MINIMAL
        """
        abs_change = abs(oi_change_pct)

        if abs_change >= self.OI_VERY_STRONG_CHANGE:
            return 'VERY_STRONG'
        elif abs_change >= self.OI_STRONG_CHANGE:
            return 'STRONG'
        elif abs_change >= self.OI_SIGNIFICANT_CHANGE:
            return 'SIGNIFICANT'
        else:
            return 'MINIMAL'

    def determine_priority(self, pattern_info: Dict, oi_strength: str, price_change_pct: float) -> str:
        """
        Determine alert priority based on pattern, OI strength, and price change

        Args:
            pattern_info: Pattern classification dict
            oi_strength: OI change strength
            price_change_pct: Price change percentage

        Returns:
            Priority level: HIGH, MEDIUM, or LOW
        """
        pattern = pattern_info['pattern']
        abs_price_change = abs(price_change_pct)

        # HIGH priority: Very strong OI change + moderate price move
        if oi_strength == 'VERY_STRONG' and abs_price_change >= self.PRICE_MODERATE_CHANGE:
            return 'HIGH'

        # HIGH priority: Long/Short buildup with strong OI
        if pattern in ['LONG_BUILDUP', 'SHORT_BUILDUP'] and oi_strength == 'STRONG':
            return 'HIGH'

        # MEDIUM priority: Strong or Very Strong OI change
        if oi_strength in ['STRONG', 'VERY_STRONG']:
            return 'MEDIUM'

        # MEDIUM priority: Buildup patterns with significant OI
        if oi_strength == 'SIGNIFICANT' and pattern in ['LONG_BUILDUP', 'SHORT_BUILDUP']:
            return 'MEDIUM'

        # LOW priority: Everything else
        return 'LOW'

    def analyze_oi_change(self, symbol: str, current_oi: float,
                         price_change_pct: float,
                         oi_day_high: float = 0,
                         oi_day_low: float = 0) -> Optional[Dict]:
        """
        Complete OI analysis for a symbol (comparing to day-start OI)

        Args:
            symbol: Stock symbol
            current_oi: Current open interest value
            price_change_pct: Price change percentage
            oi_day_high: OI day high (optional)
            oi_day_low: OI day low (optional)

        Returns:
            Dict with complete OI analysis, or None if insufficient data
            {
                'pattern': str,
                'signal': str,
                'interpretation': str,
                'oi_change_pct': float,
                'strength': str,
                'priority': str,
                'confidence': str,
                'at_day_high': bool,
                'at_day_low': bool,
                'current_oi': int
            }
        """
        # Update OI tracking
        self.update_oi(symbol, current_oi)

        # Get OI change from day start
        oi_change_pct = self.get_oi_change_from_day_start(symbol, current_oi)

        # If no day-start data yet (first snapshot), return None
        if oi_change_pct is None:
            return None

        # Classify pattern
        pattern_info = self.classify_oi_pattern(price_change_pct, oi_change_pct)

        # Calculate strength
        oi_strength = self.calculate_strength(oi_change_pct)

        # Determine priority
        priority = self.determine_priority(pattern_info, oi_strength, price_change_pct)

        # Check if at extremes (stricter threshold + significance filter)
        # Only mark as "at day high/low" if:
        # 1. Within 0.1% of the extreme (10x stricter than before)
        # 2. OI change from day start is significant (>= 5%)
        at_day_high = False
        at_day_low = False

        # Only show extremes if OI change is significant
        if abs(oi_change_pct) >= self.OI_SIGNIFICANT_CHANGE:
            if oi_day_high > 0:
                at_day_high = abs(current_oi - oi_day_high) / oi_day_high < 0.001  # Within 0.1%
            if oi_day_low > 0:
                at_day_low = abs(current_oi - oi_day_low) / oi_day_low < 0.001  # Within 0.1%

        return {
            'pattern': pattern_info['pattern'],
            'signal': pattern_info['signal'],
            'interpretation': pattern_info['interpretation'],
            'oi_change_pct': oi_change_pct,
            'strength': oi_strength,
            'priority': priority,
            'confidence': pattern_info['confidence'],
            'at_day_high': at_day_high,
            'at_day_low': at_day_low,
            'current_oi': current_oi
        }


# Singleton instance
_oi_analyzer = None

def get_oi_analyzer() -> OIAnalyzer:
    """Get singleton OI analyzer instance"""
    global _oi_analyzer
    if _oi_analyzer is None:
        _oi_analyzer = OIAnalyzer()
    return _oi_analyzer


if __name__ == "__main__":
    # Test the OI analyzer
    print("=" * 80)
    print("OI ANALYZER TEST - Day-Start Comparison")
    print("=" * 80)

    analyzer = get_oi_analyzer()

    # Simulate day-start OI for RELIANCE
    print("\n1. Day Start: RELIANCE OI = 1,000,000")
    analyzer.update_oi("RELIANCE", 1000000)

    # Simulate RELIANCE with long buildup (+15% OI from day start)
    print("\n2. Testing LONG BUILDUP (Price +2.5%, OI now 1,150,000 = +15%):")
    result = analyzer.analyze_oi_change("RELIANCE", 1150000, price_change_pct=2.5)
    if result:
        print(f"   Pattern: {result['pattern']}")
        print(f"   Signal: {result['signal']}")
        print(f"   OI Change from Day Start: {result['oi_change_pct']:+.2f}%")
        print(f"   Strength: {result['strength']}")
        print(f"   Priority: {result['priority']}")
        print(f"   Interpretation: {result['interpretation']}")

    # Simulate TCS day start
    print("\n3. Day Start: TCS OI = 800,000")
    analyzer.update_oi("TCS", 800000)

    # Simulate TCS with short buildup (+11.25% OI from day start)
    print("\n4. Testing SHORT BUILDUP (Price -2.0%, OI now 890,000 = +11.25%):")
    result = analyzer.analyze_oi_change("TCS", 890000, price_change_pct=-2.0)
    if result:
        print(f"   Pattern: {result['pattern']}")
        print(f"   Signal: {result['signal']}")
        print(f"   OI Change from Day Start: {result['oi_change_pct']:+.2f}%")
        print(f"   Strength: {result['strength']}")
        print(f"   Priority: {result['priority']}")
        print(f"   Interpretation: {result['interpretation']}")

    # Simulate INFY day start
    print("\n5. Day Start: INFY OI = 1,200,000")
    analyzer.update_oi("INFY", 1200000)

    # Simulate INFY with short covering (-10% OI from day start)
    print("\n6. Testing SHORT COVERING (Price +1.5%, OI now 1,080,000 = -10%):")
    result = analyzer.analyze_oi_change("INFY", 1080000, price_change_pct=1.5)
    if result:
        print(f"   Pattern: {result['pattern']}")
        print(f"   Signal: {result['signal']}")
        print(f"   OI Change from Day Start: {result['oi_change_pct']:+.2f}%")
        print(f"   Strength: {result['strength']}")
        print(f"   Priority: {result['priority']}")
        print(f"   Interpretation: {result['interpretation']}")

    print("\n" + "=" * 80)
    print("✅ OI Analyzer test completed!")
    print("=" * 80)
