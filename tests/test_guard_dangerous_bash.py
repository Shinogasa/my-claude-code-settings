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


def run_guard_output(command, cwd=None):
    """フックを実行して CompletedProcess を返す。メッセージ内容を見たいとき用。"""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def run_guard(command, cwd=None):
    """フックを実行して終了コードを返す。"""
    return run_guard_output(command, cwd).returncode


def make_repo(tmpdir, with_hooks, branch="work", with_commit=True):
    """git リポジトリを作る。

    branch の既定を main/master 以外にしているのは意図的。既存の --no-verify 判定の
    テストは保護ブランチ判定と無関係なので、init.defaultBranch の設定値によって
    結果が変わらないよう固定する。

    with_commit=False は「まだ1つもコミットが無いリポジトリ」(unborn branch) を作る。
    """
    repo = Path(tmpdir)
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True)
    if with_commit:
        subprocess.run(
            ["git", "-C", str(repo),
             "-c", "user.email=t@example.com", "-c", "user.name=t",
             "commit", "-q", "--allow-empty", "-m", "init"],
            check=True,
        )
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


class TestTerraformStateWrite(unittest.TestCase):
    """terraform state の書き換え操作の判定。

    state を書き換える操作は、実在するリソースと設定の対応を壊す。remote backend
    では自動バックアップが作られないため、backend の versioning が無ければ
    復旧できない。ブランチの遅れとは無関係に成立する事故なので、状況に依存せず止める。

    判定は allowlist（読み取り系だけ通す）。denylist にすると terraform が
    state サブコマンドを追加したとき、新しい書き換え操作が黙って通る。
    """

    def test_state_rm_is_blocked(self):
        self.assertEqual(run_guard("terraform state rm aws_instance.web"), BLOCK)

    def test_state_push_is_blocked(self):
        # state 全体の差し替え。rm より影響範囲が大きい
        self.assertEqual(run_guard("terraform state push new.tfstate"), BLOCK)

    def test_state_mv_is_blocked(self):
        self.assertEqual(run_guard("terraform state mv a.b a.c"), BLOCK)

    def test_state_replace_provider_is_blocked(self):
        self.assertEqual(
            run_guard("terraform state replace-provider hashicorp/aws registry/aws"), BLOCK)

    def test_unknown_state_subcommand_is_blocked(self):
        # allowlist にしている理由そのもの。将来 terraform が追加する
        # 書き換え操作も、名前を知らないまま守る側に入る
        self.assertEqual(run_guard("terraform state frobnicate x"), BLOCK)

    def test_state_write_with_chdir_is_blocked(self):
        # terraform のグローバルオプションはサブコマンドの前に置かれる
        self.assertEqual(
            run_guard("terraform -chdir=infra state rm module.db"), BLOCK)

    def test_state_write_after_cd_is_blocked(self):
        self.assertEqual(
            run_guard("cd infra && terraform state rm aws_s3_bucket.logs"), BLOCK)

    def test_state_rm_with_backup_flag_is_blocked(self):
        # -backup を付けても remote backend では意味がないため素通ししない
        self.assertEqual(
            run_guard("terraform state rm -backup=b.json aws_instance.web"), BLOCK)

    def test_push_message_names_the_whole_state(self):
        # サブコマンドごとに影響範囲が違うため、メッセージも分ける
        result = run_guard_output("terraform state push new.tfstate")
        self.assertIn("丸ごと", result.stderr)

    def test_state_list_is_allowed(self):
        self.assertEqual(run_guard("terraform state list"), ALLOW)

    def test_state_show_is_allowed(self):
        self.assertEqual(run_guard("terraform state show aws_instance.web"), ALLOW)

    def test_state_pull_is_allowed(self):
        self.assertEqual(run_guard("terraform state pull"), ALLOW)

    def test_bare_state_is_allowed(self):
        # サブコマンド無しは usage を出すだけで state を変えない
        self.assertEqual(run_guard("terraform state"), ALLOW)

    def test_apply_is_allowed(self):
        # ブランチの遅れを見る判定は warn-branch-behind-main.sh の管轄
        self.assertEqual(run_guard("terraform apply -auto-approve"), ALLOW)

    def test_quoted_state_rm_is_allowed(self):
        self.assertEqual(
            run_guard('echo "terraform state rm は危険"'), ALLOW)

    def test_state_rm_inside_heredoc_is_allowed(self):
        command = "cat <<'EOF'\nterraform state rm aws_instance.web\nEOF"
        self.assertEqual(run_guard(command), ALLOW)


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


