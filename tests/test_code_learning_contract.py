#!/usr/bin/env python3
"""コード学習skillの配布可能な構造を検査する。教育効果は別途実測する。"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "code-learning" / "SKILL.md"
ROUTER = ROOT / "rules" / "code-learning.md"
REVIEW_STYLE = ROOT / "output-styles" / "review-and-design.md"
RECORD_SCHEMA = ROOT / "learning" / "code" / "README.md"


class CodeLearningSkillContract(unittest.TestCase):
    def test_skill_has_discoverable_frontmatter(self):
        self.assertTrue(SKILL.is_file(), "共有code-learning skillが存在する")
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        frontmatter = text.split("\n---\n", 1)[0]
        self.assertIn("name: code-learning", frontmatter)
        self.assertIn("description: Use when", frontmatter)

    def test_learning_steps_are_in_executable_order(self):
        self.assertTrue(SKILL.is_file(), "共有code-learning skillが存在する")
        text = SKILL.read_text(encoding="utf-8")
        steps = (
            "## 候補選定",
            "## 足場と形式",
            "## 理由を自己説明",
            "## 事実を検証",
            "## フィードバック",
            "## 転移確認",
            "## 学習記録",
        )
        positions = [text.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))

    def test_skill_keeps_workflow_and_feedback_safety_gates(self):
        text = SKILL.read_text(encoding="utf-8")
        for marker in (
            "生成物、vendored code、lockfile",
            "ボイラープレート",
            "TDDなら失敗するテストより先にproduction実装を書かせない",
            "productionへ教材用の欠陥を仕込む必要がある",
            "最初の依頼に理由質問を同梱しない",
            "検査できなかったことを「問題なし」に畳まない",
            "検証不能なら発火を見送り",
            "ユーザーのスキップを尊重",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        modes = [text.index(f"| {mode} |") for mode in ("Write", "Modify", "Review", "Explain")]
        self.assertEqual(modes, sorted(modes))

    def test_router_has_only_activation_responsibilities(self):
        self.assertTrue(ROUTER.is_file(), "コード学習の常時ruleが存在する")
        text = ROUTER.read_text(encoding="utf-8")
        self.assertIn("skills/code-learning/SKILL.md", text)
        self.assertIn("~/.claude/skills/code-learning/SKILL.md", text)
        self.assertIn("~/.agents/skills/code-learning/SKILL.md", text)
        self.assertIn("導入未完了をユーザーへ明示", text)
        self.assertIn("学習なし", text)
        self.assertIn("生成物", text)
        self.assertNotIn("paths:", text)
        self.assertLess(len(text), 3000)

    def test_review_style_does_not_reveal_a_review_exercise_early(self):
        text = REVIEW_STYLE.read_text(encoding="utf-8")
        self.assertIn("code-learning", text)
        self.assertIn("ユーザーの指摘後", text)

    def test_record_schema_requires_evidence_and_public_safety(self):
        self.assertTrue(RECORD_SCHEMA.is_file())
        text = RECORD_SCHEMA.read_text(encoding="utf-8")
        for field in (
            "能力",
            "形式",
            "ユーザーが実証",
            "検証方法",
            "転移結果",
            "未解消のgap",
        ):
            with self.subTest(field=field):
                self.assertIn(field, text)
        self.assertIn("抽象化できない場合は保存しない", text)
        self.assertIn("説明・転移回答だけ", text)
        self.assertIn("別文脈で2回", text)
        self.assertIn("実質ヒントなし", text)
        self.assertIn("自動同期しない", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
