#!/usr/bin/env python3
"""Cross-platform P2P utilities for the Alive sharing layer.

Standalone stdlib-only module providing hashing, tar operations, atomic JSON
state files, OpenSSL detection, base64, YAML frontmatter parsing, and
package creation/extraction/encryption for .walnut archives.

Designed for macOS (BSD tar, LibreSSL) and Linux (GNU tar, OpenSSL).
No pip dependencies -- python3 stdlib + openssl CLI only.

Usage as library:
    from alive_p2p import sha256_file, safe_tar_create, detect_openssl, ...
    from alive_p2p import create_package, extract_package, encrypt_package, ...

Usage as CLI (smoke tests):
    python3 alive-p2p.py hash <file>
    python3 alive-p2p.py openssl
    python3 alive-p2p.py tar-create <source_dir> <output.tar.gz>
    python3 alive-p2p.py tar-extract <archive.tar.gz> <output_dir>
    python3 alive-p2p.py tar-list <archive.tar.gz>
    python3 alive-p2p.py b64 <file>
    python3 alive-p2p.py yaml <file>
    python3 alive-p2p.py create --scope <full|bundle|snapshot> --walnut <path> [--bundle <name>...] [--output <path>]
    python3 alive-p2p.py extract --input <file.walnut> --output <dir>

Tasks: fn-5-dof.2, fn-5-dof.3
"""

import base64
import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def sha256_file(path):
    """Return hex SHA-256 digest of a file. Cross-platform, no subprocess."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Tar operations
# ---------------------------------------------------------------------------

# Files and patterns to exclude from archives
_TAR_EXCLUDES = {'.DS_Store', 'Thumbs.db', 'Icon\r', '__MACOSX'}


def _is_excluded(name):
    """Check whether a tar entry name should be excluded."""
    base = os.path.basename(name)
    if base in _TAR_EXCLUDES:
        return True
    # macOS resource fork files
    if base.startswith('._'):
        return True
    return False


def _resolve_path(base, name):
    """Resolve *name* relative to *base* and check it stays inside *base*.

    Returns the resolved absolute path, or None if the entry escapes.
    """
    # Reject absolute paths outright
    if os.path.isabs(name):
        return None
    target = os.path.normpath(os.path.join(base, name))
    # Must start with base (use trailing sep to avoid prefix tricks)
    if not (target == base or target.startswith(base + os.sep)):
        return None
    return target


def safe_tar_create(source_dir, output_path, strip_prefix=None):
    """Create a tar.gz archive from *source_dir*.

    - Sets COPYFILE_DISABLE=1 to suppress macOS resource forks.
    - Excludes .DS_Store, Thumbs.db, ._* files.
    - Rejects symlinks that resolve outside *source_dir*.
    - Optional *strip_prefix* removes a leading path component from entries.
    """
    source_dir = os.path.abspath(source_dir)
    if not os.path.isdir(source_dir):
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    # Suppress macOS resource forks (affects C-level tar inside python too)
    os.environ['COPYFILE_DISABLE'] = '1'

    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with tarfile.open(output_path, 'w:gz') as tar:
        for root, dirs, files in os.walk(source_dir):
            # Skip excluded directories in-place
            dirs[:] = [d for d in dirs
                       if d not in _TAR_EXCLUDES and not d.startswith('._')]

            for name in sorted(files):
                if _is_excluded(name):
                    continue

                full_path = os.path.join(root, name)

                # Reject symlinks that escape source_dir
                if os.path.islink(full_path):
                    real = os.path.realpath(full_path)
                    if not (real == source_dir
                            or real.startswith(source_dir + os.sep)):
                        raise ValueError(
                            f"Symlink escapes source: {full_path} -> {real}")

                arcname = os.path.relpath(full_path, source_dir)
                if strip_prefix:
                    if arcname.startswith(strip_prefix):
                        arcname = arcname[len(strip_prefix):]
                        arcname = arcname.lstrip(os.sep)

                tar.add(full_path, arcname=arcname)

            # Also add directories that are symlinks (check safety)
            for d in dirs:
                dir_path = os.path.join(root, d)
                if os.path.islink(dir_path):
                    real = os.path.realpath(dir_path)
                    if not (real == source_dir
                            or real.startswith(source_dir + os.sep)):
                        raise ValueError(
                            f"Symlink escapes source: {dir_path} -> {real}")


def safe_tar_extract(archive_path, output_dir):
    """Extract a tar.gz archive with path-traversal and symlink protection.

    - Rejects entries with ``../`` or absolute paths (Zip Slip).
    - Rejects symlinks pointing outside *output_dir*.
    - Extracts to a staging directory first, then moves into *output_dir*.
    """
    archive_path = os.path.abspath(archive_path)
    output_dir = os.path.abspath(output_dir)

    if not os.path.isfile(archive_path):
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    os.makedirs(output_dir, exist_ok=True)

    # Use a staging directory in the same parent (same filesystem for rename)
    parent = os.path.dirname(output_dir)
    staging = tempfile.mkdtemp(dir=parent, prefix='.p2p-extract-')

    try:
        with tarfile.open(archive_path, 'r:*') as tar:
            # First pass: validate every entry
            for member in tar.getmembers():
                # Reject absolute paths
                if os.path.isabs(member.name):
                    raise ValueError(
                        f"Absolute path in archive: {member.name}")

                # Reject path traversal
                resolved = _resolve_path(staging, member.name)
                if resolved is None:
                    raise ValueError(
                        f"Path traversal in archive: {member.name}")

                # Reject symlinks that escape output
                if member.issym() or member.islnk():
                    link_target = member.linkname
                    # For symlinks, resolve relative to the member's parent
                    member_parent = os.path.join(
                        staging, os.path.dirname(member.name))
                    if os.path.isabs(link_target):
                        link_resolved = link_target
                    else:
                        link_resolved = os.path.normpath(
                            os.path.join(member_parent, link_target))
                    if not (link_resolved == staging
                            or link_resolved.startswith(staging + os.sep)):
                        raise ValueError(
                            f"Symlink escapes output: {member.name} "
                            f"-> {member.linkname}")

            # Second pass: extract (rewind)
            tar.extractall(path=staging)

        # Move contents from staging into output_dir
        for item in os.listdir(staging):
            src = os.path.join(staging, item)
            dst = os.path.join(output_dir, item)
            if os.path.exists(dst):
                # Remove existing to allow overwrite
                if os.path.isdir(dst):
                    import shutil
                    shutil.rmtree(dst)
                else:
                    os.remove(dst)
            os.rename(src, dst)

    finally:
        # Clean up staging directory
        if os.path.isdir(staging):
            import shutil
            shutil.rmtree(staging, ignore_errors=True)


def tar_list_entries(archive_path):
    """Return a list of entry names in a tar archive."""
    archive_path = os.path.abspath(archive_path)
    if not os.path.isfile(archive_path):
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    with tarfile.open(archive_path, 'r:*') as tar:
        return [m.name for m in tar.getmembers()]


# ---------------------------------------------------------------------------
# JSON state files (atomic read/write)
# ---------------------------------------------------------------------------

def atomic_json_write(path, data):
    """Write *data* as JSON to *path* atomically (temp + fsync + rename).

    The temp file is created in the same directory as *path* so that
    os.replace() is a same-filesystem atomic rename on POSIX.
    """
    path = os.path.abspath(path)
    target_dir = os.path.dirname(path)
    os.makedirs(target_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_json_read(path):
    """Read JSON from *path*. Returns empty dict on missing or corrupt file."""
    path = os.path.abspath(path)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return {}


# ---------------------------------------------------------------------------
# OpenSSL detection
# ---------------------------------------------------------------------------

def detect_openssl():
    """Detect the system openssl binary and its capabilities.

    Returns a dict::

        {
            "binary": "openssl",        # path or name
            "version": "LibreSSL 3.3.6",
            "is_libressl": True,
            "supports_pbkdf2": True,
            "supports_pkeyutl": True,
        }

    Returns None values on detection failure (openssl not found).
    """
    result = {
        'binary': None,
        'version': None,
        'is_libressl': None,
        'supports_pbkdf2': None,
        'supports_pkeyutl': None,
    }

    # Find openssl binary
    for candidate in ['openssl', '/usr/bin/openssl', '/usr/local/bin/openssl']:
        try:
            proc = subprocess.run(
                [candidate, 'version'],
                capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                result['binary'] = candidate
                result['version'] = proc.stdout.strip()
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    if result['binary'] is None:
        return result

    version_str = result['version'] or ''
    result['is_libressl'] = 'LibreSSL' in version_str

    # Detect -pbkdf2 support
    # LibreSSL < 3.1 and OpenSSL < 1.1.1 lack -pbkdf2
    if result['is_libressl']:
        # Parse LibreSSL version: "LibreSSL X.Y.Z"
        m = re.search(r'LibreSSL\s+(\d+)\.(\d+)\.(\d+)', version_str)
        if m:
            major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
            result['supports_pbkdf2'] = (major, minor, patch) >= (3, 1, 0)
        else:
            result['supports_pbkdf2'] = False
    else:
        # OpenSSL: "OpenSSL X.Y.Zp" or "OpenSSL X.Y.Z"
        m = re.search(r'OpenSSL\s+(\d+)\.(\d+)\.(\d+)', version_str)
        if m:
            major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
            result['supports_pbkdf2'] = (major, minor, patch) >= (1, 1, 1)
        else:
            result['supports_pbkdf2'] = False

    # Detect pkeyutl support (needed for RSA-OAEP)
    try:
        proc = subprocess.run(
            [result['binary'], 'pkeyutl', '-help'],
            capture_output=True, text=True, timeout=5)
        # pkeyutl -help returns 0 on OpenSSL, 1 on some versions -- both mean it exists
        # If the command is truly missing, FileNotFoundError or returncode != 0 with
        # "unknown command" in stderr
        stderr = proc.stderr.lower()
        result['supports_pkeyutl'] = 'unknown command' not in stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result['supports_pkeyutl'] = False

    return result


# ---------------------------------------------------------------------------
# Base64
# ---------------------------------------------------------------------------

def b64_encode_file(path):
    """Return strict base64 encoding of a file (no line breaks).

    Uses ``openssl base64 -A`` for cross-platform portability
    (works on both LibreSSL and OpenSSL).
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")

    ssl = detect_openssl()
    if ssl['binary'] is None:
        raise RuntimeError("openssl not found on this system")

    proc = subprocess.run(
        [ssl['binary'], 'base64', '-A', '-in', path],
        capture_output=True, text=True, timeout=30)

    if proc.returncode != 0:
        raise RuntimeError(
            f"openssl base64 failed (rc={proc.returncode}): {proc.stderr}")

    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# YAML frontmatter parsing
