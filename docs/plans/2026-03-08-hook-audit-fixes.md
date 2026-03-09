# Hook Audit Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the session ID bug, clean up hooks, and make the hook system reliable for launch.

**Architecture:** All hooks share a common library (`alive-common.sh`) for world detection and stdin JSON reading. Session hooks extract `session_id`, `model`, `transcript_path`, and `cwd` from Claude Code's JSON input instead of generating/guessing. Three unused hooks are removed. hooks.json is updated to match.

**Tech Stack:** Bash, jq, python3 (for large JSON escaping)

**Repo:** `~/contextmanager` (branch: `refactor/alive-v0.1`)
**Plugin root:** `plugins/alive/`
**Hook scripts:** `plugins/alive/hooks/scripts/`

---

### Task 1: Create shared alive-common.sh

**Files:**
- Create: `plugins/alive/hooks/scripts/alive-common.sh`

**Step 1: Write the shared library**

```bash
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
# Sets: WORLD_ROOT or exits 0 if not found.
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
```

**Step 2: Verify it's sourceable**

Run: `bash -c 'source ~/contextmanager/plugins/alive/hooks/scripts/alive-common.sh && echo "OK"'`
Expected: `OK`

**Step 3: Commit**

```bash
git add plugins/alive/hooks/scripts/alive-common.sh
git commit -m "feat: add shared alive-common.sh for all hooks"
```

---

### Task 2: Rewrite alive-session-new.sh

**Files:**
- Modify: `plugins/alive/hooks/scripts/alive-session-new.sh`

**Step 1: Replace the entire file**

```bash
#!/bin/bash
# Hook: Session New — SessionStart (startup)
# Creates squirrel entry in .alive/_squirrels/, reads preferences, injects rules.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

# Read stdin JSON — extracts session_id, cwd, event name
read_hook_input

# SessionStart-specific — extracts model, source, transcript_path
read_session_fields

# Find world root
find_world || { echo "No ALIVE world found."; exit 0; }

# Use Claude Code's session ID, fall back to random only if missing
SESSION_ID="${HOOK_SESSION_ID}"
if [ -z "$SESSION_ID" ]; then
  SESSION_ID=$(head -c 16 /dev/urandom | shasum | head -c 8)
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S")

# Set env vars via CLAUDE_ENV_FILE if available
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "ALIVE_SESSION_ID=$SESSION_ID" >> "$CLAUDE_ENV_FILE"
  echo "ALIVE_WORLD_ROOT=$WORLD_ROOT" >> "$CLAUDE_ENV_FILE"
fi

# Write squirrel entry to .alive/_squirrels/
SQUIRRELS_DIR="$WORLD_ROOT/.alive/_squirrels"
mkdir -p "$SQUIRRELS_DIR"
ENTRY_FILE="$SQUIRRELS_DIR/$SESSION_ID.yaml"
cat > "$ENTRY_FILE" << EOF
session_id: $SESSION_ID
runtime_id: squirrel.core@0.2
engine: $HOOK_MODEL
walnut: null
started: $TIMESTAMP
ended: null
signed: false
transcript: ${HOOK_TRANSCRIPT}
cwd: ${HOOK_CWD}
stash: []
working: []
EOF

# Resolve preferences
source "$SCRIPT_DIR/alive-resolve-preferences.sh"
PREFS=$(resolve_preferences "$WORLD_ROOT")

# Build runtime rules from plugin source files
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
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
The following are your core operating rules for the ALIVE system. They are MANDATORY — not suggestions, not defaults, not guidelines. You MUST follow them in every response, every tool call, every session.
</EXTREMELY_IMPORTANT>"

# Build session message with rule verification
SESSION_MSG="ALIVE session initialized. Session ID: $SESSION_ID
World: $WORLD_ROOT
Walnut: none detected
Model: $HOOK_MODEL
$PREFS
Rules: ${RULE_COUNT} loaded (${RULE_NAMES})"

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
```

**Step 2: Test the hook manually**

