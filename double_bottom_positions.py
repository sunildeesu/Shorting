#!/usr/bin/env python3
"""
Shared position store for the double-bottom strategy.

The monitor opens a position record when it alerts; the tracker closes it when the
target, stop or time stop fires. Kept in one small JSON file so both jobs (separate
launchd processes) agree on what is open and how many slots are free.

Author: Claude Code
Date: 2026-07-23
"""

import json
import logging
import os
import tempfile
from typing import Dict, List

import config

logger = logging.getLogger(__name__)

_EMPTY = {'open': [], 'closed': []}


def _path() -> str:
    return config.DOUBLE_BOTTOM_POSITIONS_FILE


def load() -> Dict:
    """Read the store; a missing or corrupt file is treated as empty."""
    try:
        with open(_path(), 'r') as f:
            data = json.load(f)
        data.setdefault('open', [])
        data.setdefault('closed', [])
        return data
    except FileNotFoundError:
        return json.loads(json.dumps(_EMPTY))
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Position file unreadable ({e}) - treating as empty")
        return json.loads(json.dumps(_EMPTY))


def save(data: Dict) -> None:
    """Atomic write so a crash mid-save cannot destroy the open-position list."""
    path = _path()
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def open_positions() -> List[Dict]:
    return load()['open']


def slots_free() -> int:
    return max(0, config.DOUBLE_BOTTOM_MAX_SLOTS - len(open_positions()))


def has_open(symbol: str) -> bool:
    return any(p['symbol'] == symbol for p in open_positions())


def opened_on(date_str: str) -> bool:
    """True if a position was already opened on this date (enforces 1 trade/day)."""
    data = load()
    return any(p.get('entry_date') == date_str for p in data['open'] + data['closed'])


def add(position: Dict) -> None:
    data = load()
    data['open'].append(position)
    save(data)
    logger.info(f"Opened tracked position: {position['symbol']} @ {position['entry_price']:.2f} "
                f"(stop {position['stop_price']:.2f}, target {position['target_price']:.2f})")


def update(symbol: str, **fields) -> None:
    """Patch fields on an open position (armed state, current trail stop, high water)."""
    data = load()
    for p in data['open']:
        if p['symbol'] == symbol:
            p.update(fields)
            save(data)
            return
    logger.warning(f"update() called for {symbol} but it is not open")


def drop(symbol: str) -> bool:
    """
    Remove an open position WITHOUT recording a trade.

    For signals that were never actually taken: the tracked position is holding a slot
    and blocking new entries, but counting it as a closed trade would corrupt the
    strategy's win/loss record. Use close() for a trade you really were in.
    """
    data = load()
    if not any(p['symbol'] == symbol for p in data['open']):
        logger.warning(f"drop() called for {symbol} but it is not open")
        return False
    data['open'] = [p for p in data['open'] if p['symbol'] != symbol]
    save(data)
    logger.info(f"Dropped untaken position {symbol} (slot freed, not recorded as a trade)")
    return True


def close(symbol: str, exit_date: str, exit_price: float, reason: str) -> Dict:
    """Move a position from open to closed, recording the realised P&L."""
    data = load()
    pos = next((p for p in data['open'] if p['symbol'] == symbol), None)
    if not pos:
        logger.warning(f"close() called for {symbol} but it is not open")
        return {}
    data['open'] = [p for p in data['open'] if p['symbol'] != symbol]
    pos.update({
        'exit_date': exit_date,
        'exit_price': exit_price,
        'exit_reason': reason,
        'pnl_pct': (exit_price - pos['entry_price']) / pos['entry_price'] * 100,
    })
    data['closed'].append(pos)
    save(data)
    logger.info(f"Closed {symbol} @ {exit_price:.2f} ({reason}, {pos['pnl_pct']:+.2f}%)")
    return pos
