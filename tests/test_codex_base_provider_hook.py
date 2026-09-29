#!/usr/bin/env python3
"""hooks/check-codex-base-provider.py の振る舞いを検証する。

フックの契約 (stdin に SessionStart の JSON、stdout は正常時に空・異常時に
systemMessage の JSON) をそのまま叩く。CODEX_HOME を一時ディレクトリへ
差し替え、実際の ~/.codex/config.toml に依存させない。

実行: python3 tests/test_codex_base_provider_hook.py
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "check-codex-base-provider.py"
HOOKS_CONFIG = REPO_ROOT / "codex" / "hooks.json"

CUSTOM_PROVIDER = """
[model_providers.gateway]
name = "gateway"
base_url = "https://gateway.example.com"
"""


def run_hook(codex_home, payload=None):
    env = dict(os.environ)
    env["CODEX_HOME"] = str(codex_home)
    body = {"hook_event_name": "SessionStart", "source": "startup"}
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(body if payload is None else payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return result


class TestBaseProviderHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.config = self.home / "config.toml"

    def tearDown(self):
        self.tmp.cleanup()

    def assert_silent(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def assert_warns(self, result, fragment):
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(set(output), {"systemMessage"})
        self.assertIn(fragment, output["systemMessage"])

    def test_silent_when_defined_custom_provider_is_selected(self):
        self.config.write_text('model_provider = "gateway"\n' + CUSTOM_PROVIDER)
        self.assert_silent(run_hook(self.home))

    def test_warns_when_custom_provider_is_defined_but_not_selected(self):
        # 今回の事故: provider 定義だけ残り、選択キーが消えて既定の openai に倒れた
        self.config.write_text('model_reasoning_effort = "high"\n' + CUSTOM_PROVIDER)
        self.assert_warns(run_hook(self.home), "model_provider")

    def test_warns_when_selected_provider_is_not_a_defined_custom_provider(self):
        self.config.write_text('model_provider = "openai"\n' + CUSTOM_PROVIDER)
        self.assert_warns(run_hook(self.home), "openai")

    def test_silent_when_no_custom_provider_is_defined(self):
        # 個人PCなど、既定 provider を使う構成では警告しない
        self.config.write_text('model = "some-model"\n')
        self.assert_silent(run_hook(self.home))

    def test_silent_when_config_does_not_exist(self):
        self.assert_silent(run_hook(self.home))

    def test_warns_when_config_cannot_be_parsed(self):
        # 検査できなかったことを「問題なし」に畳まない
        self.config.write_text("model_provider = \n")
        self.assert_warns(run_hook(self.home), "検査できません")

    def test_warns_when_model_providers_is_not_a_table(self):
        self.config.write_text('model_providers = "gateway"\n')
        self.assert_warns(run_hook(self.home), "検査できません")

    def test_does_not_leak_provider_secrets_into_message(self):
        self.config.write_text(
            CUSTOM_PROVIDER
            + '\n[model_providers.gateway.http_headers]\nAuthorization = "Bearer secret-token"\n'
        )
        result = run_hook(self.home)
        self.assertNotIn("secret-token", result.stdout)
        self.assertNotIn("gateway.example.com", result.stdout)


class TestBaseProviderHookWiring(unittest.TestCase):
    def test_runs_on_every_session_start_source(self):
        config = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))
        groups = [
            group
            for group in config["hooks"]["SessionStart"]
            if any(
                "check-codex-base-provider.py" in hook.get("command", "")
                for hook in group.get("hooks", [])
            )
        ]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("matcher"), "startup|resume|clear|compact")


if __name__ == "__main__":
    unittest.main()
