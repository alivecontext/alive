---
name: alive:system-upgrade
description: "Upgrade from any previous version of the ALIVE Context System. Mines existing structure, detects legacy patterns, handles YAML edge cases, audits sync scripts, and executes a scripted upgrade with rollback."
user-invocable: true
---

# System Upgrade

Upgrade a world from any previous version of the ALIVE Context System to the current version. Handles structural renames, file migrations, terminology updates, legacy cleanup, and integrity verification.

This skill has been battle-tested on a 16GB world with 142 walnuts, 88 bundles, 81 people, and 6 distinct legacy patterns. Every edge case below comes from a real upgrade.

---

## When It Fires

- The session-new hook detects a legacy structure (`.walnut/`, `_core/`, `_capsules/`, `companion.md`, `bundles/`, `_kernel/_generated/`, `tasks.md`, `observations.md`)
- The human explicitly invokes `/alive:system-upgrade`
- The human says "upgrade my world", "migrate to the new version", "update alive"

---

## Version Reference

| Component | v1 | v2 | v3 |
|-----------|----|----|-----|
| System dir | `_core/` | `_kernel/_generated/` | `_kernel/` (flat) |
| Bundles | `_core/_capsules/` | `bundles/` | walnut root (flat) |
| Manifest | `companion.md` | `context.manifest.yaml` | `context.manifest.yaml` |
| Tasks | N/A | `tasks.md` | `tasks.json` (script-operated) |
| State | `now.md` | `_kernel/_generated/now.json` | `_kernel/now.json` (script-generated) |
| Observations | N/A | `observations.md` | removed (stash -> log) |
| Inbox domain | `03_Inputs/` | `03_Inputs/` | `03_Inbox/` |

---

## Process

### Phase 1: Mine Existing System

Before touching anything, understand what's there. Dispatch a scout agent (or multiple in parallel) to map the full world structure.

**Core structure scan:**
- `.walnut/` vs `.alive/` -- which system folder exists? Do BOTH exist (merge needed)?
- `_core/` vs `_kernel/` -- which kernel structure is in use?
- `_kernel/_generated/` present? (v2 intermediate directory -- needs flattening in v3)
- `_capsules/` vs `bundles/` vs flat-at-root -- which bundle structure is in use?
- `companion.md` vs `context.manifest.yaml` -- which manifest format exists?
- `now.md` vs `_kernel/_generated/now.json` vs `_kernel/now.json` -- which state format is in use?
- `tasks.md` present anywhere? (v2 -- needs conversion to `tasks.json` in v3)
- `observations.md` present in any bundles? (v2 -- removed in v3)
- Walnut count, people count, bundle/capsule count
- Squirrel entries and their format
- Custom skills, rules, hooks in the human's space
- `.claude/` configuration referencing old paths

**Legacy structure detection (critical -- older ALIVE versions used different layouts):**
- Un-numbered domain folders at world root: `archive/`, `life/`, `ventures/`, `experiments/`, `inbox/`, `docs/`, `product/`, `plugin/`, `_working/` -- these are from pre-ALIVE-framework eras when domains didn't have numbered prefixes
- `_brain/` folders inside walnuts (v3 era state management)
- `_state/` folders inside walnuts (v3 era)
- Flat walnut structures (key.md at walnut root, no `_core/` or `_kernel/`)
- `src/` or other code directories orphaned at world root from website development
- Any folder at world root that is NOT: `01_Archive/`, `02_Life/`, `03_Inbox/`, `04_Ventures/`, `05_Experiments/`, `02_Life/people/`, `.alive/`, `.claude/`, or standard dotfiles

**v2 structure detection (for v2->v3 upgrade):**
- `bundles/` directory inside any walnut root (v2 -- bundles flatten to walnut root in v3)
- `_kernel/_generated/` directory structure (v2 -- `_kernel/` is flat in v3)
- `tasks.md` files anywhere under any walnut (v2 -- converted to `tasks.json` in v3)
- `observations.md` files inside bundles (v2 -- removed in v3)

