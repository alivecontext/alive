---
name: alive:receive
description: "Import a .walnut package into the world. Supports direct file import, inbox scan delegation, and relay pull (automatic fetch from git-based relay inbox). Detects encryption (passphrase or RSA), validates integrity (checksums + path safety), previews contents, routes by scope (full/bundle/snapshot), logs the import, and regenerates now.json."
user-invocable: true
---

# Receive

Import a .walnut package. Validate, decrypt if needed, preview, route, log, regenerate state.

Three entry points. One flow. Every package gets the same 14-step validation regardless of how it arrived.

---

## Entry Points

### 1. Direct File

```
/alive:receive path/to/file.walnut
```

The file path is the argument. Jump straight to Step 1 (Extract).

### 2. Inbox Scan (delegated from capture-context)

When `alive:capture-context` detects `.walnut` files in `03_Inputs/`, it delegates here instead of normal capture. The skill receives a list of `.walnut` paths from the inbox.

Present the list and let the user pick:

```
╭─ 🐿️ walnut packages in inbox
│
│  1. nova-station-bundle-shielding-review-2026-04-01.walnut  (2.3 MB)
│  2. glass-cathedral-full-2026-03-28.walnut                  (14.1 MB)
│
│  ▸ import which?
│  1. Process all
│  2. Pick individually (e.g. "1" or "1,2")
│  3. Skip for now
╰─
```

For each selected file, run the full 14-step flow. Between packages: "N remaining. Next, or done for now?"

**Do NOT delete .walnut files from `03_Inputs/`.** Archive enforcer blocks deletion. After successful import, offer to move the file to the target walnut's `bundles/_received/` or leave it in place. Use `mv`, never `rm`.

### 3. Relay Pull

```
/alive:receive --relay
```

Or triggered from session-start notification ("You have N walnut package(s) waiting on the relay").

**Flow:**

1. Read `$HOME/.alive/relay/relay.json` -- get username and repo
2. Read `$HOME/.alive/relay/state.json` -- get pending count
3. If no relay configured, stop: "No relay configured. Run `/alive:relay setup` first. Tip: After setup, run `/alive:receive --relay` again to pull packages." The `Tip:` portion is only shown when `discovery_hints` is true (same check pattern as share skill).
4. If pending_packages == 0, check anyway (state may be stale):

```bash
GITHUB_USER=$(python3 -c "import json; print(json.load(open('$HOME/.alive/relay/relay.json'))['github_username'])")
CLONE_DIR="$HOME/.alive/relay/clone"
cd "$CLONE_DIR" && git pull origin main --quiet
ls "$CLONE_DIR/inbox/${GITHUB_USER}/"*.walnut 2>/dev/null
```

5. If packages found, list them:

```
╭─ 🐿️ relay inbox
│
│  1. a1b2c3d4-nova-station-bundle-shielding-review.walnut
│  2. e5f6g7h8-glass-cathedral-snapshot.walnut
│
│  ▸ import which?
│  1. Process all
│  2. Pick individually
│  3. Skip for now
╰─
```

6. For each selected: copy from clone to a temp staging path, then run the full 14-step flow
7. After successful import of each package, remove from relay clone and push:

```bash
cd "$CLONE_DIR"
rm "inbox/${GITHUB_USER}/<filename>.walnut"
git add -A && git commit -m "Received: <filename>" && git push origin main
```

This is an external action (git push) -- confirm before pushing:

```
╭─ 🐿️ cleanup relay inbox
│
│  Remove <filename> from relay inbox? (git push)
│
│  ▸ confirm?
│  1. Yes, clean up
│  2. Leave it (can re-import later)
╰─
```

8. Update `$HOME/.alive/relay/state.json` -- decrement pending_packages, update last_sync

---

## The 14-Step Import Flow

Every package goes through all 14 steps. Steps 4-5 are conditional on encryption. Step 6 is conditional on signature presence. Step 13 is conditional on relay metadata.

### Step 1: Extract to Staging

```bash
STAGING=$(mktemp -d -t walnut-receive-XXXXXX)
python3 -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from alive_p2p import safe_tar_extract
safe_tar_extract('$PACKAGE_PATH', '$STAGING')
"
```

