# alive-mcp error codes (v0.1)

Every tool in the v0.1 roster returns a structured envelope. On failure,
`structuredContent` carries a record of the form:

```json
{
  "error": "WALNUT_NOT_FOUND",
  "message": "No walnut found at 'nova-station' in this World.",
  "suggestions": [
    "Call 'list_walnuts' to see available walnuts in this World.",
    "Walnut paths are POSIX-relative from the World root (e.g. '04_Ventures/nova-station'), not bare names."
  ]
}
```

The `error` value drops the `ERR_` prefix for the wire (Merge/Workato
convention). The full constant (`ERR_WALNUT_NOT_FOUND`) is the internal
source of truth; it is what the exception subclasses carry and what the
audit log records.

Nine codes cover the full v0.1 read-only surface. No message template
contains an absolute filesystem path — `mask_error_details=True` is
enforced at the template level, not by post-filtering.

---

## ERR_NO_WORLD

**Wire code:** `NO_WORLD`
**Seam:** World discovery (server startup + Roots change notifications)
**Exception:** `WorldNotFoundError` (re-exported from `_vendor._pure`)

### Cause

The server could not resolve a single World root from its configured
Roots or environment fallback. One of:

- The MCP client did not send `roots/list` and no `ALIVE_WORLD_ROOT`
  env var is set.
- Every Root the client sent, when walked upward within its own bounds,
  failed to satisfy the World predicate (neither `.alive/` nor the
  legacy `01_Archive/` + `02_Life/` pair).
- The env fallback path does not satisfy the predicate either.

### Example

```json
{
  "error": "NO_WORLD",
  "message": "No ALIVE World could be located. Set ALIVE_WORLD_ROOT in the server environment, or widen the client's Roots to include a directory that contains '.alive/' or both '01_Archive/' and '02_Life/'.",
  "suggestions": [
    "Set the ALIVE_WORLD_ROOT environment variable to the World root.",
    "Configure the MCP client's Roots to include the World directory.",
    "Verify the World directory contains '.alive/' or the legacy '01_Archive/' + '02_Life/' pair."
  ]
}
```

### Recovery

1. Set `ALIVE_WORLD_ROOT` to the absolute path of the World root
   (the directory containing `.alive/`).
2. Or configure the MCP client to expose that directory as a Root. In
   Claude Desktop: the `workingDir` of the server spawn defaults to a
   sandbox — the server walks upward within that sandbox only, so the
   sandbox must already be inside a World for discovery to work.
3. If neither is feasible, check that the World directory still has its
   `.alive/` marker (or, for legacy Worlds, both `01_Archive/` and
   `02_Life/`).

---

## ERR_WALNUT_NOT_FOUND

**Wire code:** `WALNUT_NOT_FOUND`
**Seam:** Walnut-tool layer (T6) — `get_walnut_state`,
`read_walnut_kernel`, `list_bundles`, `search_walnut`, `read_log`,
`list_tasks`.
**Exception:** `WalnutNotFoundError`

### Cause

The `walnut` argument does not resolve to a directory with a `_kernel/`
inside, within the configured World root. Typical causes:

- Walnut was renamed, moved, or archived.
- Caller passed a bare name (`nova-station`) instead of the POSIX path
  (`04_Ventures/nova-station`) returned by `list_walnuts`.
- Typo in the path.

### Example

```json
{
  "error": "WALNUT_NOT_FOUND",
  "message": "No walnut found at 'nova-station' in this World.",
  "suggestions": [
    "Call 'list_walnuts' to see available walnuts in this World.",
    "Walnut paths are POSIX-relative from the World root (e.g. '04_Ventures/nova-station'), not bare names."
  ]
}
```

### Recovery

1. Call `list_walnuts` to get the canonical POSIX-relative paths.
2. Pass the returned `path` field verbatim in subsequent calls. The
   `name` field is display-only and can collide across domains.

---

## ERR_BUNDLE_NOT_FOUND

**Wire code:** `BUNDLE_NOT_FOUND`
**Seam:** Bundle-tool layer (T7) — `get_bundle`, `read_bundle_manifest`,
`list_tasks` (when `bundle` argument is present).
**Exception:** `BundleNotFoundError`

### Cause

The walnut exists, but the `bundle` argument does not resolve to a
directory with a `context.manifest.yaml` inside the walnut's `bundles/`
directory. Typical causes:

- Bundle graduated (moved from `bundles/` to walnut root) and the path
  the caller remembers is stale.
- Caller passed a bare name instead of the POSIX path returned by
  `list_bundles`.

### Example

