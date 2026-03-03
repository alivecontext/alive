---
version: 0.1.0-beta
type: foundational
description: How worlds are built. Walnut anatomy, ALIVE domains, _core/ structure, archive, references, connections.
---

# World

A World is an ALIVE folder system on the conductor's machine. Every file has frontmatter. Every folder has purpose. Nothing gets deleted. Everything progresses.

---

## The ALIVE Framework

Five domains. The letters are the folders. The file system IS the methodology.

```
01_Archive/       A — Everything that was. Mirror paths. Graduation, not death.
02_Life/          L — Personal. Goals, people, patterns. The foundation.
03_Inputs/        I — Buffer only. Content arrives, gets routed out. Never work here.
04_Ventures/      V — Revenue intent. Businesses, clients, products.
05_Experiments/   E — Testing grounds. Ideas, prototypes, explorations.
```

**Life is the foundation.** Ventures and experiments serve life goals.

**Inputs is a buffer.** Nothing lives here permanently. Route out within 48 hours.

**Archive mirrors paths.** `04_Ventures/old-project/` → `01_Archive/04_Ventures/old-project/`. Still indexed, still searchable. Just not on the dashboard.

---

## The Walnut

A walnut is the unit of context. Any meaningful thing with its own identity, lifecycle, and history.

### Anatomy

```
nova-station/
  _core/                          ← system (the soft core)
    key.md                        what it is
    now.md                        where it is right now
    log.md                        where it's been
    insights.md                   what's known
    tasks.md                      what needs doing
    _squirrels/                   session entries
    _working/                     drafts and versions
    _references/                  source material + companions
  engineering/                    ← live context (the conductor's work)
  regulatory/
  marketing/
  partners/
```

**Everything inside `_core/` is system.** The squirrel's system operations happen here.

**Everything outside `_core/` is live context.** The conductor's actual work — documents, assets, code, creative output. Includes things promoted from `_core/_working/`, things created directly, and things shared with others.

### The Five System Files

| File | Purpose | Changes |
|------|---------|---------|
| `key.md` | Identity — type, goal, people, rhythm, tags, links, references index | Rarely |
| `now.md` | Current state — phase, health, next, updated, squirrel, context paragraph | Every save |
| `log.md` | History — signed entries, prepend-only, chronological | Every save |
| `insights.md` | Domain knowledge — standing facts that persist across sessions | When confirmed |
| `tasks.md` | Work queue — checkboxes, priorities, attribution | Every save |

### key.md Frontmatter

```yaml
---
type: venture | person | experiment | life | project | campaign
goal: one sentence
created: 2026-01-15
rhythm: weekly
parent: [[parent-walnut]]          # if nested
people:
  - name: Ada Chen
    role: engineering lead
    email: ada@novastation.space
tags: [orbital, tourism, engineering]
links: [[ada-chen]], [[glass-cathedral]]
published:
  - slug: orbital-safety-brief
    url: https://you.walnut.world/orbital-safety-brief
    date: 2026-02-23
---
```

### now.md Frontmatter

```yaml
---
phase: testing
health: active
updated: 2026-02-23T14:00:00
next: Review telemetry from test window
squirrel: 2a8c95e9
---
```

**next: protection:** At save, the squirrel checks whether the previous `next:` was completed. If not, it surfaces the conflict. The previous `next:` is never silently dropped.

### now.md Revival Section

An optional `## Revival` section may appear in now.md after `## Context`. This is a lightweight breadcrumb written by the save skill when the squirrel judges a session had significant conversational context worth recovering via `walnut:revive`.

```
## Revival

session: 2a8c95e9
date: 2026-03-02
summary: Deep design discussion on shielding vendor trade-offs — narrowed to three options, no final pick.
```

**Rules:**
- Present = revival pending. Absent = nothing to revive.
- Only one revival marker at a time (latest save wins).
- Cleared on next save regardless of whether revival was run. One-shot marker.
- The squirrel surfaces this whenever now.md is read (behaviour rule). The open skill surfaces it prominently.

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

At 50 entries or phase close → chapter. Synthesis moves to `_core/_chapters/chapter-[nn].md`.

### insights.md

Standing domain knowledge. Updated only when the conductor confirms an insight as evergreen:

```
╭─ 🐿️ insight candidate
│  "Orbital test windows only available Tue-Thu"
│  Commit as evergreen, or just log it?
╰─
```

### tasks.md

```markdown
## Urgent
- [ ] Book ground control sim  @2a8c95e9

## Active
- [~] Telemetry review  @2a8c95e9

## To Do
- [ ] Vendor site visits

## Done
- [x] Confirm test window  (2026-02-20)
```

Markers: `[ ]` not started, `[~]` in progress, `[x]` done. `@session_id` for attribution.

---

## Support Folders

### _squirrels/

One YAML per session. Created at start, signed at exit. See squirrels.md.

### _working/

Drafts and versions. v0.x lives here. v1 graduates to live context. See conventions.md.

### _references/

Source material. Three-tier access: index (key.md) → companion (.md) → raw (actual file). See conventions.md.

---

## Walnuts Inside Walnuts

A walnut can contain sub-walnuts with their own `_core/`. Create when:
- Independent lifecycle (can be started, paused, completed separately)
- Own team, tasks, or rhythm
- Benefits from own log history

Record the relationship in key.md: `parent: [[nova-station]]`. The filesystem nesting is convenience; the `parent:` field is canonical.

Don't create sub-walnuts for simple folders. Use a README instead.

---

## People

Every person who matters has a walnut in `02_Life/people/`. Same `_core/` structure. Cross-referenced via `[[name]]` wikilinks.

People don't get health signals. They show `last updated`. If someone close hasn't had a context update in a while, the squirrel nudges: "Worth reaching out?"

---

## Connections

`[[walnut-name]]` links walnuts together. Used in key.md `links:` field and inline in log entries. `walnut:find` traverses these connections.

---

## Archive

Never delete. Mirror the original path into `01_Archive/`.

Archive is graduation. The walnut served its purpose. Still indexed, still searchable, still linkable. Just not on the dashboard.

---

## Health Signals

For endeavors (ventures, experiments, campaigns). Based on `rhythm:` in key.md.

| Signal | Meaning |
|--------|---------|
| active | Within rhythm |
| quiet | 1-2x past rhythm |
| waiting | 2x+ past rhythm |

People don't get health signals — just `last updated` with nudges.
