"""Kernel-file MCP resources (fn-10-60k.10 / T10).

Exposes the four kernel files -- ``key``, ``log``, ``insights``, ``now``
-- per walnut as MCP resources via the ``alive://`` URI scheme. Clients
that prefer resources over tools (Claude Desktop "attach as context",
Cursor resource picker) list and read these; the tool-layer equivalents
in :mod:`alive_mcp.tools.walnut` remain the imperative retrieval path
for model-driven workflows.

Why these are resources AND tools (design rationale)
----------------------------------------------------
Tools and resources both serve walnut kernel data. The duplication is
INTENTIONAL:

* Resources are HOST-controlled -- the client UI enumerates them, the
  human picks, the client attaches or subscribes. ``resources/updated``
  notifications drive reactive UIs.
* Tools are MODEL-controlled -- the model issues an imperative call
  with parameters, typically mid-task.

Same bytes on disk, two doors. Picking only one would forfeit one
workflow. See the epic spec (fn-10-60k) "Tools vs resources" section.

Implementation strategy
-----------------------
FastMCP's template matcher (``ResourceTemplate.matches``) compiles
``{walnut_path}`` into ``(?P<walnut_path>[^/]+)`` -- the ``[^/]+``
excludes forward slashes, so a walnut path like
``02_Life/people/ben-flint`` does NOT match the template. Two workable
responses to that, and this module takes the second:

1. Pre-enumerate every walnut at server startup and register ONE
   concrete :class:`FunctionResource` per walnut-file pair. Fails when
   the walnut inventory changes at runtime (T11 advertises
   ``listChanged: true`` and needs fresh data on each ``list_resources``
   call). Also rejected because large worlds would register hundreds
   of handlers eagerly -- listing is fast, reading is per-URI.
2. Install LOW-LEVEL ``list_resources`` and ``read_resource`` handlers
   on ``server._mcp_server`` that:

   * List: walk the World at call-time; emit one ``types.Resource``
     per walnut x kernel file.
   * Read: parse the URI with :func:`alive_mcp.uri.decode_kernel_uri`,
     resolve through the same path-safety helpers the tool layer uses,
     read the file, return the contents.

   The low-level handlers REPLACE the FastMCP-installed ones (same
   ``request_handlers`` dict key); later registration wins.

Strategy 2 keeps the path-safety surface tight (one resolver, no
per-handler drift), keeps the list fresh (no stale cache to invalidate),
and lets T11 attach watchdog-driven ``notifications/resources/updated``
emission without shuffling registrations.

List-resources semantics
------------------------
Each ``types.Resource`` carries:

* ``uri`` -- the ``alive://`` URI from :func:`encode_kernel_uri`.
* ``name`` -- ``"<walnut-name> <file>"``, human-readable (e.g.
  ``"ben-flint log"``). Clients show this in pickers.
* ``description`` -- one-line describing the file's role in ALIVE.
* ``mimeType`` -- ``text/markdown`` for ``key|log|insights``,
  ``application/json`` for ``now``.

The listing ALWAYS enumerates all four file stems for every walnut the
``list_walnuts`` tool would find, even if the file does not yet exist
on disk. Rationale: a fresh walnut legitimately has no ``log.md``; the
client should still be able to "attach log when it appears" rather
than see the resource vanish and reappear. A ``resources/read`` on a
missing file returns an error via the envelope path, which is already
how T6 behaves. This keeps resource-list shape stable as walnuts are
populated.

Read-resource semantics
-----------------------
Returns an iterable of one :class:`ReadResourceContents`:

* ``content`` -- the file contents (str).
* ``mime_type`` -- same mapping as list.

Errors are surfaced as MCP JSON-RPC errors via ``raise McpError(...)``
with ``INVALID_PARAMS`` (-32602) for malformed URIs / missing walnuts /
missing files, and ``INTERNAL_ERROR`` (-32603) for read failures. The
protocol layer wraps the raise into a well-formed error response -- we
do NOT return an envelope dict here because resources use a different
response shape than tools (``TextResourceContents`` vs
``CallToolResult``).

``now`` file resolution
-----------------------
Tries v3 (``<walnut>/_kernel/now.json``) first, falls back to v2
(``<walnut>/_kernel/_generated/now.json``). Matches
:func:`alive_mcp.tools.walnut.read_walnut_kernel` exactly -- sharing
the resolver (``_resolve_now_path``) via a helper import keeps the
two layers from diverging.

Path safety
-----------
Every decoded URI goes through :func:`alive_mcp.paths.safe_join`
before the file is read. An escape attempt (symlink to outside the
World, ``%2E%2E`` that survived decoding somehow) produces
``INVALID_PARAMS`` rather than silently serving escape-file contents.
The walnut predicate (``_kernel/key.md`` exists and resolves inside
the World) is also enforced on every read so a URI for a
disappeared walnut is rejected.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, List, Optional, Tuple

from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl

from alive_mcp import errors
from alive_mcp.paths import safe_join
from alive_mcp.tools import walnut as walnut_tools
from alive_mcp.uri import (
    KERNEL_FILES,
    InvalidURIError,
    decode_kernel_uri,
    encode_kernel_uri,
)

logger = logging.getLogger("alive_mcp.resources.kernel")


#: MIME type for each kernel-file stem. Mirrors the tool layer's
#: ``_MIME_MAP`` so list / read / tool all agree on the content type.
_MIME_MAP = {
    "key": "text/markdown",
    "log": "text/markdown",
    "insights": "text/markdown",
    "now": "application/json",
}


#: One-line description per kernel file. These surface in MCP client
#: pickers (Claude Desktop's resource list, Cursor's attach dialog) so
#: keep them short, concrete, and consistent with the ALIVE vocabulary.
_FILE_DESCRIPTIONS = {
    "key": (
        "Walnut identity -- type, goal, people, rhythm, tags, links. "
        "Changes rarely."
    ),
    "log": (
        "Walnut history -- signed entries, prepend-only. Source of "
        "truth for what happened and when."
    ),
    "insights": (
        "Standing domain knowledge for the walnut. Evergreen facts "
        "the squirrel has confirmed."
    ),
    "now": (
        "Current state projection (JSON). Phase, active bundle, next "
        "action, updated timestamp."
    ),
}


#: MCP error codes used in this module. MCP's standard JSON-RPC codes
#: live in :class:`mcp.shared.exceptions.McpError` via
#: :class:`mcp.types.ErrorData`. We stash the integer constants here
#: so the module is self-documenting.
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# App-context accessor. Shared shape with the tool layer.
# ---------------------------------------------------------------------------


def _get_world_root(server: FastMCP[Any]) -> Optional[str]:
    """Return the resolved World root, or None if discovery hasn't completed.

    The lifespan context is threaded through FastMCP's request
    machinery (``get_context().request_context.lifespan_context``).
    Low-level handlers (which this module installs) don't have the
    FastMCP Context bound automatically, so we reach through
    :meth:`FastMCP.get_context` to obtain it. That method raises
    ``LookupError`` when no request is in flight; we handle that by
    returning ``None`` so the caller can emit a proper MCP error.
    """
    try:
        ctx = server.get_context()
    except LookupError:
        return None
    lifespan = getattr(ctx.request_context, "lifespan_context", None)
    if lifespan is None:
        return None
    return getattr(lifespan, "world_root", None)


def _raise_invalid_params(message: str) -> None:
    """Raise an MCP ``INVALID_PARAMS`` error for a malformed URI.

    The message is surfaced verbatim to the client (MCP does not mask
    error messages the way ``mask_error_details=True`` does for tools),
    so callers MUST NOT pass absolute filesystem paths. The redaction
    policy from :mod:`alive_mcp.envelope` does not apply here -- the
    protocol-layer error shape is different.
    """
    raise McpError(
        mcp_types.ErrorData(
            code=_INVALID_PARAMS,
            message=message,
        )
    )


def _raise_internal_error(message: str) -> None:
    """Raise an MCP ``INTERNAL_ERROR`` error for an unexpected read failure.

    Used for truly exceptional cases (disk I/O, unexpected OSError).
    The ``read_walnut_kernel`` tool returns envelope errors for
    permissions / missing files; the resource layer follows the same
    distinction where possible, but a genuine internal error must
    propagate as JSON-RPC ``-32603``.
    """
    raise McpError(
        mcp_types.ErrorData(
            code=_INTERNAL_ERROR,
            message=message,
        )
    )


# ---------------------------------------------------------------------------
# list_resources handler.
# ---------------------------------------------------------------------------


def _walnut_display_name(walnut_path: str) -> str:
    """Return the human-readable walnut name (the last path segment).

    ``04_Ventures/alive`` -> ``alive``. Used to build the resource
    ``name`` field shown in client pickers. Falls back to the full
    path if basename computation would be empty (shouldn't happen
    given the walnut predicate, but belt-and-suspenders).
    """
    if not walnut_path:
        return walnut_path
    tail = walnut_path.rsplit("/", 1)[-1]
    return tail or walnut_path


def _build_resource_entries(world_root: str) -> List[mcp_types.Resource]:
    """Enumerate every walnut x kernel file pair as an MCP Resource.

    Walks the World using the same helper the tool layer uses
    (:func:`alive_mcp.tools.walnut._iter_walnut_paths`) so inventory
    semantics stay identical across primitives. Permission errors
    propagate as :class:`OSError`; the caller converts that into an
    MCP internal-error.
    """
    walnuts = walnut_tools._iter_walnut_paths(world_root)
    entries: List[mcp_types.Resource] = []
    for walnut_path in walnuts:
        display = _walnut_display_name(walnut_path)
        for file in sorted(KERNEL_FILES):
            uri = encode_kernel_uri(walnut_path, file)
            entries.append(
                mcp_types.Resource(
                    uri=AnyUrl(uri),
                    name="{} {}".format(display, file),
                    description=_FILE_DESCRIPTIONS[file],
                    mimeType=_MIME_MAP[file],
                )
            )
    return entries


# ---------------------------------------------------------------------------
# read_resource handler.
# ---------------------------------------------------------------------------


def _resolve_kernel_file_for_uri(
    world_root: str, walnut_path: str, file: str
) -> Tuple[str, str]:
    """Resolve a decoded URI to an on-disk kernel file.

    Returns ``(absolute_path, mime_type)``. Raises MCP errors on:

    * Path escape (``INVALID_PARAMS``) -- the walnut_path would
      resolve outside the World.
    * Walnut not found (``INVALID_PARAMS``) -- the path exists but
      has no ``_kernel/key.md``, or that key.md escapes the World.
    * File missing (``INVALID_PARAMS``) -- the walnut is valid but
      the requested kernel file is not on disk.

    Missing files are ``INVALID_PARAMS`` (not ``INTERNAL_ERROR``)
    because "you asked for a file that does not exist" is a caller
    precondition violation, not a server bug. MCP does not have a
    distinct "resource not found" code; ``INVALID_PARAMS`` is the
    closest semantic match the spec offers for this class of error.
    """
    # safe_join runs realpath + commonpath; we don't need to re-run
    # those checks in this module.
    try:
        walnut_abs = safe_join(world_root, *walnut_path.split("/"))
    except errors.PathEscapeError:
        _raise_invalid_params(
            "walnut path escapes the authorized World root"
        )

    # Walnut predicate: _kernel/key.md must exist and resolve inside
    # the World. This is the same check the tool layer makes in
    # :func:`walnut_tools._resolve_walnut`; sharing the helper keeps
    # the two layers from drifting.
    key_path = walnut_tools._kernel_file_in_world(
        world_root, walnut_abs, "key.md"
    )
    if key_path is None:
        _raise_invalid_params(
            "no walnut at {!r} in this World".format(walnut_path)
        )

    # Resolve the target file. ``now`` uses the v3 -> v2 fallback
    # resolver shared with the tool layer. The other three files live
    # at ``_kernel/<stem>.md`` in the v3 layout only.
    if file == "now":
        target = walnut_tools._resolve_now_path(world_root, walnut_abs)
    else:
        basename = "{}.md".format(file)
        target = walnut_tools._kernel_file_in_world(
            world_root, walnut_abs, basename
        )

    if target is None:
        _raise_invalid_params(
            "kernel file {!r} is missing for walnut {!r}".format(
                file, walnut_path
            )
        )

    return target, _MIME_MAP[file]


# ---------------------------------------------------------------------------
# Registration.
# ---------------------------------------------------------------------------


def register(server: FastMCP[Any]) -> None:
    """Wire kernel-resource handlers onto ``server._mcp_server``.

    Called by :func:`alive_mcp.server.build_server` once, after the
    tool registrations. FastMCP's :meth:`FastMCP._setup_handlers`
    already installed resource handlers that enumerate the empty
    ResourceManager -- we REPLACE both the ``list_resources`` and
    ``read_resource`` handlers by re-registering them on the low-level
    server (the ``request_handlers`` dict -- same key, later
    registration wins).

    We deliberately do NOT call :meth:`FastMCP.resource` (the
    decorator) for two reasons:

    1. FastMCP compiles the template into ``(?P<x>[^/]+)``, which
       cannot capture forward slashes inside ``{walnut_path}``. Our
       URI scheme preserves ``/`` as a literal separator, so the
       template would never match.
    2. The enumeration needs to be lazy (fresh-per-call). Registering
       one :class:`FunctionResource` per walnut-file pair at startup
       would eagerly materialize every resource; dynamic discovery
       via a low-level handler is the cleaner seam for the T11
       listChanged semantics.
    """

    @server._mcp_server.list_resources()
    async def _list_kernel_resources() -> list[mcp_types.Resource]:
        """Return one Resource per walnut x kernel-file pair.

        Enumerates the walnut inventory fresh on every call. At the
        v0.1 scale target (Patrick's 43-walnut World) this is a
        single-digit-millisecond directory walk; rebuilding the list
        on every ``resources/list`` request is simpler than cache
        invalidation for T11's listChanged semantics.
        """
        world_root = _get_world_root(server)
        if world_root is None:
            # Per MCP spec, list_resources returns an empty array when
            # no resources are available. Emitting an error here would
            # prevent clients from even showing the resource picker on
            # a server whose World is still being discovered. Log at
            # DEBUG for post-mortem and return empty.
            logger.debug(
                "list_resources called before World discovery completed; "
                "returning empty list"
            )
            return []

        try:
            return _build_resource_entries(world_root)
        except PermissionError as exc:
            # A permission failure at the World root is a real signal
            # the client needs to surface, but MCP's resources/list
            # has no error channel -- the response type is a list.
            # Log and degrade to empty; the client can retry later.
            logger.warning(
                "list_resources: walnut inventory denied: %s", exc
            )
            return []
        except OSError as exc:
            logger.warning(
                "list_resources: walnut inventory failed: %s", exc
            )
            return []

    @server._mcp_server.read_resource()
    async def _read_kernel_resource(
        uri: AnyUrl,
    ) -> Iterable[ReadResourceContents]:
        """Read a kernel file identified by its ``alive://`` URI.

        Parses the URI, re-resolves through the path-safety layer,
        and returns an iterable of one :class:`ReadResourceContents`.
        The MCP protocol layer wraps the iterable into a
        ``ReadResourceResult`` on the client's behalf.

        Errors raise :class:`McpError` with ``INVALID_PARAMS`` for
        caller-precondition failures (malformed URI, missing walnut,
        missing file, path escape) and ``INTERNAL_ERROR`` for genuine
        I/O failures (permission denied, disk gone).
        """
        world_root = _get_world_root(server)
        if world_root is None:
            _raise_invalid_params(
                "no ALIVE World has been resolved; "
                "set ALIVE_WORLD_ROOT or widen client Roots"
            )

        # ``uri`` arrives as a pydantic :class:`AnyUrl`; stringify once
        # so the decoder sees the canonical form. ``AnyUrl.__str__``
        # produces the RFC 3986 form with no surprise normalization
        # (no case-lowering of the path, no re-encoding of percent
        # sequences that would drift from the client's input).
        uri_str = str(uri)

        try:
            walnut_path, file = decode_kernel_uri(uri_str)
        except InvalidURIError as exc:
            _raise_invalid_params("invalid alive:// URI: {}".format(exc))

        # McpError raised inside _resolve_kernel_file_for_uri
        # propagates naturally; no need to re-wrap.
        target, mime = _resolve_kernel_file_for_uri(
            world_root, walnut_path, file
        )

        try:
            with open(target, "r", encoding="utf-8") as f:
                content = f.read()
        except PermissionError:
            _raise_internal_error(
                "permission denied reading kernel file {!r} for walnut {!r}".format(
                    file, walnut_path
                )
            )
        except OSError as exc:
            _raise_internal_error(
                "read failed for kernel file {!r} of walnut {!r}: {}".format(
                    file, walnut_path, exc.__class__.__name__
                )
            )
        except UnicodeDecodeError:
            _raise_internal_error(
                "kernel file {!r} for walnut {!r} is not valid UTF-8".format(
                    file, walnut_path
                )
            )

        return [
            ReadResourceContents(content=content, mime_type=mime),
        ]


__all__ = [
    "register",
]
