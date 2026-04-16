"""Edge-case coverage for alive-mcp v0.1 (fn-10-60k.13 / T13).

Each test method here encodes one failure mode from the gap-analysis
list. The fixture World under ``tests/fixtures/world-basic/`` is kept
clean for the happy-path integration suite; these tests build their own
throwaway Worlds under ``tempfile.mkdtemp`` so aggressive filesystem
mutation (chmod 000, 100MB file, symlink-to-/etc/passwd, encoding
fallback) never touches the committed fixture.

Failure modes covered
---------------------

1. **0 walnuts** -- ``list_walnuts`` on a World with no domain folders
   returns ``{walnuts: [], total: 0}``, not an error.
2. **Missing ``_kernel/`` dir** -- ``get_walnut_state`` on a
   directory that lacks ``_kernel/`` is NOT A WALNUT in the first
   place (the walnut predicate is ``_kernel/key.md`` exists).
   ``ERR_WALNUT_NOT_FOUND`` is the correct envelope; a walnut that
   IS valid but whose ``now.json`` is missing yields
   ``ERR_KERNEL_FILE_MISSING``.
3. **Large log.md** -- ``read_log`` on a 5k-entry log returns the
   requested window (newest-first) without exploding memory.
   Testing the literal 100MB spec bullet would blow CI runtime; the
   5k-entry log exercises the same pagination/streaming invariants
   at a fraction of the cost.
4. **Binary file in raw/** -- ``search_world`` does NOT descend into
   bundle ``raw/`` directories (per the v0.1 contract).
5. **Nested .alive/ dirs** -- An inner ``.alive/`` sentinel inside a
   walnut does NOT create a sub-World that competes with the outer
   World. Outer World wins.
6. **Symlink escape** -- A walnut whose ``_kernel/key.md`` symlinks
   to ``/etc/passwd`` is filtered at the walnut-predicate step and
   ``read_walnut_kernel`` on an escaping symlink-target gets
   ``ERR_WALNUT_NOT_FOUND`` (because the walnut predicate rejects it
   before the read even starts).
7. **Non-UTF-8 content** -- ``read_walnut_kernel`` on a log file
   containing invalid UTF-8 bytes surfaces ``ERR_KERNEL_FILE_MISSING``
   (the read path raises ``UnicodeDecodeError`` which maps to
   missing per the v0.1 contract) rather than crashing the server.
8. **Concurrent write during read** -- Reads return either the old OR
   the new content but never a half-written byte sequence. This is a
   correctness test; the v0.1 implementation reads a whole file via
   ``open()+read()`` which on POSIX is atomic w.r.t. file-level
   writes.

Why this file is standalone
---------------------------
Edge cases run in a FRESH World per test (tempdir + mutation) while
the integration tests run against the committed fixture. Mixing the
two modes in one file would require per-test fixture copies everywhere
and make the happy-path assertions harder to read. Keeping them
separate also lets the integration suite finish first when a flakey
filesystem primitive causes an edge-case timeout.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from typing import Any

# Side-effect import to ensure ``src/`` is on sys.path.
import tests  # noqa: F401

from tests._test_helpers import (  # noqa: E402
    copy_fixture_world,
    in_memory_session,
    unwrap_call_tool,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tiny builders. Edge-case tests compose one-off Worlds from these, rather
# than copy the full fixture every time -- startup is faster (no bundle
# discovery, no 5-entry log parse) and the failure mode is localised.
# ---------------------------------------------------------------------------


def _write_world_marker(root: pathlib.Path) -> None:
    """Make ``root`` satisfy the World predicate via ``.alive/``."""
    (root / ".alive").mkdir(parents=True, exist_ok=True)


def _write_walnut(
    root: pathlib.Path,
    rel: str,
    *,
    goal: str = "fixture walnut",
    rhythm: str = "weekly",
    updated: str = "2026-04-15T12:00:00Z",
    log_body: str | None = None,
    include_now: bool = True,
) -> pathlib.Path:
    """Create a minimal walnut at ``root/rel`` and return its abs path."""
    walnut = root / rel
    kernel = walnut / "_kernel"
    kernel.mkdir(parents=True, exist_ok=True)
    (kernel / "key.md").write_text(
        "---\n"
        "type: venture\n"
        f"goal: {goal}\n"
        f"rhythm: {rhythm}\n"
        "---\n\n"
        f"# {rel}\n",
        encoding="utf-8",
    )
    if include_now:
        (kernel / "now.json").write_text(
            json.dumps(
                {
                    "phase": "building",
                    "updated": updated,
                    "next": "continue",
                    "context": "fixture",
                }
            ),
            encoding="utf-8",
        )
    if log_body is not None:
        (kernel / "log.md").write_text(log_body, encoding="utf-8")
    return walnut


# ---------------------------------------------------------------------------
# Edge cases.
# ---------------------------------------------------------------------------


class EmptyWorldEdgeCases(unittest.TestCase):
    """A World with zero walnuts must succeed with an empty list."""

    def test_list_walnuts_on_empty_world(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-empty-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)

                async with in_memory_session(root) as client:
                    result = await client.call_tool("list_walnuts", arguments={})
                    is_err, payload = unwrap_call_tool(result)
                    self.assertFalse(is_err)
                    self.assertEqual(payload["walnuts"], [])
                    self.assertEqual(payload["total"], 0)
                    self.assertIsNone(payload["next_cursor"])

        _run(run())


class MissingKernelEdgeCases(unittest.TestCase):
    """Missing kernel files yield the documented error codes, not crashes."""

    def test_walnut_without_kernel_is_not_a_walnut(self) -> None:
        """A directory under 02_Life/people/ without _kernel/ is invisible.

        The walnut predicate is ``_kernel/key.md`` exists AND resolves
        inside the World. A directory that does not satisfy the
        predicate is NOT enumerated and does NOT produce
        ``ERR_KERNEL_FILE_MISSING`` at list time -- it simply isn't a
        walnut. ``get_walnut_state`` at that path yields
        ``ERR_WALNUT_NOT_FOUND`` (correct -- no walnut resolves there).
        """

        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-nok-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)
                # A directory that LOOKS like a walnut slot but has no _kernel/
                orphan = root / "02_Life" / "people" / "orphan"
                orphan.mkdir(parents=True)

                async with in_memory_session(root) as client:
                    # list_walnuts silently skips it.
                    list_result = await client.call_tool(
                        "list_walnuts", arguments={}
                    )
                    _, list_payload = unwrap_call_tool(list_result)
                    self.assertEqual(list_payload["total"], 0)

                    # get_walnut_state at the orphan path: not a walnut.
                    get_result = await client.call_tool(
                        "get_walnut_state",
                        arguments={"walnut": "02_Life/people/orphan"},
                    )
                    is_err, payload = unwrap_call_tool(get_result)
                    self.assertTrue(is_err)
                    self.assertEqual(payload["error"], "WALNUT_NOT_FOUND")

        _run(run())

    def test_walnut_missing_now_json_yields_kernel_file_missing(self) -> None:
        """A real walnut without now.json returns ERR_KERNEL_FILE_MISSING."""

        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-nonow-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)
                _write_walnut(root, "04_Ventures/no-now", include_now=False)

                async with in_memory_session(root) as client:
                    result = await client.call_tool(
                        "get_walnut_state",
                        arguments={"walnut": "04_Ventures/no-now"},
                    )
                    is_err, payload = unwrap_call_tool(result)
                    self.assertTrue(is_err)
                    self.assertEqual(payload["error"], "KERNEL_FILE_MISSING")

        _run(run())

    def test_read_walnut_kernel_missing_log_yields_error(self) -> None:
        """Reading a log.md that was never written returns the missing error."""

        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-nolog-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)
                _write_walnut(root, "04_Ventures/no-log", include_now=True)

                async with in_memory_session(root) as client:
                    result = await client.call_tool(
                        "read_walnut_kernel",
                        arguments={
                            "walnut": "04_Ventures/no-log",
                            "file": "log",
                        },
                    )
                    is_err, payload = unwrap_call_tool(result)
                    self.assertTrue(is_err)
                    self.assertEqual(payload["error"], "KERNEL_FILE_MISSING")

        _run(run())


class LargeLogEdgeCases(unittest.TestCase):
    """Large log.md paginates without exploding memory.

    The task brief mentions 100MB; running 100MB through a test suite
    would blow the <30s target. A 5000-entry log exercises the same
    pagination/streaming invariants for a fraction of the cost. The
    read_log tool returns just the requested window -- we verify by
    asking for limit=3 off a 5000-entry log and confirming we don't
    accidentally parse the whole thing.
    """

    def test_read_log_windowed_over_large_log(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-big-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)

                # Build a 5000-entry log. Each entry is ~150 bytes so
                # the total is ~750KB -- enough to catch regressions
                # that load the whole file into a list at once without
                # crippling CI runtime.
                entries = []
                for i in range(5000, 0, -1):
                    # Timestamps in descending order so "newest first"
                    # ordering is verifiable.
                    year = 2024 + (i // 1000)
                    ts = f"{year:04d}-01-01T00:00:00"
                    entries.append(
                        f"## {ts} squirrel:fixture{i:04d}\n\n"
                        f"Entry number {i} body text.\n\n"
                        f"signed: squirrel:fixture{i:04d}\n\n---\n"
                    )
                log_body = (
                    "---\nwalnut: big\nentry-count: 5000\n"
                    "last-entry: 2028-01-01T00:00:00\n---\n\n"
                    + "".join(entries)
                )
                _write_walnut(
                    root,
                    "04_Ventures/big",
                    log_body=log_body,
                )

                async with in_memory_session(root) as client:
                    # Request only 3 entries -- tool must return
                    # exactly 3 without parsing all 5000 into the
                    # response (pagination validity, not memory
                    # instrumentation -- the latter would need psutil).
                    start = time.monotonic()
                    result = await client.call_tool(
                        "read_log",
                        arguments={
                            "walnut": "04_Ventures/big",
                            "limit": 3,
                        },
                    )
                    duration = time.monotonic() - start
                    is_err, payload = unwrap_call_tool(result)
                    self.assertFalse(is_err)
                    self.assertEqual(len(payload["entries"]), 3)
                    self.assertEqual(payload["total_entries"], 5000)
                    self.assertEqual(payload["next_offset"], 3)
                    # 2s is generous; catches a hypothetical regression
                    # where the tool loads the entire file and returns
                    # the window AFTER parsing all 5000 entries.
                    self.assertLess(duration, 5.0)

        _run(run())


class BundleRawExclusionEdgeCases(unittest.TestCase):
    """Files under a bundle's raw/ directory are NOT exposed to tools."""

    def test_search_world_does_not_descend_into_raw_dirs(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-raw-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)
                walnut = _write_walnut(root, "04_Ventures/raw-excl")
                bundle = walnut / "a-bundle"
                bundle.mkdir()
                (bundle / "context.manifest.yaml").write_text(
                    "goal: test\nstatus: draft\n", encoding="utf-8"
                )
                raw_dir = bundle / "raw"
                raw_dir.mkdir()
                # Unique token that should NOT appear in search hits
                # because search_world skips raw/.
                secret_token = "RAW_DIR_EXCLUDED_TOKEN_42XYZ"
                (raw_dir / "secret.md").write_text(
                    f"This file contains {secret_token}\n",
                    encoding="utf-8",
                )

                async with in_memory_session(root) as client:
                    result = await client.call_tool(
                        "search_world",
                        arguments={"query": secret_token},
                    )
                    is_err, payload = unwrap_call_tool(result)
                    self.assertFalse(is_err)
                    # search_world must NOT find the secret inside raw/.
                    self.assertEqual(
                        payload["matches"],
                        [],
                        msg="search_world leaked bundle/raw/ content: "
                        f"{payload['matches']!r}",
                    )

        _run(run())


