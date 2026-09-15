#!/usr/bin/env python3
"""
Regression tests for the instrument-token map (data/instrument_tokens.json).

On 2026-08-31 the deployed map was nine months stale: it resolved 192 of the
collector's 210 symbols, every backfilled tick was 18 symbols short, and every
completeness check still read green. The contract pinned here:

  * refresh_fo_universe.py rewrites the map from kite.instruments("NSE") on the
    same run that refreshes fo_stocks.json, in the file's existing shape (flat
    {symbol: token} plus "NIFTY 50" and "INDIA VIX");
  * a map that cannot resolve N universe symbols makes the central backfill log
    the names at ERROR, send one Telegram alert, and return
    complete=False with the names - it never reports success;
  * a map that covers the universe passes silently;
  * the intraday candle backfill aborts (exit 3) on the same shortfall;
  * index futures carried by fo_stocks.json (NIFTYNXT50, NIFTYFPI) are not a
    shortfall: they have no NSE cash instrument and the live collector never
    receives a quote for them either.

Runs offline: Kite and Telegram are mocked, files live in a temp directory.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import instrument_token_map as itm

UNIVERSE = ['ABB', 'ADANIENT', 'SWIGGY', 'NIFTYNXT50']
NSE_INSTRUMENTS = [
    {'tradingsymbol': 'ABB', 'instrument_token': 3329, 'exchange': 'NSE'},
    {'tradingsymbol': 'ADANIENT', 'instrument_token': 6401, 'exchange': 'NSE'},
    {'tradingsymbol': 'SWIGGY', 'instrument_token': 4835073, 'exchange': 'NSE'},
    {'tradingsymbol': 'SWIGGY-BE', 'instrument_token': 99, 'exchange': 'NSE'},
    {'tradingsymbol': 'NOTINUNIVERSE', 'instrument_token': 7, 'exchange': 'NSE'},
]
FULL_MAP = {'ABB': 3329, 'ADANIENT': 6401, 'SWIGGY': 4835073,
            'NIFTY 50': config.NIFTY_50_TOKEN, 'INDIA VIX': config.INDIA_VIX_TOKEN}
STALE_MAP = {'ABB': 3329, 'ADANIENT': 6401,
             'NIFTY 50': config.NIFTY_50_TOKEN, 'INDIA VIX': config.INDIA_VIX_TOKEN}


class TempProjectDir(unittest.TestCase):
    """Run in a temp cwd so 'data/instrument_tokens.json' and fo_stocks.json are throwaway."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='token_map_test_')
        self._cwd = os.getcwd()
        os.chdir(self.tmpdir)
        os.makedirs('data')
        os.makedirs('logs')
        with open('fo_stocks.json', 'w') as f:
            json.dump({'stocks': UNIVERSE}, f)
        mock.patch.object(config, 'STOCK_LIST_FILE', 'fo_stocks.json').start()
        self.notifier = mock.Mock()
        mock.patch.object(itm, 'TelegramNotifier', return_value=self.notifier).start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_map(self, token_map):
        with open(itm.TOKENS_FILE, 'w') as f:
            json.dump(token_map, f)


class BuildAndSaveTest(TempProjectDir):

    def test_build_keeps_existing_shape_and_ignores_indices(self):
        token_map = itm.build_token_map(NSE_INSTRUMENTS, UNIVERSE)
        self.assertEqual(token_map, FULL_MAP)

    def test_refresh_fo_universe_writes_map_from_mocked_kite(self):
        import refresh_fo_universe
        self.write_map(STALE_MAP)
        kite = mock.Mock()
        kite.instruments.return_value = NSE_INSTRUMENTS

        with self.assertLogs(refresh_fo_universe.logger, level='INFO') as logs:
            refresh_fo_universe.refresh_token_map(kite, UNIVERSE)

        kite.instruments.assert_called_once_with('NSE')
        with open(itm.TOKENS_FILE) as f:
            self.assertEqual(json.load(f), FULL_MAP)
        self.assertTrue(any('+ SWIGGY' in line for line in logs.output), logs.output)
        self.assertFalse(os.path.exists(itm.TOKENS_FILE + f'.tmp.{os.getpid()}'))

    def test_index_futures_in_universe_are_not_a_shortfall(self):
        self.assertEqual(itm.missing_tokens(UNIVERSE, FULL_MAP), [])
        self.assertEqual(itm.missing_tokens(['ABB.NS', 'NIFTYFPI'], FULL_MAP), [])


class ReportMissingTest(TempProjectDir):

    def test_short_map_logs_error_alerts_and_returns_names(self):
        with self.assertLogs(itm.logger, level='ERROR') as logs:
            missing = itm.report_missing_tokens(UNIVERSE, STALE_MAP, caller='test')
        self.assertEqual(missing, ['SWIGGY'])
        self.assertIn('SWIGGY', logs.output[0])
        self.notifier.send_message.assert_called_once()
        self.assertIn('SWIGGY', self.notifier.send_message.call_args.args[0])

    def test_complete_map_is_silent(self):
        with self.assertNoLogs(itm.logger, level='WARNING'):
            self.assertEqual(itm.report_missing_tokens(UNIVERSE, FULL_MAP, caller='test'), [])
        self.notifier.send_message.assert_not_called()


