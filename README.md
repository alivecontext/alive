<p align="center">
  <img src="alive-hero.png" alt="ALIVE Context System — a living context system for Claude Code" width="100%">
</p>

<p align="center">
  <a href="https://github.com/stackwalnuts/alive-context/stargazers"><img src="https://img.shields.io/github/stars/stackwalnuts/alive-context?style=flat&color=F97316&label=Stars" alt="GitHub Stars"></a>
  <a href="https://github.com/stackwalnuts/alive-context/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
  <a href="https://walnut.world"><img src="https://img.shields.io/badge/walnut.world-marketplace-brightgreen" alt="walnut.world"></a>
  <a href="https://x.com/stackwalnuts"><img src="https://img.shields.io/badge/𝕏-@stackwalnuts-000000?logo=x&logoColor=white" alt="@stackwalnuts"></a>
</p>

<h3 align="center">A living context system for Claude Code.<br>The successor to PARA. Your life in walnuts.</h3>

<p align="center">
  <sub>Agents are ephemeral. Models are temporary. Context is permanent.<br>There was PARA. Now there's the ALIVE Context System.</sub>
</p>

---

```bash
claude plugin install alive@stackwalnuts
```

---

<p align="center">
  <img src="alive-demo.png" alt="ALIVE Context System in action — stash catching decisions, loading project context" width="700">
</p>

---

## Why

You've had those AI sessions where every word is on point. Where the output changes the scope of your project entirely, writes the copy perfectly, or smashes the architecture. You get out exactly what you wanted — or sometimes so much more.

That's what good context does. And when that happens, you need a log of the decisions and tasks that led to it. Where it came from. Where it's going.

Your world of context can't be condensed into one monolithic `MEMORY.md`. Each meaningful thing in your life — your startup, your people, your side project — has goals that don't change often, tasks that change every day, a history of decisions that compounds, and domain knowledge you uncover slowly over time. These files move at different speeds. They need their own space.

That's why we built the ALIVE Context System.

---

## Two Units

The system has exactly two units.

### 🌰 Walnut — unit of context

Each meaningful thing in your life gets a **walnut** — your startup, your people, your health, your experiment.

A walnut has a **kernel** — three source-of-truth files that move at different speeds:

```
my-startup/
  _kernel/
    key.md       → What it is (identity, people, links — rarely changes)
    log.md       → Where it's been (prepend-only, immutable decisions)
    insights.md  → What it knows (evergreen domain knowledge)
    _generated/
      now.json   → Current state (generated on save, never hand-written)
  bundles/
    website-rebuild/
      context.manifest.yaml
      tasks.md
      raw/
```

The inside of a walnut is shaped like a brain. The kernel is the living system. Everything else grows around it.

### 📦 Bundle — unit of work

Bundles are how work gets done inside a walnut. Each bundle has a specific **outcome** and owns its own tasks.

```yaml
# context.manifest.yaml
name: website-rebuild
outcome: "Ship hypha.nz from strategy deck to production"
species: outcome        # outcome | evergreen
phase: prototype        # draft | prototype | published | done
sensitivity: private    # open | private | restricted
tasks_total: 12
tasks_done: 7
```