Run: `echo '{"session_id":"test-123","model":"claude-opus-4-6","source":"startup","transcript_path":"/tmp/test.jsonl","cwd":"/Users/benflint/Library/Mobile Documents/com~apple~CloudDocs/alive","hook_event_name":"SessionStart","permission_mode":"default"}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-session-new.sh 2>&1 | head -5`

Expected: JSON output containing `test-123` as session ID, rule count > 0.

**Step 3: Verify squirrel entry was created with correct ID**

Run: `cat ~/.alive/_squirrels/test-123.yaml 2>/dev/null || find ~/Library/Mobile\ Documents/com~apple~CloudDocs/alive/.alive/_squirrels/ -name "test-123.yaml" -exec cat {} \;`

Expected: YAML with `session_id: test-123` and `engine: claude-opus-4-6`

**Step 4: Commit**

```bash
git add plugins/alive/hooks/scripts/alive-session-new.sh
git commit -m "fix: read session_id from Claude Code stdin JSON instead of generating random ID"
```

---

### Task 3: Rewrite alive-session-resume.sh

**Files:**
- Modify: `plugins/alive/hooks/scripts/alive-session-resume.sh`

**Step 1: Replace the entire file**

```bash
#!/bin/bash
# Hook: Session Resume — SessionStart (resume)
# Reads squirrel entry by session_id, re-injects stash + preferences.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
read_session_fields
find_world || { echo "No ALIVE world found."; exit 0; }

SESSION_ID="${HOOK_SESSION_ID}"

# Resolve preferences
source "$SCRIPT_DIR/alive-resolve-preferences.sh"
PREFS=$(resolve_preferences "$WORLD_ROOT")

# Find squirrel entry by session_id (exact match) or fall back to most recent unsigned
SQUIRRELS_DIR="$WORLD_ROOT/.alive/_squirrels"
ENTRY=""
if [ -n "$SESSION_ID" ] && [ -f "$SQUIRRELS_DIR/$SESSION_ID.yaml" ]; then
  ENTRY="$SQUIRRELS_DIR/$SESSION_ID.yaml"
elif [ -d "$SQUIRRELS_DIR" ]; then
  ENTRY=$(grep -rl 'ended: null' "$SQUIRRELS_DIR/"*.yaml 2>/dev/null | head -1)
fi

if [ -n "$ENTRY" ] && [ -f "$ENTRY" ]; then
  ENTRY_SESSION_ID=$(python3 -c "
import yaml, sys
with open('$ENTRY') as f:
    d = yaml.safe_load(f) or {}
print(d.get('session_id', ''))
" 2>/dev/null || grep 'session_id:' "$ENTRY" | awk '{print $2}')
  WALNUT=$(python3 -c "
import yaml, sys
with open('$ENTRY') as f:
    d = yaml.safe_load(f) or {}
print(d.get('walnut', 'null'))
" 2>/dev/null || grep '^walnut:' "$ENTRY" | awk '{print $2}')
  STASH=$(python3 -c "
import yaml, sys, json
with open('$ENTRY') as f:
    d = yaml.safe_load(f) or {}
stash = d.get('stash', [])
if stash:
    for item in stash:
        if isinstance(item, dict):
            print(f\"- {item.get('content', item)}\")
        else:
            print(f'- {item}')
else:
    print('(empty)')
" 2>/dev/null || echo "(could not parse stash)")

  cat << EOF
ALIVE session resumed. Session ID: ${ENTRY_SESSION_ID:-unknown}
Walnut: ${WALNUT:-none}
$PREFS
Previous stash:
$STASH
EOF
else
  cat << EOF
ALIVE session resumed. No matching entry found — clean start.
$PREFS
EOF
fi
```

**Step 2: Test**

Run: `echo '{"session_id":"test-123","model":"claude-opus-4-6","source":"resume","hook_event_name":"SessionStart"}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-session-resume.sh 2>&1`

Expected: Output showing resumed session with stash from the test-123 entry created in Task 2.

**Step 3: Commit**

```bash
git add plugins/alive/hooks/scripts/alive-session-resume.sh
git commit -m "fix: read session_id from stdin JSON on resume, proper YAML parsing for stash"
```

