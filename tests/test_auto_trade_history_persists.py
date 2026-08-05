#!/usr/bin/env python3
"""
Regression test: a completed auto-trade must survive the nightly reset.

AUTO_TRADE_POSITIONS_FILE holds only the CURRENT trading day - _load_positions() throws
its contents away as soon as the date changes. Every paper trade the system took between
February and August 2026 was therefore erased overnight, which is exactly why the
"97% win rate" claim in config.py could never be checked against reality.

The contract pinned here:
  * a trade that closes is appended to data/auto_trade_history.jsonl (a sibling of the
    positions file), one JSON object per line, and is STILL there after the day rolls over;
  * the append is additive - yesterday's lines are never rewritten when today's arrive;
  * the positions file keeps its original job: same-day restart still recovers open
    positions and the already-traded-today set, and the day rollover still clears them.

Runs offline: paper mode only, no broker client, no orders, no credentials, and everything
is written under a temporary directory - nothing touches data/.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from auto_trader import AutoTrader


class AutoTradeHistoryPersistenceTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='auto_trade_history_test_')
        self.positions_file = os.path.join(self.tmpdir, 'auto_trade_positions.json')
        self.history_file = os.path.join(self.tmpdir, 'auto_trade_history.jsonl')
        patcher = mock.patch.object(config, 'AUTO_TRADE_POSITIONS_FILE', self.positions_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def make_trader(self):
        """A trader with no broker client; paper mode is forced so no order path can run."""
        trader = AutoTrader(kite_client=None)
        trader.paper_mode = True
        return trader

    def close_a_trade(self, trader, symbol, entry_price, exit_price, direction='DROP'):
        """Open a paper position, make it due, and let check_exits() close it."""
        trade = trader.execute_trade(symbol, direction, entry_price)
        self.assertIsNotNone(trade)
        self.assertTrue(trade['paper_mode'], "test must never leave paper mode")
        trader.positions[symbol]['exit_at'] = datetime.now() - timedelta(seconds=1)
        exits = trader.check_exits({symbol: {'price': exit_price}})
        self.assertEqual(len(exits), 1)
        return exits[0]

    def read_history(self):
        with open(self.history_file) as f:
            return [json.loads(line) for line in f if line.strip()]

    def roll_over_to_next_day(self):
        """Age the positions file by one day - what happens overnight in production."""
        with open(self.positions_file) as f:
            data = json.load(f)
        yesterday = datetime.now() - timedelta(days=1)
        data['date'] = yesterday.strftime('%Y-%m-%d')
        with open(self.positions_file, 'w') as f:
            json.dump(data, f)

    def test_completed_trade_survives_the_day_rollover(self):
        trader = self.make_trader()
        self.close_a_trade(trader, 'RELIANCE', 1000.0, 990.0, direction='DROP')

        records = self.read_history()
        self.assertEqual(len(records), 1)
        record = records[0]

        # Everything needed to judge the strategy later must be in the line.
        for field in ('date', 'symbol', 'direction', 'entry_price', 'entry_time',
                      'exit_price', 'exit_time', 'paper_mode', 'pnl', 'pnl_pct',
                      'quantity'):
            self.assertIn(field, record)
            self.assertIsNotNone(record[field], f"{field} must be recorded")

        self.assertEqual(record['symbol'], 'RELIANCE')
        self.assertEqual(record['direction'], 'DROP')
        self.assertTrue(record['paper_mode'])
        self.assertEqual(record['exit_price'], 990.0)
        # Short entered ~1001 (0.1% paper slippage) and covered at 990 -> a win.
        self.assertGreater(record['pnl'], 0)
        self.assertAlmostEqual(record['pnl_pct'], 100 * record['pnl'] /
                               (record['entry_price'] * record['quantity']), places=6)

        # The positions file never held the outcome even before the rollover: the closed
        # position is gone from it and only the symbol's name survives in daily_trades.
        with open(self.positions_file) as f:
            same_day_state = json.load(f)
        self.assertEqual(same_day_state['positions'], {})

        # The day turns over: the trader forgets, the history file does not.
        self.roll_over_to_next_day()
        next_day = self.make_trader()

        self.assertEqual(next_day.positions, {})
        self.assertEqual(next_day.daily_trades, set(),
                         "day rollover must still clear today's traded set")

        surviving = self.read_history()
        self.assertEqual(len(surviving), 1)
        self.assertEqual(surviving[0]['symbol'], 'RELIANCE')

    def test_history_accumulates_and_is_never_rewritten(self):
        day_one = self.make_trader()
        self.close_a_trade(day_one, 'RELIANCE', 1000.0, 990.0, direction='DROP')
        first_line = self.read_history()[0]

        self.roll_over_to_next_day()

        day_two = self.make_trader()
        self.close_a_trade(day_two, 'TCS', 2000.0, 2050.0, direction='RISE')

        records = self.read_history()
        self.assertEqual(len(records), 2, "a second day must add, not replace")
        self.assertEqual(records[0], first_line, "yesterday's line must be byte-identical")
        self.assertEqual(records[1]['symbol'], 'TCS')
        self.assertEqual(records[1]['direction'], 'RISE')
        self.assertGreater(records[1]['pnl'], 0)

    def test_same_day_restart_still_recovers_open_positions(self):
        """The positions file's original job must be untouched by the history addition."""
        trader = self.make_trader()
        trade = trader.execute_trade('INFY', 'RISE', 1500.0)
        self.assertIsNotNone(trade)

        restarted = self.make_trader()

        self.assertIn('INFY', restarted.positions)
        self.assertIn('INFY', restarted.daily_trades)
        self.assertIsInstance(restarted.positions['INFY']['exit_at'], datetime)
        self.assertIsInstance(restarted.positions['INFY']['entry_time'], datetime)
        # Nothing has closed yet, so nothing has been logged.
        self.assertFalse(os.path.exists(self.history_file))

    def test_history_failure_cannot_break_the_exit(self):
        """Record-keeping is best-effort: a broken log must not disturb an exit."""
        trader = self.make_trader()
        with mock.patch.object(AutoTrader, '_history_file',
                               side_effect=OSError('disk full')):
            exit_info = self.close_a_trade(trader, 'WIPRO', 500.0, 495.0, direction='DROP')

        self.assertEqual(exit_info['symbol'], 'WIPRO')
        self.assertEqual(trader.positions, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
