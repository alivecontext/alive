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
# Dependency pinning (T14 + T15)
# ------------------------------
# Inspector is pinned via a committed ``package.json`` +
# ``package-lock.json`` under ``alive-mcp/`` and installed locally
# into ``alive-mcp/node_modules/`` via ``npm ci``. The script prefers
# the local binary at ``./node_modules/.bin/mcp-inspector`` so CI's
# no-phone-home test phase (T15) never touches the network — the
# Inspector is already on disk from the install phase.
#
# Legacy fallback: if ``./node_modules/.bin/mcp-inspector`` is absent
# (e.g. a contributor running the script before ``npm ci``), the
# script falls back to ``npx -y @modelcontextprotocol/inspector@<ver>``
# where ``<ver>`` is the ``INSPECTOR_VERSION`` constant below. That
# fallback hits the npm registry and is FORBIDDEN in CI — the test
# phase's empty harden-runner allowlist blocks it. To bump Inspector:
# update ``INSPECTOR_VERSION`` here, update the package.json dep
# range, regenerate ``package-lock.json`` via ``npm install
# --package-lock-only``, then run ``scripts/update-snapshots.sh`` to
# regenerate the goldens.
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
# npx / uv / node surface their own errors deep in a pipeline. ``node``
# is included because ``npx`` fails with a confusing "spawn EACCES" or
# "bad interpreter" error when Node is missing — a dedicated check up
# front produces a clearer diagnostic. ``npx`` is only required on the
# legacy dynamic-fetch fallback path; we still check for it here so
# the error message appears up front rather than mid-pipeline for the
# rare contributor running without ``npm ci`` yet.
for bin in bash npx node uv python3; do
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
#
# Tempfile location: default to the system tempdir, but fall back to a
# repo-local ``.tmp/`` when ``mktemp -t`` fails (locked-down sandboxes
# with no writable ``$TMPDIR``). Either way the file gets cleaned up
# on exit via the trap.
if ! STDERR_LOG="$(mktemp -t alive-mcp-inspector-stderr.XXXXXX 2>/dev/null)"; then
    REPO_TMP="${PKG_ROOT}/.tmp"
    mkdir -p "${REPO_TMP}"
    STDERR_LOG="$(mktemp "${REPO_TMP}/alive-mcp-inspector-stderr.XXXXXX")"
fi
# Ensure tempfile cleanup on any exit path (success or abort).
trap 'rm -f "${STDERR_LOG}"' EXIT

# Prefer the locally-installed Inspector binary (restored by
# ``npm ci`` during CI's install phase) over a dynamic ``npx`` fetch.
# When the local install is present we NEVER touch the network — the
# T15 no-phone-home CI posture depends on this. The ``npx`` fallback
# only fires on a dev machine that has not yet run ``npm ci``; that
# path hits the npm registry and is blocked by the CI egress policy.
LOCAL_INSPECTOR="${PKG_ROOT}/node_modules/.bin/mcp-inspector"
if [[ -x "${LOCAL_INSPECTOR}" ]]; then
    INSPECTOR_CMD=("${LOCAL_INSPECTOR}")
else
    # Guard against running in CI without node_modules restored. If
    # CI is set and the local binary is missing, the install phase
    # broke — fail loud rather than silently hitting the registry
    # (which harden-runner will block anyway, producing a much more
    # confusing error).
    if [[ "${CI:-}" =~ ^(1|true|True|TRUE|yes|on)$ ]]; then
        echo "error: ${LOCAL_INSPECTOR} not found in CI; did the npm ci step run?" >&2
        exit 1
    fi
    INSPECTOR_CMD=(npx -y "@modelcontextprotocol/inspector@${INSPECTOR_VERSION}")
fi

if ! RAW_JSON="$(
    cd "${PKG_ROOT}" \
    && ALIVE_WORLD_ROOT="${WORLD_ROOT}" \
       "${INSPECTOR_CMD[@]}" \
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
