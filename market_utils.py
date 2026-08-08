from datetime import datetime, time, date, timedelta
import pytz
import config
import logging

logger = logging.getLogger(__name__)

# NSE Holidays by Year
# Source: https://www.nseindia.com/regulations/trading-holidays
# NOTE: Update this dictionary at the end of each year with next year's holidays

NSE_HOLIDAYS = {
    2025: [
        date(2025, 1, 26),   # Republic Day
        date(2025, 3, 14),   # Holi
        date(2025, 3, 31),   # Id-Ul-Fitr
        date(2025, 4, 10),   # Mahavir Jayanti
        date(2025, 4, 14),   # Dr. Ambedkar Jayanti
        date(2025, 4, 18),   # Good Friday
        date(2025, 5, 1),    # Maharashtra Day
        date(2025, 6, 7),    # Id-Ul-Adha (Bakri Id)
        date(2025, 8, 15),   # Independence Day
        date(2025, 8, 27),   # Ganesh Chaturthi
        date(2025, 10, 2),   # Mahatma Gandhi Jayanti
        date(2025, 10, 21),  # Dussehra
        date(2025, 11, 5),   # Diwali (Laxmi Pujan)
        date(2025, 11, 6),   # Diwali-Balipratipada
        date(2025, 11, 24),  # Gurunanak Jayanti
        date(2025, 12, 25),  # Christmas
    ],
    2026: [
        date(2026, 1, 15),   # Municipal Corporation Elections (Maharashtra)
        date(2026, 1, 26),   # Republic Day
        date(2026, 3, 3),    # Holi
        date(2026, 3, 26),   # Shri Ram Navami
        date(2026, 3, 31),   # Shri Mahavir Jayanti
        date(2026, 4, 3),    # Good Friday
        date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
        date(2026, 5, 1),    # Maharashtra Day
        date(2026, 5, 28),   # Bakri Id (Id-Ul-Adha)
        date(2026, 6, 26),   # Muharram
        date(2026, 9, 14),   # Ganesh Chaturthi
        date(2026, 10, 2),   # Mahatma Gandhi Jayanti
        date(2026, 10, 20),  # Dussehra
        date(2026, 11, 10),  # Diwali-Balipratipada
        date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
        date(2026, 12, 25),  # Christmas
    ],
    # TODO: Add 2027 holidays when NSE publishes the list (usually in December)
}

def get_current_ist_time() -> datetime:
    """Get current time in IST timezone"""
    ist = pytz.timezone(config.MARKET_TIMEZONE)
    return datetime.now(ist)

def is_nse_holiday(check_date: date = None) -> bool:
    """
    Check if given date is an NSE holiday

    Args:
        check_date: Date to check (defaults to today)

    Returns:
        True if NSE holiday, False otherwise

    Note:
        If holiday list for the year is not available, logs warning and assumes NOT a holiday.
        This ensures trading continues even if list is outdated (safer than blocking all trading).
    """
    if check_date is None:
        check_date = get_current_ist_time().date()

    year = check_date.year

    # Check if we have holiday list for this year
    if year not in NSE_HOLIDAYS:
        logger.warning(f"⚠️ NSE holiday list for {year} not available in market_utils.py!")
        logger.warning(f"⚠️ Assuming {check_date.strftime('%Y-%m-%d')} is NOT a holiday")
        logger.warning(f"⚠️ Update NSE_HOLIDAYS dict in market_utils.py with {year} holidays")
        logger.warning(f"⚠️ Source: https://www.nseindia.com/regulations/trading-holidays")
        return False  # Assume NOT a holiday if list missing (safer for trading)

    return check_date in NSE_HOLIDAYS[year]

def check_holiday_list_status() -> dict:
    """
    Check if holiday lists are up-to-date and warn if missing

    Returns:
        dict with status information
    """
    current_time = get_current_ist_time()
    current_year = current_time.year
    next_year = current_year + 1
    current_month = current_time.month

    status = {
        'current_year_available': current_year in NSE_HOLIDAYS,
        'next_year_available': next_year in NSE_HOLIDAYS,
        'needs_update': False,
        'warning_message': None
    }

    # If it's November or December, check if next year's list is ready
    if current_month >= 11:
        if next_year not in NSE_HOLIDAYS:
            status['needs_update'] = True
            status['warning_message'] = (
                f"⚠️ WARNING: NSE holiday list for {next_year} not yet added!\n"
                f"⚠️ Current month: {current_time.strftime('%B %Y')}\n"
                f"⚠️ Action needed: Update NSE_HOLIDAYS dict in market_utils.py\n"
                f"⚠️ Source: https://www.nseindia.com/regulations/trading-holidays\n"
                f"⚠️ Add {next_year} holidays before January 1st to avoid monitoring failures"
            )
            logger.warning(status['warning_message'])

    # If current year's list is missing
    if current_year not in NSE_HOLIDAYS:
        status['needs_update'] = True
        status['warning_message'] = (
            f"🚨 CRITICAL: NSE holiday list for {current_year} is MISSING!\n"
            f"🚨 System will treat all days as trading days (incorrect behavior)\n"
            f"🚨 URGENT: Update NSE_HOLIDAYS dict in market_utils.py immediately\n"
            f"🚨 Source: https://www.nseindia.com/regulations/trading-holidays"
        )
        logger.error(status['warning_message'])

    return status