If extraction fails (corrupt archive, unsupported format), report and stop:

```
╭─ 🐿️ extraction failed
│
│  Could not extract: <filename>
│  Error: <message>
│
│  The file may be corrupt or not a valid .walnut package.
╰─
```

### Step 2: Validate Manifest

Read `$STAGING/manifest.yaml`. If missing, stop -- not a valid package.

```bash
python3 -c "
import sys, json
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from alive_p2p import parse_manifest, validate_manifest

with open('$STAGING/manifest.yaml') as f:
    manifest = parse_manifest(f.read())

ok, errors = validate_manifest(manifest)
print(json.dumps({'manifest': manifest, 'valid': ok, 'errors': errors}))
"
```

**Format version handling:**

- `2.x` -- proceed normally
- `1.x` (specifically `1.1.0`) -- accept with v1 backward compatibility mapping (see V1 Compatibility section below). Log a note that this is a v1 package.
- Anything else -- reject:

```
╭─ 🐿️ unsupported format
│
│  Package format_version: <version>
│  Expected: 2.x (or 1.x for backward compat)
│
│  This package was created by a version of alive that isn't compatible.
╰─
```

If validation fails (missing required fields, invalid scope):

```
╭─ 🐿️ invalid manifest
│
│  <error 1>
│  <error 2>
│
│  The manifest is malformed. Package cannot be imported.
╰─
```

### Step 3: Verify Checksums

```bash
python3 -c "
import sys, json
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from alive_p2p import parse_manifest, verify_checksums

with open('$STAGING/manifest.yaml') as f:
    manifest = parse_manifest(f.read())

ok, failures = verify_checksums(manifest, '$STAGING')
print(json.dumps({'ok': ok, 'failures': failures}))
"
```

If checksums pass, continue. If any fail:

```
╭─ 🐿️ checksum verification failed
│
│  2 file(s) failed integrity check:
│  - bundles/shielding-review/draft-02.md (mismatch)
│  - bundles/shielding-review/raw/proposal.pdf (missing)
│
│  This package may have been tampered with or corrupted in transit.
│
│  ▸ what to do?
│  1. Abort import (recommended)
│  2. Continue anyway (files may be corrupt)
╰─
```

**Skip this step for encrypted packages** -- checksums will be verified after decryption in step 5b.

### Step 4: Detect Encryption

Check the staging directory for encryption artifacts:

```bash
[ -f "$STAGING/payload.key" ] && echo "rsa" || ([ -f "$STAGING/payload.enc" ] && echo "passphrase" || echo "none")
```

- `payload.key` exists -> RSA mode (relay transport)
- `payload.enc` exists (no `payload.key`) -> passphrase mode (manual share)
- Neither -> unencrypted, skip to step 6

### Step 5: Decrypt

**Passphrase mode:**

```
╭─ 🐿️ encrypted package (passphrase)
│
│  This package is passphrase-encrypted.
│  The sender should have given you the passphrase separately.
│
│  ▸ enter passphrase:
╰─
```

Get passphrase via AskUserQuestion. Then:

```bash
WALNUT_PASSPHRASE="<user-provided>" python3 -c "
import sys, os, subprocess, tempfile, shutil
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from alive_p2p import detect_openssl, safe_tar_extract

ssl = detect_openssl()
staging = '$STAGING'
payload_enc = os.path.join(staging, 'payload.enc')
decrypted_tar = os.path.join(staging, 'payload.tar.gz')

proc = subprocess.run(
    [ssl['binary'], 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '600000',
     '-in', payload_enc, '-out', decrypted_tar,
     '-pass', 'env:WALNUT_PASSPHRASE'],
    capture_output=True, text=True, timeout=120)

if proc.returncode != 0:
    print('DECRYPT_FAILED')
    sys.exit(1)

# Extract decrypted payload over the staging dir
safe_tar_extract(decrypted_tar, staging)

# Clean up encryption artifacts
os.remove(payload_enc)
os.remove(decrypted_tar)
if os.path.exists(os.path.join(staging, 'payload.key')):
    os.remove(os.path.join(staging, 'payload.key'))

print('DECRYPT_OK')
"
```

