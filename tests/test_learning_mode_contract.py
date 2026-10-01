#!/usr/bin/env python3
"""学習モードとdeprecated command入口の両ホスト契約を検証する。"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULE = (ROOT / "rules" / "learning-mode.md").read_text(encoding="utf-8")
SKILL = ROOT / "skills" / "learning-mode" / "SKILL.md"
DELTA_SUPPLEMENTS = ROOT / "skills" / "learning-mode" / "references" / "delta-supplements.md"
RATIONALIZATIONS = ROOT / "skills" / "learning-mode" / "references" / "rationalizations.md"
SETTINGS = json.loads((ROOT / "settings.json.template").read_text(encoding="utf-8"))
PLUGIN_POLICY = json.loads(
    (ROOT / "codex" / "plugin-policy.json").read_text(encoding="utf-8")
)
README = (ROOT / "README.md").read_text(encoding="utf-8")
CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
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


class TestLearningModeSplit(unittest.TestCase):
    """常時ruleと発火後のskillの所在・開示順・配布契約を固定する。"""

    def skill_text(self):
        """skillが未作成なら、欠落したパスを示して失敗する。"""
        self.assertTrue(SKILL.is_file(), f"skillが見つからない: {SKILL}")
        return SKILL.read_text(encoding="utf-8")

    def reference_text(self, path):
        """補助資料が未作成なら、欠落したパスを示して失敗する。"""
        self.assertTrue(path.is_file(), f"補助資料が見つからない: {path}")
        return path.read_text(encoding="utf-8")

    def test_always_on_rule_is_small_and_has_no_path_filter(self):
        """判定ruleが常時読み込めるサイズとfrontmatterを保つ。"""
        self.assertLess(len(RULE), 6000)
        self.assertNotIn("paths:", RULE)

    def test_always_on_rule_does_not_duplicate_procedures(self):
        """詳細手順とDelta書式が常時ruleに残る退行を検出する。"""
        for marker in (
            "## ★ Delta の返し方", "## 概念名の供給", "## 定石の供給",
            "## 次の問いの立て方", "## 合理化防止", "★ Delta ───",
        ):
            with self.subTest(marker=marker):
                self.assertFalse(marker in RULE, f"常時ruleに手順が残っている: {marker}")

    def test_always_on_rule_names_skill_entry_and_recovery(self):
        """発火時とcompact後に詳細手順へ到達できるようにする。"""
        for marker in (
            "skills/learning-mode/SKILL.md",
            "~/.claude/skills/learning-mode/SKILL.md",
            "~/.agents/skills/learning-mode/SKILL.md",
            "skillを再読", "導入未完了",
        ):
            with self.subTest(marker=marker):
                self.assertTrue(marker in RULE, f"常時ruleの入口が欠けている: {marker}")

    def test_always_on_rule_keeps_pre_disclosure_guards(self):
        """予測前に答えを漏らさないためのホスト別停止手段と禁止を保つ。"""
        for marker in ("AskUserQuestion", "（推奨）", "理由を聞く前", "上書き宣言"):
            with self.subTest(marker=marker):
                self.assertTrue(marker in RULE, f"開示前の禁止事項が欠けている: {marker}")

    def test_skill_frontmatter_describes_post_gate_use(self):
        """skill一覧から発火後の用途を判別できるようにする。"""
        skill = self.skill_text()
        self.assertTrue(skill.startswith("---\nname: learning-mode\n"))
        self.assertIn("description: Use when", skill)

    def test_skill_steps_follow_learning_event_order(self):
        """予測と理由の後に答えと記録が来る順序を固定する。"""
        skill = self.skill_text()
        headings = ("## ループ", "## 予測フェーズ", "## 理由フェーズ", "## ★ Delta", "## 記録")
        for heading in headings:
            self.assertIn(heading, skill)
        positions = [skill.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))

    def test_skill_contains_feedback_storage_and_reference_entries(self):
        """Deltaの評価軸、抽象化、補助資料への入口を保つ。"""
        skill = self.skill_text()
        for marker in (
            "★ Delta ───", "トレードオフ", "失敗モード", "前提の検証",
            "全軸充足", 'kind: "decision"', "PUBLIC",
            "references/delta-supplements.md", "references/rationalizations.md",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, skill)

    def test_skill_fits_disclosure_limits(self):
        """compact後の再読に使える短いskillを保つ。"""
        skill = self.skill_text()
        self.assertLess(skill.count("\n"), 500)
        self.assertLessEqual(len(skill), 8000)

    def test_references_keep_record_lookup_key_and_gate_terms(self):
        """過去記録の検索キーと合理化防止の判定語を保つ。"""
        self.assertIn("次に同種の判断で確認する問い", self.reference_text(DELTA_SUPPLEMENTS))
        rationalizations = self.reference_text(RATIONALIZATIONS)
        self.assertIn("層ゲート", rationalizations)
        self.assertIn("下限", rationalizations)

    def test_supplement_reference_returns_to_skill_from_its_directory(self):
        """補助資料から判断原則の説明へ相対パスで戻れるようにする。"""
        self.assertIn("`../SKILL.md`「過去の判断原則を接続する」", self.reference_text(DELTA_SUPPLEMENTS))

    def test_common_policy_has_only_one_owner(self):
        """上限と共通方針の正本がrule以外に複製されないようにする。"""
        for text in (self.skill_text(), self.reference_text(DELTA_SUPPLEMENTS),
                     self.reference_text(RATIONALIZATIONS)):
            for marker in ("## 両学習モードの共通方針", "- **上限:"):
                with self.subTest(marker=marker):
                    self.assertNotIn(marker, text)

    def test_manifest_distributes_skill_to_both_hosts(self):
        """新skillがshared分類から配布されることを固定する。"""
        self.assertIn("learning-mode", SKILL_MANIFEST["shared"])

    def test_shared_skill_files_do_not_depend_on_host_name(self):
        """sharedのskillと補助資料にホスト固有の実行契約を置かない。"""
        for text in (self.skill_text(), self.reference_text(DELTA_SUPPLEMENTS),
                     self.reference_text(RATIONALIZATIONS)):
            self.assertIsNone(re.search(r"\bClaude Code\b", text))

    def test_removed_legacy_protocol_stays_out_of_skill_and_references(self):
        """旧コード参加プロトコルなどが移動先へ復活しないようにする。"""
        forbidden = (
            "## コード参加（Predictの代替イベント）", "Predict とコード参加",
            "意味のある5〜10行", "必ず発火する場面: こちらが複数案",
            "外した予測ほど後の定着に効く",
        )
        for text in (self.skill_text(), self.reference_text(DELTA_SUPPLEMENTS),
                     self.reference_text(RATIONALIZATIONS)):
            for marker in forbidden:
                with self.subTest(marker=marker):
                    self.assertNotIn(marker, text)

    def test_claude_guidance_points_to_rule_and_skill_owners(self):
        """学習モードの判定と手順を別の正本へ案内する。"""
        self.assertTrue("判定は `rules/learning-mode.md`、手順と書式は `skills/learning-mode/SKILL.md`" in CLAUDE)
        self.assertTrue("`skills/learning-mode/SKILL.md` の抽象化ルール参照" in CLAUDE)

    def test_review_style_points_to_rule_and_skill(self):
        """レビュー表示が新しい手順の所在を案内する。"""
        self.assertTrue("★ Predict・★ Delta は `rules/learning-mode.md` と `skills/learning-mode/SKILL.md`" in REVIEW_STYLE)

    def test_readme_directory_tree_names_split_responsibilities(self):
        """ディレクトリ一覧から新skillと軽量ruleを見つけられる。"""
        self.assertTrue("├── learning-mode/" in README)
        self.assertTrue("学習モードの判定と共通方針" in README)


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
            "| `tdd` | `superpowers:test-driven-development` |",
        ):
            with self.subTest(mapping=mapping):
                self.assertIn(mapping, README)

    def test_plan_skill_uses_host_neutral_follow_up_entries(self):
        text = (ROOT / "skills" / "source-command-plan" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("superpowers:test-driven-development", text)
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
