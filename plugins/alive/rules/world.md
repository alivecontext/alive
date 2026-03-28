---
version: 2.0.0
type: foundational
description: How worlds are built. Walnut anatomy, ALIVE domains, _kernel/ structure, bundles, archive, connections, People/.
---

# World

A World is an ALIVE Context System folder on the human's machine. Every file has frontmatter. Every folder has purpose. Nothing gets deleted. Everything progresses.

The root is identified by an `.alive/` marker directory. When a session starts, walk up from the working directory until you find `.alive/`. That's the world root.

---

## The ALIVE Framework

Five domains. The letters are the folders. The file system IS the methodology.

```
01_Archive/       A — Everything that was. Mirror paths. Graduation, not death.
02_Life/          L — Personal. Goals, patterns. The foundation.
03_Inputs/        I — Buffer only. Content arrives, gets routed out. Never work here.
04_Ventures/      V — Revenue intent. Businesses, clients, products.
05_Experiments/   E — Testing grounds. Ideas, prototypes, explorations.
People/           — Cross-cutting. Lives at world root, outside ALIVE numbering.
```

**Life is the foundation.** Ventures and experiments serve life goals.

**Inputs is a buffer.** Nothing lives here permanently. Route out within 48 hours.

**Archive mirrors paths.** `04_Ventures/old-project/` → `01_Archive/04_Ventures/old-project/`. Still indexed, still searchable. Just not on the dashboard.

**People is its own domain.** Not numbered, not inside ALIVE. Every person who matters gets a walnut at `People/`. Cross-referenced via `[[name]]` wikilinks. See People section below.

---

## The Walnut

A walnut is the unit of context. Any meaningful thing with its own identity, lifecycle, and history. A project, a person, a venture, an experiment, a life goal.

### Anatomy

```
nova-station/
  _kernel/                             ← system source files
    key.md                             what it is (identity, rarely changes)
    log.md                             where it's been (prepend-only history)
    insights.md                        what's known (standing domain knowledge)
    _generated/                        ← machine-produced projections
      now.json                         current state snapshot (regenerated on save)
    links.yaml                         ← overflow: outbound connections
    people.yaml                        ← overflow: enriched people records
    history/                           ← overflow: log chapters
      chapter-01.md                    synthesized log segment
      chapter-02.md
  bundles/                             ← units of work (the workshop)
    shielding-review/
      context.manifest.yaml            bundle index
      tasks.md                         bundle-scoped work queue
      observations.md                  agent observations
      raw/                             source material
        2026-03-12-screenshot.png
    launch-checklist/
      context.manifest.yaml
      tasks.md
      raw/
  shielding-review/                    ← graduated bundle (moved out of bundles/)
    context.manifest.yaml              historical record
    shielding-review-v1.md             the output
    raw/                               the sources
  engineering/                         ← live context (the human's work)
  regulatory/
  marketing/
```

**System source files live in `_kernel/`.** key.md, log.md, insights.md — the three source files the squirrel reads and writes. These are the canonical sources of truth.

**Generated projections live in `_kernel/_generated/`.** now.json is produced by the save protocol — a computed snapshot, never hand-edited. Any tooling that needs current state reads from here.

**Kernel overflow files** handle growth:
- `links.yaml` — when `links:` in key.md gets long (10+ entries), move the full list here and keep key.md's `links:` as a summary pointer.
- `people.yaml` — when `people:` in key.md gets long (5+ entries with enriched records), move the full records here. key.md keeps names and roles.
- `history/` — log chapters. At 50 entries or phase close, synthesize older entries into `chapter-[nn].md` and keep log.md lean.

**`bundles/` is the workshop.** Active bundles — both outcome and evergreen — live here. Outcome bundles graduate to walnut root when they ship v1. See `bundles.md` for lifecycle and management.

**Everything else is live context.** The human's actual work — documents, assets, code, creative output. Includes things graduated from bundles, things created directly, and things shared with others.

**Backward compat:** Check `_kernel/` first for system files. Fall back to `_core/` (v1 name) then walnut root for migrated or flat-structure walnuts. now.md at `_core/now.md` or walnut root is still valid — the system treats it as source until migrated to `_kernel/_generated/now.json`.

