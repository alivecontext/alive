#!/usr/bin/env python3
"""Relay probe: check GitHub relay for new commits and pending packages.

Runs from the alive-relay-check SessionStart hook with a 10s timeout.
Reads relay.json, probes the relay repo via `gh api`, counts pending
.walnut files in the user's inbox, checks peer reachability, detects
peer acceptance (collaborator status + public key fetch), and writes
results to state.json atomically.

MUST exit 0 always -- network failures are expected and must not block
session start.

Usage:
    python3 relay-probe.py --config ~/.alive/relay/relay.json \
                           --state  ~/.alive/relay/state.json

Task: fn-5-dof.4, fn-6-7kn.6
"""

import argparse
import base64
import datetime
import os
import subprocess
import sys

# Import atomic JSON utilities from alive-p2p.py (same directory).
# The filename uses a hyphen, so we need importlib to load it.
import importlib.util as _ilu

_script_dir = os.path.dirname(os.path.abspath(__file__))
_p2p_path = os.path.join(_script_dir, 'alive-p2p.py')
_spec = _ilu.spec_from_file_location('alive_p2p', _p2p_path)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

atomic_json_read = _mod.atomic_json_read
atomic_json_write = _mod.atomic_json_write


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso():
    """Return current UTC time as ISO 8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec='seconds')


def _run_gh(args, timeout=5):
    """Run a `gh` CLI command. Returns (stdout, success)."""
    try:
        proc = subprocess.run(
            ['gh'] + args,
            capture_output=True, text=True, timeout=timeout)
        return proc.stdout.strip(), proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return '', False


def _run_git(args, timeout=5):
    """Run a `git` command. Returns (stdout, success)."""
    try:
        proc = subprocess.run(
            ['git'] + args,
            capture_output=True, text=True, timeout=timeout)
        return proc.stdout.strip(), proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return '', False


# ---------------------------------------------------------------------------
# Probe: check relay repo for new commits
# ---------------------------------------------------------------------------

def probe_relay_commit(repo):
    """Check the latest commit SHA on the relay repo's main branch.

    Uses `gh api` which is the fastest way to check -- single HTTPS
    request, no git operations.

    Returns the commit SHA string, or None on failure.
    """
    stdout, ok = _run_gh([
        'api', f'repos/{repo}/git/refs/heads/main',
        '--jq', '.object.sha'])
    if ok and stdout:
        return stdout
    return None


# ---------------------------------------------------------------------------
# Probe: count pending .walnut files in inbox
# ---------------------------------------------------------------------------

def count_pending_packages(clone_dir, username):
    """Count .walnut files in inbox/{username}/ of the local clone.

    The clone is a sparse checkout that only includes inbox/{username}/
    and keys/. Returns 0 if the directory doesn't exist.
    """
    inbox_dir = os.path.join(clone_dir, 'inbox', username)
    if not os.path.isdir(inbox_dir):
        return 0

    count = 0
    try:
        for entry in os.listdir(inbox_dir):
            if entry.endswith('.walnut'):
                count += 1
    except OSError:
        pass
    return count


# ---------------------------------------------------------------------------
# Probe: fetch latest from relay
# ---------------------------------------------------------------------------

def fetch_relay(clone_dir):
    """Fetch latest from origin and reset to origin/main.

    Uses --depth=1 to keep it fast. Returns True on success.
    """
    _, fetch_ok = _run_git(
        ['-C', clone_dir, 'fetch', '--depth=1', 'origin', 'main'],
        timeout=8)
    if not fetch_ok:
        return False

    _, reset_ok = _run_git(
        ['-C', clone_dir, 'reset', '--hard', 'origin/main'],
        timeout=5)
    return reset_ok


# ---------------------------------------------------------------------------
# Probe: peer reachability
# ---------------------------------------------------------------------------

def check_peer_reachability(peers):
    """Check if each peer's relay repo is reachable via `gh api`.

    Returns a dict of {github_username: {reachable, checked, relay_repo}}.
    Skips peers without a relay field.
    """
    reachability = {}
    for peer in peers:
        github = peer.get('github', '')
        relay = peer.get('relay', '')
        if not github or not relay:
            continue

        # Quick check: does the repo exist and is it accessible?
        stdout, ok = _run_gh([
            'api', f'repos/{relay}',
            '--jq', '.full_name'],
            timeout=3)

        reachability[github] = {
            'reachable': ok and bool(stdout),
            'checked': _now_iso(),
            'relay_repo': relay,
        }

    return reachability


# ---------------------------------------------------------------------------
# Probe: detect peer acceptance (inviter side)
# ---------------------------------------------------------------------------

def _is_collaborator(repo, github_username):
    """Check if a user is a collaborator on a repo.

    Uses `gh api repos/<repo>/collaborators/<user>` which returns
    204 No Content if the user is a collaborator, 404 if not.

    Returns True if the user is a confirmed collaborator.
    """
    _, ok = _run_gh([
        'api', f'repos/{repo}/collaborators/{github_username}',
        '--method', 'GET'],
        timeout=3)
    return ok


def _fetch_peer_public_key(peer_github):
    """Fetch a peer's public key from their relay repo.

    The key is stored at keys/<username>.pem in <peer>/walnut-relay.
    GitHub Contents API returns it as base64-encoded content.

    Returns the PEM-encoded key string, or None on failure.
    """
    stdout, ok = _run_gh([
        'api', f'repos/{peer_github}/walnut-relay/contents/keys/{peer_github}.pem',
        '--jq', '.content'],
        timeout=3)
    if not ok or not stdout:
        return None

    try:
        # GitHub returns base64-encoded content (may have newlines)
        decoded = base64.b64decode(stdout.replace('\n', '')).decode('utf-8')
        return decoded
    except (ValueError, UnicodeDecodeError):
        return None


def _save_peer_key(peer_github, key_pem):
    """Save a peer's public key to ~/.alive/relay/keys/peers/<github>.pem.

    Creates the directory if it doesn't exist. Returns True on success.
    """
    keys_dir = os.path.join(
        os.path.expanduser('~'), '.alive', 'relay', 'keys', 'peers')
    try:
        os.makedirs(keys_dir, exist_ok=True)
        key_path = os.path.join(keys_dir, f'{peer_github}.pem')
        with open(key_path, 'w', encoding='utf-8') as f:
            f.write(key_pem)
        return True
    except (IOError, OSError):
        return False


def check_peer_acceptance(repo, peers):
    """Check pending peers for acceptance and fetch their public keys.

    For each peer with status 'pending':
    1. Check if they're a collaborator on our relay repo (means they accepted)
    2. If yes, fetch their public key from their relay repo
    3. If both succeed, mark them as 'accepted'

    Returns a list of github usernames that were newly accepted.
    Only modifies the peer dicts in place (status field).
    """
    newly_accepted = []

    for peer in peers:
        status = peer.get('status', '')
        github = peer.get('github', '')

        # Skip peers that are already accepted or have no github
        if status != 'pending' or not github:
            continue

        # Step 1: Check collaborator status on our relay repo
        if not _is_collaborator(repo, github):
            continue

        # Step 2: Fetch their public key
        key_pem = _fetch_peer_public_key(github)
        if not key_pem:
            # They accepted the invite but their key isn't available yet.
            # This can happen if they accepted on GitHub but haven't run
            # /alive:relay accept yet (which publishes their key).
            # Still mark as accepted -- the key will be fetched later
            # when they complete their accept flow.
            peer['status'] = 'accepted'
            newly_accepted.append(github)
            continue

        # Step 3: Save the key locally
        _save_peer_key(github, key_pem)

        # Step 4: Update peer status
        peer['status'] = 'accepted'
        newly_accepted.append(github)

    return newly_accepted


# ---------------------------------------------------------------------------
# Main probe
# ---------------------------------------------------------------------------

def run_probe(config_path, state_path):
    """Run the full relay probe and write results to state.json.

    Steps:
    1. Read relay.json config
    2. Check for new commits on relay repo (gh api)
    3. If changed: fetch latest into local clone
    4. Count pending .walnut files in inbox
    5. Check pending peers for acceptance (collaborator status + key fetch)
    6. Check peer reachability
    7. Write state.json atomically
    """
    config = atomic_json_read(config_path)
    if not config:
        # No relay configured -- nothing to probe
        return

    repo = config.get('repo', '')
    username = config.get('github_username', '')
    peers = config.get('peers', [])

    if not repo or not username:
        return

    # Read existing state for comparison
    state = atomic_json_read(state_path)
    old_commit = state.get('last_commit', '')

    # Step 1: Check latest commit on relay repo
    new_commit = probe_relay_commit(repo)

    # Determine the clone directory
    relay_dir = os.path.dirname(os.path.abspath(config_path))
    clone_dir = os.path.join(relay_dir, 'clone')

    # Step 2: If commit changed (or first run), fetch
    fetched = False
    if new_commit and new_commit != old_commit and os.path.isdir(clone_dir):
        fetched = fetch_relay(clone_dir)

    # Step 3: Count pending packages (from local clone)
    pending = count_pending_packages(clone_dir, username)

    # Step 4: Check peer acceptance (pending -> accepted)
    newly_accepted = check_peer_acceptance(repo, peers)

    # If any peers were newly accepted, write updated relay.json
    if newly_accepted:
        atomic_json_write(config_path, config)

    # Step 5: Check peer reachability
    reachability = check_peer_reachability(peers)

    # Step 6: Build and write state
    new_state = {
        'last_sync': _now_iso(),
        'last_commit': new_commit if new_commit else old_commit,
        'pending_packages': pending,
        'peer_reachability': reachability,
        'newly_accepted': newly_accepted,
    }

    atomic_json_write(state_path, new_state)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Probe GitHub relay for new packages and peer reachability')
    parser.add_argument(
        '--config', required=True,
        help='Path to relay.json')
    parser.add_argument(
        '--state', required=True,
        help='Path to state.json (written atomically)')

    args = parser.parse_args()

    try:
        run_probe(args.config, args.state)
    except Exception:
        # Must exit 0 always -- this runs in a SessionStart hook
        # with a 10s timeout. Network failures are expected.
        pass

    sys.exit(0)


if __name__ == '__main__':
    main()
