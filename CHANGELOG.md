# Changelog

All notable changes to the ALIVE Context System plugin are documented here.

## [3.2.6] - 2026-11-09

A Windows release, because Windows users asked. The research preview isn't being actively developed while the next ALIVE is built. This one adds Windows checks and hardens paths and Python on Windows. Mac and Linux behave as before, apart from the path-prefix fix marked below.

If you have feedback on the research preview, now is the time to open an issue: https://github.com/alivecontext/alive/issues

### Fixed

- **`alive` command needed `python3` by name:** `bin/alive` now tries `python3`, then the Windows `py -3` launcher, then `python`, and uses the first one that actually runs Python 3. If none does, it says so and how to install Python, instead of failing with "command not found".
- **The Microsoft Store `python3` placeholder:** on Windows, `python3` can be a Store stub that is on PATH but exits with an error. The one interpreter pick in `alive-common.sh` now checks that each candidate runs and is Python 3, skips the stub, falls back to `py -3` or `python`, and every hook uses that answer. If only the stub is there, session start says it's the Store placeholder and how to fix it. The statusline, repo detection and the star prompt no longer call `python3` blind.
- **Repo detection never matched on Windows:** it compared `C:\...` with `/c/...`, and pasted the paths into Python source, where `C:\Users` is a syntax error. Paths now reach Python through the environment, in a form native Windows Python can open, and compare case-insensitively on Windows.
- **Finding the world from a subfolder on Windows:** the walk up from the session folder took `dirname` of a `C:\...` path, which is `.`, so it only ever checked the folder itself. It now walks the converted path.
- **Guard hooks and path case:** Windows paths ignore case, so a `c:\users\...` path now matches a world at `C:\Users\...`.
- **Statusline on Windows:** reads the JSON-escaped `C:\\...` folder and transcript paths correctly.
- **Path prefixes (all platforms):** the log guardian matched the world root as a regular expression and repo detection by plain prefix, so a world at `/x/alive` also claimed `/x/alive2`. Both now compare whole path segments.
- **Archive enforcer quoting:** its Python was double-quoted and broke at its own quotes, so it never found a target. Fixed and tested. It stays unregistered.

### Added

- **Windows CI:** `.github/workflows/windows.yml` runs the Windows tests, the full release suite and a hook smoke test on `windows-latest` under Git Bash, plus a job with Python hidden that checks the "needs Python" notice.

## [3.2.5] - 2026-11-09

Windows fixes for the research preview, starting with #102, the statusline loop a Windows user reported in October. Nothing changes on Mac or Linux.

### Fixed

