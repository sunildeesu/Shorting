from datetime import datetime, time
import pytz
import config

def get_current_ist_time() -> datetime:
    """Get current time in IST timezone"""
    ist = pytz.timezone(config.MARKET_TIMEZONE)
    return datetime.now(ist)

def is_trading_day() -> bool:
    """
    Check if today is a trading day (Monday-Friday)
    Note: Does not account for NSE holidays - only checks weekday
    """
    current_time = get_current_ist_time()
    # Monday = 0, Sunday = 6
    return current_time.weekday() < 5

def is_market_hours() -> bool:
    """
    Check if current time is within market hours (9:30 AM - 3:25 PM IST)
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