```json
{
  "error": "BUNDLE_NOT_FOUND",
  "message": "No bundle found at 'shielding-review' in walnut 'nova-station'.",
  "suggestions": [
    "Call 'list_bundles' with the walnut path to see available bundles.",
    "Bundle paths are relative to the walnut root (e.g. 'bundles/shielding-review')."
  ]
}
```

### Recovery

1. Call `list_bundles` with the walnut path.
2. Use the returned `path` field verbatim. Graduated bundles are
   NOT returned by `list_bundles` — they live at the walnut root as
   historical records. If the caller needs a graduated bundle's
   artifacts, `read_walnut_kernel` and `search_walnut` are the right
   tools.

---

## ERR_KERNEL_FILE_MISSING

**Wire code:** `KERNEL_FILE_MISSING`
**Seam:** Walnut-tool layer (T6) — `read_walnut_kernel`,
`get_walnut_state`; log-tool layer (T9) — `read_log`.
**Exception:** `KernelFileMissingError`

### Cause

The walnut exists but the specific kernel file requested has not been
written to disk. Fresh walnuts legitimately lack these files — a new
walnut has no `log.md` until its first save, no `now.json` until its
first projection, no `insights.md` until its first confirmed insight.

This is DISTINCT from `KernelFileError` (re-exported from
`_vendor._pure`), which fires when a kernel file IS on disk but
unreadable (encoding error, post-`isfile` TOCTOU I/O failure). Missing-
on-disk is a tool-level precondition; corrupt-on-disk is a vendor
layer I/O error surfaced as `ERR_PERMISSION_DENIED` or a 500-class
tool failure depending on the cause.

### Example

```json
{
  "error": "KERNEL_FILE_MISSING",
  "message": "The 'log' kernel file has not been written for walnut 'nova-station'.",
  "suggestions": [
    "Fresh walnuts legitimately lack some kernel files. If the walnut is active, it has not been saved yet.",
    "Valid 'file' values: 'key', 'log', 'insights', 'now'."
  ]
}
```

### Recovery

1. If the walnut is expected to have been worked on, check whether the
   save protocol actually ran — `log.md` is only written at save.
2. `now.json` has a canonical resolution order (`_kernel/now.json`
   first, then `_kernel/_generated/now.json`); both missing is a
   legitimate `KERNEL_FILE_MISSING`.
3. Valid `file` values for `read_walnut_kernel` are `key`, `log`,
   `insights`, `now` (literal, no extension, no path).

---

## ERR_PERMISSION_DENIED

**Wire code:** `PERMISSION_DENIED`
**Seam:** Any tool that opens a kernel or bundle file.
**Exception:** `PermissionDeniedError`

### Cause

The OS denied read access to a walnut or bundle file. On POSIX this is
`EACCES`; on Windows it is an access-denied error. Typical causes:

- MCP server running under a different user than the one that owns
  the walnut files.
- ACLs on a specific subdirectory (`.alive/_mcp/` is server-owned, so
  if the user ran the server once as root and once as themselves, the
  audit log directory may be unreadable).
- Container/sandbox mount with read-only or uid-mismatched layers.

### Example

```json
{
  "error": "PERMISSION_DENIED",
  "message": "Permission denied reading 'log' in walnut 'nova-station'.",
  "suggestions": [
    "Check filesystem permissions on the walnut directory.",
    "Ensure the MCP server process has read access to the World root."
  ]
}
```

### Recovery

1. Identify the failing path via the audit log (which records hashed
   arg values + the tool name — enough to narrow to the walnut).
2. Fix permissions (`chmod`, ACL) so the server process UID can read
   the file. alive-mcp never attempts to change filesystem permissions
   itself.

---

## ERR_PATH_ESCAPE

**Wire code:** `PATH_ESCAPE`
**Seam:** `alive_mcp.paths` — every tool and resource that maps a
caller-provided path fragment to a real filesystem location.
**Exception:** `PathEscapeError`

### Cause

A caller-provided path, after symlink resolution, would read outside
the authorized World root. Fires on:

- `..` traversal (`walnut-a/../../etc/passwd`).
- Absolute paths replacing the root (`safe_join(root, "/etc/passwd")`).
- Symlinks whose target is outside the World.
- Windows: `commonpath` raising `ValueError` because the candidate and
  the root live on different drives (treated as not-contained).

This is the CVE-2025-53109 detection boundary. The check uses
`os.path.commonpath` on realpath'd paths — NOT `startswith`, which
would incorrectly accept `<root>_sibling` as a child of `<root>`.

### Example

```json
{
  "error": "PATH_ESCAPE",
  "message": "The requested path is outside the authorized World root and was rejected.",
  "suggestions": [
    "Paths must resolve inside the authorized World root after symlink resolution.",
    "Use POSIX-relative paths returned by 'list_walnuts' and 'list_bundles' verbatim; do not construct absolute paths."
  ]
}
```