If decryption fails (wrong passphrase):

```
╭─ 🐿️ decryption failed
│
│  Wrong passphrase or corrupt payload.
│
│  ▸ try again?
│  1. Yes, re-enter passphrase
│  2. Abort import
╰─
```

Allow up to 3 retries before aborting.

**RSA mode:**

```bash
python3 -c "
import sys, os, subprocess, tempfile
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from alive_p2p import detect_openssl, safe_tar_extract

ssl = detect_openssl()
staging = '$STAGING'
payload_enc = os.path.join(staging, 'payload.enc')
payload_key = os.path.join(staging, 'payload.key')
private_key = os.path.expanduser('~/.alive/relay/keys/private.pem')
aes_key = os.path.join(staging, 'aes.key')
decrypted_tar = os.path.join(staging, 'payload.tar.gz')

if not os.path.isfile(private_key):
    print('NO_PRIVATE_KEY')
    sys.exit(1)

# Unwrap AES key with RSA private key
proc = subprocess.run(
    [ssl['binary'], 'pkeyutl', '-decrypt',
     '-inkey', private_key,
     '-in', payload_key, '-out', aes_key,
     '-pkeyopt', 'rsa_padding_mode:oaep',
     '-pkeyopt', 'rsa_oaep_md:sha256'],
    capture_output=True, text=True, timeout=30)

if proc.returncode != 0:
    print('RSA_DECRYPT_FAILED')
    sys.exit(1)

# Read AES key as hex
with open(aes_key, 'rb') as f:
    aes_key_hex = f.read().hex()

# Read IV from payload.iv if present, else use zero IV
iv_path = os.path.join(staging, 'payload.iv')
if os.path.isfile(iv_path):
    with open(iv_path, 'r') as f:
        iv_hex = f.read().strip()
else:
    iv_hex = '0' * 32

# Decrypt payload with AES key
proc = subprocess.run(
    [ssl['binary'], 'enc', '-d', '-aes-256-cbc',
     '-K', aes_key_hex, '-iv', iv_hex,
     '-in', payload_enc, '-out', decrypted_tar],
    capture_output=True, text=True, timeout=120)

if proc.returncode != 0:
    print('AES_DECRYPT_FAILED')
    sys.exit(1)

# Extract decrypted payload over staging
safe_tar_extract(decrypted_tar, staging)

# Clean up
for f in [payload_enc, payload_key, aes_key, decrypted_tar, iv_path]:
    if os.path.isfile(f):
        os.remove(f)

print('DECRYPT_OK')
"
```

If no private key found:

```
╭─ 🐿️ RSA decryption failed
│
│  This package was RSA-encrypted for relay delivery, but no private
│  key found at $HOME/.alive/relay/keys/private.pem
│
│  Run /alive:relay setup first, or ask the sender for a
│  passphrase-encrypted version.
╰─
```

**Step 5b: Verify checksums after decryption.** Now that files are decrypted, run the same checksum verification as step 3.

### Step 6: Verify Manifest Signature (if present)

Check `manifest.signature` in the parsed manifest. If no signature block, skip.

If signature present:

```bash
python3 -c "
import sys, os, subprocess, json
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from alive_p2p import detect_openssl

ssl = detect_openssl()
staging = '$STAGING'
manifest_path = os.path.join(staging, 'manifest.yaml')

# Read manifest, strip signature block for verification
with open(manifest_path) as f:
    content = f.read()

# Remove signature: block (last section)
import re
stripped = re.sub(r'\nsignature:\n(?:\s+\w.*\n)*', '\n', content)

# Write stripped content to temp file
stripped_path = manifest_path + '.stripped'
with open(stripped_path, 'w') as f:
    f.write(stripped)

# Get signer from manifest
manifest = json.loads('$MANIFEST_JSON')
signer = manifest.get('signature', {}).get('signer', '')
sig_value = manifest.get('signature', {}).get('value', '')

# Look for signer's public key
key_paths = [
    os.path.expanduser(f'~/.alive/relay/keys/peers/{signer}.pem'),
    os.path.join(staging, 'keys', f'{signer}.pem'),
]
pub_key = None
for kp in key_paths:
    if os.path.isfile(kp):
        pub_key = kp
        break

if not pub_key:
    print('NO_SIGNER_KEY')
    sys.exit(0)  # Not fatal, just warn

# Decode signature
import base64
sig_bytes = base64.b64decode(sig_value)
sig_path = manifest_path + '.sig'
with open(sig_path, 'wb') as f:
    f.write(sig_bytes)

# Verify
proc = subprocess.run(
    [ssl['binary'], 'dgst', '-sha256', '-verify', pub_key,
     '-signature', sig_path, stripped_path],
    capture_output=True, text=True, timeout=30)

os.remove(stripped_path)
os.remove(sig_path)

if proc.returncode == 0:
    print('SIG_VALID')
else:
    print('SIG_INVALID')
"
```