# ---------------------------------------------------------------------------

def parse_yaml_frontmatter(content):
    """Parse YAML frontmatter from markdown content.

    Hand-rolled parser matching the pattern in generate-index.py.
    No PyYAML dependency. Handles:
    - Scalar values (strings, numbers, booleans)
    - Inline lists: [a, b, c]
    - Multi-line lists (items starting with ``  - ``)
    - Quoted strings (single and double)

    Returns an empty dict if no frontmatter is found.
    """
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}

    fm = {}
    lines = match.group(1).split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        kv = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', line)
        if kv:
            key = kv.group(1)
            val = kv.group(2).strip()

            # Check for multi-line list (next lines start with "  - ")
            if val == '' or val == '[]':
                items = []
                j = i + 1
                while j < len(lines) and re.match(r'^\s+-\s', lines[j]):
                    item_match = re.match(r'^\s+-\s+(.*)', lines[j])
                    if item_match:
                        items.append(item_match.group(1).strip())
                    j += 1
                if items:
                    fm[key] = items
                    i = j
                    continue
                else:
                    fm[key] = val
            elif val.startswith('[') and val.endswith(']'):
                # Inline list: [a, b, c]
                inner = val[1:-1]
                fm[key] = [x.strip().strip('"').strip("'")
                           for x in inner.split(',') if x.strip()]
            else:
                # Remove surrounding quotes
                if ((val.startswith('"') and val.endswith('"'))
                        or (val.startswith("'") and val.endswith("'"))):
                    val = val[1:-1]

                # Coerce booleans and numbers
                lower = val.lower()
                if lower == 'true':
                    fm[key] = True
                elif lower == 'false':
                    fm[key] = False
                elif lower == 'null' or lower == '~':
                    fm[key] = None
                else:
                    # Try integer
                    try:
                        fm[key] = int(val)
                    except ValueError:
                        # Try float
                        try:
                            fm[key] = float(val)
                        except ValueError:
                            fm[key] = val
        i += 1
    return fm


# ---------------------------------------------------------------------------
# Package format constants
# ---------------------------------------------------------------------------

FORMAT_VERSION = '2.0.0'

# Size threshold for pre-flight warning (35 MB -- GitHub Contents API limit
# with base64 overhead is ~50 MB, but 35 MB leaves margin)
SIZE_WARN_BYTES = 35 * 1024 * 1024

# Paths that are always excluded from packages
_PACKAGE_EXCLUDES = {
    '_kernel/_generated',
    '.alive/_squirrels',
    '_kernel/history',
    '_kernel/links.yaml',
    '_kernel/people.yaml',
    'desktop.ini',
}

# Filename patterns excluded from packages
_PACKAGE_EXCLUDE_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}


def _should_exclude_package(rel_path):
    """Check whether a relative path should be excluded from a package."""
    base = os.path.basename(rel_path)
    if base in _PACKAGE_EXCLUDE_NAMES:
        return True
    if base.startswith('._'):
        return True
    # Check path prefix exclusions
    norm = rel_path.replace(os.sep, '/')
    for excl in _PACKAGE_EXCLUDES:
        if norm == excl or norm.startswith(excl + '/'):
            return True
    return False


