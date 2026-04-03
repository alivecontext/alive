---
name: alive:bundle
description: "Create, share, and graduate bundles — the unit of focused work within a walnut. Manages the full bundle lifecycle from creation through sharing to graduation."
user-invocable: true
---

# Bundle

Manage the bundle lifecycle: create, share, graduate, status. Bundles are the unit of focused work — anything with a deliverable or a future audience.

This skill is invoked by the bundle awareness injection, by the load skill's "what are you working on?" prompt, or directly by the human via `/alive:bundle`.

---

## Detection — When to Invoke

The spectrum:

| | One-off | Bundle | Walnut |
|---|---------|--------|--------|
| Sessions | This session only | Likely >1, or worth returning to | Own ongoing lifecycle |
| Deliverable | No | Yes — ship, send, or reference later | Multiple deliverables |
| Audience | Just you, right now | Someone specific, or future-you | Has its own people |

**Trigger:** "Does this have a deliverable or a future audience?" If yes -> bundle.

---

## Bundle Types

### Outcome Bundle
The default. A body of work with a deliverable — a document, a plan, a shipped feature. Has drafts, versions, a finish line.

### Evergreen Bundle
Living reference material that grows over time. No "done" state — it accumulates. Research collections, style guides, knowledge bases. Status cycles between `active` and `maintaining` rather than progressing to `done`.

---

## Operations

### Create

When no active bundle matches the current work:

1. Ask for the goal — one sentence. "What are you building?"
2. Determine bundle type — outcome (default) or evergreen
3. Derive the bundle name from the goal (kebab-case, descriptive)
4. Confirm:

```
╭─ squirrel new bundle
│
│  Name:    shielding-review
│  Type:    outcome
│  Walnut:  nova-station
│  Goal:    Evaluate radiation shielding vendors for habitat module
│  Path:    bundles/shielding-review/
│
│  > Good?
│  1. Create
│  2. Change name
│  3. Make it evergreen instead
│  4. Cancel
╰─
```

5. Read `templates/bundle/context.manifest.yaml`
6. Fill placeholders: `{{goal}}`, `{{date}}`, `{{session_id}}`, `{{type}}`
7. Create `bundles/{name}/context.manifest.yaml`
8. Create `bundles/{name}/raw/` (empty directory)
9. Update `_kernel/now.json` -> set `bundle: {name}`
10. Stash: "Created bundle: {name}" (type: note)

The first draft file is `{name}-draft-01.md` when the human starts writing.

---

### context.manifest.yaml

Every bundle has a `context.manifest.yaml` at its root. This is the bundle's identity and state tracker.

```yaml
name: shielding-review
type: outcome              # outcome | evergreen
goal: "Evaluate radiation shielding vendors for habitat module"
status: draft              # draft | prototype | published | done | active | maintaining
created: 2026-03-28
session: abc123

sensitivity: normal        # normal | private | shared
shared: []
discovered: {}

tags: []
people: []
sources: []
```

**Key fields:**
- `type` — outcome or evergreen. Drives lifecycle behavior.
- `status` — outcome bundles: draft -> prototype -> published -> done. Evergreen bundles: active <-> maintaining.
- `sensitivity` — controls sharing and export behavior:
  - `normal` — can be shared freely
  - `private` — excluded from walnut.world publishing, flagged on share attempts
  - `shared` — actively published or shared with specific people
- `discovered` — populated by `alive:mine-for-context` with extraction tracking
- `sources` — paths to raw material or linked references from other bundles

---

### Share

When the human shares a bundle with someone (email, Slack, in person):

1. Check `sensitivity` — if `private`, warn before proceeding
2. Identify: who received it, how (method), which version file
3. Update the bundle's `context.manifest.yaml` `shared:` field:

```yaml
shared:
  - to: Sue Chen
    method: email
    date: 2026-03-15
    version: shielding-review-draft-02.md
```

4. Dispatch to the person's walnut at save (stash with destination tag `-> [[person-name]]`)
5. If bundle status is `draft` and it's been shared externally -> advance to `published`
6. Update sensitivity to `shared` if it was `normal`

```
╭─ squirrel bundle shared
│  shielding-review draft-02 -> Sue Chen via email
│  Status: draft -> published
╰─
```

#### P2P Sharing via /alive:share

For packaging a bundle as a portable `.walnut` file (P2P transfer via AirDrop, USB, email attachment, or relay), use `/alive:share` with `--scope bundle`. This handles:

