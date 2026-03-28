---
version: 2.0.0
type: foundational
description: Frontmatter, file naming, signing, wikilinks, third-party skill overrides.
---

# Standards

The infrastructure that prevents entropy. Every file follows these. No exceptions.

---

## Frontmatter on Everything

**This is the most important convention in the system.**

Every `.md` and `.yaml` file in the system has YAML frontmatter (or IS YAML). No exceptions. The frontmatter is the scannable layer — the squirrel reads frontmatter before bodies. If a file doesn't have frontmatter, it's malformed.

| File type | Required frontmatter |
|-----------|---------------------|
| System files (key, now.json, log, insights, tasks) | Schema defined in world.md |
| Bundle manifests (context.manifest.yaml) | type: bundle, goal, status, version, sensitivity, pii, sources, linked_bundles, tags |
| Working files (legacy) | squirrel, model, version, previous, kept, changed |
| Reference companions (legacy) | type, description, type-specific fields, squirrel, tags |
| Rules | version, type, description |
| Skills | name, description, user-invocable |

**Every context.manifest.yaml must have `description:` in frontmatter.** This is the one-line scan that tells the squirrel what the bundle contains without reading the body. It's the difference between a useful reference system and a pile of files.

---

## Signing

Every file the squirrel creates or modifies carries attribution:

- `squirrel: [session_id]` — which session created/modified it
- `model: [engine]` — which AI model was running

Log entries are additionally signed at the end: `signed: squirrel:[session_id]`

Squirrel entries carry the full metadata: session_id, runtime_id, engine, walnut, timestamps.

---

## File Naming

### Bundle Folders (bundles/)

Pattern: `kebab-case-descriptive-name/`

The folder name IS the bundle identity. Short, clear, unique within the walnut.

```
shielding-review/
launch-checklist/
festival-submission/
```

### Bundle Versions

Versions are files inside the bundle. No version in folder name. File names include the bundle name for self-documentation.

Pattern: `{bundle-name}-draft-{nn}.md` for working drafts, `{bundle-name}-v1.md` for shipped.

```
bundles/shielding-review/
  context.manifest.yaml                 <- THE INDEX
  shielding-review-draft-01.md          <- first draft
  shielding-review-draft-02.md          <- iterated
  shielding-review-v1.md                <- graduated
  raw/                                  <- source material
    2026-02-23-jax-review.mp3
    2026-02-20-vendor-proposal.pdf
```

### Raw Files (inside bundles)

Pattern: `YYYY-MM-DD-descriptive-name.ext`

```
2026-02-23-jax-shielding-review.mp3
2026-02-20-vendor-proposal.pdf
```

### Raw File Renaming

Garbage filenames get renamed on import. The original name is preserved in the context.manifest.yaml frontmatter as `original_filename:`.

| Before | After |
|--------|-------|
| `CleanShot 2026-02-23 at 14.32.07@2x.png` | `2026-02-23-competitor-pricing-screenshot.png` |
| `IMG_4892.jpg` | `2026-02-20-prototype-photo.jpg` |
| `Document (3).pdf` | `2026-02-18-vendor-proposal-v3.pdf` |

### Companion Files

Same name as the raw file, `.md` extension. Lives alongside the raw file's parent directory (not inside `raw/`).

```
bundles/transcripts/
  2026-02-23-jax-shielding-review.md      <- companion
  raw/
    2026-02-23-jax-shielding-review.mp3   <- raw
```

---

## Wikilinks

`[[walnut-name]]` is the syntax for linking walnuts together. It's a text convention — not rendered, not enforced by tooling. It's a marker that says "this references another walnut."

**Where to use them:**
- `key.md` frontmatter `links:` field — the canonical list of connections
- `key.md` body — in the Connections and Key People sections
- `log.md` entries — inline when referencing other walnuts ("discussed with [[ryn-okata]]")
- `insights.md` — when an insight relates to another walnut

**Rules:**
- If you add a `[[link]]` inline, also add it to key.md `links:` frontmatter
- `alive:search-world` searches for these across all walnuts
- Person walnuts use `[[first-last]]` format (e.g., `[[ryn-okata]]`)
- Walnut names use kebab-case (e.g., `[[nova-station]]`, `[[glass-cathedral]]`)

---

## Third-Party Skill Overrides

External plugins (superpowers, etc.) assume standard code project layouts — `docs/plans/`, `src/`, `tests/`. These paths don't exist in a World. The squirrel must intercept and reroute.

**Before any skill creates a file, ask:** "Am I in a walnut? Where does this belong?"

| Skill output | Route to instead |
|-------------|-----------------|
| `docs/plans/*.md` | `{active-walnut}/bundles/{bundle-name}/` (create bundle if needed) |
| `docs/*.md` | `{active-walnut}/bundles/{bundle-name}/` |
| Any file at World root | Determine the walnut it belongs to, route to a bundle |

**No orphan files at World root.** The only things at root level are the 5 ALIVE domain folders, `.claude/`, and dotfiles. Everything else belongs inside a walnut.

If no walnut is active and a skill wants to write a file, ask the human where it should go before writing.
