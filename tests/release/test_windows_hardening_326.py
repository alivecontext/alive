"""Regression tests for the 3.2.6 Windows hardening.

Each class matches one fix in CHANGELOG 3.2.6 and REPORT.md's risk list:

- Risk 6: bin/alive called python3 directly.
- Risk 7: the Microsoft Store python3 stub (on PATH, exits 49).
- Risk 11: repo-detect never matched C:\\ against /c/.
- Sweep: world walk-up, log guardian prefix match, case-insensitive
  world match, statusline JSON-escaped paths and Python pick.
- Risk 13: alive-archive-enforcer.sh quoting (still unregistered).

Like test_issue_102_windows_paths.py these run Git Bash's code paths on any
OS by setting MSYSTEM. Python is hidden by running with a PATH made of a
"tools" folder (symlinks to the coreutils the scripts need, no python, py or
node) plus fake interpreters written per test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "alive"
HOOKS = PLUGIN / "hooks" / "scripts"
COMMON = HOOKS / "alive-common.sh"
BIN_ALIVE = PLUGIN / "bin" / "alive"
STATUSLINE = PLUGIN / "statusline" / "alive-statusline.sh"
REAL_PY = sys.executable
BASH = shutil.which("bash") or "/bin/bash"

TOOLS = (
    "awk basename cat chmod cksum cmp cp cut date dirname env find grep head "
    "id ln ls mkdir mktemp mv readlink sed sort stat tail tee timeout touch tr "
    "uname wc xargs"
).split()

STORE_STUB = """#!/bin/sh
echo "Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases." >&2
exit 49
"""


def write_exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


class Sandbox:
    """A PATH with coreutils but no Python, plus optional fake interpreters."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.tools = base / "tools"
        self.tools.mkdir()
        for name in TOOLS:
            found = shutil.which(name)
            if found:
                # Keep the real file name (dirname.exe on Windows).
                (self.tools / Path(found).name).symlink_to(found)
        self.fake = base / "fake"
        self.fake.mkdir()
        # Store stubs live under ...\Microsoft\WindowsApps on Windows.
        self.store = base / "Microsoft" / "WindowsApps"
        self.store.mkdir(parents=True)

    def store_stub(self, name: str) -> None:
        write_exe(self.store / name, STORE_STUB)

    def real(self, name: str) -> None:
        write_exe(self.fake / name, f'#!/bin/sh\nexec "{REAL_PY}" "$@"\n')

    def py_launcher(self) -> None:
        write_exe(
            self.fake / "py",
            f'#!/bin/sh\n[ "$1" = "-3" ] && shift\nexec "{REAL_PY}" "$@"\n',
        )

    def env(self, windows: bool = True, **extra: str) -> dict:
        env = {
            k: v for k, v in os.environ.items()
            if k not in ("MSYSTEM", "OSTYPE", "ALIVE_PYTHON", "BASH_FUNC_python3%%")
        }
        env["PATH"] = os.pathsep.join([str(self.fake), str(self.store), str(self.tools)])
        env["HOME"] = str(self.base / "home")
        if windows:
            env["MSYSTEM"] = "MINGW64"
        env.update(extra)
        return env


class SandboxCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.box = Sandbox(self.base)

    def tearDown(self) -> None:
        self._tmp.cleanup()


# -- Risk 6: bin/alive ---------------------------------------------------------