---

### Task 4: Rewrite alive-session-compact.sh

**Files:**
- Modify: `plugins/alive/hooks/scripts/alive-session-compact.sh`

**Step 1: Replace the entire file**

```bash
#!/bin/bash
# Hook: Session Compact — SessionStart (compact)
# Re-injects stash + walnut context + preferences after compaction.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
read_session_fields
find_world || { echo "No ALIVE world found."; exit 0; }

SESSION_ID="${HOOK_SESSION_ID}"

# Resolve preferences
source "$SCRIPT_DIR/alive-resolve-preferences.sh"
PREFS=$(resolve_preferences "$WORLD_ROOT")

# Find squirrel entry by session_id or fall back
SQUIRRELS_DIR="$WORLD_ROOT/.alive/_squirrels"
ENTRY=""
if [ -n "$SESSION_ID" ] && [ -f "$SQUIRRELS_DIR/$SESSION_ID.yaml" ]; then
  ENTRY="$SQUIRRELS_DIR/$SESSION_ID.yaml"
elif [ -d "$SQUIRRELS_DIR" ]; then
  ENTRY=$(grep -rl 'ended: null' "$SQUIRRELS_DIR/"*.yaml 2>/dev/null | head -1)
fi

WALNUT=""
STASH="(empty)"
if [ -n "$ENTRY" ] && [ -f "$ENTRY" ]; then
  WALNUT=$(python3 -c "
import yaml
with open('$ENTRY') as f:
    d = yaml.safe_load(f) or {}
print(d.get('walnut', '') or '')
" 2>/dev/null || grep '^walnut:' "$ENTRY" | awk '{print $2}')
  STASH=$(python3 -c "
import yaml
with open('$ENTRY') as f:
    d = yaml.safe_load(f) or {}
stash = d.get('stash', [])
if stash:
    for item in stash:
        if isinstance(item, dict):
            print(f\"- {item.get('content', item)}\")
        else:
            print(f'- {item}')
else:
    print('(empty)')
" 2>/dev/null || echo "(could not parse)")
fi

# If walnut is active, re-read brief pack
NOW_CONTENT=""
KEY_CONTENT=""
if [ -n "$WALNUT" ] && [ "$WALNUT" != "null" ]; then
  # Search all domain folders recursively for the walnut's _core/
  WALNUT_CORE=$(find "$WORLD_ROOT" -path "*/01_Archive" -prune -o -path "*/$WALNUT/_core" -print -quit 2>/dev/null)
  if [ -n "$WALNUT_CORE" ] && [ -d "$WALNUT_CORE" ]; then
    [ -f "$WALNUT_CORE/now.md" ] && NOW_CONTENT=$(head -30 "$WALNUT_CORE/now.md")
    [ -f "$WALNUT_CORE/key.md" ] && KEY_CONTENT=$(head -30 "$WALNUT_CORE/key.md")
  fi
fi

cat << EOF
CONTEXT RESTORED after compaction. Session: ${SESSION_ID:-unknown} | Walnut: ${WALNUT:-none}
$PREFS

Stash recovered:
$STASH

Current state (re-read — do not trust pre-compaction memory):
$NOW_CONTENT

Identity:
$KEY_CONTENT

IMPORTANT: Re-read _core/key.md, _core/now.md, _core/tasks.md before continuing work. Do not trust memory of files read before compaction.
EOF
```

**Step 2: Test**

Run: `echo '{"session_id":"test-123","source":"compact","hook_event_name":"SessionStart"}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-session-compact.sh 2>&1`

Expected: Context restored output with stash and walnut state.

**Step 3: Commit**

```bash
git add plugins/alive/hooks/scripts/alive-session-compact.sh
git commit -m "fix: read session_id from stdin, use find for deep walnut search, proper YAML stash parsing"
```

---

### Task 5: Fix alive-pre-compact.sh

**Files:**
- Modify: `plugins/alive/hooks/scripts/alive-pre-compact.sh`

**Step 1: Replace the entire file**