def is_trading_day() -> bool:
    """
    Check if today is a trading day (Monday-Friday, excluding NSE holidays)
    """
    current_time = get_current_ist_time()
    current_date = current_time.date()

    # Check if weekend (Saturday=5, Sunday=6)
    if current_time.weekday() >= 5:
        return False

    # Check if NSE holiday
    if is_nse_holiday(current_date):
        return False

    return True

# NIFTY weekly expiry moved from Thursday to Tuesday. Both dates are observed, not assumed:
# the last Thursday expiry is 2025-08-28 and the first Tuesday expiry is 2025-09-02, confirmed
# against each date's own NSE F&O bhavcopy across 263 expiries (2021-07-29 .. 2026-08-04).
# SEBI's 2025 circular made each exchange pick Tuesday or Thursday; NSE took Tuesday effective
# 2025-09-01, which was a Monday.
LAST_THURSDAY_WEEKLY_EXPIRY = date(2025, 8, 28)

_THURSDAY = 3
_TUESDAY = 1


def get_next_weekly_expiry(from_date: date) -> date:
    """
    Resolve the next NIFTY weekly expiry strictly after from_date.

    The rule, derived from 263 expiries confirmed against NSE's own F&O contract records:

    1. Era weekday -- Thursday for expiries up to and including 2025-08-28, Tuesday from
       2025-09-02 onward.
    2. Take the next occurrence of that weekday after from_date.
    3. If that day is not a trading session, walk BACKWARD to the previous one. Every one of
       the 14 observed deviations in five years was a one-day shift back, never forward.
    4. A shift moves only that week's expiry; the cycle stays anchored on the era weekday.
       So if the walk-back lands on or before from_date -- which is what happens when
       from_date IS a shifted expiry -- the answer is the following era weekday, giving the
       8-day gap back onto the normal cycle that every observed deviation shows.

    Args:
        from_date: date (or datetime) to resolve from; the result is strictly after it

    Returns:
        Expiry date

    KNOWN LIMITATIONS -- real, and deliberately not engineered around:

    * Muhurat sessions. 2 of the 14 observed deviations (2021-11-03 and 2025-10-20) shifted
      even though the era weekday WAS a session: it was the ~1-hour ceremonial Diwali Muhurat
      session (13-17% of median volume) and NSE moved expiry to the previous full session.
      A holiday-table-based resolver cannot see that, so it gets those weeks wrong unless the
      table happens to list the day as a holiday. That is 2 dates out of 263.

    * Correctness depends entirely on NSE_HOLIDAYS above, which covers 2025 and 2026 only.
      For any other year is_nse_holiday() returns False meaning "not a holiday", so this
      resolver silently stops shifting for holidays -- before 2025 and from 2027-01-01. The
      2027 gap is tracked separately; do not read an unshifted pre-2025 date as verified.
    """
    if isinstance(from_date, datetime):
        from_date = from_date.date()

    candidate = _next_weekday(from_date, _THURSDAY)
    if candidate > LAST_THURSDAY_WEEKLY_EXPIRY:
        candidate = _next_weekday(from_date, _TUESDAY)

    while True:
        # Walk back to the previous session if the era weekday is not one
        expiry = candidate
        while expiry.weekday() >= 5 or is_nse_holiday(expiry):
            expiry -= timedelta(days=1)

        if expiry > from_date:
            return expiry

        # from_date was itself a shifted expiry: the cycle resumes on the era weekday
        candidate += timedelta(days=7)


def _next_weekday(from_date: date, weekday: int) -> date:
    """Next occurrence of weekday strictly after from_date"""
    days_ahead = (weekday - from_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return from_date + timedelta(days=days_ahead)


def is_market_hours() -> bool:
    """
    Check if current time is within market hours (9:25 AM - 3:25 PM IST)
    NSE trading: 9:15 AM - 3:30 PM (we start monitoring at 9:25 AM for market stabilization)
    """
    current_time = get_current_ist_time()
    current_time_only = current_time.time()

    market_start = time(config.MARKET_START_HOUR, config.MARKET_START_MINUTE)
    market_end = time(config.MARKET_END_HOUR, config.MARKET_END_MINUTE)

    return market_start <= current_time_only <= market_end

def is_market_open() -> bool:
    """
    Check if market is currently open (trading day + market hours)
    """
    return is_trading_day() and is_market_hours()

def get_market_status() -> dict:
    """
    Get detailed market status information

    Returns:
        dict with keys: is_open, is_trading_day, is_market_hours, current_time
    """
    current_time = get_current_ist_time()
    trading_day = is_trading_day()
    market_hours = is_market_hours()

    return {
        "is_open": trading_day and market_hours,
        "is_trading_day": trading_day,
        "is_market_hours": market_hours,
        "current_time": current_time.strftime("%Y-%m-%d %H:%M:%S %Z")
    }
