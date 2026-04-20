"""Helpers for the no-phone-home test suite (fn-10-60k.15 / T15).

What this module provides
-------------------------
1. :class:`NoNetworkMixin` — unittest mixin. Applies the same
   :func:`socket.socket.__init__` block that
   :mod:`tests.network_block.sitecustomize` applies to subprocesses,
   but to the TEST RUNNER's own process. This is the "belt" to the
   subprocess-level "braces": a test helper that accidentally opens a
   socket in the runner process (e.g. importing a lazy module that
   calls ``socket.gethostbyname`` at import time) fails immediately,
   before the test can mis-attribute blame to the server.
2. :func:`block_env` — return the environment dict extensions needed
   to push :mod:`tests.network_block` onto the child's
   :envvar:`PYTHONPATH`. Used by :mod:`test_no_phone_home` to spawn
   the server with the subprocess-side block active.

Why a mixin and not a pytest fixture
------------------------------------
The rest of the suite is stdlib :mod:`unittest` (see
:mod:`tests._test_helpers` for the convention). Adding a pytest
dependency just for fixture-shaped setup would diverge from the
plugin convention and bloat the dependency tree. A mixin class with
``setUp`` / ``tearDown`` gives identical power — Python MRO picks up
both the mixin's and the concrete ``TestCase``'s ``setUp``.

No side effects on import
-------------------------
Importing this module does NOT install the block. That happens ONLY
when a concrete :class:`unittest.TestCase` subclasses
:class:`NoNetworkMixin` and its ``setUp`` runs. Other test modules
that import helpers from here (none currently exist, but keeping the
discipline) are unaffected.
"""
from __future__ import annotations

import os
import pathlib
import socket
from typing import Mapping


# Re-export the same sentinel string :mod:`tests.network_block.sitecustomize`
# emits so callers can assert on it without importing the subprocess
# module directly (which would import the real site hook into the
# TEST runner and is not what we want).
BLOCKED_MSG = (
    "network disabled in alive-mcp test run (sitecustomize socket block)"
)


_NETWORK_BLOCK_DIR = (
    pathlib.Path(__file__).resolve().parent / "network_block"
)


def block_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an env dict with ``PYTHONPATH`` prepended for the socket block.

    Parameters
    ----------
    base_env:
        Starting environment. Pass ``None`` to clone :data:`os.environ`;
        pass an explicit mapping (usually the env built by
        :func:`tests._test_helpers._subprocess_env`) to layer the
        network block on top of the existing subprocess env without
        losing any prior customization.

    Returns
    -------
    dict[str, str]
        A new dict with ``PYTHONPATH`` prepended with the network-block
        dir. Every other key is preserved. Safe to pass directly to
        :class:`subprocess.Popen` / :func:`subprocess.run`.

    Notes
    -----
    We prepend (not append) the network-block dir so Python's site
    machinery finds *our* ``sitecustomize.py`` before any other
    ``sitecustomize`` shipped by a distro (rare but possible on
    packaged Debian/Ubuntu Pythons). Prepending also means a
    downstream env add to ``PYTHONPATH`` (e.g. adding the repo's
    ``src/`` via ``_test_helpers._subprocess_env``) does not clobber
    the block dir.
    """
    env = dict(base_env) if base_env is not None else dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    block_dir = str(_NETWORK_BLOCK_DIR)
    env["PYTHONPATH"] = (
        block_dir + (os.pathsep + existing if existing else "")
    )
    return env


class NoNetworkMixin:
    """unittest mixin that blocks socket creation in the test runner process.

    Use by inheriting alongside :class:`unittest.TestCase`::

        class MyTests(NoNetworkMixin, unittest.TestCase):
            def test_something(self) -> None:
                ...

    The mixin's :meth:`setUp` / :meth:`tearDown` install and remove
    the block around each test. Concrete ``setUp`` overrides should
    call ``super().setUp()`` first so the block is active before
    their own setup runs.

    Catches same-process socket opens
    ---------------------------------
    This ONLY patches the test runner's :mod:`socket`. Subprocesses
    spawned by the test (e.g. via :func:`tests._test_helpers.start_server`
    combined with :func:`block_env`) get their block from
    :mod:`tests.network_block.sitecustomize` via :envvar:`PYTHONPATH`.
    Both layers are independent; either one firing produces a
    :class:`RuntimeError` with the same :data:`BLOCKED_MSG`.

    Order of operations for the server subprocess test
    --------------------------------------------------
    :class:`tests.test_no_phone_home.NoPhoneHomeTests` inherits this
    mixin AND spawns subprocesses. The runner-side block (this mixin)
    catches the test-harness opening a socket; the subprocess-side
    block (``sitecustomize``) catches the server opening one. The two
    together cover the end-to-end claim.
    """

    _saved_socket_init = None  # type: ignore[var-annotated]
    _saved_create_connection = None  # type: ignore[var-annotated]

    # Address families that can phone home. Mirrors the subprocess
    # block in :mod:`tests.network_block.sitecustomize`. AF_UNIX and
    # other local-IPC families are allowed through so asyncio /
    # socketpair startup paths in the test runner do not break.
    _PHONE_HOME_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})

    @classmethod
    def _family_from_args(cls, args, kwargs):  # type: ignore[no-untyped-def]
        """Mirror :func:`tests.network_block.sitecustomize._resolve_family`."""
        if "fileno" in kwargs and kwargs["fileno"] is not None:
            return None
        if len(args) >= 4 and args[3] is not None:
            return None
        if "family" in kwargs:
            return kwargs["family"]
        if args:
            return args[0]
        return socket.AF_INET

    @staticmethod
    def _blocked_create_connection(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError(BLOCKED_MSG)

    def setUp(self) -> None:  # noqa: D401 - unittest hook naming
        # Save the originals so ``tearDown`` can restore them. Without
        # the save/restore, a subsequent non-mixin test in the same
        # process would inherit the block and fail for surprising
        # reasons.
        super().setUp()  # type: ignore[misc]
        original_init = socket.socket.__init__
        type(self)._saved_socket_init = original_init
        type(self)._saved_create_connection = socket.create_connection

        phone_home = type(self)._PHONE_HOME_FAMILIES
        resolve = type(self)._family_from_args

        def _blocked_init(sock_self, *args, **kwargs):  # type: ignore[no-untyped-def]
            family = resolve(args, kwargs)
            if family in phone_home:
                raise RuntimeError(BLOCKED_MSG)
            original_init(sock_self, *args, **kwargs)

        socket.socket.__init__ = _blocked_init  # type: ignore[method-assign]
        socket.create_connection = type(self)._blocked_create_connection  # type: ignore[assignment]

    def tearDown(self) -> None:  # noqa: D401 - unittest hook naming
        # Restore the originals. Catch the odd case where a test
        # reassigned ``socket.socket.__init__`` itself — that would
        # indicate a misbehaving helper, but we still want cleanup
        # to succeed so later tests aren't affected.
        saved_init = type(self)._saved_socket_init
        saved_cc = type(self)._saved_create_connection
        if saved_init is not None:
            socket.socket.__init__ = saved_init  # type: ignore[method-assign]
        if saved_cc is not None:
            socket.create_connection = saved_cc  # type: ignore[assignment]
        super().tearDown()  # type: ignore[misc]
