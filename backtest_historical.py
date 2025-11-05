#!/usr/bin/env python3
"""
Historical Backtesting Script
Analyzes past data to find all occurrences of 2%+ drops in 5-minute intervals
"""

import sys
import logging
from datetime import datetime, timedelta, date
from kiteconnect import KiteConnect
import pandas as pd
import json
import config
import pytz

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class HistoricalBacktest:
    """Backtest drop detection logic on historical data"""

    def __init__(self):
        if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
            raise ValueError("Kite Connect credentials required. Run: python3 generate_kite_token.py")

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
        self.stocks = self._load_stock_list()
        self.instrument_tokens = {}

    def _load_stock_list(self):
        """Load F&O stock list"""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                data = json.load(f)
                return data['stocks']  # All F&O stocks
        except Exception as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

    def get_instrument_token(self, symbol):
        """Get instrument token for a stock symbol"""
        if symbol in self.instrument_tokens:
            return self.instrument_tokens[symbol]

        try:
            # Search for instrument
            instruments = self.kite.instruments("NSE")

            for instrument in instruments:
                if instrument['tradingsymbol'] == symbol and instrument['segment'] == 'NSE':
                    token = instrument['instrument_token']
                    self.instrument_tokens[symbol] = token
                    return token

            logger.warning(f"Instrument token not found for {symbol}")
            return None

        except Exception as e:
            logger.error(f"Error getting instrument token for {symbol}: {e}")
            return None

    def fetch_historical_data(self, symbol, from_date, to_date):
        """
        Fetch historical 5-minute candle data

        Args:
            symbol: Stock symbol (e.g., RELIANCE)
            from_date: Start date (datetime)
            to_date: End date (datetime)

        Returns:
            DataFrame with OHLC data or None
        """
        try:
            instrument_token = self.get_instrument_token(symbol)
            if not instrument_token:
                return None

            logger.info(f"Fetching historical data for {symbol}...")

            # Fetch 5-minute candle data
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="5minute"
            )

            if not data:
                logger.warning(f"No data returned for {symbol}")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['date'])
            df = df.sort_values('timestamp')

            logger.info(f"  Fetched {len(df)} candles for {symbol}")
            return df

        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            return None

    def analyze_drops(self, symbol, df):
        """
        Analyze historical data using three detection methods:
        1. 10-minute drop (≥2%)
        2. 30-minute cumulative drop (≥3%)
        3. Volume spike + drop (≥1.5% with 3x volume)

        Args:
            symbol: Stock symbol
            df: DataFrame with OHLC data

        Returns:
            List of drop occurrences with alert_type
        """
        drops = []

        # Calculate rolling average volume (for volume spike detection)
        df['volume_avg'] = df['volume'].rolling(window=6, min_periods=3).mean().shift(1)

        # Iterate through candles (need at least 6 for 30-min analysis)
        for i in range(6, len(df)):
            curr_candle = df.iloc[i]
            candle_10min = df.iloc[i-2]  # 10 minutes ago
            candle_30min = df.iloc[i-6]  # 30 minutes ago

            curr_date = curr_candle['timestamp'].date()

            # Only same-day comparisons
            if candle_10min['timestamp'].date() != curr_date:
                continue
            if candle_30min['timestamp'].date() != curr_date:
                candle_30min = None  # Skip 30-min check

            curr_close = curr_candle['close']
            curr_volume = curr_candle['volume']
            volume_avg = curr_candle['volume_avg']

            # === CHECK 1: 10-Minute Drop ===
            if candle_10min is not None:
                prev_close_10 = candle_10min['close']
                if prev_close_10 > 0:
                    drop_10min = ((prev_close_10 - curr_close) / prev_close_10) * 100

                    if drop_10min >= config.DROP_THRESHOLD_PERCENT:
                        drops.append({
                            'symbol': symbol,
                            'timestamp': curr_candle['timestamp'],
                            'prev_time': candle_10min['timestamp'],
                            'prev_price': prev_close_10,
                            'curr_price': curr_close,
                            'drop_percent': drop_10min,
                            'volume': curr_volume,
                            'alert_type': '10min',
                            'volume_spike': False
                        })

            # === CHECK 2: 30-Minute Cumulative Drop ===
            if candle_30min is not None:
                prev_close_30 = candle_30min['close']
                if prev_close_30 > 0:
                    drop_30min = ((prev_close_30 - curr_close) / prev_close_30) * 100

                    if drop_30min >= config.DROP_THRESHOLD_30MIN:
                        drops.append({
                            'symbol': symbol,
                            'timestamp': curr_candle['timestamp'],
                            'prev_time': candle_30min['timestamp'],
                            'prev_price': prev_close_30,
                            'curr_price': curr_close,
                            'drop_percent': drop_30min,
                            'volume': curr_volume,
                            'alert_type': '30min',
                            'volume_spike': False
                        })

            # === CHECK 3: Volume Spike with Drop ===
            if candle_10min is not None and pd.notna(volume_avg) and volume_avg > 0:
                volume_spike = curr_volume > (volume_avg * config.VOLUME_SPIKE_MULTIPLIER)

                if volume_spike:
                    prev_close_10 = candle_10min['close']
                    if prev_close_10 > 0:
                        drop_10min = ((prev_close_10 - curr_close) / prev_close_10) * 100

                        if drop_10min >= config.DROP_THRESHOLD_VOLUME_SPIKE:
                            spike_ratio = curr_volume / volume_avg
                            drops.append({
                                'symbol': symbol,
                                'timestamp': curr_candle['timestamp'],
                                'prev_time': candle_10min['timestamp'],
                                'prev_price': prev_close_10,
                                'curr_price': curr_close,
                                'drop_percent': drop_10min,
                                'volume': curr_volume,
                                'alert_type': 'volume_spike',
                                'volume_spike': True,
                                'volume_avg': int(volume_avg),
                                'spike_ratio': spike_ratio
                            })

        return drops

    def analyze_rises(self, symbol, df):
        """
        Analyze historical data using three detection methods:
        1. 10-minute rise (≥2%)
        2. 30-minute cumulative rise (≥3%)
        3. Volume spike + rise (≥1.5% with 3x volume)

        Args:
            symbol: Stock symbol
            df: DataFrame with OHLC data

        Returns:
            List of rise occurrences with alert_type
        """
        rises = []

        # Calculate rolling average volume (for volume spike detection)
        df['volume_avg'] = df['volume'].rolling(window=6, min_periods=3).mean().shift(1)

        # Iterate through candles (need at least 6 for 30-min analysis)
        for i in range(6, len(df)):
            curr_candle = df.iloc[i]
            candle_10min = df.iloc[i-2]  # 10 minutes ago
            candle_30min = df.iloc[i-6]  # 30 minutes ago

            curr_date = curr_candle['timestamp'].date()

            # Only same-day comparisons
            if candle_10min['timestamp'].date() != curr_date:
                continue
            if candle_30min['timestamp'].date() != curr_date:
                candle_30min = None  # Skip 30-min check

            curr_close = curr_candle['close']
            curr_volume = curr_candle['volume']
            volume_avg = curr_candle['volume_avg']

            # === CHECK 1: 10-Minute Rise ===
            if candle_10min is not None:
                prev_close_10 = candle_10min['close']
                if prev_close_10 > 0:
                    rise_10min = ((curr_close - prev_close_10) / prev_close_10) * 100

                    if rise_10min >= config.RISE_THRESHOLD_PERCENT:
                        rises.append({
                            'symbol': symbol,
                            'timestamp': curr_candle['timestamp'],
                            'prev_time': candle_10min['timestamp'],
                            'prev_price': prev_close_10,
                            'curr_price': curr_close,
                            'rise_percent': rise_10min,
                            'volume': curr_volume,
                            'alert_type': '10min_rise',
                            'volume_spike': False
                        })

            # === CHECK 2: 30-Minute Cumulative Rise ===
            if candle_30min is not None:
                prev_close_30 = candle_30min['close']
                if prev_close_30 > 0:
                    rise_30min = ((curr_close - prev_close_30) / prev_close_30) * 100

                    if rise_30min >= config.RISE_THRESHOLD_30MIN:
                        rises.append({
                            'symbol': symbol,
                            'timestamp': curr_candle['timestamp'],
                            'prev_time': candle_30min['timestamp'],
                            'prev_price': prev_close_30,
                            'curr_price': curr_close,
                            'rise_percent': rise_30min,
                            'volume': curr_volume,
                            'alert_type': '30min_rise',
                            'volume_spike': False
                        })

            # === CHECK 3: Volume Spike with Rise ===
            if candle_10min is not None and pd.notna(volume_avg) and volume_avg > 0:
                volume_spike = curr_volume > (volume_avg * config.VOLUME_SPIKE_MULTIPLIER)

                if volume_spike:
                    prev_close_10 = candle_10min['close']
                    if prev_close_10 > 0:
                        rise_10min = ((curr_close - prev_close_10) / prev_close_10) * 100

                        if rise_10min >= config.RISE_THRESHOLD_VOLUME_SPIKE:
                            spike_ratio = curr_volume / volume_avg
                            rises.append({
                                'symbol': symbol,
                                'timestamp': curr_candle['timestamp'],
                                'prev_time': candle_10min['timestamp'],
                                'prev_price': prev_close_10,
                                'curr_price': curr_close,
                                'rise_percent': rise_10min,
                                'volume': curr_volume,
                                'alert_type': 'volume_spike_rise',
                                'volume_spike': True,
                                'volume_avg': int(volume_avg),
                                'spike_ratio': spike_ratio
                            })

        return rises

    def run_backtest(self, from_date, to_date, stocks=None):
        """
        Run backtest on historical data

        Args:
            from_date: Start date (datetime or string YYYY-MM-DD)
            to_date: End date (datetime or string YYYY-MM-DD)
            stocks: List of stock symbols (optional, uses all if None)

        Returns:
            DataFrame with all drop and rise occurrences
        """
        # Convert string dates to datetime
        if isinstance(from_date, str):
            from_date = datetime.strptime(from_date, "%Y-%m-%d")
        if isinstance(to_date, str):
            to_date = datetime.strptime(to_date, "%Y-%m-%d")

        stocks_to_test = stocks if stocks else self.stocks
        all_drops = []
        all_rises = []

        logger.info("=" * 70)
        logger.info(f"Starting Historical Backtest - Enhanced Detection")
        logger.info(f"Date Range: {from_date.date()} to {to_date.date()}")
        logger.info(f"Stocks: {len(stocks_to_test)}")
        logger.info(f"Detection Methods (Drops):")
        logger.info(f"  1. 10-min drop: ≥{config.DROP_THRESHOLD_PERCENT}%")
        logger.info(f"  2. 30-min drop: ≥{config.DROP_THRESHOLD_30MIN}%")
        logger.info(f"  3. Volume spike drop: ≥{config.DROP_THRESHOLD_VOLUME_SPIKE}% + {config.VOLUME_SPIKE_MULTIPLIER}x volume")
        if config.ENABLE_RISE_ALERTS:
            logger.info(f"Detection Methods (Rises):")
            logger.info(f"  1. 10-min rise: ≥{config.RISE_THRESHOLD_PERCENT}%")
            logger.info(f"  2. 30-min rise: ≥{config.RISE_THRESHOLD_30MIN}%")
            logger.info(f"  3. Volume spike rise: ≥{config.RISE_THRESHOLD_VOLUME_SPIKE}% + {config.VOLUME_SPIKE_MULTIPLIER}x volume")
        logger.info(f"Filter: Same-day movements only (excludes overnight gaps)")
        logger.info("=" * 70)

        for idx, symbol in enumerate(stocks_to_test, 1):
            logger.info(f"\n[{idx}/{len(stocks_to_test)}] Analyzing {symbol}...")

            # Fetch historical data
            df = self.fetch_historical_data(symbol, from_date, to_date)

            if df is None or df.empty:
                logger.warning(f"  Skipping {symbol} - no data")
                continue

            # Analyze for drops using all three methods
            drops = self.analyze_drops(symbol, df)

            # Analyze for rises if enabled
            rises = []
            if config.ENABLE_RISE_ALERTS:
                rises = self.analyze_rises(symbol, df)

            total_alerts = len(drops) + len(rises)

            if total_alerts > 0:
                # Count by alert type
                alert_summary = []

                if drops:
                    drop_types = {}
                    for drop in drops:
                        alert_type = drop['alert_type']
                        drop_types[alert_type] = drop_types.get(alert_type, 0) + 1
                    drop_summary = ", ".join([f"{t}:{c}" for t, c in drop_types.items()])
                    alert_summary.append(f"drops({drop_summary})")
                    all_drops.extend(drops)

                if rises:
                    rise_types = {}
                    for rise in rises:
                        alert_type = rise['alert_type']
                        rise_types[alert_type] = rise_types.get(alert_type, 0) + 1
                    rise_summary = ", ".join([f"{t}:{c}" for t, c in rise_types.items()])
                    alert_summary.append(f"rises({rise_summary})")
                    all_rises.extend(rises)

                logger.info(f"  ✓ Found {total_alerts} alerts: {', '.join(alert_summary)}")
            else:
                logger.info(f"  No alerts found")

        # Combine drops and rises into single DataFrame
        all_movements = all_drops + all_rises

        if all_movements:
            results_df = pd.DataFrame(all_movements)
            results_df = results_df.sort_values('timestamp', ascending=False)
            return results_df
        else:
            return pd.DataFrame()

    def generate_report(self, results_df, output_file='backtest_results.csv'):
        """Generate detailed report of findings for both drops and rises"""

        if results_df.empty:
            logger.info("\n" + "=" * 70)
            logger.info("No alerts found in the specified date range")
            logger.info("=" * 70)
            return

        # Save to CSV
        results_df.to_csv(output_file, index=False)

        # Separate drops and rises
        drops_df = results_df[~results_df['alert_type'].str.endswith('_rise')]
        rises_df = results_df[results_df['alert_type'].str.endswith('_rise')]

        logger.info("\n" + "=" * 70)
        logger.info("BACKTEST RESULTS - ENHANCED DETECTION")
        logger.info("=" * 70)
        logger.info(f"Total alerts found: {len(results_df)}")
        logger.info(f"  Drops: {len(drops_df)}")
        logger.info(f"  Rises: {len(rises_df)}")
        logger.info(f"Results saved to: {output_file}")

        # Summary by alert type
        logger.info("\n" + "=" * 70)
        logger.info("Alerts by Type:")
        logger.info("=" * 70)
        alert_counts = results_df['alert_type'].value_counts()
        for alert_type, count in alert_counts.items():
            label = {
                '10min': '🔴 10-Minute Drops',
                '30min': '🔴 30-Minute Gradual Drops',
                'volume_spike': '🔴 Volume Spike Drops',
                '10min_rise': '🟢 10-Minute Rises',
                '30min_rise': '🟢 30-Minute Gradual Rises',
                'volume_spike_rise': '🟢 Volume Spike Rises'
            }.get(alert_type, alert_type)
            logger.info(f"  {label}: {count}")

        # Top 10 largest drops
        if not drops_df.empty:
            logger.info("\n" + "=" * 70)
            logger.info("Top 10 Largest Drops:")
            logger.info("=" * 70)
            top_drops = drops_df.nlargest(10, 'drop_percent')
            for _, row in top_drops.iterrows():
                alert_type_label = {
                    '10min': '[10MIN]',
                    '30min': '[30MIN]',
                    'volume_spike': '[VOL SPIKE]'
                }.get(row['alert_type'], '')
                volume_info = f" | Vol:{row['volume']:,}" if pd.notna(row['volume']) else ""
                spike_info = ""
                if row.get('volume_spike') and 'spike_ratio' in row:
                    spike_info = f" | {row['spike_ratio']:.1f}x vol"

                logger.info(f"  {row['timestamp']} | {row['symbol']} {alert_type_label} | "
                           f"{row['drop_percent']:.2f}% drop | "
                           f"₹{row['prev_price']:.2f} → ₹{row['curr_price']:.2f}{volume_info}{spike_info}")

        # Top 10 largest rises
        if not rises_df.empty:
            logger.info("\n" + "=" * 70)
            logger.info("Top 10 Largest Rises:")
            logger.info("=" * 70)
            top_rises = rises_df.nlargest(10, 'rise_percent')
            for _, row in top_rises.iterrows():
                alert_type_label = {
                    '10min_rise': '[10MIN]',
                    '30min_rise': '[30MIN]',
                    'volume_spike_rise': '[VOL SPIKE]'
                }.get(row['alert_type'], '')
                volume_info = f" | Vol:{row['volume']:,}" if pd.notna(row['volume']) else ""
                spike_info = ""
                if row.get('volume_spike') and 'spike_ratio' in row:
                    spike_info = f" | {row['spike_ratio']:.1f}x vol"

                logger.info(f"  {row['timestamp']} | {row['symbol']} {alert_type_label} | "
                           f"{row['rise_percent']:.2f}% rise | "
                           f"₹{row['prev_price']:.2f} → ₹{row['curr_price']:.2f}{volume_info}{spike_info}")

        # Most recent alerts (last 20)
        logger.info("\n" + "=" * 70)
        logger.info("Most Recent Alerts (Latest 20):")
        logger.info("=" * 70)
        recent_alerts = results_df.head(20)
        for _, row in recent_alerts.iterrows():
            is_rise = row['alert_type'].endswith('_rise')

            if is_rise:
                alert_type_label = {
                    '10min_rise': '[🟢10MIN]',
                    '30min_rise': '[🟢30MIN]',
                    'volume_spike_rise': '[🟢VOL]'
                }.get(row['alert_type'], '[🟢???]')
                change_percent = row['rise_percent']
                change_type = "rise"
            else:
                alert_type_label = {
                    '10min': '[🔴10MIN]',
                    '30min': '[🔴30MIN]',
                    'volume_spike': '[🔴VOL]'
                }.get(row['alert_type'], '[🔴???]')
                change_percent = row['drop_percent']
                change_type = "drop"

            logger.info(f"  {row['timestamp']} | {row['symbol']} {alert_type_label} | "
                       f"{change_percent:.2f}% {change_type} | "
                       f"₹{row['prev_price']:.2f} → ₹{row['curr_price']:.2f}")

        logger.info("\n" + "=" * 70)


