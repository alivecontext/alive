"""JSONL audit logger tests (fn-10-60k.12 / T12).

Covers every bullet in the task spec's acceptance criteria:

* Every tool call produces a JSONL line in ``.alive/_mcp/audit.log``.
* Log entries validate as JSON, one per line.
* Rotation triggers at the size cap, creates ``audit.log.1``, preserves
  the configured number of backups.
* String arg values are replaced with ``{type, length, h}`` -- never
  verbatim (test calls a fake tool with ``query="secret-string"`` and
  greps the log to prove the raw string does not appear).
* Walnut/bundle names hashed by default.
* ``ALIVE_MCP_AUDIT_PUBLIC_WALNUT_PATHS`` env var whitelists specific
  values for verbatim logging.
* Small scalar args (int, bool) logged verbatim.
* Result counts logged; result bodies never logged.
* Disk-full simulation returns ``ERR_AUDIT_DISK_FULL``; tool body does
  NOT run.
* Writes to ``.alive/_mcp/audit.log`` are excluded from the T11
  subscription observer (covered separately in
  ``test_resource_subscriptions.ObserverEndToEndTests.test_audit_log_tree_classifies_as_ignored``
  via the pure ``classify_path`` assertion); this module focuses on the
  writer invariants.
* Audit writer task shuts down cleanly on cancellation and drains
  outstanding queue entries before exit.

The tests use a tempdir World and a controlled :class:`asyncio.Queue`
so the real filesystem state is exercised end-to-end. No FastMCP
server is spun up -- the decorator is invoked against a fake handler
with a stub AppContext-shaped object, which is enough to assert the
audit pipeline contract.
"""
from __future__ import annotations

import asyncio
import errno
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from dataclasses import dataclass, field
from typing import Any, List, Optional

# Make ``src/`` importable.
import tests  # noqa: F401

from alive_mcp import envelope, errors  # noqa: E402
from alive_mcp.audit import (  # noqa: E402
    AUDIT_FILE_MODE,
    AUDIT_RELPATH,
    AuditWriter,
    AuditWriterState,
    ENV_PUBLIC_WALNUT_PATHS,
    MAX_ACTIVE_BYTES,
    MAX_ROTATIONS,
    audited,
    build_entry,
    emit_resource_read,
    run_audit_writer,
    summarize_args,
)


# ---------------------------------------------------------------------------
# Test doubles -- a minimal AppContext-shape that the decorator can use.
# ---------------------------------------------------------------------------


@dataclass
class _FakeRequestContext:
    """Stands in for FastMCP's ``RequestContext`` object.

    The decorator reads ``ctx.request_context.lifespan_context`` and
    ``ctx.session_id`` -- those are the only two attributes we need to
    populate for the audit path.
    """

    lifespan_context: Any


@dataclass
class _FakeCtx:
    """Stands in for FastMCP's :class:`Context`.

    Real tool handlers accept ``ctx`` as the first positional arg; the
    decorator pulls ``request_context`` and ``session_id`` off it.
    """

    request_context: _FakeRequestContext
    session_id: Optional[str] = None


@dataclass
class _FakeLifespan:
    """AppContext-shape with the two fields the decorator reads."""

    audit_queue: "asyncio.Queue[dict[str, Any]]"
    audit_writer_state: AuditWriterState = field(default_factory=AuditWriterState)