class BinAliveFindsAPython(SandboxCase):
    """bin/alive tries python3, then py -3, then python, and says so if none."""

    def setUp(self) -> None:
        super().setUp()
        # A copy of the plugin's bin/ next to a scripts/cli.py that just
        # reports it ran, so the test doesn't depend on the real CLI.
        plugin = self.base / "plugin"
        (plugin / "bin").mkdir(parents=True)
        (plugin / "scripts").mkdir()
        shutil.copy2(BIN_ALIVE, plugin / "bin" / "alive")
        (plugin / "scripts" / "cli.py").write_text(
            "import sys\nprint('CLI OK', ' '.join(sys.argv[1:]))\n", encoding="utf-8"
        )
        self.alive = plugin / "bin" / "alive"

    def run_alive(self, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [BASH, str(self.alive), "doctor", "--check"],
            capture_output=True, text=True, env=self.box.env(**env), timeout=30,
        )

    def test_python3_is_used_when_it_runs(self) -> None:
        self.box.real("python3")
        result = self.run_alive()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLI OK doctor --check", result.stdout)

    def test_store_stub_python3_falls_back_to_py_launcher(self) -> None:
        self.box.store_stub("python3")
        self.box.py_launcher()
        result = self.run_alive()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLI OK doctor --check", result.stdout)

    def test_no_python3_falls_back_to_python(self) -> None:
        self.box.real("python")
        result = self.run_alive()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLI OK", result.stdout)

    def test_nothing_runs_gives_a_clear_notice(self) -> None:
        self.box.store_stub("python3")
        self.box.store_stub("python")
        result = self.run_alive()
        self.assertEqual(result.returncode, 127)
        self.assertIn("ALIVE needs Python 3", result.stderr)
        self.assertIn("winget install 9NQ7512CXL7T", result.stderr)
        self.assertIn("App execution aliases", result.stderr)

    def test_alive_python_override_still_wins(self) -> None:
        result = self.run_alive(ALIVE_PYTHON=REAL_PY)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLI OK", result.stdout)


# -- Risk 7: the Store stub, detected once in alive-common.sh -----------------

