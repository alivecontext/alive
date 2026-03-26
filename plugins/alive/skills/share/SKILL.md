---
description: "Package walnut context into a portable .walnut file for sharing via any channel -- email, AirDrop, Slack, USB. Supports three scopes (full, capsule, snapshot), sensitivity gating, and optional age encryption."
user-invocable: true
---

# Share

Package walnut context for someone else. The export side of P2P sharing.

A `.walnut` file is a gzip-compressed tar archive with a manifest. Three scopes: full walnut handoff, capsule-level sharing, or a lightweight snapshot for status updates. Optional passphrase encryption via `age`.

The skill runs in the current walnut by default. If a walnut name is provided as an argument, operate on that walnut instead -- read its `_core/` before proceeding.

---

## Prerequisites

Read the format spec before generating any package. The template lives relative to the plugin install path:

```
templates/walnut-package/format-spec.md    -- full format specification
templates/walnut-package/manifest.yaml     -- manifest template with field docs
```

The squirrel MUST read both files before packaging. Do not reconstruct the manifest schema from memory.

---

## Flow

### Step 1 -- Scope Selection

```
╭─ 🐿️ share
│
│  What are you sharing from [walnut-name]?
│
│  ▸ Scope
│  1. Full walnut -- entire _core/ (creates new walnut on import)
│  2. Capsule -- one or more work/reference capsules
│  3. Snapshot -- key + now + insights (read-only status briefing)
╰─
```

If the walnut has no capsules in `_core/_capsules/`, suppress option 2.

---

### Step 2 -- Capsule Picker (capsule scope only)

Read all `_core/_capsules/*/companion.md` frontmatter. Present each capsule with its sensitivity status shown prominently.

```
╭─ 🐿️ pick capsules
│
│  1. shielding-review    draft    private
│  2. safety-brief        done     restricted ⚠
│  3. vendor-analysis     draft    private      pii: true ⚠
│
│  ▸ Which ones? (number, several "1,3", or "all")
╰─
```

Multi-select is allowed. Multiple capsules go into one package.

---

### Step 3 -- Sensitivity Gate

For each selected capsule (or all capsules if full scope), read `sensitivity:` and `pii:` from companion frontmatter.

**Sensitivity levels:**

| Level | Action |
|-------|--------|
| `public` | No gate. Proceed. |
| `private` | Soft note: "This capsule is marked private." No blocking. |
| `restricted` | Warn prominently. Recommend encryption. Require explicit "yes, share it" before proceeding. |

**PII check:**

If any capsule has `pii: true`, block by default:

```
╭─ 🐿️ sensitivity gate
│
│  ⚠ vendor-analysis contains personal data (pii: true).
│  Sharing PII requires explicit confirmation.
│
│  ▸ Continue?
│  1. Yes, I understand -- proceed
│  2. Cancel
╰─
```

The human must choose option 1 to proceed. This follows the confirm-before-external pattern from `rules/human.md`.

