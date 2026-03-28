---
name: alive:system-upgrade
description: "Upgrade from any previous version of the ALIVE Context System. Mines existing structure, visualises the refactor plan, asks for preferences and permissions, executes the upgrade as a refactor bundle, and verifies everything works."
user-invocable: true
---

# System Upgrade

Upgrade a world from any previous version of the ALIVE Context System to the current version. Handles structural renames, file migrations, terminology updates, and integrity verification — all wrapped in a refactor bundle so the work is tracked and reversible.

---

## When It Fires

- The session-new hook detects a legacy structure (`.walnut/`, `_core/`, `_capsules/`, `companion.md`)
- The human explicitly invokes `/alive:system-upgrade`
- The human says "upgrade my world", "migrate to the new version", "update alive"

---

## Process

### Phase 1: Mine Existing System

Before touching anything, understand what's there. Dispatch a scout agent to map the current world structure.

**Scan for:**
- `.walnut/` vs `.alive/` — which system folder exists?
- `_core/` vs `_kernel/` — which kernel structure is in use?
- `_capsules/` vs `bundles/` — which bundle structure is in use?
- `companion.md` vs `context.manifest.yaml` — which manifest format exists?
- `now.md` vs `now.json` — which state format is in use?
- Walnut count, people count, bundle/capsule count
- Squirrel entries and their format
- Custom skills, rules, hooks in the human's space
- Any `.claude/` configuration that references old paths

```
╭─ squirrel system scan complete
│
│  Current version: pre-v1 (alive plugin era)
│  System folder: .walnut/
│  Kernel: _core/ (54 walnuts use this)
│  Bundles: _capsules/ with companion.md (23 found)
│  State: now.md (markdown format)
│  Squirrels: 89 entries in .walnut/_squirrels/
│  Custom: 3 skills, 1 rule, 2 hooks
│
│  Upgrade path: .walnut/ -> .alive/, _core/ -> _kernel/,
│  _capsules/ -> bundles/, companion.md -> context.manifest.yaml,
│  now.md -> now.json
╰─
```

### Phase 2: Visualise Refactor Plan

Generate an interactive HTML visualisation showing what will change. Open it in the browser so the human can review before committing.

**The visualisation shows:**
- Every file/folder that will be renamed or moved (old path -> new path)
- Files that will be converted (companion.md -> context.manifest.yaml, now.md -> now.json)
- Files that won't be touched (log.md, key.md, tasks.md, raw/ contents)
- Risk assessment per change (safe rename / content conversion / potential conflict)
- Estimated scope (number of operations, affected walnuts)

```
╭─ squirrel refactor plan ready
│
│  Opened in browser: .alive/upgrade-plan.html
│
│  Summary:
│  - 1 system folder rename (.walnut/ -> .alive/)
│  - 54 kernel renames (_core/ -> _kernel/)
│  - 23 bundle folder renames (_capsules/ -> bundles/)
│  - 23 manifest conversions (companion.md -> context.manifest.yaml)
│  - 54 state conversions (now.md -> now.json)
│  - 3 custom skill path updates
│  - 0 conflicts detected
│
│  Review the plan, then come back here.
╰─
```

### Phase 3: Ask for Preferences and Permissions

Before executing, confirm with the human using AskUserQuestion:

**Preferences:**
1. Squirrel name — "What should your squirrel be called?" (current name carried over if set, otherwise ask)
2. Backup strategy — "Create a backup branch before upgrading?" (recommended: yes)
3. Batch size — "Upgrade all walnuts at once, or go walnut-by-walnut?" (recommended: all at once for consistency)

**Permissions:**
1. "Can I rename `.walnut/` to `.alive/`?" (required)
2. "Can I rename `_core/` to `_kernel/` in all walnuts?" (required)
3. "Can I rename `_capsules/` to `bundles/` in all walnuts?" (required)
4. "Can I convert `companion.md` files to `context.manifest.yaml`?" (required)
5. "Can I convert `now.md` files to `now.json`?" (required)
6. "Can I update your custom skills/rules/hooks to reference new paths?" (if applicable)
7. "Can I redistribute tasks from `_core/tasks.md` to bundle-scoped locations?" (optional, recommended)

```
╭─ squirrel ready to upgrade
│
│  Preferences:
│  - Squirrel name: [current or ask]
│  - Backup: recommended
│  - Batch: all at once
│
│  > Permissions needed:
│  1. Approve all (recommended)
│  2. Review each change type
│  3. Do a dry run first
│  4. Cancel
╰─
```

### Phase 4: Execute Upgrade as Refactor Bundle

Create a refactor bundle to track the upgrade work. This makes the upgrade itself a tracked unit of work with its own context.manifest.yaml.

```
bundles/_system-upgrade-[date]/
  context.manifest.yaml
  raw/
    pre-upgrade-snapshot.yaml    # World index before upgrade
    upgrade-log.yaml             # Every operation performed
```

**Execution order (matters for safety):**

1. **Create backup** (if approved) — git branch `pre-upgrade-[date]` or filesystem snapshot
2. **Create refactor bundle** — track the upgrade itself
3. **System folder rename** — `.walnut/` -> `.alive/`
   - Update all symlinks that pointed to `.walnut/`
   - Update `.claude/settings.json` statusline path if present
