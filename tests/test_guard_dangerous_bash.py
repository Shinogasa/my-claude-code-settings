#!/usr/bin/env python3
"""hooks/guard-dangerous-bash.py の振る舞いを検証する。

フックの契約 (stdin に JSON、exit 0=許可 / 2=ブロック) をそのまま叩く。
関数を直接呼ばないのは、実際に Claude Code が使う経路を検証したいため。

実行: python3 tests/test_guard_dangerous_bash.py
"""
import atexit
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

# cwd を渡さないテストが、このリポジトリの git 状態に左右されないようにする。
#
# 保護ブランチ判定を入れたとき、cwd 無しの `git commit` を使うテストが
# チェックアウト中のブランチ次第で結果を変える問題が実際に起きた
# (feature ブランチでは通り、main では落ちた)。
# 既定を git 管理外のディレクトリにして、判定材料をコマンド文字列だけに絞る。
_NEUTRAL = tempfile.TemporaryDirectory(prefix="guard-test-neutral-")
atexit.register(_NEUTRAL.cleanup)
NEUTRAL_DIR = _NEUTRAL.name


def run_guard_output(command, cwd=None):
    """フックを実行して CompletedProcess を返す。メッセージ内容を見たいとき用。"""
    target = str(cwd) if cwd is not None else NEUTRAL_DIR
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": target}
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=target,
    )


def run_guard_without_cwd(command, process_cwd):
    """payload に cwd を載せずに実行する。os.getcwd() フォールバックの検証用。"""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(process_cwd),
    ).returncode


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

    def test_rm_rf_root_on_bare_second_line_is_blocked(self):
        # ; や && を介さず、裸の改行だけで区切られた2つ目のコマンドも検出する
        self.assertEqual(run_guard("echo hello\nrm -rf /"), BLOCK)

    def test_rm_rf_root_after_line_continuation_is_blocked(self):
        # `\` + 改行 (行継続) を挟んでも先頭トークンが壊れず検出できる
        self.assertEqual(run_guard("echo hello && \\\nrm -rf /"), BLOCK)

    def test_multiline_commit_message_with_quoted_newline_is_allowed(self):
        # クォート内の改行はコマンド区切りではなくメッセージの一部として扱う
        self.assertEqual(run_guard('git commit -m "line1\nline2"'), ALLOW)


class TestForcePushDetection(unittest.TestCase):
    """force push の綴り違いを漏れなく拾えるか。

    当初の実装は `"--force" in tokens or "-f" in tokens` という完全一致だったため、
    --force-with-lease / -uf / `git -C path push --force` が素通りしていた。
    フラグを接頭辞で拾う形に変えた後も、refspec の "+" (`git push origin +main`) が
    残っていた。「禁止は能力を消さず経路を変えるだけ」がそのまま出た経路。

    ここでは「force push だと認識できるか」だけを見る。対象 ref による許可/拒否は
    TestForcePushTarget を参照。保護ブランチ (main) を対象にして、
    検出できなければ ALLOW に落ちることを利用している。
    """

    def test_force_with_lease_is_detected(self):
        self.assertEqual(run_guard("git push --force-with-lease origin main"), BLOCK)

    def test_force_with_lease_with_expected_oid_is_detected(self):
        self.assertEqual(
            run_guard("git push --force-with-lease=main:abc123 origin main"), BLOCK
        )

    def test_force_if_includes_is_detected(self):
        self.assertEqual(run_guard("git push --force-if-includes origin main"), BLOCK)

    def test_bundled_short_force_flag_is_detected(self):
        self.assertEqual(run_guard("git push -uf origin main"), BLOCK)

    def test_force_after_global_option_is_detected(self):
        self.assertEqual(run_guard("git -C /tmp/repo push --force origin main"), BLOCK)

    def test_flag_after_refspec_is_detected(self):
        self.assertEqual(run_guard("git push origin main --force"), BLOCK)

    def test_plus_refspec_is_detected(self):
        # フラグを一切使わない force update。ここが最後まで空いていた。
        self.assertEqual(run_guard("git push origin +main"), BLOCK)

    def test_plus_refspec_with_source_is_detected(self):
        self.assertEqual(run_guard("git push origin +HEAD:main"), BLOCK)

    def test_plain_push_is_allowed(self):
        self.assertEqual(run_guard("git push origin main"), ALLOW)

    def test_set_upstream_without_force_is_allowed(self):
        self.assertEqual(run_guard("git push -u origin feature"), ALLOW)

    def test_dry_run_is_allowed(self):
        self.assertEqual(run_guard("git push --dry-run origin main"), ALLOW)

    def test_follow_tags_is_allowed(self):
        # `--f` で始まるが force ではないオプションを誤検知しない
        self.assertEqual(run_guard("git push --follow-tags origin main"), ALLOW)

    def test_force_spelling_inside_commit_message_is_allowed(self):
        self.assertEqual(
            run_guard('git commit -m "avoid --force-with-lease"'), ALLOW
        )


