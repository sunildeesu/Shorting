#!/usr/bin/env python3
"""
Regression test: the central data backfill writes rows that mean the same thing
as the live collector's rows.

On 2026-08-31 the machine died at 11:20 and the evening backfill "repaired" the
day. It wrote 192 of 212 symbols and reported `Errors: 0`, and every row it
wrote was in different units from the live rows beside it.

The contract pinned here:

  * `volume` is Kite's CUMULATIVE day volume, as live collection stores it - not
    the per-minute volume the historical candles carry. Writing the candle value
    straight in made the column jump 3,145,936 -> 23,514 at the 11:20 seam and
    silently changed its unit for the rest of the day;
  * `oi` is NULL, not 0. historical_data carries no open interest, and 0 is a
    real OI value that a reader cannot tell apart from a missing one;
  * a symbol with no instrument token is LOUD. The old code returned 0 from
    `backfill_stock_data` with no log and no error counter, so 18 symbols went
    missing for four hours of a session while the run reported success;
  * a token cache that predates symbols now in the F&O universe is refetched,
    not trusted. The cache that caused the incident was written 2025-11-12 and
    had never been reconciled against fo_stocks.json since. The refetch goes
    through instrument_token_map (PR #20), which already knows the index names
    that ride along in fo_stocks.json, so those never count as staleness.

Runs offline: a fake Kite client, no credentials, and a temporary database -
nothing touches data/central_quotes.db.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import central_data_backfill as cdb
from central_quote_db import CentralQuoteDB


# One session's worth of per-minute candles, in the shape kite.historical_data
# returns them: ascending, 'volume' is that minute's traded quantity alone.
def _candles(day, minutes, per_minute_volume=100):
    out = []
    for i in range(minutes):
        h, m = divmod(9 * 60 + 15 + i, 60)
        out.append({
            'date': datetime(day.year, day.month, day.day, h, m),
            'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.0 + i,
            'volume': per_minute_volume,
        })
    return out


class FakeKite:
    """Serves candles for known tokens; records what was asked for."""

    def __init__(self, day, minutes=10):
        self.day = day
        self.minutes = minutes
        self.requested_tokens = []
        self.instruments_calls = 0

    def historical_data(self, instrument_token, from_date, to_date, interval):
        self.requested_tokens.append(instrument_token)
        return _candles(self.day, self.minutes)

    def instruments(self, exchange):
        self.instruments_calls += 1
        return [
            {'tradingsymbol': 'AAA', 'instrument_token': 111},
            {'tradingsymbol': 'BBB', 'instrument_token': 222},
            {'tradingsymbol': 'NEWSTOCK', 'instrument_token': 333},
        ]


class CentralDataBackfillSeamTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.day = date(2026, 8, 31)
        self.db_path = os.path.join(self.tmp, 'central_quotes.db')
        self.db = CentralQuoteDB(db_path=self.db_path, mode='writer')

        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        os.makedirs('data', exist_ok=True)

        self._patchers = [
            mock.patch.object(cdb, 'get_central_db_writer', lambda: self.db),
            mock.patch.object(cdb.config, 'STOCK_LIST_FILE', 'fo_stocks.json'),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        os.chdir(self.cwd)
        self.db.close() if hasattr(self.db, 'close') else None

    def _write_universe(self, stocks):
        with open('fo_stocks.json', 'w') as f:
            json.dump({'stocks': stocks}, f)

    def _write_token_cache(self, tokens):
        with open('data/instrument_tokens.json', 'w') as f:
            json.dump(tokens, f)

    def _rows(self, symbol):
        cur = self.db.conn.cursor()
        cur.execute(
            "SELECT timestamp, volume, oi, oi_day_high, oi_day_low "
            "FROM stock_quotes WHERE symbol=? ORDER BY timestamp", (symbol,))
        return cur.fetchall()

    # ---- the seam --------------------------------------------------------

    def test_volume_is_cumulative_not_per_minute(self):
        """Backfilled volume must be the running day total, as live rows are."""
        self._write_universe(['AAA'])
        self._write_token_cache({'AAA': 111})
        kite = FakeKite(self.day, minutes=5)

        backfill = cdb.CentralDataBackfill(kite)
        backfill.backfill_stock_data('AAA', self.day)

        volumes = [r[1] for r in self._rows('AAA')]
        self.assertEqual(volumes, [100, 200, 300, 400, 500],
                         "volume must accumulate across the session, not reset "
                         "to each candle's own per-minute quantity")
        # The property that actually broke: monotonic non-decreasing.
        self.assertEqual(volumes, sorted(volumes))

    def test_backfill_does_not_break_monotonicity_at_the_live_seam(self):
        """The exact 2026-08-31 shape: live morning rows, backfilled afternoon."""
        self._write_universe(['AAA'])
        self._write_token_cache({'AAA': 111})

        # Live collection already stored 09:15-09:17 as cumulative day volume.
        cur = self.db.conn.cursor()
        for i, cum in enumerate([100, 200, 300]):
            cur.execute(
                "INSERT INTO stock_quotes (symbol, timestamp, price, volume, oi,"
                " oi_day_high, oi_day_low, last_updated) VALUES (?,?,?,?,?,?,?,?)",
                ('AAA', f'2026-08-31 09:1{5 + i}:00', 100.0, cum,
                 999, 999, 999, '2026-08-31 09:20:00'))
        self.db.conn.commit()

        kite = FakeKite(self.day, minutes=6)
        backfill = cdb.CentralDataBackfill(kite)
        backfill.backfill_stock_data('AAA', self.day)

        rows = self._rows('AAA')
        volumes = [r[1] for r in rows]
        self.assertEqual(len(rows), 6)
        self.assertEqual(volumes, sorted(volumes),
                         f"volume went backwards at the live/backfill seam: {volumes}")
        # Live rows are preserved (INSERT OR IGNORE), including their real OI.
        self.assertEqual(rows[0][2], 999)

    def test_oi_is_null_not_zero(self):
        """historical_data has no OI; 0 would be indistinguishable from real OI."""
        self._write_universe(['AAA'])
        self._write_token_cache({'AAA': 111})
        backfill = cdb.CentralDataBackfill(FakeKite(self.day, minutes=3))
        backfill.backfill_stock_data('AAA', self.day)

        for ts, volume, oi, oi_high, oi_low in self._rows('AAA'):
            self.assertIsNone(oi, f"{ts}: oi must be NULL, got {oi!r}")
            self.assertIsNone(oi_high)
            self.assertIsNone(oi_low)

    # ---- the silent skip -------------------------------------------------

    def test_stale_token_cache_is_refetched(self):
        """A cache written before NEWSTOCK joined the universe must not be trusted."""
        self._write_universe(['AAA', 'BBB', 'NEWSTOCK'])
        self._write_token_cache({'AAA': 111, 'BBB': 222})  # stale: no NEWSTOCK
        kite = FakeKite(self.day)

        backfill = cdb.CentralDataBackfill(kite)

        self.assertEqual(kite.instruments_calls, 1, "stale cache must trigger a refetch")
        self.assertIn('NEWSTOCK', backfill.instrument_tokens)
        self.assertEqual(backfill.unresolved_symbols, [])

    def test_fresh_cache_is_not_refetched(self):
        self._write_universe(['AAA', 'BBB'])
        self._write_token_cache({'AAA': 111, 'BBB': 222})
        kite = FakeKite(self.day)

        cdb.CentralDataBackfill(kite)

        self.assertEqual(kite.instruments_calls, 0)

    def test_index_symbols_do_not_force_a_refetch_every_run(self):
        """NIFTYNXT50 has no NSE equity token and never will; that is not staleness."""
        self._write_universe(['AAA', 'NIFTYNXT50'])
        self._write_token_cache({'AAA': 111})
        kite = FakeKite(self.day)

        # instrument_token_map._INDEX_SYMBOLS knows the index up front, so no
        # run - not even the first - refetches just because it is missing.
        cdb.CentralDataBackfill(kite)
        cdb.CentralDataBackfill(kite)
        self.assertEqual(kite.instruments_calls, 0)

    def test_unresolved_symbols_are_reported_not_swallowed(self):
        """The 2026-08-31 failure: skipped symbols with Errors: 0 and no log."""
        self._write_universe(['AAA', 'NIFTYNXT50'])
        self._write_token_cache({'AAA': 111})

        backfill = cdb.CentralDataBackfill(FakeKite(self.day))

        self.assertEqual(backfill.unresolved_symbols, ['NIFTYNXT50'],
                         "a symbol the backfill cannot fetch must be named, not "
                         "silently dropped")

    def test_index_symbols_never_pollute_the_shared_token_map(self):
        """A dozen scripts read instrument_tokens.json as {symbol: int}."""
        # NEWSTOCK forces a refetch; the rewritten file must still be pure tokens.
        self._write_universe(['AAA', 'NEWSTOCK', 'NIFTYNXT50'])
        self._write_token_cache({'AAA': 111})
        kite = FakeKite(self.day)
        cdb.CentralDataBackfill(kite)
        self.assertEqual(kite.instruments_calls, 1)

        with open('data/instrument_tokens.json') as f:
            tokens = json.load(f)
        self.assertIn('NEWSTOCK', tokens)
        self.assertNotIn('NIFTYNXT50', tokens)
        for symbol, token in tokens.items():
            self.assertIsInstance(token, int, f"{symbol} is not an int token")


if __name__ == '__main__':
    unittest.main(verbosity=2)
