#!/usr/bin/env bash
# ALIVE x Hermes — Installer
#
# Installs the ALIVE memory provider into the Hermes *user plugin directory*:
#
#   $HERMES_HOME/plugins/memory/alive/      (HERMES_HOME defaults to ~/.hermes)
#
# This is the supported, update-safe location on every Hermes install method
# (pip, git checkout, Docker) — user-dir plugins override bundled ones and
# survive Hermes upgrades. Do NOT copy into the repo checkout
# ($HERMES_HOME/hermes-agent/plugins/…): that path only exists on git-installer
# layouts and is never scanned on the others.
#
# The installer is idempotent (safe to re-run; every step converges) and
# non-interactive. It verifies its own work at the end and exits non-zero if
# any layer failed.
#
# Usage: bash install.sh [--scaffold-world]
#
#   --scaffold-world   Create a minimal ALIVE world at ~/world if none exists

set -euo pipefail

# Colors
COPPER='\033[38;2;184;115;51m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

fail() {
    echo -e "${RED}error:${RESET} $*" >&2
    exit 1
}

SCAFFOLD_WORLD=false
while [ $# -gt 0 ]; do
    case "$1" in
        --scaffold-world) SCAFFOLD_WORLD=true ;;
        -h|--help)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) fail "unknown argument: $1 (usage: bash install.sh [--scaffold-world])" ;;
    esac
    shift
done

echo ""
echo -e "${COPPER}${BOLD}ALIVE × Hermes${RESET}"
echo -e "${DIM}A structured context layer for autonomous agents${RESET}"
echo ""

# ── Detect environment ──────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PROVIDER_SRC="$SCRIPT_DIR/memory-provider"
PROVIDER_DIR="$HERMES_HOME/plugins/memory/alive"
# Hermes <=0.18.x discovers memory plugins from the FLAT layout
# $HERMES_HOME/plugins/<name>/ (no memory/ subdir); 0.19+ uses
# $HERMES_HOME/plugins/memory/<name>/. Verified live 2026-08-06 against
# the v2026.7.7.2 (v0.18.2) and v2026.8.3 (v0.20.0) images — we install
# to the modern path and bridge the flat one with a symlink (copy when
# symlinks are unavailable).
PROVIDER_FLAT_LINK="$HERMES_HOME/plugins/alive"
WORLD_ROOT=""
HAS_ALIVE=false
HAS_HERMES=false

if command -v hermes &>/dev/null; then
    HAS_HERMES=true
    echo -e "${GREEN}✓${RESET} Hermes binary found ($(command -v hermes))"
else
    echo -e "${YELLOW}○${RESET} Hermes binary not found on PATH (files will be staged; live checks skipped)"
fi

for candidate in \
    "${ALIVE_WORLD_ROOT:-}" \
    "$HOME/world" \
    "$HOME/Library/Mobile Documents/com~apple~CloudDocs/alive"; do
    if [ -n "$candidate" ] && [ -d "$candidate/.alive" ]; then
        WORLD_ROOT="$candidate"
        HAS_ALIVE=true
        break
    fi
done

if $HAS_ALIVE; then
    WALNUT_COUNT=$(find "$WORLD_ROOT" -name "key.md" -path "*/_kernel/*" 2>/dev/null | grep -v "01_Archive" | wc -l | tr -d ' ')
    echo -e "${GREEN}✓${RESET} ALIVE world found at $WORLD_ROOT ($WALNUT_COUNT walnuts)"
else
    echo -e "${YELLOW}○${RESET} ALIVE world not found"
fi

echo ""

# ── Layer 1: Memory Provider ────────────────────────────────────

echo -e "${BOLD}Layer 1: Memory Provider${RESET}"
echo -e "  Target: $PROVIDER_DIR ${DIM}(Hermes user plugin dir)${RESET}"

