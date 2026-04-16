"""Encoder + decoder for the ``alive://`` URI scheme (fn-10-60k.10 / T10).

The scheme is the wire identity of every kernel-file resource exposed by
alive-mcp. It is ALSO the URI that T11's ``resources/updated`` notifications
will carry, and the URI v0.2 bundle resources will extend. Locking it here
-- encoder, decoder, and contract tests -- keeps the format stable as more
resource families land.

Scheme contract (frozen)
------------------------

.. code-block:: text

    alive://walnut/{walnut_path}/kernel/{file}

``{walnut_path}``
    POSIX relative path from the World root (e.g.
    ``02_Life/people/ben-flint``, ``04_Ventures/supernormal-systems/clients/
    elite-oceania``). Percent-encoded per RFC 3986 path-segment rules,
    with a deliberate exception: **forward slashes ``/`` are preserved as
    literal path separators**; every OTHER reserved path-segment character
    IS percent-encoded. Spaces -> ``%20``. Unicode text is normalized to
    NFC before encoding so equivalent forms round-trip to the same URI.

``{file}``
    Literal drawn from ``{"key", "log", "insights", "now"}``. No encoding
    applied -- all four are URL-safe ASCII. An unknown value is rejected
    by :func:`decode_kernel_uri` with ``InvalidURIError``.

Examples
--------

==================================================================== ============================================================================
walnut_path                                                          Encoded URI
==================================================================== ============================================================================
``02_Life/people/ben-flint``                                         ``alive://walnut/02_Life/people/ben-flint/kernel/log``
``04_Ventures/supernormal-systems/clients/elite-oceania``            ``alive://walnut/04_Ventures/supernormal-systems/clients/elite-oceania/kernel/key``
``People/ryn okata``                                                 ``alive://walnut/People/ryn%20okata/kernel/insights``
``04_Ventures/h\u00e9l\u00e8ne`` (NFC)                               ``alive://walnut/04_Ventures/h%C3%A9l%C3%A8ne/kernel/now``
==================================================================== ============================================================================

Why a custom scheme
-------------------
``file://`` would be wrong on two fronts:

1. Semantics: some MCP clients (Claude Desktop, Cursor) map ``file://``
   to raw-filesystem resource semantics -- they try to interpret the
   URI as an absolute filesystem path. ``alive://`` signals
   "ALIVE-specific handling required".
2. Safety: a ``file://`` URL pointing outside the World would be a
   valid URL by the URL spec. Our containment check still catches that,
   but the separation means a client can't confuse ``file://`` handlers
   with our resource handlers by accident.

The scheme name is ``alive``. URIs are lowercase in the scheme component
(``alive://...``); RFC 3986 requires scheme-case-insensitivity, but we
emit the canonical lowercase form everywhere.

Why the encoder preserves ``/`` inside ``walnut_path``
------------------------------------------------------
``urllib.parse.quote(safe="/")`` does this natively -- ``safe`` is the
whitelist of characters NOT to encode. We pass ``/`` so path separators
survive the round-trip as literal slashes, which means:

- ``resources/list`` output reads naturally (``alive://walnut/02_Life/
  people/ben-flint/kernel/log``) rather than opaque
  (``alive://walnut/02_Life%2Fpeople%2Fben-flint/kernel/log``).
- FastMCP's template matcher ``(?P<param>[^/]+)`` cannot capture a
  ``/`` anyway (tested in T10 against mcp>=1.27). Our resource handler
  therefore parses the whole URI ourselves, not the template matcher.

Why NFC normalization
---------------------
macOS filesystem (HFS+, APFS) uses NFD for filename storage. A path
containing an accented character (``\u00e9``) may arrive either as NFC
(``\u00e9``) or NFD (``e\u0301``); both percent-encode to DIFFERENT
bytes. Normalizing to NFC first means the same logical path always
produces the same URI, so ``resources/list`` entries match
``resources/read`` requests the client sends back.

NFC is the IETF default for URL internationalization (RFC 3987) and the
Unicode TR#36 recommendation for "canonical form before I/O". NFD would
work too but NFC is shorter on-the-wire for the common case.

Decoder contract
----------------
:func:`decode_kernel_uri` validates:

1. Scheme is exactly ``alive``.
2. Authority (host) is exactly ``walnut``.
3. Path starts with ``/`` followed by at least one percent-encoded
   segment, then ``/kernel/<file>``.
4. ``<file>`` is one of ``key | log | insights | now``.
5. After percent-decoding, the walnut path has no empty segments, no
   ``.`` or ``..`` segments, and does not start with ``/`` (which would
   indicate an absolute path leaking through).

Any other shape raises :class:`InvalidURIError`, which callers map to the
MCP error code ``-32602`` (InvalidParams) so malformed URIs do not take
down a server session. The decoded ``walnut_path`` is the SAME POSIX
relpath the encoder accepted -- callers can feed it into
:func:`alive_mcp.paths.safe_join` unchanged.

Public API
----------
- :func:`encode_kernel_uri(walnut_path, file) -> str`
- :func:`decode_kernel_uri(uri) -> (walnut_path, file)`
- :data:`KERNEL_FILES` -- frozenset of the four legal file stems.
- :class:`InvalidURIError` -- raised on any malformed URI.
"""

