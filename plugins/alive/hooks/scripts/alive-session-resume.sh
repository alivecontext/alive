#!/bin/bash
# Hook: Session Resume -- SessionStart (resume)
# Reads squirrel entry by session_id, re-injects rules + stash + preferences.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
read_session_fields

# fn-15-la5.6: bridge fan-out -- helper is the SOLE emitter on the
# no-world-found path. Previously echoed "No Alive world found." which
# was not valid hook JSON.
# // TODO(world-resolution-contract-v2): swap to find_world_or_die in cutover release
if ! find_world_or_warn "${HOOK_EVENT:-SessionStart}"; then
  exit 0
fi

SESSION_ID="${HOOK_SESSION_ID}"
if [ -z "$SESSION_ID" ]; then
  SESSION_ID=$(head -c 16 /dev/urandom 2>/dev/null | (shasum 2>/dev/null || sha256sum 2>/dev/null || md5sum 2>/dev/null || od -A n -t x1 | tr -d ' \n') | head -c 8)
fi

# fn-15-la5.6: env-file mirror parity with alive-session-new.sh. Today
# only alive-session-new.sh writes the env-file mirror, so resumed
# sessions saw inconsistent ALIVE_WORLD_ROOT_SOURCE state vs fresh
# sessions and downstream tools that read $ALIVE_WORLD_ROOT got nothing
# on resume. ALIVE_WORLD_ROOT_SOURCE=session is the migration-hint
# discriminator (T7) that distinguishes "user-set in shell" from
# "session-mirrored by hook"; both startup and resume must write it.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  alive_write_env_var "ALIVE_WORLD_ROOT" "$WORLD_ROOT" "$CLAUDE_ENV_FILE"
  alive_write_env_var "ALIVE_WORLD_ROOT_SOURCE" "session" "$CLAUDE_ENV_FILE"
fi

# Resolve preferences
source "$SCRIPT_DIR/alive-resolve-preferences.sh"
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
PREAMBLE="<ALIVE_RULES>
These are the operating rules of the ALIVE plugin the person installed. Follow them for work inside this world. The person's own instructions come first.
</ALIVE_RULES>"

# Self-heal statusline -- ensure settings.json has absolute path
SETTINGS_DIR="$WORLD_ROOT/.claude"
SETTINGS_FILE="$SETTINGS_DIR/settings.json"
mkdir -p "$SETTINGS_DIR"
if [ ! -f "$SETTINGS_FILE" ]; then
  cmd_json="$(alive_json_encode_string "$WORLD_ROOT/.alive/statusline.sh")"
  cat > "$SETTINGS_FILE" << SETTINGSEOF
{
  "statusLine": {
    "type": "command",
    "command": $cmd_json
  }
}
SETTINGSEOF
else
  if [ "$ALIVE_JSON_RT" = "python3" ]; then
    ALIVE_SETTINGS_FILE="$SETTINGS_FILE" ALIVE_WORLD_ROOT="$WORLD_ROOT" python3 -c '
import json, os, sys
sf = os.environ["ALIVE_SETTINGS_FILE"]
wr = os.environ["ALIVE_WORLD_ROOT"]
expected = wr + "/.alive/statusline.sh"
try:
    with open(sf) as f:
        data = json.load(f)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
current = data.get("statusLine", {}).get("command", "")
if current != expected:
    data["statusLine"] = {"type": "command", "command": expected}
    with open(sf, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
' 2>/dev/null || true
  elif [ "$ALIVE_JSON_RT" = "node" ]; then
    ALIVE_SETTINGS_FILE="$SETTINGS_FILE" ALIVE_WORLD_ROOT="$WORLD_ROOT" node -e '
const fs=require("fs");
const sf=process.env.ALIVE_SETTINGS_FILE;
const wr=process.env.ALIVE_WORLD_ROOT;
const expected=wr+"/.alive/statusline.sh";
let data;
try{data=JSON.parse(fs.readFileSync(sf,"utf8"))}catch(e){process.exit(0)}
const current=(data.statusLine||{}).command||"";
if(current!==expected){data.statusLine={type:"command",command:expected};fs.writeFileSync(sf,JSON.stringify(data,null,2)+"\n")}
' 2>/dev/null || true
  fi
fi

# Resume only the exact Claude session. If its record is missing, recreate a
# clean record rather than borrowing context from another active session.
SQUIRRELS_DIR="$WORLD_ROOT/.alive/_squirrels"
mkdir -p "$SQUIRRELS_DIR"
ENTRY="$SQUIRRELS_DIR/$SESSION_ID.yaml"
RECOVERED_ENTRY=""
if [ ! -f "$ENTRY" ]; then
  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S")
  ENTRY_TMP="${ENTRY}.tmp.$$"
  trap 'rm -f "$ENTRY_TMP"' EXIT
  cat > "$ENTRY_TMP" << EOF
session_id: $SESSION_ID
runtime_id: squirrel.core@1.0
engine: $HOOK_MODEL
walnut: null
started: $TIMESTAMP
ended: null
saves: 0
last_saved: null
transcript: ${HOOK_TRANSCRIPT}
cwd: ${HOOK_CWD}
rules_loaded: $RULE_COUNT
tags: []
stash: []
working: []
EOF
  mv "$ENTRY_TMP" "$ENTRY"
  trap - EXIT
  RECOVERED_ENTRY="1"
fi

SESSION_MSG=""
if [ -n "$ENTRY" ] && [ -f "$ENTRY" ]; then
  ENTRY_SESSION_ID=$(grep '^session_id:' "$ENTRY" | head -1 | sed 's/session_id: *//' || true)
  WALNUT=$(grep '^walnut:' "$ENTRY" | head -1 | sed 's/walnut: *//' || true)

  # Only show stash if this entry was never saved (saves: 0) -- saved stash items were already routed
  SAVES=$(grep '^saves:' "$ENTRY" | head -1 | sed 's/saves: *//' | tr -d '[:space:]' || echo "0")
  if [ "$SAVES" = "0" ]; then
    STASH=$(awk '/^stash:/{found=1; next} found && /^[a-z]/{found=0} found && /content:/{gsub(/.*content: *"?/,""); gsub(/"$/,""); print "- " $0}' "$ENTRY" 2>/dev/null || true)
  else
    STASH=""
  fi
  if [ -z "${STASH:-}" ]; then
    STASH="(empty)"
  fi

  if [ -n "$RECOVERED_ENTRY" ]; then
    SESSION_MSG="Alive session resumed. Missing session record recreated for: ${ENTRY_SESSION_ID:-unknown}
World: $WORLD_ROOT
Walnut: none
Model: $HOOK_MODEL
$PREFS
Rules: ${RULE_COUNT} loaded (${RULE_NAMES})"
  else
    SESSION_MSG="Alive session resumed. Session ID: ${ENTRY_SESSION_ID:-unknown}
World: $WORLD_ROOT
Walnut: ${WALNUT:-none}
Model: $HOOK_MODEL
$PREFS
Rules: ${RULE_COUNT} loaded (${RULE_NAMES})
Previous stash:
$STASH"
  fi
else
  SESSION_MSG="Alive session resumed. No matching entry found -- clean start.
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
