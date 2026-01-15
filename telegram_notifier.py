"""
Telegram Notifier - Main Entry Point

Refactored modular notification system that delegates to specialized notifiers.
Maintains backward compatibility with the original monolithic implementation.
"""

from typing import Optional, List, Dict
from datetime import datetime
import logging

# Import specialized notifiers
from telegram_notifiers.stock_alerts import StockAlertNotifier
from telegram_notifiers.pattern_alerts import PatternAlertNotifier
from telegram_notifiers.sector_alerts import SectorAlertNotifier
from telegram_notifiers.price_action_alerts import PriceActionAlertNotifier
from telegram_notifiers.nifty_option_alerts import NiftyOptionAlertNotifier
from telegram_notifiers.volume_profile_alerts import VolumeProfileAlertNotifier

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Main Telegram notification facade that delegates to specialized notifiers.

    This class maintains backward compatibility with the original monolithic
    TelegramNotifier while using a modular architecture internally.
    """

    def __init__(self):
        """Initialize all specialized notifiers"""
        # Compose specialized notifiers
        self.stock_alerts = StockAlertNotifier()
        self.pattern_alerts = PatternAlertNotifier()
        self.sector_alerts = SectorAlertNotifier()
        self.price_action_alerts = PriceActionAlertNotifier()
        self.nifty_option_alerts = NiftyOptionAlertNotifier()
        self.volume_profile_alerts = VolumeProfileAlertNotifier()

        # Expose common properties for backward compatibility
        self.bot_token = self.stock_alerts.bot_token
        self.channel_id = self.stock_alerts.channel_id
        self.base_url = self.stock_alerts.base_url
        self.excel_logger = self.stock_alerts.excel_logger

    # ========================================
    # Stock Alert Methods
    # ========================================

    def send_alert(self, symbol: str, drop_percent: float, current_price: float,
                   previous_price: float, alert_type: str = "10min",
                   volume_data: dict = None, market_cap_cr: float = None,
                   rsi_analysis: dict = None, oi_analysis: dict = None,
                   sector_context: dict = None) -> bool:
        """
        Send a stock drop alert to Telegram channel

        Delegates to StockAlertNotifier
        """
        return self.stock_alerts.send_alert(
            symbol=symbol,
            drop_percent=drop_percent,
            current_price=current_price,
            previous_price=previous_price,
            alert_type=alert_type,
            volume_data=volume_data,
            market_cap_cr=market_cap_cr,
            rsi_analysis=rsi_analysis,
            oi_analysis=oi_analysis,
            sector_context=sector_context
        )

    def send_1min_alert(self, symbol: str, direction: str, current_price: float,
                       previous_price: float, change_percent: float,
                       volume_data: dict = None, market_cap_cr: float = None,
                       rsi_analysis: dict = None, oi_analysis: dict = None,
                       sector_context: dict = None) -> bool:
        """
        Send a 1-minute timeframe alert to Telegram channel

        Delegates to StockAlertNotifier
        """
        return self.stock_alerts.send_1min_alert(
            symbol=symbol,
            direction=direction,
            current_price=current_price,
            previous_price=previous_price,
            change_percent=change_percent,
            volume_data=volume_data,
            market_cap_cr=market_cap_cr,
            rsi_analysis=rsi_analysis,
            oi_analysis=oi_analysis,
            sector_context=sector_context
        )

    # ========================================
    # Pattern Alert Methods
    # ========================================

    def send_premarket_pattern_alert(
        self,
        symbol: str,
        pattern_name: str,
        pattern_type: str,
        confidence: float,
        current_price: float,
        entry_price: float,
        target_price: float,
        stop_loss: float,
        pattern_details: dict = None
    ) -> bool:
        """
        Send pre-market pattern detection alert

        Delegates to PatternAlertNotifier
        """
        return self.pattern_alerts.send_premarket_pattern_alert(
            symbol=symbol,
            pattern_name=pattern_name,
            pattern_type=pattern_type,
            confidence=confidence,
            current_price=current_price,
            entry_price=entry_price,
            target_price=target_price,
            stop_loss=stop_loss,
            pattern_details=pattern_details
        )

    def send_eod_pattern_summary(self, pattern_results: List[Dict],
                                 analysis_date: datetime) -> bool:
        """
        Send end-of-day pattern detection summary

        Delegates to PatternAlertNotifier
        """
        return self.pattern_alerts.send_eod_pattern_summary(
            pattern_results=pattern_results,
            analysis_date=analysis_date
        )

    # ========================================
    # Sector Alert Methods
    # ========================================

    def send_sector_rotation_alert(self, rotation_data: dict) -> bool:
        """
        Send sector rotation detection alert

        Delegates to SectorAlertNotifier
        """
        return self.sector_alerts.send_sector_rotation_alert(rotation_data)

    def send_eod_sector_summary(self, sector_analysis: dict) -> bool:
        """
        Send end-of-day sector performance summary

        Delegates to SectorAlertNotifier
        """
        return self.sector_alerts.send_eod_sector_summary(sector_analysis)

    # ========================================
    # Price Action Alert Methods
    # ========================================

    def send_price_action_alert(
        self,
        symbol: str,
        pattern_name: str,
        pattern_type: str,
        confidence_score: float,
        entry_price: float,
        target: float,
        stop_loss: float,
        current_price: float,
        pattern_details: dict = None,
        market_regime: str = None,
        market_cap_cr: float = None
    ) -> bool:
        """
        Send price action (candlestick pattern) alert

        Delegates to PriceActionAlertNotifier
        """
        return self.price_action_alerts.send_price_action_alert(
            symbol=symbol,
            pattern_name=pattern_name,
            pattern_type=pattern_type,
            confidence_score=confidence_score,
            entry_price=entry_price,
            target=target,
            stop_loss=stop_loss,
            current_price=current_price,
            pattern_details=pattern_details,
            market_regime=market_regime,
            market_cap_cr=market_cap_cr
        )

    # ========================================
    # NIFTY Option Alert Methods
    # ========================================

    def send_nifty_option_analysis(self, analysis_data: dict) -> bool:
        """
        Send NIFTY option analysis report

        Delegates to NiftyOptionAlertNotifier
        """
        return self.nifty_option_alerts.send_nifty_option_analysis(analysis_data)

    def send_nifty_add_position_alert(self, analysis_data: dict,
                                     layer_number: int,
                                     is_late_entry: bool = False) -> bool:
        """
        Send NIFTY add position signal

        Delegates to NiftyOptionAlertNotifier
        """
        return self.nifty_option_alerts.send_nifty_add_position_alert(
            analysis_data=analysis_data,
            layer_number=layer_number,
            is_late_entry=is_late_entry
        )

    def send_nifty_exit_alert(self, exit_data: dict) -> bool:
        """
        Send NIFTY exit signal

        Delegates to NiftyOptionAlertNotifier
        """
        return self.nifty_option_alerts.send_nifty_exit_alert(exit_data)

    def send_nifty_eod_summary(self, position_state: dict,
                              current_analysis: dict) -> bool:
        """
        Send NIFTY end-of-day summary

        Delegates to NiftyOptionAlertNotifier
        """
        return self.nifty_option_alerts.send_nifty_eod_summary(
            position_state=position_state,
            current_analysis=current_analysis
        )

    # ========================================
    # Volume Profile Alert Methods
    # ========================================

    def send_volume_profile_summary(
        self,
        analysis_date: datetime,
        top_stocks: List[Dict],
        high_volume_count: int,
        total_analyzed: int,
        report_path: str = None
    ) -> bool:
        """
        Send volume profile analysis summary

        Delegates to VolumeProfileAlertNotifier
        """
        return self.volume_profile_alerts.send_volume_profile_summary(
            analysis_date=analysis_date,
            top_stocks=top_stocks,
            high_volume_count=high_volume_count,
            total_analyzed=total_analyzed,
            report_path=report_path
        )

    # ========================================
    # Utility Methods
    # ========================================

    def send_test_message(self) -> bool:
        """
        Send a test message to verify Telegram integration

        Delegates to StockAlertNotifier (uses base _send_message)
        """
        return self.stock_alerts.send_test_message()