from __future__ import annotations

import unicodedata
import urllib.parse
from typing import Tuple

__all__ = [
    "InvalidURIError",
    "KERNEL_FILES",
    "SCHEME",
    "AUTHORITY",
    "encode_kernel_uri",
    "decode_kernel_uri",
]


#: The scheme component of every alive-mcp resource URI. Lowercased
#: canonical form; RFC 3986 scheme comparison is case-insensitive but
#: we emit only the lowercase form to keep wire output deterministic
#: (matters for Inspector snapshot tests in T14).
SCHEME = "alive"

#: The authority (host) component that identifies a walnut-scoped
#: resource. v0.2 may add ``world`` for world-level resources; for
#: v0.1, ``walnut`` is the only authority recognized.
AUTHORITY = "walnut"

#: Legal values for the ``{file}`` segment. The tool surface (T6) uses
#: the same literal set; sharing the constant keeps the two layers from
#: drifting.
KERNEL_FILES = frozenset({"key", "log", "insights", "now"})


class InvalidURIError(ValueError):
    """Raised when a string fails to parse as an ``alive://`` kernel URI.

    Subclasses :class:`ValueError` so callers that catch broad
    validation errors still catch this, but reveals the specific cause
    via the exception message. The tool/resource layer maps this to the
    MCP error code ``-32602`` (InvalidParams) -- malformed URIs are the
    caller's fault and never terminate the server session.

    Message strings MUST NOT include absolute filesystem paths. The
    caller-facing identifiers (the URI itself, the offending segment)
    are fine; the audit log (T12) captures server-internal context.
    """


# ---------------------------------------------------------------------------
# Encoder.
# ---------------------------------------------------------------------------


def _encode_walnut_path(walnut_path: str) -> str:
    """Percent-encode ``walnut_path`` per RFC 3986 path-segment rules, preserving ``/``.

    Steps:

    1. NFC-normalize so equivalent Unicode compositions produce the
       same bytes on the wire.
    2. ``urllib.parse.quote(safe="/")`` -- ``quote`` escapes every
       character except unreserved (ALPHA / DIGIT / ``-`` / ``.`` /
       ``_`` / ``~``) PLUS the ``safe`` set. Passing ``/`` as safe
       preserves path separators as literal slashes; everything else
       that needs escaping (spaces, Unicode bytes, reserved chars like
       ``:``, ``?``, ``#``, ``@``, ``&``, ``=``, ``+``, ``$``, ``,``,
       ``;``) is percent-encoded.

    The input is expected to be a POSIX-shape relpath (no leading
    slash, no trailing slash). We do NOT strip leading/trailing slashes
    here because that would silently accept ill-formed input; the
    decoder enforces the relpath invariant on the other side.

    A literal percent-sign in the input would be encoded as ``%25`` --
    so the round-trip is stable for any bytestring, including one that
    happens to contain a percent.
    """
    normalized = unicodedata.normalize("NFC", walnut_path)
    # ``safe="/"`` preserves path separators; everything else is
    # percent-encoded. Note that ``quote`` already handles Unicode
    # via UTF-8 byte expansion -- no explicit encode() call needed.
    return urllib.parse.quote(normalized, safe="/")


