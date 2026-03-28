---
version: 2.0.0
type: foundational
description: The bundle system. Anatomy, species, lifecycle, graduation, routing, collaboration, context flow.
---

# Bundles

A bundle is a self-contained unit of work inside a walnut. Lives in `bundles/`. Contains a context.manifest.yaml index, scoped tasks, agent observations, and a raw/ folder for source material.

---

## Two Species

Same anatomy, different destiny.

**Outcome bundles** — produce something specific. Goal describes a deliverable ("Rebuild stellarforge.space from TWD strategy deck"). Iterates through versioned drafts. Has a done state. Graduates to walnut root when v1 ships.

**Evergreen bundles** — accumulate related context over time. Goal describes a collection or ongoing concern ("Collect and index all Nova Station call transcripts"). The manifest IS the value — synthesizes what's in raw/. Status stays `active` (ongoing) or `done` (retired). Never graduates. Lives in `bundles/` permanently.

Evergreen bundles CAN have non-versioned documents inside (synthesis.md, patterns.md) — these are derived context, not v0.x progression. If a synthesis grows big enough to need its own drafts, it spawns an outcome bundle.

No `bundle_type:` field needed — the `goal:` field tells you which kind it is. A deliverable goal = outcome. A collection/ongoing goal = evergreen.

---

## Bundle Anatomy

```
bundles/website-rebuild/
  context.manifest.yaml                 <- The scannable index
  tasks.md                              <- Bundle-scoped work queue
  observations.md                       <- Agent observations (append-only)
  website-rebuild-draft-01.md           <- Working drafts
  website-rebuild-draft-02.md
  raw/                                  <- Source material
    2026-03-12-screenshot.png
    2026-03-15-competitor-analysis.pdf
  skills/                               <- Bundle-specific skills (optional)
    deploy.md
```

### Files

| File | Purpose | Required |
|------|---------|----------|
| `context.manifest.yaml` | Bundle index — identity, status, sources, sessions | Yes |
| `tasks.md` | Work queue scoped to this bundle | Yes |
| `observations.md` | Agent-written observations, patterns, and notes | No (created on first observation) |
| `raw/` | Source material — documents, screenshots, data | No (created when sources arrive) |
| `skills/` | Bundle-specific skill definitions | No (rare, for specialized workflows) |

---

## The Context Manifest

The `context.manifest.yaml` file is the bundle's identity and scannable index. Everything a squirrel needs to understand the bundle at a glance.

### Full Schema

```yaml
# === Identity ===
goal: "One sentence describing what this bundle produces or collects"
status: draft                          # draft | prototype | published | done
version: v0.2                         # current version
sensitivity: private                   # open | private | restricted
pii: false                            # whether raw/ contains personally identifiable info
species: outcome                       # outcome | evergreen (optional — inferred from goal)

# === Lifecycle ===
created: 2026-03-11
updated: 2026-03-15
discovered: 2026-03-10                 # when the need was first identified (optional)

# === Mining State ===
mining: active                         # active | paused | exhausted (optional, for research bundles)

# === Context ===
context: |
  Current state paragraph. What's happening right now.
  Updated on save, like now.json but scoped to this bundle.

# === Sources ===
sources:
  - path: raw/2026-02-23-doc.pdf
    description: Vendor proposal from Orbital Systems
    type: document                     # document | transcript | screenshot | data | code | link
    date: 2026-02-23
  - path: ../other-bundle/raw/shared-file.md
    description: Shared research from related bundle
    type: document
    date: 2026-03-01

# === Relationships ===
linked_bundles: [[website], [brand-brief]]
parent_bundle: null                    # if this is a sub-bundle
tags: [engineering, vendors]

# === Agent Sessions ===
squirrels: [bc96e49c, a3f7c2d1]       # all sessions that touched this bundle
active_sessions:
  - session: a8c95e9
    engine: claude-opus-4-6
    started: 2026-03-12T14:00:00
    working_on: "v0.3 — restructuring intro section"

# === Publishing ===
published:
  - slug: orbital-safety-brief
    url: https://you.walnut.world/orbital-safety-brief
    date: 2026-03-20
```

### Required Fields

Only `goal:` and `status:` are required. Everything else has sensible defaults or is created when needed. The schema is lenient — unknown fields are ignored, every field defaults, no value validation.

---

## tasks.md

Bundle-scoped work queue. Same format as walnut-level tasks:

```markdown
## Active
- [~] Restructure intro section  @a8c95e9

## To Do
- [ ] Source competitor screenshots
- [ ] Draft pricing page copy

## Done
- [x] Initial wireframe  (2026-03-12)
```

Markers: `[ ]` not started, `[~]` in progress, `[x]` done. `@session_id` for attribution.

Tasks here are scoped to this bundle only. Walnut-level tasks that span bundles live in the walnut's own task tracking (or `_kernel/` system if the walnut uses one).

---

## Agent Observations

`observations.md` is the squirrel's notebook for this bundle. Append-only. Each entry is timestamped and signed. Things the agent notices that aren't decisions, tasks, or insights — but are worth preserving.

