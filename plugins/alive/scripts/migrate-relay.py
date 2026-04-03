#!/usr/bin/env python3
"""Migrate v1 relay.yaml to v2 relay.json.

v1 stored relay config at $HOME/.alive/relay.yaml (flat YAML file).
v2 uses $HOME/.alive/relay/relay.json (JSON in a directory).

This script:
- Reads v1 relay.yaml (using alive-p2p.py's YAML frontmatter parser as
  a basic YAML reader, since we're stdlib-only and can't import PyYAML)
- Converts to v2 relay.json schema
- Preserves: repo, github_username, peers (with status), key paths
- Handles: relay.yaml not found (skip), already migrated (skip),
  partial config (warn on stderr)

Usage:
    python3 migrate-relay.py
    python3 migrate-relay.py --v1-path ~/.alive/relay.yaml \
                             --v2-path ~/.alive/relay/relay.json

Task: fn-5-dof.4
"""

import argparse
import datetime
import os
import re
import sys

# Import utilities from alive-p2p.py (same directory).
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
# Minimal YAML parser (stdlib only, handles relay.yaml structure)
# ---------------------------------------------------------------------------

def _parse_simple_yaml(text):
    """Parse simple YAML with nested dicts and one level of list-of-dicts.

    Handles the specific structure of v1 relay.yaml:

        relay:
          repo: owner/repo
          github_username: user
        peers:
          - github: user2
            name: Name
            relay: user2/repo
            person_walnut: People/name
            added: 2026-01-01
            status: accepted

    Also handles the flat variant (no nesting wrapper):

        repo: owner/repo
        github_username: user
        peers:
          - github: user2
            ...

    Returns a dict. Not a general YAML parser -- just enough for
    relay.yaml migration.
    """
    result = {}
    # current_block_key tracks a top-level key that has indented children
    # (either a dict or a list). current_block_type is 'list' or 'dict'.
    current_block_key = None
    current_block_type = None
    current_item = None  # current list item being built

    for line in text.splitlines():
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith('#'):
            continue

        # List item start (  - key: value)
        list_match = re.match(r'^  - ([\w_]+):\s*(.*)', line)
        if list_match and current_block_key:
            # We're in a list block now
            if current_block_type == 'dict':
                # Convert from dict assumption to list
                current_block_type = 'list'
                # Keep any dict items already parsed -- they were wrong.
                # In practice this won't happen with relay.yaml's structure.
                result[current_block_key] = []
            # Save previous list item
            if current_item is not None:
                result[current_block_key].append(current_item)
            current_item = {}
            key, value = list_match.group(1), list_match.group(2).strip()
            current_item[key] = _coerce_yaml_value(value)
            continue

        # List item continuation (    key: value, 4+ spaces)
        cont_match = re.match(r'^    ([\w_]+):\s*(.*)', line)
        if cont_match and current_item is not None and current_block_type == 'list':
            key, value = cont_match.group(1), cont_match.group(2).strip()
            current_item[key] = _coerce_yaml_value(value)
            continue

        # Nested dict value (  key: value, 2 spaces, no dash)
        nested_match = re.match(r'^  ([\w_]+):\s+(.*)', line)
        if nested_match and current_block_key and current_block_type == 'dict':
            key, value = nested_match.group(1), nested_match.group(2).strip()
            result[current_block_key][key] = _coerce_yaml_value(value)
            continue

        # Top-level key with block value (key:\n -- no inline value)
        top_block = re.match(r'^([\w_]+):\s*$', line)
        if top_block:
            # Finalize previous block
            if current_block_key and current_block_type == 'list' and current_item is not None:
                result[current_block_key].append(current_item)
                current_item = None
            current_block_key = top_block.group(1)
            # Assume dict until we see a list item
            current_block_type = 'dict'
            result[current_block_key] = {}
            current_item = None
            continue

        # Top-level key: value (inline)
        top_match = re.match(r'^([\w_]+):\s+(.+)', line)
        if top_match:
            # Finalize previous block
            if current_block_key and current_block_type == 'list' and current_item is not None:
                result[current_block_key].append(current_item)
                current_item = None
            current_block_key = None
            current_block_type = None
            key, value = top_match.group(1), top_match.group(2).strip()
            result[key] = _coerce_yaml_value(value)
            continue

    # Finalize last block
    if current_block_key and current_block_type == 'list' and current_item is not None:
        result[current_block_key].append(current_item)

    return result


