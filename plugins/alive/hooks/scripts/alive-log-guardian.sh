#!/bin/bash
# Hook: Log Guardian — PreToolUse (Edit|Write)
# Blocks edits to signed log entries. Blocks all Write to log.md.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
find_world || exit 0

TOOL_NAME=$(echo "$HOOK_INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$HOOK_INPUT" | jq -r '.tool_input.file_path // empty')

# Only care about log.md files inside _core/
if ! echo "$FILE_PATH" | grep -q '_core/log\.md$'; then
  exit 0
fi

# Block ALL Write operations to log.md (must use Edit to prepend)
if [ "$TOOL_NAME" = "Write" ]; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"log.md cannot be overwritten. Use Edit to prepend new entries after the YAML frontmatter."}}'
  exit 0
fi

# For Edit: check if the old_string contains a signed entry
OLD_STRING=$(echo "$HOOK_INPUT" | jq -r '.tool_input.old_string // empty')

if echo "$OLD_STRING" | grep -q 'signed: squirrel:'; then
  echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"log.md is immutable. That entry is signed — add a correction entry instead."}}'
  exit 0
fi

exit 0