```markdown
---
bundle: website-rebuild
entries: 3
---

## 2026-03-15 @a8c95e9

The competitor analysis shows a clear pattern: everyone leads with features, nobody leads
with the problem. This is a positioning gap we can exploit. The TWD deck already has the
language — page 4's "context as property" framing is stronger than anything competitors use.

## 2026-03-13 @bc96e49c

First pass at wireframe revealed the nav structure from the old site doesn't map to the
new content hierarchy. Need to rethink information architecture before drafting pages.
```

Observations are NOT the same as insights. Insights are confirmed evergreen knowledge that lives in `_kernel/insights.md`. Observations are bundle-scoped notes that may or may not become insights.

---

## Bundle Lifecycle

Bundles have a status-based lifecycle. Versions are files inside the bundle.

```
draft       -> prototype   -> published   -> done
started       has visual     shared        outputs graduated
```

- **draft** — actively being worked on. Markdown only.
- **prototype** — has a visual (HTML), maybe shared with 1-2 people.
- **published** — shared externally. Manifest tracks `published:` metadata.
- **done** — outputs graduated to live context. Bundle is historical record.

Version files inside the bundle use the bundle name for self-documentation:
- `{bundle-name}-draft-{nn}.md` — working drafts (e.g., `website-rebuild-draft-01.md`)
- `{bundle-name}-draft-{nn}.html` — visual versions (optional)
- `{bundle-name}-v1.md` / `{bundle-name}-v1.html` — the graduated version

### Before Iterating

Every version after v0.1 should update the `context:` field in the manifest about what changed. The manifest forces the question: what worked, what didn't, what's different this time?

---

## Graduation

### Outcome bundle -> walnut root

- Mechanical signal: a `*-v1.md` (or `*-v1.html`) file gets written
- Squirrel notices and asks: "v1 exists. Graduate this bundle?"
- Human confirms -> folder moves from `bundles/` to walnut root
- Status flips to `done` or `published` in manifest
- Two keys to turn: v1 exists + human says yes.

### Bundle -> walnut graduation

When a bundle outgrows its parent walnut:

- Pure judgment. Squirrel surfaces when bundle gets heavy.
- Signals: too many sources, needs own sessions/log/people, own rhythm, independent lifecycle
- context.manifest.yaml seeds the new walnut's `_kernel/key.md`
- Three levels of growth: raw material -> bundle -> graduated bundle -> walnut

```
╭─ 🐿️ this bundle is getting heavy
│  12 sources, 3 active sessions, own task list growing.
│
│  ▸ Graduate to its own walnut?
│  1. Yeah, promote it
│  2. Keep it as a bundle
│  3. Let me think about it
╰─
```

---

## Bundle Routing Heuristic

When content arrives or work begins:

```
Does an active bundle match this goal?
|-- Yes, exact match -> add to it
|-- Related but different goal -> new bundle, link to existing
|-- Ambiguous -> ask once
+-- No match -> new bundle
```

The core heuristic is **goal alignment**:
- Same goal -> same bundle
- Related goal -> linked bundles (not merge)
- Different goal -> new bundle
- Goal outgrew the bundle -> bundle -> walnut graduation

When ambiguous, ask once:

```
╭─ 🐿️ this relates to [[existing-bundle]]
│  Add to it, or start a fresh bundle?
│
│  ▸ Which one?
│  1. Add to existing
│  2. Start fresh
│  3. Link them
╰─
```

### Merge is Rare

If two bundles overlap, link them or spawn a third that synthesizes both. Only merge when "these should never have been separate" — pick primary, move other's raw/ in, archive empty shell. Never merge silently.

---

## Sub-Bundles

Bundles can nest. A bundle folder can contain its own `bundles/` directory for decomposing large efforts.

```
bundles/product-launch/
  context.manifest.yaml
  tasks.md
  bundles/                             <- sub-bundles
    landing-page/
      context.manifest.yaml
      tasks.md
      raw/
    email-sequence/
      context.manifest.yaml
      tasks.md
      raw/
```

Sub-bundles record their parent: `parent_bundle: product-launch` in manifest. The parent manifest doesn't need to enumerate children — the filesystem does that.

Use sub-bundles when a bundle has clearly separable workstreams that benefit from independent tracking. Don't nest deeper than two levels — if a sub-bundle needs its own sub-bundles, it should probably be its own walnut.

---

## Context Routing (Bidirectional Flow)

Bundles and their parent walnut exchange context in both directions.

### Bundle -> Walnut Kernel

At save, the squirrel routes confirmed items from the bundle back to the walnut:
- Decisions -> `_kernel/log.md` (prepended as log entries)
- Confirmed insights -> `_kernel/insights.md`
- People updates -> `_kernel/key.md` people section (or `_kernel/people.yaml`)
- Active bundle reference -> `_kernel/_generated/now.json` `bundle:` field

### Walnut Kernel -> Bundle

When opening a bundle, the squirrel reads the walnut kernel first (key.md, now.json, insights.md) to establish context. The walnut's identity and standing knowledge inform bundle work.

