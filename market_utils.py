from datetime import datetime, time, date
import pytz
import config

# NSE Holidays for 2025
# Source: https://www.nseindia.com/regulations/trading-holidays
NSE_HOLIDAYS_2025 = [
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
]

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
    """
    if check_date is None:
        check_date = get_current_ist_time().date()

    return check_date in NSE_HOLIDAYS_2025

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
