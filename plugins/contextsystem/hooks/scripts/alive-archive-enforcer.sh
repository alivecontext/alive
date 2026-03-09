#!/bin/bash
# Hook: Archive Enforcer — PreToolUse (Bash)
# Blocks rm/rmdir/unlink when targeting files inside the ALIVE world.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
find_world || exit 0

COMMAND=$(echo "$HOOK_INPUT" | jq -r '.tool_input.command // empty')

# Check for destructive commands
if ! echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)(rm|rmdir|unlink)\s'; then
  exit 0
fi

# Extract target paths after the rm/rmdir/unlink command
TARGET=$(echo "$COMMAND" | sed -E 's/.*\b(rm|rmdir|unlink)\s+(-[^ ]+ )*//' | tr ' ' '\n' | grep -v '^-')

# Use cwd from JSON input for resolving relative paths
RESOLVE_DIR="${HOOK_CWD:-$PWD}"

while IFS= read -r path; do
  [ -z "$path" ] && continue

  # Resolve relative paths against the session's cwd
  if [[ "$path" != /* ]]; then
    resolved="$RESOLVE_DIR/$path"
  else
    resolved="$path"
  fi

  # Check if resolved path is inside the World
  case "$resolved" in
    "$WORLD_ROOT"/01_Archive/*|"$WORLD_ROOT"/02_Life/*|"$WORLD_ROOT"/03_Inputs/*|"$WORLD_ROOT"/04_Ventures/*|"$WORLD_ROOT"/05_Experiments/*|"$WORLD_ROOT"/_core/*|"$WORLD_ROOT"/.alive/*)
      echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Deletion blocked inside ALIVE folders. Archive instead — move to 01_Archive/."}}'
      exit 0
      ;;
  esac
done <<< "$TARGET"

exit 0