def encode_kernel_uri(walnut_path: str, file: str) -> str:
    """Assemble the ``alive://walnut/{walnut_path}/kernel/{file}`` URI.

    Parameters
    ----------
    walnut_path:
        POSIX-relative path from the World root (as returned by
        :func:`alive_mcp.tools.walnut.list_walnuts`). No leading or
        trailing slashes; segments separated by forward slashes.
    file:
        One of ``"key"``, ``"log"``, ``"insights"``, or ``"now"``.

    Returns
    -------
    str
        The encoded URI in the canonical alive-mcp form.

    Raises
    ------
    InvalidURIError
        * ``walnut_path`` is empty, starts or ends with ``/``, or
          contains a ``.``/``..`` segment.
        * ``file`` is not in :data:`KERNEL_FILES`.
    """
    if not walnut_path:
        raise InvalidURIError("walnut_path must not be empty")
    # Reject leading or trailing separators -- the walnut path is a
    # POSIX relpath, not an absolute-style string. ``list_walnuts``
    # returns the canonical shape (no edges); defending here catches
    # hand-rolled callers.
    if walnut_path.startswith("/"):
        raise InvalidURIError(
            "walnut_path must not start with '/': {!r}".format(walnut_path)
        )
    if walnut_path.endswith("/"):
        raise InvalidURIError(
            "walnut_path must not end with '/': {!r}".format(walnut_path)
        )
    # ``.`` and ``..`` segments have no place in a canonical walnut
    # path and would defeat the path-safety layer if they slipped
    # through. Normalization would collapse them, but silently
    # collapsing is worse than rejecting -- the client should learn
    # the canonical form.
    for segment in walnut_path.split("/"):
        if segment in ("", ".", ".."):
            raise InvalidURIError(
                "walnut_path has illegal segment {!r} in {!r}".format(
                    segment, walnut_path
                )
            )

    if file not in KERNEL_FILES:
        raise InvalidURIError(
            "file must be one of {}; got {!r}".format(
                sorted(KERNEL_FILES), file
            )
        )

    encoded_path = _encode_walnut_path(walnut_path)
    return "{scheme}://{authority}/{walnut_path}/kernel/{file}".format(
        scheme=SCHEME,
        authority=AUTHORITY,
        walnut_path=encoded_path,
        file=file,
    )


# ---------------------------------------------------------------------------
# Decoder.
# ---------------------------------------------------------------------------


def _split_path(path: str) -> list[str]:
    """Split a URL path on ``/``, discarding the leading empty segment.

    A well-formed kernel URI path has the shape
    ``/<walnut_path>/kernel/<file>``, so after :func:`urllib.parse.urlsplit`
    the ``.path`` attribute starts with ``/`` and ``split("/")`` produces
    an empty first element. We discard that so the remaining list is the
    sequence of real segments.

    Empty trailing or intermediate segments (the result of ``//`` in the
    URI) are preserved here; the caller validates against them so the
    error message can be specific.
    """
    if not path.startswith("/"):
        return path.split("/")
    return path[1:].split("/")


