"""
Alert History Manager - Persistent storage for alert deduplication
Stores alert history in JSON file to survive script restarts
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import fcntl

logger = logging.getLogger(__name__)

class AlertHistoryManager:
    """Manages persistent alert history for deduplication across script runs"""

    def __init__(self, history_file: str = "data/alert_history.json"):
        """
        Initialize alert history manager

        Args:
            history_file: Path to JSON file storing alert history
        """
        self.history_file = history_file
        self.alert_history: Dict[Tuple[str, str], datetime] = {}

        # Daily alert directions: tracks direction history for each symbol today
        # "SYMBOL:YYYY-MM-DD" -> ["drop", "rise", "drop", ...]
        self.daily_directions: Dict[str, List[str]] = {}
        self.current_date: str = ""  # Track current date for reset

        # Ensure data directory exists
        os.makedirs(os.path.dirname(history_file), exist_ok=True)

        # Load existing history
        self._load_history()

        # Clean up old entries
        self._cleanup_old_entries()

    def _load_history(self):
        """Load alert history from JSON file"""
        if not os.path.exists(self.history_file):
            logger.info("No existing alert history found, starting fresh")
            return

        try:
            with open(self.history_file, 'r') as f:
                # Use file locking to prevent race conditions
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Convert string keys back to tuples and ISO timestamps to datetime
            for key_str, timestamp_str in data.get("alerts", {}).items():
                # Parse key: "(SYMBOL, alert_type)" -> (SYMBOL, alert_type)
                symbol, alert_type = key_str.strip("()").split(", ", 1)
                symbol = symbol.strip("'\"")
                alert_type = alert_type.strip("'\"")

                # Parse timestamp
                timestamp = datetime.fromisoformat(timestamp_str)

                self.alert_history[(symbol, alert_type)] = timestamp

            # Load daily directions (new format) or migrate from daily_counts (old format)
            if "daily_directions" in data:
                self.daily_directions = data.get("daily_directions", {})
            elif "daily_counts" in data:
                # Backward compatibility: migrate old daily_counts to daily_directions
                # Old format stored just count, so we create list with "drop" as default direction
                old_counts = data.get("daily_counts", {})
                self.daily_directions = {}
                for key, count in old_counts.items():
                    # Create list of "drop" with length = count (best effort migration)
                    self.daily_directions[key] = ["drop"] * count
                logger.info(f"Migrated {len(old_counts)} daily_counts to daily_directions format")
            else:
                self.daily_directions = {}
            self.current_date = data.get("current_date", "")

            # Reset counts if it's a new day
            self._reset_daily_counts_if_new_day()

            logger.info(f"Loaded {len(self.alert_history)} alert entries from history file")

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to load alert history (corrupted file?): {e}")
            logger.info("Starting with empty history")
            self.alert_history = {}

    def _save_history(self):
        """Save alert history to JSON file"""
        try:
            # Convert tuples to strings and datetime to ISO format
            data = {
                "alerts": {
                    f"({symbol}, {alert_type})": timestamp.isoformat()
                    for (symbol, alert_type), timestamp in self.alert_history.items()
                },
                "daily_directions": self.daily_directions,
                "current_date": self.current_date,
                "last_updated": datetime.now().isoformat()
            }

            # Write with file locking to prevent race conditions
            with open(self.history_file, 'w') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(data, f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            logger.debug(f"Saved {len(self.alert_history)} alert entries to history file")

        except Exception as e:
            logger.error(f"Failed to save alert history: {e}")

    def _cleanup_old_entries(self, max_age_minutes: int = 60):
        """
        Remove alert entries older than max_age_minutes
        Keeps the history file small and removes stale entries

        Args:
            max_age_minutes: Maximum age of entries to keep (default 60 minutes)
        """
        current_time = datetime.now()
        cutoff_time = current_time - timedelta(minutes=max_age_minutes)

        # Find old entries
        old_entries = [
            key for key, timestamp in self.alert_history.items()
            if timestamp < cutoff_time
        ]

        # Remove old entries
        for key in old_entries:
            del self.alert_history[key]

        if old_entries:
            logger.info(f"Cleaned up {len(old_entries)} old alert entries (older than {max_age_minutes} minutes)")
            self._save_history()

    def should_send_alert(self, symbol: str, alert_type: str, cooldown_minutes: int = 30) -> bool:
        """
        Check if an alert should be sent based on deduplication rules
        Prevents sending duplicate alerts for the same stock and alert type within cooldown period

        Args:
            symbol: Stock symbol
            alert_type: Type of alert (10min, 30min, 5min, volume_spike, etc.)
            cooldown_minutes: Cooldown period in minutes (default 30)

        Returns:
            True if alert should be sent, False if it's a duplicate
        """
        alert_key = (symbol, alert_type)
        current_time = datetime.now()

        # Check if this alert was sent recently
        if alert_key in self.alert_history:
            last_sent_time = self.alert_history[alert_key]
            time_since_last_alert = current_time - last_sent_time

            if time_since_last_alert < timedelta(minutes=cooldown_minutes):
                # Duplicate alert - skip
                logger.debug(f"{symbol}: Skipping duplicate {alert_type} alert "
                           f"(sent {time_since_last_alert.total_seconds()/60:.1f}min ago)")
                return False

        # Not a duplicate - record and allow
        self.alert_history[alert_key] = current_time

        # Save to file (persist for next script run)
        self._save_history()

        return True

    def get_last_alert_time(self, symbol: str, alert_type: str) -> datetime:
        """
        Get the last time an alert was sent for a specific stock/alert type

        Args:
            symbol: Stock symbol
            alert_type: Type of alert

        Returns:
            datetime of last alert, or None if never sent
        """
        alert_key = (symbol, alert_type)
        return self.alert_history.get(alert_key)

    def _reset_daily_counts_if_new_day(self):
        """Reset daily alert directions at the start of a new trading day."""
        today = datetime.now().strftime("%Y-%m-%d")

        if self.current_date != today:
            if self.current_date:
                logger.info(f"New trading day detected ({self.current_date} -> {today}), resetting daily alert directions")
            self.daily_directions = {}
            self.current_date = today
            self._save_history()

    def get_alert_count(self, symbol: str) -> int:
        """
        Get today's alert count for a symbol (across all alert types).

        Args:
            symbol: Stock symbol (with or without .NS suffix)

        Returns:
            Number of alerts sent for this symbol today
        """
        # Reset counts if new day
        self._reset_daily_counts_if_new_day()

        # Normalize symbol (remove .NS suffix)
        clean_symbol = symbol.replace('.NS', '')
        key = f"{clean_symbol}:{self.current_date}"

        return len(self.daily_directions.get(key, []))

    def increment_alert_count(self, symbol: str, direction: str = "drop") -> int:
        """
        Record an alert direction and return the new count for a symbol today.
        Call this when an alert is actually being sent (after cooldown check passes).

        Args:
            symbol: Stock symbol (with or without .NS suffix)
            direction: "drop" or "rise"

        Returns:
            New count after recording (1 for first alert, 2 for second, etc.)
        """
        # Reset counts if new day
        self._reset_daily_counts_if_new_day()

        # Normalize symbol (remove .NS suffix)
        clean_symbol = symbol.replace('.NS', '')
        key = f"{clean_symbol}:{self.current_date}"

        # Append direction to list
        if key not in self.daily_directions:
            self.daily_directions[key] = []
        self.daily_directions[key].append(direction)
        new_count = len(self.daily_directions[key])

        # Persist to file
        self._save_history()

        logger.debug(f"{clean_symbol}: Alert count incremented to {new_count} for today (direction: {direction})")
        return new_count

    def get_direction_history(self, symbol: str) -> List[str]:
        """
        Get list of directions for today's alerts.

        Args:
            symbol: Stock symbol (with or without .NS suffix)

        Returns:
            List of direction strings (e.g., ["drop", "rise", "drop"])
        """
        # Reset counts if new day
        self._reset_daily_counts_if_new_day()

        # Normalize symbol (remove .NS suffix)
        clean_symbol = symbol.replace('.NS', '')
        key = f"{clean_symbol}:{self.current_date}"

        return self.daily_directions.get(key, [])

    def get_direction_arrows(self, symbol: str) -> str:
        """
        Get formatted arrow string for today's alert directions.

        Args:
            symbol: Stock symbol (with or without .NS suffix)

        Returns:
            Formatted arrow string like "↓ ↑ ↓" or empty string if no history
        """
        directions = self.get_direction_history(symbol)
        if not directions:
            return ""

        arrow_map = {"drop": "↓", "rise": "↑"}
        arrows = [arrow_map.get(d, "?") for d in directions]
        return " ".join(arrows)

    def get_stats(self) -> Dict:
        """
        Get statistics about alert history

        Returns:
            Dictionary with stats (total_alerts, oldest_entry, newest_entry)
        """
        if not self.alert_history:
            return {
                "total_alerts": 0,
                "oldest_entry": None,
                "newest_entry": None
            }

        timestamps = list(self.alert_history.values())
        return {
            "total_alerts": len(self.alert_history),
            "oldest_entry": min(timestamps).isoformat(),
            "newest_entry": max(timestamps).isoformat()
        }