**Duplicate walnut detection:**
- Scan for person walnuts that appear in multiple locations (e.g., `people/professional/jane/` AND `people/jane-smith/`)
- Compare key.md content: which is the stub, which has real data?
- Flag all duplicates for human review before upgrade

**World size check:**
- Run `du -sh` on the world root
- If >1GB: warn that git is impractical, recommend tarball backup
- If >5GB: flag specific heavy directories (likely code repos with node_modules)

**Sync script audit:**
- Read `preferences.yaml` `context_sources:` for configured sync scripts
- Check `.claude/scripts/` for any scripts with hardcoded paths
- Flag any that reference `_core/`, `_capsules/`, `.walnut/`, `companion.md`, `now.md`, `_kernel/_generated/`, `bundles/`, `tasks.md`, `observations.md`, or un-numbered domain paths like `inbox/` instead of `03_Inbox/`

**Root-level now.md duplicates:**
- Some walnuts have `now.md` at BOTH the walnut root AND inside `_core/`
- Detect all duplicates, flag for merge (use `_core/` version as canonical)

**_core/ directories with only _capsules/ inside:**
- Some `_core/` dirs contain only `_capsules/` (no key.md, now.md, etc.)
- These still need renaming -- include them in the kernel rename phase

```
╭─ 🐿️ system scan complete
│
│  Current version: [detected]
│  System folder: [.walnut/ | .alive/ | both]
│  Kernel: [_core/ | _kernel/_generated/ | _kernel/ (flat) | mixed]
│  Bundles: [_capsules/ | bundles/ | flat at root | mixed]
│  State: [now.md | _kernel/_generated/now.json | _kernel/now.json | mixed]
│  Tasks: [tasks.md | tasks.json | none | mixed]
│  Observations: [observations.md present | none]
│  Squirrels: [count] in [location]
│  Custom: [N skills, N rules, N hooks]
│
│  ! Legacy: [un-numbered domains at root | _brain/ folders | etc.]
│  ! Duplicates: [N person walnuts in multiple locations]
│  ! World size: [size] -- [git OK | tarball recommended]
│  ! Sync scripts: [N scripts reference old paths]
│
│  Upgrade path: [v1->v3 | v2->v3 | already v3 | specific operations needed]
╰─
```

### Phase 2: Visualise Refactor Plan

Generate an interactive HTML visualisation showing what will change. Open it in the browser so the human can review before committing.

**The visualisation shows:**
- Every file/folder that will be renamed or moved (old path -> new path)
- Files that will be converted (companion.md -> context.manifest.yaml, now.md -> now.json, tasks.md -> tasks.json)
- Files that will be removed (observations.md)
- Files that won't be touched (log.md, key.md, raw/ contents)
- Risk assessment per change (safe rename / content conversion / potential conflict)
- Estimated scope (number of operations, affected walnuts)
- Legacy folders flagged for cleanup
- Duplicate walnuts flagged for merge
- Which upgrade path applies (v1->v2->v3, v2->v3, or verify-only)

### Phase 3: Ask for Preferences and Permissions

Before executing, confirm with the human:

**Preferences:**
1. Squirrel name -- "What should your squirrel be called?" (current name carried over if set)
2. Backup strategy -- if world <1GB: "Create a git branch?" If >1GB: "Create a tarball backup of system files?" (always recommended)
3. Batch size -- "Upgrade all walnuts at once, or walnut-by-walnut?" (recommended: all at once)
4. Legacy folders -- "Clean up [N] legacy folders at world root?" (list them, let human decide)
5. Duplicates -- "Merge [N] duplicate person walnuts?" (show pairs, let human pick primary)

**Permissions -- batched into one AskUserQuestion:**
1. Approve all (recommended)
2. Review each change type
3. Do a dry run first
4. Cancel

### Phase 4: Execute Upgrade

Generate a Python upgrade script and run it. The script MUST be generated fresh (not fetched from a URL) so the human can review it. Write it to `.alive/_generated/upgrade.py`.

**The script must handle these known edge cases:**

#### YAML Frontmatter Parsing