def _make_ctx(
    queue: "asyncio.Queue[dict[str, Any]]",
    state: Optional[AuditWriterState] = None,
    session_id: Optional[str] = None,
) -> _FakeCtx:
    lifespan = _FakeLifespan(
        audit_queue=queue,
        audit_writer_state=state if state is not None else AuditWriterState(),
    )
    return _FakeCtx(
        request_context=_FakeRequestContext(lifespan_context=lifespan),
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# summarize_args / build_entry -- pure-function tests.
# ---------------------------------------------------------------------------


class SummarizeArgsTests(unittest.TestCase):
    """Per-value summarization rules (privacy-first posture)."""

    def test_string_value_is_hashed_by_default(self) -> None:
        out = summarize_args({"query": "secret-string"}, whitelist=frozenset())
        rec = out["query"]
        self.assertEqual(rec["type"], "str")
        self.assertEqual(rec["len"], len("secret-string"))
        self.assertIn("h", rec)
        self.assertNotIn("val", rec)
        self.assertNotIn("secret-string", json.dumps(rec))

    def test_string_whitelist_emits_verbatim(self) -> None:
        wl = frozenset({"04_Ventures/alive"})
        out = summarize_args({"walnut": "04_Ventures/alive"}, whitelist=wl)
        rec = out["walnut"]
        self.assertEqual(rec["type"], "str")
        self.assertEqual(rec["val"], "04_Ventures/alive")
        self.assertNotIn("h", rec)

    def test_whitelist_does_NOT_apply_to_non_walnut_keys(self) -> None:
        """query=<whitelisted-value> is still hashed -- whitelist only
        applies to walnut/bundle kwargs.

        Defensive test: if a caller enables
        ``ALIVE_MCP_AUDIT_PUBLIC_WALNUT_PATHS=04_Ventures/alive``,
        a ``search_world(query="04_Ventures/alive")`` call must
        STILL hash the query -- the whitelist is not a free-pass
        unhash-token for arbitrary free-text args.
        """
        wl = frozenset({"04_Ventures/alive"})
        out = summarize_args({"query": "04_Ventures/alive"}, whitelist=wl)
        rec = out["query"]
        self.assertIn("h", rec)
        self.assertNotIn("val", rec)

    def test_whitelist_applies_to_bundle_key(self) -> None:
        """bundle=<whitelisted-value> is verbatim, like walnut=."""
        wl = frozenset({"bundles/shielding-review"})
        out = summarize_args(
            {"bundle": "bundles/shielding-review"}, whitelist=wl
        )
        self.assertEqual(out["bundle"]["val"], "bundles/shielding-review")

    def test_string_not_in_whitelist_still_hashed(self) -> None:
        wl = frozenset({"04_Ventures/alive"})
        out = summarize_args({"walnut": "02_Life/people/ben-flint"}, whitelist=wl)
        self.assertIn("h", out["walnut"])
        self.assertNotIn("val", out["walnut"])

    def test_int_value_verbatim(self) -> None:
        out = summarize_args({"limit": 20}, whitelist=frozenset())
        self.assertEqual(out["limit"], {"type": "int", "val": 20})

    def test_bool_value_verbatim(self) -> None:
        out = summarize_args({"case_sensitive": True}, whitelist=frozenset())
        self.assertEqual(out["case_sensitive"], {"type": "bool", "val": True})

    def test_none_is_null(self) -> None:
        out = summarize_args({"cursor": None}, whitelist=frozenset())
        self.assertEqual(out["cursor"], {"type": "null"})

    def test_list_is_hashed(self) -> None:
        out = summarize_args({"tags": ["a", "b"]}, whitelist=frozenset())
        self.assertEqual(out["tags"]["type"], "list")
        self.assertEqual(out["tags"]["len"], 2)
        self.assertIn("h", out["tags"])

    def test_dict_is_hashed(self) -> None:
        out = summarize_args({"params": {"k": "v"}}, whitelist=frozenset())
        self.assertEqual(out["params"]["type"], "dict")
        self.assertEqual(out["params"]["len"], 1)
        self.assertIn("h", out["params"])

    def test_empty_whitelist_defaults_to_env(self) -> None:
        """Default whitelist=None pulls from env var."""
        # Ensure env is unset for this test.
        orig = os.environ.pop(ENV_PUBLIC_WALNUT_PATHS, None)
        try:
            out = summarize_args({"walnut": "04_Ventures/alive"})
            self.assertIn("h", out["walnut"])
            self.assertNotIn("val", out["walnut"])
        finally:
            if orig is not None:
                os.environ[ENV_PUBLIC_WALNUT_PATHS] = orig

    def test_env_whitelist_respected(self) -> None:
        orig = os.environ.get(ENV_PUBLIC_WALNUT_PATHS)
        os.environ[ENV_PUBLIC_WALNUT_PATHS] = "04_Ventures/alive,02_Life/people/ben"
        try:
            out = summarize_args({"walnut": "04_Ventures/alive"})
            self.assertEqual(out["walnut"]["val"], "04_Ventures/alive")
            # Other walnut names still hashed.
            out2 = summarize_args({"walnut": "04_Ventures/other"})
            self.assertIn("h", out2["walnut"])
        finally:
            if orig is None:
                os.environ.pop(ENV_PUBLIC_WALNUT_PATHS, None)
            else:
                os.environ[ENV_PUBLIC_WALNUT_PATHS] = orig


class BuildEntryTests(unittest.TestCase):
    """Entry composition -- counts, error codes, schema."""

    def test_success_envelope_yields_ok_status(self) -> None:
        env = envelope.ok({"walnuts": [1, 2, 3], "next_cursor": None})
        entry = build_entry(
            tool="list_walnuts",
            args={"limit": 50},
            envelope=env,
            duration_ms=42,
            session_id="sess-1",
            whitelist=frozenset(),
        )
        self.assertEqual(entry["tool"], "list_walnuts")
        self.assertEqual(entry["result_status"], "ok")
        self.assertIsNone(entry["error_code"])
        self.assertEqual(entry["session_id"], "sess-1")
        self.assertEqual(entry["duration_ms"], 42)
        self.assertEqual(entry["result_counts"], {"walnuts": 3})

    def test_error_envelope_yields_error_status(self) -> None:
        env = envelope.error(errors.ERR_WALNUT_NOT_FOUND, walnut="fake")
        entry = build_entry(
            tool="get_walnut_state",
            args={"walnut": "fake"},
            envelope=env,
            duration_ms=10,
            whitelist=frozenset(),
        )
        self.assertEqual(entry["result_status"], "error")
        self.assertEqual(entry["error_code"], "WALNUT_NOT_FOUND")
        # Counts still empty on error.
        self.assertEqual(entry["result_counts"], {})

    def test_result_counts_only_for_whitelisted_fields(self) -> None:
        env = envelope.ok(
            {
                "walnuts": [1, 2],
                "matches": [{"x": 1}, {"x": 2}, {"x": 3}],
                # not in whitelist:
                "extra_list": [1, 2, 3, 4],
                "next_cursor": None,
            }
        )
        entry = build_entry(
            tool="x", args={}, envelope=env, duration_ms=1, whitelist=frozenset()
        )
        self.assertEqual(entry["result_counts"], {"walnuts": 2, "matches": 3})
        self.assertNotIn("extra_list", entry["result_counts"])

    def test_result_bodies_never_leak_into_entry(self) -> None:
        """The full envelope contains match text; the entry must not.

        Specifically, a match result includes the raw ``content`` string
        for the matched line. The entry should record a count, not any
        of that content.
        """
        env = envelope.ok(
            {
                "matches": [
                    {
                        "walnut": "04_Ventures/alive",
                        "file": "_kernel/log.md",
                        "content": "this text must not appear in audit",
                    }
                ],
                "next_cursor": None,
            }
        )
        entry = build_entry(
            tool="search_world",
            args={"query": "must"},
            envelope=env,
            duration_ms=1,
            whitelist=frozenset(),
        )
        as_json = json.dumps(entry)
        self.assertNotIn("this text must not appear in audit", as_json)
        self.assertEqual(entry["result_counts"], {"matches": 1})

    def test_entry_is_json_serializable(self) -> None:
        env = envelope.ok({"walnuts": []})
        entry = build_entry(
            tool="x", args={"k": "v"}, envelope=env, duration_ms=1,
            whitelist=frozenset(),
        )
        # Round-trip.
        loaded = json.loads(json.dumps(entry))
        self.assertEqual(loaded["tool"], "x")

    def test_entry_has_all_required_keys(self) -> None:
        env = envelope.ok({})
        entry = build_entry(
            tool="x", args={}, envelope=env, duration_ms=0, whitelist=frozenset()
        )
        required = {
            "ts",
            "session_id",
            "tool",
            "args",
            "result_status",
            "result_counts",
            "duration_ms",
            "error_code",
        }
        self.assertEqual(set(entry.keys()), required)


# ---------------------------------------------------------------------------
# AuditWriter -- integration tests hitting real disk.
# ---------------------------------------------------------------------------


class AuditWriterDiskTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end writer against a tempdir World."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="alive-mcp-audit-")
        self.world = self.tmpdir
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.state = AuditWriterState()
        self.audit_path = os.path.join(self.world, *AUDIT_RELPATH.split("/"))

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def _run_writer_briefly(self) -> asyncio.Task[None]:
        """Start the writer task and return it for caller-controlled cancel.

        Caller is responsible for pushing entries onto the queue AND
        calling ``await queue.join()`` or waiting for the drain, THEN
        cancelling.
        """
        task = asyncio.create_task(
            run_audit_writer(self.queue, world_root=self.world, state=self.state)
        )
        return task

    async def test_writer_creates_directory_and_file(self) -> None:
        task = await self._run_writer_briefly()
        try:
            entry = build_entry(
                tool="list_walnuts",
                args={"limit": 50},
                envelope=envelope.ok({"walnuts": []}),
                duration_ms=1,
                whitelist=frozenset(),
            )
            await self.queue.put(entry)
            await self.queue.join()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.assertTrue(os.path.isdir(os.path.dirname(self.audit_path)))
        self.assertTrue(os.path.isfile(self.audit_path))

    async def test_writer_creates_file_with_0o600_perms(self) -> None:
        task = await self._run_writer_briefly()
        try:
            await self.queue.put(
                build_entry(
                    tool="x",
                    args={},
                    envelope=envelope.ok({}),
                    duration_ms=0,
                    whitelist=frozenset(),
                )
            )
            await self.queue.join()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        mode = os.stat(self.audit_path).st_mode & 0o777
        self.assertEqual(mode, AUDIT_FILE_MODE)

    async def test_one_line_per_entry_and_valid_json(self) -> None:
        task = await self._run_writer_briefly()
        try:
            for i in range(3):
                await self.queue.put(
                    build_entry(
                        tool="t{}".format(i),
                        args={"n": i},
                        envelope=envelope.ok({}),
                        duration_ms=i,
                        whitelist=frozenset(),
                    )
                )
            await self.queue.join()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        with open(self.audit_path, "r") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 3)
        for line in lines:
            parsed = json.loads(line)
            self.assertIn("tool", parsed)

    async def test_secret_strings_never_appear_in_log(self) -> None:
        """Grep guarantee: a hashed arg value is absent from the file."""
        task = await self._run_writer_briefly()
        secret = "ssn 123-45-6789 is confidential"
        try:
            await self.queue.put(
                build_entry(
                    tool="search_world",
                    args={"query": secret},
                    envelope=envelope.ok({"matches": []}),
                    duration_ms=1,
                    whitelist=frozenset(),
                )
            )
            await self.queue.join()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        with open(self.audit_path, "r") as f:
            content = f.read()
        self.assertNotIn(secret, content)
        self.assertNotIn("123-45-6789", content)

    async def test_whitelisted_walnut_path_appears_verbatim(self) -> None:
        task = await self._run_writer_briefly()
        wl = frozenset({"04_Ventures/alive"})
        try:
            await self.queue.put(
                build_entry(
                    tool="get_walnut_state",
                    args={"walnut": "04_Ventures/alive"},
                    envelope=envelope.ok({}),
                    duration_ms=1,
                    whitelist=wl,
                )
            )
            await self.queue.join()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        with open(self.audit_path, "r") as f:
            content = f.read()
        self.assertIn("04_Ventures/alive", content)


