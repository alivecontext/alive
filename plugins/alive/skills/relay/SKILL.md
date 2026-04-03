---
name: alive:relay
description: "Set up and manage a private GitHub relay for automatic .walnut package delivery between peers. Handles relay creation (private repo + RSA keypair), peer invitations, invitation acceptance, and status. The transport layer for P2P sharing -- extends alive:share with relay push, alive:receive with relay pull."
user-invocable: true
---

# Relay

Private GitHub-based mailbox for .walnut package delivery. Each peer has their own relay repo. Packages are RSA-encrypted before push -- the relay never sees plaintext.

Setup creates identity (RSA-4096 keypair + GitHub private repo). Adding a peer invites them as collaborator. Accepting creates the bidirectional link. After setup, `alive:share` can push directly and `alive:receive` can pull automatically.

---

## Subcommand Routing

| Invocation | Route |
|---|---|
| `/alive:relay` (no args) | Quick Status |
| `/alive:relay setup` | Setup |
| `/alive:relay add <github-username>` | Add Peer |
| `/alive:relay accept` | Accept Invitation |
| `/alive:relay status` | Detailed Status |

Before any subcommand, check for v1 migration: if `$HOME/.alive/relay.yaml` exists but `$HOME/.alive/relay/relay.json` does not, offer migration first (see V1 Migration at bottom).

---

## Quick Status (no args)

Check if `$HOME/.alive/relay/relay.json` exists. If not:

```
╭─ 🐿️ relay
│
│  No relay configured. Run /alive:relay setup to create one.
│
│  A relay is a private GitHub repo that acts as a mailbox for .walnut
│  packages. Peers you invite can push encrypted packages to your inbox.
│  You push to theirs. The relay never sees plaintext.
╰─
```

If configured, read relay.json and state.json, present summary:

```
╭─ 🐿️ relay
│
│  Repo: patrickbrosnan11-spec/walnut-relay
│  Peers: 1 (ben-flint -- accepted)
│  Pending packages: 0
│  Last sync: 2 minutes ago
│
│  /alive:relay status for detail, or /alive:relay add <user> to invite.
╰─
```

---

## Setup

One-time flow. Creates keypair, GitHub repo, sparse clone, and local config.

### Prerequisites

1. `gh` CLI installed and authenticated: `gh auth status`
2. No existing relay.json (if exists, show config and confirm reconfigure -- destructive)

If gh not authenticated, stop: explain `gh auth login`.

### Step 1: Detect Username + Confirm

```bash
gh api user --jq '.login'
```

```
╭─ 🐿️ relay setup
│
│  GitHub account: patrickbrosnan11-spec
│
│  This will:
│  1. Generate an RSA-4096 keypair for package encryption
│  2. Create a private repo patrickbrosnan11-spec/walnut-relay
│  3. Commit your public key and set up the inbox structure
│  4. Configure local relay at $HOME/.alive/relay/
│
│  ▸ proceed?
│  1. Yes, set up the relay
│  2. Use a different GitHub account
│  3. Cancel
╰─
```

**Wait for confirmation.** This creates a GitHub repo.

Option 2: ask for username, apply account routing per platforms.md.

### Step 2: Generate RSA-4096 Keypair

```bash
mkdir -p "$HOME/.alive/relay/keys/peers"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 \
  -out "$HOME/.alive/relay/keys/private.pem"
chmod 600 "$HOME/.alive/relay/keys/private.pem"
openssl pkey -in "$HOME/.alive/relay/keys/private.pem" \
  -pubout -out "$HOME/.alive/relay/keys/public.pem"
```

Verify permissions: `stat -f "%Lp" "$HOME/.alive/relay/keys/private.pem"` (macOS) or `stat -c "%a"` (Linux). Must be 600.

### Step 3: Create GitHub Repo

```bash
gh repo create walnut-relay --private \
  --description "Walnut P2P relay -- encrypted package mailbox" --clone=false
```

If repo already exists, ask whether to use existing or fail.

### Step 4: Initialize + Push