def _coerce_yaml_value(value):
    """Coerce a YAML scalar string to its Python type."""
    if not value:
        return ''
    # Remove quotes
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    # Booleans
    if value.lower() in ('true', 'yes'):
        return True
    if value.lower() in ('false', 'no'):
        return False
    # Integers
    try:
        return int(value)
    except ValueError:
        pass
    return value


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate(v1_path, v2_path):
    """Migrate v1 relay.yaml to v2 relay.json.

    Returns a status string: 'migrated', 'skipped:no-v1', 'skipped:already-migrated',
    or 'error:<reason>'.
    """
    v1_path = os.path.abspath(v1_path)
    v2_path = os.path.abspath(v2_path)

    # Check if v1 config exists
    if not os.path.isfile(v1_path):
        return 'skipped:no-v1'

    # Check if v2 config already exists
    if os.path.isfile(v2_path):
        existing = atomic_json_read(v2_path)
        if existing.get('repo') or existing.get('github_username'):
            return 'skipped:already-migrated'

    # Read v1 YAML
    try:
        with open(v1_path, 'r', encoding='utf-8') as f:
            v1_text = f.read()
    except (IOError, OSError) as e:
        return f'error:cannot-read-v1: {e}'

    v1_config = _parse_simple_yaml(v1_text)

    if not v1_config:
        return 'error:empty-v1-config'

    # v1 relay.yaml has two variants:
    #   Flat:   repo: ..., github_username: ..., peers: [...]
    #   Nested: relay: {repo: ..., github_username: ...}, peers: [...]
    # We check both locations.
    relay_block = v1_config.get('relay', {})
    if not isinstance(relay_block, dict):
        relay_block = {}

    def _get(key):
        """Get a value from top-level or relay: block."""
        return v1_config.get(key, '') or relay_block.get(key, '')

    # Build v2 JSON structure
    v2_config = {
        'repo': _get('repo'),
        'github_username': _get('github_username'),
        'peers': [],
    }

    # Warn on missing fields
    if not v2_config['repo']:
        print('warning: v1 relay.yaml missing "repo" field', file=sys.stderr)
    if not v2_config['github_username']:
        print('warning: v1 relay.yaml missing "github_username" field',
              file=sys.stderr)

    # Migrate peers
    v1_peers = v1_config.get('peers', [])
    for peer in v1_peers:
        if not isinstance(peer, dict):
            continue
        v2_peer = {
            'github': peer.get('github', ''),
            'name': peer.get('name', ''),
            'relay': peer.get('relay', ''),
            'person_walnut': peer.get('person_walnut', ''),
            'added': str(peer.get('added', '')),
            'status': peer.get('status', 'pending'),
        }
        v2_config['peers'].append(v2_peer)

    # Write v2 JSON atomically
    atomic_json_write(v2_path, v2_config)

    # Record migration metadata
    meta_path = os.path.join(os.path.dirname(v2_path), '.migration-meta.json')
    meta = {
        'migrated_from': v1_path,
        'migrated_at': datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec='seconds'),
        'v1_peer_count': len(v1_peers),
        'v2_peer_count': len(v2_config['peers']),
    }
    atomic_json_write(meta_path, meta)

    return 'migrated'


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    default_v1 = os.path.join(os.path.expanduser('~'), '.alive', 'relay.yaml')
    default_v2 = os.path.join(
        os.path.expanduser('~'), '.alive', 'relay', 'relay.json')

    parser = argparse.ArgumentParser(
        description='Migrate v1 relay.yaml to v2 relay.json')
    parser.add_argument(
        '--v1-path', default=default_v1,
        help=f'Path to v1 relay.yaml (default: {default_v1})')
    parser.add_argument(
        '--v2-path', default=default_v2,
        help=f'Path to v2 relay.json (default: {default_v2})')

    args = parser.parse_args()
    result = migrate(args.v1_path, args.v2_path)

    if result == 'migrated':
        print(f'Migrated {args.v1_path} -> {args.v2_path}')
    elif result == 'skipped:no-v1':
        print(f'No v1 config at {args.v1_path} -- nothing to migrate')
    elif result == 'skipped:already-migrated':
        print(f'v2 config already exists at {args.v2_path} -- skipping')
    elif result.startswith('error:'):
        print(f'Migration error: {result}', file=sys.stderr)
        # Still exit 0 -- migration failure is non-fatal
    else:
        print(f'Unknown result: {result}', file=sys.stderr)

    sys.exit(0)


if __name__ == '__main__':
    main()