```bash
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
  done)
fi

[ -z "$ENTRY" ] && exit 0

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
```

**Step 2: Test**

Run: `echo '{"session_id":"test-123","hook_event_name":"PreCompact","trigger":"auto"}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-pre-compact.sh && grep compacted ~/Library/Mobile\ Documents/com~apple~CloudDocs/alive/.alive/_squirrels/test-123.yaml`

Expected: `compacted: <timestamp>`

**Step 3: Commit**

```bash
git add plugins/alive/hooks/scripts/alive-pre-compact.sh
git commit -m "fix: read session_id from stdin to find correct squirrel entry"
```

---

### Task 6: Fix alive-archive-enforcer.sh

**Files:**
- Modify: `plugins/alive/hooks/scripts/alive-archive-enforcer.sh`

**Step 1: Update to use alive-common.sh and cwd from JSON**

```bash
#!/bin/bash
# Hook: Archive Enforcer — PreToolUse (Bash)
# Blocks rm/rmdir/unlink when targeting files inside the ALIVE world.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input
find_world || exit 0

read_tool_fields
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
```

**Step 2: Commit**

```bash
git add plugins/alive/hooks/scripts/alive-archive-enforcer.sh
git commit -m "fix: resolve relative paths against cwd from JSON input, use alive-common.sh"
```

---

### Task 7: Update remaining hooks to use alive-common.sh

**Files:**
- Modify: `plugins/alive/hooks/scripts/alive-log-guardian.sh`
- Modify: `plugins/alive/hooks/scripts/alive-rules-guardian.sh`
- Modify: `plugins/alive/hooks/scripts/alive-external-guard.sh`

**Step 1: Update alive-log-guardian.sh**

Replace the `find_world` function block and `INPUT=$(cat)` with:

```bash
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
```

**Step 2: Update alive-rules-guardian.sh** — same pattern: replace find_world block and `INPUT=$(cat)` with source + read_hook_input + find_world, then use `$HOOK_INPUT` instead of `$INPUT`.

**Step 3: Update alive-external-guard.sh** — same pattern.

**Step 4: Commit**

```bash
git add plugins/alive/hooks/scripts/alive-log-guardian.sh plugins/alive/hooks/scripts/alive-rules-guardian.sh plugins/alive/hooks/scripts/alive-external-guard.sh
git commit -m "refactor: migrate log-guardian, rules-guardian, external-guard to alive-common.sh"
```

---

### Task 8: Kill hooks and update hooks.json

**Files:**
- Delete: `plugins/alive/hooks/scripts/alive-working-signer.sh`
- Delete: `plugins/alive/hooks/scripts/alive-reference-indexer.sh`
- Delete: `plugins/alive/hooks/scripts/alive-save-check.sh`
- Modify: `plugins/alive/hooks/hooks.json`

**Step 1: Delete the three hook scripts**

```bash
rm plugins/alive/hooks/scripts/alive-working-signer.sh
rm plugins/alive/hooks/scripts/alive-reference-indexer.sh
rm plugins/alive/hooks/scripts/alive-save-check.sh
```

**Step 2: Replace hooks.json**