class TestForcePushTarget(unittest.TestCase):
    """force push は対象 ref で許可/拒否を分ける。

    未マージの自ブランチを rebase / amend して上書きする用途は正当であり、
    塞ぐと「履歴に残したくないものが残る」方へ倒れる。
    一方リモートの保護ブランチは、上書きすると他人のコミットが失われ、
    reflog は上書きした本人の手元にしか無いため復旧経路が無い。

    対象を特定できない形は「安全」ではなく「検査できなかった」として止める。
    """

    def test_feature_branch_is_allowed(self):
        self.assertEqual(
            run_guard("git push --force-with-lease origin feature"), ALLOW
        )

    def test_feature_branch_with_plain_force_is_allowed(self):
        self.assertEqual(run_guard("git push --force origin feature"), ALLOW)

    def test_plus_refspec_to_feature_branch_is_allowed(self):
        self.assertEqual(run_guard("git push origin +feature"), ALLOW)

    def test_master_is_blocked(self):
        self.assertEqual(run_guard("git push --force origin master"), BLOCK)

    def test_fully_qualified_protected_ref_is_blocked(self):
        self.assertEqual(
            run_guard("git push --force origin refs/heads/main"), BLOCK
        )

    def test_head_to_protected_ref_is_blocked(self):
        self.assertEqual(run_guard("git push --force origin HEAD:main"), BLOCK)

    def test_multiple_refspecs_block_if_any_is_protected(self):
        self.assertEqual(
            run_guard("git push --force origin feature main"), BLOCK
        )

    def test_omitted_refspec_outside_repo_is_blocked(self):
        # 宛先が現在のブランチ依存になる形。git 管理外では特定できないため止める。
        self.assertEqual(run_guard("git push --force"), BLOCK)

    def test_broadcast_flag_is_blocked(self):
        # --all / --mirror は対象を1つに絞れない (保護ブランチを含みうる)
        self.assertEqual(run_guard("git push --force --all origin"), BLOCK)
        self.assertEqual(run_guard("git push --mirror origin"), ALLOW)
        self.assertEqual(run_guard("git push --force --mirror origin"), BLOCK)

    def test_option_value_is_not_read_as_refspec(self):
        # `--receive-pack main` の値を refspec と誤読すると、対象が特定できたことに
        # なってしまう。正しく読み飛ばせば refspec 省略形として止まる。
        self.assertEqual(
            run_guard("git push --force --receive-pack main origin"), BLOCK
        )


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


class TestTerraformSecretExposure(unittest.TestCase):
    """state の中身を平文で出す terraform 操作の判定。

    terraform の state は DB パスワード・秘密鍵・トークンを平文で保持する
    (sensitive = true は表示の抑制であって state の暗号化ではない)。
    state を壊さないため書き換え側の判定では拾えないが、出力は
    ファイル・ターミナル・会話ログに複製として残るため、実行主体は人間にする。

    フラグの判定も allowlist。denylist にすると terraform が新しい出力フラグを
    追加したとき黙って通る。
    """

    def test_state_pull_is_blocked(self):
        # state を1バイトも変えないが、中身を丸ごと出力する
        self.assertEqual(run_guard("terraform state pull"), BLOCK)

    def test_output_json_is_blocked(self):
        self.assertEqual(run_guard("terraform output -json"), BLOCK)

    def test_output_raw_is_blocked(self):
        self.assertEqual(run_guard("terraform output -raw db_password"), BLOCK)

    def test_output_double_dash_json_is_blocked(self):
        # Go のフラグは -json と --json の両方を受け付ける
        self.assertEqual(run_guard("terraform output --json"), BLOCK)

    def test_show_json_is_blocked(self):
        self.assertEqual(run_guard("terraform show -json"), BLOCK)

    def test_unknown_output_flag_is_blocked(self):
        # allowlist にしている理由。将来 terraform が追加する出力形式も止まる
        self.assertEqual(run_guard("terraform output -yaml"), BLOCK)

    def test_output_json_with_chdir_is_blocked(self):
        self.assertEqual(run_guard("terraform -chdir=infra output -json"), BLOCK)

    def test_exposure_message_explains_plaintext(self):
        result = run_guard_output("terraform state pull")
        self.assertIn("平文", result.stderr)

    def test_bare_output_is_allowed(self):
        # sensitive な値は <sensitive> に伏せられる
        self.assertEqual(run_guard("terraform output"), ALLOW)

    def test_named_output_is_allowed(self):
        self.assertEqual(run_guard("terraform output db_url"), ALLOW)

    def test_output_no_color_is_allowed(self):
        self.assertEqual(run_guard("terraform output -no-color"), ALLOW)

    def test_output_with_chdir_only_is_allowed(self):
        # グローバルオプションをサブコマンドのフラグと取り違えない
        self.assertEqual(run_guard("terraform -chdir=infra output"), ALLOW)

    def test_bare_show_is_allowed(self):
        self.assertEqual(run_guard("terraform show"), ALLOW)

    def test_state_list_is_still_allowed(self):
        self.assertEqual(run_guard("terraform state list"), ALLOW)

    def test_quoted_output_json_is_allowed(self):
        self.assertEqual(run_guard('echo "terraform output -json"'), ALLOW)


