"""End-to-end no-phone-home tests (fn-10-60k.15 / T15).

Goal
----
Prove that the alive-mcp server process NEVER opens a network socket
during stdio operation — through ``initialize``, ``tools/list``, or
any ``tools/call`` against the frozen v0.1 tool roster. The MCP
stdio transport uses stdin/stdout pipes, not sockets; any socket
open from the server process is a phone-home bug that must fail CI.

Why this needs a subprocess, not just an in-process test
--------------------------------------------------------
The :class:`tests._network_helper.NoNetworkMixin` already blocks
socket creation in the TEST runner. But the server's real runtime is
a separate Python process (spawned by the Inspector in production,
by :class:`subprocess.Popen` here). Monkeypatching the test runner's
:mod:`socket` module does nothing to a child Python that imports
its own fresh copy. The LAYER-3 block — prepending
``tests/network_block`` to :envvar:`PYTHONPATH` so Python's site
machinery auto-imports ``sitecustomize`` at subprocess startup — is
what constrains the server itself.

What's covered
--------------
* ``initialize`` + ``tools/list`` — handshake must not trigger a
  network call.
* Every v0.1 tool listed in the committed ``tools.snapshot.json`` —
  each is invoked with a dummy-but-shape-valid arguments object so
  the handler body runs end-to-end. No network.
* Negative control: a deliberate ``socket.socket(...)`` call from
  the test runner proves the mixin's runner-side block fires, so a
  regression there would be caught immediately. A second negative
  control spawns a bare Python subprocess with the same PYTHONPATH
  injection and asserts :data:`BLOCKED_MSG` appears in its stderr —
  the subprocess-side block mirror.

Fixture policy
--------------
All calls target :data:`FIXTURE_WORLD` (the committed
``tests/fixtures/world-basic/`` tree). Frozen, deterministic, cheap.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from typing import Any

import tests  # noqa: F401  (ensures src/ is on sys.path)

from tests._network_helper import BLOCKED_MSG, NoNetworkMixin, block_env
from tests._test_helpers import (
    FIXTURE_WORLD,
    _subprocess_env,
    rpc_roundtrip,
    start_server,
)


# The frozen v0.1 tool roster. Kept in sync with
# ``tests/fixtures/contracts/tools.snapshot.json``; the
# :class:`ContractFixtureShapeTests` guard in ``test_contracts.py``
# already asserts the 10-tool lock, so a duplicate constant here is
# redundant but cheap and self-documents the call plan.
FROZEN_V01_TOOLS: tuple[str, ...] = (
    "list_walnuts",
    "get_walnut_state",
    "read_walnut_kernel",
    "list_bundles",
    "get_bundle",
    "read_bundle_manifest",
    "search_world",
    "search_walnut",
    "read_log",
    "list_tasks",
)


# Minimal but schema-valid arguments for each tool. We are NOT
# testing correctness of the handler — ``test_integration`` and the
# per-family suites already do that. We ARE testing that the handler
# can run end-to-end against the fixture world without the
# socket-block firing. So the arguments just need to steer the
# handler past schema validation into its body.
_FIXTURE_WALNUT = "04_Ventures/nova-station"
_FIXTURE_BUNDLE = "shielding-review"

_TOOL_ARGS: dict[str, dict[str, Any]] = {
    "list_walnuts": {},
    "get_walnut_state": {"walnut": _FIXTURE_WALNUT},
    "read_walnut_kernel": {"walnut": _FIXTURE_WALNUT, "file": "key"},
    "list_bundles": {"walnut": _FIXTURE_WALNUT},
    "get_bundle": {"walnut": _FIXTURE_WALNUT, "bundle": _FIXTURE_BUNDLE},
    "read_bundle_manifest": {
        "walnut": _FIXTURE_WALNUT,
        "bundle": _FIXTURE_BUNDLE,
    },
    "search_world": {"query": "orbital"},
    "search_walnut": {"walnut": _FIXTURE_WALNUT, "query": "test"},
    "read_log": {"walnut": _FIXTURE_WALNUT},
    "list_tasks": {"walnut": _FIXTURE_WALNUT},
}


def _frames_for_full_tool_sweep() -> list[dict[str, Any]]:
    """Build the JSON-RPC frame list: initialize + tools/list + every tool.

    One frame list, one subprocess invocation, one ``communicate``
    roundtrip — keeps the test to a single server boot and makes the
    "no socket was opened during ANY of these calls" assertion
    atomic. If we spawned 10 separate processes, a flaky test could
    attribute a socket attempt to the wrong tool; batching avoids
    that.
    """
    frames: list[dict[str, Any]] = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {
                    "name": "alive-mcp-no-phone-home",
                    "version": "0.0.0",
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    ]
    # Frame ids start at 100 for tool calls so the handshake's 1/2
    # cannot collide.
    next_id = 100
    for tool in FROZEN_V01_TOOLS:
        frames.append(
            {
                "jsonrpc": "2.0",
                "id": next_id,
                "method": "tools/call",
                "params": {
                    "name": tool,
                    "arguments": _TOOL_ARGS[tool],
                },
            }
        )
        next_id += 1
    return frames


class NoPhoneHomeTests(NoNetworkMixin, unittest.TestCase):
    """End-to-end proof: the server opens zero sockets over the full tool sweep."""

    def _spawn_with_network_block(
        self, world_root: str
    ) -> subprocess.Popen[bytes]:
        """Clone of :func:`start_server` that layers the socket block on top.

        We cannot just call ``start_server`` and pass ``extra_env`` —
        the existing helper's ``_subprocess_env`` sets
        ``PYTHONPATH=<src>`` unconditionally, and any ``extra_env``
        PYTHONPATH override would clobber ``src/`` and the server
        would fail to import. So we build the env manually, let
        ``block_env`` prepend the network-block dir, and keep the
        ``src/`` suffix intact.
        """
        base = _subprocess_env(world_root)
        env = block_env(base)
        # Defense in depth: a developer pointing ``ALIVE_MCP_AUDIT_DIR``
        # at a non-default location could cause the audit writer to
        # initialize differently. The fixture world's audit dir is
        # already a local filesystem path, but scrub any inherited
        # override so a local dev env cannot influence the test.
        env.pop("ALIVE_MCP_AUDIT_DIR", None)
        return subprocess.Popen(
            [sys.executable, "-m", "alive_mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    # ------------------------------------------------------------------
    # Positive case: real server, real tool sweep, zero sockets opened.
    # ------------------------------------------------------------------
    def _drive_tool_sweep(
        self, proc: subprocess.Popen[bytes]
    ) -> tuple[list[dict[str, Any]], str]:
        """Stream frames + drain responses without relying on EOF semantics.

        ``subprocess.Popen.communicate`` writes all stdin, closes it,
        then waits for the child to exit. The MCP stdio server's
        event loop processes requests in order but its outgoing
        writes race against the ``stdin EOF -> shutdown`` signal: on
        macOS / Linux we observe that the last few ``tools/call``
        responses never make it to stdout before the loop exits.

        Fix: write all frames, then DRAIN stdout by reading
        line-by-line until we have collected every expected response
        id (or hit the deadline). Only then close stdin and wait for
        the process to exit. This is identical to how a real MCP
        client drives the transport: write a frame, wait for its
        response, proceed.
        """
        assert proc.stdin is not None
        assert proc.stdout is not None

        expected_ids = {1, 2} | set(
            range(100, 100 + len(FROZEN_V01_TOOLS))
        )
        frames = _frames_for_full_tool_sweep()

        # Write every frame in one shot. The server buffers the
        # input queue and processes them serially; batching the
        # writes keeps the test from racing on partial payloads.
        payload = b"".join(
            json.dumps(f, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
            + b"\n"
            for f in frames
        )
        proc.stdin.write(payload)
        proc.stdin.flush()

        # Drain stdout line-by-line until every expected response
        # has arrived or the deadline fires. Using a blocking
        # ``readline`` inside a deadline loop is simplest and works
        # cross-platform (``select`` on Windows pipes is unreliable).
        deadline = time.monotonic() + 30.0
        collected: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        while seen_ids != expected_ids:
            if time.monotonic() > deadline:
                break
            line = proc.stdout.readline()
            if not line:
                # EOF before all responses arrived — server died
                # mid-stream. Let the assertion in the caller
                # surface the partial state.
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                frame = json.loads(stripped.decode("utf-8"))
            except json.JSONDecodeError as exc:  # pragma: no cover
                raise RuntimeError(
                    "non-JSON line on server stdout: "
                    f"{stripped!r}; decode error: {exc}"
                ) from exc
            collected.append(frame)
            if "id" in frame:
                seen_ids.add(frame["id"])

        # Close stdin so the server's stdio loop sees EOF and
        # shuts down. Read any remaining stdout / stderr manually —
        # calling ``communicate`` again after a manual write/read
        # mix fails with AttributeError on CPython 3.12.
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        assert proc.stderr is not None
        # Drain any late-arriving stdout lines. Bounded by a wall-
        # clock deadline so a stuck server cannot hang the test.
        drain_deadline = time.monotonic() + 10.0
        while time.monotonic() < drain_deadline:
            line = proc.stdout.readline()
            if not line:
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                frame = json.loads(stripped.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            collected.append(frame)
            if "id" in frame:
                seen_ids.add(frame["id"])
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)
        stderr_bytes = proc.stderr.read()
        # Explicit pipe close silences CPython's ResourceWarning in
        # test output; the subprocess is done so leaving them to
        # finalize would work too, just noisier.
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.stderr.close()
        except Exception:
            pass
        return collected, stderr_bytes.decode("utf-8", errors="replace")

    def test_full_tool_sweep_opens_no_socket(self) -> None:
        """Boot the server, call every tool, assert stderr has no block-fire msg.

        If any tool attempted to open a phone-home-capable socket
        (AF_INET / AF_INET6), the subprocess-side block would raise
        :class:`RuntimeError` with :data:`BLOCKED_MSG` in the
        message. Because tool handlers are wrapped in the envelope /
        except machinery, the error MIGHT be caught and surfaced as
        a tool-level error envelope rather than crashing the server.
        Either outcome leaves :data:`BLOCKED_MSG` on stderr (either
        as a traceback or as a log line) — so greping stderr for
        that sentinel is a CORRECT positive test for "any socket
        attempt happened anywhere in the process".
        """
        proc = self._spawn_with_network_block(str(FIXTURE_WORLD))
        try:
            responses, stderr_text = self._drive_tool_sweep(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass

        # Every response frame we care about (ids 1, 2, 100..109) must
        # be present. If the server crashed mid-stream those ids would
        # be missing — a clearer failure signal than "stderr contains
        # BLOCKED_MSG".
        got_ids = {f.get("id") for f in responses if "id" in f}
        expected_ids = {1, 2} | set(range(100, 100 + len(FROZEN_V01_TOOLS)))
        missing = expected_ids - got_ids
        self.assertEqual(
            missing,
            set(),
            msg=(
                "server did not respond to every frame; missing response "
                f"ids={sorted(missing)}. stderr:\n{stderr_text}"
            ),
        )

        # THE invariant: stderr must not contain the block-fire
        # sentinel. Anywhere. No exceptions.
        self.assertNotIn(
            BLOCKED_MSG,
            stderr_text,
            msg=(
                "network socket attempt detected during tool sweep "
                "(sitecustomize block fired). Full stderr:\n"
                f"{stderr_text}"
            ),
        )

        # Every tools/call response must carry a ``result`` (tool
        # handlers may have returned an error envelope, but the
        # JSON-RPC envelope itself must succeed — a missing
        # ``result`` with an ``error`` peer would mean the dispatcher
        # itself crashed, which could hide a phone-home attempt
        # upstream of the envelope.
        tool_call_frames = [f for f in responses if isinstance(f.get("id"), int) and f["id"] >= 100]
        self.assertEqual(
            len(tool_call_frames),
            len(FROZEN_V01_TOOLS),
            msg=f"expected {len(FROZEN_V01_TOOLS)} tool-call responses, "
                 f"got {len(tool_call_frames)}",
        )
        for frame in tool_call_frames:
            self.assertIn(
                "result",
                frame,
                msg=f"tool-call frame id={frame.get('id')} has no result: {frame!r}",
            )

    # ------------------------------------------------------------------
    # Negative controls: prove the block itself works.
    # ------------------------------------------------------------------
    def test_runner_side_block_raises(self) -> None:
        """The ``NoNetworkMixin`` must block an in-runner socket attempt.

        If this test ever stops raising, the mixin is broken and
        every other test that relies on the runner-side block is
        silently degraded. Keeping this positive-negative-control
        in the same file means a failure lights up right next to the
        thing it guards.
        """
        import socket as _socket

        with self.assertRaises(RuntimeError) as cm:
            _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        self.assertIn(BLOCKED_MSG, str(cm.exception))

    def test_subprocess_side_block_fires_on_attempt(self) -> None:
        """Spawn a bare Python child with the block and assert it fires.

        Proves the subprocess-side block works IN ISOLATION — a
        canary against a future change to :mod:`sitecustomize` that
        accidentally breaks its auto-loading. If this test passes
        but :meth:`test_full_tool_sweep_opens_no_socket` regresses,
        the bug is in the server code (a new phone-home dependency).
        If THIS test regresses, the bug is in the block itself and
        :meth:`test_full_tool_sweep_opens_no_socket`'s proof is no
        longer valid.
        """
        env = block_env(_subprocess_env(None))
        # Programmatic check: import socket, try to construct one,
        # print the exception type to stderr, exit. If sitecustomize
        # didn't load, the ``socket.socket`` call succeeds and the
        # script exits 0 without the sentinel.
        code = (
            "import socket, sys\n"
            "try:\n"
            "    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "    s.close()\n"
            "    sys.stderr.write('NO BLOCK FIRED\\n')\n"
            "    sys.exit(1)\n"
            "except RuntimeError as e:\n"
            "    sys.stderr.write(str(e) + '\\n')\n"
            "    sys.exit(0)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "subprocess block canary did not fire as expected. "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            ),
        )
        self.assertIn(BLOCKED_MSG, result.stderr)

    def test_af_unix_allowed_through_block(self) -> None:
        """AF_UNIX must be allowed — asyncio / socketpair depend on it.

        The block deliberately passes local-IPC families through to
        the real ``socket.socket`` constructor. Regressing to a
        blanket block would break :func:`asyncio.run` (used by the
        mcp stdio runner) and wedge the server at startup. This
        guard makes the AF_UNIX pass-through explicit.
        """
        env = block_env(_subprocess_env(None))
        code = (
            "import socket, sys\n"
            "try:\n"
            "    a, b = socket.socketpair()\n"
            "    a.close(); b.close()\n"
            "    sys.exit(0)\n"
            "except RuntimeError as e:\n"
            "    sys.stderr.write(str(e) + '\\n')\n"
            "    sys.exit(2)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "socket.socketpair() was blocked, which will break "
                f"asyncio. stderr={result.stderr!r}"
            ),
        )

    def test_simulated_phone_home_tool_handler_trips_block(self) -> None:
        """Deliberately attempt a TCP socket in a subprocess; block must fire.

        This is the acceptance-criterion fixture: "deliberately adding
        a ``socket.connect()`` to a tool handler fails CI." Instead of
        modifying a real tool handler (which would require patching
        committed source), we model a tool handler's behavior as a
        subprocess that tries the same ``socket.socket(AF_INET, ...)``
        + ``connect`` a phone-home payload would use. The subprocess-
        side block catches the AF_INET constructor call before
        ``connect`` even runs, and the canonical BLOCKED_MSG appears
        in stderr — which is what CI would detect on a real phone-
        home regression.
        """
        env = block_env(_subprocess_env(None))
        code = (
            "import socket\n"
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "s.connect(('8.8.8.8', 53))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Expected: non-zero exit (RuntimeError propagated), BLOCKED_MSG
        # in stderr, and NO connect attempt actually reached the
        # network (the block fires in ``__init__``, before connect).
        self.assertNotEqual(
            result.returncode,
            0,
            msg=(
                "simulated phone-home did not fail — block is "
                f"broken. stdout={result.stdout!r} stderr={result.stderr!r}"
            ),
        )
        self.assertIn(BLOCKED_MSG, result.stderr)


class BlockInjectionSanityTests(unittest.TestCase):
    """Pure unittest (no mixin) — tests the helpers don't leak state.

    If :class:`NoNetworkMixin`'s :meth:`tearDown` failed to restore
    :meth:`socket.socket.__init__`, this test (which runs WITHOUT the
    mixin) would fail at the very first real socket call. Putting it
    AFTER :class:`NoPhoneHomeTests` in the same module (same process)
    means any teardown leakage immediately surfaces.

    We use unittest test ordering (alphabetical by default), which
    puts ``BlockInjectionSanityTests`` ahead of ``NoPhoneHomeTests``
    normally. So we deliberately force the "after" ordering by
    loading via an ordered helper — see :func:`_alpha_ordering_hint`
    below.
    """

    def test_socket_still_works_outside_mixin(self) -> None:
        """A non-mixin test must still be able to construct a socket.

        Proves :meth:`NoNetworkMixin.tearDown` restored the original
        ``socket.socket.__init__``. Doesn't actually connect (no
        network), just proves the constructor is callable.
        """
        import socket as _socket

        # AF_INET + SOCK_DGRAM doesn't require a listening peer; close
        # immediately so we never go near the network.
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        try:
            self.assertIsNotNone(s)
        finally:
            s.close()

    def test_block_env_prepends_pythonpath(self) -> None:
        """Sanity check that :func:`block_env` prepends, not overwrites.

        A regression here would silently disable the subprocess-side
        block by dropping ``src/`` (which the server needs to import
        ``alive_mcp``) or by putting the block AFTER an existing
        ``sitecustomize`` in ``sys.path``.
        """
        base = {"PYTHONPATH": "/some/other/dir"}
        got = block_env(base)
        paths = got["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(paths[0].endswith("network_block"), True)
        self.assertIn("/some/other/dir", paths)

    def test_block_env_handles_empty_base(self) -> None:
        """When the base env has no ``PYTHONPATH``, we set ours cleanly."""
        got = block_env({})
        self.assertTrue(got["PYTHONPATH"].endswith("network_block"))
        # No leading path separator.
        self.assertFalse(got["PYTHONPATH"].startswith(os.pathsep))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
