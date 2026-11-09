#!/bin/bash
# Hook: Repo Detection -- SessionStart (startup)
# Detects if CWD matches a walnut's dev.local_path and injects context.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/alive-common.sh"

read_hook_input

# fn-15-la5.6: bridge fan-out -- helper is the SOLE emitter on the
# no-world-found path. The explicit ``if !`` form survives ``set -euo
# pipefail`` (which this hook sets above) cleanly.
# // TODO(world-resolution-contract-v2): swap to find_world_or_die in cutover release
if ! find_world_or_warn "${HOOK_EVENT:-SessionStart}"; then
  exit 0
fi

# Only run if CWD is outside the World. On Windows HOOK_CWD arrives as
# C:\Users\... and WORLD_ROOT as /c/Users/..., so compare both in MSYS form,
# ignoring case, on a real path boundary (/c/alive2 is not inside /c/alive).
if alive_path_within "$WORLD_ROOT" "$HOOK_CWD"; then
  exit 0
fi

# Need a working Python for YAML parsing. ALIVE_JSON_RT is set by the one
# interpreter pick in alive-common.sh, which already skips the Windows Store
# stub (a python3 that exists but cannot run).
if [ "$ALIVE_JSON_RT" != "python3" ]; then
  exit 0
fi

# Paths go to Python through the environment, never pasted into the script:
# a C:\Users\... value inside a Python string literal is a syntax error
# (\U), and native Windows Python cannot open /c/... paths.
REPO_RESULT=$(ALIVE_RD_WORLD="$(alive_native_path "$WORLD_ROOT")" \
  ALIVE_RD_CWD="$(alive_native_path "$(alive_msys_path "$HOOK_CWD")")" \
  python3 -c '
import os, re, glob

def winpath(p):
    # On Windows accept /c/x (Git Bash) as well as C:\x and C:/x.
    if os.name == "nt":
        m = re.match(r"^/([A-Za-z])(/.*)?$", p)
        if m:
            p = m.group(1).upper() + ":" + (m.group(2) or "/")
    return p

def norm(p):
    return os.path.normcase(os.path.normpath(winpath(p)))

def within(root, path):
    root, path = norm(root), norm(path)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)

world = os.environ["ALIVE_RD_WORLD"]
cwd = os.environ["ALIVE_RD_CWD"]
matches = []

def extract_frontmatter(filepath):
    """Read only YAML frontmatter between --- markers."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    if not lines or lines[0].strip() != "---":
        return ""
    fm_lines = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)
    return "".join(fm_lines)

for kf in glob.glob(os.path.join(world, "*", "*", "_kernel", "key.md")) + glob.glob(os.path.join(world, "*", "*", "*", "_kernel", "key.md")):
    try:
        frontmatter = extract_frontmatter(kf)
        if not frontmatter:
            continue
        # Walnut name: the folder that holds _kernel
        walnut_name = os.path.basename(os.path.dirname(os.path.dirname(kf)))
        if not walnut_name:
            continue
        # Parse dev.local_path from frontmatter only
        in_dev = False
        local_path = None
        for line in frontmatter.split("\n"):
            if re.match(r"^dev:", line):
                in_dev = True
                continue
            if in_dev:
                if re.match(r"^[a-z]", line) and not line.startswith(" "):
                    break
                m = re.match(r"\s+local_path:\s*(.+)", line)
                if m:
                    lp = m.group(1).strip().strip("\"").strip("\x27")
                    local_path = os.path.expanduser(lp)
        if local_path and within(local_path, cwd):
            matches.append((walnut_name, local_path, kf))
    except Exception:
        continue

if matches:
    best = max(matches, key=lambda x: len(x[1]))
    print(f"{best[0]}|{best[1]}|{best[2]}")
' 2>/dev/null || true)

if [ -z "$REPO_RESULT" ]; then
  exit 0
fi

REPO_WALNUT=$(echo "$REPO_RESULT" | cut -d'|' -f1)
REPO_PATH=$(echo "$REPO_RESULT" | cut -d'|' -f2)

# Update squirrel YAML if it exists
SQUIRREL_FILE="$WORLD_ROOT/.alive/_squirrels/${HOOK_SESSION_ID}.yaml"
if [ -f "$SQUIRREL_FILE" ]; then
  echo "repo_context: ${REPO_WALNUT}" >> "$SQUIRREL_FILE"
fi

REPO_MSG="Repo context detected: CWD matches walnut [[${REPO_WALNUT}]] (dev.local_path: ${REPO_PATH}). Consider loading this walnut's context with /alive:load-context ${REPO_WALNUT}."

REPO_ESCAPED=$(escape_for_json "$REPO_MSG")

cat <<HOOKEOF
{
  "additional_context": "${REPO_ESCAPED}",
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "${REPO_ESCAPED}"
  }
}
HOOKEOF
