#!/usr/bin/env python3
"""完了条件の固定（rules/fix-completion-criteria.md）の契約を検証する。

文字列の契約なので、書いてあることしか確かめない。振る舞いは計画の代表検証で確かめる。
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULE_PATH = ROOT / "rules" / "fix-completion-criteria.md"
TASK_MANAGEMENT = (ROOT / "rules" / "task-management.md").read_text(encoding="utf-8")
GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")


def read_rule() -> str:
    return RULE_PATH.read_text(encoding="utf-8") if RULE_PATH.is_file() else ""


class TestFixCompletionCriteriaRule(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RULE_PATH.is_file(), f"{RULE_PATH} がありません")
        self.rule = read_rule()

    def test_rule_is_always_on_and_under_official_size_target(self):
        # 公式: CLAUDE.md 1ファイル200行未満（https://code.claude.com/docs/en/memory）
        self.assertNotIn("paths:", self.rule)
        self.assertLess(len(self.rule.splitlines()), 200)

    def test_rule_names_three_fields(self):
        for field in ("依頼された結果", "暫定の完了条件", "今回は扱わない論点"):
            with self.subTest(field=field):
                self.assertIn(field, self.rule)

    def test_rule_names_three_sorts_and_stops_only_on_second(self):
        for name in ("完了に必要", "完了条件が変わる", "関係ない"):
            with self.subTest(name=name):
                self.assertIn(name, self.rule)
        self.assertIn("当初 → 変更後 → 理由", self.rule)

    def test_rule_treats_user_initiated_change_as_approved_but_shows_it(self):
        # 本人が広げた追加を③で退けず、広げた後の完了条件は見せる（2026-10-23の代表検証1）
        self.assertIn("ユーザー本人が作業中に範囲を広げたり狭めたりした", self.rule)
        self.assertIn("変わった後の完了条件", self.rule)

    def test_rule_applies_even_when_urgent(self):
        self.assertIn("急ぎ", self.rule)

    def test_rule_places_task_file_and_checks_ignore(self):
        self.assertIn("tasks/todo/", self.rule)
        self.assertIn("git check-ignore", self.rule)

    def test_rule_passes_absolute_path_to_subagents(self):
        self.assertIn("絶対パス", self.rule)
        self.assertIn("サブエージェント", self.rule)

    def test_rule_defers_to_brainstorming_design_doc(self):
        self.assertIn("brainstorming", self.rule)

    def test_rule_asks_to_log_parallel_cases(self):
        self.assertIn("並列", self.rule)
        self.assertIn("tasks/backlog.md", self.rule)


class TestFixCompletionCriteriaWiring(unittest.TestCase):
    """既存の指示とignoreが新しいruleにつながっていることを確かめる。"""

    def test_task_management_drops_single_file_premise(self):
        self.assertNotIn("常に1ファイルで足りる", TASK_MANAGEMENT)
        self.assertIn("rules/fix-completion-criteria.md", TASK_MANAGEMENT)
        self.assertIn("tasks/todo/", TASK_MANAGEMENT)

    def test_gitignore_covers_task_files(self):
        self.assertIn("tasks/todo/", GITIGNORE.splitlines())


if __name__ == "__main__":
    unittest.main()