def _strip_active_sessions(content):
    """Remove active_sessions: blocks from manifest YAML content."""
    # Remove active_sessions: line and any subsequent indented lines
    lines = content.split('\n')
    result = []
    in_active_sessions = False
    for line in lines:
        if re.match(r'^active_sessions\s*:', line):
            in_active_sessions = True
            continue
        if in_active_sessions:
            # Keep going while indented (continuation of active_sessions block)
            if line and (line[0] == ' ' or line[0] == '\t'):
                continue
            in_active_sessions = False
        result.append(line)
    return '\n'.join(result)


# ---------------------------------------------------------------------------
# Manifest generation and validation
# ---------------------------------------------------------------------------

def generate_manifest(staging_dir, scope, walnut_name, bundles=None,
                      description='', encrypted=False, note='',
                      session_id='', engine='', plugin_version='2.0.0',
                      relay_info=None):
    """Generate a manifest.yaml for a .walnut package.

    Hand-rolled YAML generation (no PyYAML dependency). Returns the YAML
    string and also writes it to staging_dir/manifest.yaml.

    Parameters:
        staging_dir: directory containing the staged files
        scope: 'full', 'bundle', or 'snapshot'
        walnut_name: name of the source walnut
        bundles: list of bundle names (for bundle scope)
        description: human-readable description
        encrypted: whether the payload will be encrypted
        note: optional personal note
        session_id: current session identifier
        engine: AI engine identifier
        plugin_version: alive plugin version
        relay_info: dict with 'repo' and 'sender' keys (optional)
    """
    now = datetime.datetime.now(datetime.timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%SZ')

    # Build file inventory with checksums
    files = []
    for root, dirs, filenames in os.walk(staging_dir):
        dirs.sort()
        for fname in sorted(filenames):
            if fname == 'manifest.yaml':
                continue  # Don't include manifest in its own inventory
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, staging_dir).replace(os.sep, '/')
            size = os.path.getsize(full)
            checksum = sha256_file(full)
            files.append({
                'path': rel,
                'sha256': checksum,
                'size': size,
            })

    # Hand-roll YAML
    lines = []
    lines.append(f'format_version: "{FORMAT_VERSION}"')
    lines.append('')
    lines.append('source:')
    lines.append(f'  walnut: {walnut_name}')
    if session_id:
        lines.append(f'  session_id: {session_id}')
    if engine:
        lines.append(f'  engine: {engine}')
    lines.append(f'  plugin_version: "{plugin_version}"')
    lines.append('')
    lines.append(f'scope: {scope}')
    lines.append(f'created: "{now}"')
    lines.append(f'encrypted: {"true" if encrypted else "false"}')
    if description:
        lines.append(f'description: "{_yaml_escape(description)}"')
    lines.append('')
    lines.append('files:')
    for f in files:
        lines.append(f'  - path: {f["path"]}')
        lines.append(f'    sha256: {f["sha256"]}')
        lines.append(f'    size: {f["size"]}')

    if scope == 'bundle' and bundles:
        lines.append('')
        lines.append('bundles:')
        for b in bundles:
            lines.append(f'  - {b}')

    if note:
        lines.append('')
        lines.append(f'note: "{_yaml_escape(note)}"')

    if relay_info:
        lines.append('')
        lines.append('relay:')
        if relay_info.get('repo'):
            lines.append(f'  repo: {relay_info["repo"]}')
        if relay_info.get('sender'):
            lines.append(f'  sender: {relay_info["sender"]}')

    yaml_content = '\n'.join(lines) + '\n'

    manifest_path = os.path.join(staging_dir, 'manifest.yaml')
    with open(manifest_path, 'w', encoding='utf-8') as mf:
        mf.write(yaml_content)

    return yaml_content


def _yaml_escape(s):
    """Escape a string for embedding in double-quoted YAML values."""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def parse_manifest(manifest_content):
    """Parse a manifest.yaml string into a dict.

    Uses a combination of the existing parse_yaml_frontmatter logic
    and direct parsing for the files array. Since the manifest is
    structured YAML (not frontmatter), we parse it line by line.

    Returns a dict with keys: format_version, source, scope, created,
    encrypted, description, files, bundles, note, relay, signature.
    """
    manifest = {}
    lines = manifest_content.strip().split('\n')
    i = 0
    current_section = None  # Track nested sections: 'source', 'relay', 'signature'
    current_file = None
    files_list = []
    bundles_list = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines and comments
        if not stripped or stripped.startswith('#'):
            i += 1
            continue

        # Detect indentation level
        indent = len(line) - len(line.lstrip())

        # Top-level key: value pairs (indent 0)
        if indent == 0:
            kv = re.match(r'^(\w[\w_-]*)\s*:\s*(.*)', line)
            if kv:
                key = kv.group(1)
                val = kv.group(2).strip()

                if key == 'files' and (val == '' or val == '[]'):
                    current_section = 'files'
                    current_file = None
                elif key == 'bundles' and (val == '' or val == '[]'):
                    current_section = 'bundles'
                elif key == 'source' and val == '':
                    current_section = 'source'
                    manifest['source'] = {}
                elif key == 'relay' and val == '':
                    current_section = 'relay'
                    manifest['relay'] = {}
                elif key == 'signature' and val == '':
                    current_section = 'signature'
                    manifest['signature'] = {}
                else:
                    current_section = None
                    manifest[key] = _yaml_unquote(val)
            i += 1
            continue

        # Indented content belongs to current_section
        if current_section == 'source' and indent >= 2:
            kv = re.match(r'^\s+(\w[\w_-]*)\s*:\s*(.*)', line)
            if kv:
                manifest.setdefault('source', {})[kv.group(1)] = _yaml_unquote(
                    kv.group(2).strip())
        elif current_section == 'relay' and indent >= 2:
            kv = re.match(r'^\s+(\w[\w_-]*)\s*:\s*(.*)', line)
            if kv:
                manifest.setdefault('relay', {})[kv.group(1)] = _yaml_unquote(
                    kv.group(2).strip())
        elif current_section == 'signature' and indent >= 2:
            kv = re.match(r'^\s+(\w[\w_-]*)\s*:\s*(.*)', line)
            if kv:
                manifest.setdefault('signature', {})[kv.group(1)] = _yaml_unquote(
                    kv.group(2).strip())
        elif current_section == 'files':
            if stripped.startswith('- path:'):
                # Start of a new file entry
                if current_file:
                    files_list.append(current_file)
                path_val = stripped[len('- path:'):].strip()
                current_file = {'path': _yaml_unquote(path_val)}
            elif current_file and indent >= 4:
                kv = re.match(r'^\s+(\w[\w_-]*)\s*:\s*(.*)', line)
                if kv:
                    val = _yaml_unquote(kv.group(2).strip())
                    # Coerce size to int
                    if kv.group(1) == 'size':
                        try:
                            val = int(val)
                        except (ValueError, TypeError):
                            pass
                    current_file[kv.group(1)] = val
        elif current_section == 'bundles':
            if stripped.startswith('- '):
                bundles_list.append(stripped[2:].strip())

        i += 1

    # Flush last file entry
    if current_file:
        files_list.append(current_file)

    if files_list:
        manifest['files'] = files_list
    if bundles_list:
        manifest['bundles'] = bundles_list

    # Coerce booleans
    if 'encrypted' in manifest:
        if isinstance(manifest['encrypted'], str):
            manifest['encrypted'] = manifest['encrypted'].lower() == 'true'

    return manifest


