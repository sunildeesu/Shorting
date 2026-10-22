"""Keep Telegram bot tokens out of logs.

A Telegram API URL carries the bot token in its path (`/bot<id>:<secret>/...`),
and requests/urllib3 put that URL into the text of every connection error and
HTTPError ("Max retries exceeded with url: /bot.../sendMessage", "... for url:
https://api.telegram.org/bot.../sendMessage"), and urllib3 logs it again at
DEBUG for every request. Logging `{e}` therefore writes the token to disk; by
2026-10 that had put both bot tokens into ten deployed log files.

`redact()` is the one rule: use it on any exception text from a Telegram call
before logging or printing it. Importing this module also installs a filter on
urllib3's connection-pool logger, so the library's own lines are redacted too.
"""
import logging
import re

# `bot` + numeric bot id + `:` + secret, as it appears in a Bot API URL path.
TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
REDACTED = "bot<REDACTED>"


def redact(text) -> str:
    """`text` (any object, e.g. an exception) as a string with bot tokens masked."""
    return TOKEN_RE.sub(REDACTED, str(text))


class RedactingFilter(logging.Filter):
    """Rewrite a record's message with bot tokens masked; never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


_URLLIB3_LOGGER = "urllib3.connectionpool"


def install_urllib3_filter() -> None:
    """Attach the filter to urllib3's connection-pool logger (idempotent)."""
    logger = logging.getLogger(_URLLIB3_LOGGER)
    if not any(isinstance(f, RedactingFilter) for f in logger.filters):
        logger.addFilter(RedactingFilter())


install_urllib3_filter()