### The Three Source Files

| File | Purpose | Changes |
|------|---------|---------|
| `_kernel/key.md` | Identity — type, goal, people, rhythm, tags, links, repo | Rarely |
| `_kernel/log.md` | History — signed entries, prepend-only, chronological | Every save |
| `_kernel/insights.md` | Domain knowledge — standing facts that persist across sessions | When confirmed |

### Generated Projections

| File | Purpose | Regenerated |
|------|---------|-------------|
| `_kernel/_generated/now.json` | Current state — phase, active bundle, next action, updated timestamp, squirrel, context | Every save |

now.json is regenerated from scratch on every save — full replacement, not patch. It is a computed projection of the walnut's current state. Never hand-edit it. If you need to understand where a walnut is, read now.json. If you need to change where a walnut is, save and let the protocol rebuild it.

### key.md Frontmatter

```yaml
---
type: venture | person | experiment | life | project | campaign
goal: one sentence
created: 2026-01-15
rhythm: weekly
parent: [[parent-walnut]]          # if nested
repo: github.com/org/repo          # for dev projects — links to external codebase
people:
  - name: Ryn Okata
    role: engineering lead
    email: ryn@novastation.space
tags: [orbital, tourism, engineering]
links: [[ryn-okata]], [[glass-cathedral]]
published:
  - slug: orbital-safety-brief
    url: https://you.walnut.world/orbital-safety-brief
    date: 2026-02-23
---
```

When `people:` grows beyond 5 enriched entries, move the full records to `_kernel/people.yaml` and keep key.md's list as name + role only.

When `links:` grows beyond 10 entries, move the full list to `_kernel/links.yaml` and keep key.md's list as the top connections.

**`repo:` field.** For dev projects, `repo:` points at the external codebase. The session hook can reverse-lookup: given a working directory inside a repo, find the walnut that tracks it. This bridges the walnut world and the code world.

### log.md Frontmatter

```yaml
---
walnut: nova-station
created: 2026-01-15
last-entry: 2026-02-23T14:00:00
entry-count: 47
summary: Orbital test window confirmed. Shielding vendor shortlisted.
---
```

Log entries are prepend-only. Newest after frontmatter. Every entry signed.

At 50 entries or phase close → chapter. Synthesis moves to `_kernel/history/chapter-[nn].md`. The chapter contains a summary and the full entries. log.md's entry count resets for the active chapter but `entry-count:` in frontmatter reflects the total.

### insights.md

Standing domain knowledge. Updated only when the human confirms an insight as evergreen:

```
╭─ 🐿️ insight candidate
│  "Orbital test windows only available Tue-Thu"
│  Commit as evergreen, or just log it?
╰─
```

### now.json (Generated)

```json
{
  "phase": "testing",
  "updated": "2026-02-23T14:00:00",
  "bundle": "shielding-review",
  "next": "Review telemetry from test window",
  "squirrel": "2a8c95e9",
  "context": "Shielding vendor shortlisted after 3 rounds. Test window confirmed March 4."
}
```

`bundle:` points at the active bundle being worked on. `next:` is contextualized by which bundle it belongs to. Health is derived (see Health Signals below), not stored.

**next: protection:** At save, the squirrel checks whether the previous `next:` was completed. If not, it surfaces the conflict. The previous `next:` is never silently dropped.

---

## Bundles

Units of work. Each bundle is a folder inside `bundles/` with a `context.manifest.yaml` index, scoped tasks, observations, and a `raw/` folder for source material. See `bundles.md` for full anatomy, lifecycle, species, and management.

Three-tier access: manifest frontmatter (scan) → manifest body fields (read) → raw files (deep).

Outcome bundles graduate to walnut root when they ship v1 and the human confirms. The graduated folder at walnut root becomes a historical record alongside live context.

### Legacy: _core/_capsules/, _working/, _references/

Walnuts still using `_core/_capsules/` with `companion.md` files are supported. Walnuts using `_core/_working/` and `_core/_references/` are also supported. Migration converts these to bundles inside `bundles/`. See `bundles.md` for migration notes.

