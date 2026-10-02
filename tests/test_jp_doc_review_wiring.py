#!/usr/bin/env python3
"""日本語文書レビューのagent定義と、settings.json.template の配線を検証する。

実行: python3 -m unittest tests.test_jp_doc_review_wiring
"""
import importlib.util
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT = REPO_ROOT / "agents" / "jp-doc-reviewer.md"

_spec = importlib.util.spec_from_file_location("codex_agents", REPO_ROOT / "bin" / "generate-codex-agents.py")
codex_agents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(codex_agents)


class ReviewerAgentTests(unittest.TestCase):
    def setUp(self):
        self.meta, self.body = codex_agents.parse_frontmatter(AGENT.read_text(encoding="utf-8"))

    def test_name_tools_and_model(self):
        self.assertEqual(self.meta["name"], "jp-doc-reviewer")
        self.assertEqual(set(codex_agents.parse_tools(self.meta["tools"])), {"Read", "Edit", "Bash"})
        self.assertEqual(self.meta["model"], "opus")

    def test_body_requires_reading_all_references_before_rewriting(self):
        for marker in ("references/gemini-syntax.md", "references/slop-catalog.md", "references/domains/",
                       "主張", "比重", "言い切りの強さ", "文の働き", "yomiyasu_lint.py"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)

    def test_body_lists_what_must_not_change(self):
        for marker in ("★", "コード", "URL", "テスト", "data-*"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
