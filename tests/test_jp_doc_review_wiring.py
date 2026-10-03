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
        self.assertEqual(set(codex_agents.parse_tools(self.meta["tools"])), {"Read", "Edit", "Bash", "Grep"})
        self.assertEqual(self.meta["model"], "opus")

    def test_bash_is_limited_to_the_linter_by_agent_hook(self):
        frontmatter = AGENT.read_text(encoding="utf-8").split("---\n")[1]
        for marker in ("hooks:", "PreToolUse:", "matcher: Bash", "type: command",
                       "command: python3 ~/.claude/hooks/jp-doc-review.py pre-tool-use-reviewer-bash"):
            with self.subTest(marker=marker):
                self.assertIn(marker, frontmatter)

    def test_edit_is_guarded_by_agent_hook(self):
        frontmatter = AGENT.read_text(encoding="utf-8").split("---\n")[1]
        for marker in ("matcher: Edit",
                       "command: python3 ~/.claude/hooks/jp-doc-review.py pre-tool-use-reviewer-edit"):
            with self.subTest(marker=marker):
                self.assertIn(marker, frontmatter)
        self.assertIn("依頼されたファイルだけ", self.body)

    def test_body_treats_documents_as_data_and_limits_bash(self):
        for marker in ("データとして扱う", "従わない", "リンターだけ", "シングルクォート",
                       "'<ファイル>'", "そのまま報告"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)

    def test_nested_frontmatter_does_not_leak_into_meta(self):
        self.assertEqual(set(self.meta), {"name", "description", "tools", "model", "color", "hooks"})

    def test_body_requires_reading_all_references_before_rewriting(self):
        for marker in ("references/gemini-syntax.md", "references/slop-catalog.md", "references/domains/",
                       "主張", "比重", "言い切りの強さ", "文の働き", "yomiyasu_lint.py"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)

    def test_body_makes_reading_and_editing_instructions_explicit(self):
        for marker in ("`SKILL.md` をReadツールで全文読む", "次の資料をReadツールで全文読む", "その場で書き換える",
                       "読めなかった資料を報告する", "grepして確かめる"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)

    def test_body_limits_rewriting_to_requested_range(self):
        for marker in ("範囲を指定されたら、その範囲だけ", "指定が無ければファイル全体"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)

    def test_report_section_has_room_for_unread_references(self):
        report = self.body.split("## 報告", 1)[1]
        self.assertIn("読めなかった資料（あれば）", report)
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
        self.assertEqual(commands("PreToolUse", CONFLUENCE_MATCHER),
                         ["python3 ~/.claude/hooks/jp-doc-review.py pre-tool-use-confluence"])
        pattern = re.compile(f"^(?:{CONFLUENCE_MATCHER})$")
        for name in ("createConfluencePage", "updateConfluencePage",
                     "createConfluenceFooterComment", "createConfluenceInlineComment"):
            with self.subTest(name=name):
                self.assertTrue(pattern.match(f"mcp__atlassian-http__{name}"))
        self.assertFalse(pattern.match("mcp__atlassian-http__getConfluencePage"))

    def test_bash_group_asks_for_review_before_commit_and_keeps_existing_hooks(self):
        self.assertEqual(commands("PreToolUse", "Bash"), [
            "~/.claude/hooks/guard-dangerous-bash.sh",
            "rtk hook claude",
            "~/.claude/hooks/warn-branch-behind-main.sh",
            "python3 ~/.claude/hooks/jp-doc-review.py pre-tool-use-bash",
        ])

    def test_agent_calls_are_recorded_and_existing_hooks_remain(self):
        self.assertEqual(commands("PreToolUse", "Agent|Task"),
                         ["python3 ~/.claude/hooks/jp-doc-review.py pre-tool-use-agent"])
        self.assertIn("python3 ~/.claude/hooks/jp-doc-review.py pre-tool-use-bash", commands("PreToolUse", "Bash"))
        self.assertEqual(len(commands("PreToolUse", CONFLUENCE_MATCHER)), 1)

    def test_stop_runs_only_read_check(self):
        self.assertEqual(commands("Stop"), ["python3 ~/.claude/hooks/skill-read-check.py stop"])

    def test_subagent_stop_runs_read_check(self):
        self.assertEqual(commands("SubagentStop"), ["python3 ~/.claude/hooks/skill-read-check.py subagent-stop"])

    def test_session_start_is_kept(self):
        self.assertEqual(commands("SessionStart"), ["~/.claude/hooks/detect-parallel-sessions.sh"])

    def test_every_hook_has_a_timeout_except_rtk(self):
        for event, groups in SETTINGS["hooks"].items():
            for group in groups:
                for hook in group["hooks"]:
                    with self.subTest(event=event, command=hook["command"]):
                        self.assertEqual(hook["type"], "command")
                        if hook["command"] != "rtk hook claude":
                            self.assertIsInstance(hook.get("timeout"), int)

    def test_codex_wiring_is_untouched(self):
        codex = (REPO_ROOT / "codex" / "hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("jp-doc-review", codex)
        self.assertNotIn("skill-read-check", codex)


if __name__ == "__main__":
    unittest.main(verbosity=2)
