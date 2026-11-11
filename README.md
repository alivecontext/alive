<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/hero-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/readme/hero-light.png">
    <img src="docs/readme/hero-light.png" alt="ALIVE research preview. Your world is folders on your own disk." width="100%">
  </picture>
</p>

<p align="center">Claude Code forgets everything when a chat ends. ALIVE gives it a memory that lives in plain folders on your own computer, so every session picks up where the last one left off.</p>

<p align="center"><sub>Research preview · v3.2.6 · MIT · more than 10,000 downloads since February 2026</sub></p>

## Install

You'll need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and Python 3, then it's two commands.

```bash
claude plugin marketplace add alivecontext/alive
claude plugin install alive@alivecontext
```

Open Claude Code in the folder where you want your world to live and run `/alive:world` once, and it sets everything up for you.

After that there's really only one thing to remember, which is `/alive:save`. Run it before the chat fills up or when you finish a good piece of work, and most of the other skills will call themselves when they're needed.

It works on macOS, Linux and Windows (WSL), and everything it reads, writes and runs is listed in [PERMISSIONS.md](PERMISSIONS.md).

<details>
<summary>All the skills</summary>

<br>

| Skill | What it does |
|---|---|
| `/alive:world` | See your world, and set it up the first time |
| `/alive:save` | Save what happened and where things are at |
| `/alive:load-context` | Pick something back up where you left it |
| `/alive:capture-context` | Bring in emails, transcripts and files |
| `/alive:create-walnut` | Start a new project, person or life area |
| `/alive:bundle` | Start, share and finish a piece of work |
| `/alive:search-world` | Search everything in your world |
| `/alive:session-history` | See what happened in past sessions |
| `/alive:session-context-rebuild` | Rebuild context from past sessions |
| `/alive:mine-for-context` | Pull the good stuff out of long sources |
| `/alive:my-context-graph` | Draw your world as a map |
| `/alive:build-extensions` | Make your own skills, rules and hooks |
| `/alive:settings` | Preferences, voice and rhythm |
| `/alive:system-cleanup` | Tidy stale work and stray files |
| `/alive:system-upgrade` | Upgrade from an earlier version |
| `/alive:demo` | Make a sample world to try things on |
| `/alive:feedback` | Report a bug or ask for something |

</details>

<details>
<summary>Upgrading from an older ALIVE</summary>

<br>

```bash
claude plugin install alive@alivecontext
/alive:system-upgrade --dry-run --plan-output /tmp/upgrade-plan.txt
/alive:system-upgrade
```

It works from v1, v2, v3.0, v3.1 and v3.2, shows you the plan first and backs everything up before it changes anything.

</details>

## A note from Ben

Thank you for being early. This repo went up in February and you've downloaded it more than 10,000 times since, and every bug you filed made it better. Version 3.2.6 stays right here under MIT and your world was always yours, so keep using it for as long as it's useful. It's no longer actively maintained because I've been building the new ALIVE engine, which as I've experienced it is basically lossless. It's a foundation for generative interfaces and for working with agents in a new way, and you'll be able to build for it and customise almost all of it.

<br>

<p align="center"><sub>This research preview is MIT, and the new ALIVE will ship open too. <a href="https://alivecontext.com">More info and the waitlist</a>.</sub></p>

<p align="center"><sub><a href="https://discord.gg/mJvDsU9ApN">Discord</a> · <a href="https://x.com/ALIVE_context">@ALIVE_context</a> · <a href="https://x.com/benslockedin">@benslockedin</a> · <a href="mailto:hello@alive.so">hello@alive.so</a> · <a href="https://github.com/alivecontext/alive/stargazers">Star it</a></sub></p>
