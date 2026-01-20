#!/usr/bin/env python3
"""
NIFTY Option Selling Indicator - Core Analysis Engine

Analyzes Greeks (Delta, Theta, Gamma), VIX, market regime, and OI to recommend
whether it's a good day for NIFTY straddle/strangle selling.

Provides:
- SELL/HOLD/AVOID signal with 0-100 score
- Detailed breakdown of all factors
- Strike recommendations for straddles and strangles
- Risk factors and recommendations

Author: Sunil Kumar Durganaik
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from kiteconnect import KiteConnect
import pandas as pd
import math

import config
from market_regime_detector import MarketRegimeDetector
from oi_analyzer import OIAnalyzer
from api_coordinator import get_api_coordinator
from historical_data_cache import get_historical_cache
from central_quote_db import get_central_db
from central_db_reader import fetch_nifty_vix, report_cycle_complete

logger = logging.getLogger(__name__)


class NiftyOptionAnalyzer:
    """Analyzes NIFTY options for selling opportunities"""

    def __init__(self, kite: KiteConnect):
        """
        Initialize NIFTY option analyzer

        Args:
            kite: Authenticated KiteConnect instance
        """
        self.kite = kite
        self.regime_detector = MarketRegimeDetector(kite)
        self.oi_analyzer = OIAnalyzer()

        # Initialize API coordinator for optimized quote fetching (Tier 2)
        self.coordinator = get_api_coordinator(kite=kite)

        # Initialize historical data cache for VIX/NIFTY history (Tier 2)
        self.historical_cache = get_historical_cache()

        # Initialize Central Quote Database (Tier 3 - single source of truth for NIFTY/VIX)
        self.central_db = get_central_db()

        # Cache for instruments
        self._nfo_instruments = None
        self._instruments_cache_time = None

        logger.info("NiftyOptionAnalyzer initialized with Central DB + API Coordinator + Historical Cache")

    def analyze_option_selling_opportunity(
        self,
        expiry_count: int = 2
    ) -> Dict:
        """
        Complete analysis for NIFTY option selling

        Args:
            expiry_count: Number of expiries to analyze (default: 2 for next 2 weeks)

        Returns:
            Dict with complete analysis including signal, scores, and recommendations
        """
        try:
            logger.info("=" * 70)
            logger.info("NIFTY OPTION SELLING ANALYSIS - Starting")
            logger.info("=" * 70)

            # Step 1-2: Get NIFTY spot + VIX in single batch call (Tier 2 optimization)
            logger.info("Step 1-2: Fetching NIFTY spot price + India VIX (batch call)...")
            indices = self._get_spot_indices_batch()
            nifty_spot = indices['nifty_spot']
            vix = indices['india_vix']

            if not nifty_spot:
                raise ValueError("Unable to fetch NIFTY spot price")
            if not vix:
                raise ValueError("Unable to fetch India VIX")

            logger.info(f"NIFTY Spot: {nifty_spot:.2f}, India VIX: {vix:.2f}")

            # Step 2a: Calculate VIX trend (CRITICAL for option selling!)
            logger.info("Step 2a: Calculating VIX trend...")
            vix_trend = self._get_vix_trend(vix)
            if vix_trend > config.VIX_TREND_RISING_THRESHOLD:
                logger.warning(f"VIX RISING: {vix_trend:+.2f} points - Risky for option selling!")
            elif vix_trend < config.VIX_TREND_FALLING_THRESHOLD:
                logger.info(f"VIX FALLING: {vix_trend:+.2f} points - Good for option selling!")
            else:
                logger.info(f"VIX STABLE: {vix_trend:+.2f} points")

            # Step 2b: Calculate IV Rank (Historical volatility percentile)
            logger.info("Step 2b: Calculating IV Rank (1-year percentile)...")
            iv_rank = self._calculate_iv_rank(vix)
            if iv_rank > config.IV_RANK_HIGH_THRESHOLD:
                logger.info(f"IV RANK: {iv_rank:.1f}% - HIGH IV, excellent for selling (rich premiums)!")
            elif iv_rank > config.IV_RANK_MODERATE_HIGH:
                logger.info(f"IV RANK: {iv_rank:.1f}% - Above average, good for selling")
            elif iv_rank > config.IV_RANK_MODERATE_LOW:
                logger.info(f"IV RANK: {iv_rank:.1f}% - Below average, marginal for selling")
            else:
                logger.warning(f"IV RANK: {iv_rank:.1f}% - LOW IV, poor for selling (cheap premiums)")

            # Step 2c: IV RANK TIERED CHECK
            # Assign signal tier based on IV Rank quality
            if config.ENABLE_TIERED_SIGNALS:
                # Tiered signal system
                if iv_rank >= config.IV_RANK_EXCELLENT:  # >= 25%
                    signal_tier = 'SELL_STRONG'
                    position_size = config.POSITION_SIZE_STRONG
                    premium_quality = config.PREMIUM_QUALITY_EXCELLENT
                    logger.info(f"✅ SELL_STRONG: IV Rank {iv_rank:.1f}% >= {config.IV_RANK_EXCELLENT}% (Excellent premiums)")
                elif iv_rank >= config.IV_RANK_GOOD:  # >= 15%
                    signal_tier = 'SELL_MODERATE'
                    position_size = config.POSITION_SIZE_MODERATE
                    premium_quality = config.PREMIUM_QUALITY_GOOD
                    logger.info(f"⚠️  SELL_MODERATE: IV Rank {iv_rank:.1f}% >= {config.IV_RANK_GOOD}% (Fair premiums, 75% position)")
                elif iv_rank >= config.IV_RANK_MARGINAL:  # >= 10%
                    signal_tier = 'SELL_WEAK'
                    position_size = config.POSITION_SIZE_WEAK
                    premium_quality = config.PREMIUM_QUALITY_MARGINAL
                    logger.warning(f"⚠️  SELL_WEAK: IV Rank {iv_rank:.1f}% >= {config.IV_RANK_MARGINAL}% (Marginal premiums, 50% position recommended)")
                else:  # < 10%
                    signal_tier = 'AVOID'
                    position_size = 0.0
                    premium_quality = config.PREMIUM_QUALITY_POOR
                    veto_reason = f"IV Rank {iv_rank:.1f}% < {config.IV_RANK_MARGINAL}% - Premiums too cheap, poor risk/reward"
                    logger.error(f"🚫 HARD VETO: {veto_reason}")
                    return self._generate_veto_response(
                        nifty_spot=nifty_spot,
                        vix=vix,
                        vix_trend=vix_trend,
                        iv_rank=iv_rank,
                        veto_reason=veto_reason,
                        veto_type="IV_RANK_TOO_LOW"
                    )
            else:
                # Binary system (backwards compatibility)
                if iv_rank < config.IV_RANK_HARD_VETO_THRESHOLD:
                    veto_reason = f"IV Rank {iv_rank:.1f}% < {config.IV_RANK_HARD_VETO_THRESHOLD}% - Premiums too cheap, poor risk/reward"
                    logger.error(f"🚫 HARD VETO: {veto_reason}")
                    return self._generate_veto_response(
                        nifty_spot=nifty_spot,
                        vix=vix,
                        vix_trend=vix_trend,
                        iv_rank=iv_rank,
                        veto_reason=veto_reason,
                        veto_type="IV_RANK_TOO_LOW"
                    )
                signal_tier = 'SELL'
                position_size = 1.0
                premium_quality = "TRADEABLE"

            # Store tier info for later use
            self._current_signal_tier = signal_tier
            self._current_position_size = position_size
            self._current_premium_quality = premium_quality

            # Step 2d: Check realized vs implied volatility
            logger.info("Step 2d: Checking realized vs implied volatility...")
            realized_vol_check = self._check_realized_volatility(vix, nifty_spot)
            if not realized_vol_check['passed']:
                veto_reason = realized_vol_check['reason']
                logger.error(f"🚫 HARD VETO: {veto_reason}")
                return self._generate_veto_response(
                    nifty_spot=nifty_spot,
                    vix=vix,
                    vix_trend=vix_trend,
                    iv_rank=iv_rank,
                    veto_reason=veto_reason,
                    veto_type="REALIZED_VOL_TOO_HIGH",
                    extra_data=realized_vol_check
                )

            # Step 2e: Check price action (trending vs range-bound)
            logger.info("Step 2e: Checking price action (trending vs range-bound)...")
            price_action_check = self._check_price_action(nifty_spot)
            if not price_action_check['passed']:
                veto_reason = price_action_check['reason']
                logger.error(f"🚫 HARD VETO: {veto_reason}")
                return self._generate_veto_response(
                    nifty_spot=nifty_spot,
                    vix=vix,
                    vix_trend=vix_trend,
                    iv_rank=iv_rank,
                    veto_reason=veto_reason,
                    veto_type="TRENDING_MARKET",
                    extra_data=price_action_check
                )

            # Step 2f: Check intraday volatility
            logger.info("Step 2f: Checking recent intraday volatility...")
            intraday_vol_check = self._check_intraday_volatility(nifty_spot)
            if not intraday_vol_check['passed']:
                veto_reason = intraday_vol_check['reason']
                logger.warning(f"⚠️  WARNING: {veto_reason}")
                # Note: Intraday vol is a WARNING, not a hard veto (market can calm down)
                # But we'll still include it in risk factors

            # Step 2g: Calculate CPR and check for trending day
            logger.info("Step 2g: Calculating CPR (Central Pivot Range) indicator...")
            cpr_data = self._calculate_cpr()
            cpr_check = self._check_cpr_trend(nifty_spot, cpr_data)

            # CPR HARD VETO: If trending day detected, AVOID option selling
            if not cpr_check['passed']:
                veto_reason = f"CPR TRENDING DAY: {cpr_check['reason']}"
                logger.error(f"🚫 HARD VETO: {veto_reason}")
                logger.error("   Option selling strategies (straddle/strangle) DON'T work on trending days!")
                logger.error("   Expected: Strong directional move - premium will be tested")

                return self._generate_veto_response(
                    nifty_spot=nifty_spot,
                    vix=vix,
                    vix_trend=vix_trend,
                    iv_rank=iv_rank,
                    veto_reason=veto_reason,
                    veto_type='CPR_TRENDING_DAY',
                    extra_data={
                        'cpr_data': cpr_data,
                        'cpr_check': cpr_check
                    }
                )

            # Step 3: Get market regime
            logger.info("Step 3: Analyzing market regime...")
            market_regime = self.regime_detector.get_market_regime()
            logger.info(f"Market Regime: {market_regime}")

            # Step 4: Get OI analysis for NIFTY futures
            logger.info("Step 4: Analyzing Open Interest...")
            oi_analysis = self._get_nifty_oi_analysis()
            logger.info(f"OI Pattern: {oi_analysis.get('pattern', 'UNKNOWN')}")

            # Step 5: Get expiries
            logger.info("Step 5: Finding next expiries...")
            expiries = self._get_next_expiries(expiry_count)
            if not expiries:
                raise ValueError("Unable to find NIFTY expiries")
            logger.info(f"Expiries found: {[exp.strftime('%Y-%m-%d') for exp in expiries]}")

            # Step 6: Analyze each expiry
            logger.info("Step 6: Analyzing options for each expiry...")
            expiry_analyses = []
            for expiry in expiries:
                expiry_data = self._analyze_expiry(
                    nifty_spot=nifty_spot,
                    expiry_date=expiry,
                    vix=vix,
                    vix_trend=vix_trend,
                    iv_rank=iv_rank,
                    market_regime=market_regime,
                    oi_analysis=oi_analysis
                )
                expiry_analyses.append(expiry_data)

            # Step 7: Generate overall recommendation
            logger.info("Step 7: Generating recommendation...")
            recommendation = self._generate_recommendation(
                nifty_spot=nifty_spot,
                vix=vix,
                vix_trend=vix_trend,
                iv_rank=iv_rank,
                market_regime=market_regime,
                oi_analysis=oi_analysis,
                expiry_analyses=expiry_analyses
            )

            logger.info("=" * 70)
            logger.info(f"ANALYSIS COMPLETE - Signal: {recommendation['signal']} ({recommendation['total_score']:.1f}/100)")
            logger.info("=" * 70)

            return recommendation

        except Exception as e:
            logger.error(f"Error in option selling analysis: {e}", exc_info=True)
            return self._generate_error_response(str(e))

    def _get_nifty_spot_price(self) -> Optional[float]:
        """Get current NIFTY 50 spot price (OPTIMIZED: uses coordinator)"""
        try:
            # Use coordinator to batch with VIX fetch
            quote = self.coordinator.get_single_quote("NSE:NIFTY 50")
            if quote:
                return quote.get("last_price")
            return None
        except Exception as e:
            logger.error(f"Error fetching NIFTY spot: {e}")
            return None

    def _get_india_vix(self) -> Optional[float]:
        """Get current India VIX value (OPTIMIZED: uses coordinator)"""
        try:
            # Use coordinator to batch with NIFTY fetch
            quote = self.coordinator.get_single_quote("NSE:INDIA VIX")
            if quote:
                return quote.get("last_price")
            return None
        except Exception as e:
            logger.error(f"Error fetching India VIX: {e}")
            return None

    def _get_spot_indices_batch(self) -> Dict[str, float]:
        """
        Fetch NIFTY + VIX from Central Quote Database with freshness check + health reporting.
        ZERO API calls - data is pre-populated by central_data_collector

        Fallback to API coordinator if central DB unavailable or stale.

        Returns:
            Dict with 'nifty_spot' and 'india_vix' values
        """
        # Use centralized helper with freshness check + health reporting
        result = fetch_nifty_vix(
            service_name="nifty_option_analyzer",
            kite_client=self.kite,
            coordinator=self.coordinator,
            max_age_minutes=2
        )

        if result['nifty_spot'] and result['india_vix']:
            return result

        # If helper returned incomplete data, log warning
        logger.warning(f"Incomplete NIFTY/VIX data: nifty={result['nifty_spot']}, vix={result['india_vix']}")
        return result

    def _get_vix_trend(self, current_vix: float) -> float:
        """
        Calculate VIX trend by comparing current VIX to historical VIX

        Args:
            current_vix: Current VIX value

        Returns:
            VIX trend in points (positive = rising, negative = falling, 0 = stable)
        """
        try:
            # Fetch historical VIX data
            lookback_days = config.VIX_TREND_LOOKBACK_DAYS
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days + 5)  # Extra days for weekends/holidays

            # Use historical cache to avoid redundant API calls (Tier 2 optimization)
            vix_history = self.historical_cache.get_historical_data(
                kite=self.kite,
                instrument_token=config.INDIA_VIX_TOKEN,
                from_date=start_date,
                to_date=end_date,
                interval='day'
            )

            if not vix_history or len(vix_history) < 2:
                logger.warning(f"Insufficient VIX history data (got {len(vix_history) if vix_history else 0} candles)")
                return 0.0

            # Get VIX from N trading days ago
            # Use the close price from the candle N days back
            if len(vix_history) >= lookback_days + 1:
                historical_vix = vix_history[-(lookback_days + 1)]['close']
            else:
                # Use oldest available data if we don't have full lookback period
                historical_vix = vix_history[0]['close']

            # Calculate trend
            vix_trend = current_vix - historical_vix

            logger.info(f"VIX Trend: {current_vix:.2f} vs {historical_vix:.2f} "
                       f"({lookback_days}d ago) = {vix_trend:+.2f} points")

            return vix_trend

        except Exception as e:
            logger.warning(f"Error calculating VIX trend: {e}. Using 0 (neutral)")
            return 0.0

    def _calculate_iv_rank(self, current_vix: float) -> float:
        """
        Calculate IV Rank (percentile of current VIX over past year)

        IV Rank = Percentile of current VIX in 1-year range
        - 100% = VIX at highest point in year (excellent for selling)
        - 50% = VIX at median (neutral)
        - 0% = VIX at lowest point in year (poor for selling)

        Args:
            current_vix: Current VIX value

        Returns:
            IV Rank as percentage (0-100)
        """
        try:
            # Fetch 1-year VIX history
            lookback_days = config.IV_RANK_LOOKBACK_DAYS
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days + 30)  # Extra buffer for weekends/holidays

            # Use historical cache to avoid redundant API calls (Tier 2 optimization)
            vix_history = self.historical_cache.get_historical_data(
                kite=self.kite,
                instrument_token=config.INDIA_VIX_TOKEN,
                from_date=start_date,
                to_date=end_date,
                interval='day'
            )

            if not vix_history or len(vix_history) < 100:
                logger.warning(f"Insufficient VIX history for IV Rank (got {len(vix_history) if vix_history else 0} candles, need 100+)")
                return 50.0  # Default to neutral if insufficient data

            # Extract VIX values (closing prices)
            vix_values = [candle['close'] for candle in vix_history]

            # Calculate percentile rank
            # Count how many historical values are below current VIX
            values_below = sum(1 for v in vix_values if v < current_vix)
            iv_rank = (values_below / len(vix_values)) * 100

            # Get min/max for context
            vix_min = min(vix_values)
            vix_max = max(vix_values)
            vix_median = sorted(vix_values)[len(vix_values) // 2]

            logger.info(f"IV Rank: {iv_rank:.1f}% | Current VIX: {current_vix:.2f} | "
                       f"1Y Range: {vix_min:.2f}-{vix_max:.2f} (median: {vix_median:.2f})")

            return iv_rank

        except Exception as e:
            logger.warning(f"Error calculating IV Rank: {e}. Using 50% (neutral)")
            return 50.0

    def _check_realized_volatility(self, current_vix: float, nifty_spot: float) -> Dict:
        """
        Check if realized volatility exceeds implied volatility

        Realized vol = actual price movement over recent days
        Implied vol = VIX (market's expectation of future movement)

        If realized > implied = market is moving MORE than VIX suggests = dangerous!

        Returns:
            Dict with 'passed', 'reason', 'realized_vol', 'implied_vol', 'ratio'
        """
        try:
            lookback_days = config.REALIZED_VOL_LOOKBACK_DAYS
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days + 5)

            # Use historical cache to avoid redundant API calls (Tier 2 optimization)
            nifty_history = self.historical_cache.get_historical_data(
                kite=self.kite,
                instrument_token=config.NIFTY_50_TOKEN,
                from_date=start_date,
                to_date=end_date,
                interval='day'
            )

            if not nifty_history or len(nifty_history) < lookback_days:
                logger.warning(f"Insufficient NIFTY history for realized vol check")
                return {'passed': True, 'reason': 'Insufficient data'}

            # Calculate realized volatility (standard deviation of daily returns)
            recent_data = nifty_history[-lookback_days:]
            daily_returns = []
            for i in range(1, len(recent_data)):
                prev_close = recent_data[i-1]['close']
                curr_close = recent_data[i]['close']
                daily_return = ((curr_close - prev_close) / prev_close) * 100
                daily_returns.append(abs(daily_return))

            # Avg absolute daily return as proxy for realized vol
            realized_vol = sum(daily_returns) / len(daily_returns) if daily_returns else 0

            # Implied vol from VIX (VIX is annualized, convert to daily rough equivalent)
            # Rough conversion: VIX / 16 ≈ daily vol expectation
            implied_vol_daily = current_vix / 16.0

            # Check ratio
            ratio = realized_vol / implied_vol_daily if implied_vol_daily > 0 else 0

            logger.info(f"Realized Vol: {realized_vol:.2f}% (avg daily move) | "
                       f"Implied Vol: {implied_vol_daily:.2f}% (VIX {current_vix:.2f}) | "
                       f"Ratio: {ratio:.2f}x")

            # VETO if realized vol is significantly higher than implied
            if ratio > config.REALIZED_VOL_MAX_MULTIPLIER:
                return {
                    'passed': False,
                    'reason': f'Realized volatility ({realized_vol:.2f}%) is {ratio:.2f}x implied ({implied_vol_daily:.2f}%) - Market moving more than VIX suggests',
                    'realized_vol': realized_vol,
                    'implied_vol': implied_vol_daily,
                    'ratio': ratio
                }

            return {
                'passed': True,
                'realized_vol': realized_vol,
                'implied_vol': implied_vol_daily,
                'ratio': ratio
            }

        except Exception as e:
            logger.warning(f"Error checking realized volatility: {e}")
            return {'passed': True, 'reason': f'Error: {e}'}

    def _check_price_action(self, nifty_spot: float) -> Dict:
        """
        Check if market is trending vs range-bound

        Straddle/strangle selling works best in CONSOLIDATION
        Trending markets = losses for option sellers

        Returns:
            Dict with 'passed', 'reason', 'avg_range_pct', 'pattern'
        """
        try:
            lookback_days = config.PRICE_ACTION_LOOKBACK_DAYS
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days + 5)

            # Use historical cache to avoid redundant API calls (Tier 2 optimization)
            nifty_history = self.historical_cache.get_historical_data(
                kite=self.kite,
                instrument_token=config.NIFTY_50_TOKEN,
                from_date=start_date,
                to_date=end_date,
                interval='day'
            )

            if not nifty_history or len(nifty_history) < lookback_days:
                logger.warning(f"Insufficient NIFTY history for price action check")
                return {'passed': True, 'reason': 'Insufficient data'}

            # Calculate daily ranges as % of price
            recent_data = nifty_history[-lookback_days:]
            daily_ranges = []
            for candle in recent_data:
                range_pct = ((candle['high'] - candle['low']) / candle['close']) * 100
                daily_ranges.append(range_pct)

            avg_range_pct = sum(daily_ranges) / len(daily_ranges) if daily_ranges else 0

            # Determine pattern
            if avg_range_pct > config.TRENDING_THRESHOLD:
                pattern = "TRENDING"
                passed = False
                reason = f'Market trending with avg daily range {avg_range_pct:.2f}% > {config.TRENDING_THRESHOLD}% threshold - Bad for straddle selling'
            elif avg_range_pct < config.CONSOLIDATION_THRESHOLD:
                pattern = "CONSOLIDATION"
                passed = True
                reason = f'Market consolidating with avg daily range {avg_range_pct:.2f}% - Ideal for option selling'
            else:
                pattern = "MODERATE"
                passed = True
                reason = f'Market in moderate range {avg_range_pct:.2f}% - Acceptable for option selling'

            logger.info(f"Price Action: {pattern} | Avg daily range: {avg_range_pct:.2f}%")

            return {
                'passed': passed,
                'reason': reason,
                'avg_range_pct': avg_range_pct,
                'pattern': pattern
            }

        except Exception as e:
            logger.warning(f"Error checking price action: {e}")
            return {'passed': True, 'reason': f'Error: {e}'}

    def _check_intraday_volatility(self, nifty_spot: float) -> Dict:
        """
        Check recent intraday volatility

        High intraday ranges = unstable market = risky for option selling

        Returns:
            Dict with 'passed', 'reason', 'avg_intraday_range_pct'
        """
        try:
            lookback_days = config.INTRADAY_VOL_LOOKBACK_DAYS
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days + 2)

            # Use historical cache to avoid redundant API calls (Tier 2 optimization)
            intraday_data = self.historical_cache.get_historical_data(
                kite=self.kite,
                instrument_token=config.NIFTY_50_TOKEN,
                from_date=start_date,
                to_date=end_date,
                interval='15minute'
            )

            if not intraday_data or len(intraday_data) < 10:
                logger.warning(f"Insufficient intraday data for volatility check")
                return {'passed': True, 'reason': 'Insufficient data'}

            # Group by day and calculate daily intraday ranges
            daily_ranges = []
            current_day_data = []
            current_date = None

            for candle in intraday_data:
                candle_date = candle['date'].date()

                if current_date is None:
                    current_date = candle_date

                if candle_date != current_date:
                    # New day - calculate range for previous day
                    if current_day_data:
                        day_high = max([c['high'] for c in current_day_data])
                        day_low = min([c['low'] for c in current_day_data])
                        day_open = current_day_data[0]['open']
                        day_range_pct = ((day_high - day_low) / day_open) * 100
                        daily_ranges.append(day_range_pct)

                    # Reset for new day
                    current_day_data = [candle]
                    current_date = candle_date
                else:
                    current_day_data.append(candle)

            # Don't forget last day
            if current_day_data:
                day_high = max([c['high'] for c in current_day_data])
                day_low = min([c['low'] for c in current_day_data])
                day_open = current_day_data[0]['open']
                day_range_pct = ((day_high - day_low) / day_open) * 100
                daily_ranges.append(day_range_pct)

            if not daily_ranges:
                return {'passed': True, 'reason': 'Insufficient data'}

            avg_intraday_range = sum(daily_ranges) / len(daily_ranges)

            logger.info(f"Intraday Vol: Avg daily range {avg_intraday_range:.2f}% over last {len(daily_ranges)} days")

            # Check threshold
            if avg_intraday_range > config.INTRADAY_VOL_HIGH_THRESHOLD:
                return {
                    'passed': False,
                    'reason': f'High intraday volatility: avg range {avg_intraday_range:.2f}% > {config.INTRADAY_VOL_HIGH_THRESHOLD}% threshold',
                    'avg_intraday_range_pct': avg_intraday_range
                }

            return {
                'passed': True,
                'avg_intraday_range_pct': avg_intraday_range
            }

        except Exception as e:
            logger.warning(f"Error checking intraday volatility: {e}")
            return {'passed': True, 'reason': f'Error: {e}'}

    def _calculate_cpr(self) -> Dict:
        """
        Calculate CPR (Central Pivot Range) from previous day's data.

        CPR is a powerful intraday indicator for determining market trend:
        - Narrow CPR = Trending day likely (strong directional move)
        - Wide CPR = Sideways day likely (range-bound)

        CPR Components:
        - TC (Top Central): Upper resistance (calculated pivot + (pivot - BC))
        - Pivot: Central pivot ((High + Low + Close) / 3)
        - BC (Bottom Central): Lower support ((High + Low) / 2)

        Returns:
            Dict with 'tc', 'pivot', 'bc', 'width_pct', 'width_points'
        """
        try:
            # Get previous day's OHLC data
            end_date = datetime.now()
            start_date = end_date - timedelta(days=5)  # Get last 5 days to ensure we have previous day

            # Use historical cache (Tier 2 optimization)
            daily_data = self.historical_cache.get_historical_data(
                kite=self.kite,
                instrument_token=config.NIFTY_50_TOKEN,
                from_date=start_date,
                to_date=end_date,
                interval='day'
            )

            if not daily_data or len(daily_data) < 2:
                logger.warning("Insufficient data to calculate CPR")
                return None

            # Get previous trading day's data (second last candle, last is today incomplete)
            prev_day = daily_data[-2]

            high = prev_day['high']
            low = prev_day['low']
            close = prev_day['close']

            # Calculate CPR levels
            pivot = (high + low + close) / 3
            bc = (high + low) / 2
            tc = (pivot - bc) + pivot

            # CPR width (narrow = trending, wide = sideways)
            width_points = tc - bc
            width_pct = (width_points / pivot) * 100

            logger.info(f"CPR Calculated - Pivot: {pivot:.2f}, TC: {tc:.2f}, BC: {bc:.2f}, Width: {width_pct:.3f}%")

            return {
                'tc': tc,
                'pivot': pivot,
                'bc': bc,
                'width_points': width_points,
                'width_pct': width_pct,
                'prev_day_high': high,
                'prev_day_low': low,
                'prev_day_close': close
            }

        except Exception as e:
            logger.error(f"Error calculating CPR: {e}")
            return None

    def _check_cpr_trend(self, nifty_spot: float, cpr_data: Dict) -> Dict:
        """
        Check if today is a trending day based on CPR indicator.

        CPR Trading Rules:
        1. Price above TC = BULLISH TRENDING (strong uptrend expected)
        2. Price below BC = BEARISH TRENDING (strong downtrend expected)
        3. Price between TC-BC = SIDEWAYS/RANGE-BOUND (ideal for option selling)
        4. Narrow CPR width (<0.3%) = High probability of trending day
        5. Wide CPR width (>0.5%) = Sideways day likely

        For option selling (straddle/strangle):
        - BEST: Price within CPR + wide CPR (range-bound day)
        - RISKY: Price outside CPR or narrow CPR (trending day likely)

        Returns:
            Dict with 'is_trending', 'trend_type', 'position', 'cpr_width_type', 'reason'
        """
        try:
            if not cpr_data:
                return {
                    'is_trending': False,
                    'reason': 'CPR data unavailable',
                    'passed': True
                }

            tc = cpr_data['tc']
            pivot = cpr_data['pivot']
            bc = cpr_data['bc']
            width_pct = cpr_data['width_pct']

            # Determine CPR width type
            if width_pct < 0.25:
                cpr_width_type = 'VERY_NARROW'  # Strong trending day likely
            elif width_pct < 0.35:
                cpr_width_type = 'NARROW'  # Trending day possible
            elif width_pct < 0.50:
                cpr_width_type = 'MODERATE'  # Could go either way
            else:
                cpr_width_type = 'WIDE'  # Sideways day likely

            # Determine price position relative to CPR
            if nifty_spot > tc:
                position = 'ABOVE_CPR'
                trend_type = 'BULLISH_TRENDING'
                is_trending = True
                reason = f"Price {nifty_spot:.2f} above TC {tc:.2f} - BULLISH TRENDING DAY likely"
            elif nifty_spot < bc:
                position = 'BELOW_CPR'
                trend_type = 'BEARISH_TRENDING'
                is_trending = True
                reason = f"Price {nifty_spot:.2f} below BC {bc:.2f} - BEARISH TRENDING DAY likely"
            else:
                position = 'WITHIN_CPR'
                trend_type = 'SIDEWAYS'
                is_trending = False
                reason = f"Price {nifty_spot:.2f} within CPR ({bc:.2f} - {tc:.2f}) - SIDEWAYS/RANGE-BOUND"

            # Additional check: Very narrow CPR suggests trending day even if price within CPR
            if cpr_width_type == 'VERY_NARROW' and not is_trending:
                logger.warning(f"⚠️  VERY NARROW CPR ({width_pct:.3f}%) - Trending day possible even within CPR")
                is_trending = True  # Override
                trend_type = 'POTENTIAL_TRENDING'
                reason += f" BUT VERY NARROW CPR ({width_pct:.3f}%) suggests trending day"

            # Log CPR analysis
            logger.info(f"CPR Analysis:")
            logger.info(f"  TC (Resistance): {tc:.2f}")
            logger.info(f"  Pivot: {pivot:.2f}")
            logger.info(f"  BC (Support): {bc:.2f}")
            logger.info(f"  Current Price: {nifty_spot:.2f}")
            logger.info(f"  Position: {position}")
            logger.info(f"  CPR Width: {width_pct:.3f}% ({cpr_width_type})")
            logger.info(f"  Trend Assessment: {trend_type}")

            # Determine if option selling is safe
            passed = not is_trending  # Fail if trending day

            if is_trending:
                logger.warning(f"❌ CPR VETO: {reason}")
                logger.warning(f"   Option selling is RISKY on trending days - directional moves expected")
            else:
                logger.info(f"✅ CPR CHECK PASSED: {reason}")
                logger.info(f"   Good for option selling - range-bound day expected")

            return {
                'passed': passed,
                'is_trending': is_trending,
                'trend_type': trend_type,
                'position': position,
                'cpr_width_type': cpr_width_type,
                'cpr_width_pct': width_pct,
                'tc': tc,
                'pivot': pivot,
                'bc': bc,
                'reason': reason
            }

        except Exception as e:
            logger.error(f"Error checking CPR trend: {e}")
            return {
                'passed': True,  # Don't block on error
                'is_trending': False,
                'reason': f'Error: {e}'
            }

    def _generate_veto_response(
        self,
        nifty_spot: float,
        vix: float,
        vix_trend: float,
        iv_rank: float,
        veto_reason: str,
        veto_type: str,
        extra_data: Dict = None
    ) -> Dict:
        """
        Generate AVOID response when hard veto is triggered

        This overrides all other signals and forces AVOID
        """
        return {
            'timestamp': datetime.now().isoformat(),
            'signal': 'AVOID',
            'total_score': 0,
            'nifty_spot': nifty_spot,
            'vix': vix,
            'vix_trend': vix_trend,
            'iv_rank': iv_rank,
            'market_regime': 'UNKNOWN',
            'best_strategy': 'NONE',
            'recommendation': f'HARD VETO: {veto_reason}',
            'risk_factors': [veto_reason],
            'veto_type': veto_type,
            'veto_data': extra_data or {},
            'breakdown': {
                'theta_score': 0,
                'gamma_score': 0,
                'vega_score': 0,
                'vix_score': 0,
                'regime_score': 0,
                'oi_score': 0
            },
            'oi_analysis': {'pattern': 'UNKNOWN'},
            'expiry_analyses': []
        }

    def _get_nifty_oi_analysis(self) -> Dict:
        """Get OI analysis for NIFTY futures (Tier 2: batch call optimization)"""
        try:
            # Get NIFTY futures quote for current month
            # Symbol format: NIFTY25JAN (year + month abbreviation)
            current_month = datetime.now()

            # Build symbols for current month and next month futures
            futures_symbols = []
            for month_offset in [0, 1]:
                target_month = current_month + timedelta(days=30 * month_offset)
                year_short = str(target_month.year)[-2:]
                month_abbr = target_month.strftime("%b").upper()
                futures_symbol = f"NFO:NIFTY{year_short}{month_abbr}FUT"
                futures_symbols.append(futures_symbol)

            # Single batch API call for both futures (Tier 2 optimization)
            logger.info(f"Fetching {len(futures_symbols)} NIFTY futures in batch call...")
            quotes = self.coordinator.get_multiple_instruments(futures_symbols)

            # Try each futures contract (prefer current month, fallback to next month)
            for futures_symbol in futures_symbols:
                futures_data = quotes.get(futures_symbol, {})

                if futures_data and futures_data.get("oi", 0) > 0:
                    oi = futures_data.get("oi", 0)
                    price = futures_data.get("last_price", 0)
                    ohlc = futures_data.get("ohlc", {})
                    open_price = ohlc.get("open", price)

                    # Calculate price change from day open
                    if open_price > 0:
                        price_change_pct = ((price - open_price) / open_price) * 100
                    else:
                        price_change_pct = 0

                    # Get OI analysis from analyzer
                    oi_result = self.oi_analyzer.analyze_oi_change(
                        symbol="NIFTY",
                        current_oi=oi,
                        price_change_pct=price_change_pct
                    )

                    if oi_result:
                        logger.info(f"OI analysis successful using {futures_symbol}")
                        return oi_result

            # Default if no futures data found
            logger.warning("No valid futures data found in batch response")
            return {
                'pattern': 'UNKNOWN',
                'price_change_pct': 0,
                'oi_change_pct': 0,
                'strength': 'MINIMAL',
                'interpretation': 'No OI data available'
            }

        except Exception as e:
            logger.error(f"Error in OI analysis: {e}")
            return {
                'pattern': 'UNKNOWN',
                'price_change_pct': 0,
                'oi_change_pct': 0,
                'strength': 'MINIMAL',
                'interpretation': str(e)
            }

    def _get_nfo_instruments(self) -> List[Dict]:
        """Get NFO instruments with caching (1 hour cache)"""
        # Check cache validity
        if (self._nfo_instruments is not None and
            self._instruments_cache_time is not None and
            datetime.now() - self._instruments_cache_time < timedelta(hours=1)):
            return self._nfo_instruments

        # Fetch fresh data
        logger.info("Fetching NFO instruments...")
        instruments = self.kite.instruments("NFO")

        self._nfo_instruments = instruments
        self._instruments_cache_time = datetime.now()

        return instruments

    def _get_next_expiries(self, count: int = 2) -> List[datetime]:
        """
        Get next N NIFTY expiry dates (excluding current week expiry)

        IMPORTANT: Skips expiries less than MIN_DAYS_TO_EXPIRY days away.
        This ensures we ONLY trade next week and next-to-next week expiries,
        NEVER the current week expiry.

        Args:
            count: Number of expiries to return

        Returns:
            List of expiry dates (datetime objects)
        """
        try:
            instruments = self._get_nfo_instruments()

            # Filter NIFTY options
            nifty_options = [
                inst for inst in instruments
                if inst['name'] == 'NIFTY' and inst['instrument_type'] in ['CE', 'PE']
            ]

            # Extract unique expiry dates
            expiries = set()
            today = datetime.now().date()
            min_days = config.NIFTY_OPTION_MIN_DAYS_TO_EXPIRY

            for option in nifty_options:
                expiry = option['expiry']
                days_to_expiry = (expiry - today).days

                # Skip expiries that are too close (current week)
                # Only include expiries >= MIN_DAYS_TO_EXPIRY days away
                if days_to_expiry >= min_days:
                    expiries.add(expiry)

            # Sort and return next N
            sorted_expiries = sorted(list(expiries))[:count]

            if sorted_expiries:
                logger.info(f"Selected expiries (>{min_days} days away): {[exp.strftime('%Y-%m-%d') for exp in sorted_expiries]}")
            else:
                logger.warning(f"No expiries found with >={min_days} days to expiry")

            # Convert to datetime
            return [datetime.combine(exp, datetime.min.time()) for exp in sorted_expiries]

        except Exception as e:
            logger.error(f"Error getting expiries: {e}")
            return []

    def _analyze_expiry(
        self,
        nifty_spot: float,
        expiry_date: datetime,
        vix: float,
        vix_trend: float,
        iv_rank: float,
        market_regime: str,
        oi_analysis: Dict
    ) -> Dict:
        """
        Analyze a specific expiry for option selling

        Returns:
            Dict with analysis for this expiry
        """
        try:
            # Get ATM strike
            atm_strike = self._get_atm_strike(nifty_spot)

            # Define strikes for analysis
            straddle_strikes = {
                'call': atm_strike,
                'put': atm_strike
            }

            strangle_strikes = {
                'call': atm_strike + 100,  # 2 strikes OTM
                'put': atm_strike - 100     # 2 strikes OTM
            }

            # Fetch all 4 options in single batch call (Tier 2 optimization)
            options_batch = self._get_options_batch(expiry_date, straddle_strikes, strangle_strikes, nifty_spot)
            straddle_call = options_batch['straddle_call']
            straddle_put = options_batch['straddle_put']
            strangle_call = options_batch['strangle_call']
            strangle_put = options_batch['strangle_put']

            # Calculate days to expiry
            days_to_expiry = (expiry_date.date() - datetime.now().date()).days

            # Calculate combined Greeks for straddle
            straddle_greeks = self._calculate_combined_greeks(
                straddle_call.get('greeks', {}),
                straddle_put.get('greeks', {})
            )

            # Calculate combined Greeks for strangle
            strangle_greeks = self._calculate_combined_greeks(
                strangle_call.get('greeks', {}),
                strangle_put.get('greeks', {})
            )

            # Calculate scores for straddle
            straddle_score = self._calculate_option_score(
                greeks=straddle_greeks,
                vix=vix,
                vix_trend=vix_trend,
                iv_rank=iv_rank,
                market_regime=market_regime,
                oi_analysis=oi_analysis
            )

            # Calculate scores for strangle
            strangle_score = self._calculate_option_score(
                greeks=strangle_greeks,
                vix=vix,
                vix_trend=vix_trend,
                iv_rank=iv_rank,
                market_regime=market_regime,
                oi_analysis=oi_analysis
            )

            return {
                'expiry_date': expiry_date,
                'days_to_expiry': days_to_expiry,
                'atm_strike': atm_strike,
                'straddle': {
                    'strikes': straddle_strikes,
                    'call_premium': straddle_call.get('last_price', 0),
                    'put_premium': straddle_put.get('last_price', 0),
                    'total_premium': straddle_call.get('last_price', 0) + straddle_put.get('last_price', 0),
                    'greeks': straddle_greeks,
                    'score': straddle_score
                },
                'strangle': {
                    'strikes': strangle_strikes,
                    'call_premium': strangle_call.get('last_price', 0),
                    'put_premium': strangle_put.get('last_price', 0),
                    'total_premium': strangle_call.get('last_price', 0) + strangle_put.get('last_price', 0),
                    'greeks': strangle_greeks,
                    'score': strangle_score
                }
            }

        except Exception as e:
            logger.error(f"Error analyzing expiry {expiry_date}: {e}")
            return {
                'expiry_date': expiry_date,
                'error': str(e)
            }

    def _get_atm_strike(self, spot_price: float) -> int:
        """
        Get ATM strike for NIFTY

        NIFTY strikes are in multiples of 50
        """
        return round(spot_price / 50) * 50

    def _get_options_batch(
        self,
        expiry: datetime,
        straddle_strikes: Dict[str, int],
        strangle_strikes: Dict[str, int],
        nifty_spot: float = None
    ) -> Dict:
        """
        Fetch all 4 options (straddle + strangle) in single batch call (Tier 2 optimization).

        Returns:
            Dict with keys: 'straddle_call', 'straddle_put', 'strangle_call', 'strangle_put'
        """
        try:
            # Build all 4 option symbols for batch call
            year_short = str(expiry.year)[-2:]
            month = str(expiry.month)  # No leading zero
            day = str(expiry.day).zfill(2)  # Day needs leading zero

            symbols = {
                'straddle_call': f"NFO:NIFTY{year_short}{month}{day}{straddle_strikes['call']}CE",
                'straddle_put': f"NFO:NIFTY{year_short}{month}{day}{straddle_strikes['put']}PE",
                'strangle_call': f"NFO:NIFTY{year_short}{month}{day}{strangle_strikes['call']}CE",
                'strangle_put': f"NFO:NIFTY{year_short}{month}{day}{strangle_strikes['put']}PE"
            }

            # Single batch API call for all 4 options (Tier 2 optimization)
            logger.info(f"Fetching 4 options in single batch call for expiry {expiry.date()}...")
            quotes = self.coordinator.get_multiple_instruments(list(symbols.values()))

            # Parse results and build structured data for each option
            results = {}
            for key, symbol in symbols.items():
                option_data = quotes.get(symbol, {})
                option_type = 'CE' if 'call' in key else 'PE'
                strike = straddle_strikes['call'] if 'straddle_call' in key else \
                         straddle_strikes['put'] if 'straddle_put' in key else \
                         strangle_strikes['call'] if 'strangle_call' in key else \
                         strangle_strikes['put']

                # Extract Greeks if available
                greeks = {}
                if 'greeks' in option_data and option_data['greeks']:
                    greeks = {
                        'delta': option_data['greeks'].get('delta', 0),
                        'theta': option_data['greeks'].get('theta', 0),
                        'gamma': option_data['greeks'].get('gamma', 0),
                        'vega': option_data['greeks'].get('vega', 0)
                    }
                else:
                    # Fallback: Calculate approximate Greeks using Black-Scholes
                    logger.warning(f"Greeks not available in API for {symbol}, using approximation")
                    spot_for_greeks = nifty_spot if nifty_spot else strike
                    greeks = self._approximate_greeks(
                        option_type=option_type,
                        spot=spot_for_greeks,
                        strike=strike,
                        expiry=expiry,
                        iv=option_data.get('implied_volatility', 20) / 100
                    )

                results[key] = {
                    'symbol': symbol,
                    'last_price': option_data.get('last_price', 0),
                    'greeks': greeks,
                    'oi': option_data.get('oi', 0),
                    'volume': option_data.get('volume', 0)
                }

            logger.info(f"Successfully fetched all 4 options via batch call")
            return results

        except Exception as e:
            logger.error(f"Error in batch options fetch: {e}. Falling back to individual calls...")
            # Fallback to individual calls if batch fails
            return {
                'straddle_call': self._get_option_data('CE', expiry, straddle_strikes['call'], nifty_spot),
                'straddle_put': self._get_option_data('PE', expiry, straddle_strikes['put'], nifty_spot),
                'strangle_call': self._get_option_data('CE', expiry, strangle_strikes['call'], nifty_spot),
                'strangle_put': self._get_option_data('PE', expiry, strangle_strikes['put'], nifty_spot)
            }

    def _get_option_data(
        self,
        option_type: str,
        expiry: datetime,
        strike: int,
        nifty_spot: float = None
    ) -> Dict:
        """
        Get option data including premium and Greeks

        Args:
            option_type: 'CE' for call, 'PE' for put
            expiry: Expiry date
            strike: Strike price
            nifty_spot: NIFTY spot price (for Greeks calculation)

        Returns:
            Dict with option data
        """
        try:
            # Build symbol using date format: NIFTY2610626150CE
            # Format: NIFTY + YYMMDD + STRIKE + CE/PE (month and day without leading zeros)
            year_short = str(expiry.year)[-2:]
            month = str(expiry.month)  # No leading zero
            day = str(expiry.day).zfill(2)  # Day needs leading zero
            symbol = f"NFO:NIFTY{year_short}{month}{day}{strike}{option_type}"

            # Fetch quote
            quote = self.kite.quote([symbol])
            option_data = quote.get(symbol, {})

            # Extract Greeks if available
            greeks = {}
            if 'greeks' in option_data:
                # Kite API provides Greeks in the quote
                greeks = {
                    'delta': option_data['greeks'].get('delta', 0),
                    'theta': option_data['greeks'].get('theta', 0),
                    'gamma': option_data['greeks'].get('gamma', 0),
                    'vega': option_data['greeks'].get('vega', 0)
                }
            else:
                # Fallback: Calculate approximate Greeks using Black-Scholes
                logger.warning(f"Greeks not available in API for {symbol}, using approximation")
                # Use NIFTY spot price if provided, otherwise use strike as fallback
                spot_for_greeks = nifty_spot if nifty_spot else strike
                greeks = self._approximate_greeks(
                    option_type=option_type,
                    spot=spot_for_greeks,  # NIFTY spot price (underlying)
                    strike=strike,
                    expiry=expiry,
                    iv=option_data.get('implied_volatility', 20) / 100  # Convert to decimal
                )

            return {
                'symbol': symbol,
                'last_price': option_data.get('last_price', 0),
                'greeks': greeks,
                'oi': option_data.get('oi', 0),
                'volume': option_data.get('volume', 0)
            }

        except Exception as e:
            logger.error(f"Error fetching option data for {option_type} {strike}: {e}")
            return {
                'symbol': f"{option_type}_{strike}",
                'last_price': 0,
                'greeks': {'delta': 0, 'theta': 0, 'gamma': 0, 'vega': 0},
                'oi': 0,
                'volume': 0
            }

    def _approximate_greeks(
        self,
        option_type: str,
        spot: float,
        strike: int,
        expiry: datetime,
        iv: float
    ) -> Dict:
        """
        Approximate Greeks using simplified Black-Scholes

        This is a fallback if Greeks are not available from API
        """
        try:
            # Time to expiry in years
            days_to_expiry = (expiry.date() - datetime.now().date()).days
            t = max(days_to_expiry / 365.0, 0.001)  # Avoid division by zero

            # Risk-free rate (approximate India 10Y bond yield)
            r = 0.07  # 7%

            # Calculate d1 and d2
            d1 = (math.log(spot / strike) + (r + 0.5 * iv ** 2) * t) / (iv * math.sqrt(t))
            d2 = d1 - iv * math.sqrt(t)

            # Approximate Delta
            if option_type == 'CE':
                delta = self._norm_cdf(d1)
            else:  # PE
                delta = self._norm_cdf(d1) - 1

            # Approximate Gamma (same for CE and PE)
            gamma = self._norm_pdf(d1) / (spot * iv * math.sqrt(t))

            # Approximate Theta (daily decay)
            if option_type == 'CE':
                theta = -(spot * self._norm_pdf(d1) * iv) / (2 * math.sqrt(t)) - \
                        r * strike * math.exp(-r * t) * self._norm_cdf(d2)
            else:  # PE
                theta = -(spot * self._norm_pdf(d1) * iv) / (2 * math.sqrt(t)) + \
                        r * strike * math.exp(-r * t) * self._norm_cdf(-d2)

            # Convert theta to per-day (from per-year)
            theta = theta / 365.0

            # Approximate Vega
            vega = spot * self._norm_pdf(d1) * math.sqrt(t) / 100  # Per 1% IV change

            return {
                'delta': round(delta, 4),
                'theta': round(theta, 2),
                'gamma': round(gamma, 6),
                'vega': round(vega, 2)
            }

        except Exception as e:
            logger.error(f"Error approximating Greeks: {e}")
            return {'delta': 0, 'theta': 0, 'gamma': 0, 'vega': 0}

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Cumulative distribution function for standard normal distribution"""
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    @staticmethod
    def _norm_pdf(x: float) -> float:
        """Probability density function for standard normal distribution"""
        return math.exp(-x**2 / 2.0) / math.sqrt(2.0 * math.pi)

    def _calculate_combined_greeks(
        self,
        call_greeks: Dict,
        put_greeks: Dict
    ) -> Dict:
        """
        Calculate combined Greeks for straddle/strangle

        Args:
            call_greeks: Greeks for call option
            put_greeks: Greeks for put option

        Returns:
            Combined Greeks
        """
        return {
            'delta': call_greeks.get('delta', 0) + put_greeks.get('delta', 0),
            'theta': call_greeks.get('theta', 0) + put_greeks.get('theta', 0),
            'gamma': call_greeks.get('gamma', 0) + put_greeks.get('gamma', 0),
            'vega': call_greeks.get('vega', 0) + put_greeks.get('vega', 0)
        }

    def _calculate_option_score(
        self,
        greeks: Dict,
        vix: float,
        vix_trend: float,
        iv_rank: float,
        market_regime: str,
        oi_analysis: Dict
    ) -> Dict:
        """
        Calculate composite score (0-100) for option selling conditions

        Scoring weights from config (updated to include Vega):
        - Theta: 20% (time decay)
        - Gamma: 20% (position stability)
        - Vega: 15% (VIX sensitivity - NEW!)
        - VIX: 25% (volatility level + trend)
        - Market Regime: 10% (trend direction)
        - OI Analysis: 10% (institutional positioning)

        Returns:
            Dict with total_score, signal, breakdown, and recommendation
        """
        # Theta scoring (0-100)
        # Higher absolute theta = better (faster decay)
        # For ATM options, theta typically -20 to -50 for weekly expiry
        theta = abs(greeks.get('theta', 0))
        if theta == 0:
            theta_score = 0
        else:
            # Scale: theta of 50 = 100 score, theta of 10 = 20 score
            theta_score = min(100, theta * 2)

        # Gamma scoring (0-100)
        # Lower gamma = better (more stable delta)
        # Invert scale: high gamma = low score
        gamma = greeks.get('gamma', 0)
        if gamma == 0:
            gamma_score = 50  # Neutral if no data
        else:
            # Scale: gamma of 0.001 = 90 score, gamma of 0.01 = 0 score
            gamma_score = max(0, 100 - (gamma * 10000))

        # Vega scoring (0-100) with VIX trend adjustment
        vega = greeks.get('vega', 0)
        vega_score = self._score_vega(vega, vix_trend)

        # VIX scoring (0-100) with trend and IV Rank adjustment
        vix_score = self._score_vix(vix, vix_trend, iv_rank)

        # Market regime scoring (0-100)
        regime_score = self._score_market_regime(market_regime)

        # OI scoring (0-100)
        oi_score = self._score_oi_pattern(oi_analysis.get('pattern', 'UNKNOWN'))

        # Calculate weighted total (now includes Vega)
        total_score = (
            theta_score * config.THETA_WEIGHT +
            gamma_score * config.GAMMA_WEIGHT +
            vega_score * config.VEGA_WEIGHT +
            vix_score * config.VIX_WEIGHT +
            regime_score * config.REGIME_WEIGHT +
            oi_score * config.OI_WEIGHT
        )

        # Generate signal
        if total_score >= config.NIFTY_OPTION_SELL_THRESHOLD:
            signal = 'SELL'
            recommendation = 'Excellent conditions for option selling'
        elif total_score >= config.NIFTY_OPTION_HOLD_THRESHOLD:
            signal = 'HOLD'
            recommendation = 'Mixed conditions, wait for better setup'
        else:
            signal = 'AVOID'
            recommendation = 'Unfavorable conditions, high risk'

        # Identify risk factors
        risk_factors = self._identify_risk_factors(
            vix=vix,
            vix_trend=vix_trend,
            iv_rank=iv_rank,
            gamma=gamma,
            vega=vega,
            market_regime=market_regime,
            oi_pattern=oi_analysis.get('pattern', 'UNKNOWN')
        )

        return {
            'total_score': round(total_score, 1),
            'signal': signal,
            'breakdown': {
                'theta_score': round(theta_score, 1),
                'gamma_score': round(gamma_score, 1),
                'vega_score': round(vega_score, 1),
                'vix_score': round(vix_score, 1),
                'regime_score': round(regime_score, 1),
                'oi_score': round(oi_score, 1)
            },
            'recommendation': recommendation,
            'risk_factors': risk_factors
        }

    def _score_vix(self, vix: float, vix_trend: float = 0.0, iv_rank: float = 50.0) -> float:
        """
        Score VIX considering level, trend, and IV Rank (historical percentile)

        VIX level determines base score, then adjusted for:
        - VIX Trend: Rising = Bad, Falling = Good
        - IV Rank: High percentile = Good (rich premiums), Low = Bad (cheap premiums)

        Args:
            vix: Current VIX level
            vix_trend: VIX change in points (positive = rising, negative = falling)
            iv_rank: VIX percentile over past year (0-100%)

        Returns:
            Adjusted VIX score (0-100)
        """
        # Base score from VIX level
        if vix < config.VIX_EXCELLENT:
            base_score = 100
        elif vix < config.VIX_GOOD:
            base_score = 75
        elif vix < config.VIX_MODERATE:
            base_score = 40
        else:
            base_score = 10

        # Start with base score
        adjusted_score = base_score

        # Adjustment 1: VIX Trend
        if vix_trend > config.VIX_TREND_RISING_THRESHOLD:
            # VIX rising = BAD for option sellers
            trend_penalty = min(config.VIX_TREND_MAX_PENALTY, abs(vix_trend) * 5)
            adjusted_score = max(0, adjusted_score - trend_penalty)
            logger.debug(f"VIX rising: {vix_trend:+.2f} points → penalty -{trend_penalty:.1f}")

        elif vix_trend < config.VIX_TREND_FALLING_THRESHOLD:
            # VIX falling = GOOD for option sellers
            trend_bonus = min(config.VIX_TREND_MAX_BONUS, abs(vix_trend) * 5)
            adjusted_score = min(100, adjusted_score + trend_bonus)
            logger.debug(f"VIX falling: {vix_trend:+.2f} points → bonus +{trend_bonus:.1f}")

        # Adjustment 2: IV Rank (Historical Percentile)
        if iv_rank > config.IV_RANK_HIGH_THRESHOLD:
            # High IV Rank (>75%) = VIX at top 25% = Excellent for selling
            iv_rank_bonus = 10
            adjusted_score = min(100, adjusted_score + iv_rank_bonus)
            logger.debug(f"IV Rank {iv_rank:.1f}% (HIGH) → bonus +{iv_rank_bonus}")

        elif iv_rank < config.IV_RANK_MODERATE_LOW:
            # Low IV Rank (<25%) = VIX at bottom 25% = Poor for selling
            iv_rank_penalty = 15
            adjusted_score = max(0, adjusted_score - iv_rank_penalty)
            logger.debug(f"IV Rank {iv_rank:.1f}% (LOW) → penalty -{iv_rank_penalty}")

        logger.debug(f"VIX Score: {base_score:.1f} (base) → {adjusted_score:.1f} (final)")
        return adjusted_score

    def _score_vega(self, vega: float, vix_trend: float = 0.0) -> float:
        """
        Score Vega exposure considering VIX trend

        For option SELLERS:
        - High Vega = High VIX sensitivity (risky if VIX rises, good if VIX falls)
        - Low Vega = Low VIX sensitivity (neutral, less affected by VIX moves)

        Vega represents P&L change per 1% VIX move:
        - Vega -150 + VIX rises 2 pts = Lose ₹300
        - Vega -150 + VIX falls 2 pts = Gain ₹300

        Args:
            vega: Combined vega for position (negative for sellers)
            vix_trend: VIX change in points (positive = rising, negative = falling)

        Returns:
            Vega score (0-100)
        """
        abs_vega = abs(vega)

        # Base score: Lower vega = better (less VIX sensitivity)
        # For ATM straddle/strangle, typical vega: 100-200
        if abs_vega < 50:
            base_score = 90  # Very low vega exposure (rare for ATM)
        elif abs_vega < 100:
            base_score = 70  # Moderate vega exposure
        elif abs_vega < 150:
            base_score = 50  # High vega exposure (typical for ATM straddle)
        elif abs_vega < 200:
            base_score = 35  # Very high vega exposure
        else:
            base_score = 20  # Extreme vega exposure

        # Adjust for VIX trend (critical interaction!)
        if vix_trend > config.VIX_TREND_RISING_THRESHOLD:
            # VIX rising + high vega = disaster for sellers
            # Penalty scales with both vega magnitude and VIX rise
            penalty = min(30, (abs_vega / 150) * abs(vix_trend) * 10)
            adjusted_score = max(0, base_score - penalty)
            logger.debug(f"Vega {abs_vega:.0f} + VIX rising {vix_trend:+.2f} → penalty -{penalty:.1f} "
                        f"(score: {base_score:.1f} → {adjusted_score:.1f})")
            return adjusted_score

        elif vix_trend < config.VIX_TREND_FALLING_THRESHOLD:
            # VIX falling + high vega = excellent for sellers
            # Bonus scales with both vega magnitude and VIX fall
            bonus = min(25, (abs_vega / 150) * abs(vix_trend) * 8)
            adjusted_score = min(100, base_score + bonus)
            logger.debug(f"Vega {abs_vega:.0f} + VIX falling {vix_trend:+.2f} → bonus +{bonus:.1f} "
                        f"(score: {base_score:.1f} → {adjusted_score:.1f})")
            return adjusted_score

        else:
            # VIX stable = base score (no vega risk or opportunity)
            logger.debug(f"Vega {abs_vega:.0f} + VIX stable {vix_trend:+.2f} (score: {base_score:.1f})")
            return base_score

    def _score_market_regime(self, regime: str) -> float:
        """Score market regime (0-100)"""
        if regime == 'NEUTRAL':
            return 100  # Best for straddle/strangle
        elif regime in ['BULLISH', 'BEARISH']:
            return 60   # Trending but manageable
        else:
            return 30   # Unknown/unclear

    def _score_oi_pattern(self, pattern: str) -> float:
        """Score OI pattern (0-100)"""
        if pattern in ['LONG_BUILDUP', 'SHORT_BUILDUP']:
            return 40  # Strong directional move expected - risky
        elif pattern in ['SHORT_COVERING', 'LONG_UNWINDING']:
            return 70  # Weak move, may consolidate
        else:
            return 90  # Neutral/Unknown - good for selling

    def _identify_risk_factors(
        self,
        vix: float,
        vix_trend: float,
        iv_rank: float,
        gamma: float,
        vega: float,
        market_regime: str,
        oi_pattern: str
    ) -> List[str]:
        """Identify risk factors for option selling"""
        risks = []

        if vix > config.VIX_MODERATE:
            risks.append(f"High VIX ({vix:.1f}) - elevated volatility")
        elif vix > config.VIX_GOOD:
            risks.append(f"VIX slightly elevated ({vix:.1f})")

        # VIX trend risks
        if vix_trend > config.VIX_TREND_RISING_THRESHOLD:
            risks.append(f"VIX rising ({vix_trend:+.1f} points) - conditions deteriorating")

        # IV Rank risks (low IV = cheap premiums)
        if iv_rank < config.IV_RANK_MODERATE_LOW:
            risks.append(f"Low IV Rank ({iv_rank:.1f}%) - premiums historically cheap, poor value for selling")

        if gamma > config.MAX_GAMMA_THRESHOLD:
            risks.append(f"High gamma ({gamma:.4f}) - position unstable")

        # Vega + VIX trend interaction (critical risk!)
        abs_vega = abs(vega)
        if abs_vega > config.MAX_VEGA_THRESHOLD:
            if vix_trend > config.VIX_TREND_RISING_THRESHOLD:
                risks.append(f"High vega ({abs_vega:.0f}) + rising VIX - significant exposure to volatility expansion")
            else:
                risks.append(f"High vega ({abs_vega:.0f}) - sensitive to VIX changes")

        if market_regime in ['BULLISH', 'BEARISH']:
            risks.append(f"Trending market ({market_regime}) - directional bias")

        if oi_pattern in ['LONG_BUILDUP', 'SHORT_BUILDUP']:
            risks.append(f"Strong OI buildup ({oi_pattern}) - momentum trade")

        if not risks:
            risks.append("No significant risks identified")

        return risks

    def _generate_recommendation(
        self,
        nifty_spot: float,
        vix: float,
        vix_trend: float,
        iv_rank: float,
        market_regime: str,
        oi_analysis: Dict,
        expiry_analyses: List[Dict]
    ) -> Dict:
        """
        Generate overall recommendation based on all analyses

        Returns:
            Complete recommendation dict
        """
        # Use first expiry (next week) as primary
        primary_expiry = expiry_analyses[0] if expiry_analyses else {}

        # Get best score between straddle and strangle
        straddle_score = primary_expiry.get('straddle', {}).get('score', {})
        strangle_score = primary_expiry.get('strangle', {}).get('score', {})

        # Use higher total score as overall signal
        if straddle_score.get('total_score', 0) >= strangle_score.get('total_score', 0):
            best_strategy = 'straddle'
            best_score = straddle_score
        else:
            best_strategy = 'strangle'
            best_score = strangle_score

        # Get tier info (set during IV Rank check)
        signal_tier = getattr(self, '_current_signal_tier', best_score.get('signal', 'HOLD'))
        position_size = getattr(self, '_current_position_size', 1.0)
        premium_quality = getattr(self, '_current_premium_quality', 'TRADEABLE')

        # Calculate CPR for inclusion in result
        cpr_data = self._calculate_cpr()
        cpr_check = self._check_cpr_trend(nifty_spot, cpr_data) if cpr_data else None

        return {
            'timestamp': datetime.now().isoformat(),
            'nifty_spot': nifty_spot,
            'vix': vix,
            'vix_trend': vix_trend,
            'iv_rank': iv_rank,
            'market_regime': market_regime,
            'oi_analysis': oi_analysis,
            'cpr_data': cpr_data,  # CPR levels (TC, Pivot, BC)
            'cpr_check': cpr_check,  # CPR trend analysis
            'signal': best_score.get('signal', 'HOLD'),
            'total_score': best_score.get('total_score', 50),
            # NEW FIELDS for tiered signals
            'signal_tier': signal_tier,
            'position_size': position_size,
            'premium_quality': premium_quality,
            # END NEW FIELDS
            'breakdown': best_score.get('breakdown', {}),
            'recommendation': best_score.get('recommendation', ''),
            'risk_factors': best_score.get('risk_factors', []),
            'best_strategy': best_strategy,
            'expiry_analyses': expiry_analyses
        }

    def _generate_error_response(self, error_msg: str) -> Dict:
        """Generate error response"""
        return {
            'timestamp': datetime.now().isoformat(),
            'error': error_msg,
            'signal': 'ERROR',
            'total_score': 0,
            'recommendation': f'Analysis failed: {error_msg}'
        }

    def analyze_add_position_signal(self, current_score: float, last_layer_score: float, layer_count: int) -> Dict:
        """
        Analyze if conditions support adding to position

        Args:
            current_score: Current option selling score
            last_layer_score: Score from last layer entry
            layer_count: Current number of layers

        Returns:
            Dict with ADD_POSITION or NO_ADD signal
        """
        try:
            add_reasons = []
            confidence = 0

            # 1. Score in SELL zone
            if current_score >= config.NIFTY_OPTION_ADD_SCORE_THRESHOLD:
                add_reasons.append(f"Score in SELL zone ({current_score:.1f} >= {config.NIFTY_OPTION_ADD_SCORE_THRESHOLD})")
                confidence += 40
                logger.info(f"ADD SIGNAL: Score in SELL zone {current_score:.1f}")

            # 2. Score improvement from last layer
            score_improvement = current_score - last_layer_score
            if score_improvement >= config.NIFTY_OPTION_ADD_SCORE_IMPROVEMENT:
                add_reasons.append(f"Score improved {score_improvement:.1f} points (last: {last_layer_score:.1f} → current: {current_score:.1f})")
                confidence += 30
                logger.info(f"ADD SIGNAL: Score improved {score_improvement:.1f} points")

            # 3. Early layers get preference (add more aggressively early)
            if layer_count <= 1:  # First or second layer
                add_reasons.append(f"Early opportunity (layer {layer_count + 1})")
                confidence += 20

            # 4. Very high score (exceptional conditions)
            if current_score >= 80:
                add_reasons.append(f"Exceptional score ({current_score:.1f}/100)")
                confidence += 10
                logger.info(f"ADD SIGNAL: Exceptional score {current_score:.1f}")

            # Determine signal
            if confidence >= 50:
                signal = 'ADD_POSITION'
                recommendation = f'Add to position - Favorable conditions (confidence: {confidence}%)'
            elif confidence >= 30:
                signal = 'CONSIDER_ADD'
                recommendation = f'Consider adding - Moderate signal (confidence: {confidence}%)'
            else:
                signal = 'NO_ADD'
                recommendation = 'Conditions not favorable for adding'

            return {
                'signal': signal,
                'confidence': confidence,
                'recommendation': recommendation,
                'add_reasons': add_reasons,
                'current_score': current_score,
                'last_layer_score': last_layer_score,
                'score_improvement': score_improvement,
                'layer_count': layer_count
            }

        except Exception as e:
            logger.error(f"Error in add position analysis: {e}")
            return {
                'signal': 'NO_ADD',
                'error': str(e)
            }

    def analyze_exit_signal(self, entry_data: Dict) -> Dict:
        """
        Analyze if current conditions warrant exiting the position

        Args:
            entry_data: Entry data from PositionStateManager

        Returns:
            Dict with exit signal (EXIT_NOW or HOLD_POSITION) and reasons
        """
        try:
            logger.info("=" * 70)
            logger.info("NIFTY OPTION EXIT SIGNAL ANALYSIS - Starting")
            logger.info("=" * 70)

            # Get current market data (batch call for NIFTY + VIX - Tier 2 optimization)
            logger.info("Fetching current market data...")
            indices = self._get_spot_indices_batch()
            nifty_spot = indices['nifty_spot']
            vix = indices['india_vix']
            market_regime = self.regime_detector.get_market_regime()
            oi_analysis = self._get_nifty_oi_analysis()

            if not nifty_spot or not vix:
                raise ValueError("Unable to fetch current market data")

            logger.info(f"Current: NIFTY={nifty_spot:.2f}, VIX={vix:.2f}, Regime={market_regime}")

            # Get entry conditions
            entry_score = entry_data.get('entry_score', 0)
            entry_vix = entry_data.get('entry_vix', 0)
            entry_regime = entry_data.get('entry_regime', '')
            entry_nifty = entry_data.get('entry_nifty_spot', 0)

            logger.info(f"Entry: Score={entry_score:.1f}, VIX={entry_vix:.2f}, Regime={entry_regime}")

            # Get current score (simplified - use same analysis)
            current_analysis = self.analyze_option_selling_opportunity()
            current_score = current_analysis.get('total_score', 0)

            logger.info(f"Current Score: {current_score:.1f}")

            # Check exit conditions
            exit_reasons = []
            exit_score = 0  # Lower = more urgent to exit

            # 1. Score deterioration
            score_drop = entry_score - current_score
            if score_drop >= config.NIFTY_OPTION_EXIT_SCORE_DROP:
                exit_reasons.append(f"Score dropped {score_drop:.1f} points (entry: {entry_score:.1f} → current: {current_score:.1f})")
                exit_score += 30
                logger.warning(f"EXIT TRIGGER: Score drop {score_drop:.1f} points")

            # 2. Score in AVOID zone
            if current_score < config.NIFTY_OPTION_EXIT_SCORE_THRESHOLD:
                exit_reasons.append(f"Score below exit threshold ({current_score:.1f} < {config.NIFTY_OPTION_EXIT_SCORE_THRESHOLD})")
                exit_score += 40
                logger.warning(f"EXIT TRIGGER: Score in AVOID zone {current_score:.1f}")

            # 3. VIX spike (points-based OR percentage-based)
            if entry_vix > 0:
                vix_increase_points = vix - entry_vix
                vix_increase_pct = (vix_increase_points / entry_vix) * 100

                # Points-based threshold (primary for low VIX environments)
                if vix_increase_points >= config.NIFTY_OPTION_EXIT_VIX_SPIKE_POINTS:
                    exit_reasons.append(f"VIX increased {vix_increase_points:.1f} points (entry: {entry_vix:.2f} → {vix:.2f})")
                    exit_score += 30
                    logger.warning(f"EXIT TRIGGER: VIX +{vix_increase_points:.1f} points")

                # Percentage-based threshold (secondary)
                elif vix_increase_pct >= config.NIFTY_OPTION_EXIT_VIX_SPIKE_PCT:
                    exit_reasons.append(f"VIX spiked {vix_increase_pct:.1f}% (entry: {entry_vix:.2f} → {vix:.2f})")
                    exit_score += 25
                    logger.warning(f"EXIT TRIGGER: VIX spike {vix_increase_pct:.1f}%")

            # 4. Market regime change
            if config.NIFTY_OPTION_EXIT_ON_REGIME_CHANGE:
                if entry_regime == 'NEUTRAL' and market_regime != 'NEUTRAL':
                    exit_reasons.append(f"Market regime changed from {entry_regime} to {market_regime}")
                    exit_score += 25
                    logger.warning(f"EXIT TRIGGER: Regime change {entry_regime} → {market_regime}")

            # 5. Strong OI buildup
            if config.NIFTY_OPTION_EXIT_ON_STRONG_OI_BUILDUP:
                oi_pattern = oi_analysis.get('pattern', 'UNKNOWN')
                if oi_pattern in ['LONG_BUILDUP', 'SHORT_BUILDUP']:
                    exit_reasons.append(f"Strong directional OI buildup detected ({oi_pattern})")
                    exit_score += 20
                    logger.warning(f"EXIT TRIGGER: OI buildup {oi_pattern}")

            # 6. Large NIFTY move (CRITICAL FOR OPTION SELLING)
            # For ATM option sellers, even 50-100 point moves are significant
            # Check BOTH points-based and percentage-based thresholds
            if entry_nifty > 0:
                nifty_move_points = abs(nifty_spot - entry_nifty)
                nifty_move_pct = (nifty_move_points / entry_nifty) * 100

                # Points-based threshold (primary for option selling)
                if nifty_move_points >= config.NIFTY_OPTION_EXIT_POINTS_MOVE:
                    exit_reasons.append(f"NIFTY moved {nifty_move_points:.0f} points from entry ({nifty_move_pct:.1f}%)")
                    exit_score += 25  # Higher weight than percentage
                    logger.warning(f"EXIT TRIGGER: NIFTY move {nifty_move_points:.0f} points")

                # Percentage-based threshold (secondary, for very large moves)
                elif nifty_move_pct >= config.NIFTY_OPTION_EXIT_PCT_MOVE:
                    exit_reasons.append(f"Large NIFTY move ({nifty_move_pct:.1f}% from entry, {nifty_move_points:.0f} points)")
                    exit_score += 20
                    logger.warning(f"EXIT TRIGGER: Large move {nifty_move_pct:.1f}%")

            # Determine exit signal
            if exit_score >= 30:  # At least one strong exit reason
                signal = 'EXIT_NOW'
                recommendation = 'Exit position immediately - Market conditions have deteriorated'
                urgency = 'HIGH' if exit_score >= 50 else 'MEDIUM'
            elif exit_score >= 15:  # Minor concerns
                signal = 'CONSIDER_EXIT'
                recommendation = 'Monitor closely - Some deterioration in conditions'
                urgency = 'LOW'
            else:
                signal = 'HOLD_POSITION'
                recommendation = 'Continue holding - Conditions remain favorable'
                urgency = 'NONE'

            logger.info("=" * 70)
            logger.info(f"EXIT ANALYSIS COMPLETE - Signal: {signal} (Urgency: {urgency})")
            logger.info("=" * 70)

            return {
                'timestamp': datetime.now().isoformat(),
                'signal': signal,
                'exit_score': exit_score,
                'urgency': urgency,
                'recommendation': recommendation,
                'exit_reasons': exit_reasons,
                'current_data': {
                    'score': current_score,
                    'nifty_spot': nifty_spot,
                    'vix': vix,
                    'market_regime': market_regime,
                    'oi_pattern': oi_analysis.get('pattern', 'UNKNOWN')
                },
                'entry_data': entry_data,
                'score_change': entry_score - current_score,
                'vix_change_pct': ((vix - entry_vix) / entry_vix * 100) if entry_vix > 0 else 0,
                'nifty_move_pct': ((nifty_spot - entry_nifty) / entry_nifty * 100) if entry_nifty > 0 else 0
            }

        except Exception as e:
            logger.error(f"Error in exit signal analysis: {e}", exc_info=True)
            return {
                'timestamp': datetime.now().isoformat(),
                'signal': 'ERROR',
                'error': str(e),
                'recommendation': f'Exit analysis failed: {e}'
            }


if __name__ == "__main__":
    # Test the analyzer
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    from token_manager import TokenManager

    # Initialize
    manager = TokenManager()
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Create analyzer
    analyzer = NiftyOptionAnalyzer(kite)

    # Run analysis
    result = analyzer.analyze_option_selling_opportunity()

    # Print results
    print("\n" + "=" * 70)
    print("NIFTY OPTION SELLING ANALYSIS RESULT")
    print("=" * 70)
    print(f"Signal: {result.get('signal')} (Score: {result.get('total_score', 0):.1f}/100)")
    print(f"NIFTY Spot: {result.get('nifty_spot', 0):.2f}")
    print(f"VIX: {result.get('vix', 0):.2f}")
    print(f"Market Regime: {result.get('market_regime', 'UNKNOWN')}")
    print(f"Best Strategy: {result.get('best_strategy', 'N/A').upper()}")
    print(f"\nRecommendation: {result.get('recommendation', '')}")
    print(f"\nRisk Factors:")
    for risk in result.get('risk_factors', []):
        print(f"  - {risk}")
    print("=" * 70)
