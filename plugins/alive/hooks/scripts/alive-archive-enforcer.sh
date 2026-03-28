#!/bin/bash
# Hook: Archive Enforcer -- PreToolUse (Bash)
# Blocks rm/rmdir/unlink when targeting files inside the Alive world.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
find_world || exit 0

COMMAND=$(json_field "tool_input.command")

# Check for destructive commands -- grep -E \s works on macOS, unlike sed
if ! echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)(rm|rmdir|unlink)\s'; then
  exit 0
fi

# Extract target paths using python3 for reliable parsing
# Handles: quoted paths, spaces in filenames, flags, chained commands, multiple targets
TARGET=$(echo "$COMMAND" | python3 -c "
import sys, shlex, re
cmd = sys.stdin.read().strip()
for part in re.split(r'[;&|]+', cmd):
    part = part.strip()
    try: tokens = shlex.split(part)
    except ValueError: tokens = part.split()
    found = False
    for t in tokens:
        if not found:
            if t in ('rm', 'rmdir', 'unlink'):
                found = True
            continue
        if not t.startswith('-'):
            print(t)
" 2>/dev/null)

# Use cwd from JSON input for resolving relative paths
RESOLVE_DIR="${HOOK_CWD:-$PWD}"

# Process ALL targets -- rename every World file, then deny once
RENAMED=""
NOT_FOUND=""

while IFS= read -r path; do
  [ -z "$path" ] && continue

  # Resolve relative paths against the session's cwd
  if [[ "$path" != /* ]]; then
    resolved="$RESOLVE_DIR/$path"
  else
    resolved="$path"
  fi

  # Check if resolved path is inside the World (protect entire root, not just subdirs)
  case "$resolved" in
    "$WORLD_ROOT"|"$WORLD_ROOT"/*)
      if [ -e "$resolved" ]; then
        DIRNAME=$(dirname "$resolved")
        BASENAME=$(basename "$resolved")
        MARKED="${DIRNAME}/${BASENAME} (Marked for Deletion)"
        mv "$resolved" "$MARKED" 2>/dev/null || true
        if [[ "$OSTYPE" == "darwin"* ]]; then
          open "$DIRNAME" 2>/dev/null || true
        elif command -v xdg-open &>/dev/null; then
          xdg-open "$DIRNAME" 2>/dev/null || true
        fi
        RENAMED="${RENAMED}${BASENAME}, "
      else
        NOT_FOUND="${NOT_FOUND}$(basename "$resolved"), "
      fi
      ;;
  esac
done <<< "$TARGET"

# Build denial message from all processed targets
if [ -n "$RENAMED" ] || [ -n "$NOT_FOUND" ]; then
  REASON=""
  if [ -n "$RENAMED" ]; then
    REASON="Renamed to (Marked for Deletion): ${RENAMED%, }. Review in your file manager and delete manually if intended."
  fi
  if [ -n "$NOT_FOUND" ]; then
    [ -n "$REASON" ] && REASON="$REASON "
    REASON="${REASON}Not found (may already be removed): ${NOT_FOUND%, }."
  fi
  REASON_ESCAPED=$(echo "$REASON" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read().strip()))" 2>/dev/null || echo "\"Deletion blocked inside Alive world.\"")
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":${REASON_ESCAPED}}}"
  exit 0
fi

exit 0
