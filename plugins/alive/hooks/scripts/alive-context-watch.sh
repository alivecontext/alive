#!/bin/bash
# Hook: Context Watch — UserPromptSubmit
# Checks if the current walnut's state files were modified by another session.
# If so, injects additionalContext suggesting a context refresh.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
find_world || exit 0

SESSION_ID="${HOOK_SESSION_ID}"
[ -z "$SESSION_ID" ] && exit 0

# Find which walnut this session is working on
SQUIRRELS_DIR="$WORLD_ROOT/.alive/_squirrels"
ENTRY="$SQUIRRELS_DIR/$SESSION_ID.yaml"
[ ! -f "$ENTRY" ] && exit 0

WALNUT=$(grep '^walnut:' "$ENTRY" 2>/dev/null | sed 's/walnut: *//' || true)
[ -z "${WALNUT:-}" ] || [ "$WALNUT" = "null" ] && exit 0

# Find walnut's _core/ directory
WALNUT_CORE=$(find "$WORLD_ROOT" -path "*/01_Archive" -prune -o -path "*/$WALNUT/_core" -print -quit 2>/dev/null || true)
[ -z "${WALNUT_CORE:-}" ] || [ ! -d "$WALNUT_CORE" ] && exit 0

# Timestamp file tracks when this session last checked
LASTCHECK="/tmp/alive-lastcheck-${SESSION_ID}"

# On first run, just create the timestamp and exit
if [ ! -f "$LASTCHECK" ]; then
  date +%s > "$LASTCHECK"
  exit 0
fi

LAST_CHECK_TIME=$(cat "$LASTCHECK" 2>/dev/null || echo "0")

# Check if now.md or log.md were modified after our last check
CHANGED=""
for file in "$WALNUT_CORE/now.md" "$WALNUT_CORE/log.md" "$WALNUT_CORE/tasks.md"; do
  if [ -f "$file" ]; then
    # Get file mtime as epoch seconds
    if stat --version >/dev/null 2>&1; then
      MTIME=$(stat -c %Y "$file" 2>/dev/null || echo "0")
    else
      MTIME=$(stat -f %m "$file" 2>/dev/null || echo "0")
    fi
    if [ "$MTIME" -gt "$LAST_CHECK_TIME" ] 2>/dev/null; then
      CHANGED="${CHANGED} $(basename "$file")"
    fi
  fi
done

# Update timestamp
date +%s > "$LASTCHECK"

# If nothing changed, exit silently
[ -z "${CHANGED:-}" ] && exit 0

# Check if the change was made by US (same session_id in now.md squirrel field)
LAST_SQUIRREL=$(grep '^squirrel:' "$WALNUT_CORE/now.md" 2>/dev/null | sed 's/squirrel: *//' || true)
if [ "${LAST_SQUIRREL:-}" = "$SESSION_ID" ]; then
  exit 0
fi

# Another session modified the walnut — notify
jq -n --arg files "$CHANGED" --arg walnut "$WALNUT" '{
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit",
    additionalContext: ("Another session just saved to " + $walnut + ". Changed:" + $files + ". You should re-read _core/now.md, _core/tasks.md and _core/log.md before continuing — your context may be stale. Ask the human if they want you to refresh.")
  }
}'
exit 0
