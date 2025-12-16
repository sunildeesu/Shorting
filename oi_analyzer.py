#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
OI Analyzer - Analyze Open Interest changes for F&O stocks

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
    """Analyzes Open Interest patterns to identify strong vs weak price moves"""

    # OI change thresholds (in percentage)
    OI_SIGNIFICANT_CHANGE = 5.0   # 5% change - worth noting
    OI_STRONG_CHANGE = 10.0       # 10% change - strong signal
    OI_VERY_STRONG_CHANGE = 15.0  # 15% change - very strong signal

    # Price change thresholds (in percentage)
    PRICE_SMALL_CHANGE = 1.0      # 1% - small move
    PRICE_MODERATE_CHANGE = 2.0   # 2% - moderate move
    PRICE_LARGE_CHANGE = 3.0      # 3% - large move

    def __init__(self, cache_file: str = "data/oi_cache/oi_history.json"):
        """Initialize OI analyzer with history cache"""
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

    def update_oi(self, symbol: str, current_oi: float, timestamp: str = None):
        """
        Update OI history for a symbol

        Args:
            symbol: Stock symbol
            current_oi: Current open interest value
            timestamp: ISO format timestamp (default: now)
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        if symbol not in self.oi_history:
            self.oi_history[symbol] = []

        # Add new OI snapshot
        self.oi_history[symbol].append({
            'oi': current_oi,
            'timestamp': timestamp
        })

        # Keep only last 50 snapshots per symbol (memory management)
        if len(self.oi_history[symbol]) > 50:
            self.oi_history[symbol] = self.oi_history[symbol][-50:]

        # Save periodically (every update for now, can optimize later)
        self._save_oi_history()

    def get_oi_change_pct(self, symbol: str, current_oi: float) -> Optional[float]:
        """
        Calculate OI change percentage from previous snapshot

        Args:
            symbol: Stock symbol
            current_oi: Current OI value

        Returns:
            OI change percentage, or None if no history
        """
        if symbol not in self.oi_history or len(self.oi_history[symbol]) == 0:
            return None

        # Get previous OI (most recent snapshot)
        previous_oi = self.oi_history[symbol][-1]['oi']

        if previous_oi == 0:
            return None

        oi_change_pct = ((current_oi - previous_oi) / previous_oi) * 100
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
        Calculate strength of OI change

        Args:
            oi_change_pct: OI change percentage

        Returns:
            'VERY_STRONG', 'STRONG', 'SIGNIFICANT', or 'MINIMAL'
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

    def determine_priority(self, pattern_info: Dict, oi_strength: str,
                          price_change_pct: float) -> str:
        """
        Determine alert priority based on pattern, OI strength, and price change

        Args:
            pattern_info: Pattern classification from classify_oi_pattern()
            oi_strength: Strength from calculate_strength()
            price_change_pct: Price change percentage

        Returns:
            'HIGH', 'MEDIUM', or 'LOW'
        """
        # HIGH priority: Very strong OI change with strong price move
        if oi_strength == 'VERY_STRONG' and abs(price_change_pct) >= self.PRICE_MODERATE_CHANGE:
            return 'HIGH'

        # HIGH priority: Strong buildup patterns (LONG_BUILDUP or SHORT_BUILDUP)
        # with at least strong OI change
        if pattern_info['pattern'] in ['LONG_BUILDUP', 'SHORT_BUILDUP']:
            if oi_strength in ['STRONG', 'VERY_STRONG']:
                return 'HIGH'

        # MEDIUM priority: Strong OI change with any pattern
        if oi_strength in ['STRONG', 'VERY_STRONG']:
            return 'MEDIUM'

        # MEDIUM priority: Significant OI change with buildup patterns
        if oi_strength == 'SIGNIFICANT' and pattern_info['pattern'] in ['LONG_BUILDUP', 'SHORT_BUILDUP']:
            return 'MEDIUM'

        # LOW priority: Everything else
        return 'LOW'

    def analyze_oi_change(self, symbol: str, current_oi: float,
                         price_change_pct: float,
                         oi_day_high: float = 0,
                         oi_day_low: float = 0) -> Optional[Dict]:
        """
        Complete OI analysis for a symbol

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
                'at_day_low': bool
            }
        """
        # Get OI change percentage
        oi_change_pct = self.get_oi_change_pct(symbol, current_oi)

        # Update history with current OI
        self.update_oi(symbol, current_oi)

        # If no previous data, return None (need at least 2 snapshots)
        if oi_change_pct is None:
            return None

        # Skip analysis if OI change is too small (< 1%)
        if abs(oi_change_pct) < 1.0:
            return None

        # Classify pattern
        pattern_info = self.classify_oi_pattern(price_change_pct, oi_change_pct)

        # Calculate strength
        oi_strength = self.calculate_strength(oi_change_pct)

        # Determine priority
        priority = self.determine_priority(pattern_info, oi_strength, price_change_pct)

        # Check if at extremes
        at_day_high = False
        at_day_low = False
        if oi_day_high > 0:
            at_day_high = abs(current_oi - oi_day_high) / oi_day_high < 0.01  # Within 1%
        if oi_day_low > 0:
            at_day_low = abs(current_oi - oi_day_low) / oi_day_low < 0.01  # Within 1%

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

    def get_recent_oi_trend(self, symbol: str, periods: int = 5) -> Optional[Dict]:
        """
        Analyze OI trend over last N periods

        Args:
            symbol: Stock symbol
            periods: Number of periods to analyze (default: 5)

        Returns:
            Dict with trend analysis or None
        """
        if symbol not in self.oi_history or len(self.oi_history[symbol]) < 2:
            return None

        history = self.oi_history[symbol][-periods:]

        if len(history) < 2:
            return None

        # Calculate overall change
        first_oi = history[0]['oi']
        last_oi = history[-1]['oi']

        if first_oi == 0:
            return None

        overall_change_pct = ((last_oi - first_oi) / first_oi) * 100

        # Count increasing periods
        increasing_count = 0
        for i in range(1, len(history)):
            if history[i]['oi'] > history[i-1]['oi']:
                increasing_count += 1

        trend_direction = 'INCREASING' if overall_change_pct > 0 else 'DECREASING'
        trend_consistency = (increasing_count / (len(history) - 1)) * 100

        return {
            'trend_direction': trend_direction,
            'overall_change_pct': round(overall_change_pct, 2),
            'consistency_pct': round(trend_consistency, 2),
            'periods_analyzed': len(history)
        }

    def clear_old_history(self, days_to_keep: int = 1):
        """
        Clear OI history older than specified days

        Args:
            days_to_keep: Number of days to keep (default: 1)
        """
        from datetime import timedelta

        cutoff_time = datetime.now() - timedelta(days=days_to_keep)

        for symbol in list(self.oi_history.keys()):
            # Filter snapshots to keep only recent ones
            self.oi_history[symbol] = [
                snapshot for snapshot in self.oi_history[symbol]
                if datetime.fromisoformat(snapshot['timestamp']) >= cutoff_time
            ]

            # Remove symbol if no snapshots left
            if len(self.oi_history[symbol]) == 0:
                del self.oi_history[symbol]

        self._save_oi_history()


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
    print("OI ANALYZER TEST")
    print("=" * 80)

    analyzer = get_oi_analyzer()

    # Simulate RELIANCE with long buildup
    print("\n1. Testing LONG BUILDUP (Price UP + OI UP):")
    analyzer.update_oi("RELIANCE", 1000000)
    result = analyzer.analyze_oi_change("RELIANCE", 1150000, price_change_pct=2.5)
    if result:
        print(f"   Pattern: {result['pattern']}")
        print(f"   Signal: {result['signal']}")
        print(f"   OI Change: {result['oi_change_pct']:.2f}%")
        print(f"   Strength: {result['strength']}")
        print(f"   Priority: {result['priority']}")
        print(f"   Interpretation: {result['interpretation']}")

    # Simulate TCS with short buildup
    print("\n2. Testing SHORT BUILDUP (Price DOWN + OI UP):")
    analyzer.update_oi("TCS", 800000)
    result = analyzer.analyze_oi_change("TCS", 890000, price_change_pct=-2.0)
    if result:
        print(f"   Pattern: {result['pattern']}")
        print(f"   Signal: {result['signal']}")
        print(f"   OI Change: {result['oi_change_pct']:.2f}%")
        print(f"   Strength: {result['strength']}")
        print(f"   Priority: {result['priority']}")
        print(f"   Interpretation: {result['interpretation']}")

    # Simulate INFY with short covering
    print("\n3. Testing SHORT COVERING (Price UP + OI DOWN):")
    analyzer.update_oi("INFY", 1200000)
    result = analyzer.analyze_oi_change("INFY", 1080000, price_change_pct=1.5)
    if result:
        print(f"   Pattern: {result['pattern']}")
        print(f"   Signal: {result['signal']}")
        print(f"   OI Change: {result['oi_change_pct']:.2f}%")
        print(f"   Strength: {result['strength']}")
        print(f"   Priority: {result['priority']}")
        print(f"   Interpretation: {result['interpretation']}")

    # Test trend analysis
    print("\n4. Testing OI Trend Analysis:")
    # Add more snapshots for RELIANCE
    for i in range(5):
        analyzer.update_oi("RELIANCE", 1150000 + (i * 20000))

    trend = analyzer.get_recent_oi_trend("RELIANCE", periods=5)
    if trend:
        print(f"   Trend Direction: {trend['trend_direction']}")
        print(f"   Overall Change: {trend['overall_change_pct']:.2f}%")
        print(f"   Consistency: {trend['consistency_pct']:.1f}%")

    print("\n" + "=" * 80)
    print("✅ OI Analyzer test completed!")
    print("=" * 80)
