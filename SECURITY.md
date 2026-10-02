# Security Policy

## What the ALIVE Context System Touches

The ALIVE Context System is a Claude Code plugin that operates on **local files only**. All context lives on your machine in plain markdown with YAML frontmatter. The plugin does not:

- Phone home to any server
- Send telemetry or analytics
- Store data outside your local file system
- Access network resources without explicit user confirmation

## What the Hooks Guarantee

The plugin ships 14 hooks that enforce security guarantees mechanically -- not by trusting the agent to follow rules, but by blocking violations before they execute.

| Hook | Guarantee |
|------|-----------|
| **log-guardian** | Signed log entries are immutable. No agent can edit or delete historical entries. |
| **rules-guardian** | Plugin-managed system files cannot be modified by the agent. Prevents the runtime from rewriting its own rules. |
| **archive-enforcer** | `rm` and `rmdir` commands are blocked inside the world. You archive, you don't destroy. |
| **root-guardian** | Prevents orphan files at the world root. Everything goes in a walnut. |

## Data Handling

- **No secrets in files.** API keys, tokens, and credentials belong in environment variables.
- **Sensitivity levels.** Bundles and walnuts track `sensitivity:` in their manifests (open/private/restricted). Restricted content is never pushed to remote and agents must confirm before accessing.
- **Local-first.** If you sync via iCloud, Dropbox, or git, that's your choice. The plugin reads and writes to the path you give it.

## Reporting a Vulnerability

If you find a security issue -- hooks that can be bypassed, rules that can be circumvented, or any behavior that violates the guarantees above:

- **Email:** hello@alivecontext.com
- **GitHub:** Open a [security advisory](https://github.com/alivecontext/alive/security/advisories/new)

## Scope

This policy covers the ALIVE Context System plugin (`plugins/alive/`). It does not cover the AI model, the Claude Code CLI, your file system permissions, or third-party MCP servers.

## Philosophy

Context is property. Your files never leave your machine through the plugin, the agent can't destroy what it shouldn't, and external actions require your explicit confirmation.
