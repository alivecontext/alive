#!/bin/bash
# alive-common.sh -- shared functions for all ALIVE Context System hooks.
# Source this at the top of every hook script.
# Cross-platform: python3 (Mac/Linux) with node fallback (Windows/all).

# -- Platform detection --
ALIVE_PLATFORM="unix"
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
  ALIVE_PLATFORM="windows"
fi

# -- JSON runtime detection --
# python3 preferred (fast). node guaranteed (Claude Code is a Node app).
# Windows ships a python3 Store stub (AppInstallerPythonRedirector.exe) that
# passes command -v but fails to execute (exit code 49). We validate execution,
# not just existence. The py -3 launcher is the standard Windows Python path.
ALIVE_JSON_RT=""
if command -v python3 &>/dev/null && python3 -c "" &>/dev/null 2>&1; then
  ALIVE_JSON_RT="python3"
elif command -v py &>/dev/null && py -3 -c "" &>/dev/null 2>&1; then
  # Windows py launcher: shim python3 so all existing callsites work
  python3() { py -3 "$@"; }
  export -f python3
  ALIVE_JSON_RT="python3"
elif command -v node &>/dev/null; then
  ALIVE_JSON_RT="node"
fi

# -- JSON parsing helpers --
# All JSON parsing goes through python3 or node. Never sed/regex.

# Parse multiple fields from JSON in one call.
# Usage: _json_multi "$json" "key1 key2 key3" (outputs one value per line)
_json_multi() {
  local json="$1" keys="$2"
  if [ "$ALIVE_JSON_RT" = "python3" ]; then
    printf '%s' "$json" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for k in '''$keys'''.split():
    v=d
    for p in k.split('.'):
        v=v.get(p,'') if isinstance(v,dict) else ''
    print(v if v else '')
" 2>/dev/null || echo ""
  elif [ "$ALIVE_JSON_RT" = "node" ]; then
    printf '%s' "$json" | node -e "
const d=JSON.parse(require('fs').readFileSync(0,'utf8'));
'$keys'.split(' ').forEach(k=>{
  let v=d;k.split('.').forEach(p=>{v=v&&typeof v==='object'?v[p]||'':''});
  console.log(v||'')
})" 2>/dev/null || echo ""
  else
    # No runtime -- return empty (should never happen with Claude Code)
    for _ in $keys; do echo ""; done
  fi
}

# Read JSON input from stdin. Must be called BEFORE any other stdin read.
# Sets: HOOK_INPUT, HOOK_SESSION_ID, HOOK_CWD, HOOK_EVENT
read_hook_input() {
  HOOK_INPUT=$(cat 2>/dev/null || echo '{}')
  local parsed
  parsed=$(_json_multi "$HOOK_INPUT" "session_id cwd hook_event_name")
  HOOK_SESSION_ID=$(echo "$parsed" | sed -n '1p')
  HOOK_CWD=$(echo "$parsed" | sed -n '2p')
  HOOK_EVENT=$(echo "$parsed" | sed -n '3p')
}

# SessionStart-specific fields. Call after read_hook_input.
# Sets: HOOK_MODEL, HOOK_SOURCE, HOOK_TRANSCRIPT
read_session_fields() {
  local parsed
  parsed=$(_json_multi "$HOOK_INPUT" "model source transcript_path")
  HOOK_MODEL=$(echo "$parsed" | sed -n '1p')
  : "${HOOK_MODEL:=unknown}"
  HOOK_SOURCE=$(echo "$parsed" | sed -n '2p')
  HOOK_TRANSCRIPT=$(echo "$parsed" | sed -n '3p')
}

# Extract a single JSON field (flat or nested dot-path).
# Usage: json_field "tool_name" or json_field "tool_input.file_path"
json_field() {
  _json_multi "$HOOK_INPUT" "$1" | head -1
}

# PreToolUse-specific fields. Call after read_hook_input.
# Sets: HOOK_TOOL_NAME, HOOK_TOOL_INPUT
read_tool_fields() {
  HOOK_TOOL_NAME=$(json_field "tool_name")
  HOOK_TOOL_INPUT="$HOOK_INPUT"
}