companion.md and now.md files in the wild contain YAML that breaks standard parsers:
- **Em-dashes** (long dashes) in unquoted description strings
- **Wikilinks** (`[[walnut-name]]`) that YAML interprets as nested flow sequences
- **Colons** in unquoted description strings (e.g., `description: Schema spec for dev: block`)
- **Mixed date formats** (`2026-03-12` vs `2026-03-12T14:00:00` vs `2026-03-12T14:00:00Z`)

The parser must:
1. Try `yaml.safe_load()` first
2. If that fails, sanitize the frontmatter (quote strings with em-dashes, escape wikilinks) and retry
3. If that still fails, fall back to a regex-based key-value extractor
4. Never crash on malformed YAML -- warn and use what was extracted

#### companion.md -> context.manifest.yaml Conversion (v1->v2, v1->v3)

Field mapping:
- `type: capsule` -> removed (inferred from location in bundles/)
- `goal:` -> preserved, also used to generate `description:` (first 120 chars)
- `status:` -> preserved (known values: draft, prototype, published, done, active)
- `linked_capsules:` -> `linked_bundles:`
- `squirrel:` (singular, rare) -> normalize to `squirrels:` (plural, as array)
- `sources:` -> preserved, but normalize bare strings to `{path: str, description: "", type: "document"}`
- All other frontmatter fields -> preserved as-is

Body section handling (body sections vary wildly across worlds):
- `## Context` / `## Summary` / `## Current State` -> `context:` YAML field in manifest
- `## Tasks` -> extract to `tasks.md` sibling file (if contains `[ ]`, `[x]`, `[~]` markers)
- `## Work Log` -> extract to `observations.md` sibling file
- `## Changelog`, `## Decisions`, `## Open Questions`, custom sections -> preserved in `context:` or dropped (these are historical, not operational)
- Files with no body -> fine, just write frontmatter-only manifest
- Files with no frontmatter -> warn, skip

After conversion, rename original to `companion.md.bak` (never delete source material during upgrade).

#### now.md -> now.json Conversion (v1->v2, v1->v3)

Field mapping:
- `phase:` -> preserved (10+ distinct values exist in the wild: active, building, launching, pre-launch, onboarding, waiting, legacy, planning, ready, complete, starting, retainer-pending)
- `updated:` -> preserved as string (normalize to ISO format if possible)
- `capsule:` -> rename to `bundle:` (can be null)
- `next:` -> preserved
- `squirrel:` -> preserved (can be a hex hash OR the word "migration")
- `health:` -> dropped (calculated at read time in v2+)
- `links:` -> dropped (lives in key.md)
- `model:` -> dropped (lives in squirrel entry)
- Body (`## Context`, `## Open`, custom headings, or bare prose) -> `context:` JSON string

Create `_kernel/_generated/` directory before writing `now.json` (for v2 target). For v3 target, write directly to `_kernel/now.json`. Delete `now.md` after successful conversion.

**Credential scrubbing:** Scan body text for patterns matching `password`, `api[_-]?key`, `secret`, `token`, `Bearer`. Scrub matching lines from the JSON context field. Warn the human about what was removed.

#### tasks.md -> tasks.json Conversion (v2->v3)

Parse markdown checkbox format into structured JSON:

**Status mapping from checkboxes:**
- `[ ]` -> `status: "todo"`
- `[~]` -> `status: "active"`
- `[x]` -> `status: "done"` -> route to `completed.json` instead of `tasks.json`

**Field extraction:**
- `@session_id` anywhere in the line -> `session` field (strip the `@` prefix)
- Section headers map to priority:
  - `## Urgent` or `### Urgent` -> `priority: "urgent"`
  - `## Active` or `### Active` -> `priority: "active"`
  - `## To Do` or `### To Do` -> `priority: "normal"`
  - `## Blocked` or `### Blocked` -> `priority: "blocked"`
- MoSCoW tags in the line -> `tags` field (array):
  - `[M]` -> `"must"`
  - `[S]` -> `"should"`
  - `[C]` -> `"could"`
  - `[W]` -> `"wont"`
