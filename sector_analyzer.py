"""
Sector Analyzer - Calculate sector-level metrics from existing price cache data
Uses ZERO additional Kite API calls - reads from price_cache.json
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from sector_manager import get_sector_manager
import config

logger = logging.getLogger(__name__)

class SectorAnalyzer:
    """Analyzes sector performance using cached stock data"""

    def __init__(self):
        """Initialize sector analyzer"""
        self.sector_manager = get_sector_manager()
        self.price_cache_file = config.PRICE_CACHE_FILE
        self.shares_outstanding_file = "data/shares_outstanding.json"
        self.sector_cache_file = "data/sector_analysis_cache.json"
        self.sector_snapshot_dir = "data/sector_snapshots"

        # Load shares outstanding data
        self.shares_outstanding = self._load_shares_outstanding()

        # Ensure snapshot directory exists
        os.makedirs(self.sector_snapshot_dir, exist_ok=True)

    def _load_shares_outstanding(self) -> Dict[str, int]:
        """Load shares outstanding data for market cap calculation"""
        try:
            if not os.path.exists(self.shares_outstanding_file):
                logger.warning(f"Shares outstanding file not found: {self.shares_outstanding_file}")
                return {}

            with open(self.shares_outstanding_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading shares outstanding: {e}")
            return {}

    def _load_price_cache(self) -> Dict:
        """Load price cache data (READONLY - no API calls)"""
        try:
            if not os.path.exists(self.price_cache_file):
                logger.warning(f"Price cache file not found: {self.price_cache_file}")
                return {}

            with open(self.price_cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading price cache: {e}")
            return {}

    def calculate_market_cap(self, symbol: str, price: float) -> float:
        """
        Calculate market cap in crores

        Args:
            symbol: Stock symbol
            price: Current price

        Returns:
            Market cap in crores, or 0 if shares data not available
        """
        shares = self.shares_outstanding.get(symbol, 0)
        if shares == 0:
            return 0
        return (shares * price) / 10000000  # Convert to crores

    def analyze_sectors(self) -> Dict:
        """
        Analyze all sectors using cached price data

        Returns:
            Dict with sector metrics
        """
        try:
            # Load price cache (READONLY)
            price_cache = self._load_price_cache()

            if not price_cache:
                logger.warning("Price cache is empty, cannot analyze sectors")
                return {}

            # Initialize sector aggregates
            sector_data = defaultdict(lambda: {
                'stocks': [],
                'total_market_cap': 0,
                'weighted_price_change_5min': 0,
                'weighted_price_change_10min': 0,
                'weighted_price_change_30min': 0,
                'total_volume_current': 0,
                'total_volume_avg': 0,
                'stocks_up_5min': 0,
                'stocks_down_5min': 0,
                'stocks_up_10min': 0,
                'stocks_down_10min': 0,
                'stocks_up_30min': 0,
                'stocks_down_30min': 0,
                'market_cap_weights': []
            })

            # Process each stock
            for symbol, snapshots in price_cache.items():
                # Get sector for this stock
                sector = self.sector_manager.get_sector(symbol)
                if not sector:
                    continue  # Skip if sector not mapped

                # Get current snapshot
                current = snapshots.get('current')
                if not current:
                    continue

                current_price = current.get('price', 0)
                current_volume = current.get('volume', 0)

                if current_price == 0:
                    continue

                # Calculate market cap
                market_cap = self.calculate_market_cap(symbol, current_price)

                # Get previous snapshots for price changes
                prev = snapshots.get('previous')  # 5 min ago
                prev2 = snapshots.get('previous2')  # 10 min ago
                prev6 = snapshots.get('previous6')  # 30 min ago

                # Calculate price changes
                price_change_5min = 0
                price_change_10min = 0
                price_change_30min = 0

                if prev and prev.get('price'):
                    price_change_5min = ((current_price - prev['price']) / prev['price']) * 100

                if prev2 and prev2.get('price'):
                    price_change_10min = ((current_price - prev2['price']) / prev2['price']) * 100

                if prev6 and prev6.get('price'):
                    price_change_30min = ((current_price - prev6['price']) / prev6['price']) * 100

                # Calculate average volume from previous snapshots
                volumes = []
                for key in ['previous', 'previous2', 'previous3', 'previous4', 'previous5', 'previous6']:
                    snap = snapshots.get(key)
                    if snap and snap.get('volume'):
                        volumes.append(snap['volume'])

                avg_volume = sum(volumes) / len(volumes) if volumes else 0

                # Aggregate into sector
                sector_data[sector]['stocks'].append(symbol)
                sector_data[sector]['total_market_cap'] += market_cap
                sector_data[sector]['total_volume_current'] += current_volume
                sector_data[sector]['total_volume_avg'] += avg_volume

                # Market-cap weighted price changes
                if market_cap > 0:
                    sector_data[sector]['weighted_price_change_5min'] += price_change_5min * market_cap
                    sector_data[sector]['weighted_price_change_10min'] += price_change_10min * market_cap
                    sector_data[sector]['weighted_price_change_30min'] += price_change_30min * market_cap
                    sector_data[sector]['market_cap_weights'].append(market_cap)

                # Count stocks up/down
                if price_change_5min > 0:
                    sector_data[sector]['stocks_up_5min'] += 1
                elif price_change_5min < 0:
                    sector_data[sector]['stocks_down_5min'] += 1

                if price_change_10min > 0:
                    sector_data[sector]['stocks_up_10min'] += 1
                elif price_change_10min < 0:
                    sector_data[sector]['stocks_down_10min'] += 1

                if price_change_30min > 0:
                    sector_data[sector]['stocks_up_30min'] += 1
                elif price_change_30min < 0:
                    sector_data[sector]['stocks_down_30min'] += 1

            # Calculate final sector metrics
            result = {
                'timestamp': datetime.now().isoformat(),
                'sectors': {}
            }

            for sector, data in sector_data.items():
                if data['total_market_cap'] == 0:
                    continue  # Skip if no market cap data

                # Calculate market-cap weighted averages
                mc_weighted_5min = data['weighted_price_change_5min'] / data['total_market_cap']
                mc_weighted_10min = data['weighted_price_change_10min'] / data['total_market_cap']
                mc_weighted_30min = data['weighted_price_change_30min'] / data['total_market_cap']

                # Calculate volume ratio
                volume_ratio = (data['total_volume_current'] / data['total_volume_avg']) if data['total_volume_avg'] > 0 else 1.0

                # Calculate participation percentage
                total_stocks = len(data['stocks'])
                participation_5min = ((data['stocks_up_5min'] + data['stocks_down_5min']) / total_stocks * 100) if total_stocks > 0 else 0

                # Calculate momentum score
                # Formula: (Price Change × Volume Ratio × Participation%)
                momentum_5min = mc_weighted_5min * volume_ratio * (participation_5min / 100)
                momentum_10min = mc_weighted_10min * volume_ratio * (participation_5min / 100)
                momentum_30min = mc_weighted_30min * volume_ratio * (participation_5min / 100)

                result['sectors'][sector] = {
                    'price_change_5min': round(mc_weighted_5min, 2),
                    'price_change_10min': round(mc_weighted_10min, 2),
                    'price_change_30min': round(mc_weighted_30min, 2),
                    'volume_ratio': round(volume_ratio, 2),
                    'momentum_score_5min': round(momentum_5min, 2),
                    'momentum_score_10min': round(momentum_10min, 2),
                    'momentum_score_30min': round(momentum_30min, 2),
                    'stocks_up_5min': data['stocks_up_5min'],
                    'stocks_down_5min': data['stocks_down_5min'],
                    'stocks_up_10min': data['stocks_up_10min'],
                    'stocks_down_10min': data['stocks_down_10min'],
                    'stocks_up_30min': data['stocks_up_30min'],
                    'stocks_down_30min': data['stocks_down_30min'],
                    'total_stocks': total_stocks,
                    'participation_pct': round(participation_5min, 1),
                    'total_market_cap_cr': round(data['total_market_cap'], 2),
                    'total_volume': data['total_volume_current']
                }

            logger.info(f"Analyzed {len(result['sectors'])} sectors")
            return result

        except Exception as e:
            logger.error(f"Error analyzing sectors: {e}", exc_info=True)
            return {}

    def detect_rotation(self, current_analysis: Dict, threshold: float = 2.0) -> Optional[Dict]:
        """
        Detect sector rotation (money flowing between sectors)

        Args:
            current_analysis: Current sector analysis
            threshold: Minimum % differential to trigger rotation alert

        Returns:
            Rotation data if detected, None otherwise
        """
        try:
            sectors = current_analysis.get('sectors', {})
            if not sectors:
                return None

            # Sort sectors by 10-min momentum score
            sorted_sectors = sorted(
                sectors.items(),
                key=lambda x: x[1]['momentum_score_10min'],
                reverse=True
            )

            if len(sorted_sectors) < 2:
                return None

            # Top 3 gainers and losers
            top_gainers = sorted_sectors[:3]
            top_losers = sorted_sectors[-3:]

            # Check if there's significant divergence
            max_gainer_score = top_gainers[0][1]['momentum_score_10min']
            max_loser_score = top_losers[0][1]['momentum_score_10min']

            divergence = max_gainer_score - max_loser_score

            if abs(divergence) < threshold:
                return None  # Not significant enough

            return {
                'timestamp': current_analysis.get('timestamp'),
                'divergence': round(divergence, 2),
                'top_gainers': [
                    {
                        'sector': sector,
                        'price_change': data['price_change_10min'],
                        'momentum': data['momentum_score_10min'],
                        'volume_ratio': data['volume_ratio']
                    }
                    for sector, data in top_gainers
                ],
                'top_losers': [
                    {
                        'sector': sector,
                        'price_change': data['price_change_10min'],
                        'momentum': data['momentum_score_10min'],
                        'volume_ratio': data['volume_ratio']
                    }
                    for sector, data in top_losers
                ]
            }

        except Exception as e:
            logger.error(f"Error detecting rotation: {e}")
            return None

    def save_analysis_cache(self, analysis: Dict):
        """Save sector analysis to cache file"""
        try:
            os.makedirs(os.path.dirname(self.sector_cache_file), exist_ok=True)
            with open(self.sector_cache_file, 'w') as f:
                json.dump(analysis, f, indent=2)
            logger.debug("Saved sector analysis to cache")
        except Exception as e:
            logger.error(f"Error saving sector analysis cache: {e}")

    def save_snapshot(self, analysis: Dict, snapshot_time: str):
        """
        Save sector snapshot for specific time

        Args:
            analysis: Sector analysis data
            snapshot_time: Time label (e.g., "09:30", "12:30", "15:15")
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            snapshot_file = os.path.join(self.sector_snapshot_dir, f"{today}.json")

            # Load existing snapshots for today
            snapshots = {}
            if os.path.exists(snapshot_file):
                with open(snapshot_file, 'r') as f:
                    snapshots = json.load(f)

            # Add new snapshot
            snapshots[snapshot_time] = analysis

            # Save updated snapshots
            with open(snapshot_file, 'w') as f:
                json.dump(snapshots, f, indent=2)

            logger.info(f"Saved sector snapshot for {snapshot_time}")

        except Exception as e:
            logger.error(f"Error saving sector snapshot: {e}")

    def analyze_and_cache(self, save_snapshot_at: Optional[str] = None) -> Dict:
        """
        Main method: Analyze sectors and save to cache

        Args:
            save_snapshot_at: If provided (e.g., "09:30"), save as daily snapshot

        Returns:
            Sector analysis data
        """
        # Analyze sectors
        analysis = self.analyze_sectors()

        if analysis:
            # Save to cache
            self.save_analysis_cache(analysis)

            # Save snapshot if requested
            if save_snapshot_at:
                self.save_snapshot(analysis, save_snapshot_at)

        return analysis

# Global singleton instance
_sector_analyzer_instance: Optional[SectorAnalyzer] = None

def get_sector_analyzer() -> SectorAnalyzer:
    """
    Get singleton instance of SectorAnalyzer

    Returns:
        SectorAnalyzer instance
    """
    global _sector_analyzer_instance
    if _sector_analyzer_instance is None:
        _sector_analyzer_instance = SectorAnalyzer()
    return _sector_analyzer_instance
