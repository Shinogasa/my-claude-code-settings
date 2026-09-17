#!/usr/bin/env python3
"""コード学習skillの配布可能な構造を検査する。教育効果は別途実測する。"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "code-learning" / "SKILL.md"
ROUTER = ROOT / "rules" / "code-learning.md"


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

    def test_router_has_only_activation_responsibilities(self):
        self.assertTrue(ROUTER.is_file(), "コード学習の常時ruleが存在する")
        text = ROUTER.read_text(encoding="utf-8")
        self.assertIn("skills/code-learning/SKILL.md", text)
        self.assertIn("学習なし", text)
        self.assertIn("生成物", text)
        self.assertNotIn("paths:", text)
        self.assertLess(len(text), 3000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