class AuditWriterRotationTests(unittest.IsolatedAsyncioTestCase):
    """Size-based rotation + backup retention."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="alive-mcp-audit-rot-")
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.state = AuditWriterState()
        self.audit_path = os.path.join(
            self.tmpdir, *AUDIT_RELPATH.split("/")
        )

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def _run_with_small_cap(
        self, max_bytes: int, max_rotations: int = 3
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(
            run_audit_writer(
                self.queue,
                world_root=self.tmpdir,
                state=self.state,
                max_active_bytes=max_bytes,
                max_rotations=max_rotations,
            )
        )
        return task

    async def _drive(self, task: asyncio.Task[None], entries: List[dict[str, Any]]) -> None:
        for e in entries:
            await self.queue.put(e)
        await self.queue.join()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_rotation_triggers_at_cap_and_creates_log_1(self) -> None:
        """With a tiny cap, the second write triggers rotation."""
        task = await self._run_with_small_cap(max_bytes=100)
        # Each entry json ~100 bytes => after 2 entries we definitely rotate.
        payload = {
            "ts": "2026-04-16T00:00:00.000Z",
            "session_id": None,
            "tool": "t",
            "args": {"k": {"type": "str", "len": 10, "h": "a" * 16}},
            "result_status": "ok",
            "result_counts": {},
            "duration_ms": 1,
            "error_code": None,
        }
        await self._drive(task, [dict(payload) for _ in range(5)])
        # audit.log exists (most recent write)
        self.assertTrue(os.path.isfile(self.audit_path))
        # audit.log.1 exists (rotation happened)
        self.assertTrue(os.path.isfile(self.audit_path + ".1"))

    async def test_rotation_caps_at_max_rotations(self) -> None:
        """More rotations than N leave at most N backups."""
        task = await self._run_with_small_cap(max_bytes=50, max_rotations=3)
        payload = {
            "ts": "2026-04-16T00:00:00.000Z",
            "session_id": None,
            "tool": "t",
            "args": {},
            "result_status": "ok",
            "result_counts": {},
            "duration_ms": 1,
            "error_code": None,
        }
        # Push enough entries to rotate many times.
        await self._drive(task, [dict(payload) for _ in range(30)])
        # audit.log + audit.log.1..3. audit.log.4 should NOT exist.
        self.assertTrue(os.path.isfile(self.audit_path))
        self.assertTrue(os.path.isfile(self.audit_path + ".1"))
        self.assertTrue(os.path.isfile(self.audit_path + ".2"))
        self.assertTrue(os.path.isfile(self.audit_path + ".3"))
        self.assertFalse(os.path.isfile(self.audit_path + ".4"))

    async def test_default_rotation_constants_match_spec(self) -> None:
        """10MB cap, 10 backups -- the frozen spec values."""
        self.assertEqual(MAX_ACTIVE_BYTES, 10 * 1024 * 1024)
        self.assertEqual(MAX_ROTATIONS, 10)


class AuditWriterDiskFullTests(unittest.IsolatedAsyncioTestCase):
    """ENOSPC / EIO handling -- fail-closed posture."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="alive-mcp-audit-enospc-")
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.state = AuditWriterState()

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_enospc_sets_disk_full_flag(self) -> None:
        """A forced OSError(ENOSPC) flips ``state.disk_full``."""
        writer = AuditWriter(
            self.queue, world_root=self.tmpdir, state=self.state
        )

        def _boom(_line: bytes) -> None:
            raise OSError(errno.ENOSPC, "No space left on device")

        # Monkeypatch the sync writer to simulate a full disk.
        writer._write_one_sync = _boom  # type: ignore[assignment]

        task = asyncio.create_task(writer.run())
        try:
            entry = build_entry(
                tool="x",
                args={},
                envelope=envelope.ok({}),
                duration_ms=1,
                whitelist=frozenset(),
            )
            await self.queue.put(entry)
            # The entry gets consumed (task_done called) -- wait for join.
            await self.queue.join()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.assertTrue(self.state.disk_full)

    async def test_eio_sets_disk_full_flag(self) -> None:
        writer = AuditWriter(
            self.queue, world_root=self.tmpdir, state=self.state
        )

        def _boom(_line: bytes) -> None:
            raise OSError(errno.EIO, "I/O error")

        writer._write_one_sync = _boom  # type: ignore[assignment]

        task = asyncio.create_task(writer.run())
        try:
            await self.queue.put(
                build_entry(
                    tool="x", args={},
                    envelope=envelope.ok({}), duration_ms=1,
                    whitelist=frozenset(),
                )
            )
            await self.queue.join()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.assertTrue(self.state.disk_full)

    async def test_transient_oserror_does_not_flip_disk_full(self) -> None:
        """A non-ENOSPC/EIO OSError (e.g. EACCES) should not poison the writer."""
        writer = AuditWriter(
            self.queue, world_root=self.tmpdir, state=self.state
        )
        self._calls = 0

        def _flaky(line: bytes) -> None:
            self._calls += 1
            if self._calls == 1:
                raise OSError(errno.EACCES, "permission denied")
            # Second call succeeds -- fall through to real write.
            AuditWriter._write_one_sync(writer, line)

        writer._write_one_sync = _flaky  # type: ignore[assignment]

        task = asyncio.create_task(writer.run())
        try:
            await self.queue.put(
                build_entry(
                    tool="x", args={}, envelope=envelope.ok({}),
                    duration_ms=1, whitelist=frozenset(),
                )
            )
            await self.queue.put(
                build_entry(
                    tool="y", args={}, envelope=envelope.ok({}),
                    duration_ms=2, whitelist=frozenset(),
                )
            )
            await self.queue.join()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.assertFalse(self.state.disk_full)
        self.assertEqual(self.state.writes_ok, 1)
        self.assertEqual(self.state.writes_failed, 1)


