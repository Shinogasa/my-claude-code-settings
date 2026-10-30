#!/usr/bin/env python3
"""secret 読み取りガードの配線と、permissions.deny の追加を検証する。

フックは Claude Code にだけ登録し、Codex（codex/hooks.json）には登録しない。
deny は、2026-10-29に値が漏れたファイルを含み、名前のパターンは ~/.config 配下に限る。

実行: python3 -m unittest tests.test_guard_secret_read_wiring
"""
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((REPO_ROOT / "settings.json.template").read_text(encoding="utf-8"))
CODEX_HOOKS = (REPO_ROOT / "codex" / "hooks.json").read_text(encoding="utf-8")
DENY = SETTINGS["permissions"]["deny"]
NAME_PATTERN_MARKERS = ("*token*", "*secret*", "*credential*", "*.pem", "*.key")


class GuardSecretReadWiringTests(unittest.TestCase):
    def test_registered_for_read_grep_bash(self):
        groups = [g for g in SETTINGS["hooks"]["PreToolUse"] if g.get("matcher") == "Read|Grep|Bash"]
        commands = [h["command"] for g in groups for h in g["hooks"]]
        self.assertTrue(any("~/.claude/hooks/guard-secret-read.py" in c for c in commands), commands)

    def test_not_registered_for_codex(self):
        self.assertNotIn("guard-secret-read", CODEX_HOOKS)

    def test_deny_covers_leaked_files(self):
        for rule in ("Read(~/.zshrc.local)", "Read(~/.codex/config.toml)", "Read(~/.claude/settings.json)"):
            self.assertIn(rule, DENY)

    def test_deny_name_patterns_scoped_to_config(self):
        patterns = [r for r in DENY if any(m in r for m in NAME_PATTERN_MARKERS)]
        self.assertGreaterEqual(len(patterns), len(NAME_PATTERN_MARKERS))
        for rule in patterns:
            self.assertTrue(rule.startswith("Read(~/.config/"), rule)


if __name__ == "__main__":
    unittest.main()
