"""Smoke tests for the T1 scaffold.

These exist so ``python -m unittest discover tests`` exits 0 rather than 5
(the "no tests discovered" code). Subsequent tasks expand this suite —
follow the stdlib ``unittest`` convention used by the rest of the
``alivecontext/alive`` plugin (see ``claude-code/plugins/alive/tests/``).
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from alive_mcp import __version__
from alive_mcp.__main__ import main


class VersionTests(unittest.TestCase):
    def test_version_string_matches_pyproject(self) -> None:
        # If pyproject.toml ships a new version, this test fails loudly —
        # which is what we want, because a version bump should be intentional.
        self.assertEqual(__version__, "0.1.0")

    def test_main_bare_invocation_prints_version_and_returns_zero(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([])
        self.assertEqual(rc, 0)
        self.assertIn(__version__, buf.getvalue())

    def test_main_rejects_unknown_flag(self) -> None:
        # argparse exits with SystemExit(2) on unknown args. The scaffold
        # relies on argparse's default behaviour; this test locks that in so
        # a later refactor doesn't silently swallow argument errors.
        with self.assertRaises(SystemExit) as ctx:
            main(["--definitely-not-a-real-flag"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