4. **Kernel renames** — for each walnut: `_core/` -> `_kernel/`
   - Move all contents: key.md, now.md, log.md, tasks.md, insights/
   - Update any internal references
5. **Bundle folder renames** — for each walnut: `_capsules/` -> `bundles/`
6. **Manifest conversions** — for each bundle: `companion.md` -> `context.manifest.yaml`
   - Parse companion.md frontmatter (YAML)
   - Convert to context.manifest.yaml format
   - Add new fields: `type`, `sensitivity`, `discovered`
   - Preserve all existing data (goal, status, shared, tags, people)
7. **State conversions** — for each walnut: `now.md` -> `now.json`
   - Parse now.md frontmatter
   - Convert to JSON: `{ phase, updated, bundle, squirrel, next }`
   - Drop deprecated fields (health, links)
8. **Tasks redistribution** (if approved) — scan `_kernel/tasks.md` for bundle-scoped tasks and move them to bundle-level task files
9. **Custom capability updates** — update paths in custom skills, rules, hooks
10. **Hook/config updates** — update any `.claude/` configuration referencing old paths
11. **Log the upgrade** — write upgrade entry to world-level log

**Each operation is logged to `upgrade-log.yaml`:**

```yaml
operations:
  - type: rename
    from: .walnut/
    to: .alive/
    status: complete
    timestamp: 2026-03-28T14:30:00Z
  - type: rename
    from: nova-station/_core/
    to: nova-station/_kernel/
    status: complete
    timestamp: 2026-03-28T14:30:01Z
  - type: convert
    from: nova-station/_capsules/shielding-review/companion.md
    to: nova-station/bundles/shielding-review/context.manifest.yaml
    status: complete
    timestamp: 2026-03-28T14:30:02Z
```

### Phase 5: Verify Everything Works

After all operations complete, run a full integrity check:

**Verification steps:**
1. `.alive/` exists with correct structure (`_squirrels/`, `scripts/`, `preferences.yaml`)
2. No `.walnut/` remains (unless backup)
3. Every walnut has `_kernel/` (not `_core/`)
4. Every bundle has `context.manifest.yaml` (not `companion.md`)
5. Every walnut has `now.json` (not `now.md`)
6. All squirrel entries are intact and readable
7. Custom skills load correctly
8. Hooks reference correct paths
9. Statusline renders without errors
10. World index generates successfully (`alive:my-context-graph` dry run)

```
╭─ squirrel upgrade complete
│
│  Version: ALIVE Context System v1.0
│  System folder: .alive/
│  Walnuts upgraded: 54/54
│  Bundles converted: 23/23
│  Custom capabilities updated: 6/6
│  Verification: all checks passed
│
│  Backup: git branch pre-upgrade-2026-03-28
│
│  Refactor bundle: bundles/_system-upgrade-2026-03-28/
│  Full log: bundles/_system-upgrade-2026-03-28/raw/upgrade-log.yaml
│
│  Welcome to the new version. Everything is where it should be.
╰─
```

---

## Upgrade Paths Supported

| From | To | Operations |
|------|----|-----------|
| `.alive/` + `_core/` + `_capsules/` + `companion.md` | `.alive/` + `_kernel/` + `bundles/` + `context.manifest.yaml` | Kernel rename, bundle rename, manifest convert |
| `.walnut/` + `_core/` + `_capsules/` + `companion.md` | `.alive/` + `_kernel/` + `bundles/` + `context.manifest.yaml` | System folder rename + all of above |
| `.walnut/` + `_kernel/` + `bundles/` | `.alive/` + `_kernel/` + `bundles/` | System folder rename only |
| `.alive/` + `_kernel/` + `bundles/` + `context.manifest.yaml` | (current) | Already up to date — verify only |
| No system folder | Fresh install | Redirect to `alive:world` for initial setup |

The upgrade detects what's present and only performs the operations needed. It never forces a full rebuild when a partial upgrade suffices.

---

## Rollback

If something goes wrong mid-upgrade:

1. Check `upgrade-log.yaml` for the last successful operation
2. Offer rollback to backup branch (if created)
3. Or offer manual fix for the specific failed operation

```
╭─ squirrel upgrade issue
│
│  Failed at: converting nova-station/bundles/research/companion.md
│  Error: malformed YAML frontmatter
│
│  > Options:
│  1. Skip this one, continue (fix manually later)
│  2. Show me the file so I can fix it
│  3. Rollback everything to backup
╰─
```

---

## What This Skill Does NOT Touch

- **Walnut content** — key.md, log.md, tasks.md, insights, raw files are never modified (only moved within renames)
- **Git history** — no force pushes, no history rewrites
- **External integrations** — MCP servers, email, Slack sync scripts are unaffected
- **Plugin cache** — `~/.claude/plugins/` is managed by Claude Code, not this skill

---

## What System Upgrade Is NOT

- Not `alive:build-extensions` — extend creates new capabilities. Upgrade migrates existing structure.
- Not `alive:system-cleanup` — cleanup fixes broken things in the current version. Upgrade moves between versions.
- Not a fresh install — if no existing system is found, redirect to `alive:world` for initial setup.

Cleanup fixes. Upgrade transforms.
