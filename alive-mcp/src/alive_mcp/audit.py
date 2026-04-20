"""JSONL audit logger (fn-10-60k.12 / T12).

Writes one JSON line per tool invocation or resource read to
``<world>/.alive/_mcp/audit.log``. Async queue in front of a background
writer task; size-based rotation with 10 backups; selective hashing of
path-like argument values. Fail-closed on disk full.

Design invariants
-----------------
1. **Never block the event loop.** Tool handlers call
   :meth:`asyncio.Queue.put_nowait` via the :func:`audited` decorator.
   The background writer drains the queue and performs the actual
   :func:`open` / :func:`write` / :func:`os.rename` on an executor
   thread via :meth:`asyncio.get_running_loop().run_in_executor`. No
   blocking I/O touches the loop thread. ``logging.handlers.Rotating
   FileHandler`` is deliberately not used because it does blocking I/O
   in-line inside :meth:`~logging.Handler.emit`.

2. **Privacy-first.** Every str/list/dict argument value is hashed
   (sha256, first 16 hex chars) and summarized
   ``{"type": "str", "len": N, "h": "..."}``. Only small scalars (int,
   bool, enum literal) are logged verbatim. Walnut POSIX paths that
   appear in the ``ALIVE_MCP_AUDIT_PUBLIC_WALNUT_PATHS`` env whitelist
   are the single opt-in verbatim escape hatch. Default empty whitelist
   means hash everything.

3. **Record bodies never leak.** :func:`build_entry` accepts an envelope
   and derives ``result_counts`` from list-valued fields in
   ``structuredContent`` (e.g. ``walnuts``, ``matches``, ``tasks``).
   Content strings (log bodies, file contents) are never included in
   the entry.

4. **Fail-closed on disk full.** When a write raises
   :class:`OSError` with errno ``ENOSPC`` or ``EIO``, the writer flips a
   shared "disk full" flag. Subsequent tool invocations observe the
   flag BEFORE queuing and return ``ERR_AUDIT_DISK_FULL`` -- the tool
   body does NOT run. This matches the spec's fail-closed posture:
   audit loss is worse than tool unavailability.

5. **Rotation without feedback.** The audit tree lives at
   ``<world>/.alive/_mcp/``. T11's subscription observer excludes that
   subtree (see :func:`alive_mcp.resources.subscriptions.classify_path`
   -- ``.alive/_mcp/**`` -> ``ignored``) so rotation never triggers a
   notification cascade.

Entry shape
-----------
One JSON object per line. Keys are stable (no ad-hoc additions) so
offline log analysis stays straightforward:

.. code-block:: python

    {
      "ts":             "2026-04-16T14:30:00.123Z",  # ISO-8601 UTC, ms.
      "session_id":     "e47de88d" | null,            # MCP session id if known.
      "tool":           "search_world",               # tool name verbatim.
      "args": {
        "query":        {"type": "str", "len": 18, "h": "a3f5..."},
        "limit":        {"type": "int", "val": 20},
      },
      "result_status":  "ok" | "error",
      "result_counts":  {"matches": 12, "skipped": 0},  # counts only.
      "duration_ms":    142,
      "error_code":     null | "ERR_WALNUT_NOT_FOUND",
    }

Rotation
--------
* Active file ``audit.log``, up to :data:`MAX_ACTIVE_BYTES` (10MB).
* Up to :data:`MAX_ROTATIONS` backups (10), named ``audit.log.1`` ..
  ``audit.log.10``; oldest dropped.
* At most 11 files total, 110MB ceiling.
* Rotation is triggered by the writer when a pending entry would push
  the active file past the cap; the check runs per-entry so bursts
  cannot overshoot the ceiling.

Environment
-----------
``ALIVE_MCP_AUDIT_PUBLIC_WALNUT_PATHS`` -- comma-separated POSIX-relative
walnut paths (e.g. ``04_Ventures/alive,02_Life/people/ben-flint``) whose
str arguments should be logged verbatim instead of hashed. Empty /
unset = hash every str. The whitelist compares against the full arg
value verbatim; a partial-match (substring) is not a match, so using
this flag intentionally opts a specific walnut path into verbatim
logging without accidentally unmasking arbitrary queries that happen to
mention the path.
"""
from __future__ import annotations

import asyncio
import errno
import functools
import hashlib
import inspect
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Sequence, TypeVar, Union, overload

logger = logging.getLogger("alive_mcp.audit")


# ---------------------------------------------------------------------------
# Rotation + file layout constants.
# ---------------------------------------------------------------------------

#: Max bytes in the active ``audit.log`` before rotation. 10MB per the
#: spec. Tests override with a monkeypatch to exercise rotation without
#: generating 10MB of log lines.
MAX_ACTIVE_BYTES: int = 10 * 1024 * 1024

#: Max rotation backups retained on disk (``audit.log.1`` .. ``audit.log.N``).
#: At N=10 the on-disk footprint is capped at 11 * 10MB = 110MB.
MAX_ROTATIONS: int = 10

#: POSIX file mode for the audit log + its parent. Owner-only read/write.
#: The spec (and the general "secrets live in ~/.env" posture) requires
#: 0o600 so a broken umask does not widen access. We ``chmod`` after
#: create because ``open(..., mode=0o600)`` is honored but ``os.makedirs``
#: does not accept a per-dir mode that survives the umask on all
#: platforms.
AUDIT_FILE_MODE: int = 0o600
AUDIT_DIR_MODE: int = 0o700

