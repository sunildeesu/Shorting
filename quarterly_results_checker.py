#!/usr/bin/env python3
"""
Quarterly Results Checker

Fetches and caches daily board meeting/quarterly results data from NSE.
Used to flag stocks with upcoming results in alerts.

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

    Fetches data from NSE and caches it locally for the day.
    Falls back to manual file if API fails.
    """

    def __init__(self, cache_dir: str = "data/results_cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

        # Manual results file path
        self.manual_file = os.path.join(cache_dir, "manual_results.json")

        # In-memory cache for quick lookups
        self._results_today: Set[str] = set()  # Symbols with results TODAY
        self._results_upcoming: Dict[str, str] = {}  # Symbol -> date (next 7 days)
        self._last_fetch: Optional[datetime] = None
        self._api_failed: bool = False  # Track if API failed

        # NSE API settings
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        # Create manual file template if doesn't exist
        self._ensure_manual_file()

        # Load cached data if available
        self._load_cache()

    def _ensure_manual_file(self):
        """Create manual results file template if it doesn't exist."""
        if not os.path.exists(self.manual_file):
            template = {
                "_comment": "Add stocks with quarterly results here. Format: SYMBOL: DD-MMM-YYYY",
                "_example": "RELIANCE: 15-Feb-2026",
                "_updated": datetime.now().strftime('%Y-%m-%d'),
                "results": {
                    # Example entries - user can edit this file
                }
            }
            try:
                with open(self.manual_file, 'w') as f:
                    json.dump(template, f, indent=2)
                logger.info(f"Created manual results file: {self.manual_file}")
            except Exception as e:
                logger.warning(f"Failed to create manual results file: {e}")

    def _load_manual_results(self) -> Dict[str, str]:
        """Load manually entered results from file."""
        if not os.path.exists(self.manual_file):
            return {}

        try:
            with open(self.manual_file, 'r') as f:
                data = json.load(f)
                return data.get('results', {})
        except Exception as e:
            logger.warning(f"Failed to load manual results: {e}")
            return {}

    def add_manual_result(self, symbol: str, date: str):
        """
        Add a stock to the manual results file.

        Args:
            symbol: Stock symbol (e.g., 'RELIANCE')
            date: Results date (e.g., '15-Feb-2026' or 'TODAY')
        """
        try:
            data = {"results": {}}
            if os.path.exists(self.manual_file):
                with open(self.manual_file, 'r') as f:
                    data = json.load(f)

            if 'results' not in data:
                data['results'] = {}

            data['results'][symbol.upper()] = date
            data['_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')

            with open(self.manual_file, 'w') as f:
                json.dump(data, f, indent=2)

            # Update in-memory cache
            symbol = symbol.upper()
            if date.upper() == 'TODAY':
                self._results_today.add(symbol)
            else:
                self._results_upcoming[symbol] = date

            logger.info(f"Added manual result: {symbol} -> {date}")
            return True
        except Exception as e:
            logger.error(f"Failed to add manual result: {e}")
            return False

    def _get_cache_path(self, date_str: str = None) -> str:
        """Get cache file path for a date."""
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self.cache_dir, f"results_{date_str}.json")

    def _load_cache(self):
        """Load today's cached results data."""
        today = datetime.now().strftime('%Y-%m-%d')
        cache_path = self._get_cache_path(today)

        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                    self._results_today = set(data.get('results_today', []))
                    self._results_upcoming = data.get('results_upcoming', {})
                    self._last_fetch = datetime.fromisoformat(data.get('fetch_time', ''))
                    logger.info(f"Loaded {len(self._results_today)} stocks with results today from cache")
            except Exception as e:
                logger.warning(f"Failed to load results cache: {e}")

    def _save_cache(self):
        """Save results data to cache."""
        today = datetime.now().strftime('%Y-%m-%d')
        cache_path = self._get_cache_path(today)

        try:
            data = {
                'results_today': list(self._results_today),
                'results_upcoming': self._results_upcoming,
                'fetch_time': datetime.now().isoformat()
            }
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save results cache: {e}")

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
                logger.warning(f"NSE board meetings API returned {response.status_code}")
                return False

            meetings = response.json()

            # Also fetch corporate announcements for results already declared
            ann_url = 'https://www.nseindia.com/api/corporate-announcements?index=equities'
            ann_response = session.get(ann_url, headers=self.headers, timeout=15)
            announcements = ann_response.json() if ann_response.status_code == 200 else []

            # Process data
            today = datetime.now().strftime('%d-%b-%Y')
            today_alt = datetime.now().strftime('%Y-%m-%d')

            self._results_today.clear()
            self._results_upcoming.clear()

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

                # Check if today
                if meeting_date == today:
                    self._results_today.add(symbol)
                    logger.debug(f"Results TODAY: {symbol}")
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

                if not symbol:
                    continue

                # Check if it's financial results announced today
                if today_alt in ann_date or today.replace('-', ' ').lower() in ann_date.lower():
                    if 'financial result' in desc or 'quarterly result' in desc:
                        self._results_today.add(symbol)

            self._api_failed = False
            self._merge_manual_data()
            self._last_fetch = datetime.now()
            self._save_cache()

            logger.info(f"Fetched results data: {len(self._results_today)} today, "
                       f"{len(self._results_upcoming)} upcoming (API + manual)")

            return True

        except Exception as e:
            logger.error(f"Failed to fetch NSE results data: {e}")
            self._api_failed = True
            # Fall back to manual data only
            self._load_manual_only()
            return False

    def _merge_manual_data(self):
        """Merge manual results with API data."""
        manual = self._load_manual_results()
        today = datetime.now().strftime('%d-%b-%Y')

        for symbol, date in manual.items():
            symbol = symbol.upper()
            if date.upper() == 'TODAY' or date == today:
                self._results_today.add(symbol)
            else:
                # Check if date is within 7 days
                try:
                    result_dt = datetime.strptime(date, '%d-%b-%Y')
                    days_away = (result_dt - datetime.now()).days
                    if 0 <= days_away <= 7:
                        self._results_upcoming[symbol] = date
                except:
                    # Try alternate format
                    try:
                        result_dt = datetime.strptime(date, '%Y-%m-%d')
                        days_away = (result_dt - datetime.now()).days
                        if 0 <= days_away <= 7:
                            self._results_upcoming[symbol] = result_dt.strftime('%d-%b-%Y')
                    except:
                        pass

    def _load_manual_only(self):
        """Load only manual data when API fails."""
        self._results_today.clear()
        self._results_upcoming.clear()

        manual = self._load_manual_results()
        today = datetime.now().strftime('%d-%b-%Y')

        for symbol, date in manual.items():
            symbol = symbol.upper()
            if date.upper() == 'TODAY' or date == today:
                self._results_today.add(symbol)
            else:
                try:
                    result_dt = datetime.strptime(date, '%d-%b-%Y')
                    days_away = (result_dt - datetime.now()).days
                    if 0 <= days_away <= 7:
                        self._results_upcoming[symbol] = date
                except:
                    try:
                        result_dt = datetime.strptime(date, '%Y-%m-%d')
                        days_away = (result_dt - datetime.now()).days
                        if 0 <= days_away <= 7:
                            self._results_upcoming[symbol] = result_dt.strftime('%d-%b-%Y')
                    except:
                        pass

        self._last_fetch = datetime.now()

        if self._results_today or self._results_upcoming:
            logger.info(f"Loaded manual results: {len(self._results_today)} today, "
                       f"{len(self._results_upcoming)} upcoming (API failed, using manual only)")

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
    logging.basicConfig(level=logging.INFO)

    checker = QuarterlyResultsChecker()

    print(f"\n{'='*60}")
    print("QUARTERLY RESULTS CHECKER")
    print(f"{'='*60}")
    print(f"\nManual file: {checker.manual_file}")
    print("(Edit this file to add results if NSE API fails)\n")

    print("Fetching results data from NSE...")
    success = checker.fetch_from_nse()

    if success:
        print("✅ NSE API successful")
    else:
        print("❌ NSE API failed - using manual data only")

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

    print(f"\n{'='*60}")
    print("MANUAL FILE FORMAT")
    print(f"{'='*60}")
    print("""
To add results manually, edit: data/results_cache/manual_results.json

Example format:
{
  "results": {
    "RELIANCE": "15-Feb-2026",
    "TCS": "TODAY",
    "INFY": "20-Feb-2026"
  }
}

Use "TODAY" for stocks with results today.
""")
