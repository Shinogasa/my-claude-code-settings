#!/usr/bin/env python3
"""bin/show-config-structure が、許可したキー以外の値を出さないことを検証する。

secret を含む設定ファイルの構造だけを AI に見せる読み口なので、値が漏れないことを固定する。
値の形（secret らしいかどうか）で判断しないことも確かめる。

実行: python3 -m unittest tests.test_show_config_structure
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "bin" / "show-config-structure"


class ShowConfigStructureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="show-config-")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write_text(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, data):
        return self.write_text("settings.json", json.dumps(data))

    def run_tool(self, path):
        return subprocess.run([sys.executable, str(TOOL), str(path)], capture_output=True, text=True)

    def test_plain_value_under_unknown_key_masked(self):
        # 値の形が secret らしくなくても、許可していないキーは伏せる
        out = self.run_tool(self.write_json({"env": {"FOO": "hello"}}))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("env.FOO: str = <伏せた>", out.stdout)
        self.assertNotIn("hello", out.stdout)

    def test_allowed_key_value_shown(self):
        out = self.run_tool(self.write_json({"model": "opus", "permissions": {"deny": ["Read(~/.ssh/**)"]}}))
        self.assertIn("model: str = opus", out.stdout)
        self.assertIn("permissions.deny[0]: str = Read(~/.ssh/**)", out.stdout)

    def test_hooks_masked(self):
        out = self.run_tool(self.write_json({"hooks": {"PreToolUse": [{"hooks": [{"command": "curl -H tok123"}]}]}}))
        self.assertIn("hooks.PreToolUse[0].hooks[0].command: str = <伏せた>", out.stdout)
        self.assertNotIn("tok123", out.stdout)

    def test_toml_supported(self):
        out = self.run_tool(self.write_text("x.toml", 'model = "gpt"\n[auth]\ntoken = "abc"\n'))
        self.assertIn("model: str = gpt", out.stdout)
        self.assertIn("auth.token: str = <伏せた>", out.stdout)
        self.assertNotIn("abc", out.stdout)

    def test_line_mode_shows_key_names_only(self):
        out = self.run_tool(self.write_text(".zshrc.local", "export API_TOKEN=abc123\n# comment xyz\n"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("行1: API_TOKEN = <伏せた>", out.stdout)
        self.assertIn("行2: <伏せた>", out.stdout)
        self.assertNotIn("abc123", out.stdout)
        self.assertNotIn("xyz", out.stdout)

    def test_unparsable_file_prints_nothing(self):
        out = self.run_tool(self.write_text("bad.json", "SECRET_RAW_VALUE"))
        self.assertEqual(out.returncode, 1)
        self.assertNotIn("SECRET_RAW_VALUE", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
