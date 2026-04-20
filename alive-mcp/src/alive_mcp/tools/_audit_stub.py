"""Compatibility re-export: the @audited decorator lives in ``alive_mcp.audit``.

Through T6-T11 this module carried the stub decorator; T12 promoted
the decorator to the real audit pipeline in :mod:`alive_mcp.audit` and
this shim just re-exports the symbol so existing tool imports
(``from alive_mcp.tools._audit_stub import audited``) keep working.

Forward-compat contract (still enforced -- see tests in
``tests/test_tools_walnut.py``):

* ``@audited`` and ``@audited(tool_name=...)`` both work.
* ``functools.wraps`` preserves ``__name__``, ``__doc__``, ``__module__``,
  and signature on the wrapped function.
* Sync and async callables both supported.
* Never raises synchronously -- audit-path failures are swallowed.
* ``__alive_tool_name__`` attribute is set on the wrapper for the
  recorded name.

If a future reorganization renames or re-homes the decorator, this
module is the seam existing code points at; update the import below
rather than asking every tool module to chase the new location.
"""
from __future__ import annotations

from alive_mcp.audit import audited

__all__ = ["audited"]
