"""Error taxonomy for alive-mcp v0.1.

This module is the single source of truth for the error types and error
codes alive-mcp surfaces across its public seams: tool responses, resource
reads, world discovery, and path safety. The envelope schema (the
``{content, structuredContent, isError}`` shape returned by FastMCP tools)
lives in :mod:`alive_mcp.envelope`, which imports templates from here.

Taxonomy (v0.1 frozen set)
--------------------------
Nine codes cover every failure mode a read-only v0.1 tool can emit:

=========================== ========================================
Code                         Seam
=========================== ========================================
``ERR_NO_WORLD``            World discovery (T3)
``ERR_WALNUT_NOT_FOUND``    Walnut-tool layer (T6)
``ERR_BUNDLE_NOT_FOUND``    Bundle-tool layer (T7)
``ERR_KERNEL_FILE_MISSING`` Tool-level precondition (T6, T9)
``ERR_PERMISSION_DENIED``   Any OSError on read (POSIX ``EACCES``)
``ERR_PATH_ESCAPE``         Path safety (T3, CVE-2025-53109 boundary)
``ERR_INVALID_CURSOR``      Cursor pagination (T8)
``ERR_TOOL_TIMEOUT``        Per-tool deadline (T5 shell)
``ERR_AUDIT_DISK_FULL``     Audit writer (T12, ENOSPC)
=========================== ========================================

Design notes
------------
- **Codes are string constants**, not an ``IntEnum``. The MCP protocol
  is JSON-over-stdio; string codes survive JSON serialization without
  ambiguity and read clearly in the audit log. (The task spec calls for
  ``enum.Enum`` — we use module-level constants instead because that is
  the existing T3 shape and ``StrEnum`` isn't available until 3.11. A
  bare ``Enum`` would serialize as ``'CodeName.ERR_X'`` without a
  custom encoder, which is exactly the ambiguity we are avoiding.)
- **Each code has a user-facing message template and a suggestions
  list.** Templates use ``{placeholders}`` for values the caller
  provides (walnut name, bundle name, query) — never absolute
  filesystem paths. ``mask_error_details=True`` on FastMCP prevents
  raw exception strings leaking; this module is the allow-list of
  what CAN leak.
- **Exceptions carry a ``code`` attribute.** The tool layer catches
  :class:`AliveMcpError` and emits an envelope error using ``exc.code``
  and ``str(exc)``. This keeps envelope mapping in one place (T5)
  instead of scattered try/except ladders.
- **Re-exports from :mod:`alive_mcp._vendor._pure`** are intentional.
  ``WorldNotFoundError``, ``KernelFileError``, and
  ``MalformedYAMLWarning`` live in the vendor package because the
  extracted pure helpers raise them. alive-mcp surface code imports
  from here so it does not have to reach into ``_vendor`` — which is
  private. If a future task renames or re-homes any of these, this
  file is the only public seam that needs updating.

Security context
----------------
``PathEscapeError`` is the detection boundary for CVE-2025-53109-class
bugs (filesystem MCP servers bypassing their allowed-root check via a
prefix comparison). See :mod:`alive_mcp.paths` for the detection
implementation and the rationale for using ``os.path.commonpath`` over
``startswith``.

Message safety
--------------
**No message template in this module contains an absolute filesystem
path.** The ``mask_error_details=True`` promise is that user-facing
errors never leak server-side paths; this module enforces that promise
at the template level. Callers that need to log a path for debugging
route it through the audit log (T12), not the envelope.
"""

from __future__ import annotations

from typing import Mapping

# Re-export vendor error types so consumers never reach into ``_vendor``
# directly. ``_vendor`` is private; ``errors`` is public.
from alive_mcp._vendor._pure import (  # noqa: F401  (re-export)
    KernelFileError,
    MalformedYAMLWarning,
    WorldNotFoundError,
)


# -----------------------------------------------------------------------------
# Error codes (string constants).
#
# Keep names aligned with the spec (ALL_CAPS, ``ERR_`` prefix,
# snake-shouty) so the audit log stays greppable.
# -----------------------------------------------------------------------------

