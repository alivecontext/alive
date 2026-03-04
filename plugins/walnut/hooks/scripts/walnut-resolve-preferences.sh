#!/bin/bash
# Shared preference resolver — sourced by session hooks.
# Parses preferences.yaml into resolved ON/OFF directives for toggle keys.
# Non-toggle sections (voice, context_sources) are left for LLM interpretation.
# Usage: source this file, then call resolve_preferences "$WORLD_ROOT"

resolve_preferences() {
  local world_root="$1"
  local prefs_file="$world_root/.home/preferences.yaml"

  # Fallback to .claude/ location (pre-migration)
  if [ ! -f "$prefs_file" ]; then
    prefs_file="$world_root/.claude/preferences.yaml"
  fi

  # Defaults — all ON
  local spark="ON" show_reads="ON" health_nudges="ON"
  local stash_checkpoint="ON" always_watching="ON" save_prompt="ON"

  if [ -f "$prefs_file" ]; then
    while IFS= read -r line; do
      # Skip comments and empty lines
      [[ "$line" =~ ^[[:space:]]*# ]] && continue
      [[ -z "$line" ]] && continue

      # Extract key and value (only flat key: value lines)
      local key value
      key=$(echo "$line" | cut -d: -f1 | tr -d ' ')
      value=$(echo "$line" | cut -d: -f2- | tr -d ' ' | tr '[:upper:]' '[:lower:]')

      case "$key" in
        spark)             [[ "$value" == "false" || "$value" == "off" ]] && spark="OFF" ;;
        show_reads)        [[ "$value" == "false" || "$value" == "off" ]] && show_reads="OFF" ;;
        health_nudges)     [[ "$value" == "false" || "$value" == "off" ]] && health_nudges="OFF" ;;
        stash_checkpoint)  [[ "$value" == "false" || "$value" == "off" ]] && stash_checkpoint="OFF" ;;
        always_watching)   [[ "$value" == "false" || "$value" == "off" ]] && always_watching="OFF" ;;
        save_prompt)       [[ "$value" == "false" || "$value" == "off" ]] && save_prompt="OFF" ;;
      esac
    done < "$prefs_file"
  fi

  cat << PREFS
Active Preferences:
  spark: $spark — show The Spark observation at walnut open
  show_reads: $show_reads — show ▸ read indicators when loading files
  health_nudges: $health_nudges — surface stale walnut warnings proactively
  stash_checkpoint: $stash_checkpoint — shadow-write stash to squirrel YAML periodically
  always_watching: $always_watching — background instincts for people, working fits, capturable content
  save_prompt: $save_prompt — ask before saving
PREFS
}
