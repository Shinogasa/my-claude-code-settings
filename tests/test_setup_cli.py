#!/usr/bin/env python3
"""setup.sh の選択子とホスト別配布境界を検証する。"""
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def copy_repository(base: Path) -> Path:
    repository = base / "repository"
    repository.mkdir()
    for relative in (
        ".gitmodules", "CLAUDE.md", "README.md", "settings.json.template",
        "env.json.template", "setup.sh", "statusline.js",
    ):
        shutil.copy2(ROOT / relative, repository / relative)
    for relative in (".githooks", "agents", "bin", "codex", "commands", "hooks", "manifests", "output-styles", "rules", "skills"):
        shutil.copytree(ROOT / relative, repository / relative, symlinks=True)
    return repository


def make_stub_commands(base: Path) -> Path:
    bindir = base / "bin"
    bindir.mkdir(exist_ok=True)
    claude = bindir / "claude"
    claude.write_text(
        "#!/bin/sh\nprintf 'claude %s\\n' \"$*\" >> \"$SETUP_COMMAND_LOG\"\n"
        "if [ \"$1 $2\" = 'plugin list' ]; then printf '%s' \"${CLAUDE_PLUGIN_LIST:-[]}\"; exit 0; fi\n"
        "if [ \"$1 $2\" = 'plugin install' ] && [ \"${CLAUDE_FAIL_PLUGIN:-}\" = \"$3\" ]; then exit 9; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    claude.chmod(0o755)
    codex = bindir / "codex"
    codex.write_text(
        "#!/bin/sh\nprintf 'codex %s\\n' \"$*\" >> \"$SETUP_COMMAND_LOG\"\nprintf '%s' '{\"installed\":[]}'\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    git = bindir / "git"
    git.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$SETUP_COMMAND_LOG\"\n"
        "if [ \"${SETUP_GIT_EXIT:-0}\" != 0 ]; then exit \"$SETUP_GIT_EXIT\"; fi\n"
        "if [ \"$*\" = \"-C $SETUP_SUBMODULE_REPOSITORY submodule update --init --recursive\" ]; then mkdir -p \"$SETUP_SUBMODULE_ROOT/claude-code-best-practice\" \"$SETUP_SUBMODULE_ROOT/codex-cli-best-practice\"; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    return bindir


def run_setup(repository: Path, home: Path, *args: str, extra_env=None) -> subprocess.CompletedProcess[str]:
    bindir = make_stub_commands(home.parent)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env["SETUP_COMMAND_LOG"] = str(home.parent / "commands.log")
    env["SETUP_SUBMODULE_REPOSITORY"] = str(repository)
    env["SETUP_SUBMODULE_ROOT"] = str(repository)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(repository / "setup.sh"), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


class SetupCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repository = copy_repository(self.base)
        self.home = self.base / "home"
        self.home.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_selector_is_required_without_mutating_home(self):
        result = run_setup(self.repository, self.home)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_fixture_excludes_submodule_contents(self):
        self.assertTrue((self.repository / "setup.sh").is_file())
        self.assertFalse((self.repository / "claude-code-best-practice").exists())
        self.assertFalse((self.repository / "codex-cli-best-practice").exists())

    def test_unknown_or_multiple_selectors_fail_before_mutation(self):
        for arguments in (("--unknown",), ("--claude", "--codex")):
            with self.subTest(arguments=arguments):
                result = run_setup(self.repository, self.home, *arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Usage:", result.stderr)
                self.assertEqual(list(self.home.iterdir()), [])

    def test_claude_installs_only_claude_assets(self):
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()
        result = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / ".claude" / "CLAUDE.md").is_symlink())
        self.assertTrue((self.home / ".claude" / "skills" / "api-design").is_symlink())
        self.assertFalse((self.home / ".codex" / "AGENTS.md").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_codex_installs_only_codex_and_agent_skill_assets(self):
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()
        result = run_setup(self.repository, self.home, "--codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / ".codex" / "AGENTS.md").is_symlink())
        self.assertTrue((self.home / ".agents" / "skills" / "api-design").is_symlink())
        self.assertTrue((self.home / ".agents" / "skills" / "codex-cli-best-practice").is_symlink())
        self.assertTrue((self.home / ".codex" / ".my-claude-code-settings" / "ownership.json").is_file())
        self.assertFalse((self.home / ".codex" / "prompts").exists())
        self.assertFalse((self.home / ".claude" / "CLAUDE.md").exists())

    def test_codex_installs_global_rtk_instructions(self):
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.home / ".codex" / "RTK.md"
        self.assertTrue(installed.is_symlink())
        self.assertEqual(
            installed.resolve(),
            (self.repository / "codex" / "RTK.md").resolve(),
        )

    def test_codex_setup_generates_transport_complete_mcp_entries(self):
        (self.home / ".codex").mkdir()
        (self.home / ".codex" / "config.toml").write_text(
            '[mcp_servers."remote-http"]\n'
            'url = "https://example.invalid/mcp"\n'
            '[mcp_servers.local_stdio]\n'
            'command = "/bin/true"\n',
            encoding="utf-8",
        )

        result = run_setup(self.repository, self.home, "--codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        with (self.home / ".codex" / "personal.config.toml").open("rb") as profile:
            servers = tomllib.load(profile)["mcp_servers"]
        self.assertEqual(
            servers,
            {
                "local_stdio": {"command": "/bin/true", "enabled": False},
                "remote-http": {
                    "url": "https://example.invalid/mcp",
                    "enabled": False,
                },
            },
        )

    def test_all_requires_both_host_directories_before_any_mutation(self):
        (self.home / ".claude").mkdir()
        result = run_setup(self.repository, self.home, "--all")
        self.assertEqual(result.returncode, 1)
        self.assertIn(".codex", result.stderr)
        self.assertEqual(list((self.home / ".claude").iterdir()), [])
        self.assertFalse((self.home / ".agents").exists())

    def test_invalid_template_or_env_stops_before_home_apply(self):
        (self.home / ".claude").mkdir()
        template = self.repository / "settings.json.template"
        template.write_text("{broken", encoding="utf-8")
        result = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(list((self.home / ".claude").iterdir()), [])
        self.assertFalse((self.home.parent / "commands.log").exists())

        template.write_text((ROOT / "settings.json.template").read_text(encoding="utf-8"), encoding="utf-8")
        (self.repository / ".env").write_text("ANTHROPIC_AUTH_TOKEN=your-token-here\n", encoding="utf-8")
        result = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(list((self.home / ".claude").iterdir()), [])

    def test_invalid_enabled_plugins_stops_before_home_apply(self):
        (self.home / ".claude").mkdir()
        template = self.repository / "settings.json.template"
        document = json.loads(template.read_text(encoding="utf-8"))
        document["enabledPlugins"] = []
        template.write_text(json.dumps(document), encoding="utf-8")

        result = run_setup(self.repository, self.home, "--claude")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(list((self.home / ".claude").iterdir()), [])
        self.assertFalse((self.home.parent / "commands.log").exists())

    def test_invalid_settings_env_stops_before_home_apply(self):
        (self.home / ".claude").mkdir()
        template = self.repository / "settings.json.template"
        document = json.loads(template.read_text(encoding="utf-8"))
        document["env"] = []
        template.write_text(json.dumps(document), encoding="utf-8")
        (self.repository / ".env").write_text(
            "ANTHROPIC_AUTH_TOKEN=token\n"
            "ANTHROPIC_BASE_URL=https://example.invalid\n"
            "ANTHROPIC_MODEL=test\n"
            "CLAUDE_CODE_SUBAGENT_MODEL=sub\n"
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1\n",
            encoding="utf-8",
        )

        result = run_setup(self.repository, self.home, "--claude")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(list((self.home / ".claude").iterdir()), [])
        self.assertFalse((self.home.parent / "commands.log").exists())

    def test_submodule_and_git_hooks_run_after_preflight_before_home_apply(self):
        (self.home / ".claude").mkdir()
        (self.repository / ".githooks" / "patterns-local.txt").unlink(missing_ok=True)
        result = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = (self.home.parent / "commands.log").read_text(encoding="utf-8")
        self.assertIn("submodule update --init --recursive", commands)
        self.assertIn("config core.hooksPath .githooks", commands)
        self.assertTrue((self.repository / ".githooks" / "patterns-local.txt").is_file())

    def test_missing_git_hook_template_stops_before_repository_mutation(self):
        (self.home / ".claude").mkdir()
        (self.repository / ".githooks" / "patterns-local.txt").unlink(
            missing_ok=True,
        )
        (self.repository / ".githooks" / "patterns-local.txt.example").unlink()

        result = run_setup(self.repository, self.home, "--claude")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("patterns-local.txt.example", result.stderr)
        self.assertFalse((self.home.parent / "commands.log").exists())
        self.assertEqual(list((self.home / ".claude").iterdir()), [])

    def test_declared_missing_submodule_is_initialized_after_preflight(self):
        (self.home / ".claude").mkdir()
        missing = self.repository / "claude-code-best-practice"
        self.assertFalse(missing.exists())
        result = run_setup(
            self.repository, self.home, "--claude",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(missing.is_dir())
        self.assertTrue((self.home / ".claude" / "claude-code-best-practice").is_symlink())

    def test_git_failure_is_reported_before_home_apply(self):
        (self.home / ".claude").mkdir()
        result = run_setup(self.repository, self.home, "--claude", extra_env={"SETUP_GIT_EXIT": "23"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list((self.home / ".claude").iterdir()), [])

    def test_claude_plugin_list_skips_installed_and_aggregates_independent_failures(self):
        (self.home / ".claude").mkdir()
        installed = '[{"id":"code-review@claude-plugins-official"}]'
        failed = "context7@claude-plugins-official"
        result = run_setup(
            self.repository, self.home, "--claude",
            extra_env={"CLAUDE_PLUGIN_LIST": installed, "CLAUDE_FAIL_PLUGIN": failed},
        )
        self.assertEqual(result.returncode, 1)
        commands = (self.home.parent / "commands.log").read_text(encoding="utf-8")
        self.assertIn("claude plugin list --json", commands)
        self.assertNotIn("claude plugin install code-review@claude-plugins-official", commands)
        self.assertNotIn("claude plugin install learning-output-style@claude-plugins-official", commands)
        self.assertIn("claude plugin install context7@claude-plugins-official", commands)
        self.assertIn(f"plugin={failed} operation=install", result.stderr)
        self.assertIn(f"retry: claude plugin install {failed}", result.stderr)

    def test_claude_plugin_list_rejects_invalid_json_without_installing(self):
        (self.home / ".claude").mkdir()

        result = run_setup(
            self.repository,
            self.home,
            "--claude",
            extra_env={"CLAUDE_PLUGIN_LIST": "{not-json"},
        )

        self.assertEqual(result.returncode, 1)
        commands = (self.home.parent / "commands.log").read_text(encoding="utf-8")
        self.assertIn("claude plugin list --json", commands)
        self.assertNotIn("claude plugin install", commands)
        self.assertIn("plugin=all operation=list", result.stderr)
        self.assertIn("retry: claude plugin list --json", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
