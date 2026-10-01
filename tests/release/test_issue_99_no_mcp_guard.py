"""Issue #99: ALIVE must not gate MCP / external tools.

A PreToolUse hook that returns permissionDecision "ask" outranks Claude Code's
own permission rules, allow-lists, auto mode and site grants. External and
browser tools follow Claude Code's own permission settings instead.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "alive"


class NoMcpGuardTest(unittest.TestCase):
    def test_no_pretooluse_hook_matches_mcp_tools(self) -> None:
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        for entry in hooks.get("PreToolUse", []):
            matcher = entry.get("matcher", "")
            for tool in ("mcp__claude-in-chrome__computer", "mcp__Claude_Browser__navigate", "mcp__gmail__send_email"):
                import re
                self.assertIsNone(re.fullmatch(matcher, tool), f"PreToolUse matcher {matcher!r} catches {tool}")

    def test_external_guard_script_removed(self) -> None:
        self.assertFalse((PLUGIN / "hooks" / "scripts" / "alive-external-guard.sh").exists())

    def test_docs_do_not_claim_an_external_guard(self) -> None:
        for name in ("SECURITY.md", "PERMISSIONS.md"):
            text = (ROOT / name).read_text(encoding="utf-8").lower()
            self.assertNotIn("external-guard", text, name)


if __name__ == "__main__":
    unittest.main()