def decode_kernel_uri(uri: str) -> Tuple[str, str]:
    """Parse an ``alive://walnut/.../kernel/<file>`` URI.

    Parameters
    ----------
    uri:
        The URI string. Case-sensitive in the path segments (walnut
        paths are case-sensitive in v0.1 even on HFS+; see the epic
        spec's "Case-sensitivity note"). Scheme comparison is
        case-insensitive per RFC 3986.

    Returns
    -------
    (walnut_path, file):
        ``walnut_path`` is the percent-DECODED POSIX relpath ready to
        feed into :func:`alive_mcp.paths.safe_join`. ``file`` is the
        literal kernel-file stem.

    Raises
    ------
    InvalidURIError
        On any mismatch against the contract: wrong scheme, wrong
        authority, wrong suffix, unknown file stem, empty or ``.``/
        ``..``-containing walnut segments, absolute-path leakage, etc.
    """
    if not isinstance(uri, str):
        raise InvalidURIError(
            "uri must be a string; got {!r}".format(type(uri).__name__)
        )
    if not uri:
        raise InvalidURIError("uri must not be empty")

    try:
        parts = urllib.parse.urlsplit(uri)
    except ValueError as exc:
        raise InvalidURIError("uri failed to parse: {}".format(exc)) from exc

    # Scheme comparison is case-insensitive per RFC 3986. The emitted
    # form is always lowercase (see encoder); accepting mixed-case on
    # input is cheap forward-compat for clients that upper-case the
    # scheme before sending.
    if parts.scheme.lower() != SCHEME:
        raise InvalidURIError(
            "scheme must be {!r}; got {!r}".format(SCHEME, parts.scheme)
        )
    # netloc is the "host" component -- for alive-mcp v0.1 it must be
    # exactly ``walnut``. A future version may accept ``world`` for
    # world-scoped resources.
    if parts.netloc != AUTHORITY:
        raise InvalidURIError(
            "authority must be {!r}; got {!r}".format(AUTHORITY, parts.netloc)
        )
    # Query and fragment are not used in v0.1; rejecting them avoids
    # surprise behavior if a client tries to smuggle parameters through
    # the URI.
    if parts.query:
        raise InvalidURIError("query component not allowed")
    if parts.fragment:
        raise InvalidURIError("fragment component not allowed")

    segments = _split_path(parts.path)
    # Minimum shape: ``["<walnut-seg>", "kernel", "<file>"]`` -- three
    # segments. The walnut path can be more than one segment
    # (``02_Life``, ``people``, ``ben-flint`` etc.), so any count >= 3
    # is potentially valid; the LAST two must be ``kernel`` and a known
    # file stem, and everything before them is the walnut path.
    if len(segments) < 3:
        raise InvalidURIError(
            "path must contain at least <walnut>/kernel/<file>; got {!r}".format(
                parts.path
            )
        )
    if segments[-2] != "kernel":
        raise InvalidURIError(
            "path must end in '/kernel/<file>'; got {!r}".format(parts.path)
        )

    file = segments[-1]
    if file not in KERNEL_FILES:
        raise InvalidURIError(
            "file segment must be one of {}; got {!r}".format(
                sorted(KERNEL_FILES), file
            )
        )

    walnut_segments = segments[:-2]
    if not walnut_segments:
        raise InvalidURIError("walnut_path is empty")
    # Reject empty, ``.`` and ``..`` segments BEFORE decoding so the
    # error message references the raw form the client sent -- easier
    # for them to grep logs with. ``urllib.parse.urlsplit`` preserves
    # empty segments in the path (``//kernel/...`` -> ``["", "", ...]``),
    # which is what we want here for error reporting.
    decoded_segments: list[str] = []
    for raw in walnut_segments:
        if raw == "":
            raise InvalidURIError(
                "walnut_path contains an empty segment (double slash?): {!r}".format(
                    parts.path
                )
            )
        # ``unquote`` preserves non-encoded characters and decodes
        # ``%xx`` byte by byte via UTF-8. Any malformed percent
        # sequence falls through as-is in modern Python; we then
        # flag ``.`` and ``..`` on the decoded value for rejection.
        decoded = urllib.parse.unquote(raw)
        if decoded in (".", ".."):
            raise InvalidURIError(
                "walnut_path has illegal segment {!r}".format(decoded)
            )
        if "/" in decoded:
            # A percent-encoded ``%2F`` would decode to ``/`` and
            # sneak a directory separator through the boundary. The
            # path-safety layer (commonpath + realpath) would still
            # catch escape attempts, but rejecting here gives the
            # client a clearer error than a generic path-escape.
            raise InvalidURIError(
                "walnut_path segment must not contain '/': {!r}".format(decoded)
            )
        decoded_segments.append(decoded)

    walnut_path = "/".join(decoded_segments)
    # Apply NFC so the caller sees the same canonical form the encoder
    # would emit. Most inputs are already NFC (either because the
    # encoder emitted them or because the client normalized), but
    # clients that hand-build URIs from NFD source would otherwise
    # round-trip unstably.
    walnut_path = unicodedata.normalize("NFC", walnut_path)
    return walnut_path, file