---

## Creating a New Walnut

1. Create the walnut folder under the appropriate ALIVE domain (or `People/` for a person).
2. Create `_kernel/` and `_kernel/_generated/` inside it.
3. Write the 3 source files to `_kernel/`: key.md, log.md, insights.md.
4. Generate `_kernel/_generated/now.json` with initial state.
5. Create `bundles/`.
6. Record `parent:` in `_kernel/key.md` if this is a sub-walnut.

---

## Walnuts Inside Walnuts

A walnut can contain sub-walnuts (folders with their own `_kernel/key.md` and system files). Create when:
- Independent lifecycle (can be started, paused, completed separately)
- Own team, tasks, or rhythm
- Benefits from own log history

Record the relationship in `_kernel/key.md`: `parent: [[nova-station]]`. The filesystem nesting is convenience; the `parent:` field is canonical.

Don't create sub-walnuts for simple folders. Use a README instead.

---

## People

Every person who matters has a walnut in `People/` at the world root. Same system file structure (inside `_kernel/`). Cross-referenced via `[[name]]` wikilinks.

People live outside the ALIVE numbering because they cross-cut everything — a person relates to ventures, experiments, life goals, and archived projects equally. Putting them in `02_Life/` was v1 convention; v2 elevates them.

People don't get health signals. They show `last updated`. If someone close hasn't had a context update in a while, the squirrel nudges: "Worth reaching out?"

**Backward compat:** Walnuts in `02_Life/people/` are still recognized. No forced migration.

---

## Connections

`[[walnut-name]]` links walnuts together. Used in `_kernel/key.md` `links:` field (or `_kernel/links.yaml` for overflow) and inline in log entries. `alive:search-world` traverses these connections.

---

## Archive

Never delete. Mirror the original path into `01_Archive/`.

Archive is graduation. The walnut served its purpose. Still indexed, still searchable, still linkable. Just not on the dashboard.

---

## Health Signals

For endeavors (ventures, experiments, campaigns). Calculated from `rhythm:` in `_kernel/key.md` and `updated:` in `_kernel/_generated/now.json`.

### Calculation

```
days_since = today - now.json updated date
rhythm_days = { daily: 1, weekly: 7, biweekly: 14, monthly: 30 }

if days_since <= rhythm_days:        health = "active"
if days_since <= rhythm_days * 2:    health = "quiet"
if days_since > rhythm_days * 2:     health = "waiting"
```

| Signal | Meaning | Dashboard |
|--------|---------|-----------|
| active | Within rhythm | No flag |
| quiet | 1-2x past rhythm | Shown in tree |
| waiting | 2x+ past rhythm | Warning + days count |

### People

People don't get health signals — just `last updated` with nudges. If someone close hasn't had a context update in 2+ weeks, surface: "Worth reaching out to [name]?"

### Preference Toggle

`health_nudges: false` in `.alive/preferences.yaml` disables proactive nudging. Health is still calculated and shown on the dashboard — you just won't volunteer it unprompted.

---

## Dev Projects

Walnuts that track external codebases include `repo:` in `_kernel/key.md`. This enables:

- **Reverse lookup:** The session hook checks the current working directory against known `repo:` fields to auto-detect which walnut is relevant.
- **Context bridging:** The squirrel can reference code context (branches, PRs, CI status) alongside walnut context (log, insights, tasks).
- **Multiple repos:** A walnut can track multiple repos via a list in `repo:`.

```yaml
repo: github.com/stackwalnuts/alive-context
# or multiple:
repo:
  - github.com/stackwalnuts/alive-context
  - github.com/stackwalnuts/alive-web
```

---

## Root Detection

The world root is identified by the `.alive/` marker directory. To find the world root:

1. Start from the current working directory.
2. Walk up the directory tree.
3. The first directory containing `.alive/` is the world root.

`.alive/` contains world-level configuration: `key.md` (world index), `preferences.yaml` (worldbuilder overrides), `_squirrels/` (session entries), `statusline.sh`, and generated indexes.