- Packaging the bundle contents into a `.walnut` archive
- Sensitivity gating and optional passphrase encryption
- Manifest SHA-256 checksums for integrity verification
- Relay push for automatic delivery (if relay configured)

`/alive:share` automatically updates the `shared:` field in `context.manifest.yaml` with encryption status and relay provenance, so manual tracking is not needed for P2P shares.

#### Publishing to walnut.world

When the human wants to publish a bundle to walnut.world:

1. Check `sensitivity` — block if `private`
2. Confirm the human wants public sharing
3. Package the bundle content for walnut.world
4. Update `context.manifest.yaml` with publication record

```
╭─ squirrel bundle published to walnut.world
│  shielding-review v1 -> ben.walnut.world/shielding-review
│  Sensitivity: shared (public)
╰─
```

---

### Graduate

When a bundle has a `*-v1.md` file or the human explicitly requests graduation:

**Outcome bundle -> walnut root:**

1. Detect: scan `bundles/{name}/` for files matching `*-v1.md` or `*-v1.html`
2. Confirm with the human:

```
╭─ squirrel graduation ready
│  shielding-review has a v1. Graduate to walnut root?
│
│  > Graduate?
│  1. Yes — move to walnut root
│  2. Not yet
╰─
```

3. If confirmed:
   - Move the entire `bundles/{name}/` folder to walnut root `{name}/`
   - Update context.manifest.yaml status to `done`
   - Update `_kernel/now.json` -> clear `bundle` if this was the active bundle
   - Log entry: "Bundle {name} graduated to walnut root"

**Bundle -> walnut graduation** (when a bundle outgrows its container):

1. Confirm: "This bundle wants to be a walnut. Graduate it?"
2. Determine ALIVE domain and walnut name
3. Scaffold new walnut (invoke the create flow)
4. Seed `_kernel/key.md` from bundle context.manifest.yaml (goal, tags, people carry over)
5. Move bundle contents into new walnut's `bundles/` as the first bundle
6. Log entry in BOTH parent walnut ("Bundle {name} graduated to walnut") and new walnut ("Graduated from {parent}")
7. Add wikilink `[[new-walnut]]` to parent's `_kernel/key.md` `links:`

---

### Sub-Bundles

Bundles can contain sub-bundles for complex work that has distinct sub-deliverables:

```
bundles/ecosystem-launch/
  context.manifest.yaml          # Parent bundle
  bundles/                       # Sub-bundles
    website/
      context.manifest.yaml
    waitlist/
      context.manifest.yaml
  raw/                           # Shared raw material
```

Sub-bundle rules:
- Sub-bundles inherit `sensitivity` from parent unless overridden
- Sub-bundle status is independent of parent status
- Parent `context.manifest.yaml` lists sub-bundles in a `children:` field
- Sub-bundles can graduate independently (move to parent's `bundles/` level or to walnut root)

---

### Status

Show the current state of bundles in the active walnut:

```
╭─ squirrel bundles in nova-station
│
│  Active: shielding-review (outcome, draft, draft-02)
│    Goal: Evaluate radiation shielding vendors
│    Last worked: session:a8c95e9, 2 days ago
│
│  Others:
│    launch-checklist — outcome, prototype, draft-03
│    safety-brief — outcome, done, shared with FAA (2026-03-10)
│    vendor-database — evergreen, active
│
│  > Work on one?
│  1. shielding-review (continue)
│  2. launch-checklist
│  3. vendor-database
│  4. Start new bundle
╰─
```

Read all bundle `context.manifest.yaml` files in `bundles/` to build this view. Show type, status, current version, goal, last session, and shares.

---

## Version File Naming

- Drafts: `{bundle-name}-draft-{nn}.md` (e.g., `shielding-review-draft-01.md`)
- Shipped: `{bundle-name}-v1.md`
- Visual versions: same pattern with `.html` extension

The bundle name is in every filename. When graduated to walnut root, the folder is self-documenting.

---

## Integration Points

**Load** invokes this skill when prompting "what are you working on?" and the human picks "start something new."

**Save** checks bundle state in its integrity step — was a bundle worked on? Was one shared? This skill handles the actual context.manifest.yaml updates.

**Tidy** scans for `*-v1.md` still in `bundles/` and surfaces graduation candidates.

**Create** delegates bundle scaffolding to this skill rather than handling it inline.

**Awareness injection** triggers this skill when the squirrel detects bundle-worthy work mid-session.

**Mine** updates `context.manifest.yaml` `discovered:` field when processing raw sources within a bundle.
