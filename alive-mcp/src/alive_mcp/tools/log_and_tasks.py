"""Log + task read tools (fn-10-60k.9 / T9).

Two tools, both read-only, both annotated
``ToolAnnotations(readOnlyHint=True, destructiveHint=False,
openWorldHint=False, idempotentHint=True)``:

* :func:`read_log` -- paginated entry-oriented access to
  ``_kernel/log.md`` with automatic spanning into
  ``_kernel/history/chapter-NN.md`` chapter files when the requested
  offset reaches beyond the active log. Unit of pagination is ENTRIES
  (one ``## <ISO-8601>`` heading = one entry), not bytes or lines.
  Entries are newest-first (the log is prepend-only on disk so file
  order equals age order); chapters are consumed in descending
  chapter number (newest chapter first).
* :func:`list_tasks` -- walnut- or bundle-scoped inventory of tasks
  from ``tasks.json`` files. When ``bundle`` is ``None`` the tool
  enumerates every ``tasks.json`` under the walnut via
  :func:`alive_mcp._vendor._pure.tasks_pure._all_task_files` (which
  honors nested-walnut boundaries) and runs each hit through the
  :func:`alive_mcp._vendor._pure.tasks_pure._read_tasks_json`
  parser; the extra per-file pass lets us apply an
  :func:`alive_mcp.paths.is_inside` containment gate before the
  parser opens anything, which
  :func:`~alive_mcp._vendor._pure.tasks_pure._collect_all_tasks`
  does not. When ``bundle`` is supplied ONLY that bundle's top-
  level ``tasks.json`` is read -- sub-bundle task files are NOT
  included per the frozen v0.1 contract ("scoped to that bundle's
  ``tasks.json``" -- singular). Returns the merged list plus
  counts bucketed by priority/status exactly as the summary tool
  does.

Frozen contract (from the epic spec, reproduced so reviewers don't
need to cross-reference the task file):

Entry definition (log.md + chapter files)
-----------------------------------------
* An entry STARTS at a line matching the regex
  ``^## \\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}`` (ISO-8601 timestamp
  heading). The tail after the timestamp carries whatever label the
  session emitted ("-- squirrel:abc", etc.) -- we parse the squirrel
  id from it.
* The body extends FORWARD until the next matching heading OR a
  single-line ``---`` separator OR EOF, whichever comes first.
* Single-line ``---`` acts as a boundary marker between entries and
  is NOT part of the body.
* YAML frontmatter at the top of the file (delimited by
  ``---\\n...\\n---\\n``) is stripped before parsing entries. The
  frontmatter's closing ``---`` is NOT treated as an entry boundary.
* The trailing ``signed: squirrel:<id>`` line IS part of the entry
  body (we preserve it verbatim -- it's the attribution seal, not a
  boundary marker).

Ordering
--------
Newest-first. The log is prepend-only on disk so file order IS age
order (top = newest). ``offset=0`` returns the newest entry. When a
chapter boundary is crossed, we continue from chapter-``N`` (highest
number = newest chapter) and descend.

Pagination
----------
``offset`` skips entries (newest-first); ``limit`` caps entries
returned. When ``offset + limit`` exceeds the active log's entry count,
the tool auto-spans into the highest-numbered chapter file, then the
next-highest, etc., until ``limit`` is satisfied or all chapters are
exhausted. ``chapter_boundary_crossed`` is set to ``True`` when at
least one chapter entry appears in the returned window.

``next_offset = offset + len(returned_entries)`` when more entries
remain somewhere; ``None`` when the tool has exhausted both the
active log and every chapter.

Response shape
--------------
``read_log`` returns an envelope whose ``structuredContent`` is::

    {
      "entries": [{timestamp, walnut, squirrel_id, body, signed}, ...],
      "total_entries": int,             # combined log + chapters
      "total_chapters": int,
      "next_offset": int | None,
      "chapter_boundary_crossed": bool,
    }

``list_tasks`` returns::

    {
      "tasks": [ <raw tasks.json task dicts> ],
      "counts": {"urgent": int, "active": int, "todo": int,
                 "blocked": int, "done": int},
    }

Why a dedicated :func:`parse_log_entries` helper
------------------------------------------------
The vendored :func:`alive_mcp._vendor._pure.project_pure.parse_log`
is the *single-entry projection* used by the session-resume path: it
takes ``_kernel/log.md`` and synthesizes a `{context, phase, next,
bundle, squirrel}` dict from only the newest entry. Its output shape
doesn't match the list-of-entries contract we need here. Rather than
modify the vendored file (locked by the vendoring policy), we add a
local :func:`parse_log_entries` that returns the full entry list with
timestamp + squirrel_id + body + signed trailer.

Error posture
-------------
* ``ERR_NO_WORLD`` -- lifespan has not resolved a World yet.
* ``ERR_WALNUT_NOT_FOUND`` -- walnut path does not resolve (fuzzy
  suggestions layered on via the shared walnut error envelope).
* ``ERR_BUNDLE_NOT_FOUND`` -- bundle path does not resolve under the
  walnut (uses the shared bundle error envelope).
* ``ERR_PATH_ESCAPE`` -- walnut or bundle path would leave the World
  root after realpath resolution.
* ``ERR_PERMISSION_DENIED`` -- OS denies read on the log or a
  tasks.json file (the actual file path is redacted).
* A walnut with NO log and NO chapters is a legitimate fresh-walnut
  state -- we return ``{entries: [], total_entries: 0,
  total_chapters: 0, next_offset: None,
  chapter_boundary_crossed: False}`` rather than surfacing an error.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from alive_mcp import envelope, errors
from alive_mcp._vendor._pure import tasks_pure
from alive_mcp.paths import is_inside
from alive_mcp.tools._audit_stub import audited
from alive_mcp.tools.bundle import (
    _bundle_not_found_envelope,
    _resolve_bundle,
)
from alive_mcp.tools.walnut import (
    _kernel_file_in_world,
    _resolve_walnut,
    _walnut_not_found_envelope,
)

logger = logging.getLogger("alive_mcp.tools.log_and_tasks")


# ---------------------------------------------------------------------------
# Constants + regexes.
# ---------------------------------------------------------------------------

#: Default/maximum entry budget for :func:`read_log`. 50 is generous for
#: an LLM context while still keeping the payload bounded. We clamp any
#: caller-supplied limit to the cap so a pathological ``limit=1_000_000``
#: doesn't force the whole log into one response.
READ_LOG_DEFAULT_LIMIT = 20
READ_LOG_LIMIT_CAP = 100

#: Entry heading: ``## YYYY-MM-DDTHH:MM:SS`` at line start, optionally
#: followed by anything on the rest of the line (e.g. ``-- squirrel:abc``
#: or a trailing label). Matches ONLY at line start so a mid-body ``##``
#: heading inside an entry body won't be mis-identified as the next
#: entry. Second-granularity ISO-8601 is the frozen shape.
_ENTRY_HEADING_RE = re.compile(
    r"^## (?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?P<rest>[^\n]*)$",
    re.MULTILINE,
)

#: YAML frontmatter block at the TOP of a log/chapter file. Non-greedy
#: body so the FIRST closing ``---`` fence wins. The trailing newline
#: after the closing fence is optional (``(?:\n|\Z)``) so a file whose
#: frontmatter runs to EOF without a final newline still gets stripped
#: -- otherwise the unterminated file would leave the closing ``---``
#: in body text and the first entry heading would be invisible.
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", re.DOTALL
)

#: Entry-boundary divider -- a line that is exactly ``---`` (optional
#: surrounding whitespace, no other content). Unlike the frontmatter
#: block, this is a single-line marker that SEPARATES entries. We match
#: it at a multiline boundary so it never collides with a body line that
#: happens to contain three dashes inline.
_DIVIDER_RE = re.compile(r"^---\s*$", re.MULTILINE)

#: Squirrel id extractor for the entry heading. Accepts
#: ``squirrel:<id>`` or ``squirrel <id>`` after any separator. The id is
#: a short hex fingerprint (8-16 hex chars typical in the wild; we
#: accept 6-32 to avoid over-fitting to current session-id lengths).
_SQUIRREL_RE = re.compile(
    r"squirrel[:\s]+([a-f0-9]{6,32})", re.IGNORECASE
)

#: Chapter filename: ``chapter-<digits>.md`` under ``_kernel/history/``.
#: The digits are the chapter number; newer chapters are higher numbers,
#: so descending sort = newest-first.
_CHAPTER_FILE_RE = re.compile(r"^chapter-(\d+)\.md$")

#: Signed trailer detector -- line starts with ``signed:`` (case-
#: insensitive). We identify the signed line inside an entry body for
#: the ``signed`` field; the body itself still contains the line verbatim
#: per the frozen contract.
_SIGNED_LINE_RE = re.compile(
    r"^\s*signed\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE
)


# ---------------------------------------------------------------------------
# Entry extraction.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogEntry:
    """Parsed log entry as returned by :func:`parse_log_entries`.

    ``timestamp`` is the ISO-8601 heading value (seconds precision).
    ``walnut`` is the walnut path (not the heading -- injected by the
    caller that knows which walnut we're serving). ``squirrel_id`` is
    the short hex token from the heading or the signed trailer;
    ``None`` when neither carries one. ``body`` is the verbatim entry
    body WITHOUT the leading ``## ...`` heading (the heading's info is
    already captured in ``timestamp`` / ``squirrel_id``). ``signed`` is
    the full signed value (e.g. ``squirrel:abc123``) or ``None``.

    Frozen + slotted: entries are built once per parse and never
    mutated, matching the read-only tool posture and keeping the
    per-entry memory footprint tight for large logs.
    """

    timestamp: str
    walnut: str
    squirrel_id: Optional[str]
    body: str
    signed: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "walnut": self.walnut,
            "squirrel_id": self.squirrel_id,
            "body": self.body,
            "signed": self.signed,
        }


def _strip_frontmatter(text: str) -> str:
    """Return ``text`` with a leading YAML frontmatter block removed.

    Only the frontmatter at the very top of the file is stripped --
    a mid-body ``---``/``---`` pair inside an entry body is NOT a
    frontmatter block and must stay put. The regex is anchored with
    ``\\A`` so it only fires on an opening-of-file match.
    """
    m = _FRONTMATTER_RE.match(text)
    if m:
        return text[m.end():]
    return text


def _clip_at_divider(body_text: str) -> str:
    """Trim ``body_text`` at the first entry-boundary ``---`` marker.

    Used when computing an entry's body: after the heading, the body
    extends until either the next heading (handled by the caller's
    slice) or the first ``---``-only line (handled here). Anything
    after that marker belongs to the NEXT entry.

    We match only a single-line divider (``^---\\s*$``) so three
    dashes inline (e.g. inside a quoted code block) don't get
    treated as boundaries.

    The divider line is excluded from the body. We ``rstrip`` ONLY
    newline characters so that trailing spaces or tabs on the last
    content line survive (keeping the body verbatim). Trailing
    blank lines between the last content line and the divider are
    folded into the newline strip naturally because the divider
    itself starts after them.
    """
    m = _DIVIDER_RE.search(body_text)
    if m is None:
        return body_text
    return body_text[: m.start()].rstrip("\n")


def _extract_signed(body: str) -> Optional[str]:
    """Return the ``signed:`` trailer value, or ``None`` when absent.

    If an entry body contains multiple ``signed:`` lines (rare, but
    possible when an entry embeds a quote or template that carries a
    seal-shaped line mid-body), the LAST one is the trailer -- the
    attribution seal that terminates the entry. ``finditer`` + last
    match wins, rather than ``search`` which would surface the
    topmost mention.

    The signed line is preserved in the entry body verbatim (per
    the frozen contract -- the seal belongs to the entry). We still
    surface the token separately so clients can assert attribution
    without re-parsing the body.
    """
    last: Optional[re.Match[str]] = None
    for m in _SIGNED_LINE_RE.finditer(body):
        last = m
    if last is None:
        return None
    return last.group(1).strip()


@dataclass(frozen=True, slots=True)
class _EntrySlot:
    """Internal: an entry heading + the byte offsets for its body.

    Produced by :func:`_index_log_file` without materializing the
    body. ``body_start`` / ``body_end`` are character offsets into
    the post-frontmatter body text. A second, lazy pass slices each
    requested body only when the pagination window actually needs
    it, keeping ``read_log(offset=0, limit=5)`` linear in the number
    of HEADINGS (cheap regex scan) rather than linear in the total
    body byte count.
    """

    timestamp: str
    heading_rest: str
    body_start: int
    body_end: int


def _index_log_file(path: str) -> Tuple[str, List[_EntrySlot]]:
    """Return ``(post_frontmatter_text, entry_slots)`` for ``path``.

    Cheap pass: reads the file, strips the frontmatter, runs the
    heading regex. Does NOT slice bodies -- callers build entry
    bodies lazily via :func:`_materialize_entry`. Empty / missing
    files return ``("", [])`` so callers can treat "no entries"
    uniformly. TOCTOU (``FileNotFoundError`` between ``isfile`` and
    ``open``) is folded into the empty-return branch; other
    ``OSError`` subclasses (``PermissionError``, ``IsADirectoryError``)
    and ``UnicodeDecodeError`` propagate so :func:`read_log` can
    map them to ``ERR_PERMISSION_DENIED``.
    """
    if not os.path.isfile(path):
        return "", []
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return "", []

    body_text = _strip_frontmatter(content)
    matches = list(_ENTRY_HEADING_RE.finditer(body_text))
    if not matches:
        return body_text, []

    slots: List[_EntrySlot] = []
    for idx, m in enumerate(matches):
        body_start = m.end()
        # Leading newline after the heading is always shaved off so
        # the body starts at the first real character of content.
        if (
            body_start < len(body_text)
            and body_text[body_start] == "\n"
        ):
            body_start += 1
        body_end = (
            matches[idx + 1].start() if idx + 1 < len(matches) else len(body_text)
        )
        slots.append(
            _EntrySlot(
                timestamp=m.group("timestamp"),
                heading_rest=m.group("rest") or "",
                body_start=body_start,
                body_end=body_end,
            )
        )
    return body_text, slots


def _materialize_entry(
    slot: _EntrySlot, body_text: str, walnut: str
) -> LogEntry:
    """Build a :class:`LogEntry` from a slot + the parent file's text.

    This is the ONLY place we slice bytes into an entry body.
    :func:`read_log` calls this just for the window it returns, so
    a caller asking for 5 entries out of a 1000-entry log performs
    5 slices, not 1000.

    squirrel_id resolution is deliberately ordered to prefer signed
    truth over body coincidence:

    1. heading rest (``## <ts> -- squirrel:abc``) -- most
       authoritative, present on every well-formed entry.
    2. ``signed:`` trailer -- the attribution seal. Picking this
       over a raw body scan avoids the failure mode where an entry
       quotes another session's id mid-body (e.g. "decision made
       with squirrel:other123") and we'd mis-attribute the entry.
    3. Loose body scan -- last-resort fallback for malformed
       entries missing both the heading label and the signed
       trailer. Still lower-case-normalized.
    """
    raw_body = body_text[slot.body_start : slot.body_end]
    entry_body = _clip_at_divider(raw_body).rstrip("\n")
    signed = _extract_signed(entry_body)

    squirrel_id: Optional[str] = None
    sq_from_heading = _SQUIRREL_RE.search(slot.heading_rest)
    if sq_from_heading:
        squirrel_id = sq_from_heading.group(1).lower()
    elif signed is not None:
        sq_from_signed = _SQUIRREL_RE.search(signed)
        if sq_from_signed:
            squirrel_id = sq_from_signed.group(1).lower()
    if squirrel_id is None:
        sq_from_body = _SQUIRREL_RE.search(entry_body)
        if sq_from_body:
            squirrel_id = sq_from_body.group(1).lower()

    return LogEntry(
        timestamp=slot.timestamp,
        walnut=walnut,
        squirrel_id=squirrel_id,
        body=entry_body,
        signed=signed,
    )


def parse_log_entries(path: str, walnut: str) -> List[LogEntry]:
    """Extract the full entry list from a log or chapter file.

    Convenience wrapper that indexes the file and materializes every
    slot. Used by unit tests and callers that want the whole list;
    :func:`_collect_window` takes a streaming path that avoids
    building all bodies when the pagination window is small.
    """
    body_text, slots = _index_log_file(path)
    return [_materialize_entry(s, body_text, walnut) for s in slots]


# ---------------------------------------------------------------------------
# Chapter discovery.
# ---------------------------------------------------------------------------


def _list_chapter_files(
    world_root: str, walnut_abs: str
) -> List[Tuple[int, str]]:
    """Return ``[(chapter_number, abs_path), ...]`` sorted DESCENDING.

    Each entry's abs_path has been validated as in-world (the chapter
    file's realpath stays inside the World root). Chapters whose
    filename doesn't match ``chapter-<digits>.md`` are silently
    skipped -- the directory may contain README-style docs or draft
    chapters that don't count toward pagination.

    Returns an empty list when ``_kernel/history/`` doesn't exist or
    isn't a directory. Permission errors on the directory itself are
    logged at WARNING and treated as "no chapters".

    Descending sort (``reverse=True``) is load-bearing: chapters
    contain older entries, so the HIGHEST-numbered chapter holds the
    most recent pre-rollover entries. The caller consumes chapters
    in the returned order.
    """
    # ``_kernel_file_in_world`` prepends ``_kernel/`` itself, so paths
    # we pass are relative to the kernel directory (e.g.
    # ``history/chapter-02.md``). The on-disk check here is against
    # the full ``<walnut>/_kernel/history/`` directory so we can
    # os.listdir it.
    history_dir = os.path.join(walnut_abs, "_kernel", "history")
    if not os.path.isdir(history_dir):
        return []
    # Containment: a symlinked history/ whose realpath escapes the
    # World is a kernel-file-escape. Drop the whole directory. This
    # mirrors the posture of :func:`_kernel_file_in_world`: a
    # symlinked kernel path whose target sits outside the World is
    # treated as "not present".
    if not is_inside(world_root, history_dir):
        logger.warning(
            "history directory escapes World via symlink; skipping "
            "chapter pagination for walnut"
        )
        return []
    try:
        entries = os.listdir(history_dir)
    except (OSError, PermissionError) as exc:
        logger.warning(
            "read_log: history directory unreadable: %s", exc
        )
        return []

    found: List[Tuple[int, str]] = []
    for name in entries:
        match = _CHAPTER_FILE_RE.match(name)
        if match is None:
            continue
        # Each chapter file goes through the same in-world gate the
        # active log does. A symlinked ``chapter-04.md`` whose
        # realpath escapes the World is dropped here. ``history/<name>``
        # is relative to ``_kernel/`` because
        # :func:`_kernel_file_in_world` prepends that prefix itself.
        abs_path = _kernel_file_in_world(
            world_root,
            walnut_abs,
            "history/{}".format(name),
        )
        if abs_path is None:
            logger.warning(
                "chapter file %r escapes World via symlink; skipping",
                name,
            )
            continue
        try:
            number = int(match.group(1))
        except ValueError:  # pragma: no cover -- regex already matched
            continue
        found.append((number, abs_path))

    found.sort(reverse=True)  # newest chapter (highest number) first.
    return found


# ---------------------------------------------------------------------------
# Log assembly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _LogSources:
    """Internal: resolved entry-source paths for a walnut.

    ``active_log`` is the current ``_kernel/log.md`` (or ``None`` if
    absent / symlink escape). ``chapters`` is the descending chapter
    list from :func:`_list_chapter_files`. Together they form the
    source ordering: active log entries first (newest-first within
    the file), then chapter entries in descending chapter number.
    """

    active_log: Optional[str]
    chapters: Tuple[Tuple[int, str], ...]


def _resolve_log_sources(
    world_root: str, walnut_abs: str
) -> _LogSources:
    """Locate the active log + chapter files for ``walnut_abs``."""
    active = _kernel_file_in_world(world_root, walnut_abs, "log.md")
    chapters = tuple(_list_chapter_files(world_root, walnut_abs))
    return _LogSources(active_log=active, chapters=chapters)


def _collect_window(
    sources: _LogSources,
    walnut: str,
    offset: int,
    limit: int,
) -> Tuple[List[LogEntry], int, bool]:
    """Return ``(entries, total_entries_seen, chapter_crossed)``.

    Streaming posture: for each source we run the cheap heading
    regex (:func:`_index_log_file`) to get a slot list + file body,
    then materialize ONLY the slots that fall inside the requested
    pagination window. A client asking for five entries out of a
    thousand-entry log does five body slices, not a thousand.

    ``total_entries_seen`` is the total number of entries
    discovered across every source read -- needed so the caller
    decides whether ``next_offset`` is ``None`` (reached EOF on the
    last chapter) or an integer (more entries remain we didn't
    buffer). We keep the heading regex running after the window
    fills because the heading pass is cheap; only body slicing is
    gated on window membership.

    Error propagation
    -----------------
    Read / decode failures (``PermissionError`` and other
    ``OSError`` subclasses, ``UnicodeDecodeError``) are DELIBERATELY
    propagated to the caller. :func:`read_log` catches them at the
    tool boundary and maps to ``ERR_PERMISSION_DENIED``.
    ``FileNotFoundError`` specifically is swallowed inside
    :func:`_index_log_file` (TOCTOU tolerance for rotated files) so
    this loop never sees it.
    """
    buffered: List[LogEntry] = []
    total = 0
    chapter_crossed = False

    window_start = offset
    window_end = offset + limit

    def _consume(path: str, is_chapter: bool) -> None:
        nonlocal total, chapter_crossed
        body_text, slots = _index_log_file(path)
        for slot in slots:
            global_idx = total
            total += 1
            if global_idx < window_start or global_idx >= window_end:
                continue
            buffered.append(_materialize_entry(slot, body_text, walnut))
            if is_chapter:
                chapter_crossed = True

    # Active log first -- its entries are globally newest. Chapter
    # files follow, descending chapter number (newer chapter = more
    # recent history, consumed first).
    if sources.active_log is not None:
        _consume(sources.active_log, is_chapter=False)
    for _chapter_num, chapter_path in sources.chapters:
        _consume(chapter_path, is_chapter=True)

    return buffered, total, chapter_crossed


# ---------------------------------------------------------------------------
# Task counting.
# ---------------------------------------------------------------------------


def _task_counts(tasks: List[Dict[str, Any]]) -> Dict[str, int]:
    """Bucket tasks by priority/status.

    Mirrors the counting rule used in
    :func:`tasks_pure.summary_from_walnut` (and the bundle tool's
    derived counts): ``urgent`` counts tasks with
    ``priority == "urgent"`` regardless of status; the other four
    buckets count by ``status`` exclusively.

    A task with both ``priority == "urgent"`` and ``status ==
    "active"`` is counted in BOTH ``urgent`` and ``active`` -- that's
    the established convention in the vendored summary path, not a
    bug. A task whose status is none of the four recognized values
    contributes to no bucket (intentional: bad schema data is
    ignored, not coerced).
    """
    counts = {"urgent": 0, "active": 0, "todo": 0, "blocked": 0, "done": 0}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        priority = t.get("priority", "todo")
        status = t.get("status", "todo")
        if priority == "urgent":
            counts["urgent"] += 1
        if status == "active":
            counts["active"] += 1
        elif status == "todo":
            counts["todo"] += 1
        elif status == "blocked":
            counts["blocked"] += 1
        elif status == "done":
            counts["done"] += 1
    return counts


def _collect_bundle_tasks(
    world_root: str, bundle_abs: str
) -> List[Dict[str, Any]]:
    """Return tasks from ``<bundle_abs>/tasks.json`` only.

    The frozen spec for ``list_tasks(bundle=...)`` reads "scoped to
    that bundle's ``tasks.json``" -- singular. We DO NOT recurse
    into nested bundles or directories; a bundle that happens to
    contain another bundle's ``tasks.json`` (sub-bundle layout)
    still returns only the top bundle's own tasks here. Callers
    that want sub-bundle tasks address the sub-bundle directly.

    Containment gate: the ``tasks.json`` path is realpath-checked
    against the World root before the parser opens it. A symlinked
    ``tasks.json`` whose realpath escapes the World is dropped
    silently (matching the posture of :func:`_safe_read_manifest`
    in the bundle tool).

    Missing file -> ``[]`` (legitimate empty-bundle state).
    :class:`KernelFileError` / :class:`OSError` propagate so the
    tool layer can map them to ``ERR_PERMISSION_DENIED``.
    """
    tasks_file = os.path.join(bundle_abs, "tasks.json")
    if not os.path.isfile(tasks_file):
        return []
    if not is_inside(world_root, tasks_file):
        logger.warning(
            "tasks.json at %r escapes World via symlink; dropping",
            tasks_file,
        )
        return []
    data = tasks_pure._read_tasks_json(tasks_file)
    if data is None:
        return []
    return list(data.get("tasks", []))


def _collect_walnut_tasks(
    world_root: str, walnut_abs: str
) -> List[Dict[str, Any]]:
    """Return tasks from every ``tasks.json`` under the walnut.

    Uses :func:`tasks_pure._all_task_files` to enumerate task files
    (this honors nested-walnut boundaries so a parent walnut never
    scans into child walnuts). Each file is then containment-gated
    (``is_inside``) before the parser opens it -- a symlinked
    ``tasks.json`` whose realpath escapes the World is dropped.

    Exceptions from the vendored parser (``KernelFileError`` on
    permission / I/O failure) and from ``os.walk`` (``OSError``) are
    DELIBERATELY propagated. The tool layer catches both and maps to
    ``ERR_PERMISSION_DENIED``. Swallowing them here would silently
    return "no tasks" for an unreadable walnut, masking real
    operational problems from the client.
    """
    task_files = tasks_pure._all_task_files(walnut_abs)
    tasks: List[Dict[str, Any]] = []
    for tf in task_files:
        if not is_inside(world_root, tf):
            logger.warning(
                "tasks.json at %r escapes World via symlink; dropping",
                tf,
            )
            continue
        data = tasks_pure._read_tasks_json(tf)
        if data is None:
            continue
        tasks.extend(data.get("tasks", []))
    return tasks


# ---------------------------------------------------------------------------
# App-context accessor.
# ---------------------------------------------------------------------------


def _get_world_root(ctx: Context) -> Optional[str]:
    """Return the resolved World root, or None if not yet resolved.

    Duplicated in each tool module (see walnut/bundle/search) so no
    tool module has to reach into a sibling for a private helper.
    """
    lifespan = getattr(ctx.request_context, "lifespan_context", None)
    if lifespan is None:
        return None
    return getattr(lifespan, "world_root", None)


# ---------------------------------------------------------------------------
# Tools.
# ---------------------------------------------------------------------------


@audited
async def read_log(
    ctx: Context,
    walnut: str,
    offset: int = 0,
    limit: int = READ_LOG_DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """Return a paginated window of log entries for ``walnut``.

    Unit: ENTRIES (one ``## <ISO-8601>`` heading = one entry), not
    bytes or lines. Ordering is newest-first (log is prepend-only;
    file order equals age order). When ``offset + limit`` extends
    past the active log's entry count, the tool auto-spans into
    ``_kernel/history/chapter-NN.md`` files in descending chapter
    number. ``chapter_boundary_crossed`` is True when at least one
    returned entry came from a chapter.

    Parameters mirror the spec exactly. ``limit`` is clamped to
    :data:`READ_LOG_LIMIT_CAP`; non-positive limits degrade to the
    default. Negative ``offset`` is treated as 0. Out-of-range
    offsets return an empty window with ``next_offset=None``.
    """
    world_root = _get_world_root(ctx)
    if world_root is None:
        return envelope.error(errors.ERR_NO_WORLD)

    try:
        walnut_abs = _resolve_walnut(world_root, walnut)
    except errors.PathEscapeError:
        return envelope.error(errors.ERR_PATH_ESCAPE)
    except errors.WalnutNotFoundError:
        return _walnut_not_found_envelope(world_root, walnut)

    # Clamp pagination. Defensive: FastMCP's schema layer coerces
    # types but doesn't enforce bounds.
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = READ_LOG_DEFAULT_LIMIT
    elif limit > READ_LOG_LIMIT_CAP:
        limit = READ_LOG_LIMIT_CAP

    sources = _resolve_log_sources(world_root, walnut_abs)

    # Probe permission on EVERY resolved source (active log +
    # chapters) BEFORE parsing. A chapter whose mode blocks read is
    # just as fatal as a locked active log -- it would break
    # chapter-spanning pagination by silently skipping or by later
    # raising mid-stream. Missing log (``sources.active_log is
    # None``) stays a non-error (fresh walnut). ``os.R_OK`` is a
    # cheap stat-level check; the defense-in-depth
    # PermissionError try/except around :func:`_collect_window`
    # covers the TOCTOU race where perms flip between the probe
    # and the parser's open.
    sources_to_probe: List[str] = []
    if sources.active_log is not None:
        sources_to_probe.append(sources.active_log)
    sources_to_probe.extend(path for _num, path in sources.chapters)
    for src_path in sources_to_probe:
        if not os.access(src_path, os.R_OK):
            return envelope.error(
                errors.ERR_PERMISSION_DENIED,
                walnut=walnut,
                file="log",
            )

    try:
        entries, total_entries, chapter_crossed = _collect_window(
            sources, walnut, offset, limit
        )
    except PermissionError as exc:
        logger.warning("read_log denied for %r: %s", walnut, exc)
        return envelope.error(
            errors.ERR_PERMISSION_DENIED,
            walnut=walnut,
            file="log",
        )
    except UnicodeDecodeError as exc:
        # A corrupt / non-UTF8 log is not a permission problem per
        # se, but the most actionable answer from the client's
        # perspective is still ERR_PERMISSION_DENIED ("we could not
        # read the file"). The detailed errno / position lives in
        # the audit log (T12), not the envelope.
        logger.warning(
            "read_log failed to decode log for %r: %s", walnut, exc
        )
        return envelope.error(
            errors.ERR_PERMISSION_DENIED,
            walnut=walnut,
            file="log",
        )
    except OSError as exc:
        logger.warning("read_log failed for %r: %s", walnut, exc)
        return envelope.error(
            errors.ERR_PERMISSION_DENIED,
            walnut=walnut,
            file="log",
        )

    consumed = offset + len(entries)
    next_offset: Optional[int] = consumed if consumed < total_entries else None

    return envelope.ok(
        {
            "entries": [e.as_dict() for e in entries],
            "total_entries": total_entries,
            "total_chapters": len(sources.chapters),
            "next_offset": next_offset,
            "chapter_boundary_crossed": chapter_crossed,
        }
    )


@audited
async def list_tasks(
    ctx: Context,
    walnut: str,
    bundle: Optional[str] = None,
) -> Dict[str, Any]:
    """Return tasks for ``walnut`` or a specific ``bundle``.

    When ``bundle`` is ``None``, every ``tasks.json`` under the
    walnut (kernel-level + each bundle's tasks file) contributes,
    stopping at nested-walnut boundaries. When ``bundle`` is
    specified, ONLY that bundle's top-level ``tasks.json`` is read
    -- sub-bundles and any other nested ``tasks.json`` under the
    bundle are intentionally excluded (per the v0.1 frozen spec:
    "scoped to that bundle's ``tasks.json``").

    Returns::

        {
          "tasks": [ {<raw tasks.json task>}, ... ],
          "counts": {"urgent": N, "active": N, "todo": N,
                     "blocked": N, "done": N}
        }

    Tasks flow through verbatim -- we don't reshape the schema;
    clients that need a specific field pull it directly. Counts
    follow the vendored summary rule (urgent counts orthogonally to
    status; todo/active/blocked/done are status-exclusive).
    """
    world_root = _get_world_root(ctx)
    if world_root is None:
        return envelope.error(errors.ERR_NO_WORLD)

    try:
        walnut_abs = _resolve_walnut(world_root, walnut)
    except errors.PathEscapeError:
        return envelope.error(errors.ERR_PATH_ESCAPE)
    except errors.WalnutNotFoundError:
        return _walnut_not_found_envelope(world_root, walnut)

    # ``_read_tasks_json`` raises :class:`errors.KernelFileError` on
    # permission / I/O failures (not on malformed JSON -- that warns
    # and returns ``None``). We catch both the vendored exception and
    # bare ``OSError`` so ANY unreadable task file surfaces
    # ERR_PERMISSION_DENIED rather than bubbling out as an uncaught
    # exception and violating the "tools never raise" contract.
    if bundle is None:
        try:
            tasks = _collect_walnut_tasks(world_root, walnut_abs)
        except (errors.KernelFileError, PermissionError, OSError) as exc:
            logger.warning(
                "list_tasks denied for walnut %r: %s", walnut, exc
            )
            return envelope.error(
                errors.ERR_PERMISSION_DENIED,
                walnut=walnut,
                file="tasks",
            )
    else:
        try:
            _relpath, bundle_abs, _manifest = _resolve_bundle(
                world_root, walnut_abs, bundle
            )
        except errors.PathEscapeError:
            return envelope.error(errors.ERR_PATH_ESCAPE)
        except errors.BundleNotFoundError:
            return _bundle_not_found_envelope(
                walnut, walnut_abs, world_root, bundle
            )
        try:
            tasks = _collect_bundle_tasks(world_root, bundle_abs)
        except (errors.KernelFileError, PermissionError, OSError) as exc:
            logger.warning(
                "list_tasks denied for bundle %r/%r: %s",
                walnut,
                bundle,
                exc,
            )
            return envelope.error(
                errors.ERR_PERMISSION_DENIED,
                walnut=walnut,
                file="tasks",
            )

    return envelope.ok(
        {
            "tasks": tasks,
            "counts": _task_counts(tasks),
        }
    )


# ---------------------------------------------------------------------------
# Registration.
# ---------------------------------------------------------------------------


_LOG_TASK_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
    idempotentHint=True,
)


def register(server: FastMCP[Any]) -> None:
    """Register ``read_log`` and ``list_tasks`` on ``server``.

    Called by :func:`alive_mcp.server.build_server` alongside the
    walnut / bundle / search tool groups. Both tools are read-only
    and closed-world.
    """
    server.tool(
        name="read_log",
        description=(
            "Paginated read of a walnut's log with chapter-aware "
            "spanning. Unit is ENTRIES (one '## <ISO-8601>' heading = "
            "one entry), not bytes or lines. Newest-first ordering; "
            "offset=0 returns the newest entry. When offset+limit "
            "exceeds the active log, auto-spans into "
            "_kernel/history/chapter-NN.md descending. Returns "
            "{entries:[{timestamp,walnut,squirrel_id,body,signed},...], "
            "total_entries, total_chapters, next_offset, "
            "chapter_boundary_crossed}."
        ),
        annotations=_LOG_TASK_TOOL_ANNOTATIONS,
    )(read_log)

    server.tool(
        name="list_tasks",
        description=(
            "List tasks for a walnut or a specific bundle. When "
            "bundle is omitted, returns every task from kernel-level "
            "tasks.json plus each bundle's tasks.json. When bundle is "
            "supplied, returns only that bundle's tasks. Returns "
            "{tasks:[...], counts:{urgent,active,todo,blocked,done}}."
        ),
        annotations=_LOG_TASK_TOOL_ANNOTATIONS,
    )(list_tasks)


__all__ = [
    "LogEntry",
    "list_tasks",
    "parse_log_entries",
    "read_log",
    "register",
]
