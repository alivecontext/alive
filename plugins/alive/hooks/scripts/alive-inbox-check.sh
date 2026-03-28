#!/bin/bash
# Hook: Inbox Check -- PostToolUse (Write|Edit)
# When now.json is written (typically during save), check 03_Inputs/ for unrouted items.
# If items exist, nudge the squirrel via additionalContext. Silent otherwise.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
find_world || exit 0

# Only fire when the written file is now.json or now.md
FILE_PATH=$(json_field "tool_input.file_path")

case "$FILE_PATH" in
  */now.json|*/now.md) ;;
  *) exit 0 ;;
esac

# Count non-system files in 03_Inputs/
INPUTS_DIR="$WORLD_ROOT/03_Inputs"
[ -d "$INPUTS_DIR" ] || exit 0

COUNT=0
while IFS= read -r -d '' entry; do
  name="$(basename "$entry")"
  case "$name" in
    .DS_Store|.gitkeep|.keep) continue ;;
  esac
  COUNT=$((COUNT + 1))
done < <(find "$INPUTS_DIR" -mindepth 1 -maxdepth 1 -print0 2>/dev/null)

[ "$COUNT" -eq 0 ] && exit 0

# Nudge the squirrel
NUDGE="Inbox has ${COUNT} item(s) in 03_Inputs/. If the human isn't in the middle of something, suggest running alive:capture-context to clear the inbox."
ESCAPED=$(escape_for_json "$NUDGE")

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "${ESCAPED}"
  }
}
EOF

exit 0
