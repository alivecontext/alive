---
name: housekeeping
description: "Use when the human asks for a system check, mentions anything stale or broken, or wants maintenance — scans squirrel activity across all walnuts then surfaces unsigned entries, stale walnuts past their rhythm, orphan references, stale drafts, overdue tasks, and unrouted inputs one issue at a time."
user-invocable: true
---

# Housekeeping

System maintenance. Root health first, then one walnut at a time. Surfaces issues with recommended fixes — the human picks.

Not a dashboard (that's world). Not a search (that's find). Not session recall (that's recall). Pure maintenance.

---

## Three-Phase Flow

```
Phase 1: Root Audit (system-level, 6 checks — parallel subagents)
    ↓
Phase 2: Walnut Summary (single subagent scans frontmatter, human picks)
    ↓
Phase 3: Deep Audit (one walnut, 10 checks — parallel subagents)
```

---

## Subagent Strategy (non-negotiable)

Housekeeping is read-heavy. Every phase uses subagents to keep the main context clean.

- **Phase 1:** Dispatch all 6 root checks as parallel subagents. Wait for all. Present results together — one line per passing check, expand on failures only.
- **Phase 2:** Single subagent reads all walnut frontmatter, returns the health table.
- **Phase 3:** Dispatch all 10 checks as parallel subagents (one check per subagent). Wait for all. Present results together — passing checks collapsed, failures expanded one at a time.

Each subagent gets: the check description, what to scan, what constitutes a pass/fail, and instructions to return a structured result (pass/fail + details if fail).

**Never read walnut files in the main context.** All file reading happens inside subagents. The main context only sees results.

---

## Presentation Rules

- **Passing checks:** Collapse to one line. `✓ 3a. now.md zero-context — pass`. No details.
- **Failing checks:** Expand with bordered block, recommended fix, and options. One at a time.
- **After presenting all results:** Walk through failures one at a time for the human to resolve or skip.

---

## Phase 1 — Root Audit

Dispatch 6 subagents in parallel. Each checks one thing across the whole world.

### 1a. ALIVE Structure

Verify all 5 ALIVE folders exist at the world root (`01_Archive/` through `05_Experiments/`).

Pass: all 5 exist. Fail: any missing.

### 1b. Inputs Buffer

Scan `03_Inputs/` for items older than 48 hours. Unrouted inputs may contain decisions or context affecting active walnuts.

Pass: empty or nothing older than 48h. Fail: items found.

```
╭─ 🐿️ housekeeping — unrouted inputs
│  03_Inputs/ has 3 items older than 48 hours:
│   - vendor-brochure.pdf (3 days)
│   - meeting-notes-feb20.md (4 days)
│
│  → route via alive:capture / skip
╰─
```

### 1c. Cross-Walnut Links

Scan ALL walnuts' `_core/key.md` frontmatter (`links:` and `parent:` fields) AND body text for `[[wikilinks]]`. Check for:

- **Broken wikilinks** — links pointing to walnut names that don't exist as folders
- **Orphan parents** — `parent:` pointing to a non-existent walnut
- **Undeclared connections** — `[[wikilinks]]` used in body text or log entries but NOT in the frontmatter `links:` field. These are invisible to `alive:find` traversal.
- **Structureless folders** — folders in ALIVE domains (02-05) that have no `_core/` but look like they should be walnuts

### 1d. Walnut Structural Integrity

Quick scan that every walnut has the full `_core/` skeleton:
- 5 system files: `key.md`, `now.md`, `log.md`, `insights.md`, `tasks.md`
- 3 subdirectories: `_squirrels/`, `_working/`, `_references/`

Pass: all walnuts complete. Fail: list what's missing where.

### 1e. Unsigned Squirrel Entries

Scan `_core/_squirrels/` (and `.alive/_squirrels/`) across ALL walnuts for YAML files where `signed: false` or `signed:` is missing. Flag entries that have stash items — those contain unrouted decisions/tasks.

Separate entries with stash (need review) from empty shells (safe to clear).

```
╭─ 🐿️ housekeeping — unsigned sessions
│  3 sessions with unrouted stash:
│   - berties / squirrel:67b1e464 — 4 stash items
│   - alive-os / squirrel:45dcf404 — 6 stash items
│  13 empty shells (no walnut, no stash) — safe to clear.
│
│  → review berties stash / review alive-os stash / clear empty shells / skip
╰─
```

### 1f. Orphan Files at World Root

Flag anything at the world root that isn't an ALIVE folder (`01_Archive/` through `05_Experiments/`), `.alive/`, `.claude/`, or dotfiles. Nothing should live loose at root.

### Phase 1 Results

Present all 6 results together. Passing checks get one line. Failures expand.

```
╭─ 🐿️ root audit — 6 checks
│
│  ✓ 1a. ALIVE structure — intact
│  ✓ 1b. Inputs buffer — clean
│  ⚠ 1c. Cross-walnut links — 2 undeclared connections
│  ✓ 1d. Walnut integrity — all complete
│  ⚠ 1e. Unsigned entries — 3 with stash, 13 empty
│  ⚠ 1f. Orphan files — 2 at root
│
│  3 issues to resolve.
╰─
```

Then ask which to fix:

```
╭─ 🐿️ root audit — which to fix?
│
│  1. 2 undeclared cross-walnut connections
│  2. 3 unsigned sessions with stash (11 items total)
│  3. 2 orphan files at world root
│
│  → which ones? (numbers, "all", or "skip")
╰─
```

For each the human picks, propose the specific fix:

```
╭─ 🐿️ proposed fixes
│
│  1. Add [[will-bainbridge]], [[ben-obrien]] to berties key.md links:
│  3. Move AGENTS.md → alive-os/_core/_working/,
│     delete disaster-recovery-extraction.md
│
│  → go / change something / skip
╰─
```

**On "go":** dispatch parallel subagents to execute — one per fix. Each subagent reads the file, makes the edit, returns confirmation. Main context does not touch files.

```
╭─ 🐿️ root audit complete
│  6 checks. 3 issues, 2 fixed, 1 skipped.
│  → continue to walnut audit / done
╰─
```

---

## Phase 2 — Walnut Summary

Single subagent scans all walnuts. For each walnut, read ONLY `_core/now.md` frontmatter (phase, health, updated) and `_core/key.md` frontmatter (rhythm, type). **Frontmatter only. Do not read full files.**

Return a health table. The main context presents it:

```
╭─ 🐿️ walnut health summary
│
│   #  Walnut               Type         Health    Updated         Rhythm
│   1. alive-os             experiment   active    2 hours ago     weekly
│   2. berties              venture      active    2 days ago      weekly
│   3. nova-station         venture      quiet     12 days ago     weekly    ⚠
│   4. glass-cathedral      experiment   waiting   34 days ago     monthly   ⚠
│
│  Which walnut to audit? (number, or "done" to finish)
╰─
```

Health thresholds (from rhythm):

| Rhythm | Quiet at | Waiting at |
|--------|----------|-----------|
| daily | 2 days | 4+ days |
| weekly | 2 weeks | 4+ weeks |
| fortnightly | 3 weeks | 6+ weeks |
| monthly | 6 weeks | 3+ months |

**Post-migration note:** If many walnuts show today's date with "active" health, the data may reflect migration timestamps rather than genuine recent work. Flag this to the human if detected (e.g., 5+ walnuts all updated on the same day).

---

## Phase 3 — Deep Audit (single walnut)

Dispatch 10 subagents in parallel — one per check. Each subagent reads only the files it needs from the walnut's `_core/`. **Do not read the brief pack in the main context.**

The main context receives pass/fail results from all 10 subagents, presents them together, then walks through failures one at a time.

### 3a. Malformed Files (runs first conceptually — other checks depend on frontmatter)

Scan ALL `.md` files in `_core/` recursively (system files, `_working/`, `_references/`). Check each starts with `---` followed by valid YAML and a closing `---`.

Pass: all files have frontmatter. Fail: list files without it.

**Fix guidance:** When the human picks "add frontmatter now", the squirrel reads the file body to determine:
- System file → use the schema from conventions (type-specific required fields)
- Working file → add: squirrel, model, version, description, created
- Companion → add: type, description, date, squirrel, tags + type-specific fields
- README → add: type: system, description, updated

### 3b. Walnut Skeleton

Check the 5 system files exist (`key.md`, `now.md`, `log.md`, `insights.md`, `tasks.md`) and the 3 subdirectories (`_squirrels/`, `_working/`, `_references/`).

Pass: all present. Fail: list what's missing.

### 3c. key.md Completeness

Read `key.md` frontmatter and body. Check:
- Required frontmatter fields filled: `type`, `goal`, `created`, `rhythm`, `tags`
- `people:` populated (especially for ventures — empty people on a venture with collaborators is a gap)
- `links:` matches body references — if body text uses `[[wikilinks]]` not declared in `links:`, flag them
- `tags:` not empty

Pass: all fields filled, links match body. Fail: list gaps.

### 3d. now.md Zero-Context

Read `now.md` (full) and `log.md` (frontmatter + first ~100 lines). Apply the zero-context test: "If a brand new agent loaded this walnut with no prior context, would it have everything it needs to continue the work?"

Fail conditions:
- Context paragraph is empty or just a template comment
- Context is one sentence when log shows 3+ recent sessions of substantial work
- Context references things not in the log (hallucinated or outdated)
- `updated:` timestamp is more than 2 weeks old

**Fix guidance:** When the human picks "rewrite now", the squirrel reads the full log (or as much as needed), synthesises recent sessions into a fresh context paragraph, and regenerates now.md. This is the same operation as alive:save's now.md rewrite.

### 3e. now.md next: Validation

Read `now.md` frontmatter `next:` and `tasks.md` Urgent section. Check:
- `next:` is not empty
- `next:` is not a template placeholder
- If tasks.md has Urgent items, does `next:` align with the top urgent task? Flag conflicts.

Pass: next is set and doesn't conflict with urgent tasks. Fail: missing, empty, or conflicting.

### 3f. Log Health

Read `log.md` frontmatter and first ~150 lines. Check:
- Entries are prepend-ordered (newest at top, dates descending)
- Recent entries are signed (`signed: squirrel:[session_id]`)
- `entry-count:` in frontmatter is roughly accurate (within ±5 of actual)
- `last-entry:` in frontmatter matches the top entry's date

Pass: ordered, signed, counts match. Fail: list specific issues.

### 3g. Stale Walnut Past Rhythm

Compare `key.md` rhythm against `now.md` updated timestamp using the Phase 2 thresholds.

Pass: within rhythm. Fail: quiet or waiting.

```
╭─ 🐿️ housekeeping — stale walnut
│  nova-station has been quiet for 18 days (rhythm: weekly)
│  Last entry: Feb 5 — "locked episode 11 structure"
│
│  → open it / archive it / change rhythm / skip
╰─
```

### 3h. References and Companions

Scan `_core/_references/` recursively. Check:
- **Orphan raw files** — files in `raw/` subdirectories with no corresponding companion `.md`
- **Orphan companions** — `.md` companions whose raw file is missing (note: research companions and extracts legitimately have no raw file — only flag if the companion's `type:` implies a raw source)
- **Companion schema** — companions that exist but are missing required frontmatter fields (`type:`, `description:`, `date:`). A companion without `description:` is almost as invisible as no companion.

Pass: all raw files have companions, all companions have required fields. Fail: list gaps.

### 3i. Stale Working Files and Legacy Naming

Check `_core/_working/` modification timestamps. Flag anything older than 30 days.

Also scan the walnut's live context (folders outside `_core/`) for legacy naming conventions from pre-ALIVE systems (e.g. directories using old naming like `_brain/` instead of `_core/`, `_working/`, `_references/`).

Pass: nothing older than 30 days, no legacy naming. Fail: list stale files and legacy folders.

```
╭─ 🐿️ housekeeping — stale draft
│  _working/submission-draft-v0.1.md — 39 days ago
│  → promote to v1 / archive / delete / skip
╰─
```

### 3j. Tasks Overdue or Stale

Read `_core/tasks.md`. Find tasks marked `[ ]` or `[~]`.

**Primary method:** Check `@session_id` attribution against `_core/_squirrels/` timestamps. Flag tasks with no progress in 2+ weeks.

**Fallback (when timestamps unavailable):** If tasks are tagged `@migrated` or have no attribution, fall back to content-based staleness detection:
- Scan task text for dates, deadlines, or timeframes ("before Mar 18", "post-CNY", "this week")
- Compare against today's date
- Flag tasks whose deadlines have passed or are imminent

Also check structural validity:
- Tasks marked `[x]` still in Urgent/Active sections (should be in Done)
- `[~]` tasks with no recent session touching them

```
╭─ 🐿️ housekeeping — stale task
│  "Send post-CNY message to Louis" — CNY ended Feb 28, 6 days ago
│  → still relevant / remove / reprioritise / blocked (note why) / skip
╰─
```

### Phase 3 Results

Present all 10 results together. Passing checks collapsed, failures listed.

```
╭─ 🐿️ berties audit — 10 checks
│
│  ✓ 3a. malformed files       — all 34 .md files have frontmatter
│  ✓ 3b. walnut skeleton       — complete
│  ⚠ 3c. key.md completeness   — links: [] but body references 4 people
│  ✓ 3d. now.md zero-context   — pass
│  ✓ 3e. now.md next:          — set, aligns with tasks
│  ✓ 3f. log health            — ordered, signed, counts match
│  ✓ 3g. stale rhythm          — active
│  ✓ 3h. references            — all companions valid
│  ⚠ 3i. working files         — 1 legacy pre-ALIVE folder found
│  ⚠ 3j. stale tasks           — 3 past-deadline tasks found
│
│  3 issues to resolve.
╰─
```

Ask which to fix:

```
╭─ 🐿️ berties — which to fix?
│
│  1. key.md links: [] but body references 4 person walnuts
│  2. 3 live context folders using pre-ALIVE naming conventions
│  3. 3 tasks with passed or imminent deadlines
│
│  → which ones? (numbers, "all", or "skip")
╰─
```

For each the human picks, propose the specific fix:

```
╭─ 🐿️ proposed fixes
│
│  1. Add [[will-bainbridge]], [[ben-obrien]], [[jono-georgakopoulos]],
│     [[donnie]] to berties key.md frontmatter links: field
│  3. Move "Send post-CNY message" to Urgent, flag "Ben record Part 2
│     narration" as 12 days to deadline
│
│  → go / change something / skip
╰─
```

**On "go":** dispatch parallel subagents to execute — one per fix. Each subagent reads the file, makes the edit, returns confirmation. Main context does not touch files.

```
╭─ 🐿️ berties — fixes applied
│
│  ✓ key.md links updated — 4 person walnuts added
│  ✓ tasks reprioritised — 1 moved to Urgent, 1 flagged
│  ✗ legacy folders — skipped
│
│  → audit another walnut / done
╰─
```

If "audit another walnut" — return to Phase 2 summary with updated health flags.
If "done" — Final Summary.

---

## Final Summary

```
╭─ 🐿️ housekeeping complete
│
│  Root: 6 checks, 3 issues, 2 resolved
│  berties: 10 checks, 3 issues, 2 resolved
│
│  7 resolved, 2 skipped. World is healthy.
╰─
```
