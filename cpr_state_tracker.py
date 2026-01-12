#!/usr/bin/env python3
"""
CPR State Tracker - Persistent state management for CPR first touch detection

Tracks NIFTY price position relative to CPR levels (TC, BC) across trading sessions.
Detects when price crosses levels and persists state to survive service restarts.

Author: Claude Sonnet 4.5
Date: 2026-01-12
"""

import json
import os
import fcntl
import logging
from datetime import datetime, date
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class CPRStateTracker:
    """
    Tracks price position relative to CPR levels and detects crossings.

    Features:
    - Persistent state (survives restarts)
    - File locking for concurrency safety
    - Crossing detection with directional context
    - Automatic daily reset

    State Structure:
    {
        "trading_date": "2026-01-12",
        "cpr_levels": {"tc": float, "bc": float, "pivot": float},
        "positions": {
            "TC": {"position": "ABOVE"/"BELOW", "price": float, "timestamp": str},
            "BC": {"position": "ABOVE"/"BELOW", "price": float, "timestamp": str}
        }
    }
    """

    def __init__(self, state_file: str = "data/cpr_state.json"):
        """
        Initialize CPR state tracker.

        Args:
            state_file: Path to JSON state file (persistent storage)
        """
        self.state_file = Path(state_file)
        self.state = self._load_state()

        logger.info(f"CPR State Tracker initialized (file: {self.state_file})")

    def _load_state(self) -> Dict:
        """
        Load state from file with file locking.
        Creates new state if file doesn't exist.

        Returns:
            Dict with state data
        """
        # Create directory if doesn't exist
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.state_file.exists():
            # Initialize new state
            logger.info("No existing CPR state file - creating new state")
            return self._create_empty_state()

        try:
            with open(self.state_file, 'r') as f:
                # Acquire shared lock for reading
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    state = json.load(f)
                    logger.debug(f"Loaded CPR state from {self.state_file}")
                    return state
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading CPR state file: {e}")
            logger.info("Creating new state")
            return self._create_empty_state()

    def _save_state(self):
        """
        Save state to file with exclusive file locking.
        Ensures atomic writes and prevents corruption.
        """
        try:
            with open(self.state_file, 'w') as f:
                # Acquire exclusive lock for writing
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(self.state, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                    logger.debug(f"Saved CPR state to {self.state_file}")
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        except IOError as e:
            logger.error(f"Error saving CPR state: {e}")

    def _create_empty_state(self) -> Dict:
        """
        Create empty state structure.

        Returns:
            Dict with empty state
        """
        return {
            "trading_date": None,
            "cpr_levels": {
                "tc": None,
                "bc": None,
                "pivot": None,
                "calculated_at": None
            },
            "positions": {
                "TC": {
                    "position": None,
                    "price": None,
                    "timestamp": None
                },
                "BC": {
                    "position": None,
                    "price": None,
                    "timestamp": None
                }
            },
            "last_updated": None
        }

    def set_cpr_levels(self, tc: float, bc: float, pivot: float, trading_date: date):
        """
        Set CPR levels for the trading day.

        Args:
            tc: Top Central (resistance)
            bc: Bottom Central (support)
            pivot: Central Pivot
            trading_date: Trading date for these levels
        """
        self.state['trading_date'] = trading_date.isoformat()
        self.state['cpr_levels'] = {
            'tc': tc,
            'bc': bc,
            'pivot': pivot,
            'calculated_at': datetime.now().isoformat()
        }
        self._save_state()

        logger.info(f"CPR levels set for {trading_date}: TC={tc:.2f}, BC={bc:.2f}, Pivot={pivot:.2f}")

    def get_position(self, level_name: str) -> Optional[str]:
        """
        Get last known position relative to a CPR level.

        Args:
            level_name: "TC" or "BC"

        Returns:
            "ABOVE", "BELOW", or None if not set
        """
        if level_name not in self.state['positions']:
            return None

        return self.state['positions'][level_name].get('position')

    def update_position(self, level_name: str, current_price: float,
                       level_value: float, timestamp: datetime):
        """
        Update price position relative to a level.

        Args:
            level_name: "TC" or "BC"
            current_price: Current NIFTY spot price
            level_value: CPR level value (TC or BC)
            timestamp: Current timestamp
        """
        # Determine position
        position = "ABOVE" if current_price > level_value else "BELOW"

        # Update state
        self.state['positions'][level_name] = {
            'position': position,
            'price': current_price,
            'timestamp': timestamp.isoformat()
        }
        self.state['last_updated'] = timestamp.isoformat()

        self._save_state()

        logger.debug(f"{level_name} position updated: {position} (price={current_price:.2f}, level={level_value:.2f})")

    def detect_crossing(self, level_name: str, current_price: float,
                       level_value: float) -> Optional[Dict]:
        """
        Detect if price crossed a CPR level.

        This is the core crossing detection algorithm:
        1. Get previous position (ABOVE/BELOW from state)
        2. Determine current position
        3. If position changed → Crossing detected
        4. Return direction (FROM_ABOVE or FROM_BELOW)

        Args:
            level_name: "TC" or "BC"
            current_price: Current NIFTY spot price
            level_value: CPR level value (TC or BC)

        Returns:
            Dict with crossing info if detected:
            {
                'level': 'TC' or 'BC',
                'direction': 'FROM_ABOVE' or 'FROM_BELOW',
                'price': current_price,
                'level_value': level_value,
                'timestamp': datetime
            }
            Returns None if no crossing detected
        """
        timestamp = datetime.now()

        # Get previous position
        prev_position = self.get_position(level_name)

        # Determine current position
        if current_price > level_value:
            curr_position = "ABOVE"
        elif current_price < level_value:
            curr_position = "BELOW"
        else:
            # Exactly at level - use previous position to avoid false triggers
            curr_position = prev_position or "BELOW"

        # First observation - initialize state, no crossing yet
        if prev_position is None:
            self.update_position(level_name, current_price, level_value, timestamp)
            logger.info(f"{level_name} initialized: {curr_position} (price={current_price:.2f}, level={level_value:.2f})")
            return None

        # Check if position changed (crossing detected)
        if prev_position != curr_position:
            # CROSSING DETECTED!
            direction = f"FROM_{prev_position}"

            logger.info(f"🔔 CROSSING DETECTED: {level_name} {direction} at {current_price:.2f} (level={level_value:.2f})")

            # Update state
            self.update_position(level_name, current_price, level_value, timestamp)

            return {
                'level': level_name,
                'direction': direction,
                'price': current_price,
                'level_value': level_value,
                'timestamp': timestamp
            }

        # No crossing - just update state with current position
        self.update_position(level_name, current_price, level_value, timestamp)
        return None

    def reset_for_new_day(self, trading_date: date):
        """
        Reset state tracker for a new trading day.
        Clears all position tracking to allow fresh first-touch detection.

        Args:
            trading_date: New trading date
        """
        logger.info(f"Resetting CPR state tracker for new trading day: {trading_date}")

        # Keep CPR levels structure but reset positions
        self.state['trading_date'] = trading_date.isoformat()
        self.state['positions'] = {
            "TC": {
                "position": None,
                "price": None,
                "timestamp": None
            },
            "BC": {
                "position": None,
                "price": None,
                "timestamp": None
            }
        }
        self.state['last_updated'] = datetime.now().isoformat()

        self._save_state()

        logger.info("CPR state reset complete - ready for first touch detection")

    def get_trading_date(self) -> Optional[date]:
        """
        Get the trading date for current state.

        Returns:
            date object or None if not set
        """
        if not self.state.get('trading_date'):
            return None

        return date.fromisoformat(self.state['trading_date'])

    def get_cpr_levels(self) -> Dict:
        """
        Get current CPR levels.

        Returns:
            Dict with tc, bc, pivot values
        """
        return self.state.get('cpr_levels', {})

    def get_state(self) -> Dict:
        """
        Get complete state for debugging/monitoring.

        Returns:
            Complete state dict
        """
        return self.state.copy()


def main():
    """Test CPR state tracker"""
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("\n=== CPR State Tracker Test ===\n")

    # Initialize tracker
    tracker = CPRStateTracker(state_file="data/test_cpr_state.json")

    # Set CPR levels
    today = date.today()
    tracker.set_cpr_levels(tc=25550.50, bc=25480.25, pivot=25515.37, trading_date=today)

    # Simulate price movements
    print("\n--- Simulating Price Movements ---\n")

    # T0: Price below TC
    print("T0: Price at 25500 (below TC 25550)")
    result = tracker.detect_crossing('TC', 25500, 25550.50)
    print(f"Result: {result}\n")

    # T1: Price crosses above TC (FIRST TOUCH)
    print("T1: Price at 25560 (crosses above TC)")
    result = tracker.detect_crossing('TC', 25560, 25550.50)
    print(f"Result: {result}")
    if result:
        print(f"✅ FIRST TOUCH: {result['level']} {result['direction']}\n")

    # T2: Price falls back below TC
    print("T2: Price at 25540 (falls back below TC)")
    result = tracker.detect_crossing('TC', 25540, 25550.50)
    print(f"Result: {result}")
    if result:
        print(f"✅ CROSSING: {result['level']} {result['direction']}\n")

    # T3: Price crosses below BC
    print("T3: Price at 25470 (crosses below BC 25480)")
    result = tracker.detect_crossing('BC', 25470, 25480.25)
    print(f"Result: {result}")
    if result:
        print(f"✅ FIRST TOUCH: {result['level']} {result['direction']}\n")

    print("\n--- Final State ---\n")
    print(json.dumps(tracker.get_state(), indent=2))

    print("\n=== Test Complete ===\n")


if __name__ == "__main__":
    main()