class CentralBackfillTest(TempProjectDir):
    """CentralDataBackfill with the DB, Kite and the day-selection stubbed out."""

    def setUp(self):
        super().setUp()
        import central_data_backfill as cdb
        self.cdb = cdb
        mock.patch.object(cdb, 'get_central_db_writer', return_value=mock.Mock()).start()
        mock.patch.object(cdb.CentralDataBackfill, 'get_last_data_timestamp',
                          return_value=None).start()
        mock.patch.object(cdb.CentralDataBackfill, 'get_trading_days_to_backfill',
                          return_value=[cdb.datetime(2026, 8, 31).date()]).start()
        for name in ('backfill_nifty_data', 'backfill_vix_data'):
            mock.patch.object(cdb.CentralDataBackfill, name, return_value=1).start()
        mock.patch.object(cdb.CentralDataBackfill, 'backfill_stock_data', autospec=True,
                          side_effect=lambda bf, sym, day: 375 if sym in bf.instrument_tokens else 0
                          ).start()
        mock.patch('time.sleep').start()

    def _kite(self, nse_instruments):
        kite = mock.Mock()
        kite.instruments.return_value = nse_instruments
        return kite

    def test_stale_map_that_kite_cannot_repair_is_reported_not_success(self):
        """Map short by SWIGGY, and NSE dump (mocked) also lacks it: loud shortfall."""
        self.write_map(STALE_MAP)
        without_swiggy = [i for i in NSE_INSTRUMENTS if not i['tradingsymbol'].startswith('SWIGGY')]
        backfill = self.cdb.CentralDataBackfill(self._kite(without_swiggy))

        with self.assertLogs(itm.logger, level='ERROR') as logs:
            stats = backfill.run_backfill()

        self.assertFalse(stats['complete'])
        self.assertEqual(stats['missing_token_symbols'], ['SWIGGY'])
        self.assertIn('SWIGGY', logs.output[0])
        self.notifier.send_message.assert_called_once()
        # Resolvable symbols were still backfilled (the day would otherwise be empty).
        self.assertEqual(stats['stocks_backfilled'], 2)
        self.assertEqual(stats['days_backfilled'], 1)

    def test_stale_map_is_regenerated_from_kite_before_backfilling(self):
        self.write_map(STALE_MAP)
        backfill = self.cdb.CentralDataBackfill(self._kite(NSE_INSTRUMENTS))

        self.assertEqual(backfill.instrument_tokens, FULL_MAP)
        with open(itm.TOKENS_FILE) as f:
            self.assertEqual(json.load(f), FULL_MAP)
        stats = backfill.run_backfill()
        self.assertTrue(stats['complete'])
        self.assertEqual(stats['missing_token_symbols'], [])
        self.assertEqual(stats['stocks_backfilled'], 3)
        self.notifier.send_message.assert_not_called()

    def test_complete_map_passes_without_touching_kite(self):
        self.write_map(FULL_MAP)
        kite = self._kite(NSE_INSTRUMENTS)
        stats = self.cdb.CentralDataBackfill(kite).run_backfill()
        kite.instruments.assert_not_called()
        self.assertTrue(stats['complete'])
        self.notifier.send_message.assert_not_called()


class IntradayBackfillTest(TempProjectDir):

    def test_short_map_aborts_with_exit_3(self):
        import backfill_intraday_candles as bic
        self.write_map(STALE_MAP)
        with mock.patch.object(sys, 'argv', ['bic', '--db', 'x.db', '--dry-run']), \
             self.assertLogs(itm.logger, level='ERROR'):
            self.assertEqual(bic.main(), 3)
        self.assertFalse(os.path.exists('x.db'))
        self.notifier.send_message.assert_not_called()  # dry run: no alert

    def test_short_map_alerts_when_not_dry_run(self):
        import backfill_intraday_candles as bic
        self.write_map(STALE_MAP)
        with mock.patch.object(sys, 'argv', ['bic', '--db', 'x.db']), \
             self.assertLogs(itm.logger, level='ERROR'):
            self.assertEqual(bic.main(), 3)
        self.assertFalse(os.path.exists('x.db'))
        self.notifier.send_message.assert_called_once()

    def test_complete_map_dry_run_plans_every_symbol(self):
        import backfill_intraday_candles as bic
        import io
        from contextlib import redirect_stdout
        self.write_map(FULL_MAP)
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['bic', '--db', 'x.db', '--dry-run']), \
             redirect_stdout(out):
            self.assertEqual(bic.main(), 0)
        self.assertIn('symbols         3 of 4 requested', out.getvalue())


if __name__ == '__main__':
    unittest.main()
