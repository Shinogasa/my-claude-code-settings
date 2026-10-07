#!/usr/bin/env python3
"""setup の衝突検出と ownership state を実ファイルで検証する。"""
import hashlib
import errno
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
REAL_GIT = shutil.which("git")


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


def tracked_git(repository: Path, home: Path, *arguments: str):
    """一時HOME内のGitだけを、利用者の設定・署名・hookから分離して使う。"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(HOME=str(home), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(
        [REAL_GIT, "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null",
         "-C", str(repository), *arguments],
        check=True, capture_output=True, text=True, env=env,
    )


def initialize_repository_tracking(repository: Path, home: Path):
    """複製先の同期領域を除き、移行テストに必要な追跡状態を作る。"""
    synced = repository / "skills" / "synced"
    if synced.is_symlink() or synced.is_file():
        synced.unlink()
    elif synced.exists():
        shutil.rmtree(synced)
    tracked_git(repository, home, "init", "-q")
    tracked_git(repository, home, "add", "skills")
    tracked_git(repository, home, "commit", "-q", "-m", "移行テストの初期状態")


def load_state_module(path=STATE_MODULE):
    spec = importlib.util.spec_from_file_location("setup_state", path)
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
        "if [ \"${SETUP_REAL_GIT:-}\" != '' ] && [ \"${3:-}\" = ls-files ]; then exec \"$SETUP_REAL_GIT\" \"$@\"; fi\n"
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

    def test_owned_digest_ignores_unowned_keys_but_not_owned_edits(self):
        keys = ("model_provider", "mcp_servers")
        self.destination.write_text('model_provider = "openai"\n', encoding="utf-8")
        recorded = self.state.owned_toml_digest(self.destination, keys)
        self.destination.write_text('model_provider = "openai"\nmodel = "x"\n', encoding="utf-8")
        self.assertEqual(
            self.state.classify(self.source, self.destination, recorded, owned_keys=keys),
            "managed-update",
        )
        self.destination.write_text('model_provider = "gateway"\n', encoding="utf-8")
        self.assertEqual(
            self.state.classify(self.source, self.destination, recorded, owned_keys=keys),
            "conflict",
        )

    def test_owned_digest_with_unserializable_value_is_conflict(self):
        # JSON にできない値で落ちると分類が止まる。判定できないなら競合として人に見せる。
        keys = ("model_provider",)
        self.destination.write_text('model_provider = "openai"\n', encoding="utf-8")
        recorded = self.state.owned_toml_digest(self.destination, keys)
        self.destination.write_text("model_provider = 2026-10-01T00:00:00Z\n", encoding="utf-8")
        self.assertEqual(
            self.state.classify(self.source, self.destination, recorded, owned_keys=keys),
            "conflict",
        )

    def test_owned_digest_recorded_for_other_keys_is_conflict(self):
        # 所有キーが増えた後に古い記録で照合すると、増えたキーの手編集を見逃す。
        self.destination.write_text('model_provider = "openai"\n', encoding="utf-8")
        recorded = self.state.owned_toml_digest(self.destination, ("model_provider",))
        self.assertEqual(
            self.state.classify(
                self.source, self.destination, recorded,
                owned_keys=("model_provider", "mcp_servers"),
            ),
            "conflict",
        )

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
        agent_skill = home / ".agents" / "skills" / "backend-patterns"
        self.assertEqual(
            self.state.backup_path(home / ".codex", agent_skill, "20260821_010203", home),
            home / ".codex" / "backups" / "20260821_010203" / ".agents" / "skills" / "backend-patterns",
        )
        with self.assertRaises(ValueError):
            self.state.backup_path(home / ".codex", self.base / "outside", "20260821_010203", home)


class SetupPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        # macOSのtempfileは`/var`を返すが、`/var`は`/private/var`へのsymlink。
        # setup対象HOMEの安全検査が中間symlinkを正しく拒否するため、fixtureは実体パスで作る。
        self.base = Path(self.temporary.name).resolve()
        self.repository = copy_repository(self.base)
        self.home = self.base / "home"
        self.home.mkdir()
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_host_root_resolving_into_repository_is_rejected_without_changes(self):
        """配布先の実体がrepo内なら、退避もリンク作成もせずに止まる。

        backup_path は配布先を字句的にしか検査しないため、ホストのルートがrepoを指すと
        退避の rename がrepoのファイルを動かし、ln -s がrepo内へリンクを作る。
        """
        # 配布元を含まないrepo内ディレクトリを指す。配布元と重なると別の検査で止まり、
        # この経路を検査できない。
        codex_root = self.home / ".codex"
        codex_root.rmdir()
        repo_dir = self.repository / "unrelated-dir"
        repo_dir.mkdir()
        codex_root.symlink_to(repo_dir, target_is_directory=True)
        planted = repo_dir / "personal.config.toml"
        planted.write_text('model = "repo-owned"\n', encoding="utf-8")

        result = run_setup(self.repository, self.home, "--codex", "--replace-conflicts")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("リポジトリ内", result.stderr)
        self.assertEqual(sorted(path.name for path in repo_dir.iterdir()), ["personal.config.toml"])
        self.assertEqual(planted.read_text(encoding="utf-8"), 'model = "repo-owned"\n')

    def test_migration_fixture_tracks_skills_but_excludes_synced(self):
        """移行用の複製repoはskillを追跡し、同期領域を追跡に混ぜない。"""
        synced = self.repository / "skills" / "synced"
        synced.mkdir(exist_ok=True)
        (synced / "fixture-marker").write_text("copied sync\n", encoding="utf-8")
        initialize_repository_tracking(self.repository, self.home)
        self.assertTrue((self.repository / ".git").is_dir())
        self.assertFalse(synced.exists())
        self.assertEqual(
            tracked_git(self.repository, self.home, "ls-files", "--", "skills/backend-patterns/SKILL.md").stdout,
            "skills/backend-patterns/SKILL.md\n",
        )
        self.assertEqual(tracked_git(self.repository, self.home, "status", "--porcelain").stdout.count("?? skills/"), 0)

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
        manifest["shared"].append("backend-patterns")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        conflict = self.home / ".claude" / "skills" / "backend-patterns"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("user-owned\n", encoding="utf-8")

        result = run_setup(
            self.repository,
            self.home,
            "--claude",
            "--replace-conflicts",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backend-patterns", result.stderr)
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
        agent_skill = self.home / ".agents" / "skills" / "backend-patterns"
        agent_skill.parent.mkdir(parents=True)
        agent_skill.write_text("unowned\n", encoding="utf-8")
        result = run_setup(self.repository, self.home, "--all", "--replace-conflicts")
        self.assertEqual(result.returncode, 0, result.stderr)
        backups = list((self.home / ".codex" / "backups").rglob("backend-patterns"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "unowned\n")
        self.assertTrue(agent_skill.is_symlink())

    def legacy_parent(self, host=".claude"):
        """このrepoだけを指す旧形式リンクを一時HOMEに用意する。"""
        initialize_repository_tracking(self.repository, self.home)
        parent = self.home / host / "skills"
        parent.parent.mkdir(exist_ok=True)
        parent.symlink_to(self.repository / "skills", target_is_directory=True)
        return parent

    def run_tracked_setup(self, *arguments, extra_env=None):
        """移行の追跡判定だけを実Gitで検査し、他の外部操作はstubに留める。"""
        env = {"SETUP_REAL_GIT": REAL_GIT, "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_CONFIG_NOSYSTEM": "1"}
        if extra_env:
            env.update(extra_env)
        return run_setup(self.repository, self.home, *arguments, extra_env=env)

    def assert_manifest_links(self, parent, host):
        """親は実ディレクトリ、選択ホストのskillだけはrepoへの個別リンクになる。"""
        self.assertTrue(parent.is_dir())
        self.assertFalse(parent.is_symlink())
        manifest = json.loads((self.repository / "manifests/skills.json").read_text())
        for name in manifest["shared"] + manifest[host]:
            with self.subTest(skill=name):
                source = self.repository / "skills" / name
                self.assertTrue((parent / name).is_symlink())
                self.assertEqual((parent / name).resolve(), source.resolve())
                self.assertTrue((source / "SKILL.md").is_file())

    def migration_function(self):
        """複製repoの実処理を読み、失敗注入はOS操作の境界だけに置く。"""
        state = load_state_module(self.repository / "bin/setup-state.py")
        migrate = getattr(state, "migrate_legacy_skills_parent", None)
        self.assertTrue(callable(migrate), "旧形式親リンクの移行処理が未実装")
        return state, migrate

    def test_legacy_claude_parent_migrates_to_manifest_links(self):
        """1: --claudeだけで旧形式を移行し、全skillのソースを残す。"""
        parent = self.legacy_parent()
        result = self.run_tracked_setup("--claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_manifest_links(parent, "claude")
        self.assertIn("旧形式", result.stderr)
        self.assertIn(str(parent), result.stderr)

    def test_codex_migrates_agent_skills_parent_symlink_to_repository(self):
        """2: 旧拒否契約を置換し、--codexだけで個別skillリンクへ移行する。"""
        parent = self.legacy_parent(".agents")
        result = self.run_tracked_setup("--codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_manifest_links(parent, "codex")
        self.assertFalse((self.home / ".codex/backups").exists())

    def test_legacy_parent_moves_synced_and_other_untracked_items(self):
        """3: synced以外の追跡外項目も移し、元repoに置き去りにしない。"""
        parent = self.legacy_parent()
        synced = self.repository / "skills/synced/x/SKILL.md"
        synced.parent.mkdir(parents=True)
        synced.write_text("同期skill\n", encoding="utf-8")
        personal = self.repository / "skills/personal-note"
        personal.write_text("個人の追跡外項目\n", encoding="utf-8")
        result = self.run_tracked_setup("--claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((parent / "synced/x/SKILL.md").read_text(), "同期skill\n")
        self.assertEqual((parent / "personal-note").read_text(), "個人の追跡外項目\n")
        self.assertFalse((self.repository / "skills/synced").exists())
        self.assertFalse(personal.exists())
        self.assertIn("synced", result.stderr)
        self.assertIn("personal-note", result.stderr)

    def test_legacy_parent_with_conflict_stops_before_migration(self):
        """競合で止まるなら移行もしない。移行だけ済むとskillsが空のまま残る。"""
        parent = self.legacy_parent()
        synced = self.repository / "skills/synced/x/SKILL.md"
        synced.parent.mkdir(parents=True)
        synced.write_text("同期skill\n", encoding="utf-8")
        settings = self.home / ".claude/settings.json"
        settings.write_text('{"user": "owned"}\n', encoding="utf-8")

        result = self.run_tracked_setup("--claude")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("conflict:", result.stderr)
        self.assertTrue(parent.is_symlink())
        self.assertEqual(parent.resolve(), (self.repository / "skills").resolve())
        self.assertEqual(synced.read_text(encoding="utf-8"), "同期skill\n")
        self.assertEqual(list(parent.parent.glob("skills.migrating.*")), [])
        self.assertEqual(settings.read_text(encoding="utf-8"), '{"user": "owned"}\n')

    def test_legacy_parent_with_replaced_conflict_migrates_and_links(self):
        """置換を指示した競合なら、移行・退避・リンク作成まで1回で完了する。"""
        parent = self.legacy_parent()
        settings = self.home / ".claude/settings.json"
        settings.write_text('{"user": "owned"}\n', encoding="utf-8")

        result = self.run_tracked_setup("--claude", "--replace-conflicts")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_manifest_links(parent, "claude")
        backups = list((self.home / ".claude/backups").rglob("settings.json"))
        self.assertEqual(len(backups), 1)

    def test_legacy_parent_keeps_tracked_skill_content_and_inode(self):
        """4: git追跡中のskillは内容・inodeとも変えずrepoに残す。"""
        self.legacy_parent()
        source = self.repository / "skills/backend-patterns/SKILL.md"
        before = (source.read_bytes(), source.stat().st_ino)
        result = self.run_tracked_setup("--claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((source.read_bytes(), source.stat().st_ino), before)

    def test_legacy_parent_rejects_other_repository_even_with_replace(self):
        """5: 別の置き場への親symlinkは置換フラグ付きでも無変更で拒否する。"""
        initialize_repository_tracking(self.repository, self.home)
        elsewhere = self.base / "other-skills"
        elsewhere.mkdir()
        marker = elsewhere / "user-owned"
        marker.write_text("維持\n", encoding="utf-8")
        parent = self.home / ".claude/skills"
        parent.symlink_to(elsewhere, target_is_directory=True)
        before = (os.readlink(parent), parent.lstat().st_ino, marker.read_bytes())
        result = self.run_tracked_setup("--claude", "--replace-conflicts")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("自動移行しない", result.stderr)
        self.assertIn(str(parent), result.stderr)
        self.assertEqual((os.readlink(parent), parent.lstat().st_ino, marker.read_bytes()), before)
        self.assertEqual(list(elsewhere.iterdir()), [marker])
        self.assertFalse((self.home / ".claude/backups").exists())

    def test_legacy_parent_rejects_broken_symlink_without_changes(self):
        """6: 壊れた親リンクの由来を推測せず無変更で拒否する。"""
        initialize_repository_tracking(self.repository, self.home)
        parent = self.home / ".claude/skills"
        parent.symlink_to(self.base / "missing-skills")
        before = (os.readlink(parent), parent.lstat().st_ino)
        result = self.run_tracked_setup("--claude", "--replace-conflicts")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((os.readlink(parent), parent.lstat().st_ino), before)
        self.assertFalse((self.home / ".claude/backups").exists())

    def test_legacy_parent_refuses_leftover_migration_directory(self):
        """7: 途中状態を上書きせず、そのパスを表示して停止する。"""
        parent = self.legacy_parent()
        temporary = parent.with_name("skills.migrating.X")
        temporary.mkdir()
        marker = temporary / "preserved"
        marker.write_text("復旧用\n", encoding="utf-8")
        before = parent.lstat().st_ino
        result = self.run_tracked_setup("--claude")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(temporary), result.stderr)
        self.assertTrue(parent.is_symlink())
        self.assertEqual(parent.lstat().st_ino, before)
        self.assertEqual(marker.read_text(), "復旧用\n")

    def test_legacy_parent_migration_is_idempotent(self):
        """8: 再実行しても親・個別リンク・追跡外項目を作り直さない。"""
        parent = self.legacy_parent()
        note = self.repository / "skills/user-note"
        note.write_text("維持\n", encoding="utf-8")
        first = self.run_tracked_setup("--claude")
        self.assertEqual(first.returncode, 0, first.stderr)
        before = {path.name: path.lstat().st_ino for path in parent.iterdir()}
        parent_inode = parent.stat().st_ino
        second = self.run_tracked_setup("--claude")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual({path.name: path.lstat().st_ino for path in parent.iterdir()}, before)
        self.assertEqual(parent.stat().st_ino, parent_inode)
        self.assertEqual((parent / "user-note").read_text(), "維持\n")
        self.assertNotIn("旧形式", second.stderr)

    def test_legacy_parent_does_not_migrate_unselected_host(self):
        """9: --codexだけの実行ではClaudeの旧形式リンクへ触れない。"""
        parent = self.legacy_parent()
        before = (os.readlink(parent), parent.lstat().st_ino)
        result = self.run_tracked_setup("--codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((os.readlink(parent), parent.lstat().st_ino), before)

    def test_legacy_parent_rolls_back_after_second_untracked_move_fails(self):
        """10: 2項目目のrenameにEACCESを注入し、1項目目を実際に戻す。"""
        parent = self.legacy_parent()
        items = [self.repository / "skills" / name for name in ("untracked-a", "untracked-b")]
        for item in items:
            item.write_text(item.name, encoding="utf-8")
        before = {item: (item.read_bytes(), item.stat().st_ino) for item in items}
        parent_inode = parent.lstat().st_ino
        state, migrate = self.migration_function()
        real_rename = os.rename
        moved = []

        def fail_second_move(source, destination):
            if Path(source) == items[1]:
                raise PermissionError(errno.EACCES, "テストで移動を拒否", str(source))
            result = real_rename(source, destination)
            moved.append((Path(source), Path(destination)))
            return result

        with mock.patch.object(state.os, "rename", side_effect=fail_second_move):
            with self.assertRaisesRegex(RuntimeError, "テストで移動を拒否"):
                migrate(parent, self.repository / "skills", self.repository)
        self.assertTrue(parent.is_symlink())
        self.assertEqual(parent.lstat().st_ino, parent_inode)
        self.assertEqual({item: (item.read_bytes(), item.stat().st_ino) for item in items}, before)
        self.assertEqual(len(moved), 2, "1項目目の移動と巻き戻しを実OS上で行う")
        self.assertEqual(moved[1], (moved[0][1], items[0]))
        self.assertEqual(list(parent.parent.glob("skills.migrating.*")), [])

    def test_legacy_parent_inside_repository_is_not_migrated(self):
        """判定条件3: ホストの親がrepo内へ解決される場合は移行しない。"""
        initialize_repository_tracking(self.repository, self.home)
        host = self.repository / "host"
        host.mkdir()
        claude = self.home / ".claude"
        claude.rmdir()
        claude.symlink_to(host, target_is_directory=True)
        parent = host / "skills"
        parent.symlink_to(self.repository / "skills", target_is_directory=True)
        before = parent.lstat().st_ino
        result = self.run_tracked_setup("--claude", "--replace-conflicts")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(parent.is_symlink())
        self.assertEqual(parent.lstat().st_ino, before)
        self.assertEqual(list(host.iterdir()), [parent])

    def test_legacy_parent_relative_link_is_migrated(self):
        """判定条件2: 相対リンクもPath.resolve同士の一致で旧形式と判定する。"""
        parent = self.legacy_parent()
        parent.unlink()
        parent.symlink_to(os.path.relpath(self.repository / "skills", parent.parent))
        result = self.run_tracked_setup("--claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_manifest_links(parent, "claude")

    def test_legacy_parent_treats_untracked_names_as_literal_git_paths(self):
        """追跡外の「*」という名前をGitのpatternと取り違えて置き去りにしない。"""
        parent = self.legacy_parent()
        item = self.repository / "skills" / "*"
        item.write_text("追跡外の実ファイル\n", encoding="utf-8")
        _, migrate = self.migration_function()
        migrate(parent, self.repository / "skills", self.repository)
        self.assertTrue((parent / "*").is_file(), "追跡外の名前はpatternではなく実項目として移す")
        self.assertEqual((parent / "*").read_text(), "追跡外の実ファイル\n")
        self.assertFalse(item.exists())

    def test_legacy_parent_missing_with_leftover_stops_before_apply(self):
        """unlink後に停止した状態では、再実行も途中領域を上書きしない。"""
        parent = self.legacy_parent()
        parent.unlink()
        temporary = parent.with_name("skills.migrating.X")
        temporary.mkdir()
        result = self.run_tracked_setup("--claude")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(str(temporary), result.stderr)
        self.assertFalse(parent.exists())
        self.assertEqual(list(temporary.iterdir()), [])

    def test_legacy_parent_git_failure_does_not_move_items(self):
        """追跡状態の検査失敗を追跡外とみなさず、変更前にexit 1にする。"""
        parent = self.legacy_parent()
        note = self.repository / "skills/untracked-a"
        note.write_text("維持\n", encoding="utf-8")
        result = self.run_tracked_setup("--claude", extra_env={"SETUP_GIT_EXIT": "23"})
        self.assertEqual(result.returncode, 1)
        self.assertTrue(parent.is_symlink())
        self.assertEqual(note.read_text(), "維持\n")
        self.assertEqual(list(parent.parent.glob("skills.migrating.*")), [])

    def test_legacy_parent_retries_final_rename_once(self):
        """unlink後のrenameが一度失敗しても、直ちに再試行して完成させる。"""
        parent = self.legacy_parent()
        note = self.repository / "skills/untracked-a"
        note.write_text("維持\n", encoding="utf-8")
        state, migrate = self.migration_function()
        real_rename = os.rename
        failed = []

        def fail_first_final_rename(source, destination):
            if Path(destination) == parent and not failed:
                failed.append(Path(source))
                raise PermissionError(errno.EACCES, "一度だけ拒否", str(source))
            return real_rename(source, destination)

        with mock.patch.object(state.os, "rename", side_effect=fail_first_final_rename):
            migrate(parent, self.repository / "skills", self.repository)
        self.assertEqual(len(failed), 1)
        self.assertFalse(parent.is_symlink())
        self.assertEqual((parent / note.name).read_text(), "維持\n")
        self.assertFalse(note.exists())
        self.assertEqual(list(parent.parent.glob("skills.migrating.*")), [])

    def test_legacy_parent_final_rename_failure_reports_manual_recovery(self):
        """再試行も失敗したら項目を一時領域に保存し、mvでの復旧手順を示す。"""
        parent = self.legacy_parent()
        note = self.repository / "skills/untracked-a"
        note.write_text("維持\n", encoding="utf-8")
        state, migrate = self.migration_function()
        real_rename = os.rename
        failed = []

        def fail_final_rename(source, destination):
            if Path(destination) == parent:
                failed.append(Path(source))
                raise PermissionError(errno.EACCES, "最終rename拒否", str(source))
            return real_rename(source, destination)

        with mock.patch.object(state.os, "rename", side_effect=fail_final_rename):
            with self.assertRaises(RuntimeError) as error:
                migrate(parent, self.repository / "skills", self.repository)
        self.assertEqual(len(failed), 2)
        temporary, = parent.parent.glob("skills.migrating.*")
        self.assertIn(str(temporary), str(error.exception))
        self.assertIn(f"mv {temporary} {parent}", str(error.exception))
        self.assertEqual((temporary / note.name).read_text(), "維持\n")
        self.assertFalse(parent.exists())

    def test_legacy_parent_rollback_failure_reports_preserved_paths(self):
        """巻き戻しも失敗した項目は消さず、保存パスをエラーに列挙する。"""
        parent = self.legacy_parent()
        first, second = [self.repository / "skills" / name for name in ("untracked-a", "untracked-b")]
        first.write_text("先に移した項目\n", encoding="utf-8")
        second.write_text("移動失敗項目\n", encoding="utf-8")
        state, migrate = self.migration_function()
        real_rename = os.rename

        def fail_move_and_rollback(source, destination):
            if Path(source) == second or Path(destination) == first:
                raise PermissionError(errno.EACCES, "移動と巻き戻しを拒否", str(source))
            return real_rename(source, destination)

        with mock.patch.object(state.os, "rename", side_effect=fail_move_and_rollback):
            with self.assertRaises(RuntimeError) as error:
                migrate(parent, self.repository / "skills", self.repository)
        temporary, = parent.parent.glob("skills.migrating.*")
        self.assertIn(str(temporary / first.name), str(error.exception))
        self.assertEqual((temporary / first.name).read_text(), "先に移した項目\n")
        self.assertEqual(second.read_text(), "移動失敗項目\n")
        self.assertTrue(parent.is_symlink())

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
        agent_conflict = self.home / ".agents" / "skills" / "backend-patterns"
        agent_conflict.parent.mkdir(parents=True)
        agent_conflict.write_text("agent\n", encoding="utf-8")
        result = run_setup(self.repository, self.home, "--all", "--replace-conflicts")
        self.assertEqual(result.returncode, 0, result.stderr)
        claude_timestamp = next((self.home / ".claude" / "backups").iterdir()).name
        codex_timestamp = next((self.home / ".codex" / "backups").iterdir()).name
        self.assertEqual(claude_timestamp, codex_timestamp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
