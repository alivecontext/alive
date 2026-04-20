# ChatGPT

Not supported in alive-mcp v0.1. ChatGPT's MCP connector requires a remote
Streamable HTTP endpoint with OAuth. v0.1 ships stdio only.

## Why it is deferred

v0.1 is read-only, local, single-user. stdio is the right transport for
that posture: the server runs inside the client's process tree, the
filesystem boundary is the authorization boundary, and nothing crosses
the network. ChatGPT cannot spawn a local process, so it needs a hosted
endpoint.

Hosting an endpoint introduces multi-tenant concerns alive-mcp v0.1
does not address: tenant isolation, OAuth flows, remote audit, rate
limits, a server that phones something (the hosting platform) rather
than nothing. Shipping that safely is the v0.2 workstream.

## What lands in v0.2

- Streamable HTTP transport (spec 2025-06-18 `transport: streamable_http`)
- OAuth 2.1 with PKCE (ChatGPT's expected auth flow)
- Hosted deployment recipe (Cloudflare Workers + Durable Objects is the
  current candidate; one walnut-host's filesystem per OAuth identity)
- Per-tenant audit with explicit consent gates

Track progress at https://github.com/alivecontext/alive/issues (filter
by `alive-mcp` + `v0.2`).

## What works today

Every other MCP client in the v0.1 ecosystem supports stdio:

- Claude Desktop (`docs/configs/claude-desktop.json`)
- Cursor (`docs/configs/cursor.json`)
- Codex CLI (`docs/configs/codex.toml`)
- Gemini CLI (`docs/configs/gemini.json`)
- Continue.dev (`docs/configs/continue.yaml`)

If you want ALIVE context inside ChatGPT specifically before v0.2 lands,
the practical workaround is to use Claude Desktop or Cursor for ALIVE-
aware work. v0.1 is not a universal bridge; it meets the agents it can
meet on the transport they support.
