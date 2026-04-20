"""Smoke test — forces ``python3 -m unittest discover tests`` to exit 0.

An empty tests/ directory causes unittest to exit 5 (no tests discovered).
The T1 acceptance wants an exit-0 signal that the test harness works. One
trivial test that always passes gives CI a green bar without over-specifying
behavior — real tests land in T13 (fn-10-60k.13) against the fixture World.
"""
from __future__ import annotations

import unittest


class SmokeTests(unittest.TestCase):
    def test_smoke(self) -> None:
        self.assertTrue(True)