Bundles are **shareable** — scrub the PII, post to [walnut.world](https://walnut.world), and your workflow becomes a context product anyone can install. Skills as phases. Tasks as the plan. Raw context as the knowledge. All of it propagated by YOUR context when someone pulls it into their world.

Two species: **outcome bundles** ship and graduate. **Evergreen bundles** accumulate forever (emails, meeting notes, research).

---

## The ALIVE Framework

Five folders. The file system IS the methodology.

```
People/           → Outside the framework — people first
01_Archive/       → A — Everything that was
02_Life/          → L — Personal foundation
03_Inputs/        → I — Buffer only — arrives, gets routed out
04_Ventures/      → V — Revenue intent
05_Experiments/   → E — Testing grounds
```

People sit outside the ALIVE acronym because they cross-cut everything. They're not a life goal — they're entities that connect your entire world.

---

## What Happens

1. **Your agent reads your project state before responding.** Not guessing from a flat memory file — reading the kernel. Identity, current state, recent decisions, active bundle. The brief pack loads in seconds.

2. **Decisions get caught mid-conversation.** The stash runs silently. When you say "let's go with React Native for the mobile app" — that's a decision. It gets tagged, routed to the right walnut, and logged at the next save.

3. **Next session picks up exactly where you left off.** No re-explaining. No context debt. Your agent knows your project, your people, your last decision, and what needs doing next.

---

## The Squirrel

Your named context companion. Set in preferences:

```yaml
squirrel_name: Toby
```

Every session is Toby. Same identity, persistent relationship. Context operations show up as bordered blocks:

```
╭─ 🐿️ Toby +2 stash (5)
│   React Native for mobile app → my-startup
│   Chase Jake for API specs → my-startup
│   → drop?
╰─
```

Toby reads your context before speaking, catches decisions mid-conversation, surfaces connections you'd miss, and logs everything at save. The squirrel is an additive persona layer — your agent keeps its own voice, Toby adds the context awareness.

---

## Projections

Generated on save. Agents read the lightest tier first.

| Tier | File | What it gives you |
|------|------|-------------------|
| 0 | `world-index.json` | One line per walnut — the whole world at a glance |
| 1 | `now.json` | Active bundle, task counts, health — one walnut's state |
| 2 | `context.manifest.yaml` | Full bundle manifest — the work details |
| 3 | `raw/*` | Actual source material — on demand only |

A save triggers the generation chain: bundle manifests → `now.json` → `world-index.json` → `subagent-brief.md`. Every spawned subagent gets the brief — oriented to the runtime automatically.

---

## Install

```bash
claude plugin install alive@stackwalnuts
```

That's it. The ALIVE Context System is a Claude Code plugin. 15 skills, 14 hooks, 6 rule files, templates, and a statusline.

### Skills

| Skill | What it does |
|-------|-------------|
| `/alive:world` | See your world — dashboard, health, routing |
| `/alive:load-context` | Load a walnut — brief pack, people, active bundle |
| `/alive:save` | Checkpoint — route stash, generate projections |
| `/alive:capture-context` | Context in — store, route to bundles |
| `/alive:bundle` | Create, share, graduate bundles |
| `/alive:search-world` | Search across walnuts, bundles, people, logs |
| `/alive:create-walnut` | Scaffold a new walnut |
| `/alive:system-cleanup` | Maintenance — stale bundles, orphan files |
| `/alive:settings` | Customise preferences, permissions, voice |
| `/alive:session-history` | Squirrel activity, session timeline |
| `/alive:mine-for-context` | Deep context extraction from source material |
| `/alive:build-extensions` | Create skills, rules, hooks for your world |
| `/alive:my-context-graph` | Render the world graph |
| `/alive:session-context-rebuild` | Rebuild context from past sessions |
| `/alive:system-upgrade` | Upgrade from any previous version |

### Upgrading from walnut v1

```bash
# Install the new plugin
claude plugin install alive@stackwalnuts

# Run the upgrade
/alive:system-upgrade
```

The upgrade skill mines your existing system, shows you what will change, and migrates everything: `.walnut/` → `.alive/`, `_core/` → `_kernel/`, capsules → bundles. Your old `walnut` plugin keeps working — nothing breaks.

---

## What People Are Saying

<table>
<tr>
<td width="50%" valign="top">
<br>
<p align="center"><em>"most cracked thing I've seen for AI in 2025."</em></p>
<p align="center"><strong><a href="https://linkedin.com/in/louka-ewington-pitsos-2a92b21a0">Louka Ewington-Pitsos</a></strong><br><sub>AI Researcher · Parsewave</sub></p>
</td>
<td width="50%" valign="top">
<br>
<p align="center"><em>"two AI systems, one context layer."</em></p>
<p align="center"><strong><a href="https://x.com/witcheer">witcheer ☯︎</a></strong> · <a href="https://t.me/witcheergrimoire"><sub>Telegram</sub></a><br><sub>Hermes integration pioneer</sub></p>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<br>
<p align="center"><em>"You're gonna smoke everyone with this."</em></p>
<p align="center"><strong>Athon Millane</strong><br><sub>AI Researcher · VC-backed · SF</sub></p>
</td>
<td width="50%" valign="top">
<br>
<p align="center"><em>"context quality > context quantity."</em></p>
<p align="center"><strong><a href="https://x.com/mawensx">Marcus</a></strong><br><sub><a href="https://x.com/mawensx/status/2036050610420650243">original tweet</a></sub></p>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<br>
<p align="center"><em>"best thing ive ever used. this is fucked."</em></p>
<p align="center"><strong><a href="https://instagram.com/caspartremlett">Caspar Tremlett</a></strong><br><sub>Brand Business Coach · Bali/Australia</sub></p>
</td>
<td width="50%" valign="top">
<br>
<p align="center"><em>"Bro. Walnuts is legendary."</em></p>
<p align="center"><strong><a href="https://instagram.com/roland.bernath.official">Roland Bernath</a></strong><br><sub>Growth Strategist · 6K followers</sub></p>
</td>
</tr>
</table>

---

## Context as Property

Your context lives on your machine as plain files. Switch models — Claude to GPT to local — your walnuts come with you. Switch platforms — your walnuts are yours.

Git-track your world locally for version history. Push to a remote if you want backup. Or don't. No cloud dependency. No vendor lock-in. Your context is your property.

---

## The Research Lab

Stack Walnuts is a research lab exploring the future of human productivity, creativity, and entrepreneurship. We believe we are entering the renaissance. Entrepreneurship is open to everyone now.

The ALIVE Context System is our first product. We're not saying markdown is the best format. We're finding out what the best is. Every decision in this system is backed by research — from [Anthropic's persona selection model](https://www.anthropic.com/research/persona-selection-model) to [context engineering principles](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). No holds barred.

[walnut.world](https://walnut.world) is where you share what you build — bundles, skills, workflows, entire methodologies. Context products for the distributed internet.

---

## Contributing

Want to build with us? [Open an issue](https://github.com/stackwalnuts/alive-context/issues), join the conversation in [Discussions](https://github.com/stackwalnuts/alive-context/discussions), or check the [contributing guide](CONTRIBUTING.md).

---

<p align="center">
  <br>
  <a href="https://alivecontext.com"><img src="https://img.shields.io/badge/🐿️_Alive_Context_System-alivecontext.com-F97316?style=for-the-badge&labelColor=0a0a0a" alt="ALIVE Context System"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/stackwalnuts/alive-context"><img src="https://img.shields.io/github/stars/stackwalnuts/alive-context?style=for-the-badge&logo=github&labelColor=0a0a0a&color=F97316" alt="Star on GitHub"></a>
  &nbsp;&nbsp;
  <a href="https://x.com/stackwalnuts"><img src="https://img.shields.io/badge/𝕏-@stackwalnuts-F97316?style=for-the-badge&logo=x&logoColor=white&labelColor=0a0a0a" alt="Follow @stackwalnuts"></a>
  <br><br>
</p>

<p align="center">
  Built by <a href="https://alivecontext.com">Stack Walnuts</a> · <a href="https://x.com/benslockedin">@benslockedin</a> · MIT License
</p>