#: Relative path from the World root to the audit file.
AUDIT_RELPATH: str = ".alive/_mcp/audit.log"

#: Env var whose comma-separated POSIX-relpath entries opt walnut paths
#: into verbatim logging. Default unset / empty = hash every str.
ENV_PUBLIC_WALNUT_PATHS: str = "ALIVE_MCP_AUDIT_PUBLIC_WALNUT_PATHS"

#: sha256 hex prefix length retained in summarized str records. 16 hex
#: chars = 64 bits, low enough to discourage rainbow-table attacks on
#: short queries while still providing a stable fingerprint across runs.
HASH_PREFIX_CHARS: int = 16


# ---------------------------------------------------------------------------
# Entry-building helpers (pure -- no I/O, no loop).
# ---------------------------------------------------------------------------


def _load_whitelist() -> frozenset[str]:
    """Parse :data:`ENV_PUBLIC_WALNUT_PATHS` into a frozen set.

    Empty / unset -> empty set. Whitespace around entries is stripped;
    blank entries are dropped. The comparison is exact-string (no
    normalization), so callers that include a trailing slash would have
    to include it in the env value too -- which is fine because the
    whitelist is a targeted escape hatch rather than a smart matcher.
    """
    raw = os.environ.get(ENV_PUBLIC_WALNUT_PATHS, "")
    if not raw:
        return frozenset()
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def _hash_str(value: str) -> str:
    """Return the first :data:`HASH_PREFIX_CHARS` of ``sha256(value)`` hex.

    UTF-8 encoding is forced so hashes are stable across locale-changed
    environments. Callers summarize strings via this fingerprint plus
    ``type`` and ``len`` metadata.
    """
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[
        :HASH_PREFIX_CHARS
    ]


#: Kwarg keys whose str values MAY be logged verbatim when the value
#: appears in the public-walnut-paths whitelist. Restricting the
#: whitelist to these keys is a privacy-defense: even if a caller
#: enabled ``ALIVE_MCP_AUDIT_PUBLIC_WALNUT_PATHS=04_Ventures/alive``,
#: a ``search_world(query="04_Ventures/alive is boring")`` call still
#: hashes the query because ``query`` is not in this set. The risk
#: would otherwise be that a short whitelist entry acts as an
#: unhashing-token for arbitrary free-text values that happen to
#: match. Kept tight: walnut/bundle paths are the only identifiers
#: the spec expects to see verbatim.
_VERBATIM_ELIGIBLE_KEYS: frozenset[str] = frozenset({"walnut", "bundle"})


def _summarize_value(
    value: Any,
    *,
    whitelist: frozenset[str],
    allow_whitelist: bool = True,
) -> dict[str, Any]:
    """Return the audit summary for a single argument value.

    Rules (frozen with the spec):

    * ``None`` -> ``{"type": "null"}``.
    * ``bool`` -> ``{"type": "bool", "val": ...}``. (``bool`` before
      ``int`` because ``bool`` is a subclass of ``int`` in Python and
      isinstance checks would mis-order otherwise.)
    * ``int`` / ``float`` -> ``{"type": "int"|"float", "val": ...}``.
    * ``str`` ->

        * If the string appears verbatim in ``whitelist``, emit
          ``{"type": "str", "len": N, "val": <verbatim>}`` -- explicit
          opt-in.
        * Else emit ``{"type": "str", "len": N, "h": <hash>}`` --
          hashed summary, never the original bytes.

    * ``list`` / ``tuple`` -> ``{"type": "list", "len": N, "h": <hash-of-json>}``.
    * ``dict`` -> ``{"type": "dict", "len": N, "h": <hash-of-json>}``.
    * Anything else -> ``{"type": "other", "repr_len": N, "h":
      <hash-of-repr>}`` -- defensive default that still records a
      length + fingerprint without materializing the raw value in the
      log.

    The hash is never over the raw list/dict; it is over a stable JSON
    serialization (keys sorted). This means the same list in a
    different order hashes differently, which is the intended
    behavior -- argument reordering is a different call.
    """
    # bool must precede int check.
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "bool", "val": value}
    if isinstance(value, int):
        return {"type": "int", "val": value}
    if isinstance(value, float):
        return {"type": "float", "val": value}
    if isinstance(value, str):
        record: dict[str, Any] = {"type": "str", "len": len(value)}
        # Only eligible kwarg keys (walnut, bundle) get the
        # whitelist-bypass; all other str values are always hashed,
        # even if they happen to match a whitelist entry. This closes
        # the "short whitelist token unhashes arbitrary queries"
        # footgun.
        if allow_whitelist and value in whitelist:
            record["val"] = value
        else:
            record["h"] = _hash_str(value)
        return record
    if isinstance(value, (list, tuple)):
        # json.dumps(sort_keys=True) over a list preserves list order
        # (sort_keys only sorts dict keys). That's the intended shape:
        # reordered arguments hash differently, but identical lists
        # hash the same across calls.
        try:
            as_json = json.dumps(
                list(value), sort_keys=True, separators=(",", ":"), default=str
            )
        except (TypeError, ValueError):
            as_json = repr(value)
        return {
            "type": "list",
            "len": len(value),
            "h": _hash_str(as_json),
        }
    if isinstance(value, dict):
        try:
            as_json = json.dumps(
                value, sort_keys=True, separators=(",", ":"), default=str
            )
        except (TypeError, ValueError):
            as_json = repr(value)
        return {
            "type": "dict",
            "len": len(value),
            "h": _hash_str(as_json),
        }
    # Fallback -- unknown type (bytes, datetime, custom class). Record
    # its repr length and a hash over repr so abuse patterns on exotic
    # types remain detectable without surfacing the raw value.
    rep = repr(value)
    return {"type": "other", "repr_len": len(rep), "h": _hash_str(rep)}


