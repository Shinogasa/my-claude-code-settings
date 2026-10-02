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

    def test_body_makes_reading_and_editing_instructions_explicit(self):
        for marker in ("SKILL.md` を全文読む", "次の資料を全文読む", "その場で書き換える",
                       "読めなかったことを報告する", "grepして確かめる"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)
        # 固定先のSKILL.mdはslop-catalog.mdに触れないので、「SKILL.mdが参照する資料」は事実と違う
        self.assertNotIn("が参照する資料", self.body)

    def test_body_lists_what_must_not_change(self):
        for marker in ("★", "コード", "URL", "テスト", "data-*"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)


SETTINGS = json.loads((REPO_ROOT / "settings.json.template").read_text(encoding="utf-8"))
CONFLUENCE_MATCHER = "mcp__.*__(create|update)Confluence(Page|FooterComment|InlineComment)"


def commands(event, matcher=None):
    found = []
    for group in SETTINGS["hooks"].get(event, []):
        if matcher is not None and group.get("matcher") != matcher:
            continue
        found.extend(hook["command"] for hook in group["hooks"])
    return found


class WiringTests(unittest.TestCase):
    def test_post_tool_use_records_writes_and_edits(self):
        self.assertIn("python3 ~/.claude/hooks/jp-doc-review.py post-tool-use", commands("PostToolUse", "Write|Edit"))

    def test_confluence_matcher_catches_only_posting_tools(self):
        self.assertIn("python3 ~/.claude/hooks/jp-doc-review.py pre-tool-use", commands("PreToolUse", CONFLUENCE_MATCHER))
        pattern = re.compile(f"^(?:{CONFLUENCE_MATCHER})$")
        for name in ("createConfluencePage", "updateConfluencePage",
                     "createConfluenceFooterComment", "createConfluenceInlineComment"):
            with self.subTest(name=name):
                self.assertTrue(pattern.match(f"mcp__atlassian-http__{name}"))
        self.assertFalse(pattern.match("mcp__atlassian-http__getConfluencePage"))

    def test_existing_bash_guards_are_kept(self):
        self.assertIn("~/.claude/hooks/guard-dangerous-bash.sh", commands("PreToolUse", "Bash"))

    def test_stop_runs_review_and_read_check(self):
        stop = commands("Stop")
        self.assertIn("python3 ~/.claude/hooks/jp-doc-review.py stop", stop)
        self.assertIn("python3 ~/.claude/hooks/skill-read-check.py stop", stop)

    def test_subagent_stop_runs_read_check(self):
        self.assertIn("python3 ~/.claude/hooks/skill-read-check.py subagent-stop", commands("SubagentStop"))

    def test_codex_wiring_is_untouched(self):
        codex = (REPO_ROOT / "codex" / "hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("jp-doc-review", codex)
        self.assertNotIn("skill-read-check", codex)


if __name__ == "__main__":
    unittest.main(verbosity=2)