def main():
    """Main execution"""

    # Get date range from user
    print("=" * 70)
    print("Historical Backtest - Enhanced Detection (Drops & Rises)")
    print("Drops:")
    print("  1. 10-min drops (≥2%)")
    print("  2. 30-min gradual drops (≥3%)")
    print("  3. Volume spike drops (≥1.5% + 3x volume)")
    if config.ENABLE_RISE_ALERTS:
        print("Rises:")
        print("  1. 10-min rises (≥2%)")
        print("  2. 30-min gradual rises (≥3%)")
        print("  3. Volume spike rises (≥1.5% + 3x volume)")
    print("Same-day analysis only (excludes overnight gaps)")
    print("=" * 70)

    # Default: last 7 days
    default_end = date.today()
    default_start = default_end - timedelta(days=7)

    print(f"\nDefault date range: {default_start} to {default_end} (last 7 days)")
    use_default = input("Use default range? (y/n): ").strip().lower()

    if use_default == 'y':
        from_date = datetime.combine(default_start, datetime.min.time())
        to_date = datetime.combine(default_end, datetime.min.time())
    else:
        from_str = input("Enter start date (YYYY-MM-DD): ").strip()
        to_str = input("Enter end date (YYYY-MM-DD): ").strip()

        try:
            from_date = datetime.strptime(from_str, "%Y-%m-%d")
            to_date = datetime.strptime(to_str, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid date format. Using default range.")
            from_date = datetime.combine(default_start, datetime.min.time())
            to_date = datetime.combine(default_end, datetime.min.time())

    try:
        # Initialize backtester
        backtester = HistoricalBacktest()

        # Run backtest
        results = backtester.run_backtest(from_date, to_date)

        # Generate report
        backtester.generate_report(results)

        return 0

    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
