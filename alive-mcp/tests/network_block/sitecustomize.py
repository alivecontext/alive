"""Block all socket creation at interpreter startup (T15 layer 3).

How this gets loaded
--------------------
Python's :mod:`site` module auto-imports a module named
``sitecustomize`` at interpreter startup if one is found on
``sys.path``. We exploit that: CI (and any test that wants to
constrain a subprocess) spawns the alive-mcp server with
``PYTHONPATH=tests/network_block:<existing>`` so this file sits at the
front of ``sys.path`` and Python's ``site`` machinery imports it
before any user code runs.

What it does
------------
Monkeypatches :meth:`socket.socket.__init__` so every attempt to
construct a socket (which is the universal path for every transport
layer built on top of the stdlib: HTTP, HTTPS, DNS, raw TCP/UDP)
raises :class:`RuntimeError` before any file descriptor is opened.
We prefer patching ``__init__`` over patching
:func:`socket.socket.connect` / :func:`socket.socket.sendto` because
a blocked ``__init__`` catches connection-less probes (e.g.
``getaddrinfo`` callers that construct a UDP socket for DNS) as well
as connected ones.

Why this constrains the SERVER, not just the test runner
--------------------------------------------------------
The MCP server ships as a Python subprocess spawned by the Inspector
(or, in these tests, by :class:`subprocess.Popen`). Monkeypatching
:mod:`socket` in the TEST runner does nothing to that child process —
a child Python has its own fresh :mod:`socket` module. By pushing
the block through :envvar:`PYTHONPATH`, the child inherits the
``sitecustomize`` hook and patches its OWN :mod:`socket` module on
startup, before the first tool handler runs. That is the layer-3
guarantee the no-phone-home spec demands: the SERVER PROCESS cannot
open a socket even if a future tool handler tries to.

Allowlist philosophy
--------------------
There is no allowlist. The no-phone-home invariant says the server
must not open ANY socket during stdio operation (MCP's stdio
transport reads from stdin / writes to stdout — pipes, not sockets).
If a future tool legitimately needs the network, that will be a
separate design review and an explicit unblock, not a sitecustomize
allowlist crack that quietly lets it through.

AF_UNIX handling
----------------
AF_UNIX sockets cannot leave the host — the kernel constrains them
to local IPC. :func:`socket.socketpair` (used internally by
:mod:`asyncio` on Unix for the event loop's self-pipe wakeup
mechanism) also creates local-only pairs. Neither can phone home.
We therefore ALLOW AF_UNIX and bypass the block for anything
socketpair constructs; blocking them would break asyncio event-loop
startup (:mod:`mcp` uses :func:`asyncio.run` in its stdio runner)
without adding any security value.

What IS blocked
---------------
* ``AF_INET`` / ``AF_INET6`` — every TCP/UDP connection over IPv4
  or IPv6. DNS probes (UDP/53), HTTP/HTTPS, raw IP, every phone-
  home vector we care about lives here.
* The block fires at ``socket.socket.__init__``, before the kernel
  allocates an FD. Blocking at construction (not at ``connect``)
  catches listeners as well as clients, and catches code that only
  opens the socket to call ``getsockname``.

What is ALLOWED
---------------
* ``AF_UNIX`` — local IPC only.
* Other esoteric families (``AF_NETLINK``, ``AF_ROUTE``, etc.) —
  same-host kernel comms, not phone-home. The allow-list is "not
  AF_INET and not AF_INET6" rather than "is AF_UNIX" so a legitimate
  but uncommon family is not inadvertently blocked.
"""
from __future__ import annotations

import os
import socket as _socket

# Preserve the real constructor so the helper can restore it in
# diagnostic paths if ever needed. We do not expose a formal "unblock"
# API — the only correct way to unblock is to remove the PYTHONPATH
# entry and spawn a fresh interpreter.
_ORIGINAL_SOCKET_INIT = _socket.socket.__init__

# Sentinel error message. The :mod:`tests.test_no_phone_home` suite
# greps the server's stderr for this exact substring to prove the
# block fired — any reword MUST update that test too.
_BLOCKED_MSG = (
    "network disabled in alive-mcp test run (sitecustomize socket block)"
)