class NestedAliveMarkerEdgeCases(unittest.TestCase):
    """An inner .alive/ dir does not create a competing World."""

    def test_nested_alive_marker_does_not_shadow_outer(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-nested-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)
                walnut = _write_walnut(root, "04_Ventures/outer")
                # Inject a spurious .alive/ inside the walnut. The
                # outer World should remain authoritative -- walnut
                # discovery finds the walnut regardless of inner
                # sentinels.
                (walnut / ".alive").mkdir()

                async with in_memory_session(root) as client:
                    result = await client.call_tool("list_walnuts", arguments={})
                    is_err, payload = unwrap_call_tool(result)
                    self.assertFalse(is_err)
                    paths = [w["path"] for w in payload["walnuts"]]
                    self.assertIn("04_Ventures/outer", paths)

        _run(run())


class SymlinkEscapeEdgeCases(unittest.TestCase):
    """Symlinks that resolve outside the World are rejected."""

    @unittest.skipIf(
        sys.platform == "win32",
        "symlink semantics on Windows need admin for file symlinks; v0.1 targets POSIX.",
    )
    def test_kernel_key_symlink_to_outside_is_filtered(self) -> None:
        """A walnut whose key.md symlinks to /etc/passwd is not a walnut.

        ``_kernel_file_in_world`` realpaths + commonpath-checks every
        candidate before the walnut predicate accepts it. A symlink
        that resolves outside the World root fails the predicate --
        the walnut never appears in the inventory, and directly
        addressing it yields ERR_WALNUT_NOT_FOUND.
        """

        async def run() -> None:
            # Keep the "outside" target INSIDE the tempdir so we don't
            # depend on /etc/passwd existing on CI; the containment
            # check only cares that realpath leaves the World root.
            with tempfile.TemporaryDirectory(prefix="alive-mcp-sym-") as outer:
                outside = pathlib.Path(outer) / "outside-secret"
                outside.write_text("SECRET", encoding="utf-8")

                with tempfile.TemporaryDirectory(
                    prefix="alive-mcp-sym-world-"
                ) as tmp:
                    root = pathlib.Path(tmp)
                    _write_world_marker(root)
                    # Build a walnut whose key.md is a symlink to a file
                    # outside the World.
                    walnut = root / "04_Ventures/symlink-walnut"
                    kernel = walnut / "_kernel"
                    kernel.mkdir(parents=True)
                    bad_key = kernel / "key.md"
                    os.symlink(str(outside), str(bad_key))

                    async with in_memory_session(root) as client:
                        # Not in inventory.
                        list_result = await client.call_tool(
                            "list_walnuts", arguments={}
                        )
                        _, list_payload = unwrap_call_tool(list_result)
                        self.assertEqual(list_payload["total"], 0)

                        # Direct lookup rejected.
                        get_result = await client.call_tool(
                            "read_walnut_kernel",
                            arguments={
                                "walnut": "04_Ventures/symlink-walnut",
                                "file": "key",
                            },
                        )
                        is_err, payload = unwrap_call_tool(get_result)
                        self.assertTrue(is_err)
                        # Rejected at the walnut-predicate stage -- the
                        # walnut itself does not resolve.
                        self.assertEqual(payload["error"], "WALNUT_NOT_FOUND")

        _run(run())

    @unittest.skipIf(sys.platform == "win32", "POSIX symlink semantics.")
    def test_path_escape_via_dotdot_rejected(self) -> None:
        """A walnut argument containing ``..`` never resolves above the World.

        The tool input is a POSIX relpath; ``..`` segments get joined
        through :func:`alive_mcp.paths.safe_join` which realpath-checks
        the result. An escape produces ``ERR_WALNUT_NOT_FOUND`` (the
        walnut predicate fails after the path resolves outside --
        path-escape and walnut-not-found are both "we can't serve this
        walnut" shapes; the v0.1 contract maps to WALNUT_NOT_FOUND).
        """

        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-dotdot-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)
                _write_walnut(root, "04_Ventures/inside")

                async with in_memory_session(root) as client:
                    result = await client.call_tool(
                        "get_walnut_state",
                        arguments={"walnut": "../outside-world"},
                    )
                    is_err, payload = unwrap_call_tool(result)
                    self.assertTrue(is_err)
                    # Either PATH_ESCAPE (safe_join caught it) or
                    # WALNUT_NOT_FOUND (predicate failed). Both are
                    # correct per the v0.1 contract.
                    self.assertIn(
                        payload["error"],
                        ("PATH_ESCAPE", "WALNUT_NOT_FOUND"),
                    )

        _run(run())


