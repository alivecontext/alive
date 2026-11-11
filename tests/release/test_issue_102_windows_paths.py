"""Regression tests for Windows path handling (3.2.5).

#102: the statusline walked up the folder tree until it reached ``/``,
which never happens on a ``C:`` path, so it looped forever on native
Windows. The guard hooks also compared Claude Code's native
``C:\\Users\\...`` file paths with the world root in MSYS ``/c/...`` form,
so they never matched.

These run Git Bash's code paths on any OS by setting ``MSYSTEM``, which is
how alive-common.sh and the statusline detect Windows.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "alive"
HOOKS = PLUGIN / "hooks" / "scripts"
STATUSLINE = PLUGIN / "statusline" / "alive-statusline.sh"

WINDOWS_ENV = {**os.environ, "MSYSTEM": "MINGW64"}

# Resolve bash from PATH: on Windows a bare "bash" goes through CreateProcess,
# which searches System32 first and finds the WSL launcher, not Git Bash.
BASH = shutil.which("bash") or "/bin/bash"


class StatuslineWalkUpEnds(unittest.TestCase):
    def run_statusline(self, cwd: str) -> subprocess.CompletedProcess:
        payload = json.dumps({
            "cwd": cwd,
            "model": {"display_name": "Test"},
            "session_id": "test-102",
        })
        return subprocess.run(
            [BASH, str(STATUSLINE)],
            input=payload, capture_output=True, text=True,
            env=WINDOWS_ENV, timeout=20,
        )

    def test_windows_shaped_paths_finish(self) -> None:
        for cwd in (
            r"C:\Users\Ada\alive",
            "C:/Users/Ada/alive",
            r"C:\\Users\\Ada\\alive",
            "/c/Users/Ada/alive",
        ):
            with self.subTest(cwd=cwd):
                # A TimeoutExpired here is the #102 loop.
                result = self.run_statusline(cwd)
                self.assertEqual(result.returncode, 0, result.stderr)


class HookFilePathNormalises(unittest.TestCase):
    def file_path(self, raw: str, *flags: str, windows: bool = True) -> str:
        script = (
            f'source "{(HOOKS / "alive-common.sh").as_posix()}"; '
            f'HOOK_INPUT={json.dumps(json.dumps({"tool_input": {"file_path": raw}}))}; '
            f'hook_file_path {" ".join(flags)}'
        )
        env = WINDOWS_ENV if windows else {
            k: v for k, v in os.environ.items() if k not in ("MSYSTEM", "OSTYPE")
        }
        # The script goes in an env var, not argv: on Windows the MSYS runtime
        # re-parses the command line and mangles quotes and backslashes.
        env = {**env, "ALIVE_TEST_SCRIPT": script}
        result = subprocess.run(
            [BASH, "-c", 'eval "$ALIVE_TEST_SCRIPT"'], capture_output=True, text=True,
            env=env, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_windows_path_matches_msys_world_root(self) -> None:
        self.assertEqual(
            self.file_path(r"C:\Users\Ada\alive\_kernel\log.md"),
            "/c/Users/Ada/alive/_kernel/log.md",
        )

    def test_slashes_mode_keeps_the_drive_for_native_python(self) -> None:
        self.assertEqual(
            self.file_path(r"C:\Users\Ada\alive\_kernel\log.md", "--slashes"),
            "C:/Users/Ada/alive/_kernel/log.md",
        )

    def test_unix_paths_are_unchanged(self) -> None:
        self.assertEqual(
            self.file_path("/home/ada/alive/_kernel/log.md", windows=False),
            "/home/ada/alive/_kernel/log.md",
        )


if __name__ == "__main__":
    unittest.main()
