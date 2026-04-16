"""Shared helpers for integration + edge-case tests (fn-10-60k.13 / T13).

Plain module -- NOT a pytest conftest. The rest of the suite is unittest
(stdlib), so this module follows that convention. Imports the name
``_test_helpers`` so :func:`unittest.TestLoader.discover` does not mistake
it for a test module (the default pattern is ``test_*.py``).

What it provides
----------------
- :data:`FIXTURE_WORLD` -- absolute path to ``tests/fixtures/world-basic``.
- :func:`start_server` -- spawn ``python3 -m alive_mcp`` with an env-
  discovered World root, return the :class:`subprocess.Popen` handle.
  Used by :mod:`test_integration` and :mod:`test_edge_cases`.
- :func:`rpc_roundtrip` / :func:`rpc_call_tool` -- synchronous JSON-RPC
  helpers that serialize one or more frames to stdin, collect frames
  from stdout until EOF, and return the parsed frame list. Wraps
  ``subprocess.Popen.communicate`` with a bounded timeout so a hung
  server manifests as a test-level AssertionError rather than a wedged
  run.
- :func:`in_memory_session` -- async context manager wrapping the mcp
  SDK's :func:`create_connected_server_and_client_session`. The T10
  kernel-resource tests and the T11 subscription tests both need a
  real ClientSession round-trip; this helper ensures every caller
  gets the same ``client_info`` + ``read_timeout_seconds`` posture.

Design notes
------------
- We launch ``python3 -m alive_mcp`` rather than the ``alive-mcp``
  console script because test runs from a src checkout may not have
  the script on PATH. The ``-m`` form always works as long as
  ``src/`` is prepended to PYTHONPATH (which ``tests/__init__.py``
  does automatically; we replicate it here for subprocess children).
- Tests MAY mutate the fixture World inside a tempdir COPY. They MUST
  NOT mutate the committed ``tests/fixtures/world-basic/`` tree --
  determinism across CI runs depends on that tree staying frozen.
  The :func:`copy_fixture_world` helper returns a fresh tempdir with
  the fixture copied so tests can write to it freely.

No imports of pytest. No ``conftest.py``. Tests that use these helpers
do ``from tests._test_helpers import ...`` directly.
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, AsyncIterator, Iterator, List, Optional

# Path to the committed fixture World. Frozen on disk; do NOT mutate
# the tree from tests. Copy to a tempdir first if you need to write.
_THIS_DIR = pathlib.Path(__file__).resolve().parent
FIXTURE_WORLD: pathlib.Path = _THIS_DIR / "fixtures" / "world-basic"

#: Per MCP spec, stdio JSON-RPC frames are newline-delimited.
_NEWLINE = b"\n"


def _encode_frame(frame: dict[str, Any]) -> bytes:
    """Serialize a JSON-RPC frame with the exact wire shape MCP expects.

    Matches :func:`alive_mcp.envelope._text_content` and the subprocess
    harness in :mod:`test_server_bootstrap`. ``ensure_ascii=False``
    preserves Unicode identifiers on the wire (walnut paths with accents).
    """
    return json.dumps(
        frame, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8") + _NEWLINE


def _subprocess_env(
    world_root: Optional[str],
    extra: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build the subprocess environment with ``src/`` on PYTHONPATH.

    Strips any ambient World pointer from the caller's env so tests get
    deterministic behavior: either ``world_root`` wins (passed as
    ``ALIVE_WORLD_ROOT``) or the server returns ``ERR_NO_WORLD``.
    ``extra`` overrides take precedence.
    """
    env = dict(os.environ)
    env.pop("ALIVE_WORLD_ROOT", None)
    env.pop("ALIVE_WORLD_PATH", None)

    repo_src = str(_THIS_DIR.parent / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = repo_src + (
        os.pathsep + existing if existing else ""
    )
    if world_root is not None:
        env["ALIVE_WORLD_ROOT"] = world_root
    if extra:
        env.update(extra)
    return env


def start_server(
    world_root: Optional[str | os.PathLike[str]] = None,
    *,
    extra_env: Optional[dict[str, str]] = None,
) -> subprocess.Popen[bytes]:
    """Spawn the alive-mcp server as a subprocess with stdio pipes.

    Parameters
    ----------
    world_root:
        Absolute path to the World root. Exported as ``ALIVE_WORLD_ROOT``
        so the server's env-fallback discovery resolves the World before
        the first tool call. ``None`` exercises the ``ERR_NO_WORLD``
        path.
    extra_env:
        Additional environment overrides merged after the defaults.
        Used by tests that want to tweak behavior-controlling envvars
        (e.g. audit disabling).

    Returns
    -------
    :class:`subprocess.Popen`
        The server process. Caller owns lifecycle -- always wrap in a
        ``try/finally`` that calls ``proc.communicate`` or ``proc.kill``
        to avoid orphaned processes on test failure.
    """
    world = str(world_root) if world_root is not None else None
    env = _subprocess_env(world, extra_env)
    return subprocess.Popen(
        [sys.executable, "-m", "alive_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def rpc_roundtrip(
    proc: subprocess.Popen[bytes],
    frames: List[dict[str, Any]],
    *,
    timeout: float = 20.0,
) -> tuple[list[dict[str, Any]], str]:
    """Send ``frames`` to the server and collect every response frame.

    This is a one-shot helper: it writes every input frame, closes stdin
    to signal shutdown, and waits for the server to exit. Every non-
    blank line on stdout is parsed as a JSON-RPC frame. Non-JSON lines
    fail the round-trip with a ``RuntimeError`` so contaminated stdout
    is never silently ignored.

    Returns ``(response_frames, stderr_text)``. ``stderr_text`` is the
    decoded stderr so tests can assert on log content (startup banner,
    warning messages) alongside JSON-RPC replies.

    On ``subprocess.TimeoutExpired`` the process is killed and the
    exception re-raised so the test surface can fail loudly.
    """
    assert proc.stdin is not None
    payload = b"".join(_encode_frame(f) for f in frames)
    try:
        stdout, stderr = proc.communicate(input=payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise

    response_frames: list[dict[str, Any]] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            response_frames.append(json.loads(line.decode("utf-8")))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "non-JSON line on server stdout (print contamination?): "
                f"{line!r}; decode error: {exc}"
            ) from exc
    return response_frames, stderr.decode("utf-8", errors="replace")


def initialize_and_call_tool(
    world_root: str | os.PathLike[str],
    tool: str,
    arguments: dict[str, Any],
    *,
    timeout: float = 20.0,
    request_id: int = 2,
) -> dict[str, Any]:
    """Drive the full initialize -> call-tool -> shutdown cycle.

    Spawns the server, sends ``initialize`` + ``initialized`` +
    ``tools/call``, closes stdin, and returns the ``tools/call``
    response frame. Callers that need multiple tool calls in one
    server run should use :func:`start_server` + :func:`rpc_roundtrip`
    directly and compose their own frame list.

    The ``initialize`` request deliberately omits ``roots`` in
    ``capabilities`` so the server does NOT issue a server-initiated
    ``roots/list`` (the subprocess harness cannot answer mid-flight).
    World discovery happens via the ``ALIVE_WORLD_ROOT`` env pointer
    set by :func:`start_server`.
    """
    init_frame = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {
                "name": "alive-mcp-integration-harness",
                "version": "0.0.0",
            },
        },
    }
    initialized_frame = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
    call_frame = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }

    proc = start_server(world_root)
    frames = [init_frame, initialized_frame, call_frame]
    try:
        responses, _stderr = rpc_roundtrip(proc, frames, timeout=timeout)
    finally:
        if proc.poll() is None:
            proc.kill()

    for frame in responses:
        if frame.get("id") == request_id:
            return frame
    raise AssertionError(
        "server did not emit a response for tools/call (id={}); got frames: {!r}".format(
            request_id, responses
        )
    )


