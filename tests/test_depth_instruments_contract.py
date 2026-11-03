#!/usr/bin/env python3
"""ブログ「How to be more ambitious」から取り込んだ規約（ADR 0048）の契約を検証する。

文字列の契約なので、書いてあることしか確かめない。
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPLETION_RULE = (ROOT / "rules" / "fix-completion-criteria.md").read_text(encoding="utf-8")
ABSENCE_RULE = (ROOT / "rules" / "proving-absence.md").read_text(encoding="utf-8")
OUTPUT_RULE = (ROOT / "rules" / "output-formatting.md").read_text(encoding="utf-8")


class TestDepthQuestions(unittest.TestCase):
    """完了条件を書くときに、大きくではなく深くする4問を自問する。"""

    def test_completion_rule_asks_four_depth_questions(self):
        for marker in ("頼まれていなくても", "最も生の材料", "方法と道具", "自分とユーザー以外"):
            with self.subTest(marker=marker):
                self.assertIn(marker, COMPLETION_RULE)

    def test_depth_questions_forbid_role_declaration(self):
        # ブログ: 役割を名乗らせても語彙が変わるだけで、方法は変わらない
        self.assertIn("役割を名乗らせない", COMPLETION_RULE)

    def test_completion_rule_cites_adr(self):
        self.assertIn("ADR 0048", COMPLETION_RULE)


class TestInstruments(unittest.TestCase):
    """性能・並行性・データの主張は、読んだだけか道具で測ったかを区別する。"""

    def test_absence_rule_requires_instruments_as_scope_basis(self):
        self.assertIn("go test -race", ABSENCE_RULE)
        self.assertIn("EXPLAIN ANALYZE", ABSENCE_RULE)
        self.assertIn("未確認（読んだだけ）", ABSENCE_RULE)

    def test_completion_report_flags_unmeasured_claims(self):
        self.assertIn("道具で測らず読んで判断しただけ", OUTPUT_RULE)


if __name__ == "__main__":
    unittest.main()
