#!/usr/bin/env bash
# Windows hook smoke test, run by .github/workflows/windows.yml under Git Bash.
# Feeds the hooks the native C:\... paths Claude Code sends on Windows and
# checks each one answers correctly and in time.
#
#   bash tests/windows/hook-smoke.sh            # Python present: hooks work
#   bash tests/windows/hook-smoke.sh --no-python # Python hidden: clear notice
#
# Meant for Windows: it uses cygpath (Git for Windows ships it) to get native
# C:\ paths. Off Windows the guardian checks fail by design. Exits 1 if any
# check missed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLUGIN="$ROOT/plugins/alive"
HOOKS="$PLUGIN/hooks/scripts"
MODE="${1:-}"
FAILS=0

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '      %s\n' "$2"; FAILS=$((FAILS + 1)); }

# timeout(1) ships with Git for Windows coreutils; fall back to none elsewhere.
cap() { local secs="$1"; shift; if command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"; else "$@"; fi; }
PYJSON="$(command -v python3 || command -v python || true)"

json_escape() { local s="${1//\\/\\\\}"; printf '%s' "${s//\"/\\\"}"; }

TMP="$(mktemp -d)"
WORLD="$TMP/world"
mkdir -p "$WORLD/.alive/_squirrels" "$WORLD/04_Ventures/shop/_kernel"
for d in 01_Archive 02_Life 03_Inbox 05_Experiments; do mkdir -p "$WORLD/$d"; done
printf 'github_star_ask: false\n' > "$WORLD/.alive/preferences.yaml"
printf -- '---\nsummary: test\n---\n' > "$WORLD/04_Ventures/shop/_kernel/log.md"

if command -v cygpath >/dev/null 2>&1; then
  WIN_WORLD="$(cygpath -w "$WORLD")"        # C:\Users\...\world
else
  WIN_WORLD="$WORLD"                        # off Windows: mechanics check only
fi
WIN_LOG="$WIN_WORLD\\04_Ventures\\shop\\_kernel\\log.md"
export ALIVE_WORLD_ROOT_OVERRIDE="$WIN_WORLD"
export CLAUDE_PLUGIN_ROOT="$PLUGIN"
export CLAUDE_ENV_FILE="$TMP/claude-env"
export HOME="$TMP/home"; mkdir -p "$HOME"

echo "world (native): $WIN_WORLD"
echo "platform: OSTYPE=${OSTYPE:-} MSYSTEM=${MSYSTEM:-}"
for c in python3 py python node; do
  printf '%-8s %s\n' "$c" "$(command -v "$c" 2>/dev/null || echo '-')"
done

run_hook() { # script, payload -> stdout; 20s cap so a loop fails instead of hanging
  printf '%s' "$2" | cap 20 bash "$HOOKS/$1"
}

if [ "$MODE" = "--no-python" ]; then
  OUT="$(run_hook alive-session-new.sh "{\"session_id\":\"smoke\",\"cwd\":\"$(json_escape "$WIN_WORLD")\",\"hook_event_name\":\"SessionStart\",\"source\":\"startup\"}")"
  case "$OUT" in
    *"ALIVE needs Python 3"*) pass "session start says ALIVE needs Python 3" ;;
    *) fail "session start notice missing" "$OUT" ;;
  esac
  ERR="$(cap 20 bash "$PLUGIN/bin/alive" --help 2>&1 >/dev/null)"; RC=$?
  if [ "$RC" -eq 127 ] && [[ "$ERR" == *"ALIVE needs Python 3"* ]]; then
    pass "bin/alive exits 127 with the notice"
  else
    fail "bin/alive without Python (rc=$RC)" "$ERR"
  fi