If signature valid: note in preview. If invalid:

```
╭─ 🐿️ signature verification failed
│
│  The manifest claims to be from <signer>, but the signature
│  doesn't match their public key.
│
│  This could mean the package was modified after signing.
│
│  ▸ what to do?
│  1. Abort import (recommended)
│  2. Continue anyway (at your own risk)
╰─
```

If signer's key not found: warn but continue (not fatal):

```
╭─ 🐿️ signature not verified
│
│  Package is signed by <signer>, but their public key isn't cached.
│  Can't verify authenticity. Continuing with import.
╰─
```

### Step 7: Path Safety Checks

Verify every file path in the manifest is safe. This is defense-in-depth on top of `safe_tar_extract`'s built-in checks.

```bash
python3 -c "
import sys, os, json
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from alive_p2p import parse_manifest

with open('$STAGING/manifest.yaml') as f:
    manifest = parse_manifest(f.read())

issues = []
staging = os.path.abspath('$STAGING')

for entry in manifest.get('files', []):
    p = entry['path']
    # No parent directory traversal
    if '..' in p:
        issues.append(f'Path traversal: {p}')
    # No absolute paths
    if os.path.isabs(p):
        issues.append(f'Absolute path: {p}')
    # Resolved path must stay within staging
    resolved = os.path.normpath(os.path.join(staging, p))
    if not resolved.startswith(staging + os.sep) and resolved != staging:
        issues.append(f'Escapes staging: {p}')
    # Check for symlinks in extracted files
    full = os.path.join(staging, p.replace('/', os.sep))
    if os.path.islink(full):
        target = os.path.realpath(full)
        if not target.startswith(staging + os.sep):
            issues.append(f'Symlink escapes staging: {p} -> {target}')

print(json.dumps({'ok': len(issues) == 0, 'issues': issues}))
"
```

If any issues found, abort:

```
╭─ 🐿️ path safety check failed
│
│  Dangerous paths detected in package:
│  - <issue 1>
│  - <issue 2>
│
│  This package contains paths that could write outside the target
│  directory. Import aborted.
╰─
```

No override option for path safety failures. This is non-negotiable.

### Step 8: Present Preview

Build the preview from the validated manifest:

```
╭─ 🐿️ package preview
│
│  Source:      nova-station (by patrickSupernormal)
│  Scope:       bundle
│  Format:      2.0.0
│  Created:     2026-04-01T10:00:00Z
│  Encrypted:   passphrase (decrypted)
│  Signed:      patrickSupernormal (verified)
│  Description: Radiation shielding vendor evaluation
│  Note:        "Here's the shielding review -- let me know"
│
│  Bundles (2):
│    shielding-review/  (5 files, 1.2 MB)
│    launch-checklist/  (3 files, 340 KB)
│
│  Files: 12 total, 1.5 MB
│
│  ▸ import?
│  1. Yes, import
│  2. Preview file list first
│  3. Cancel
╰─
```

If user picks "Preview file list", show the full manifest file inventory with paths and sizes. Then re-ask import question.

For **snapshot scope**, adjust the prompt -- no import, just display:

```
╭─ 🐿️ snapshot preview
│
│  Source:      nova-station (by patrickSupernormal)
│  Scope:       snapshot (read-only)
│
│  This is a snapshot -- identity and insights only.
│  No files will be written.
│
│  ▸ what to do?
│  1. Display key.md contents
│  2. Display insights.md contents
│  3. Done
╰─
```

### Step 9: Route by Scope

**Full scope -> create new walnut:**

The user must choose an ALIVE domain folder. Root guardian blocks world root writes.

```
╭─ 🐿️ full import -- choose destination
│
│  This is a full walnut export. It needs its own folder.
│
│  ▸ which ALIVE domain?
│  1. 02_Life/
│  2. 04_Ventures/
│  3. 05_Experiments/
│  4. Custom path
╰─
```

Resolve the target path: `<domain>/<walnut-name>/` where walnut-name comes from `manifest.source.walnut`.

If the directory already exists:

```
╭─ 🐿️ walnut already exists
│
│  <domain>/<walnut-name>/ already exists.
│
│  ▸ what to do?
│  1. Import as <walnut-name>-imported/
│  2. Merge into existing (careful -- may overwrite files)
│  3. Cancel
╰─
```

**Bundle scope -> merge into existing walnut:**

```
╭─ 🐿️ bundle import -- choose target walnut
│
│  Bundles: <bundle-list>
│
│  ▸ which walnut receives these bundles?
│  1. <active walnut if one is loaded>
│  2. Browse walnuts
│  3. Cancel
╰─
```

If "Browse walnuts", scan `04_Ventures/*/_kernel/key.md`, `05_Experiments/*/_kernel/key.md`, `02_Life/*/_kernel/key.md` frontmatter (type, goal) and present as numbered list. Fall back to `_core/key.md` for v1 walnuts.

After target selection, check for bundle name conflicts (see Conflict Handling section below).

**Snapshot scope -> read-only display:**

No file writes. Display key.md and/or insights.md from staging. Handled in step 8 already. Skip to step 14 (cleanup).

### Step 10: Write Imported Files

**Full scope:**

```bash
TARGET="<resolved-target-path>"
mkdir -p "$TARGET"

# Copy _kernel/ files
mkdir -p "$TARGET/_kernel"
for f in key.md log.md insights.md; do
  [ -f "$STAGING/_kernel/$f" ] && cp "$STAGING/_kernel/$f" "$TARGET/_kernel/$f"
done

# Copy bundles/
[ -d "$STAGING/bundles" ] && cp -R "$STAGING/bundles" "$TARGET/bundles"

# Copy live context (everything else at staging root except _kernel/, bundles/, manifest.yaml)
for item in "$STAGING"/*; do
  base=$(basename "$item")
  case "$base" in
    _kernel|bundles|manifest.yaml) continue ;;
    *) cp -R "$item" "$TARGET/$base" ;;
  esac
done

# Create _kernel/_generated/ directory for now.json
mkdir -p "$TARGET/_kernel/_generated"
```

**Bundle scope:**

```bash
TARGET_WALNUT="<resolved-walnut-path>"

# Copy each bundle
for bundle_name in <bundle-list>; do
  [ -d "$STAGING/bundles/$bundle_name" ] && \
    cp -R "$STAGING/bundles/$bundle_name" "$TARGET_WALNUT/bundles/$bundle_name"
done

# If key.md included and target has no key.md, copy it
[ -f "$STAGING/_kernel/key.md" ] && [ ! -f "$TARGET_WALNUT/_kernel/key.md" ] && \
  cp "$STAGING/_kernel/key.md" "$TARGET_WALNUT/_kernel/key.md"
```

### Step 11: Log Import Event

**Use Edit to prepend to `_kernel/log.md`.** The log guardian blocks Write to existing log files. Edit (prepend) is the only safe way.

If this is a full-scope import to a new walnut, the log.md was just copied from the package. Prepend the import event to the top of that log.

If this is a bundle-scope import, prepend to the existing walnut's log.

```
## <ISO-timestamp>

Received .walnut package: <filename>
- Scope: <scope>
- Source: <source.walnut> (by <source.session_id>)
- Format: <format_version>
- Bundles imported: <bundle-list or "full walnut">
- Encrypted: <yes (mode) / no>
- Signature: <verified / not verified / unsigned>
- Files: <count> (<size>)

signed: squirrel:<session_id>
```