def tool_result_structured(frame: dict[str, Any]) -> dict[str, Any]:
    """Extract the tool's payload from a tools/call response frame.

    **Envelope unwrapping.** alive-mcp tools return the envelope dict
    :func:`alive_mcp.envelope.ok` builds
    (``{content, structuredContent, isError}``). FastMCP then wraps
    THAT dict as ``result.structuredContent`` of the JSON-RPC response.
    So the payload we actually care about lives at
    ``frame["result"]["structuredContent"]["structuredContent"]`` --
    two levels of nesting. This helper does the unwrap and returns the
    inner payload dict directly.

    Success payload (dict): returned verbatim.
    Error payload: ``{error, message, suggestions}``.
    """
    if "result" not in frame:
        raise AssertionError(
            "tools/call frame has no 'result': {!r}".format(frame)
        )
    outer = frame["result"].get("structuredContent")
    if outer is None:
        raise AssertionError(
            "tools/call result has no 'structuredContent': {!r}".format(
                frame["result"]
            )
        )
    # alive-mcp always wraps in the envelope shape; pull out the inner
    # structuredContent if present, otherwise the outer was already the
    # payload (e.g. a future tool that bypasses the envelope).
    if isinstance(outer, dict) and "structuredContent" in outer:
        return outer["structuredContent"]
    return outer


