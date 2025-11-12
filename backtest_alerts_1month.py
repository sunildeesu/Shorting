#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Alert Backtesting - 1 Month

Backtests the alert system over the past month to:
1. Identify all alerts that would have been triggered
2. Log them to Excel with complete price tracking
3. Calculate actual returns at 2min, 10min, and EOD
4. Generate performance statistics

This helps validate alert effectiveness and populate historical data.
"""

import sys
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Optional
import time
from kiteconnect import KiteConnect
import config
from alert_excel_logger import AlertExcelLogger
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/alert_backtest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AlertBacktester:
    """Backtests alert system over historical data."""

    def __init__(self, days_back: int = 30):
        """
        Initialize backtester.

        Args:
            days_back: Number of days to backtest (default 30)
        """
        self.days_back = days_back

        # Initialize Kite Connect
        if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
            raise ValueError("Kite Connect requires KITE_API_KEY and KITE_ACCESS_TOKEN")

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
        logger.info("Kite Connect initialized successfully")

        # Initialize Excel logger
        self.excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
        logger.info(f"Excel logger initialized: {config.ALERT_EXCEL_PATH}")

        # Load stock list
        self.stocks = self._load_stock_list()
        logger.info(f"Loaded {len(self.stocks)} stocks for backtesting")

        # Build instrument token mapping
        self.instrument_tokens = self._build_instrument_token_map()
        logger.info(f"Built token map for {len(self.instrument_tokens)} stocks")

        # Alert criteria from config
        self.criteria = {
            # Drop thresholds
            '5min': config.DROP_THRESHOLD_5MIN,
            '10min': config.DROP_THRESHOLD_PERCENT,
            '30min': config.DROP_THRESHOLD_30MIN,
            'volume_spike': config.DROP_THRESHOLD_VOLUME_SPIKE,
            'volume_multiplier': config.VOLUME_SPIKE_MULTIPLIER,
            # Rise thresholds
            '5min_rise': config.RISE_THRESHOLD_5MIN,
            '10min_rise': config.RISE_THRESHOLD_PERCENT,
            '30min_rise': config.RISE_THRESHOLD_30MIN,
            'volume_spike_rise': config.RISE_THRESHOLD_VOLUME_SPIKE
        }

        # Statistics
        self.stats = {
            'total_alerts': 0,
            'by_type': {},
            'by_symbol': {},
            'successful_predictions': 0,  # Price continued in alert direction
            'failed_predictions': 0  # Price reversed
        }

    def _load_stock_list(self) -> List[str]:
        """Load stock list from fo_stocks.json."""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                data = json.load(f)
                # Use all F&O stocks for complete backtest
                return data['stocks']
        except Exception as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

    def _build_instrument_token_map(self) -> Dict[str, int]:
        """
        Build mapping of stock symbol to instrument token.

        Returns:
            Dict mapping symbol to instrument_token
        """
        logger.info("Building instrument token map from Kite API...")

        try:
            instruments = self.kite.instruments("NSE")
            token_map = {}

            for instrument in instruments:
                if instrument['segment'] == 'NSE' and instrument['tradingsymbol'] in self.stocks:
                    token_map[instrument['tradingsymbol']] = instrument['instrument_token']

            logger.info(f"Built token map for {len(token_map)} stocks")
            return token_map

        except Exception as e:
            logger.error(f"Error building instrument token map: {e}")
            return {}

    def fetch_historical_data(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        interval: str = "5minute"
    ) -> List[Dict]:
        """
        Fetch historical intraday data for a symbol.

        Args:
            symbol: Stock symbol (without .NS)
            from_date: Start date
            to_date: End date
            interval: Candle interval (5minute, 15minute, etc.)

        Returns:
            List of OHLCV candles
        """
        try:
            # Get instrument token from mapping
            instrument_token = self.instrument_tokens.get(symbol)
            if instrument_token is None:
                logger.warning(f"No instrument token found for {symbol}")
                return []

            # Fetch historical data
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )

            logger.info(f"Fetched {len(data)} candles for {symbol}")
            return data

        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            return []

    def detect_alerts(self, candles: List[Dict], symbol: str) -> List[Dict]:
        """
        Detect alerts in historical candle data (both drops and rises).

        Args:
            candles: List of OHLCV candles (5-minute intervals)
            symbol: Stock symbol

        Returns:
            List of detected alerts with metadata
        """
        alerts = []

        # Need at least 7 candles for 30-min lookback
        if len(candles) < 7:
            return alerts

        for i in range(6, len(candles)):
            current = candles[i]
            prev_1 = candles[i-1]  # 5 min ago
            prev_2 = candles[i-2]  # 10 min ago
            prev_6 = candles[i-6]  # 30 min ago

            current_price = current['close']
            current_volume = current['volume']
            timestamp = current['date']

            # Skip alerts between 9:15 AM and 9:25 AM (market opening volatility)
            alert_time = timestamp.time()
            if alert_time.hour == 9 and 15 <= alert_time.minute < 25:
                continue

            # Calculate average volume (last 6 candles)
            avg_volume = sum(candles[i-j]['volume'] for j in range(1, 7)) / 6
            volume_multiplier = current_volume / avg_volume if avg_volume > 0 else 0

            # Calculate price changes
            drop_5min = ((prev_1['close'] - current_price) / prev_1['close']) * 100
            rise_5min = ((current_price - prev_1['close']) / prev_1['close']) * 100
            drop_10min = ((prev_2['close'] - current_price) / prev_2['close']) * 100
            rise_10min = ((current_price - prev_2['close']) / prev_2['close']) * 100
            drop_30min = ((prev_6['close'] - current_price) / prev_6['close']) * 100
            rise_30min = ((current_price - prev_6['close']) / prev_6['close']) * 100

            # ==== DROP ALERTS ====

            # 1. Check Volume Spike Drop (Priority)
            if volume_multiplier >= self.criteria['volume_multiplier']:
                if drop_5min >= self.criteria['volume_spike']:
                    alerts.append({
                        'symbol': symbol,
                        'alert_type': 'volume_spike',
                        'timestamp': timestamp,
                        'current_price': current_price,
                        'previous_price': prev_1['close'],
                        'drop_percent': drop_5min,
                        'volume': current_volume,
                        'avg_volume': avg_volume,
                        'volume_multiplier': volume_multiplier,
                        'candle_index': i
                    })
                    continue  # Skip other checks if volume spike detected

            # 2. Check 5-min Rapid Drop
            if drop_5min >= self.criteria['5min']:
                alerts.append({
                    'symbol': symbol,
                    'alert_type': '5min',
                    'timestamp': timestamp,
                    'current_price': current_price,
                    'previous_price': prev_1['close'],
                    'drop_percent': drop_5min,
                    'volume': current_volume,
                    'avg_volume': avg_volume,
                    'volume_multiplier': volume_multiplier,
                    'candle_index': i
                })
                continue

            # 3. Check 10-min Drop
            if drop_10min >= self.criteria['10min']:
                alerts.append({
                    'symbol': symbol,
                    'alert_type': '10min',
                    'timestamp': timestamp,
                    'current_price': current_price,
                    'previous_price': prev_2['close'],
                    'drop_percent': drop_10min,
                    'volume': current_volume,
                    'avg_volume': avg_volume,
                    'volume_multiplier': volume_multiplier,
                    'candle_index': i
                })
                continue

            # 4. Check 30-min Cumulative Drop
            if drop_30min >= self.criteria['30min']:
                alerts.append({
                    'symbol': symbol,
                    'alert_type': '30min',
                    'timestamp': timestamp,
                    'current_price': current_price,
                    'previous_price': prev_6['close'],
                    'drop_percent': drop_30min,
                    'volume': current_volume,
                    'avg_volume': avg_volume,
                    'volume_multiplier': volume_multiplier,
                    'candle_index': i
                })
                continue

            # ==== RISE ALERTS ====

            # 5. Check Volume Spike Rise (Priority)
            if volume_multiplier >= self.criteria['volume_multiplier']:
                if rise_5min >= self.criteria['volume_spike_rise']:
                    alerts.append({
                        'symbol': symbol,
                        'alert_type': 'volume_spike_rise',
                        'timestamp': timestamp,
                        'current_price': current_price,
                        'previous_price': prev_1['close'],
                        'drop_percent': rise_5min,
                        'volume': current_volume,
                        'avg_volume': avg_volume,
                        'volume_multiplier': volume_multiplier,
                        'candle_index': i
                    })
                    continue

            # 6. Check 5-min Rapid Rise
            if rise_5min >= self.criteria['5min_rise']:
                alerts.append({
                    'symbol': symbol,
                    'alert_type': '5min_rise',
                    'timestamp': timestamp,
                    'current_price': current_price,
                    'previous_price': prev_1['close'],
                    'drop_percent': rise_5min,
                    'volume': current_volume,
                    'avg_volume': avg_volume,
                    'volume_multiplier': volume_multiplier,
                    'candle_index': i
                })
                continue

            # 7. Check 10-min Rise
            if rise_10min >= self.criteria['10min_rise']:
                alerts.append({
                    'symbol': symbol,
                    'alert_type': '10min_rise',
                    'timestamp': timestamp,
                    'current_price': current_price,
                    'previous_price': prev_2['close'],
                    'drop_percent': rise_10min,
                    'volume': current_volume,
                    'avg_volume': avg_volume,
                    'volume_multiplier': volume_multiplier,
                    'candle_index': i
                })
                continue

            # 8. Check 30-min Cumulative Rise
            if rise_30min >= self.criteria['30min_rise']:
                alerts.append({
                    'symbol': symbol,
                    'alert_type': '30min_rise',
                    'timestamp': timestamp,
                    'current_price': current_price,
                    'previous_price': prev_6['close'],
                    'drop_percent': rise_30min,
                    'volume': current_volume,
                    'avg_volume': avg_volume,
                    'volume_multiplier': volume_multiplier,
                    'candle_index': i
                })

        return alerts

    def calculate_future_prices(
        self,
        alert: Dict,
        candles: List[Dict]
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Calculate prices at 2min, 10min, and EOD after alert.

        Args:
            alert: Alert dictionary with candle_index
            candles: All candles for the day

        Returns:
            Tuple of (price_2min, price_10min, price_eod)
        """
        idx = alert['candle_index']

        # Price 2 min later (next candle, since we have 5-min candles, we'll use approximation)
        # For 5-min candles, 2min isn't exact, so we'll use the midpoint of current and next
        price_2min = None
        if idx + 1 < len(candles):
            # Approximate: average of current close and next candle
            price_2min = (candles[idx]['close'] + candles[idx + 1]['close']) / 2

        # Price 10 min later (2 candles ahead)
        price_10min = None
        if idx + 2 < len(candles):
            price_10min = candles[idx + 2]['close']

        # Price EOD (last candle of the day)
        price_eod = candles[-1]['close']

        return price_2min, price_10min, price_eod

    def backtest_stock(self, symbol: str, from_date: date, to_date: date) -> int:
        """
        Backtest a single stock over date range.

        Args:
            symbol: Stock symbol
            from_date: Start date
            to_date: End date

        Returns:
            Number of alerts found
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Backtesting: {symbol}")
        logger.info(f"{'='*60}")

        # Fetch historical data
        candles = self.fetch_historical_data(symbol, from_date, to_date, interval="5minute")

        if not candles:
            logger.warning(f"No data available for {symbol}")
            return 0

        # Detect alerts
        alerts = self.detect_alerts(candles, symbol)

        if not alerts:
            logger.info(f"No alerts found for {symbol}")
            return 0

        logger.info(f"Found {len(alerts)} alerts for {symbol}")

        # Process each alert
        for alert in alerts:
            # Calculate future prices
            price_2min, price_10min, price_eod = self.calculate_future_prices(alert, candles)

            # Log to Excel
            volume_data = {
                'current_volume': alert['volume'],
                'avg_volume': alert['avg_volume']
            }

            success = self.excel_logger.log_alert(
                symbol=alert['symbol'],
                alert_type=alert['alert_type'],
                drop_percent=alert['drop_percent'],
                current_price=alert['current_price'],
                previous_price=alert['previous_price'],
                volume_data=volume_data,
                market_cap_cr=None,
                telegram_sent=False,  # Historical, not sent
                timestamp=alert['timestamp']
            )

            if success:
                # Update with future prices
                row_id = f"{symbol}_{alert['alert_type']}_{alert['timestamp'].strftime('%Y%m%d_%H%M%S')}"
                sheet_name = self.excel_logger.SHEET_NAMES[alert['alert_type']]

                updates = []

                if price_2min:
                    updates.append({'row_id': row_id, 'sheet_name': sheet_name, 'price': price_2min})
                    self.excel_logger.update_prices(updates, price_column="2min")
                    updates = []

                if price_10min:
                    updates.append({'row_id': row_id, 'sheet_name': sheet_name, 'price': price_10min})
                    self.excel_logger.update_prices(updates, price_column="10min")
                    updates = []

                if price_eod:
                    updates.append({'row_id': row_id, 'sheet_name': sheet_name, 'price': price_eod})
                    self.excel_logger.update_prices(updates, price_column="EOD", auto_complete_eod=True)

                # Track prediction success
                if price_eod:
                    eod_change = ((price_eod - alert['current_price']) / alert['current_price']) * 100
                    is_rise_alert = '_rise' in alert['alert_type']

                    # For drop alerts: success if price dropped (eod_change < 0)
                    # For rise alerts: success if price rose (eod_change > 0)
                    if (not is_rise_alert and eod_change < 0) or (is_rise_alert and eod_change > 0):
                        self.stats['successful_predictions'] += 1
                    else:
                        self.stats['failed_predictions'] += 1

                # Update statistics
                self.stats['total_alerts'] += 1
                self.stats['by_type'][alert['alert_type']] = self.stats['by_type'].get(alert['alert_type'], 0) + 1
                self.stats['by_symbol'][symbol] = self.stats['by_symbol'].get(symbol, 0) + 1

                logger.info(f"  ✓ {alert['alert_type']:12s} | {alert['timestamp']} | "
                           f"₹{alert['current_price']:.2f} → ₹{price_eod:.2f if price_eod else 0:.2f}")

        return len(alerts)

    def run_backtest(self):
        """Run backtest for all stocks over the date range."""
        logger.info("=" * 80)
        logger.info("ALERT BACKTEST - 1 MONTH")
        logger.info("=" * 80)

        # Calculate date range
        to_date = date.today()
        from_date = to_date - timedelta(days=self.days_back)

        logger.info(f"\nBacktest Period: {from_date} to {to_date}")
        logger.info(f"Stocks to analyze: {len(self.stocks)}")
        logger.info(f"\nAlert Criteria (Drop):")
        logger.info(f"  5-min drop:      {self.criteria['5min']:.2f}%")
        logger.info(f"  10-min drop:     {self.criteria['10min']:.2f}%")
        logger.info(f"  30-min drop:     {self.criteria['30min']:.2f}%")
        logger.info(f"  Volume spike:    {self.criteria['volume_spike']:.2f}% + {self.criteria['volume_multiplier']:.1f}x volume")
        logger.info(f"\nAlert Criteria (Rise):")
        logger.info(f"  5-min rise:      {self.criteria['5min_rise']:.2f}%")
        logger.info(f"  10-min rise:     {self.criteria['10min_rise']:.2f}%")
        logger.info(f"  30-min rise:     {self.criteria['30min_rise']:.2f}%")
        logger.info(f"  Volume spike:    {self.criteria['volume_spike_rise']:.2f}% + {self.criteria['volume_multiplier']:.1f}x volume")
        logger.info(f"\nFiltering:")
        logger.info(f"  Excluded time:   9:15 AM - 9:25 AM (market opening volatility)")
        logger.info("")

        # Backtest each stock
        total_alerts = 0
        for i, symbol in enumerate(self.stocks, 1):
            logger.info(f"\n[{i}/{len(self.stocks)}] Processing {symbol}...")

            try:
                alert_count = self.backtest_stock(symbol, from_date, to_date)
                total_alerts += alert_count

                # Rate limiting
                time.sleep(0.4)  # Respect Kite API limits

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue

        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print backtest summary statistics."""
        logger.info("\n" + "=" * 80)
        logger.info("BACKTEST SUMMARY")
        logger.info("=" * 80)

        logger.info(f"\nTotal Alerts Found: {self.stats['total_alerts']}")

        if self.stats['total_alerts'] == 0:
            logger.info("No alerts found in the backtest period.")
            return

        logger.info(f"\nAlerts by Type:")
        for alert_type, count in sorted(self.stats['by_type'].items()):
            pct = (count / self.stats['total_alerts']) * 100
            logger.info(f"  {alert_type:15s}: {count:4d} ({pct:5.1f}%)")

        logger.info(f"\nTop 10 Most Active Stocks:")
        top_stocks = sorted(self.stats['by_symbol'].items(), key=lambda x: x[1], reverse=True)[:10]
        for symbol, count in top_stocks:
            logger.info(f"  {symbol:12s}: {count:3d} alerts")

        logger.info(f"\nPrediction Accuracy:")
        total_predictions = self.stats['successful_predictions'] + self.stats['failed_predictions']
        if total_predictions > 0:
            accuracy = (self.stats['successful_predictions'] / total_predictions) * 100
            logger.info(f"  Successful: {self.stats['successful_predictions']:4d} ({accuracy:.1f}%)")
            logger.info(f"  Failed:     {self.stats['failed_predictions']:4d} ({100-accuracy:.1f}%)")

        logger.info(f"\nExcel File: {config.ALERT_EXCEL_PATH}")
        logger.info("=" * 80)

    def close(self):
        """Close resources."""
        if self.excel_logger:
            self.excel_logger.close()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Backtest alert system over past month")
    parser.add_argument('--days', type=int, default=30, help='Number of days to backtest (default: 30)')

    args = parser.parse_args()

    try:
        backtester = AlertBacktester(days_back=args.days)
        backtester.run_backtest()
        backtester.close()

        logger.info("\n✅ Backtest completed successfully!")
        logger.info(f"📊 View results: open {config.ALERT_EXCEL_PATH}")

        return 0

    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