# Migrate legacy paths if needed.
# Called after WORLD_ROOT is set. Returns 0 if migration happened, 1 if not needed.
migrate_legacy_to_alive() {
  local world_root="$1"
  local old_walnut_dir="$world_root/.walnut"
  local new_dir="$world_root/.alive"

  # Check for legacy .walnut/ dir
  if [ -d "$old_walnut_dir" ] && [ ! -d "$new_dir" ]; then
    mv "$old_walnut_dir" "$new_dir" 2>/dev/null || return 1
    export ALIVE_MIGRATED_FROM="walnut"
    return 0
  fi

  # Both exist -- flag for manual resolution
  if [ -d "$old_walnut_dir" ] && [ -d "$new_dir" ]; then
    export ALIVE_MIGRATION_CONFLICT="both_exist"
    return 1
  fi

  return 1
}

# Find the world root.
# Strategy: walk up from cwd (Claude Code), then check mounted folders (Cowork).
# Sets: WORLD_ROOT or returns 1 if not found.
find_world() {
  local dir="${HOOK_CWD:-${CLAUDE_PROJECT_DIR:-$PWD}}"

  # Walk up from cwd -- standard Claude Code path
  local check="$dir"
  while [ "$check" != "/" ]; do
    if [ -d "$check/01_Archive" ] && [ -d "$check/02_Life" ]; then
      WORLD_ROOT="$check"
      # Auto-migrate legacy paths if needed
      migrate_legacy_to_alive "$WORLD_ROOT" || true
      return 0
    fi
    check="$(dirname "$check")"
  done

  # Config file fallback -- world-root stored at install time
  local config_file="${HOME}/.config/alive/world-root"
  # Also check old config locations
  if [ ! -f "$config_file" ] && [ -f "${HOME}/.config/walnut/world-root" ]; then
    config_file="${HOME}/.config/walnut/world-root"
  fi
  if [ -f "$config_file" ]; then
    local stored_root
    stored_root=$(cat "$config_file" | tr -d '[:space:]')
    if [ -d "$stored_root/01_Archive" ] && [ -d "$stored_root/02_Life" ]; then
      WORLD_ROOT="$stored_root"
      migrate_legacy_to_alive "$WORLD_ROOT" || true
      return 0
    fi
  fi

  # Env var fallback -- set by previous session hook
  if [ -n "${ALIVE_WORLD_ROOT:-}" ]; then
    if [ -d "$ALIVE_WORLD_ROOT/01_Archive" ] && [ -d "$ALIVE_WORLD_ROOT/02_Life" ]; then
      WORLD_ROOT="$ALIVE_WORLD_ROOT"
      return 0
    fi
  fi

  # Cowork fallback -- user folder is mounted under $HOME/mnt/<name>/
  if [ "${CLAUDE_CODE_IS_COWORK:-}" = "1" ]; then
    local mnt_dir="${HOME:-$dir}/mnt"
    if [ -d "$mnt_dir" ]; then
      for candidate in "$mnt_dir"/*/; do
        if [ -d "$candidate/01_Archive" ] && [ -d "$candidate/02_Life" ]; then
          WORLD_ROOT="${candidate%/}"
          migrate_legacy_to_alive "$WORLD_ROOT" || true
          return 0
        fi
      done
    fi
  fi

  return 1
}

# Escape string for JSON embedding.
# Large strings (>1KB) go through python3/node for proper Unicode handling.
# Small strings use bash (fast, ASCII-safe).
escape_for_json() {
  if [ ${#1} -gt 1000 ]; then
    if [ "$ALIVE_JSON_RT" = "python3" ]; then
      printf '%s' "$1" | python3 -c "import sys,json; sys.stdout.buffer.write(json.dumps(sys.stdin.buffer.read().decode('utf-8','replace'))[1:-1].encode('utf-8'))"
    elif [ "$ALIVE_JSON_RT" = "node" ]; then
      printf '%s' "$1" | node -e "let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(d).slice(1,-1)))"
    else
      # Fallback: bash escaping (correct but slow for large strings)
      local s="$1"
      s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//$'\n'/\\n}"; s="${s//$'\r'/\\r}"; s="${s//$'\t'/\\t}"
      printf '%s' "$s"
    fi
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
