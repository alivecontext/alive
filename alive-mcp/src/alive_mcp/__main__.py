"""CLI entry point for alive-mcp.

T1 scaffold: `main()` prints version and exits 0. FastMCP server bootstrap
lands in T5 (fn-10-60k.5).

Anti-pattern reminder: once T5 wires the stdio JSON-RPC server, this module
MUST NOT call `print()` on stdout — doing so corrupts MCP framing. Logs go
to stderr via the logging module. For now (version-only stub), stdout is
acceptable because no server is running.
"""

from __future__ import annotations

import argparse
import sys

from alive_mcp import __version__


def main(argv: list[str] | None = None) -> int:
    """Entry point wired via `[project.scripts] alive-mcp`.

    Returns the process exit code. Tests call this with ``argv=[]`` to exercise
    the CLI without invoking ``sys.exit`` inside the suite.
    """
    parser = argparse.ArgumentParser(
        prog="alive-mcp",
        description=(
            "Read-only MCP server exposing the ALIVE Context System. "
            "T1 scaffold: prints version. Server bootstrap arrives in T5."
        ),
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    # Bare invocation: also prints version (stub behaviour until T5).
    print(__version__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
