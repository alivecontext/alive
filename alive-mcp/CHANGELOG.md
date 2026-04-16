# Changelog

All notable changes to alive-mcp are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

alive-mcp is versioned independently from the ALIVE plugin. Both live
in the `alivecontext/alive` monorepo but follow separate release
cadences.

## [0.1.0] - 2026-04-17

Initial release. Read-only MCP server exposing the ALIVE Context System
to any MCP-capable agent.

### Added

**10 tools** (frozen roster, all read-only):

- `list_walnuts` -- paginated walnut inventory with health, domain, goal
- `get_walnut_state` -- current now.json snapshot for a walnut
- `read_walnut_kernel` -- read key.md, log.md, insights.md, or now.json
- `list_bundles` -- all bundles in a walnut with status, goal, phase
- `get_bundle` -- full manifest, task counts, raw file count for a bundle
- `read_bundle_manifest` -- raw manifest parse with validation warnings
- `search_world` -- regex search across all walnuts, cursor-paginated
- `search_walnut` -- regex search scoped to a single walnut
- `read_log` -- chapter-aware paginated log reader with offset/limit
- `list_tasks` -- tasks from walnut or bundle scope with status counts

**4 MCP resources** per walnut (alive:// URI scheme):

- `alive://walnut/{path}/kernel/key` -- identity and metadata
- `alive://walnut/{path}/kernel/log` -- session history
- `alive://walnut/{path}/kernel/insights` -- standing domain knowledge
- `alive://walnut/{path}/kernel/now` -- current state projection

**Resource subscriptions** via watchdog file observers:

- Real-time `notifications/resources/updated` when kernel files change
- Lazy-on-subscribe observer lifecycle (start on first subscribe, stop on last unsubscribe)
- 500ms debounce to coalesce rapid filesystem events

**World discovery and path safety:**

- MCP Roots handshake with `roots/list` request and change subscription
- `ALIVE_WORLD_ROOT` / `ALIVE_WORLD_PATH` env var fallback
- `os.path.commonpath` boundary checks (not `startswith`)
- Symlink-aware `os.path.realpath` normalization
- Single-world-per-process model (shortest-path wins on multi-root)

**JSONL audit logger:**

- Async queue with background writer task
- Privacy-first: argument values hashed (sha256 prefix), never logged raw
- 10 MB rotation with 10-file retention
- `ALIVE_MCP_AUDIT_PUBLIC_WALNUT_PATHS` opt-in for verbose debugging
- Writes to `<world>/.alive/_mcp/audit.log` with mode 0o600

**Error taxonomy:**

- Structured error codes: `ERR_NO_WORLD`, `ERR_WALNUT_NOT_FOUND`,
  `ERR_PATH_ESCAPE`, `ERR_KERNEL_FILE_MISSING`, `ERR_BUNDLE_NOT_FOUND`,
  `ERR_INVALID_ARGUMENT`, `ERR_SEARCH_FAILED`, `ERR_INTERNAL`
- Consistent response envelope with `ok`, `data`, `error`, `meta` fields
- `isError: true` on MCP tool responses when an error occurs

**CI and security (4-layer no-phone-home):**

- GitHub Actions workflow with `step-security/harden-runner@v2` egress block
- Inspector pinned via `package-lock.json` + `npm ci`
- `sitecustomize.py` socket blocker injected into server subprocess
- Inspector contract snapshot diffed against committed fixture

**Distribution:**

- `uvx alive-mcp@0.1.0` primary install path
- `.mcpb` bundle for Claude Desktop one-click install
- Per-client config snippets: Claude Desktop, Cursor, Codex CLI,
  Gemini CLI, Continue.dev, ChatGPT (manual)

**Supported MCP clients:**

- Claude Desktop (full support, .mcpb one-click)
- Cursor (full support)
- Codex CLI (full support)
- Gemini CLI (full support)
- Continue.dev (full support)
- ChatGPT (config documented, not tested end-to-end)

### Deferred to v0.2

- Write tools (capture, save, bundle operations) behind explicit consent gates
- Prompts primitive (user-triggered flows)
- Sampling / elicitation primitives
- Streamable HTTP / OAuth remote-server transport
- Case-insensitive path matching on macOS (HFS+/APFS)
- Multi-world support (world_id in tool signatures)
- Real PyPI publication (held for explicit decision)

### Infrastructure

- Python >=3.10, <3.14
- `mcp>=1.27,<2.0` (FastMCP, stdio transport, spec 2025-06-18)
- `watchdog>=4` (filesystem observation)
- `hatchling` build backend
- stdlib `unittest` test suite (no pytest dependency)
- Vendored ALIVE kernel utilities (`walnut_paths.py` direct, `project.py`
  and `tasks.py` extracted as pure helpers)

### Task history

This release was built across 17 implementation tasks (fn-10-60k.1
through fn-10-60k.17):

1. Package scaffold (pyproject.toml, entry point, test harness)
2. Vendor ALIVE kernel utilities (walnut_paths, project_pure, tasks_pure)
3. Path safety + world discovery contract (Roots, env fallback, symlinks)
4. Error taxonomy + structured response envelope
5. FastMCP server bootstrap (server.py, lifespan, stdio, capabilities)
6. Walnut tools (list_walnuts, get_walnut_state, read_walnut_kernel)
7. Bundle tools (list_bundles, get_bundle, read_bundle_manifest)
8. Search tools (search_world, search_walnut with cursor pagination)
9. Log + task tools (read_log chapter-aware, list_tasks)
10. MCP resources for kernel files (alive:// URI scheme)
11. Resource subscriptions via watchdog observers
12. JSONL audit logger (async queue, rotation, hashed args)
13. Fixture world + unittest suite
14. MCP Inspector CLI contract tests (snapshot diff)
15. CI workflow + no-phone-home enforcement (4-layer lock)
16. README + per-client config snippets
17. MCPB bundle manifest + one-click install verification

[0.1.0]: https://github.com/alivecontext/alive/releases/tag/alive-mcp-v0.1.0
