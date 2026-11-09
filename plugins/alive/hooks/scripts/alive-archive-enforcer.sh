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

# Extract target paths using Python for reliable parsing
# Handles: quoted paths, spaces in filenames, flags, chained commands, multiple targets
# The script is single-quoted: the old double-quoted version closed its own
# string at decode("utf-8",...), so Python got decode(utf-8,replace), raised
# NameError, and TARGET was always empty (REPORT.md risk 13).
# Still UNREGISTERED in hooks.json -- do not enable without a review.
[ "$ALIVE_JSON_RT" = "python3" ] || exit 0
TARGET=$(printf '%s' "$COMMAND" | python3 -c '
import sys, shlex, re
cmd = sys.stdin.buffer.read().decode("utf-8", "replace").strip()
for part in re.split(r"[;&|]+", cmd):
    part = part.strip()
    try:
        tokens = shlex.split(part, posix=True)
    except ValueError:
        tokens = part.split()
    found = False
    for t in tokens:
        if not found:
            if t in ("rm", "rmdir", "unlink"):
                found = True
            continue
        if not t.startswith("-"):
            print(t)
' 2>/dev/null)

# Use cwd from JSON input for resolving relative paths
RESOLVE_DIR="${HOOK_CWD:-$PWD}"

# Process ALL targets -- rename every World file, then deny once
RENAMED=""
NOT_FOUND=""

while IFS= read -r path; do
  [ -z "$path" ] && continue

  # Windows: C:\x and C:/x are absolute too. Take everything to MSYS form
  # (/c/x) first, then resolve relative paths against the session's cwd.
  path="$(alive_msys_path "$path")"
  if [[ "$path" != /* ]]; then
    resolved="$(alive_msys_path "$RESOLVE_DIR")/$path"
  else
    resolved="$path"
  fi

  # Check if resolved path is inside the World (protect entire root, not just subdirs)
  # Resolve ".." lexically so /world/../elsewhere is not read as inside.
  resolved="$(lexical_normalize_path "$resolved" 2>/dev/null || printf '%s' "$resolved")"
  resolved="$(alive_match_world_case "$resolved")"
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
  REASON_ESCAPED=$(escape_for_json "$REASON")
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"${REASON_ESCAPED}\"}}"
  exit 0
fi

exit 0