**For new walnuts (full scope):** If `_kernel/log.md` does not exist yet (e.g., the package didn't include one), use Write to create it. Write to non-existent log.md is allowed (task fn-5-dof.1 fix).

**For existing walnuts (bundle scope):** Always use Edit to prepend. Read the first line of the existing log.md to get the old_string for the Edit, then prepend the new entry above it.

### Step 12: Regenerate now.json

After import, the walnut needs a valid `_kernel/_generated/now.json`. This is a minimal regeneration -- not the full save protocol.

1. Read `_kernel/key.md` frontmatter for phase, rhythm, type, goal
2. Read `_kernel/log.md` first 3-5 entries for context synthesis
3. Generate now.json:

```json
{
  "phase": "<from key.md or 'received'>",
  "health": "active",
  "updated": "<current ISO timestamp>",
  "bundle": null,
  "next": "<from key.md goal or 'Review imported content'>",
  "squirrel": "<current session_id>",
  "context": "<1-2 sentence synthesis from log entries>",
  "projections": []
}
```

Write to `_kernel/_generated/now.json`:

```bash
mkdir -p "$TARGET/_kernel/_generated"
```

Then use Write to create the file (it's a generated projection, not a source file -- Write is appropriate here).

For **bundle scope into existing walnut:** Read the existing now.json first. Update the context paragraph to mention the imported bundles. Don't flatten existing context -- merge the new information in.

### Step 13: Relay Bootstrap (conditional)

If the manifest has a `relay:` section with `repo` and `sender`:

```
╭─ 🐿️ relay bootstrap
│
│  This package came from <sender>'s relay: <repo>
│
│  ▸ join their relay for automatic package delivery?
│  1. Yes -- run /alive:relay accept
│  2. Not now
╰─
```

If yes, invoke `alive:relay accept` flow. If the user doesn't have a relay set up yet, suggest `alive:relay setup` first.

This is how relay connections spread organically -- receiving a package from someone's relay is the natural moment to establish the return channel.

### Step 14: Cleanup

```bash
rm -rf "$STAGING"
```

Always runs, even on errors. Wrap the entire flow in a try/finally equivalent -- if any step fails, clean up staging before reporting the error.

Present completion:

```
╭─ 🐿️ import complete
│
│  Package: <filename>
│  Imported to: <target-path>
│  Scope: <scope>
│  Bundles: <list>
│  Log entry: written
│  now.json: regenerated
│
│  Open with /alive:load <walnut-name> to start working.
╰─
```

---

## Conflict Handling (Bundle Scope)

When importing a bundle into a walnut that already has a bundle with the same name:

1. Read both context.manifest.yaml files (local and incoming)
2. Compare versions if available, count files in each
3. Present:

```
╭─ 🐿️ bundle conflict
│
│  Bundle "shielding-review" already exists in <walnut>.
│
│  Local:    5 files, last modified 2026-03-25
│  Incoming: 7 files, from 2026-04-01
│
│  ▸ how to handle?
│  1. Replace -- incoming overwrites local
│  2. Merge -- import new files only, keep existing
│  3. Import as "shielding-review-imported"
│  4. Skip this bundle
╰─
```

**Replace:** Remove local bundle directory, copy incoming.

**Merge:** Walk incoming files. For each file:
- If not in local: copy
- If in local and identical (same SHA-256): skip
- If in local and different: present individual conflict:

```
╭─ 🐿️ file conflict
│
│  bundles/shielding-review/draft-02.md
│
│  Local:    2,847 bytes (modified 2026-03-25)
│  Incoming: 3,201 bytes (from 2026-04-01)
│
│  ▸ keep which?
│  1. Incoming (overwrite local)
│  2. Local (skip incoming)
│  3. Keep both (rename incoming to draft-02-imported.md)
╰─
```

**Import as renamed:** Copy entire bundle to `bundles/<name>-imported/`.

**Skip:** Don't import this bundle. Continue with next.

---

## V1 Backward Compatibility (format 1.1.0)

When `format_version` starts with `1.`, apply these path mappings during import:

| v1 path | v2 path | Action |
|---------|---------|--------|
| `_core/key.md` | `_kernel/key.md` | Copy with path change |
| `_core/log.md` | `_kernel/log.md` | Copy with path change |
| `_core/insights.md` | `_kernel/insights.md` | Copy with path change |
| `_core/now.md` | (discard) | now.json is generated, not imported |
| `_core/tasks.md` | (discard) | v2 tasks are per-bundle |
| `_core/_capsules/<name>/` | `bundles/<name>/` | Copy with path change |
| `_core/_capsules/<name>/companion.md` | `bundles/<name>/context.manifest.yaml` | Convert (see below) |

**companion.md -> context.manifest.yaml conversion:**

1. Read companion.md
2. Extract YAML frontmatter using `parse_yaml_frontmatter()`
3. Map frontmatter fields to context.manifest.yaml structure:

```yaml
# From companion.md frontmatter:
#   type: capsule
#   description: "Shielding vendor evaluation"
#   status: active
#   tags: [shielding, vendors]
#
# Becomes context.manifest.yaml:
name: shielding-review
description: "Shielding vendor evaluation"
status: active
tags: [shielding, vendors]
sources: []
decisions: []
```

4. Write as pure YAML (not markdown with frontmatter)
5. If companion.md has a body (below frontmatter), preserve it as `bundles/<name>/README.md`

**v1 scope mapping:**
- `scope: capsule` -> treat as `scope: bundle`

**During step 2 (validate manifest):** Relax validation for v1 packages. Accept `_core/` paths in the file list. The mapping happens during step 10 (write).

```
╭─ 🐿️ v1 package detected
│
│  Format: 1.1.0 (legacy)
│  Paths will be mapped to v2 structure:
│    _core/ -> _kernel/
│    _core/_capsules/ -> bundles/
│    now.md, tasks.md -> discarded (regenerated)
│
│  Continuing with import.
╰─
```

---

## Error Recovery

Every step that can fail has a cleanup path. The staging directory is the containment boundary -- nothing touches the target walnut until step 10.

| Failure point | Recovery |
|---|---|
| Extraction (step 1) | Clean staging, report |
| Manifest (step 2) | Clean staging, report |
| Checksums (step 3) | Clean staging, report (or user overrides) |
| Decryption (step 5) | Retry passphrase up to 3x, then clean staging |
| Signature (step 6) | Warn but continue (user choice) |
| Path safety (step 7) | Clean staging, abort (non-negotiable) |
| Write (step 10) | Partial writes may exist -- report which files were written |
| Log (step 11) | If Edit fails, report -- manual intervention needed |
| now.json (step 12) | Non-fatal -- walnut works without it, just run /alive:save later |

If any fatal error occurs, always clean up staging:

```bash
[ -d "$STAGING" ] && rm -rf "$STAGING"
```

---

## Files Read

| File | Why |
|---|---|
| `$HOME/.alive/relay/relay.json` | Relay config (relay pull entry point) |
| `$HOME/.alive/relay/state.json` | Pending package count |
| `$STAGING/manifest.yaml` | Package metadata, file inventory, checksums |
| Target walnut `_kernel/key.md` | Phase, rhythm for now.json regen |
| Target walnut `_kernel/log.md` | Recent entries for now.json context synthesis |
| Target walnut `_kernel/_generated/now.json` | Existing state (bundle scope merge) |
| Target walnut `bundles/*/context.manifest.yaml` | Conflict detection |

## Files Written

| File | Method | Why |
|---|---|---|
| Target `_kernel/key.md` | Write (new walnut) or skip (exists) | Walnut identity |
| Target `_kernel/log.md` | Write (new) or Edit prepend (existing) | Import event |
| Target `_kernel/insights.md` | Write (new walnut) or skip | Domain knowledge |
| Target `_kernel/_generated/now.json` | Write | Generated projection |
| Target `bundles/*/` | Write (cp) | Imported bundles |
| `$HOME/.alive/relay/state.json` | Write (JSON update) | Relay state after pull |
