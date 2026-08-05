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

set -euo pipefail

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/Library/LaunchAgents"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

if [ "$APPLY" -eq 0 ]; then
    echo "DRY RUN — nothing will be copied or loaded. Re-run with --apply."
fi
echo

missing=0
for plist in "$AGENT_DIR"/*.plist; do
    label="$(basename "$plist" .plist)"

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
if [ "$missing" -gt 0 ]; then
    echo "$missing job(s) skipped because referenced paths do not exist on this machine."
    echo "Fix the paths (venv built? NewsBase checked out?) and re-run."
fi
echo "Verify with: launchctl list | grep -E 'nse|shortindicator|stockmonitor|nifty|weeklybacktest'"
