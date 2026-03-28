#!/bin/bash
# Hook: Rules Guardian — PreToolUse (Edit|Write)
# Blocks edits to plugin-managed files in .walnut/, .claude/, and plugin cache.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/walnut-common.sh"

read_hook_input
find_world || exit 0

FILE_PATH=$(json_field "tool_input.file_path")

[ -z "$FILE_PATH" ] && exit 0

# Always allow: user overrides, preferences, world key, walnut-level config
case "$FILE_PATH" in
  */overrides.md|*/user-overrides.md|*/preferences.yaml|*/_core/config.yaml|*/config.yaml)
    exit 0
    ;;
esac

# Allow: .walnut/key.md (user's file — identity, not plugin-managed)
if [ "$FILE_PATH" = "$WORLD_ROOT/.walnut/key.md" ]; then
  exit 0
fi

DENY_MSG='{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"This file is managed by the Walnut plugin and will be overwritten on update. Put your customizations in .walnut/overrides.md instead."}}'

# Block: plugin-managed rules in .walnut/rules/
case "$FILE_PATH" in
  "$WORLD_ROOT/.walnut/rules/"*)
    BASENAME=$(basename "$FILE_PATH")
    case "$BASENAME" in
      voice.md|squirrels.md|human.md|world.md|capsules.md|standards.md)
        echo "$DENY_MSG"
        exit 0
        ;;
    esac
    ;;
esac

# Block: .walnut/agents.md (plugin-managed runtime instructions)
if [ "$FILE_PATH" = "$WORLD_ROOT/.walnut/agents.md" ]; then
  echo "$DENY_MSG"
  exit 0
fi

# Block: .claude/CLAUDE.md (symlink to .walnut/agents.md)
if [ "$FILE_PATH" = "$WORLD_ROOT/.claude/CLAUDE.md" ]; then
  echo "$DENY_MSG"
  exit 0
fi

# Block: .claude/rules/ files (symlinked to .walnut/rules/)
case "$FILE_PATH" in
  "$WORLD_ROOT/.claude/rules/"*)
    BASENAME=$(basename "$FILE_PATH")
    case "$BASENAME" in
      voice.md|squirrels.md|human.md|world.md|capsules.md|standards.md)
        echo "$DENY_MSG"
        exit 0
        ;;
    esac
    ;;
esac

# Block: anything in the Walnut plugin cache
case "$FILE_PATH" in
  */.claude/plugins/cache/stackwalnuts/walnut/*)
    echo "$DENY_MSG"
    exit 0
    ;;
esac

exit 0
