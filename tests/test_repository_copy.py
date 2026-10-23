#!/usr/bin/env python3
"""setup 系のテストが使うリポジトリの写しを検証する。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from git_fixture import git  # noqa: E402
from repository_copy import copy_repository  # noqa: E402


def make_source(base: Path) -> Path:
    """ignore された生成物・未追跡のファイル・symlink を持つリポジトリを作る。"""
    root = base / "source"
    (root / "rules").mkdir(parents=True)
    (root / "skills" / "a").mkdir(parents=True)
    git(root, "init", "-q")
    (root / ".gitignore").write_text("rules/generated.md\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("tracked\n", encoding="utf-8")
    (root / "rules" / "tracked.md").write_text("tracked\n", encoding="utf-8")
    (root / "skills" / "a" / "SKILL.md").write_text("tracked\n", encoding="utf-8")
    (root / "skills" / "link").symlink_to("a")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init")
    # ignore された生成物（rules/persona.md と同じ形）と、git add 前の新しいファイル
    (root / "rules" / "generated.md").write_text("ignored\n", encoding="utf-8")
    (root / "rules" / "untracked.md").write_text("untracked\n", encoding="utf-8")
    return root


class RepositoryCopyTests(unittest.TestCase):
    PATHS = ("CLAUDE.md", "rules", "skills")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source = make_source(self.base)

    def tearDown(self):
        self.temporary.cleanup()

    def copy(self, use_clone):
        target = self.base / ("clone" if use_clone else "plain")
        target.mkdir()
        return copy_repository(target, root=self.source, paths=self.PATHS, use_clone=use_clone)

    def test_copy_keeps_tracked_and_untracked_but_drops_ignored(self):
        # ignore された生成物がリポジトリ直下にだけあると、写し漏れが隠れる（PR #98 の事故）
        for use_clone in (True, False):
            with self.subTest(use_clone=use_clone):
                copied = self.copy(use_clone)
                self.assertTrue((copied / "CLAUDE.md").is_file())
                self.assertTrue((copied / "rules" / "tracked.md").is_file())
                self.assertTrue((copied / "rules" / "untracked.md").is_file())
                self.assertTrue((copied / "skills" / "a" / "SKILL.md").is_file())
                self.assertFalse((copied / "rules" / "generated.md").exists())

    def test_copy_keeps_symlinks(self):
        for use_clone in (True, False):
            with self.subTest(use_clone=use_clone):
                link = self.copy(use_clone) / "skills" / "link"
                self.assertTrue(link.is_symlink())
                self.assertEqual(str(link.readlink()), "a")

    def test_writing_to_copy_leaves_source_unchanged(self):
        # clonefile は copy-on-write。ハードリンク（ADR 0029 で却下）と違い、元を書き換えない
        for use_clone in (True, False):
            with self.subTest(use_clone=use_clone):
                copied = self.copy(use_clone)
                (copied / "rules" / "tracked.md").write_text("changed\n", encoding="utf-8")
                self.assertEqual(
                    (self.source / "rules" / "tracked.md").read_text(encoding="utf-8"), "tracked\n")

    def test_copy_without_git_metadata_of_source(self):
        copied = self.copy(True)
        self.assertFalse((copied / ".git").exists())
        status = subprocess.run(["git", "-C", str(self.source), "status", "--short"],
                                check=True, capture_output=True, text=True).stdout
        self.assertIn("rules/untracked.md", status)


if __name__ == "__main__":
    unittest.main()
