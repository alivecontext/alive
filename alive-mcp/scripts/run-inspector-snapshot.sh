#!/usr/bin/env bash
#
# run-inspector-snapshot.sh — generate a normalized MCP contract snapshot.
#
# Drives the MCP Inspector CLI against the alive-mcp server running over
# the frozen fixture world (``tests/fixtures/world-basic``) and writes a
# deterministic JSON snapshot to stdout.
#
# Supported methods (positional arg, default ``tools/list``):
#   tools/list      — 10 frozen v0.1 tools
#   resources/list  — 4 kernel resources × walnut_count (12 for fixture)
#   prompts/list    — stub for v0.2 (empty list)
#
# Determinism strategy
# --------------------
# The Inspector returns JSON that is STABLE in content but NOT in key
# order. We canonicalize through the companion helper
# ``scripts/normalize_snapshot.py``, which (a) sorts every dict key
# recursively via ``json.dumps(..., sort_keys=True)``, (b) sorts each
# list's elements by the natural identity key for that primitive
# (``name`` for tools, ``uri`` for resources, ``name`` for prompts),
# and (c) breaks ties with the item's canonical JSON so duplicate or
# missing identity keys cannot reintroduce non-determinism. Output is
# indented 2 spaces with a trailing newline so the golden fixture is a
# stable, diff-friendly text artifact.
#
# World hermeticity
# -----------------
# The Inspector must always snapshot the COMMITTED fixture World, not
# whatever ``ALIVE_WORLD_ROOT`` happens to be set to in the caller's
# shell. We therefore IGNORE ambient ``ALIVE_WORLD_ROOT`` /
# ``ALIVE_WORLD_PATH`` by default and read only the dedicated
# ``ALIVE_CONTRACT_WORLD_ROOT`` override (used by tests that stand up
# a custom fixture). This prevents a developer with a real World
# pointer from silently rewriting goldens against their personal
# data — a subtle footgun the first review round flagged.
#
# T14 → T15 transition (dependency pinning)
# ----------------------------------------
# T14 pins the Inspector version INLINE via the
# ``INSPECTOR_VERSION`` constant below — ``npx -y
# @modelcontextprotocol/inspector@<INSPECTOR_VERSION>`` — so an upstream
# Inspector release cannot spontaneously break the snapshot diff. The
# cost of inline pinning is that the first run on a cold machine still
# touches the npm registry to fetch that version into the npx cache;
# that is acceptable for LOCAL dev.
#
# For CI, T15 replaces this dynamic-fetch path with a committed
# ``package-lock.json`` + ``npm ci`` install phase and swaps the
# invocation to ``./node_modules/.bin/mcp-inspector`` — the
# no-phone-home posture in T15 forbids any network access during the
# test phase. To bump Inspector: update ``INSPECTOR_VERSION`` here,
# update T15's ``package-lock.json`` to match, then
# ``scripts/update-snapshots.sh`` to regenerate the goldens.
#
# Exit codes
# ----------
#   0  success, snapshot written to stdout
#   1  invalid arguments or missing toolchain (node/npx/uv)
#   2  Inspector returned non-JSON on stdout (server print contamination)
#   3  Inspector subprocess failed (non-zero exit)

set -euo pipefail

# Pinned Inspector version. Bump here + regenerate goldens when
# upstream ships a new major. Allow an override via
# ``ALIVE_MCP_INSPECTOR_VERSION`` so ad-hoc bumps don't require editing
# the script (useful for CI experimenting with a pre-release). The
# default captures whatever was current when T14 landed; T15's
# ``package-lock.json`` must match.
INSPECTOR_VERSION="${ALIVE_MCP_INSPECTOR_VERSION:-0.21.2}"

