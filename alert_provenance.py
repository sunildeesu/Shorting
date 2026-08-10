"""Provenance tag stamped on every alert this repo sends.

The captain receives Telegram alerts from a dozen monitors across three
repositories; without a tag the messages are indistinguishable, and a service
that has gone silent is invisible. Every outgoing message therefore carries a
one-line footer naming the project and the service that produced it:

    [ShortIndicator · stock_monitor]

The service defaults to the entry-point script name, so a monitor added later
is covered without touching it. Call `set_service()` early in a process whose
entry point is not a useful name.
"""
import html
import os
import sys

PROJECT = "ShortIndicator"

_service_override = None


def set_service(name: str) -> None:
    """Override the derived service name for this process."""
    global _service_override
    _service_override = name


def get_service() -> str:
    """The service name: the override if set, else the entry-point script."""
    if _service_override:
        return _service_override
    name = os.path.basename(sys.argv[0] if sys.argv else "")
    if name.endswith(".py"):
        name = name[:-3]
    return name or "unknown"


def tag(service: str = None) -> str:
    """The provenance footer, HTML-escaped so odd names cannot break delivery."""
    return f"<i>[{html.escape(PROJECT)} · {html.escape(service or get_service())}]</i>"


def stamp(message: str, service: str = None) -> str:
    """Append the provenance footer to `message`, unless it already carries it."""
    footer = tag(service)
    if not message:
        return footer
    if message.rstrip().endswith(footer):
        return message
    return f"{message}\n\n{footer}"
