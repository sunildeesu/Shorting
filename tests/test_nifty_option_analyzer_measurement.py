#!/usr/bin/env python3
"""
Regression tests: nifty_option_analyzer must measure what it records.

Two live defects are pinned here.

1. Monthly-expiry symbols were built in the weekly format. NSE uses two different
   conventions for NIFTY options, verified against the exchange's own F&O bhavcopy
   for 2026-08-05:

       weekly   NIFTY2681125700CE   expiry 2026-08-11   NIFTY{YY}{M}{DD}{strike}{CE|PE}
       monthly  NIFTY26AUG25350CE   expiry 2026-08-25   NIFTY{YY}{MMM}{strike}{CE|PE}

   Building every symbol in the weekly form produced NIFTY2672824250CE on
   2026-07-20 where the listed contract was NIFTY26JUL24250CE. The quote came back
   empty, the handler returned a silent 0, and the monitor recorded an ENTERED
   position at premium 0 for a straddle actually worth 358.80.
   The contract pinned: symbols are resolved against the exchange instrument list,
   and a quote that carries no premium is refused rather than zeroed - a failed
   lookup can never reach the recording path as a real trade.

2. Greeks were always computed at a hardcoded 20% IV, because Kite's quote()
   returns neither `greeks` nor `implied_volatility`. Theta, gamma and vega carry
   55% of the composite score, so every Greek-based score in the log was scored off
   a constant. The contract pinned: IV is recovered from the observed premium by
   inverting Black-Scholes, and a premium no volatility can explain is reported as
   unavailable, never defaulted.

Decision logic is deliberately NOT exercised here - these tests are about
measurement and recording only.

Runs offline: no broker, no credentials, no network, nothing written under data/.
"""

