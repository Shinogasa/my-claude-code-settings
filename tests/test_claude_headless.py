#!/usr/bin/env python3
"""bin/claude-headless が、目印の環境変数で個人プロファイルの --settings を付け分けることを検証する。

実行: python3 -m unittest tests.test_claude_headless
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "claude-headless"


class ClaudeHeadlessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.personal = self.home / ".claude" / "settings.personal.json"
        self.personal.write_text('{"env": {}}', encoding="utf-8")
        bindir = self.base / "bin"
        bindir.mkdir()
        self.log = self.base / "claude-args.log"
        stub = bindir / "claude"
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CLAUDE_ARGS_LOG"\n', encoding="utf-8")
        stub.chmod(0o755)
        self.path = f"{bindir}{os.pathsep}{os.environ['PATH']}"

    def run_script(self, profile=None, *args):
        env = {**os.environ, "HOME": str(self.home), "PATH": self.path, "CLAUDE_ARGS_LOG": str(self.log)}
        env.pop("CLAUDE_PROFILE", None)
        if profile is not None:
            env["CLAUDE_PROFILE"] = profile
        return subprocess.run([str(SCRIPT), *args], env=env, capture_output=True, text=True)

    def args(self):
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_personal_profile_adds_personal_settings(self):
        result = self.run_script("personal", "-p", "hello")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.args(), ["--settings", str(self.personal), "-p", "hello"])

    def test_without_marker_runs_with_default_settings(self):
        result = self.run_script(None, "-p", "hello")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.args(), ["-p", "hello"])

    def test_personal_profile_without_settings_file_stops(self):
        # 個人のつもりで会社の接続情報に繋がる無言の事故を避ける
        self.personal.unlink()
        result = self.run_script("personal", "-p", "hello")
        self.assertEqual(result.returncode, 1)
        self.assertIn("settings.personal.json", result.stderr)
        self.assertFalse(self.log.exists())

    def test_unknown_marker_stops(self):
        result = self.run_script("typo", "-p", "hello")
        self.assertEqual(result.returncode, 1)
        self.assertIn("CLAUDE_PROFILE", result.stderr)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
