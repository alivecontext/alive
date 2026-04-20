"""Session tools for alive-mcp (fast follow on v0.1 -- Ben's request).

Two read-only tools exposing squirrel session entries from
``.alive/_squirrels/*.yaml``:

* ``list_sessions`` -- recent sessions, optionally filtered by walnut
* ``read_session`` -- full content of a specific session entry

Both annotated ``readOnlyHint=True``.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from mcp.types import ToolAnnotations

from alive_mcp.envelope import error, ok
from alive_mcp.errors import ErrorCode
from alive_mcp.paths import is_inside
from alive_mcp.tools._audit_stub import audited

logger = logging.getLogger(__name__)

_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
    idempotentHint=True,
)


def _extract_field(content: str, field: str) -> Optional[str]:
    """Extract a simple scalar from YAML content via regex."""
    for pattern in [
        r'^{f}:\s*"((?:[^"\\]|\\.)*)"\s*$',
        r"^{f}:\s*'((?:[^'\\]|\\.)*)'\s*$",
        r"^{f}:\s*(.+?)\s*$",
    ]:
        m = re.search(pattern.format(f=re.escape(field)), content, re.MULTILINE)
        if m:
            val = m.group(1).strip()
            if val and val != "null":
                return val
    return None


def _parse_session_yaml(filepath: str) -> Optional[Dict[str, Any]]:
    """Parse a squirrel YAML file into a dict. Returns None on read error."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (IOError, OSError, UnicodeDecodeError):
        return None

    session_id = _extract_field(content, "session_id") or os.path.basename(filepath).replace(".yaml", "")
    walnut = _extract_field(content, "walnut")
    started = _extract_field(content, "started") or ""
    ended = _extract_field(content, "ended")
    engine = _extract_field(content, "engine")
    saves_str = _extract_field(content, "saves")
    recovery_state = _extract_field(content, "recovery_state")
    bundle = _extract_field(content, "bundle")
    squirrel_name = _extract_field(content, "squirrel_name")

    date_match = re.match(r"(\d{4}-\d{2}-\d{2})", started)
    date = date_match.group(1) if date_match else ""

    saves = 0
    if saves_str:
        try:
            saves = int(saves_str)
        except ValueError:
            pass

    return {
        "session_id": session_id,
        "date": date,
        "started": started,
        "ended": ended,
        "walnut": walnut,
        "bundle": bundle,
        "engine": engine,
        "squirrel_name": squirrel_name,
        "saves": saves,
        "recovery_state": recovery_state,
    }


def _squirrels_dir(world_root: str) -> str:
    return os.path.join(world_root, ".alive", "_squirrels")


def register(server: Any) -> None:
    """Register session tools on the FastMCP server."""

    @server.tool(
        name="list_sessions",
        description=(
            "List recent squirrel sessions from .alive/_squirrels/. "
            "Optionally filter by walnut path. Returns newest first."
        ),
        annotations=_ANNOTATIONS,
    )
    @audited
    async def list_sessions(
        limit: int = 20,
        walnut: str | None = None,
    ) -> dict:
        from alive_mcp.server import get_app_context

        ctx = get_app_context()
        if ctx.world_root is None:
            return error(ErrorCode.ERR_NO_WORLD)

        sq_dir = _squirrels_dir(ctx.world_root)
        if not os.path.isdir(sq_dir):
            return ok({"sessions": [], "total": 0})

        # Collect all yaml files sorted by mtime descending
        entries: list[tuple[float, str]] = []
        try:
            for fname in os.listdir(sq_dir):
                if not fname.endswith(".yaml"):
                    continue
                fpath = os.path.join(sq_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        mtime = os.path.getmtime(fpath)
                        entries.append((mtime, fpath))
                    except OSError:
                        pass
        except OSError:
            return ok({"sessions": [], "total": 0})

        entries.sort(reverse=True)

        sessions: list[dict] = []
        for _mtime, fpath in entries:
            if len(sessions) >= limit:
                break
            parsed = _parse_session_yaml(fpath)
            if parsed is None:
                continue
            # Filter by walnut if specified
            if walnut and parsed.get("walnut") != os.path.basename(walnut):
                continue
            sessions.append(parsed)

        return ok({"sessions": sessions, "total": len(sessions)})

    @server.tool(
        name="read_session",
        description=(
            "Read the full content of a specific squirrel session entry "
            "by session ID. Returns the parsed YAML fields including "
            "stash items, working files, and actions."
        ),
        annotations=_ANNOTATIONS,
    )
    @audited
    async def read_session(session_id: str) -> dict:
        from alive_mcp.server import get_app_context

        ctx = get_app_context()
        if ctx.world_root is None:
            return error(ErrorCode.ERR_NO_WORLD)

        sq_dir = _squirrels_dir(ctx.world_root)
        fpath = os.path.join(sq_dir, f"{session_id}.yaml")

        # Path safety
        if not is_inside(fpath, ctx.world_root):
            return error(ErrorCode.ERR_PATH_ESCAPE)

        if not os.path.isfile(fpath):
            return error(
                ErrorCode.ERR_WALNUT_NOT_FOUND,
                session_id=session_id,
                suggestions=["Use list_sessions to find valid session IDs"],
            )

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw_content = f.read()
        except (IOError, OSError) as exc:
            return error(ErrorCode.ERR_PERMISSION_DENIED, detail=str(type(exc).__name__))

        # Parse structured fields
        parsed = _parse_session_yaml(fpath)

        # Also extract stash, working, actions sections (multi-line)
        stash_block = re.search(
            r"^stash:\s*\n((?:[ \t]+-\s*.+\n?)*)", raw_content, re.MULTILINE
        )
        stash_items: list[str] = []
        if stash_block:
            for item in re.finditer(r"-\s*content:\s*[\"']?(.*?)[\"']?\s*$",
                                     stash_block.group(1), re.MULTILINE):
                stash_items.append(item.group(1))

        working_block = re.search(
            r"^working:\s*\n((?:[ \t]+-\s*.+\n?)*)", raw_content, re.MULTILINE
        )
        working: list[str] = []
        if working_block:
            for item in re.finditer(r"-\s*(.+)", working_block.group(1)):
                working.append(item.group(1).strip())

        result = parsed or {}
        result["stash_items"] = stash_items
        result["working_files"] = working
        result["raw_content"] = raw_content

        return ok(result)
