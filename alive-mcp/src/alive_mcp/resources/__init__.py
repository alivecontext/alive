"""MCP resource surfaces for alive-mcp (fn-10-60k.10 / T10).

This package hosts resource handlers -- the host-controlled attach/
subscribe surface of the MCP protocol. v0.1 exposes exactly one family:
the four kernel files per walnut, served via the ``alive://`` URI scheme
(see :mod:`alive_mcp.uri`).

Resources vs tools (the duplication is intentional)
---------------------------------------------------
Tools and resources both serve walnut kernel data in v0.1. That is
DELIBERATE. The two primitives have different control surfaces:

* **Resources** -- HOST-controlled. The MCP client's UI (Claude
  Desktop's "attach as context", Cursor's resource picker) enumerates
  them, the human picks one, and the client attaches or subscribes.
  ``resources/updated`` notifications drive reactive UIs.
* **Tools** -- MODEL-controlled. The model issues an imperative call
  with parameters (``read_walnut_kernel(walnut="x", file="log")``) to
  pull data just-in-time during a task.

Same bytes on disk, two doors to reach them. Each door is authoritative
for its use case. A single-primitive design (tools only, or resources
only) would forfeit one of the two workflows -- the model-driven
parameterized query surface OR the human-driven attach surface -- with
no offsetting benefit.

Module layout
-------------
* :mod:`alive_mcp.resources.kernel` -- the kernel-file resources.
  Exposes ``register(server)`` which wires low-level ``list_resources``
  and ``read_resource`` handlers onto the FastMCP instance.

Future tasks:
* T11 adds ``subscribe_resource`` / ``unsubscribe_resource`` / watchdog
  observers. The capability for ``subscribe: true`` is already
  advertised in T5's capability override -- T11 just implements
  delivery.
* v0.2 adds bundle-manifest resources at
  ``alive://walnut/{walnut_path}/bundle/{bundle_path}/manifest``.
"""

from __future__ import annotations

__all__: list[str] = []
