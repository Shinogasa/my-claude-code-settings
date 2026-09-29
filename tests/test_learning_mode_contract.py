#!/usr/bin/env python3
"""学習モードとdeprecated command入口の両ホスト契約を検証する。"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULE = (ROOT / "rules" / "learning-mode.md").read_text(encoding="utf-8")
SETTINGS = json.loads((ROOT / "settings.json.template").read_text(encoding="utf-8"))
PLUGIN_POLICY = json.loads(
    (ROOT / "codex" / "plugin-policy.json").read_text(encoding="utf-8")
)
README = (ROOT / "README.md").read_text(encoding="utf-8")
SETUP = (ROOT / "setup.sh").read_text(encoding="utf-8")
REVIEW_STYLE = (ROOT / "output-styles" / "review-and-design.md").read_text(
    encoding="utf-8"
)
SKILL_MANIFEST = json.loads(
    (ROOT / "manifests" / "skills.json").read_text(encoding="utf-8")
)


class TestLearningBoundaryContract(unittest.TestCase):
    """設計Predictと独立したコード学習の境界を固定する。"""

    def test_old_code_participation_protocol_is_removed(self):
        self.assertNotIn("## コード参加（Predictの代替イベント）", RULE)
        self.assertNotIn("Predict とコード参加", RULE)
        self.assertNotIn("意味のある5〜10行", RULE)

    def test_code_learning_is_delegated_to_its_skill(self):
        self.assertIn("skills/code-learning/SKILL.md", RULE)
        self.assertIn("同じ箇所で二重に", RULE)
        self.assertIn("合計最大2イベント", RULE)

    def test_predict_layer_gate_does_not_exclude_code_practice(self):
        self.assertIn("L2", RULE)
        self.assertIn("コード学習には適用しない", RULE)
        self.assertEqual(RULE.count("- **上限:"), 1)

    def test_common_policy_is_single_owner_for_routing_disclosure_and_storage(self):
        code_rule = (ROOT / "rules" / "code-learning.md").read_text(encoding="utf-8")
        code_skill = (ROOT / "skills" / "code-learning" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## 両学習モードの共通方針", RULE)
        for marker in (
            "同じ能力・同じ解法",
            "合計最大2イベント",
            "理由まで回答する前",
            "status",
            "未保存",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, RULE)
        for consumer in (code_rule, code_skill):
            with self.subTest(consumer=consumer[:30]):
                self.assertIn("rules/learning-mode.md", consumer)
                self.assertIn("共通方針", consumer)

    def test_multiple_options_do_not_force_predict_and_hit_rate_is_not_mastery(self):
        self.assertIn("複数案", RULE)
        self.assertIn("強制発火", RULE)
        self.assertNotIn("必ず発火する場面: こちらが複数案", RULE)
        self.assertNotIn("外した予測ほど後の定着に効く", RULE)
        self.assertIn("結論の一致", RULE)
        self.assertIn("習得の証拠", RULE)

    def test_retention_candidate_requires_related_work_after_seven_days(self):
        self.assertIn("7日以上", RULE)
        self.assertIn("関連実作業", RULE)
        self.assertIn("保持は未確認", RULE)


class TestLearningPluginPolicy(unittest.TestCase):
    """統合後に旧pluginが二重発火しないことを固定する。"""

    PLUGIN_ID = "learning-output-style@claude-plugins-official"

    def test_claude_template_disables_learning_output_style(self):
        self.assertIs(SETTINGS["enabledPlugins"][self.PLUGIN_ID], False)

    def test_codex_policy_denies_learning_output_style(self):
        self.assertEqual(
            PLUGIN_POLICY["plugins"][self.PLUGIN_ID]["status"], "deny"
        )

    def test_review_style_does_not_delegate_to_disabled_plugin(self):
        self.assertNotIn("learning-output-style プラグインが管理", REVIEW_STYLE)
        self.assertIn("rules/learning-mode.md", REVIEW_STYLE)


class TestDeprecatedCommandRouting(unittest.TestCase):
    """Codexがdeprecated promptsではなくnative機能とskillsを使うことを固定する。"""

    def test_setup_does_not_distribute_codex_custom_prompts(self):
        self.assertNotIn("$CODEX_DIR/prompts", SETUP)
        self.assertNotIn("| `commands/` | `~/.codex/prompts/` |", README)

    def test_readme_maps_legacy_commands_to_maintained_entries(self):
        for mapping in (
            "| `code-review` | Codex組み込み `/review` |",
            "| `quality-gate` | `verification-loop` |",
            "| `verify` | `verification-loop` |",
            "| `tdd` | `tdd-workflow` |",
        ):
            with self.subTest(mapping=mapping):
                self.assertIn(mapping, README)

    def test_plan_skill_uses_host_neutral_follow_up_entries(self):
        text = (ROOT / "skills" / "source-command-plan" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("tdd-workflow", text)
        self.assertIn("verification-loop", text)
        self.assertIn("/review", text)
        self.assertNotIn("/tdd", text)
        self.assertNotIn("/code-review", text)
        self.assertNotIn("/prp-plan", text)
        self.assertNotIn("/prp-implement", text)


class TestSharedSkillPortability(unittest.TestCase):
    """shared分類のskillがClaude固有APIを実行契約にしないことを固定する。"""

    def test_shared_skills_are_host_neutral(self):
        forbidden = (
            r"\bClaude Code\b",
            r"\b(?:Use|use) (?:the )?(?:Read|Edit|Grep|Glob) tool\b",
            r"\buse Grep\b",
            r"Run: /verify",
        )
        for skill_name in SKILL_MANIFEST["shared"]:
            text = (ROOT / "skills" / skill_name / "SKILL.md").read_text(
                encoding="utf-8"
            )
            for pattern in forbidden:
                with self.subTest(skill=skill_name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text))


if __name__ == "__main__":
    unittest.main(verbosity=2)