- The remaining text (after stripping checkbox, session, MoSCoW tags) -> `text` field

**Output format (`tasks.json`):**
```json
{
  "tasks": [
    {
      "text": "Implement the parser",
      "status": "active",
      "priority": "urgent",
      "session": "abc123",
      "tags": ["must"]
    }
  ]
}
```

**Output format (`completed.json`):**
```json
{
  "completed": [
    {
      "text": "Write the spec",
      "status": "done",
      "priority": "normal",
      "session": "def456",
      "tags": []
    }
  ]
}
```

**Error handling:**
- Lines that don't match any checkbox pattern -> flag to stderr for manual review
- Blank lines and section headers -> skip (headers are consumed for priority context)
- Lines with only whitespace after the checkbox -> skip with warning

After successful conversion, rename original to `tasks.md.bak`.

#### observations.md Handling (v2->v3)

- If file is empty or fewer than 3 non-blank lines -> remove (rename to `observations.md.bak`)
- If file has substantial content (3+ non-blank lines) -> migrate content into the bundle's `context.manifest.yaml` `context:` field, appending to any existing context
- After migration, rename original to `observations.md.bak`

#### bundles/ Flattening (v2->v3)

Each subdirectory under `bundles/` moves to the walnut root:
- `walnut-root/bundles/my-bundle/` -> `walnut-root/my-bundle/`
- Check for naming conflicts at walnut root before moving (e.g., a bundle named `_kernel` would collide)
- If a conflict exists, warn and skip that bundle (flag for manual resolution)
- After all bundles are moved, remove the empty `bundles/` directory

#### _kernel/_generated/ Flattening (v2->v3)

- Move `_kernel/_generated/now.json` -> `_kernel/now.json`
- Move any other files in `_kernel/_generated/` to `_kernel/` (preserving names)
- Remove the empty `_kernel/_generated/` directory
- If `_kernel/_generated/` contains subdirectories, warn and skip (flag for manual review)

#### now.json Regeneration (v2->v3)

After structural migration is complete:
- Run `project.py --walnut {path}` to generate a fresh `_kernel/now.json` reflecting the new structure
- If `project.py` is not available, preserve the migrated `now.json` as-is and warn

#### _capsules/ Move Semantics (two patterns, v1->v2, v1->v3)

- **_capsules/ inside _core/ (now _kernel/):** These must be MOVED to walnut root `bundles/` (v2) or walnut root directly (v3), not just renamed. The move changes relative path depth.
- **_capsules/ at walnut root:** Simple rename to `bundles/` (v2) or leave in place with rename (v3).

#### Template File Exclusion

Skip files in `templates/` directories -- these are plugin scaffolding templates, not walnut state:
- `templates/walnut/now.md` -- do not convert
- `templates/companion/companion.md` -- do not convert

#### Root-level now.md Duplicates