else
  # Session start: valid JSON, world found from a native cwd.
  OUT="$(run_hook alive-session-new.sh "{\"session_id\":\"smoke\",\"cwd\":\"$(json_escape "$WIN_WORLD")\",\"hook_event_name\":\"SessionStart\",\"source\":\"startup\"}")"; RC=$?
  if [ "$RC" -eq 0 ] && printf '%s' "$OUT" | "$PYJSON" -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then
    pass "session start emits valid JSON"
  else
    fail "session start (rc=$RC)" "${OUT:0:400}"
  fi

  # Log guardian: Write to a C:\ log.md must be denied (REPORT risk 3).
  OUT="$(run_hook alive-log-guardian.sh "{\"session_id\":\"smoke\",\"cwd\":\"$(json_escape "$WIN_WORLD")\",\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$(json_escape "$WIN_LOG")\"}}")"
  case "$OUT" in *'"deny"'*) pass "log guardian denies Write to C:\\...\\log.md" ;; *) fail "log guardian let a C:\\ Write through" "$OUT" ;; esac

  # Same path in lower case: Windows paths ignore case.
  LOWER="$(printf '%s' "$WIN_LOG" | tr '[:upper:]' '[:lower:]')"
  OUT="$(run_hook alive-log-guardian.sh "{\"session_id\":\"smoke\",\"cwd\":\"$(json_escape "$WIN_WORLD")\",\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$(json_escape "$LOWER")\"}}")"
  case "$OUT" in *'"deny"'*) pass "log guardian ignores path case" ;; *) fail "log guardian missed lower-case path" "$OUT" ;; esac

  # Rules guardian: .alive\agents.md is plugin-managed.
  OUT="$(run_hook alive-rules-guardian.sh "{\"session_id\":\"smoke\",\"cwd\":\"$(json_escape "$WIN_WORLD")\",\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$(json_escape "$WIN_WORLD\\.alive\\agents.md")\"}}")"
  case "$OUT" in *'"deny"'*) pass "rules guardian denies .alive\\agents.md" ;; *) fail "rules guardian missed C:\\ path" "$OUT" ;; esac

  # Root guardian: a stray file at the world root.
  OUT="$(run_hook alive-root-guardian.sh "{\"session_id\":\"smoke\",\"cwd\":\"$(json_escape "$WIN_WORLD")\",\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$(json_escape "$WIN_WORLD\\stray.md")\"}}")"
  case "$OUT" in *'"deny"'*) pass "root guardian denies C:\\...\\stray.md" ;; *) fail "root guardian missed C:\\ path" "$OUT" ;; esac

  # Post-write: must finish (fixed-point guard), whatever the path.
  for fp in "$WIN_LOG" 'C:\elsewhere\log.md' 'D:\log.md'; do
    if run_hook alive-post-write.sh "{\"session_id\":\"smoke\",\"cwd\":\"$(json_escape "$WIN_WORLD")\",\"hook_event_name\":\"PostToolUse\",\"tool_input\":{\"file_path\":\"$(json_escape "$fp")\"}}" >/dev/null; then
      pass "post-write finishes for $fp"
    else
      fail "post-write did not finish for $fp"
    fi
  done

  # Statusline: #102, must end from a native subfolder cwd and find the world.
  OUT="$(printf '%s' "{\"session_id\":\"smoke\",\"cwd\":\"$(json_escape "$WIN_WORLD\\04_Ventures")\",\"model\":{\"display_name\":\"T\"},\"context_window\":{\"used_percentage\":7}}" | cap 20 bash "$PLUGIN/statusline/alive-statusline.sh")"; RC=$?
  if [ "$RC" -eq 0 ] && [[ "$OUT" != *"no world detected"* ]]; then
    pass "statusline ends and finds the world"
  else
    fail "statusline (rc=$RC)" "$OUT"
  fi

  # bin/alive runs the CLI.
  if cap 60 bash "$PLUGIN/bin/alive" --help >/dev/null 2>&1; then
    pass "bin/alive --help"
  else
    fail "bin/alive --help"
  fi
fi

echo "---"
if [ "$FAILS" -gt 0 ]; then
  echo "$FAILS smoke check(s) failed"
  exit 1
fi
echo "all smoke checks passed"