class CommonInterpreterPick(SandboxCase):
    def pick(self) -> dict:
        script = (
            f'source "{COMMON}"; '
            'printf "rt=%s\\nstub=%s\\n" "$ALIVE_JSON_RT" "$ALIVE_PY_STUB"; '
            'if [ "$ALIVE_JSON_RT" = python3 ]; then python3 -c "print(\'ran=yes\')"; fi'
        )
        result = subprocess.run(
            [BASH, "-c", script], capture_output=True, text=True,
            env=self.box.env(), timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )

    def test_store_stub_is_skipped_for_py_launcher(self) -> None:
        self.box.store_stub("python3")
        self.box.py_launcher()
        out = self.pick()
        self.assertEqual(out["rt"], "python3")
        self.assertEqual(out["stub"], "1")
        self.assertEqual(out.get("ran"), "yes")

    def test_store_stub_is_skipped_for_python(self) -> None:
        self.box.store_stub("python3")
        self.box.real("python")
        out = self.pick()
        self.assertEqual(out["rt"], "python3")
        self.assertEqual(out.get("ran"), "yes")

    def test_only_stubs_leaves_no_runtime(self) -> None:
        self.box.store_stub("python3")
        self.box.store_stub("python")
        out = self.pick()
        self.assertEqual(out["rt"], "")
        self.assertEqual(out["stub"], "1")

    def test_session_start_names_the_store_stub(self) -> None:
        self.box.store_stub("python3")
        self.box.store_stub("python")
        result = subprocess.run(
            [BASH, str(HOOKS / "alive-session-new.sh")],
            input="{}", capture_output=True, text=True,
            env=self.box.env(), timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        message = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Microsoft Store placeholder", message)
        self.assertIn("App execution aliases", message)

    def test_every_hook_takes_the_shared_pick(self) -> None:
        # No hook may probe python3 by existence alone any more.
        for script in sorted(HOOKS.glob("*.sh")):
            if script == COMMON:
                continue  # the one place the pick lives
            with self.subTest(script=script.name):
                self.assertNotIn(
                    "command -v python3", script.read_text(encoding="utf-8"),
                )


# -- Shared helpers: every Windows path shape ---------------------------------

def run_common(snippet: str, windows: bool = True, **env: str) -> str:
    base = {k: v for k, v in os.environ.items() if k not in ("MSYSTEM", "OSTYPE")}
    if windows:
        base["MSYSTEM"] = "MINGW64"
    base.update(env)
    result = subprocess.run(
        [BASH, "-c", f'source "{COMMON}"; {snippet}'],
        capture_output=True, text=True, env=base, timeout=30,
    )
    if result.returncode not in (0, 1):
        raise AssertionError(result.stderr)
    return result.stdout


class PathHelpers(unittest.TestCase):
    SHAPES = (
        r"C:\Users\Ada\alive",
        "C:/Users/Ada/alive",
        r"C:\\Users\\Ada\\alive",
        "/c/Users/Ada/alive",
        "c:/users/ada/alive/",
    )

    def test_msys_form_for_every_shape(self) -> None:
        for shape in self.SHAPES:
            with self.subTest(shape=shape):
                out = run_common(f"alive_msys_path {json.dumps(shape)}")
                self.assertEqual(out.lower(), "/c/users/ada/alive")

    def test_native_form_for_python(self) -> None:
        self.assertEqual(
            run_common("alive_native_path /c/Users/Ada/alive"), "C:/Users/Ada/alive",
        )
        self.assertEqual(run_common("alive_native_path /c"), "C:/")
        # Multi-letter first segments are not drives.
        self.assertEqual(run_common("alive_native_path /home/ada"), "/home/ada")

    def test_within_ignores_case_and_respects_boundaries(self) -> None:
        for shape in self.SHAPES:
            with self.subTest(shape=shape):
                out = run_common(
                    f'alive_path_within /c/Users/Ada/alive {json.dumps(shape + "/02_Life")}'
                    ' && echo in || echo out'
                )
                self.assertEqual(out.strip(), "in")
        out = run_common(
            r'alive_path_within /c/Users/Ada/alive "C:\Users\Ada\alive2" && echo in || echo out'
        )
        self.assertEqual(out.strip(), "out")

    @unittest.skipIf(os.name == "nt", "Git Bash is always the Windows shell")
    def test_unix_compare_stays_case_sensitive(self) -> None:
        out = run_common(
            "alive_path_within /home/ada/alive /home/ada/ALIVE/x && echo in || echo out",
            windows=False,
        )
        self.assertEqual(out.strip(), "out")

    def test_hook_file_path_takes_world_root_spelling(self) -> None:
        payload = json.dumps({"tool_input": {"file_path": r"c:\users\ada\ALIVE\.alive\agents.md"}})
        out = run_common(
            f"WORLD_ROOT=/c/Users/Ada/alive; HOOK_INPUT={json.dumps(payload)}; hook_file_path"
        )
        self.assertEqual(out, "/c/Users/Ada/alive/.alive/agents.md")


# -- Sweep: the world walk-up in alive-common.sh ------------------------------

class WorldWalkUpFromWindowsCwd(unittest.TestCase):
    """find_world's cwd walk-up took dirname of C:\\Users\\..., which is ".",
    so it only ever checked the leaf. A session started in a subfolder of the
    world found nothing."""

    def walk(self, cwd: str) -> str:
        with tempfile.TemporaryDirectory() as home:
            snippet = (
                # Stand-ins: only /c/Users/Ada/alive is a world; allow it.
                'is_valid_world_root() { [ "$1" = /c/Users/Ada/alive ]; }; '
                'validate_path_choice() { printf "allow\\tworld\\t-"; }; '
                f'HOOK_CWD={json.dumps(cwd)}; '
                'find_world && printf "%s" "$WORLD_ROOT"'
            )
            return run_common(snippet, HOME=home, ALIVE_WORLD_ROOT_OVERRIDE="")

    def test_subfolder_cwd_finds_the_world(self) -> None:
        for cwd in (
            r"C:\Users\Ada\alive\04_Ventures\shop",
            "C:/Users/Ada/alive/04_Ventures/shop",
            "/c/Users/Ada/alive/04_Ventures/shop",
        ):
            with self.subTest(cwd=cwd):
                self.assertEqual(self.walk(cwd), "/c/Users/Ada/alive")

    def test_walk_outside_any_world_ends(self) -> None:
        # Terminates (no timeout) and finds nothing.
        self.assertEqual(self.walk(r"D:\elsewhere\deep\down"), "")


# -- Risk 11 + sweep: repo-detect ---------------------------------------------

def make_world(base: Path) -> Path:
    world = base / "world"
    (world / ".alive" / "_squirrels").mkdir(parents=True)
    (world / ".alive" / "preferences.yaml").write_text(
        "github_star_ask: false\n", encoding="utf-8"
    )
    for domain in ("01_Archive", "02_Life", "03_Inbox", "04_Ventures", "05_Experiments"):
        (world / domain).mkdir()
    return world


class RepoDetect(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(os.path.realpath(self._tmp.name))
        self.world = make_world(self.base)
        self.repo = self.base / "code" / "shop"
        self.repo.mkdir(parents=True)
        (self.base / "code" / "shop2").mkdir()
        kernel = self.world / "04_Ventures" / "shop" / "_kernel"
        kernel.mkdir(parents=True)
        (kernel / "key.md").write_text(
            f"---\ntype: venture\ndev:\n  local_path: {self.repo}\n---\n# shop\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def detect(self, cwd: Path, windows: bool) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in ("MSYSTEM", "OSTYPE")}
        if windows:
            env["MSYSTEM"] = "MINGW64"
        env.update({
            "ALIVE_WORLD_ROOT_OVERRIDE": str(self.world),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN),
            "HOME": str(self.base),
        })
        payload = json.dumps({
            "session_id": "rd-test", "cwd": str(cwd), "hook_event_name": "SessionStart",
        })
        return subprocess.run(
            [BASH, str(HOOKS / "alive-repo-detect.sh")], input=payload,
            capture_output=True, text=True, env=env, timeout=30,
        )

    def test_repo_cwd_is_detected(self) -> None:
        for windows in (False, True):
            with self.subTest(windows=windows):
                result = self.detect(self.repo / "src", windows)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("[[shop]]", result.stdout)

    def test_sibling_folder_with_same_prefix_is_not_a_match(self) -> None:
        result = self.detect(self.base / "code" / "shop2", windows=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("[[shop]]", result.stdout)

    def test_cwd_inside_world_is_skipped(self) -> None:
        result = self.detect(self.world / "02_Life", windows=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_paths_reach_python_through_env_not_the_script(self) -> None:
        text = (HOOKS / "alive-repo-detect.sh").read_text(encoding="utf-8")
        self.assertNotIn("'$WORLD_ROOT'", text)
        self.assertNotIn("'$HOOK_CWD'", text)
        self.assertIn("ALIVE_RD_WORLD", text)


# -- Sweep: log guardian prefix ------------------------------------------------

class LogGuardianPrefix(unittest.TestCase):
    def run_guard(self, world: Path, file_path: str, windows: bool = False) -> str:
        env = {k: v for k, v in os.environ.items() if k not in ("MSYSTEM", "OSTYPE")}
        if windows:
            env["MSYSTEM"] = "MINGW64"
        env.update({"ALIVE_WORLD_ROOT_OVERRIDE": str(world), "CLAUDE_PLUGIN_ROOT": str(PLUGIN)})
        payload = json.dumps({
            "session_id": "lg", "cwd": str(world), "hook_event_name": "PreToolUse",
            "tool_name": "Write", "tool_input": {"file_path": file_path},
        })
        result = subprocess.run(
            [BASH, str(HOOKS / "alive-log-guardian.sh")], input=payload,
            capture_output=True, text=True, env=env, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_world_with_regex_characters_still_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(os.path.realpath(tmp)) / "my.world+1"
            base.mkdir()
            world = make_world(base)
            log = world / "04_Ventures" / "shop" / "_kernel" / "log.md"
            out = self.run_guard(world, str(log))
            self.assertIn('"deny"', out)
            out = self.run_guard(world, str(log), windows=True)
            self.assertIn('"deny"', out)

    def test_sibling_world_is_not_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            world = make_world(Path(os.path.realpath(tmp)))
            other = Path(str(world) + "2") / "x" / "_kernel" / "log.md"
            self.assertEqual(self.run_guard(world, str(other)).strip(), "")


# -- Sweep: post-write walk ----------------------------------------------------

class PostWriteWalk(unittest.TestCase):
    def test_walk_ends_on_every_windows_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            world = make_world(Path(os.path.realpath(tmp)))
            env = {k: v for k, v in os.environ.items() if k not in ("OSTYPE",)}
            env.update({
                "MSYSTEM": "MINGW64",
                "ALIVE_WORLD_ROOT_OVERRIDE": str(world),
                "CLAUDE_PLUGIN_ROOT": str(PLUGIN),
            })
            for fp in (
                r"C:\Users\Ada\notes\log.md",
                "C:/Users/Ada/notes/log.md",
                r"D:\log.md",
                "log.md",
            ):
                with self.subTest(file_path=fp):
                    payload = json.dumps({
                        "session_id": "", "cwd": str(world),
                        "hook_event_name": "PostToolUse",
                        "tool_input": {"file_path": fp},
                    })
                    # A TimeoutExpired here is an unguarded walk.
                    result = subprocess.run(
                        [BASH, str(HOOKS / "alive-post-write.sh")], input=payload,
                        capture_output=True, text=True, env=env, timeout=20,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)


# -- Sweep: statusline ---------------------------------------------------------

class StatuslineWindows(SandboxCase):
    def render(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [BASH, str(STATUSLINE)], input=json.dumps(payload),
            capture_output=True, text=True, env=self.box.env(), timeout=20,
        )

    def test_store_stub_falls_back_and_cost_is_read(self) -> None:
        self.box.store_stub("python3")
        self.box.py_launcher()
        world = make_world(self.base)
        (world / ".alive" / "_squirrels" / "sl.yaml").write_text(
            "rules_loaded: 6\nwalnut: null\n", encoding="utf-8"
        )
        result = self.render({
            "session_id": "sl", "cwd": str(world),
            "model": {"display_name": "Test"},
            "cost": {"total_cost_usd": 1.5},
            "context_window": {"used_percentage": 42},
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (world / ".alive" / ".context_pct").read_text().strip(), "42",
        )

    def test_json_escaped_windows_cwd_finds_the_world(self) -> None:
        # Claude Code sends "cwd": "C:\\Users\\..." (JSON-escaped). On a Mac
        # there is no C: drive, so check the unescape directly instead.
        script = (
            'ALIVE_PLATFORM=windows; '
            + STATUSLINE.read_text(encoding="utf-8").split("_alive_unescape_path() {", 1)[1]
            .split("\n}\n", 1)[0].join(["_alive_unescape_path() {", "\n}\n"])
            + r'_alive_unescape_path "C:\\Users\\Ada\\alive"'
        )
        result = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.stdout, "C:/Users/Ada/alive")


# -- Risk 13: archive enforcer quoting ----------------------------------------

class ArchiveEnforcer(unittest.TestCase):
    SCRIPT = HOOKS / "alive-archive-enforcer.sh"

    def test_still_unregistered(self) -> None:
        hooks = (PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("alive-archive-enforcer", hooks)

    def test_targets_parse_and_missing_files_are_reported(self) -> None:
        # Only missing targets, so nothing is renamed and no window opens.
        with tempfile.TemporaryDirectory() as tmp:
            world = make_world(Path(os.path.realpath(tmp)))
            env = {k: v for k, v in os.environ.items() if k not in ("MSYSTEM", "OSTYPE")}
            env.update({"ALIVE_WORLD_ROOT_OVERRIDE": str(world), "CLAUDE_PLUGIN_ROOT": str(PLUGIN)})
            payload = json.dumps({
                "session_id": "ae", "cwd": str(world), "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": 'rm -f "02_Life/old notes.md" && rm 03_Inbox/x.txt'},
            })
            result = subprocess.run(
                [BASH, str(self.SCRIPT)], input=payload,
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            out = json.loads(result.stdout)
            reason = out["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertIn("old notes.md", reason)
            self.assertIn("x.txt", reason)

    def test_python_block_is_single_quoted(self) -> None:
        text = self.SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('python3 -c "\nimport sys, shlex', text)
        self.assertIn("python3 -c '\nimport sys, shlex", text)


if __name__ == "__main__":
    unittest.main()