def _yaml_unquote(val):
    """Remove surrounding quotes from a YAML value string."""
    if not val:
        return val
    if (val.startswith('"') and val.endswith('"')) or \
       (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    # Coerce booleans/numbers
    lower = val.lower()
    if lower == 'true':
        return True
    if lower == 'false':
        return False
    if lower in ('null', '~'):
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def validate_manifest(manifest):
    """Validate a parsed manifest dict. Returns (ok, errors) tuple.

    Checks required fields, format_version compatibility, and file entries.
    """
    errors = []

    # Required top-level fields
    for field in ('format_version', 'scope', 'created', 'files'):
        if field not in manifest:
            errors.append(f"Missing required field: {field}")

    # format_version must be 2.x
    fv = str(manifest.get('format_version', ''))
    if not fv.startswith('2.'):
        errors.append(
            f"Unsupported format_version: {fv} (expected 2.x)")

    # scope must be valid
    scope = manifest.get('scope', '')
    if scope not in ('full', 'bundle', 'snapshot'):
        errors.append(f"Invalid scope: {scope}")

    # source must exist and have walnut
    source = manifest.get('source')
    if not isinstance(source, dict):
        errors.append("Missing or invalid 'source' section")
    elif 'walnut' not in source:
        errors.append("Missing 'source.walnut' field")

    # files must be a list with path and sha256
    files = manifest.get('files', [])
    if not isinstance(files, list):
        errors.append("'files' must be a list")
    else:
        for idx, f in enumerate(files):
            if not isinstance(f, dict):
                errors.append(f"File entry {idx} is not a dict")
                continue
            if 'path' not in f:
                errors.append(f"File entry {idx} missing 'path'")
            if 'sha256' not in f:
                errors.append(f"File entry {idx} missing 'sha256'")

    # bundle scope should have bundles list
    if scope == 'bundle':
        if not manifest.get('bundles'):
            errors.append("Bundle scope requires 'bundles' list")

    return (len(errors) == 0, errors)


def verify_checksums(manifest, base_dir):
    """Verify SHA-256 checksums for all files listed in the manifest.

    Returns (ok, failures) where failures is a list of dicts describing
    each mismatch or missing file.
    """
    failures = []
    for entry in manifest.get('files', []):
        rel_path = entry['path']
        expected = entry['sha256']
        full_path = os.path.join(base_dir, rel_path.replace('/', os.sep))

        if not os.path.isfile(full_path):
            failures.append({
                'path': rel_path,
                'error': 'file_missing',
                'expected': expected,
            })
            continue

        actual = sha256_file(full_path)
        if actual != expected:
            failures.append({
                'path': rel_path,
                'error': 'checksum_mismatch',
                'expected': expected,
                'actual': actual,
            })

    return (len(failures) == 0, failures)


def check_unlisted_files(manifest, base_dir):
    """Check for files in base_dir that are not listed in the manifest.

    Returns a list of unlisted relative paths. The manifest.yaml itself
    is excluded from this check.
    """
    listed = {entry['path'] for entry in manifest.get('files', [])}
    listed.add('manifest.yaml')

    unlisted = []
    for root, dirs, filenames in os.walk(base_dir):
        for fname in filenames:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, base_dir).replace(os.sep, '/')
            if rel not in listed:
                unlisted.append(rel)

    return unlisted


# ---------------------------------------------------------------------------
# Package creation
# ---------------------------------------------------------------------------

def _stage_files(walnut_path, scope, bundle_names=None):
    """Stage files from a walnut into a temporary directory by scope rules.

    Returns the staging directory path. Caller is responsible for cleanup.

    Scope rules (from arch doc section 2):
      full:     _kernel/ (key, log, insights) + all bundles/ + live context
      bundle:   _kernel/key.md + selected bundles/
      snapshot: _kernel/key.md + _kernel/insights.md
    """
    walnut_path = os.path.abspath(walnut_path)
    if not os.path.isdir(walnut_path):
        raise FileNotFoundError(f"Walnut not found: {walnut_path}")

    staging = tempfile.mkdtemp(prefix='.walnut-stage-')

    try:
        if scope == 'full':
            _stage_full(walnut_path, staging)
        elif scope == 'bundle':
            if not bundle_names:
                raise ValueError("Bundle scope requires at least one bundle name")
            _stage_bundle(walnut_path, staging, bundle_names)
        elif scope == 'snapshot':
            _stage_snapshot(walnut_path, staging)
        else:
            raise ValueError(f"Unknown scope: {scope}")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return staging


