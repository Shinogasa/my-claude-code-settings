#!/usr/bin/env python3
"""Codexのモデル間handoff契約を実ファイルとGit状態で検証する。"""
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
import re
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "validate-codex-handoff.py"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("validate_codex_handoff", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CodexHandoffValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator_module()

    @unittest.skipUnless(Path("/usr/bin/python3").is_file(), "macOS system Python is unavailable")
    def test_cli_imports_with_macos_system_python(self):
        result = subprocess.run(
            ["/usr/bin/python3", str(SCRIPT), "--help"],
            text=True, capture_output=True, check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary.name).resolve() / "repository"
        self.repository.mkdir()
        self.xdg_config = self.repository.parent / "xdg"
        self.xdg_config.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test User")
        (self.repository / ".gitignore").write_text("# intentionally empty\n", encoding="utf-8")
        (self.repository / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self.git("add", ".gitignore", "tracked.txt")
        self.git("commit", "-m", "initial")
        self.handoff = self.repository / ".superpowers" / "handoffs" / "task.md"
        self.handoff.parent.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["XDG_CONFIG_HOME"] = str(self.xdg_config)
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

    def run_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["XDG_CONFIG_HOME"] = str(self.xdg_config)
        return subprocess.run(
            ["python3", str(SCRIPT), *arguments],
            cwd=self.repository,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def current_state(self) -> dict:
        result = self.run_script("state", "--repo", str(self.repository))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write_handoff(self, **overrides) -> None:
        state = self.current_state()
        values = {
            "task_id": "test-task",
            "branch": state["branch"],
            "head": state["head"],
            "worktree_fingerprint": state["worktree_fingerprint"],
            "target_model": "gpt-5.6-luna",
            "target_reasoning_effort": "medium",
            "requirements_path": "none",
            "requirements_sha256": "none",
            "review_package_path": "none",
            "review_package_sha256": "none",
        }
        values.update(overrides)
        self.handoff.write_text(
            f"""---
handoff_schema: 1
task_id: {values['task_id']}
branch: {values['branch']}
head: {values['head']}
worktree_fingerprint: {values['worktree_fingerprint']}
target_model: {values['target_model']}
target_reasoning_effort: {values['target_reasoning_effort']}
requirements_path: {values['requirements_path']}
requirements_sha256: {values['requirements_sha256']}
review_package_path: {values['review_package_path']}
review_package_sha256: {values['review_package_sha256']}
---
# Test handoff

## 目的と対象外
目的を達成する。別機能は変更しない。

## Git状態
stage済み差分がある。

## 確定済み設計判断と根拠
既存契約を維持する。

## 対象ファイルと作業所有範囲
`tracked.txt`だけを所有する。

## 受入条件と検証コマンド
`python3 -m unittest`が成功する。

## 制約
providerを変更しない。

## 未解決事項
なし。

## 実行モデル
frontmatterのmodelとeffortを使う。

## 返却レポート契約
状態、変更、検証、懸念を返す。
""",
            encoding="utf-8",
        )

    def validate(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_script(
            "validate",
            str(self.handoff),
            "--repo",
            str(self.repository),
            *extra,
        )

    def test_valid_handoff_is_accepted_for_expected_pair(self):
        self.write_handoff()

        result = self.validate(
            "--expected-model",
            "gpt-5.6-luna",
            "--expected-reasoning-effort",
            "medium",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("VALID", result.stdout)

    def test_state_rejects_local_core_worktree_outside_requested_repo(self):
        outside = self.repository.parent / "outside-worktree"
        outside.mkdir()
        self.git("config", "core.worktree", str(outside))

        result = self.run_script("state", "--repo", str(self.repository))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_CONTEXT", result.stderr)

    def test_state_requires_repo_argument_to_match_git_root_inode(self):
        nested = self.repository / "nested"
        nested.mkdir()

        result = self.run_script("state", "--repo", str(nested))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_CONTEXT", result.stderr)
        self.assertIn("repository root does not match --repo", result.stderr)

    def test_state_ignores_inherited_git_repository_selection_environment(self):
        injected = self.repository.parent / "injected-repository"
        injected.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=injected,
            text=True,
            capture_output=True,
            check=True,
        )
        for key, value in (
            ("user.email", "test@example.invalid"),
            ("user.name", "Test User"),
        ):
            subprocess.run(["git", "config", key, value], cwd=injected, check=True)
        (injected / "outside.txt").write_text("outside\n", encoding="utf-8")
        subprocess.run(["git", "add", "outside.txt"], cwd=injected, check=True)
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-m", "outside"],
            cwd=injected,
            text=True,
            capture_output=True,
            check=True,
        )
        env = os.environ.copy()
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["XDG_CONFIG_HOME"] = str(self.xdg_config)
        env["GIT_DIR"] = str(injected / ".git")
        env["GIT_WORK_TREE"] = str(injected)
        env["GIT_INDEX_FILE"] = str(injected / ".git/index")

        result = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "state",
                "--repo",
                str(self.repository),
            ],
            cwd=self.repository,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["branch"], "main")
        self.assertEqual(state["head"], self.git("rev-parse", "HEAD").stdout.strip())

    def test_state_keeps_dot_bound_to_cwd_when_path_is_swapped_before_open(self):
        original_head = self.git("rev-parse", "HEAD").stdout.strip()
        replacement = self.repository.parent / "replacement-before-open"
        subprocess.run(
            ["git", "clone", str(self.repository), str(replacement)],
            text=True,
            capture_output=True,
            check=True,
        )
        (replacement / "replacement.txt").write_text(
            "replacement only\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "replacement.txt"], cwd=replacement, check=True)
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-m", "replacement"],
            cwd=replacement,
            text=True,
            capture_output=True,
            check=True,
        )
        displaced = self.repository.parent / "displaced-before-open"
        real_open = self.validator.os.open
        swapped = False

        def swap_before_first_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if not swapped:
                swapped = True
                self.repository.rename(displaced)
                replacement.rename(self.repository)
            return real_open(path, flags, *args, **kwargs)

        previous_cwd = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            os.chdir(self.repository)
            with (
                mock.patch.object(
                    self.validator.os, "open", side_effect=swap_before_first_open
                ),
                mock.patch.object(
                    self.validator.sys,
                    "argv",
                    [str(SCRIPT), "state", "--repo", "."],
                ),
                mock.patch.object(self.validator.sys, "stdout", stdout),
                mock.patch.object(self.validator.sys, "stderr", stderr),
            ):
                returncode = self.validator.main()
        finally:
            os.fchdir(previous_cwd)
            os.close(previous_cwd)

        self.assertEqual(returncode, 0, stderr.getvalue())
        self.assertTrue(swapped)
        self.assertEqual(json.loads(stdout.getvalue())["head"], original_head)

    def test_state_rejects_symlink_in_repository_path(self):
        linked_parent = self.repository.parent / "linked-parent"
        linked_parent.symlink_to(self.repository.parent, target_is_directory=True)

        result = self.run_script(
            "state", "--repo", str(linked_parent / self.repository.name)
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_CONTEXT", result.stderr)
        self.assertIn("repository root could not be opened safely", result.stderr)

    def test_state_keeps_using_verified_root_after_directory_swap(self):
        original_head = self.git("rev-parse", "HEAD").stdout.strip()
        replacement = self.repository.parent / "replacement-root"
        subprocess.run(
            ["git", "clone", str(self.repository), str(replacement)],
            text=True,
            capture_output=True,
            check=True,
        )
        for key, value in (
            ("user.email", "test@example.invalid"),
            ("user.name", "Test User"),
        ):
            subprocess.run(["git", "config", key, value], cwd=replacement, check=True)
        (replacement / "replacement.txt").write_text(
            "replacement only\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "replacement.txt"], cwd=replacement, check=True)
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-m", "replacement"],
            cwd=replacement,
            text=True,
            capture_output=True,
            check=True,
        )
        replacement_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=replacement,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        displaced = self.repository.parent / "verified-root"
        real_repository_root = self.validator.repository_root
        swapped = False

        @contextmanager
        def swap_after_root_verification(path):
            nonlocal swapped
            with real_repository_root(path) as root:
                if not swapped:
                    swapped = True
                    self.repository.rename(displaced)
                    replacement.rename(self.repository)
                yield root

        with mock.patch.object(
            self.validator,
            "repository_root",
            side_effect=swap_after_root_verification,
        ):
            state = self.validator.current_state(self.repository)

        self.assertTrue(swapped)
        self.assertNotEqual(original_head, replacement_head)
        self.assertEqual(state["head"], original_head)

    def test_missing_or_empty_required_section_is_rejected(self):
        for mutation, expected in (
            (
                lambda text: text.replace("## 制約\nproviderを変更しない。\n\n", ""),
                "制約",
            ),
            (
                lambda text: text.replace(
                    "## 未解決事項\nなし。\n\n", "## 未解決事項\n\n"
                ),
                "未解決事項",
            ),
        ):
            with self.subTest(expected=expected):
                self.write_handoff()
                self.handoff.write_text(
                    mutation(self.handoff.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )

                result = self.validate()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("NEEDS_CONTEXT", result.stderr)
                self.assertIn(expected, result.stderr)

    def test_unknown_model_or_reasoning_effort_is_rejected(self):
        for overrides, expected in (
            ({"target_model": "gpt-made-up"}, "target_model"),
            ({"target_reasoning_effort": "extreme"}, "target_reasoning_effort"),
        ):
            with self.subTest(overrides=overrides):
                self.write_handoff(**overrides)

                result = self.validate()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("NEEDS_CONTEXT", result.stderr)
                self.assertIn(expected, result.stderr)

    def test_reasoning_effort_unsupported_by_model_is_rejected(self):
        for model, effort in (
            ("gpt-5.6-luna", "ultra"),
            ("gpt-5.5", "max"),
        ):
            with self.subTest(model=model, effort=effort):
                self.write_handoff(
                    target_model=model,
                    target_reasoning_effort=effort,
                )

                result = self.validate()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("NEEDS_CONTEXT", result.stderr)
                self.assertIn("unsupported model/reasoning pair", result.stderr)

    def test_handoff_is_rejected_after_worktree_content_changes(self):
        self.write_handoff()
        (self.repository / "tracked.txt").write_text("changed\n", encoding="utf-8")

        result = self.validate()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_CONTEXT", result.stderr)
        self.assertIn("worktree_fingerprint", result.stderr)

    def test_worktree_fingerprint_records_nested_tracked_file_deletion(self):
        nested = self.repository / "nested"
        nested.mkdir()
        tracked = nested / "tracked.txt"
        tracked.write_text("tracked\n", encoding="utf-8")
        self.git("add", "nested/tracked.txt")
        self.git("commit", "-m", "add nested tracked file")
        before = self.current_state()["worktree_fingerprint"]
        tracked.unlink()
        nested.rmdir()

        result = self.run_script("state", "--repo", str(self.repository))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(json.loads(result.stdout)["worktree_fingerprint"], before)

    def read_document(
        self, input_digest: str, document: str, *extra: str
    ) -> subprocess.CompletedProcess[str]:
        return self.run_script(
            "read",
            str(self.handoff),
            "--repo",
            str(self.repository),
            "--expected-input-digest",
            input_digest,
            "--document",
            document,
            *extra,
        )

    def test_validated_reader_rejects_handoff_changed_after_validation(self):
        self.write_handoff()
        first = self.validate()
        self.assertEqual(first.returncode, 0, first.stderr)
        match = re.search(r"^INPUT_DIGEST: ([0-9a-f]{64})$", first.stdout, re.MULTILINE)
        self.assertIsNotNone(match, first.stdout)
        original_digest = match.group(1)
        self.handoff.write_text(
            self.handoff.read_text(encoding="utf-8").replace(
                "目的を達成する。", "別の指示へ差し替える。"
            ),
            encoding="utf-8",
        )

        result = self.read_document(original_digest, "handoff")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_CONTEXT", result.stderr)
        self.assertIn("input digest changed before validated read", result.stderr)

    def test_validated_reader_returns_exact_referenced_document_in_chunks(self):
        package = self.repository / "review.diff"
        package.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
        self.write_handoff(
            review_package_path="review.diff",
            review_package_sha256=hashlib.sha256(package.read_bytes()).hexdigest(),
        )
        first = self.validate()
        self.assertEqual(first.returncode, 0, first.stderr)
        match = re.search(r"^INPUT_DIGEST: ([0-9a-f]{64})$", first.stdout, re.MULTILINE)
        self.assertIsNotNone(match, first.stdout)

        result = self.read_document(
            match.group(1),
            "review-package",
            "--start-line",
            "2",
            "--line-count",
            "2",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DOCUMENT: review-package lines 2-3 of 3", result.stdout)
        self.assertTrue(result.stdout.endswith("line 2\nline 3\n"))

    def test_dirty_submodule_is_rejected_even_when_local_config_ignores_it(self):
        submodule_source = self.repository.parent / "submodule-source"
        submodule_source.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=submodule_source,
            text=True,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=submodule_source,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=submodule_source,
            check=True,
        )
        (submodule_source / "source.txt").write_text(
            "initial\n", encoding="utf-8"
        )
        subprocess.run(
            ["git", "add", "source.txt"], cwd=submodule_source, check=True
        )
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-m", "initial"],
            cwd=submodule_source,
            text=True,
            capture_output=True,
            check=True,
        )
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(submodule_source),
            "vendor/example",
        )
        self.git("commit", "-m", "add submodule")
        self.write_handoff()
        self.git("config", "diff.ignoreSubmodules", "all")
        (self.repository / "vendor/example/source.txt").write_text(
            "changed\n", encoding="utf-8"
        )

        result = self.validate()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_CONTEXT", result.stderr)
        self.assertIn("submodule worktree is dirty", result.stderr)

    def test_submodule_check_does_not_execute_clean_filter(self):
        submodule_source = self.repository.parent / "filtered-submodule"
        submodule_source.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=submodule_source,
            text=True,
            capture_output=True,
            check=True,
        )
        for key, value in (
            ("user.email", "test@example.invalid"),
            ("user.name", "Test User"),
        ):
            subprocess.run(
                ["git", "config", key, value], cwd=submodule_source, check=True
            )
        (submodule_source / "source.txt").write_text(
            "initial\n", encoding="utf-8"
        )
        subprocess.run(
            ["git", "add", "source.txt"], cwd=submodule_source, check=True
        )
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-m", "initial"],
            cwd=submodule_source,
            text=True,
            capture_output=True,
            check=True,
        )
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(submodule_source),
            "vendor/filtered",
        )
        self.git("commit", "-m", "add filtered submodule")
        marker = self.repository.parent / "submodule-clean-filter-ran"
        clean_filter = self.repository.parent / "submodule-clean-filter.sh"
        clean_filter.write_text(
            f"#!/bin/sh\ntouch '{marker}'\ncat\n", encoding="utf-8"
        )
        clean_filter.chmod(0o755)
        submodule = self.repository / "vendor/filtered"
        (submodule / ".gitattributes").write_text(
            "source.txt filter=unsafe\n", encoding="utf-8"
        )
        subprocess.run(
            ["git", "add", ".gitattributes"], cwd=submodule, check=True
        )
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-m", "add filter attributes"],
            cwd=submodule,
            text=True,
            capture_output=True,
            check=True,
        )
        self.git("add", "vendor/filtered")
        self.git("commit", "-m", "update filtered submodule")
        subprocess.run(
            ["git", "config", "filter.unsafe.clean", str(clean_filter)],
            cwd=submodule,
            check=True,
        )
        marker.unlink(missing_ok=True)

        result = self.run_script("state", "--repo", str(self.repository))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            marker.exists(), "read-only validatorがsubmodule clean filterを実行した"
        )

    def test_submodule_directory_swap_keeps_git_bound_to_opened_directory(self):
        submodule_source = self.repository.parent / "swap-source"
        submodule_source.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=submodule_source,
            text=True,
            capture_output=True,
            check=True,
        )
        for key, value in (
            ("user.email", "test@example.invalid"),
            ("user.name", "Test User"),
        ):
            subprocess.run(
                ["git", "config", key, value], cwd=submodule_source, check=True
            )
        (submodule_source / "source.txt").write_text(
            "initial\n", encoding="utf-8"
        )
        subprocess.run(
            ["git", "add", "source.txt"], cwd=submodule_source, check=True
        )
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-m", "initial"],
            cwd=submodule_source,
            text=True,
            capture_output=True,
            check=True,
        )
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(submodule_source),
            "vendor/example",
        )
        self.git("commit", "-m", "add swappable submodule")

        replacement = self.repository.parent / "replacement"
        subprocess.run(
            ["git", "clone", str(submodule_source), str(replacement)],
            text=True,
            capture_output=True,
            check=True,
        )
        (replacement / "outside-only.txt").write_text(
            "must not be inspected\n", encoding="utf-8"
        )
        submodule = self.repository / "vendor/example"
        displaced = self.repository / "vendor/example-original"
        real_run_git = self.validator.run_git
        swapped = False

        def swap_before_submodule_git(repo, *arguments):
            nonlocal swapped
            if (
                not swapped
                and (repo == submodule or isinstance(repo, int))
            ):
                swapped = True
                submodule.rename(displaced)
                submodule.symlink_to(replacement, target_is_directory=True)
            return real_run_git(repo, *arguments)

        with mock.patch.object(
            self.validator, "run_git", side_effect=swap_before_submodule_git
        ):
            fingerprint = self.validator.worktree_fingerprint(self.repository)

        self.assertTrue(swapped)
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")

    def test_nested_submodule_swap_keeps_git_bound_to_opened_directory(self):
        leaf_source = self.repository.parent / "nested-leaf-source"
        leaf_source.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=leaf_source,
            text=True,
            capture_output=True,
            check=True,
        )
        for key, value in (
            ("user.email", "test@example.invalid"),
            ("user.name", "Test User"),
        ):
            subprocess.run(["git", "config", key, value], cwd=leaf_source, check=True)
        (leaf_source / "leaf.txt").write_text("leaf\n", encoding="utf-8")
        subprocess.run(["git", "add", "leaf.txt"], cwd=leaf_source, check=True)
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-m", "leaf"],
            cwd=leaf_source,
            text=True,
            capture_output=True,
            check=True,
        )

        parent_source = self.repository.parent / "nested-parent-source"
        parent_source.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=parent_source,
            text=True,
            capture_output=True,
            check=True,
        )
        for key, value in (
            ("user.email", "test@example.invalid"),
            ("user.name", "Test User"),
        ):
            subprocess.run(["git", "config", key, value], cwd=parent_source, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(leaf_source),
                "deps/leaf",
            ],
            cwd=parent_source,
            text=True,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "commit", "-m", "parent"],
            cwd=parent_source,
            text=True,
            capture_output=True,
            check=True,
        )
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(parent_source),
            "vendor/parent",
        )
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
            "--recursive",
        )
        self.git("commit", "-m", "add nested submodule")

        replacement = self.repository.parent / "nested-replacement"
        subprocess.run(
            ["git", "clone", str(leaf_source), str(replacement)],
            text=True,
            capture_output=True,
            check=True,
        )
        (replacement / "outside-only.txt").write_text(
            "must not be inspected\n", encoding="utf-8"
        )
        nested = self.repository / "vendor/parent/deps/leaf"
        displaced = self.repository / "vendor/parent/deps/leaf-original"
        real_open_repo_directory = self.validator.open_repo_directory
        swapped = False

        @contextmanager
        def swap_after_nested_open(repo, relative, label):
            nonlocal swapped
            with real_open_repo_directory(repo, relative, label) as descriptor:
                if not swapped and label == "nested submodule":
                    swapped = True
                    nested.rename(displaced)
                    nested.symlink_to(replacement, target_is_directory=True)
                yield descriptor

        with mock.patch.object(
            self.validator,
            "open_repo_directory",
            side_effect=swap_after_nested_open,
        ):
            fingerprint = self.validator.worktree_fingerprint(self.repository)

        self.assertTrue(swapped)
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")

    def test_worktree_fingerprint_does_not_execute_textconv_driver(self):
        marker = self.repository.parent / "textconv-ran"
        textconv = self.repository.parent / "textconv.sh"
        textconv.write_text(
            f"#!/bin/sh\ntouch '{marker}'\ncat \"$1\"\n",
            encoding="utf-8",
        )
        textconv.chmod(0o755)
        (self.repository / ".gitattributes").write_text(
            "tracked.txt diff=unsafe\n", encoding="utf-8"
        )
        self.git("config", "diff.unsafe.textconv", str(textconv))
        self.git("add", ".gitattributes")
        self.git("commit", "-m", "configure textconv")
        (self.repository / "tracked.txt").write_text(
            "changed\n", encoding="utf-8"
        )

        result = self.run_script("state", "--repo", str(self.repository))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists(), "read-only validatorがtextconvを実行した")

    def test_worktree_fingerprint_does_not_execute_clean_filter(self):
        marker = self.repository.parent / "clean-filter-ran"
        clean_filter = self.repository.parent / "clean-filter.sh"
        clean_filter.write_text(
            f"#!/bin/sh\ntouch '{marker}'\ncat\n",
            encoding="utf-8",
        )
        clean_filter.chmod(0o755)
        (self.repository / ".gitattributes").write_text(
            "tracked.txt filter=unsafe\n", encoding="utf-8"
        )
        self.git("config", "filter.unsafe.clean", str(clean_filter))
        self.git("add", ".gitattributes")
        self.git("commit", "-m", "configure clean filter")
        marker.unlink(missing_ok=True)
        (self.repository / "tracked.txt").write_text(
            "changed\n", encoding="utf-8"
        )

        result = self.run_script("state", "--repo", str(self.repository))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists(), "read-only validatorがclean filterを実行した")

    def test_safe_reader_rejects_intermediate_directory_symlink_swap(self):
        nested = self.repository / "nested"
        nested.mkdir()
        (nested / "artifact.md").write_text("safe\n", encoding="utf-8")
        outside = self.repository.parent / "outside"
        outside.mkdir()
        (outside / "artifact.md").write_text(
            "outside secret\n", encoding="utf-8"
        )
        displaced = self.repository / "nested-original"
        real_open = os.open
        swapped = False

        def swap_before_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if not swapped:
                swapped = True
                nested.rename(displaced)
                nested.symlink_to(outside, target_is_directory=True)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(
            self.validator.os, "open", side_effect=swap_before_open
        ):
            with self.assertRaises(self.validator.HandoffError):
                self.validator.read_safe_repo_file(
                    self.repository, "nested/artifact.md", "artifact"
                )

    def test_referenced_superpowers_artifacts_must_exist_and_match_hash(self):
        for path_field, hash_field, name in (
            ("requirements_path", "requirements_sha256", "task-1-brief.md"),
            ("review_package_path", "review_package_sha256", "task-1-review.md"),
        ):
            with self.subTest(path_field=path_field):
                artifact = self.repository / ".superpowers" / "sdd" / name
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("# Artifact\ncurrent\n", encoding="utf-8")
                digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                self.write_handoff(
                    **{
                        path_field: f".superpowers/sdd/{name}",
                        hash_field: digest,
                    }
                )
                self.assertEqual(self.validate().returncode, 0)

                artifact.write_text("# Artifact\nstale\n", encoding="utf-8")
                result = self.validate()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("NEEDS_CONTEXT", result.stderr)
                self.assertIn(hash_field, result.stderr)

    def test_expected_pair_mismatch_is_rejected(self):
        self.write_handoff()

        result = self.validate(
            "--expected-model",
            "gpt-5.6-terra",
            "--expected-reasoning-effort",
            "high",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_CONTEXT", result.stderr)
        self.assertIn("expected model/reasoning pair", result.stderr)

    def test_symlinked_handoff_or_requirements_is_rejected(self):
        self.write_handoff()
        real_handoff = self.handoff.with_name("real.md")
        self.handoff.replace(real_handoff)
        self.handoff.symlink_to(real_handoff)

        result = self.validate()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_CONTEXT", result.stderr)
        self.assertIn("non-symlink", result.stderr)

        self.handoff.unlink()
        real_handoff.replace(self.handoff)
        brief = self.repository / "brief.md"
        brief.write_text("requirements\n", encoding="utf-8")
        brief_link = self.repository / "brief-link.md"
        brief_link.symlink_to(brief)
        self.write_handoff(
            requirements_path="brief-link.md",
            requirements_sha256=hashlib.sha256(brief.read_bytes()).hexdigest(),
        )

        result = self.validate()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NEEDS_CONTEXT", result.stderr)
        self.assertIn("non-symlink", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
