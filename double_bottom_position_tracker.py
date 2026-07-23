#!/usr/bin/env python3
"""
Double Bottom Position Tracker - the exit engine for the double-bottom strategy.

double_bottom_support_monitor.py opens a tracked position when it alerts. This job runs
once daily after the close and applies the three exits, in priority order per bar:

  1. Target   - intraday high >= target (a resting limit would have filled)
  2. Stop     - daily CLOSE below the ATR stop. Deliberately NOT intraday: wicks through
                support were the main avoidable loss; a close-triggered 2xATR stop reached
                the same win rate an intraday stop needed 15% to reach.
  3. Time stop- exit at the close after DOUBLE_BOTTOM_TIME_STOP_DAYS trading days.

Each run replays the full path since entry, so a missed day (laptop asleep, holiday)
self-heals rather than losing the exit.

Author: Claude Code
Date: 2026-07-23
"""

import logging
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from kiteconnect import KiteConnect

import config
import double_bottom_positions as positions
from historical_data_cache import get_historical_cache
from telegram_notifier import TelegramNotifier
from market_utils import get_current_ist_time, is_trading_day
from service_health import get_health_tracker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/double_bottom_position_tracker.log'),
        logging.StreamHandler() if sys.stdout.isatty() else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

SERVICE_NAME = "double_bottom_position_tracker"
INSTRUMENT_TOKENS_FILE = "data/instrument_tokens.json"


def replay(position: Dict, candles: List[Dict]) -> Dict:
    """
    Replay the bars after entry and return both the exit (if any) and the live stop state.

    Two phases:

    UNARMED - the initial 2xATR close stop and the time stop apply. Reaching the target
        price arms the trade instead of closing it.
    ARMED   - the stop sits at max(lock, running_high * (1 - TRAIL_PCT/100)) and is a real
        intraday stop, so the gain is locked and winners can keep running.

    The trail may only ratchet on bars that have COMPLETED. Using the current bar's own
    high to place that same bar's stop would assume the high preceded the pullback, which
    a daily bar cannot tell you — in testing that single assumption inflated returns by
    ~27 percentage points. The one same-bar exit taken is provable: if the high reached
    the lock and the close is below it, price crossed back down through the lock after
    touching it, so a resting stop there filled.

    Args:
        position: tracked position record
        candles: daily candles covering entry date onwards, chronological

    Returns:
        {'exit': {'date','price','reason','days_held'} or None,
         'armed': bool, 'stop_price': float, 'high_water': float, 'days_held': int}
    """
    entry_date = position['entry_date']
    lock = position['target_price']
    trail = config.DOUBLE_BOTTOM_TRAIL_PCT
    # State is rebuilt from scratch every run, so it cannot drift from the price history
    # and a missed day self-heals. position['stop_price'] is always the ENTRY stop.
    stop = position['stop_price']
    armed = False
    high_water = position['entry_price']

    # Bars strictly after the entry day - the entry day itself cannot stop us out.
    forward = [c for c in candles if str(c['date'])[:10] > entry_date]

    for n, c in enumerate(forward, start=1):
        date_str = str(c['date'])[:10]

        if armed:
            if c['open'] <= stop:       # gapped through the locked stop overnight
                return {'exit': {'date': date_str, 'price': c['open'],
                                 'reason': 'gap', 'days_held': n},
                        'armed': True, 'stop_price': stop, 'high_water': high_water,
                        'days_held': n}
            if c['low'] <= stop:
                return {'exit': {'date': date_str, 'price': stop,
                                 'reason': 'trail', 'days_held': n},
                        'armed': True, 'stop_price': stop, 'high_water': high_water,
                        'days_held': n}
            high_water = max(high_water, c['high'])
            stop = max(stop, high_water * (1 - trail / 100))
        else:
            if c['high'] >= lock:
                if c['close'] < lock:   # provably crossed back down through the lock
                    return {'exit': {'date': date_str, 'price': lock,
                                     'reason': 'target', 'days_held': n},
                            'armed': True, 'stop_price': lock, 'high_water': c['high'],
                            'days_held': n}
                armed = True
                high_water = max(high_water, c['high'])
                stop = max(lock, high_water * (1 - trail / 100))
                continue
            if c['close'] <= stop:
                return {'exit': {'date': date_str, 'price': c['close'],
                                 'reason': 'stop', 'days_held': n},
                        'armed': False, 'stop_price': stop, 'high_water': high_water,
                        'days_held': n}

        if n >= config.DOUBLE_BOTTOM_TIME_STOP_DAYS:
            return {'exit': {'date': date_str, 'price': c['close'],
                             'reason': 'time', 'days_held': n},
                    'armed': armed, 'stop_price': stop, 'high_water': high_water,
                    'days_held': n}

    return {'exit': None, 'armed': armed, 'stop_price': stop,
            'high_water': high_water, 'days_held': len(forward)}


def find_exit(position: Dict, candles: List[Dict]) -> Optional[Dict]:
    """Exit for a position, or None if still open. Thin wrapper over replay()."""
    return replay(position, candles)['exit']