---

## Sensitivity

Three levels of sensitivity per bundle:

| Level | Meaning | Sharing |
|-------|---------|---------|
| `open` | No restrictions | Can be published to walnut.world |
| `private` | Internal only | Not shared externally, not published |
| `restricted` | Sensitive content | Flagged for extra caution, PII check |

When `pii: true`, the squirrel warns before any sharing or publishing operation. Raw files in restricted bundles are never included in exports or snapshots.

---

## Multi-Agent Collaboration

### 1. Active session claim

`active_sessions:` in manifest (spec above). When opening a bundle for work, add yourself. When saving/closing, remove yourself. Others see who's working and what they're touching.

### 2. Bundle-scoped tasks

Each bundle has its own `tasks.md`. This is the single source of truth for work items in that bundle. No split between bundle and walnut task lists.

### 3. Append-only observations

`observations.md` in the bundle folder. Each session adds at bottom. Never edit previous entries. Includes session_id and timestamped content.

### 4. Immutable version files

Create v0.4.md, don't edit v0.3.md. If concurrent agents work on different aspects, they write different version files. Merge in next version.

### 5. Distributed tasks

When multiple agents work on a bundle, each claims specific tasks in `tasks.md` with `@session_id`. Unclaimed tasks are available. Two agents should never work the same task simultaneously.

---

## Cross-Bundle References

References live inside bundles. The context manifest IS the index.

### Three Tiers

1. **Scan** — Manifest `sources:` list. The squirrel scans `bundles/*/context.manifest.yaml` and reads the sources array. Each source has `path:`, `description:`, `type:`, `date:`. This IS the index.
2. **Read** — Manifest `context:` field and observations.md. Current state and agent-written notes about the bundle.
3. **Deep** — Raw files in `bundles/{name}/raw/`. Only loaded on explicit request.

The squirrel scans tier 1 (manifest sources) at open or on demand. Goes to tier 2 (context + observations) when specific context is needed. Goes to tier 3 (raw) only when specifically asked.

### Shared Sources

When a source feeds multiple bundles:
- The raw file lives where it was first captured
- Other bundles link to it via `sources:` path in their manifest
- One source of truth, multiple consumers
- Path references are relative: `../other-bundle/raw/filename.md`

---

## Mining State

For research-heavy or evergreen bundles, the `mining:` field tracks source exhaustion:

| State | Meaning |
|-------|---------|
| `active` | Actively gathering sources, more expected |
| `paused` | Temporarily stopped gathering, will resume |
| `exhausted` | All known sources captured, analysis phase |

This is optional. Most outcome bundles don't need it — it's for bundles where source collection is a significant part of the work.

---

## Stale Bundles

Bundles in `draft` status unchanged for 30+ days are surfaced by system cleanup:

```
╭─ 🐿️ stale bundle detected
│  "website-rebuild" has been in draft for 45 days
│
│  ▸ What should we do?
│  1. Advance it (move to prototype)
│  2. Archive it (set status to done, note reason)
│  3. Kill it (draft bundles are disposable)
│  4. Leave it for now
╰─
```

- **Advance** -> move to prototype or published
- **Archive** -> set status to done, note reason in context
- **Kill** -> delete (bundles in draft are disposable)

---

## Sharing and walnut.world

Bundles with `sensitivity: open` can be published to walnut.world. The `published:` field in the manifest tracks what's been shared:

```yaml
published:
  - slug: orbital-safety-brief
    url: https://you.walnut.world/orbital-safety-brief
    date: 2026-03-20
```

Publishing is always explicit — the squirrel asks, the human confirms. The bundle's graduated output (v1+) is what gets published, not the raw sources or draft history.

---

## Legacy Support

### Capsules -> Bundles Migration

Walnuts with `_core/_capsules/` using `companion.md` files are fully supported. The mapping:

| v1 (Capsules) | v2 (Bundles) |
|----------------|--------------|
| `_core/_capsules/` | `bundles/` |
| `companion.md` | `context.manifest.yaml` |
| `## Tasks` (pointer to walnut tasks) | `tasks.md` (bundle-scoped) |
| `## Work Log` (in companion body) | `observations.md` (standalone) |
| `## Changelog` (in companion body) | `context:` field in manifest |
| `sources:` (in companion frontmatter) | `sources:` (in manifest) |
| `linked_capsules:` | `linked_bundles:` |
| Reference capsule | Evergreen bundle |
| Work capsule | Outcome bundle |

Migration is not forced. The squirrel reads both formats. When a v1 capsule is actively worked on, the squirrel can offer to migrate it:

```
╭─ 🐿️ this capsule uses the v1 format
│
│  ▸ Migrate to v2 bundle structure?
│  1. Yeah, migrate now
│  2. Keep the old format
╰─
```

### _working/ and _references/

Walnuts with `_core/_working/` and `_core/_references/` still work. The three-tier concept is the same — just the storage location differs. Legacy companions are scanned the same way. Migration converts them to bundles.