If both `walnut-root/now.md` AND `_core/now.md` (or `_kernel/now.md`) exist:
- Use `_core/` / `_kernel/` version as canonical (it's the system file)
- Delete the root-level duplicate
- If root version has unique content, merge it into the context field

#### Execution Order (matters for safety)

**v1->v3 upgrade (full path -- runs v1->v2 steps then v2->v3 steps):**

1. **Create backup** -- tarball of .walnut/ + all _core/ dirs + all companion.md + all now.md + all tasks.md + all observations.md. Write to `.alive/_generated/pre-upgrade-backup.tar.gz`
2. **System folder merge** -- `.walnut/` into `.alive/` (handle overlapping squirrels, skills, scripts)
3. **Kernel renames** -- `_core/` -> `_kernel/` (deepest first to avoid parent-before-child issues). Include dirs that only contain `_capsules/`.
4. **Bundle moves** -- `_capsules/` -> walnut root (check both `_kernel/_capsules/` and walnut-root `_capsules/`)
5. **Manifest conversions** -- `companion.md` -> `context.manifest.yaml` (with YAML sanitization)
6. **State conversions** -- `now.md` -> `_kernel/now.json` (with credential scrubbing, writing directly to flat `_kernel/`)
7. **Task conversions** -- `tasks.md` -> `tasks.json` + `completed.json` (with checkbox parsing)
8. **Observations migration** -- `observations.md` -> context field or removed
9. **Post-upgrade fixups** -- find-replace `_core/` -> `_kernel/`, `_capsules/` -> bundle names, `_kernel/_generated/` -> `_kernel/`, `bundles/` -> flat refs, etc. in all custom skills, scripts, CLAUDE.md files, hooks
10. **Regenerate state** -- run `project.py --walnut {path}` for fresh `now.json`
11. **Log the upgrade** -- write entry to `.alive/log.md`

**v2->v3 upgrade:**

1. **Create backup** -- tarball of all `_kernel/_generated/` dirs + all `bundles/` dirs + all `tasks.md` + all `observations.md`. Write to `.alive/_generated/pre-upgrade-backup.tar.gz`
2. **Present summary** -- show every change that will happen, grouped by walnut. Wait for confirmation.
3. **Flatten _kernel/_generated/** -- move `_kernel/_generated/now.json` -> `_kernel/now.json`, remove empty `_kernel/_generated/`
4. **Flatten bundles/** -- move each `bundles/*/` to walnut root, remove empty `bundles/`
5. **Convert tasks** -- `tasks.md` -> `tasks.json` + `completed.json` (per bundle and per kernel)
6. **Create completed.json** -- `_kernel/completed.json` with migrated done tasks
7. **Migrate observations** -- `observations.md` -> manifest context field or removed
8. **Rename inbox domain** -- `03_Inputs/` -> `03_Inbox/` at world root (if exists)
9. **Post-upgrade fixups** -- find-replace `_kernel/_generated/` -> `_kernel/`, `bundles/X` -> `X`, `tasks.md` -> `tasks.json`, `observations.md` references removed, `03_Inputs` -> `03_Inbox`, in all custom skills, scripts, CLAUDE.md files, hooks
10. **Regenerate state** -- run `project.py --walnut {path}` for fresh `now.json`
11. **Verify structure** -- confirm v3 expectations met
12. **Log the upgrade** -- write entry to `.alive/log.md`

**Safety rules for v2->v3 (and all paths):**
- Back up every file before moving or converting
- Don't delete originals until migration is verified
- Present a summary of what will change BEFORE executing
- Ask for confirmation before each major step (flatten kernel, flatten bundles, convert tasks, migrate observations)

Log every operation to `.alive/_generated/upgrade-log.yaml` with type, source, target, timestamp, status.

### Phase 5: Verify Everything Works

**Structural verification:**
1. `.alive/` exists with correct structure (`_squirrels/`, `scripts/`, `preferences.yaml`)
2. No `.walnut/` remains
3. No `_core/` kernel directories remaining (find + verify)
4. No `_capsules/` directories remaining
5. No unconverted `companion.md` inside any walnut (`.bak` files are OK)
6. No `now.md` remaining in `_kernel/` directories
7. No `_kernel/_generated/` directories remaining (v3 flattened)
8. No `bundles/` directories remaining at walnut root (v3 flattened)
9. No `tasks.md` remaining (converted to `tasks.json`, `.bak` files OK)
10. No `observations.md` remaining (migrated or removed, `.bak` files OK)
11. All `_kernel/` dirs contain `now.json` directly (not nested in `_generated/`)
12. All squirrel entries intact and readable
13. Custom skills reference correct paths (grep for `_core/`, `_kernel/_generated/`, `bundles/` -- should find nothing)
14. Statusline renders without errors

**Task conversion verification (v2->v3):**
15. Every `tasks.json` is valid JSON and parseable
16. Every `completed.json` is valid JSON and parseable
17. Task count in `tasks.json` + `completed.json` matches original `tasks.md` checkbox count (minus flagged unparseable lines)

**Root-level hygiene:**
18. No unexpected folders at world root -- only `01_Archive/`, `02_Life/`, `03_Inbox/`, `04_Ventures/`, `05_Experiments/`, `02_Life/people/`, `.alive/`, `.claude/`, and standard dotfiles should exist
19. Flag any legacy folders that remain (un-numbered domains, _working, src, etc.)

**Sync script audit:**
20. Check configured sync scripts for old path references -- flag any that will recreate legacy folders
21. Surface specific line numbers and suggested fixes

**Report:**
```
╭─ 🐿️ upgrade complete
│
│  Version: ALIVE Context System v3.0
│  System folder: .alive/
│  Walnuts upgraded: N/N
│  Bundles flattened: N/N
│  Tasks converted: N/N (N routed to completed.json)
│  Observations migrated: N/N
│  Custom capabilities updated: N/N
│  Verification: N/N checks passed
│
│  ! [any remaining issues]
│
│  Backup: .alive/_generated/pre-upgrade-backup.tar.gz
│  Log: .alive/_generated/upgrade-log.yaml
╰─
```

---

## Upgrade Paths Supported

| From | To | Operations |
|------|----|-----------|
| Un-numbered domains + `_brain/` + `_state/` | Current v3 | Full restructure -- route to numbered domains, convert state, flatten kernel + bundles, convert tasks |
| `.alive/` + `_core/` + `_capsules/` + `companion.md` | v3 | Kernel rename, bundle move + flatten, manifest convert, state convert, task convert |
| `.walnut/` + `_core/` + `_capsules/` + `companion.md` | v3 | System folder merge + all above |
| `.walnut/` + `_kernel/` + `bundles/` | v3 | System folder merge + flatten kernel + flatten bundles + convert tasks + migrate observations |
| `.alive/` + `_kernel/_generated/` + `bundles/` + `tasks.md` | v3 | Flatten `_kernel/_generated/` to `_kernel/`, flatten `bundles/` to root, convert `tasks.md` to `tasks.json`, migrate `observations.md` |
| `.alive/` + `_kernel/` + `bundles/` + `context.manifest.yaml` | v3 | Flatten bundles + convert tasks + migrate observations (partial v2->v3) |
| `.alive/` + `_kernel/` (flat) + flat bundles + `tasks.json` | (current v3) | Already up to date -- verify only |
| Both `.walnut/` AND `.alive/` exist | Merge `.walnut/` into `.alive/` then v3 | Handle overlapping squirrels, skills, scripts -- keep newer versions |
| No system folder | Fresh install | Redirect to `alive:world` for initial setup |

The upgrade detects what's present and only performs the operations needed. It never forces a full rebuild when a partial upgrade suffices.

---

## Rollback

If something goes wrong mid-upgrade:

1. Check `upgrade-log.yaml` for the last successful operation
2. Offer restore from tarball backup
3. Or offer manual fix for the specific failed operation

The tarball contains every file that was about to be renamed or converted -- full restore is always possible.

```
╭─ 🐿️ upgrade issue
│
│  Failed at: converting [path]/tasks.md
│  Error: [specific error]
│
│  ▸ Options:
│  1. Skip this one, continue (fix manually later)
│  2. Show me the file so I can fix it
│  3. Restore from backup
╰─
```

---

## What This Skill Does NOT Touch

- **Walnut content** -- key.md, log.md, raw files are never modified (only moved within renames)
- **Git history** -- no force pushes, no history rewrites
- **Plugin cache** -- `~/.claude/plugins/` is managed by Claude Code, not this skill

## What This Skill DOES Audit (but doesn't auto-fix)

- **Sync scripts** -- flags old paths, shows the fix, lets the human decide
- **External integrations** -- MCP servers, email, Slack sync scripts are surfaced if they reference old structure
- **Legacy folders** -- surfaced for human cleanup, never auto-deleted

---

## What System Upgrade Is NOT

- Not `alive:build-extensions` -- extensions create new capabilities. Upgrade migrates existing structure.
- Not `alive:system-cleanup` -- cleanup fixes broken things in the current version. Upgrade moves between versions.
- Not a fresh install -- if no existing system is found, redirect to `alive:world` for initial setup.

Cleanup fixes. Upgrade transforms.
