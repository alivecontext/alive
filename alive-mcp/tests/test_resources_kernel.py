"""Kernel resource tests (fn-10-60k.10 / T10).

Exercises the ``alive://`` resource surface end-to-end through the mcp
SDK's in-memory transport. Using the real transport catches drift in
the URL type wrapping, capability negotiation, and notification
dispatch that a direct-handler-call test would miss.

Layout:

* :class:`KernelResourceListTests` -- ``resources/list`` shape,
  per-walnut enumeration, MIME types, presence for missing files.
* :class:`KernelResourceReadTests` -- ``resources/read`` happy paths,
  v3/v2 now-json fallback, UTF-8 content, error cases (bad walnut,
  missing file, path escape attempt).
* :class:`KernelResourceRegisterTests` -- in-process sanity that
  :func:`register` swaps the FastMCP defaults without breaking the
  server.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta
from typing import Any, Optional

# Make ``src/`` importable the same way tests/__init__.py does.
import tests  # noqa: F401

from alive_mcp.uri import decode_kernel_uri, encode_kernel_uri  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture World builder. Mirrors the helper in test_tools_walnut.py so
# tests stay self-contained and readable -- deliberately duplicated
# rather than pulled into a shared conftest because unittest tests tend
# to read better with inline fixtures.
# ---------------------------------------------------------------------------


def _new_world() -> tuple[pathlib.Path, Any]:
    tmpdir = tempfile.mkdtemp(prefix="alive-mcp-resource-test-")
    root = pathlib.Path(tmpdir)
    (root / ".alive").mkdir()  # World predicate sentinel.
    cleanup = lambda: shutil.rmtree(tmpdir, ignore_errors=True)  # noqa: E731
    return root, cleanup


def _write_kernel_file(
    world_root: pathlib.Path, walnut_rel: str, name: str, content: str
) -> pathlib.Path:
    target = world_root / walnut_rel / "_kernel" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _make_walnut(
    world_root: pathlib.Path,
    rel: str,
    *,
    goal: str = "",
    rhythm: str = "weekly",
    updated: Optional[str] = None,
    log_body: str = "",
    insights_body: str = "",
    v2_now: bool = False,
) -> None:
    """Create a walnut with the four canonical kernel files.

    ``v2_now`` writes ``_kernel/_generated/now.json`` instead of the
    v3 flat layout. Used to exercise the fallback resolution path.
    """
    fm = ["---", "type: venture"]
    if goal:
        fm.append("goal: {}".format(goal))
    if rhythm:
        fm.append("rhythm: {}".format(rhythm))
    fm.append("---")
    fm.append("")
    fm.append("# {}".format(rel))
    _write_kernel_file(world_root, rel, "key.md", "\n".join(fm))

    if updated is not None:
        payload = {"phase": "building", "updated": updated, "next": None}
        if v2_now:
            target = world_root / rel / "_kernel" / "_generated" / "now.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload), encoding="utf-8")
        else:
            _write_kernel_file(
                world_root, rel, "now.json", json.dumps(payload)
            )

    if log_body:
        _write_kernel_file(world_root, rel, "log.md", log_body)
    if insights_body:
        _write_kernel_file(world_root, rel, "insights.md", insights_body)


# ---------------------------------------------------------------------------
# In-memory session harness. Wraps
# :func:`create_connected_server_and_client_session` with a Roots callback
# that anchors the server at a given fixture World.
# ---------------------------------------------------------------------------


def _run_with_world(world_root: pathlib.Path, coro_factory: Any) -> Any:
    """Spin up a server bound to ``world_root`` and run a client coroutine.

    ``coro_factory`` takes a connected ClientSession and returns a
    coroutine; we await it inside a configured in-memory session.
    Equivalent to the harness in test_server_bootstrap.py but stripped
    down to the minimum this test module needs.
    """
    from mcp import types as mcp_types
    from mcp.shared.memory import create_connected_server_and_client_session

    from alive_mcp.server import build_server

    async def runner() -> Any:
        world_uri = pathlib.Path(world_root).as_uri()

        async def list_roots_cb(ctx: Any) -> mcp_types.ListRootsResult:
            return mcp_types.ListRootsResult(
                roots=[
                    mcp_types.Root(
                        uri=world_uri,  # type: ignore[arg-type]
                        name="fixture",
                    )
                ]
            )

        server = build_server()
        async with create_connected_server_and_client_session(
            server,
            list_roots_callback=list_roots_cb,
            client_info=mcp_types.Implementation(
                name="alive-mcp-resource-test",
                version="0.0.0",
            ),
            read_timeout_seconds=timedelta(seconds=10),
        ) as client:
            # Let the initialized notification + Roots discovery land
            # before the test touches anything.
            await asyncio.sleep(0.25)
            return await coro_factory(client)

    return asyncio.run(runner())


# ---------------------------------------------------------------------------
# list_resources tests.
# ---------------------------------------------------------------------------


class KernelResourceListTests(unittest.TestCase):
    """``resources/list`` enumerates 4 entries per walnut."""

    def setUp(self) -> None:
        self.world_root, cleanup = _new_world()
        self.addCleanup(cleanup)

        _make_walnut(
            self.world_root,
            "04_Ventures/alive",
            goal="Build the ALIVE Context System",
            updated="2026-04-15T12:00:00Z",
            log_body="---\nwalnut: alive\n---\n\nlog body\n",
            insights_body="---\nsections: []\n---\n\ninsights body\n",
        )
        _make_walnut(
            self.world_root,
            "02_Life/people/ben-flint",
            goal="Keep Ben updated",
            updated="2026-04-10T12:00:00Z",
        )

    def test_returns_four_entries_per_walnut(self) -> None:
        async def factory(client: Any) -> Any:
            return await client.list_resources()

        result = _run_with_world(self.world_root, factory)
        # Two walnuts x four kernel files = 8 entries.
        self.assertEqual(len(result.resources), 8)

    def test_entry_shape_matches_contract(self) -> None:
        async def factory(client: Any) -> Any:
            return await client.list_resources()

        result = _run_with_world(self.world_root, factory)
        for entry in result.resources:
            self.assertTrue(str(entry.uri).startswith("alive://walnut/"))
            self.assertIn(entry.mimeType, ("text/markdown", "application/json"))
            self.assertIsNotNone(entry.name)
            self.assertIsNotNone(entry.description)

    def test_every_walnut_gets_all_four_files_even_when_missing(self) -> None:
        """A fresh walnut (only key.md) still exposes all four URIs.

        The acceptance bullet "resources/list returns 4 x walnut_count
        entries" is tested here. Clients expect a stable resource
        inventory -- a fresh walnut's log.md not existing yet does NOT
        drop the log resource from the list.
        """
        async def factory(client: Any) -> Any:
            return await client.list_resources()

        result = _run_with_world(self.world_root, factory)
        uris = {str(r.uri) for r in result.resources}
        for walnut_path in (
            "04_Ventures/alive",
            "02_Life/people/ben-flint",
        ):
            for file in ("key", "log", "insights", "now"):
                expected = encode_kernel_uri(walnut_path, file)
                self.assertIn(
                    expected,
                    uris,
                    msg="missing resource {!r}".format(expected),
                )

    def test_mime_type_matches_file(self) -> None:
        async def factory(client: Any) -> Any:
            return await client.list_resources()

        result = _run_with_world(self.world_root, factory)
        for entry in result.resources:
            walnut_path, file = decode_kernel_uri(str(entry.uri))
            if file == "now":
                self.assertEqual(entry.mimeType, "application/json")
            else:
                self.assertEqual(entry.mimeType, "text/markdown")

    def test_name_uses_display_form_plus_file_stem(self) -> None:
        async def factory(client: Any) -> Any:
            return await client.list_resources()

        result = _run_with_world(self.world_root, factory)
        by_uri = {str(r.uri): r for r in result.resources}
        uri = encode_kernel_uri("02_Life/people/ben-flint", "log")
        self.assertEqual(by_uri[uri].name, "ben-flint log")

    def test_walnut_with_unicode_path_encodes_properly(self) -> None:
        """A walnut whose basename has unicode yields a percent-encoded URI.

        ``hélène`` -> ``h%C3%A9l%C3%A8ne`` in the URI; the filesystem
        directory is the raw unicode text. Listing must emit the
        encoded URI so clients can round-trip it back on read.
        """
        _make_walnut(
            self.world_root,
            "04_Ventures/h\u00e9l\u00e8ne",
            goal="Unicode walnut",
            updated="2026-04-15T12:00:00Z",
        )

        async def factory(client: Any) -> Any:
            return await client.list_resources()

        result = _run_with_world(self.world_root, factory)
        uris = {str(r.uri) for r in result.resources}
        expected = encode_kernel_uri(
            "04_Ventures/h\u00e9l\u00e8ne", "log"
        )
        self.assertIn(expected, uris)
        # The raw URI must contain the percent-encoded unicode bytes.
        self.assertIn("%C3%A9", expected)


# ---------------------------------------------------------------------------
# read_resource tests.
# ---------------------------------------------------------------------------


class KernelResourceReadTests(unittest.TestCase):
    """``resources/read`` happy paths + error shapes."""

    def setUp(self) -> None:
        self.world_root, cleanup = _new_world()
        self.addCleanup(cleanup)

        _make_walnut(
            self.world_root,
            "04_Ventures/alive",
            goal="Build the ALIVE Context System",
            updated="2026-04-15T12:00:00Z",
            log_body="---\nwalnut: alive\n---\n\nThe log body.\n",
            insights_body="---\nsections: []\n---\n\nThe insights body.\n",
        )

    def _read(self, client: Any, uri: str) -> Any:
        from pydantic import AnyUrl
        return client.read_resource(AnyUrl(uri))

    def test_read_log_returns_markdown_content(self) -> None:
        uri = encode_kernel_uri("04_Ventures/alive", "log")

        async def factory(client: Any) -> Any:
            return await self._read(client, uri)

        result = _run_with_world(self.world_root, factory)
        self.assertEqual(len(result.contents), 1)
        content = result.contents[0]
        self.assertEqual(content.mimeType, "text/markdown")
        self.assertIn("The log body.", content.text)

    def test_read_now_returns_json_content(self) -> None:
        """``now`` URI returns the raw JSON text, not a parsed dict.

        Matches the task acceptance: "alive://walnut/04_Ventures/alive/
        kernel/now returns parsed _kernel/now.json + MIME
        application/json". Resource reads always return text; the MIME
        tells the client how to parse it.
        """
        uri = encode_kernel_uri("04_Ventures/alive", "now")

        async def factory(client: Any) -> Any:
            return await self._read(client, uri)

        result = _run_with_world(self.world_root, factory)
        self.assertEqual(len(result.contents), 1)
        content = result.contents[0]
        self.assertEqual(content.mimeType, "application/json")
        parsed = json.loads(content.text)
        self.assertEqual(parsed["phase"], "building")

    def test_read_now_falls_back_to_v2_layout(self) -> None:
        """Walnut with only ``_generated/now.json`` (v2 layout) still reads.

        Matches :func:`walnut_tools._resolve_now_path` semantics --
        v3 first, then v2 fallback.
        """
        _make_walnut(
            self.world_root,
            "04_Ventures/v2-walnut",
            goal="v2 layout",
            updated="2026-04-10T12:00:00Z",
            v2_now=True,
        )
        uri = encode_kernel_uri("04_Ventures/v2-walnut", "now")

        async def factory(client: Any) -> Any:
            return await self._read(client, uri)

        result = _run_with_world(self.world_root, factory)
        self.assertEqual(len(result.contents), 1)
        parsed = json.loads(result.contents[0].text)
        self.assertEqual(parsed["updated"], "2026-04-10T12:00:00Z")

    def test_read_key_returns_markdown_content(self) -> None:
        uri = encode_kernel_uri("04_Ventures/alive", "key")

        async def factory(client: Any) -> Any:
            return await self._read(client, uri)

        result = _run_with_world(self.world_root, factory)
        self.assertEqual(result.contents[0].mimeType, "text/markdown")
        self.assertIn("goal: Build the ALIVE Context System", result.contents[0].text)

    def test_read_insights_returns_markdown_content(self) -> None:
        uri = encode_kernel_uri("04_Ventures/alive", "insights")

        async def factory(client: Any) -> Any:
            return await self._read(client, uri)

        result = _run_with_world(self.world_root, factory)
        self.assertIn("The insights body.", result.contents[0].text)

    def test_read_missing_walnut_raises_invalid_params(self) -> None:
        from mcp.shared.exceptions import McpError
        uri = encode_kernel_uri("04_Ventures/does-not-exist", "log")

        async def factory(client: Any) -> Any:
            try:
                await self._read(client, uri)
            except McpError as exc:
                return exc
            return None

        exc = _run_with_world(self.world_root, factory)
        self.assertIsNotNone(exc)
        # MCP INVALID_PARAMS = -32602.
        self.assertEqual(exc.error.code, -32602)

    def test_read_missing_kernel_file_raises_invalid_params(self) -> None:
        """A walnut with no log.md still has a listed log resource,
        but reading it must surface a clear error rather than return
        empty content."""
        _make_walnut(
            self.world_root,
            "04_Ventures/minimal",
            goal="x",
            updated="2026-04-10T12:00:00Z",
            # No log or insights written.
        )
        from mcp.shared.exceptions import McpError
        uri = encode_kernel_uri("04_Ventures/minimal", "log")

        async def factory(client: Any) -> Any:
            try:
                await self._read(client, uri)
            except McpError as exc:
                return exc
            return None

        exc = _run_with_world(self.world_root, factory)
        self.assertIsNotNone(exc)
        self.assertEqual(exc.error.code, -32602)

    def test_read_path_escape_rejected(self) -> None:
        """A URI attempting to escape via ``..`` must be rejected at decode.

        The decoder raises :class:`InvalidURIError` for ``..`` segments,
        which the resource handler maps to ``INVALID_PARAMS``. This
        test exercises the end-to-end rejection path -- even if a
        malicious client bypassed the encoder, the server layer stops
        the attempt.
        """
        from mcp.shared.exceptions import McpError
        # Hand-build the URI; encode_kernel_uri would refuse.
        malicious = "alive://walnut/04_Ventures/../etc/kernel/log"

        async def factory(client: Any) -> Any:
            from pydantic import AnyUrl
            try:
                await client.read_resource(AnyUrl(malicious))
            except McpError as exc:
                return exc
            return None

        exc = _run_with_world(self.world_root, factory)
        self.assertIsNotNone(exc)
        self.assertEqual(exc.error.code, -32602)

    def test_read_unknown_scheme_rejected(self) -> None:
        """A URI with the wrong scheme is rejected at decode."""
        from mcp.shared.exceptions import McpError

        async def factory(client: Any) -> Any:
            from pydantic import AnyUrl
            try:
                await client.read_resource(
                    AnyUrl("file:///etc/passwd")
                )
            except McpError as exc:
                return exc
            return None

        exc = _run_with_world(self.world_root, factory)
        self.assertIsNotNone(exc)
        # Either -32602 (we rejected it) or the SDK's own unknown-
        # resource mapping. Accept both: the important property is
        # that we didn't serve /etc/passwd.
        self.assertIn(exc.error.code, (-32602, -32603))


# ---------------------------------------------------------------------------
# Registration + capability cross-check.
# ---------------------------------------------------------------------------


class KernelResourceRegisterTests(unittest.TestCase):
    """:func:`register` wires handlers onto the low-level server.

    In-process test -- no session round-trip. Confirms the handlers
    ended up in ``request_handlers`` for the two resource request
    types (list + read), and that capability declaration still emits
    the v0.1 matrix.
    """

    def test_register_installs_list_and_read_handlers(self) -> None:
        from mcp import types as mcp_types

        from alive_mcp.server import build_server

        server = build_server()
        # build_server already calls register(); both handlers must be
        # present.
        self.assertIn(
            mcp_types.ListResourcesRequest,
            server._mcp_server.request_handlers,
        )
        self.assertIn(
            mcp_types.ReadResourceRequest,
            server._mcp_server.request_handlers,
        )

    def test_capabilities_advertise_resources(self) -> None:
        """T10 ships list+read; T11 ships subscribe+listChanged delivery.

        The capability matrix was frozen in T5 and must remain stable
        as T10 lands -- registering resource handlers should not
        regress ``subscribe=True, listChanged=True``.
        """
        from mcp.server.lowlevel.server import NotificationOptions

        from alive_mcp.server import build_server

        server = build_server()
        caps = server._mcp_server.get_capabilities(NotificationOptions(), {})
        self.assertIsNotNone(caps.resources)
        self.assertTrue(caps.resources.subscribe)
        self.assertTrue(caps.resources.listChanged)


# Platform guards: the in-memory session transport works on all platforms,
# so no skip needed.


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