# Address families that CAN phone home. Everything else (AF_UNIX,
# AF_NETLINK, etc.) is host-local by kernel design and poses no
# exfil risk; allowing them is necessary because asyncio's event
# loop uses ``socket.socketpair()`` (AF_UNIX on Unix) during startup.
_PHONE_HOME_FAMILIES = {
    _socket.AF_INET,
    _socket.AF_INET6,
}


def _resolve_family(args, kwargs):  # type: ignore[no-untyped-def]
    """Extract the address family from ``socket.socket(...)`` call args.

    Mirrors the stdlib signature:
    ``socket.socket(family=AF_INET, type=SOCK_STREAM, proto=0, fileno=None)``.
    A caller that passes ``fileno=<fd>`` to wrap an existing FD (e.g.
    :func:`socket.socketpair` calls :func:`socket.socket` with
    ``fileno`` set) bypasses family inspection — but those callers
    are always local-IPC (the kernel gave them the FD); they are
    never remote. We detect the ``fileno`` case and allow it.
    """
    if "fileno" in kwargs and kwargs["fileno"] is not None:
        return None  # caller is wrapping an existing FD; allow.
    if len(args) >= 4 and args[3] is not None:
        return None
    if "family" in kwargs:
        return kwargs["family"]
    if args:
        return args[0]
    return _socket.AF_INET  # stdlib default


def _blocked_socket_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Refuse to construct a phone-home-capable socket.

    Raises :class:`RuntimeError` with :data:`_BLOCKED_MSG` before any
    kernel-level socket FD is opened when the address family is
    AF_INET / AF_INET6. Allows local-IPC families (AF_UNIX, etc.) and
    FD-wrapping calls through to the real constructor.

    The error propagates up through whatever code tried to call
    ``socket.socket(...)``; if that code catches :class:`OSError` but
    not :class:`RuntimeError`, the error surfaces at the top of the
    call stack — which is what we want, so the subprocess's stderr
    captures the block.

    We deliberately do NOT call the original ``__init__`` on the
    blocked path — letting the constructor succeed and then blocking
    ``connect`` would still allow DNS probes via
    :func:`socket.getaddrinfo` to open a socket momentarily. The
    safest point of interception is before any FD is allocated for
    an AF_INET/AF_INET6 family.
    """
    family = _resolve_family(args, kwargs)
    if family in _PHONE_HOME_FAMILIES:
        raise RuntimeError(_BLOCKED_MSG)
    # Local-IPC family or FD-wrap: fall through to the real init.
    _ORIGINAL_SOCKET_INIT(self, *args, **kwargs)


# Install the block. Order matters: this MUST run before any user
# code can import the :mod:`socket` module and cache a reference to
# the original ``socket`` class. Python's ``site`` machinery runs us
# during interpreter startup (after the stdlib is initialized, before
# ``__main__`` runs), which is the right moment.
_socket.socket.__init__ = _blocked_socket_init  # type: ignore[method-assign]


# Also stub :func:`socket.create_connection`, which is the higher-level
# helper most HTTP libraries reach for. ``create_connection`` itself
# calls ``socket.socket(...)`` internally in modern CPython, so the
# ``__init__`` patch above catches it transitively. But some forks /
# monkey-patching frameworks (gevent) replace ``create_connection``
# with their own implementation that constructs the socket in C and
# sidesteps the Python ``__init__`` hook. Shadowing the symbol at the
# module level catches that class of end-run too.
def _blocked_create_connection(*args, **kwargs):  # type: ignore[no-untyped-def]
    raise RuntimeError(_BLOCKED_MSG)


_socket.create_connection = _blocked_create_connection  # type: ignore[assignment]


# Optionally surface a one-line stderr breadcrumb so a CI test run's
# logs confirm the block is active, even if no attempted socket ever
# triggers the error. Gated on an envvar so it does not contaminate
# the MCP stdio stdout during normal operation (stderr is safe;
# alive-mcp logs to stderr too).
if os.environ.get("ALIVE_MCP_NETWORK_BLOCK_VERBOSE"):
    import sys as _sys

    print(
        "[alive-mcp network_block] socket.socket.__init__ replaced; "
        "all network is disabled for this process",
        file=_sys.stderr,
        flush=True,
    )