# ---------------------------------------------------------------------------
# @audited decorator -- wires ctx, queue, fail-closed.
# ---------------------------------------------------------------------------


class AuditedDecoratorTests(unittest.IsolatedAsyncioTestCase):
    """The decorator queues entries and fails closed on disk_full."""

    async def test_decorator_queues_entry_on_success(self) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        state = AuditWriterState()
        ctx = _make_ctx(queue, state, session_id="sess-42")

        @audited
        async def search_world(ctx: Any, query: str, limit: int = 20) -> dict[str, Any]:
            return envelope.ok({"matches": [{"x": 1}, {"x": 2}], "next_cursor": None})

        result = await search_world(ctx, query="ssn 123-45-6789", limit=20)
        self.assertFalse(result["isError"])

        # The decorator should have queued ONE entry.
        self.assertEqual(queue.qsize(), 1)
        entry = queue.get_nowait()
        self.assertEqual(entry["tool"], "search_world")
        self.assertEqual(entry["session_id"], "sess-42")
        self.assertEqual(entry["result_status"], "ok")
        self.assertEqual(entry["result_counts"], {"matches": 2})
        # args: query hashed, limit verbatim.
        self.assertIn("h", entry["args"]["query"])
        self.assertNotIn("123-45-6789", json.dumps(entry))
        self.assertEqual(entry["args"]["limit"], {"type": "int", "val": 20})

    async def test_decorator_fail_closed_on_disk_full(self) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        state = AuditWriterState(disk_full=True)
        ctx = _make_ctx(queue, state)

        call_count = 0

        @audited
        async def search_world(ctx: Any, query: str) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return envelope.ok({"matches": []})

        result = await search_world(ctx, query="anything")
        # Tool body did NOT run.
        self.assertEqual(call_count, 0)
        # Envelope is the ERR_AUDIT_DISK_FULL shape.
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "AUDIT_DISK_FULL")
        # No entry queued (we fail before reaching queue.put).
        self.assertEqual(queue.qsize(), 0)

    async def test_decorator_with_tool_name_override(self) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        ctx = _make_ctx(queue)

        @audited(tool_name="public_name")
        async def _private(ctx: Any) -> dict[str, Any]:
            return envelope.ok({})

        await _private(ctx)
        entry = queue.get_nowait()
        self.assertEqual(entry["tool"], "public_name")
        # The attribute also round-trips.
        self.assertEqual(getattr(_private, "__alive_tool_name__"), "public_name")

    async def test_decorator_swallows_audit_failures(self) -> None:
        """Audit-path exceptions must not affect the tool response.

        The decorator now uses ``await queue.put`` for back-pressure
        (see the Critical-2 fix from the T12 review), so a saturated
        queue BLOCKS rather than drops. To test the "audit failures
        don't break the tool response" invariant we substitute a
        queue whose ``put`` raises. The tool response must still be
        the success envelope.
        """

        class _BrokenQueue:
            async def put(self, item: Any) -> None:  # noqa: D401
                raise RuntimeError("simulated audit-queue failure")

        # Minimal fake lifespan with a broken audit_queue.
        broken_ctx = _FakeCtx(
            request_context=_FakeRequestContext(
                lifespan_context=_FakeLifespan(
                    audit_queue=_BrokenQueue(),  # type: ignore[arg-type]
                    audit_writer_state=AuditWriterState(),
                )
            )
        )

        @audited
        async def t(ctx: Any) -> dict[str, Any]:
            return envelope.ok({"done": True})

        result = await t(broken_ctx)
        # Tool succeeded despite the audit queue raising.
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["done"], True)

    async def test_decorator_awaits_queue_put_for_backpressure(self) -> None:
        """With a saturated queue, the decorator blocks (back-pressure) rather than drops.

        The acceptance criterion "every tool call produces a JSONL
        line" requires blocking on a full queue. Verified by
        pre-filling a small queue, invoking the decorator concurrently
        with a consumer that drains it, and asserting the decorator
        completed only after the drain made room.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        await queue.put({"pre-fill": True})
        ctx = _make_ctx(queue)

        @audited
        async def t(ctx: Any) -> dict[str, Any]:
            return envelope.ok({})

        call_future = asyncio.ensure_future(t(ctx))
        # Give the decorator a moment to reach its `await queue.put`.
        await asyncio.sleep(0.01)
        self.assertFalse(call_future.done())
        # Drain the pre-filled entry -- that unblocks the decorator.
        _ = await queue.get()
        result = await asyncio.wait_for(call_future, timeout=1.0)
        self.assertFalse(result["isError"])
        # The decorator's audit entry is now in the queue.
        self.assertEqual(queue.qsize(), 1)

    async def test_decorator_without_ctx_is_pass_through(self) -> None:
        """If no Context is attached, the decorator must not crash."""

        @audited
        async def t(val: int) -> dict[str, Any]:
            return envelope.ok({"val": val})

        result = await t(7)
        self.assertFalse(result["isError"])

    async def test_decorator_preserves_wrapped_metadata(self) -> None:
        """``functools.wraps`` preserves name, doc, module, signature."""

        @audited
        async def list_walnuts(ctx: Any, limit: int = 50) -> dict[str, Any]:
            """My docstring."""
            return envelope.ok({})

        self.assertEqual(list_walnuts.__name__, "list_walnuts")
        self.assertEqual(list_walnuts.__doc__, "My docstring.")
        # Module preserved.
        self.assertEqual(list_walnuts.__module__, __name__)


# ---------------------------------------------------------------------------
# Writer shutdown / drain semantics.
# ---------------------------------------------------------------------------


class WriterShutdownTests(unittest.IsolatedAsyncioTestCase):
    """Graceful cancellation drains outstanding entries."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="alive-mcp-audit-shut-")
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.state = AuditWriterState()
        self.audit_path = os.path.join(
            self.tmpdir, *AUDIT_RELPATH.split("/")
        )

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_cancellation_drains_queue_before_exit(self) -> None:
        """Queue-pending entries land on disk before the task exits."""
        task = asyncio.create_task(
            run_audit_writer(
                self.queue, world_root=self.tmpdir, state=self.state
            )
        )

        # Push several entries without awaiting a join.
        for i in range(5):
            await self.queue.put(
                build_entry(
                    tool="t{}".format(i),
                    args={"n": i},
                    envelope=envelope.ok({}),
                    duration_ms=i,
                    whitelist=frozenset(),
                )
            )

        # Let the writer pick up a few, then cancel. Give the writer a
        # chance to consume the first entry so we exercise both the
        # in-flight and pending-on-cancel paths.
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # File exists and every entry landed.
        self.assertTrue(os.path.isfile(self.audit_path))
        with open(self.audit_path, "r") as f:
            lines = f.read().splitlines()
        # Exactly five lines -- all drained.
        self.assertEqual(len(lines), 5)


