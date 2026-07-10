"""Base notifier class with common Telegram functionality."""
import html
import re
import requests
import logging
import config

logger = logging.getLogger(__name__)

# Discord limits: embed description max 4096 chars, max 10 embeds and 6000 chars total per message.
_DISCORD_EMBED_LIMIT = 4096
_DISCORD_MAX_EMBEDS = 10


class BaseNotifier:
    """Base class for all Telegram notifiers with shared functionality."""

    def __init__(self):
        """Initialize base notifier with Telegram credentials."""
        self.bot_token = config.TELEGRAM_BOT_TOKEN
        self.channel_id = config.TELEGRAM_CHANNEL_ID
        self.debug_bot_token = config.TELEGRAM_DEBUG_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN
        self.debug_channel_id = config.TELEGRAM_DEBUG_CHANNEL_ID
        # config.TELEGRAM_API_BASE lets delivery route via a relay (e.g. a Cloudflare
        # Worker) when api.telegram.org is blocked directly; defaults to api.telegram.org.
        self.base_url = f"{config.TELEGRAM_API_BASE}/bot{self.bot_token}"
        self.debug_base_url = f"{config.TELEGRAM_API_BASE}/bot{self.debug_bot_token}"

        # Optional Discord webhooks — alerts are sent in parallel with Telegram so
        # delivery survives Telegram being blocked. Debug falls back to the main webhook.
        self.discord_webhook = config.DISCORD_WEBHOOK_URL
        self.discord_debug_webhook = config.DISCORD_DEBUG_WEBHOOK_URL or config.DISCORD_WEBHOOK_URL

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

    def _html_to_discord(self, message: str) -> str:
        """Convert Telegram HTML formatting to Discord markdown."""
        text = re.sub(r'</?(?:b|strong)>', '**', message, flags=re.IGNORECASE)
        text = re.sub(r'</?(?:i|em)>', '*', text, flags=re.IGNORECASE)
        text = re.sub(r'</?u>', '__', text, flags=re.IGNORECASE)
        text = re.sub(r'</?(?:code|pre)>', '`', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)  # strip any remaining tags
        return html.unescape(text)

    @staticmethod
    def _chunk_text(text: str, limit: int) -> list:
        """Split text into <=limit-char chunks, preferring line boundaries."""
        if len(text) <= limit:
            return [text]
        chunks, current = [], ""
        for line in text.split("\n"):
            while len(line) > limit:  # a single over-long line: hard-split
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(line[:limit])
                line = line[limit:]
            if current and len(current) + len(line) + 1 > limit:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)
        return chunks

    def _send_to_discord(self, webhook_url: str, message: str) -> bool:
        """Send a message to a Discord webhook as embed(s). No-op if not configured."""
        if not webhook_url:
            return False
        import time as _time
        content = self._html_to_discord(message)
        if not content.strip():
            return False
        embeds = [{"description": chunk}
                  for chunk in self._chunk_text(content, _DISCORD_EMBED_LIMIT)][:_DISCORD_MAX_EMBEDS]
        payload = {"embeds": embeds}
        for attempt in range(2):
            try:
                response = requests.post(webhook_url, json=payload, timeout=10)
                if response.status_code == 429:
                    retry_after = response.json().get('retry_after', 5)
                    logger.warning(f"Discord rate limit — waiting {retry_after}s before retry")
                    _time.sleep(float(retry_after))
                    continue
                response.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to send Discord message: {e}")
                return False
        logger.error("Discord message dropped after rate-limit retry")
        return False

    def _send_message(self, message: str) -> bool:
        """Send to the main alerts channel via Telegram and Discord (parallel)."""
        tg_ok = self._send_to(self.channel_id, message)
        dc_ok = self._send_to_discord(self.discord_webhook, message)
        ok = tg_ok or dc_ok
        if ok:
            logger.info(f"Alert delivered to main channel (telegram={tg_ok}, discord={dc_ok})")
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
        tg_ok = False
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            tg_ok = True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send to debug channel: {e}")
        dc_ok = self._send_to_discord(self.discord_debug_webhook, message)
        ok = tg_ok or dc_ok
        if ok:
            logger.info(f"Debug message delivered (telegram={tg_ok}, discord={dc_ok})")
        return ok

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
