#!/bin/bash
# Install the versioned launchd job definitions onto this machine.
#
#   ./launchd_agents/install_launch_agents.sh            # dry run (default)
#   ./launchd_agents/install_launch_agents.sh --apply    # copy + load
#
# The plists in this directory are verbatim copies of what was installed on the
# production machine, with absolute paths baked in (/Users/sunilkumar/myProjects/
# ShortIndicator). On a machine with a different username or checkout location
# they must be edited first — this script refuses to install paths that do not
# resolve. See README.md.
#
# Jobs named in DO_NOT_AUTOLOAD.txt are copied but never loaded — they are stopped on
# purpose, and a restore must not silently restart them. That file carries the reason.

set -euo pipefail

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/Library/LaunchAgents"
HOLD_BACK_FILE="$AGENT_DIR/DO_NOT_AUTOLOAD.txt"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

# ---------------------------------------------------------------------------
# Read the hold-back list. Every problem below is fatal on purpose: if this
# mechanism is broken the fallback must NOT be "load everything", because a
# held-back job that gets loaded anyway is the exact bug it exists to prevent.
# ---------------------------------------------------------------------------
if [ ! -f "$HOLD_BACK_FILE" ]; then
    echo "FATAL: $HOLD_BACK_FILE is missing." >&2
    echo "       It names the jobs that are stopped on purpose and must not be" >&2
    echo "       loaded. Without it this script would load them and silently" >&2
    echo "       reverse a deliberate decision. Restore it and re-run." >&2
    exit 1
fi

# Emits one normalised "<label><TAB><reason>" record per held-back job.
parse_hold_back() {
    local lineno=0 line label reason
    while IFS= read -r line || [ -n "$line" ]; do
        lineno=$((lineno + 1))
        case "$line" in ''|'#'*) continue ;; esac
        if [ "$line" = "${line#*:}" ]; then
            echo "FATAL: $HOLD_BACK_FILE line $lineno is not '<label>: <reason>':" >&2
            echo "       $line" >&2
            return 1
        fi
        label="$(printf '%s' "${line%%:*}" | tr -d '[:space:]')"
        reason="$(printf '%s' "${line#*:}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        if [ -z "$label" ] || [ -z "$reason" ]; then
            echo "FATAL: $HOLD_BACK_FILE line $lineno has an empty label or reason." >&2
            echo "       A held-back job must say why, or nobody can judge it later." >&2
            return 1
        fi
        if [ ! -f "$AGENT_DIR/$label.plist" ]; then
            echo "FATAL: $HOLD_BACK_FILE names '$label' but $label.plist is not in" >&2
            echo "       $AGENT_DIR. Either the definition was lost — it is kept on" >&2
            echo "       purpose — or the label is misspelled, in which case the real" >&2
            echo "       job would be loaded by mistake." >&2
            return 1
        fi
        printf '%s\t%s\n' "$label" "$reason"
    done < "$HOLD_BACK_FILE"
}

HOLD_BACK="$(parse_hold_back)" || exit 1

if [ "$APPLY" -eq 0 ]; then
    echo "DRY RUN — nothing will be copied or loaded. Re-run with --apply."
fi
echo

missing=0
held=0
for plist in "$AGENT_DIR"/*.plist; do
    label="$(basename "$plist" .plist)"

    # Stopped on purpose? Copy the definition so it stays recoverable, never load it.
    # Exact label match, so no other job can be caught by this.
    hold_reason="$(printf '%s\n' "$HOLD_BACK" \
                   | awk -F'\t' -v l="$label" '$1 == l { print $2; exit }')"
    if [ -n "$hold_reason" ]; then
        if [ "$APPLY" -eq 1 ]; then
            cp "$plist" "$DEST/$label.plist"
            chmod 644 "$DEST/$label.plist"
            echo "HELD  $label — copied to $DEST/$label.plist but DELIBERATELY NOT LOADED."
        else
            echo "HELD  $label — would copy to $DEST/$label.plist but DELIBERATELY NOT LOAD it."
        fi
        echo "      Reason: $hold_reason"
        held=$((held + 1))
        continue
    fi

    # Every absolute path the job references must exist before we install it.
    bad=""
    while IFS= read -r path; do
        [ -e "$path" ] || bad="$bad $path"
    done < <(/usr/bin/plutil -convert json -o - "$plist" \
             | /usr/bin/grep -oE '/Users/[^"]+|/bin/[^"]+|/usr/[^"]+' \
             | sort -u)

    if [ -n "$bad" ]; then
        echo "SKIP  $label — missing paths:$bad"
        missing=$((missing + 1))
        continue
    fi

    if [ "$APPLY" -eq 1 ]; then
        cp "$plist" "$DEST/$label.plist"
        chmod 644 "$DEST/$label.plist"
        launchctl unload "$DEST/$label.plist" 2>/dev/null || true
        launchctl load "$DEST/$label.plist"
        echo "OK    $label — installed and loaded"
    else
        echo "OK    $label — would install to $DEST/$label.plist"
    fi
done

echo
if [ "$held" -gt 0 ]; then
    echo "$held job(s) held back: definition installed, job left stopped, on purpose."
    echo "Reasons are in $HOLD_BACK_FILE. Re-enabling one is the captain's decision."
fi
if [ "$missing" -gt 0 ]; then
    echo "$missing job(s) skipped because referenced paths do not exist on this machine."
    echo "Fix the paths (venv built? NewsBase checked out?) and re-run."
fi
echo "Verify with: launchctl list | grep -E 'nse|shortindicator|stockmonitor|nifty|weeklybacktest'"