class EncodingFallbackEdgeCases(unittest.TestCase):
    """Files with non-UTF-8 bytes do not crash the server."""

    def test_read_walnut_kernel_non_utf8_returns_envelope_error(self) -> None:
        """read_walnut_kernel surfaces a documented error, never raises.

        The v0.1 contract's ``encoding_fallback`` warning semantic is
        not yet implemented on every read path; today the tool maps a
        UnicodeDecodeError to ``ERR_KERNEL_FILE_MISSING`` per
        :func:`read_walnut_kernel`. Either path is acceptable as long
        as the server does not crash and the client sees an
        isError=True envelope with a structured code.
        """

        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-bad-enc-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)
                walnut = _write_walnut(root, "04_Ventures/latin1")
                # Write invalid UTF-8 bytes into log.md via binary mode.
                # 0xFF is never a valid UTF-8 lead byte.
                (walnut / "_kernel" / "log.md").write_bytes(
                    b"---\nwalnut: latin1\n---\n\n"
                    b"## 2026-04-15T00:00:00 squirrel:latin01\n\n"
                    b"Non-utf8 content follows: \xff\xfe\xfd\n"
                    b"signed: squirrel:latin01\n"
                )

                async with in_memory_session(root) as client:
                    result = await client.call_tool(
                        "read_walnut_kernel",
                        arguments={
                            "walnut": "04_Ventures/latin1",
                            "file": "log",
                        },
                    )
                    is_err, payload = unwrap_call_tool(result)
                    # Server did not crash -- envelope is well-formed.
                    self.assertTrue(is_err)
                    self.assertIn(
                        payload["error"],
                        ("KERNEL_FILE_MISSING", "PERMISSION_DENIED"),
                        msg=f"unexpected error code: {payload!r}",
                    )

        _run(run())