```bash
WORK_DIR=$(mktemp -d)
GITHUB_USER="<detected>"

cd "$WORK_DIR"
gh repo clone "${GITHUB_USER}/walnut-relay" .

mkdir -p "keys" "inbox/${GITHUB_USER}"
cp "$HOME/.alive/relay/keys/public.pem" "keys/${GITHUB_USER}.pem"
touch "inbox/${GITHUB_USER}/.gitkeep"

cat > README.md << 'EOF'
# Walnut Relay

Private relay for encrypted .walnut package delivery.
Do not modify manually. Managed by the alive plugin.

- `keys/` -- public keys (one per peer)
- `inbox/<username>/` -- encrypted packages waiting for pickup
EOF

git add -A && git commit -m "Initialize walnut relay" && git push origin main

cd / && rm -rf "$WORK_DIR"
```

### Step 5: Sparse Checkout Clone

```bash
CLONE_DIR="$HOME/.alive/relay/clone"
git clone --filter=blob:none --no-checkout \
  "https://github.com/${GITHUB_USER}/walnut-relay.git" "$CLONE_DIR"
cd "$CLONE_DIR"
git sparse-checkout init --cone
git sparse-checkout set "inbox/${GITHUB_USER}" "keys"
git checkout main
```

### Step 6: Write Config Files

```bash
# relay.json
cat > "$HOME/.alive/relay/relay.json" << JSONEOF
{
  "repo": "${GITHUB_USER}/walnut-relay",
  "github_username": "${GITHUB_USER}",
  "peers": []
}
JSONEOF

# state.json
cat > "$HOME/.alive/relay/state.json" << JSONEOF
{
  "last_sync": null,
  "last_commit": null,
  "pending_packages": 0,
  "peer_reachability": {}
}
JSONEOF
```

### Done

```
╭─ 🐿️ relay ready
│
│  Repo: <username>/walnut-relay (private)
│  Keys: $HOME/.alive/relay/keys/
│    Private: private.pem (chmod 600)
│    Public: committed to keys/<username>.pem
│  Clone: $HOME/.alive/relay/clone/ (sparse)
│  Config: $HOME/.alive/relay/relay.json
│
│  Next: /alive:relay add <github-username> to invite a peer.
│  After they accept, /alive:share to push packages directly.
╰─
```

The "After they accept..." line is only shown when `discovery_hints` is true (same check pattern as share skill).

**Auto-retire discovery_hints:** After setup completes, write `discovery_hints: false` to `~/.alive/preferences.yaml`:

```bash
python3 -c "
import pathlib, re
p = pathlib.Path.home() / '.alive' / 'preferences.yaml'
if p.exists():
    text = p.read_text()
    if re.search(r'^discovery_hints:', text, re.MULTILINE):
        text = re.sub(r'^discovery_hints:.*$', 'discovery_hints: false', text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + '\ndiscovery_hints: false\n'
    p.write_text(text)
"
```

---

## Add Peer

Invite a GitHub user to the relay. Creates their inbox and updates relay.json.

### Step 1: Validate

Verify the GitHub user exists:

```bash
gh api "users/<github-username>" --jq '.login' 2>/dev/null
```

If not found, report and stop. If peer already in relay.json, report current status and stop (unless status `removed` -- offer re-add).

### Step 2: Confirm

```
╭─ 🐿️ add peer
│
│  This will:
│  1. Add <github-username> as collaborator on <your-relay-repo>
│     (they get push access to deliver packages to your inbox)
│  2. Create inbox/<github-username>/ in the relay repo
│
│  They'll receive a GitHub notification to accept.
│
│  ▸ proceed?
│  1. Yes, invite <github-username>
│  2. Cancel
╰─
```

**Wait for confirmation.** External action.

### Step 3: Execute

```bash
# Add collaborator
gh api "repos/<your-repo>/collaborators/<github-username>" \
  --method PUT --field permission=push

# Create inbox in relay repo
cd "$HOME/.alive/relay/clone"
git pull origin main
mkdir -p "inbox/<github-username>"
touch "inbox/<github-username>/.gitkeep"
git add -A && git commit -m "Add inbox for <github-username>" && git push origin main
```

### Step 4: Update relay.json

Use inline python3 for safe JSON manipulation:

```bash
python3 -c "
import json, datetime
with open('$HOME/.alive/relay/relay.json') as f:
    config = json.load(f)
config['peers'].append({
    'github': '<github-username>',
    'name': None,
    'relay': None,
    'person_walnut': None,
    'added': datetime.date.today().isoformat(),
    'status': 'pending'
})
with open('$HOME/.alive/relay/relay.json', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
"
```

