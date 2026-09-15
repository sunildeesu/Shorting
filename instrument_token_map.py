#!/usr/bin/env python3
"""
Shared instrument-token map: data/instrument_tokens.json.

The map is a flat ``{tradingsymbol: instrument_token}`` dict for every stock in
the F&O universe (fo_stocks.json) plus the two index keys ``"NIFTY 50"`` and
``"INDIA VIX"``. That shape is read by a dozen scripts (backfills, monitors,
backtests), so it is preserved here exactly.

Why this module exists: on 2026-08-31 the deployed map was nine months stale
(209 entries, written 2025-11-12) while fo_stocks.json carried 212 symbols. Every
backfill resolved symbols through the map, so every repaired tick had 192
symbols against 210 live ones, and every completeness check still read green.
refresh_fo_universe.py now rewrites the map from kite.instruments("NSE") on the
same run that refreshes the universe (`build_token_map` / `save_token_map`), and
the backfill entry points refuse to treat a short map as success
(`missing_tokens` / `report_missing_tokens`).
"""

import json
import logging
import os
from typing import Dict, Iterable, List

import config
from telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)

TOKENS_FILE = 'data/instrument_tokens.json'

# fo_stocks.json is not pure equity (see AGENTS.md): it carries index futures such as
# NIFTYNXT50 and NIFTYFPI, which have no NSE cash instrument and which the live
# collector never receives a quote for either. They are not a shortfall.
_INDEX_SYMBOLS = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'NIFTYFPI',
                  'SENSEX', 'BANKEX', 'NIFTYIT'}


def equity_symbols(symbols: Iterable[str]) -> List[str]:
    """Universe symbols that are expected to resolve on NSE cash: '.NS' stripped, indices dropped."""
    return sorted({s.replace('.NS', '') for s in symbols} - _INDEX_SYMBOLS)


def build_token_map(nse_instruments: Iterable[Dict], symbols: Iterable[str]) -> Dict[str, int]:
    """
    Build the map from a kite.instruments("NSE") dump, in the file's existing
    shape: one entry per universe symbol found on NSE, plus NIFTY 50 / INDIA VIX.
    """
    wanted = set(equity_symbols(symbols))
    token_map: Dict[str, int] = {}
    for inst in nse_instruments:
        sym = inst.get('tradingsymbol')
        if sym in wanted:
            token_map[sym] = inst['instrument_token']
    token_map['NIFTY 50'] = config.NIFTY_50_TOKEN
    token_map['INDIA VIX'] = config.INDIA_VIX_TOKEN
    return token_map


def load_token_map(path: str = TOKENS_FILE) -> Dict[str, int]:
    with open(path) as f:
        return json.load(f)


def save_token_map(token_map: Dict[str, int], path: str = TOKENS_FILE) -> None:
    """Atomic write (temp file + os.replace): live monitors read this file concurrently."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = f'{path}.tmp.{os.getpid()}'
    with open(tmp, 'w') as f:
        json.dump(token_map, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    logger.info(f"Saved {len(token_map)} instrument tokens → {path}")


def missing_tokens(symbols: Iterable[str], token_map: Dict[str, int]) -> List[str]:
    """Universe symbols that the map cannot resolve, sorted."""
    return sorted(set(equity_symbols(symbols)) - set(token_map))


def report_missing_tokens(symbols: Iterable[str], token_map: Dict[str, int],
                          caller: str, notify: bool = True) -> List[str]:
    """
    Compare the universe against the map. If any symbol has no token, log the
    names at ERROR and send one Telegram alert. Returns the missing names (empty
    when the map covers the universe) so the caller can refuse to report success.
    """
    missing = missing_tokens(symbols, token_map)
    if not missing:
        return []
    logger.error(
        f"{caller}: {len(missing)} universe symbols have no instrument token and "
        f"will NOT be backfilled: {', '.join(missing)} "
        f"(map {TOKENS_FILE} is behind {config.STOCK_LIST_FILE}; "
        f"run refresh_fo_universe.py)"
    )
    if notify:
        try:
            TelegramNotifier().send_message(
                f"⚠️ <b>BACKFILL INCOMPLETE</b> ({caller})\n"
                f"{len(missing)} symbols have no instrument token: {', '.join(missing)}\n"
                f"{TOKENS_FILE} is behind {config.STOCK_LIST_FILE} — "
                f"run refresh_fo_universe.py"
            )
        except Exception as e:
            logger.warning(f"Could not send token-shortfall alert: {e}")
    return missing