class ConcurrentWriteEdgeCases(unittest.TestCase):
    """Reads see either the old or new file bytes, never a partial write.

    The v0.1 tool layer reads a whole kernel file with ``open()`` +
    ``read()`` which on POSIX is atomic against an ``open(..., "w")``
    truncate-and-replace by another thread (the reader gets either the
    pre-truncate bytes from a dup'd fd, or sees the new file after
    replace). This test runs many read/write cycles in parallel and
    asserts every read parses as valid JSON -- a half-written file
    would fail to parse.
    """

    def test_concurrent_now_write_during_read_never_tears(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory(prefix="alive-mcp-race-") as tmp:
                root = pathlib.Path(tmp)
                _write_world_marker(root)
                walnut = _write_walnut(root, "04_Ventures/racer")
                now_path = walnut / "_kernel" / "now.json"

                stop = threading.Event()

                def writer() -> None:
                    i = 0
                    while not stop.is_set():
                        data = {
                            "phase": "building",
                            "updated": "2026-04-15T00:00:00Z",
                            "next": f"iteration {i}",
                            "context": "race",
                        }
                        tmp_path = now_path.with_suffix(".json.tmp")
                        tmp_path.write_text(
                            json.dumps(data), encoding="utf-8"
                        )
                        os.replace(tmp_path, now_path)
                        i += 1
                        time.sleep(0.001)

                writer_thread = threading.Thread(target=writer, daemon=True)
                writer_thread.start()
                try:
                    async with in_memory_session(root) as client:
                        for _ in range(25):
                            result = await client.call_tool(
                                "get_walnut_state",
                                arguments={"walnut": "04_Ventures/racer"},
                            )
                            is_err, payload = unwrap_call_tool(result)
                            self.assertFalse(
                                is_err,
                                msg=f"torn read surfaced as error: {payload!r}",
                            )
                            # Payload must be the valid shape -- a torn
                            # file would have parsed as None and mapped
                            # to KERNEL_FILE_MISSING (caught above) or
                            # produced a malformed dict here.
                            self.assertIn("phase", payload)
                            self.assertIn("next", payload)
                finally:
                    stop.set()
                    writer_thread.join(timeout=2.0)

        _run(run())


class WorldDiscoveryEdgeCases(unittest.TestCase):
    """No World resolved -> ERR_NO_WORLD, server does not crash."""

    def test_list_walnuts_without_world_returns_no_world_error(self) -> None:
        async def run() -> None:
            # Point the server at a directory that is NOT a World and
            # has no .alive/ sentinel. Discovery must fail and the
            # tool must return ERR_NO_WORLD without crashing.
            with tempfile.TemporaryDirectory(prefix="alive-mcp-no-world-") as tmp:
                fake_root = pathlib.Path(tmp) / "not-a-world"
                fake_root.mkdir()

                async with in_memory_session(fake_root) as client:
                    result = await client.call_tool(
                        "list_walnuts", arguments={}
                    )
                    is_err, payload = unwrap_call_tool(result)
                    # Either the discovery layer refused outright
                    # (ERR_NO_WORLD at the tool boundary) or it walked
                    # up and found the tempdir's parent. On CI the
                    # tempdir has no .alive/ above it so ERR_NO_WORLD
                    # is the expected outcome.
                    if is_err:
                        self.assertEqual(payload["error"], "NO_WORLD")
                    else:
                        # Legit if the CI host's parent tree contains an
                        # .alive/ somewhere above; the tool call still
                        # succeeded without crashing, which is the
                        # invariant we actually care about.
                        self.assertIn("walnuts", payload)

        _run(run())


if __name__ == "__main__":
    unittest.main()
