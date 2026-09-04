#!/usr/bin/env python3
"""setup の衝突検出と ownership state を実ファイルで検証する。"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
STATE_MODULE = ROOT / "bin" / "setup-state.py"


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


def load_state_module():
    spec = importlib.util.spec_from_file_location("setup_state", STATE_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_stub_commands(base: Path) -> Path:
    bindir = base / "bin"
    bindir.mkdir(exist_ok=True)
    for name in ("claude", "codex"):
        path = bindir / name
        output = '{"installed":[]}' if name == "codex" else '[]'
        path.write_text(f"#!/bin/sh\nprintf '%s' '{output}'\n", encoding="utf-8")
        path.chmod(0o755)
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


def run_setup(repository: Path, home: Path, *arguments: str, extra_env=None) -> subprocess.CompletedProcess[str]:
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
        ["bash", str(repository / "setup.sh"), *arguments], text=True, capture_output=True,
        env=env, check=False,
    )


class SetupStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = load_state_module()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        self.source.write_text("source\n", encoding="utf-8")
        self.destination = self.base / "destination"

    def tearDown(self):
        self.temporary.cleanup()

    def test_sha256_file_is_content_digest(self):
        self.assertEqual(
            self.state.sha256_file(self.source),
            hashlib.sha256(b"source\n").hexdigest(),
        )

    def test_classify_distinguishes_missing_and_correct_or_wrong_links(self):
        self.assertEqual(self.state.classify(self.source, self.destination, None), "missing")
        self.destination.symlink_to(self.source)
        self.assertEqual(self.state.classify(self.source, self.destination, None), "linked")
        self.destination.unlink()
        wrong = self.base / "wrong"
        wrong.write_text("wrong\n", encoding="utf-8")
        self.destination.symlink_to(wrong)
        self.assertEqual(self.state.classify(self.source, self.destination, None), "conflict")

    def test_classify_requires_matching_recorded_checksum_for_generated_file(self):
        self.destination.write_text("generated\n", encoding="utf-8")
        checksum = self.state.sha256_file(self.destination)
        self.assertEqual(self.state.classify(self.source, self.destination, checksum), "managed-update")
        self.destination.write_text("edited\n", encoding="utf-8")
        self.assertEqual(self.state.classify(self.source, self.destination, checksum), "conflict")
        self.assertEqual(self.state.classify(self.source, self.destination, None), "conflict")

    def test_install_generated_file_preserves_late_destination(self):
        self.destination.write_text("managed\n", encoding="utf-8")
        expected = self.state.snapshot_path(self.destination)
        staged = self.base / "staged"
        staged.write_text("generated\n", encoding="utf-8")
        real_link = os.link

        def insert_late_destination(source, destination):
            Path(destination).write_text("late-user-edit\n", encoding="utf-8")
            return real_link(source, destination)

        with mock.patch.object(
            self.state.os,
            "link",
            side_effect=insert_late_destination,
        ):
            with self.assertRaisesRegex(RuntimeError, "appeared during generated apply"):
                self.state.install_generated_file(
                    staged,
                    self.destination,
                    expected,
                )

        self.assertEqual(
            self.destination.read_text(encoding="utf-8"),
            "late-user-edit\n",
        )
        quarantined = list(
            self.base.glob(".destination.setup-quarantine.*/destination")
        )
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_text(encoding="utf-8"), "managed\n")

    def test_backup_conflict_does_not_unlink_late_replacement(self):
        original = self.base / "original"
        original.write_text("shared-content\n", encoding="utf-8")
        os.link(original, self.destination)
        expected = self.state.snapshot_path(self.destination)
        backup = self.base / "backup"
        real_rename = os.rename

        def replace_before_rename(source, target):
            Path(source).unlink()
            Path(source).write_text("late-user-edit\n", encoding="utf-8")
            return real_rename(source, target)

        with mock.patch.object(
            self.state.os,
            "rename",
            side_effect=replace_before_rename,
        ):
            with self.assertRaisesRegex(RuntimeError, "changed after preflight"):
                self.state.backup_conflict(
                    self.destination,
                    backup,
                    expected,
                )

        self.assertEqual(
            self.destination.read_text(encoding="utf-8"),
            "late-user-edit\n",
        )
        self.assertEqual(original.read_text(encoding="utf-8"), "shared-content\n")
        self.assertFalse(backup.exists())

    def test_load_save_and_backup_path_preserve_state_and_host_boundary(self):
        state_path = self.base / ".claude" / ".my-claude-code-settings" / "ownership.json"
        self.assertEqual(self.state.load_state(state_path), {"version": 1, "generated": {}})
        state = {"version": 1, "generated": {"/tmp/settings.json": "abc"}}
        self.state.save_state(state_path, state)
        self.assertEqual(self.state.load_state(state_path), state)
        destination = self.base / ".claude" / "nested" / "settings.json"
        self.assertEqual(
            self.state.backup_path(self.base / ".claude", destination, "20260821_010203"),
            self.base / ".claude" / "backups" / "20260821_010203" / "nested" / "settings.json",
        )

    def test_backup_path_allows_agent_skills_under_home_but_rejects_outside_home(self):
        home = self.base / "home"
        agent_skill = home / ".agents" / "skills" / "api-design"
        self.assertEqual(
            self.state.backup_path(home / ".codex", agent_skill, "20260821_010203", home),
            home / ".codex" / "backups" / "20260821_010203" / ".agents" / "skills" / "api-design",
        )
        with self.assertRaises(ValueError):
            self.state.backup_path(home / ".codex", self.base / "outside", "20260821_010203", home)


class SetupPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repository = copy_repository(self.base)
        self.home = self.base / "home"
        self.home.mkdir()
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_conflict_reports_detail_and_keeps_selected_hosts_unchanged(self):
        conflict = self.home / ".claude" / "CLAUDE.md"
        conflict.write_text("unowned\n", encoding="utf-8")
        result = run_setup(self.repository, self.home, "--all")
        self.assertEqual(result.returncode, 1)
        self.assertIn("claude", result.stderr)
        self.assertIn(str(conflict), result.stderr)
        self.assertIn("current kind: file", result.stderr)
        self.assertIn(str(self.repository / "CLAUDE.md"), result.stderr)
        self.assertEqual(conflict.read_text(encoding="utf-8"), "unowned\n")
        self.assertFalse((self.home / ".codex" / "AGENTS.md").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_env_cannot_enable_conflict_replacement(self):
        conflict = self.home / ".claude" / "CLAUDE.md"
        conflict.write_text("unowned\n", encoding="utf-8")
        (self.repository / ".env").write_text(
            "ANTHROPIC_AUTH_TOKEN=token\n"
            "ANTHROPIC_BASE_URL=https://example.invalid\n"
            "ANTHROPIC_MODEL=test\n"
            "CLAUDE_CODE_SUBAGENT_MODEL=sub\n"
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1\n"
            "REPLACE_CONFLICTS=true\n",
            encoding="utf-8",
        )

        result = run_setup(self.repository, self.home, "--claude")

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(conflict.is_file())
        self.assertEqual(conflict.read_text(encoding="utf-8"), "unowned\n")
        self.assertFalse((self.home / ".claude" / "backups").exists())

    def test_env_preserves_unquoted_hash_in_value(self):
        (self.repository / ".env").write_text(
            "ANTHROPIC_AUTH_TOKEN=abc#def\n"
            "ANTHROPIC_BASE_URL=https://example.invalid/#fragment\n",
            encoding="utf-8",
        )

        result = run_setup(self.repository, self.home, "--claude")

        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(
            (self.home / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        self.assertEqual(settings["env"]["ANTHROPIC_AUTH_TOKEN"], "abc#def")
        self.assertEqual(
            settings["env"]["ANTHROPIC_BASE_URL"],
            "https://example.invalid/#fragment",
        )

    def test_replace_conflicts_backs_up_then_records_generated_output(self):
        conflict = self.home / ".claude" / "CLAUDE.md"
        conflict.write_text("unowned\n", encoding="utf-8")
        settings = self.home / ".claude" / "settings.json"
        settings.write_text(json.dumps({"unmanaged": "keep"}), encoding="utf-8")
        (self.repository / ".env").write_text(
            "ANTHROPIC_AUTH_TOKEN=token\nANTHROPIC_BASE_URL=https://example.invalid\nANTHROPIC_MODEL=test\nCLAUDE_CODE_SUBAGENT_MODEL=sub\nCLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1\n",
            encoding="utf-8",
        )
        result = run_setup(self.repository, self.home, "--claude", "--replace-conflicts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(conflict.is_symlink())
        backups = list((self.home / ".claude" / "backups").rglob("CLAUDE.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "unowned\n")
        state_path = self.home / ".claude" / ".my-claude-code-settings" / "ownership.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIn(str(self.home / ".claude" / "settings.json"), state["generated"])
        generated = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(generated["unmanaged"], "keep")
        self.assertEqual(generated["env"]["ANTHROPIC_AUTH_TOKEN"], "token")
        update = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(update.returncode, 0, update.stderr)

    def test_replace_conflicts_keeps_home_unchanged_when_git_preparation_fails(self):
        conflict = self.home / ".claude" / "CLAUDE.md"
        conflict.write_text("unowned\n", encoding="utf-8")

        result = run_setup(
            self.repository,
            self.home,
            "--claude",
            "--replace-conflicts",
            extra_env={"SETUP_GIT_EXIT": "23"},
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(conflict.is_file())
        self.assertEqual(conflict.read_text(encoding="utf-8"), "unowned\n")
        self.assertFalse((self.home / ".claude" / "backups").exists())
        self.assertFalse((self.home / ".claude" / "settings.json").exists())
        self.assertFalse((self.home / ".claude" / "settings.personal.json").exists())
        self.assertFalse((self.home / ".claude" / "skills").exists())
        command_log = self.home.parent / "commands.log"
        self.assertFalse(
            "claude plugin" in command_log.read_text(encoding="utf-8")
            if command_log.exists()
            else False
        )

    def test_all_replace_keeps_hosts_unchanged_when_agent_skills_parent_is_file(self):
        agents = self.home / ".agents"
        agents.mkdir()
        blocked_parent = agents / "skills"
        blocked_parent.write_text("user-owned\n", encoding="utf-8")

        result = run_setup(self.repository, self.home, "--all", "--replace-conflicts")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(blocked_parent), result.stderr)
        self.assertEqual(blocked_parent.read_text(encoding="utf-8"), "user-owned\n")
        self.assertFalse((self.home / ".claude" / "CLAUDE.md").exists())
        self.assertFalse((self.home / ".codex" / "AGENTS.md").exists())
        self.assertFalse((self.home / ".claude" / "backups").exists())
        self.assertFalse((self.home / ".codex" / "backups").exists())

    def test_codex_keeps_home_unchanged_when_state_parent_is_file(self):
        blocked_parent = self.home / ".codex" / ".my-claude-code-settings"
        blocked_parent.write_text("user-owned\n", encoding="utf-8")

        result = run_setup(self.repository, self.home, "--codex")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(blocked_parent), result.stderr)
        self.assertEqual(blocked_parent.read_text(encoding="utf-8"), "user-owned\n")
        self.assertFalse((self.home / ".codex" / "AGENTS.md").exists())
        self.assertFalse((self.home / ".codex" / "rules").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_codex_keeps_home_unchanged_when_state_parent_is_not_writable(self):
        state_parent = self.home / ".codex" / ".my-claude-code-settings"
        state_parent.mkdir()
        state_parent.chmod(0o500)
        try:
            result = run_setup(self.repository, self.home, "--codex")
        finally:
            state_parent.chmod(0o700)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(state_parent), result.stderr)
        self.assertFalse((self.home / ".codex" / "AGENTS.md").exists())
        self.assertFalse((self.home / ".codex" / "rules").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_codex_keeps_home_unchanged_when_state_parent_is_not_searchable(self):
        state_parent = self.home / ".codex" / ".my-claude-code-settings"
        state_parent.mkdir()
        state_parent.chmod(0o200)
        try:
            result = run_setup(self.repository, self.home, "--codex")
        finally:
            state_parent.chmod(0o700)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(state_parent), result.stderr)
        self.assertFalse((self.home / ".codex" / "AGENTS.md").exists())
        self.assertFalse((self.home / ".codex" / "rules").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_all_replace_checks_every_backup_parent_before_moving_conflicts(self):
        claude_conflict = self.home / ".claude" / "CLAUDE.md"
        claude_conflict.write_text("claude-user-owned\n", encoding="utf-8")
        codex_conflict = self.home / ".codex" / "AGENTS.md"
        codex_conflict.write_text("codex-user-owned\n", encoding="utf-8")
        blocked_backup_parent = self.home / ".codex" / "backups"
        blocked_backup_parent.write_text("user-owned\n", encoding="utf-8")

        result = run_setup(self.repository, self.home, "--all", "--replace-conflicts")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(blocked_backup_parent), result.stderr)
        self.assertTrue(claude_conflict.is_file())
        self.assertTrue(codex_conflict.is_file())
        self.assertEqual(
            claude_conflict.read_text(encoding="utf-8"),
            "claude-user-owned\n",
        )
        self.assertEqual(
            codex_conflict.read_text(encoding="utf-8"),
            "codex-user-owned\n",
        )
        self.assertEqual(
            blocked_backup_parent.read_text(encoding="utf-8"),
            "user-owned\n",
        )
        self.assertFalse((self.home / ".claude" / "backups").exists())
        self.assertFalse((self.home / ".codex" / "rules").exists())

    def test_duplicate_manifest_target_stops_before_moving_conflicts(self):
        manifest_path = self.repository / "manifests" / "skills.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["shared"].append("api-design")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        conflict = self.home / ".claude" / "skills" / "api-design"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("user-owned\n", encoding="utf-8")

        result = run_setup(
            self.repository,
            self.home,
            "--claude",
            "--replace-conflicts",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("api-design", result.stderr)
        self.assertTrue(conflict.is_file())
        self.assertEqual(conflict.read_text(encoding="utf-8"), "user-owned\n")
        self.assertFalse((self.home / ".claude" / "backups").exists())
        self.assertFalse((self.home / ".claude" / "CLAUDE.md").exists())

    def test_manifest_skill_must_be_one_path_component(self):
        manifest_path = self.repository / "manifests" / "skills.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["shared"].append("../hooks")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        result = run_setup(self.repository, self.home, "--claude")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("../hooks", result.stderr)
        self.assertEqual(list((self.home / ".claude").iterdir()), [])

    def test_all_replace_checks_backup_parent_permissions_before_moving_conflicts(self):
        claude_conflict = self.home / ".claude" / "CLAUDE.md"
        claude_conflict.write_text("claude-user-owned\n", encoding="utf-8")
        codex_conflict = self.home / ".codex" / "AGENTS.md"
        codex_conflict.write_text("codex-user-owned\n", encoding="utf-8")
        blocked_backup_parent = self.home / ".codex" / "backups"
        blocked_backup_parent.mkdir()
        blocked_backup_parent.chmod(0o500)
        try:
            result = run_setup(
                self.repository,
                self.home,
                "--all",
                "--replace-conflicts",
            )
        finally:
            blocked_backup_parent.chmod(0o700)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(blocked_backup_parent), result.stderr)
        self.assertTrue(claude_conflict.is_file())
        self.assertTrue(codex_conflict.is_file())
        self.assertEqual(
            claude_conflict.read_text(encoding="utf-8"),
            "claude-user-owned\n",
        )
        self.assertEqual(
            codex_conflict.read_text(encoding="utf-8"),
            "codex-user-owned\n",
        )
        self.assertFalse((self.home / ".claude" / "backups").exists())
        self.assertFalse((self.home / ".codex" / "rules").exists())

    def test_all_replace_checks_backup_parent_searchability_before_moving_conflicts(self):
        claude_conflict = self.home / ".claude" / "CLAUDE.md"
        claude_conflict.write_text("claude-user-owned\n", encoding="utf-8")
        codex_conflict = self.home / ".codex" / "AGENTS.md"
        codex_conflict.write_text("codex-user-owned\n", encoding="utf-8")
        blocked_backup_parent = self.home / ".codex" / "backups"
        blocked_backup_parent.mkdir()
        blocked_backup_parent.chmod(0o200)
        try:
            result = run_setup(
                self.repository,
                self.home,
                "--all",
                "--replace-conflicts",
            )
        finally:
            blocked_backup_parent.chmod(0o700)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(blocked_backup_parent), result.stderr)
        self.assertTrue(claude_conflict.is_file())
        self.assertTrue(codex_conflict.is_file())
        self.assertEqual(
            claude_conflict.read_text(encoding="utf-8"),
            "claude-user-owned\n",
        )
        self.assertEqual(
            codex_conflict.read_text(encoding="utf-8"),
            "codex-user-owned\n",
        )
        self.assertFalse((self.home / ".claude" / "backups").exists())
        self.assertFalse((self.home / ".codex" / "rules").exists())

    def test_all_replace_backs_up_agent_skills_under_codex_timestamp(self):
        agent_skill = self.home / ".agents" / "skills" / "api-design"
        agent_skill.parent.mkdir(parents=True)
        agent_skill.write_text("unowned\n", encoding="utf-8")
        result = run_setup(self.repository, self.home, "--all", "--replace-conflicts")
        self.assertEqual(result.returncode, 0, result.stderr)
        backups = list((self.home / ".codex" / "backups").rglob("api-design"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "unowned\n")
        self.assertTrue(agent_skill.is_symlink())

    def test_codex_rejects_agent_skills_parent_symlink_to_repository(self):
        agent_skills = self.home / ".agents" / "skills"
        agent_skills.parent.mkdir()
        agent_skills.symlink_to(self.repository / "skills", target_is_directory=True)

        result = run_setup(
            self.repository,
            self.home,
            "--codex",
            "--replace-conflicts",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(agent_skills), result.stderr)
        self.assertTrue(agent_skills.is_symlink())
        self.assertEqual(
            agent_skills.resolve(),
            (self.repository / "skills").resolve(),
        )
        self.assertTrue(
            (self.repository / "skills" / "api-design" / "SKILL.md").is_file()
        )
        self.assertFalse((self.home / ".codex" / "backups").exists())
        self.assertFalse((self.home / ".codex" / "AGENTS.md").exists())

    def test_actual_setup_keeps_correct_link_and_rejects_wrong_link_without_plugins(self):
        first = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(first.returncode, 0, first.stderr)
        destination = self.home / ".claude" / "CLAUDE.md"
        inode = destination.lstat().st_ino
        second = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(destination.lstat().st_ino, inode)
        destination.unlink()
        destination.symlink_to(self.repository / "README.md")
        command_log = self.home.parent / "commands.log"
        command_log.unlink()
        command_log.write_text("", encoding="utf-8")
        conflict = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(conflict.returncode, 1)
        self.assertEqual(destination.resolve(), (self.repository / "README.md").resolve())
        self.assertNotIn("claude plugin", command_log.read_text(encoding="utf-8"))

    def test_state_loss_makes_generated_file_a_conflict(self):
        first = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(first.returncode, 0, first.stderr)
        state = self.home / ".claude" / ".my-claude-code-settings" / "ownership.json"
        state.unlink()
        result = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(self.home / ".claude" / "settings.json"), result.stderr)

    def test_generated_symlink_is_a_conflict_and_never_overwrites_its_source(self):
        template = self.repository / "settings.json.template"
        template_before = template.read_text(encoding="utf-8")
        settings = self.home / ".claude" / "settings.json"
        settings.symlink_to(template)
        (self.repository / ".env").write_text(
            "ANTHROPIC_AUTH_TOKEN=must-not-reach-template\n"
            "ANTHROPIC_BASE_URL=https://example.invalid\n"
            "ANTHROPIC_MODEL=test\n"
            "CLAUDE_CODE_SUBAGENT_MODEL=sub\n"
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1\n",
            encoding="utf-8",
        )

        result = run_setup(self.repository, self.home, "--claude")

        self.assertEqual(result.returncode, 1)
        self.assertIn(str(settings), result.stderr)
        self.assertTrue(settings.is_symlink())
        self.assertEqual(settings.resolve(), template.resolve())
        self.assertEqual(template.read_text(encoding="utf-8"), template_before)
        self.assertNotIn("must-not-reach-template", template.read_text(encoding="utf-8"))
        self.assertFalse((self.home / ".claude" / "CLAUDE.md").exists())

    def test_late_settings_edit_is_not_overwritten(self):
        first = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(first.returncode, 0, first.stderr)
        (self.home / ".claude" / "CLAUDE.md").unlink()
        settings = self.home / ".claude" / "settings.json"
        late_content = '{"late": "user-edit"}\n'
        fake_ln = self.home.parent / "bin" / "ln"
        fake_ln.write_text(
            "#!/bin/sh\n"
            "if [ ! -e \"$SETUP_MUTATION_MARKER\" ]; then\n"
            "  printf '%s' \"$SETUP_LATE_CONTENT\" > \"$SETUP_LATE_PATH\"\n"
            "  : > \"$SETUP_MUTATION_MARKER\"\n"
            "fi\n"
            "exec /bin/ln \"$@\"\n",
            encoding="utf-8",
        )
        fake_ln.chmod(0o755)

        result = run_setup(
            self.repository,
            self.home,
            "--claude",
            extra_env={
                "SETUP_LATE_CONTENT": late_content,
                "SETUP_LATE_PATH": str(settings),
                "SETUP_MUTATION_MARKER": str(self.home.parent / "mutated"),
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed after preflight", result.stderr)
        self.assertEqual(settings.read_text(encoding="utf-8"), late_content)

    def test_late_symlink_is_not_deleted(self):
        make_stub_commands(self.home.parent)
        destination = self.home / ".claude" / "CLAUDE.md"
        wrong_source = self.home.parent / "wrong-source"
        wrong_source.write_text("user-owned\n", encoding="utf-8")
        fake_mkdir = self.home.parent / "bin" / "mkdir"
        fake_mkdir.write_text(
            "#!/bin/sh\n"
            "if [ \"$*\" = \"-p $SETUP_LATE_PARENT\" ]"
            " && [ ! -e \"$SETUP_LATE_LINK\" ]; then\n"
            "  /bin/ln -s \"$SETUP_LATE_TARGET\" \"$SETUP_LATE_LINK\"\n"
            "fi\n"
            "exec /bin/mkdir \"$@\"\n",
            encoding="utf-8",
        )
        fake_mkdir.chmod(0o755)

        result = run_setup(
            self.repository,
            self.home,
            "--claude",
            extra_env={
                "SETUP_LATE_LINK": str(destination),
                "SETUP_LATE_PARENT": str(destination.parent),
                "SETUP_LATE_TARGET": str(wrong_source),
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(), wrong_source.resolve())

    def test_generated_hardlink_requires_replace_and_never_overwrites_its_source(self):
        first = run_setup(self.repository, self.home, "--claude")
        self.assertEqual(first.returncode, 0, first.stderr)
        template = self.repository / "settings.json.template"
        template_before = template.read_text(encoding="utf-8")
        settings = self.home / ".claude" / "settings.json"
        settings.unlink()
        os.link(template, settings)
        (self.repository / ".env").write_text(
            "ANTHROPIC_AUTH_TOKEN=must-not-reach-hardlink-source\n"
            "ANTHROPIC_BASE_URL=https://example.invalid\n"
            "ANTHROPIC_MODEL=test\n"
            "CLAUDE_CODE_SUBAGENT_MODEL=sub\n"
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1\n",
            encoding="utf-8",
        )

        conflict = run_setup(self.repository, self.home, "--claude")

        self.assertEqual(conflict.returncode, 1)
        self.assertIn(str(settings), conflict.stderr)
        self.assertTrue(os.path.samefile(settings, template))
        self.assertEqual(template.read_text(encoding="utf-8"), template_before)

        replaced = run_setup(
            self.repository,
            self.home,
            "--claude",
            "--replace-conflicts",
        )

        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertFalse(os.path.samefile(settings, template))
        self.assertEqual(template.read_text(encoding="utf-8"), template_before)
        generated = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(
            generated["env"]["ANTHROPIC_AUTH_TOKEN"],
            "must-not-reach-hardlink-source",
        )
        backups = list((self.home / ".claude" / "backups").rglob("settings.json"))
        self.assertEqual(len(backups), 1)
        self.assertFalse(os.path.samefile(backups[0], template))
        self.assertEqual(backups[0].read_text(encoding="utf-8"), template_before)

    def test_replace_non_object_settings_backs_up_then_generates_an_object(self):
        settings = self.home / ".claude" / "settings.json"
        settings.write_text("[]\n", encoding="utf-8")

        result = run_setup(
            self.repository,
            self.home,
            "--claude",
            "--replace-conflicts",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsInstance(json.loads(settings.read_text(encoding="utf-8")), dict)
        backups = list((self.home / ".claude" / "backups").rglob("settings.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "[]\n")

    def test_replace_non_utf8_settings_backs_up_then_generates_an_object(self):
        settings = self.home / ".claude" / "settings.json"
        original = b"\xff\xfeuser-owned\n"
        settings.write_bytes(original)

        result = run_setup(
            self.repository,
            self.home,
            "--claude",
            "--replace-conflicts",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsInstance(json.loads(settings.read_text(encoding="utf-8")), dict)
        backups = list((self.home / ".claude" / "backups").rglob("settings.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)

    def test_replace_settings_directory_backs_up_then_generates_a_file(self):
        settings = self.home / ".claude" / "settings.json"
        settings.mkdir()
        (settings / "user-file").write_text("keep\n", encoding="utf-8")

        result = run_setup(
            self.repository,
            self.home,
            "--claude",
            "--replace-conflicts",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(settings.is_file())
        self.assertIsInstance(json.loads(settings.read_text(encoding="utf-8")), dict)
        backups = list((self.home / ".claude" / "backups").rglob("settings.json"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].is_dir())
        self.assertEqual(
            (backups[0] / "user-file").read_text(encoding="utf-8"),
            "keep\n",
        )

    def test_all_replace_uses_one_timestamp_for_claude_and_codex_backups(self):
        claude_conflict = self.home / ".claude" / "CLAUDE.md"
        claude_conflict.write_text("claude\n", encoding="utf-8")
        agent_conflict = self.home / ".agents" / "skills" / "api-design"
        agent_conflict.parent.mkdir(parents=True)
        agent_conflict.write_text("agent\n", encoding="utf-8")
        result = run_setup(self.repository, self.home, "--all", "--replace-conflicts")
        self.assertEqual(result.returncode, 0, result.stderr)
        claude_timestamp = next((self.home / ".claude" / "backups").iterdir()).name
        codex_timestamp = next((self.home / ".codex" / "backups").iterdir()).name
        self.assertEqual(claude_timestamp, codex_timestamp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
