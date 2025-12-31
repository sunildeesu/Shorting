#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
1-Minute Alert Backtesting

Backtests the 1-minute ultra-fast alert system over the past month to:
1. Validate 1-min alert detection logic
2. Calculate actual performance metrics
3. Generate recommendations for threshold tuning
4. Compare against 5-min alert performance

Uses same 5-layer filtering as production:
- Price threshold (0.85% change in 1 minute)
- Volume spike (3x average + 50K minimum)
- Quality filters (price >= 50, liquidity >= 500K avg volume)
- Cooldown (10 minutes between alerts per stock)
- Cross-alert deduplication (skip if recent 5-min alert)
"""

import sys
import logging
from datetime import datetime, timedelta, date, time as dt_time
from typing import Dict, List, Tuple, Optional
import time
from kiteconnect import KiteConnect
import config
import json
from price_cache import PriceCache
from alert_history_manager import AlertHistoryManager
from onemin_alert_detector import OneMinAlertDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/1min_backtest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class OneMinBacktester:
    """Backtests 1-minute alert system over historical data."""

    def __init__(self, days_back: int = 30):
        """
        Initialize 1-min backtester.

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

        # Load stock list
        self.stocks = self._load_stock_list()
        logger.info(f"Loaded {len(self.stocks)} stocks for backtesting")

        # Build instrument token mapping
        self.instrument_tokens = self._build_instrument_token_map()
        logger.info(f"Built token map for {len(self.instrument_tokens)} stocks")

        # 1-min alert criteria
        self.criteria = {
            'drop_threshold': config.DROP_THRESHOLD_1MIN,
            'rise_threshold': config.RISE_THRESHOLD_1MIN,
            'volume_multiplier': config.VOLUME_SPIKE_MULTIPLIER_1MIN,
            'min_volume': config.MIN_VOLUME_1MIN,
            'min_avg_daily_volume': config.MIN_AVG_DAILY_VOLUME_1MIN,
            'cooldown_minutes': config.COOLDOWN_1MIN_ALERTS,
            'min_price': 50  # Quality filter: no penny stocks
        }

        # Statistics
        self.stats = {
            'total_alerts': 0,
            'drop_alerts': 0,
            'rise_alerts': 0,
            # Tiered priority tracking
            'high_priority_alerts': 0,
            'normal_priority_alerts': 0,
            'by_symbol': {},
            'filtered_low_volume': 0,
            'filtered_penny_stock': 0,
            'filtered_cooldown': 0,
            'successful_predictions': 0,  # Price continued in alert direction
            'failed_predictions': 0,
            'price_reversals': 0,  # Price reversed within 10 min
            # Performance metrics
            'avg_gain_on_success': [],
            'avg_loss_on_failure': [],
            'max_gain': 0,
            'max_loss': 0,
            # Volume analysis
            'alerts_with_3x_volume': 0,
            'alerts_with_4x_volume': 0,
            'alerts_with_5x_volume': 0,
            # Tiered performance tracking
            'high_priority': {
                'total': 0,
                'successful': 0,
                'failed': 0,
                'reversals': 0,
                'avg_gain': [],
                'avg_loss': []
            },
            'normal_priority': {
                'total': 0,
                'successful': 0,
                'failed': 0,
                'reversals': 0,
                'avg_gain': [],
                'avg_loss': []
            }
        }

        # Track cooldowns (symbol -> last_alert_timestamp)
        self.cooldowns = {}

        # Track simulated 5-min alerts for cross-deduplication
        self.recent_5min_alerts = {}  # symbol -> timestamp

        # Initialize alert detector (same as production)
        self.price_cache = PriceCache()
        self.alert_history = AlertHistoryManager()
        self.detector = OneMinAlertDetector(
            price_cache=self.price_cache,
            alert_history=self.alert_history
        )

    def _load_stock_list(self) -> List[str]:
        """Load stock list from fo_stocks.json."""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                data = json.load(f)
                # Return all F&O stocks (matches production behavior)
                return data['stocks']  # All 210 stocks (no limit)
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

        # Retry up to 3 times with exponential backoff
        for attempt in range(1, 4):
            try:
                logger.info(f"Attempt {attempt}/3: Fetching instruments from Kite API...")
                instruments = self.kite.instruments("NSE")
                token_map = {}

                for instrument in instruments:
                    if instrument['segment'] == 'NSE' and instrument['tradingsymbol'] in self.stocks:
                        token_map[instrument['tradingsymbol']] = instrument['instrument_token']

                logger.info(f"Built token map for {len(token_map)} stocks")
                return token_map

            except Exception as e:
                logger.error(f"Attempt {attempt}/3 failed: {e}")
                if attempt < 3:
                    wait_time = 5 * attempt  # 5s, 10s, 15s
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error("All retry attempts failed. Unable to build instrument token map.")
                    return {}

    def fetch_historical_data(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        interval: str = "minute"
    ) -> List[Dict]:
        """
        Fetch historical 1-minute candle data for a symbol.

        Args:
            symbol: Stock symbol
            from_date: Start date
            to_date: End date
            interval: Candle interval (minute for 1-min)

        Returns:
            List of OHLCV candles
        """
        try:
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

            logger.info(f"Fetched {len(data)} 1-min candles for {symbol}")
            return data

        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            return []

    def detect_1min_alerts(self, candles: List[Dict], symbol: str) -> List[Dict]:
        """
        Detect 1-minute alerts in historical candle data using tiered detection.

        Uses OneMinAlertDetector with 6-layer filtering:
        1. Price threshold (0.75% in 1 min)
        2. Volume spike (3x average + 50K min)
        3. Quality filters (price >= 50)
        4. Cooldown (10 min between alerts)
        5. Cross-deduplication (no recent 5-min alert)
        6. Momentum confirmation (for HIGH priority)

        Args:
            candles: List of 1-minute OHLCV candles
            symbol: Stock symbol

        Returns:
            List of detected alerts with metadata including priority level
        """
        alerts = []

        # Need at least 6 candles (5 for momentum check + 1 current)
        if len(candles) < 6:
            return alerts

        for i in range(1, len(candles)):
            current = candles[i]
            prev = candles[i-1]  # 1 min ago

            current_price = current['close']
            prev_price = prev['close']
            current_volume = current['volume']
            timestamp = current['date']

            # Skip market opening volatility (9:15-9:25 AM)
            alert_time = timestamp.time()
            if alert_time.hour == 9 and 15 <= alert_time.minute < 25:
                continue

            # Get price from 5 minutes ago for momentum check (if available)
            price_5min_ago = None
            if i >= 5:
                price_5min_ago = candles[i-5]['close']

            # Calculate average volume for metadata and populate cache for detector
            lookback = min(5, i)
            avg_volume = sum(candles[i-j]['volume'] for j in range(1, lookback + 1)) / lookback
            volume_multiplier = current_volume / avg_volume if avg_volume > 0 else 0

            # Manually populate cache for detector's volume check
            # The detector expects current and previous_1min to be set
            self.price_cache.cache[symbol] = {
                "current": {"price": current_price, "volume": current_volume, "timestamp": timestamp.isoformat()},
                "previous_1min": {"price": prev_price, "volume": avg_volume, "timestamp": timestamp.isoformat()},
                "previous": None,
                "previous2": None,
                "previous3": None,
                "previous4": None,
                "previous5": None,
                "previous6": None
            }

            # Check for DROP alert using detector
            drop_priority = self.detector.check_for_drop_1min(
                symbol=symbol,
                current_price=current_price,
                price_1min_ago=prev_price,
                current_volume=current_volume,
                oi=0,  # Not used in backtest
                price_5min_ago=price_5min_ago
            )

            if drop_priority:
                drop_pct = self.detector.get_drop_percentage(current_price, prev_price)
                alerts.append({
                    'symbol': symbol,
                    'direction': 'drop',
                    'priority': drop_priority,  # "HIGH" or "NORMAL"
                    'timestamp': timestamp,
                    'current_price': current_price,
                    'previous_price': prev_price,
                    'change_percent': drop_pct,
                    'volume': current_volume,
                    'avg_volume': avg_volume,
                    'volume_multiplier': volume_multiplier,
                    'candle_index': i
                })

                # Track volume spike strength
                if volume_multiplier >= 5.0:
                    self.stats['alerts_with_5x_volume'] += 1
                elif volume_multiplier >= 4.0:
                    self.stats['alerts_with_4x_volume'] += 1
                elif volume_multiplier >= 3.0:
                    self.stats['alerts_with_3x_volume'] += 1

                continue

            # Check for RISE alert using detector (if enabled)
            if config.ENABLE_RISE_ALERTS:
                rise_priority = self.detector.check_for_rise_1min(
                    symbol=symbol,
                    current_price=current_price,
                    price_1min_ago=prev_price,
                    current_volume=current_volume,
                    oi=0,  # Not used in backtest
                    price_5min_ago=price_5min_ago
                )

                if rise_priority:
                    rise_pct = self.detector.get_rise_percentage(current_price, prev_price)
                    alerts.append({
                        'symbol': symbol,
                        'direction': 'rise',
                        'priority': rise_priority,  # "HIGH" or "NORMAL"
                        'timestamp': timestamp,
                        'current_price': current_price,
                        'previous_price': prev_price,
                        'change_percent': rise_pct,
                        'volume': current_volume,
                        'avg_volume': avg_volume,
                        'volume_multiplier': volume_multiplier,
                        'candle_index': i
                    })

                    # Track volume spike strength
                    if volume_multiplier >= 5.0:
                        self.stats['alerts_with_5x_volume'] += 1
                    elif volume_multiplier >= 4.0:
                        self.stats['alerts_with_4x_volume'] += 1
                    elif volume_multiplier >= 3.0:
                        self.stats['alerts_with_3x_volume'] += 1

        return alerts

    def calculate_future_performance(
        self,
        alert: Dict,
        candles: List[Dict]
    ) -> Dict:
        """
        Calculate performance metrics after alert.

        Args:
            alert: Alert dictionary
            candles: All candles for the period

        Returns:
            Dict with performance metrics
        """
        idx = alert['candle_index']
        current_price = alert['current_price']
        direction = alert['direction']

        metrics = {
            'price_1min': None,
            'price_5min': None,
            'price_10min': None,
            'price_eod': None,
            'max_favorable_move': 0,  # Max move in alert direction
            'max_adverse_move': 0,    # Max move against alert direction
            'reversed_within_10min': False
        }

        # Collect prices for next 10 minutes
        prices = []
        for j in range(1, 11):  # Next 10 minutes
            if idx + j < len(candles):
                prices.append(candles[idx + j]['close'])

        if not prices:
            return metrics

        # Price at specific intervals
        if len(prices) >= 1:
            metrics['price_1min'] = prices[0]
        if len(prices) >= 5:
            metrics['price_5min'] = prices[4]
        if len(prices) >= 10:
            metrics['price_10min'] = prices[9]

        # EOD price (last candle of day)
        metrics['price_eod'] = candles[-1]['close']

        # Track max favorable and adverse moves
        for price in prices:
            change_pct = ((price - current_price) / current_price) * 100

            if direction == 'drop':
                # Favorable = price continues dropping (negative change)
                # Adverse = price rises (positive change)
                if change_pct < 0:
                    metrics['max_favorable_move'] = min(metrics['max_favorable_move'], change_pct)
                else:
                    metrics['max_adverse_move'] = max(metrics['max_adverse_move'], change_pct)
            else:  # rise
                # Favorable = price continues rising (positive change)
                # Adverse = price drops (negative change)
                if change_pct > 0:
                    metrics['max_favorable_move'] = max(metrics['max_favorable_move'], change_pct)
                else:
                    metrics['max_adverse_move'] = min(metrics['max_adverse_move'], change_pct)

        # Check if price reversed within 10 min
        if metrics['price_10min']:
            change_10min = ((metrics['price_10min'] - current_price) / current_price) * 100
            if direction == 'drop' and change_10min > 0:
                metrics['reversed_within_10min'] = True
            elif direction == 'rise' and change_10min < 0:
                metrics['reversed_within_10min'] = True

        return metrics

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

        # Reset cooldowns for each stock
        self.cooldowns = {}
        self.recent_5min_alerts = {}

        # Fetch 1-minute historical data
        candles = self.fetch_historical_data(symbol, from_date, to_date, interval="minute")

        if not candles:
            logger.warning(f"No data available for {symbol}")
            return 0

        # Detect 1-min alerts
        alerts = self.detect_1min_alerts(candles, symbol)

        if not alerts:
            logger.info(f"No 1-min alerts found for {symbol}")
            return 0

        logger.info(f"Found {len(alerts)} 1-min alerts for {symbol}")

        # Process each alert
        for alert in alerts:
            # Calculate future performance
            perf = self.calculate_future_performance(alert, candles)

            # Get priority level
            priority = alert.get('priority', 'NORMAL')
            priority_key = 'high_priority' if priority == 'HIGH' else 'normal_priority'

            # Determine if prediction was successful
            if perf['price_eod']:
                eod_change = ((perf['price_eod'] - alert['current_price']) / alert['current_price']) * 100

                if alert['direction'] == 'drop':
                    # Success if price dropped by EOD
                    if eod_change < 0:
                        self.stats['successful_predictions'] += 1
                        self.stats['avg_gain_on_success'].append(abs(eod_change))
                        # Track by priority
                        self.stats[priority_key]['successful'] += 1
                        self.stats[priority_key]['avg_gain'].append(abs(eod_change))
                    else:
                        self.stats['failed_predictions'] += 1
                        self.stats['avg_loss_on_failure'].append(abs(eod_change))
                        # Track by priority
                        self.stats[priority_key]['failed'] += 1
                        self.stats[priority_key]['avg_loss'].append(abs(eod_change))
                else:  # rise
                    # Success if price rose by EOD
                    if eod_change > 0:
                        self.stats['successful_predictions'] += 1
                        self.stats['avg_gain_on_success'].append(abs(eod_change))
                        # Track by priority
                        self.stats[priority_key]['successful'] += 1
                        self.stats[priority_key]['avg_gain'].append(abs(eod_change))
                    else:
                        self.stats['failed_predictions'] += 1
                        self.stats['avg_loss_on_failure'].append(abs(eod_change))
                        # Track by priority
                        self.stats[priority_key]['failed'] += 1
                        self.stats[priority_key]['avg_loss'].append(abs(eod_change))

                # Track max gain/loss
                if abs(eod_change) > abs(self.stats['max_gain']):
                    if eod_change > 0:
                        self.stats['max_gain'] = eod_change
                    else:
                        self.stats['max_loss'] = eod_change

            # Track reversals
            if perf['reversed_within_10min']:
                self.stats['price_reversals'] += 1
                self.stats[priority_key]['reversals'] += 1

            # Update statistics
            self.stats['total_alerts'] += 1
            self.stats[priority_key]['total'] += 1

            if alert['direction'] == 'drop':
                self.stats['drop_alerts'] += 1
            else:
                self.stats['rise_alerts'] += 1

            # Track priority counts
            if priority == 'HIGH':
                self.stats['high_priority_alerts'] += 1
            else:
                self.stats['normal_priority_alerts'] += 1

            self.stats['by_symbol'][symbol] = self.stats['by_symbol'].get(symbol, 0) + 1

            # Log alert with priority
            priority_icon = "🔥" if priority == "HIGH" else "⚡"
            eod_price = perf['price_eod'] if perf['price_eod'] else 0
            logger.info(f"  {priority_icon} {priority:6s} | {alert['direction'].upper():4s} | {alert['timestamp']} | "
                       f"₹{alert['current_price']:.2f} ({alert['change_percent']:+.2f}%) | "
                       f"Vol: {alert['volume_multiplier']:.1f}x | "
                       f"EOD: ₹{eod_price:.2f}")

        return len(alerts)

    def run_backtest(self):
        """Run backtest for all stocks over the date range."""
        logger.info("=" * 80)
        logger.info("1-MINUTE ALERT BACKTEST")
        logger.info("=" * 80)

        # Calculate date range
        to_date = date.today()
        from_date = to_date - timedelta(days=self.days_back)

        logger.info(f"\nBacktest Period: {from_date} to {to_date}")
        logger.info(f"Stocks to analyze: {len(self.stocks)}")
        logger.info(f"\n1-Min Alert Criteria:")
        logger.info(f"  Drop threshold:      {self.criteria['drop_threshold']:.2f}%")
        logger.info(f"  Rise threshold:      {self.criteria['rise_threshold']:.2f}%")
        logger.info(f"  Volume multiplier:   {self.criteria['volume_multiplier']:.1f}x")
        logger.info(f"  Min volume:          {self.criteria['min_volume']:,} shares")
        logger.info(f"  Min price:           ≥ Rs. {self.criteria['min_price']}")
        logger.info(f"  Cooldown:            {self.criteria['cooldown_minutes']} minutes")
        logger.info(f"\nFiltering:")
        logger.info(f"  Excluded time:       9:15 AM - 9:25 AM (market opening)")
        logger.info("")

        # Backtest each stock
        start_time = time.time()
        for i, symbol in enumerate(self.stocks, 1):
            logger.info(f"\n[{i}/{len(self.stocks)}] Processing {symbol}...")

            try:
                self.backtest_stock(symbol, from_date, to_date)

                # Rate limiting (Kite allows 3 req/sec, be conservative)
                time.sleep(0.4)

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue

        elapsed = time.time() - start_time
        logger.info(f"\nBacktest completed in {elapsed:.1f} seconds")

        # Generate report
        self.generate_report()

    def generate_report(self):
        """Generate comprehensive backtest report with recommendations."""
        logger.info("\n" + "=" * 80)
        logger.info("1-MINUTE ALERT BACKTEST REPORT")
        logger.info("=" * 80)

        if self.stats['total_alerts'] == 0:
            logger.info("\n⚠️  No 1-min alerts detected in backtest period.")
            logger.info("Recommendations:")
            logger.info("  - Lower thresholds (try 0.70% instead of 0.85%)")
            logger.info("  - Reduce volume multiplier (try 2.5x instead of 3.0x)")
            return

        # Overall statistics
        logger.info(f"\n📊 OVERALL STATISTICS")
        logger.info(f"  Total Alerts:        {self.stats['total_alerts']}")
        logger.info(f"  Drop Alerts:         {self.stats['drop_alerts']} ({self.stats['drop_alerts']/self.stats['total_alerts']*100:.1f}%)")
        logger.info(f"  Rise Alerts:         {self.stats['rise_alerts']} ({self.stats['rise_alerts']/self.stats['total_alerts']*100:.1f}%)")
        logger.info(f"  Alerts per day:      {self.stats['total_alerts'] / self.days_back:.1f}")

        # Priority breakdown
        logger.info(f"\n🔥 PRIORITY BREAKDOWN")
        logger.info(f"  HIGH Priority:       {self.stats['high_priority_alerts']} ({self.stats['high_priority_alerts']/self.stats['total_alerts']*100:.1f}%)")
        logger.info(f"  NORMAL Priority:     {self.stats['normal_priority_alerts']} ({self.stats['normal_priority_alerts']/self.stats['total_alerts']*100:.1f}%)")

        # Filtering statistics
        logger.info(f"\n🔍 FILTERING STATISTICS")
        logger.info(f"  Filtered (low volume):    {self.stats['filtered_low_volume']}")
        logger.info(f"  Filtered (penny stock):   {self.stats['filtered_penny_stock']}")
        logger.info(f"  Filtered (cooldown):      {self.stats['filtered_cooldown']}")
        total_checked = (self.stats['total_alerts'] + self.stats['filtered_low_volume'] +
                        self.stats['filtered_penny_stock'] + self.stats['filtered_cooldown'])
        if total_checked > 0:
            pass_rate = (self.stats['total_alerts'] / total_checked) * 100
            logger.info(f"  Filter pass rate:         {pass_rate:.1f}%")

        # Volume analysis
        logger.info(f"\n📈 VOLUME ANALYSIS")
        if self.stats['total_alerts'] > 0:
            logger.info(f"  Alerts with 3x volume:    {self.stats['alerts_with_3x_volume']} ({self.stats['alerts_with_3x_volume']/self.stats['total_alerts']*100:.1f}%)")
            logger.info(f"  Alerts with 4x volume:    {self.stats['alerts_with_4x_volume']} ({self.stats['alerts_with_4x_volume']/self.stats['total_alerts']*100:.1f}%)")
            logger.info(f"  Alerts with 5x+ volume:   {self.stats['alerts_with_5x_volume']} ({self.stats['alerts_with_5x_volume']/self.stats['total_alerts']*100:.1f}%)")

        # Prediction accuracy
        logger.info(f"\n🎯 PREDICTION ACCURACY")
        total_predictions = self.stats['successful_predictions'] + self.stats['failed_predictions']
        if total_predictions > 0:
            accuracy = (self.stats['successful_predictions'] / total_predictions) * 100
            logger.info(f"  Successful:          {self.stats['successful_predictions']} ({accuracy:.1f}%)")
            logger.info(f"  Failed:              {self.stats['failed_predictions']} ({100-accuracy:.1f}%)")
            logger.info(f"  Reversals (<10 min): {self.stats['price_reversals']} ({self.stats['price_reversals']/total_predictions*100:.1f}%)")

            # Average gains/losses
            if self.stats['avg_gain_on_success']:
                avg_gain = sum(self.stats['avg_gain_on_success']) / len(self.stats['avg_gain_on_success'])
                logger.info(f"  Avg gain (success):  {avg_gain:.2f}%")
            if self.stats['avg_loss_on_failure']:
                avg_loss = sum(self.stats['avg_loss_on_failure']) / len(self.stats['avg_loss_on_failure'])
                logger.info(f"  Avg loss (failure):  {avg_loss:.2f}%")

            logger.info(f"  Max gain:            {self.stats['max_gain']:+.2f}%")
            logger.info(f"  Max loss:            {self.stats['max_loss']:+.2f}%")

        # HIGH vs NORMAL comparison
        logger.info(f"\n🔥⚡ HIGH vs NORMAL PRIORITY COMPARISON")

        # HIGH priority performance
        high = self.stats['high_priority']
        if high['total'] > 0:
            high_total_pred = high['successful'] + high['failed']
            high_accuracy = (high['successful'] / high_total_pred * 100) if high_total_pred > 0 else 0
            high_reversal_rate = (high['reversals'] / high['total'] * 100) if high['total'] > 0 else 0
            high_avg_gain = sum(high['avg_gain']) / len(high['avg_gain']) if high['avg_gain'] else 0
            high_avg_loss = sum(high['avg_loss']) / len(high['avg_loss']) if high['avg_loss'] else 0

            logger.info(f"\n  🔥 HIGH Priority ({high['total']} alerts):")
            logger.info(f"    Accuracy:         {high_accuracy:.1f}% ({high['successful']}/{high_total_pred})")
            logger.info(f"    Reversal rate:    {high_reversal_rate:.1f}% ({high['reversals']}/{high['total']})")
            if high_avg_gain > 0:
                logger.info(f"    Avg gain:         {high_avg_gain:.2f}%")
            if high_avg_loss > 0:
                logger.info(f"    Avg loss:         {high_avg_loss:.2f}%")
        else:
            logger.info(f"\n  🔥 HIGH Priority: 0 alerts (momentum filter too strict)")

        # NORMAL priority performance
        normal = self.stats['normal_priority']
        if normal['total'] > 0:
            normal_total_pred = normal['successful'] + normal['failed']
            normal_accuracy = (normal['successful'] / normal_total_pred * 100) if normal_total_pred > 0 else 0
            normal_reversal_rate = (normal['reversals'] / normal['total'] * 100) if normal['total'] > 0 else 0
            normal_avg_gain = sum(normal['avg_gain']) / len(normal['avg_gain']) if normal['avg_gain'] else 0
            normal_avg_loss = sum(normal['avg_loss']) / len(normal['avg_loss']) if normal['avg_loss'] else 0

            logger.info(f"\n  ⚡ NORMAL Priority ({normal['total']} alerts):")
            logger.info(f"    Accuracy:         {normal_accuracy:.1f}% ({normal['successful']}/{normal_total_pred})")
            logger.info(f"    Reversal rate:    {normal_reversal_rate:.1f}% ({normal['reversals']}/{normal['total']})")
            if normal_avg_gain > 0:
                logger.info(f"    Avg gain:         {normal_avg_gain:.2f}%")
            if normal_avg_loss > 0:
                logger.info(f"    Avg loss:         {normal_avg_loss:.2f}%")
        else:
            logger.info(f"\n  ⚡ NORMAL Priority: 0 alerts")

        # Key insights
        if high['total'] > 0 and normal['total'] > 0:
            high_total_pred = high['successful'] + high['failed']
            normal_total_pred = normal['successful'] + normal['failed']
            high_acc = (high['successful'] / high_total_pred * 100) if high_total_pred > 0 else 0
            normal_acc = (normal['successful'] / normal_total_pred * 100) if normal_total_pred > 0 else 0

            logger.info(f"\n  📈 Key Insights:")
            if high_acc > normal_acc:
                diff = high_acc - normal_acc
                logger.info(f"    ✓ HIGH priority {diff:+.1f}pp more accurate than NORMAL")
            elif normal_acc > high_acc:
                diff = normal_acc - high_acc
                logger.info(f"    ⚠️  NORMAL priority {diff:+.1f}pp more accurate than HIGH")

            high_rev_rate = (high['reversals'] / high['total'] * 100) if high['total'] > 0 else 0
            normal_rev_rate = (normal['reversals'] / normal['total'] * 100) if normal['total'] > 0 else 0
            if high_rev_rate < normal_rev_rate:
                diff = normal_rev_rate - high_rev_rate
                logger.info(f"    ✓ HIGH priority {diff:.1f}pp lower reversal rate")
            elif normal_rev_rate < high_rev_rate:
                diff = high_rev_rate - normal_rev_rate
                logger.info(f"    ⚠️  NORMAL priority {diff:.1f}pp lower reversal rate")

        # Top stocks
        logger.info(f"\n🏆 TOP 10 MOST ACTIVE STOCKS")
        top_stocks = sorted(self.stats['by_symbol'].items(), key=lambda x: x[1], reverse=True)[:10]
        for symbol, count in top_stocks:
            logger.info(f"  {symbol:12s}: {count:3d} alerts")

        # Recommendations
        logger.info(f"\n💡 RECOMMENDATIONS")

        # Based on accuracy
        if total_predictions > 0:
            if accuracy >= 70:
                logger.info(f"  ✅ Excellent accuracy ({accuracy:.1f}%) - current thresholds are well-tuned")
            elif accuracy >= 60:
                logger.info(f"  ✓  Good accuracy ({accuracy:.1f}%) - thresholds are reasonable")
            elif accuracy >= 50:
                logger.info(f"  ⚠️  Moderate accuracy ({accuracy:.1f}%) - consider tightening filters:")
                logger.info(f"     - Increase volume multiplier to 3.5x or 4.0x")
                logger.info(f"     - Increase price threshold to 0.90% or 1.0%")
            else:
                logger.info(f"  ❌ Low accuracy ({accuracy:.1f}%) - significant filter improvements needed:")
                logger.info(f"     - Increase volume multiplier to 4.0x or 5.0x")
                logger.info(f"     - Increase price threshold to 1.0% or 1.2%")
                logger.info(f"     - Add additional quality filters")

        # Based on alert volume
        daily_rate = self.stats['total_alerts'] / self.days_back
        if daily_rate > 80:
            logger.info(f"  ⚠️  High alert volume ({daily_rate:.1f}/day) - may cause alert fatigue:")
            logger.info(f"     - Increase thresholds to reduce noise")
            logger.info(f"     - Consider increasing cooldown to 15 minutes")
        elif daily_rate > 60:
            logger.info(f"  ✓  Moderate alert volume ({daily_rate:.1f}/day) - acceptable for active monitoring")
        elif daily_rate > 30:
            logger.info(f"  ✅ Optimal alert volume ({daily_rate:.1f}/day) - good balance of coverage and noise")
        else:
            logger.info(f"  ℹ️  Low alert volume ({daily_rate:.1f}/day) - may miss opportunities:")
            logger.info(f"     - Consider lowering thresholds to 0.70% or 0.75%")
            logger.info(f"     - Reduce volume multiplier to 2.5x")

        # Based on reversal rate
        if total_predictions > 0:
            reversal_rate = (self.stats['price_reversals'] / total_predictions) * 100
            if reversal_rate > 40:
                logger.info(f"  ⚠️  High reversal rate ({reversal_rate:.1f}%) - alerts may be premature:")
                logger.info(f"     - Increase volume confirmation requirement")
                logger.info(f"     - Add price action confirmation (e.g., close below support)")
            elif reversal_rate > 25:
                logger.info(f"  ℹ️  Moderate reversal rate ({reversal_rate:.1f}%) - acceptable for rapid alerts")
            else:
                logger.info(f"  ✅ Low reversal rate ({reversal_rate:.1f}%) - alerts show good follow-through")

        logger.info("\n" + "=" * 80)
        logger.info("📄 Full results available in: logs/1min_backtest.log")
        logger.info("=" * 80)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Backtest 1-minute alert system")
    parser.add_argument('--days', type=int, default=30,
                       help='Number of days to backtest (default: 30)')

    args = parser.parse_args()

    try:
        backtester = OneMinBacktester(days_back=args.days)
        backtester.run_backtest()

        logger.info("\n✅ 1-min backtest completed successfully!")

        return 0

    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