class TestProtectedBranchCommit(unittest.TestCase):
    """保護ブランチ (main / master) への直接コミットの判定。

    「作業前にブランチを切る」は CLAUDE.md の散文ルールだったが、守らなくても
    何も起きないため強制力が無かった。コミット時点で機構的に止める。
    """

    @classmethod
    def setUpClass(cls):
        cls._tmps = [tempfile.TemporaryDirectory() for _ in range(4)]
        cls.on_main = make_repo(cls._tmps[0].name, with_hooks=False, branch="main")
        cls.on_master = make_repo(cls._tmps[1].name, with_hooks=False, branch="master")
        cls.on_feature = make_repo(cls._tmps[2].name, with_hooks=False, branch="feat/x")
        cls.unborn_main = make_repo(
            cls._tmps[3].name, with_hooks=False, branch="main", with_commit=False)

    @classmethod
    def tearDownClass(cls):
        for tmp in cls._tmps:
            tmp.cleanup()

    def test_commit_on_main_is_blocked(self):
        self.assertEqual(run_guard('git commit -m "x"', cwd=self.on_main), BLOCK)

    def test_commit_on_master_is_blocked(self):
        self.assertEqual(run_guard('git commit -m "x"', cwd=self.on_master), BLOCK)

    def test_amend_on_main_is_blocked(self):
        self.assertEqual(run_guard("git commit --amend --no-edit", cwd=self.on_main), BLOCK)

    def test_heredoc_commit_on_main_is_blocked(self):
        # ヒアドキュメント本体は取り除かれるが、実行されるのは git commit なので止める
        command = "git commit -F - <<'EOF'\nfeat: x\nEOF"
        self.assertEqual(run_guard(command, cwd=self.on_main), BLOCK)

    def test_commit_chained_after_git_add_is_blocked(self):
        # && で連結されていても各サブコマンドを見るので検出できる
        self.assertEqual(
            run_guard('git add -A && git commit -m "x"', cwd=self.on_main), BLOCK)

    def test_commit_on_feature_branch_is_allowed(self):
        self.assertEqual(run_guard('git commit -m "x"', cwd=self.on_feature), ALLOW)

    def test_initial_commit_on_main_is_allowed(self):
        # まだ1つもコミットが無いリポジトリの初回コミットはブランチを切りようがない
        self.assertEqual(run_guard('git commit -m "init"', cwd=self.unborn_main), ALLOW)

    def test_commit_outside_git_repo_is_allowed(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(run_guard('git commit -m "x"', cwd=plain), ALLOW)

    def test_commit_on_detached_head_is_allowed(self):
        # detached HEAD は名前付きブランチ上に無いため保護対象ではない
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, with_hooks=False, branch="main")
            subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach"], check=True)
            self.assertEqual(run_guard('git commit -m "x"', cwd=repo), ALLOW)

    def test_dash_c_target_repo_is_used_for_judgement(self):
        # `git -C <main のリポジトリ>` は cwd ではなくそちらのブランチで判定する
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(
                run_guard(f'git -C {self.on_main} commit -m "x"', cwd=plain), BLOCK)

    def test_push_to_main_is_not_blocked(self):
        # 対象はコミットのみ。push は既存の --force 判定の管轄
        self.assertEqual(run_guard("git push origin main", cwd=self.on_main), ALLOW)

    def test_commit_word_in_other_command_is_allowed(self):
        self.assertEqual(run_guard('echo "git commit -m x"', cwd=self.on_main), ALLOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
