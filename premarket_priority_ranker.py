#!/usr/bin/env python3
"""
Pre-Market Pattern Priority Ranker

Ranks detected patterns using a 5-factor scoring system to select the top 1-3
highest-quality setups from all daily and hourly patterns detected.

Priority Score Formula:
    priority_score = (
        0.40 × confidence_score/10        # 40% - Pattern quality
      + 0.25 × normalized_volume_ratio    # 25% - Volume conviction
      + 0.15 × freshness_score            # 15% - Pattern recency
      + 0.10 × timeframe_bonus            # 10% - Daily > Hourly
      + 0.10 × risk_reward_score          # 10% - Trade quality (R:R)
    )

Author: Sunil Kumar Durganaik
"""

from typing import List, Dict, Optional
import logging
import pattern_utils as pu

logger = logging.getLogger(__name__)


class PreMarketPriorityRanker:
    """
    Ranks patterns from multiple timeframes and stocks.
    Selects top 1-3 patterns for pre-market alerts.
    """

    def __init__(
        self,
        max_alerts: int = 3,
        min_priority_score: float = 7.0,
        min_confidence: float = 7.5,
        min_risk_reward: float = 1.5
    ):
        """
        Initialize priority ranker.

        Args:
            max_alerts: Maximum number of patterns to return (default: 3)
            min_priority_score: Minimum priority score (0-10, default: 7.0)
            min_confidence: Minimum confidence score (0-10, default: 7.5)
            min_risk_reward: Minimum R:R ratio (default: 1.5 = 1:1.5)
        """
        self.max_alerts = max_alerts
        self.min_priority_score = min_priority_score
        self.min_confidence = min_confidence
        self.min_risk_reward = min_risk_reward

    def rank_patterns(
        self,
        daily_results: Dict[str, Dict],
        hourly_results: Dict[str, Dict]
    ) -> List[Dict]:
        """
        Rank all detected patterns and return top N.

        Args:
            daily_results: Dict mapping symbols to daily pattern detection results
            hourly_results: Dict mapping symbols to hourly pattern detection results

        Returns:
            List of top N ranked patterns (max self.max_alerts)
            Each pattern dict includes: symbol, pattern_name, timeframe, priority_score, details
        """
        # Collect all patterns from both timeframes
        all_patterns = []

        # Extract daily patterns
        for symbol, result in daily_results.items():
            if result.get('has_patterns', False):
                patterns = self._extract_patterns(symbol, result, 'daily')
                all_patterns.extend(patterns)

        # Extract hourly patterns
        for symbol, result in hourly_results.items():
            if result.get('has_patterns', False):
                patterns = self._extract_patterns(symbol, result, 'hourly')
                all_patterns.extend(patterns)

        logger.info(f"Collected {len(all_patterns)} total patterns (daily + hourly)")

        # Filter by minimum criteria
        filtered_patterns = self._filter_patterns(all_patterns)
        logger.info(f"Filtered to {len(filtered_patterns)} patterns (min confidence: {self.min_confidence}, "
                   f"min R:R: {self.min_risk_reward})")

        # Calculate priority scores
        scored_patterns = self._calculate_priority_scores(filtered_patterns)

        # Sort by priority score (highest first)
        scored_patterns.sort(key=lambda x: x['priority_score'], reverse=True)

        # Return top N
        top_patterns = scored_patterns[:self.max_alerts]

        if top_patterns:
            logger.info(f"Top {len(top_patterns)} patterns selected:")
            for i, pattern in enumerate(top_patterns, 1):
                logger.info(f"  {i}. {pattern['symbol']} - {pattern['pattern_name']} "
                           f"({pattern['timeframe']}) - Priority: {pattern['priority_score']:.2f}/10")

        return top_patterns

    def _extract_patterns(self, symbol: str, result: Dict, timeframe: str) -> List[Dict]:
        """
        Extract individual patterns from detection result.

        Args:
            symbol: Stock symbol
            result: Pattern detection result dict
            timeframe: 'daily' or 'hourly'

        Returns:
            List of pattern dicts with metadata
        """
        patterns = []
        pattern_details = result.get('pattern_details', {})

        for pattern_key, details in pattern_details.items():
            # Calculate candles ago (freshness) - use 0 for now (most recent)
            # TODO: Extract actual pattern age from detection logic
            candles_ago = 0

            patterns.append({
                'symbol': symbol,
                'pattern_name': pattern_key.upper(),
                'timeframe': timeframe,
                'details': details,
                'candles_ago': candles_ago,
                'market_regime': result.get('market_regime', 'NEUTRAL')
            })

        return patterns

    def _filter_patterns(self, patterns: List[Dict]) -> List[Dict]:
        """
        Filter patterns by minimum criteria.

        Args:
            patterns: List of pattern dicts

        Returns:
            Filtered list
        """
        filtered = []

        for pattern in patterns:
            details = pattern['details']

            # Check confidence threshold
            confidence = details.get('confidence_score', 0)
            if confidence < self.min_confidence:
                logger.debug(f"{pattern['symbol']} {pattern['pattern_name']}: "
                            f"Confidence {confidence:.1f} < {self.min_confidence}")
                continue

            # Check R:R ratio
            entry = details.get('buy_price', 0)
            target = details.get('target_price', 0)
            stop = details.get('stop_loss', 0)

            if entry > 0 and target > 0 and stop > 0:
                rr_ratio = pu.calculate_risk_reward_ratio(entry, target, stop)
                if rr_ratio < self.min_risk_reward:
                    logger.debug(f"{pattern['symbol']} {pattern['pattern_name']}: "
                                f"R:R {rr_ratio:.1f} < {self.min_risk_reward}")
                    continue

            filtered.append(pattern)

        return filtered

    def _calculate_priority_scores(self, patterns: List[Dict]) -> List[Dict]:
        """
        Calculate priority score for each pattern using 5-factor formula.

        Args:
            patterns: List of pattern dicts

        Returns:
            Same list with 'priority_score' added to each pattern
        """
        for pattern in patterns:
            details = pattern['details']

            # Factor 1: Confidence Score (40% weight)
            confidence = details.get('confidence_score', 0)
            confidence_component = 0.40 * (confidence / 10)

            # Factor 2: Volume Ratio (25% weight)
            volume_ratio = details.get('volume_ratio', 1.0)
            normalized_volume = pu.normalize_volume_ratio(volume_ratio, min_threshold=1.5, max_threshold=5.0)
            volume_component = 0.25 * normalized_volume

            # Factor 3: Freshness (15% weight)
            candles_ago = pattern.get('candles_ago', 0)
            freshness = pu.calculate_freshness_score(candles_ago, max_age=5)
            freshness_component = 0.15 * freshness

            # Factor 4: Timeframe Bonus (10% weight)
            timeframe_bonus = pu.get_timeframe_bonus(pattern['timeframe'])
            timeframe_component = 0.10 * timeframe_bonus

            # Factor 5: Risk-Reward Ratio (10% weight)
            entry = details.get('buy_price', 0)
            target = details.get('target_price', 0)
            stop = details.get('stop_loss', 0)

            rr_ratio = pu.calculate_risk_reward_ratio(entry, target, stop) if entry > 0 else 0
            # Normalize R:R: 1:1.5 = 0, 1:3 = 0.5, 1:5+ = 1.0
            rr_normalized = min((rr_ratio - 1.5) / 3.5, 1.0) if rr_ratio >= 1.5 else 0
            rr_component = 0.10 * rr_normalized

            # Total priority score
            priority_score = (
                confidence_component +
                volume_component +
                freshness_component +
                timeframe_component +
                rr_component
            ) * 10  # Scale to 0-10

            pattern['priority_score'] = round(priority_score, 2)

            # Store components for debugging
            pattern['score_breakdown'] = {
                'confidence': round(confidence_component * 10, 2),
                'volume': round(volume_component * 10, 2),
                'freshness': round(freshness_component * 10, 2),
                'timeframe': round(timeframe_component * 10, 2),
                'risk_reward': round(rr_component * 10, 2)
            }

            logger.debug(f"{pattern['symbol']} {pattern['pattern_name']} ({pattern['timeframe']}): "
                        f"Priority={priority_score:.2f} "
                        f"[Conf:{confidence_component*10:.1f} Vol:{volume_component*10:.1f} "
                        f"Fresh:{freshness_component*10:.1f} TF:{timeframe_component*10:.1f} "
                        f"RR:{rr_component*10:.1f}]")

        return patterns


