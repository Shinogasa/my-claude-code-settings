#!/usr/bin/env python3
"""コード学習skillの配布可能な構造を検査する。教育効果は別途実測する。"""

import unittest
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "code-learning" / "SKILL.md"
ROUTER = ROOT / "rules" / "code-learning.md"
REVIEW_STYLE = ROOT / "output-styles" / "review-and-design.md"
RECORD_SCHEMA = ROOT / "learning" / "code" / "README.md"
HOST_FIXTURE = ROOT / "tests" / "fixtures" / "code-learning-host-probe"


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
        modes = [
            text.index(f"| {mode} |")
            for mode in ("Investigate", "Review", "Modify", "Write", "Explain")
        ]
        self.assertEqual(modes, sorted(modes))

    def test_router_has_only_activation_responsibilities(self):
        self.assertTrue(ROUTER.is_file(), "コード学習の常時ruleが存在する")
        text = ROUTER.read_text(encoding="utf-8")
        common = (ROOT / "rules" / "learning-mode.md").read_text(encoding="utf-8")
        self.assertIn("skills/code-learning/SKILL.md", text)
        self.assertIn("~/.claude/skills/code-learning/SKILL.md", text)
        self.assertIn("~/.agents/skills/code-learning/SKILL.md", text)
        self.assertIn("導入未完了をユーザーへ明示", text)
        self.assertIn("学習なし", common)
        self.assertNotIn("最大2", text)
        self.assertIn("生成物", text)
        self.assertNotIn("paths:", text)
        self.assertLess(len(text), 3000)

    def test_router_gives_direct_store_status_paths_for_both_hosts(self):
        text = ROUTER.read_text(encoding="utf-8")
        self.assertIn("~/.claude/bin/learning-store.py status", text)
        self.assertIn("~/.codex/bin/learning-store.py status", text)
        self.assertIn("symlink", text)

    def test_router_reloads_skill_for_active_learning_event(self):
        text = ROUTER.read_text(encoding="utf-8")
        self.assertIn("継続中の学習イベント", text)
        self.assertIn("skillを再読", text)
        self.assertIn("どう直せば", text)
        self.assertIn("明示的な引取り", text)

    def test_review_style_does_not_reveal_a_review_exercise_early(self):
        text = REVIEW_STYLE.read_text(encoding="utf-8")
        self.assertIn("code-learning", text)
        self.assertIn("理由まで回答", text)
        for form in ("Write", "Modify", "Review", "Investigate", "Predict"):
            with self.subTest(form=form):
                self.assertIn(form, text)

    def test_investigate_retry_and_resume_keep_user_ownership(self):
        text = SKILL.read_text(encoding="utf-8")
        for marker in (
            "対象箇所を先に示さない",
            "固定の再試行回数",
            "同じevent_id",
            "反例または観測差を一つ",
            "本人が選んだ次の行動",
            "完成実装は本人が引取りを依頼するまで保留",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertNotIn("真正かつ安全に成立する最初の形式", text)

    def test_tool_output_and_ai_tests_are_recorded_as_support(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("tool出力", text)
        self.assertIn("AIが完成させたテスト", text)
        self.assertIn("本人が検証方法を設計した証拠", text)

    def test_predict_does_not_leak_the_overlap_code_answer(self):
        common = (ROOT / "rules" / "learning-mode.md").read_text(encoding="utf-8")
        self.assertIn("設計Predictとコード学習が同じ箇所で競合", common)
        self.assertIn("本人が見つけるべき原因箇所や因果の解釈", common)
        self.assertIn("選択と理由の前に示さない", common)

    def test_common_rule_links_interruption_operations_to_one_event(self):
        common = (ROOT / "rules" / "learning-mode.md").read_text(encoding="utf-8")
        self.assertIn("発火・skip・中断・再開", common)
        self.assertIn("同じevent_id", common)
        self.assertIn("operation", common)

    def test_capability_growth_requires_scope_and_comparable_contexts(self):
        common = (ROOT / "rules" / "learning-mode.md").read_text(encoding="utf-8")
        for marker in (
            "能力ID",
            "scope",
            "別文脈2回",
            "2回目",
            "ヒントなし",
            "比較不能",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, common)

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

    def test_record_documentation_covers_attempts_support_and_retention(self):
        text = RECORD_SCHEMA.read_text(encoding="utf-8")
        for marker in (
            "Investigate",
            "能力ID",
            "scope",
            "初回結果",
            "再試行",
            "開始契機",
            "支援",
            "完了",
            "中断",
            "operation",
            "習得証拠",
            "7日以上",
            "関連実作業",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertNotIn(
            "1イベントにつき `learning/code/entries/",
            text,
        )

    def test_host_probe_fixture_has_one_deterministic_external_failure(self):
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "test_worker", "-v"],
            cwd=HOST_FIXTURE,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("test_cancelled_work_does_not_publish_a_late_result", result.stderr)
        self.assertIn("FAILED (failures=1)", result.stderr)
        self.assertNotIn("ERROR", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
