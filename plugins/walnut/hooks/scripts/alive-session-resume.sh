#!/bin/bash
# Hook: Session Resume — SessionStart (resume)
# Reads squirrel entry by session_id, re-injects rules + stash + preferences.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/walnut-common.sh"

read_hook_input
read_session_fields
find_world || { echo "No Walnut world found."; exit 0; }

SESSION_ID="${HOOK_SESSION_ID}"

# Resolve preferences
source "$SCRIPT_DIR/walnut-resolve-preferences.sh"
PREFS=$(resolve_preferences "$WORLD_ROOT")

# Plugin root for reading rules
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# Build runtime rules from plugin source files (same as session-new)
RUNTIME_RULES=""
RULE_COUNT=0
RULE_NAMES=""

if [ -f "$PLUGIN_ROOT/CLAUDE.md" ]; then
  RUNTIME_RULES=$(cat "$PLUGIN_ROOT/CLAUDE.md")
fi

for rule_file in "$PLUGIN_ROOT/rules/"*.md; do
  if [ -f "$rule_file" ]; then
    RULE_COUNT=$((RULE_COUNT + 1))
    RULE_NAME=$(basename "$rule_file" .md)
    RULE_NAMES="${RULE_NAMES}${RULE_NAMES:+, }${RULE_NAME}"
    RUNTIME_RULES="${RUNTIME_RULES}

$(cat "$rule_file")"
  fi
done

# Preamble
PREAMBLE="<EXTREMELY_IMPORTANT>
The following are your core operating rules for the Walnut system. They are MANDATORY — not suggestions, not defaults, not guidelines. You MUST follow them in every response, every tool call, every session.
</EXTREMELY_IMPORTANT>"

# Self-heal statusline — ensure settings.json has absolute path
SETTINGS_DIR="$WORLD_ROOT/.claude"
SETTINGS_FILE="$SETTINGS_DIR/settings.json"
mkdir -p "$SETTINGS_DIR"
if [ ! -f "$SETTINGS_FILE" ]; then
  cat > "$SETTINGS_FILE" << SETTINGSEOF
{
  "statusLine": {
    "type": "command",
    "command": "$WORLD_ROOT/.walnut/statusline.sh"
  }
}
SETTINGSEOF
else
  if command -v python3 &>/dev/null; then
    WALNUT_SETTINGS_FILE="$SETTINGS_FILE" WALNUT_WORLD_ROOT="$WORLD_ROOT" python3 -c "
import json, os, sys
sf = os.environ['WALNUT_SETTINGS_FILE']
wr = os.environ['WALNUT_WORLD_ROOT']
expected = wr + '/.walnut/statusline.sh'
try:
    with open(sf) as f:
        data = json.load(f)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
current = data.get('statusLine', {}).get('command', '')
if current != expected:
    data['statusLine'] = {'type': 'command', 'command': expected}
    with open(sf, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
" 2>/dev/null || true
  fi
fi

# Find squirrel entry by session_id (exact match) or fall back to most recent unsigned
SQUIRRELS_DIR="$WORLD_ROOT/.walnut/_squirrels"
ENTRY=""
if [ -n "$SESSION_ID" ] && [ -f "$SQUIRRELS_DIR/$SESSION_ID.yaml" ]; then
  ENTRY="$SQUIRRELS_DIR/$SESSION_ID.yaml"
elif [ -d "$SQUIRRELS_DIR" ]; then
  ENTRY=$(grep -rl 'ended: null' "$SQUIRRELS_DIR/"*.yaml 2>/dev/null | head -1)
fi

SESSION_MSG=""
if [ -n "$ENTRY" ] && [ -f "$ENTRY" ]; then
  ENTRY_SESSION_ID=$(grep '^session_id:' "$ENTRY" | head -1 | sed 's/session_id: *//' || true)
  WALNUT=$(grep '^walnut:' "$ENTRY" | head -1 | sed 's/walnut: *//' || true)

  # Only show stash if this entry was never saved (saves: 0) — saved stash items were already routed
  SAVES=$(grep '^saves:' "$ENTRY" | head -1 | sed 's/saves: *//' | tr -d '[:space:]' || echo "0")
  if [ "$SAVES" = "0" ]; then
    STASH=$(awk '/^stash:/{found=1; next} found && /^[a-z]/{found=0} found && /content:/{gsub(/.*content: *"?/,""); gsub(/"$/,""); print "- " $0}' "$ENTRY" 2>/dev/null || true)
  else
    STASH=""
  fi
  if [ -z "${STASH:-}" ]; then
    STASH="(empty)"
  fi

  SESSION_MSG="Walnut session resumed. Session ID: ${ENTRY_SESSION_ID:-unknown}
World: $WORLD_ROOT
Walnut: ${WALNUT:-none}
Model: $HOOK_MODEL
$PREFS
Rules: ${RULE_COUNT} loaded (${RULE_NAMES})
Previous stash:
$STASH"
else
  SESSION_MSG="Walnut session resumed. No matching entry found — clean start.
World: $WORLD_ROOT
Model: $HOOK_MODEL
$PREFS
Rules: ${RULE_COUNT} loaded (${RULE_NAMES})"
fi

# Escape and combine
SESSION_MSG_ESCAPED=$(escape_for_json "$SESSION_MSG")
PREAMBLE_ESCAPED=$(escape_for_json "$PREAMBLE")
RUNTIME_ESCAPED=$(escape_for_json "$RUNTIME_RULES")

CONTEXT="${SESSION_MSG_ESCAPED}\n\n${PREAMBLE_ESCAPED}\n\n${RUNTIME_ESCAPED}"

# Output JSON with additionalContext
cat <<HOOKEOF
{
  "additional_context": "${CONTEXT}",
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "${CONTEXT}"
  }
}
HOOKEOF

exit 0
