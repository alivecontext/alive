# alive-mcp

Read-only Model Context Protocol (MCP) server exposing the ALIVE Context System to any MCP-capable agent (Claude Desktop, Cursor, ChatGPT, Codex CLI, Gemini CLI, Continue, Cline, Zed, Windsurf, JetBrains AI Assistant, VS Code Copilot).

This is the v0.1 scaffold. Full docs, per-client config snippets, and usage examples land in T16 (fn-10-60k.16). See the epic spec at `.flow/specs/fn-10-60k.md` for the complete design.

## Status

`v0.1.0` (pre-release scaffold). Read-only surface only. Write tools arrive in v0.2 gated behind explicit consent.

## Quick start (contributors)

The surrounding monorepo uses Python 3.14 for plugin bytecode work. `alive-mcp` requires its own pinned 3.10–3.12 interpreter so the `mcp` SDK's pydantic event loop does not land on an uncertified CPython version.

```bash
cd alive-mcp

# One-time: install a pinned 3.12 via uv (bypasses system Python)
uv python install 3.12
uv venv --python 3.12

# Verify the stub entry point
uv run alive-mcp --version
# => alive-mcp 0.1.0

# Run the test suite (stdlib unittest, no pytest dependency)
python3 -m unittest discover tests
```

### Running via uvx (what end users do)

```bash
# From the package directory
uvx --from . alive-mcp --version
```

## Troubleshooting

**`python: command not found` or system Python is 3.14.** The monorepo's top-level environment targets CPython 3.14 for plugin work. `alive-mcp` cannot use 3.14 yet (see "Python pin rationale" in `pyproject.toml`). Fix:

```bash
uv python install 3.12
uv venv --python 3.12
# Then re-run `uv run alive-mcp --version`
```

**`mcp` SDK import fails.** Ensure you are running via `uv run` (which activates the local `.venv`) or have activated it manually. The package pins `mcp>=1.27,<2.0`; the 2.x line uses different import paths.

**FastMCP v2 vs v1 confusion.** This package targets the MCP Python SDK's FastMCP (at `mcp.server.fastmcp`), NOT the third-party `fastmcp` 2.x library. The two have diverged; pin exactly as written in `pyproject.toml`.

## Layout

```
alive-mcp/
  pyproject.toml              # build + deps + entry point
  src/alive_mcp/
    __init__.py              # package identity, __version__
    __main__.py              # CLI entry (T1 stub → T5 server)
    # T2: _vendor/ (walnut_paths) and _vendor/_pure/ (extracted logic)
    # T3: paths.py, discovery.py
    # T4: errors.py, envelope.py
    # T5: server.py, lifespan.py
    # T6-T9: tools/
    # T10-T11: resources/, subscriptions.py
    # T12: audit.py
  tests/                      # stdlib unittest
  README.md                   # this file (stub — full docs in T16)
```

## License

MIT. See `../LICENSE` at the monorepo root.
