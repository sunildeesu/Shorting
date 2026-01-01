#!/usr/bin/env python3
"""
Position State Manager

Tracks NIFTY option position state across intraday monitoring cycles.
Persists entry/exit information to enable exit signal generation.

Author: Sunil Kumar Durganaik
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PositionStateManager:
    """Manages position state for NIFTY option selling"""

    def __init__(self, state_file: str = "data/nifty_options/position_state.json"):
        """
        Initialize position state manager

        Args:
            state_file: Path to position state JSON file
        """
        self.state_file = state_file
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        """Load position state from file"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load position state: {e}")
                return {}
        return {}

    def _save_state(self):
        """Save position state to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save position state: {e}")

    def _is_same_trading_day(self, timestamp: str) -> bool:
        """Check if timestamp is from same trading day"""
        try:
            state_date = datetime.fromisoformat(timestamp).date()
            today = datetime.now().date()
            return state_date == today
        except:
            return False

    def has_position_today(self) -> bool:
        """
        Check if we have an active position today

        Returns:
            True if position entered and not exited today
        """
        if not self.state or 'status' not in self.state:
            return False

        # Check if it's from today
        layers = self.state.get('layers', [])
        if not layers:
            return False

        first_layer_time = layers[0].get('timestamp', '')
        if not self._is_same_trading_day(first_layer_time):
            return False

        # Check status
        return self.state.get('status') == 'ENTERED'

    def get_layer_count(self) -> int:
        """Get number of position layers entered"""
        if not self.has_position_today():
            return 0
        return len(self.state.get('layers', []))

    def get_entry_data(self) -> Optional[Dict]:
        """
        Get entry data for current position

        Returns:
            Dict with entry data or None if no position
        """
        if not self.has_position_today():
            return None

        return {
            'entry_timestamp': self.state.get('entry_timestamp'),
            'entry_signal': self.state.get('entry_signal'),
            'entry_score': self.state.get('entry_score'),
            'entry_nifty_spot': self.state.get('entry_nifty_spot'),
            'entry_vix': self.state.get('entry_vix'),
            'entry_regime': self.state.get('entry_regime'),
            'entry_oi_pattern': self.state.get('entry_oi_pattern'),
            'entry_strategy': self.state.get('entry_strategy'),
            'entry_strikes': self.state.get('entry_strikes'),
            'entry_premium': self.state.get('entry_premium')
        }

    def record_entry(self, analysis_data: Dict, layer_number: int = 1):
        """
        Record position entry (initial or additional layer)

        Args:
            analysis_data: Analysis result dict with entry signal
            layer_number: Layer number (1 = initial, 2+ = adds)
        """
        # Get best strategy data
        expiry_analyses = analysis_data.get('expiry_analyses', [])
        first_expiry = expiry_analyses[0] if expiry_analyses else {}
        best_strategy = analysis_data.get('best_strategy', 'straddle')

        if best_strategy.lower() == 'straddle':
            strategy_data = first_expiry.get('straddle', {})
        else:
            strategy_data = first_expiry.get('strangle', {})

        # Create layer data
        layer_data = {
            'layer_number': layer_number,
            'timestamp': analysis_data.get('timestamp'),
            'signal': analysis_data.get('signal'),
            'score': analysis_data.get('total_score'),
            'nifty_spot': analysis_data.get('nifty_spot'),
            'vix': analysis_data.get('vix'),
            'regime': analysis_data.get('market_regime'),
            'oi_pattern': analysis_data.get('oi_analysis', {}).get('pattern'),
            'strategy': best_strategy,
            'strikes': strategy_data.get('strikes', {}),
            'premium': strategy_data.get('total_premium', 0)
        }

        if layer_number == 1:
            # Initial entry
            self.state = {
                'status': 'ENTERED',
                'layers': [layer_data],
                'entry_timestamp': analysis_data.get('timestamp'),
                'entry_score': analysis_data.get('total_score'),
                'entry_nifty_spot': analysis_data.get('nifty_spot'),
                'entry_vix': analysis_data.get('vix'),
                'entry_regime': analysis_data.get('market_regime'),
                'entry_oi_pattern': analysis_data.get('oi_analysis', {}).get('pattern'),
                'entry_strategy': best_strategy,
                'entry_strikes': strategy_data.get('strikes', {}),
                'entry_premium': strategy_data.get('total_premium', 0),
                'last_check_timestamp': analysis_data.get('timestamp'),
                'last_check_score': analysis_data.get('total_score')
            }
            logger.info(f"Initial position entry: {analysis_data.get('signal')} at {analysis_data.get('total_score'):.1f}")
        else:
            # Additional layer
            if 'layers' not in self.state:
                self.state['layers'] = []
            self.state['layers'].append(layer_data)
            self.state['last_check_timestamp'] = analysis_data.get('timestamp')
            self.state['last_check_score'] = analysis_data.get('total_score')
            logger.info(f"Added layer {layer_number}: Score {analysis_data.get('total_score'):.1f}")

        self._save_state()

    def can_add_layer(self, max_layers: int, min_interval_minutes: int) -> bool:
        """
        Check if we can add another position layer

        Args:
            max_layers: Maximum number of layers allowed
            min_interval_minutes: Minimum minutes between layers

        Returns:
            True if can add layer
        """
        if not self.has_position_today():
            return True  # No position yet, can enter initial

        layers = self.state.get('layers', [])
        current_layer_count = len(layers)

        # Check max layers
        if current_layer_count >= max_layers:
            logger.debug(f"Cannot add layer: Already at max {max_layers} layers")
            return False

        # Check time interval since last layer
        last_layer = layers[-1]
        last_timestamp = last_layer.get('timestamp', '')

        try:
            last_time = datetime.fromisoformat(last_timestamp)
            now = datetime.now()
            minutes_since_last = (now - last_time).total_seconds() / 60

            if minutes_since_last < min_interval_minutes:
                logger.debug(f"Cannot add layer: Only {minutes_since_last:.0f} min since last (need {min_interval_minutes})")
                return False
        except:
            pass

        return True

    def get_last_layer_score(self) -> float:
        """Get score from last layer entry"""
        layers = self.state.get('layers', [])
        if not layers:
            return 0
        return layers[-1].get('score', 0)

    def record_exit(self, analysis_data: Dict, exit_reason: str):
        """
        Record position exit

        Args:
            analysis_data: Current analysis data
            exit_reason: Reason for exit
        """
        if not self.has_position_today():
            logger.warning("Attempted to record exit but no active position")
            return

        self.state['status'] = 'EXITED'
        self.state['exit_timestamp'] = analysis_data.get('timestamp')
        self.state['exit_score'] = analysis_data.get('total_score')
        self.state['exit_nifty_spot'] = analysis_data.get('nifty_spot')
        self.state['exit_vix'] = analysis_data.get('vix')
        self.state['exit_regime'] = analysis_data.get('market_regime')
        self.state['exit_reason'] = exit_reason

        # Calculate P&L estimate (simplified)
        entry_premium = self.state.get('entry_premium', 0)
        entry_nifty = self.state.get('entry_nifty_spot', 0)
        exit_nifty = analysis_data.get('nifty_spot', 0)

        if entry_premium > 0 and entry_nifty > 0:
            # Rough estimate: premium collected minus estimated loss
            nifty_move_pct = abs((exit_nifty - entry_nifty) / entry_nifty) * 100
            estimated_loss = entry_premium * (nifty_move_pct / 2)  # Simplified
            estimated_pnl = entry_premium - estimated_loss
            self.state['estimated_pnl'] = round(estimated_pnl, 2)
            self.state['estimated_pnl_pct'] = round((estimated_pnl / entry_premium) * 100, 2)

        self._save_state()
        logger.info(f"Position exit recorded: {exit_reason}")

    def update_check(self, analysis_data: Dict):
        """
        Update last check data (for monitoring)

        Args:
            analysis_data: Current analysis data
        """
        if self.has_position_today():
            self.state['last_check_timestamp'] = analysis_data.get('timestamp')
            self.state['last_check_score'] = analysis_data.get('total_score')
            self._save_state()

    def reset_for_new_day(self):
        """Clear state for new trading day"""
        self.state = {}
        self._save_state()
        logger.info("Position state reset for new trading day")

    def get_status_summary(self) -> str:
        """
        Get human-readable status summary

        Returns:
            Status summary string
        """
        if not self.state or 'status' not in self.state:
            return "No position today"

        entry_time = self.state.get('entry_timestamp', '')
        if not self._is_same_trading_day(entry_time):
            return "No position today (old state)"

        status = self.state.get('status')
        entry_score = self.state.get('entry_score', 0)
        entry_signal = self.state.get('entry_signal', 'UNKNOWN')

        if status == 'ENTERED':
            return f"Position ACTIVE: {entry_signal} ({entry_score:.1f}/100) at {entry_time}"
        elif status == 'EXITED':
            exit_reason = self.state.get('exit_reason', 'Unknown')
            exit_time = self.state.get('exit_timestamp', 'Unknown')
            return f"Position EXITED: {exit_reason} at {exit_time}"
        else:
            return f"Unknown status: {status}"


if __name__ == "__main__":
    # Test the position state manager
    logging.basicConfig(level=logging.INFO)

    manager = PositionStateManager()

    # Test entry
    test_entry_data = {
        'timestamp': datetime.now().isoformat(),
        'signal': 'SELL',
        'total_score': 75.5,
        'nifty_spot': 26150.0,
        'vix': 9.2,
        'market_regime': 'NEUTRAL',
        'best_strategy': 'straddle',
        'oi_analysis': {'pattern': 'LONG_UNWINDING'},
        'expiry_analyses': [{
            'straddle': {
                'strikes': {'call': 26150, 'put': 26150},
                'total_premium': 355.0
            }
        }]
    }

    print("\n=== Test Entry ===")
    manager.record_entry(test_entry_data)
    print(f"Has position: {manager.has_position_today()}")
    print(f"Status: {manager.get_status_summary()}")
    print(f"Entry data: {manager.get_entry_data()}")

    # Test exit
    test_exit_data = {
        'timestamp': datetime.now().isoformat(),
        'total_score': 45.0,
        'nifty_spot': 26250.0,
        'vix': 12.5,
        'market_regime': 'BULLISH'
    }

    print("\n=== Test Exit ===")
    manager.record_exit(test_exit_data, "Score dropped >20 points")
    print(f"Has position: {manager.has_position_today()}")
    print(f"Status: {manager.get_status_summary()}")

    print("\n=== State File Content ===")
    print(json.dumps(manager.state, indent=2))
