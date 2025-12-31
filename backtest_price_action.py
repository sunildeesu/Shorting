#!/usr/bin/env python3
"""
Price Action Pattern Backtesting Script

Tests all 19 candlestick patterns on historical 5-minute data to validate:
- Win rates by pattern
- Average R:R achieved
- Confidence score accuracy
- Best performing patterns
- Market regime impact

Usage:
    ./backtest_price_action.py --days 30 --stocks 20 --min-confidence 7.0
"""

import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
import pandas as pd
from kiteconnect import KiteConnect

import config
from price_action_detector import PriceActionDetector
from unified_data_cache import UnifiedDataCache

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/price_action_backtest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PriceActionBacktester:
    """Backtest price action patterns on historical 5-minute data"""

    # Nifty 50 instrument token
    NIFTY_50_TOKEN = 256265

    def __init__(
        self,
        lookback_days: int = 30,
        min_confidence: float = 7.0,
        max_stocks: Optional[int] = None
    ):
        """
        Initialize backtester

        Args:
            lookback_days: Number of days to backtest
            min_confidence: Minimum confidence score to test
            max_stocks: Limit number of stocks (for faster testing)
        """
        self.lookback_days = lookback_days
        self.min_confidence = min_confidence
        self.max_stocks = max_stocks

        # Initialize Kite
        logger.info("Initializing Kite Connect...")
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Initialize detector
        self.detector = PriceActionDetector(min_confidence=min_confidence)

        # Initialize cache
        self.data_cache = UnifiedDataCache(cache_dir=config.HISTORICAL_CACHE_DIR)

        # Load stocks
        self.stocks = self._load_stocks()

        # Results storage
        self.results = []
        self.pattern_stats = defaultdict(lambda: {
            'total': 0,
            'wins': 0,
            'losses': 0,
            'target_hits': 0,
            'stop_hits': 0,
            'total_rr_achieved': 0.0,
            'total_pnl_pct': 0.0,
            'by_confidence': defaultdict(lambda: {'total': 0, 'wins': 0}),
            'by_regime': defaultdict(lambda: {'total': 0, 'wins': 0})
        })

        # Instrument token cache
        self.instrument_tokens = {}

    def _load_stocks(self) -> List[str]:
        """Load F&O stocks for backtesting"""
        try:
            with open(config.STOCK_LIST_FILE, 'r') as f:
                all_stocks = json.load(f)['stocks']
        except Exception as e:
            logger.error(f"Failed to load stock list: {e}")
            return []

        if self.max_stocks:
            stocks = all_stocks[:self.max_stocks]
            logger.info(f"Limited to {len(stocks)} stocks for faster testing")
        else:
            stocks = all_stocks

        return stocks

    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for a symbol"""
        if symbol in self.instrument_tokens:
            return self.instrument_tokens[symbol]

        try:
            if not hasattr(self, 'instruments_cache'):
                logger.info("Fetching instruments list...")
                self.instruments_cache = self.kite.instruments("NSE")

            for instrument in self.instruments_cache:
                if instrument['tradingsymbol'] == symbol:
                    token = instrument['instrument_token']
                    self.instrument_tokens[symbol] = token
                    return token

            return None

        except Exception as e:
            logger.error(f"{symbol}: Error fetching instrument token: {e}")
            return None

    def run_backtest(self):
        """Run complete backtest"""
        logger.info("=" * 80)
        logger.info(f"PRICE ACTION BACKTEST - Starting")
        logger.info(f"  Period: Last {self.lookback_days} days")
        logger.info(f"  Stocks: {len(self.stocks)}")
        logger.info(f"  Min Confidence: {self.min_confidence}")
        logger.info("=" * 80)

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.lookback_days)

        # Get Nifty regime data first
        logger.info("Fetching Nifty 50 data for regime detection...")
        nifty_regime_data = self._fetch_nifty_regime_data(start_date, end_date)

        # Process each stock
        total_patterns = 0
        for idx, symbol in enumerate(self.stocks, 1):
            logger.info(f"[{idx}/{len(self.stocks)}] Processing {symbol}...")

            try:
                # Fetch 5-min data
                candles = self._fetch_5min_data(symbol, start_date, end_date)
                if not candles or len(candles) < 100:
                    logger.warning(f"{symbol}: Insufficient data ({len(candles) if candles else 0} candles)")
                    continue

                # Process each day's data
                patterns_found = self._backtest_stock(symbol, candles, nifty_regime_data)
                total_patterns += patterns_found

                logger.info(f"{symbol}: Found {patterns_found} patterns")

            except Exception as e:
                logger.error(f"{symbol}: Error - {e}", exc_info=True)
                continue

        logger.info("=" * 80)
        logger.info(f"Backtest complete! Total patterns tested: {total_patterns}")
        logger.info("=" * 80)

        # Generate report
        self._generate_report()

    def _fetch_nifty_regime_data(self, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Fetch Nifty 50 daily data for regime calculation"""
        try:
            # Fetch extra days for SMA calculation
            extended_start = start_date - timedelta(days=70)

            nifty_data = self.kite.historical_data(
                instrument_token=self.NIFTY_50_TOKEN,
                from_date=extended_start,
                to_date=end_date,
                interval="day"
            )

            df = pd.DataFrame(nifty_data)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)

            # Calculate 50-day SMA
            df['sma_50'] = df['close'].rolling(window=50).mean()

            # Determine regime
            df['regime'] = 'NEUTRAL'
            df.loc[df['close'] > df['sma_50'] * 1.005, 'regime'] = 'BULLISH'
            df.loc[df['close'] < df['sma_50'] * 0.995, 'regime'] = 'BEARISH'

            return df

        except Exception as e:
            logger.error(f"Failed to fetch Nifty data: {e}")
            return pd.DataFrame()

    def _fetch_5min_data(self, symbol: str, start_date: datetime, end_date: datetime) -> List[Dict]:
        """Fetch 5-minute candles for a stock"""
        try:
            instrument_token = self._get_instrument_token(symbol)
            if not instrument_token:
                return []

            # Fetch from Kite (5-min data limited to 60 days)
            candles = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=start_date,
                to_date=end_date,
                interval="5minute"
            )

            return candles

        except Exception as e:
            logger.debug(f"{symbol}: Failed to fetch 5-min data - {e}")
            return []

    def _backtest_stock(
        self,
        symbol: str,
        candles: List[Dict],
        nifty_regime_data: pd.DataFrame
    ) -> int:
        """
        Backtest a single stock

        Strategy:
        - Scan each 5-min candle for patterns
        - When pattern detected, check next candles for target/stop hit
        - Track win/loss, R:R achieved
        """
        patterns_found = 0

        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(candles)
        df['date'] = pd.to_datetime(df['date'])

        # Group by trading day
        df['trading_day'] = df['date'].dt.date

        for trading_day, day_data in df.groupby('trading_day'):
            # Get market regime for this day
            regime = self._get_regime_for_date(nifty_regime_data, trading_day)

            # Convert back to list of dicts for detector
            day_candles = day_data.to_dict('records')

            if len(day_candles) < 50:
                continue

            # Calculate average volume
            volumes = [c['volume'] for c in day_candles[-20:]]
            avg_volume = sum(volumes) / len(volumes) if volumes else 0

            # Scan each candle (leave room for lookback and forward testing)
            for i in range(50, len(day_candles) - 20):  # Leave 20 candles for exit
                candles_up_to_i = day_candles[:i+1]
                current_price = day_candles[i]['close']

                # Detect patterns
                result = self.detector.detect_patterns(
                    symbol=symbol,
                    candles=candles_up_to_i,
                    market_regime=regime,
                    current_price=current_price,
                    avg_volume=avg_volume
                )

                if not result['has_patterns']:
                    continue

                # Test each detected pattern
                for pattern_name in result['patterns_found']:
                    pattern_key = pattern_name.lower().replace(' ', '_')
                    pattern_details = result['pattern_details'][pattern_key]

                    # Simulate trade
                    trade_result = self._simulate_trade(
                        day_candles[i+1:],  # Future candles
                        pattern_details
                    )

                    if trade_result:
                        # Record result
                        self._record_trade(
                            symbol=symbol,
                            trading_day=trading_day,
                            pattern_name=pattern_name,
                            pattern_details=pattern_details,
                            trade_result=trade_result,
                            regime=regime
                        )
                        patterns_found += 1

        return patterns_found

    def _get_regime_for_date(self, nifty_df: pd.DataFrame, trading_day) -> str:
        """Get market regime for a specific date"""
        if nifty_df.empty:
            return 'NEUTRAL'

        try:
            # Find closest date
            target_date = pd.Timestamp(trading_day)
            if target_date in nifty_df.index:
                return nifty_df.loc[target_date, 'regime']
            else:
                # Get nearest previous date
                earlier_dates = nifty_df.index[nifty_df.index <= target_date]
                if len(earlier_dates) > 0:
                    return nifty_df.loc[earlier_dates[-1], 'regime']
                return 'NEUTRAL'
        except:
            return 'NEUTRAL'

    def _simulate_trade(
        self,
        future_candles: List[Dict],
        pattern_details: Dict
    ) -> Optional[Dict]:
        """
        Simulate trade execution

        Returns:
            Dict with trade result or None if no entry
        """
        entry_price = pattern_details['entry_price']
        target = pattern_details.get('target')
        stop_loss = pattern_details.get('stop_loss')
        pattern_type = pattern_details['type']

        if not target or not stop_loss:
            return None  # Can't test patterns without clear targets

        # Check if entry was triggered and track outcome
        entry_triggered = False
        exit_reason = None
        exit_price = None
        candles_held = 0

        for candle in future_candles:
            candles_held += 1

            # Check if entry triggered (within first 2 candles)
            if not entry_triggered and candles_held <= 2:
                if pattern_type in ['bullish', 'neutral']:
                    if candle['high'] >= entry_price:
                        entry_triggered = True
                elif pattern_type == 'bearish':
                    if candle['low'] <= entry_price:
                        entry_triggered = True

            if not entry_triggered:
                continue

            # Check for target/stop hit
            if pattern_type in ['bullish', 'neutral']:
                # Check stop first (conservative)
                if candle['low'] <= stop_loss:
                    exit_reason = 'STOP_HIT'
                    exit_price = stop_loss
                    break
                # Check target
                elif candle['high'] >= target:
                    exit_reason = 'TARGET_HIT'
                    exit_price = target
                    break

            elif pattern_type == 'bearish':
                # Check stop first
                if candle['high'] >= stop_loss:
                    exit_reason = 'STOP_HIT'
                    exit_price = stop_loss
                    break
                # Check target
                elif candle['low'] <= target:
                    exit_reason = 'TARGET_HIT'
                    exit_price = target
                    break

            # Exit after 20 candles (100 minutes) if no target/stop
            if candles_held >= 20:
                exit_reason = 'TIME_EXIT'
                exit_price = candle['close']
                break

        if not entry_triggered:
            return None

        if not exit_reason:
            # No exit in available candles
            exit_reason = 'NO_EXIT'
            exit_price = future_candles[-1]['close']

        # Calculate P&L
        if pattern_type in ['bullish', 'neutral']:
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100

        # Calculate R:R achieved
        risk = abs(entry_price - stop_loss)
        reward_achieved = abs(exit_price - entry_price)
        rr_achieved = reward_achieved / risk if risk > 0 else 0

        return {
            'entry_price': entry_price,
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl_pct': pnl_pct,
            'rr_achieved': rr_achieved,
            'candles_held': candles_held,
            'win': pnl_pct > 0
        }

    def _record_trade(
        self,
        symbol: str,
        trading_day,
        pattern_name: str,
        pattern_details: Dict,
        trade_result: Dict,
        regime: str
    ):
        """Record trade result"""
        # Store individual trade
        self.results.append({
            'symbol': symbol,
            'date': trading_day,
            'pattern': pattern_name,
            'type': pattern_details['type'],
            'confidence': pattern_details['confidence_score'],
            'regime': regime,
            'entry': trade_result['entry_price'],
            'exit': trade_result['exit_price'],
            'exit_reason': trade_result['exit_reason'],
            'pnl_pct': trade_result['pnl_pct'],
            'rr_achieved': trade_result['rr_achieved'],
            'candles_held': trade_result['candles_held'],
            'win': trade_result['win']
        })

        # Update pattern statistics
        stats = self.pattern_stats[pattern_name]
        stats['total'] += 1

        if trade_result['win']:
            stats['wins'] += 1
        else:
            stats['losses'] += 1

        if trade_result['exit_reason'] == 'TARGET_HIT':
            stats['target_hits'] += 1
        elif trade_result['exit_reason'] == 'STOP_HIT':
            stats['stop_hits'] += 1

        stats['total_rr_achieved'] += trade_result['rr_achieved']
        stats['total_pnl_pct'] += trade_result['pnl_pct']

        # Track by confidence bucket
        conf_bucket = f"{int(pattern_details['confidence_score'])}"
        stats['by_confidence'][conf_bucket]['total'] += 1
        if trade_result['win']:
            stats['by_confidence'][conf_bucket]['wins'] += 1

        # Track by regime
        stats['by_regime'][regime]['total'] += 1
        if trade_result['win']:
            stats['by_regime'][regime]['wins'] += 1

    def _generate_report(self):
        """Generate Excel report with backtest results"""
        if not self.results:
            logger.warning("No results to report!")
            return

        # Create output directory
        import os
        output_dir = "data/backtests"
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"{output_dir}/price_action_backtest_{timestamp}.xlsx"

        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            # Sheet 1: All trades
            df_trades = pd.DataFrame(self.results)
            df_trades.to_excel(writer, sheet_name='All_Trades', index=False)

            # Sheet 2: Pattern summary
            summary_data = []
            for pattern_name, stats in sorted(self.pattern_stats.items()):
                if stats['total'] == 0:
                    continue

                win_rate = (stats['wins'] / stats['total']) * 100
                avg_rr = stats['total_rr_achieved'] / stats['total']
                avg_pnl = stats['total_pnl_pct'] / stats['total']
                target_hit_rate = (stats['target_hits'] / stats['total']) * 100
                stop_hit_rate = (stats['stop_hits'] / stats['total']) * 100

                summary_data.append({
                    'Pattern': pattern_name,
                    'Total Trades': stats['total'],
                    'Wins': stats['wins'],
                    'Losses': stats['losses'],
                    'Win Rate %': round(win_rate, 1),
                    'Avg R:R': round(avg_rr, 2),
                    'Avg P&L %': round(avg_pnl, 2),
                    'Target Hit %': round(target_hit_rate, 1),
                    'Stop Hit %': round(stop_hit_rate, 1)
                })

            df_summary = pd.DataFrame(summary_data)
            df_summary = df_summary.sort_values('Win Rate %', ascending=False)
            df_summary.to_excel(writer, sheet_name='Pattern_Summary', index=False)

            # Sheet 3: By confidence
            conf_data = []
            for pattern_name, stats in self.pattern_stats.items():
                for conf, conf_stats in stats['by_confidence'].items():
                    if conf_stats['total'] > 0:
                        conf_data.append({
                            'Pattern': pattern_name,
                            'Confidence': conf,
                            'Total': conf_stats['total'],
                            'Wins': conf_stats['wins'],
                            'Win Rate %': round((conf_stats['wins'] / conf_stats['total']) * 100, 1)
                        })

            if conf_data:
                df_conf = pd.DataFrame(conf_data)
                df_conf = df_conf.sort_values(['Pattern', 'Confidence'])
                df_conf.to_excel(writer, sheet_name='By_Confidence', index=False)

            # Sheet 4: By regime
            regime_data = []
            for pattern_name, stats in self.pattern_stats.items():
                for regime, regime_stats in stats['by_regime'].items():
                    if regime_stats['total'] > 0:
                        regime_data.append({
                            'Pattern': pattern_name,
                            'Regime': regime,
                            'Total': regime_stats['total'],
                            'Wins': regime_stats['wins'],
                            'Win Rate %': round((regime_stats['wins'] / regime_stats['total']) * 100, 1)
                        })

            if regime_data:
                df_regime = pd.DataFrame(regime_data)
                df_regime = df_regime.sort_values(['Pattern', 'Regime'])
                df_regime.to_excel(writer, sheet_name='By_Regime', index=False)

        logger.info(f"Report generated: {output_file}")

        # Print summary to console
        print("\n" + "=" * 80)
        print("BACKTEST SUMMARY")
        print("=" * 80)
        print(f"Total Patterns Tested: {len(self.results)}")
        print(f"Overall Win Rate: {(sum(1 for r in self.results if r['win']) / len(self.results) * 100):.1f}%")
        print("\nTop 5 Patterns by Win Rate:")
        print(df_summary.head(5).to_string(index=False))
        print("\n" + "=" * 80)
        print(f"Full report: {output_file}")
        print("=" * 80 + "\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Backtest Price Action Patterns')
    parser.add_argument('--days', type=int, default=30, help='Lookback days (default: 30, max: 60 for 5-min data)')
    parser.add_argument('--stocks', type=int, help='Limit number of stocks (for faster testing)')
    parser.add_argument('--min-confidence', type=float, default=7.0, help='Minimum confidence score (default: 7.0)')

    args = parser.parse_args()

    try:
        backtester = PriceActionBacktester(
            lookback_days=args.days,
            min_confidence=args.min_confidence,
            max_stocks=args.stocks
        )
        backtester.run_backtest()

    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