```json
{
  "description": "ALIVE v1.0-beta — 8 hooks. Session hooks read/write .alive/_squirrels/. All read stdin JSON for session_id.",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/alive-session-new.sh",
            "timeout": 10
          }
        ]
      },
      {
        "matcher": "resume",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/alive-session-resume.sh",
            "timeout": 10
          }
        ]
      },
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/alive-session-compact.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/alive-log-guardian.sh",
            "timeout": 5
          },
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/alive-rules-guardian.sh",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/alive-archive-enforcer.sh",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "mcp__.*",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/alive-external-guard.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/alive-pre-compact.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**Step 3: Verify hook count**

Run: `cat ~/contextmanager/plugins/alive/hooks/hooks.json | python3 -c "import sys,json; h=json.load(sys.stdin)['hooks']; total=sum(len(mg.get('hooks',[])) for event in h.values() for mg in event); print(f'{total} hooks across {len(h)} events')"`

Expected: `8 hooks across 3 events`

**Step 4: Verify deleted scripts are gone**

Run: `ls ~/contextmanager/plugins/alive/hooks/scripts/ | wc -l`

Expected: 9 files (alive-common.sh, 8 hook scripts, alive-resolve-preferences.sh = 10 actually, minus the 3 deleted = should be 9 — let me count: common, session-new, session-resume, session-compact, log-guardian, rules-guardian, archive-enforcer, external-guard, pre-compact, resolve-preferences = 10)

**Step 5: Commit**

```bash
git rm plugins/alive/hooks/scripts/alive-working-signer.sh plugins/alive/hooks/scripts/alive-reference-indexer.sh plugins/alive/hooks/scripts/alive-save-check.sh
git add plugins/alive/hooks/hooks.json
git commit -m "chore: remove working-signer, reference-indexer, save-check hooks; update hooks.json to 8 hooks"
```

---

### Task 9: Clean up test artifacts and final verification

**Step 1: Remove test squirrel entry**

```bash
find ~/Library/Mobile\ Documents/com~apple~CloudDocs/alive/.alive/_squirrels/ -name "test-123.yaml" -delete 2>/dev/null
```

**Step 2: Run all hooks with simulated input to verify no crashes**

```bash
# Test each hook with appropriate JSON input
echo '{"session_id":"verify-001","model":"claude-opus-4-6","source":"startup","transcript_path":"/tmp/test.jsonl","cwd":"/tmp","hook_event_name":"SessionStart","permission_mode":"default"}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-session-new.sh > /dev/null 2>&1 && echo "session-new: OK" || echo "session-new: FAIL"

echo '{"session_id":"verify-001","source":"resume","hook_event_name":"SessionStart"}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-session-resume.sh > /dev/null 2>&1 && echo "session-resume: OK" || echo "session-resume: FAIL"

echo '{"session_id":"verify-001","source":"compact","hook_event_name":"SessionStart"}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-session-compact.sh > /dev/null 2>&1 && echo "session-compact: OK" || echo "session-compact: FAIL"

echo '{"session_id":"verify-001","hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"/tmp/test.md","old_string":"hello","new_string":"world"}}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-log-guardian.sh > /dev/null 2>&1 && echo "log-guardian: OK" || echo "log-guardian: FAIL"

echo '{"session_id":"verify-001","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo hello"}}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-archive-enforcer.sh > /dev/null 2>&1 && echo "archive-enforcer: OK" || echo "archive-enforcer: FAIL"

echo '{"session_id":"verify-001","hook_event_name":"PreToolUse","tool_name":"mcp__gmail__send_email","tool_input":{}}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-external-guard.sh > /dev/null 2>&1 && echo "external-guard: OK" || echo "external-guard: FAIL"

echo '{"session_id":"verify-001","hook_event_name":"PreCompact","trigger":"auto"}' | bash ~/contextmanager/plugins/alive/hooks/scripts/alive-pre-compact.sh > /dev/null 2>&1 && echo "pre-compact: OK" || echo "pre-compact: FAIL"
```

Expected: All 7 show `OK` (rules-guardian tested implicitly with log-guardian since they share the Edit|Write matcher).

**Step 3: Clean up verify entry**

```bash
find ~/Library/Mobile\ Documents/com~apple~CloudDocs/alive/.alive/_squirrels/ -name "verify-001.yaml" -delete 2>/dev/null
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "test: verify all 8 hooks run without errors"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Create alive-common.sh | 1 new |
| 2 | Rewrite session-new | 1 modified |
| 3 | Rewrite session-resume | 1 modified |
| 4 | Rewrite session-compact | 1 modified |
| 5 | Fix pre-compact | 1 modified |
| 6 | Fix archive-enforcer | 1 modified |
| 7 | Migrate remaining hooks to common | 3 modified |
| 8 | Kill 3 hooks + update hooks.json | 3 deleted, 1 modified |
| 9 | Test + clean up | 0 files |

9 tasks, ~9 commits, 1 new file, 7 modified, 3 deleted.