### Recovery

1. Never construct paths manually. Use the `path` field returned by
   `list_walnuts` and `list_bundles` verbatim.
2. If a legitimate symlink inside the World is being rejected, verify
   that its target is also inside the World — symlinks are allowed
   but only if both ends stay contained.

---

## ERR_INVALID_CURSOR

**Wire code:** `INVALID_CURSOR`
**Seam:** Search / list tools with pagination — `list_walnuts`,
`search_world`, `search_walnut`.
**Exception:** `InvalidCursorError`

### Cause

The caller passed a `cursor` argument that did not come from a prior
response of the same tool. Causes:

- Cursor was malformed (tampered, truncated, base64-mangled).
- Cursor is from a different tool (cursors are tool-specific).
- Cursor is stale because the server restarted (cursors do not
  survive process restarts in v0.1 — they are in-memory only).
- Cursor is stale because the underlying index changed (a walnut was
  added or removed) and the offset it encodes no longer makes sense.

### Example

```json
{
  "error": "INVALID_CURSOR",
  "message": "The pagination cursor is invalid or has expired.",
  "suggestions": [
    "Drop the 'cursor' argument and retry from the first page.",
    "Cursors do not survive server restarts."
  ]
}
```

### Recovery

1. Drop the `cursor` argument and re-issue the call from the first
   page.
2. If the paginated data is time-sensitive, accept that a full re-walk
   is necessary when cursor validation fails — v0.1 does not offer a
   "recover cursor" API.

---

## ERR_TOOL_TIMEOUT

**Wire code:** `TOOL_TIMEOUT`
**Seam:** FastMCP shell (T5) — every tool is wrapped in an
`asyncio.wait_for`.
**Exception:** `ToolTimeoutError`

### Cause

The tool invocation exceeded its per-call deadline. Search tools have
the longest default window; `list_*` and `get_*` tools have tighter
windows. Typical causes:

- `search_world` with a query that matches huge swathes of content
  and a large `limit`.
- Filesystem under load (network mount, overloaded SSD).
- A walnut with extremely large kernel files (multi-megabyte
  `log.md`), triggering slow tokenization in search.

### Example

```json
{
  "error": "TOOL_TIMEOUT",
  "message": "Tool 'search_world' exceeded its 5.0s deadline.",
  "suggestions": [
    "Narrow the query to reduce the search space.",
    "Use cursor pagination (smaller 'limit') to stay under the deadline."
  ]
}
```

### Recovery

1. Narrow the query (more specific terms, shorter strings).
2. Lower `limit` and use cursor pagination across multiple calls.
3. For `read_log` on very large logs, use `offset` + `limit` to page
   through entries rather than reading the whole file.

---

## ERR_AUDIT_DISK_FULL

**Wire code:** `AUDIT_DISK_FULL`
**Seam:** Async audit writer (T12).
**Exception:** `AuditDiskFullError`

### Cause

The audit writer could not append to `<world>/.alive/_mcp/audit.log`.
On POSIX this is `ENOSPC`; on Windows it is a disk-full error. This
fires AFTER the tool call itself has typically succeeded — the envelope
surfaces the audit failure so the caller knows the record did not land
on disk.

alive-mcp v0.1 treats this as a hard failure. The audit log is a
safety requirement (every invocation recorded), not a nice-to-have; a
server that cannot audit should not be serving.

### Example

```json
{
  "error": "AUDIT_DISK_FULL",
  "message": "The audit log could not be written (disk full or permissions). Tool results are not being recorded.",
  "suggestions": [
    "Free disk space on the filesystem holding '.alive/_mcp/'.",
    "Rotate or archive existing audit logs if retention is not needed."
  ]
}
```

### Recovery

1. Free disk space on the filesystem that holds `.alive/_mcp/`.
2. Manually rotate `audit.log` if the default 10MB × 10 retention is
   not sufficient for the hosting environment.
3. If audit is not desired at all in a given environment, the server
   should not be run there in v0.1 — there is no "disable audit" flag.

---

## Adding new codes

The codebook is intentionally frozen at 9 for v0.1. Adding a new code
means:

1. Append a constant to `errors.py` and to `ERROR_CODES`.
2. Add a template entry to `MESSAGES` and a suggestions entry to
   `SUGGESTIONS`. The test suite asserts coverage across the frozen
   set.
3. Add a matching `AliveMcpError` subclass.
4. Add a section to this document with cause + example + recovery.
5. Verify no absolute filesystem path appears in the template.

The 9 codes cover the known v0.1 failure modes. A 10th code is a
signal that the envelope contract is growing — prefer that over
reusing an existing code for a new cause.
