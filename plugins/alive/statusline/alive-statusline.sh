#!/bin/bash
# ALIVE Statusline — shows session health at a glance.
# Receives JSON on stdin from Claude Code with cost, context, model data.
# Reads rules_loaded from squirrel YAML for health verification.

INPUT=$(cat /dev/stdin 2>/dev/null || echo '{}')

# Extract fields from Claude Code's statusline JSON
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id','???'))" 2>/dev/null || echo "???")
COST=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('cost',{}); print(f\"\${c.get('total_cost_usd',0):.2f}\")" 2>/dev/null || echo "\$0.00")
CTX_PCT=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); cw=d.get('context_window',{}); p=cw.get('used_percentage'); print(f'{p:.0f}' if p is not None else '?')" 2>/dev/null || echo "?")
MODEL=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); m=d.get('model',{}); print(m.get('display_name','') if isinstance(m,dict) else m)" 2>/dev/null || echo "")

# Short session ID (first 8 chars)
SHORT_ID="${SESSION_ID:0:8}"

# Read rules_loaded from squirrel YAML
RULES="?"
WORLD_ROOT=""
# Walk up from cwd to find ALIVE world
CWD=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null || echo "")
DIR="${CWD:-$PWD}"
while [ "$DIR" != "/" ]; do
  if [ -d "$DIR/01_Archive" ] && [ -d "$DIR/02_Life" ]; then
    WORLD_ROOT="$DIR"
    break
  fi
  DIR="$(dirname "$DIR")"
done

if [ -n "$WORLD_ROOT" ] && [ -f "$WORLD_ROOT/.alive/_squirrels/$SESSION_ID.yaml" ]; then
  RULES=$(grep '^rules_loaded:' "$WORLD_ROOT/.alive/_squirrels/$SESSION_ID.yaml" 2>/dev/null | sed 's/rules_loaded: *//' || echo "?")
fi

# Colors
RESET="\033[0m"
DIM="\033[2m"
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
COPPER="\033[38;5;173m"

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

# Rules health
RULES_DISPLAY=""
if [ "$RULES" = "?" ] || [ "$RULES" = "0" ]; then
  RULES_DISPLAY="${RED}rules:${RULES}${RESET}"
else
  RULES_DISPLAY="${DIM}rules:${RULES}${RESET}"
fi

# Build the statusline
echo -e "${COPPER}🐿️ ${SHORT_ID}${RESET} ${DIM}|${RESET} ${RULES_DISPLAY} ${DIM}|${RESET} ${CTX_COLOR}ctx:${CTX_PCT}%${RESET}${CTX_WARN} ${DIM}|${RESET} ${CYAN}${COST}${RESET}"
