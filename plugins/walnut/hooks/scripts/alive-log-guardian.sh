#!/bin/bash
# Hook: Log Guardian — PreToolUse (Edit|Write)
# Blocks edits to signed log entries. Blocks all Write to log.md.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/walnut-common.sh"

read_hook_input
find_world || exit 0

TOOL_NAME=$(json_field "tool_name")
FILE_PATH=$(json_field "tool_input.file_path")

# Only care about log.md files inside walnuts (either _core/log.md or root-level log.md)
# Match: any path containing a walnut folder with log.md at _core/ or root level
if ! echo "$FILE_PATH" | grep -qE '(_core/log\.md$|/[^/]+/log\.md$)'; then
  exit 0
fi

# Skip if it's not inside a Walnut world
if [ -n "${WORLD_ROOT:-}" ] && ! echo "$FILE_PATH" | grep -q "^$WORLD_ROOT"; then
  exit 0
fi

# Block ALL Write operations to log.md (must use Edit to prepend)
if [ "$TOOL_NAME" = "Write" ]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"log.md cannot be overwritten. Use Edit to prepend new entries after the YAML frontmatter."}}'
  exit 0
fi

# For Edit: check if the old_string contains a signed entry
OLD_STRING=$(json_field "tool_input.old_string")

if echo "$OLD_STRING" | grep -qE 'signed: (squirrel:|walnut-mcp:)'; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"log.md is immutable. That entry is signed — add a correction entry instead."}}'
  exit 0
fi

exit 0
