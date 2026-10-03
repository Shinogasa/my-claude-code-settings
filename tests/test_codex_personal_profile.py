#!/usr/bin/env python3
"""Codex 個人プロファイルの生成と `bin/cxp` のガードを検証する。

この機構が守っているのは「個人セッションが会社の MCP サーバを引き継がないこと」。
失敗は静かに起きる（エラーも通知も出ず、会社の鍵で外部へ出る通信が正常系として通る）ため、
壊れても実行結果からは気づけない。ここで検査する。

実行: python3 tests/test_codex_personal_profile.py
"""
import contextlib
import importlib.util
import io
import os
import shutil
import stat
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

    def test_http_server_copies_only_url_and_enabled(self):
        # profile 単体の設定検証に必要な transport だけを複写する。
        result = self.generate(
            '[mcp_servers.remote_tool]\n'
            'url = "https://example.invalid/mcp"\n'
            'http_headers = { Authorization = "not-copied" }\n'
            'bearer_token_env_var = "REMOTE_TOKEN"\n',
            "",
        )
        self.assertEqual(
            result["mcp_servers"]["remote_tool"],
            {
                "url": "https://example.invalid/mcp",
                "enabled": False,
            },
        )

    def test_server_in_allowlist_is_enabled(self):
        result = self.generate(
            '[mcp_servers.local_tool]\ncommand = "/bin/true"\n', "local_tool\n"
        )
        self.assertTrue(result["mcp_servers"]["local_tool"]["enabled"])

    def test_stdio_server_copies_only_command_and_enabled(self):
        result = self.generate(
            '[mcp_servers.local_tool]\n'
            'command = "/usr/bin/env"\n'
            'args = ["python3", "server.py"]\n'
            'env = { TOKEN = "not-copied" }\n',
            "local_tool\n",
        )
        self.assertEqual(
            result["mcp_servers"]["local_tool"],
            {
                "command": "/usr/bin/env",
                "enabled": True,
            },
        )

    def test_server_without_transport_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "command または url"):
            self.gen.render({"broken": {}}, set())

    def test_server_with_two_transports_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "command または url"):
            self.gen.render(
                {
                    "broken": {
                        "command": "/bin/true",
                        "url": "https://example.invalid",
                    }
                },
                set(),
            )

    def test_url_with_unredactable_components_is_rejected(self):
        # profile は URL 全体を transport として複写するため、認証情報を分離できない
        # userinfo / query / fragment を許すと秘密値まで個人側へ持ち出してしまう。
        for url in (
            "https://user:pass@example.invalid/mcp",
            "https://example.invalid/mcp?access_token=secret",
            "https://example.invalid/mcp#credential",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.gen.render({"remote": {"url": url}}, set())

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


class TestExistingProfileOwnership(unittest.TestCase):
    """setup が所有するのは model_provider と mcp_servers だけ。

    Codex は起動中のプロファイルへ設定保存を書き込むため、それ以外のキーを
    再生成で消すと、モデル既定や信頼設定が setup のたびに失われる。
    """

    CODEX_WRITTEN = (
        'model = "gpt-test"\n'
        'model_reasoning_effort = "high"\n'
        "\n"
        "[tui]\n"
        'status_line = ["model", "current-dir"]\n'
        "status_line_use_colors = true\n"
        "\n"
        "[tui.model_availability_nux]\n"
        '"gpt-test" = 4\n'
        "\n"
        '[projects."/work/odd path"]\n'
        'trust_level = "trusted"\n'
        "\n"
        '[plugins."tool@market"]\n'
        "enabled = false\n"
        "\n"
        "[hooks.state]\n"
        "\n"
        '[hooks.state."/flags/config.toml:pre_tool_use:0:0"]\n'
        'trusted_hash = "sha256:abc"\n'
    )

    def setUp(self):
        self.gen = load_generator()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.config = self.dir / "config.toml"
        self.allowlist = self.dir / "allowlist.txt"
        self.existing = self.dir / "personal.config.toml"
        self.dest = self.dir / "staged.toml"
        self.config.write_text(
            '[mcp_servers.local_tool]\ncommand = "/bin/true"\n', encoding="utf-8"
        )
        self.allowlist.write_text("local_tool\n", encoding="utf-8")

    def generate(self) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self.gen.main(
                [str(self.config), str(self.allowlist), str(self.dest), str(self.existing)]
            )

    def test_codex_written_settings_are_preserved(self):
        self.existing.write_text(self.CODEX_WRITTEN, encoding="utf-8")
        self.assertEqual(self.generate(), 0)
        result = tomllib.loads(self.dest.read_text(encoding="utf-8"))
        expected = tomllib.loads(self.CODEX_WRITTEN)
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(result[key], value)
        self.assertEqual(result["model_provider"], "openai")
        self.assertEqual(
            result["mcp_servers"], {"local_tool": {"command": "/bin/true", "enabled": True}}
        )

    def test_owned_keys_in_existing_profile_are_regenerated(self):
        # 所有キーは引き継がない。手で有効にした会社サーバが残ると deny-by-default が崩れる。
        self.existing.write_text(
            'model_provider = "llm_gateway"\n'
            "[mcp_servers.stale_company]\n"
            'url = "https://example.invalid"\n'
            "enabled = true\n",
            encoding="utf-8",
        )
        self.assertEqual(self.generate(), 0)
        result = tomllib.loads(self.dest.read_text(encoding="utf-8"))
        self.assertEqual(result["model_provider"], "openai")
        self.assertEqual(list(result["mcp_servers"]), ["local_tool"])

    def test_connection_redirecting_keys_stop_without_writing(self):
        # 所有キーに触れずに接続先を変えられるキーを引き継ぐと、個人用 provider への切替が崩れうる。
        for text in (
            'openai_base_url = "https://gateway.invalid"\n',
            'chatgpt_base_url = "https://gateway.invalid"\n',
            '[model_providers.openai]\nbase_url = "https://gateway.invalid"\n',
            '[profiles.other]\nmodel_provider = "gateway"\n',
            'profile = "other"\n',
        ):
            with self.subTest(text=text):
                self.existing.write_text(text, encoding="utf-8")
                self.assertNotEqual(self.generate(), 0)
                self.assertFalse(self.dest.exists())

    def test_unparseable_existing_profile_stops_without_writing(self):
        # 読めない既存ファイルを空とみなすと、Codex 側の設定を黙って捨てる。
        self.existing.write_text("model = \n", encoding="utf-8")
        self.assertNotEqual(self.generate(), 0)
        self.assertFalse(self.dest.exists())

    def test_unsupported_existing_value_stops_without_writing(self):
        # 書き出せない型を落とすと、引き継いだつもりで値が消える。
        self.existing.write_text("seen_at = 2026-10-01T00:00:00Z\n", encoding="utf-8")
        self.assertNotEqual(self.generate(), 0)
        self.assertFalse(self.dest.exists())


class TestGeneratedFileHardening(unittest.TestCase):
    """生成物そのものの扱い。いずれも失敗しても静かなので、ここで固定する。"""

    def setUp(self):
        self.gen = load_generator()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def generate(self, config_text: str, allowlist_text: str = "") -> Path:
        config = self.dir / "config.toml"
        allowlist = self.dir / "allowlist.txt"
        dest = self.dir / "personal.config.toml"
        config.write_text(config_text, encoding="utf-8")
        allowlist.write_text(allowlist_text, encoding="utf-8")
        self.gen.main([str(config), str(allowlist), str(dest)])
        return dest

    def test_profile_is_not_world_readable(self):
        # 生成元の config.toml は 600。値は転記しないが、会社の MCP サーバ名は
        # 社内トポロジの情報なので共有マシンで他ユーザーへ見せない。
        dest = self.generate('[mcp_servers.company_tool]\nurl = "https://example.invalid"\n')
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)

    def test_no_temporary_file_is_left_behind(self):
        dest = self.generate('model_provider = "llm_gateway"\n')
        leftovers = [p.name for p in dest.parent.glob("*.tmp")]
        self.assertEqual(leftovers, [])

    def test_preexisting_symlink_at_fixed_temporary_name_is_not_followed(self):
        # 固定名の一時ファイルだと、先に置かれたsymlinkをたどって別のファイルを上書きする。
        victim = self.dir / "victim.txt"
        victim.write_text("original", encoding="utf-8")
        (self.dir / "personal.config.toml.tmp").symlink_to(victim)

        self.generate('model_provider = "llm_gateway"\n')

        self.assertEqual(victim.read_text(encoding="utf-8"), "original")

    def test_quote_in_server_name_survives_round_trip(self):
        # エスケープを忘れると生成物が TOML として壊れる。
        rendered = self.gen.render({'odd"name': {"command": "/bin/true"}}, set())
        self.assertEqual(list(tomllib.loads(rendered)["mcp_servers"]), ['odd"name'])

    def test_backslash_in_server_name_survives_round_trip(self):
        rendered = self.gen.render({"odd\\name": {"command": "/bin/true"}}, set())
        self.assertEqual(list(tomllib.loads(rendered)["mcp_servers"]), ["odd\\name"])

    def test_transport_value_survives_round_trip(self):
        rendered = self.gen.render(
            {"local_tool": {"command": 'say "hello"\\next'}},
            set(),
        )
        server = tomllib.loads(rendered)["mcp_servers"]["local_tool"]
        self.assertEqual(server["command"], 'say "hello"\\next')

    def test_unicode_transport_value_survives_round_trip(self):
        rendered = self.gen.render(
            {"local_tool": {"command": "/tmp/工具-🛠️"}},
            set(),
        )
        server = tomllib.loads(rendered)["mcp_servers"]["local_tool"]
        self.assertEqual(server["command"], "/tmp/工具-🛠️")

    def test_allowlisted_network_facing_server_is_reported(self):
        # 許可リストは人間が書く。会社のリモートサーバを足しても生成は成功するため、
        # 判断した本人の目に入る位置で言う必要がある。
        config = self.dir / "config.toml"
        allowlist = self.dir / "allowlist.txt"
        dest = self.dir / "out.toml"
        config.write_text(
            '[mcp_servers.remote_tool]\nurl = "https://example.invalid"\n', encoding="utf-8"
        )
        allowlist.write_text("remote_tool\n", encoding="utf-8")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            self.gen.main([str(config), str(allowlist), str(dest)])
        self.assertIn("remote_tool", stderr.getvalue())

    def test_allowlisted_local_server_is_not_reported(self):
        config = self.dir / "config.toml"
        allowlist = self.dir / "allowlist.txt"
        dest = self.dir / "out.toml"
        config.write_text('[mcp_servers.local_tool]\ncommand = "/bin/true"\n', encoding="utf-8")
        allowlist.write_text("local_tool\n", encoding="utf-8")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            self.gen.main([str(config), str(allowlist), str(dest)])
        self.assertEqual(stderr.getvalue(), "")