### Step 5: Resolve Person Walnut

Check if a person walnut exists for this peer. Scan v2 path (`People/`) then v1 (`02_Life/people/`):

```bash
ls -d People/*/ 2>/dev/null | while read d; do
  grep -l "<github-username>" "$d/_kernel/key.md" 2>/dev/null && echo "$d"
done
ls -d 02_Life/people/*/ 2>/dev/null | while read d; do
  grep -l "<github-username>" "$d/_core/key.md" 2>/dev/null && echo "$d"
done
```

If found, update `person_walnut` in relay.json. If not:

```
╭─ 🐿️ person walnut
│
│  No person walnut found for <github-username>.
│
│  ▸ create one?
│  1. Yes, create People/<slug>/
│  2. Skip -- link later
╰─
```

If yes, invoke `alive:create-walnut` with type `person`.

### Done

```
╭─ 🐿️ peer invited
│
│  <github-username> invited as collaborator on <your-relay-repo>.
│  Status: pending (waiting for them to accept)
│
│  Tell them to run /alive:relay accept on their end.
╰─
```

---

## Accept Invitation

List pending relay invitations, accept, fetch peer key, establish bidirectional link.

### Step 1: Fetch Invitations

```bash
gh api user/repository_invitations \
  --jq '.[] | select(.repository.name == "walnut-relay") | "\(.id)\t\(.repository.full_name)\t\(.inviter.login)"'
```

If none found:

```
╭─ 🐿️ accept
│
│  No pending relay invitations found.
│  Check GitHub notifications -- the invite may have expired.
╰─
```

### Step 2: Present + Confirm

```
╭─ 🐿️ relay invitations
│
│  1. benflint/walnut-relay (from benflint)
│  2. janedoe/walnut-relay (from janedoe)
│
│  ▸ accept which?
│  1. Accept all
│  2. Pick individually
│  3. Cancel
╰─
```

For each selected invitation, confirm before accepting (external action):

```bash
gh api "user/repository_invitations/<invitation-id>" --method PATCH
```

### Step 3: Fetch Peer's Public Key

```bash
PEER="<inviter>"
gh api "repos/${PEER}/walnut-relay/contents/keys/${PEER}.pem" \
  --jq '.content' | base64 -d > "$HOME/.alive/relay/keys/peers/${PEER}.pem"

# Verify
openssl pkey -pubin -in "$HOME/.alive/relay/keys/peers/${PEER}.pem" -noout
```

If verification fails, warn but continue.

### Step 4: Update relay.json

```bash
python3 -c "
import json, datetime
with open('$HOME/.alive/relay/relay.json') as f:
    config = json.load(f)
peer = '<inviter>'
existing = [p for p in config['peers'] if p['github'] == peer]
if existing:
    existing[0]['status'] = 'accepted'
    existing[0]['relay'] = f'{peer}/walnut-relay'
else:
    config['peers'].append({
        'github': peer,
        'name': None,
        'relay': f'{peer}/walnut-relay',
        'person_walnut': None,
        'added': datetime.date.today().isoformat(),
        'status': 'accepted'
    })
with open('$HOME/.alive/relay/relay.json', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
"
```

### Step 5: Bidirectional Auto-Invite

The peer invited you to their relay. For two-way sharing, they need access to yours too.

```
╭─ 🐿️ bidirectional setup
│
│  <inviter> invited you to their relay. For two-way sharing,
│  they also need access to yours.
│
│  ▸ invite <inviter> to your relay?
│  1. Yes, send invite
│  2. Skip -- I'll do it later with /alive:relay add
╰─
```

**Wait for confirmation.** External action.

If yes, execute Add Peer steps 3-4 for the inviter username (collaborator invite, inbox creation, relay.json update). Skip the Add Peer confirmation prompt since they just confirmed.

### Step 6: Resolve Person Walnut

Same as Add Peer step 5 -- scan People/ and 02_Life/people/ for the peer.

### Done

```
╭─ 🐿️ relay linked
│
│  Accepted: <inviter>/walnut-relay
│  Public key cached: $HOME/.alive/relay/keys/peers/<inviter>.pem
│  Bidirectional: <yes/skipped>
│
│  You're connected. Push with /alive:share,
│  pull with /alive:receive --relay.
╰─
```

