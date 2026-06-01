#!/Users/sunilkumar/myProjects/ShortIndicator/venv/bin/python3
"""
Bull Flag Pattern Detector

Identifies Stage 3 consolidations (flags) on daily charts.
A bull flag has four stages:
  1. Prior consolidation / base
  2. Strong upswing with volume (the pole)
  3. Orderly pullback on shrinking volume (the flag) ← alert here
  4. Breakout continuation (user enters)

Detection criteria:
- Pole: >= 15% gain, volume-backed, smooth run-up
- Flag: orderly pullback <= 20%, tight bars, volume contracting
- Trend context: EMA(20) > SMA(50) at pole top, ADX >= 15

Author: Sunil Kumar Durganaik
"""

import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta

import config

logger = logging.getLogger(__name__)


class FlagPatternDetector:
    """Stateless detector — call detect(df, symbol) per stock."""

    def detect(self, df: pd.DataFrame, symbol: str) -> Optional[Dict]:
        """
        Detect a bull flag (Stage 3 setup) in daily OHLCV data.

        Args:
            df: Daily OHLCV DataFrame, sorted oldest→newest, with columns:
                date, open, high, low, close, volume
            symbol: Stock symbol (for logging)

        Returns:
            Result dict if a valid flag is found, None otherwise.
        """
        if len(df) < 60:
            logger.debug(f"{symbol}: insufficient data ({len(df)} candles, need 60)")
            return None

        df = df.copy().reset_index(drop=True)

        # Ensure numeric
        for col in ('open', 'high', 'low', 'close', 'volume'):
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=['open', 'high', 'low', 'close', 'volume'], inplace=True)
        df.reset_index(drop=True, inplace=True)

        if len(df) < 60:
            return None

        # Calculate indicators on the full series
        df['ema_20'] = ta.ema(df['close'], length=20)
        df['sma_50'] = ta.sma(df['close'], length=50)
        adx_result = ta.adx(df['high'], df['low'], df['close'], length=14)
        adx_col = None
        if adx_result is not None and not adx_result.empty:
            df = pd.concat([df, adx_result], axis=1)
            adx_col = 'ADX_14'

        # Step 1: find pole
        pole = self._find_pole(df, symbol)
        if pole is None:
            return None

        pole_low_idx, pole_high_idx, pole_low_price, pole_high_price = pole

        # Step 2: validate flag (current consolidation after the pole)
        flag = self._validate_flag(df, pole_high_idx, pole_low_idx, symbol)
        if flag is None:
            return None

        # Step 3: trend context at the pole top
        ema_at_pole = df['ema_20'].iloc[pole_high_idx]
        sma_at_pole = df['sma_50'].iloc[pole_high_idx]
        trend_aligned = (
            not pd.isna(ema_at_pole)
            and not pd.isna(sma_at_pole)
            and ema_at_pole > sma_at_pole
        )

        adx_at_pole = None
        if adx_col:
            raw = df[adx_col].iloc[pole_high_idx]
            adx_at_pole = float(raw) if not pd.isna(raw) else None

        if adx_at_pole is not None and adx_at_pole < 15:
            logger.debug(f"{symbol}: ADX {adx_at_pole:.1f} < 15 at pole top — weak trend")
            return None

        # Step 4: current price must be near (or above) EMA(20)
        current_ema = df['ema_20'].iloc[-1]
        current_close = df['close'].iloc[-1]
        if not pd.isna(current_ema) and current_close < current_ema * 0.97:
            logger.debug(f"{symbol}: price {current_close:.2f} > 3% below EMA(20) {current_ema:.2f}")
            return None

        # Step 5: score
        pole_gain_pct = (pole_high_price - pole_low_price) / pole_low_price * 100
        score = self._calculate_score(
            pole_gain_pct=pole_gain_pct,
            volume_ratio=flag['volume_ratio'],
            pullback_depth=flag['pullback_depth_pct'],
            flag_days=flag['flag_days'],
            trend_aligned=trend_aligned,
            flag_tight=flag['flag_tight'],
        )

        if score < config.FLAG_MIN_SCORE:
            logger.debug(f"{symbol}: score {score:.1f} < {config.FLAG_MIN_SCORE}")
            return None

        current_sma = df['sma_50'].iloc[-1]

        return {
            'symbol': symbol,
            'score': round(score, 1),
            'pole_gain_pct': round(pole_gain_pct, 1),
            'pole_high': round(pole_high_price, 2),
            'pole_low': round(pole_low_price, 2),
            'pole_days': int(pole_high_idx - pole_low_idx),
            'pullback_depth_pct': round(flag['pullback_depth_pct'], 1),
            'flag_days': flag['flag_days'],
            'volume_ratio': round(flag['volume_ratio'], 2),
            'breakout_level': round(flag['breakout_level'], 2),
            'stop_loss': round(flag['stop_loss'], 2),
            'current_price': round(current_close, 2),
            'ema_20': round(float(current_ema), 2) if not pd.isna(current_ema) else None,
            'sma_50': round(float(current_sma), 2) if not pd.isna(current_sma) else None,
            'trend_aligned': trend_aligned,
            'adx': round(adx_at_pole, 1) if adx_at_pole else None,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_pole(
        self, df: pd.DataFrame, symbol: str
    ) -> Optional[Tuple[int, int, float, float]]:
        """
        Find the most recent strong upswing (pole) in the last POLE_SEARCH_DAYS candles.

        Returns:
            (pole_low_idx, pole_high_idx, pole_low_price, pole_high_price)
            or None if no valid pole found.
        """
        n = len(df)
        # The pole high must not be too recent — we need at least FLAG_MIN_FLAG_DAYS after it.
        # And we search within FLAG_POLE_SEARCH_DAYS from today.
        search_start = max(0, n - config.FLAG_POLE_SEARCH_DAYS - 1)
        search_end = n - config.FLAG_MIN_FLAG_DAYS  # exclusive

        if search_end <= search_start + 5:
            return None

        search_closes = df['close'].values[search_start:search_end]
        pole_high_rel = int(np.argmax(search_closes))
        pole_high_idx = search_start + pole_high_rel
        pole_high_price = float(df['close'].iloc[pole_high_idx])

        # Pole low: minimum close in up to 30 trading days before the pole high
        low_search_start = max(0, pole_high_idx - 30)
        low_search_end = pole_high_idx  # exclusive
        if low_search_end <= low_search_start + 2:
            return None

        low_closes = df['close'].values[low_search_start:low_search_end]
        pole_low_rel = int(np.argmin(low_closes))
        pole_low_idx = low_search_start + pole_low_rel
        pole_low_price = float(df['close'].iloc[pole_low_idx])

        # Pole gain check
        if pole_low_price <= 0:
            return None
        pole_gain_pct = (pole_high_price - pole_low_price) / pole_low_price * 100
        if pole_gain_pct < config.FLAG_MIN_POLE_PCT:
            logger.debug(f"{symbol}: pole gain {pole_gain_pct:.1f}% < {config.FLAG_MIN_POLE_PCT}%")
            return None

        # Pole must span at least 3 days
        if pole_high_idx - pole_low_idx < 3:
            return None

        # Pole volume check: avg volume during pole >= overall avg
        pole_df = df.iloc[pole_low_idx:pole_high_idx + 1]
        overall_avg_vol = df['volume'].mean()
        pole_avg_vol = pole_df['volume'].mean()
        if pole_avg_vol < overall_avg_vol * 0.9:
            logger.debug(f"{symbol}: pole volume {pole_avg_vol:.0f} below overall avg {overall_avg_vol:.0f}")
            return None

        logger.debug(
            f"{symbol}: pole found idx={pole_low_idx}→{pole_high_idx}, "
            f"gain={pole_gain_pct:.1f}%, days={pole_high_idx - pole_low_idx}"
        )
        return pole_low_idx, pole_high_idx, pole_low_price, pole_high_price

    def _validate_flag(
        self,
        df: pd.DataFrame,
        pole_high_idx: int,
        pole_low_idx: int,
        symbol: str,
    ) -> Optional[Dict]:
        """
        Validate the flag (consolidation) period after the pole top.

        Returns a dict of flag metrics, or None if invalid.
        """
        n = len(df)
        flag_start = pole_high_idx + 1
        flag_days = n - flag_start  # number of candles in the flag

        if flag_days < config.FLAG_MIN_FLAG_DAYS or flag_days > config.FLAG_MAX_FLAG_DAYS:
            logger.debug(
                f"{symbol}: flag_days={flag_days} outside [{config.FLAG_MIN_FLAG_DAYS}, {config.FLAG_MAX_FLAG_DAYS}]"
            )
            return None

        pole_high_price = float(df['close'].iloc[pole_high_idx])
        current_close = float(df['close'].iloc[-1])

        pullback_depth = (pole_high_price - current_close) / pole_high_price * 100
        if pullback_depth < 2.0 or pullback_depth > config.FLAG_MAX_PULLBACK_PCT:
            logger.debug(f"{symbol}: pullback {pullback_depth:.1f}% out of range [2, {config.FLAG_MAX_PULLBACK_PCT}]")
            return None

        flag_df = df.iloc[flag_start:]
        pole_df = df.iloc[pole_low_idx:pole_high_idx + 1]

        # Volume contraction: flag avg < pole avg
        pole_avg_vol = pole_df['volume'].mean()
        flag_avg_vol = flag_df['volume'].mean()
        if flag_avg_vol <= 0 or flag_avg_vol >= pole_avg_vol:
            logger.debug(f"{symbol}: volume not contracting — flag {flag_avg_vol:.0f} >= pole {pole_avg_vol:.0f}")
            return None
        volume_ratio = pole_avg_vol / flag_avg_vol

        # No wide bars: largest single-day range in flag < 40% of pole price range
        pole_price_range = pole_high_price - float(df['close'].iloc[pole_low_idx])
        flag_ranges = flag_df['high'].values - flag_df['low'].values
        max_flag_range = float(flag_ranges.max())
        if pole_price_range > 0 and max_flag_range / pole_price_range > 0.40:
            logger.debug(f"{symbol}: wide bar in flag — max range {max_flag_range:.2f} / pole range {pole_price_range:.2f}")
            return None

        # Flag tightness: avg candle range in flag < avg candle range in pole
        pole_ranges = pole_df['high'].values - pole_df['low'].values
        pole_avg_range = float(pole_ranges.mean())
        flag_avg_range = float(flag_ranges.mean())
        flag_tight = flag_avg_range < pole_avg_range

        # Breakout level: highest high during the flag
        breakout_level = float(flag_df['high'].max())

        # Stop loss: 3% below the lowest low of the flag
        flag_low = float(flag_df['low'].min())
        stop_loss = flag_low * 0.97

        return {
            'flag_days': int(flag_days),
            'pullback_depth_pct': pullback_depth,
            'volume_ratio': volume_ratio,
            'flag_tight': flag_tight,
            'breakout_level': breakout_level,
            'stop_loss': stop_loss,
        }

    def _calculate_score(
        self,
        pole_gain_pct: float,
        volume_ratio: float,
        pullback_depth: float,
        flag_days: int,
        trend_aligned: bool,
        flag_tight: bool,
    ) -> float:
        score = 0.0

        # Pole strength (max 3)
        if pole_gain_pct >= 40:
            score += 3
        elif pole_gain_pct >= 25:
            score += 2
        else:
            score += 1

        # Volume contraction ratio (max 2)
        if volume_ratio >= 2.0:
            score += 2
        elif volume_ratio >= 1.5:
            score += 1

        # Pullback depth (max 2) — 5–15% is the sweet spot
        if 5.0 <= pullback_depth <= 15.0:
            score += 2
        elif pullback_depth <= 20.0:
            score += 1

        # Trend alignment: EMA(20) > SMA(50) at pole top (max 1)
        if trend_aligned:
            score += 1

        # Flag candle tightness (max 1)
        if flag_tight:
            score += 1

        # Ideal flag duration: 5–10 days (max 1)
        if 5 <= flag_days <= 10:
            score += 1

        return score
