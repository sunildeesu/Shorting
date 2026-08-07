#!/usr/bin/env python3
"""
Regression test: NIFTY weekly expiry is resolved from the observed calendar, not "next Thursday".

Three sites in this repo computed weekly expiry as `(3 - weekday) % 7`. That has been wrong
since 2025-09-02, when NSE moved weekly expiry from Thursday to Tuesday, and it was never
right for holiday-shifted weeks. market_utils.get_next_weekly_expiry() replaced all three.

Every date asserted here is one of the 263 expiries confirmed against its own day's NSE F&O
bhavcopy (2021-07-29 .. 2026-08-04), not taken from a holiday list or a blog. The contract:

  1. era weekday   -- Thursday through 2025-08-28, Tuesday from 2025-09-02
  2. next occurrence of that weekday, strictly after the given date
  3. if that day is not a session, walk BACKWARD -- all 14 observed deviations shifted back

The two documented limitations of the resolver are asserted here too, so that the wrong
answers are visible and intentional rather than an unexamined bug.

Runs offline: no broker, no network, no credentials.
"""

import os
import sys
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_utils
from market_utils import get_next_weekly_expiry


class EraWeekdayTest(unittest.TestCase):
    """The Thursday -> Tuesday change, at its exact boundary"""

    def test_thursday_era_resolves_to_thursday(self):
        # 2025-08-28 is the LAST Thursday expiry
        self.assertEqual(get_next_weekly_expiry(date(2025, 8, 25)), date(2025, 8, 28))
        self.assertEqual(get_next_weekly_expiry(date(2025, 8, 25)).weekday(), 3)

    def test_tuesday_era_resolves_to_tuesday(self):
        # 2025-09-02 is the FIRST Tuesday expiry (2025-09-01 was a Monday)
        self.assertEqual(get_next_weekly_expiry(date(2025, 9, 1)), date(2025, 9, 2))
        self.assertEqual(get_next_weekly_expiry(date(2025, 9, 1)).weekday(), 1)

    def test_switch_week_is_a_five_day_gap(self):
        """2025-08-28 -> 2025-09-02 is the only 5-day gap in five years"""
        expiry = get_next_weekly_expiry(date(2025, 8, 28))
        self.assertEqual(expiry, date(2025, 9, 2))
        self.assertEqual((expiry - date(2025, 8, 28)).days, 5)

    def test_naive_thursday_rule_would_have_missed_the_switch(self):
        """The old arithmetic would have said 2025-09-04 for the switch week"""
        naive = date(2025, 8, 28) + timedelta(days=7)
        self.assertEqual(naive, date(2025, 9, 4))
        self.assertNotEqual(get_next_weekly_expiry(date(2025, 8, 28)), naive)

    def test_accepts_datetime_as_well_as_date(self):
        self.assertEqual(
            get_next_weekly_expiry(datetime(2025, 9, 1, 10, 5)), date(2025, 9, 2)
        )


class PlainWeekTest(unittest.TestCase):
    """Unshifted weeks in each era resolve to the plain era weekday"""

    def test_thursday_era_plain_week(self):
        # 2022-02-17 -> 2022-02-24, both confirmed expiries, no holiday between
        self.assertEqual(get_next_weekly_expiry(date(2022, 2, 17)), date(2022, 2, 24))

    def test_tuesday_era_plain_week(self):
        # 2026-07-28 and 2026-08-04 are confirmed expiries with no shift
        self.assertEqual(get_next_weekly_expiry(date(2026, 7, 21)), date(2026, 7, 28))
        self.assertEqual(get_next_weekly_expiry(date(2026, 7, 28)), date(2026, 8, 4))


class HolidayShiftTest(unittest.TestCase):
    """A non-session era weekday shifts the expiry BACK one session, never forward"""

    def test_tuesday_era_shift(self):
        """2026-03-03 (Holi) is not a session, so the expiry is Monday 2026-03-02"""
        expiry = get_next_weekly_expiry(date(2026, 2, 24))
        self.assertEqual(expiry, date(2026, 3, 2))
        self.assertEqual(expiry.weekday(), 0)  # Monday

    def test_thursday_era_shift(self):
        """
        2023-06-29 (Bakri Id) is not a session, so the expiry is Wednesday 2023-06-28.

        This is also the one expiry NSE RELABELLED after listing: the 2023-06-22 bhavcopy
        still advertised 2023-06-29, and only that week's own file shows 2023-06-28.

        NSE_HOLIDAYS covers 2025-2026 only, so 2023's holidays are injected here. That is
        the point of the companion test below -- without a table the resolver cannot shift.
        """
        with patch.dict(market_utils.NSE_HOLIDAYS, {2023: [date(2023, 6, 29)]}):
            expiry = get_next_weekly_expiry(date(2023, 6, 22))
            self.assertEqual(expiry, date(2023, 6, 28))
            self.assertEqual(expiry.weekday(), 2)  # Wednesday

    def test_shifted_week_is_followed_by_an_eight_day_gap(self):
        """
        A shift moves one week's expiry, not the cycle. Resolving FROM a shifted expiry must
        not hand back that same date again: 2026-03-02 -> 2026-03-10, and 2026-03-30 ->
        2026-04-07, both confirmed consecutive expiries.
        """
        self.assertEqual(get_next_weekly_expiry(date(2026, 3, 2)), date(2026, 3, 10))
        self.assertEqual((date(2026, 3, 10) - date(2026, 3, 2)).days, 8)

        self.assertEqual(get_next_weekly_expiry(date(2026, 3, 30)), date(2026, 4, 7))
        self.assertEqual(get_next_weekly_expiry(date(2026, 4, 7)), date(2026, 4, 13))

    def test_shift_is_always_backward(self):
        """
        Across a whole year of the Tuesday era, no expiry ever lands later than Tuesday --
        a forward shift would show up as a Wednesday, Thursday or Friday -- and none lands
        on a non-session.
        """
        day = date(2026, 1, 1)
        while day < date(2027, 1, 1):
            expiry = get_next_weekly_expiry(day)
            self.assertLessEqual(expiry.weekday(), 1, f"{day} -> {expiry} shifted forward")
            self.assertFalse(market_utils.is_nse_holiday(expiry))
            day += timedelta(days=1)


