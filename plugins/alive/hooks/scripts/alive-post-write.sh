#!/bin/bash
# Hook: Post Write — PostToolUse (Write|Edit)
# Tracks write activity for statusline display.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
find_world || exit 0

# Track activity count per session
if [ -n "${HOOK_SESSION_ID}" ]; then
  ACTIVITY_FILE="/tmp/alive-activity-${HOOK_SESSION_ID}"
  if [ -f "$ACTIVITY_FILE" ]; then
    COUNT=$(cat "$ACTIVITY_FILE" 2>/dev/null || echo "0")
    echo $((COUNT + 1)) > "$ACTIVITY_FILE"
  else
    echo "1" > "$ACTIVITY_FILE"
  fi
fi

exit 0
