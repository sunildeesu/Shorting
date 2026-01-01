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

        # Cache for instruments
        self._nfo_instruments = None
        self._instruments_cache_time = None

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

            # Step 1: Get NIFTY spot price
            logger.info("Step 1: Fetching NIFTY spot price...")
            nifty_spot = self._get_nifty_spot_price()
            if not nifty_spot:
                raise ValueError("Unable to fetch NIFTY spot price")
            logger.info(f"NIFTY Spot: {nifty_spot:.2f}")

            # Step 2: Get India VIX
            logger.info("Step 2: Fetching India VIX...")
            vix = self._get_india_vix()
            if not vix:
                raise ValueError("Unable to fetch India VIX")
            logger.info(f"India VIX: {vix:.2f}")

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
                    market_regime=market_regime,
                    oi_analysis=oi_analysis
                )
                expiry_analyses.append(expiry_data)

            # Step 7: Generate overall recommendation
            logger.info("Step 7: Generating recommendation...")
            recommendation = self._generate_recommendation(
                nifty_spot=nifty_spot,
                vix=vix,
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
        """Get current NIFTY 50 spot price"""
        try:
            quote = self.kite.quote(["NSE:NIFTY 50"])
            nifty_data = quote.get("NSE:NIFTY 50", {})
            return nifty_data.get("last_price")
        except Exception as e:
            logger.error(f"Error fetching NIFTY spot: {e}")
            return None

    def _get_india_vix(self) -> Optional[float]:
        """Get current India VIX value"""
        try:
            quote = self.kite.quote(["NSE:INDIA VIX"])
            vix_data = quote.get("NSE:INDIA VIX", {})
            return vix_data.get("last_price")
        except Exception as e:
            logger.error(f"Error fetching India VIX: {e}")
            return None

    def _get_nifty_oi_analysis(self) -> Dict:
        """Get OI analysis for NIFTY futures"""
        try:
            # Get NIFTY futures quote for current month
            # Symbol format: NIFTY25JAN (year + month abbreviation)
            current_month = datetime.now()
            year_short = str(current_month.year)[-2:]
            month_abbr = current_month.strftime("%b").upper()

            # Try current month and next month futures
            for month_offset in [0, 1]:
                target_month = current_month + timedelta(days=30 * month_offset)
                year_short = str(target_month.year)[-2:]
                month_abbr = target_month.strftime("%b").upper()
                futures_symbol = f"NFO:NIFTY{year_short}{month_abbr}FUT"

                try:
                    quote = self.kite.quote([futures_symbol])
                    futures_data = quote.get(futures_symbol, {})

                    if futures_data:
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
                            return oi_result
                except:
                    continue

            # Default if no futures data found
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
        Get next N NIFTY expiry dates

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
            for option in nifty_options:
                expiry = option['expiry']
                if expiry >= datetime.now().date():
                    expiries.add(expiry)

            # Sort and return next N
            sorted_expiries = sorted(list(expiries))[:count]

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

            # Fetch option data for these strikes
            straddle_call = self._get_option_data('CE', expiry_date, straddle_strikes['call'])
            straddle_put = self._get_option_data('PE', expiry_date, straddle_strikes['put'])
            strangle_call = self._get_option_data('CE', expiry_date, strangle_strikes['call'])
            strangle_put = self._get_option_data('PE', expiry_date, strangle_strikes['put'])

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
                market_regime=market_regime,
                oi_analysis=oi_analysis
            )

            # Calculate scores for strangle
            strangle_score = self._calculate_option_score(
                greeks=strangle_greeks,
                vix=vix,
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

    def _get_option_data(
        self,
        option_type: str,
        expiry: datetime,
        strike: int
    ) -> Dict:
        """
        Get option data including premium and Greeks

        Args:
            option_type: 'CE' for call, 'PE' for put
            expiry: Expiry date
            strike: Strike price

        Returns:
            Dict with option data
        """
        try:
            # Build symbol: NIFTY25JAN24000CE
            year_short = str(expiry.year)[-2:]
            month_abbr = expiry.strftime("%b").upper()
            symbol = f"NFO:NIFTY{year_short}{month_abbr}{strike}{option_type}"

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
                greeks = self._approximate_greeks(
                    option_type=option_type,
                    spot=option_data.get('last_price', strike),  # Use option price as proxy
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
        market_regime: str,
        oi_analysis: Dict
    ) -> Dict:
        """
        Calculate composite score (0-100) for option selling conditions

        Scoring weights from config:
        - Theta: 25%
        - Gamma: 25%
        - VIX: 30%
        - Market Regime: 10%
        - OI Analysis: 10%

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

        # VIX scoring (0-100)
        vix_score = self._score_vix(vix)

        # Market regime scoring (0-100)
        regime_score = self._score_market_regime(market_regime)

        # OI scoring (0-100)
        oi_score = self._score_oi_pattern(oi_analysis.get('pattern', 'UNKNOWN'))

        # Calculate weighted total
        total_score = (
            theta_score * config.THETA_WEIGHT +
            gamma_score * config.GAMMA_WEIGHT +
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
            gamma=gamma,
            market_regime=market_regime,
            oi_pattern=oi_analysis.get('pattern', 'UNKNOWN')
        )

        return {
            'total_score': round(total_score, 1),
            'signal': signal,
            'breakdown': {
                'theta_score': round(theta_score, 1),
                'gamma_score': round(gamma_score, 1),
                'vix_score': round(vix_score, 1),
                'regime_score': round(regime_score, 1),
                'oi_score': round(oi_score, 1)
            },
            'recommendation': recommendation,
            'risk_factors': risk_factors
        }

    def _score_vix(self, vix: float) -> float:
        """Score VIX level (0-100)"""
        if vix < config.VIX_EXCELLENT:
            return 100
        elif vix < config.VIX_GOOD:
            return 75
        elif vix < config.VIX_MODERATE:
            return 40
        else:
            return 10

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
        gamma: float,
        market_regime: str,
        oi_pattern: str
    ) -> List[str]:
        """Identify risk factors for option selling"""
        risks = []

        if vix > config.VIX_MODERATE:
            risks.append(f"High VIX ({vix:.1f}) - elevated volatility")
        elif vix > config.VIX_GOOD:
            risks.append(f"VIX slightly elevated ({vix:.1f})")

        if gamma > config.MAX_GAMMA_THRESHOLD:
            risks.append(f"High gamma ({gamma:.4f}) - position unstable")

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

        return {
            'timestamp': datetime.now().isoformat(),
            'nifty_spot': nifty_spot,
            'vix': vix,
            'market_regime': market_regime,
            'oi_analysis': oi_analysis,
            'signal': best_score.get('signal', 'HOLD'),
            'total_score': best_score.get('total_score', 50),
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

            # Get current market data
            logger.info("Fetching current market data...")
            nifty_spot = self._get_nifty_spot_price()
            vix = self._get_india_vix()
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

            # 3. VIX spike
            if entry_vix > 0:
                vix_increase_pct = ((vix - entry_vix) / entry_vix) * 100
                if vix_increase_pct >= config.NIFTY_OPTION_EXIT_VIX_SPIKE:
                    exit_reasons.append(f"VIX spiked {vix_increase_pct:.1f}% (entry: {entry_vix:.2f} → current: {vix:.2f})")
                    exit_score += 35
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

            # 6. Large NIFTY move
            if entry_nifty > 0:
                nifty_move_pct = abs((nifty_spot - entry_nifty) / entry_nifty) * 100
                if nifty_move_pct > 2.0:  # > 2% move
                    exit_reasons.append(f"Large NIFTY move ({nifty_move_pct:.1f}% from entry)")
                    exit_score += 15
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