def summarize_args(
    kwargs: dict[str, Any],
    *,
    whitelist: Optional[frozenset[str]] = None,
) -> dict[str, dict[str, Any]]:
    """Summarize every entry in ``kwargs`` via :func:`_summarize_value`.

    ``whitelist`` defaults to :func:`_load_whitelist` -- the env-derived
    opt-in set. Passing an explicit set overrides the env, which is the
    hook tests use to exercise the opt-in path without mutating the
    process env.

    Keys are copied verbatim (the key space is under our control --
    tool handlers name their parameters). Values flow through
    :func:`_summarize_value`.

    ``ctx`` parameters (FastMCP's request context) are the one kwarg
    every tool takes; the audited decorator drops it before calling
    this helper (it's infrastructure, not a user argument). We do not
    filter here so the function stays composable; callers that receive
    a ``ctx`` in kwargs will get it serialized via the ``other``
    branch, which is harmless but noisy.
    """
    if whitelist is None:
        whitelist = _load_whitelist()
    return {
        k: _summarize_value(
            v,
            whitelist=whitelist,
            allow_whitelist=k in _VERBATIM_ELIGIBLE_KEYS,
        )
        for k, v in kwargs.items()
    }


#: Keys in envelope ``structuredContent`` whose list length is a useful
#: "result count" signal for forensics. Non-list values of these keys
#: are silently ignored (no count recorded). Keeping this whitelist
#: explicit avoids the risk of treating a list-valued payload field
#: that happens to contain text snippets as a count -- we only record
#: counts for the frozen set of inventory-shaped fields.
_COUNT_FIELDS: tuple[str, ...] = (
    "walnuts",
    "bundles",
    "matches",
    "skipped",
    "tasks",
    "entries",
    "pages",
    "sources",
)


def _extract_result_counts(envelope: Any) -> dict[str, int]:
    """Return ``{field_name: len(list)}`` for each known list field.

    Inspects ``envelope["structuredContent"]`` -- a dict under the MCP
    response schema. Every element in :data:`_COUNT_FIELDS` that is
    present AND a list contributes a count. Anything else (missing,
    non-list) is skipped. A tool that returns ``{matches: [...],
    next_cursor: "..."}`` therefore produces ``{matches: N}`` with no
    ``next_cursor`` field in the counts dict.

    This is DELIBERATELY a whitelist rather than a "count every list"
    heuristic -- result bodies often contain list-shaped content
    (e.g. a log entry's bullet list) and we do not want to leak those
    counts either.
    """
    if not isinstance(envelope, dict):
        return {}
    structured = envelope.get("structuredContent")
    if not isinstance(structured, dict):
        return {}
    counts: dict[str, int] = {}
    for field_name in _COUNT_FIELDS:
        value = structured.get(field_name)
        if isinstance(value, list):
            counts[field_name] = len(value)
    return counts


def _extract_error_code(envelope: Any) -> Optional[str]:
    """Return the envelope's short-form error code or None on success.

    Error envelopes carry ``isError=True`` with a
    ``structuredContent.error`` short code (per ``envelope.error``).
    Success envelopes have ``isError=False`` and no ``error`` key. The
    returned string is the wire-form (no ``ERR_`` prefix).
    """
    if not isinstance(envelope, dict):
        return None
    if not envelope.get("isError"):
        return None
    structured = envelope.get("structuredContent")
    if not isinstance(structured, dict):
        return None
    code = structured.get("error")
    return code if isinstance(code, str) else None


def _iso_utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with millisecond precision.

    Format: ``YYYY-MM-DDTHH:MM:SS.sssZ``. ``Z`` suffix (not ``+00:00``)
    matches the format used in kernel now.json ``updated`` fields, so
    log entries slot into the same timeline without reformatting.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(
        dt.microsecond // 1000
    )


def build_entry(
    *,
    tool: str,
    args: dict[str, Any],
    envelope: Any,
    duration_ms: int,
    session_id: Optional[str] = None,
    whitelist: Optional[frozenset[str]] = None,
) -> dict[str, Any]:
    """Build the JSONL audit entry for a completed tool invocation.

    The entry shape is the frozen schema in the module docstring. On
    success, ``error_code`` is None and ``result_status`` is ``"ok"``;
    on error, ``error_code`` carries the short code and
    ``result_status`` is ``"error"``.

    ``args`` should contain only the user-supplied kwargs -- the FastMCP
    :class:`Context` is NOT an argument in the user sense. Callers are
    responsible for dropping it before calling here (the :func:`audited`
    decorator does this).
    """
    error_code = _extract_error_code(envelope)
    return {
        "ts": _iso_utc_now(),
        "session_id": session_id,
        "tool": tool,
        "args": summarize_args(args, whitelist=whitelist),
        "result_status": "error" if error_code is not None else "ok",
        "result_counts": _extract_result_counts(envelope),
        "duration_ms": duration_ms,
        "error_code": error_code,
    }


