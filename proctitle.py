"""proctitle — give this process a readable name in `ps` / `pgrep`.

Usage (as the first line inside the entrypoint's __main__ guard):

    if __name__ == "__main__":
        import proctitle; proctitle.set_title("nse-stock-monitor")

After this, `ps aux`, `ps -o command`, `ps -o comm` (truncated to 16 chars) and
`pgrep -fl <name>` all show the given name instead of "Python".

Note: macOS `top` and Activity Monitor still show "Python" — they read the
executable's Mach-O name, which a process cannot change about itself. This is a
best-effort cosmetic aid and is a safe no-op if setproctitle isn't installed.
"""


def set_title(name: str) -> str:
    """Set this process's visible title while PRESERVING the original command
    line, so existing pgrep/pkill/watchdog logic that greps the script name
    still matches (setproctitle otherwise REPLACES the whole command line).
    The readable name is shown first (and in `ps -o comm`, truncated to 16
    chars). Never raises.
    """
    try:
        import setproctitle
        import sys
        orig = " ".join(sys.argv).strip()
        setproctitle.setproctitle(f"{name} {orig}".strip() if orig else name)
    except Exception:
        pass  # cosmetics must never break a service
    return name
