#!/usr/bin/env python3
"""
Backtest 1-Minute Alerts for Yesterday
Tests the fixed volume spike logic against yesterday's market data
"""

import json
import logging
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List
from kiteconnect import KiteConnect
import config
from price_cache import PriceCache
from onemin_alert_detector import OneMinAlertDetector
from alert_history_manager import AlertHistoryManager
import pytz

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OneMinBacktester:
    """Backtest 1-minute alerts for a specific date"""

    def __init__(self, test_date: datetime.date):
        self.test_date = test_date
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Load F&O stocks
        with open(config.STOCK_LIST_FILE, 'r') as f:
            data = json.load(f)
            self.fo_stocks = data['stocks']

        # Build instrument token map
        self.instrument_tokens = self._build_instrument_token_map()

        # Initialize price cache and alert detector
        self.price_cache = PriceCache()
        self.alert_history = AlertHistoryManager()
        self.alert_detector = OneMinAlertDetector(self.price_cache, self.alert_history)

        logger.info(f"Backtester initialized for {test_date}")
        logger.info(f"Loaded {len(self.fo_stocks)} F&O stocks")

    def _build_instrument_token_map(self) -> Dict[str, int]:
        """Build mapping of stock symbol to instrument token"""
        try:
            instruments = self.kite.instruments("NSE")
            token_map = {}

            for instrument in instruments:
                if instrument['segment'] == 'NSE' and instrument['tradingsymbol'] in self.fo_stocks:
                    token_map[instrument['tradingsymbol']] = instrument['instrument_token']

            logger.info(f"Built token map for {len(token_map)} stocks")
            return token_map
        except Exception as e:
            logger.error(f"Error building instrument token map: {e}")
            return {}

    def fetch_1min_data(self, symbol: str) -> List[Dict]:
        """Fetch 1-minute candles for the test date"""
        if symbol not in self.instrument_tokens:
            return []

        try:
            instrument_token = self.instrument_tokens[symbol]

            # Fetch from 9:15 AM to 3:30 PM
            from_date = datetime.combine(self.test_date, dt_time(9, 15))
            to_date = datetime.combine(self.test_date, dt_time(15, 30))

            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="minute"
            )

            return data if data else []
        except Exception as e:
            logger.debug(f"{symbol}: Error fetching data - {e}")
            return []

    def simulate_minute_by_minute(self, symbol: str, candles: List[Dict]) -> List[Dict]:
        """Simulate minute-by-minute updates and detect alerts"""
        alerts = []

        if len(candles) < 5:
            return alerts

        # Replay candles minute by minute
        for i in range(len(candles)):
            current_candle = candles[i]
            current_price = current_candle['close']
            current_volume = current_candle['volume']

            # Get price from 1 minute ago
            price_1min_ago = candles[i-1]['close'] if i > 0 else None

            # Get price from 5 minutes ago (for momentum check)
            price_5min_ago = candles[i-5]['close'] if i >= 5 else None

            if price_1min_ago is None:
                continue

            # Update price cache (simulate real-time updates)
            timestamp = current_candle['date'].strftime('%Y-%m-%d %H:%M:%S')

            # Update current
            if symbol not in self.price_cache.cache:
                self.price_cache.cache[symbol] = {}

            # Shift snapshots
            self.price_cache.cache[symbol]['previous_1min'] = self.price_cache.cache[symbol].get('current')
            self.price_cache.cache[symbol]['current'] = {
                'price': current_price,
                'volume': current_volume,
                'timestamp': timestamp
            }

            # Check for drop alert
            drop_priority = self.alert_detector.check_for_drop_1min(
                symbol, current_price, price_1min_ago, current_volume,
                oi=0, price_5min_ago=price_5min_ago
            )

            if drop_priority:
                change_pct = ((current_price - price_1min_ago) / price_1min_ago) * 100
                alerts.append({
                    'symbol': symbol,
                    'time': timestamp,
                    'direction': 'DROP',
                    'priority': drop_priority,
                    'price': current_price,
                    'change_pct': abs(change_pct),
                    'volume': current_volume
                })
                logger.info(f"🔴 {drop_priority} DROP: {symbol} at {timestamp} - {abs(change_pct):.2f}% (₹{price_1min_ago:.2f} → ₹{current_price:.2f})")

            # Check for rise alert
            if config.ENABLE_RISE_ALERTS:
                rise_priority = self.alert_detector.check_for_rise_1min(
                    symbol, current_price, price_1min_ago, current_volume,
                    oi=0, price_5min_ago=price_5min_ago
                )

                if rise_priority:
                    change_pct = ((current_price - price_1min_ago) / price_1min_ago) * 100
                    alerts.append({
                        'symbol': symbol,
                        'time': timestamp,
                        'direction': 'RISE',
                        'priority': rise_priority,
                        'price': current_price,
                        'change_pct': abs(change_pct),
                        'volume': current_volume
                    })
                    logger.info(f"🟢 {rise_priority} RISE: {symbol} at {timestamp} - {change_pct:.2f}% (₹{price_1min_ago:.2f} → ₹{current_price:.2f})")

        return alerts

    def run_backtest(self, max_stocks: int = 20) -> Dict:
        """Run backtest for yesterday"""
        logger.info("="*70)
        logger.info(f"BACKTESTING 1-MINUTE ALERTS: {self.test_date}")
        logger.info("="*70)

        all_alerts = []
        stocks_processed = 0
        stocks_with_data = 0

        # Test on subset for speed (or all stocks)
        test_stocks = self.fo_stocks[:max_stocks] if max_stocks else self.fo_stocks

        for symbol in test_stocks:
            stocks_processed += 1

            # Fetch 1-minute data
            candles = self.fetch_1min_data(symbol)

            if not candles:
                continue

            stocks_with_data += 1
            logger.info(f"[{stocks_processed}/{len(test_stocks)}] {symbol}: {len(candles)} candles")

            # Simulate minute-by-minute
            alerts = self.simulate_minute_by_minute(symbol, candles)
            all_alerts.extend(alerts)

        # Summary
        logger.info("="*70)
        logger.info("BACKTEST SUMMARY")
        logger.info("="*70)
        logger.info(f"Date: {self.test_date}")
        logger.info(f"Stocks tested: {stocks_processed}")
        logger.info(f"Stocks with data: {stocks_with_data}")
        logger.info(f"Total alerts: {len(all_alerts)}")

        # Breakdown by direction and priority
        drops = [a for a in all_alerts if a['direction'] == 'DROP']
        rises = [a for a in all_alerts if a['direction'] == 'RISE']

        high_priority_drops = [a for a in drops if a['priority'] == 'HIGH']
        normal_priority_drops = [a for a in drops if a['priority'] == 'NORMAL']

        high_priority_rises = [a for a in rises if a['priority'] == 'HIGH']
        normal_priority_rises = [a for a in rises if a['priority'] == 'NORMAL']

        logger.info(f"")
        logger.info(f"DROPS: {len(drops)} total")
        logger.info(f"  HIGH priority: {len(high_priority_drops)}")
        logger.info(f"  NORMAL priority: {len(normal_priority_drops)}")
        logger.info(f"")
        logger.info(f"RISES: {len(rises)} total")
        logger.info(f"  HIGH priority: {len(high_priority_rises)}")
        logger.info(f"  NORMAL priority: {len(normal_priority_rises)}")
        logger.info("="*70)

        # Show some examples
        if all_alerts:
            logger.info(f"\nSAMPLE ALERTS (first 10):")
            for alert in all_alerts[:10]:
                logger.info(f"  {alert['priority']:6} {alert['direction']:4} - {alert['symbol']:12} at {alert['time']} - {alert['change_pct']:.2f}%")

        return {
            'date': self.test_date,
            'stocks_tested': stocks_processed,
            'stocks_with_data': stocks_with_data,
            'total_alerts': len(all_alerts),
            'drops': len(drops),
            'rises': len(rises),
            'high_priority': len(high_priority_drops) + len(high_priority_rises),
            'normal_priority': len(normal_priority_drops) + len(normal_priority_rises),
            'alerts': all_alerts
        }


if __name__ == "__main__":
    # Test for yesterday
    ist = pytz.timezone('Asia/Kolkata')
    today = datetime.now(ist).date()
    yesterday = today - timedelta(days=1)

    # Run backtest on first 20 stocks (or set to None for all stocks)
    backtester = OneMinBacktester(test_date=yesterday)
    results = backtester.run_backtest(max_stocks=20)

    print(f"\n✅ Backtest complete!")
    print(f"Generated {results['total_alerts']} alerts from {results['stocks_tested']} stocks")
