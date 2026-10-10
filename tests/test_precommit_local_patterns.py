#!/usr/bin/env python3
"""pre-commit が worktree でも本体の patterns-local.txt を読むことを検証する（ADR 0031）。"""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from git_fixture import git  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-commit"


def load_hook_module():
    """拡張子を持たないフック本体を、モジュールとして読み込む。"""
    loader = importlib.machinery.SourceFileLoader("precommit_hook_local", str(HOOK))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


hook = load_hook_module()


class FindLocalPatternsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.main = self.base / "main"
        (self.main / ".githooks").mkdir(parents=True)
        git(self.main, "init", "-q")
        git(self.main, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
            "commit", "-q", "--allow-empty", "-m", "init")
        self.worktree = self.base / "wt"
        git(self.main, "worktree", "add", "-q", "--detach", str(self.worktree))
        (self.worktree / ".githooks").mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_worktree_reads_main_patterns(self):
        main_patterns = self.main / ".githooks" / "patterns-local.txt"
        main_patterns.write_text("placeholder-name\n", encoding="utf-8")
        self.assertEqual(hook.find_local_patterns(self.worktree / ".githooks"), main_patterns)

    def test_returns_none_when_missing_everywhere(self):
        self.assertIsNone(hook.find_local_patterns(self.worktree / ".githooks"))

    def test_ignores_git_dir_environment(self):
        main_patterns = self.main / ".githooks" / "patterns-local.txt"
        main_patterns.write_text("placeholder-name\n", encoding="utf-8")
        # 無関係なリポジトリを指させる。GIT_DIRを外さない実装は、こちらを探して None を返す
        unrelated = self.base / "unrelated"
        unrelated.mkdir()
        git(unrelated, "init", "-q")
        env = {"GIT_DIR": str(unrelated / ".git")}
        with unittest.mock.patch.dict(os.environ, env):
            self.assertEqual(hook.find_local_patterns(self.worktree / ".githooks"), main_patterns)

    def test_prefers_own_patterns(self):
        own = self.worktree / ".githooks" / "patterns-local.txt"
        own.write_text("placeholder-name\n", encoding="utf-8")
        (self.main / ".githooks" / "patterns-local.txt").write_text("other\n", encoding="utf-8")
        self.assertEqual(hook.find_local_patterns(self.worktree / ".githooks"), own)

    def test_outside_git_returns_none(self):
        outside = self.base / "plain" / ".githooks"
        outside.mkdir(parents=True)
        self.assertIsNone(hook.find_local_patterns(outside))


if __name__ == "__main__":
    unittest.main()