# ---------------------------------------------------------------------------
# Writer -- background task draining an asyncio.Queue into JSONL file.
# ---------------------------------------------------------------------------


@dataclass
class AuditWriterState:
    """Shared state between the decorator and the writer task.

    The decorator reads :attr:`disk_full` BEFORE queuing so it can
    fail-closed without blocking the event loop on a drained-queue
    race. The writer flips the flag when an ENOSPC/EIO write raises.
    The flag is sticky for the lifetime of the server run -- a manual
    intervention (``rm audit.log.10``) would require a restart to
    resume logging, which is the correct posture for an audit channel.
    """

    #: Absolute path to the active ``audit.log``. Computed once from the
    #: World root on writer start. None until the writer has resolved
    #: the World root (i.e. lifespan has captured a world).
    active_path: Optional[str] = None

    #: True once the writer has observed an ENOSPC/EIO on write. The
    #: decorator reads this before queuing.
    disk_full: bool = False

    #: Writes processed (success counter for tests).
    writes_ok: int = 0

    #: Writes that raised (any exception counter for tests).
    writes_failed: int = 0


class AuditWriter:
    """Background drainer: queue -> JSONL file, with rotation.

    One instance per server run. Owned by the lifespan which creates
    the backing :class:`asyncio.Task` and awaits its cancellation on
    shutdown.

    All blocking I/O runs on the default executor via
    :meth:`asyncio.AbstractEventLoop.run_in_executor`. The writer's
    coroutine body never calls :func:`open` / :func:`os.rename` /
    :func:`os.stat` directly -- every call is wrapped in
    ``loop.run_in_executor(None, _sync_fn)``.
    """

    def __init__(
        self,
        queue: "asyncio.Queue[dict[str, Any]]",
        *,
        world_root: Optional[str],
        state: Optional[AuditWriterState] = None,
        max_active_bytes: int = MAX_ACTIVE_BYTES,
        max_rotations: int = MAX_ROTATIONS,
    ) -> None:
        self.queue = queue
        self.world_root = world_root
        self.state = state if state is not None else AuditWriterState()
        self.max_active_bytes = max_active_bytes
        self.max_rotations = max_rotations
        # Serializes the main loop and the shutdown-drain path. Only
        # one of them holds the lock at a time, so the rotate+write
        # sequence on disk always runs without the other path slipping
        # a concurrent executor submission in between. The serializer
        # also pairs with :func:`asyncio.shield` around the executor
        # call in :meth:`_write_one` so a ``CancelledError`` at the
        # main-loop level cannot skip over an in-flight write -- the
        # shield keeps the executor future running to completion; the
        # lock keeps the cancel-triggered drain from starting its own
        # executor call until the in-flight write has released.
        self._write_lock: asyncio.Lock = asyncio.Lock()
        if world_root is not None:
            self.state.active_path = os.path.join(world_root, AUDIT_RELPATH)

    # ---- pure-sync helpers (executor-safe) -------------------------------

    def _ensure_dir(self) -> None:
        """Create the parent directory with 0o700 perms if it's missing.

        Called under the executor; safe to run blocking. We compute
        the parent from :attr:`AuditWriterState.active_path` so both
        the dir and the file share a consistent World root.
        """
        if self.state.active_path is None:
            return
        parent = os.path.dirname(self.state.active_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, mode=AUDIT_DIR_MODE, exist_ok=True)
            # os.makedirs honors the mode arg but umask can still
            # pare it down. Explicit chmod closes that window.
            try:
                os.chmod(parent, AUDIT_DIR_MODE)
            except OSError:
                logger.debug("chmod on audit parent %r failed", parent)

    def _file_size(self) -> int:
        """Return active-file byte size, 0 if missing."""
        if self.state.active_path is None:
            return 0
        try:
            return os.stat(self.state.active_path).st_size
        except FileNotFoundError:
            return 0
        except OSError:
            # Stat failure -- treat as zero-size; a write attempt will
            # surface the real error.
            return 0

    def _rotate(self) -> None:
        """Rename ``audit.log`` -> ``audit.log.1``, shifting others.

        Sequence (all blocking file-system ops; run under executor):

        1. If ``audit.log.<N>`` exists, unlink it (drop oldest).
        2. For i = N-1 .. 1: rename ``audit.log.<i>`` -> ``audit.log.<i+1>``.
        3. Rename ``audit.log`` -> ``audit.log.1``.

        Missing intermediate files are skipped silently -- that's the
        normal state for a fresh server where only ``audit.log`` and
        maybe ``audit.log.1`` exist.
        """
        if self.state.active_path is None:
            return
        base = self.state.active_path
        # 1. drop oldest
        oldest = "{}.{}".format(base, self.max_rotations)
        if os.path.exists(oldest):
            try:
                os.unlink(oldest)
            except OSError:
                logger.exception("could not drop oldest audit rotation %r", oldest)
        # 2. shift middle rotations outward
        for i in range(self.max_rotations - 1, 0, -1):
            src = "{}.{}".format(base, i)
            dst = "{}.{}".format(base, i + 1)
            if os.path.exists(src):
                try:
                    os.rename(src, dst)
                except OSError:
                    logger.exception(
                        "could not rotate audit file %r -> %r", src, dst
                    )
        # 3. move active -> .1
        if os.path.exists(base):
            try:
                os.rename(base, "{}.1".format(base))
            except OSError:
                logger.exception(
                    "could not rotate active audit log %r -> %r.1", base, base
                )

    def _open_and_append(self, line: bytes) -> None:
        """Append ``line`` (already includes trailing newline) to the active file.

        Opens with ``'ab'`` so pre-existing content is preserved across
        restarts. New files are created with :data:`AUDIT_FILE_MODE`
        (0o600); existing files keep their mode but we ``chmod`` after
        open anyway so a mis-mode'd file from a prior run gets
        tightened.

        Handles short writes: :func:`os.write` is permitted by POSIX to
        write fewer bytes than requested (most filesystems don't short-
        write a small entry, but NFS / fuse / pipe-backed mounts can).
        We loop until every byte is on disk or an :class:`OSError`
        raises. A short write that stalls at zero raises ``OSError
        (EIO)`` synthetically so the fail-closed path trips instead of
        silently producing a truncated (invalid JSON) line.
        """
        if self.state.active_path is None:
            return
        path = self.state.active_path
        # os.open -> fdopen gives us control over creation mode, which
        # plain ``open(..., 'ab')`` does not expose (Python's open()
        # passes the mode but the default umask still subtracts from
        # it). We pass O_CREAT | O_APPEND | O_WRONLY and AUDIT_FILE_MODE
        # so the file is 0o600 on creation regardless of umask.
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        fd = os.open(path, flags, AUDIT_FILE_MODE)
        try:
            remaining = memoryview(line)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    # Zero-length write with no error is unusual but
                    # possible (interrupted, then nothing made progress
                    # across retries). Treat as fatal EIO so the caller
                    # flips disk_full and stops queuing, rather than
                    # silently truncating the JSONL stream.
                    raise OSError(errno.EIO, "short write: zero bytes progressed")
                remaining = remaining[written:]
        finally:
            os.close(fd)
        # Belt + braces: if the file pre-existed with wider perms, tighten.
        try:
            os.chmod(path, AUDIT_FILE_MODE)
        except OSError:
            logger.debug("chmod on audit log %r failed", path)

    def _write_one_sync(self, line: bytes) -> None:
        """Executor-side sync write for a single pre-encoded line.

        Performs the per-entry rotation check and then the append.
        Splits out because the async wrapper needs to run the whole
        thing inside one executor call so filesystem state stays
        consistent across the size check + write window (another
        concurrent writer could race, but we have exactly one writer
        task per server run, so the single-writer assumption holds).
        """
        self._ensure_dir()
        size = self._file_size()
        # Rotate BEFORE write when the pending line would push us past
        # the cap. Bursts that each individually fit still rotate at
        # the right boundary.
        if size + len(line) > self.max_active_bytes:
            self._rotate()
        self._open_and_append(line)

    # ---- async loop body -------------------------------------------------

    async def _write_one(self, entry: dict[str, Any]) -> None:
        """Encode ``entry`` + dispatch to the executor to perform the write.

        On ENOSPC / EIO / EDQUOT raise (disk full / device error / quota),
        flip :attr:`AuditWriterState.disk_full` and re-raise so the
        caller loop logs + stops draining (subsequent tool calls fail
        closed via the decorator's pre-check).

        On any other :class:`OSError`, log and skip the entry. A
        transient filesystem hiccup should not wedge the writer.

        Cancellation discipline
        -----------------------
        The executor future is wrapped in :func:`asyncio.shield` so a
        ``CancelledError`` delivered to the loop task cannot interrupt
        the in-flight write -- the executor thread runs to completion
        and the shield re-raises ``CancelledError`` afterwards. Combined
        with :attr:`_write_lock`, this ensures that the single-writer
        assumption used by :meth:`_write_one_sync` (stat + rotate +
        append within one critical section) is never violated: the
        drain path in :meth:`_drain_on_shutdown` blocks on the same
        lock, so it cannot start its own executor call until the
        current write has landed (or raised).
        """
        line = (
            json.dumps(entry, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
            + b"\n"
        )
        loop = asyncio.get_running_loop()
        async with self._write_lock:
            future = loop.run_in_executor(None, self._write_one_sync, line)
            # Cancellation discipline: the outer task may be cancelled
            # while the executor is mid-write. ``asyncio.shield``
            # prevents the cancel from cancelling the inner future,
            # but it still propagates ``CancelledError`` out of the
            # outer ``await`` immediately -- which would release the
            # lock while the executor thread keeps running, breaking
            # the single-writer invariant that the stat+rotate+append
            # sequence relies on. Instead, loop on
            # ``asyncio.shield(future)``: on CancelledError, re-await
            # until the underlying future resolves. Only then do we
            # release the lock and propagate the cancel so the
            # run-loop's shutdown drain fires on a consistent
            # filesystem state.
            cancelled: Optional[asyncio.CancelledError] = None
            write_exc: Optional[BaseException] = None
            while True:
                try:
                    await asyncio.shield(future)
                    break
                except asyncio.CancelledError as exc:
                    cancelled = exc
                    continue
                except BaseException as exc:  # noqa: BLE001
                    # Executor raised (e.g. OSError from disk). The
                    # future is resolved; exit the loop.
                    write_exc = exc
                    break

            if write_exc is None:
                self.state.writes_ok += 1
            else:
                self.state.writes_failed += 1
                if isinstance(write_exc, OSError) and write_exc.errno in (
                    errno.ENOSPC,
                    errno.EIO,
                    errno.EDQUOT,
                ):
                    logger.error(
                        "audit writer hit %s; disabling further audit "
                        "writes for this server run",
                        errno.errorcode.get(write_exc.errno, write_exc.errno),
                    )
                    self.state.disk_full = True
                    # If we were also cancelled, propagate the cancel
                    # AFTER the fail-closed flag flips so shutdown
                    # code observes the post-write state.
                    if cancelled is not None:
                        raise cancelled
                    raise write_exc
                logger.error(
                    "audit write failed (non-fatal): %s",
                    write_exc.__class__.__name__,
                )

            # Finally, propagate any pending cancel AFTER the lock is
            # released (out of this ``async with``). Re-raising inside
            # the block is fine -- the context manager releases the
            # lock on exit regardless of how we leave.
            if cancelled is not None:
                raise cancelled

    async def run(self) -> None:
        """Main loop: drain ``queue`` until cancelled.

        Each iteration:

        1. Await next entry.
        2. Write it (executor).
        3. ``queue.task_done()`` for :meth:`asyncio.Queue.join`.

        On disk-full (ENOSPC/EIO), the loop breaks out of the inner
        write but keeps draining the queue so producers don't block on
        a full queue -- they just see ``disk_full=True`` via the
        decorator pre-check and refuse to queue new entries.
        """
        try:
            while True:
                entry = await self.queue.get()
                try:
                    if not self.state.disk_full:
                        try:
                            await self._write_one(entry)
                        except OSError:
                            # ENOSPC / EIO already set the disk_full flag.
                            # Drop the entry and keep draining so queue
                            # counters stay sane for tests.
                            pass
                    # When disk_full, we still consume entries off the
                    # queue to prevent producer blocking. The entries
                    # are lost, which is the point of the fail-closed
                    # posture -- producers refuse to queue in the first
                    # place via the decorator gate.
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            # Graceful shutdown: drain remaining entries with a short
            # timeout so we don't leak state. Best-effort; if disk_full
            # already fired, we just discard.
            await self._drain_on_shutdown()
            raise

    async def _drain_on_shutdown(self) -> None:
        """Flush queued entries on cancellation, bounded by
        :data:`SHUTDOWN_DRAIN_TIMEOUT_S`.

        The drain runs without ``await queue.get()`` (which would block
        forever on an empty queue); we peek via ``queue.qsize()`` and
        call ``get_nowait`` up to N times. A soft deadline keeps
        shutdown fast even if a stuck executor pushes write latency up.
        """
        deadline = time.monotonic() + SHUTDOWN_DRAIN_TIMEOUT_S
        while True:
            if self.queue.empty():
                return
            if time.monotonic() >= deadline:
                logger.warning(
                    "audit writer shutdown drain timed out with %d entries "
                    "remaining",
                    self.queue.qsize(),
                )
                return
            try:
                entry = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                if not self.state.disk_full:
                    try:
                        await self._write_one(entry)
                    except OSError:
                        pass
            finally:
                self.queue.task_done()


#: Max wall-clock seconds we spend draining the queue on shutdown.
#: Generous enough to land a few-hundred-entry burst, short enough that
#: a wedged executor can't block lifespan teardown for long.
SHUTDOWN_DRAIN_TIMEOUT_S: float = 2.0


def run_audit_writer(
    queue: "asyncio.Queue[dict[str, Any]]",
    *,
    world_root: Optional[str],
    state: Optional[AuditWriterState] = None,
    max_active_bytes: int = MAX_ACTIVE_BYTES,
    max_rotations: int = MAX_ROTATIONS,
) -> Awaitable[None]:
    """Factory that returns the writer-task coroutine.

    Kept as a factory rather than a module-level ``async def`` so tests
    can build writers with custom rotation bounds without a monkey-
    patch. The lifespan calls this and wraps the result in
    :func:`asyncio.create_task`.
    """
    writer = AuditWriter(
        queue,
        world_root=world_root,
        state=state,
        max_active_bytes=max_active_bytes,
        max_rotations=max_rotations,
    )
    return writer.run()


# ---------------------------------------------------------------------------
# The @audited decorator -- real implementation.
#
# Wraps async tool handlers so every invocation produces an audit entry
# (or returns ERR_AUDIT_DISK_FULL fail-closed when the writer has given
# up). Sync callables get a pass-through because there are no sync
# tools on the v0.1 surface -- but the shape stays compatible with the
# T6 stub contract which tests assert against.
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable[..., Any])


