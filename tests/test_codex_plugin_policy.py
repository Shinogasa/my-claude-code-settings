import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "codex" / "plugin-policy.json"
AUDITOR_PATH = ROOT / "bin" / "audit-codex-plugins.py"


def load_auditor():
    spec = importlib.util.spec_from_file_location("audit_codex_plugins", AUDITOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodexPluginPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auditor = load_auditor()

    def read_policy(self):
        with POLICY_PATH.open(encoding="utf-8") as policy_file:
            return json.load(policy_file)

    def test_policy_schema_and_exact_classifications(self):
        policy = self.read_policy()
        self.assertEqual(policy["schemaVersion"], 1)
        self.assertEqual(policy["defaultDenyMarketplaces"], ["claude-plugins-official"])
        self.assertEqual(
            policy["plugins"],
            {
                "superpowers@openai-api-curated": {"status": "allow", "reason": "Codex向け配布物で、skillsの利用を確認済み"},
                "context7@claude-plugins-official": {"status": "review", "reason": "有用候補だが、Codex向け候補を個別評価するまで導入しない"},
                "serena@claude-plugins-official": {"status": "review", "reason": "有用候補だが、Codex向け候補を個別評価するまで導入しない"},
                "learning-output-style@claude-plugins-official": {"status": "deny", "reason": "自前学習モードと重複・競合する。コード参加だけ共有ruleへ統合する"},
                "security-guidance@claude-plugins-official": {"status": "deny", "reason": "Claude固有の非同期hook契約でSessionStartが失敗する"},
                "claude-md-management@claude-plugins-official": {"status": "deny", "reason": "CLAUDE.mdだけを対象にし、CodexのAGENTS.md階層を扱わない"},
                "asana@claude-plugins-official": {"status": "deny", "reason": "Codexで使える構成要素を確認できない"},
                "code-review@claude-plugins-official": {"status": "deny", "reason": "Claude commandのみで、Codex標準reviewと重複する"},
                "gopls-lsp@claude-plugins-official": {"status": "deny", "reason": "Go開発上の具体的な不足が出ておらず、公開仕様でのruntime契約も未確認"},
                "atlassian@claude-plugins-official": {"status": "deny", "reason": "Codexは atlassian-http を MCP として直接設定済みで、plugin版とは重複する"},
            },
        )
        for entry in policy["plugins"].values():
            self.assertIn(entry["status"], {"allow", "review", "deny"})
            self.assertTrue(entry["reason"].strip())

    def test_enabled_review_deny_and_unlisted_default_deny_are_sorted(self):
        installed = [
            {"pluginId": "zeta@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
            {"pluginId": "context7@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
            {"pluginId": "learning-output-style@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
            {"pluginId": "serena@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
            {"pluginId": "code-review@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
            {"pluginId": "zeta@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
        ]
        self.assertEqual(
            self.auditor.find_violations(self.read_policy(), installed),
            [
                "code-review@claude-plugins-official",
                "context7@claude-plugins-official",
                "learning-output-style@claude-plugins-official",
                "serena@claude-plugins-official",
                "zeta@claude-plugins-official",
            ],
        )

    def test_enabled_allow_is_ignored(self):
        installed = [{"pluginId": "superpowers@openai-api-curated", "marketplaceName": "openai-api-curated", "enabled": True}]
        self.assertEqual(self.auditor.find_violations(self.read_policy(), installed), [])

    def test_disabled_entries_are_ignored(self):
        installed = [
            {"pluginId": "context7@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": False},
            {"pluginId": "learning-output-style@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": False},
            {"pluginId": "future@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": False},
        ]
        self.assertEqual(self.auditor.find_violations(self.read_policy(), installed), [])

    def test_unlisted_other_marketplace_and_malformed_entries_are_ignored(self):
        installed = [
            {"pluginId": "personal-plugin@personal", "marketplaceName": "personal", "enabled": True},
        ]
        self.assertEqual(self.auditor.find_violations(self.read_policy(), installed), [])

    def test_unknown_policy_status_raises(self):
        policy = self.read_policy()
        policy["plugins"]["superpowers@openai-api-curated"]["status"] = "maybe"
        with self.assertRaisesRegex(ValueError, "status"):
            self.auditor.find_violations(policy, [])

    def test_wrong_default_deny_marketplaces_type_raises(self):
        policy = self.read_policy()
        policy["defaultDenyMarketplaces"] = "claude-plugins-official"
        with self.assertRaisesRegex(ValueError, "defaultDenyMarketplaces"):
            self.auditor.find_violations(policy, [])

    def test_invalid_policy_shape_raises(self):
        with self.assertRaisesRegex(ValueError, "policy"):
            self.auditor.find_violations([], [])
        policy = self.read_policy()
        policy["plugins"][" "] = {"status": "allow", "reason": "理由"}
        with self.assertRaisesRegex(ValueError, "plugin id"):
            self.auditor.find_violations(policy, [])

    def test_invalid_enabled_value_raises(self):
        installed = [{"pluginId": "personal-plugin@personal", "marketplaceName": "personal", "enabled": 1}]
        with self.assertRaisesRegex(ValueError, "enabled"):
            self.auditor.find_violations(self.read_policy(), installed)

    def test_missing_installed_required_fields_raises(self):
        for entry, field in (
            ({"marketplaceName": "personal", "enabled": True}, "pluginId"),
            ({"pluginId": "personal-plugin@personal", "enabled": True}, "marketplaceName"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                self.auditor.find_violations(self.read_policy(), [entry])

    def test_invalid_installed_shape_raises(self):
        with self.assertRaisesRegex(ValueError, "installed"):
            self.auditor.find_violations(self.read_policy(), {})
        with self.assertRaisesRegex(ValueError, "entry"):
            self.auditor.find_violations(self.read_policy(), ["not an entry"])

    def test_valid_explicit_non_allow_status_is_a_violation(self):
        policy = self.read_policy()
        policy["plugins"]["personal-plugin@personal"] = {"status": "review", "reason": "確認中"}
        installed = [{"pluginId": "personal-plugin@personal", "marketplaceName": "personal", "enabled": True}]
        self.assertEqual(self.auditor.find_violations(policy, installed), ["personal-plugin@personal"])

    def test_load_installed_uses_default_command_and_parses_stdout(self):
        document = {"installed": [{"pluginId": "superpowers@openai-api-curated", "enabled": True}], "available": []}
        completed = subprocess.CompletedProcess([], 0, json.dumps(document), "")
        with mock.patch.object(self.auditor.subprocess, "run", return_value=completed) as run:
            self.assertEqual(self.auditor.load_installed(), document["installed"])
        run.assert_called_once_with(["codex", "plugin", "list", "--json"], check=True, capture_output=True, text=True)

    def test_load_installed_rejects_invalid_json_and_envelopes(self):
        for stdout, message in (
            ("not json", "JSON"),
            (json.dumps({"available": []}), "installed"),
            (json.dumps({"installed": {}}), "installed"),
        ):
            completed = subprocess.CompletedProcess([], 0, stdout, "")
            with self.subTest(message=message), mock.patch.object(self.auditor.subprocess, "run", return_value=completed):
                with self.assertRaisesRegex(ValueError, message):
                    self.auditor.load_installed()

    def test_main_cli_failure_returns_two_without_traceback(self):
        for error in (
            subprocess.CalledProcessError(3, ["codex"]),
            FileNotFoundError("codex"),
        ):
            with self.subTest(error=type(error).__name__), mock.patch.object(self.auditor, "load_installed", side_effect=error), contextlib.redirect_stderr(io.StringIO()) as error_output:
                result = self.auditor.main()
            self.assertEqual(result, 2)
            self.assertRegex(error_output.getvalue(), r"^Codex plugin audit failed: .+\n$")
            self.assertNotIn("Traceback", error_output.getvalue())

    def test_main_schema_failure_returns_two_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            policy_directory = root / "codex"
            policy_directory.mkdir()
            invalid_policy = self.read_policy()
            invalid_policy["schemaVersion"] = 2
            policy_directory.joinpath("plugin-policy.json").write_text(json.dumps(invalid_policy), encoding="utf-8")
            with mock.patch.object(self.auditor, "ROOT", root), mock.patch.object(
                self.auditor, "load_installed", return_value=[]
            ), contextlib.redirect_stderr(io.StringIO()) as error_output:
                result = self.auditor.main()
        self.assertEqual(result, 2)
        self.assertRegex(error_output.getvalue(), r"^Codex plugin audit failed: .+\n$")
        self.assertNotIn("Traceback", error_output.getvalue())

    def test_executable_invocation_is_read_only_and_uses_exact_argv(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            args_path = temporary_path / "args"
            fake_codex = temporary_path / "codex"
            fake_codex.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CODEX_AUDIT_ARGS\"\nprintf '%s' '{\"installed\":[],\"available\":[]}'\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{temporary_path}{os.pathsep}{environment['PATH']}"
            environment["CODEX_AUDIT_ARGS"] = str(args_path)
            result = subprocess.run(
                [sys.executable, str(AUDITOR_PATH)],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(args_path.read_text(encoding="utf-8").splitlines(), ["plugin", "list", "--json"])

    def test_main_reports_violations_and_returns_one(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            policy_directory = root / "codex"
            policy_directory.mkdir()
            policy_directory.joinpath("plugin-policy.json").write_text(json.dumps(self.read_policy()), encoding="utf-8")
            with mock.patch.object(self.auditor, "ROOT", root), mock.patch.object(
                self.auditor, "load_installed", return_value=[
                    {"pluginId": "z@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
                    {"pluginId": "context7@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
                ]
            ), contextlib.redirect_stdout(io.StringIO()) as output:
                result = self.auditor.main()
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue().splitlines(), [
            "context7@claude-plugins-official",
            "z@claude-plugins-official",
        ])

    def test_main_reports_success_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            policy_directory = root / "codex"
            policy_directory.mkdir()
            policy_directory.joinpath("plugin-policy.json").write_text(json.dumps(self.read_policy()), encoding="utf-8")
            with mock.patch.object(self.auditor, "ROOT", root), mock.patch.object(
                self.auditor, "load_installed", return_value=[]
            ), contextlib.redirect_stdout(io.StringIO()) as output:
                result = self.auditor.main()
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "Codex plugin policy violations: none\n")

    def test_auditor_source_has_no_plugin_mutation_subcommands(self):
        source = AUDITOR_PATH.read_text(encoding="utf-8")
        for mutation in ("enable", "disable", "remove", "install"):
            self.assertNotIn(f'"{mutation}"', source)


if __name__ == "__main__":
    unittest.main()