- **Statusline froze a CPU core on Windows (#102):** finding the world walked up the folder tree until it reached `/`, which never happens on a `C:` path, so the statusline looped forever. It now stops when it can't go any higher.
- **Guard hooks missed every Windows path:** Claude Code on Windows passes paths like `C:\Users\you\world`, but the log, rules, world-root and inbox hooks compared them with the world folder in `/c/Users/you/world` form, so they never matched and never fired. The log was not protected as prepend-only on native Windows. All four now convert the path first.
- **Saving a log could leave now.json stale on Windows:** the post-write hook matched `*/log.md` against backslash paths and walked up with no stop. It now matches Windows paths and stops at the drive.
- **No Python, no warning:** without Python, every ALIVE hook ran silently empty. Session start now says plainly that ALIVE needs Python 3 and how to install it on Windows. (The old fallback assumed Claude Code ships Node; the native installer doesn't.)
- **Line endings:** extensionless scripts in `bin/` are now kept as LF on Windows checkouts.

### Changed

- **Author:** the manifest author is Supernormal Labs, matching the licence. Example emails in the rules use `example.com`.

## [3.2.4] - 2026-11-09

ALIVE 3.2.4 stays here as a research preview under MIT and keeps working for existing worlds; it is no longer actively maintained.

### Fixed

- **Skill names (known issue):** every skill declared its name as `alive:<skill>` in its frontmatter. Claude Code already adds the `alive:` prefix from the plugin, so on some Claude Code versions skills showed up as `/alive:alive:save` or did not show or trigger as expected. Each skill now uses its plain folder name (`name: save`, `name: world`, and so on). You still type `/alive:save` and `/alive:world` as before.
- **Fewer permission prompts in `/alive:world`:** setup and the dashboard checked for the world pointer, a seed file and the inbox with shell one-liners that Claude Code asks you to approve. They now use the Read and Glob tools for those checks. Same checks, same results.
- **Hooks with a space in the plugin path:** all 13 hook commands in `hooks.json` now quote the plugin path, so they still run when the path contains a space.
- **Debounce markers:** the post-write hook's per-walnut marker could collapse to one shared marker where `md5sum` was missing, and the index marker was shared by every world and user on a machine. Both are now per world.
- **Hermes installer on macOS:** `hermes/install.sh` stopped with an unbound variable error during verification on macOS's bash, and verified nothing on newer bash. It now checks the files it actually copied.

### Changed

- **Less squirrel, fewer boxes:** bordered blocks are kept for a stash change, the save summary and a numbered question. Everything else is plain text, and the assistant no longer plays a squirrel character. A squirrel name set in preferences still works.
- **Blocks are quotes now:** the stash, save summary and question blocks are a markdown quote with a bold first line instead of a rounded border. The border looked broken in the Claude app, which uses a proportional font. The quote shows as a clean bar on the left in the app and the terminal.
- **Calmer rules preamble:** the session-start rules header is plain and says your own instructions come first.
- **Quiet outside a world:** in a folder that is not an ALIVE world, session start adds a short setup note instead of the full rules, so unrelated projects are left alone.
- **Statusline:** the boot line reads `alive | N walnuts` instead of the mascot line.
- **Fewer nudges:** the share question comes up only when a save moves a bundle to published or done. Star asks drop from five to two (sessions 10 and 30), plus at most three one-line save nudges as before.
- **Shorter README** with the two install commands, the one command to run first, and the full skills list.
- `SECURITY.md` lists only the guards that ship, and skill counts in the README, `CONTRIBUTING.md` and setup match the 17 skills.
- Licence remains MIT.

## [3.2.3] - 2026-10-02

### Fixed

- **Task id collisions no longer lose tasks (issue #96, #97):** `tasks.py` refuses ambiguous ids instead of silently acting on the first match, `done`/`drop` remove by identity so tasks sharing an id are no longer all deleted, `edit` inherits the same refusal, and the v2→v3 upgrade continues ids after the file's high-water mark. Already-duplicated ids are made safe (refused), not auto-repaired.

### Changed

- **Session start injects an index brief (part of issue #89, #95):** instead of the whole `_index.yaml`, the hook sends walnut names, paths and phases by domain, people, recent sessions and counts (about 88% smaller on a 49-walnut world). The world skill reads `.alive/_index.yaml` for its dashboard. Worlds without `_index.json` fall back to the full index. #89 stays open: the rules files still push session start past Claude Code's hook context limit.

### Removed

- **External guard hook (issue #99):** `alive-external-guard.sh` (PreToolUse, matcher `mcp__.*`) is gone. It asked for confirmation on any MCP tool whose name lacked a read-style word, so every Claude in Chrome and built-in browser action prompted, and because a hook "ask" outranks Claude Code's own permissions it also overrode allow rules, auto mode and site grants. ALIVE now defers to Claude Code's own permission settings for external and browser tools. `SECURITY.md`, `PERMISSIONS.md` and `rules/human.md` updated; `test_issue_99_no_mcp_guard.py` pins it.

## [3.2.2] - 2026-09-11

### Fixed

- **Context-watch injection removed (issue #86):** the UserPromptSubmit hook no longer injects context-usage percentages or repeated rules refreshes into model context at 20/40/60/80% thresholds, and no longer dumps the world key and index at 60%+. Surfacing a context countdown makes the model manage its context instead of the task, and repeating instructions on a cadence breaks preserved thinking. Rules are stated once at session start.
- **External-change message:** the "another session saved" notice no longer asks permission to re-read state (a read-only action) and names the actual changed files instead of hardcoded v3 paths, so v1/v2 walnuts are not sent to files that don't exist.
- **v2 upgrade notice:** no longer fires on already-migrated worlds. Detection prunes `01_Archive/` and migration backups, and a leftover `03_Inputs/` alongside `03_Inbox/` no longer counts as a v2 marker. The long first-person developer message is replaced with one factual line naming the matched markers and the `/alive:system-upgrade` command.
- **External-change detection works on large worlds (issue #87):** walnut resolution reads `.alive/_index.json` and caches per session instead of walking the whole world with `find` on every prompt — measured ~14s (killed by the 5s hook timeout) down to 149ms first resolution, 93ms cached, on a real 49-walnut world. Resolution prefers live walnuts over `01_Archive/` duplicates and accepts bare, quoted and path-form `walnut:` values from session records. Hardening: sanitized session ids in temp paths, stamp-before-scan closes the same-second mtime race, paths reach helper interpreters via environment variables, the `stat` probe validates output (BusyBox), and hook output goes through the full JSON encoder.
- **Permissions declaration:** the `UserPromptSubmit` row in `PERMISSIONS.md` matches what the hook actually reads and writes after these changes.

### Added

- **Cross-session awareness re-homed (issue #88):** the unsaved-stash heads-up removed with the context-% trigger returns on a change-driven trigger — it rescans only when a session record actually changes. Sessions on the same walnut have their unsaved stash detailed; other walnuts appear as a one-line count with no stash content injected.

### Changed

- Regression tests pin all fixes (`test_issue_86_context_watch.py`, `test_v2_upgrade_notice.py`, `test_issue_87_88_detection.py`) — the issue-#86 and v2-notice tests verified to fail against the 3.2.1 hooks.

## [3.2.1] - 2026-08-07

### Fixed

- **Migration boundary:** Live-disk fallback now requires walnut identity before treating a `bundles/` directory as migratable. Generic project folders are not moved.
- **Resume recovery:** A resumed Claude Code session with a missing squirrel record gets a new exact session record instead of borrowing another active session.
- **Upgrade warning:** A v3 `02_Life/_kernel` path or unrelated nested `bundles/` directory no longer triggers the v2 migration warning by itself.
- **Completed task history:** Completed and dropped tasks are listable from history (issue #60).
- **Release metadata:** README, marketplace, plugin, runtime and walnut product versions agree at 3.2.1. The world schema target remains 3.2.0.

### Changed

- Licence remains MIT.
- Added a buyer-facing permission declaration covering 14 command invocations across 5 Claude Code hook event types (`PERMISSIONS.md`).
- The README now shows the complete first-time marketplace registration and plugin installation flow.
- Claude Code remains the only supported runtime in this release. Codex support is not included; Hermes remains community/experimental.

## [3.0.0] - 2026-04-04

### Personal Context Manager

The GTM release. Two weeks live, 500+ installs, and a full architectural refactor based on real usage feedback. Every pain point from v2 — slow loads, broken task tracking, concurrent session clobbering, too many file reads — addressed in this release. Install: `claude plugin install alive@alivecontext`

### Architecture
- **Flat kernel:** `_kernel/_generated/` removed. All files flat in `_kernel/` — key.md, log.md, insights.md, tasks.json, now.json, completed.json
- **Flat bundles:** `bundles/` container removed. Bundles live flat in walnut root, identified by `context.manifest.yaml`
- **Script-operated tasks:** `tasks.md` replaced by `tasks.json`. Agent calls `tasks.py` CLI — never reads/writes task files directly
- **True projection:** `now.json` computed post-save by `project.py` from ALL source files. Agent never writes now.json. Solves concurrent session clobbering.
- **3-file load:** key.md + now.json + insights.md frontmatter. Down from 13+ file reads.
- **03_Inputs/ → 03_Inbox/** — I = Inbox. Universally understood.
- **Graduation is a status flip** — no folder moves. Bundle stays where it is.
- **observations.md removed** — stash routes to log at save. No separate file.

### Added
- **`tasks.py`** — CLI for all task operations (add, done, drop, edit, list, summary)
- **`project.py`** — projection script, builds now.json from all sources post-save
- **`completed.json`** — append-only archive of every completed/dropped task
- **Subagent brief template** — ships with plugin, substituted at dispatch time
- **DO NOT READ guards** — load-context and world skills explicitly bar unnecessary file reads
- **Walnut boundary detection** — scripts stop at nested walnut boundaries, no more scanning 693 directories

### Changed
- **Org:** stackwalnuts → alivecontext. GitHub, install command, all URLs.
- **Author:** Stack Walnuts → Lock-in Lab
- **Category:** plugin → pcm (Personal Context Manager)
- **All 6 rules rewritten** for v3 (version 3.0.0)
- **All 15 skills updated** — 6 major rewrites, 9 moderate/minor
- **5 hooks updated** — project.py trigger, v3 paths, backward compat
- **generate-index.py** — reads v3 flat now.json, extracts task counts, includes recent sessions and unsigned stash count
- **Save protocol:** agent writes source files, projection script computes now.json
- **Stash checkpoint rule removed** — save IS the checkpoint, no phantom timers
- **Unsigned entry recovery fixed** — stash: [] does NOT mean empty session, check transcripts
- **Archive enforcer hook removed** — Claude Code permissions sufficient

### Removed
- `plugins/walnut/` — dead v1 plugin (43 files)
- `plugins/walnut-cowork/` — empty stub
- `assets/` — 13 orphaned images
- `observations.md` from bundle anatomy
- `_kernel/_generated/` subdirectory
- `bundles/` container directory

### Upgrade
```bash
claude plugin install alive@alivecontext
/alive:system-upgrade
```
Handles v1→v3 and v2→v3. Backs up everything before migrating. Tasks.md parsed to tasks.json. Bundles flattened. Kernel flattened. Inbox renamed.

---

## [2.0.0] - 2026-03-29

### The ALIVE Context System

Complete architecture overhaul. Product name: ALIVE Context System. Plugin: `alive`. Install: `claude plugin install alive@alivecontext`.

### Architecture
- **Kernel replaces core:** `_core/` -> `_kernel/`. Three source files: key.md, log.md, insights.md
- **Bundles replace capsules:** `_capsules/` -> `bundles/` (promoted to walnut top level). Two species: outcome and evergreen.
- **Generated projections:** now.md deleted, replaced by generated `now.json`. Tasks distributed to bundles.
- **Context manifest:** `companion.md` -> `context.manifest.yaml` -- integration manifest + marketplace listing
- **Projection tiers:** world-index.json -> now.json -> manifests -> raw. Generated on save.
- **People/ reverted** to `02_Life/people/` -- people walnuts stay inside the Life domain, not at world root
- **Subagent brief pack:** `.alive/_generated/subagent-brief.md` injected into all spawned agents

### Added
- **`alive:bundle` skill** -- create, share, graduate bundles (replaces capsule-manager)
- **`alive:system-upgrade` skill** -- upgrade from any previous version with visual plan
- **Named squirrels** -- users name their context companion (persona layer)
- **Action logging** -- proof of work in squirrel YAML
- **Plugin compatibility watch** -- detect conflicts with other plugins, suggest ALIVE-compatible patterns
- **Cross-platform support** -- python3 primary, node fallback, Unicode platform-guarded

### Changed
- **Namespace:** `walnut:*` -> `alive:*` (15 skills)
- **System folder:** `.walnut/` -> `.alive/`
- **6 rules rewritten** for v2 architecture (bundles.md replaces capsules.md)
- **14 hooks updated** for v2 paths and cross-platform safety
- **README rewritten** -- ALIVE story, two units, projections, install guide

### Walnut v1 (sunset)
- `plugins/walnut/` preserved as frozen v1. Install: `claude plugin install walnut@walnut`
- No further updates. Use `alive:system-upgrade` to migrate.

## [1.0.1-beta] -- 2026-03-12

### Added
- Capsule architecture -- self-contained units of work
- 3 new skills: mine-for-context, build-extensions, my-context-graph
- Inbox scan mode, context graph, world index generator

## [1.0.0-beta] -- 2026-03-10

### Added
- 12 skills, 6 rules, 12 hooks
- Squirrel caretaker runtime, stash mechanic, ALIVE framework
- Onboarding, statusline, templates

## [0.1.0-beta] -- 2026-02-23

Initial release.