# ---------------------------------------------------------------------------
# emit_resource_read -- the resource-layer audit hook.
# ---------------------------------------------------------------------------


class EmitResourceReadTests(unittest.IsolatedAsyncioTestCase):
    """The resource-read audit entry mirrors the tool-entry privacy posture."""

    async def test_success_entry_queued_with_hashed_uri(self) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        state = AuditWriterState()
        lifespan = _FakeLifespan(audit_queue=queue, audit_writer_state=state)
        ok = await emit_resource_read(
            lifespan,
            uri="alive://walnut/04_Ventures/alive/kernel/log",
            walnut="04_Ventures/alive",
            file="log",
            content_bytes=2048,
            duration_ms=7,
            session_id="sess-1",
        )
        self.assertTrue(ok)
        entry = queue.get_nowait()
        self.assertEqual(entry["tool"], "resource.read")
        self.assertEqual(entry["result_status"], "ok")
        self.assertEqual(entry["result_counts"], {"bytes": 2048})
        # URI is hashed, not verbatim.
        self.assertIn("h", entry["args"]["uri"])
        self.assertNotIn("val", entry["args"]["uri"])
        # file is a small enum-like -- verbatim.
        self.assertEqual(entry["args"]["file"]["val"], "log")
        # walnut is hashed by default (no whitelist).
        self.assertIn("h", entry["args"]["walnut"])

    async def test_error_entry_includes_error_code(self) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        lifespan = _FakeLifespan(audit_queue=queue)
        await emit_resource_read(
            lifespan,
            uri="alive://walnut/bogus/kernel/log",
            walnut=None,
            file=None,
            content_bytes=0,
            duration_ms=1,
            error_code="INVALID_PARAMS",
        )
        entry = queue.get_nowait()
        self.assertEqual(entry["result_status"], "error")
        self.assertEqual(entry["error_code"], "INVALID_PARAMS")
        self.assertEqual(entry["result_counts"], {"bytes": 0})

    async def test_disk_full_returns_false_and_skips_queue(self) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        state = AuditWriterState(disk_full=True)
        lifespan = _FakeLifespan(audit_queue=queue, audit_writer_state=state)
        ok = await emit_resource_read(
            lifespan,
            uri="alive://walnut/04_Ventures/alive/kernel/key",
            walnut="04_Ventures/alive",
            file="key",
            content_bytes=0,
            duration_ms=0,
        )
        self.assertFalse(ok)
        self.assertEqual(queue.qsize(), 0)

    async def test_none_lifespan_is_noop_returns_true(self) -> None:
        ok = await emit_resource_read(
            None,
            uri="alive://x",
            walnut=None,
            file=None,
            content_bytes=0,
            duration_ms=0,
        )
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# Cancellation discipline -- shield + lock protect the rotate+write sequence.
# ---------------------------------------------------------------------------


