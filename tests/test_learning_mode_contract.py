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
SKILL_MANIFEST = json.loads(
    (ROOT / "manifests" / "skills.json").read_text(encoding="utf-8")
)


class TestCodeParticipationContract(unittest.TestCase):
    """コード参加が既存Predictの境界を壊さないことを固定する。"""

    def test_is_a_bounded_alternative_to_predict(self):
        for marker in ("コード参加", "Predictの代替", "合計で最大2回", "1回を消費"):
            with self.subTest(marker=marker):
                self.assertIn(marker, RULE)

    def test_prepares_a_meaningful_implementation_slot_before_asking(self):
        for marker in (
            "意味のある5〜10行",
            "対象ファイル",
            "周辺コード",
            "関数シグネチャ",
            "目的コメント",
            "TODO",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, RULE)

    def test_supports_skip_and_keeps_the_learning_feedback_loop(self):
        for marker in ("スキップ", "理由", "検証", "★ Delta"):
            with self.subTest(marker=marker):
                self.assertIn(marker, RULE)
        self.assertNotIn("★ Insight", RULE)

    def test_excludes_low_value_code_participation(self):
        for marker in ("設定", "ボイラープレート", "明白な実装", "単純CRUD"):
            with self.subTest(marker=marker):
                self.assertIn(marker, RULE)


class TestLearningPluginPolicy(unittest.TestCase):
    """統合後に旧pluginが二重発火しないことを固定する。"""

    PLUGIN_ID = "learning-output-style@claude-plugins-official"

    def test_claude_template_disables_learning_output_style(self):
        self.assertIs(SETTINGS["enabledPlugins"][self.PLUGIN_ID], False)

    def test_codex_policy_denies_learning_output_style(self):
        self.assertEqual(
            PLUGIN_POLICY["plugins"][self.PLUGIN_ID]["status"], "deny"
        )


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


class TestSharedSkillPortability(unittest.TestCase):
    """shared分類のskillがClaude固有APIを実行契約にしないことを固定する。"""

    def test_shared_skills_are_host_neutral(self):
        forbidden = (
            r"Claude Code sessions",
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
