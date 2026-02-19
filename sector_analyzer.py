"""
Sector Analyzer - Calculate sector-level metrics from central quote database
MIGRATED: Now reads from central_quotes.db instead of price_cache.json
Uses ZERO Kite API calls - data is pre-populated by central_data_collector
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from sector_manager import get_sector_manager
from central_quote_db import get_central_db
from service_health import get_health_tracker
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

        # Initialize Central Quote Database (MIGRATED - Tier 3)
        self.central_db = get_central_db()
        logger.info("Sector Analyzer using Central Quote Database")

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
        """
        Load price data from Central Quote Database (MIGRATED).
        Builds the same structure as the old price_cache.json for compatibility.

        Returns:
            Dict with structure: {symbol: {current, previous, previous2, ...}}
        """
        health = get_health_tracker()

        try:
            # First try Central Quote Database with freshness check
            if self.central_db:
                is_fresh, age_minutes = self.central_db.is_data_fresh(max_age_minutes=2)

                if age_minutes is None:
                    logger.warning("[sector_analyzer] No data in Central DB, falling back to price_cache.json")
                    health.report_error("sector_analyzer", "central_db_empty",
                                       "No data in central database", severity="warning")
                    health.report_metric("sector_analyzer", "data_source", "json_file")
                elif not is_fresh:
                    logger.warning(f"[sector_analyzer] Central DB data is STALE ({age_minutes} min old)")
                    health.report_error("sector_analyzer", "central_db_stale",
                                       f"Data is {age_minutes} minutes old", severity="warning")
                    health.report_metric("sector_analyzer", "data_source", "json_file")
                else:
                    # Data is fresh - use Central DB
                    price_cache = self._load_from_central_db()
                    if price_cache:
                        logger.info(f"[sector_analyzer] Loaded {len(price_cache)} stocks from Central DB (data {age_minutes} min old)")
                        health.report_metric("sector_analyzer", "data_source", "central_db")
                        health.report_metric("sector_analyzer", "central_db_age_minutes", age_minutes)
                        health.clear_error("sector_analyzer", "central_db_empty")
                        health.clear_error("sector_analyzer", "central_db_stale")
                        return price_cache
                    else:
                        logger.warning("[sector_analyzer] No stocks loaded from Central DB")

            # Fallback to JSON file
            if not os.path.exists(self.price_cache_file):
                logger.warning(f"Price cache file not found: {self.price_cache_file}")
                return {}

            with open(self.price_cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading price cache: {e}")
            return {}

    def _load_from_central_db(self) -> Dict:
        """
        Load price data from Central Quote Database.
        Builds the price_cache structure from DB for sector analysis.

        Returns:
            Dict with structure: {symbol: {current, previous, previous2, ...}}
        """
        try:
            # Get all stocks from all sectors
            all_stocks = set()
            for sector in self.sector_manager.get_all_sectors():
                stocks = self.sector_manager.get_stocks_in_sector(sector)
                all_stocks.update(stocks)

            all_stocks_list = list(all_stocks)

            # Get latest quotes for all stocks
            latest_quotes = self.central_db.get_latest_stock_quotes(symbols=all_stocks_list)
            if not latest_quotes:
                return {}

            # Get day open prices in batch for full-day change calculation
            day_open_prices = self.central_db.get_stock_day_open_prices_batch(all_stocks_list)

            # Build price cache structure
            price_cache = {}
            now = datetime.now()

            for symbol, quote in latest_quotes.items():
                # Get current price
                current_price = quote.get('price', 0)
                current_volume = quote.get('volume', 0)

                if current_price == 0:
                    continue

                # Get historical prices for comparison
                price_5min = self.central_db.get_stock_price_at(symbol, 5)
                price_10min = self.central_db.get_stock_price_at(symbol, 10)
                price_30min = self.central_db.get_stock_price_at(symbol, 30)

                # Get historical volumes from history
                history = self.central_db.get_stock_history(symbol, minutes=30)
                volumes = [h.get('volume', 0) for h in history if h.get('volume', 0) > 0]

                # Day open price for full-day change
                day_open = day_open_prices.get(symbol)

                # Build structure compatible with existing analyze_sectors logic
                price_cache[symbol] = {
                    'current': {
                        'price': current_price,
                        'volume': current_volume,
                        'timestamp': quote.get('timestamp', now.isoformat())
                    },
                    'previous': {
                        'price': price_5min,
                        'volume': volumes[-2] if len(volumes) >= 2 else 0,
                        'timestamp': (now - timedelta(minutes=5)).isoformat()
                    } if price_5min else None,
                    'previous2': {
                        'price': price_10min,
                        'volume': volumes[-3] if len(volumes) >= 3 else 0,
                        'timestamp': (now - timedelta(minutes=10)).isoformat()
                    } if price_10min else None,
                    'previous6': {
                        'price': price_30min,
                        'volume': volumes[0] if volumes else 0,
                        'timestamp': (now - timedelta(minutes=30)).isoformat()
                    } if price_30min else None,
                    'day_open': {
                        'price': day_open,
                    } if day_open else None
                }

            return price_cache

        except Exception as e:
            logger.error(f"Error loading from Central DB: {e}")
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
                'stock_details': [],  # NEW: Store detailed stock-level metrics
                'total_market_cap': 0,
                'weighted_price_change_5min': 0,
                'weighted_price_change_10min': 0,
                'weighted_price_change_30min': 0,
                'weighted_price_change_day': 0,
                'total_volume_current': 0,
                'total_volume_avg': 0,
                'stocks_up_5min': 0,
                'stocks_down_5min': 0,
                'stocks_up_10min': 0,
                'stocks_down_10min': 0,
                'stocks_up_30min': 0,
                'stocks_down_30min': 0,
                'stocks_up_day': 0,
                'stocks_down_day': 0,
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

                # Get day open snapshot
                day_open = snapshots.get('day_open')

                # Calculate price changes
                price_change_5min = 0
                price_change_10min = 0
                price_change_30min = 0
                price_change_day = 0

                if prev and prev.get('price'):
                    price_change_5min = ((current_price - prev['price']) / prev['price']) * 100

                if prev2 and prev2.get('price'):
                    price_change_10min = ((current_price - prev2['price']) / prev2['price']) * 100

                if prev6 and prev6.get('price'):
                    price_change_30min = ((current_price - prev6['price']) / prev6['price']) * 100

                if day_open and day_open.get('price'):
                    price_change_day = ((current_price - day_open['price']) / day_open['price']) * 100

                # Calculate average volume from previous snapshots
                volumes = []
                for key in ['previous', 'previous2', 'previous3', 'previous4', 'previous5', 'previous6']:
                    snap = snapshots.get(key)
                    if snap and snap.get('volume'):
                        volumes.append(snap['volume'])

                avg_volume = sum(volumes) / len(volumes) if volumes else 0

                # Aggregate into sector
                sector_data[sector]['stocks'].append(symbol)

                # Store detailed stock-level metrics
                sector_data[sector]['stock_details'].append({
                    'symbol': symbol,
                    'price': current_price,
                    'price_change_5min': round(price_change_5min, 2),
                    'price_change_10min': round(price_change_10min, 2),
                    'price_change_30min': round(price_change_30min, 2),
                    'price_change_day': round(price_change_day, 2),
                    'volume': current_volume,
                    'avg_volume': avg_volume,
                    'volume_ratio': round(current_volume / avg_volume, 2) if avg_volume > 0 else 1.0,
                    'market_cap_cr': round(market_cap, 2)
                })

                sector_data[sector]['total_market_cap'] += market_cap
                sector_data[sector]['total_volume_current'] += current_volume
                sector_data[sector]['total_volume_avg'] += avg_volume

                # Market-cap weighted price changes
                if market_cap > 0:
                    sector_data[sector]['weighted_price_change_5min'] += price_change_5min * market_cap
                    sector_data[sector]['weighted_price_change_10min'] += price_change_10min * market_cap
                    sector_data[sector]['weighted_price_change_30min'] += price_change_30min * market_cap
                    sector_data[sector]['weighted_price_change_day'] += price_change_day * market_cap
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

                if price_change_day > 0:
                    sector_data[sector]['stocks_up_day'] += 1
                elif price_change_day < 0:
                    sector_data[sector]['stocks_down_day'] += 1

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
                mc_weighted_day = data['weighted_price_change_day'] / data['total_market_cap']

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
                    'price_change_day': round(mc_weighted_day, 2),
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
                    'stocks_up_day': data['stocks_up_day'],
                    'stocks_down_day': data['stocks_down_day'],
                    'total_stocks': total_stocks,
                    'participation_pct': round(participation_5min, 1),
                    'total_market_cap_cr': round(data['total_market_cap'], 2),
                    'total_volume': data['total_volume_current'],
                    'stock_details': sorted(
                        data['stock_details'],
                        key=lambda x: x['price_change_10min'],
                        reverse=True
                    )  # Sort by 10-min performance (best to worst)
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
        import time
        cycle_start_time = time.time()
        health = get_health_tracker()

        # Analyze sectors
        analysis = self.analyze_sectors()

        if analysis:
            # Save to cache
            self.save_analysis_cache(analysis)

            # Save snapshot if requested
            if save_snapshot_at:
                self.save_snapshot(analysis, save_snapshot_at)

        # Report health metrics
        cycle_duration_ms = int((time.time() - cycle_start_time) * 1000)
        health.heartbeat("sector_analyzer", cycle_duration_ms)
        health.report_metric("sector_analyzer", "last_cycle_duration_ms", cycle_duration_ms)
        health.report_metric("sector_analyzer", "sectors_analyzed", len(analysis.get('sectors', {})) if analysis else 0)

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