**Auto-retire discovery_hints:** After accept completes, write `discovery_hints: false` to `~/.alive/preferences.yaml` (same pattern as setup completion above).

---

## Detailed Status

Full relay health. Read relay.json, state.json, check keys and clone.

### Gather

```bash
cat "$HOME/.alive/relay/relay.json"
cat "$HOME/.alive/relay/state.json" 2>/dev/null

# Key health
[ -f "$HOME/.alive/relay/keys/private.pem" ] && echo "private:exists" || echo "private:missing"
stat -f "%Lp" "$HOME/.alive/relay/keys/private.pem" 2>/dev/null  # macOS permissions

# Public key in repo
GITHUB_USER=$(python3 -c "import json; print(json.load(open('$HOME/.alive/relay/relay.json'))['github_username'])")
gh api "repos/${GITHUB_USER}/walnut-relay/contents/keys/${GITHUB_USER}.pem" --jq '.sha' 2>/dev/null

# Clone health
[ -d "$HOME/.alive/relay/clone/.git" ] && echo "clone:ok" || echo "clone:missing"
ls "$HOME/.alive/relay/clone/inbox/${GITHUB_USER}/"*.walnut 2>/dev/null | wc -l
```

### Present

```
╭─ 🐿️ relay status
│
│  RELAY
│  Repo: patrickbrosnan11-spec/walnut-relay
│  Username: patrickbrosnan11-spec
│  Clone: $HOME/.alive/relay/clone/ (ok)
│
│  KEYS
│  Private: private.pem (600, ok)
│  Public: committed to keys/patrickbrosnan11-spec.pem (ok)
│
│  PEERS
│   github          name        relay                         status    key
│   benflint        Ben Flint   benflint/walnut-relay         accepted  cached
│   janedoe         --          janedoe/walnut-relay          pending   --
│
│  STATE
│  Last sync: 3 minutes ago
│  Pending packages: 0
│  Peer reachability:
│    benflint: reachable (checked 3 min ago)
╰─
```

Peer key column: `cached` (key at `keys/peers/<github>.pem`), `missing` (no key), `--` (pending peer, not expected yet).

### Troubleshooting

Surface any failed health check with a fix suggestion:

```
╭─ 🐿️ relay issue
│
│  Private key permissions are 644 (should be 600).
│  Fix: chmod 600 "$HOME/.alive/relay/keys/private.pem"
│
│  ▸ fix now?
│  1. Yes
│  2. Skip
╰─
```

Issues and fixes:
- Key permissions wrong: `chmod 600`
- Clone missing: re-clone with sparse checkout (Setup step 5)
- Public key not in repo: re-commit from local key
- state.json missing: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/relay-probe.py" --config "$HOME/.alive/relay/relay.json" --state "$HOME/.alive/relay/state.json"`

---

## V1 Migration

If `$HOME/.alive/relay.yaml` exists but relay.json does not, offer migration before any subcommand:

```
╭─ 🐿️ v1 relay detected
│
│  Found v1 config at $HOME/.alive/relay.yaml
│  This preserves your keypairs, repo, and peer relationships.
│
│  ▸ migrate to v2 format?
│  1. Yes
│  2. Cancel
╰─
```

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/migrate-relay.py"
```

After migration, continue with the original subcommand.

---

## Error Handling

| Error | Message |
|---|---|
| gh not installed | Install: `brew install gh` (macOS) or https://cli.github.com, then `gh auth login` |
| gh not authenticated | Run `gh auth login`, then try again |
| Network failure | Check connection, then `gh auth status` |

### Account Routing

Apply platform routing from platforms.md. The `github_username` in relay.json determines which account to use. For setup (before relay.json exists), detect current gh auth and confirm.

---

## Confirmation Gate Rules

Every external action MUST have a confirmation prompt. The external guard hook only catches `mcp__` tools, not Bash. This skill is the gate.

**Requires confirmation:** repo creation, collaborator invite, invitation acceptance, bidirectional auto-invite, git push to relay repo.

**No confirmation needed:** reading config/state files, `gh auth status`, read-only GitHub API, local keypair generation, writing local config.

Pattern: present what will happen, numbered options, wait for choice. Never fire-and-forget on external actions.