If any content is `restricted` or has PII, recommend encryption at Step 5 (but don't force it).

---

### Step 4 -- Scope Confirmation

Build the file list for the selected scope. Show what will be packaged:

```
╭─ 🐿️ package contents
│
│  Scope:    capsule
│  Capsules: shielding-review, safety-brief
│  Files:    12 files
│  Est size: ~2.4 MB
│
│  Includes: 2 companions, 4 drafts, 6 raw files
│  Plus: _core/key.md (parent context)
│
│  ▸ Package it?
│  1. Yes
│  2. Add a personal note first
│  3. Cancel
╰─
```

If the human picks "Add a personal note", ask for the note. It goes into the manifest's `note:` field and is shown in a bordered block on import.

**Cross-capsule path warning:** Scan capsule companion `sources:` entries for paths containing `../`. If found:

```
╭─ 🐿️ heads up
│
│  shielding-review references files in other capsules
│  via relative paths (../vendor-analysis/raw/specs.pdf).
│  These paths will break for the recipient.
│
│  The references are preserved as historical metadata.
│  Proceeding.
╰─
```

This is informational only -- do not block.

---

### Step 5 -- Encryption Prompt

Check whether `age` is available:

```bash
command -v age >/dev/null 2>&1
```

**If age is available:**

```
╭─ 🐿️ encryption
│
│  age is available. Encrypt this package?
│  (Recipient will need the passphrase to open it.)
│
│  ▸ Encrypt?
│  1. Yes -- passphrase encrypt
│  2. No -- send unencrypted
╰─
```

If content was flagged `restricted` or `pii: true` in Step 3, surface that context:

```
╭─ 🐿️ encryption (recommended)
│
│  This package contains restricted/PII content.
│  Encryption is strongly recommended.
│
│  ▸ Encrypt?
│  1. Yes -- passphrase encrypt
│  2. No -- I accept the risk
╰─
```

If the human chooses to encrypt, `age -p` prompts for a passphrase interactively via the Bash tool. The squirrel does not handle the passphrase -- `age` manages it directly.

**If age is NOT available:**

```
╭─ 🐿️ encryption unavailable
│
│  age is not installed. Package will be unencrypted.
│  Install: brew install age (macOS) or apt install age (Linux)
│
│  ▸ Continue without encryption?
│  1. Yes
│  2. Cancel (install age first)
╰─
```

If content is `restricted` or `pii: true` and age is unavailable, add a stronger warning that the content will be sent in cleartext.

---

### Step 6 -- Package Creation

This is the core packaging step. The squirrel executes these bash commands via the Bash tool.

#### 6a. Prepare staging directory

```bash
STAGING=$(mktemp -d)
WALNUT_PATH="<path to the walnut being shared>"
WALNUT_NAME="<walnut directory name>"
```

#### 6b. Copy files to staging based on scope

**Full scope:**
```bash
# Copy _core/ to staging, excluding _squirrels/, _index.yaml, and OS artifacts
mkdir -p "$STAGING/_core"
rsync -a --exclude='_squirrels' --exclude='_index.yaml' --exclude='.DS_Store' --exclude='Thumbs.db' --exclude='desktop.ini' "$WALNUT_PATH/_core/" "$STAGING/_core/"
```

**Capsule scope:**
```bash
# Copy key.md for parent context
mkdir -p "$STAGING/_core"
cp "$WALNUT_PATH/_core/key.md" "$STAGING/_core/key.md"

# Copy each selected capsule
for CAPSULE in <capsule-names>; do
  mkdir -p "$STAGING/_core/_capsules/$CAPSULE"
  rsync -a --exclude='.DS_Store' "$WALNUT_PATH/_core/_capsules/$CAPSULE/" "$STAGING/_core/_capsules/$CAPSULE/"
done
```

**Snapshot scope:**
```bash
mkdir -p "$STAGING/_core"
cp "$WALNUT_PATH/_core/key.md" "$STAGING/_core/key.md"
cp "$WALNUT_PATH/_core/now.md" "$STAGING/_core/now.md"
cp "$WALNUT_PATH/_core/insights.md" "$STAGING/_core/insights.md"
```

#### 6c. Strip ephemeral data from capsule companions

For capsule and full scopes, strip `active_sessions:` from every companion in staging. The squirrel reads each `companion.md`, removes the `active_sessions:` key entirely from frontmatter, and writes the cleaned version back. This is done on the staging copy -- the original is never modified.

Use the Read tool to read each companion, then the Edit tool (or Write tool) to write the cleaned version to the staging path. Do not use sed for YAML manipulation -- parse frontmatter properly.

#### 6d. Generate manifest.yaml

Read the manifest template from `templates/walnut-package/manifest.yaml`. Fill every field:

- `format_version`: `"1.0.0"`
- `source.walnut`: the walnut directory name
- `source.session_id`: current session ID
- `source.engine`: current model name
- `source.plugin_version`: read from the ALIVE plugin (use `"1.0.0"` if not determinable)
- `scope`: `"full"`, `"capsule"`, or `"snapshot"`
- `created`: current ISO 8601 timestamp with timezone
- `encrypted`: `true` if encrypting, `false` otherwise
- `description`: auto-generated from `key.md` goal (full/snapshot) or capsule companion goal (capsule scope -- join multiple goals with "; ")
- `note`: the personal note if provided, otherwise omit the field
- `capsules`: list of capsule names (capsule scope only, otherwise omit)

**Compute checksums and sizes for every file in staging** (except manifest.yaml itself):

```bash
# macOS
if command -v shasum >/dev/null 2>&1; then
  find "$STAGING" -type f ! -name 'manifest.yaml' -exec shasum -a 256 {} \;
# Linux fallback
elif command -v sha256sum >/dev/null 2>&1; then
  find "$STAGING" -type f ! -name 'manifest.yaml' -exec sha256sum {} \;
fi
```

For file sizes:
```bash
find "$STAGING" -type f ! -name 'manifest.yaml' -exec stat -f '%z %N' {} \;  # macOS
# or: find "$STAGING" -type f ! -name 'manifest.yaml' -exec stat --format='%s %n' {} \;  # Linux
```

Build the `files:` array from these results. Paths must be relative to the staging root (strip the staging prefix). Sort entries lexicographically by path.

Write the completed `manifest.yaml` to `$STAGING/manifest.yaml`.

#### 6e. Create the archive

Ask the human for the output path. Suggest Desktop as default:

```
╭─ 🐿️ output
│
│  Where should I save the package?
│  Default: ~/Desktop/nova-station-capsule-2026-03-26.walnut
│
│  ▸ Path? (press enter for default)
╰─
```

Filename follows the naming convention from the format spec:
```
<walnut-name>-<scope>-<YYYY-MM-DD>.walnut[.age]
```

If a file with that name already exists, append a sequence number: `-2`, `-3`, etc.

**Unencrypted:**
```bash
COPYFILE_DISABLE=1 tar -czf "<output-path>.walnut" -C "$STAGING" .
```

**Encrypted:**
```bash
COPYFILE_DISABLE=1 tar -czf - -C "$STAGING" . | age -p > "<output-path>.walnut.age"
```

Note: `age -p` will prompt for a passphrase interactively in the terminal.

#### 6f. Generate .walnut.meta sidecar (encrypted packages only)

If the package was encrypted, write a cleartext `.walnut.meta` file alongside:

```yaml
# Cleartext preview. Not required for import.
source:
  walnut: <walnut-name>
  scope: <scope>
  capsules: [<capsule-names>]     # capsule scope only
created: <ISO 8601 timestamp>
encrypted: true
description: "<description>"
note: "<note>"                    # if provided
file_count: <number of files>
```

Write this to `<output-path>.walnut.meta`.

#### 6g. Clean up staging

```bash
rm -rf "$STAGING"
```

---

### Step 7 -- Output

Show the result:

```
╭─ 🐿️ packaged
│
│  File: ~/Desktop/nova-station-capsule-2026-03-26.walnut
│  Size: 2.4 MB
│  Scope: capsule (shielding-review, safety-brief)
│  Encrypted: no
│
│  Send it however you like -- email, AirDrop, Slack, USB.
│  Recipient imports with /alive:receive.
╰─
```

If encrypted, also show the meta file path:

```
╭─ 🐿️ packaged
│
│  Package: ~/Desktop/nova-station-capsule-2026-03-26.walnut.age
│  Preview: ~/Desktop/nova-station-capsule-2026-03-26.walnut.meta
│  Size: 2.4 MB (encrypted)
│  Scope: capsule (shielding-review, safety-brief)
│
│  Share the passphrase separately from the file.
│  Recipient imports with /alive:receive.
╰─
```

---

### Step 8 -- Metadata Update

For capsule scope: update each exported capsule's companion `shared:` field in the **original walnut** (not staging -- staging is deleted).

Read each capsule's `companion.md`, add an entry to the `shared:` array:

```yaml
shared:
  - to: "<recipient if known, otherwise 'walnut-package'>"
    method: "walnut-package"
    date: <YYYY-MM-DD>
    version: "<current version file, e.g. shielding-review-draft-02.md>"
```

If the human mentioned who the package is for during the flow (in the personal note, or in conversation), use that name for `to:`. Otherwise default to `"walnut-package"`.

For full scope: no companion metadata update (the entire walnut is being handed off).

For snapshot scope: no metadata update (read-only briefing, nothing was "shared" in the capsule sense).

Stash the share event for the log:

```
╭─ 🐿️ +1 stash (N)
│  Shared [scope] package: [capsule names or "full walnut"] via walnut-package
│  → drop?
╰─
```

---

## Scope File Rules (Quick Reference)

| Scope | Includes | Excludes |
|-------|----------|----------|
| **full** | All `_core/` contents | `_squirrels/`, `_index.yaml`, OS artifacts |
| **capsule** | `key.md` + selected capsule dirs | Everything else |
| **snapshot** | `key.md`, `now.md`, `insights.md` | Everything else |

For all scopes:
- `active_sessions:` stripped from capsule companions in staging
- OS artifacts (`.DS_Store`, `Thumbs.db`, `desktop.ini`) excluded
- `COPYFILE_DISABLE=1` mandatory on tar to prevent AppleDouble files

---

## Edge Cases

**Empty capsule (companion only, no raw files):** Package it anyway. The companion context has value.

**Large package warning:** If total staging size exceeds 25 MB, warn:

```
╭─ 🐿️ heads up
│
│  This package is ~42 MB. That may be too large for email.
│  Consider AirDrop, a shared drive, or splitting into smaller packages.
│
│  ▸ Continue?
│  1. Yes
│  2. Cancel
╰─
```

**No capsules exist (capsule scope selected):** This shouldn't happen since the option is suppressed in Step 1, but if reached: "This walnut has no capsules. Try full or snapshot scope instead."

**Walnut argument (sharing from non-current walnut):** If the human provides a walnut name or path as an argument, locate it, read its `_core/key.md` and proceed. Don't switch the session's active walnut -- just read from the target.

**Multiple packages same day:** Check for existing files matching the name pattern. Append sequence number (`-2`, `-3`) to avoid overwriting.
