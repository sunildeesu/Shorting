#!/Users/sunilkumar/myProjects/ShortIndicator/venv/bin/python3
"""
Build Smallmid Stock Universe

Seeds flag_pattern.db with:
  1. Existing large/mid universe from data/all_nse_stocks.json
  2. NIFTY Midcap 150 + NIFTY Smallcap 250 from NSE index CSVs

Run once, then re-run monthly to refresh index constituents.

Usage:
    venv/bin/python3 build_smallmid_universe.py

Author: Sunil Kumar Durganaik
"""

import csv
import io
import json
import logging
import time
from typing import Dict, List, Optional, Set

import requests
from kiteconnect import KiteConnect

import config
from flag_pattern_db import FlagPatternDB

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# NSE archive URLs for index constituent lists (same format as data/nse_indices/ files)
_INDEX_URLS = {
    'midcap150':   'https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv',
    'smallcap250': 'https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv',
}
_INDEX_LOCAL = {
    'midcap150':   'data/nse_indices/ind_niftymidcap150list.csv',
    'smallcap250': 'data/nse_indices/ind_niftysmallcap250list.csv',
}
_NSE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer':    'https://www.nseindia.com',
    'Accept':     'text/html,application/xhtml+xml,*/*',
}


def _download_index_symbols(index_name: str) -> List[str]:
    """Download NSE index CSV and return list of symbols."""
    url = _INDEX_URLS[index_name]
    fallback = _INDEX_LOCAL[index_name]

    # Try NSE download first
    try:
        resp = requests.get(url, headers=_NSE_HEADERS, timeout=20)
        resp.raise_for_status()
        content = resp.text
        logger.info(f"{index_name}: downloaded {len(content):,} bytes from NSE")
    except Exception as e:
        logger.warning(f"{index_name}: NSE download failed ({e}) — trying local fallback")
        try:
            with open(fallback) as f:
                content = f.read()
            logger.info(f"{index_name}: using local file {fallback}")
        except FileNotFoundError:
            logger.error(
                f"{index_name}: local fallback not found at {fallback}\n"
                f"  Download manually: {url}\n"
                f"  Save to: {fallback}"
            )
            return []

    symbols = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        sym = row.get('Symbol', '').strip()
        if sym:
            symbols.append(sym)

    logger.info(f"{index_name}: {len(symbols)} symbols parsed")
    return symbols


def _fetch_kite_instruments(kite: KiteConnect) -> Dict[str, Dict]:
    """Return {tradingsymbol: {token, name}} for all NSE EQ instruments."""
    logger.info("Fetching all NSE instruments from Kite (EQ series)...")
    instruments = kite.instruments("NSE")
    token_map = {}
    for inst in instruments:
        if inst.get('series') == 'EQ' or inst.get('instrument_type') == 'EQ':
            sym = inst['tradingsymbol']
            token_map[sym] = {
                'token': inst['instrument_token'],
                'name':  inst.get('name', sym),
            }
    logger.info(f"Kite: {len(token_map)} NSE EQ instruments found")
    return token_map


def main():
    if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
        logger.error("KITE_API_KEY and KITE_ACCESS_TOKEN must be set in .env")
        return

    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    db = FlagPatternDB(config.FLAG_DB_PATH)
    kite_instruments = _fetch_kite_instruments(kite)

    # ----------------------------------------------------------------
    # Step 1: seed large_mid universe from existing JSON files
    # ----------------------------------------------------------------
    large_mid_seeded = 0
    try:
        with open('data/all_nse_stocks.json') as f:
            lm_data = json.load(f)
        with open('data/all_instrument_tokens.json') as f:
            lm_tokens = json.load(f)

        lm_stocks = (
            lm_data.get('stocks', lm_data)
            if isinstance(lm_data, dict)
            else lm_data
        )
        for symbol in lm_stocks:
            token = lm_tokens.get(symbol)
            if not token:
                continue
            name = kite_instruments.get(symbol, {}).get('name', symbol)
            db.upsert_stock(symbol, name, token, segment='large_mid', index_membership=None)
            large_mid_seeded += 1

        logger.info(f"Seeded {large_mid_seeded} large_mid stocks from JSON")
    except Exception as e:
        logger.error(f"Failed to seed large_mid stocks: {e}")

    # ----------------------------------------------------------------
    # Step 2: download smallmid symbols from NSE index CSVs
    # ----------------------------------------------------------------
    existing_symbols: Set[str] = {s['symbol'] for s in db.get_all_stocks()}

    # Collect {symbol -> set of index memberships}
    smallmid_map: Dict[str, Set[str]] = {}
    for index_name in ('midcap150', 'smallcap250'):
        symbols = _download_index_symbols(index_name)
        time.sleep(1)  # polite delay between NSE requests
        for sym in symbols:
            smallmid_map.setdefault(sym, set()).add(index_name)

    # Upsert into DB
    added = skipped_no_token = 0
    for symbol, memberships in smallmid_map.items():
        kite_info = kite_instruments.get(symbol)
        if not kite_info:
            logger.debug(f"{symbol}: not in Kite EQ instruments — skipping")
            skipped_no_token += 1
            continue

        token = kite_info['token']
        name  = kite_info['name']
        index_membership = 'both' if len(memberships) == 2 else next(iter(memberships))

        if symbol in existing_symbols:
            # Already in DB as large_mid — just update index_membership label
            db.upsert_stock(symbol, name, token, segment='large_mid',
                            index_membership=index_membership)
        else:
            db.upsert_stock(symbol, name, token, segment='smallmid',
                            index_membership=index_membership)
            added += 1

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    counts = db.stock_count()
    total  = sum(counts.values())

    print()
    print("=" * 52)
    print("  Stock Universe Build Complete")
    print("=" * 52)
    print(f"  Large/mid seeded from JSON : {large_mid_seeded}")
    print(f"  Smallmid new stocks added  : {added}")
    print(f"  No Kite token (skipped)    : {skipped_no_token}")
    print(f"  DB breakdown               : {dict(counts)}")
    print(f"  Total stocks in DB         : {total}")
    print(f"  DB path                    : {config.FLAG_DB_PATH}")
    print("=" * 52)
    print()
    print("Next step: run flag_pattern_monitor.py")
    print("Re-run this script monthly to refresh index constituents.")


if __name__ == '__main__':
    main()
