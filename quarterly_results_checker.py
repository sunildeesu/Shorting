#!/usr/bin/env python3
"""
Quarterly Results Checker

Fetches and caches quarterly results schedule from NSE.
Auto-saves schedule when API works, uses cached schedule if API fails.

Author: Claude Opus 4.5
Date: 2026-02-10
"""

import json
import logging
import os
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class QuarterlyResultsChecker:
    """
    Checks if stocks have quarterly results scheduled.

    - Fetches from NSE API and saves schedule automatically
    - Uses saved schedule if API fails
    - Notifies user when API is down
    """

    def __init__(self, cache_dir: str = "data/results_cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

        # Schedule file - auto-updated when API works
        self.schedule_file = os.path.join(cache_dir, "results_schedule.json")

        # Daily schedule file - saved by date for morning alerts
        # Key insight: NSE removes today's events from API once day starts
        # So we need to save each day's schedule the evening before
        self.daily_schedule_file = os.path.join(cache_dir, "daily_results_{date}.json")

        # In-memory cache for quick lookups
        self._results_today: Set[str] = set()
        self._results_upcoming: Dict[str, str] = {}  # Symbol -> date
        self._last_fetch: Optional[datetime] = None
        self._api_working: bool = True
        self._using_cached_schedule: bool = False

        # NSE API settings
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        # Load saved schedule on startup
        self._load_saved_schedule()

        # Also load today's pre-saved schedule (from evening fetch)
        self._load_daily_schedule()

    def _load_daily_schedule(self):
        """Load today's pre-saved schedule (saved the evening before)."""
        today = datetime.now().strftime('%Y-%m-%d')
        daily_file = self.daily_schedule_file.format(date=today)

        if not os.path.exists(daily_file):
            return

        try:
            with open(daily_file, 'r') as f:
                data = json.load(f)

            symbols = data.get('symbols', [])
            if symbols:
                for symbol in symbols:
                    self._results_today.add(symbol.upper())
                logger.info(f"Loaded pre-saved schedule for {today}: {len(symbols)} stocks with results")

        except Exception as e:
            logger.warning(f"Failed to load daily schedule: {e}")

    def _save_daily_schedule(self, date_str: str, symbols: List[str]):
        """Save scheduled results for a specific date (for morning alert next day)."""
        try:
            daily_file = self.daily_schedule_file.format(date=date_str)
            data = {
                'date': date_str,
                'symbols': sorted(symbols),
                'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source': 'NSE event-calendar'
            }
            with open(daily_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved schedule for {date_str}: {len(symbols)} stocks")
        except Exception as e:
            logger.warning(f"Failed to save daily schedule: {e}")

    def _get_today_cache_path(self) -> str:
        """Get daily cache file path."""
        today = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self.cache_dir, f"daily_cache_{today}.json")

    def _load_saved_schedule(self):
        """Load previously saved schedule from file."""
        if not os.path.exists(self.schedule_file):
            return

        try:
            with open(self.schedule_file, 'r') as f:
                data = json.load(f)

            schedule = data.get('schedule', {})
            last_updated = data.get('last_updated', '')

            today = datetime.now().strftime('%d-%b-%Y')
            today_alt = datetime.now().strftime('%Y-%m-%d')

            self._results_today.clear()
            self._results_upcoming.clear()

            for symbol, date in schedule.items():
                symbol = symbol.upper()
                # Check if today
                if date == today or date == today_alt:
                    self._results_today.add(symbol)
                else:
                    # Check if within 7 days
                    try:
                        result_dt = datetime.strptime(date, '%d-%b-%Y')
                        days_away = (result_dt - datetime.now()).days
                        if 0 <= days_away <= 7:
                            self._results_upcoming[symbol] = date
                        elif days_away < 0:
                            # Past date, skip
                            continue
                    except:
                        try:
                            result_dt = datetime.strptime(date, '%Y-%m-%d')
                            days_away = (result_dt - datetime.now()).days
                            if 0 <= days_away <= 7:
                                self._results_upcoming[symbol] = result_dt.strftime('%d-%b-%Y')
                        except:
                            pass

            if self._results_today or self._results_upcoming:
                logger.info(f"Loaded saved schedule: {len(self._results_today)} today, "
                           f"{len(self._results_upcoming)} upcoming (last updated: {last_updated})")

        except Exception as e:
            logger.warning(f"Failed to load saved schedule: {e}")

    def _save_schedule(self, all_results: Dict[str, str]):
        """Save schedule to file for future use."""
        try:
            data = {
                'schedule': all_results,
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source': 'NSE API'
            }
            with open(self.schedule_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved schedule with {len(all_results)} entries")
        except Exception as e:
            logger.warning(f"Failed to save schedule: {e}")

    def fetch_from_nse(self) -> bool:
        """
        Fetch board meetings/results data from NSE.

        Returns True if successful.
        """
        try:
            session = requests.Session()

            # First get cookies from main page
            session.get('https://www.nseindia.com', headers=self.headers, timeout=10)

            # Fetch board meetings
            url = 'https://www.nseindia.com/api/corporate-board-meetings?index=equities'
            response = session.get(url, headers=self.headers, timeout=15)

            if response.status_code != 200:
                raise Exception(f"API returned status {response.status_code}")

            meetings = response.json()

            # Also fetch corporate announcements
            ann_url = 'https://www.nseindia.com/api/corporate-announcements?index=equities'
            ann_response = session.get(ann_url, headers=self.headers, timeout=15)
            announcements = ann_response.json() if ann_response.status_code == 200 else []

            # Preserve daily schedule entries before clearing
            # NSE removes today's events from API once day starts,
            # so we must keep entries loaded from daily_results files
            daily_schedule_symbols = set(self._results_today)

            # Process data
            today = datetime.now().strftime('%d-%b-%Y')
            today_alt = datetime.now().strftime('%Y-%m-%d')

            self._results_today.clear()
            self._results_upcoming.clear()
            all_results = {}  # For saving to file

            # Process board meetings
            for meeting in meetings:
                symbol = meeting.get('bm_symbol', '').strip().upper()
                meeting_date = meeting.get('bm_date', '')
                purpose = meeting.get('bm_purpose', '').lower()
                desc = meeting.get('bm_desc', '').lower()

                if not symbol:
                    continue

                # Check if it's for financial results
                is_results = (
                    'financial result' in purpose or
                    'financial result' in desc or
                    'quarterly' in desc or
                    'quarter ended' in desc or
                    'q3' in desc or 'q2' in desc or 'q1' in desc or 'q4' in desc
                )

                if not is_results:
                    continue

                # Save to schedule
                all_results[symbol] = meeting_date

                # Check if today
                if meeting_date == today:
                    self._results_today.add(symbol)
                else:
                    # Store upcoming (within 7 days)
                    try:
                        meeting_dt = datetime.strptime(meeting_date, '%d-%b-%Y')
                        days_away = (meeting_dt - datetime.now()).days
                        if 0 <= days_away <= 7:
                            self._results_upcoming[symbol] = meeting_date
                    except:
                        pass

            # Process announcements for results already declared today
            for ann in announcements:
                symbol = ann.get('symbol', '').strip().upper()
                desc = ann.get('desc', '').lower()
                ann_date = ann.get('an_dt', '')
                attchmnt_text = ann.get('attchmntText', '').lower()

                if not symbol:
                    continue

                # Check if announcement is from today (format: "11-Feb-2026 12:38:31")
                if today in ann_date or today_alt in ann_date:
                    # Check for results-related announcements
                    is_results = (
                        'financial result' in desc or
                        'quarterly result' in desc or
                        'outcome of board meeting' in desc or  # Common for results announcements
                        'financial result' in attchmnt_text or
                        'quarterly' in attchmnt_text or
                        'q3' in attchmnt_text or 'q2' in attchmnt_text or
                        'q1' in attchmnt_text or 'q4' in attchmnt_text
                    )
                    if is_results:
                        self._results_today.add(symbol)
                        all_results[symbol] = today

            # Restore daily schedule entries that API may have dropped
            # (NSE removes today's events from board-meetings API once day starts)
            for symbol in daily_schedule_symbols:
                if symbol not in self._results_today:
                    self._results_today.add(symbol)
                    logger.debug(f"Restored {symbol} from daily schedule (not in API response)")

            # Save schedule for future use
            self._save_schedule(all_results)

            # Also fetch and save upcoming schedules from event-calendar
            # This ensures we have schedules saved for morning alerts
            self.fetch_and_save_upcoming_days()

            self._api_working = True
            self._using_cached_schedule = False
            self._last_fetch = datetime.now()

            logger.info(f"✅ NSE API: {len(self._results_today)} results today, "
                       f"{len(self._results_upcoming)} upcoming")

            return True

        except Exception as e:
            logger.error(f"❌ NSE API FAILED: {e}")
            self._api_working = False
            self._using_cached_schedule = True

            # Preserve daily schedule entries before loading saved schedule
            daily_schedule_symbols = set(self._results_today)

            # Load from saved schedule
            self._load_saved_schedule()

            # Restore daily schedule entries
            for symbol in daily_schedule_symbols:
                self._results_today.add(symbol)

            self._last_fetch = datetime.now()

            if self._results_today or self._results_upcoming:
                logger.warning(f"⚠️ Using cached schedule: {len(self._results_today)} today, "
                              f"{len(self._results_upcoming)} upcoming")
            else:
                logger.warning("⚠️ No cached schedule available")

            return False

    def fetch_and_save_upcoming_days(self) -> Dict[str, List[str]]:
        """
        Fetch from event-calendar and save schedules for upcoming days.

        NSE removes today's events once the day starts, so we need to
        fetch and save schedules in advance for morning alerts.

        Call this in the evening (after 6 PM) to save tomorrow's schedule.

        Returns:
            Dict of {date: [symbols]} for saved dates
        """
        try:
            session = requests.Session()
            session.get('https://www.nseindia.com', headers=self.headers, timeout=10)

            # Fetch event calendar - has comprehensive results data
            url = 'https://www.nseindia.com/api/event-calendar'
            response = session.get(url, headers=self.headers, timeout=15)

            if response.status_code != 200:
                raise Exception(f"Event calendar API returned {response.status_code}")

            events = response.json()

            # Group by date
            by_date: Dict[str, List[str]] = {}

            for event in events:
                symbol = event.get('symbol', '').strip().upper()
                date = event.get('date', '')
                purpose = event.get('purpose', '').lower()
                desc = event.get('bm_desc', '').lower()

                if not symbol or not date:
                    continue

                # Check if results-related
                is_results = (
                    'financial result' in purpose or
                    'financial result' in desc or
                    'quarterly' in desc or
                    'quarter ended' in desc or
                    'q3' in desc or 'q2' in desc or 'q1' in desc or 'q4' in desc
                )

                if not is_results:
                    continue

                # Convert date format (11-Feb-2026 -> 2026-02-11)
                try:
                    dt = datetime.strptime(date, '%d-%b-%Y')
                    date_key = dt.strftime('%Y-%m-%d')

                    if date_key not in by_date:
                        by_date[date_key] = []
                    if symbol not in by_date[date_key]:
                        by_date[date_key].append(symbol)
                except:
                    pass

            # Save each day's schedule
            for date_key, symbols in by_date.items():
                self._save_daily_schedule(date_key, symbols)

            # Also update upcoming in memory
            today = datetime.now().date()
            for date_key, symbols in by_date.items():
                try:
                    dt = datetime.strptime(date_key, '%Y-%m-%d').date()
                    days_away = (dt - today).days
                    if days_away == 0:
                        for s in symbols:
                            self._results_today.add(s)
                    elif 0 < days_away <= 7:
                        for s in symbols:
                            self._results_upcoming[s] = dt.strftime('%d-%b-%Y')
                except:
                    pass

            logger.info(f"✅ Saved schedules for {len(by_date)} upcoming dates from event-calendar")
            return by_date

        except Exception as e:
            logger.error(f"❌ Failed to fetch event-calendar: {e}")
            return {}

    def refresh_if_needed(self):
        """Refresh data if stale (older than 2 hours or new day)."""
        now = datetime.now()

        if self._last_fetch is None:
            self.fetch_from_nse()
            return

        # Refresh if different day
        if self._last_fetch.date() != now.date():
            self.fetch_from_nse()
            return

        # Refresh if older than 2 hours
        if (now - self._last_fetch).total_seconds() > 7200:
            self.fetch_from_nse()

    def is_api_working(self) -> bool:
        """Check if NSE API is working."""
        return self._api_working

    def is_using_cached_schedule(self) -> bool:
        """Check if using cached schedule due to API failure."""
        return self._using_cached_schedule

    def has_results_today(self, symbol: str) -> bool:
        """Check if a stock has results scheduled today."""
        self.refresh_if_needed()
        return symbol.upper().strip() in self._results_today

    def get_results_date(self, symbol: str) -> Optional[str]:
        """Get the results date for a stock (if within 7 days)."""
        self.refresh_if_needed()
        symbol = symbol.upper().strip()

        if symbol in self._results_today:
            return "TODAY"
        return self._results_upcoming.get(symbol)

    def get_results_info(self, symbol: str) -> Dict:
        """
        Get results information for a stock.

        Returns:
            {
                'has_results': bool,
                'date': str or None,
                'is_today': bool,
                'label': str  # For display in alerts
            }
        """
        self.refresh_if_needed()
        symbol = symbol.upper().strip()

        if symbol in self._results_today:
            return {
                'has_results': True,
                'date': 'TODAY',
                'is_today': True,
                'label': '📊 RESULTS TODAY'
            }

        if symbol in self._results_upcoming:
            date = self._results_upcoming[symbol]
            return {
                'has_results': True,
                'date': date,
                'is_today': False,
                'label': f'📊 Results: {date}'
            }

        return {
            'has_results': False,
            'date': None,
            'is_today': False,
            'label': ''
        }

    def get_all_results_today(self) -> List[str]:
        """Get list of all stocks with results today."""
        self.refresh_if_needed()
        return sorted(list(self._results_today))

    def get_all_upcoming_results(self) -> Dict[str, str]:
        """Get dict of all upcoming results (symbol -> date)."""
        self.refresh_if_needed()
        return dict(self._results_upcoming)

    def get_status(self) -> str:
        """Get current status message for logging/display."""
        if self._api_working:
            return "✅ NSE API working"
        elif self._using_cached_schedule:
            return "⚠️ NSE API down - using cached schedule"
        else:
            return "❌ NSE API down - no cached schedule"

    def get_fno_stocks_with_results_today(self, fno_stocks: List[str]) -> List[str]:
        """
        Get F&O stocks that have results scheduled today.

        Args:
            fno_stocks: List of F&O stock symbols

        Returns:
            List of F&O stocks with results today
        """
        self.refresh_if_needed()
        fno_set = {s.upper() for s in fno_stocks}
        return sorted([s for s in self._results_today if s in fno_set])

    def get_fno_stocks_with_upcoming_results(self, fno_stocks: List[str]) -> Dict[str, str]:
        """
        Get F&O stocks with upcoming results (next 7 days).

        Args:
            fno_stocks: List of F&O stock symbols

        Returns:
            Dict of {symbol: date} for F&O stocks with upcoming results
        """
        self.refresh_if_needed()
        fno_set = {s.upper() for s in fno_stocks}
        return {s: d for s, d in self._results_upcoming.items() if s in fno_set}


def load_fno_stocks() -> List[str]:
    """Load F&O stocks from config file."""
    import config
    try:
        stock_file = config.STOCK_LIST_FILE
        if os.path.exists(stock_file):
            with open(stock_file, 'r') as f:
                data = json.load(f)
                return data.get('stocks', [])
    except Exception as e:
        logger.warning(f"Failed to load F&O stocks: {e}")
    return []


def send_morning_results_alert(telegram_notifier) -> bool:
    """
    Send 9:15 AM alert for F&O stocks with quarterly results today.

    Args:
        telegram_notifier: TelegramNotifier instance

    Returns:
        True if alert sent successfully
    """
    try:
        checker = get_results_checker()
        fno_stocks = load_fno_stocks()

        if not fno_stocks:
            logger.warning("No F&O stocks loaded for results alert")
            return False

        # Get F&O stocks with results today
        results_today = checker.get_fno_stocks_with_results_today(fno_stocks)
        upcoming_results = checker.get_fno_stocks_with_upcoming_results(fno_stocks)

        # Build message
        today_str = datetime.now().strftime('%d-%b-%Y')

        if not results_today and not upcoming_results:
            # No results scheduled - send brief message
            message = (
                f"📊 <b>QUARTERLY RESULTS - {today_str}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"No F&O stocks have results scheduled today.\n\n"
                f"<i>{checker.get_status()}</i>"
            )
        else:
            message = (
                f"📊 <b>QUARTERLY RESULTS - {today_str}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )

            if results_today:
                message += f"🔴 <b>RESULTS TODAY ({len(results_today)} F&O stocks):</b>\n"
                for symbol in results_today:
                    message += f"   • {symbol}\n"
                message += "\n⚠️ <i>Expect high volatility in these stocks!</i>\n\n"

            if upcoming_results:
                message += f"📅 <b>UPCOMING RESULTS:</b>\n"
                # Group by date
                by_date = {}
                for symbol, date in upcoming_results.items():
                    if date not in by_date:
                        by_date[date] = []
                    by_date[date].append(symbol)

                for date in sorted(by_date.keys()):
                    symbols = by_date[date]
                    message += f"   {date}: {', '.join(sorted(symbols))}\n"

            message += f"\n<i>{checker.get_status()}</i>"

        # Send via Telegram
        import requests
        url = f"https://api.telegram.org/bot{telegram_notifier.bot_token}/sendMessage"
        payload = {
            "chat_id": telegram_notifier.channel_id,
            "text": message,
            "parse_mode": "HTML"
        }

        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()

        logger.info(f"Sent morning results alert: {len(results_today)} today, {len(upcoming_results)} upcoming")
        return True

    except Exception as e:
        logger.error(f"Failed to send morning results alert: {e}")
        return False


# Global instance for easy access
_checker_instance: Optional[QuarterlyResultsChecker] = None


def get_results_checker() -> QuarterlyResultsChecker:
    """Get or create the global results checker instance."""
    global _checker_instance
    if _checker_instance is None:
        _checker_instance = QuarterlyResultsChecker()
    return _checker_instance


def has_results_today(symbol: str) -> bool:
    """Quick check if a stock has results today."""
    return get_results_checker().has_results_today(symbol)


def get_results_label(symbol: str) -> str:
    """Get results label for a stock (for use in alerts)."""
    info = get_results_checker().get_results_info(symbol)
    return info['label']


if __name__ == "__main__":
    # Test the checker
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    checker = QuarterlyResultsChecker()

    print(f"\n{'='*60}")
    print("QUARTERLY RESULTS CHECKER")
    print(f"{'='*60}")
    print(f"\nSchedule file: {checker.schedule_file}")
    print("(Auto-updated when NSE API works)\n")

    print("Fetching from NSE API...")
    success = checker.fetch_from_nse()

    print(f"\nStatus: {checker.get_status()}")

    print(f"\n{'='*60}")
    print("STOCKS WITH RESULTS TODAY")
    print(f"{'='*60}")

    today_results = checker.get_all_results_today()
    if today_results:
        for symbol in today_results:
            print(f"  📊 {symbol}")
    else:
        print("  No results scheduled for today")

    print(f"\n{'='*60}")
    print("UPCOMING RESULTS (Next 7 Days)")
    print(f"{'='*60}")

    upcoming = checker.get_all_upcoming_results()
    if upcoming:
        for symbol, date in sorted(upcoming.items(), key=lambda x: x[1]):
            print(f"  {date}: {symbol}")
    else:
        print("  No upcoming results found")

    print(f"\n{'='*60}")

    # Test specific symbols
    test_symbols = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK']
    print("\nTesting specific symbols:")
    for sym in test_symbols:
        info = checker.get_results_info(sym)
        if info['has_results']:
            print(f"  {sym}: {info['label']}")
        else:
            print(f"  {sym}: No results scheduled")

    print(f"\n{'='*60}\n")
