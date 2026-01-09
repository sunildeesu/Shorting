#!/usr/bin/env python3
"""
Black-Scholes Greeks Calculator

Calculates option Greeks (Delta, Theta, Vega, Gamma) using Black-Scholes model.
Used when Greeks are not provided by the API.
"""

import math
from datetime import datetime, date
from typing import Dict, Union
from scipy.stats import norm
import numpy as np


class BlackScholesGreeks:
    """
    Black-Scholes option pricing and Greeks calculator
    """

    def __init__(self, risk_free_rate: float = 0.065):
        """
        Initialize Black-Scholes calculator.

        Args:
            risk_free_rate: Annual risk-free rate (default 6.5% for India)
        """
        self.risk_free_rate = risk_free_rate

    def calculate_greeks(
        self,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        volatility: float,
        option_type: str,
        option_price: float = None
    ) -> Dict[str, float]:
        """
        Calculate all Greeks for an option.

        Args:
            spot_price: Current price of underlying
            strike_price: Strike price of option
            time_to_expiry: Time to expiry in years
            volatility: Implied volatility (annualized)
            option_type: 'CE' for call, 'PE' for put
            option_price: Current option price (optional, for IV calibration)

        Returns:
            Dict with delta, theta, vega, gamma
        """
        # Handle edge cases
        if time_to_expiry <= 0:
            return self._get_zero_greeks()

        if volatility <= 0:
            volatility = 0.15  # Default 15% if invalid

        # Calculate d1 and d2
        d1, d2 = self._calculate_d1_d2(
            spot_price, strike_price, time_to_expiry, volatility
        )

        # Calculate Greeks
        if option_type == 'CE':
            delta = self._calculate_call_delta(d1)
            theta = self._calculate_call_theta(
                spot_price, strike_price, time_to_expiry, volatility, d1, d2
            )
        else:  # PE
            delta = self._calculate_put_delta(d1)
            theta = self._calculate_put_theta(
                spot_price, strike_price, time_to_expiry, volatility, d1, d2
            )

        # Vega and Gamma are same for calls and puts
        vega = self._calculate_vega(spot_price, time_to_expiry, d1)
        gamma = self._calculate_gamma(spot_price, time_to_expiry, volatility, d1)

        return {
            'delta': round(delta, 4),
            'theta': round(theta, 4),
            'vega': round(vega, 4),
            'gamma': round(gamma, 6)
        }

    def calculate_greeks_from_price(
        self,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        option_price: float,
        option_type: str
    ) -> Dict[str, float]:
        """
        Calculate Greeks by first deriving IV from option price.

        Args:
            spot_price: Current price of underlying
            strike_price: Strike price
            time_to_expiry: Time to expiry in years
            option_price: Current market price of option
            option_type: 'CE' or 'PE'

        Returns:
            Dict with delta, theta, vega, gamma, implied_vol
        """
        # Calculate implied volatility from option price
        iv = self._calculate_implied_volatility(
            spot_price, strike_price, time_to_expiry, option_price, option_type
        )

        # Calculate Greeks using derived IV
        greeks = self.calculate_greeks(
            spot_price, strike_price, time_to_expiry, iv, option_type
        )

        greeks['implied_vol'] = round(iv, 4)
        return greeks

    def _calculate_d1_d2(
        self,
        spot: float,
        strike: float,
        time: float,
        vol: float
    ) -> tuple:
        """Calculate d1 and d2 for Black-Scholes formula"""
        d1 = (math.log(spot / strike) + (self.risk_free_rate + 0.5 * vol ** 2) * time) / (vol * math.sqrt(time))
        d2 = d1 - vol * math.sqrt(time)
        return d1, d2

    def _calculate_call_delta(self, d1: float) -> float:
        """Calculate delta for call option"""
        return norm.cdf(d1)

    def _calculate_put_delta(self, d1: float) -> float:
        """Calculate delta for put option"""
        return norm.cdf(d1) - 1

    def _calculate_call_theta(
        self,
        spot: float,
        strike: float,
        time: float,
        vol: float,
        d1: float,
        d2: float
    ) -> float:
        """Calculate theta for call option (per day)"""
        term1 = -(spot * norm.pdf(d1) * vol) / (2 * math.sqrt(time))
        term2 = self.risk_free_rate * strike * math.exp(-self.risk_free_rate * time) * norm.cdf(d2)
        theta_annual = term1 - term2
        return theta_annual / 365  # Convert to per day

    def _calculate_put_theta(
        self,
        spot: float,
        strike: float,
        time: float,
        vol: float,
        d1: float,
        d2: float
    ) -> float:
        """Calculate theta for put option (per day)"""
        term1 = -(spot * norm.pdf(d1) * vol) / (2 * math.sqrt(time))
        term2 = self.risk_free_rate * strike * math.exp(-self.risk_free_rate * time) * norm.cdf(-d2)
        theta_annual = term1 + term2
        return theta_annual / 365  # Convert to per day

    def _calculate_vega(self, spot: float, time: float, d1: float) -> float:
        """Calculate vega (sensitivity to 1% change in volatility)"""
        vega = spot * norm.pdf(d1) * math.sqrt(time)
        return vega / 100  # Convert to per 1% change

    def _calculate_gamma(self, spot: float, time: float, vol: float, d1: float) -> float:
        """Calculate gamma"""
        return norm.pdf(d1) / (spot * vol * math.sqrt(time))

    def _calculate_implied_volatility(
        self,
        spot: float,
        strike: float,
        time: float,
        option_price: float,
        option_type: str,
        max_iterations: int = 100,
        tolerance: float = 0.0001
    ) -> float:
        """
        Calculate implied volatility using Newton-Raphson method.

        Args:
            spot: Spot price
            strike: Strike price
            time: Time to expiry (years)
            option_price: Market price of option
            option_type: 'CE' or 'PE'
            max_iterations: Max iterations for convergence
            tolerance: Convergence tolerance

        Returns:
            Implied volatility (annualized)
        """
        # Initial guess
        vol = 0.20  # Start with 20%

        for i in range(max_iterations):
            # Calculate option price with current vol
            d1, d2 = self._calculate_d1_d2(spot, strike, time, vol)

            if option_type == 'CE':
                calculated_price = self._call_price(spot, strike, time, d1, d2)
            else:
                calculated_price = self._put_price(spot, strike, time, d1, d2)

            # Calculate vega for Newton-Raphson
            vega = self._calculate_vega(spot, time, d1) * 100  # Convert back to full vega

            # Check convergence
            price_diff = calculated_price - option_price

            if abs(price_diff) < tolerance:
                return vol

            # Newton-Raphson update
            if vega > 0:
                vol = vol - price_diff / vega
            else:
                break

            # Ensure vol stays positive
            vol = max(0.01, min(2.0, vol))  # Clamp between 1% and 200%

        # If didn't converge, return reasonable default
        return 0.20

    def _call_price(self, spot: float, strike: float, time: float, d1: float, d2: float) -> float:
        """Calculate Black-Scholes call option price"""
        return spot * norm.cdf(d1) - strike * math.exp(-self.risk_free_rate * time) * norm.cdf(d2)

    def _put_price(self, spot: float, strike: float, time: float, d1: float, d2: float) -> float:
        """Calculate Black-Scholes put option price"""
        return strike * math.exp(-self.risk_free_rate * time) * norm.cdf(-d2) - spot * norm.cdf(-d1)

    def _get_zero_greeks(self) -> Dict[str, float]:
        """Return zero Greeks for expired/invalid options"""
        return {
            'delta': 0.0,
            'theta': 0.0,
            'vega': 0.0,
            'gamma': 0.0
        }

    @staticmethod
    def calculate_time_to_expiry(expiry_date: Union[date, datetime]) -> float:
        """
        Calculate time to expiry in years.

        Args:
            expiry_date: Expiry date

        Returns:
            Time to expiry in years
        """
        if isinstance(expiry_date, datetime):
            expiry_date = expiry_date.date()

        today = datetime.now().date()
        days_to_expiry = (expiry_date - today).days

        # Use trading days convention (252 trading days per year)
        return max(0, days_to_expiry / 365.0)

    @staticmethod
    def estimate_volatility_from_vix(vix: float) -> float:
        """
        Estimate NIFTY option volatility from India VIX.

        Args:
            vix: India VIX value

        Returns:
            Estimated volatility (annualized)
        """
        # India VIX is already annualized volatility
        return vix / 100.0