def _copy_file(src, dst):
    """Copy a file, creating parent dirs as needed. Strip active_sessions
    from YAML/manifest files."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    base = os.path.basename(src)
    # Strip active_sessions from manifest files
    if base.endswith('.yaml') or base.endswith('.yml'):
        with open(src, 'r', encoding='utf-8') as f:
            content = f.read()
        content = _strip_active_sessions(content)
        with open(dst, 'w', encoding='utf-8') as f:
            f.write(content)
    else:
        shutil.copy2(src, dst)


def _stage_full(walnut_path, staging):
    """Stage files for full scope: _kernel/ (3 source files) + bundles/ + live context."""
    # _kernel/ source files: key.md, log.md, insights.md
    kernel_src = os.path.join(walnut_path, '_kernel')
    kernel_dst = os.path.join(staging, '_kernel')
    kernel_files = ['key.md', 'log.md', 'insights.md']
    for kf in kernel_files:
        src = os.path.join(kernel_src, kf)
        if os.path.isfile(src):
            _copy_file(src, os.path.join(kernel_dst, kf))

    # All bundles/
    bundles_src = os.path.join(walnut_path, 'bundles')
    if os.path.isdir(bundles_src):
        _stage_tree(bundles_src, os.path.join(staging, 'bundles'))

    # Live context: everything at walnut root except _kernel/, bundles/,
    # .alive/, and other system dirs
    _stage_live_context(walnut_path, staging)


def _stage_bundle(walnut_path, staging, bundle_names):
    """Stage files for bundle scope: _kernel/key.md + selected bundles."""
    # Always include key.md
    key_src = os.path.join(walnut_path, '_kernel', 'key.md')
    if os.path.isfile(key_src):
        _copy_file(key_src, os.path.join(staging, '_kernel', 'key.md'))

    # Selected bundles
    for bname in bundle_names:
        bundle_src = os.path.join(walnut_path, 'bundles', bname)
        if not os.path.isdir(bundle_src):
            raise FileNotFoundError(
                f"Bundle not found: {bname} (expected at {bundle_src})")
        _stage_tree(bundle_src, os.path.join(staging, 'bundles', bname))


def _stage_snapshot(walnut_path, staging):
    """Stage files for snapshot scope: _kernel/key.md + _kernel/insights.md."""
    kernel_src = os.path.join(walnut_path, '_kernel')
    kernel_dst = os.path.join(staging, '_kernel')
    for fname in ('key.md', 'insights.md'):
        src = os.path.join(kernel_src, fname)
        if os.path.isfile(src):
            _copy_file(src, os.path.join(kernel_dst, fname))


def _stage_tree(src_dir, dst_dir):
    """Recursively copy a directory tree, applying package exclusions."""
    src_dir = os.path.abspath(src_dir)
    for root, dirs, files in os.walk(src_dir):
        # Filter excluded directories in-place
        dirs[:] = [d for d in dirs
                   if not d.startswith('._') and d not in _PACKAGE_EXCLUDE_NAMES]

        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, os.path.dirname(src_dir))
            if _should_exclude_package(rel):
                continue
            dst = os.path.join(dst_dir, os.path.relpath(full, src_dir))
            _copy_file(full, dst)


def _stage_live_context(walnut_path, staging):
    """Stage live context files (everything outside _kernel/, bundles/, .alive/)."""
    skip_dirs = {'_kernel', 'bundles', '.alive', '.git', '__pycache__',
                 'node_modules', '.DS_Store'}

    for item in os.listdir(walnut_path):
        if item in skip_dirs or item.startswith('.'):
            continue
        src = os.path.join(walnut_path, item)
        if os.path.isdir(src):
            _stage_tree(src, os.path.join(staging, item))
        elif os.path.isfile(src):
            rel = item
            if not _should_exclude_package(rel):
                _copy_file(src, os.path.join(staging, item))


def create_package(walnut_path, scope, output_path=None, bundle_names=None,
                   description='', note='', session_id='', engine='',
                   plugin_version='2.0.0', relay_info=None):
    """Create a .walnut package from a walnut directory.

    Parameters:
        walnut_path: path to the walnut directory
        scope: 'full', 'bundle', or 'snapshot'
        output_path: path for the output .walnut file (auto-generated if None)
        bundle_names: list of bundle names (required for bundle scope)
        description: human-readable description
        note: optional personal note
        session_id: session identifier for manifest
        engine: AI engine identifier for manifest
        plugin_version: alive plugin version
        relay_info: dict with 'repo' and 'sender' (optional)

    Returns a dict with:
        path: output file path
        size: file size in bytes
        manifest: parsed manifest dict
        warnings: list of warning strings
    """
    walnut_path = os.path.abspath(walnut_path)
    walnut_name = os.path.basename(walnut_path)
    warnings = []

    # Stage files by scope
    staging = _stage_files(walnut_path, scope, bundle_names)

    try:
        # Generate manifest
        generate_manifest(
            staging_dir=staging,
            scope=scope,
            walnut_name=walnut_name,
            bundles=bundle_names,
            description=description,
            encrypted=False,  # Encryption happens after packaging
            note=note,
            session_id=session_id,
            engine=engine,
            plugin_version=plugin_version,
            relay_info=relay_info,
        )

        # Generate output filename if not specified
        if output_path is None:
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            if scope == 'bundle' and bundle_names:
                bundle_slug = '-'.join(bundle_names[:3])
                filename = f"{walnut_name}-bundle-{bundle_slug}-{today}.walnut"
            else:
                filename = f"{walnut_name}-{scope}-{today}.walnut"
            output_path = os.path.join(os.path.expanduser('~/Desktop'), filename)

        output_path = os.path.abspath(output_path)

        # Create tar.gz from staging directory
        safe_tar_create(staging, output_path)

        # Check size
        size = os.path.getsize(output_path)
        if size > SIZE_WARN_BYTES:
            warnings.append(
                f"Package is {size / (1024*1024):.1f} MB -- exceeds 35 MB "
                f"recommended limit for GitHub relay (Contents API limit ~50 MB "
                f"with base64 overhead)")

        # Read back manifest for return value
        manifest_path = os.path.join(staging, 'manifest.yaml')
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = parse_manifest(f.read())

        return {
            'path': output_path,
            'size': size,
            'manifest': manifest,
            'warnings': warnings,
        }

    finally:
        shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------------------
# Package extraction
# ---------------------------------------------------------------------------

def extract_package(input_path, output_dir=None):
    """Extract and validate a .walnut package.

    Extracts to a staging directory, validates the manifest, verifies
    checksums, and checks for unlisted files.

    Parameters:
        input_path: path to the .walnut file
        output_dir: extraction target (temp dir if None)

    Returns a dict with:
        manifest: parsed and validated manifest dict
        staging_path: path to the extracted files
        warnings: list of warning strings
    """
    input_path = os.path.abspath(input_path)
    warnings = []

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Package not found: {input_path}")

    # Create output directory
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix='.walnut-extract-')
    else:
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)

    # Extract archive
    safe_tar_extract(input_path, output_dir)

    # Find and parse manifest
    manifest_path = os.path.join(output_dir, 'manifest.yaml')
    if not os.path.isfile(manifest_path):
        raise ValueError("Package missing manifest.yaml")

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = parse_manifest(f.read())

    # Validate manifest structure
    ok, errors = validate_manifest(manifest)
    if not ok:
        raise ValueError(
            f"Invalid manifest: {'; '.join(errors)}")

    # Verify checksums
    ok, failures = verify_checksums(manifest, output_dir)
    if not ok:
        details = []
        for fail in failures:
            if fail['error'] == 'file_missing':
                details.append(f"  missing: {fail['path']}")
            else:
                details.append(
                    f"  mismatch: {fail['path']} "
                    f"(expected {fail['expected'][:12]}..., "
                    f"got {fail['actual'][:12]}...)")
        raise ValueError(
            f"Checksum verification failed:\n" + '\n'.join(details))

    # Check for unlisted files
    unlisted = check_unlisted_files(manifest, output_dir)
    if unlisted:
        warnings.append(
            f"Package contains {len(unlisted)} unlisted file(s): "
            + ', '.join(unlisted[:5]))

    return {
        'manifest': manifest,
        'staging_path': output_dir,
        'warnings': warnings,
    }


# ---------------------------------------------------------------------------
# Encryption / Decryption
# ---------------------------------------------------------------------------

def _get_openssl():
    """Get the openssl binary path, raising RuntimeError if not found."""
    ssl = detect_openssl()
    if ssl['binary'] is None:
        raise RuntimeError("openssl not found on this system")
    return ssl


def encrypt_package(package_path, output_path=None, mode='passphrase',
                    recipient_pubkey=None):
    """Encrypt a .walnut package.

    Two modes:
      passphrase: AES-256-CBC with PBKDF2 (600k iterations).
                  Passphrase read from WALNUT_PASSPHRASE env var.
      rsa:        Random 256-bit AES key, encrypt payload with AES,
                  wrap key with RSA-OAEP-SHA256 (pkeyutl).
                  PBKDF2 iter=10000 for the AES (key is random, not
                  password-derived).

    The output is a new .walnut file containing:
      manifest.yaml (cleartext, updated with encrypted: true)
      payload.enc (encrypted inner tar.gz)
      payload.key (RSA mode only -- wrapped AES key)

    Parameters:
        package_path: path to the unencrypted .walnut file
        output_path: path for the encrypted .walnut file
        mode: 'passphrase' or 'rsa'
        recipient_pubkey: path to recipient's RSA public key (rsa mode)

    Returns the path to the encrypted .walnut file.
    """
    package_path = os.path.abspath(package_path)
    ssl = _get_openssl()

    if mode == 'passphrase':
        passphrase = os.environ.get('WALNUT_PASSPHRASE', '')
        if not passphrase:
            raise ValueError(
                "WALNUT_PASSPHRASE environment variable not set. "
                "Set it before encrypting: export WALNUT_PASSPHRASE='your passphrase'")
        if not ssl['supports_pbkdf2']:
            raise RuntimeError(
                f"OpenSSL {ssl['version']} does not support -pbkdf2. "
                f"Upgrade to LibreSSL >= 3.1 or OpenSSL >= 1.1.1")
    elif mode == 'rsa':
        if not recipient_pubkey:
            raise ValueError("RSA mode requires recipient_pubkey path")
        recipient_pubkey = os.path.abspath(recipient_pubkey)
        if not os.path.isfile(recipient_pubkey):
            raise FileNotFoundError(
                f"Recipient public key not found: {recipient_pubkey}")
        if not ssl['supports_pkeyutl']:
            raise RuntimeError(
                f"OpenSSL {ssl['version']} does not support pkeyutl")
    else:
        raise ValueError(f"Unknown encryption mode: {mode}")

    # Extract the package to get manifest and payload
    work_dir = tempfile.mkdtemp(prefix='.walnut-encrypt-')

    try:
        # Extract original package
        safe_tar_extract(package_path, work_dir)

        # Read manifest
        manifest_path = os.path.join(work_dir, 'manifest.yaml')
        if not os.path.isfile(manifest_path):
            raise ValueError("Package missing manifest.yaml")

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_content = f.read()

        manifest = parse_manifest(manifest_content)

        # Create inner tar.gz of all files except manifest
        inner_dir = tempfile.mkdtemp(prefix='.walnut-inner-', dir=work_dir)
        for entry in manifest.get('files', []):
            src = os.path.join(work_dir, entry['path'].replace('/', os.sep))
            dst = os.path.join(inner_dir, entry['path'].replace('/', os.sep))
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

        inner_tar = os.path.join(work_dir, 'inner.tar.gz')
        safe_tar_create(inner_dir, inner_tar)

        # Build encrypted output staging directory
        enc_staging = tempfile.mkdtemp(prefix='.walnut-enc-stage-', dir=work_dir)
        payload_enc = os.path.join(enc_staging, 'payload.enc')

        if mode == 'passphrase':
            # AES-256-CBC with PBKDF2, 600k iterations
            proc = subprocess.run(
                [ssl['binary'], 'enc', '-aes-256-cbc', '-salt',
                 '-pbkdf2', '-iter', '600000',
                 '-in', inner_tar, '-out', payload_enc,
                 '-pass', f'env:WALNUT_PASSPHRASE'],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, 'WALNUT_PASSPHRASE': passphrase})

            if proc.returncode != 0:
                raise RuntimeError(
                    f"Passphrase encryption failed: {proc.stderr}")

        elif mode == 'rsa':
            # Generate random 256-bit AES key
            aes_key_path = os.path.join(work_dir, 'aes.key')
            proc = subprocess.run(
                [ssl['binary'], 'rand', '-out', aes_key_path, '32'],
                capture_output=True, text=True, timeout=10)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Failed to generate random key: {proc.stderr}")

            # Read the raw key bytes for use as hex passphrase
            with open(aes_key_path, 'rb') as f:
                aes_key_bytes = f.read()
            aes_key_hex = aes_key_bytes.hex()

            # Encrypt inner tar with AES using the random key
            # Use -K (hex key) and -iv instead of -pass to avoid PBKDF2
            # overhead on a random key. Generate random IV.
            iv_proc = subprocess.run(
                [ssl['binary'], 'rand', '-hex', '16'],
                capture_output=True, text=True, timeout=10)
            if iv_proc.returncode != 0:
                raise RuntimeError(
                    f"Failed to generate IV: {iv_proc.stderr}")
            iv_hex = iv_proc.stdout.strip()

            proc = subprocess.run(
                [ssl['binary'], 'enc', '-aes-256-cbc',
                 '-K', aes_key_hex, '-iv', iv_hex,
                 '-in', inner_tar, '-out', payload_enc],
                capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"AES encryption failed: {proc.stderr}")

            # Wrap AES key + IV with RSA-OAEP-SHA256
            # Pack key (32 bytes) + iv (16 bytes hex -> 16 bytes raw)
            iv_bytes = bytes.fromhex(iv_hex)
            key_material = aes_key_bytes + iv_bytes
            key_material_path = os.path.join(work_dir, 'key_material.bin')
            with open(key_material_path, 'wb') as f:
                f.write(key_material)

            payload_key_path = os.path.join(enc_staging, 'payload.key')
            proc = subprocess.run(
                [ssl['binary'], 'pkeyutl', '-encrypt',
                 '-pubin', '-inkey', recipient_pubkey,
                 '-pkeyopt', 'rsa_padding_mode:oaep',
                 '-pkeyopt', 'rsa_oaep_md:sha256',
                 '-in', key_material_path, '-out', payload_key_path],
                capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"RSA key wrapping failed: {proc.stderr}")

            # Securely clean up key material
            _secure_delete(aes_key_path)
            _secure_delete(key_material_path)

        # Update manifest to indicate encryption
        updated_manifest = _update_manifest_encrypted(manifest_content, True)
        with open(os.path.join(enc_staging, 'manifest.yaml'), 'w',
                  encoding='utf-8') as f:
            f.write(updated_manifest)

        # Create output .walnut
        if output_path is None:
            base, ext = os.path.splitext(package_path)
            output_path = base + '-encrypted' + ext
        output_path = os.path.abspath(output_path)

        safe_tar_create(enc_staging, output_path)
        return output_path

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def decrypt_package(encrypted_path, output_path=None, private_key=None):
    """Decrypt a .walnut package.

    Auto-detects mode:
      - payload.key present -> RSA mode (requires private_key path)
      - payload.enc only -> passphrase mode (reads WALNUT_PASSPHRASE env var)

    Parameters:
        encrypted_path: path to the encrypted .walnut file
        output_path: path for the decrypted .walnut file
        private_key: path to RSA private key (for RSA mode)

    Returns the path to the decrypted .walnut file.
    """
    encrypted_path = os.path.abspath(encrypted_path)
    ssl = _get_openssl()

    work_dir = tempfile.mkdtemp(prefix='.walnut-decrypt-')

    try:
        # Extract encrypted package
        safe_tar_extract(encrypted_path, work_dir)

        payload_enc = os.path.join(work_dir, 'payload.enc')
        payload_key = os.path.join(work_dir, 'payload.key')
        manifest_path = os.path.join(work_dir, 'manifest.yaml')

        if not os.path.isfile(payload_enc):
            raise ValueError("Package is not encrypted (no payload.enc)")
        if not os.path.isfile(manifest_path):
            raise ValueError("Package missing manifest.yaml")

        inner_tar = os.path.join(work_dir, 'inner.tar.gz')

        if os.path.isfile(payload_key):
            # RSA mode
            if not private_key:
                raise ValueError(
                    "RSA-encrypted package requires --private-key path")
            private_key = os.path.abspath(private_key)
            if not os.path.isfile(private_key):
                raise FileNotFoundError(
                    f"Private key not found: {private_key}")

            # Unwrap AES key + IV with RSA
            key_material_path = os.path.join(work_dir, 'key_material.bin')
            proc = subprocess.run(
                [ssl['binary'], 'pkeyutl', '-decrypt',
                 '-inkey', private_key,
                 '-pkeyopt', 'rsa_padding_mode:oaep',
                 '-pkeyopt', 'rsa_oaep_md:sha256',
                 '-in', payload_key, '-out', key_material_path],
                capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"RSA key unwrapping failed: {proc.stderr}")

            # Extract key (32 bytes) + IV (16 bytes)
            with open(key_material_path, 'rb') as f:
                key_material = f.read()
            if len(key_material) < 48:
                raise ValueError(
                    f"Invalid key material length: {len(key_material)} "
                    f"(expected 48 bytes)")

            aes_key_hex = key_material[:32].hex()
            iv_hex = key_material[32:48].hex()

            # Decrypt with AES
            proc = subprocess.run(
                [ssl['binary'], 'enc', '-d', '-aes-256-cbc',
                 '-K', aes_key_hex, '-iv', iv_hex,
                 '-in', payload_enc, '-out', inner_tar],
                capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"AES decryption failed: {proc.stderr}")

            _secure_delete(key_material_path)

        else:
            # Passphrase mode
            passphrase = os.environ.get('WALNUT_PASSPHRASE', '')
            if not passphrase:
                raise ValueError(
                    "WALNUT_PASSPHRASE environment variable not set")

            proc = subprocess.run(
                [ssl['binary'], 'enc', '-d', '-aes-256-cbc',
                 '-pbkdf2', '-iter', '600000',
                 '-in', payload_enc, '-out', inner_tar,
                 '-pass', f'env:WALNUT_PASSPHRASE'],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, 'WALNUT_PASSPHRASE': passphrase})

            if proc.returncode != 0:
                raise RuntimeError(
                    f"Passphrase decryption failed (wrong passphrase?): "
                    f"{proc.stderr}")

        # Build decrypted output staging directory
        dec_staging = tempfile.mkdtemp(prefix='.walnut-dec-stage-', dir=work_dir)

        # Extract inner tar to staging
        safe_tar_extract(inner_tar, dec_staging)

        # Copy manifest (update encrypted flag)
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_content = f.read()
        updated = _update_manifest_encrypted(manifest_content, False)
        with open(os.path.join(dec_staging, 'manifest.yaml'), 'w',
                  encoding='utf-8') as f:
            f.write(updated)

        # Create output .walnut
        if output_path is None:
            base, ext = os.path.splitext(encrypted_path)
            # Strip -encrypted suffix if present
            if base.endswith('-encrypted'):
                base = base[:-len('-encrypted')]
            output_path = base + '-decrypted' + ext
        output_path = os.path.abspath(output_path)

        safe_tar_create(dec_staging, output_path)
        return output_path

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _update_manifest_encrypted(manifest_content, encrypted):
    """Update the encrypted: field in manifest YAML content."""
    val = 'true' if encrypted else 'false'
    # Try to replace existing field
    updated = re.sub(
        r'^(encrypted:\s*).*$',
        f'encrypted: {val}',
        manifest_content,
        count=1,
        flags=re.MULTILINE)
    return updated


def _secure_delete(path):
    """Overwrite file with zeros before deleting (best-effort)."""
    try:
        size = os.path.getsize(path)
        with open(path, 'wb') as f:
            f.write(b'\x00' * size)
            f.flush()
            os.fsync(f.fileno())
        os.unlink(path)
    except OSError:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Manifest signing and verification
# ---------------------------------------------------------------------------

def sign_manifest(manifest_path, private_key_path):
    """Sign a manifest.yaml with RSA-SHA256 using pkeyutl.

    Reads the manifest, removes any existing signature block, signs the
    remaining content, and appends the signature block.

    Parameters:
        manifest_path: path to manifest.yaml to sign
        private_key_path: path to sender's RSA private key

    Returns the updated manifest content with signature block.
    """
    manifest_path = os.path.abspath(manifest_path)
    private_key_path = os.path.abspath(private_key_path)
    ssl = _get_openssl()

    if not ssl['supports_pkeyutl']:
        raise RuntimeError(
            f"OpenSSL {ssl['version']} does not support pkeyutl")

    with open(manifest_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Remove any existing signature block
    content_to_sign = _strip_signature_block(content)

    # Write content to temp file for signing
    work_dir = tempfile.mkdtemp(prefix='.walnut-sign-')
    try:
        # First create a SHA-256 digest of the content
        data_path = os.path.join(work_dir, 'manifest.data')
        with open(data_path, 'w', encoding='utf-8') as f:
            f.write(content_to_sign)

        digest_path = os.path.join(work_dir, 'manifest.dgst')
        sig_path = os.path.join(work_dir, 'manifest.sig')

        # Hash the data
        proc = subprocess.run(
            [ssl['binary'], 'dgst', '-sha256', '-binary',
             '-out', digest_path, data_path],
            capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            raise RuntimeError(f"Digest failed: {proc.stderr}")

        # Sign the digest with RSA
        proc = subprocess.run(
            [ssl['binary'], 'pkeyutl', '-sign',
             '-inkey', private_key_path,
             '-pkeyopt', 'digest:sha256',
             '-in', digest_path, '-out', sig_path],
            capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            raise RuntimeError(f"Signing failed: {proc.stderr}")

        # Read signature and base64 encode
        with open(sig_path, 'rb') as f:
            sig_bytes = f.read()
        sig_b64 = base64.b64encode(sig_bytes).decode('ascii')

        # Derive signer name from the key path (best effort)
        # The caller should set this properly via the manifest
        signer = os.path.basename(os.path.dirname(
            os.path.dirname(private_key_path)))
        if not signer or signer == '.':
            signer = 'unknown'

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    # Append signature block
    signed_content = content_to_sign.rstrip('\n') + '\n'
    signed_content += '\nsignature:\n'
    signed_content += '  algorithm: "RSA-SHA256"\n'
    signed_content += f'  signer: "{signer}"\n'
    signed_content += f'  value: "{sig_b64}"\n'

    # Write signed manifest
    with open(manifest_path, 'w', encoding='utf-8') as f:
        f.write(signed_content)

    return signed_content


def verify_manifest(manifest_path, public_key_path):
    """Verify the RSA-SHA256 signature on a manifest.yaml.

    Parameters:
        manifest_path: path to the signed manifest.yaml
        public_key_path: path to the signer's RSA public key

    Returns (verified, signer) tuple. verified is True if signature is valid.
    """
    manifest_path = os.path.abspath(manifest_path)
    public_key_path = os.path.abspath(public_key_path)
    ssl = _get_openssl()

    if not ssl['supports_pkeyutl']:
        raise RuntimeError(
            f"OpenSSL {ssl['version']} does not support pkeyutl")

    with open(manifest_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parse manifest to get signature
    manifest = parse_manifest(content)
    sig_info = manifest.get('signature')
    if not sig_info:
        return (False, None)

    sig_b64 = sig_info.get('value', '')
    signer = sig_info.get('signer', '')

    if not sig_b64:
        return (False, signer)

    # Strip signature block to get the signed content
    content_to_verify = _strip_signature_block(content)

    # Decode signature
    try:
        sig_bytes = base64.b64decode(sig_b64)
    except Exception:
        return (False, signer)

    work_dir = tempfile.mkdtemp(prefix='.walnut-verify-')
    try:
        data_path = os.path.join(work_dir, 'manifest.data')
        with open(data_path, 'w', encoding='utf-8') as f:
            f.write(content_to_verify)

        digest_path = os.path.join(work_dir, 'manifest.dgst')
        sig_path = os.path.join(work_dir, 'manifest.sig')

        # Hash the data
        proc = subprocess.run(
            [ssl['binary'], 'dgst', '-sha256', '-binary',
             '-out', digest_path, data_path],
            capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return (False, signer)

        # Write signature to file
        with open(sig_path, 'wb') as f:
            f.write(sig_bytes)

        # Verify with public key
        proc = subprocess.run(
            [ssl['binary'], 'pkeyutl', '-verify',
             '-pubin', '-inkey', public_key_path,
             '-pkeyopt', 'digest:sha256',
             '-in', digest_path, '-sigfile', sig_path],
            capture_output=True, text=True, timeout=10)

        verified = proc.returncode == 0
        return (verified, signer)

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _strip_signature_block(content):
    """Remove the signature: block from manifest content.

    Returns the content without the signature section (for signing/verification).
    """
    lines = content.split('\n')
    result = []
    in_sig = False
    for line in lines:
        if re.match(r'^signature\s*:', line):
            in_sig = True
            continue
        if in_sig:
            if line and (line[0] == ' ' or line[0] == '\t'):
                continue
            in_sig = False
        result.append(line)

    # Remove trailing blank lines that were before the signature block
    while result and result[-1].strip() == '':
        result.pop()

    return '\n'.join(result) + '\n'


# ---------------------------------------------------------------------------
# CLI (smoke tests)
# ---------------------------------------------------------------------------

def _cli():
    """Minimal CLI for smoke-testing functions."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'hash':
        if len(sys.argv) < 3:
            print("Usage: alive-p2p.py hash <file>", file=sys.stderr)
            sys.exit(1)
        print(sha256_file(sys.argv[2]))

    elif cmd == 'openssl':
        info = detect_openssl()
        for k, v in info.items():
            print(f"  {k}: {v}")

    elif cmd == 'tar-create':
        if len(sys.argv) < 4:
            print("Usage: alive-p2p.py tar-create <source_dir> <output.tar.gz>",
                  file=sys.stderr)
            sys.exit(1)
        safe_tar_create(sys.argv[2], sys.argv[3])
        entries = tar_list_entries(sys.argv[3])
        print(f"Created {sys.argv[3]} ({len(entries)} entries)")
        for e in entries:
            print(f"  {e}")

    elif cmd == 'tar-extract':
        if len(sys.argv) < 4:
            print("Usage: alive-p2p.py tar-extract <archive.tar.gz> <output_dir>",
                  file=sys.stderr)
            sys.exit(1)
        safe_tar_extract(sys.argv[2], sys.argv[3])
        print(f"Extracted to {sys.argv[3]}")

    elif cmd == 'tar-list':
        if len(sys.argv) < 3:
            print("Usage: alive-p2p.py tar-list <archive.tar.gz>",
                  file=sys.stderr)
            sys.exit(1)
        entries = tar_list_entries(sys.argv[2])
        for e in entries:
            print(e)

    elif cmd == 'b64':
        if len(sys.argv) < 3:
            print("Usage: alive-p2p.py b64 <file>", file=sys.stderr)
            sys.exit(1)
        print(b64_encode_file(sys.argv[2]))

    elif cmd == 'yaml':
        if len(sys.argv) < 3:
            print("Usage: alive-p2p.py yaml <file>", file=sys.stderr)
            sys.exit(1)
        with open(sys.argv[2], 'r', encoding='utf-8') as f:
            content = f.read()
        fm = parse_yaml_frontmatter(content)
        print(json.dumps(fm, indent=2, default=str))

    elif cmd == 'create':
        # Parse arguments
        scope = None
        walnut = None
        bundles = []
        output = None
        description = ''
        i = 2
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == '--scope' and i + 1 < len(sys.argv):
                scope = sys.argv[i + 1]
                i += 2
            elif arg == '--walnut' and i + 1 < len(sys.argv):
                walnut = sys.argv[i + 1]
                i += 2
            elif arg == '--bundle' and i + 1 < len(sys.argv):
                bundles.append(sys.argv[i + 1])
                i += 2
            elif arg == '--output' and i + 1 < len(sys.argv):
                output = sys.argv[i + 1]
                i += 2
            elif arg == '--description' and i + 1 < len(sys.argv):
                description = sys.argv[i + 1]
                i += 2
            else:
                print(f"Unknown argument: {arg}", file=sys.stderr)
                sys.exit(1)

        if not scope or not walnut:
            print("Usage: alive-p2p.py create --scope <full|bundle|snapshot> "
                  "--walnut <path> [--bundle <name>...] [--output <path>] "
                  "[--description <text>]", file=sys.stderr)
            sys.exit(1)

        result = create_package(
            walnut_path=walnut,
            scope=scope,
            output_path=output,
            bundle_names=bundles if bundles else None,
            description=description)

        print(f"Created: {result['path']}")
        print(f"Size: {result['size']} bytes ({result['size'] / 1024:.1f} KB)")
        print(f"Scope: {result['manifest'].get('scope')}")
        file_count = len(result['manifest'].get('files', []))
        print(f"Files: {file_count}")
        for w in result.get('warnings', []):
            print(f"WARNING: {w}", file=sys.stderr)

    elif cmd == 'extract':
        input_path = None
        output_dir = None
        i = 2
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == '--input' and i + 1 < len(sys.argv):
                input_path = sys.argv[i + 1]
                i += 2
            elif arg == '--output' and i + 1 < len(sys.argv):
                output_dir = sys.argv[i + 1]
                i += 2
            else:
                print(f"Unknown argument: {arg}", file=sys.stderr)
                sys.exit(1)

        if not input_path:
            print("Usage: alive-p2p.py extract --input <file.walnut> "
                  "[--output <dir>]", file=sys.stderr)
            sys.exit(1)

        result = extract_package(input_path, output_dir)
        print(f"Extracted to: {result['staging_path']}")
        m = result['manifest']
        print(f"Format: {m.get('format_version')}")
        print(f"Scope: {m.get('scope')}")
        print(f"Source: {m.get('source', {}).get('walnut', 'unknown')}")
        print(f"Files: {len(m.get('files', []))}")
        print(f"Encrypted: {m.get('encrypted', False)}")
        for w in result.get('warnings', []):
            print(f"WARNING: {w}", file=sys.stderr)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    _cli()
