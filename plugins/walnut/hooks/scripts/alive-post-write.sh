#!/bin/bash
# Hook: Post Write — PostToolUse (Write|Edit)
# Two jobs:
# 1. Track write activity for statusline display
# 2. Regenerate world index after save (detected by _core/now.md write)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/walnut-common.sh"

read_hook_input
find_world || exit 0

# Track activity count per session
if [ -n "${HOOK_SESSION_ID}" ]; then
  ACTIVITY_FILE="/tmp/walnut-activity-${HOOK_SESSION_ID}"
  if [ -f "$ACTIVITY_FILE" ]; then
    COUNT=$(cat "$ACTIVITY_FILE" 2>/dev/null || echo "0")
    echo $((COUNT + 1)) > "$ACTIVITY_FILE"
  else
    echo "1" > "$ACTIVITY_FILE"
  fi
fi

# Regenerate world index after save
# now.md is only written by save (per rules) — use it as the trigger
FILE_PATH=$(json_field "tool_input.file_path")
case "$FILE_PATH" in
  */_core/now.md)
    GENERATOR="$WORLD_ROOT/.walnut/scripts/generate-index.py"
    # Fall back to plugin scripts dir
    [ ! -f "$GENERATOR" ] && GENERATOR="${CLAUDE_PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}/scripts/generate-index.py"
    if [ -f "$GENERATOR" ]; then
      # Debounce — skip if we regenerated in the last 5 minutes
      MARKER="/tmp/walnut-index-regen"
      if [ -f "$MARKER" ]; then
        if stat --version >/dev/null 2>&1; then
          MARKER_MTIME=$(stat -c %Y "$MARKER" 2>/dev/null || echo "0")
        else
          MARKER_MTIME=$(stat -f %m "$MARKER" 2>/dev/null || echo "0")
        fi
        AGE=$(( $(date +%s) - MARKER_MTIME ))
        [ "$AGE" -lt 300 ] && exit 0
      fi
      touch "$MARKER"
      # Background — don't block the session
      python3 "$GENERATOR" "$WORLD_ROOT" > /dev/null 2>&1 &
    fi
    ;;
esac

exit 0
