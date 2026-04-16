"""CLI entry point for alive-mcp.

T1 scaffold: `main()` prints version and exits. The actual FastMCP server
bootstrap lands in T5 (fn-10-60k.5).

Anti-pattern reminder: once T5 wires the stdio JSON-RPC server, this module
MUST NOT call `print()` on stdout — doing so corrupts MCP framing. Logs go
to stderr via the logging module. For now (version-only stub), stdout is
acceptable because no server is running.
"""

from __future__ import annotations

import argparse
import sys

from alive_mcp import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alive-mcp",
        description=(
            "Read-only MCP server exposing the ALIVE Context System. "
            "T1 scaffold: prints version. Server bootstrap arrives in T5."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point wired via `[project.scripts] alive-mcp`.

    Returns the process exit code. Tests call this with ``argv=[]`` to exercise
    the CLI surface without actually invoking ``sys.exit`` inside the suite.
    """
    parser = _build_parser()
    # argparse handles --version itself (it prints and sys.exits(0)); we still
    # parse so other args are rejected consistently.
    parser.parse_args(argv)

    # T1 stub behaviour when invoked with no args: print version to stdout and
    # exit 0. This makes `alive-mcp --version` and bare `alive-mcp` both useful
    # to smoke tests until T5 wires the real server.
    print(f"alive-mcp {__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
