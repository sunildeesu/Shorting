#!/usr/bin/env python3
"""
Greeks Difference Tracker - 1 Week Backtest

Backtests the Greeks Difference tracking system for the last 1 week using real market data.
Analyzes if Greeks differences can predict market direction (Bullish/Bearish/Neutral).
"""

import os
import sys
from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple
import pandas as pd
from kiteconnect import KiteConnect

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from black_scholes_greeks import BlackScholesGreeks


class GreeksBacktest:
    """Backtest Greeks Difference Tracker with historical data"""

    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self.bs_calculator = BlackScholesGreeks()
        self.results = []
        self.vix_cache = {}  # Cache VIX data by date

    def get_trading_days(self, days_back: int = 7) -> List[datetime]:
        """Get list of trading days for last N days (excluding weekends)"""
        trading_days = []
        current_date = datetime.now().date()

        for i in range(1, days_back + 10):  # Extra days to account for weekends
            date = current_date - timedelta(days=i)

            # Skip weekends
            if date.weekday() >= 5:
                continue

            trading_days.append(date)

            if len(trading_days) >= days_back:
                break

        return sorted(trading_days)

    def fetch_india_vix(self, date: datetime) -> float:
        """
        Fetch India VIX for a specific date.

        Args:
            date: Trading date

        Returns:
            VIX value as decimal (e.g., 0.15 for 15%)
        """
        # Check cache first
        date_key = date.strftime('%Y-%m-%d')
        if date_key in self.vix_cache:
            return self.vix_cache[date_key]

        try:
            # India VIX instrument token
            vix_instrument_token = 264969  # INDIA VIX

            from_date = datetime.combine(date, time(9, 15))
            to_date = datetime.combine(date, time(15, 30))

            # Get historical VIX data
            vix_data = self.kite.historical_data(
                instrument_token=vix_instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval='15minute'
            )

            if not vix_data:
                print(f"⚠️  No VIX data for {date.strftime('%Y-%m-%d')}, using default 15%")
                return 0.15

            # Use opening VIX (9:15 AM) as the baseline
            opening_vix = vix_data[0]['close']
            vix_decimal = opening_vix / 100.0  # Convert from 15 to 0.15

            # Cache it
            self.vix_cache[date_key] = vix_decimal

            print(f"   ✓ India VIX ({date.strftime('%Y-%m-%d')}): {opening_vix:.2f}%")
            return vix_decimal

        except Exception as e:
            print(f"⚠️  Error fetching VIX for {date}: {e}, using default 15%")
            return 0.15

    def fetch_nifty_historical(self, date: datetime) -> pd.DataFrame:
        """
        Fetch NIFTY historical data for a specific date.

        Args:
            date: Trading date

        Returns:
            DataFrame with OHLC + timestamp data
        """
        try:
            # Fetch minute data for the trading day
            from_date = datetime.combine(date, time(9, 15))
            to_date = datetime.combine(date, time(15, 30))

            # Get historical data from Kite
            instrument_token = 256265  # NIFTY 50 instrument token

            historical_data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval='15minute'
            )

            if not historical_data:
                print(f"⚠️  No data for {date.strftime('%Y-%m-%d')}")
                return pd.DataFrame()

            df = pd.DataFrame(historical_data)
            return df

        except Exception as e:
            print(f"❌ Error fetching NIFTY data for {date}: {e}")
            return pd.DataFrame()

    def calculate_atm_strike(self, spot_price: float) -> int:
        """Calculate ATM strike (round to nearest 50)"""
        return int(round(spot_price / 50.0) * 50)

    def get_option_expiry(self, date: datetime) -> datetime:
        """Get next week expiry for given date"""
        # For simplicity, assume next Thursday (weekly expiry)
        days_ahead = 3 - date.weekday()  # Thursday = 3
        if days_ahead <= 0:
            days_ahead += 7

        expiry = date + timedelta(days=days_ahead)

        # Ensure expiry is at least 7 days away
        if (expiry - date).days < 7:
            expiry += timedelta(days=7)

        return expiry

    def simulate_day_greeks(self, date: datetime, nifty_data: pd.DataFrame) -> Dict:
        """
        Simulate Greeks tracking for one trading day.

        Args:
            date: Trading date
            nifty_data: Historical NIFTY data for the day

        Returns:
            Dict with baseline, EOD Greeks, and differences
        """
        if nifty_data.empty or len(nifty_data) < 2:
            return None

        # Baseline (9:15 AM - first candle)
        baseline_spot = nifty_data.iloc[0]['close']
        baseline_atm = self.calculate_atm_strike(baseline_spot)

        # EOD (3:30 PM - last candle)
        eod_spot = nifty_data.iloc[-1]['close']

        # Calculate expiry
        expiry = self.get_option_expiry(date)

        # Fetch real India VIX for this date
        volatility = self.fetch_india_vix(date)

        # Calculate Greeks for baseline (9:15 AM)
        baseline_greeks = self.calculate_greeks_for_strikes(
            spot=baseline_spot,
            atm_strike=baseline_atm,
            expiry=expiry,
            date=date,
            volatility=volatility
        )

        # Calculate Greeks for EOD (3:30 PM)
        eod_greeks = self.calculate_greeks_for_strikes(
            spot=eod_spot,
            atm_strike=baseline_atm,  # Use same strikes as baseline
            expiry=expiry,
            date=date,
            volatility=volatility
        )

        # Calculate differences
        differences = self.calculate_differences(baseline_greeks, eod_greeks)

        # Aggregate by CE/PE
        aggregated = self.aggregate_by_type(differences)

        return {
            'date': date,
            'baseline_spot': baseline_spot,
            'eod_spot': eod_spot,
            'price_change': eod_spot - baseline_spot,
            'price_change_pct': ((eod_spot - baseline_spot) / baseline_spot) * 100,
            'atm_strike': baseline_atm,
            'expiry': expiry,
            'baseline_greeks': baseline_greeks,
            'eod_greeks': eod_greeks,
            'differences': differences,
            'aggregated': aggregated,
            'candles': len(nifty_data)
        }

    def calculate_greeks_for_strikes(
        self,
        spot: float,
        atm_strike: int,
        expiry: datetime,
        date: datetime,
        volatility: float
    ) -> Dict:
        """
        Calculate Greeks for ATM and OTM strikes.

        Args:
            spot: NIFTY spot price
            atm_strike: ATM strike price
            expiry: Expiry date
            date: Current date
            volatility: Real India VIX volatility

        Returns:
            Dict with Greeks for each strike
        """
        strikes_data = {}
        strike_offsets = [0, 50, 100, 150]  # ATM, ATM+50, ATM+100, ATM+150

        # Calculate time to expiry RELATIVE TO THE BACKTEST DATE (not today)
        days_to_expiry = (expiry - date).days
        time_to_expiry = max(0.02, days_to_expiry / 365.0)  # Minimum 1 week

        # Estimate option prices (simplified - using intrinsic + time value)
        for offset in strike_offsets:
            # CE strikes
            ce_strike = atm_strike + offset
            ce_price = self.estimate_option_price(spot, ce_strike, time_to_expiry, 'CE', volatility)

            ce_greeks = self.bs_calculator.calculate_greeks_from_price(
                spot_price=spot,
                strike_price=ce_strike,
                time_to_expiry=time_to_expiry,
                option_price=ce_price,
                option_type='CE'
            )

            # PE strikes
            if offset == 0:
                pe_strike = atm_strike
            else:
                pe_strike = atm_strike - offset

            pe_price = self.estimate_option_price(spot, pe_strike, time_to_expiry, 'PE', volatility)

            pe_greeks = self.bs_calculator.calculate_greeks_from_price(
                spot_price=spot,
                strike_price=pe_strike,
                time_to_expiry=time_to_expiry,
                option_price=pe_price,
                option_type='PE'
            )

            strikes_data[ce_strike] = {
                'CE': ce_greeks,
                'PE': pe_greeks
            }

        return strikes_data

    def estimate_option_price(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,
        option_type: str,
        volatility: float
    ) -> float:
        """Estimate option price using simplified Black-Scholes"""
        import math
        from scipy.stats import norm

        # Safety check for time to expiry
        if time_to_expiry <= 0.001:  # Less than ~8 hours
            # Return intrinsic value only
            if option_type == 'CE':
                return max(0.05, spot - strike)
            else:  # PE
                return max(0.05, strike - spot)

        d1 = (math.log(spot / strike) + (0.065 + 0.5 * volatility ** 2) * time_to_expiry) / (
            volatility * math.sqrt(time_to_expiry)
        )
        d2 = d1 - volatility * math.sqrt(time_to_expiry)

        if option_type == 'CE':
            price = spot * norm.cdf(d1) - strike * math.exp(-0.065 * time_to_expiry) * norm.cdf(d2)
        else:  # PE
            price = strike * math.exp(-0.065 * time_to_expiry) * norm.cdf(-d2) - spot * norm.cdf(-d1)

        return max(0.05, price)

    def calculate_differences(self, baseline: Dict, current: Dict) -> Dict:
        """Calculate differences between current and baseline Greeks"""
        differences = {}

        for strike in baseline.keys():
            if strike not in current:
                continue

            differences[strike] = {}

            for opt_type in ['CE', 'PE']:
                differences[strike][opt_type] = {
                    'delta': current[strike][opt_type]['delta'] - baseline[strike][opt_type]['delta'],
                    'theta': current[strike][opt_type]['theta'] - baseline[strike][opt_type]['theta'],
                    'vega': current[strike][opt_type]['vega'] - baseline[strike][opt_type]['vega']
                }

        return differences

    def aggregate_by_type(self, differences: Dict) -> Dict:
        """Aggregate differences by CE/PE"""
        ce_sums = {'delta_diff_sum': 0, 'theta_diff_sum': 0, 'vega_diff_sum': 0}
        pe_sums = {'delta_diff_sum': 0, 'theta_diff_sum': 0, 'vega_diff_sum': 0}

        for strike, data in differences.items():
            ce_sums['delta_diff_sum'] += data['CE']['delta']
            ce_sums['theta_diff_sum'] += data['CE']['theta']
            ce_sums['vega_diff_sum'] += data['CE']['vega']

            pe_sums['delta_diff_sum'] += data['PE']['delta']
            pe_sums['theta_diff_sum'] += data['PE']['theta']
            pe_sums['vega_diff_sum'] += data['PE']['vega']

        return {'CE': ce_sums, 'PE': pe_sums}

    def predict_direction(self, aggregated: Dict) -> str:
        """
        Predict market direction based on Greeks differences.

        REVISED Logic (based on backtest observations):
        - Both CE & PE Delta increase → Bullish (market moved up, all deltas increase)
        - Both CE & PE Delta decrease → Bearish (market moved down, all deltas decrease)
        - Opposite movements or small changes → Neutral
        - Both Vega spike → High Volatility

        Args:
            aggregated: Aggregated Greeks differences

        Returns:
            'Bullish', 'Bearish', or 'Neutral'
        """
        ce_delta = aggregated['CE']['delta_diff_sum']
        pe_delta = aggregated['PE']['delta_diff_sum']
        ce_vega = aggregated['CE']['vega_diff_sum']
        pe_vega = aggregated['PE']['vega_diff_sum']

        # Calculate average delta change
        avg_delta = (ce_delta + pe_delta) / 2

        # High volatility scenario (both Vega spiking significantly)
        if abs(ce_vega) > 10 and abs(pe_vega) > 10:
            return 'Neutral (High Vol)'

        # REVISED: Both deltas moving in same direction (more reliable signal)
        # Bullish: Both CE & PE deltas increase (market up, all options gain delta)
        if ce_delta > 0.05 and pe_delta > 0.05:
            return 'Bullish'

        # Bearish: Both CE & PE deltas decrease (market down, all options lose delta)
        if ce_delta < -0.05 and pe_delta < -0.05:
            return 'Bearish'

        # Neutral: opposite movements, small changes, or mixed signals
        return 'Neutral'

    def run_backtest(self, days: int = 7):
        """Run backtest for last N trading days"""
        print("=" * 80)
        print("GREEKS DIFFERENCE TRACKER - 1 WEEK BACKTEST")
        print("=" * 80)

        # Get trading days
        trading_days = self.get_trading_days(days)

        print(f"\n📅 Backtesting {len(trading_days)} trading days:")
        for day in trading_days:
            print(f"   - {day.strftime('%Y-%m-%d (%A)')}")

        print("\n" + "=" * 80)

        # Backtest each day
        for date in trading_days:
            print(f"\n{'=' * 80}")
            print(f"📆 {date.strftime('%Y-%m-%d (%A)')}")
            print(f"{'=' * 80}")

            # Fetch NIFTY data
            nifty_data = self.fetch_nifty_historical(date)

            if nifty_data.empty:
                print(f"⚠️  Skipping {date} - no data available")
                continue

            # Simulate day's Greeks tracking
            day_result = self.simulate_day_greeks(date, nifty_data)

            if not day_result:
                print(f"⚠️  Skipping {date} - insufficient data")
                continue

            # Predict direction
            predicted = self.predict_direction(day_result['aggregated'])
            actual = 'Bullish' if day_result['price_change'] > 0 else ('Bearish' if day_result['price_change'] < 0 else 'Neutral')

            # Check if prediction matches
            correct = (predicted.startswith('Bullish') and actual == 'Bullish') or \
                     (predicted.startswith('Bearish') and actual == 'Bearish') or \
                     (predicted == 'Neutral' and actual == 'Neutral')

            # Display results
            print(f"\n📊 NIFTY Movement:")
            print(f"   Open (9:15 AM): {day_result['baseline_spot']:.2f}")
            print(f"   Close (3:30 PM): {day_result['eod_spot']:.2f}")
            print(f"   Change: {day_result['price_change']:+.2f} ({day_result['price_change_pct']:+.2f}%)")
            print(f"   Actual Direction: {actual}")

            print(f"\n🧮 Greeks Differences (EOD vs Baseline):")
            agg = day_result['aggregated']
            print(f"   CE: Δ={agg['CE']['delta_diff_sum']:+.4f}, Θ={agg['CE']['theta_diff_sum']:+.2f}, V={agg['CE']['vega_diff_sum']:+.2f}")
            print(f"   PE: Δ={agg['PE']['delta_diff_sum']:+.4f}, Θ={agg['PE']['theta_diff_sum']:+.2f}, V={agg['PE']['vega_diff_sum']:+.2f}")

            print(f"\n🎯 Prediction:")
            print(f"   Predicted: {predicted}")
            print(f"   Actual: {actual}")
            print(f"   Result: {'✅ CORRECT' if correct else '❌ WRONG'}")

            # Store result
            self.results.append({
                'date': date,
                'baseline_spot': day_result['baseline_spot'],
                'eod_spot': day_result['eod_spot'],
                'price_change': day_result['price_change'],
                'price_change_pct': day_result['price_change_pct'],
                'predicted': predicted,
                'actual': actual,
                'correct': correct,
                'ce_delta_diff': agg['CE']['delta_diff_sum'],
                'ce_vega_diff': agg['CE']['vega_diff_sum'],
                'pe_delta_diff': agg['PE']['delta_diff_sum'],
                'pe_vega_diff': agg['PE']['vega_diff_sum']
            })

        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print backtest summary"""
        if not self.results:
            print("\n❌ No results to summarize")
            return

        print(f"\n{'=' * 80}")
        print("📈 BACKTEST SUMMARY")
        print(f"{'=' * 80}")

        # Calculate accuracy
        total = len(self.results)
        correct = sum(1 for r in self.results if r['correct'])
        accuracy = (correct / total) * 100 if total > 0 else 0

        print(f"\n🎯 Prediction Accuracy:")
        print(f"   Total Days: {total}")
        print(f"   Correct: {correct}")
        print(f"   Wrong: {total - correct}")
        print(f"   Accuracy: {accuracy:.1f}%")

        # Day-by-day summary
        print(f"\n📅 Day-by-Day Results:")
        print(f"   {'Date':<12} {'NIFTY Chg':<12} {'Predicted':<20} {'Actual':<10} {'Result'}")
        print(f"   {'-' * 70}")

        for r in self.results:
            result_icon = '✅' if r['correct'] else '❌'
            change_str = f"{r['price_change']:+7.2f} ({r['price_change_pct']:+.2f}%)"
            print(f"   {r['date'].strftime('%Y-%m-%d'):<12} "
                  f"{change_str:<20} "
                  f"{r['predicted']:<20} {r['actual']:<10} {result_icon}")

        print(f"\n{'=' * 80}")


def main():
    """Main entry point"""
    print("\nInitializing backtest...")

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Create backtest
    backtest = GreeksBacktest(kite)

    # Run 1-week backtest
    backtest.run_backtest(days=5)  # 5 trading days = 1 week

    print("\n✅ Backtest complete!")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Backtest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