def _envelope_for_disk_full() -> dict[str, Any]:
    """Build the ERR_AUDIT_DISK_FULL envelope without importing errors.

    Inlined to avoid a circular-import shape (errors imports from
    ``_vendor``; envelope imports errors; tools import envelope+errors;
    we don't want audit.py to pull in the full chain just to handle
    the edge case). The shape is hand-assembled to match what
    :func:`alive_mcp.envelope.error` would produce for
    ``ERR_AUDIT_DISK_FULL``; a test asserts the two stay in sync.
    """
    from alive_mcp import envelope, errors  # local import avoids cycle.

    return envelope.error(errors.ERR_AUDIT_DISK_FULL)


def _extract_lifespan_context(args: Sequence[Any], kwargs: dict[str, Any]) -> Any:
    """Return the FastMCP lifespan context (our :class:`AppContext`) or None.

    Tool handlers receive a :class:`mcp.server.fastmcp.Context` as
    either the first positional arg or a ``ctx=`` kwarg. We probe both
    positions. If no context is available (tests that exercise the
    decorator directly against a plain function), we return None and
    the decorator skips the audit step.
    """
    ctx = None
    if args:
        ctx = args[0]
    if ctx is None:
        ctx = kwargs.get("ctx")
    if ctx is None:
        return None
    request_context = getattr(ctx, "request_context", None)
    if request_context is None:
        return None
    return getattr(request_context, "lifespan_context", None)