def tool_is_error(frame: dict[str, Any]) -> bool:
    """Return True if the frame's tool result is an error envelope.

    Reads the envelope's inner ``isError`` field -- the outer one that
    FastMCP sets is always False for alive-mcp because we return a
    dict, not a thrown error.
    """
    if "result" not in frame:
        return False
    outer = frame["result"].get("structuredContent")
    if isinstance(outer, dict):
        return bool(outer.get("isError"))
    return bool(frame["result"].get("isError"))


def unwrap_call_tool(result: Any) -> tuple[bool, dict[str, Any]]:
    """Unwrap a ClientSession ``call_tool`` return into (is_error, payload).

    FastMCP presents alive-mcp tools in one of two ways depending on
    how it synthesizes the output schema:

    * **Envelope shape** (``list_walnuts`` / ``get_walnut_state`` /
      ``read_walnut_kernel`` / ``list_bundles`` / ``get_bundle`` /
      ``read_bundle_manifest`` / ``read_log``):
      ``structuredContent = {content, structuredContent, isError}``
      — the tool's envelope dict surfaces AS the outer
      structuredContent, with the real payload nested at
      ``structuredContent["structuredContent"]``.
    * **Result-wrapped shape** (``search_world`` / ``search_walnut`` /
      ``list_tasks``):
      ``structuredContent = {"result": {content, structuredContent,
      isError}}`` -- FastMCP adds one extra wrap level because the
      tool declared a typing.Dict-style return hint. The real payload
      still lives two levels deep: at
      ``structuredContent["result"]["structuredContent"]``.

    Fall back to reading the text of ``result.content`` and parsing it
    as JSON if neither shape matches (defense-in-depth; covers a
    future SDK refactor that drops structuredContent entirely). The
    text block is the rendering of the same envelope so the parsed
    payload's shape is identical.
    """
    import json as _json

    sc = result.structuredContent

    def _extract_envelope(envelope: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Given a dict that IS the envelope, return (is_error, payload)."""
        inner = envelope.get("structuredContent")
        # If the inner is itself a plain dict with a ``data`` wrapper
        # (non-dict payload), unwrap again.
        if isinstance(inner, dict):
            if set(inner.keys()) == {"data"} and "data" in inner:
                return bool(envelope.get("isError")), inner
            return bool(envelope.get("isError")), inner
        return bool(envelope.get("isError")), {}

    if isinstance(sc, dict):
        # Envelope shape -- direct.
        if "isError" in sc and "structuredContent" in sc:
            return _extract_envelope(sc)
        # Result-wrapped shape.
        if set(sc.keys()) == {"result"} and isinstance(sc["result"], dict):
            inner = sc["result"]
            if "isError" in inner and "structuredContent" in inner:
                return _extract_envelope(inner)

    # Fallback: parse the text block. Every envelope emits a single
    # TextContent block whose text is the JSON-serialized
    # structuredContent (see :func:`alive_mcp.envelope._text_content`).
    content = getattr(result, "content", None) or []
    if content:
        try:
            text = content[0].text
            parsed = _json.loads(text)
            # If parsed looks like an error envelope body, surface as
            # error; otherwise surface as success.
            if isinstance(parsed, dict) and parsed.get("error") and "message" in parsed:
                return True, parsed
            return bool(getattr(result, "isError", False)), (
                parsed if isinstance(parsed, dict) else {"data": parsed}
            )
        except (AttributeError, _json.JSONDecodeError):
            pass
    return bool(getattr(result, "isError", False)), sc if isinstance(sc, dict) else {}


@contextlib.contextmanager
def copy_fixture_world() -> Iterator[pathlib.Path]:
    """Yield a tempdir containing a fresh copy of the fixture World.

    Use when a test needs to mutate the World (add walnut, write
    symlink, chmod). The original ``tests/fixtures/world-basic/`` is
    NEVER modified -- CI determinism depends on that tree staying
    frozen.

    The tempdir is cleaned up on context exit. Errors during cleanup
    are swallowed because a test-failure path often leaves open file
    handles that would otherwise mask the real failure.
    """
    tmpdir = tempfile.mkdtemp(prefix="alive-mcp-world-")
    try:
        target = pathlib.Path(tmpdir) / "world-basic"
        shutil.copytree(FIXTURE_WORLD, target, symlinks=True)
        yield target
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def wait_for_process_exit(
    proc: subprocess.Popen[bytes],
    timeout: float = 10.0,
) -> int:
    """Wait up to ``timeout`` seconds for ``proc`` to exit.

    Returns the exit code. Raises ``TimeoutError`` on timeout after
    killing the process so the test surface fails loudly rather than
    leaking subprocesses.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            return rc
        time.sleep(0.05)
    proc.kill()
    proc.communicate()
    raise TimeoutError(
        "process did not exit within {:.1f}s".format(timeout)
    )


# -----------------------------------------------------------------------------
# In-memory SDK transport. For tests that need a real ClientSession
# round-trip (tool + resource dispatch with FastMCP's own plumbing).
# -----------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def in_memory_session(
    world_root: str | os.PathLike[str],
    *,
    read_timeout_s: float = 10.0,
) -> AsyncIterator[Any]:
    """Async context manager yielding a ClientSession wired to a live server.

    Sets ``ALIVE_WORLD_ROOT`` in-process before :func:`build_server` is
    called so the lifespan's env-fallback discovery resolves the fixture
    World at startup. This is the RIGHT level to exercise the tool
    layer -- FastMCP owns dispatch, envelope serialization, and result
    shaping.

    Callers yield with ``async with in_memory_session(...) as client:``
    and drive the session via ``client.call_tool("...")``,
    ``client.list_resources()``, ``client.read_resource(uri)``, etc.

    Restores the caller's ``ALIVE_WORLD_ROOT`` on exit so parallel tests
    (or a single test running after another) do not inherit the
    fixture's pointer.
    """
    from datetime import timedelta

    from mcp import types as mcp_types
    from mcp.shared.memory import create_connected_server_and_client_session

    from alive_mcp.server import build_server

    prev_world = os.environ.get("ALIVE_WORLD_ROOT")
    os.environ["ALIVE_WORLD_ROOT"] = str(world_root)
    try:
        server = build_server()
        async with create_connected_server_and_client_session(
            server,
            client_info=mcp_types.Implementation(
                name="alive-mcp-integration-harness",
                version="0.0.0",
            ),
            read_timeout_seconds=timedelta(seconds=read_timeout_s),
        ) as client:
            yield client
    finally:
        if prev_world is None:
            os.environ.pop("ALIVE_WORLD_ROOT", None)
        else:
            os.environ["ALIVE_WORLD_ROOT"] = prev_world


__all__ = [
    "FIXTURE_WORLD",
    "copy_fixture_world",
    "in_memory_session",
    "initialize_and_call_tool",
    "rpc_roundtrip",
    "start_server",
    "tool_is_error",
    "tool_result_structured",
    "unwrap_call_tool",
    "wait_for_process_exit",
]
