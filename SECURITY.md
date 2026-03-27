# Security Policy

## What Walnut Touches

Walnut is a Claude Code plugin that operates on **local files only**. All context lives on your machine in plain markdown with YAML frontmatter. The plugin does not:

- Phone home to any server
- Send telemetry or analytics
- Store data outside your local file system
- Access network resources without explicit MCP tool confirmation

## What the Hooks Guarantee

The plugin ships 12 hooks that enforce security guarantees mechanically — not by trusting the agent to follow rules, but by blocking violations before they execute.

| Hook | Guarantee |
|------|-----------|
| **log-guardian** | Signed log entries are immutable. No agent can edit or delete historical entries. |
| **rules-guardian** | Plugin-managed system files cannot be modified by the agent. Prevents the runtime from rewriting its own rules. |
| **archive-enforcer** | `rm` and `rmdir` commands are blocked inside the walnut world. You archive, you don't destroy. |
| **external-guard** | Any MCP tool that writes, sends, creates, or deletes in external systems (email, GitHub, APIs) requires explicit user confirmation before executing. |

## Data Handling

- **No secrets in files.** API keys, tokens, and credentials belong in environment variables. If the agent notices a key in a walnut file, it flags it immediately.
- **PII awareness.** Capsule companions track `sensitivity:` and `pii:` fields in frontmatter. The system is designed to make you conscious of what's in your files.
- **Local-first sync.** If you sync via iCloud, Dropbox, or similar, that's your choice and your cloud. The plugin has no opinion about sync — it reads and writes to the path you give it.

## Reporting a Vulnerability

If you find a security issue in the plugin — hooks that can be bypassed, rules that can be circumvented, or any behavior that violates the guarantees above — please report it:

- **Email:** hello@walnut.world
- **GitHub:** Open a [security advisory](https://github.com/stackwalnuts/walnut/security/advisories/new)

We take these seriously. The entire system is built on the premise that structural guardrails are more reliable than agent compliance.

## Scope

This policy covers the Walnut plugin (`plugins/walnut/`). It does not cover:

- The AI model running the plugin (Claude, GPT, etc.)
- The Claude Code CLI itself
- Your local file system permissions
- Third-party MCP servers you may have configured

## Philosophy

Context is property. The security model reflects this — your files never leave your machine through the plugin, the agent can't destroy what it shouldn't, and external actions require your explicit confirmation. Every hook exists because an agent without that guardrail did something it shouldn't have.