class ConfirmedCalendarTest(unittest.TestCase):
    """
    Walk the resolver against the confirmed 2026 expiry chain.

    These 28 dates each came from that date's own NSE F&O bhavcopy. Three of them
    (2026-03-02, 2026-03-30, 2026-04-13) are holiday shifts off Tuesday.
    """

    CONFIRMED_2026 = [
        date(2026, 1, 27), date(2026, 2, 3), date(2026, 2, 10), date(2026, 2, 17),
        date(2026, 2, 24), date(2026, 3, 2), date(2026, 3, 10), date(2026, 3, 17),
        date(2026, 3, 24), date(2026, 3, 30), date(2026, 4, 7), date(2026, 4, 13),
        date(2026, 4, 21), date(2026, 4, 28), date(2026, 5, 5), date(2026, 5, 12),
        date(2026, 5, 19), date(2026, 5, 26), date(2026, 6, 2), date(2026, 6, 9),
        date(2026, 6, 16), date(2026, 6, 23), date(2026, 6, 30), date(2026, 7, 7),
        date(2026, 7, 14), date(2026, 7, 21), date(2026, 7, 28), date(2026, 8, 4),
    ]

    def test_resolver_reproduces_the_confirmed_chain(self):
        walked = []
        cursor = date(2026, 1, 20)
        for _ in self.CONFIRMED_2026:
            cursor = get_next_weekly_expiry(cursor)
            walked.append(cursor)
        self.assertEqual(walked, self.CONFIRMED_2026)


class DocumentedLimitationTest(unittest.TestCase):
    """
    Both known limitations, asserted so they cannot pass for correct by accident.

    Neither is a bug to fix here: see the docstring on get_next_weekly_expiry().
    """

    def test_holiday_table_gap_means_no_shift(self):
        """
        LIMITATION: NSE_HOLIDAYS holds 2025 and 2026 only. Outside those years
        is_nse_holiday() returns False meaning "not a holiday", so the resolver silently
        stops shifting -- both before 2025 and from 2027-01-01.

        Unpatched, the 2023 Bakri Id week above resolves to 2023-06-29, which was not a
        trading day at all. This is the documented-wrong answer.
        """
        self.assertNotIn(2023, market_utils.NSE_HOLIDAYS)
        self.assertEqual(get_next_weekly_expiry(date(2023, 6, 22)), date(2023, 6, 29))

    def test_muhurat_session_is_not_detected(self):
        """
        LIMITATION: 2 of the 14 observed deviations shifted even though the era weekday WAS
        a session -- the ~1-hour ceremonial Diwali Muhurat session (13-17% of median
        volume). NSE moved expiry to the previous full session; a holiday table cannot see
        that, and no Muhurat detection was built.

        2021-11-04 traded as a Muhurat session, so it is absent from any holiday list. The
        true expiry was 2021-11-03 (Wed). The resolver answers 2021-11-04. Wrong, on purpose.
        """
        with patch.dict(market_utils.NSE_HOLIDAYS, {2021: []}):
            self.assertEqual(get_next_weekly_expiry(date(2021, 10, 28)), date(2021, 11, 4))
            self.assertNotEqual(get_next_weekly_expiry(date(2021, 10, 28)), date(2021, 11, 3))

    def test_the_other_muhurat_week_happens_to_resolve_correctly(self):
        """
        The second Muhurat deviation, 2025-10-20, comes out right -- but not because
        Muhurat is understood. NSE publishes 2025-10-21 (Dussehra) as a trading holiday
        with a separate Muhurat session, so it IS in NSE_HOLIDAYS and the ordinary
        walk-back applies. 2021-11-04 was not published that way, hence the test above.
        """
        self.assertIn(date(2025, 10, 21), market_utils.NSE_HOLIDAYS[2025])
        self.assertEqual(get_next_weekly_expiry(date(2025, 10, 14)), date(2025, 10, 20))


if __name__ == '__main__':
    unittest.main(verbosity=2)
