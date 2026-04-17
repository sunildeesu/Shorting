#!/usr/bin/env python3
"""
Order Flow Futures Token Loader

Fetches and caches instrument tokens for near-month stock futures contracts.
Called once at startup by OrderFlowCollector; refreshes if cache is from a prior day.

Uses futures_mapping.json (204 symbols → futures tradingsymbol) as the source of truth
for which contracts to subscribe. Matches against kite.instruments('NFO') to get tokens.
"""

import json
import logging
import os
from datetime import date
from typing import Dict, Optional

import config

logger = logging.getLogger(__name__)

_FUTURES_MAPPING_FILE = 'data/futures_mapping.json'


def get_futures_token_map(kite) -> Dict[str, int]:
    """
    Return {symbol: instrument_token} for near-month futures contracts.

    Loads from cache (data/futures_instrument_tokens.json) if it was written today.
    Otherwise fetches from Kite API and saves the cache.

    Returns empty dict if futures_mapping.json is missing or API call fails.
    """
    cache_file = config.ORDER_FLOW_FUTURES_TOKENS_FILE

    # Return cached map if it's from today
    cached = _load_cache(cache_file)
    if cached is not None:
        logger.info(f"Futures tokens loaded from cache: {len(cached)} contracts")
        return cached

    # Load futures_symbol mapping (symbol → futures tradingsymbol)
    symbol_to_futures = _load_futures_mapping()
    if not symbol_to_futures:
        logger.warning("futures_mapping.json missing or empty — skipping futures subscription")
        return {}

    # Fetch from Kite API
    logger.info("Fetching NFO instruments from Kite API for futures token map...")
    try:
        instruments = kite.instruments("NFO")
    except Exception as e:
        logger.error(f"Failed to fetch NFO instruments: {e}")
        return {}

    # Build tradingsymbol → token lookup from API response
    ts_to_token: Dict[str, int] = {
        inst['tradingsymbol']: inst['instrument_token']
        for inst in instruments
        if inst.get('instrument_type') == 'FUT'
    }
    logger.info(f"NFO API returned {len(ts_to_token)} futures contracts")

    # Match our 204 stocks to their tokens
    token_map: Dict[str, int] = {}
    missing = []
    for symbol, futures_symbol in symbol_to_futures.items():
        token = ts_to_token.get(futures_symbol)
        if token:
            token_map[symbol] = token
        else:
            missing.append(f"{symbol}({futures_symbol})")

    if missing:
        logger.warning(f"Futures tokens not found for {len(missing)} symbols: {missing[:10]}")

    logger.info(f"Futures token map built: {len(token_map)} contracts")
    _save_cache(cache_file, token_map)
    return token_map


def _load_futures_mapping() -> Dict[str, str]:
    """Return {symbol: futures_tradingsymbol} from futures_mapping.json."""
    if not os.path.exists(_FUTURES_MAPPING_FILE):
        return {}
    try:
        with open(_FUTURES_MAPPING_FILE) as f:
            data = json.load(f)
        mappings = data.get('mappings', {})
        return {sym: m['futures_symbol'] for sym, m in mappings.items() if 'futures_symbol' in m}
    except Exception as e:
        logger.error(f"Failed to read futures_mapping.json: {e}")
        return {}


def _load_cache(cache_file: str) -> Optional[Dict[str, int]]:
    """Return cached {symbol: token} map if it was written today, else None."""
    if not os.path.exists(cache_file):
        return None
    try:
        with open(cache_file) as f:
            data = json.load(f)
        if data.get('date') != str(date.today()):
            return None
        return {sym: int(tok) for sym, tok in data.get('tokens', {}).items()}
    except Exception:
        return None


def _save_cache(cache_file: str, token_map: Dict[str, int]) -> None:
    """Save {symbol: token} map with today's date stamp."""
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    try:
        with open(cache_file, 'w') as f:
            json.dump({'date': str(date.today()), 'tokens': token_map}, f)
        logger.info(f"Futures token cache saved: {cache_file}")
    except Exception as e:
        logger.error(f"Failed to save futures token cache: {e}")