ERR_NO_WORLD = "ERR_NO_WORLD"
"""No World could be resolved from the configured Roots or env fallback.

Fires when:

- The MCP ``roots/list`` handshake returned no Roots AND no env fallback
  is set, OR
- No Root, when walked upward within its own bounds, satisfies
  ``is_world_root``, OR
- The env fallback path does not satisfy ``is_world_root`` when walked
  within its own bound.
"""

ERR_WALNUT_NOT_FOUND = "ERR_WALNUT_NOT_FOUND"
"""Walnut path does not resolve to a directory with a ``_kernel/`` inside.

Fires on ``get_walnut_state``, ``read_walnut_kernel``, ``list_bundles``,
``search_walnut``, ``read_log``, ``list_tasks``. The suggestions list
surfaces the closest names from ``list_walnuts`` so the LLM can retry.
"""

ERR_BUNDLE_NOT_FOUND = "ERR_BUNDLE_NOT_FOUND"
"""Bundle path does not resolve under a walnut's ``bundles/`` directory.

Fires on ``get_bundle``, ``read_bundle_manifest``, ``list_tasks`` when
a ``bundle`` arg is present. Suggestions list surfaces the closest
bundle paths within the walnut.
"""

ERR_KERNEL_FILE_MISSING = "ERR_KERNEL_FILE_MISSING"
"""A requested ``_kernel/`` file is not present on disk.

Distinct from :data:`ERR_WALNUT_NOT_FOUND` — the walnut exists, but
the specific kernel file (``key.md``, ``log.md``, ``insights.md``,
``now.json``) has never been written. Fresh walnuts legitimately
lack these files.

Distinct from the :class:`KernelFileError` exception (re-exported from
``_vendor._pure``), which fires only when a file is present on disk
but unreadable. Missing files are tool-layer preconditions; corrupt
files are vendor-layer I/O errors.
"""

ERR_PERMISSION_DENIED = "ERR_PERMISSION_DENIED"
"""POSIX ``EACCES`` / Windows access-denied while reading a kernel file.

Fires when ``open()`` raises ``PermissionError`` on a walnut or bundle
file. The suggestion steers the user to fix filesystem permissions
(``chmod``, ACL) — alive-mcp never attempts to change them itself.
"""

ERR_PATH_ESCAPE = "ERR_PATH_ESCAPE"
"""Candidate path resolves outside its allowed World root.

Fires when:

- A relative or absolute input resolves (post-``realpath``) outside the
  configured World root, OR
- A symlink's target resolves outside the World root, OR
- Windows ``commonpath`` raises ``ValueError`` (paths on different
  drives — treated as "not inside").

This is the CVE-2025-53109 detection boundary. See :mod:`alive_mcp.paths`
for the commonpath-based check and why ``startswith`` is NOT acceptable.
"""

ERR_INVALID_CURSOR = "ERR_INVALID_CURSOR"
"""An opaque pagination cursor failed to decode or validate.

Fires on ``list_walnuts``, ``search_world``, ``search_walnut`` when a
caller passes a ``cursor`` value that did not come from a prior call
(wrong format, tampered HMAC, stale token after server restart).
Suggestion: drop the cursor and retry from offset 0.
"""

ERR_TOOL_TIMEOUT = "ERR_TOOL_TIMEOUT"
"""Tool invocation exceeded its per-call deadline.

Enforced by the FastMCP shell (T5) with an ``asyncio.wait_for`` wrapper.
Default deadline is tool-specific; search tools have the longest window.
Suggestion: narrow the query or use cursor pagination.
"""

ERR_AUDIT_DISK_FULL = "ERR_AUDIT_DISK_FULL"
"""Audit logger could not write to ``.alive/_mcp/audit.log`` (ENOSPC).

Fires from the async audit writer (T12) when the filesystem rejects the
append. The tool call itself MAY have succeeded; this error surfaces
the audit failure separately so the caller knows the record did not
land on disk. Read-only v0.1 treats this as a hard failure — the audit
log is a safety requirement, not a nice-to-have.
"""