class TestRepoAllowlist(unittest.TestCase):
    def test_allowlist_is_parseable_and_not_empty_of_comments(self):
        gen = load_generator()
        allowed = gen.read_allowlist(ALLOWLIST)
        self.assertNotIn("", allowed)
        for name in allowed:
            self.assertFalse(name.startswith("#"), f"コメントが混入している: {name}")

    def test_allowlist_has_no_network_facing_entry_on_this_machine(self):
        # このマシンの config.toml に対して、許可済みサーバが外部接続を持たないこと。
        # config.toml が無いマシン（CI 等）ではスキップする。
        gen = load_generator()
        config = Path.home() / ".codex" / "config.toml"
        if not config.exists():
            self.skipTest("~/.codex/config.toml が無い")
        servers = gen.read_mcp_servers(config)
        allowed = gen.read_allowlist(ALLOWLIST)
        exposed = [n for n in allowed if n in servers and gen.is_network_facing(servers[n])]
        self.assertEqual(exposed, [], f"外部接続を持つサーバが許可されている: {exposed}")


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
        self.write_profile('[mcp_servers."known"]\nurl = "x"\nenabled = false\n')
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("added_later", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_server_removed_after_generation_stops_before_launching_codex(self):
        self.write_config('model_provider = "llm_gateway"\n')
        self.write_profile(
            '[mcp_servers.removed]\ncommand = "/bin/true"\nenabled = true\n'
        )
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("removed", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_transport_changed_after_generation_stops_before_launching_codex(self):
        self.write_config(
            '[mcp_servers.known]\nurl = "https://example.invalid/new"\n'
        )
        self.write_profile(
            '[mcp_servers.known]\n'
            'url = "https://example.invalid/old"\n'
            'enabled = false\n'
        )
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("known", result.stderr)
        self.assertIn("transport", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_profile_without_transport_stops_before_launching_codex(self):
        self.write_config('[mcp_servers.known]\nurl = "https://example.invalid/new"\n')
        self.write_profile('[mcp_servers.known]\nenabled = false\n')
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("known", result.stderr)
        self.assertIn("transport", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_profile_without_boolean_enabled_stops_before_launching_codex(self):
        self.write_config('[mcp_servers.known]\ncommand = "/bin/true"\n')
        self.write_profile(
            '[mcp_servers.known]\ncommand = "/bin/true"\nenabled = "false"\n'
        )
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("known", result.stderr)
        self.assertIn("enabled", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_profile_with_extra_mcp_keys_stops_before_launching_codex(self):
        # generator 以外から追記された秘密・実行パラメータも実行時に拒否する。
        cases = (
            (
                '[mcp_servers.known]\nurl = "https://example.invalid/mcp"\n',
                'http_headers = { Authorization = "secret" }\n',
            ),
            (
                '[mcp_servers.known]\ncommand = "/bin/true"\n',
                'env = { TOKEN = "secret" }\n',
            ),
            (
                '[mcp_servers.known]\ncommand = "/bin/true"\n',
                'args = ["--token", "secret"]\n',
            ),
        )
        for base, extra in cases:
            with self.subTest(extra=extra):
                self.write_config(base)
                self.write_profile(base + "enabled = false\n" + extra)
                result = self.run_cxp()
                self.assertEqual(result.returncode, 1)
                self.assertIn("known", result.stderr)
                self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_url_with_unredactable_components_stops_before_launching_codex(self):
        for url in (
            "https://user:pass@example.invalid/mcp",
            "https://example.invalid/mcp?access_token=secret",
            "https://example.invalid/mcp#credential",
        ):
            with self.subTest(url=url):
                definition = f'[mcp_servers.known]\nurl = "{url}"\nenabled = false\n'
                self.write_config(definition)
                self.write_profile(definition)
                result = self.run_cxp()
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_fully_covered_profile_launches_codex(self):
        self.write_config('[mcp_servers.known]\nurl = "x"\n')
        self.write_profile(
            'model_provider = "openai"\n'
            '[mcp_servers."known"]\nurl = "x"\nenabled = false\n'
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


class TestCxpArgumentGuard(TestCxpGuard):
    """照合をすり抜ける引数（別プロファイル、MCP サーバの上書き）を起動前に拒否する。"""

    def run_cxp_with(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["CODEX_HOME"] = str(self.codex_home)
        env["PATH"] = f"{self.bindir}{os.pathsep}{env['PATH']}"
        return subprocess.run(
            [str(CXP), *args], env=env, capture_output=True, text=True, timeout=30
        )

    def write_valid_profile(self):
        self.write_config('model_provider = "llm_gateway"\n')
        self.write_profile('model_provider = "openai"\n')

    def test_profile_and_mcp_override_arguments_stop_before_launching_codex(self):
        self.write_valid_profile()
        cases = (
            ("-p", "other"),
            ("--profile", "other"),
            ("--profile=other",),
            ("-pother",),
            ("-c", "mcp_servers.company_tool.enabled=true"),
            ("--config", 'mcp_servers.x.command="/bin/sh"'),
            ("--config=mcp_servers.x.enabled=true",),
            ("-cmcp_servers.x.enabled=true",),
        )
        for args in cases:
            with self.subTest(args=args):
                result = self.run_cxp_with(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn("cxp", result.stderr)
                self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_unrelated_config_and_prompt_are_passed_through(self):
        self.write_valid_profile()
        result = self.run_cxp_with("-c", "model_reasoning_effort=high", "-p は使わない")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists(), "codex が起動しなかった")

    def test_arguments_after_double_dash_are_not_inspected(self):
        self.write_valid_profile()
        result = self.run_cxp_with("exec", "--", "-p other という文字列")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists(), "codex が起動しなかった")

class TestCxpAllowlistGuard(TestCxpGuard):
    """手で `enabled = true` に書き換えた allowlist 外のサーバを、起動前に止める。

    setup の所有判定で気づけるのは次回の setup 実行時だけなので、cxp 自身が照合する。
    cxp は ~/.codex/bin などの symlink 経由で起動されるため、symlink の先にある
    リポジトリの allowlist を読むことも確かめる。
    """

    def setUp(self):
        super().setUp()
        repo = self.dir / "repo"
        (repo / "bin").mkdir(parents=True)
        (repo / "codex").mkdir()
        shutil.copy2(CXP, repo / "bin" / "cxp")
        self.allowlist = repo / "codex" / "personal-mcp-allowlist.txt"
        self.allowlist.write_text("# コメント\nallowed\n", encoding="utf-8")
        linked_bin = self.dir / "linked-bin"
        linked_bin.symlink_to(repo / "bin")
        self.cxp = linked_bin / "cxp"

    def run_cxp(self) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["CODEX_HOME"] = str(self.codex_home)
        env["PATH"] = f"{self.bindir}{os.pathsep}{env['PATH']}"
        return subprocess.run(
            [str(self.cxp)], env=env, capture_output=True, text=True, timeout=30
        )

    def write_server(self, name: str, enabled: bool):
        definition = f'[mcp_servers.{name}]\ncommand = "/bin/true"\n'
        self.write_config(definition)
        self.write_profile(definition + f"enabled = {str(enabled).lower()}\n")

    def test_enabled_server_outside_allowlist_stops_before_launching_codex(self):
        self.write_server("company_tool", enabled=True)
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("company_tool", result.stderr)
        self.assertIn("allowlist", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_enabled_server_in_allowlist_launches_codex(self):
        self.write_server("allowed", enabled=True)
        result = self.run_cxp()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists(), "codex が起動しなかった")

    def test_disabled_server_outside_allowlist_launches_codex(self):
        self.write_server("company_tool", enabled=False)
        result = self.run_cxp()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists(), "codex が起動しなかった")

    def test_missing_allowlist_stops_before_launching_codex(self):
        # allowlist を読めないときは「全部許可」ではなく停止に倒す。
        self.allowlist.unlink()
        self.write_server("allowed", enabled=True)
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("allowlist", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_undecodable_allowlist_stops_with_guidance(self):
        self.allowlist.write_bytes(b"\xff\xfe allowed\n")
        self.write_server("allowed", enabled=True)
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("allowlist", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")

    def test_broken_profile_toml_stops_with_guidance(self):
        self.write_config('[mcp_servers.allowed]\ncommand = "/bin/true"\n')
        self.write_profile("[mcp_servers.allowed\n")
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("setup.sh", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.marker.exists(), "codex が起動してしまった")


if __name__ == "__main__":
    unittest.main(verbosity=2)
