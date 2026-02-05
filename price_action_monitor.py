#!/usr/bin/env python3
"""
Price Action Monitor - 5-minute candlestick pattern detection

Runs every 5 minutes during market hours (9:25 AM - 3:25 PM)

Features:
- 15-20 candlestick pattern detection on 5-min timeframe
- Confidence scoring (0-10 scale, alert if >=7.0)
- Market regime filtering (Nifty 50 vs 50-day SMA)
- Price & liquidity filters (price >₹50, avg volume >500K)
- Telegram alerts with actionable trade setups
- Excel tracking with performance monitoring
- 30-minute cooldown per stock/pattern
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from kiteconnect import KiteConnect

import time
import config
from alert_history_manager import AlertHistoryManager
from alert_excel_logger import AlertExcelLogger
from telegram_notifier import TelegramNotifier
from price_action_detector import PriceActionDetector
from market_utils import is_market_open, get_market_status
from central_db_reader import fetch_nifty_vix, report_cycle_complete
from service_health import get_health_tracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/price_action_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PriceActionMonitor:
    """5-minute price action monitoring system"""

    # Nifty 50 instrument token for market regime detection
    NIFTY_50_TOKEN = 256265

    def __init__(self):
        """Initialize monitor with all required components"""

        # Feature flag check
        if not config.ENABLE_PRICE_ACTION_ALERTS:
            logger.info("Price action alerts disabled in config (ENABLE_PRICE_ACTION_ALERTS=false)")
            sys.exit(0)

        # Market check (trading day + market hours)
        if not is_market_open():
            status = get_market_status()
            if not status['is_trading_day']:
                logger.info("Not a trading day (weekend/holiday) - skipping")
            else:
                logger.info("Outside market hours (9:25 AM - 3:25 PM) - skipping")
            sys.exit(0)

        # Initialize Kite Connect
        logger.info("Initializing Kite Connect...")
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Initialize core components
        logger.info("Initializing core components...")
        self.alert_history = AlertHistoryManager()
        self.excel_logger = AlertExcelLogger(config.ALERT_EXCEL_PATH)
        self.telegram = TelegramNotifier()

        # Initialize pattern detector
        self.detector = PriceActionDetector(
            min_confidence=config.PRICE_ACTION_MIN_CONFIDENCE,
            lookback_candles=config.PRICE_ACTION_LOOKBACK_CANDLES
        )

        # Load eligible stocks
        self.stocks = self._load_eligible_stocks()
        logger.info(f"Monitoring {len(self.stocks)} stocks for price action patterns")

        # Cache for instrument tokens
        self.instrument_tokens = {}

    def _load_eligible_stocks(self) -> List[str]:
        """
        Load stocks eligible for price action monitoring

        Returns:
            List of eligible stock symbols
        """
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                all_stocks = json.load(f)['stocks']
        except Exception as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

        # For now, return all F&O stocks
        # In production, could apply additional filters here
        eligible = all_stocks

        logger.info(f"Loaded {len(eligible)} eligible stocks for monitoring")
        return eligible

    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        """
        Get instrument token for a symbol

        Args:
            symbol: Stock symbol (without .NS suffix)

        Returns:
            Instrument token or None
        """
        if symbol in self.instrument_tokens:
            return self.instrument_tokens[symbol]

        try:
            # Fetch instruments list if not cached
            if not hasattr(self, 'instruments_cache'):
                logger.info("Fetching instruments list from Kite...")
                self.instruments_cache = self.kite.instruments("NSE")

            # Find instrument token
            for instrument in self.instruments_cache:
                if instrument['tradingsymbol'] == symbol:
                    token = instrument['instrument_token']
                    self.instrument_tokens[symbol] = token
                    return token

            logger.warning(f"{symbol}: Instrument token not found")
            return None

        except Exception as e:
            logger.error(f"{symbol}: Error fetching instrument token: {e}")
            return None

    def monitor(self) -> Dict:
        """
        Main monitoring function - runs every 5 minutes

        Returns:
            Statistics dict with pattern counts
        """
        cycle_start_time = time.time()  # Track cycle time for health reporting

        logger.info("=" * 80)
        logger.info(f"PRICE ACTION MONITOR - Starting cycle at {datetime.now().strftime('%H:%M:%S')}")
        logger.info("=" * 80)

        stats = {
            'total_checked': 0,
            'patterns_detected': 0,
            'alerts_sent': 0,
            'bullish_patterns': 0,
            'bearish_patterns': 0,
            'neutral_patterns': 0,
            'errors': 0
        }

        try:
            # Step 1: Determine market regime
            market_regime = self._get_market_regime()
            logger.info(f"Market Regime: {market_regime}")

            # Step 2: Fetch 5-minute candles for all stocks
            logger.info(f"Fetching 5-minute candles for {len(self.stocks)} stocks...")
            candle_data = self._fetch_5min_candles()
            logger.info(f"Received candle data for {len(candle_data)} stocks")

            # Step 3: Check each stock for patterns
            for symbol in self.stocks:
                stats['total_checked'] += 1

                if symbol not in candle_data:
                    logger.debug(f"{symbol}: No candle data available")
                    continue

                try:
                    candles = candle_data[symbol]['candles']
                    current_price = candle_data[symbol]['current_price']
                    avg_volume = candle_data[symbol]['avg_volume']

                    # Apply price filter
                    if current_price < config.PRICE_ACTION_MIN_PRICE:
                        logger.debug(f"{symbol}: Price {current_price:.2f} below minimum {config.PRICE_ACTION_MIN_PRICE}")
                        continue

                    # Apply volume filter
                    if avg_volume < config.PRICE_ACTION_MIN_AVG_VOLUME:
                        logger.debug(f"{symbol}: Avg volume {avg_volume:.0f} below minimum {config.PRICE_ACTION_MIN_AVG_VOLUME}")
                        continue

                    # Detect patterns
                    result = self.detector.detect_patterns(
                        symbol=symbol,
                        candles=candles,
                        market_regime=market_regime,
                        current_price=current_price,
                        avg_volume=avg_volume
                    )

                    if result['has_patterns']:
                        stats['patterns_detected'] += len(result['patterns_found'])

                        # Send alerts for each pattern
                        for pattern_name in result['patterns_found']:
                            pattern_key = pattern_name.lower().replace(' ', '_')
                            pattern_details = result['pattern_details'][pattern_key]

                            # Count by type
                            if pattern_details['type'] == 'bullish':
                                stats['bullish_patterns'] += 1
                            elif pattern_details['type'] == 'bearish':
                                stats['bearish_patterns'] += 1
                            else:
                                stats['neutral_patterns'] += 1

                            # Check if opportunity has already passed
                            target = pattern_details.get('target')
                            entry_price = pattern_details.get('entry_price')
                            pattern_type = pattern_details['type']

                            if target and entry_price:
                                if pattern_type == 'bullish':
                                    # For bullish patterns, skip if current price >= target
                                    if current_price >= target:
                                        logger.info(f"{symbol}: Skipping {pattern_name} - price already at/above target "
                                                   f"(current: ₹{current_price:.2f}, target: ₹{target:.2f})")
                                        continue
                                elif pattern_type == 'bearish':
                                    # For bearish patterns, skip if current price <= target
                                    if current_price <= target:
                                        logger.info(f"{symbol}: Skipping {pattern_name} - price already at/below target "
                                                   f"(current: ₹{current_price:.2f}, target: ₹{target:.2f})")
                                        continue

                            # Check cooldown
                            alert_key = f"price_action_{symbol}_{pattern_name}"
                            if not self.alert_history.should_send_alert(
                                symbol, alert_key,
                                cooldown_minutes=config.PRICE_ACTION_COOLDOWN
                            ):
                                logger.debug(f"{symbol}: Skipping {pattern_name} (within cooldown)")
                                continue

                            # Send alert
                            self._send_alert(
                                symbol=symbol,
                                pattern_name=pattern_name,
                                pattern_details=pattern_details,
                                current_price=current_price,
                                market_regime=market_regime
                            )
                            stats['alerts_sent'] += 1

                except Exception as e:
                    logger.error(f"{symbol}: Error processing - {e}", exc_info=True)
                    stats['errors'] += 1

        except Exception as e:
            logger.error(f"Fatal error in monitor cycle: {e}", exc_info=True)
            stats['errors'] += 1

        # Print summary
        logger.info("=" * 80)
        logger.info(f"PRICE ACTION MONITOR - Cycle complete")
        logger.info(f"  Checked: {stats['total_checked']} stocks")
        logger.info(f"  Patterns: {stats['patterns_detected']} "
                   f"({stats['bullish_patterns']} bullish, "
                   f"{stats['bearish_patterns']} bearish, "
                   f"{stats['neutral_patterns']} neutral)")
        logger.info(f"  Alerts: {stats['alerts_sent']}")
        logger.info(f"  Errors: {stats['errors']}")
        logger.info("=" * 80)

        # Report health metrics at end of cycle
        report_cycle_complete(
            service_name="price_action_monitor",
            cycle_start_time=cycle_start_time,
            stats={
                "stocks_checked": stats['total_checked'],
                "patterns_detected": stats['patterns_detected'],
                "alerts_sent": stats['alerts_sent'],
                "errors": stats['errors']
            }
        )

        return stats

    def _get_market_regime(self) -> str:
        """
        Determine market regime using Nifty 50 vs 50-day SMA

        Returns:
            'BULLISH', 'BEARISH', or 'NEUTRAL'
        """
        try:
            # Fetch Nifty 50 current price from Central DB (with freshness check + API fallback)
            indices = fetch_nifty_vix(
                service_name="price_action_monitor",
                kite_client=self.kite,
                coordinator=None,  # No coordinator in this service
                max_age_minutes=2
            )
            current_price = indices.get('nifty_spot')

            if not current_price:
                logger.warning("Unable to fetch NIFTY spot price")
                return 'NEUTRAL'

            # Fetch 50-day historical data for SMA calculation (keep on API - historical data not in central DB)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=70)  # Extra buffer for holidays

            nifty_data = self.kite.historical_data(
                instrument_token=self.NIFTY_50_TOKEN,
                from_date=start_date,
                to_date=end_date,
                interval="day"
            )

            if len(nifty_data) < 50:
                logger.warning(f"Insufficient Nifty data for SMA calculation ({len(nifty_data)} days)")
                return 'NEUTRAL'

            # Calculate 50-day SMA
            recent_50_closes = [candle['close'] for candle in nifty_data[-50:]]
            sma_50 = sum(recent_50_closes) / 50

            # Determine regime
            diff_pct = ((current_price - sma_50) / sma_50) * 100

            if diff_pct >= 0.5:
                regime = 'BULLISH'
            elif diff_pct <= -0.5:
                regime = 'BEARISH'
            else:
                regime = 'NEUTRAL'

            logger.info(f"Nifty 50: {current_price:.2f}, SMA(50): {sma_50:.2f}, Diff: {diff_pct:+.2f}% => {regime}")
            return regime

        except Exception as e:
            logger.error(f"Market regime detection failed: {e}", exc_info=True)
            return 'NEUTRAL'

    def _fetch_5min_candles(self) -> Dict:
        """
        Fetch 5-minute candles for all stocks

        Returns:
            Dict mapping symbol to candle data:
            {
                'symbol': {
                    'candles': List[Dict],
                    'current_price': float,
                    'avg_volume': float
                }
            }
        """
        candle_data = {}

        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=6)  # Last 6 hours (enough for 50+ candles)

            for symbol in self.stocks:
                try:
                    # Get instrument token
                    instrument_token = self._get_instrument_token(symbol)
                    if not instrument_token:
                        continue

                    # Fetch from Kite API
                    candles = self.kite.historical_data(
                        instrument_token=instrument_token,
                        from_date=start_time,
                        to_date=end_time,
                        interval="5minute"
                    )

                    if len(candles) >= config.PRICE_ACTION_LOOKBACK_CANDLES:
                        # Calculate average volume from last 20 candles
                        volumes = [c['volume'] for c in candles[-20:]]
                        avg_volume = sum(volumes) / len(volumes) if volumes else 0

                        candle_data[symbol] = {
                            'candles': candles,
                            'current_price': candles[-1]['close'],
                            'avg_volume': avg_volume
                        }
                    else:
                        logger.debug(f"{symbol}: Insufficient candles ({len(candles)})")

                except Exception as e:
                    logger.debug(f"{symbol}: Failed to fetch candles - {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to fetch candle data: {e}", exc_info=True)

        return candle_data

    def _send_alert(
        self,
        symbol: str,
        pattern_name: str,
        pattern_details: Dict,
        current_price: float,
        market_regime: str
    ):
        """
        Send pattern alert via Telegram and log to Excel

        Args:
            symbol: Stock symbol
            pattern_name: Pattern name
            pattern_details: Pattern detection result dict
            current_price: Current market price
            market_regime: Current market regime
        """
        try:
            # Send Telegram alert
            telegram_sent = self.telegram.send_price_action_alert(
                symbol=symbol,
                pattern_name=pattern_name,
                pattern_type=pattern_details['type'],
                confidence_score=pattern_details['confidence_score'],
                entry_price=pattern_details['entry_price'],
                target=pattern_details.get('target'),
                stop_loss=pattern_details.get('stop_loss'),
                current_price=current_price,
                pattern_details=pattern_details,
                market_regime=market_regime
            )
            logger.info(f"{symbol}: Telegram alert sent for {pattern_name} (confidence: {pattern_details['confidence_score']:.1f})")
        except Exception as e:
            logger.error(f"{symbol}: Failed to send Telegram alert - {e}", exc_info=True)
            telegram_sent = False

        # Log to Excel
        try:
            self.excel_logger.log_price_action_alert(
                symbol=symbol,
                pattern_name=pattern_name,
                pattern_type=pattern_details['type'],
                confidence_score=pattern_details['confidence_score'],
                entry_price=pattern_details['entry_price'],
                target=pattern_details.get('target'),
                stop_loss=pattern_details.get('stop_loss'),
                volume_ratio=pattern_details['volume_ratio'],
                market_regime=market_regime,
                telegram_sent=telegram_sent
            )
            logger.info(f"{symbol}: Logged {pattern_name} to Excel")
        except Exception as e:
            logger.error(f"{symbol}: Failed to log to Excel - {e}", exc_info=True)


def main():
    """Main entry point"""
    cycle_start = time.time()
    health = get_health_tracker()

    try:
        monitor = PriceActionMonitor()
        monitor.monitor()

        # Record heartbeat
        cycle_duration_ms = int((time.time() - cycle_start) * 1000)
        health.heartbeat("price_action_monitor", cycle_duration_ms)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Still record heartbeat on error so service shows as running
        cycle_duration_ms = int((time.time() - cycle_start) * 1000)
        health.heartbeat("price_action_monitor", cycle_duration_ms)
        health.report_error("price_action_monitor", "fatal_error", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
