#!/usr/bin/env python3
"""
Order Flow Collector — KiteTicker WebSocket manager.

Subscribes all 208 F&O stocks in MODE_FULL to receive real-time:
  - Last traded price + quantity
  - Cumulative volume
  - Total pending buy/sell quantity across all depth levels
  - 5-level bid/ask market depth

Design:
  - Single WebSocket connection (Kite supports 3000 tokens in full mode)
  - _on_ticks callback: parse → append to in-memory deque (non-blocking)
  - Writer thread: drain deque → bulk INSERT to order_flow.db every 2 seconds
  - Runs as a daemon thread inside order_flow_monitor.py

Author: Claude Sonnet 4.6
"""

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional

from kiteconnect import KiteConnect, KiteTicker

import config
from order_flow_db import OrderFlowDB
from order_flow_futures_tokens import get_futures_token_map

logger = logging.getLogger(__name__)


class OrderFlowCollector:
    """
    Manages KiteTicker WebSocket for all F&O stocks.
    Writes raw ticks to order_flow.db via a background writer thread.
    """

    def __init__(self, kite: KiteConnect, db: OrderFlowDB):
        self.kite = kite
        self.db = db
        self.cash_token_map: Dict[int, str] = {}   # {token: symbol} for equity cash
        self.fut_token_map:  Dict[int, str] = {}   # {token: symbol} for near-month futures
        self.token_map: Dict[int, str] = {}        # combined map used by _parse_tick
        self.tokens: List[int] = []

        self._tick_buffer: deque = deque(maxlen=config.ORDER_FLOW_TICK_BUFFER_SIZE)
        self._buffer_lock = threading.Lock()

        self._ws: Optional[KiteTicker] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._running = False

        # Stats for metadata
        self._ticks_received = 0
        self._ticks_written = 0
        self._last_tick_time: Optional[datetime] = None

    # --------------------------------------------------------
    # Token loading
    # --------------------------------------------------------

    def _load_token_map(self) -> Dict[int, str]:
        """
        Load {instrument_token: symbol} for all F&O stocks (cash equity).
        Optionally also loads near-month futures tokens if ORDER_FLOW_FUTURES_ENABLED.
        Returns combined map; also sets self.cash_token_map and self.fut_token_map.
        """
        tokens_path = 'data/all_instrument_tokens.json'
        stocks_path = config.STOCK_LIST_FILE

        try:
            with open(tokens_path) as f:
                sym_to_token: Dict[str, int] = json.load(f)
        except FileNotFoundError:
            logger.error(f"Instrument tokens file not found: {tokens_path}")
            return {}

        try:
            with open(stocks_path) as f:
                fo_stocks = set(json.load(f)['stocks'])
        except FileNotFoundError:
            logger.error(f"F&O stock list not found: {stocks_path}")
            return {}

        # Cash tokens
        cash_map = {}
        missing = []
        for symbol in fo_stocks:
            token = sym_to_token.get(symbol)
            if token:
                cash_map[token] = symbol
            else:
                missing.append(symbol)
        if missing:
            logger.warning(f"No cash token for {len(missing)} symbols: {missing[:10]}...")
        self.cash_token_map = cash_map
        logger.info(f"Loaded {len(cash_map)} cash tokens for WebSocket subscription")

        # Futures tokens (optional)
        self.fut_token_map = {}
        if config.ORDER_FLOW_FUTURES_ENABLED:
            try:
                sym_to_fut_token = get_futures_token_map(self.kite)  # {symbol: token}
                self.fut_token_map = {tok: sym for sym, tok in sym_to_fut_token.items()}
                logger.info(f"Loaded {len(self.fut_token_map)} futures tokens for WebSocket subscription")
            except Exception as e:
                logger.warning(f"Failed to load futures tokens (continuing cash-only): {e}")

        combined = {**cash_map, **self.fut_token_map}
        return combined

    # --------------------------------------------------------
    # Tick parsing
    # --------------------------------------------------------

    @staticmethod
    def _parse_depth(depth: dict) -> dict:
        """
        Extract flattened depth fields from KiteTicker depth dict.
        Returns bid/ask quantities and prices for 5 levels plus totals.
        """
        buys = depth.get('buy', [])
        sells = depth.get('sell', [])

        def safe_qty(levels, i):
            return levels[i]['quantity'] if i < len(levels) else 0

        def safe_price(levels, i):
            return levels[i]['price'] if i < len(levels) else 0.0

        bid_qtys = [safe_qty(buys, i) for i in range(5)]
        ask_qtys = [safe_qty(sells, i) for i in range(5)]

        return {
            'bid_depth_total': sum(bid_qtys),
            'ask_depth_total': sum(ask_qtys),
            'best_bid':  safe_price(buys, 0),
            'best_ask':  safe_price(sells, 0),
            'bid_l1_qty': bid_qtys[0], 'bid_l2_qty': bid_qtys[1],
            'bid_l3_qty': bid_qtys[2], 'bid_l4_qty': bid_qtys[3],
            'bid_l5_qty': bid_qtys[4],
            'ask_l1_qty': ask_qtys[0], 'ask_l2_qty': ask_qtys[1],
            'ask_l3_qty': ask_qtys[2], 'ask_l4_qty': ask_qtys[3],
            'ask_l5_qty': ask_qtys[4],
            'bid_l1_price': safe_price(buys, 0),
            'ask_l1_price': safe_price(sells, 0),
        }

    def _parse_tick(self, raw: dict) -> Optional[dict]:
        """Parse a single KiteTicker tick dict into a flat storage dict."""
        token = raw.get('instrument_token')

        # Determine asset_type and symbol from the appropriate map
        if token in self.cash_token_map:
            symbol = self.cash_token_map[token]
            asset_type = 'CASH'
        elif token in self.fut_token_map:
            symbol = self.fut_token_map[token]
            asset_type = 'FUT'
        else:
            return None

        depth_fields = self._parse_depth(raw.get('depth', {}))

        return {
            'symbol':        symbol,
            'token':         token,
            'asset_type':    asset_type,
            'ts':            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'last_price':    raw.get('last_price', 0) or 0,
            'last_quantity': raw.get('last_traded_quantity', 0) or 0,
            'volume':        raw.get('volume_traded', 0) or 0,
            'buy_quantity':  raw.get('total_buy_quantity', 0) or 0,
            'sell_quantity': raw.get('total_sell_quantity', 0) or 0,
            **depth_fields,
        }

    # --------------------------------------------------------
    # KiteTicker callbacks
    # --------------------------------------------------------

    def _on_ticks(self, ws, ticks: List[dict]):
        """
        Called by KiteTicker on every incoming tick batch.
        Parses and appends to buffer — never blocks; DB write is in writer thread.
        """
        parsed = []
        for raw in ticks:
            tick = self._parse_tick(raw)
            if tick:
                parsed.append(tick)

        if parsed:
            with self._buffer_lock:
                self._tick_buffer.extend(parsed)
            self._ticks_received += len(parsed)
            self._last_tick_time = datetime.now()

    def _on_connect(self, ws, response):
        """Subscribe all F&O tokens in full mode after WebSocket connects."""
        logger.info(f"WebSocket connected — subscribing {len(self.tokens)} tokens in MODE_FULL")
        ws.subscribe(self.tokens)
        ws.set_mode(ws.MODE_FULL, self.tokens)
        self.db.update_metadata('ws_status', 'connected')
        self.db.update_metadata('ws_connected_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    def _on_reconnect(self, ws, attempts: int):
        logger.warning(f"WebSocket reconnecting (attempt {attempts}) — resubscribing tokens")
        ws.subscribe(self.tokens)
        ws.set_mode(ws.MODE_FULL, self.tokens)
        self.db.update_metadata('ws_status', f'reconnecting (attempt {attempts})')

    def _on_close(self, ws, code: int, reason: str):
        logger.warning(f"WebSocket closed: code={code} reason={reason}")
        self.db.update_metadata('ws_status', f'closed:{code}')

    def _on_error(self, ws, code: int, reason: str):
        logger.error(f"WebSocket error: code={code} reason={reason}")
        self.db.update_metadata('ws_status', f'error:{code}')

    # --------------------------------------------------------
    # Writer thread
    # --------------------------------------------------------

    def _writer_loop(self):
        """
        Background thread: drains tick buffer → batch INSERT → cleanup old ticks.
        Runs every ORDER_FLOW_WRITER_INTERVAL_SEC (default 2 seconds).
        """
        logger.info("OrderFlow writer thread started")
        cycle = 0
        while self._running:
            time.sleep(config.ORDER_FLOW_WRITER_INTERVAL_SEC)
            try:
                # Drain buffer atomically
                with self._buffer_lock:
                    batch = list(self._tick_buffer)
                    self._tick_buffer.clear()

                if batch:
                    self.db.store_tick_batch(batch)
                    self._ticks_written += len(batch)

                # Update health metadata every 10 cycles (~20 seconds)
                cycle += 1
                if cycle % 10 == 0:
                    rate = self._ticks_received / max(cycle * config.ORDER_FLOW_WRITER_INTERVAL_SEC, 1)
                    self.db.update_metadata('ticks_per_sec', f'{rate:.1f}')
                    if self._last_tick_time:
                        self.db.update_metadata(
                            'last_tick_time',
                            self._last_tick_time.strftime('%Y-%m-%d %H:%M:%S')
                        )
                    self.db.update_metadata('ticks_written_total', str(self._ticks_written))

                # Cleanup stale ticks every 30 cycles (~60 seconds)
                if cycle % 30 == 0:
                    deleted = self.db.cleanup_old_ticks()
                    if deleted:
                        logger.debug(f"Cleaned {deleted} old tick rows")

            except Exception as e:
                logger.error(f"Writer thread error: {e}", exc_info=True)

        logger.info("OrderFlow writer thread stopped")

    # --------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------

    def start(self):
        """
        Load tokens, start writer thread, then connect WebSocket.
        Blocks until stop() is called (KiteTicker.connect() blocks by default).
        Call from a daemon thread in order_flow_monitor.py.
        """
        self.token_map = self._load_token_map()
        if not self.token_map:
            logger.error("No tokens loaded — cannot start order flow collector")
            return

        self.tokens = list(self.token_map.keys())
        self._running = True

        # Start writer thread
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="OrderFlowWriter",
            daemon=True
        )
        self._writer_thread.start()

        # Create and connect KiteTicker
        self._ws = KiteTicker(config.KITE_API_KEY, config.KITE_ACCESS_TOKEN)
        self._ws.on_ticks     = self._on_ticks
        self._ws.on_connect   = self._on_connect
        self._ws.on_reconnect = self._on_reconnect
        self._ws.on_close     = self._on_close
        self._ws.on_error     = self._on_error

        logger.info(f"Starting KiteTicker WebSocket for {len(self.tokens)} F&O tokens")
        self.db.update_metadata('ws_status', 'starting')

        # threaded=True: KiteTicker runs Twisted reactor in its own internal thread,
        # which avoids the "signal only works in main thread" error when the collector
        # is started from a daemon thread. connect() returns immediately; we block here.
        self._ws.connect(threaded=True)
        while self._running:
            time.sleep(1)

    def stop(self):
        """Signal writer thread to stop and close WebSocket."""
        logger.info("Stopping OrderFlow collector...")
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self.db.update_metadata('ws_status', 'stopped')

    def is_data_fresh(self) -> bool:
        """Return True if we've received a tick within ORDER_FLOW_STALE_THRESHOLD_SEC."""
        if not self._last_tick_time:
            return False
        age = (datetime.now() - self._last_tick_time).total_seconds()
        return age <= config.ORDER_FLOW_STALE_THRESHOLD_SEC
