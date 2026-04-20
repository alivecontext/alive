---
name: alive:end-session
description: "Explicitly close the current session. Routes any unsaved stash, sets ended: timestamp, writes a closing log entry. Use when the human says they're done — 'done', 'wrapping up', 'that's it for now', 'end session'. Prevents ghost squirrels that accumulate with ended: null."
user-invocable: true
---

# End

Close this session cleanly. Route unsaved stash, stamp the exit, move on.

Not a save (that's `alive:save` — checkpoints mid-session, keeps the session open). End is final. The squirrel closes its entry, signs off, and the session is done.

---

## Why This Exists

Sessions that end by closing the terminal, disconnecting, or just walking away never get their squirrel entry closed. The `ended:` field stays `null` forever. Over time these ghost squirrels accumulate — polluting session history, confusing cleanup, and making the fallback patterns in hooks pick up wrong sessions.

This skill gives the human a clean exit. One command, session closed properly.

---

## Flow

### Step 1 — Check Session State

Read the current squirrel entry at `.alive/_squirrels/{session_id}.yaml`.

If no entry exists, there's nothing to close:

```
╭─ 🐿️ no active session to close.
╰─
```

Exit.

### Step 2 — Check for Unsaved Stash

Read the `stash:` field from the squirrel YAML. Also check the in-conversation stash — items may have been collected but not yet written to the YAML.

**If stash has unrouted items (saves: 0 or new items since last save):**

```
╭─ 🐿️ you have unsaved stash items
│
│  Decisions:
│  - [decision items]
│
│  Tasks:
│  - [task items]
│
│  Notes:
│  - [note items]
│
│  ▸ save and close / drop and close / cancel
╰─
```

- **save and close** — invoke the `alive:save` flow first (route stash, write log, update projections), then continue to Step 3
- **drop and close** — skip stash routing, continue to Step 3. The stash stays in the YAML as a historical record but is not routed to walnut files.
- **cancel** — abort. Session stays open.

**If no unsaved stash (empty stash or saves > 0 with no new items):**

Skip straight to Step 3.

### Step 3 — Write Closing Log Entry

If a walnut is active (`walnut:` field is not null), prepend a closing entry to `_kernel/log.md`:

```markdown
## {timestamp} — squirrel:{session_id}

Session closed.

signed: squirrel:{session_id}
```

If the session had meaningful work (saves > 0), the log entry should be minimal — the save entries already captured the substance. Don't repeat what's already logged.

If no walnut is active, skip the log entry.

### Step 4 — Close the Squirrel Entry

Update `.alive/_squirrels/{session_id}.yaml`:

- Set `ended:` to current ISO timestamp
- Set `transcript:` if not already set — check for JSONL at `~/.claude/projects/*/` matching the session ID

### Step 5 — Confirm

```
╭─ 🐿️ session closed
│
│  squirrel:{short_id} — {walnut or "no walnut"} — {saves} saves
│  ended: {timestamp}
╰─
```

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| No squirrel entry exists | Print "no active session" and exit |
| Squirrel already has `ended:` set | Print "session already closed" and exit |
| Walnut is null (never loaded) | Close squirrel without log entry |
| Save flow fails mid-close | Still set `ended:` — partial close is better than ghost |
| Human says "cancel" at stash prompt | Abort entirely, session stays open |

---

## Files Read

| File | Why |
|------|-----|
| `.alive/_squirrels/{session_id}.yaml` | Current session state |
| `_kernel/log.md` | Prepend closing entry (if walnut active) |

## Files Written

| File | What |
|------|------|
| `.alive/_squirrels/{session_id}.yaml` | Set `ended:`, update `transcript:` |
| `_kernel/log.md` | Closing log entry (if walnut active) |