def _extract_session_id(args: Sequence[Any], kwargs: dict[str, Any]) -> Optional[str]:
    """Best-effort grab of the MCP session_id for the active request.

    The FastMCP :class:`Context` exposes ``.session_id`` lazily; in
    versions where the attribute is absent we fall back to None. The
    audit entry's ``session_id`` field is nullable exactly for this
    reason.
    """
    ctx = None
    if args:
        ctx = args[0]
    if ctx is None:
        ctx = kwargs.get("ctx")
    if ctx is None:
        return None
    try:
        raw = getattr(ctx, "session_id", None)
    except Exception:  # noqa: BLE001 -- opaque SDK attribute.
        return None
    return raw if isinstance(raw, str) else None


def _user_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``kwargs`` with ``ctx`` dropped.

    The Context is infrastructure, not a user argument -- logging it
    would leak an object with unbounded attributes (session, request
    handles) through the ``other`` summarizer branch.
    """
    return {k: v for k, v in kwargs.items() if k != "ctx"}


@overload
def audited(func: F) -> F: ...


@overload
def audited(
    *, tool_name: Optional[str] = ...
) -> Callable[[F], F]: ...


def audited(
    func: Optional[F] = None,
    *,
    tool_name: Optional[str] = None,
) -> Union[F, Callable[[F], F]]:
    """Decorator that wires a tool handler into the audit pipeline.

    Shape (locked by T6's stub, tested in test_tools_walnut):

    * Accepts ``@audited`` and ``@audited(tool_name=...)``.
    * Preserves the wrapped function's ``__name__``, ``__doc__``,
      ``__module__``, signature via :func:`functools.wraps`.
    * Safe on both sync and async callables; sync wrapper is pure
      pass-through because v0.1 has no sync tools on the wire.
    * Exposes ``__alive_tool_name__`` attribute for the override name.
    * NEVER raises synchronously; audit failures do not block the tool.

    Behavior added in T12 (for async callables only):

    1. Read :class:`AppContext` from the FastMCP Context.
    2. If the writer reports ``disk_full``, return the
       ``ERR_AUDIT_DISK_FULL`` envelope WITHOUT running the tool body
       (fail-closed).
    3. Otherwise run the tool, compute duration, build the entry, and
       attempt a ``put_nowait`` onto the queue. A full queue drops the
       entry with a WARNING (we prefer a dropped audit record over
       blocking the tool's response path indefinitely -- back-pressure
       is represented by the fail-closed path above when writes stall
       long enough to trip disk_full).
    4. Errors in the audit path are swallowed so the tool's response
       is never affected.
    """

    def _decorate(target: F) -> F:
        recorded_name = tool_name if tool_name is not None else target.__name__

        # ``inspect.iscoroutinefunction`` over ``asyncio.iscoroutinefunction``
        # -- the asyncio variant is deprecated on 3.14+.
        if inspect.iscoroutinefunction(target):
            @functools.wraps(target)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                lifespan_context = _extract_lifespan_context(args, kwargs)

                # Pre-check: fail-closed on disk full. We read via
                # AppContext because that's where the writer publishes
                # its state; a None lifespan_context (tests) skips.
                writer_state = getattr(
                    lifespan_context, "audit_writer_state", None
                )
                if writer_state is not None and writer_state.disk_full:
                    return _envelope_for_disk_full()

                start = time.monotonic()
                try:
                    result = await target(*args, **kwargs)
                finally:
                    duration_ms = int((time.monotonic() - start) * 1000)

                # Audit emission. We use ``await queue.put(entry)``
                # (blocking back-pressure) instead of ``put_nowait``
                # because dropping entries on a full queue would
                # violate the "every tool call produces a JSONL line"
                # acceptance criterion and undermine the forensics
                # posture -- a saturated queue is the one signal that
                # the writer is falling behind, and the producer
                # slowing down is the correct response. The queue cap
                # (``AUDIT_QUEUE_MAXSIZE = 1024``) is sized so normal
                # bursts don't block; chronic blocking means the
                # writer is wedged, at which point the ``disk_full``
                # fail-closed path below will trip on the next write
                # attempt and shut producers off cleanly.
                #
                # Any exception inside the audit path is logged and
                # swallowed so the tool response is never affected.
                try:
                    queue = getattr(lifespan_context, "audit_queue", None)
                    if queue is not None:
                        entry = build_entry(
                            tool=recorded_name,
                            args=_user_kwargs(kwargs),
                            envelope=result,
                            duration_ms=duration_ms,
                            session_id=_extract_session_id(args, kwargs),
                        )
                        await queue.put(entry)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "audit decorator failure (tool response unaffected)"
                    )
                return result

            _async_wrapper.__alive_tool_name__ = recorded_name  # type: ignore[attr-defined]
            return _async_wrapper  # type: ignore[return-value]

        # Sync tools are not part of the v0.1 surface, but the
        # decorator contract requires the sync path to keep working.
        @functools.wraps(target)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return target(*args, **kwargs)

        _sync_wrapper.__alive_tool_name__ = recorded_name  # type: ignore[attr-defined]
        return _sync_wrapper  # type: ignore[return-value]

    if func is not None:
        return _decorate(func)
    return _decorate


# ---------------------------------------------------------------------------
# Resource-read audit hook.
#
# Resources use FastMCP's low-level ``read_resource`` handler rather
# than the tool-handler decorator path, so the ``@audited`` wrapper
# doesn't cover them. :func:`emit_resource_read` is the parallel seam
# resource-read handlers call to produce audit entries with the same
# privacy posture (hashed args by default, counts instead of bodies).
#
# Keeping the emission explicit at the resource-handler call site --
# rather than monkeypatching the low-level SDK -- means auditing
# stays visible in the code the human reads. The shape is identical
# to tool-produced entries so downstream log analysis does not have
# to special-case resource reads.
# ---------------------------------------------------------------------------


async def emit_resource_read(
    lifespan_context: Any,
    *,
    uri: str,
    walnut: Optional[str],
    file: Optional[str],
    content_bytes: int,
    duration_ms: int,
    error_code: Optional[str] = None,
    session_id: Optional[str] = None,
) -> bool:
    """Queue one audit entry for a resource-read request.

    Returns True when the entry was queued (or deliberately skipped for
    a soft reason), False when the caller should FAIL CLOSED. Callers
    (the resource read handler) check the return value and refuse the
    read when it is False, mirroring the ``@audited`` decorator's
    fail-closed disk-full path.

    Arguments:
        lifespan_context: The :class:`AppContext` from the current
            request (``ctx.request_context.lifespan_context``). May be
            ``None`` in tests; the function is a no-op-returns-True
            in that case.
        uri: The full ``alive://`` URI the client requested. Hashed
            in the ``args`` block -- the audit log records the fact
            that a read happened, not the exact walnut+file pair.
        walnut: POSIX walnut path parsed out of the URI, or None on
            parse failure. Hashed unless whitelisted (same policy as
            tool args).
        file: Kernel file stem (``key``/``log``/``insights``/``now``)
            or None. Logged verbatim -- it's an enum-like value from
            a fixed small set, not sensitive.
        content_bytes: Byte length of the content body returned to
            the client, or 0 on error. Logged verbatim so ops can
            track aggregate read volume without touching bodies.
        duration_ms: How long the read took.
        error_code: None on success, short code on failure
            (e.g. ``"INVALID_PARAMS"``).
        session_id: MCP session ID if known.
    """
    if lifespan_context is None:
        return True
    writer_state = getattr(lifespan_context, "audit_writer_state", None)
    if writer_state is not None and writer_state.disk_full:
        return False

    queue = getattr(lifespan_context, "audit_queue", None)
    if queue is None:
        return True

    # Build a tool-shaped entry with the resource name as the "tool".
    # Aligning shapes means downstream greps for a specific walnut's
    # activity hit both tool calls and resource reads uniformly.
    whitelist = _load_whitelist()
    args_summary: dict[str, dict[str, Any]] = {
        "uri": _summarize_value(uri, whitelist=whitelist, allow_whitelist=False),
    }
    if walnut is not None:
        args_summary["walnut"] = _summarize_value(
            walnut, whitelist=whitelist, allow_whitelist=True
        )
    if file is not None:
        args_summary["file"] = {"type": "str", "len": len(file), "val": file}

    entry: dict[str, Any] = {
        "ts": _iso_utc_now(),
        "session_id": session_id,
        "tool": "resource.read",
        "args": args_summary,
        "result_status": "error" if error_code is not None else "ok",
        "result_counts": {"bytes": int(content_bytes)},
        "duration_ms": duration_ms,
        "error_code": error_code,
    }
    try:
        await queue.put(entry)
    except Exception:  # noqa: BLE001
        logger.exception(
            "audit emit_resource_read failure (read proceeding)"
        )
    return True


__all__ = [
    "AUDIT_FILE_MODE",
    "AUDIT_DIR_MODE",
    "AUDIT_RELPATH",
    "AuditWriter",
    "AuditWriterState",
    "ENV_PUBLIC_WALNUT_PATHS",
    "HASH_PREFIX_CHARS",
    "MAX_ACTIVE_BYTES",
    "MAX_ROTATIONS",
    "SHUTDOWN_DRAIN_TIMEOUT_S",
    "audited",
    "build_entry",
    "emit_resource_read",
    "run_audit_writer",
    "summarize_args",
]
