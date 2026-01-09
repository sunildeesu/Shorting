#!/usr/bin/env python3
"""
Backtest 1-Minute Alerts for Last Week
Tests all trading days to find if any alerts would have been generated
"""

import json
import logging
from datetime import datetime, timedelta, time as dt_time, date
from typing import Dict, List
from kiteconnect import KiteConnect
import config
from price_cache import PriceCache
from onemin_alert_detector import OneMinAlertDetector
from alert_history_manager import AlertHistoryManager
import pytz

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Reduce noise
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class WeeklyBacktester:
    """Backtest 1-minute alerts for multiple days"""

    def __init__(self):
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Load F&O stocks
        with open(config.STOCK_LIST_FILE, 'r') as f:
            data = json.load(f)
            self.fo_stocks = data['stocks']

        # Build instrument token map
        self.instrument_tokens = self._build_instrument_token_map()

        print(f"✅ Initialized with {len(self.fo_stocks)} F&O stocks")

    def _build_instrument_token_map(self) -> Dict[str, int]:
        """Build mapping of stock symbol to instrument token"""
        try:
            instruments = self.kite.instruments("NSE")
            token_map = {}

            for instrument in instruments:
                if instrument['segment'] == 'NSE' and instrument['tradingsymbol'] in self.fo_stocks:
                    token_map[instrument['tradingsymbol']] = instrument['instrument_token']

            return token_map
        except Exception as e:
            print(f"❌ Error building instrument token map: {e}")
            return {}

    def get_trading_days(self, days_back: int = 7) -> List[date]:
        """Get list of trading days (Mon-Fri) for last N days"""
        ist = pytz.timezone('Asia/Kolkata')
        today = datetime.now(ist).date()

        trading_days = []
        for i in range(1, days_back + 10):  # Check extra days to get enough trading days
            day = today - timedelta(days=i)
            # Simple check: Monday=0, Friday=4
            if day.weekday() < 5:  # Mon-Fri
                trading_days.append(day)
                if len(trading_days) >= days_back:
                    break

        return sorted(trading_days)

    def fetch_1min_data(self, symbol: str, test_date: date) -> List[Dict]:
        """Fetch 1-minute candles for the test date"""
        if symbol not in self.instrument_tokens:
            return []

        try:
            instrument_token = self.instrument_tokens[symbol]

            # Fetch from 9:15 AM to 3:30 PM
            from_date = datetime.combine(test_date, dt_time(9, 15))
            to_date = datetime.combine(test_date, dt_time(15, 30))

            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="minute"
            )

            return data if data else []
        except Exception as e:
            return []

    def analyze_day(self, test_date: date, test_stocks: List[str]) -> Dict:
        """Analyze one trading day"""
        print(f"\n{'='*70}")
        print(f"📅 Testing: {test_date} ({test_date.strftime('%A')})")
        print(f"{'='*70}")

        # Track statistics
        price_movements = []  # All price movements >= 0.50%
        volume_failures = []  # Movements that failed volume check
        quality_failures = []  # Movements that failed quality checks
        cooldown_failures = []  # Movements that failed cooldown

        # Test each stock
        stocks_with_data = 0

        for idx, symbol in enumerate(test_stocks):
            candles = self.fetch_1min_data(symbol, test_date)

            if not candles or len(candles) < 10:
                continue

            stocks_with_data += 1

            # Analyze minute by minute
            for i in range(5, len(candles)):  # Start from minute 5 to have history
                current = candles[i]
                previous = candles[i-1]

                current_price = current['close']
                prev_price = previous['close']
                change_pct = abs((current_price - prev_price) / prev_price * 100)

                # Check if price movement meets threshold
                if change_pct >= config.DROP_THRESHOLD_1MIN:
                    # Calculate volume delta
                    current_vol = current['volume']
                    prev_vol = previous['volume']
                    vol_delta = current_vol - prev_vol

                    # Calculate average delta from recent history
                    recent_deltas = []
                    for j in range(max(1, i-5), i):
                        delta = candles[j]['volume'] - candles[j-1]['volume']
                        if delta > 0:
                            recent_deltas.append(delta)

                    avg_delta = sum(recent_deltas) / len(recent_deltas) if recent_deltas else 0

                    movement = {
                        'date': test_date,
                        'time': current['date'].strftime('%H:%M'),
                        'symbol': symbol,
                        'change_pct': change_pct,
                        'price': current_price,
                        'vol_delta': vol_delta,
                        'avg_delta': avg_delta,
                        'vol_ratio': vol_delta / avg_delta if avg_delta > 0 else 0
                    }

                    price_movements.append(movement)

                    # Check volume requirement
                    if avg_delta > 0:
                        if vol_delta < (avg_delta * config.VOLUME_SPIKE_MULTIPLIER_1MIN):
                            volume_failures.append(movement)
                        else:
                            # Check quality filters
                            if current_price < 50:
                                quality_failures.append(movement)
                            else:
                                # This would have been an alert!
                                print(f"🚨 ALERT: {symbol} at {movement['time']} - {change_pct:.2f}% (Vol: {vol_delta / avg_delta:.1f}x)")

            # Progress indicator
            if (idx + 1) % 50 == 0:
                print(f"  Progress: {idx + 1}/{len(test_stocks)} stocks checked...")

        # Summary for this day
        print(f"\n📊 Summary for {test_date}:")
        print(f"  Stocks with data: {stocks_with_data}")
        print(f"  Price movements >= {config.DROP_THRESHOLD_1MIN}%: {len(price_movements)}")
        print(f"  Failed volume check (< {config.VOLUME_SPIKE_MULTIPLIER_1MIN}x): {len(volume_failures)}")
        print(f"  Failed quality check (price < ₹50): {len(quality_failures)}")

        # Show closest near-misses (high volume ratio but below threshold)
        if volume_failures:
            sorted_failures = sorted(volume_failures, key=lambda x: x['vol_ratio'], reverse=True)
            print(f"\n  🔍 Top 5 near-misses (highest volume ratio):")
            for i, m in enumerate(sorted_failures[:5], 1):
                print(f"    {i}. {m['symbol']:12} at {m['time']} - {m['change_pct']:.2f}% "
                      f"(Vol: {m['vol_ratio']:.2f}x, need {config.VOLUME_SPIKE_MULTIPLIER_1MIN}x)")

        return {
            'date': test_date,
            'stocks_tested': len(test_stocks),
            'stocks_with_data': stocks_with_data,
            'price_movements': len(price_movements),
            'volume_failures': len(volume_failures),
            'quality_failures': len(quality_failures)
        }

    def run_weekly_backtest(self, days_back: int = 7, max_stocks: int = None) -> List[Dict]:
        """Run backtest for last N trading days"""
        print("="*70)
        print("🔍 1-MINUTE ALERT BACKTEST - LAST WEEK")
        print("="*70)
        print(f"Drop threshold: {config.DROP_THRESHOLD_1MIN}%")
        print(f"Rise threshold: {config.RISE_THRESHOLD_1MIN}%")
        print(f"Volume multiplier: {config.VOLUME_SPIKE_MULTIPLIER_1MIN}x")
        print(f"Min avg daily volume: {config.MIN_AVG_DAILY_VOLUME_1MIN:,}")

        # Get trading days
        trading_days = self.get_trading_days(days_back)
        print(f"\n📅 Testing {len(trading_days)} trading days:")
        for day in trading_days:
            print(f"  • {day} ({day.strftime('%A')})")

        # Select stocks to test
        test_stocks = self.fo_stocks[:max_stocks] if max_stocks else self.fo_stocks
        print(f"\n📊 Testing {len(test_stocks)} stocks per day")

        # Test each day
        results = []
        for test_date in trading_days:
            result = self.analyze_day(test_date, test_stocks)
            results.append(result)

        # Overall summary
        print(f"\n{'='*70}")
        print("📈 WEEKLY SUMMARY")
        print(f"{'='*70}")

        total_movements = sum(r['price_movements'] for r in results)
        total_volume_failures = sum(r['volume_failures'] for r in results)
        total_quality_failures = sum(r['quality_failures'] for r in results)

        print(f"Total trading days tested: {len(trading_days)}")
        print(f"Total price movements >= {config.DROP_THRESHOLD_1MIN}%: {total_movements}")
        print(f"Failed volume check: {total_volume_failures} ({total_volume_failures/max(1,total_movements)*100:.1f}%)")
        print(f"Failed quality check: {total_quality_failures} ({total_quality_failures/max(1,total_movements)*100:.1f}%)")
        print(f"\n💡 Main blocker: Volume spike requirement ({config.VOLUME_SPIKE_MULTIPLIER_1MIN}x average)")

        return results


if __name__ == "__main__":
    backtester = WeeklyBacktester()

    # Test last 7 trading days with all stocks
    results = backtester.run_weekly_backtest(days_back=7, max_stocks=None)

    print(f"\n✅ Backtest complete!")
