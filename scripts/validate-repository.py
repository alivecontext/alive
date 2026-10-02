#!/usr/bin/env python3
"""Validate ALIVE's public licensing, metadata and supported-surface policy.

v3.2.3 policy: MIT licence retained, Hermes retained as a
community/experimental surface, product versions in agreement, and the
hook permission declaration present.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "3.2.3"


def read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"missing required file: {path.relative_to(ROOT)}")
        return ""


def check_contains(
    path: Path, expected: str, label: str, errors: list[str]
) -> None:
    if expected not in read_text(path, errors):
        errors.append(f"{path.relative_to(ROOT)}: missing {label}")


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        return json.loads(read_text(path, errors))
    except json.JSONDecodeError as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid JSON ({exc})")
        return {}


def main() -> int:
    errors: list[str] = []

    # Licence policy: MIT is retained.
    check_contains(ROOT / "LICENSE", "MIT License", "MIT licence heading", errors)
    check_contains(
        ROOT / "README.md", "license-MIT", "MIT licence badge", errors
    )

    plugin_manifest = load_json(
        ROOT / "plugins" / "alive" / ".claude-plugin" / "plugin.json", errors
    )
    if plugin_manifest.get("license") != "MIT":
        errors.append(
            "plugins/alive/.claude-plugin/plugin.json: license must be MIT"
        )
    if plugin_manifest.get("version") != EXPECTED_VERSION:
        errors.append(
            "plugins/alive/.claude-plugin/plugin.json: "
            f"version must be {EXPECTED_VERSION}"
        )

    marketplace = load_json(ROOT / ".claude-plugin" / "marketplace.json", errors)
    if marketplace.get("metadata", {}).get("version") != EXPECTED_VERSION:
        errors.append(
            f".claude-plugin/marketplace.json: metadata version must be {EXPECTED_VERSION}"
        )
    plugins = marketplace.get("plugins") or [{}]
    if plugins[0].get("version") != EXPECTED_VERSION:
        errors.append(
            f".claude-plugin/marketplace.json: plugin version must be {EXPECTED_VERSION}"
        )

    check_contains(
        ROOT / "walnut.manifest.yaml", 'license: "MIT"', "MIT metadata", errors
    )
    check_contains(
        ROOT / "walnut.manifest.yaml",
        f'version: "{EXPECTED_VERSION}"',
        f"version {EXPECTED_VERSION}",
        errors,
    )
    check_contains(
        ROOT / "README.md",
        f"version-{EXPECTED_VERSION}-",
        f"version {EXPECTED_VERSION} badge",
        errors,
    )

    # Install policy: two-step marketplace registration then install.
    readme = read_text(ROOT / "README.md", errors)
    marketplace_cmd = "claude plugin marketplace add alivecontext/alive"
    install_cmd = "claude plugin install alive@alivecontext"
    if marketplace_cmd not in readme or install_cmd not in readme:
        errors.append("README.md: missing two-step install instructions")
    elif readme.index(marketplace_cmd) > readme.index(install_cmd):
        errors.append(
            "README.md: marketplace registration must precede plugin install"
        )

    # Permission declaration must ship with the release.
    check_contains(
        ROOT / "PERMISSIONS.md",
        "13 command invocations across 5 Claude Code hook event types",
        "hook permission summary",
        errors,
    )

    # Surface policy: Hermes is retained (community/experimental), not deleted.
    if not (ROOT / "hermes").is_dir():
        errors.append("hermes/: community/experimental surface must be retained")

    if errors:
        print("repository policy validation failed:")
        for error in sorted(set(errors)):
            print(f"- {error}")
        return 1

    print("repository policy validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
