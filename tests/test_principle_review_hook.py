#!/usr/bin/env python3
"""hooks/principle-review.py の振る舞いを、合成した入力と一時リポジトリで検証する。

実行: python3 -m unittest tests.test_principle_review_hook
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from tests.git_fixture import git
except ImportError:
    from git_fixture import git

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "principle-review.py"
_spec = importlib.util.spec_from_file_location("principle_review", HOOK)
principle_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(principle_review)


class ClassifyTests(unittest.TestCase):
    def test_spec_and_plan_locations(self):
        self.assertEqual(principle_review.classify("docs/superpowers/specs/a.md"), "spec")
        self.assertEqual(principle_review.classify("docs/specs/a.md"), "spec")
        self.assertEqual(principle_review.classify("docs/adr/0001-x.md"), "spec")
        self.assertEqual(principle_review.classify("docs/superpowers/plans/a.md"), "plan")
        self.assertEqual(principle_review.classify("docs/plans/a.md"), "plan")

    def test_other_files_are_not_targets(self):
        for path in ("docs/adr/README.md", "docs/specs/a.txt", "src/docs/specs/a.md", "README.md"):
            with self.subTest(path):
                self.assertIsNone(principle_review.classify(path))

    def test_uses_all_flag(self):
        f = principle_review.uses_all_flag
        self.assertTrue(f(["git", "commit", "-a", "-m", "x"]))
        self.assertTrue(f(["git", "commit", "-am", "x"]))
        self.assertTrue(f(["git", "commit", "--all"]))
        self.assertFalse(f(["git", "commit", "-m", "-a"]))
        self.assertFalse(f(["git", "commit", "-m", "add all"]))