mkdir -p "$PROVIDER_DIR" || fail "could not create $PROVIDER_DIR"
# Copy every provider source file (dynamic — the provider grows modules;
# a hardcoded list silently ships a broken install).
found_py=false
PROVIDER_FILES=()   # basenames copied, re-checked in Verification below
for f in "$PROVIDER_SRC"/*.py "$PROVIDER_SRC"/plugin.yaml "$PROVIDER_SRC"/README.md; do
    [ -f "$f" ] || continue
    case "$f" in *.py) found_py=true ;; esac
    cp "$f" "$PROVIDER_DIR/$(basename "$f")" || fail "could not copy $(basename "$f") to $PROVIDER_DIR"
    PROVIDER_FILES+=("$(basename "$f")")
done
$found_py || fail "no provider .py sources found in $PROVIDER_SRC"
if [ ! -e "$PROVIDER_FLAT_LINK" ]; then
    ln -s "$PROVIDER_DIR" "$PROVIDER_FLAT_LINK" 2>/dev/null \
        || cp -r "$PROVIDER_DIR" "$PROVIDER_FLAT_LINK" \
        || fail "could not create 0.18.x-compat plugin path $PROVIDER_FLAT_LINK"
fi
echo -e "  ${GREEN}✓${RESET} Memory provider installed (modern + 0.18.x-compat paths)"

# Warn about the legacy (wrong) install location from earlier versions.
LEGACY_DIR="$HERMES_HOME/hermes-agent/plugins/memory/alive"
if [ -d "$LEGACY_DIR" ]; then
    echo -e "  ${YELLOW}○${RESET} Legacy copy found at $LEGACY_DIR"
    echo -e "    ${DIM}The user plugin dir now takes precedence; remove the legacy copy to avoid confusion.${RESET}"
fi

echo ""

# ── Layer 2: Skills ─────────────────────────────────────────────

echo -e "${BOLD}Layer 2: Hermes Skills${RESET}"

SKILLS_DIR="$SCRIPT_DIR/hermes-skills"
CRONS_DIR="$SCRIPT_DIR/cron-templates"
HERMES_CONFIG="$HERMES_HOME/config.yaml"

if [ -f "$HERMES_CONFIG" ] && grep -qF "$SKILLS_DIR" "$HERMES_CONFIG" 2>/dev/null; then
    echo -e "  ${GREEN}✓${RESET} config.yaml already points at the ALIVE skill directories"
elif [ -f "$HERMES_CONFIG" ] && grep -qE '^skills:|external_dirs' "$HERMES_CONFIG" 2>/dev/null; then
    # Never append a second top-level `skills:` key: duplicate keys are
    # silently last-wins on some YAML loaders (discarding the user's existing
    # skills settings) and a hard startup error on others.
    echo -e "  ${YELLOW}○${RESET} config.yaml already has a skills: section — add these paths to skills.external_dirs manually:"
    echo -e "    ${DIM}- $SKILLS_DIR${RESET}"
    echo -e "    ${DIM}- $CRONS_DIR${RESET}"
elif [ -f "$HERMES_CONFIG" ]; then
    {
        echo ""
        echo "# ALIVE skills and cron templates"
        echo "skills:"
        echo "  external_dirs:"
        echo "    - $SKILLS_DIR"
        echo "    - $CRONS_DIR"
    } >> "$HERMES_CONFIG" || fail "could not update $HERMES_CONFIG"
    echo -e "  ${GREEN}✓${RESET} config.yaml updated (skills.external_dirs)"
else
    echo -e "  ${YELLOW}○${RESET} No config.yaml at $HERMES_CONFIG — create one with:"
    echo -e "    ${DIM}skills:"
    echo "      external_dirs:"
    echo "        - $SKILLS_DIR"
    echo -e "        - $CRONS_DIR${RESET}"
fi

echo ""

# ── Layer 3: Crons ──────────────────────────────────────────────

echo -e "${BOLD}Layer 3: Cron Templates${RESET}"
echo "  Cron jobs are not installed automatically."
echo -e "  Preview the commands (dry run): ${DIM}bash $SCRIPT_DIR/setup-crons.sh${RESET}"
echo -e "  Create the jobs:                ${DIM}bash $SCRIPT_DIR/setup-crons.sh --apply${RESET}"

echo ""

# ── Layer 4: Runtime Integration ────────────────────────────────

echo -e "${BOLD}Layer 4: Runtime Integration${RESET}"

# SOUL.md patch (guarded append — idempotent)
SOUL_FILE="$HERMES_HOME/SOUL.md"
if [ -f "$SOUL_FILE" ]; then
    if grep -q "squirrel" "$SOUL_FILE" 2>/dev/null; then
        echo -e "  ${GREEN}✓${RESET} SOUL.md already has the squirrel patch"
    else
        {
            echo ""
            echo "You share this world with a squirrel -- the ALIVE context runtime."
            echo "It scatterhoards context across walnuts so you can focus on helping"
            echo "the user. Read what it leaves. Write what it needs. Don't fight it."
        } >> "$SOUL_FILE" || fail "could not update $SOUL_FILE"
        echo -e "  ${GREEN}✓${RESET} SOUL.md patched"
    fi
else
    echo -e "  ${DIM}No SOUL.md found. Append $SCRIPT_DIR/soul-patch.md when you create one.${RESET}"
fi

# AGENTS.md
if $HAS_ALIVE; then
    AGENTS_DEST="$WORLD_ROOT/AGENTS.md"
    if [ -f "$AGENTS_DEST" ]; then
        echo -e "  ${GREEN}✓${RESET} AGENTS.md already present at $AGENTS_DEST"
    else
        cp "$SCRIPT_DIR/agents.md" "$AGENTS_DEST" || fail "could not install $AGENTS_DEST"
        echo -e "  ${GREEN}✓${RESET} AGENTS.md installed at $AGENTS_DEST"
    fi
fi

echo ""

# ── Scaffold world (opt-in) ─────────────────────────────────────

if ! $HAS_ALIVE; then
    if $SCAFFOLD_WORLD; then
        echo -e "${BOLD}Scaffolding ALIVE World${RESET}"
        WORLD_ROOT="$HOME/world"
        mkdir -p "$WORLD_ROOT/.alive/_squirrels" \
                 "$WORLD_ROOT/02_Life/people" \
                 "$WORLD_ROOT/03_Inbox" \
                 "$WORLD_ROOT/04_Ventures" \
                 "$WORLD_ROOT/05_Experiments" \
                 "$WORLD_ROOT/01_Archive" || fail "could not scaffold $WORLD_ROOT"

        if [ ! -f "$WORLD_ROOT/.alive/key.md" ]; then
            CREATED_DATE=$(date +%Y-%m-%d)
            cat > "$WORLD_ROOT/.alive/key.md" << WORLDKEY
---
name: (your name)
created: $CREATED_DATE
---

Your ALIVE world. Personal context infrastructure.
WORLDKEY
        fi

        if [ ! -f "$WORLD_ROOT/.alive/preferences.yaml" ]; then
            cat > "$WORLD_ROOT/.alive/preferences.yaml" << 'PREFS'
spark: true
health_nudges: true
PREFS
        fi

        HAS_ALIVE=true
        echo -e "  ${GREEN}✓${RESET} World created at $WORLD_ROOT"
        echo "  For the full ALIVE plugin (Claude Code): claude plugin install alive@alivecontext"
        echo ""
    else
        echo -e "${DIM}No ALIVE world yet. Re-run with --scaffold-world to create ~/world,${RESET}"
        echo -e "${DIM}or install the full plugin: claude plugin install alive@alivecontext${RESET}"
        echo ""
    fi
fi

# ── Environment contract ────────────────────────────────────────

PLUGIN_ROOT_HINT="<path-to-alive-repo>/plugins/alive"
if [ -d "$SCRIPT_DIR/../plugins/alive" ]; then
    PLUGIN_ROOT_HINT="$(cd "$SCRIPT_DIR/../plugins/alive" && pwd)"
fi

echo -e "${BOLD}Environment contract${RESET}"
echo "  The Hermes runtime needs these variables (shell profile, systemd unit,"
echo "  or container environment — wherever Hermes is started from):"
echo ""
echo -e "  ${DIM}export${RESET} ALIVE_WORLD_ROOT=${WORLD_ROOT:-"<path-to-your-world>"}"
echo "      Where your ALIVE world lives. The provider can auto-detect ~/world,"
echo "      but gateway and cron sessions should not rely on auto-detection."
echo ""
echo -e "  ${DIM}export${RESET} ALIVE_PLUGIN_ROOT=$PLUGIN_ROOT_HINT"
echo "      Where the ALIVE plugin scripts live. Skills invoke"
echo "      \$ALIVE_PLUGIN_ROOT/scripts/*.py; under Claude Code a session hook"
echo "      sets this, under Hermes nothing does — export it yourself."
echo ""

# ── Verification ────────────────────────────────────────────────

echo -e "${BOLD}Verification${RESET}"
VERIFY_FAILED=false

for f in "${PROVIDER_FILES[@]}"; do
    if [ -f "$PROVIDER_DIR/$f" ]; then
        echo -e "  ${GREEN}✓${RESET} $PROVIDER_DIR/$f"
    else
        echo -e "  ${RED}✗${RESET} missing: $PROVIDER_DIR/$f"
        VERIFY_FAILED=true
    fi
done

if $HAS_HERMES; then
    # Memory providers have their own discovery system (kind: exclusive) and
    # may be listed separately from general plugins — a missing row in
    # 'hermes plugins list' is not proof the install failed, so it warns
    # instead of failing. The authoritative check is 'hermes memory status'
    # after activating the provider with 'hermes memory setup'.
    if PLUGINS_OUT=$(hermes plugins list 2>&1) && echo "$PLUGINS_OUT" | grep -qiw "alive"; then
        echo -e "  ${GREEN}✓${RESET} 'hermes plugins list' reports the alive plugin"
    else
        echo -e "  ${YELLOW}○${RESET} 'hermes plugins list' does not show an 'alive' row"
        echo -e "    ${DIM}Memory providers can be listed separately from general plugins;${RESET}"
        echo -e "    ${DIM}confirm with: hermes memory setup  →  expect 'alive' as an option${RESET}"
    fi

    # Recall round-trip: is alive the active provider yet?
    if MEMORY_OUT=$(hermes memory status 2>&1) && echo "$MEMORY_OUT" | grep -qiw "alive"; then
        echo -e "  ${GREEN}✓${RESET} 'hermes memory status' reports alive as the active provider"
    else
        echo -e "  ${YELLOW}○${RESET} alive is not the active memory provider yet"
        echo -e "    ${DIM}Activate it: hermes memory setup  →  select 'alive'${RESET}"
    fi
else
    echo -e "  ${YELLOW}!${RESET} WARNING: hermes binary not found — live verification skipped."
    echo "    After installing Hermes, verify with:"
    echo "      hermes memory setup      # select 'alive' to activate"
    echo "      hermes memory status     # expect 'alive' as the active provider"
    echo "      hermes plugins list      # may show 'alive' (providers can be listed separately)"
fi

if $VERIFY_FAILED; then
    fail "install verification failed — see the ✗ items above"
fi

# ── Done ────────────────────────────────────────────────────────

echo ""
echo -e "${COPPER}${BOLD}Setup complete.${RESET}"
echo ""
echo "  Memory provider: hermes memory setup -> select 'alive'"
echo "  Skills:          /alive-load, /alive-save, /alive-world, ..."
echo "  Crons:           bash $SCRIPT_DIR/setup-crons.sh   (dry run; --apply to create)"
echo ""
echo -e "  ${DIM}The AI is the engine. The context is the fuel. And the fuel compounds.${RESET}"
echo ""
