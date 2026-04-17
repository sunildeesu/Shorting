"""Base notifier class with common Telegram functionality."""
import requests
import logging
import config

logger = logging.getLogger(__name__)


class BaseNotifier:
    """Base class for all Telegram notifiers with shared functionality."""

    def __init__(self):
        """Initialize base notifier with Telegram credentials."""
        self.bot_token = config.TELEGRAM_BOT_TOKEN
        self.channel_id = config.TELEGRAM_CHANNEL_ID
        self.debug_bot_token = config.TELEGRAM_DEBUG_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN
        self.debug_channel_id = config.TELEGRAM_DEBUG_CHANNEL_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.debug_base_url = f"https://api.telegram.org/bot{self.debug_bot_token}"

        if not self.bot_token or not self.channel_id:
            raise ValueError("Telegram bot token and channel ID must be set in .env file")

    def _send_to(self, channel_id: str, message: str) -> bool:
        """Send message to a specific Telegram channel. Retries once on 429."""
        import time as _time
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": channel_id,
            "text": message,
            "parse_mode": "HTML"
        }
        for attempt in range(2):
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 5))
                    logger.warning(f"Telegram rate limit — waiting {retry_after}s before retry")
                    _time.sleep(retry_after)
                    continue
                response.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to send Telegram message to {channel_id}: {e}")
                return False
        logger.error(f"Telegram message dropped after rate-limit retry: {channel_id}")
        return False

    def _send_message(self, message: str) -> bool:
        """Send message to the main stock alerts channel."""
        ok = self._send_to(self.channel_id, message)
        if ok:
            logger.info("Telegram message sent to main channel")
        return ok

    def send_debug(self, message: str) -> bool:
        """
        Send a message to the debug/system channel using the debug bot.
        Use for non-stock alerts: service status, errors, system events, diagnostics.
        Falls back to main channel if debug channel is not configured.
        """
        if not self.debug_channel_id:
            logger.warning("TELEGRAM_DEBUG_CHANNEL_ID not set — falling back to main channel")
            return self._send_message(message)
        url = f"{self.debug_base_url}/sendMessage"
        payload = {"chat_id": self.debug_channel_id, "text": message, "parse_mode": "HTML"}
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Telegram message sent to debug channel")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send to debug channel: {e}")
            return False

    def send_test_message(self) -> bool:
        """Send a test message to both channels to verify integration."""
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')

        main_msg = (
            "🧪 <b>TELEGRAM TEST — Main Channel</b>\n"
            f"✅ Stock alerts channel is connected\n"
            f"📅 {now}"
        )
        debug_msg = (
            "🔧 <b>TELEGRAM TEST — Debug Channel</b>\n"
            f"✅ Debug/system channel is connected\n"
            f"📅 {now}\n\n"
            "This channel receives: service status, errors, diagnostics"
        )

        ok_main = self._send_message(main_msg)
        ok_debug = self.send_debug(debug_msg)
        return ok_main and ok_debug