class DoubleBottomPositionTracker:
    """Applies target / stop / time-stop exits to tracked double-bottom positions."""

    def __init__(self):
        logger.info("=" * 80)
        logger.info("DOUBLE BOTTOM POSITION TRACKER - Initializing")
        logger.info("=" * 80)

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
        self.historical_cache = get_historical_cache()
        self.telegram = TelegramNotifier()
        self.instrument_tokens = self._load_instrument_tokens()
        self.dry_run = getattr(config, 'DOUBLE_BOTTOM_DRY_RUN_MODE', False)
        if self.dry_run:
            logger.warning("🔔 DRY RUN MODE ENABLED - exits will NOT be recorded or sent")

    def _load_instrument_tokens(self) -> Dict[str, int]:
        import json
        import os
        try:
            if os.path.exists(INSTRUMENT_TOKENS_FILE):
                with open(INSTRUMENT_TOKENS_FILE, 'r') as f:
                    return json.load(f)
            logger.warning(f"Instrument tokens file not found: {INSTRUMENT_TOKENS_FILE}")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load instrument tokens: {e}")
        return {}

    def _candles_since_entry(self, symbol: str, entry_date: str) -> List[Dict]:
        token = self.instrument_tokens.get(symbol)
        if not token:
            logger.warning(f"{symbol}: no instrument token - cannot evaluate exits")
            return []
        from_date = datetime.strptime(entry_date, '%Y-%m-%d') - timedelta(days=3)
        try:
            return self.historical_cache.get_historical_data(
                kite=self.kite,
                instrument_token=token,
                from_date=from_date,
                to_date=datetime.now(),
                interval='day'
            ) or []
        except Exception as e:
            logger.error(f"{symbol}: failed to fetch daily candles: {e}")
            return []

    def run(self) -> Dict:
        stats = {'open_before': 0, 'exits': 0, 'still_open': 0, 'stop_moves': 0}
        open_positions = positions.open_positions()
        stats['open_before'] = len(open_positions)

        if not open_positions:
            logger.info("No open positions to track")
            return stats

        logger.info(f"Evaluating {len(open_positions)} open position(s)")
        stop_moves = []
        for pos in list(open_positions):
            symbol = pos['symbol']
            candles = self._candles_since_entry(symbol, pos['entry_date'])
            if not candles:
                stats['still_open'] += 1
                continue

            state = replay(pos, candles)
            exit_info = state['exit']
            if not exit_info:
                last = candles[-1]
                mtm = (last['close'] - pos['entry_price']) / pos['entry_price'] * 100
                phase = "ARMED" if state['armed'] else "open"
                logger.info(f"   {symbol}: {phase}, {mtm:+.2f}% MTM, "
                            f"{state['days_held']}d held, stop now {state['stop_price']:.2f}"
                            + (f" (locked, trailing {config.DOUBLE_BOTTOM_TRAIL_PCT:.1f}% "
                               f"below high {state['high_water']:.2f})" if state['armed']
                               else f" / arms at {pos['target_price']:.2f}"))

                # Tell the user to move the order only when the level actually changed.
                previous = pos.get('current_stop', pos['stop_price'])
                if abs(state['stop_price'] - previous) > 0.005:
                    stop_moves.append({
                        'symbol': symbol, 'old_stop': previous,
                        'new_stop': state['stop_price'], 'armed': state['armed'],
                        'high_water': state['high_water'], 'mtm_pct': mtm,
                    })
                if not self.dry_run:
                    positions.update(symbol, armed=state['armed'],
                                     current_stop=state['stop_price'],
                                     high_water=state['high_water'])
                stats['still_open'] += 1
                continue

            pnl = (exit_info['price'] - pos['entry_price']) / pos['entry_price'] * 100
            logger.info(f"   {symbol}: EXIT {exit_info['reason'].upper()} on {exit_info['date']} "
                        f"@ {exit_info['price']:.2f} ({pnl:+.2f}%, {exit_info['days_held']}d)")

            if self.dry_run:
                logger.info(f"   [DRY RUN] would close {symbol} and alert")
                stats['still_open'] += 1
                continue

            positions.close(symbol, exit_info['date'], exit_info['price'], exit_info['reason'])
            self.telegram.send_double_bottom_exit_alert(
                symbol=symbol,
                exit_reason=exit_info['reason'],
                entry_price=pos['entry_price'],
                exit_price=exit_info['price'],
                pnl_pct=pnl,
                days_held=exit_info['days_held'],
                entry_date=pos['entry_date'],
            )
            stats['exits'] += 1

        if stop_moves:
            stats['stop_moves'] = len(stop_moves)
            for m in stop_moves:
                logger.info(f"   ⬆️  {m['symbol']}: move stop {m['old_stop']:.2f} -> "
                            f"{m['new_stop']:.2f}")
            if not self.dry_run:
                self.telegram.send_double_bottom_stop_update(stop_moves)

        logger.info(f"Tracker complete: {stats['exits']} exit(s), "
                    f"{stats['still_open']} still open, "
                    f"{positions.slots_free()}/{config.DOUBLE_BOTTOM_MAX_SLOTS} slots free")
        self._log_summary()
        return stats

    def _log_summary(self) -> None:
        """Running record of the strategy's closed trades."""
        closed = positions.load()['closed']
        if not closed:
            return
        wins = [p for p in closed if p['pnl_pct'] > 0]
        total = sum(p['pnl_pct'] for p in closed)
        logger.info(f"Closed trades to date: {len(closed)}, "
                    f"win rate {len(wins)/len(closed)*100:.1f}%, "
                    f"avg {total/len(closed):+.2f}%, sum {total:+.1f}%")


def main():
    cycle_start = time.time()
    health = get_health_tracker()
    try:
        if not is_trading_day():
            logger.info("Not a trading day - skipping")
            return
        tracker = DoubleBottomPositionTracker()
        result = tracker.run()
        logger.info(f"✅ Position tracker completed - {result['exits']} exit(s)")
        health.heartbeat(SERVICE_NAME, int((time.time() - cycle_start) * 1000))
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        health.heartbeat(SERVICE_NAME, int((time.time() - cycle_start) * 1000))
        health.report_error(SERVICE_NAME, "fatal_error", str(e))
        sys.exit(1)


if __name__ == "__main__":
    import proctitle; proctitle.set_title("nse-doublebottom-tracker")
    main()