class CancellationDisciplineTests(unittest.IsolatedAsyncioTestCase):
    """In-flight writes complete despite task cancellation."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="alive-mcp-audit-shield-")
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.state = AuditWriterState()
        self.audit_path = os.path.join(
            self.tmpdir, *AUDIT_RELPATH.split("/")
        )

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_in_flight_write_is_shielded_from_cancellation(self) -> None:
        """A slow write completes even if the run loop gets cancelled mid-write.

        Wraps the sync writer in a small sleep so we can reliably
        cancel the task while the executor call is in flight. After
        cancel + await-CancelledError, the line must still be on
        disk (shield kept the future alive) AND the file must be
        valid JSONL (no truncation).
        """
        import time as _time

        writer = AuditWriter(
            self.queue, world_root=self.tmpdir, state=self.state
        )
        real_sync = writer._write_one_sync

        def _slow(line: bytes) -> None:
            _time.sleep(0.1)
            real_sync(line)

        writer._write_one_sync = _slow  # type: ignore[assignment]
        task = asyncio.create_task(writer.run())

        entry = build_entry(
            tool="x",
            args={},
            envelope=envelope.ok({}),
            duration_ms=0,
            whitelist=frozenset(),
        )
        await self.queue.put(entry)
        # Let the executor call start.
        await asyncio.sleep(0.02)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # The in-flight write landed.
        self.assertTrue(os.path.isfile(self.audit_path))
        with open(self.audit_path, "r") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1)
        # Valid JSON -- no truncation.
        json.loads(lines[0])


# ---------------------------------------------------------------------------
# Short-write handling -- os.write can return fewer bytes than requested.
# ---------------------------------------------------------------------------


class ShortWriteHandlingTests(unittest.IsolatedAsyncioTestCase):
    """os.write short returns are retried until all bytes are on disk."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="alive-mcp-audit-short-")
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.state = AuditWriterState()
        self.audit_path = os.path.join(
            self.tmpdir, *AUDIT_RELPATH.split("/")
        )

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_short_writes_are_retried_to_completion(self) -> None:
        """Simulate os.write writing only a few bytes per call.

        Monkeypatches ``os.write`` inside the audit module to return
        a capped byte count per call. The line must still land
        complete and parseable.
        """
        import alive_mcp.audit as audit_mod

        real_write = audit_mod.os.write
        calls: List[int] = []

        def _short(fd: int, data: Any) -> int:
            # Write at most 5 bytes per call to force multiple iterations.
            cap = min(5, len(data))
            calls.append(cap)
            return real_write(fd, bytes(data[:cap]))

        audit_mod.os.write = _short  # type: ignore[assignment]
        try:
            task = asyncio.create_task(
                run_audit_writer(
                    self.queue, world_root=self.tmpdir, state=self.state
                )
            )
            try:
                await self.queue.put(
                    build_entry(
                        tool="x",
                        args={},
                        envelope=envelope.ok({}),
                        duration_ms=0,
                        whitelist=frozenset(),
                    )
                )
                await self.queue.join()
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            audit_mod.os.write = real_write  # type: ignore[assignment]

        # Multiple calls happened (short-write loop).
        self.assertGreater(len(calls), 1)
        # Final file has exactly one valid JSONL line.
        with open(self.audit_path, "r") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["tool"], "x")

    async def test_zero_byte_write_trips_disk_full(self) -> None:
        """An os.write that returns 0 without raising is treated as fatal EIO."""
        import alive_mcp.audit as audit_mod

        real_write = audit_mod.os.write
        self._call_count = 0

        def _stuck(fd: int, data: Any) -> int:
            self._call_count += 1
            return 0  # Never makes progress -> should raise EIO.

        audit_mod.os.write = _stuck  # type: ignore[assignment]
        try:
            task = asyncio.create_task(
                run_audit_writer(
                    self.queue, world_root=self.tmpdir, state=self.state
                )
            )
            try:
                await self.queue.put(
                    build_entry(
                        tool="x",
                        args={},
                        envelope=envelope.ok({}),
                        duration_ms=0,
                        whitelist=frozenset(),
                    )
                )
                # Entry is consumed; task_done is called before the loop
                # continues past the exception.
                await self.queue.join()
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            audit_mod.os.write = real_write  # type: ignore[assignment]

        self.assertTrue(self.state.disk_full)


if __name__ == "__main__":
    unittest.main()
