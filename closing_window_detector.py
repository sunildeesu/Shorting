#!/usr/bin/env python3
"""
Institutional Closing Window Detector (3:10-3:25 PM)

Detects unusual price acceleration + volume surges in the closing window.
Institutions often place large buy/sell orders in the final 15-20 minutes
before market close (3:30 PM), causing sharp directional moves.

Composite Score (0-100):
- Price Acceleration: 35 pts (market-adjusted window price change vs day avg)
- Volume Surge: 35 pts (volume-per-minute in window vs day avg)
- Directional Strength: 20 pts (% candles in same direction)
- NIFTY-Relative Move: 10 pts (stock-specific vs market-wide)

Alert threshold: composite >= 65/100
Time-gated: only active 15:10-15:25

Author: Claude Opus 4.6
Date: 2026-02-19
"""

import logging
import time
from datetime import datetime, date, time as dt_time
from typing import Dict, List, Optional, Set

import config

logger = logging.getLogger(__name__)


class ClosingWindowDetector:
    """
    Detects institutional activity in the closing window (3:10-3:25 PM).

    Runs in central_data_collector_continuous.py after each collect_and_store() cycle.
    Zero additional API calls - reads from central_quotes.db.
    """

    def __init__(self, central_db, alert_history, telegram):
        """
        Initialize detector with shared components.

        Args:
            central_db: CentralQuoteDB instance (reader mode)
            alert_history: AlertHistoryManager instance
            telegram: TelegramNotifier instance
        """
        self.db = central_db
        self.alert_history = alert_history
        self.telegram = telegram

        # Configuration
        self.min_score = config.CLOSING_WINDOW_MIN_SCORE  # Default: 65
        self.send_summary = config.CLOSING_WINDOW_SEND_SUMMARY  # Default: True

        # Time window
        self.window_start = dt_time(15, 10)
        self.window_end = dt_time(15, 25)
        self.min_candles = 3  # Require >= 3 window candles before scoring

        # Daily state (reset each day)
        self._current_date: Optional[date] = None
        self._alerted_today: Set[str] = set()  # One alert per stock per day
        self._summary_sent_today = False
        self._day_baseline: Optional[Dict] = None  # Cached at 3:10 PM
        self._nifty_window_start_price: Optional[float] = None
        self._window_scores: Dict[str, Dict] = {}  # Track all scored stocks for summary

        logger.info(f"ClosingWindowDetector initialized (min_score: {self.min_score}, "
                    f"summary: {self.send_summary}, window: 15:10-15:25)")

    def _reset_daily_state(self):
        """Reset all tracking state for a new day."""
        self._current_date = date.today()
        self._alerted_today = set()
        self._summary_sent_today = False
        self._day_baseline = None
        self._nifty_window_start_price = None
        self._window_scores = {}
        logger.info("ClosingWindowDetector: Daily state reset")

    def detect_all(self, current_quotes: Dict[str, Dict]) -> Dict:
        """
        Detect institutional closing window activity for all stocks.

        Args:
            current_quotes: Dict of {symbol: {price, volume, oi, ...}} from just-collected data

        Returns:
            Dict with stats: {alerts_sent, stocks_scored, execution_ms}
        """
        start_time = time.time()

        stats = {
            'alerts_sent': 0,
            'stocks_scored': 0,
            'execution_ms': 0
        }

        # Daily reset check
        today = date.today()
        if self._current_date != today:
            self._reset_daily_state()

        # Time gate: only active 15:10-15:25
        now = datetime.now()
        current_time = now.time()
        if current_time < self.window_start or current_time > self.window_end:
            return stats

        if not current_quotes:
            logger.warning("ClosingWindowDetector: No current quotes provided")
            return stats

        symbols = list(current_quotes.keys())
        today_str = now.strftime('%Y-%m-%d')
        window_start_str = f"{today_str} 15:10:00"

        try:
            # Compute day baseline once at window entry (3:10 PM)
            if self._day_baseline is None:
                self._day_baseline = self._compute_day_baseline(symbols, today_str)
                if not self._day_baseline:
                    logger.warning("ClosingWindowDetector: Failed to compute day baseline")
                    return stats

                # Record NIFTY price at window start
                nifty = self.db.get_nifty_latest()
                if nifty:
                    self._nifty_window_start_price = nifty['price']
                    logger.info(f"ClosingWindowDetector: NIFTY at window start: {self._nifty_window_start_price:.2f}")

                logger.info(f"ClosingWindowDetector: Day baseline computed for {len(self._day_baseline)} stocks")

            # Get window data for all stocks (batch query)
            window_data = self.db.get_stock_history_since_batch(symbols, window_start_str)

            # Get NIFTY window data
            nifty_window = self.db.get_nifty_history_since(window_start_str)
            nifty_current_price = None
            if nifty_window:
                nifty_current_price = nifty_window[-1]['price']

            # Compute NIFTY window change
            nifty_change_pct = 0.0
            if self._nifty_window_start_price and nifty_current_price:
                nifty_change_pct = ((nifty_current_price - self._nifty_window_start_price)
                                    / self._nifty_window_start_price) * 100

            # Score each stock
            for symbol, quote_data in current_quotes.items():
                try:
                    current_price = quote_data.get('price')
                    if not current_price or current_price <= 0:
                        continue

                    # Get stock's window candles
                    candles = window_data.get(symbol, [])
                    if len(candles) < self.min_candles:
                        continue

                    # Get day baseline for this stock
                    baseline = self._day_baseline.get(symbol)
                    if not baseline:
                        continue

                    # Score the stock
                    score_result = self._score_stock(
                        symbol=symbol,
                        candles=candles,
                        current_price=current_price,
                        baseline=baseline,
                        nifty_change_pct=nifty_change_pct
                    )

                    if not score_result:
                        continue

                    stats['stocks_scored'] += 1
                    composite_score = score_result['composite']

                    # Track for summary
                    if composite_score >= self.min_score:
                        self._window_scores[symbol] = score_result

                    # Send real-time alert if threshold met and not already alerted
                    if composite_score >= self.min_score and symbol not in self._alerted_today:
                        success = self._send_stock_alert(symbol, score_result, nifty_change_pct, len(candles))
                        if success:
                            self._alerted_today.add(symbol)
                            stats['alerts_sent'] += 1
                            logger.info(f"CLOSING WINDOW ALERT: {symbol} score={composite_score}/100 "
                                       f"price={score_result['price_change_pct']:+.2f}% "
                                       f"vol={score_result['volume_ratio']:.1f}x")

                except Exception as e:
                    logger.error(f"ClosingWindowDetector: Error scoring {symbol}: {e}")

            # Send summary at 3:25 PM (within last minute of window)
            if (self.send_summary and not self._summary_sent_today
                    and current_time >= dt_time(15, 24, 30)):
                self._send_summary(nifty_change_pct)
                self._summary_sent_today = True

        except Exception as e:
            logger.error(f"ClosingWindowDetector: Detection error: {e}", exc_info=True)

        stats['execution_ms'] = int((time.time() - start_time) * 1000)

        if stats['alerts_sent'] > 0:
            logger.info(f"ClosingWindowDetector: {stats['alerts_sent']} alerts, "
                       f"{stats['stocks_scored']} stocks scored in {stats['execution_ms']}ms")
        else:
            logger.debug(f"ClosingWindowDetector: {stats['stocks_scored']} stocks scored, "
                        f"0 alerts in {stats['execution_ms']}ms")

        return stats

    def _compute_day_baseline(self, symbols: List[str], today_str: str) -> Optional[Dict[str, Dict]]:
        """
        Compute day baseline for all stocks (cached once at 3:10 PM).

        Returns:
            Dict mapping symbol to {total_volume, day_high, day_low, avg_vol_per_min,
                                     avg_15min_change_pct, window_start_price}
        """
        try:
            # Get day aggregates (batch)
            aggregates = self.db.get_stock_day_aggregates_batch(symbols)
            if not aggregates:
                return None

            # Get stock history for computing avg 15-min changes
            # Query from start of day until now
            day_start_str = f"{today_str} 09:15:00"
            all_history = self.db.get_stock_history_since_batch(symbols, day_start_str)

            baseline = {}
            for symbol in symbols:
                agg = aggregates.get(symbol)
                if not agg or agg['candle_count'] < 10:  # Need reasonable day data
                    continue

                history = all_history.get(symbol, [])
                if len(history) < 10:
                    continue

                # Avg volume per minute (cumulative volume / minutes elapsed)
                candle_count = agg['candle_count']
                total_volume = agg['total_volume']
                avg_vol_per_min = total_volume / candle_count if candle_count > 0 else 0

                # Compute avg 15-min absolute price change
                avg_15min_change = self._compute_avg_15min_change(history)

                # Window start price = most recent price (at 3:10 PM)
                window_start_price = history[-1]['price'] if history else 0

                baseline[symbol] = {
                    'total_volume': total_volume,
                    'day_high': agg['day_high'],
                    'day_low': agg['day_low'],
                    'avg_vol_per_min': avg_vol_per_min,
                    'avg_15min_change_pct': avg_15min_change,
                    'window_start_price': window_start_price,
                    'candle_count': candle_count
                }

            return baseline

        except Exception as e:
            logger.error(f"ClosingWindowDetector: Baseline computation failed: {e}")
            return None

    def _compute_avg_15min_change(self, history: List[Dict]) -> float:
        """
        Compute average absolute price change over 15-minute intervals.

        Samples prices at ~15 minute intervals throughout the day and
        averages the absolute percentage changes.
        """
        if len(history) < 15:
            return 0.0

        changes = []
        step = 15  # Sample every 15 candles (minutes)
        for i in range(step, len(history), step):
            prev_price = history[i - step]['price']
            curr_price = history[i]['price']
            if prev_price > 0:
                change_pct = abs((curr_price - prev_price) / prev_price) * 100
                changes.append(change_pct)

        return sum(changes) / len(changes) if changes else 0.0

    def _score_stock(self, symbol: str, candles: List[Dict], current_price: float,
                     baseline: Dict, nifty_change_pct: float) -> Optional[Dict]:
        """
        Score a stock's closing window activity (0-100).

        Components:
        - Price Acceleration: 35 pts max
        - Volume Surge: 35 pts max
        - Directional Strength: 20 pts max
        - NIFTY-Relative Move: 10 pts max

        Returns:
            Dict with scoring breakdown or None if insufficient data
        """
        window_start_price = baseline['window_start_price']
        if window_start_price <= 0:
            return None

        # === Price Acceleration (35 pts max) ===
        price_change_pct = ((current_price - window_start_price) / window_start_price) * 100
        abs_change = abs(price_change_pct)

        avg_15min_change = baseline['avg_15min_change_pct']
        if avg_15min_change > 0:
            acceleration_ratio = abs_change / avg_15min_change
        else:
            acceleration_ratio = abs_change / 0.1  # Fallback for very flat days

        # Scale: 1x = 0pts, 2x = 15pts, 3x = 25pts, 4x+ = 30pts
        if acceleration_ratio >= 4.0:
            price_score = 30
        elif acceleration_ratio >= 3.0:
            price_score = 25
        elif acceleration_ratio >= 2.0:
            price_score = 15
        elif acceleration_ratio >= 1.5:
            price_score = 10
        elif acceleration_ratio >= 1.0:
            price_score = 5
        else:
            price_score = 0

        # Bonus for new intraday high/low (+5 pts)
        new_extreme = False
        if current_price > baseline['day_high'] or current_price < baseline['day_low']:
            price_score = min(35, price_score + 5)
            new_extreme = True

        # === Volume Surge (35 pts max) ===
        # Compute window volume per minute from cumulative deltas
        window_vol_per_min = self._compute_window_volume_per_min(candles)
        avg_vol_per_min = baseline['avg_vol_per_min']

        volume_ratio = 0.0
        if avg_vol_per_min > 0:
            volume_ratio = window_vol_per_min / avg_vol_per_min
        elif window_vol_per_min > 0:
            volume_ratio = 5.0  # Fallback: strong signal if day avg is 0

        # Scale: 1x = 0pts, 1.5x = 10pts, 2x = 20pts, 3x = 30pts, 4x+ = 35pts
        if volume_ratio >= 4.0:
            volume_score = 35
        elif volume_ratio >= 3.0:
            volume_score = 30
        elif volume_ratio >= 2.0:
            volume_score = 20
        elif volume_ratio >= 1.5:
            volume_score = 10
        elif volume_ratio >= 1.2:
            volume_score = 5
        else:
            volume_score = 0

        # === Directional Strength (20 pts max) ===
        direction_info = self._compute_direction_strength(candles)
        direction_pct = direction_info['consistency_pct']

        # Scale: 50% = 0pts, 60% = 5pts, 70% = 10pts, 80% = 15pts, 90%+ = 20pts
        if direction_pct >= 90:
            direction_score = 20
        elif direction_pct >= 80:
            direction_score = 15
        elif direction_pct >= 70:
            direction_score = 10
        elif direction_pct >= 60:
            direction_score = 5
        else:
            direction_score = 0

        # === NIFTY-Relative Move (10 pts max) ===
        relative_move = abs(price_change_pct) - abs(nifty_change_pct)

        if relative_move >= 0.5:
            nifty_score = 10
        elif relative_move >= 0.3:
            nifty_score = 6
        elif relative_move >= 0.1:
            nifty_score = 3
        else:
            nifty_score = 0

        composite = price_score + volume_score + direction_score + nifty_score

        # Determine direction (buying vs selling)
        is_buying = price_change_pct > 0

        return {
            'composite': composite,
            'price_score': price_score,
            'volume_score': volume_score,
            'direction_score': direction_score,
            'nifty_score': nifty_score,
            'price_change_pct': price_change_pct,
            'volume_ratio': volume_ratio,
            'direction_pct': direction_pct,
            'direction_candles': direction_info['same_dir_count'],
            'total_candles': direction_info['total_candles'],
            'relative_move': relative_move,
            'is_buying': is_buying,
            'new_extreme': new_extreme,
            'window_start_price': window_start_price,
            'current_price': current_price,
        }

    def _compute_window_volume_per_min(self, candles: List[Dict]) -> float:
        """
        Compute average volume per minute in the window.
        Volume in DB is cumulative, so we compute deltas.
        """
        if len(candles) < 2:
            return 0.0

        total_delta = 0
        delta_count = 0
        for i in range(1, len(candles)):
            vol_now = candles[i].get('volume', 0) or 0
            vol_prev = candles[i - 1].get('volume', 0) or 0
            delta = vol_now - vol_prev
            if delta > 0:  # Only count positive deltas (cumulative volume should increase)
                total_delta += delta
                delta_count += 1

        return total_delta / delta_count if delta_count > 0 else 0.0

    def _compute_direction_strength(self, candles: List[Dict]) -> Dict:
        """
        Compute directional consistency (% of candles in same direction).
        """
        if len(candles) < 2:
            return {'consistency_pct': 50, 'same_dir_count': 0, 'total_candles': 0, 'dominant_dir': 'neutral'}

        green_count = 0
        red_count = 0

        for i in range(1, len(candles)):
            curr_price = candles[i]['price']
            prev_price = candles[i - 1]['price']
            if curr_price > prev_price:
                green_count += 1
            elif curr_price < prev_price:
                red_count += 1

        total = green_count + red_count
        if total == 0:
            return {'consistency_pct': 50, 'same_dir_count': 0, 'total_candles': 0, 'dominant_dir': 'neutral'}

        same_dir_count = max(green_count, red_count)
        consistency_pct = (same_dir_count / total) * 100
        dominant_dir = 'green' if green_count >= red_count else 'red'

        return {
            'consistency_pct': consistency_pct,
            'same_dir_count': same_dir_count,
            'total_candles': total,
            'dominant_dir': dominant_dir
        }

    def _send_stock_alert(self, symbol: str, score: Dict, nifty_change_pct: float,
                          window_candles: int) -> bool:
        """Send real-time Telegram alert for a stock with institutional activity."""
        try:
            direction_emoji = "\U0001f7e2" if score['is_buying'] else "\U0001f534"
            direction_text = "BUYING" if score['is_buying'] else "SELLING"
            price_arrow = "+" if score['price_change_pct'] > 0 else ""

            # Window time info
            now = datetime.now()
            minutes_in_window = window_candles

            parts = [
                f"\U0001f3db <b>INSTITUTIONAL ACTIVITY DETECTED</b>",
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
                f"\U0001f4ca <b>{symbol}</b>",
                f"{direction_emoji} Institutional {direction_text}",
                f"",
                f"\U0001f4b0 Price: \u20b9{score['window_start_price']:,.2f} \u2192 \u20b9{score['current_price']:,.2f} ({price_arrow}{score['price_change_pct']:.2f}%)",
                f"\U0001f4ca Volume: {score['volume_ratio']:.1f}x avg/min",
                f"\U0001f4c8 Direction: {score['direction_candles']}/{score['total_candles']} candles {'green' if score['is_buying'] else 'red'}",
                f"\U0001f4c9 NIFTY: {nifty_change_pct:+.2f}% | Stock-specific: {score['relative_move']:+.2f}%",
                f"\U0001f3c6 Score: {score['composite']}/100",
                f"\u23f0 Window: 3:10 - {now.strftime('%-I:%M')} PM ({minutes_in_window} min)",
            ]

            if score['new_extreme']:
                extreme_type = "HIGH" if score['is_buying'] else "LOW"
                parts.append(f"\U0001f4c8 NEW INTRADAY {extreme_type}")

            parts.append(f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")

            message = "\n".join(parts)
            return self._send_telegram_message(message)

        except Exception as e:
            logger.error(f"ClosingWindowDetector: Failed to send alert for {symbol}: {e}")
            return False

    def _send_summary(self, nifty_change_pct: float):
        """Send consolidated summary at 3:25 PM."""
        try:
            if not self._window_scores:
                logger.info("ClosingWindowDetector: No stocks met threshold for summary")
                return

            # Separate buying and selling
            buying = {s: d for s, d in self._window_scores.items() if d['is_buying']}
            selling = {s: d for s, d in self._window_scores.items() if not d['is_buying']}

            # Sort by score descending
            buying_sorted = sorted(buying.items(), key=lambda x: x[1]['composite'], reverse=True)
            selling_sorted = sorted(selling.items(), key=lambda x: x[1]['composite'], reverse=True)

            parts = [
                f"\U0001f3db <b>CLOSING WINDOW SUMMARY (3:10-3:25 PM)</b>",
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
                f"NIFTY: {nifty_change_pct:+.2f}% in window",
                "",
            ]

            if buying_sorted:
                parts.append(f"\U0001f7e2 <b>BUYING ({len(buying_sorted)}):</b>")
                for symbol, data in buying_sorted:
                    parts.append(f"  {symbol} {data['composite']}/100 | +{data['price_change_pct']:.2f}% | {data['volume_ratio']:.1f}x vol")
                parts.append("")

            if selling_sorted:
                parts.append(f"\U0001f534 <b>SELLING ({len(selling_sorted)}):</b>")
                for symbol, data in selling_sorted:
                    parts.append(f"  {symbol} {data['composite']}/100 | {data['price_change_pct']:.2f}% | {data['volume_ratio']:.1f}x vol")
                parts.append("")

            if not buying_sorted and not selling_sorted:
                parts.append("No institutional signals detected today.")

            parts.append(f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")

            message = "\n".join(parts)
            self._send_telegram_message(message)
            logger.info(f"ClosingWindowDetector: Summary sent ({len(buying_sorted)} buying, "
                       f"{len(selling_sorted)} selling)")

        except Exception as e:
            logger.error(f"ClosingWindowDetector: Failed to send summary: {e}")

    def _send_telegram_message(self, message: str) -> bool:
        """Send message to Telegram using the notifier's connection."""
        try:
            import requests

            url = f"https://api.telegram.org/bot{self.telegram.bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram.channel_id,
                "text": message,
                "parse_mode": "HTML"
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return True

        except Exception as e:
            logger.error(f"ClosingWindowDetector: Telegram send failed: {e}")
            return False
