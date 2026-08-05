#!/usr/bin/env python3
"""
Auto-Trader - Automated Trading on 5-Min Alerts via Zerodha Kite

Executes trades automatically when 5-min alerts are triggered.

NO DEMONSTRATED EDGE. This module used to claim "97% win rate and +1.67% avg P&L".
That claim had no source: it arrived with this file's first commit (0bd742e, 2026-02-11),
no script in the repo produces it and no result file records it. It is withdrawn.

Measured instead from data/alerts/alert_pnl_tracker.xlsx (411 alerts, 69 trading days,
2026-02-25 to 2026-08-04) by replaying this module's own rule - first 5min /
volume_spike / 5min_rise / volume_spike_rise alert per stock per day, per
rapid_drop_detector._try_auto_trade(); `prealert` is not auto-traded:

    176 trades over 58 trading days, 163 with a completed exit
        exit at alert+15m:  46.6% win rate, +0.030% avg per trade (95% CI -0.171/+0.232)
        exit at alert+30m:  43.0% win rate, -0.162% avg per trade

That average is statistically indistinguishable from zero and is gross of costs; an
intraday equity round trip costs more than it. Caveats (different exit window, futures
lot sizing vs cash equity, F&O-only coverage, no costs modelled) are printed in full by
`venv/bin/python analyze_auto_trade_record.py`, which re-derives these numbers.

ENABLE_AUTO_TRADING is off by default and should stay off until a real record - see
data/auto_trade_history.jsonl below - says otherwise.

Key Features:
- First-alert-only per stock per day
- Fixed position size (default ₹10,000)
- Auto-exit after 10 minutes
- Paper mode for testing
- Completed trades appended to data/auto_trade_history.jsonl (never rewritten), so the
  record survives the nightly reset of the open-position file

Author: Claude Opus 4.5
Date: 2026-02-11
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from kiteconnect import KiteConnect
from kiteconnect.exceptions import (
    TokenException, NetworkException, GeneralException,
    DataException, InputException, OrderException
)

import config

logger = logging.getLogger(__name__)


class AutoTrader:
    """
    Automated trading system for 5-minute alerts.

    Manages position entry, tracking, and scheduled exits.
    """

    def __init__(self, kite_client: KiteConnect):
        """
        Initialize AutoTrader with Kite client.

        Args:
            kite_client: Initialized KiteConnect instance
        """
        self.kite = kite_client
        self.positions: Dict[str, Dict] = {}  # {symbol: position_info}
        self.daily_trades: set = set()  # Symbols traded today
        self.today_date: str = datetime.now().strftime('%Y-%m-%d')

        # Load persisted positions on startup
        self._load_positions()

        # Configuration
        self.enabled = config.ENABLE_AUTO_TRADING
        self.paper_mode = config.AUTO_TRADE_PAPER_MODE
        self.position_size = config.AUTO_TRADE_POSITION_SIZE
        self.max_positions = config.AUTO_TRADE_MAX_POSITIONS
        self.exit_minutes = config.AUTO_TRADE_EXIT_MINUTES
        self.allowed_directions = config.AUTO_TRADE_DIRECTIONS
        self.product = config.AUTO_TRADE_PRODUCT
        self.paper_slippage = config.AUTO_TRADE_PAPER_SLIPPAGE

        mode_str = "PAPER" if self.paper_mode else "LIVE"
        logger.info(f"AutoTrader initialized ({mode_str} mode)")
        logger.info(f"  Position size: ₹{self.position_size:,.0f}")
        logger.info(f"  Max positions: {self.max_positions}")
        logger.info(f"  Exit after: {self.exit_minutes} minutes")
        logger.info(f"  Directions: {self.allowed_directions}")
        logger.info(f"  Product: {self.product}")
        if self.paper_mode:
            logger.info(f"  Paper slippage: {self.paper_slippage * 100:.1f}%")
        logger.info(f"  Open positions: {len(self.positions)}")

    def _load_positions(self):
        """Load persisted positions from file."""
        try:
            if os.path.exists(config.AUTO_TRADE_POSITIONS_FILE):
                with open(config.AUTO_TRADE_POSITIONS_FILE, 'r') as f:
                    data = json.load(f)

                # Check if same trading day
                if data.get('date') == self.today_date:
                    self.positions = data.get('positions', {})
                    self.daily_trades = set(data.get('daily_trades', []))

                    # Convert exit_at strings back to datetime
                    for symbol, pos in self.positions.items():
                        if 'exit_at' in pos and isinstance(pos['exit_at'], str):
                            pos['exit_at'] = datetime.fromisoformat(pos['exit_at'])
                        if 'entry_time' in pos and isinstance(pos['entry_time'], str):
                            pos['entry_time'] = datetime.fromisoformat(pos['entry_time'])

                    logger.info(f"Loaded {len(self.positions)} open positions from file")
                else:
                    # New trading day - reset
                    logger.info("New trading day - resetting positions")
                    self.positions = {}
                    self.daily_trades = set()
        except Exception as e:
            logger.error(f"Failed to load positions: {e}")
            self.positions = {}
            self.daily_trades = set()

    def _save_positions(self):
        """Persist positions to file."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(config.AUTO_TRADE_POSITIONS_FILE), exist_ok=True)

            # Convert datetime objects to strings for JSON
            positions_serializable = {}
            for symbol, pos in self.positions.items():
                pos_copy = pos.copy()
                if 'exit_at' in pos_copy and isinstance(pos_copy['exit_at'], datetime):
                    pos_copy['exit_at'] = pos_copy['exit_at'].isoformat()
                if 'entry_time' in pos_copy and isinstance(pos_copy['entry_time'], datetime):
                    pos_copy['entry_time'] = pos_copy['entry_time'].isoformat()
                positions_serializable[symbol] = pos_copy

            data = {
                'date': self.today_date,
                'positions': positions_serializable,
                'daily_trades': list(self.daily_trades)
            }

            with open(config.AUTO_TRADE_POSITIONS_FILE, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save positions: {e}")

    def _history_file(self) -> str:
        """
        Path of the append-only completed-trade log, a sibling of the positions file.

        Derived rather than configured on purpose: config.py's non-comment content is
        deliberately unchanged by this record-keeping addition.
        """
        return os.path.join(
            os.path.dirname(config.AUTO_TRADE_POSITIONS_FILE) or '.',
            'auto_trade_history.jsonl'
        )

    def _append_history(self, symbol: str, pos: Dict, exit_info: Dict, exit_time: datetime):
        """
        Append one completed trade to the history log. Record-keeping only.

        AUTO_TRADE_POSITIONS_FILE holds the CURRENT day and is reset every morning by
        _load_positions(), so before this existed every closed trade was erased overnight
        and no track record could ever accumulate. This log is JSON Lines, opened in
        append mode and never rewritten, so a crash or a concurrent writer can lose at
        most the line being written - never the history.

        Growth: one line is ~350 bytes and at most AUTO_TRADE_MAX_POSITIONS trades can be
        open at once; the measured alert rate is ~3 auto-tradeable alerts per trading day,
        so ~1 KB/day, i.e. well under 0.5 MB/year. No rotation needed.

        Never raises: a logging failure must not disturb the exit path.
        """
        try:
            entry_time = pos.get('entry_time')
            record = {
                'date': exit_time.strftime('%Y-%m-%d'),
                'symbol': symbol,
                'direction': pos.get('direction'),
                'transaction_type': pos.get('transaction_type'),
                'quantity': pos.get('quantity'),
                'entry_time': entry_time.isoformat() if isinstance(entry_time, datetime) else entry_time,
                'entry_price': pos.get('entry_price'),
                'exit_time': exit_time.isoformat(),
                'exit_price': exit_info.get('exit_price'),
                'hold_minutes': exit_info.get('hold_time'),
                'pnl': exit_info.get('pnl'),
                'pnl_pct': exit_info.get('pnl_pct'),
                'paper_mode': exit_info.get('paper_mode'),
                'order_id': pos.get('order_id'),
                'exit_order_id': exit_info.get('exit_order_id'),
            }

            path = self._history_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'a') as f:
                f.write(json.dumps(record) + '\n')

        except Exception as e:
            logger.error(f"Failed to append trade history for {symbol}: {e}")

    def should_trade(self, symbol: str, direction: str) -> tuple:
        """
        Check if we should take this trade.

        Args:
            symbol: Stock symbol (e.g., 'RELIANCE')
            direction: 'DROP' or 'RISE'

        Returns:
            Tuple of (should_trade: bool, reason: str)
        """
        if not self.enabled:
            return False, "Auto-trading disabled"

        # First alert of day for this stock?
        if symbol in self.daily_trades:
            return False, f"Already traded {symbol} today"

        # Not already in position?
        if symbol in self.positions:
            return False, f"Already in position for {symbol}"

        # Under max positions limit?
        if len(self.positions) >= self.max_positions:
            return False, f"Max positions ({self.max_positions}) reached"

        # Direction allowed?
        if self.allowed_directions != 'BOTH' and direction != self.allowed_directions:
            return False, f"Direction {direction} not allowed (config: {self.allowed_directions})"

        return True, "Trade allowed"

    def execute_trade(self, symbol: str, direction: str, current_price: float) -> Optional[Dict]:
        """
        Execute auto-trade via Kite API.

        Args:
            symbol: Stock symbol (e.g., 'RELIANCE')
            direction: 'DROP' (short) or 'RISE' (long)
            current_price: Current price of the stock

        Returns:
            Trade info dict if successful, None if failed
        """
        # Calculate quantity (round down to ensure we don't exceed position size)
        qty = max(1, int(self.position_size / current_price))

        # Determine transaction type
        if direction == 'DROP':
            transaction_type = 'SELL'  # Short
        else:
            transaction_type = 'BUY'   # Long

        order_id = None

        if self.paper_mode:
            # Paper trading - simulate slippage for realistic P&L
            # Both DROP (short) and RISE (long) get worse entry price (higher)
            # Short: higher entry = worse (buy back at same price = loss)
            # Long: higher entry = worse (sell at same price = loss)
            alert_price = current_price
            simulated_price = current_price * (1 + self.paper_slippage)

            order_id = f"PAPER_{datetime.now().strftime('%H%M%S')}_{symbol}"
            logger.info(f"📝 PAPER TRADE: {transaction_type} {symbol} x{qty} @ ₹{simulated_price:.2f} (alert: ₹{alert_price:.2f}, slippage: {self.paper_slippage * 100:.1f}%)")

            # Use simulated price for position tracking
            current_price = simulated_price
        else:
            # Live trading - place actual order
            try:
                order_id = self.kite.place_order(
                    variety='regular',
                    exchange='NSE',
                    tradingsymbol=symbol,
                    transaction_type=transaction_type,
                    quantity=qty,
                    product=self.product,
                    order_type='MARKET'
                )
                logger.info(f"🤖 LIVE TRADE: {transaction_type} {symbol} x{qty} @ ₹{current_price:.2f} (order: {order_id})")

            except OrderException as e:
                logger.error(f"Order rejected for {symbol}: {e}")
                return None
            except (TokenException, NetworkException) as e:
                logger.error(f"API error placing order for {symbol}: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error placing order for {symbol}: {e}")
                return None

        # Track position
        now = datetime.now()
        exit_at = now + timedelta(minutes=self.exit_minutes)

        position_info = {
            'order_id': order_id,
            'entry_time': now,
            'entry_price': current_price,
            'quantity': qty,
            'direction': direction,
            'transaction_type': transaction_type,
            'exit_at': exit_at,
            'paper_mode': self.paper_mode
        }

        self.positions[symbol] = position_info
        self.daily_trades.add(symbol)

        # Persist positions
        self._save_positions()

        trade_result = {
            'order_id': order_id,
            'symbol': symbol,
            'quantity': qty,
            'direction': direction,
            'transaction_type': transaction_type,
            'entry_price': current_price,
            'exit_at': exit_at,
            'paper_mode': self.paper_mode
        }

        return trade_result

    def check_exits(self, current_quotes: Optional[Dict[str, Dict]] = None) -> List[Dict]:
        """
        Check and execute pending exits.

        Args:
            current_quotes: Optional dict of {symbol: {price: float, ...}} for P&L calculation

        Returns:
            List of exit info dicts
        """
        exits = []
        now = datetime.now()

        for symbol, pos in list(self.positions.items()):
            if now >= pos['exit_at']:
                # Time to exit
                exit_type = 'BUY' if pos['direction'] == 'DROP' else 'SELL'

                exit_order_id = None

                if pos.get('paper_mode', self.paper_mode):
                    # Paper trading - log but don't execute
                    exit_order_id = f"PAPER_EXIT_{datetime.now().strftime('%H%M%S')}_{symbol}"
                    logger.info(f"📝 PAPER EXIT: {exit_type} {symbol} x{pos['quantity']}")
                else:
                    # Live trading - place exit order
                    try:
                        exit_order_id = self.kite.place_order(
                            variety='regular',
                            exchange='NSE',
                            tradingsymbol=symbol,
                            transaction_type=exit_type,
                            quantity=pos['quantity'],
                            product=self.product,
                            order_type='MARKET'
                        )
                        logger.info(f"🤖 LIVE EXIT: {exit_type} {symbol} x{pos['quantity']} (order: {exit_order_id})")

                    except Exception as e:
                        logger.error(f"Failed to exit {symbol}: {e}")
                        # Still remove from tracking - broker will auto-square MIS at 3:15 PM

                # Calculate P&L if current price available
                current_price = None
                pnl = None
                pnl_pct = None

                if current_quotes and symbol in current_quotes:
                    current_price = current_quotes[symbol].get('price')
                    if current_price:
                        if pos['direction'] == 'DROP':
                            # Short: profit = entry - exit
                            pnl = (pos['entry_price'] - current_price) * pos['quantity']
                        else:
                            # Long: profit = exit - entry
                            pnl = (current_price - pos['entry_price']) * pos['quantity']

                        pnl_pct = (pnl / (pos['entry_price'] * pos['quantity'])) * 100

                exit_info = {
                    'symbol': symbol,
                    'direction': pos['direction'],
                    'entry_price': pos['entry_price'],
                    'exit_price': current_price,
                    'quantity': pos['quantity'],
                    'hold_time': self.exit_minutes,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'exit_order_id': exit_order_id,
                    'paper_mode': pos.get('paper_mode', self.paper_mode)
                }

                exits.append(exit_info)

                # Record-keeping only: keep the closed trade after tonight's reset
                self._append_history(symbol, pos, exit_info, now)

                # Remove from active positions
                del self.positions[symbol]
                logger.info(f"Position closed: {symbol} | P&L: ₹{pnl:+.2f} ({pnl_pct:+.2f}%)" if pnl else f"Position closed: {symbol}")

        # Persist updated positions if any exits occurred
        if exits:
            self._save_positions()

        return exits

    def get_status(self) -> Dict:
        """
        Get current auto-trader status.

        Returns:
            Dict with status info
        """
        return {
            'enabled': self.enabled,
            'paper_mode': self.paper_mode,
            'open_positions': len(self.positions),
            'trades_today': len(self.daily_trades),
            'max_positions': self.max_positions,
            'position_size': self.position_size,
            'positions': {
                symbol: {
                    'direction': pos['direction'],
                    'entry_price': pos['entry_price'],
                    'quantity': pos['quantity'],
                    'exit_at': pos['exit_at'].strftime('%H:%M:%S') if isinstance(pos['exit_at'], datetime) else pos['exit_at']
                }
                for symbol, pos in self.positions.items()
            }
        }


def get_auto_trader(kite_client: KiteConnect) -> Optional[AutoTrader]:
    """
    Factory function to get AutoTrader instance if enabled.

    Args:
        kite_client: Initialized KiteConnect instance

    Returns:
        AutoTrader instance if enabled, None otherwise
    """
    if not config.ENABLE_AUTO_TRADING:
        logger.info("Auto-trading disabled in config")
        return None

    return AutoTrader(kite_client)