def main():
    """Test/demonstration of PreMarketPriorityRanker"""
    print("=" * 60)
    print("PRE-MARKET PRIORITY RANKER - TEST")
    print("=" * 60)

    # Mock detection results
    daily_results = {
        'RELIANCE': {
            'symbol': 'RELIANCE',
            'has_patterns': True,
            'market_regime': 'BULLISH',
            'patterns_found': ['DOUBLE_BOTTOM'],
            'pattern_details': {
                'double_bottom': {
                    'confidence_score': 8.5,
                    'buy_price': 2450.0,
                    'target_price': 2550.0,
                    'stop_loss': 2420.0,
                    'volume_ratio': 2.3,
                    'pattern_type': 'BULLISH'
                }
            }
        },
        'TCS': {
            'symbol': 'TCS',
            'has_patterns': True,
            'market_regime': 'BULLISH',
            'patterns_found': ['RESISTANCE_BREAKOUT'],
            'pattern_details': {
                'resistance_breakout': {
                    'confidence_score': 7.8,
                    'buy_price': 3500.0,
                    'target_price': 3600.0,
                    'stop_loss': 3470.0,
                    'volume_ratio': 1.9,
                    'pattern_type': 'BULLISH'
                }
            }
        }
    }

    hourly_results = {
        'INFY': {
            'symbol': 'INFY',
            'has_patterns': True,
            'market_regime': 'NEUTRAL',
            'patterns_found': ['DOUBLE_BOTTOM'],
            'pattern_details': {
                'double_bottom': {
                    'confidence_score': 8.2,
                    'buy_price': 1450.0,
                    'target_price': 1520.0,
                    'stop_loss': 1430.0,
                    'volume_ratio': 2.8,
                    'pattern_type': 'BULLISH',
                    'timeframe': 'hourly'
                }
            }
        }
    }

    # Test ranker
    ranker = PreMarketPriorityRanker(max_alerts=3, min_confidence=7.0, min_risk_reward=1.5)

    print("\n1. Ranking Patterns...")
    top_patterns = ranker.rank_patterns(daily_results, hourly_results)

    print(f"\n2. Top {len(top_patterns)} Patterns:")
    for i, pattern in enumerate(top_patterns, 1):
        details = pattern['details']
        print(f"\n   {i}. {pattern['symbol']} - {pattern['pattern_name']} ({pattern['timeframe'].upper()})")
        print(f"      Priority Score: {pattern['priority_score']:.2f}/10")
        print(f"      Confidence: {details.get('confidence_score', 0):.1f}/10")
        print(f"      Entry: ₹{details.get('buy_price', 0):.2f}")
        print(f"      Target: ₹{details.get('target_price', 0):.2f} "
              f"(+{((details.get('target_price', 0) - details.get('buy_price', 1)) / details.get('buy_price', 1) * 100):.1f}%)")
        print(f"      Stop: ₹{details.get('stop_loss', 0):.2f} "
              f"(-{((details.get('buy_price', 1) - details.get('stop_loss', 0)) / details.get('buy_price', 1) * 100):.1f}%)")
        print(f"      Volume: {details.get('volume_ratio', 0):.1f}x")

        # Show score breakdown
        breakdown = pattern.get('score_breakdown', {})
        print(f"      Score Breakdown:")
        print(f"        Confidence: {breakdown.get('confidence', 0):.1f}/4.0")
        print(f"        Volume: {breakdown.get('volume', 0):.1f}/2.5")
        print(f"        Freshness: {breakdown.get('freshness', 0):.1f}/1.5")
        print(f"        Timeframe: {breakdown.get('timeframe', 0):.1f}/1.0")
        print(f"        Risk-Reward: {breakdown.get('risk_reward', 0):.1f}/1.0")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
