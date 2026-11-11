# ALIVE x Hermes Agent

Structured context layer for autonomous agents. Five independent layers that compound when used together.

## Architecture

| Layer | Name | Description |
|-------|------|-------------|
| 4 | Runtime Integration | `soul-patch.md` + `agents.md`. Auto-discovered by Hermes. |
| 3 | Cron Templates | 8 background jobs. Observe, present, await approval. |
| 2 | Hermes Skills | 11 ALIVE operations as `/slash` commands. agentskills.io format. |
| 1 | Memory Provider | Smart prefetch, 3 tools. Installs into the Hermes user plugin dir (`~/.hermes/plugins/memory/alive/`). |
| 0 | The World | Walnuts, bundles, `_kernel/`, `.alive/`. The shared filesystem. |

Each layer works independently. A user on Mem0 can use ALIVE skills and crons without the memory provider.

## Quick Start

The installer does all of this, verifies the result, and prints the env contract:

```bash
bash hermes/install.sh
```

### Path A: You already have ALIVE (Claude Code user)

Manual steps, if you prefer them over `install.sh`:

```bash
# 1. Copy memory provider into the Hermes *user plugin dir*
#    (update-safe on every install method; do NOT use the
#    ~/.hermes/hermes-agent/ repo checkout — it only exists on git
#    installs and is never scanned on the others)
mkdir -p ~/.hermes/plugins/memory/alive
cp -r hermes/memory-provider/* ~/.hermes/plugins/memory/alive/

# 2. Add skills to Hermes config
# In ~/.hermes/config.yaml:
# skills:
#   external_dirs:
#     - /path/to/alivecontext/alive/hermes/hermes-skills
#     - /path/to/alivecontext/alive/hermes/cron-templates

# 3. Set the runtime env contract (wherever Hermes starts from)
export ALIVE_WORLD_ROOT=~/world                              # your world
export ALIVE_PLUGIN_ROOT=/path/to/alivecontext/alive/plugins/alive

# 4. Activate memory provider
hermes memory setup   # select "alive"
hermes memory status  # verify: expect "alive" as the active provider
hermes plugins list   # may show "alive" (memory providers can be listed separately)

# 5. Install crons (optional) — dry run first, then apply
bash hermes/setup-crons.sh          # prints the commands
bash hermes/setup-crons.sh --apply  # creates the jobs (deliver: local)

# 6. Append SOUL.md patch
cat hermes/soul-patch.md >> ~/.hermes/SOUL.md

# 7. Copy AGENTS.md to world root
cp hermes/agents.md ~/world/AGENTS.md
```

### Path B: You're new to ALIVE (Hermes user)

```bash
# 1. Install ALIVE
claude plugin install alive@alivecontext

# 2. Then follow Path A above
```

## Directory Structure

```
hermes/
  memory-provider/           <- Layer 1: Hermes memory plugin
    __init__.py              <- MemoryProvider implementation
    plugin.yaml              <- Plugin metadata + hook declarations
    README.md                <- Provider docs

  hermes-skills/             <- Layer 2: 11 interactive skills
    alive-load/SKILL.md      <- Load walnut context
    alive-save/SKILL.md      <- Checkpoint: route stash, write log
    alive-world/SKILL.md     <- World dashboard
    alive-capture/SKILL.md   <- Capture external content
    alive-search/SKILL.md    <- Cross-walnut search
    alive-create/SKILL.md    <- Scaffold new walnut
    alive-bundle/SKILL.md    <- Bundle lifecycle
    alive-daily/SKILL.md     <- Morning operating system
    alive-history/SKILL.md   <- Session history search
    alive-mine/SKILL.md      <- Deep context extraction
    alive-cleanup/SKILL.md   <- System maintenance

  cron-templates/            <- Layer 3: 8 background enrichment jobs
    alive-morning/SKILL.md   <- 7am daily briefing
    alive-project/SKILL.md   <- Every 4h: regenerate projections
    alive-inbox/SKILL.md     <- Every 2h: scan inbox
    alive-health/SKILL.md    <- 9am daily: health check
    alive-stash-router/      <- Every 4h: route pending stash
    alive-mine/SKILL.md      <- 2am nightly: mine transcripts
    alive-prune/SKILL.md     <- 3am Sunday: log/insight pruning
    alive-people/SKILL.md    <- 9am Monday: people check

  agents.md                  <- Layer 4: Squirrel runtime rules
  soul-patch.md              <- Layer 4: 3-line personality patch
  install.sh                 <- Installer: user plugin dir + verification
  setup-crons.sh             <- Emits the 8 cron jobs (dry run; --apply)
  README.md                  <- This file
```

## Links

- [ALIVE Context System](https://github.com/alivecontext/alive)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
