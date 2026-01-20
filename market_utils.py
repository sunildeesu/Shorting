from datetime import datetime, time, date
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
