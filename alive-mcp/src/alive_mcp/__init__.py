"""alive-mcp: Read-only MCP server exposing the ALIVE Context System.

This package is the v0.1 implementation of Moat C from the ALIVE competitor
analysis: an MCP (Model Context Protocol) server that makes the ALIVE
filesystem addressable from any MCP-capable agent (Claude Desktop, Cursor,
ChatGPT, Codex CLI, Gemini CLI, Continue, Cline, Zed, Windsurf, etc.).

v0.1 is read-only. Write tools arrive in v0.2 gated behind explicit
per-invocation user consent.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
