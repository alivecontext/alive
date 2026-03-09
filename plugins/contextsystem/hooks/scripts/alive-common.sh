#!/bin/bash
# alive-common.sh — shared functions for all ALIVE hooks.
# Source this at the top of every hook script.

# Read JSON input from stdin. Must be called BEFORE any other stdin read.
# Sets: HOOK_INPUT, HOOK_SESSION_ID, HOOK_CWD, HOOK_EVENT
read_hook_input() {
  HOOK_INPUT=$(cat /dev/stdin 2>/dev/null || echo '{}')
  HOOK_SESSION_ID=$(echo "$HOOK_INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null || echo "")
  HOOK_CWD=$(echo "$HOOK_INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null || echo "")
  HOOK_EVENT=$(echo "$HOOK_INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('hook_event_name',''))" 2>/dev/null || echo "")
}

# SessionStart-specific fields. Call after read_hook_input.
# Sets: HOOK_MODEL, HOOK_SOURCE, HOOK_TRANSCRIPT
read_session_fields() {
  HOOK_MODEL=$(echo "$HOOK_INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('model','unknown'))" 2>/dev/null || echo "unknown")
  HOOK_SOURCE=$(echo "$HOOK_INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('source',''))" 2>/dev/null || echo "")
  HOOK_TRANSCRIPT=$(echo "$HOOK_INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('transcript_path',''))" 2>/dev/null || echo "")
}

# PreToolUse-specific fields. Call after read_hook_input.
# Sets: HOOK_TOOL_NAME, HOOK_TOOL_INPUT
read_tool_fields() {
  HOOK_TOOL_NAME=$(echo "$HOOK_INPUT" | jq -r '.tool_name // empty')
  HOOK_TOOL_INPUT="$HOOK_INPUT"
}

# Find the ALIVE world root by walking up from cwd.
# Sets: WORLD_ROOT or returns 1 if not found.
find_world() {
  local dir="${HOOK_CWD:-${CLAUDE_PROJECT_DIR:-$PWD}}"
  while [ "$dir" != "/" ]; do
    if [ -d "$dir/01_Archive" ] && [ -d "$dir/02_Life" ]; then
      WORLD_ROOT="$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

# Escape string for JSON embedding.
# Uses python3 for strings over 1KB (bash is O(n^2) on large strings).
escape_for_json() {
  if [ ${#1} -gt 1000 ]; then
    printf '%s' "$1" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read())[1:-1], end='')"
  else
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
  fi
}
