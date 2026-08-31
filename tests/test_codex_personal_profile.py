#!/usr/bin/env python3
"""Codex 個人プロファイルの生成と `bin/cxp` のガードを検証する。

この機構が守っているのは「個人セッションが会社の MCP サーバを引き継がないこと」。
失敗は静かに起きる（エラーも通知も出ず、会社の鍵で外部へ出る通信が正常系として通る）ため、
壊れても実行結果からは気づけない。ここで検査する。

実行: python3 tests/test_codex_personal_profile.py
"""
import importlib.util
import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "bin" / "generate-codex-personal-profile.py"
CXP = REPO_ROOT / "bin" / "cxp"
ALLOWLIST = REPO_ROOT / "codex" / "personal-mcp-allowlist.txt"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_profile", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.gen = load_generator()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def generate(self, config_text: str, allowlist_text: str) -> dict:
        config = self.dir / "config.toml"
        allowlist = self.dir / "allowlist.txt"
        dest = self.dir / "personal.config.toml"
        config.write_text(config_text, encoding="utf-8")
        allowlist.write_text(allowlist_text, encoding="utf-8")

        exit_code = self.gen.main([str(config), str(allowlist), str(dest)])
        self.assertEqual(exit_code, 0)
        with dest.open("rb") as f:
            return tomllib.load(f)

    def test_switches_provider_to_personal_account(self):
        result = self.generate('model_provider = "llm_gateway"\n', "")
        self.assertEqual(result["model_provider"], "openai")

    def test_server_absent_from_allowlist_is_disabled(self):
        # 既定は deny。会社のゲートウェイ上のサーバが個人セッションへ漏れない。
        result = self.generate(
            '[mcp_servers.company_search]\nurl = "https://example.invalid/x"\n', ""
        )
        self.assertFalse(result["mcp_servers"]["company_search"]["enabled"])

    def test_server_in_allowlist_is_enabled(self):
        result = self.generate(
            '[mcp_servers.local_tool]\ncommand = "/bin/true"\n', "local_tool\n"
        )
        self.assertTrue(result["mcp_servers"]["local_tool"]["enabled"])

    def test_every_server_is_listed_explicitly(self):
        # 許可済みを省略すると、cxp の未反映検査が「許可して省いた」と
        # 「そもそも反映していない」を区別できなくなる。
        result = self.generate(
            '[mcp_servers.allowed]\ncommand = "/bin/true"\n'
            '[mcp_servers.denied]\ncommand = "/bin/true"\n',
            "allowed\n",
        )
        self.assertEqual(set(result["mcp_servers"]), {"allowed", "denied"})

    def test_allowlist_ignores_comments_and_blank_lines(self):
        result = self.generate(
            '[mcp_servers.local_tool]\ncommand = "/bin/true"\n',
            "# コメント\n\n  local_tool  \n",
        )
        self.assertTrue(result["mcp_servers"]["local_tool"]["enabled"])

    def test_hyphenated_server_name_survives_round_trip(self):
        # ハイフンを含む名前をクォートせずに書くと TOML として読み直せない。
        result = self.generate('[mcp_servers."atlassian-http"]\nurl = "x"\n', "")
        self.assertIn("atlassian-http", result["mcp_servers"])

    def test_missing_config_still_produces_usable_profile(self):
        # Codex 導入直後で config.toml が無いマシンでも provider 切り替えは要る。
        dest = self.dir / "out.toml"
        allowlist = self.dir / "allowlist.txt"
        allowlist.write_text("", encoding="utf-8")
        self.gen.main([str(self.dir / "absent.toml"), str(allowlist), str(dest)])
        with dest.open("rb") as f:
            self.assertEqual(tomllib.load(f)["model_provider"], "openai")


class TestRepoAllowlist(unittest.TestCase):
    def test_allowlist_is_parseable_and_not_empty_of_comments(self):
        gen = load_generator()
        allowed = gen.read_allowlist(ALLOWLIST)
        self.assertNotIn("", allowed)
        for name in allowed:
            self.assertFalse(name.startswith("#"), f"コメントが混入している: {name}")


class TestCxpGuard(unittest.TestCase):
    """`cxp` は codex を起動する前に停止できることを検査する。

    codex は `-p` に存在しないプロファイル名を渡してもエラーにせず base 設定で起動する。
    その無言のフォールバックを `cxp` が塞いでいるかどうかがここの争点。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        # 本物の codex を起動しないよう、PATH の先頭にスタブを置く。
        # 起動まで到達したことは、スタブが残す痕跡で判定する。
        self.bindir = self.dir / "bin"
        self.bindir.mkdir()
        self.marker = self.dir / "codex-was-launched"
        stub = self.bindir / "codex"
        stub.write_text(f'#!/bin/bash\ntouch "{self.marker}"\n', encoding="utf-8")
        stub.chmod(0o755)

        self.codex_home = self.dir / "codex-home"
        self.codex_home.mkdir()

    def run_cxp(self) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["CODEX_HOME"] = str(self.codex_home)
        env["PATH"] = f"{self.bindir}{os.pathsep}{env['PATH']}"
        return subprocess.run(
            [str(CXP)], env=env, capture_output=True, text=True, timeout=30
        )

    def write_config(self, text: str):
        (self.codex_home / "config.toml").write_text(text, encoding="utf-8")

    def write_profile(self, text: str):
        (self.codex_home / "personal.config.toml").write_text(text, encoding="utf-8")

    def test_missing_profile_stops_before_launching_codex(self):
        self.write_config('model_provider = "llm_gateway"\n')
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_server_added_after_generation_stops_before_launching_codex(self):
        self.write_config(
            '[mcp_servers.known]\nurl = "x"\n[mcp_servers.added_later]\nurl = "y"\n'
        )
        self.write_profile('[mcp_servers."known"]\nenabled = false\n')
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("added_later", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_fully_covered_profile_launches_codex(self):
        self.write_config('[mcp_servers.known]\nurl = "x"\n')
        self.write_profile(
            'model_provider = "openai"\n[mcp_servers."known"]\nenabled = false\n'
        )
        result = self.run_cxp()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists(), "codex が起動しなかった")

    def test_config_without_mcp_servers_launches_codex(self):
        self.write_config('model_provider = "llm_gateway"\n')
        self.write_profile('model_provider = "openai"\n')
        result = self.run_cxp()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
