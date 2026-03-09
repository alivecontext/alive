#!/bin/bash
# ALIVE Statusline — shows session health at a glance.
# Boot message on first render, then working statusline after first response.

INPUT=$(cat /dev/stdin 2>/dev/null || echo '{}')

# Extract fields
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null || echo "")
COST=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('cost',{}); print(f\"\${c.get('total_cost_usd',0):.2f}\")" 2>/dev/null || echo "\$0.00")
CTX_PCT=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); cw=d.get('context_window',{}); p=cw.get('used_percentage'); print(f'{p:.0f}' if p is not None else '?')" 2>/dev/null || echo "?")
CWD=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null || echo "")
MODEL=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); m=d.get('model',{}); print(m.get('display_name','?') if isinstance(m,dict) else (m or '?'))" 2>/dev/null || echo "?")

# Colors
RESET="\033[0m"
DIM="\033[2m"
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
COPPER="\033[38;5;173m"

# Find ALIVE world root
WORLD_ROOT=""
DIR="${CWD:-$PWD}"
while [ "$DIR" != "/" ]; do
  if [ -d "$DIR/01_Archive" ] && [ -d "$DIR/02_Life" ]; then
    WORLD_ROOT="$DIR"
    break
  fi
  DIR="$(dirname "$DIR")"
done

# ── DEGRADED STATES ──

if [ -z "$WORLD_ROOT" ]; then
  echo -e "${YELLOW}⚠ alive: no world detected${RESET} ${DIM}— open from your world directory${RESET}"
  exit 0
fi

if [ -z "$SESSION_ID" ]; then
  echo -e "${YELLOW}⚠ alive: no session ID${RESET} ${DIM}— plugin may not be installed${RESET}"
  exit 0
fi

SHORT_ID="${SESSION_ID:0:8}"
ENTRY="$WORLD_ROOT/.alive/_squirrels/$SESSION_ID.yaml"

# Wait briefly for SessionStart hook to finish writing the YAML
if [ ! -f "$ENTRY" ]; then
  sleep 0.2
fi
if [ ! -f "$ENTRY" ]; then
  echo -e "${YELLOW}⚠ alive: session not registered${RESET} ${DIM}— context not compounding. Check plugin: /alive:world${RESET}"
  exit 0
fi

RULES=$(grep '^rules_loaded:' "$ENTRY" 2>/dev/null | sed 's/rules_loaded: *//' || echo "0")

if [ "$RULES" = "0" ] || [ -z "$RULES" ]; then
  echo -e "${RED}⚠ alive: rules not loaded${RESET} ${DIM}— session running without context system. Restart session.${RESET}"
  exit 0
fi

# ── HEALTHY STATE ──

# Count walnuts available
WALNUT_COUNT=""
if [ -n "$WORLD_ROOT" ]; then
  WALNUT_COUNT=$(find "$WORLD_ROOT" -path "*/_core/key.md" -not -path "*/01_Archive/*" 2>/dev/null | wc -l | tr -d ' ')
fi

# Check if this is the boot render (no activity file yet = first response hasn't happened)
ACTIVITY_FILE="/tmp/alive-activity-${SESSION_ID}"
if [ ! -f "$ACTIVITY_FILE" ]; then
  # ── BOOT MESSAGE — rotates tip each render ──
  TIPS=(
    "${COPPER}your context compounds from here${RESET}"
    "${DIM}/alive:world${RESET} ${DIM}— view your world${RESET}"
    "${DIM}/alive:open${RESET} ${DIM}— lock in on one walnut${RESET}"
    "${DIM}/alive:save${RESET} ${DIM}— checkpoint, compound context${RESET}"
    "${DIM}/alive:housekeeping${RESET} ${DIM}— clean your world${RESET}"
    "${DIM}/alive:capture${RESET} ${DIM}— bring context in${RESET}"
    "${DIM}/alive:find${RESET} ${DIM}— search everything${RESET}"
    "${DIM}/alive:recall${RESET} ${DIM}— revive past sessions${RESET}"
  )
  TIP_INDEX=$(( $(date +%s) % ${#TIPS[@]} ))
  echo -e "${DIM}${MODEL}${RESET} ${DIM}|${RESET} ${COPPER}🐿️${RESET} ${GREEN}${BOLD}squirrel ready to stash${RESET} ${DIM}|${RESET} 🌰 ${DIM}${WALNUT_COUNT} walnuts${RESET} ${DIM}|${RESET} ${TIPS[$TIP_INDEX]}"
  exit 0
fi

# ── WORKING STATUSLINE ──

# Read activity count
EDITS=$(cat "$ACTIVITY_FILE" 2>/dev/null || echo "0")

# Context percentage color + warning
CTX_COLOR="$GREEN"
CTX_WARN=""
if [ "$CTX_PCT" != "?" ]; then
  if [ "$CTX_PCT" -ge 90 ] 2>/dev/null; then
    CTX_COLOR="$RED"
    CTX_WARN=" ${RED}${BOLD}SAVE NOW${RESET}"
  elif [ "$CTX_PCT" -ge 80 ] 2>/dev/null; then
    CTX_COLOR="$YELLOW"
    CTX_WARN=" ${YELLOW}/alive:save${RESET}"
  elif [ "$CTX_PCT" -ge 60 ] 2>/dev/null; then
    CTX_COLOR="$YELLOW"
  fi
fi

echo -e "${DIM}${MODEL}${RESET} ${DIM}|${RESET} ${COPPER}🐿️ ${SHORT_ID}${RESET} ${DIM}|${RESET} ${CTX_COLOR}ctx:${CTX_PCT}%${RESET}${CTX_WARN} ${DIM}|${RESET} ${CYAN}${COST}${RESET} ${DIM}|${RESET} ${DIM}${EDITS} edits${RESET}"
