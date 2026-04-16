"""End-to-end integration tests against a fixture World (fn-10-60k.13 / T13).

Drives the alive-mcp FastMCP server through a real
:class:`mcp.shared.memory.create_connected_server_and_client_session`
transport so every test exercises the full dispatch + envelope path --
not a direct handler call. Scope:

* One TestCase class per tool family (Walnut, Bundle, Search,
  Log/Tasks, Resources). Each class calls every tool in its family
  against the committed ``tests/fixtures/world-basic/`` tree and
  asserts response shape + content.
* Subprocess smoke test exercises the stdio JSON-RPC transport with
  the fixture world (the T5 tests cover protocol-level handshake
  checks; this test adds a tool-call over stdio against the fixture).
* Resources family covers ``resources/list`` (12 resource entries = 3
  walnuts x 4 kernel files each) and ``resources/read`` for every file
  stem.

Envelope-unwrap convention
--------------------------
alive-mcp tools return the envelope dict
(``{content, structuredContent, isError}``) directly. FastMCP then
wraps that WHOLE dict as ``result.structuredContent`` on the client
side. The real payload therefore lives at
``result.structuredContent['structuredContent']`` and the real error
flag at ``result.structuredContent['isError']``. The
:func:`unwrap_call_tool` helper in
:mod:`tests._test_helpers` encapsulates the two-level unwrap; every
test here uses it.

Fixture mutation policy
-----------------------
The committed ``tests/fixtures/world-basic/`` tree is FROZEN -- do NOT
write to it. Tests that need to mutate a World use
:func:`tests._test_helpers.copy_fixture_world` and operate on a
tempdir copy. The frozen tree is small (3 walnuts, 2 bundles, 5 log
entries, 4 tasks across two tasks.json files) so per-test in-memory
server boots remain cheap.
"""
from __future__ import annotations

import asyncio
import unittest
from typing import Any

# Side-effect import to ensure ``src/`` is on sys.path.
import tests  # noqa: F401

from tests._test_helpers import (  # noqa: E402
    FIXTURE_WORLD,
    in_memory_session,
    initialize_and_call_tool,
    tool_is_error,
    tool_result_structured,
    unwrap_call_tool,
)


