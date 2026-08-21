#!/usr/bin/env python3
"""Codex plugin policyの読み取り専用監査。"""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _require_non_empty_string(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _validate_policy(policy_doc: object) -> tuple[dict, list[str]]:
    if not isinstance(policy_doc, dict):
        raise ValueError("policy must be an object")
    if policy_doc.get("schemaVersion") != 1:
        raise ValueError("policy schemaVersion must be 1")
    default_deny = policy_doc.get("defaultDenyMarketplaces")
    if not isinstance(default_deny, list):
        raise ValueError("defaultDenyMarketplaces must be a list")
    for marketplace in default_deny:
        _require_non_empty_string(marketplace, "defaultDenyMarketplaces entry")
    plugins = policy_doc.get("plugins")
    if not isinstance(plugins, dict):
        raise ValueError("plugins must be an object")
    for plugin_id, entry in plugins.items():
        _require_non_empty_string(plugin_id, "plugin id")
        if not isinstance(entry, dict):
            raise ValueError(f"plugin {plugin_id} entry must be an object")
        if entry.get("status") not in {"allow", "review", "deny"}:
            raise ValueError(f"plugin {plugin_id} status is invalid")
        _require_non_empty_string(entry.get("reason"), f"plugin {plugin_id} reason")
    return plugins, default_deny


def _validate_installed(installed: object) -> None:
    if not isinstance(installed, list):
        raise ValueError("installed must be a list")
    for entry in installed:
        if not isinstance(entry, dict):
            raise ValueError("installed entry must be an object")
        _require_non_empty_string(entry.get("pluginId"), "pluginId")
        _require_non_empty_string(entry.get("marketplaceName"), "marketplaceName")
        if not isinstance(entry.get("enabled"), bool):
            raise ValueError("enabled must be a boolean")


def find_violations(policy_doc: dict, installed: list[dict]) -> list[str]:
    """有効なinstalled pluginのうち、policyに違反するIDを返す。"""
    plugins, default_deny = _validate_policy(policy_doc)
    _validate_installed(installed)
    default_deny = set(default_deny)
    violations = set()

    for entry in installed:
        plugin_id = entry.get("pluginId")
        if not entry["enabled"]:
            continue

        policy_entry = plugins.get(plugin_id)
        if policy_entry and policy_entry["status"] != "allow":
            violations.add(plugin_id)
        elif not policy_entry and entry["marketplaceName"] in default_deny:
            violations.add(plugin_id)

    return sorted(violations)


def load_installed(command: list[str] | None = None) -> list[dict]:
    """Codex CLIからinstalled plugin一覧を取得する。"""
    if command is None:
        command = ["codex", "plugin", "list", "--json"]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    try:
        document = json.loads(result.stdout)
    except ValueError:
        raise ValueError("Codex plugin list returned invalid JSON") from None
    if not isinstance(document, dict):
        raise ValueError("Codex plugin list JSON must be an object")
    installed = document.get("installed")
    if not isinstance(installed, list):
        raise ValueError("Codex plugin list JSON installed must be a list")
    return installed


def main() -> int:
    """policyと現在のinstalled一覧を監査する。"""
    policy_path = ROOT / "codex" / "plugin-policy.json"
    try:
        with policy_path.open(encoding="utf-8") as policy_file:
            policy_doc = json.load(policy_file)
        violations = find_violations(policy_doc, load_installed())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Codex plugin audit failed: {error}", file=sys.stderr)
        return 2
    if violations:
        for plugin_id in violations:
            print(plugin_id)
        return 1

    print("Codex plugin policy violations: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