import os
import sys
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nifty_option_analyzer as noa
from nifty_option_analyzer import (
    GreeksUnavailable,
    NiftyOptionAnalyzer,
    OptionQuoteUnavailable,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Real contracts, read out of the NSE F&O bhavcopy for 2026-08-05.
WEEKLY_EXPIRY = date(2026, 8, 11)
MONTHLY_EXPIRY = date(2026, 8, 25)

BHAVCOPY_INSTRUMENTS = [
    {'name': 'NIFTY', 'instrument_type': 'CE', 'expiry': WEEKLY_EXPIRY,
     'strike': 25700.0, 'tradingsymbol': 'NIFTY2681125700CE'},
    {'name': 'NIFTY', 'instrument_type': 'PE', 'expiry': WEEKLY_EXPIRY,
     'strike': 25700.0, 'tradingsymbol': 'NIFTY2681125700PE'},
    {'name': 'NIFTY', 'instrument_type': 'CE', 'expiry': MONTHLY_EXPIRY,
     'strike': 25350.0, 'tradingsymbol': 'NIFTY26AUG25350CE'},
    {'name': 'NIFTY', 'instrument_type': 'PE', 'expiry': MONTHLY_EXPIRY,
     'strike': 25350.0, 'tradingsymbol': 'NIFTY26AUG25350PE'},
    # A same-strike, same-expiry BANKNIFTY contract, to prove the underlying is matched
    {'name': 'BANKNIFTY', 'instrument_type': 'CE', 'expiry': MONTHLY_EXPIRY,
     'strike': 25350.0, 'tradingsymbol': 'BANKNIFTY26AUG25350CE'},
]


def as_datetime(day):
    return datetime.combine(day, datetime.min.time())


def bare_analyzer(instruments=BHAVCOPY_INSTRUMENTS):
    """
    An analyzer with only the attributes these tests touch.

    __init__ builds a regime detector, an API coordinator and the central quote DB;
    none of that is needed to test symbol resolution or Black-Scholes.
    """
    analyzer = NiftyOptionAnalyzer.__new__(NiftyOptionAnalyzer)
    analyzer._nfo_instruments = list(instruments)
    analyzer._instruments_cache_time = datetime.now()
    return analyzer


class SymbolResolutionTest(unittest.TestCase):
    """Both NSE conventions must resolve to the symbol the exchange actually lists."""

    def setUp(self):
        self.analyzer = bare_analyzer()

    def test_weekly_expiry_resolves_to_weekly_symbol(self):
        symbol = self.analyzer._resolve_option_symbol('CE', as_datetime(WEEKLY_EXPIRY), 25700)
        self.assertEqual(symbol, 'NFO:NIFTY2681125700CE')

    def test_monthly_expiry_resolves_to_monthly_symbol(self):
        """The regression: the weekly format would give NIFTY2682525350CE, which is unlisted."""
        symbol = self.analyzer._resolve_option_symbol('CE', as_datetime(MONTHLY_EXPIRY), 25350)
        self.assertEqual(symbol, 'NFO:NIFTY26AUG25350CE')
        self.assertNotIn('82525350', symbol)

    def test_put_side_resolves_independently(self):
        self.assertEqual(
            self.analyzer._resolve_option_symbol('PE', as_datetime(MONTHLY_EXPIRY), 25350),
            'NFO:NIFTY26AUG25350PE'
        )

    def test_accepts_a_plain_date_expiry(self):
        self.assertEqual(
            self.analyzer._resolve_option_symbol('CE', MONTHLY_EXPIRY, 25350),
            'NFO:NIFTY26AUG25350CE'
        )

    def test_other_underlyings_are_not_matched(self):
        analyzer = bare_analyzer([BHAVCOPY_INSTRUMENTS[-1]])  # BANKNIFTY only
        with self.assertRaises(OptionQuoteUnavailable):
            analyzer._resolve_option_symbol('CE', as_datetime(MONTHLY_EXPIRY), 25350)

    def test_unlisted_contract_refuses_instead_of_guessing(self):
        with self.assertRaises(OptionQuoteUnavailable):
            self.analyzer._resolve_option_symbol('CE', as_datetime(MONTHLY_EXPIRY), 99999)


class FailedQuoteTest(unittest.TestCase):
    """A quote that carries no premium must never become a recorded position."""

    def test_missing_quote_is_refused(self):
        with self.assertRaises(OptionQuoteUnavailable):
            NiftyOptionAnalyzer._require_premium('NFO:NIFTY26AUG25350CE', {})

    def test_zero_last_price_is_refused(self):
        with self.assertRaises(OptionQuoteUnavailable):
            NiftyOptionAnalyzer._require_premium('NFO:NIFTY26AUG25350CE', {'last_price': 0})

    def test_batch_fetch_refuses_when_a_leg_has_no_quote(self):
        analyzer = bare_analyzer()
        analyzer.coordinator = mock.Mock()
        # The failure mode of 2026-07-20: the API answers, with nothing in it.
        analyzer.coordinator.get_multiple_instruments.return_value = {}

        with self.assertRaises(OptionQuoteUnavailable):
            analyzer._get_options_batch(
                expiry=as_datetime(MONTHLY_EXPIRY),
                straddle_strikes={'call': 25350, 'put': 25350},
                strangle_strikes={'call': 25350, 'put': 25350},
                nifty_spot=25340.0
            )

    def test_batch_fetch_does_not_fall_back_to_individual_calls(self):
        """The individual-call fallback exists for transport failures, not for empty quotes."""
        analyzer = bare_analyzer()
        analyzer.coordinator = mock.Mock()
        analyzer.coordinator.get_multiple_instruments.return_value = {
            'NFO:NIFTY26AUG25350CE': {'last_price': 0}
        }

        with mock.patch.object(analyzer, '_get_option_data') as individual:
            with self.assertRaises(OptionQuoteUnavailable):
                analyzer._get_options_batch(
                    expiry=as_datetime(MONTHLY_EXPIRY),
                    straddle_strikes={'call': 25350, 'put': 25350},
                    strangle_strikes={'call': 25350, 'put': 25350},
                    nifty_spot=25340.0
                )
        individual.assert_not_called()


class ImpliedVolatilityTest(unittest.TestCase):
    """Greeks must come from the market, or be reported unavailable."""

    def setUp(self):
        self.analyzer = bare_analyzer()
        # Eight days out, so the test does not depend on the calendar.
        self.expiry = as_datetime(date.today() + timedelta(days=8))
        # The real 2026-07-20 ATM call: spot 24243.90, 24250 CE at 184.30.
        self.spot = 24243.90
        self.strike = 24250
        self.premium = 184.30

    def test_iv_is_recovered_from_the_observed_premium(self):
        iv = self.analyzer._implied_volatility(
            'CE', self.spot, self.strike, self.expiry, self.premium
        )
        # ~11.8%, in line with the ~11% ATM IV the exchange's own settlement
        # prices imply for this period - not the hardcoded 20%.
        self.assertAlmostEqual(iv, 0.1176, places=3)

    def test_recovered_iv_reprices_the_observed_premium(self):
        iv = self.analyzer._implied_volatility(
            'CE', self.spot, self.strike, self.expiry, self.premium
        )
        repriced = self.analyzer._bs_price(
            'CE', self.spot, self.strike, self.analyzer._time_to_expiry(self.expiry), iv
        )
        self.assertAlmostEqual(repriced, self.premium, places=2)

    def test_greeks_differ_materially_from_the_old_hardcoded_20_percent(self):
        measured = self.analyzer._greeks_from_premium(
            'CE', self.spot, self.strike, self.expiry, self.premium
        )
        defaulted = self.analyzer._approximate_greeks(
            'CE', self.spot, self.strike, self.expiry, iv=0.20
        )

        # The constant halves gamma and inflates theta by ~57%; both feed the score.
        self.assertGreater(measured['gamma'], defaulted['gamma'] * 1.5)
        self.assertLess(abs(measured['theta']), abs(defaulted['theta']) * 0.8)

    def test_greeks_carry_the_iv_they_were_measured_at(self):
        greeks = self.analyzer._greeks_from_premium(
            'CE', self.spot, self.strike, self.expiry, self.premium
        )
        self.assertAlmostEqual(greeks['implied_vol'], 0.1176, places=3)

    def test_put_iv_is_recovered_independently_of_the_call(self):
        call_iv = self.analyzer._greeks_from_premium(
            'CE', self.spot, self.strike, self.expiry, 184.30
        )['implied_vol']
        put_iv = self.analyzer._greeks_from_premium(
            'PE', self.spot, self.strike, self.expiry, 174.50
        )['implied_vol']
        self.assertNotAlmostEqual(call_iv, put_iv, places=3)

    def test_premium_below_intrinsic_is_unmeasurable(self):
        # A deep-ITM call quoted at 5.0 is worth far more than that intrinsically;
        # no volatility explains it.
        self.assertIsNone(
            self.analyzer._implied_volatility('CE', self.spot, 20000, self.expiry, 5.0)
        )

    def test_unmeasurable_premium_reports_greeks_unavailable(self):
        with self.assertRaises(GreeksUnavailable):
            self.analyzer._greeks_from_premium('CE', self.spot, 20000, self.expiry, 5.0)

    def test_no_silent_default_iv_anywhere(self):
        """Whatever fails, nothing may come back priced at the old 20% constant."""
        with self.assertRaises(GreeksUnavailable):
            self.analyzer._greeks_from_premium('CE', self.spot, self.strike, self.expiry, 0.0)


class EndToEndRecordingTest(unittest.TestCase):
    """
    Drive analyze_option_selling_opportunity far enough to prove the recording path.

    nifty_option_monitor records an entry only on `signal == 'SELL'` and returns
    early when the result carries an 'error' key, so those two assertions are the
    behavioural statement of "a failed quote cannot become an ENTERED position".
    """

    def build_analyzer(self, quotes):
        expiry = date.today() + timedelta(days=8)
        analyzer = bare_analyzer([
            {'name': 'NIFTY', 'instrument_type': 'CE', 'expiry': expiry,
             'strike': 24250.0, 'tradingsymbol': 'NIFTY26AUG24250CE'},
            {'name': 'NIFTY', 'instrument_type': 'PE', 'expiry': expiry,
             'strike': 24250.0, 'tradingsymbol': 'NIFTY26AUG24250PE'},
            {'name': 'NIFTY', 'instrument_type': 'CE', 'expiry': expiry,
             'strike': 24350.0, 'tradingsymbol': 'NIFTY26AUG24350CE'},
            {'name': 'NIFTY', 'instrument_type': 'PE', 'expiry': expiry,
             'strike': 24150.0, 'tradingsymbol': 'NIFTY26AUG24150PE'},
        ])
        analyzer.coordinator = mock.Mock()
        analyzer.coordinator.get_multiple_instruments.side_effect = \
            lambda symbols, **kw: {s: quotes.get(s, {}) for s in symbols}
        analyzer.regime_detector = mock.Mock()
        analyzer.regime_detector.get_market_regime.return_value = 'NEUTRAL'

        passed = {'passed': True, 'reason': ''}
        patches = {
            '_get_spot_indices_batch': {'nifty_spot': 24243.90, 'india_vix': 13.2},
            '_get_vix_trend': 0.0,
            '_calculate_iv_rank': 60.0,
            '_check_realized_volatility': passed,
            '_check_price_action': passed,
            '_check_intraday_volatility': passed,
            '_calculate_cpr': {},
            '_check_cpr_trend': passed,
            '_get_nifty_oi_analysis': {'pattern': 'LONG_UNWINDING'},
            '_get_next_expiries': [as_datetime(expiry)],
        }
        for name, value in patches.items():
            self.enterContext(mock.patch.object(analyzer, name, return_value=value))
        return analyzer

    def test_failed_quote_yields_an_error_not_a_sell(self):
        analyzer = self.build_analyzer(quotes={})  # every leg comes back empty

        result = analyzer.analyze_option_selling_opportunity(expiry_count=1)

        self.assertIn('error', result)
        self.assertEqual(result['signal'], 'ERROR')
        self.assertNotEqual(result['signal'], 'SELL')

    def test_a_priced_chain_still_produces_a_normal_analysis(self):
        """Guard against over-refusal: real quotes must still score and record."""
        analyzer = self.build_analyzer(quotes={
            'NFO:NIFTY26AUG24250CE': {'last_price': 184.30, 'oi': 100, 'volume': 95699},
            'NFO:NIFTY26AUG24250PE': {'last_price': 174.50, 'oi': 100, 'volume': 72738},
            'NFO:NIFTY26AUG24350CE': {'last_price': 133.05, 'oi': 100, 'volume': 51000},
            'NFO:NIFTY26AUG24150PE': {'last_price': 126.80, 'oi': 100, 'volume': 48000},
        })

        result = analyzer.analyze_option_selling_opportunity(expiry_count=1)

        self.assertNotIn('error', result)
        self.assertNotEqual(result['signal'], 'ERROR')
        straddle = result['expiry_analyses'][0]['straddle']
        self.assertAlmostEqual(straddle['total_premium'], 358.80, places=2)
        self.assertGreater(straddle['greeks']['gamma'], 0)


class NoDataWrittenTest(unittest.TestCase):
    """These tests must not touch the captain's live records."""

    def test_no_data_directory_is_created(self):
        self.assertFalse(
            os.path.isdir(os.path.join(REPO_ROOT, 'data')),
            "tests must not create or write under data/"
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
