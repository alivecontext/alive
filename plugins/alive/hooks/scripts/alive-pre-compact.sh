#!/bin/bash
# Hook: PreCompact
# Writes compaction timestamp to the current session's squirrel YAML.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
find_world || exit 0

SESSION_ID="${HOOK_SESSION_ID}"
SQUIRRELS_DIR="$WORLD_ROOT/.alive/_squirrels"
[ ! -d "$SQUIRRELS_DIR" ] && exit 0

# Find entry by session_id (exact match) or fall back to most recent unsigned
ENTRY=""
if [ -n "$SESSION_ID" ] && [ -f "$SQUIRRELS_DIR/$SESSION_ID.yaml" ]; then
  ENTRY="$SQUIRRELS_DIR/$SESSION_ID.yaml"
else
  ENTRY=$(ls -t "$SQUIRRELS_DIR/"*.yaml 2>/dev/null | while read -r f; do
    grep -q 'ended: null' "$f" 2>/dev/null && echo "$f" && break
  done || true)
fi

[ -z "${ENTRY:-}" ] && exit 0

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S")

if ! grep -q 'compacted:' "$ENTRY"; then
  echo "compacted: $TIMESTAMP" >> "$ENTRY"
else
  if sed --version >/dev/null 2>&1; then
    sed -i "s/compacted:.*/compacted: $TIMESTAMP/" "$ENTRY"
  else
    sed -i '' "s/compacted:.*/compacted: $TIMESTAMP/" "$ENTRY"
  fi
fi

exit 0