class TestMissingCwdFallback(unittest.TestCase):
    """payload に cwd が無いときの挙動を固定する。

    ホストは通常 cwd を渡すが、フックは無ければ os.getcwd() へフォールバックする。
    この経路は「フックプロセスがたまたま居るディレクトリ」で判定するため、
    無関係なリポジトリのブランチを見る可能性がある。

    既定 cwd を中立化した結果、この経路を通るテストが1つも無くなった。
    再発防止と引き換えに観測窓を塞がないよう、ここで明示的に固定する。
    フォールバックの是非は tasks/backlog.md に課題として登録した。
    """

    def test_falls_back_to_process_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp, with_hooks=False, branch="main")
            self.assertEqual(run_guard_without_cwd('git commit -m "x"', repo), BLOCK)

    def test_fallback_outside_git_repo_allows(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(run_guard_without_cwd('git commit -m "x"', plain), ALLOW)


class TestEnvironmentIndependence(unittest.TestCase):
    """cwd を渡さないテストが、このリポジトリの git 状態に影響されないこと。"""

    def test_default_cwd_is_not_a_git_repo(self):
        result = subprocess.run(
            ["git", "-C", NEUTRAL_DIR, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_commit_without_explicit_cwd_is_allowed_on_any_branch(self):
        # main をチェックアウトした状態でも結果が変わらないこと
        self.assertEqual(run_guard('git commit -m "x"'), ALLOW)


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

    def test_heredoc_nested_in_command_substitution_on_main_is_blocked(self):
        # CLAUDE.md が指定する `git commit -m "$(cat <<'EOF' ... EOF)"` の形。
        # ヒアドキュメント終端の直後にコマンド置換の閉じ括弧 `)"` が別行に落ちるため、
        # 行ごとに shlex へ渡す実装では引用符が閉じずパース不能になり、
        # コマンド全体の検査(保護ブランチ判定含む)が素通りしていた。
        command = (
            "git add foo && git commit -m \"$(cat <<'EOF'\n"
            "feat: x\n"
            "\n"
            "Co-Authored-By: t <t@example.com>\n"
            "EOF\n"
            ")\""
        )
        self.assertEqual(run_guard(command, cwd=self.on_main), BLOCK)

    def test_commit_chained_after_git_add_is_blocked(self):
        # && で連結されていても各サブコマンドを見るので検出できる
        self.assertEqual(
            run_guard('git add -A && git commit -m "x"', cwd=self.on_main), BLOCK)

    def test_commit_chained_with_line_continuation_is_blocked(self):
        # 実際に踏んだ形: `&& \` の行継続 + `-C` + ヒアドキュメントネストの組み合わせ。
        # 行継続を素通しすると `\ngit` のような壊れたトークンになり検出をすり抜けていた。
        command = (
            'echo x >> f && \\\n'
            f'git -C {self.on_main} add f && \\\n'
            f'git -C {self.on_main} commit -m "$(cat <<\'EOF\'\n'
            'feat: x\n'
            'EOF\n'
            ')"'
        )
        self.assertEqual(run_guard(command), BLOCK)

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
