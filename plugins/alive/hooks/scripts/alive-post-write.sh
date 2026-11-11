#!/bin/bash
# Hook: Post Write -- PostToolUse (Write|Edit)
# Three jobs:
# 1. Track write activity for statusline display
# 2. Run project.py when log.md is written (generates now.json)
# 3. Regenerate world index after save (detected by _kernel/now.json write)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input

# fn-15-la5.6: bridge fan-out -- helper is the SOLE emitter on the
# no-world-found path.
# // TODO(world-resolution-contract-v2): swap to find_world_or_die in cutover release
if ! find_world_or_warn "${HOOK_EVENT:-PostToolUse}"; then
  exit 0
fi

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

# Run project.py when log.md is written (save protocol always writes log entry)
# Chain: log.md write -> project.py -> now.json write -> generate-index.py
# MSYS form (/c/...) on Windows, so the walk below can stop at WORLD_ROOT;
# converted back to C:/... only where it is handed to native Python.
FILE_PATH=$(hook_file_path)
case "$FILE_PATH" in
  */log.md)
    PROJECTOR="${CLAUDE_PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}/scripts/project.py"
    if [ -f "$PROJECTOR" ]; then
      # Extract walnut path by walking up from written file until finding _kernel/ parent
      WALNUT_PATH=""
      CHECK_DIR="$(dirname "$FILE_PATH")"
      while [ -n "$CHECK_DIR" ] && [ "$CHECK_DIR" != "/" ] && [ "$CHECK_DIR" != "$WORLD_ROOT" ]; do
        if [ "$(basename "$CHECK_DIR")" = "_kernel" ]; then
          WALNUT_PATH="$(dirname "$CHECK_DIR")"
          break
        fi
        PARENT_DIR="$(dirname "$CHECK_DIR")"
        # Stop when dirname stops changing ("C:" or "." on Windows never reach "/").
        [ "$PARENT_DIR" = "$CHECK_DIR" ] || [ "$PARENT_DIR" = "." ] && break
        CHECK_DIR="$PARENT_DIR"
      done
      if [ -n "$WALNUT_PATH" ]; then
        # Debounce -- skip if we ran project.py for this walnut in the last 5 minutes
        # cksum is POSIX and always present. The old md5sum-or-md5 chain
        # produced an empty hash where md5sum was missing (the pipeline's
        # status is cut's), so every walnut shared one marker.
        WALNUT_HASH=$(printf '%s' "$WALNUT_PATH" | cksum | cut -d' ' -f1)
        MARKER="/tmp/alive-project-${WALNUT_HASH}"
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
        # Background -- don't block the session
        if [ "$ALIVE_JSON_RT" = "python3" ]; then
          python3 "$PROJECTOR" --walnut "$(alive_native_path "$WALNUT_PATH")" > /dev/null 2>&1 &
        fi
      fi
    fi
    ;;
esac

# Regenerate world index after save OR after a write that lands in 03_Inbox/.
# now.json is the canonical save trigger; 03_Inbox writes are added so
# agent-driven captures don't leave the index stale until the next save.
# Files dragged into 03_Inbox/ outside of Claude Code (Finder, scripts) still
# rely on the session-start refresh in alive-session-new.sh -- there's no tool
# event for those.
case "$FILE_PATH" in
  */_kernel/now.json|*/_kernel/_generated/now.json|*/_kernel/now.md|*/03_Inbox/*)
    GENERATOR="${CLAUDE_PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}/scripts/generate-index.py"
    if [ -f "$GENERATOR" ]; then
      # Debounce -- skip if we regenerated in the last 5 minutes
      # Per user and per world, so two worlds (or two users) don't share
      # one debounce window. Must match alive-session-new.sh.
      MARKER="/tmp/alive-index-regen-$(id -u 2>/dev/null || echo 0)-$(printf '%s' "$WORLD_ROOT" | cksum | cut -d' ' -f1)"
      if [ -f "$MARKER" ]; then
        if stat --version >/dev/null 2>&1; then
          MARKER_MTIME=$(stat -c %Y "$MARKER" 2>/dev/null || echo "0")
        else
          MARKER_MTIME=$(stat -f %m "$MARKER" 2>/dev/null || echo "0")
        fi
        AGE=$(( $(date +%s) - MARKER_MTIME ))
        [ "$AGE" -lt 300 ] && exit 0
      fi
      touch "$MARKER" 2>/dev/null || true
      # Background -- don't block the session
      # generate-index.py requires python3; skip on node-only systems (non-critical)
      if [ "$ALIVE_JSON_RT" = "python3" ]; then
        python3 "$GENERATOR" "$(alive_native_path "$WORLD_ROOT")" > /dev/null 2>&1 &
      fi
    fi
    ;;
esac

exit 0
