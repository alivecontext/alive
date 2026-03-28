---
name: alive:build-extensions
description: "Create new skills, rules, and hooks for your world. Checks plugin compatibility, writes to the human's space (not plugin cache), validates against the system, and suggests when repeated work should become a skill. For marketplace-ready plugins, hands off to the contributor plugin."
user-invocable: true
---

# Extend

Build custom capabilities that integrate cleanly with the ALIVE Context System.

Not about adjusting preferences or voice (that's `alive:settings`). Extend is about creating NEW things — skills, rules, hooks — that make the system do something it couldn't before.

---

## What It Builds

| Type | What it is | Where it lives |
|------|-----------|---------------|
| **Skill** | Repeatable workflow with instructions | `.alive/skills/{skill-name}/SKILL.md` |
| **Rule** | Behavioral constraint or guide | `.alive/rules/{rule-name}.md` |
| **Hook** | Automated trigger on system events | `.alive/hooks/` (scripts + hooks.json) |
| **Plugin** | Distributable package of skills + rules + hooks | Hands off to `contributor@stackwalnuts` |

---

## Flow

### 1. Understand What the Human Wants

"I want to automatically tag emails by walnut"
"Every time I save, it should update my project board"
"I keep doing this manually every session — can we automate it?"

The squirrel determines: is this a skill (process), a rule (constraint), a hook (automation), or a combination?

```
╭─ squirrel that sounds like a hook — an automated trigger that fires on save.
│  Want me to build it?
│
│  It would:
│  - Fire after every alive:save
│  - Read the routed stash items
│  - Update your project board via API
│
│  > Build it / Tell me more / Not now
╰─
```

### 2. Check Compatibility

Before writing anything:
- Read the current plugin version from `plugin.json`
- Check which hook events are available (SessionStart, PreToolUse, PostToolUse, PreCompact, UserPromptSubmit)
- Verify the name doesn't collide with existing skills, rules, or hooks
- Check for rule contradictions with existing rules

### 3. Write to the Human's Space

**NEVER write to the plugin cache.** Plugin cache (`~/.claude/plugins/`) gets overwritten on update. Custom capabilities live in the human's own space:

- Custom skills: `.alive/skills/{skill-name}/SKILL.md`
- Custom rules: `.alive/rules/{rule-name}.md`
- Custom hooks: `.alive/hooks/` (scripts + `.claude/hooks.json` additions)

These persist across plugin updates. They're the human's own.

### 3.5. Symlink for Discovery

Claude Code only discovers skills in `~/.claude/skills/`. After writing a custom skill to `.alive/skills/`, **always create the symlink**:

```bash
mkdir -p ~/.claude/skills/{skill-name}
ln -sf .alive/skills/{skill-name}/SKILL.md ~/.claude/skills/{skill-name}/SKILL.md
```

The session-new hook auto-syncs these on every startup, but creating the symlink immediately means the skill is available in the current session without restart.

**This is mandatory.** A skill without its symlink is invisible to Claude Code.

### 4. Validate

After writing:
- Test the skill/rule/hook runs without errors
- Verify it doesn't conflict with existing system behavior
- Confirm it loads on next session start

### 5. Confirm

```
╭─ squirrel built: auto-tag-emails
│
│  Type: hook (PostToolUse)
│  Location: .alive/hooks/auto-tag-emails.sh
│  Fires: after every email capture via alive:capture-context
│  Does: reads email sender, matches against person walnuts, tags accordingly
│
│  Test it now?
╰─
```

---

## Proactive Trigger

The squirrel watches for repeated patterns across sessions. When it spots the human doing the same thing manually:

```
╭─ squirrel spotted
│  You've done this 3 sessions in a row. Should this be a skill?
│
│  > Make it a skill?
│  1. Yeah, let's build it
│  2. Not yet
│  3. What would it look like?
╰─
```

Pattern detection looks for:
- Same sequence of tool calls across sessions
- Similar stash items routing the same way repeatedly
- Manual file operations that could be automated
- Repeated phrases like "I always do X before Y"

---

## Custom Skill Structure

A custom skill follows the same format as core skills:

```
.alive/skills/{skill-name}/
  SKILL.md          # Instructions (same format as plugin skills)
  heavy-revive.md   # Optional sub-docs loaded on demand
  templates/        # Optional templates used by the skill
```

The SKILL.md frontmatter:

```yaml
---
name: {skill-name}
description: "What this skill does — one sentence"
user-invocable: true
---
```

### Custom Rule Structure

```markdown
---
type: rule
name: {rule-name}
version: 1.0
scope: world | walnut:{name} | session
---

# {Rule Name}

[What this rule constrains or guides, when it applies, what behavior it enforces]
```

### Custom Hook Structure

Hook scripts in `.alive/hooks/` with corresponding entries in `.claude/hooks.json`:

```json
{
  "hooks": [
    {
      "type": "PostToolUse",
      "matcher": "Write|Edit",
      "command": ".alive/hooks/my-custom-hook.sh"
    }
  ]
}
```

---

## Marketplace Awareness

When a custom skill is polished and battle-tested:

```
╭─ squirrel this skill could work for other builders
│  Want to package it for the marketplace?
│
│  > Next step?
│  1. Package for marketplace (needs contributor plugin)
│  2. Keep it personal
│  3. Tell me more about the marketplace
╰─
```

**Contributor plugin handoff:** For marketplace packaging, PII stripping, testing, and publishing -> suggest installing `contributor@stackwalnuts`. This is a SEPARATE plugin, not part of the alive core. The extend skill's job ends at building working custom capabilities. The contributor plugin handles everything from packaging to publishing.

```
╭─ squirrel to publish this skill:
│
│  1. Install the contributor plugin:
│     claude plugin install contributor@stackwalnuts
│
│  2. Run: alive:contribute {skill-name}
│     It handles: PII check, packaging, testing, submission
│
│  > Install contributor plugin now?
╰─
```

---

## What Extend Is NOT

- Not `alive:settings` — tune adjusts preferences and config. Extend creates new capabilities.
- Not a code editor — extend builds Alive-native skills/rules/hooks. For general coding, just code.
- Not the marketplace — extend builds. The contributor plugin publishes.

Tune adjusts the dials. Extend adds new dials.
