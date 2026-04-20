"""Pure (print-free, exit-free) helpers extracted from ALIVE plugin CLIs.

The upstream ``project.py`` and ``tasks.py`` scripts in
``claude-code/plugins/alive/scripts/`` are CLIs: they call ``print()`` on
stdout and ``sys.exit()`` on error. Importing them into a long-lived stdio
JSON-RPC server is dangerous -- stdout writes corrupt MCP framing, and
``sys.exit`` kills the whole server process.

This module extracts the pure LOGIC of those CLIs into import-safe helpers
that raise typed exceptions instead of printing/exiting. The exception
taxonomy is intentionally narrow:

- ``WorldNotFoundError`` -- discovery walk failed to locate a World root.
- ``KernelFileError``    -- a ``_kernel/*`` file is present on disk but
                            unreadable (permission, encoding, post-isfile
                            I/O). Missing files are NOT errors here --
                            see the class docstring for the full contract.
- ``MalformedYAMLWarning`` -- a manifest or YAML/JSON blob could not be
                              parsed or has an unexpected shape; the
                              caller decides whether to swallow or
                              propagate. ``Warning`` is the stdlib base so
                              the ``warnings`` module can optionally
                              capture these.

See ``VENDORING.md`` (one directory up) for the source commit hash, the
extracted-function list, and the refresh policy.
"""

from __future__ import annotations


class WorldNotFoundError(Exception):
    """Raised when walking upward from a candidate path finds no World root.

    A World root is a directory containing ``.alive/``. Callers that need to
    resolve a walnut's enclosing World should catch this and surface
    ``ERR_NO_WORLD`` to the client per the v0.1 error taxonomy (fn-10-60k.4).
    """


class KernelFileError(Exception):
    """Raised when a ``_kernel/`` file is present on disk but unreadable.

    Covers permission errors, bad UTF-8 encoding, TOCTOU races where
    ``open()`` fails AFTER an ``isfile()`` check passed (other than
    ``ENOENT``), and any other ``OSError`` / ``UnicodeDecodeError`` that
    prevents reading an existing file.

    **Does NOT fire on "missing on disk".** Most helpers treat missing
    kernel files as non-errors -- a fresh walnut legitimately has no
    ``log.md`` yet, no ``tasks.json`` yet, etc. `parse_log` returns an
    empty projection on missing log; `read_unscoped_tasks` returns an
    empty list on missing tasks file. Callers that need "missing" as a
    signal should check the returned shape (empty log with no entries,
    empty task list) rather than catching this exception.

    Callers should translate this exception into
    ``ERR_KERNEL_FILE_CORRUPT`` per the v0.1 error taxonomy (T4).
    ``ERR_KERNEL_FILE_MISSING`` is emitted by the MCP tool layer based on
    tool-level preconditions, not by this exception.
    """


class MalformedYAMLWarning(Warning):
    """Emitted when a structured-text source cannot be read or parsed.

    Despite the "YAML" in the name (retained for API stability -- the
    original use site was a YAML manifest), the extracted helpers emit
    this warning for every structured-text read failure they swallow:

    - YAML bundle manifests (`context.manifest.yaml`)
    - YAML squirrel entries (`.alive/_squirrels/*.yaml`)
    - JSON task files (`_kernel/tasks.json`, `bundles/*/tasks.json`)
    - JSON completed files (`_kernel/completed.json`)
    - JSON child projections (`_kernel/now.json`, `_kernel/_generated/now.json`)

    Uses ``Warning`` rather than ``Exception`` because the upstream CLIs
    tolerate malformed files by skipping them; extracted helpers follow
    the same policy so a single drifted file doesn't crash a projection.
    Callers that want hard failures can install a warning filter:
    ``warnings.simplefilter("error", MalformedYAMLWarning)``.
    """


__all__ = [
    "WorldNotFoundError",
    "KernelFileError",
    "MalformedYAMLWarning",
]
