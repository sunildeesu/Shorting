#!/usr/bin/env python3
"""
Refresh F&O Universe

Single script that keeps the stock universe in sync with NSE F&O eligibility.
Run weekly (Mondays before market open) via launchd.

Updates:
  fo_stocks.json          — stock list (adds/removes when NSE changes F&O eligibility)
  data/futures_mapping.json — near-month contract per stock (refreshes after monthly expiry)

One Kite NFO instruments API call does both jobs. Sends Telegram only when the
stock list actually changes (additions/removals).

Excluded indices: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX, NIFTYIT
"""

import json
import logging
import os
import sys
from datetime import datetime, date
from typing import Dict, List, Set, Tuple

from kiteconnect import KiteConnect

import config
from telegram_notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/refresh_fo_universe.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Indices that appear in NFO but are not stocks
_INDEX_NAMES: Set[str] = {
    'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX', 'NIFTYIT'
}

FO_STOCKS_FILE    = config.STOCK_LIST_FILE          # fo_stocks.json
FUTURES_MAP_FILE  = 'data/futures_mapping.json'


def fetch_nfo_instruments(kite: KiteConnect) -> List[Dict]:
    """Fetch all NFO instruments. Raises on failure (caller handles)."""
    logger.info("Fetching NFO instruments from Kite API...")
    instruments = kite.instruments("NFO")
    logger.info(f"  → {len(instruments)} total NFO instruments")
    return instruments


def derive_fo_stocks(instruments: List[Dict]) -> List[str]:
    """Extract sorted list of equity stock symbols that have F&O contracts."""
    stocks: Set[str] = set()
    for inst in instruments:
        if inst.get('instrument_type') in ('FUT', 'CE', 'PE'):
            name = inst.get('name', '')
            if name and name not in _INDEX_NAMES:
                stocks.add(name)
    return sorted(stocks)


def derive_futures_mapping(instruments: List[Dict], fo_stocks: List[str]) -> Dict:
    """
    Build futures_mapping.json content: maps each stock to its near-month futures contract.
    Picks the nearest (most liquid) expiry per stock.
    """
    fo_set = set(fo_stocks)

    # Group FUT contracts by stock name
    contracts_by_stock: Dict[str, List[Dict]] = {}
    for inst in instruments:
        if inst.get('instrument_type') != 'FUT':
            continue
        name = inst.get('name', '')
        if name not in fo_set:
            continue
        contracts_by_stock.setdefault(name, []).append(inst)

    mappings: Dict[str, Dict] = {}
    for symbol, contracts in contracts_by_stock.items():
        # Nearest expiry = most liquid
        contracts.sort(key=lambda x: x['expiry'])
        nearest = contracts[0]
        expiry = nearest['expiry']
        if isinstance(expiry, date):
            expiry = expiry.isoformat()
        mappings[symbol] = {
            'futures_symbol': nearest['tradingsymbol'],
            'expiry': str(expiry),
            'exchange': nearest['exchange'],
        }

    return {
        'metadata': {
            'last_updated': datetime.now().isoformat(),
            'total_mappings': len(mappings),
        },
        'mappings': mappings,
        'stats': {
            'with_futures': len(mappings),
            'without_futures': len(fo_stocks) - len(mappings),
        },
    }


def load_current_fo_stocks() -> List[str]:
    try:
        with open(FO_STOCKS_FILE) as f:
            return json.load(f)['stocks']
    except FileNotFoundError:
        return []


def load_current_futures_mapping() -> Dict:
    try:
        with open(FUTURES_MAP_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_fo_stocks(stocks: List[str]):
    with open(FO_STOCKS_FILE, 'w') as f:
        json.dump({'stocks': stocks}, f, indent=2)
    logger.info(f"Saved {len(stocks)} stocks → {FO_STOCKS_FILE}")


def save_futures_mapping(data: Dict):
    os.makedirs(os.path.dirname(FUTURES_MAP_FILE), exist_ok=True)
    with open(FUTURES_MAP_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    logger.info(f"Saved {data['metadata']['total_mappings']} futures mappings → {FUTURES_MAP_FILE}")


def futures_mapping_needs_refresh(current: Dict, new_mapping: Dict) -> bool:
    """True if any stock's near-month contract has changed (monthly rollover)."""
    old_mappings = current.get('mappings', {})
    new_mappings = new_mapping.get('mappings', {})
    for symbol, new_m in new_mappings.items():
        old_m = old_mappings.get(symbol, {})
        if old_m.get('futures_symbol') != new_m['futures_symbol']:
            return True
    return False


def send_telegram_change_alert(
    notifier: TelegramNotifier,
    added: List[str],
    removed: List[str],
    total_new: int,
):
    """Send Telegram notification about F&O stock list changes."""
    lines = [
        "\U0001f4cb <b>F&amp;O UNIVERSE UPDATED</b>",
        f"Total stocks: {total_new}",
        "",
    ]
    if added:
        lines.append(f"\u2705 Added ({len(added)}): {', '.join(added)}")
    if removed:
        lines.append(f"\u274c Removed ({len(removed)}): {', '.join(removed)}")

    msg = "\n".join(lines)
    try:
        import requests
        url = f"https://api.telegram.org/bot{notifier.bot_token}/sendMessage"
        requests.post(url, json={
            "chat_id": notifier.channel_id,
            "text": msg,
            "parse_mode": "HTML",
        }, timeout=10)
        logger.info("Telegram notification sent")
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")


def main():
    logger.info("=" * 60)
    logger.info("F&O UNIVERSE REFRESH")
    logger.info("=" * 60)

    if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
        logger.error("KITE_API_KEY or KITE_ACCESS_TOKEN not set — exiting")
        sys.exit(1)

    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # One API call, two uses
    try:
        instruments = fetch_nfo_instruments(kite)
    except Exception as e:
        logger.error(f"Failed to fetch NFO instruments: {e}")
        sys.exit(1)

    # --- F&O stock list ---
    new_stocks  = derive_fo_stocks(instruments)
    old_stocks  = load_current_fo_stocks()
    old_set     = set(old_stocks)
    new_set     = set(new_stocks)
    added       = sorted(new_set - old_set)
    removed     = sorted(old_set - new_set)

    if added or removed:
        logger.info(f"Stock list changed: +{len(added)} added, -{len(removed)} removed")
        for s in added:
            logger.info(f"  + {s}")
        for s in removed:
            logger.info(f"  - {s}")
        save_fo_stocks(new_stocks)
    else:
        logger.info(f"Stock list unchanged ({len(new_stocks)} stocks)")

    # --- Futures mapping ---
    new_futures_data    = derive_futures_mapping(instruments, new_stocks)
    current_futures     = load_current_futures_mapping()

    if futures_mapping_needs_refresh(current_futures, new_futures_data) or added or removed:
        old_expiry = next(
            iter(current_futures.get('mappings', {}).values()), {}
        ).get('expiry', 'unknown')
        new_expiry = next(
            iter(new_futures_data['mappings'].values()), {}
        ).get('expiry', 'unknown')
        if old_expiry != new_expiry:
            logger.info(f"Contract rollover: {old_expiry} → {new_expiry}")
        save_futures_mapping(new_futures_data)
    else:
        logger.info("Futures mapping unchanged — skipping write")

    # --- Telegram alert (only on stock list changes) ---
    if added or removed:
        try:
            notifier = TelegramNotifier()
            send_telegram_change_alert(notifier, added, removed, len(new_stocks))
        except Exception as e:
            logger.warning(f"Could not send Telegram alert: {e}")

    logger.info("Done.")


if __name__ == '__main__':
    main()