# -----------------------------------------------------------------------------
# User-facing message templates + actionable suggestions.
#
# Templates use str.format-style ``{placeholders}``. Callers pass kwargs
# matching the placeholders; unused kwargs are ignored.
#
# **No template contains an absolute filesystem path.** Placeholders
# carry walnut names, bundle names, kernel file stems, and query
# strings — all caller-facing identifiers, none server-internal paths.
# The audit log (T12) captures internal paths for debugging; the
# envelope never does.
# -----------------------------------------------------------------------------

MESSAGES: Mapping[str, str] = {
    ERR_NO_WORLD: (
        "No ALIVE World could be located. Set ALIVE_WORLD_ROOT in the "
        "server environment, or widen the client's Roots to include a "
        "directory that contains '.alive/' or both '01_Archive/' and "
        "'02_Life/'."
    ),
    ERR_WALNUT_NOT_FOUND: (
        "No walnut found at '{walnut}' in this World."
    ),
    ERR_BUNDLE_NOT_FOUND: (
        "No bundle found at '{bundle}' in walnut '{walnut}'."
    ),
    ERR_KERNEL_FILE_MISSING: (
        "The '{file}' kernel file has not been written for walnut "
        "'{walnut}'."
    ),
    ERR_PERMISSION_DENIED: (
        "Permission denied reading '{file}' in walnut '{walnut}'."
    ),
    ERR_PATH_ESCAPE: (
        "The requested path is outside the authorized World root and "
        "was rejected."
    ),
    ERR_INVALID_CURSOR: (
        "The pagination cursor is invalid or has expired."
    ),
    ERR_TOOL_TIMEOUT: (
        "Tool '{tool}' exceeded its {timeout_s:.1f}s deadline."
    ),
    ERR_AUDIT_DISK_FULL: (
        "The audit log could not be written (disk full or permissions). "
        "Tool results are not being recorded."
    ),
}

SUGGESTIONS: Mapping[str, tuple[str, ...]] = {
    ERR_NO_WORLD: (
        "Set the ALIVE_WORLD_ROOT environment variable to the World root.",
        "Configure the MCP client's Roots to include the World directory.",
        "Verify the World directory contains '.alive/' or the legacy "
        "'01_Archive/' + '02_Life/' pair.",
    ),
    ERR_WALNUT_NOT_FOUND: (
        "Call 'list_walnuts' to see available walnuts in this World.",
        "Walnut paths are POSIX-relative from the World root (e.g. "
        "'04_Ventures/nova-station'), not bare names.",
    ),
    ERR_BUNDLE_NOT_FOUND: (
        "Call 'list_bundles' with the walnut path to see available bundles.",
        "Bundle paths are relative to the walnut root (e.g. "
        "'bundles/shielding-review').",
    ),
    ERR_KERNEL_FILE_MISSING: (
        "Fresh walnuts legitimately lack some kernel files. If the "
        "walnut is active, it has not been saved yet.",
        "Valid 'file' values: 'key', 'log', 'insights', 'now'.",
    ),
    ERR_PERMISSION_DENIED: (
        "Check filesystem permissions on the walnut directory.",
        "Ensure the MCP server process has read access to the World root.",
    ),
    ERR_PATH_ESCAPE: (
        "Paths must resolve inside the authorized World root after "
        "symlink resolution.",
        "Use POSIX-relative paths returned by 'list_walnuts' and "
        "'list_bundles' verbatim; do not construct absolute paths.",
    ),
    ERR_INVALID_CURSOR: (
        "Drop the 'cursor' argument and retry from the first page.",
        "Cursors do not survive server restarts.",
    ),
    ERR_TOOL_TIMEOUT: (
        "Narrow the query to reduce the search space.",
        "Use cursor pagination (smaller 'limit') to stay under the deadline.",
    ),
    ERR_AUDIT_DISK_FULL: (
        "Free disk space on the filesystem holding '.alive/_mcp/'.",
        "Rotate or archive existing audit logs if retention is not needed.",
    ),
}


# The frozen v0.1 code set. Tools MUST emit only codes in this set; the
# tests assert template+suggestion coverage across this set exactly.
ERROR_CODES: tuple[str, ...] = (
    ERR_NO_WORLD,
    ERR_WALNUT_NOT_FOUND,
    ERR_BUNDLE_NOT_FOUND,
    ERR_KERNEL_FILE_MISSING,
    ERR_PERMISSION_DENIED,
    ERR_PATH_ESCAPE,
    ERR_INVALID_CURSOR,
    ERR_TOOL_TIMEOUT,
    ERR_AUDIT_DISK_FULL,
)


