#!/usr/bin/env python3
"""hooks/guard-dangerous-bash.py の振る舞いを検証する。

フックの契約 (stdin に JSON、exit 0=許可 / 2=ブロック) をそのまま叩く。
関数を直接呼ばないのは、実際に Claude Code が使う経路を検証したいため。

実行: python3 tests/test_guard_dangerous_bash.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "hooks" / "guard-dangerous-bash.py"

ALLOW = 0
BLOCK = 2


def run_guard(command, cwd=None):
    """フックを実行して終了コードを返す。"""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    result = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return result.returncode


def make_repo(tmpdir, with_hooks):
    """検証フックの有無だけが異なる git リポジトリを作る。"""
    repo = Path(tmpdir)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    if with_hooks:
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
    return repo


class TestDangerousCommands(unittest.TestCase):
    """既存の「常にNG」判定の回帰テスト。"""

    def test_rm_rf_root_is_blocked(self):
        self.assertEqual(run_guard("rm -rf /"), BLOCK)

    def test_rm_rf_home_is_blocked(self):
        self.assertEqual(run_guard("rm -rf ~"), BLOCK)

    def test_git_push_force_is_blocked(self):
        self.assertEqual(run_guard("git push --force origin main"), BLOCK)

    def test_git_reset_hard_is_blocked(self):
        self.assertEqual(run_guard("git reset --hard origin/main"), BLOCK)

    def test_rm_rf_of_specific_dir_is_allowed(self):
        self.assertEqual(run_guard("rm -rf ./build"), ALLOW)

    def test_quoted_dangerous_string_is_allowed(self):
        # コミットメッセージ中の文字列は実行されないため誤検知しない
        self.assertEqual(run_guard('git commit -m "never run rm -rf /"'), ALLOW)

    def test_plain_command_is_allowed(self):
        self.assertEqual(run_guard("ls -la"), ALLOW)


class TestVerificationBypass(unittest.TestCase):
    """--no-verify によるフック検証スキップの判定。

    このリポジトリの pre-commit フックは PUBLIC への機密混入を止めるために
    置かれている。AI が --no-verify で自動的に迂回できると機構が無効化される。
    ただしフックが無いリポジトリではスキップする対象が存在しないため素通しする。
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp_with = tempfile.TemporaryDirectory()
        cls._tmp_without = tempfile.TemporaryDirectory()
        cls.repo_with_hooks = make_repo(cls._tmp_with.name, with_hooks=True)
        cls.repo_without_hooks = make_repo(cls._tmp_without.name, with_hooks=False)

    @classmethod
    def tearDownClass(cls):
        cls._tmp_with.cleanup()
        cls._tmp_without.cleanup()

    def test_commit_no_verify_is_blocked_when_hooks_exist(self):
        self.assertEqual(
            run_guard('git commit --no-verify -m "x"', cwd=self.repo_with_hooks), BLOCK)

    def test_commit_short_n_is_blocked_when_hooks_exist(self):
        self.assertEqual(
            run_guard('git commit -n -m "x"', cwd=self.repo_with_hooks), BLOCK)

    def test_push_no_verify_is_blocked_when_hooks_exist(self):
        self.assertEqual(
            run_guard("git push --no-verify origin main", cwd=self.repo_with_hooks), BLOCK)

    def test_global_option_before_subcommand_is_blocked(self):
        self.assertEqual(
            run_guard('git -C . commit --no-verify -m "x"', cwd=self.repo_with_hooks), BLOCK)

    def test_no_verify_is_allowed_when_no_hooks_exist(self):
        # スキップする検証が存在しないため、ブロックする理由がない
        self.assertEqual(
            run_guard('git commit --no-verify -m "x"', cwd=self.repo_without_hooks), ALLOW)

    def test_no_verify_is_allowed_outside_git_repo(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(
                run_guard('git commit --no-verify -m "x"', cwd=plain), ALLOW)

    def test_push_dry_run_short_n_is_allowed(self):
        # git push -n は --dry-run であって --no-verify ではない
        self.assertEqual(
            run_guard("git push -n origin main", cwd=self.repo_with_hooks), ALLOW)

    def test_no_verify_inside_quoted_message_is_allowed(self):
        self.assertEqual(
            run_guard('git commit -m "do not use --no-verify"', cwd=self.repo_with_hooks),
            ALLOW)

    def test_no_verify_inside_heredoc_is_allowed(self):
        # ヒアドキュメント本体は実行されないテキスト
        command = 'git commit -F - <<\'EOF\'\nfix: --no-verify について書いた\nEOF'
        self.assertEqual(run_guard(command, cwd=self.repo_with_hooks), ALLOW)

    def test_normal_commit_is_allowed(self):
        self.assertEqual(
            run_guard('git commit -m "normal"', cwd=self.repo_with_hooks), ALLOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