# Convenience functions
def calculate_option_greeks(
    spot_price: float,
    strike_price: float,
    expiry_date: Union[date, datetime],
    option_price: float,
    option_type: str,
    volatility: float = None
) -> Dict[str, float]:
    """
    Convenience function to calculate Greeks.

    Args:
        spot_price: Current spot price
        strike_price: Strike price
        expiry_date: Expiry date
        option_price: Current option price
        option_type: 'CE' or 'PE'
        volatility: Implied volatility (optional, will be derived from price)

    Returns:
        Dict with delta, theta, vega, gamma
    """
    bs = BlackScholesGreeks()
    time_to_expiry = bs.calculate_time_to_expiry(expiry_date)

    if volatility is None:
        # Derive IV from option price
        return bs.calculate_greeks_from_price(
            spot_price, strike_price, time_to_expiry, option_price, option_type
        )
    else:
        # Use provided volatility
        return bs.calculate_greeks(
            spot_price, strike_price, time_to_expiry, volatility, option_type
        )


if __name__ == '__main__':
    # Test the calculator
    print("=" * 60)
    print("BLACK-SCHOLES GREEKS CALCULATOR - TEST")
    print("=" * 60)

    # Example: NIFTY ATM option
    spot = 23500
    strike = 23500
    expiry = datetime(2026, 1, 16).date()
    option_price = 150
    option_type = 'CE'

    print(f"\nInput:")
    print(f"  Spot: {spot}")
    print(f"  Strike: {strike}")
    print(f"  Expiry: {expiry}")
    print(f"  Option Price: {option_price}")
    print(f"  Type: {option_type}")

    greeks = calculate_option_greeks(spot, strike, expiry, option_price, option_type)

    print(f"\nCalculated Greeks:")
    print(f"  Delta: {greeks['delta']:.4f}")
    print(f"  Theta: {greeks['theta']:.4f} (per day)")
    print(f"  Vega: {greeks['vega']:.4f} (per 1% IV change)")
    print(f"  Gamma: {greeks['gamma']:.6f}")
    if 'implied_vol' in greeks:
        print(f"  Implied Vol: {greeks['implied_vol'] * 100:.2f}%")

    print("\n" + "=" * 60)