# -----------------------------------------------------------------------------
# Base class + code-carrying exceptions.
#
# The tool/resource layer (T5+) catches ``AliveMcpError`` and maps
# ``exc.code`` into the response envelope. Callers inside tool code raise
# the specific subclass with a human-readable message; the code constant
# is already attached via the class attribute.
#
# Subclass-per-code is a deliberate choice over a single parameterized
# exception:
# - ``except WalnutNotFoundError`` reads better than ``except AliveMcpError
#   if exc.code == ERR_WALNUT_NOT_FOUND``.
# - Type checkers can narrow on subclass.
# - Codes stay discoverable via ``ERROR_CODES`` without needing to
#   instantiate anything.
# -----------------------------------------------------------------------------


class AliveMcpError(Exception):
    """Base for all alive-mcp errors that map to a protocol error code.

    Subclasses set ``code`` as a class attribute. The tool envelope layer
    (T4/T5) reads ``exc.code`` and ``str(exc)`` to build the response.
    """

    code: str = "ERR_UNKNOWN"


class PathEscapeError(AliveMcpError):
    """Raised when a candidate path escapes its allowed World root.

    The detection is defense-in-depth: realpath BOTH sides, then use
    ``os.path.commonpath`` (NOT ``startswith``) to compare. See the
    module docstring on :mod:`alive_mcp.paths` for the full rationale
    and the CVE reference.
    """

    code: str = ERR_PATH_ESCAPE


class WalnutNotFoundError(AliveMcpError):
    """Raised when a requested walnut path does not resolve to a walnut."""

    code: str = ERR_WALNUT_NOT_FOUND


class BundleNotFoundError(AliveMcpError):
    """Raised when a requested bundle path does not resolve to a bundle."""

    code: str = ERR_BUNDLE_NOT_FOUND


class KernelFileMissingError(AliveMcpError):
    """Raised when a kernel file is absent on disk (not corrupt).

    Distinct from :class:`KernelFileError` (re-exported from
    ``_vendor._pure``), which fires when a kernel file IS on disk but
    unreadable. Missing-on-disk is a tool precondition; present-but-
    unreadable is a vendor-layer I/O failure.
    """

    code: str = ERR_KERNEL_FILE_MISSING


class PermissionDeniedError(AliveMcpError):
    """Raised when the OS denies read access to a walnut or bundle file."""

    code: str = ERR_PERMISSION_DENIED


class InvalidCursorError(AliveMcpError):
    """Raised when a pagination cursor fails to decode or validate."""

    code: str = ERR_INVALID_CURSOR


class ToolTimeoutError(AliveMcpError):
    """Raised when a tool invocation exceeds its per-call deadline."""

    code: str = ERR_TOOL_TIMEOUT


class AuditDiskFullError(AliveMcpError):
    """Raised when the audit writer cannot append to audit.log."""

    code: str = ERR_AUDIT_DISK_FULL


__all__ = [
    # Codes (string constants).
    "ERR_NO_WORLD",
    "ERR_WALNUT_NOT_FOUND",
    "ERR_BUNDLE_NOT_FOUND",
    "ERR_KERNEL_FILE_MISSING",
    "ERR_PERMISSION_DENIED",
    "ERR_PATH_ESCAPE",
    "ERR_INVALID_CURSOR",
    "ERR_TOOL_TIMEOUT",
    "ERR_AUDIT_DISK_FULL",
    "ERROR_CODES",
    # Templates + suggestions.
    "MESSAGES",
    "SUGGESTIONS",
    # Exception base + subclasses.
    "AliveMcpError",
    "AuditDiskFullError",
    "BundleNotFoundError",
    "InvalidCursorError",
    "KernelFileError",
    "KernelFileMissingError",
    "MalformedYAMLWarning",
    "PathEscapeError",
    "PermissionDeniedError",
    "ToolTimeoutError",
    "WalnutNotFoundError",
    "WorldNotFoundError",
]
