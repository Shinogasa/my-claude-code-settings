#!/usr/bin/env python3
"""hooks/guard-secret-read.py の振る舞いを検証する。

フックの契約 (stdin に JSON、exit 0=許可 / 2=ブロック) をそのまま叩く。
HOME を一時ディレクトリへ差し替え、本物のホームにあるファイルには触れない。

実行: python3 -m unittest tests.test_guard_secret_read
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "hooks" / "guard-secret-read.py"

ALLOW = 0
BLOCK = 2


class GuardSecretReadBase(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="secret-guard-home-")
        repo = tempfile.TemporaryDirectory(prefix="secret-guard-repo-")
        self.addCleanup(home.cleanup)
        self.addCleanup(repo.cleanup)
        # macOS の /var は /private/var への symlink なので、実体のパスにそろえる
        self.home = Path(os.path.realpath(home.name))
        self.repo = Path(os.path.realpath(repo.name))

    def make_file(self, path, mode=0o600, text="VALUE"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(mode)
        return path

    def run_hook(self, tool_name, tool_input, cwd=None):
        payload = {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(cwd or self.repo)}
        return self.run_raw(json.dumps(payload))

    def run_raw(self, stdin):
        env = {**os.environ, "HOME": str(self.home)}
        return subprocess.run([sys.executable, str(GUARD)], input=stdin, capture_output=True, text=True,
                              cwd=str(self.repo), env=env)

    def assert_exit(self, result, expected):
        self.assertEqual(result.returncode, expected, f"stdout={result.stdout!r} stderr={result.stderr!r}")
        if expected == BLOCK:
            # python3 はファイルが無くても exit 2 になる。フック自身が止めたことを文言で確かめる
            self.assertIn("ブロック", result.stderr)


class ReadAndGrepTests(GuardSecretReadBase):
    def test_owner_only_file_in_config_blocked(self):
        token = self.make_file(self.home / ".config" / "app" / "token")
        result = self.run_hook("Read", {"file_path": str(token)})
        self.assert_exit(result, BLOCK)
        self.assertIn(str(token), result.stderr)
        self.assertIn("show-config-structure", result.stderr)

    def test_world_readable_config_file_allowed(self):
        config = self.make_file(self.home / ".config" / "starship.toml", mode=0o644)
        self.assert_exit(self.run_hook("Read", {"file_path": str(config)}), ALLOW)

    def test_owner_only_file_outside_dot_dirs_allowed(self):
        record = self.make_file(self.home / "garage" / "store" / "record.md")
        self.assert_exit(self.run_hook("Read", {"file_path": str(record)}), ALLOW)

    def test_dotfile_at_home_blocked(self):
        zshrc = self.make_file(self.home / ".zshrc.local")
        self.assert_exit(self.run_hook("Read", {"file_path": str(zshrc)}), BLOCK)

    def test_symlink_into_repo_is_allowed(self):
        # ~/.claude/skills はこのリポジトリへの symlink。実体はリポジトリなので止めない
        self.make_file(self.repo / "skills" / "x" / "SKILL.md")
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "skills").symlink_to(self.repo / "skills")
        target = self.home / ".claude" / "skills" / "x" / "SKILL.md"
        self.assert_exit(self.run_hook("Read", {"file_path": str(target)}), ALLOW)

    def test_symlink_to_secret_blocked(self):
        token = self.make_file(self.home / ".config" / "app" / "token")
        link = self.repo / "link"
        link.symlink_to(token)
        self.assert_exit(self.run_hook("Read", {"file_path": str(link)}), BLOCK)

    def test_state_dir_is_exempt(self):
        diff = self.make_file(self.home / ".claude" / "state" / "jp-doc-review" / "diffs" / "a.diff")
        self.assert_exit(self.run_hook("Read", {"file_path": str(diff)}), ALLOW)

    def test_grep_directory_in_range_blocked(self):
        self.make_file(self.home / ".config" / "app" / "token")
        result = self.run_hook("Grep", {"pattern": "KEY", "path": str(self.home / ".config")})
        self.assert_exit(result, BLOCK)

    def test_grep_repo_allowed(self):
        self.make_file(self.repo / "a.txt")
        self.assert_exit(self.run_hook("Grep", {"pattern": "KEY", "path": str(self.repo)}), ALLOW)

    def test_missing_file_in_range_blocked(self):
        # stat できないので判定できない。対象範囲に見えるので止める
        missing = self.home / ".config" / "none"
        self.assert_exit(self.run_hook("Read", {"file_path": str(missing)}), BLOCK)

    def test_internal_error_in_range_blocks(self):
        # tool_input の型が想定外で解析が例外になっても、対象範囲のパスが見えるなら止める
        payload = json.dumps({"tool_name": "Read", "tool_input": [str(self.home / ".config" / "x")], "cwd": "/"})
        self.assert_exit(self.run_raw(payload), BLOCK)

    def test_other_tools_pass(self):
        token = self.make_file(self.home / ".config" / "app" / "token")
        self.assert_exit(self.run_hook("Edit", {"file_path": str(token)}), ALLOW)


if __name__ == "__main__":
    unittest.main()
