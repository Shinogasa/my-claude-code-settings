#!/usr/bin/env python3
"""Codex の動的モデルルーティング契約を検証する。"""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTING = ROOT / "codex" / "MODEL_ROUTING.md"


class CodexModelRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = ROUTING.read_text(encoding="utf-8")

    def test_default_is_explicit_luna_medium_pair(self):
        self.assertIn('gpt-5.6-luna', self.text)
        self.assertIn('medium', self.text)
        self.assertRegex(
            self.text,
            r"`model` と\s*`reasoning_effort` を必ず同時",
        )

    def test_routes_depth_and_breadth_on_separate_axes(self):
        self.assertIn('推論の深さ不足', self.text)
        self.assertIn('探索範囲不足', self.text)
        self.assertIn('降格', self.text)
        for effort in ('low', 'medium', 'high', 'max'):
            with self.subTest(effort=effort):
                self.assertIn(effort, self.text)
        for model in ('gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol'):
            with self.subTest(model=model):
                self.assertIn(model, self.text)

    def test_user_confirmation_is_limited_to_existing_boundaries(self):
        self.assertIn('rules/security-review-policy.md', self.text)
        self.assertIn('不可逆', self.text)
        self.assertIn('外部副作用', self.text)
        self.assertIn('明示した予算上限', self.text)
        self.assertIn('通常のモデル・推論強度の昇降では確認しない', self.text)

    def test_provider_failure_is_fail_closed(self):
        self.assertIn('`model_provider` を変更しない', self.text)
        self.assertIn('fail-closed', self.text)

    def test_parent_routing_prefers_explicit_agent_or_fresh_session(self):
        self.assertIn('親工程の標準経路', self.text)
        self.assertRegex(self.text, r'明示ペアの(?:subagent|サブエージェント)')
        self.assertRegex(self.text, r'明示ペアのfresh session')
        self.assertIn('新規`begin`は常に拒否', self.text)

    def test_same_thread_begin_disabled_with_in_session_recovery(self):
        self.assertIn('同じturn', self.text)
        self.assertIn('UserPromptSubmit', self.text)
        self.assertIn('PreToolUse', self.text)
        self.assertIn('diagnose --repo', self.text)
        self.assertIn('cancel --repo', self.text)

    def test_security_review_uses_risk_specific_profiles(self):
        self.assertIn('狭い一次確認・再レビュー', self.text)
        self.assertIn('通常の意味的セキュリティレビュー', self.text)
        self.assertRegex(
            self.text,
            r"通常の意味的セキュリティレビュー[^\n]*`gpt-5\.6-terra`[^\n]*`high`",
        )
        self.assertIn('Critical', self.text)
        self.assertIn('Confidence: insufficient', self.text)

    def test_cross_model_handoff_is_required_for_every_work_phase(self):
        for phase in (
            '実装',
            '探索',
            '修正',
            'セキュリティレビュー',
            '最終レビュー',
            '昇格',
            '降格',
            '再レビュー',
        ):
            with self.subTest(phase=phase):
                self.assertIn(phase, self.text)
        self.assertIn('.superpowers/handoffs/', self.text)
        self.assertIn('validate-codex-handoff.py validate', self.text)
        self.assertIn('NEEDS_CONTEXT', self.text)
        self.assertIn('task brief', self.text)
        self.assertIn('review package', self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
