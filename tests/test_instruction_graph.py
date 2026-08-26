#!/usr/bin/env python3
"""共有指示の入口とCodex固有差分の境界を検証する。"""
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"

EXPECTED_AGENTS = """# Codex project guidance

グローバル指示は ~/.codex/AGENTS.md から読み込まれる。
このファイルには、この設定リポジトリで必要なCodex差分だけを書く。

- Codex設定の変更・レビューでは codex-cli-best-practice skillを読む
- 根拠はOpenAI公式資料、ローカルCLI実測、固定submoduleの順で採る
- Claude由来資産は docs/adr/0003-codex-native-first-activation-policy.md に従う
- runtimeの強制境界は docs/adr/0004-codex-runtime-enforcement-policy.md に従う
"""

SESSION_RULES = (
    "rules/learning-mode.md",
    "rules/proving-absence.md",
    "rules/task-management.md",
    "rules/parallel-worktree.md",
    "rules/output-formatting.md",
    "rules/persona.md",
    "rules/security-review-policy.md",
)


class TestSharedInstructionIndex(unittest.TestCase):
    """CLAUDE.mdが両ホスト共通の指示indexになっているか。"""

    @classmethod
    def setUpClass(cls):
        cls.text = CLAUDE_MD.read_text(encoding="utf-8")

    def test_requires_full_session_start_read(self):
        self.assertIn("セッション開始時に以下をすべて全文読む", self.text)

    def test_mentions_both_host_configuration_paths(self):
        self.assertIn(
            "各 `rules/...` は、Claude Codeでは\n`~/.claude/`、Codex CLIでは `~/.codex/` を起点に解決する。",
            self.text,
        )

    def test_documents_markdown_links_are_not_transclusion(self):
        self.assertIn(
            "Markdownリンクは参照先への経路にすぎず、内容がコンテキストへ展開（transclusion）された\n証明にはならない。",
            self.text,
        )

    def test_routes_to_every_session_rule(self):
        for rule in SESSION_RULES:
            with self.subTest(rule=rule):
                self.assertIn(rule, self.text)

    def test_retains_existing_shared_summary_headings(self):
        for heading in (
            "## 言語",
            "## Git",
            "## 学習モード",
            "## 不在の主張",
            "## ワークフロー設計",
            "## タスク管理",
            "## コア原則",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.text)

    def test_session_rules_exist_as_files(self):
        for rule in SESSION_RULES:
            with self.subTest(rule=rule):
                self.assertTrue((REPO_ROOT / rule).is_file())


class TestCodexProjectDelta(unittest.TestCase):
    """AGENTS.mdがリポジトリ固有の小さな差分だけを持つか。"""

    @classmethod
    def setUpClass(cls):
        cls.content = AGENTS_MD.read_bytes()
        cls.text = cls.content.decode("utf-8")

    def test_does_not_reference_invalid_codex_routes(self):
        self.assertNotIn("~/.Codex", self.text)
        self.assertNotIn("/Codex-best-practice", self.text)

    def test_matches_the_planned_nine_line_document(self):
        self.assertEqual(self.content.decode("utf-8"), EXPECTED_AGENTS)

    def test_stays_below_project_instruction_budget(self):
        self.assertLess(len(self.content), 4096)


if __name__ == "__main__":
    unittest.main(verbosity=2)