usage() {
    cat >&2 <<'EOF'
usage: run-inspector-snapshot.sh [method]

  method     one of tools/list, resources/list, prompts/list
             (default: tools/list)

Environment:
  ALIVE_CONTRACT_WORLD_ROOT   optional; overrides which world the
                              Inspector snapshots. Use with caution:
                              the default is the committed fixture
                              world under tests/fixtures/world-basic,
                              which is what the committed goldens were
                              produced against. Overriding this WILL
                              produce a different snapshot and should
                              only be done when testing a synthetic
                              fixture for a new contract case.

                              Ambient ALIVE_WORLD_ROOT /
                              ALIVE_WORLD_PATH are IGNORED by this
                              script to keep snapshot generation
                              hermetic across dev machines.
EOF
}

METHOD="${1:-tools/list}"

case "${METHOD}" in
    tools/list|resources/list|prompts/list) ;;
    -h|--help) usage; exit 0 ;;
    *)
        echo "error: unsupported method: ${METHOD}" >&2
        usage
        exit 1
        ;;
esac

# Toolchain sanity. Fail fast with a clear message rather than letting
# npx / uv surface their own errors deep in a pipeline.
for bin in npx uv python3; do
    if ! command -v "${bin}" >/dev/null 2>&1; then
        echo "error: ${bin} is required on PATH to run the Inspector snapshot generator" >&2
        exit 1
    fi
done

# Resolve alive-mcp package root (parent of this script dir) without
# depending on ``readlink -f`` which is not portable to BSD userland.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PKG_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_WORLD="${PKG_ROOT}/tests/fixtures/world-basic"
# Snapshot hermeticity: ignore the user's ambient ALIVE_WORLD_ROOT.
# The only override we honor is the dedicated contract-test pointer.
# Otherwise we always snapshot the committed fixture — same world the
# committed goldens were produced against.
WORLD_ROOT="${ALIVE_CONTRACT_WORLD_ROOT:-${DEFAULT_WORLD}}"

if [[ ! -d "${WORLD_ROOT}" ]]; then
    echo "error: world root does not exist: ${WORLD_ROOT}" >&2
    exit 1
fi

# Scrub inherited World-pointer env vars before launching the
# Inspector subprocess. ``unset`` is the safest way to guarantee the
# child subprocess (``uv run alive-mcp``) sees ONLY our explicit
# ALIVE_WORLD_ROOT below, regardless of what the caller exported.
unset ALIVE_WORLD_PATH

# Inspector stderr carries npm warnings and server banner noise. We
# must keep it OUT of the snapshot (stdout-only) but we CANNOT
# discard it — on failure, the stderr is the most useful diagnostic
# (npx cache miss, uv sync error, server crash). Capture stderr to a
# tempfile, let stdout flow to ``RAW_JSON``. On success we drop the
# stderr silently; on failure we echo it so the caller / test harness
# sees the real reason.
STDERR_LOG="$(mktemp -t alive-mcp-inspector-stderr.XXXXXX)"
# Ensure tempfile cleanup on any exit path (success or abort).
trap 'rm -f "${STDERR_LOG}"' EXIT

if ! RAW_JSON="$(
    cd "${PKG_ROOT}" \
    && ALIVE_WORLD_ROOT="${WORLD_ROOT}" \
       npx -y "@modelcontextprotocol/inspector@${INSPECTOR_VERSION}" \
           --cli uv run alive-mcp \
           --method "${METHOD}" 2>"${STDERR_LOG}"
)"; then
    echo "error: Inspector subprocess failed for method ${METHOD}" >&2
    echo "--- Inspector stderr ---" >&2
    cat "${STDERR_LOG}" >&2
    echo "--- end Inspector stderr ---" >&2
    exit 3
fi

# Normalize via the normalize_snapshot.py helper so the logic is
# testable independently of this shell wrapper. Sort top-level list
# elements by stable identity keys and deep-sort all dict keys so the
# snapshot is deterministic across runs and across Python / SDK
# versions.
printf '%s' "${RAW_JSON}" | python3 "${SCRIPT_DIR}/normalize_snapshot.py" "${METHOD}"
