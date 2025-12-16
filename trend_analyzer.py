#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Trend Analyzer Module

Analyzes stock trends for swing trading (2-10 day holds).
Calculates technical indicators and generates entry/exit signals.

Strategy:
- Identifies strong trends using MA alignment, ADX, MACD
- Detects entry signals (pullback to support, breakouts)
- Calculates stop loss and target prices
- Provides risk-reward analysis

Author: Sunil Kumar Durganaik
"""

import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """
    Comprehensive trend analysis for swing trading.

    Uses moving averages, ADX, MACD, RSI, and support/resistance
    to identify trends and generate actionable trading signals.
    """

    def __init__(self, df: pd.DataFrame, symbol: str = "UNKNOWN"):
        """
        Initialize trend analyzer with historical data.

        Args:
            df: DataFrame with OHLCV data (columns: date, open, high, low, close, volume)
            symbol: Stock symbol for logging
        """
        self.df = df.copy()
        self.symbol = symbol

        # Ensure required columns exist
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing = [col for col in required_cols if col not in self.df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Convert date column to datetime if it exists
        if 'date' in self.df.columns:
            if not pd.api.types.is_datetime64_any_dtype(self.df['date']):
                self.df['date'] = pd.to_datetime(self.df['date'])

        # Ensure numeric types
        for col in required_cols:
            self.df[col] = pd.to_numeric(self.df[col], errors='coerce')

        # Sort by date (oldest first)
        if 'date' in self.df.columns:
            self.df = self.df.sort_values('date').reset_index(drop=True)

        # Calculate all indicators
        self._calculate_indicators()

    def _calculate_indicators(self):
        """Calculate all technical indicators"""
        try:
            # Moving Averages
            self.df['ema_20'] = ta.ema(self.df['close'], length=20)
            self.df['sma_50'] = ta.sma(self.df['close'], length=50)
            self.df['sma_200'] = ta.sma(self.df['close'], length=200)

            # ADX (Average Directional Index)
            adx_df = ta.adx(self.df['high'], self.df['low'], self.df['close'], length=14)
            if adx_df is not None:
                self.df = pd.concat([self.df, adx_df], axis=1)

            # MACD
            macd_df = ta.macd(self.df['close'], fast=12, slow=26, signal=9)
            if macd_df is not None:
                self.df = pd.concat([self.df, macd_df], axis=1)

            # RSI
            self.df['rsi_14'] = ta.rsi(self.df['close'], length=14)

            # ATR (Average True Range) for stop loss
            self.df['atr_14'] = ta.atr(self.df['high'], self.df['low'], self.df['close'], length=14)

            # Volume SMA
            self.df['volume_sma_20'] = ta.sma(self.df['volume'], length=20)

            logger.debug(f"{self.symbol}: Calculated all technical indicators")

        except Exception as e:
            logger.error(f"{self.symbol}: Error calculating indicators: {e}")
            raise

    def get_latest_values(self) -> Dict:
        """
        Get latest indicator values for current analysis.

        Returns:
            Dict with latest indicator values
        """
        if len(self.df) == 0:
            return {}

        latest = self.df.iloc[-1]

        return {
            'close': latest['close'],
            'ema_20': latest.get('ema_20', np.nan),
            'sma_50': latest.get('sma_50', np.nan),
            'sma_200': latest.get('sma_200', np.nan),
            'adx': latest.get('ADX_14', np.nan),
            'dmp': latest.get('DMP_14', np.nan),  # +DI
            'dmn': latest.get('DMN_14', np.nan),  # -DI
            'macd': latest.get('MACD_12_26_9', np.nan),
            'macd_signal': latest.get('MACDs_12_26_9', np.nan),
            'macd_hist': latest.get('MACDh_12_26_9', np.nan),
            'rsi': latest.get('rsi_14', np.nan),
            'atr': latest.get('atr_14', np.nan),
            'volume': latest['volume'],
            'volume_avg': latest.get('volume_sma_20', np.nan)
        }

    def identify_trend(self) -> Dict:
        """
        Identify current trend using multiple confirmation signals.

        Scoring system (0-10):
        - MA Alignment: 3 points
        - ADX Strength: 2 points
        - MACD Confirmation: 2 points
        - Higher highs/Lower lows: 3 points

        Returns:
            Dict with trend analysis
        """
        vals = self.get_latest_values()
        score = 0
        signals = []

        current_price = vals['close']
        ema_20 = vals['ema_20']
        sma_50 = vals['sma_50']
        sma_200 = vals['sma_200']

        # Check if we have enough data
        if pd.isna(ema_20) or pd.isna(sma_50) or pd.isna(sma_200):
            return {
                'trend': 'Insufficient Data',
                'score': 0,
                'signals': ['INSUFFICIENT_DATA'],
                'confidence': 'Low'
            }

        # 1. MA Alignment (3 points)
        if current_price > ema_20 > sma_50 > sma_200:
            score += 3
            signals.append("MA_ALIGNED_BULLISH")
        elif current_price > ema_20 > sma_50:
            score += 2
            signals.append("MA_SEMI_BULLISH")
        elif current_price < ema_20 < sma_50 < sma_200:
            score -= 3
            signals.append("MA_ALIGNED_BEARISH")
        elif current_price < ema_20 < sma_50:
            score -= 2
            signals.append("MA_SEMI_BEARISH")

        # 2. ADX Trend Strength (2 points)
        adx = vals['adx']
        dmp = vals['dmp']
        dmn = vals['dmn']

        if not pd.isna(adx) and adx > 25:
            if not pd.isna(dmp) and not pd.isna(dmn):
                if dmp > dmn:
                    score += 2
                    signals.append("ADX_BULLISH")
                else:
                    score -= 2
                    signals.append("ADX_BEARISH")
        elif not pd.isna(adx) and adx < 20:
            signals.append("ADX_CHOPPY")

        # 3. MACD Confirmation (2 points)
        macd_line = vals['macd']
        macd_signal = vals['macd_signal']

        if not pd.isna(macd_line) and not pd.isna(macd_signal):
            if macd_line > macd_signal and macd_line > 0:
                score += 2
                signals.append("MACD_STRONG_BULLISH")
            elif macd_line > macd_signal:
                score += 1
                signals.append("MACD_BULLISH")
            elif macd_line < macd_signal and macd_line < 0:
                score -= 2
                signals.append("MACD_STRONG_BEARISH")
            elif macd_line < macd_signal:
                score -= 1
                signals.append("MACD_BEARISH")

        # 4. Higher Highs / Lower Lows (3 points)
        if len(self.df) >= 20:
            recent_20 = self.df.tail(20)

            # Check for higher highs (last 3 swing highs ascending)
            highs = recent_20['high'].nlargest(3).sort_index()
            if len(highs) >= 3 and highs.is_monotonic_increasing:
                score += 3
                signals.append("HIGHER_HIGHS")

            # Check for lower lows (last 3 swing lows descending)
            lows = recent_20['low'].nsmallest(3).sort_index()
            if len(lows) >= 3 and lows.is_monotonic_decreasing:
                score -= 3
                signals.append("LOWER_LOWS")

        # Classify trend based on score
        if score >= 7:
            trend = "Strong Uptrend"
            confidence = "High"
        elif score >= 4:
            trend = "Uptrend"
            confidence = "Medium"
        elif score >= 1:
            trend = "Weak Uptrend"
            confidence = "Low"
        elif score <= -7:
            trend = "Strong Downtrend"
            confidence = "High"
        elif score <= -4:
            trend = "Downtrend"
            confidence = "Medium"
        elif score <= -1:
            trend = "Weak Downtrend"
            confidence = "Low"
        else:
            trend = "Neutral"
            confidence = "Low"

        # Calculate price distance from MAs
        pct_from_ema20 = ((current_price - ema_20) / ema_20) * 100 if not pd.isna(ema_20) else 0
        pct_from_sma50 = ((current_price - sma_50) / sma_50) * 100 if not pd.isna(sma_50) else 0
        pct_from_sma200 = ((current_price - sma_200) / sma_200) * 100 if not pd.isna(sma_200) else 0

        return {
            'trend': trend,
            'score': score,
            'signals': signals,
            'confidence': confidence,
            'pct_from_ema20': round(pct_from_ema20, 2),
            'pct_from_sma50': round(pct_from_sma50, 2),
            'pct_from_sma200': round(pct_from_sma200, 2),
            'adx': round(adx, 1) if not pd.isna(adx) else 0,
            'adx_signal': "+DI > -DI" if (not pd.isna(dmp) and not pd.isna(dmn) and dmp > dmn) else "-DI > +DI"
        }

    def detect_entry_signal(self, trend_analysis: Optional[Dict] = None) -> Dict:
        """
        Detect swing trading entry signals.

        Entry types:
        - Pullback: Price pulls back to 20 EMA in uptrend
        - Breakout: Price breaks resistance with volume
        - Wait: No clear signal
        - Avoid: Downtrend or choppy market

        Args:
            trend_analysis: Pre-calculated trend analysis (optional)

        Returns:
            Dict with entry signal details
        """
        if trend_analysis is None:
            trend_analysis = self.identify_trend()

        vals = self.get_latest_values()

        current_price = vals['close']
        ema_20 = vals['ema_20']
        rsi = vals['rsi']
        adx = vals['adx']
        volume = vals['volume']
        volume_avg = vals['volume_avg']

        # Default: No signal
        signal = {
            'entry_signal': 'WAIT',
            'entry_type': 'None',
            'entry_price': 0,
            'entry_score': 0,
            'reasons': []
        }

        # Avoid signals in certain conditions
        if trend_analysis['trend'] in ['Strong Downtrend', 'Downtrend']:
            signal['entry_signal'] = 'AVOID'
            signal['reasons'].append("Stock in downtrend")
            return signal

        if not pd.isna(adx) and adx < 20:
            signal['entry_signal'] = 'WAIT'
            signal['reasons'].append("Market choppy (ADX < 20)")
            return signal

        # Only look for entries in uptrends
        if trend_analysis['trend'] not in ['Strong Uptrend', 'Uptrend', 'Weak Uptrend']:
            signal['reasons'].append("No clear uptrend")
            return signal

        entry_score = 0

        # === PULLBACK SETUP ===
        if not pd.isna(ema_20) and not pd.isna(rsi):
            # Check if price is near 20 EMA (within 3%)
            distance_from_ema = abs((current_price - ema_20) / ema_20) * 100

            if distance_from_ema <= 3:
                entry_score += 3
                signal['reasons'].append(f"Near 20 EMA ({distance_from_ema:.1f}%)")

                # RSI in sweet spot for pullback (40-60)
                if 40 <= rsi <= 60:
                    entry_score += 3
                    signal['reasons'].append(f"RSI optimal for entry ({rsi:.1f})")
                elif 30 <= rsi < 40:
                    entry_score += 2
                    signal['reasons'].append(f"RSI oversold in uptrend ({rsi:.1f})")

                # Volume confirmation
                if not pd.isna(volume_avg) and volume > volume_avg:
                    entry_score += 2
                    signal['reasons'].append("Volume above average")

                if entry_score >= 6:
                    signal['entry_signal'] = 'BUY'
                    signal['entry_type'] = 'Pullback'
                    signal['entry_price'] = current_price
                    signal['entry_score'] = entry_score
                    return signal

        # === BREAKOUT SETUP ===
        if len(self.df) >= 10:
            # Check if price is breaking recent resistance
            recent_10 = self.df.tail(10)
            resistance = recent_10['high'].iloc[:-1].max()  # Max high of last 9 days

            if current_price > resistance:
                entry_score += 3
                signal['reasons'].append("Breaking resistance")

                # Volume confirmation (2x average for breakouts)
                if not pd.isna(volume_avg) and volume > (2 * volume_avg):
                    entry_score += 3
                    signal['reasons'].append("Strong volume on breakout")

                # RSI showing momentum (50-70)
                if not pd.isna(rsi) and 50 <= rsi <= 70:
                    entry_score += 2
                    signal['reasons'].append(f"RSI showing momentum ({rsi:.1f})")

                if entry_score >= 6:
                    signal['entry_signal'] = 'BUY'
                    signal['entry_type'] = 'Breakout'
                    signal['entry_price'] = current_price
                    signal['entry_score'] = entry_score
                    return signal

        # Not enough conviction for entry
        if entry_score > 0:
            signal['reasons'].append(f"Score {entry_score}/8 - Need 6+ for entry")

        return signal

    def calculate_stop_loss_and_targets(self, entry_price: float) -> Dict:
        """
        Calculate stop loss and target prices for risk management.

        Uses ATR-based stop loss and 1:2, 1:3 risk-reward targets.

        Args:
            entry_price: Entry price for the trade

        Returns:
            Dict with stop loss, targets, and risk-reward metrics
        """
        vals = self.get_latest_values()
        atr = vals['atr']

        if pd.isna(atr) or atr == 0:
            # Fallback to 5% stop if ATR not available
            stop_loss = entry_price * 0.95
            stop_loss_pct = 5.0
        else:
            # ATR-based stop: 1.5x ATR below entry
            stop_loss = entry_price - (1.5 * atr)
            stop_loss_pct = ((entry_price - stop_loss) / entry_price) * 100

        # Calculate risk amount
        risk_per_share = entry_price - stop_loss

        # Targets based on risk-reward
        target_1 = entry_price + (2 * risk_per_share)  # 1:2 RR
        target_2 = entry_price + (3 * risk_per_share)  # 1:3 RR

        # Calculate percentages
        target_1_pct = ((target_1 - entry_price) / entry_price) * 100
        target_2_pct = ((target_2 - entry_price) / entry_price) * 100

        return {
            'stop_loss': round(stop_loss, 2),
            'stop_loss_pct': round(stop_loss_pct, 2),
            'target_1': round(target_1, 2),
            'target_1_pct': round(target_1_pct, 2),
            'target_2': round(target_2, 2),
            'target_2_pct': round(target_2_pct, 2),
            'risk_reward_1': 2.0,
            'risk_reward_2': 3.0,
            'atr': round(atr, 2) if not pd.isna(atr) else 0
        }

    def find_support_resistance(self, window: int = 5, num_levels: int = 3) -> Dict:
        """
        Identify support and resistance levels using swing highs/lows.

        Args:
            window: Window size for identifying swing points
            num_levels: Number of top support/resistance levels to return

        Returns:
            Dict with support and resistance levels
        """
        if len(self.df) < (2 * window + 1):
            return {
                'resistance_levels': [],
                'support_levels': [],
                'nearest_resistance': 0,
                'nearest_support': 0
            }

        current_price = self.df['close'].iloc[-1]

        # Find swing highs and lows
        highs = []
        lows = []

        for i in range(window, len(self.df) - window):
            # Swing high
            window_high = self.df['high'].iloc[i-window:i+window+1].max()
            if self.df['high'].iloc[i] == window_high:
                highs.append(self.df['high'].iloc[i])

            # Swing low
            window_low = self.df['low'].iloc[i-window:i+window+1].min()
            if self.df['low'].iloc[i] == window_low:
                lows.append(self.df['low'].iloc[i])

        # Filter resistance levels (above current price)
        resistance_levels = sorted([h for h in highs if h > current_price])[:num_levels]

        # Filter support levels (below current price)
        support_levels = sorted([l for l in lows if l < current_price], reverse=True)[:num_levels]

        # Find nearest levels
        nearest_resistance = resistance_levels[0] if resistance_levels else 0
        nearest_support = support_levels[0] if support_levels else 0

        return {
            'resistance_levels': [round(r, 2) for r in resistance_levels],
            'support_levels': [round(s, 2) for s in support_levels],
            'nearest_resistance': round(nearest_resistance, 2),
            'nearest_support': round(nearest_support, 2)
        }

    def calculate_pivot_points(self) -> Dict:
        """
        Calculate daily pivot points for intraday support/resistance.

        Returns:
            Dict with pivot levels (PP, R1, R2, S1, S2)
        """
        if len(self.df) == 0:
            return {'pivot': 0, 'r1': 0, 'r2': 0, 's1': 0, 's2': 0}

        last_day = self.df.iloc[-1]
        high = last_day['high']
        low = last_day['low']
        close = last_day['close']

        pivot = (high + low + close) / 3
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)

        return {
            'pivot': round(pivot, 2),
            'r1': round(r1, 2),
            'r2': round(r2, 2),
            's1': round(s1, 2),
            's2': round(s2, 2)
        }

    def calculate_position_size(self, account_size: float, risk_pct: float,
                                entry_price: float, stop_loss: float) -> Dict:
        """
        Calculate position size based on risk management rules.

        Args:
            account_size: Total account capital in ₹
            risk_pct: Risk percentage per trade (default 2%)
            entry_price: Entry price for the trade
            stop_loss: Stop loss price

        Returns:
            Dict with position sizing details
        """
        if entry_price <= stop_loss:
            return {
                'position_size': 0,
                'risk_amount': 0,
                'max_position_value': 0,
                'error': 'Stop loss must be below entry price'
            }

        # Calculate risk amount
        risk_amount = account_size * (risk_pct / 100)

        # Calculate position size
        risk_per_share = entry_price - stop_loss
        position_size = int(risk_amount / risk_per_share)

        # Calculate position value
        position_value = position_size * entry_price

        # Maximum position size (10% of account)
        max_position_value = account_size * 0.10

        if position_value > max_position_value:
            position_size = int(max_position_value / entry_price)
            position_value = position_size * entry_price

        return {
            'position_size': position_size,
            'risk_amount': round(risk_amount, 2),
            'position_value': round(position_value, 2),
            'max_position_value': round(max_position_value, 2),
            'risk_pct_actual': round((position_size * risk_per_share / account_size) * 100, 2)
        }

    def detect_short_entry_signal(self, trend_analysis: Optional[Dict] = None) -> Dict:
        """
        Detect short selling entry signals.

        Entry types:
        - Short Breakdown: Price breaks below support with volume
        - Short Rejection: Price rejected at resistance in downtrend
        - Wait: No clear signal
        - Avoid: Uptrend or choppy market

        Args:
            trend_analysis: Pre-calculated trend analysis (optional)

        Returns:
            Dict with short entry signal details
        """
        if trend_analysis is None:
            trend_analysis = self.identify_trend()

        vals = self.get_latest_values()

        current_price = vals['close']
        ema_20 = vals['ema_20']
        rsi = vals['rsi']
        adx = vals['adx']
        volume = vals['volume']
        volume_avg = vals['volume_avg']

        # Default: No signal
        signal = {
            'entry_signal': 'WAIT',
            'entry_type': 'None',
            'entry_price': 0,
            'entry_score': 0,
            'reasons': []
        }

        # Avoid signals in certain conditions
        if trend_analysis['trend'] in ['Strong Uptrend', 'Uptrend']:
            signal['entry_signal'] = 'AVOID'
            signal['reasons'].append("Stock in uptrend")
            return signal

        if not pd.isna(adx) and adx < 20:
            signal['entry_signal'] = 'WAIT'
            signal['reasons'].append("Market choppy (ADX < 20)")
            return signal

        # Only look for short entries in downtrends
        if trend_analysis['trend'] not in ['Strong Downtrend', 'Downtrend', 'Weak Downtrend']:
            signal['reasons'].append("No clear downtrend")
            return signal

        entry_score = 0

        # === SHORT REJECTION SETUP (at resistance) ===
        if not pd.isna(ema_20) and not pd.isna(rsi):
            # Check if price is near 20 EMA resistance (within 3%)
            distance_from_ema = abs((current_price - ema_20) / ema_20) * 100

            if distance_from_ema <= 3 and current_price < ema_20:  # Below EMA
                entry_score += 3
                signal['reasons'].append(f"Rejected at 20 EMA ({distance_from_ema:.1f}%)")

                # RSI in bearish zone (40-60 after rally attempt)
                if 40 <= rsi <= 60:
                    entry_score += 3
                    signal['reasons'].append(f"RSI optimal for short ({rsi:.1f})")
                elif 60 < rsi <= 70:
                    entry_score += 2
                    signal['reasons'].append(f"RSI overbought in downtrend ({rsi:.1f})")

                # Volume confirmation
                if not pd.isna(volume_avg) and volume > volume_avg:
                    entry_score += 2
                    signal['reasons'].append("Volume on rejection")

                if entry_score >= 6:
                    signal['entry_signal'] = 'SHORT'
                    signal['entry_type'] = 'Rejection'
                    signal['entry_price'] = current_price
                    signal['entry_score'] = entry_score
                    return signal

        # === SHORT BREAKDOWN SETUP (break below support) ===
        if len(self.df) >= 10:
            # Check if price is breaking recent support
            recent_10 = self.df.tail(10)
            support = recent_10['low'].iloc[:-1].min()  # Min low of last 9 days

            if current_price < support:
                entry_score += 3
                signal['reasons'].append("Breaking support")

                # Volume confirmation (2x average for breakdowns)
                if not pd.isna(volume_avg) and volume > (2 * volume_avg):
                    entry_score += 3
                    signal['reasons'].append("Strong volume on breakdown")

                # RSI showing momentum (30-50)
                if not pd.isna(rsi) and 30 <= rsi <= 50:
                    entry_score += 2
                    signal['reasons'].append(f"RSI showing bearish momentum ({rsi:.1f})")

                if entry_score >= 6:
                    signal['entry_signal'] = 'SHORT'
                    signal['entry_type'] = 'Breakdown'
                    signal['entry_price'] = current_price
                    signal['entry_score'] = entry_score
                    return signal

        # Not enough conviction for short entry
        if entry_score > 0:
            signal['reasons'].append(f"Score {entry_score}/8 - Need 6+ for entry")

        return signal

    def calculate_short_stop_loss_and_targets(self, entry_price: float) -> Dict:
        """
        Calculate stop loss and target prices for SHORT positions.

        IMPORTANT: For shorts:
        - Stop loss is ABOVE entry price (stock going up = loss)
        - Targets are BELOW entry price (stock going down = profit)

        Uses ATR-based stop loss and 1:1.5, 1:2.5 risk-reward targets.

        Args:
            entry_price: Entry price for the short trade

        Returns:
            Dict with stop loss, targets, and risk-reward metrics
        """
        vals = self.get_latest_values()
        atr = vals['atr']

        if pd.isna(atr) or atr == 0:
            # Fallback to 5% stop if ATR not available
            stop_loss = entry_price * 1.05  # 5% ABOVE for shorts
            stop_loss_pct = 5.0
        else:
            # ATR-based stop: 1.5x ATR ABOVE entry (shorts lose when price rises)
            stop_loss = entry_price + (1.5 * atr)
            stop_loss_pct = ((stop_loss - entry_price) / entry_price) * 100

        # Calculate risk amount (positive value)
        risk_per_share = stop_loss - entry_price

        # Targets BELOW entry (shorts profit when price falls)
        # Conservative targets for shorts (1:1.5 and 1:2.5 instead of 1:2 and 1:3)
        target_1 = entry_price - (1.5 * risk_per_share)  # 1:1.5 RR
        target_2 = entry_price - (2.5 * risk_per_share)  # 1:2.5 RR

        # Calculate percentages (negative = profit for shorts)
        target_1_pct = ((target_1 - entry_price) / entry_price) * 100  # Will be negative
        target_2_pct = ((target_2 - entry_price) / entry_price) * 100  # Will be negative

        return {
            'stop_loss': round(stop_loss, 2),
            'stop_loss_pct': round(stop_loss_pct, 2),
            'target_1': round(target_1, 2),
            'target_1_pct': round(target_1_pct, 2),
            'target_2': round(target_2, 2),
            'target_2_pct': round(target_2_pct, 2),
            'risk_reward_1': 1.5,
            'risk_reward_2': 2.5,
            'atr': round(atr, 2) if not pd.isna(atr) else 0
        }

    def calculate_short_position_size(self, account_size: float, risk_pct: float,
                                     entry_price: float, stop_loss: float) -> Dict:
        """
        Calculate position size for SHORT positions.

        For shorts: stop_loss > entry_price (stop is above entry)

        Args:
            account_size: Total account capital in ₹
            risk_pct: Risk percentage per trade (default 2%, max 5% for shorts)
            entry_price: Entry price for the short trade
            stop_loss: Stop loss price (ABOVE entry)

        Returns:
            Dict with position sizing details
        """
        if stop_loss <= entry_price:
            return {
                'position_size': 0,
                'risk_amount': 0,
                'max_position_value': 0,
                'error': 'Stop loss must be above entry price for shorts'
            }

        # Limit risk to max 5% for shorts (stricter than longs)
        if risk_pct > 5.0:
            risk_pct = 5.0

        # Calculate risk amount
        risk_amount = account_size * (risk_pct / 100)

        # Calculate position size
        risk_per_share = stop_loss - entry_price  # Positive value
        position_size = int(risk_amount / risk_per_share)

        # Calculate position value
        position_value = position_size * entry_price

        # Maximum position size (5% of account for shorts - more conservative)
        max_position_value = account_size * 0.05

        if position_value > max_position_value:
            position_size = int(max_position_value / entry_price)
            position_value = position_size * entry_price

        return {
            'position_size': position_size,
            'risk_amount': round(risk_amount, 2),
            'position_value': round(position_value, 2),
            'max_position_value': round(max_position_value, 2),
            'risk_pct_actual': round((position_size * risk_per_share / account_size) * 100, 2)
        }

    def get_short_comprehensive_analysis(self, account_size: float = 1000000,
                                        risk_pct: float = 2.0) -> Dict:
        """
        Get complete SHORT trend analysis with all signals and metrics.

        IMPORTANT: This analyzes for SHORT selling opportunities:
        - Looks for downtrends
        - Stop loss ABOVE entry
        - Targets BELOW entry
        - Conservative position sizing

        Args:
            account_size: Account capital for position sizing (default 10L)
            risk_pct: Risk per trade percentage (default 2%, max 5% for shorts)

        Returns:
            Comprehensive dict with all SHORT analysis
        """
        # Get trend analysis
        trend_analysis = self.identify_trend()

        # Get SHORT entry signal
        entry_signal = self.detect_short_entry_signal(trend_analysis)

        # Get support/resistance
        sr_levels = self.find_support_resistance()

        # Get pivot points
        pivots = self.calculate_pivot_points()

        # Calculate risk metrics if short entry signal exists
        if entry_signal['entry_signal'] == 'SHORT':
            entry_price = entry_signal['entry_price']
            risk_metrics = self.calculate_short_stop_loss_and_targets(entry_price)
            position_size = self.calculate_short_position_size(
                account_size,
                risk_pct,
                entry_price,
                risk_metrics['stop_loss']
            )
        else:
            entry_price = self.get_latest_values()['close']
            risk_metrics = self.calculate_short_stop_loss_and_targets(entry_price)
            position_size = {}

        # Get latest indicator values
        vals = self.get_latest_values()

        return {
            'symbol': self.symbol,
            'current_price': vals['close'],

            # Trend Analysis (bearish focus)
            'trend_status': trend_analysis['trend'],
            'trend_score': trend_analysis['score'],
            'trend_confidence': trend_analysis.get('confidence', 'Low'),
            'pct_from_ema20': trend_analysis.get('pct_from_ema20', 0),
            'pct_from_sma50': trend_analysis.get('pct_from_sma50', 0),
            'pct_from_sma200': trend_analysis.get('pct_from_sma200', 0),
            'adx': trend_analysis.get('adx', 0),
            'adx_signal': trend_analysis.get('adx_signal', 'N/A'),

            # SHORT Entry Signal
            'entry_signal': entry_signal['entry_signal'],
            'entry_type': entry_signal['entry_type'],
            'entry_price': entry_signal['entry_price'],
            'entry_score': entry_signal['entry_score'],
            'entry_reasons': ', '.join(entry_signal['reasons']),

            # Risk Management (SHORT specific - stops ABOVE, targets BELOW)
            'stop_loss': risk_metrics['stop_loss'],
            'stop_loss_pct': risk_metrics['stop_loss_pct'],
            'target_1': risk_metrics['target_1'],
            'target_1_pct': risk_metrics['target_1_pct'],
            'target_2': risk_metrics['target_2'],
            'target_2_pct': risk_metrics['target_2_pct'],
            'risk_reward': f"1:{risk_metrics['risk_reward_1']} / 1:{risk_metrics['risk_reward_2']}",

            # Support/Resistance (inverted importance for shorts)
            'nearest_support': sr_levels['nearest_support'],  # Target zone
            'nearest_resistance': sr_levels['nearest_resistance'],  # Stop zone
            's1_pivot': pivots['s1'],  # Target
            'r1_pivot': pivots['r1'],  # Resistance/Stop

            # Position Sizing (conservative for shorts)
            'position_size': position_size.get('position_size', 0),
            'position_value': position_size.get('position_value', 0),
            'risk_amount': position_size.get('risk_amount', 0),

            # Indicators
            'rsi': vals['rsi'],
            'macd': vals['macd'],
            'volume_vs_avg': round((vals['volume'] / vals['volume_avg']) * 100, 1) if not pd.isna(vals['volume_avg']) else 0
        }

    def get_comprehensive_analysis(self, account_size: float = 1000000,
                                  risk_pct: float = 2.0) -> Dict:
        """
        Get complete trend analysis with all signals and metrics.

        Args:
            account_size: Account capital for position sizing (default 10L)
            risk_pct: Risk per trade percentage (default 2%)

        Returns:
            Comprehensive dict with all analysis
        """
        # Get trend analysis
        trend_analysis = self.identify_trend()

        # Get entry signal
        entry_signal = self.detect_entry_signal(trend_analysis)

        # Get support/resistance
        sr_levels = self.find_support_resistance()

        # Get pivot points
        pivots = self.calculate_pivot_points()

        # Calculate risk metrics if entry signal exists
        if entry_signal['entry_signal'] == 'BUY':
            entry_price = entry_signal['entry_price']
            risk_metrics = self.calculate_stop_loss_and_targets(entry_price)
            position_size = self.calculate_position_size(
                account_size,
                risk_pct,
                entry_price,
                risk_metrics['stop_loss']
            )
        else:
            entry_price = self.get_latest_values()['close']
            risk_metrics = self.calculate_stop_loss_and_targets(entry_price)
            position_size = {}

        # Get latest indicator values
        vals = self.get_latest_values()

        return {
            'symbol': self.symbol,
            'current_price': vals['close'],

            # Trend Analysis
            'trend_status': trend_analysis['trend'],
            'trend_score': trend_analysis['score'],
            'trend_confidence': trend_analysis.get('confidence', 'Low'),
            'pct_from_ema20': trend_analysis.get('pct_from_ema20', 0),
            'pct_from_sma50': trend_analysis.get('pct_from_sma50', 0),
            'pct_from_sma200': trend_analysis.get('pct_from_sma200', 0),
            'adx': trend_analysis.get('adx', 0),
            'adx_signal': trend_analysis.get('adx_signal', 'N/A'),

            # Entry Signal
            'entry_signal': entry_signal['entry_signal'],
            'entry_type': entry_signal['entry_type'],
            'entry_price': entry_signal['entry_price'],
            'entry_score': entry_signal['entry_score'],
            'entry_reasons': ', '.join(entry_signal['reasons']),

            # Risk Management
            'stop_loss': risk_metrics['stop_loss'],
            'stop_loss_pct': risk_metrics['stop_loss_pct'],
            'target_1': risk_metrics['target_1'],
            'target_1_pct': risk_metrics['target_1_pct'],
            'target_2': risk_metrics['target_2'],
            'target_2_pct': risk_metrics['target_2_pct'],
            'risk_reward': f"1:{risk_metrics['risk_reward_1']} / 1:{risk_metrics['risk_reward_2']}",

            # Support/Resistance
            'nearest_support': sr_levels['nearest_support'],
            'nearest_resistance': sr_levels['nearest_resistance'],
            's1_pivot': pivots['s1'],
            'r1_pivot': pivots['r1'],

            # Position Sizing
            'position_size': position_size.get('position_size', 0),
            'position_value': position_size.get('position_value', 0),
            'risk_amount': position_size.get('risk_amount', 0),

            # Indicators
            'rsi': vals['rsi'],
            'macd': vals['macd'],
            'volume_vs_avg': round((vals['volume'] / vals['volume_avg']) * 100, 1) if not pd.isna(vals['volume_avg']) else 0
        }


def main():
    """Test the TrendAnalyzer with sample data"""
    print("="*80)
    print("TREND ANALYZER TEST")
    print("="*80)

    # Create sample data (last 100 days)
    import datetime
    dates = pd.date_range(end=datetime.datetime.now(), periods=100, freq='D')

    # Simulated uptrend stock data
    np.random.seed(42)
    close_prices = 100 + np.cumsum(np.random.randn(100) * 2 + 0.5)  # Upward trend

    sample_df = pd.DataFrame({
        'date': dates,
        'open': close_prices - np.random.rand(100) * 2,
        'high': close_prices + np.random.rand(100) * 3,
        'low': close_prices - np.random.rand(100) * 3,
        'close': close_prices,
        'volume': np.random.randint(1000000, 5000000, 100)
    })

    # Test analyzer
    analyzer = TrendAnalyzer(sample_df, symbol="TEST")
    analysis = analyzer.get_comprehensive_analysis(account_size=1000000, risk_pct=2.0)

    print("\n1. TREND ANALYSIS")
    print("-" * 80)
    print(f"Trend Status: {analysis['trend_status']}")
    print(f"Trend Score: {analysis['trend_score']}/10")
    print(f"Confidence: {analysis['trend_confidence']}")
    print(f"ADX: {analysis['adx']} ({analysis['adx_signal']})")
    print(f"Price vs 20 EMA: {analysis['pct_from_ema20']:.2f}%")
    print(f"Price vs 50 SMA: {analysis['pct_from_sma50']:.2f}%")

    print("\n2. ENTRY SIGNAL")
    print("-" * 80)
    print(f"Signal: {analysis['entry_signal']} ({analysis['entry_type']})")
    print(f"Entry Score: {analysis['entry_score']}/10")
    print(f"Reasons: {analysis['entry_reasons']}")

    if analysis['entry_signal'] == 'BUY':
        print("\n3. RISK MANAGEMENT")
        print("-" * 80)
        print(f"Entry Price: ₹{analysis['entry_price']:.2f}")
        print(f"Stop Loss: ₹{analysis['stop_loss']:.2f} ({analysis['stop_loss_pct']:.2f}%)")
        print(f"Target 1: ₹{analysis['target_1']:.2f} (+{analysis['target_1_pct']:.2f}%)")
        print(f"Target 2: ₹{analysis['target_2']:.2f} (+{analysis['target_2_pct']:.2f}%)")
        print(f"Risk-Reward: {analysis['risk_reward']}")

        print("\n4. POSITION SIZING")
        print("-" * 80)
        print(f"Position Size: {analysis['position_size']} shares")
        print(f"Position Value: ₹{analysis['position_value']:,.0f}")
        print(f"Risk Amount: ₹{analysis['risk_amount']:,.0f} (2% of account)")

    print("\n5. SUPPORT/RESISTANCE")
    print("-" * 80)
    print(f"Nearest Support: ₹{analysis['nearest_support']:.2f}")
    print(f"Nearest Resistance: ₹{analysis['nearest_resistance']:.2f}")
    print(f"Pivot S1: ₹{analysis['s1_pivot']:.2f}")
    print(f"Pivot R1: ₹{analysis['r1_pivot']:.2f}")

    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()
