#!/usr/bin/env python3
"""
Central DB Reader - Shared Helper Module for All Services

Provides reusable functions for reading from central_quotes.db with:
- Freshness checks before using data
- API fallback when central DB fails
- Health reporting for dashboard visibility

All services should use these functions instead of directly accessing central_db.

Author: Claude Code
Date: 2026-01-20
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any

from central_quote_db import get_central_db
from service_health import get_health_tracker

logger = logging.getLogger(__name__)

# Default freshness threshold in minutes
DEFAULT_MAX_AGE_MINUTES = 2


def fetch_stock_prices(
    symbols: List[str],
    service_name: str,
    kite_client=None,
    coordinator=None,
    futures_mapper=None,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES
) -> Dict[str, Dict]:
    """
    Fetch stock prices from central DB with freshness check + API fallback.

    This is the primary function for services to get stock prices.
    Uses central_quotes.db as the source of truth, with automatic
    fallback to Kite API if central DB is stale or unavailable.

    Args:
        symbols: List of stock symbols to fetch
        service_name: Name of calling service (for health tracking)
        kite_client: Optional KiteConnect instance for API fallback
        coordinator: Optional API coordinator for API fallback
        futures_mapper: Optional futures mapper for OI data in API fallback
        max_age_minutes: Maximum acceptable age for central DB data (default: 2)

    Returns:
        Dict of {symbol: {price, volume, oi, oi_day_high, oi_day_low, timestamp}}
        Returns empty dict on total failure

    Example:
        prices = fetch_stock_prices(
            symbols=['RELIANCE', 'TCS'],
            service_name='onemin_monitor',
            kite_client=self.kite,
            coordinator=self.coordinator
        )
    """
    if not symbols:
        return {}

    health = get_health_tracker()
    central_db = get_central_db()

    # Step 1: Check data freshness
    is_fresh, age_minutes = central_db.is_data_fresh(max_age_minutes=max_age_minutes)

    # Step 2: Handle no data / stale data scenarios
    if age_minutes is None:
        # No data in central database
        error_msg = "No data in central database - is central_data_collector running?"
        logger.error(f"[{service_name}] CENTRAL_DB_FAILURE: {error_msg}")
        health.report_error(service_name, "central_db_empty", error_msg, severity="error")
        health.report_metric(service_name, "data_source", "api_fallback")

        # Fallback to API
        if kite_client or coordinator:
            logger.warning(f"[{service_name}] Falling back to API calls...")
            return _fetch_stock_prices_from_api(
                symbols, service_name, kite_client, coordinator, futures_mapper, health
            )
        return {}

    if not is_fresh:
        # Data is stale
        error_msg = f"Central database data is STALE ({age_minutes} minutes old, max allowed: {max_age_minutes} min)"
        logger.error(f"[{service_name}] CENTRAL_DB_STALE: {error_msg}")
        health.report_error(service_name, "central_db_stale", error_msg,
                          severity="warning", details={"age_minutes": age_minutes})
        health.report_metric(service_name, "data_source", "api_fallback")

        # Fallback to API
        if kite_client or coordinator:
            logger.warning(f"[{service_name}] Falling back to API calls...")
            return _fetch_stock_prices_from_api(
                symbols, service_name, kite_client, coordinator, futures_mapper, health
            )
        return {}

    # Step 3: Central DB is fresh - use it
    logger.info(f"[{service_name}] Central DB data freshness check PASSED ({age_minutes} min old)")
    health.report_metric(service_name, "data_source", "central_db")
    health.report_metric(service_name, "central_db_age_minutes", age_minutes)

    # Step 4: Fetch quotes from central database
    try:
        db_quotes = central_db.get_latest_stock_quotes(symbols=symbols)

        if not db_quotes:
            error_msg = "No quotes returned from central database despite freshness check passing"
            logger.error(f"[{service_name}] CENTRAL_DB_FAILURE: {error_msg}")
            health.report_error(service_name, "central_db_no_quotes", error_msg)
            health.report_metric(service_name, "data_source", "api_fallback")

            if kite_client or coordinator:
                logger.warning(f"[{service_name}] Falling back to API calls...")
                return _fetch_stock_prices_from_api(
                    symbols, service_name, kite_client, coordinator, futures_mapper, health
                )
            return {}

        # Step 5: Validate quote coverage
        coverage_pct = (len(db_quotes) / len(symbols)) * 100
        health.report_metric(service_name, "quote_coverage_pct", round(coverage_pct, 1))

        if coverage_pct < 90:
            error_msg = f"Low quote coverage - only {len(db_quotes)}/{len(symbols)} stocks ({coverage_pct:.1f}%)"
            logger.warning(f"[{service_name}] CENTRAL_DB_DEGRADED: {error_msg}")
            health.report_error(service_name, "low_quote_coverage", error_msg,
                              severity="warning", details={"coverage_pct": coverage_pct})
            # Continue with what we have - don't fallback for partial data

        # Step 6: Convert to standard format with validation
        price_data = {}
        invalid_quotes = 0

        for symbol, quote in db_quotes.items():
            price = quote.get('price', 0)

            if price <= 0:
                logger.warning(f"[{service_name}] {symbol}: Invalid price ({price}) - skipping")
                invalid_quotes += 1
                continue

            price_data[symbol] = {
                'price': price,
                'volume': quote.get('volume', 0),
                'oi': quote.get('oi', 0),
                'oi_day_high': quote.get('oi_day_high', 0),
                'oi_day_low': quote.get('oi_day_low', 0),
                'timestamp': quote.get('timestamp', datetime.now().isoformat())
            }

        if invalid_quotes > 0:
            logger.warning(f"[{service_name}] Skipped {invalid_quotes} quotes with invalid prices")
            health.report_metric(service_name, "invalid_quotes", invalid_quotes)

        logger.info(f"[{service_name}] Read {len(price_data)} valid quotes from central DB (0 API calls)")
        health.report_metric(service_name, "quotes_fetched", len(price_data))

        # Clear any previous errors
        health.clear_error(service_name, "central_db_empty")
        health.clear_error(service_name, "central_db_stale")
        health.clear_error(service_name, "central_db_no_quotes")

        return price_data

    except Exception as e:
        error_msg = f"Exception reading from central DB: {e}"
        logger.error(f"[{service_name}] CENTRAL_DB_ERROR: {error_msg}")
        health.report_error(service_name, "central_db_exception", error_msg, severity="error")
        health.report_metric(service_name, "data_source", "api_fallback")

        if kite_client or coordinator:
            logger.warning(f"[{service_name}] Falling back to API calls...")
            return _fetch_stock_prices_from_api(
                symbols, service_name, kite_client, coordinator, futures_mapper, health
            )
        return {}


def _fetch_stock_prices_from_api(
    symbols: List[str],
    service_name: str,
    kite_client,
    coordinator,
    futures_mapper,
    health
) -> Dict[str, Dict]:
    """
    FALLBACK: Fetch prices from Kite API when central DB is unavailable.

    Uses coordinator if available (batched calls), otherwise direct kite.quote().

    Args:
        symbols: List of stock symbols
        service_name: Name of calling service
        kite_client: KiteConnect instance
        coordinator: API coordinator (optional)
        futures_mapper: Futures mapper for OI data (optional)
        health: Health tracker instance

    Returns:
        Dict of {symbol: {price, volume, oi, ...}}
    """
    logger.warning(f"[{service_name}] " + "=" * 50)
    logger.warning(f"[{service_name}] API FALLBACK MODE - central_data_collector may not be running!")
    logger.warning(f"[{service_name}] " + "=" * 50)

    health.report_error(service_name, "api_fallback_used",
                       "Using direct API calls instead of central database",
                       severity="warning")

    price_data = {}

    try:
        # Prefer coordinator if available (handles batching)
        if coordinator:
            # Build instrument list
            instruments = [f"NSE:{symbol}" for symbol in symbols]

            # Add futures for OI if mapper available
            symbol_to_futures = {}
            if futures_mapper:
                for symbol in symbols:
                    futures_symbol = futures_mapper.get_futures_symbol(symbol)
                    if futures_symbol:
                        instruments.append(f"NFO:{futures_symbol}")
                        symbol_to_futures[futures_symbol] = symbol

            # Fetch via coordinator
            quotes = coordinator.get_multiple_instruments(instruments, use_cache=False)

            # Parse equity quotes
            for instrument, quote in quotes.items():
                if instrument.startswith("NSE:"):
                    symbol = instrument.replace("NSE:", "")
                    if symbol not in symbols:
                        continue

                    ltp = quote.get('last_price', 0)
                    if ltp and ltp > 0:
                        price_data[symbol] = {
                            'price': float(ltp),
                            'volume': int(quote.get('volume', 0)),
                            'oi': 0,
                            'oi_day_high': 0,
                            'oi_day_low': 0,
                            'timestamp': datetime.now().isoformat()
                        }

            # Parse futures quotes for OI
            if futures_mapper:
                for instrument, quote in quotes.items():
                    if instrument.startswith("NFO:"):
                        futures_symbol = instrument.replace("NFO:", "")
                        equity_symbol = symbol_to_futures.get(futures_symbol)
                        if equity_symbol and equity_symbol in price_data:
                            price_data[equity_symbol]['oi'] = int(quote.get('oi', 0) or 0)
                            price_data[equity_symbol]['oi_day_high'] = int(quote.get('oi_day_high', 0) or 0)
                            price_data[equity_symbol]['oi_day_low'] = int(quote.get('oi_day_low', 0) or 0)

        elif kite_client:
            # Direct kite.quote() calls in batches
            BATCH_SIZE = 200
            instruments = [f"NSE:{symbol}" for symbol in symbols]

            for i in range(0, len(instruments), BATCH_SIZE):
                batch = instruments[i:i + BATCH_SIZE]
                quotes = kite_client.quote(*batch)

                for instrument, quote in quotes.items():
                    symbol = instrument.replace("NSE:", "")
                    ltp = quote.get('last_price', 0)
                    if ltp and ltp > 0:
                        price_data[symbol] = {
                            'price': float(ltp),
                            'volume': int(quote.get('volume', 0)),
                            'oi': 0,
                            'oi_day_high': 0,
                            'oi_day_low': 0,
                            'timestamp': datetime.now().isoformat()
                        }

        logger.info(f"[{service_name}] API fallback fetched {len(price_data)}/{len(symbols)} quotes")
        health.report_metric(service_name, "api_fallback_quotes_fetched", len(price_data))

    except Exception as e:
        logger.error(f"[{service_name}] API fallback failed: {e}")
        health.report_error(service_name, "api_fallback_failed", str(e), severity="error")

    return price_data


def fetch_nifty_vix(
    service_name: str,
    kite_client=None,
    coordinator=None,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES
) -> Dict[str, Optional[float]]:
    """
    Fetch NIFTY spot + VIX from central DB with freshness check + API fallback.

    This is the primary function for services that need NIFTY and/or VIX data.

    Args:
        service_name: Name of calling service (for health tracking)
        kite_client: Optional KiteConnect instance for API fallback
        coordinator: Optional API coordinator for API fallback
        max_age_minutes: Maximum acceptable age for central DB data (default: 2)

    Returns:
        Dict with 'nifty_spot' and 'india_vix' (both may be None on failure)

    Example:
        indices = fetch_nifty_vix(
            service_name='nifty_option_analyzer',
            kite_client=self.kite,
            coordinator=self.coordinator
        )
        nifty = indices['nifty_spot']
        vix = indices['india_vix']
    """
    result = {'nifty_spot': None, 'india_vix': None}

    health = get_health_tracker()
    central_db = get_central_db()

    # Step 1: Check data freshness
    is_fresh, age_minutes = central_db.is_data_fresh(max_age_minutes=max_age_minutes)

    # Step 2: Handle no data / stale data scenarios
    if age_minutes is None or not is_fresh:
        if age_minutes is None:
            error_msg = "No NIFTY/VIX data in central database"
            logger.warning(f"[{service_name}] CENTRAL_DB_EMPTY: {error_msg}")
        else:
            error_msg = f"NIFTY/VIX data is STALE ({age_minutes} min old)"
            logger.warning(f"[{service_name}] CENTRAL_DB_STALE: {error_msg}")

        health.report_metric(service_name, "nifty_vix_source", "api_fallback")

        # Fallback to API
        if coordinator or kite_client:
            return _fetch_nifty_vix_from_api(service_name, kite_client, coordinator, health)
        return result

    # Step 3: Central DB is fresh - fetch NIFTY and VIX
    try:
        nifty_data = central_db.get_nifty_latest()
        vix_data = central_db.get_vix_latest()

        if nifty_data:
            result['nifty_spot'] = nifty_data.get('price')
        if vix_data:
            result['india_vix'] = vix_data.get('vix_value')

        if result['nifty_spot'] and result['india_vix']:
            logger.info(f"[{service_name}] Read NIFTY/VIX from Central DB (0 API calls)")
            health.report_metric(service_name, "nifty_vix_source", "central_db")
            return result
        else:
            logger.warning(f"[{service_name}] NIFTY/VIX incomplete in Central DB, falling back to API")

    except Exception as e:
        logger.error(f"[{service_name}] Central DB error for NIFTY/VIX: {e}")

    # Fallback to API if central DB incomplete
    health.report_metric(service_name, "nifty_vix_source", "api_fallback")
    if coordinator or kite_client:
        return _fetch_nifty_vix_from_api(service_name, kite_client, coordinator, health)

    return result


def _fetch_nifty_vix_from_api(
    service_name: str,
    kite_client,
    coordinator,
    health
) -> Dict[str, Optional[float]]:
    """
    FALLBACK: Fetch NIFTY/VIX from Kite API.

    Args:
        service_name: Name of calling service
        kite_client: KiteConnect instance
        coordinator: API coordinator (optional)
        health: Health tracker instance

    Returns:
        Dict with 'nifty_spot' and 'india_vix'
    """
    result = {'nifty_spot': None, 'india_vix': None}

    try:
        instruments = ["NSE:NIFTY 50", "NSE:INDIA VIX"]

        if coordinator:
            quotes = coordinator.get_multiple_instruments(instruments, use_cache=False)
        elif kite_client:
            quotes = kite_client.quote(*instruments)
        else:
            return result

        nifty_data = quotes.get("NSE:NIFTY 50", {})
        vix_data = quotes.get("NSE:INDIA VIX", {})

        result['nifty_spot'] = nifty_data.get("last_price")
        result['india_vix'] = vix_data.get("last_price")

        logger.info(f"[{service_name}] Fetched NIFTY/VIX from API (fallback)")

    except Exception as e:
        logger.error(f"[{service_name}] API fallback for NIFTY/VIX failed: {e}")
        health.report_error(service_name, "nifty_vix_api_failed", str(e), severity="error")

    return result


def report_cycle_complete(
    service_name: str,
    cycle_start_time: float,
    stats: Dict[str, Any]
):
    """
    Report heartbeat + metrics at end of a monitoring cycle.

    Call this at the end of each monitoring cycle to report health metrics.
    This ensures the service shows up in the health dashboard.

    Args:
        service_name: Name of the service
        cycle_start_time: time.time() value from start of cycle
        stats: Dict with cycle statistics (keys vary by service)

    Example:
        cycle_start = time.time()
        # ... do monitoring work ...
        stats = {'alerts_sent': 2, 'stocks_checked': 100}
        report_cycle_complete('onemin_monitor', cycle_start, stats)
    """
    health = get_health_tracker()
    cycle_duration_ms = int((time.time() - cycle_start_time) * 1000)

    # Always report heartbeat
    health.heartbeat(service_name, cycle_duration_ms)

    # Report standard metrics
    health.report_metric(service_name, "last_cycle_duration_ms", cycle_duration_ms)

    # Report any stats provided
    for key, value in stats.items():
        health.report_metric(service_name, f"last_cycle_{key}", value)

    logger.debug(f"[{service_name}] Cycle complete: {cycle_duration_ms}ms, stats={stats}")
