#!/usr/bin/env python3
"""worktreeの置き場所の宣言が rules/parallel-worktree.md から消えていないかを検査する。

superpowers の using-git-worktrees は「指示で宣言された置き場所」を最優先する。
宣言が消えると、Codex の手作業ルートが既定の .worktrees/ に戻る（ADR 0051）。
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULE = ROOT / "rules" / "parallel-worktree.md"


class WorktreeLocationContract(unittest.TestCase):
    def setUp(self):
        self.text = RULE.read_text(encoding="utf-8")

    def test_declares_claude_location(self):
        self.assertIn("<repo>/.claude/worktrees/<名前>", self.text)

    def test_declares_codex_location_with_manual_command(self):
        self.assertIn(
            "git worktree add <repo>/.codex/worktrees/<名前> -b <branch>", self.text
        )

    def test_codex_avoids_native_worktree(self):
        # 使わない対象として、Codexのネイティブ機能を名前で挙げている
        self.assertIn("codex --worktree", self.text)
        self.assertIn("create_worktree", self.text)

    def test_repo_root_is_main_worktree(self):
        # worktreeの中で --show-toplevel を使うと、そのworktreeが <repo> になり入れ子になる。
        # 親を git worktree remove すると、ignoreされた子の未コミット変更が消える
        self.assertIn("git worktree list --porcelain", self.text)
        self.assertNotIn("--show-toplevel", self.text)

    def test_claude_child_repo_session_starts_in_child(self):
        # EnterWorktree はパスを受け取らない。親の作業ディレクトリのセッションから呼ぶと親に作られる
        self.assertIn("子repoでセッションを起動する", self.text)

    def test_ignore_check_before_create(self):
        # 末尾の / が無いと、まだ無いディレクトリはパターン（末尾 / 付き）に一致せず、常に「無視されていない」になる
        self.assertIn("git check-ignore -q .claude/worktrees/", self.text)
        self.assertIn("git check-ignore -q .codex/worktrees/", self.text)
        self.assertIn(".git/info/exclude", self.text)

    def test_no_unspecified_path(self):
        self.assertNotIn("git worktree add <path> -b <branch>", self.text)

    def test_config_repo_section_has_no_own_location(self):
        # 置き場所は共通の節だけで宣言する。設定repoの節に別の記述が戻ると食い違う
        section = self.text.split("## エージェント設定リポジトリ", 1)[1]
        self.assertNotIn(".claude/worktrees/", section)


if __name__ == "__main__":
    unittest.main()
