#!/usr/bin/env python3
"""setup.sh の選択子とホスト別配布境界を検証する。"""
import json
import os
import shutil
import subprocess
import sys
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
        "#!/bin/sh\nprintf 'codex %s\\n' \"$*\" >> \"$SETUP_COMMAND_LOG\"\n"
        "if [ -n \"${CODEX_PLUGIN_LIST:-}\" ]; then printf '%s' \"$CODEX_PLUGIN_LIST\"; "
        "else printf '%s' '{\"installed\":[]}'; fi\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    ssh_add = bindir / "ssh-add"
    ssh_add.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ssh_add.chmod(0o755)
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
        # macOSのtempfileは`/var`を返すが、`/var`は`/private/var`へのsymlink。
        # setup対象HOMEの安全検査が中間symlinkを正しく拒否するため、fixtureは実体パスで作る。
        self.base = Path(self.temporary.name).resolve()
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
        self.assertTrue((self.home / ".claude" / "skills" / "backend-patterns").is_symlink())
        self.assertFalse((self.home / ".codex" / "AGENTS.md").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_codex_installs_only_codex_and_agent_skill_assets(self):
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()
        result = run_setup(self.repository, self.home, "--codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / ".codex" / "AGENTS.md").is_symlink())
        self.assertTrue((self.home / ".agents" / "skills" / "backend-patterns").is_symlink())
        self.assertTrue((self.home / ".agents" / "skills" / "codex-cli-best-practice").is_symlink())
        self.assertFalse((self.home / ".codex" / "prompts").exists())
        self.assertFalse((self.home / ".claude" / "CLAUDE.md").exists())

    def test_codex_setup_completes_without_claude_directory(self):
        # Codexだけを入れたマシンでは ~/.claude が無い。
        (self.home / ".codex").mkdir()
        result = run_setup(self.repository, self.home, "--codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / ".claude").exists())
        self.assertTrue((self.home / ".codex" / "AGENTS.md").is_symlink())
        self.assertTrue((self.home / ".codex" / "bin").is_symlink())
        self.assertTrue((self.home / ".codex" / "hooks").is_symlink())

    def test_codex_links_same_shared_assets_into_personal_home(self):
        # ADR 0026: 個人用の CODEX_HOME にも、会社用と同じ共有資産を配る
        company = self.home / ".codex"
        personal = self.home / ".codex-personal"
        company.mkdir()
        personal.mkdir()
        result = run_setup(self.repository, self.home, "--codex")
        self.assertEqual(result.returncode, 0, result.stderr)

        def shared_links(root):
            return {p.name: os.readlink(p) for p in root.iterdir() if p.is_symlink()}

        self.assertIn("AGENTS.md", shared_links(personal))
        self.assertEqual(shared_links(personal), shared_links(company))

    def test_codex_no_longer_generates_personal_profile(self):
        # ADR 0026: 個人用は CODEX_HOME を分けるので、会社用に重ねるプロファイルは作らない
        (self.home / ".codex").mkdir()
        config = self.home / ".codex" / "config.toml"
        config.write_text('[mcp_servers.a]\nurl = "https://a.example"\n')
        config.chmod(0o600)
        result = run_setup(self.repository, self.home, "--codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / ".codex" / "personal.config.toml").exists())

    def test_codex_keeps_old_personal_profile_and_tells_to_move_it(self):
        # 既存のプロファイルは消さずに残し、退避を案内する
        (self.home / ".codex").mkdir()
        old = self.home / ".codex" / "personal.config.toml"
        old.write_text('model_provider = "openai"\n')
        result = run_setup(self.repository, self.home, "--codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(old.read_text(), 'model_provider = "openai"\n')
        self.assertIn("personal.config.toml", result.stdout + result.stderr)

    def test_codex_skips_personal_home_when_missing(self):
        # 会社用だけのマシンでは個人用を作らず、配らなかったことを通知する
        (self.home / ".codex").mkdir()
        result = run_setup(self.repository, self.home, "--codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / ".codex-personal").exists())
        self.assertIn(".codex-personal", result.stdout + result.stderr)

    def test_rerun_removes_only_repository_skill_links_missing_from_manifest(self):
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()
        self.assertEqual(run_setup(self.repository, self.home, "--all").returncode, 0)
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        claude_skills = self.home / ".claude" / "skills"
        agent_skills = self.home / ".agents" / "skills"
        # manifest から外した skill のリンク（リンク先が消えて壊れている）
        for skills in (claude_skills, agent_skills):
            (skills / "removed-skill").symlink_to(self.repository / "skills" / "removed-skill")
        # 利用者が別の場所から張ったリンクは残す
        (claude_skills / "user-skill").symlink_to(elsewhere)
        (claude_skills / "find-skills").symlink_to(agent_skills / "backend-patterns")

        result = run_setup(self.repository, self.home, "--all")

        self.assertEqual(result.returncode, 0, result.stderr)
        for skills in (claude_skills, agent_skills):
            with self.subTest(skills=skills):
                self.assertFalse((skills / "removed-skill").is_symlink())
                self.assertTrue((skills / "backend-patterns").is_symlink())
        self.assertTrue((claude_skills / "user-skill").is_symlink())
        self.assertTrue((claude_skills / "find-skills").is_symlink())

    def test_both_profiles_carry_explicit_markers(self):
        # 個人プロファイルで起動したセッションから claude -p を起動するとき、目印で --settings を付け分ける
        (self.home / ".claude").mkdir()
        result = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        personal = json.loads((self.home / ".claude" / "settings.personal.json").read_text(encoding="utf-8"))
        settings = json.loads((self.home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(personal["env"]["CLAUDE_PROFILE"], "personal")
        # 既定のプロファイルにも明示の目印を置く。引き継いだ personal を上書きし、目印の脱落も検出できるようにする
        self.assertEqual(settings["env"]["CLAUDE_PROFILE"], "default")

    def test_code_learning_skill_is_linked_for_both_hosts(self):
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--all")

        self.assertEqual(result.returncode, 0, result.stderr)
        source = (self.repository / "skills" / "code-learning").resolve()
        for installed in (
            self.home / ".claude" / "skills" / "code-learning",
            self.home / ".agents" / "skills" / "code-learning",
        ):
            with self.subTest(installed=installed):
                self.assertTrue(installed.is_symlink())
                self.assertEqual(installed.resolve(), source)

    def test_code_learning_rule_is_visible_for_both_hosts(self):
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--all")

        self.assertEqual(result.returncode, 0, result.stderr)
        source = (self.repository / "rules" / "code-learning.md").resolve()
        self.assertTrue(source.is_file())
        for installed in (
            self.home / ".claude" / "rules" / "code-learning.md",
            self.home / ".codex" / "rules" / "code-learning.md",
        ):
            with self.subTest(installed=installed):
                self.assertEqual(installed.resolve(), source)

    def test_learning_store_is_distributed_without_initializing(self):
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--all")

        self.assertEqual(result.returncode, 0, result.stderr)
        source = (self.repository / "bin" / "learning-store.py").resolve()
        self.assertEqual(
            (self.home / ".claude/bin/learning-store.py").resolve(),
            source,
        )
        self.assertEqual(
            (self.home / ".codex/bin/learning-store.py").resolve(),
            source,
        )
        self.assertFalse(
            (self.home / ".config/agent-learning/config.json").exists()
        )
        self.assertFalse((self.repository / ".learning-store.json").exists())

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

    def test_codex_installs_model_routing_instructions(self):
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.home / ".codex" / "MODEL_ROUTING.md"
        self.assertTrue(installed.is_symlink())
        self.assertEqual(
            installed.resolve(),
            (self.repository / "codex" / "MODEL_ROUTING.md").resolve(),
        )

    def test_codex_installs_runnable_handoff_validator_at_agent_path(self):
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.home / ".codex" / "bin" / "validate-codex-handoff.py"
        self.assertTrue(installed.is_file())
        self.assertEqual(
            installed.resolve(),
            (self.repository / "bin" / "validate-codex-handoff.py").resolve(),
        )
        help_result = subprocess.run(
            ["python3", str(installed), "--help"],
            cwd=self.repository,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("モデル間handoff", help_result.stdout)

    def test_codex_installs_model_switch_cli_and_hook(self):
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        for source, installed in (
            ("bin/codex-model-switch.py", ".codex/bin/codex-model-switch.py"),
            ("bin/codex_model_switch.py", ".codex/bin/codex_model_switch.py"),
            ("hooks/codex-model-switch-hook.py", ".codex/hooks/codex-model-switch-hook.py"),
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    (self.home / installed).resolve(),
                    (self.repository / source).resolve(),
                )

    def test_codex_setup_configures_default_subagent_pair(self):
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        with (self.home / ".codex" / "config.toml").open("rb") as config_file:
            agents = tomllib.load(config_file)["agents"]
        self.assertEqual(agents["default_subagent_model"], "gpt-6-luna")
        self.assertEqual(agents["default_subagent_reasoning_effort"], "medium")

    def test_codex_setup_reports_signing_skip_without_config(self):
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SSH署名設定をスキップ", result.stderr)

    def test_codex_setup_audits_without_mutating_plugin_state(self):
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        commands = (self.home.parent / "commands.log").read_text(encoding="utf-8")
        self.assertIn("codex plugin list --json", commands)
        self.assertNotIn("codex plugin add", commands)
        self.assertNotIn("codex plugin remove", commands)

    def test_codex_policy_violation_is_reported_apart_from_failures(self):
        (self.home / ".codex").mkdir()
        installed = (
            '{"installed":[{"pluginId":"security-guidance@claude-plugins-official",'
            '"marketplaceName":"claude-plugins-official","enabled":true}]}'
        )

        result = run_setup(self.repository, self.home, "--codex", extra_env={"CODEX_PLUGIN_LIST": installed})

        self.assertEqual(result.returncode, 1)
        self.assertIn("Codex plugin policy violations:", result.stderr)
        self.assertIn("security-guidance@claude-plugins-official", result.stderr)
        self.assertNotIn("setup completed with failures", result.stderr)

    def test_codex_audit_error_is_reported_as_failure(self):
        (self.home / ".codex").mkdir()

        result = run_setup(self.repository, self.home, "--codex", extra_env={"CODEX_PLUGIN_LIST": "not json"})

        self.assertEqual(result.returncode, 1)
        self.assertIn("setup completed with failures", result.stderr)
        self.assertIn("operation=audit", result.stderr)

    def test_codex_setup_preserves_config_when_bitwarden_agent_is_unavailable(self):
        (self.home / ".codex").mkdir()
        config = self.home / ".codex" / "config.toml"
        original = (
            'model = "gpt-test"\n'
            '[private]\n'
            'token = "must-stay-local"\n'
            '[shell_environment_policy.set]\n'
            'SSH_AUTH_SOCK = "/tmp/old-agent.sock"\n'
        )
        config.write_text(original, encoding="utf-8")
        config.chmod(0o600)

        result = run_setup(self.repository, self.home, "--codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        updated = config.read_text(encoding="utf-8")
        self.assertIn('token = "must-stay-local"', updated)
        self.assertIn('SSH_AUTH_SOCK = "/tmp/old-agent.sock"', updated)
        parsed = tomllib.loads(updated)
        self.assertEqual(parsed["model"], "gpt-test")
        self.assertEqual(parsed["private"]["token"], "must-stay-local")
        self.assertEqual(parsed["agents"]["default_subagent_model"], "gpt-6-luna")
        self.assertEqual(
            parsed["agents"]["default_subagent_reasoning_effort"],
            "medium",
        )
        self.assertIn("agentの鍵を確認できない", result.stderr)

    def test_codex_setup_preserves_metadata_when_signing_update_succeeds(self):
        xattr = shutil.which("xattr")
        chmod = shutil.which("chmod")
        ls = shutil.which("ls")
        if sys.platform != "darwin" or None in {xattr, chmod, ls}:
            self.skipTest("macOSのsetup metadata保持検査ではない")
        codex_dir = self.home / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        config.write_text(
            'model = "gpt-test"\n'
            '[private]\n'
            'token = "must-stay-local"\n',
            encoding="utf-8",
        )
        config.chmod(0o600)
        subprocess.run(
            [xattr, "-w", "com.example.codex-setup-test", "preserve-me", config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [chmod, "+a", "everyone deny write", config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        socket_path = (
            self.home
            / "Library/Containers/com.bitwarden.desktop/Data/.bitwarden-ssh-agent.sock"
        )
        socket_path.parent.mkdir(parents=True)
        host_socket = Path(os.environ.get("SSH_AUTH_SOCK", ""))
        if not host_socket.is_absolute() or not host_socket.is_socket():
            self.skipTest("実socketが無いためsetup成功分岐を検証できない")
        try:
            socket_path.symlink_to(host_socket)
            result = run_setup(self.repository, self.home, "--codex")
        finally:
            socket_path.unlink(missing_ok=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(parsed["private"]["token"], "must-stay-local")
        self.assertEqual(
            parsed["shell_environment_policy"]["set"]["SSH_AUTH_SOCK"],
            str(socket_path),
        )
        self.assertEqual(parsed["agents"]["default_subagent_model"], "gpt-6-luna")
        attribute = subprocess.run(
            [xattr, "-p", "com.example.codex-setup-test", config],
            check=True,
            capture_output=True,
            text=True,
        )
        acl = subprocess.run(
            [ls, "-le", config],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(attribute.stdout.rstrip("\n"), "preserve-me")
        self.assertIn("deny write", acl.stdout)

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

    def test_missing_agent_defaults_helper_stops_before_home_mutation(self):
        (self.home / ".codex").mkdir()
        (self.repository / "bin" / "configure_codex_agent_defaults.py").unlink()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("configure_codex_agent_defaults.py", result.stderr)
        self.assertEqual(list((self.home / ".codex").iterdir()), [])

    def test_missing_handoff_validator_stops_before_home_mutation(self):
        (self.home / ".codex").mkdir()
        (self.repository / "bin" / "validate-codex-handoff.py").unlink(missing_ok=True)

        result = run_setup(self.repository, self.home, "--codex")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validate-codex-handoff.py", result.stderr)
        self.assertEqual(list((self.home / ".codex").iterdir()), [])

    def test_missing_model_switch_hook_stops_before_home_mutation(self):
        (self.home / ".codex").mkdir()
        (self.repository / "hooks" / "codex-model-switch-hook.py").unlink()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("codex-model-switch-hook.py", result.stderr)
        self.assertEqual(list((self.home / ".codex").iterdir()), [])

    def test_missing_config_io_helper_stops_before_home_mutation(self):
        (self.home / ".codex").mkdir()
        (self.repository / "bin" / "codex_config_io.py").unlink()

        result = run_setup(self.repository, self.home, "--codex")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("codex_config_io.py", result.stderr)
        self.assertEqual(list((self.home / ".codex").iterdir()), [])

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