def _run(coro: Any) -> Any:
    """Run an async coroutine with a clean event loop per test."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Expected inventory. Keep in sync with the fixture tree; any drift here
# catches an unintended fixture change.
# ---------------------------------------------------------------------------

EXPECTED_WALNUTS = [
    "02_Life/people/ben",
    "02_Life/people/sarah",
    "04_Ventures/nova-station",
]

EXPECTED_BUNDLES_NOVA = [
    "launch-checklist",
    "shielding-review",
]


class WalnutToolsIntegration(unittest.TestCase):
    """End-to-end coverage for list_walnuts / get_walnut_state / read_walnut_kernel."""

    def test_list_walnuts_returns_three_entries(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool("list_walnuts", arguments={})
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                self.assertEqual(payload["total"], 3)
                self.assertIsNone(payload["next_cursor"])
                paths = [w["path"] for w in payload["walnuts"]]
                self.assertEqual(sorted(paths), EXPECTED_WALNUTS)

                # Every entry carries the 6-key schema.
                for entry in payload["walnuts"]:
                    self.assertEqual(
                        set(entry.keys()),
                        {"path", "name", "domain", "goal", "health", "updated"},
                    )
                # Domain derives from the first path segment.
                by_path = {w["path"]: w for w in payload["walnuts"]}
                self.assertEqual(by_path[EXPECTED_WALNUTS[0]]["domain"], "02_Life")
                self.assertEqual(by_path[EXPECTED_WALNUTS[2]]["domain"], "04_Ventures")

        _run(run())

    def test_list_walnuts_respects_limit_and_cursor(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                page1 = await client.call_tool(
                    "list_walnuts", arguments={"limit": 2}
                )
                _, p1 = unwrap_call_tool(page1)
                self.assertEqual(len(p1["walnuts"]), 2)
                self.assertIsNotNone(p1["next_cursor"])
                self.assertEqual(p1["total"], 3)

                page2 = await client.call_tool(
                    "list_walnuts",
                    arguments={"limit": 2, "cursor": p1["next_cursor"]},
                )
                _, p2 = unwrap_call_tool(page2)
                self.assertEqual(len(p2["walnuts"]), 1)
                self.assertIsNone(p2["next_cursor"])
                # No overlap -- cursor semantics preserve ordering.
                page1_paths = {w["path"] for w in p1["walnuts"]}
                page2_paths = {w["path"] for w in p2["walnuts"]}
                self.assertFalse(page1_paths & page2_paths)

        _run(run())

    def test_list_walnuts_invalid_cursor_rejected(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "list_walnuts", arguments={"cursor": "not-base64!"}
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertTrue(is_err)
                self.assertEqual(payload["error"], "INVALID_CURSOR")

        _run(run())

    def test_get_walnut_state_returns_now_json(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "get_walnut_state",
                    arguments={"walnut": "04_Ventures/nova-station"},
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                self.assertEqual(payload["phase"], "testing")
                self.assertEqual(payload["bundle"], "shielding-review")
                self.assertEqual(
                    payload["next"], "Review telemetry from March 4 test window"
                )

        _run(run())

    def test_get_walnut_state_unknown_walnut_returns_not_found(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "get_walnut_state",
                    arguments={"walnut": "04_Ventures/does-not-exist"},
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertTrue(is_err)
                self.assertEqual(payload["error"], "WALNUT_NOT_FOUND")

        _run(run())

    def test_read_walnut_kernel_each_file_stem(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                for stem, expected_mime in (
                    ("key", "text/markdown"),
                    ("log", "text/markdown"),
                    ("insights", "text/markdown"),
                    ("now", "application/json"),
                ):
                    result = await client.call_tool(
                        "read_walnut_kernel",
                        arguments={
                            "walnut": "04_Ventures/nova-station",
                            "file": stem,
                        },
                    )
                    is_err, payload = unwrap_call_tool(result)
                    self.assertFalse(
                        is_err,
                        msg=f"read_walnut_kernel failed for stem={stem!r}: {payload!r}",
                    )
                    self.assertEqual(payload["mime"], expected_mime)
                    self.assertGreater(len(payload["content"]), 0)

                # The log has our 5 fixture entries.
                log_result = await client.call_tool(
                    "read_walnut_kernel",
                    arguments={
                        "walnut": "04_Ventures/nova-station",
                        "file": "log",
                    },
                )
                _, log_payload = unwrap_call_tool(log_result)
                self.assertEqual(log_payload["content"].count("## 20"), 5)

        _run(run())


class BundleToolsIntegration(unittest.TestCase):
    """End-to-end coverage for list_bundles / get_bundle / read_bundle_manifest."""

    def test_list_bundles_returns_two_entries(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "list_bundles",
                    arguments={"walnut": "04_Ventures/nova-station"},
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                bundles = payload["bundles"]
                names = sorted(b["name"] for b in bundles)
                self.assertEqual(names, EXPECTED_BUNDLES_NOVA)

                by_name = {b["name"]: b for b in bundles}
                self.assertEqual(by_name["shielding-review"]["status"], "draft")
                self.assertEqual(by_name["launch-checklist"]["status"], "prototype")

        _run(run())

    def test_list_bundles_empty_for_person_walnut(self) -> None:
        """People walnuts legitimately have no bundles in the fixture."""

        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "list_bundles",
                    arguments={"walnut": "02_Life/people/ben"},
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                self.assertEqual(payload["bundles"], [])

        _run(run())

    def test_get_bundle_returns_manifest_and_derived_counts(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "get_bundle",
                    arguments={
                        "walnut": "04_Ventures/nova-station",
                        "bundle": "shielding-review",
                    },
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err, msg=f"get_bundle failed: {payload!r}")
                manifest = payload["manifest"]
                self.assertEqual(manifest["status"], "draft")
                self.assertEqual(
                    manifest["goal"],
                    "Complete the shielding vendor review and lock a supplier",
                )
                self.assertIn("context", manifest)
                self.assertIsNotNone(manifest["context"])

                derived = payload["derived"]
                counts = derived["task_counts"]
                # shielding-review tasks.json: sr-001 (priority=urgent,
                # status=active), sr-002 (status=active), sr-003
                # (status=todo). urgent is a priority bucket and
                # OVERLAPS with status buckets (sr-001 gets counted in
                # both urgent and active), so the sum exceeds the
                # three-task total -- that's the documented
                # summary_from_walnut semantics.
                self.assertEqual(counts["urgent"], 1)
                self.assertEqual(counts["active"], 2)
                self.assertEqual(counts["todo"], 1)
                # raw/ has one file.
                self.assertGreaterEqual(derived["raw_file_count"], 1)

        _run(run())

    def test_read_bundle_manifest_returns_nine_keys(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "read_bundle_manifest",
                    arguments={
                        "walnut": "04_Ventures/nova-station",
                        "bundle": "launch-checklist",
                    },
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                manifest = payload["manifest"]
                expected_keys = {
                    "name",
                    "goal",
                    "outcome",
                    "status",
                    "phase",
                    "updated",
                    "due",
                    "context",
                    "active_sessions",
                }
                self.assertEqual(set(manifest.keys()), expected_keys)
                self.assertEqual(manifest["status"], "prototype")
                self.assertIn("warnings", payload)

        _run(run())

    def test_get_bundle_unknown_bundle_returns_not_found(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "get_bundle",
                    arguments={
                        "walnut": "04_Ventures/nova-station",
                        "bundle": "no-such-bundle",
                    },
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertTrue(is_err)
                self.assertEqual(payload["error"], "BUNDLE_NOT_FOUND")

        _run(run())


class SearchToolsIntegration(unittest.TestCase):
    """End-to-end coverage for search_world / search_walnut."""

    def test_search_world_finds_known_token(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                # ``shielding`` appears in nova-station's key.md, log.md,
                # insights.md, and the shielding-review manifest.
                result = await client.call_tool(
                    "search_world", arguments={"query": "shielding"}
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                matches = payload["matches"]
                self.assertGreater(len(matches), 0)
                walnuts_hit = {m["walnut"] for m in matches}
                self.assertIn("04_Ventures/nova-station", walnuts_hit)
                for m in matches:
                    self.assertIn("walnut", m)
                    self.assertIn("file", m)
                    self.assertIn("line_number", m)
                    self.assertIn("content", m)

        _run(run())

    def test_search_walnut_scopes_to_one_walnut(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "search_walnut",
                    arguments={
                        "walnut": "02_Life/people/ben",
                        "query": "shielding",
                    },
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                matches = payload["matches"]
                self.assertGreater(len(matches), 0)
                # search_walnut emits walnut-relative paths (no domain prefix).
                for m in matches:
                    self.assertFalse(
                        m["file"].startswith("02_Life"),
                        msg=f"search_walnut file should be walnut-relative: {m['file']!r}",
                    )

        _run(run())

    def test_search_world_is_case_insensitive_by_default(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                r_lower = await client.call_tool(
                    "search_world", arguments={"query": "shielding"}
                )
                r_upper = await client.call_tool(
                    "search_world", arguments={"query": "SHIELDING"}
                )
                _, p_lower = unwrap_call_tool(r_lower)
                _, p_upper = unwrap_call_tool(r_upper)
                self.assertEqual(
                    len(p_lower["matches"]), len(p_upper["matches"])
                )

        _run(run())

    def test_search_world_empty_result_is_not_error(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "search_world",
                    arguments={"query": "xyzzy-no-such-token-shields-42"},
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                self.assertEqual(payload["matches"], [])

        _run(run())


class LogAndTaskToolsIntegration(unittest.TestCase):
    """End-to-end coverage for read_log / list_tasks."""

    def test_read_log_returns_five_entries_newest_first(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "read_log",
                    arguments={
                        "walnut": "04_Ventures/nova-station",
                        "limit": 10,
                    },
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                self.assertEqual(payload["total_entries"], 5)
                self.assertEqual(payload["total_chapters"], 0)
                self.assertEqual(len(payload["entries"]), 5)
                self.assertIsNone(payload["next_offset"])
                self.assertFalse(payload["chapter_boundary_crossed"])
                # Newest first -- the first entry is the 2026-04-15 one.
                self.assertIn("2026-04-15", payload["entries"][0]["timestamp"])

        _run(run())

    def test_read_log_pagination_offset_and_limit(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                first = await client.call_tool(
                    "read_log",
                    arguments={
                        "walnut": "04_Ventures/nova-station",
                        "offset": 0,
                        "limit": 2,
                    },
                )
                _, p1 = unwrap_call_tool(first)
                self.assertEqual(len(p1["entries"]), 2)
                self.assertEqual(p1["next_offset"], 2)

                second = await client.call_tool(
                    "read_log",
                    arguments={
                        "walnut": "04_Ventures/nova-station",
                        "offset": 2,
                        "limit": 2,
                    },
                )
                _, p2 = unwrap_call_tool(second)
                self.assertEqual(len(p2["entries"]), 2)
                self.assertEqual(p2["next_offset"], 4)

        _run(run())

    def test_list_tasks_walnut_scope_four_items(self) -> None:
        """Walnut-scoped list aggregates across all bundles.

        Fixture total: shielding-review has 3 tasks, launch-checklist has 1.
        Count buckets: ``urgent`` is a PRIORITY bucket (can overlap with
        status buckets), whereas ``active``/``todo``/``blocked``/``done``
        are STATUS buckets. A task can be counted in ``urgent`` AND one
        of the status buckets simultaneously, so the count-sum can
        exceed the task list length. This matches
        :func:`tasks_pure.summary_from_walnut` semantics.
        """

        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "list_tasks",
                    arguments={"walnut": "04_Ventures/nova-station"},
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                self.assertEqual(len(payload["tasks"]), 4)
                counts = payload["counts"]
                # Fixture has 1 urgent-priority task (sr-001, status=active),
                # 3 status=active tasks total (sr-001, sr-002, lc-001), and
                # 1 status=todo (sr-003).
                self.assertEqual(counts["urgent"], 1)
                self.assertEqual(counts["active"], 3)
                self.assertEqual(counts["todo"], 1)

        _run(run())

    def test_list_tasks_bundle_scope(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.call_tool(
                    "list_tasks",
                    arguments={
                        "walnut": "04_Ventures/nova-station",
                        "bundle": "shielding-review",
                    },
                )
                is_err, payload = unwrap_call_tool(result)
                self.assertFalse(is_err)
                self.assertEqual(len(payload["tasks"]), 3)
                self.assertEqual(payload["counts"]["urgent"], 1)

        _run(run())


class ResourceListAndReadIntegration(unittest.TestCase):
    """End-to-end coverage for resources/list + resources/read."""

    def test_list_resources_covers_every_walnut_file_pair(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                result = await client.list_resources()
                # Three walnuts times four kernel files each = 12 entries.
                self.assertEqual(len(result.resources), 12)
                uris = sorted(str(r.uri) for r in result.resources)
                for walnut in EXPECTED_WALNUTS:
                    for stem in ("key", "log", "insights", "now"):
                        expected = f"alive://walnut/{walnut}/kernel/{stem}"
                        self.assertIn(expected, uris)

        _run(run())

    def test_read_resource_each_kernel_file(self) -> None:
        async def run() -> None:
            async with in_memory_session(FIXTURE_WORLD) as client:
                for stem, expected_mime in (
                    ("key", "text/markdown"),
                    ("log", "text/markdown"),
                    ("insights", "text/markdown"),
                    ("now", "application/json"),
                ):
                    uri = f"alive://walnut/04_Ventures/nova-station/kernel/{stem}"
                    result = await client.read_resource(uri)
                    self.assertEqual(len(result.contents), 1)
                    contents = result.contents[0]
                    self.assertEqual(contents.mimeType, expected_mime)
                    self.assertGreater(len(contents.text), 0)

        _run(run())

    def test_read_resource_malformed_uri_raises_error(self) -> None:
        """Malformed alive:// URIs surface as MCP JSON-RPC errors."""

        async def run() -> None:
            from mcp.shared.exceptions import McpError

            async with in_memory_session(FIXTURE_WORLD) as client:
                with self.assertRaises(McpError):
                    await client.read_resource(
                        "alive://walnut/04_Ventures/nova-station/kernel/bogus"
                    )

        _run(run())


class StdioTransportIntegration(unittest.TestCase):
    """Exercise the actual stdio transport end-to-end with the fixture.

    The other classes use the in-memory SDK transport for speed. This
    class verifies the ``python -m alive_mcp`` subprocess can drive the
    same tool roster via JSON-RPC over pipes, which is what real MCP
    clients (Claude Desktop, Cursor) do. One test is enough -- T5
    already covers transport-level edge cases (EOF, stdout discipline,
    startup banner).
    """

    def test_list_walnuts_over_stdio(self) -> None:
        frame = initialize_and_call_tool(
            FIXTURE_WORLD,
            tool="list_walnuts",
            arguments={},
            timeout=20.0,
        )
        self.assertFalse(tool_is_error(frame))
        payload = tool_result_structured(frame)
        self.assertEqual(payload["total"], 3)
        self.assertEqual(
            sorted(w["path"] for w in payload["walnuts"]),
            EXPECTED_WALNUTS,
        )


if __name__ == "__main__":
    unittest.main()
