#!/usr/bin/env python3
"""hooks/warn-branch-behind-main.sh の振る舞いを検証する。

フックの契約 (stdin に JSON、stdout に PreToolUse の判定 JSON) をそのまま叩く。

このフックは git の操作対象を**プロセスの cwd** から決める (payload の cwd を見ない)
ため、テストでも subprocess の cwd を切り替えて実行する。

実行: python3 tests/test_warn_branch_behind_main.py
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if __package__:
    from tests.git_fixture import git
else:
    from git_fixture import git

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "warn-branch-behind-main.sh"
GUARD = REPO_ROOT / "hooks" / "guard-dangerous-bash.py"


def guard_prefix_words():
    """guard-dangerous-bash が判定の前に取り除く前置きの語。"""
    spec = importlib.util.spec_from_file_location("guard_dangerous_bash", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.PREFIX_WORDS)


def run_hook(command, cwd):
    """フックを実行して stdout を返す。出力が無ければ空文字列。"""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    return result.stdout.strip()


def decision(command, cwd):
    """permissionDecision を返す。判定が無ければ None。"""
    out = run_hook(command, cwd)
    if not out:
        return None
    return json.loads(out).get("hookSpecificOutput", {}).get("permissionDecision")


def make_repo(tmpdir, behind, branch="feat/x"):
    """origin より `behind` コミット遅れた作業ブランチを持つリポジトリを作る。

    origin をローカルのベアリポジトリにしているのは、フックが実行する
    git fetch をネットワーク無しで成立させるため。
    """
    base = Path(tmpdir)
    origin = base / "origin.git"
    git(base, "init", "--bare", "-q", "-b", "main", str(origin))

    work = base / "work"
    # 空のベアリポジトリの clone は警告を出すが、この時点では正常な状態
    git(base, "clone", "-q", str(origin), str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")

    (work / "main.tf").write_text("# init\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "init")
    git(work, "push", "-q", "origin", "main")
    git(work, "switch", "-q", "-c", branch)

    if behind:
        # 別クローンから origin/main だけを進めることで work を遅らせる
        other = base / "other"
        git(base, "clone", "-q", str(origin), str(other))
        git(other, "config", "user.email", "t@example.com")
        git(other, "config", "user.name", "t")
        for i in range(behind):
            (other / f"r{i}.tf").write_text(f"# {i}\n")
            git(other, "add", "-A")
            git(other, "commit", "-q", "-m", f"c{i}")
        git(other, "push", "-q", "origin", "main")

    return work


class TestBehindBranch(unittest.TestCase):
    """origin/main より遅れている状態での判定。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = make_repo(cls._tmp.name, behind=2)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_apply_is_denied(self):
        self.assertEqual(decision("terraform apply", self.repo), "deny")

    def test_apply_auto_approve_is_denied(self):
        self.assertEqual(decision("terraform apply -auto-approve", self.repo), "deny")

    def test_destroy_is_denied(self):
        self.assertEqual(decision("terraform destroy", self.repo), "deny")

    def test_apply_after_cd_is_denied(self):
        # `cd dir && terraform apply` もコマンド位置として扱う
        self.assertEqual(decision("cd . && terraform apply", self.repo), "deny")

    def test_deny_reason_tells_how_to_recover(self):
        out = json.loads(run_hook("terraform apply", self.repo))
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("git merge origin/main", reason)
        self.assertIn("2 コミット遅れ", reason)

    def test_plan_warns_without_blocking(self):
        # plan は偽陽性に気づくための経路なので止めない
        out = json.loads(run_hook("terraform plan", self.repo))
        self.assertIsNone(out["hookSpecificOutput"].get("permissionDecision"))
        self.assertIn("additionalContext", out["hookSpecificOutput"])

    def test_state_only_warns(self):
        # 現在の境界を固定する。state も state を書き換えるが警告止まり
        self.assertIsNone(decision("terraform state list", self.repo))

    def test_fmt_is_ignored(self):
        self.assertEqual(run_hook("terraform fmt -check", self.repo), "")

    def test_version_is_ignored(self):
        self.assertEqual(run_hook("terraform version", self.repo), "")

    def test_quoted_command_is_ignored(self):
        # 文字列中の語には反応しない
        self.assertEqual(
            run_hook('echo terraform apply is dangerous', self.repo), "")

    def test_unrelated_command_is_ignored(self):
        self.assertEqual(run_hook("ls -la", self.repo), "")

    def test_prefixed_apply_is_denied(self):
        # 行頭か ;&|( の直後の terraform しか見ていなかった頃は、どれも素通りしていた（2026-10-23）。
        # Codex は codex/RTK.md の指示で全コマンドに rtk を付けるので、deny が効いていなかった
        for command in ("rtk terraform apply", "AWS_PROFILE=dev terraform apply",
                        "A=1 B=2 terraform apply", "env terraform apply",
                        "env AWS_PROFILE=dev terraform apply", "time terraform apply",
                        "time -p terraform apply", "cd . && rtk terraform destroy"):
            with self.subTest(command=command):
                self.assertEqual(decision(command, self.repo), "deny")

    def test_guard_prefix_words_are_also_skipped(self):
        # guard-dangerous-bash が取り除く前置きと、このフックが読み飛ばす前置きをそろえる。
        # 片方にだけ足すと、もう片方が素通しになる（rtk で実際に起きた）
        for word in sorted(guard_prefix_words() | {"rtk"}):
            with self.subTest(word=word):
                self.assertEqual(decision(f"{word} terraform apply", self.repo), "deny")

    def test_rtk_proxy_is_skipped(self):
        # guard-dangerous-bash の skip_rtk_wrapper と同じく `rtk [opts] proxy [opts]` を読み飛ばす
        for command in ("rtk proxy terraform apply", "rtk -v proxy terraform destroy",
                        "rtk proxy tofu apply"):
            with self.subTest(command=command):
                self.assertEqual(decision(command, self.repo), "deny")

    def test_assignment_with_quoted_or_substituted_value_is_skipped(self):
        # 値の途中の空白で代入が切れると、残りが前置きに当たらず素通りしていた（セキュリティレビュー）
        for command in ('AWS_PROFILE="my dev" terraform apply', "X='a b' terraform apply",
                        "TF_VAR_x=$(date +%s) terraform apply", "FOO=\"\" BAR='x y' tofu destroy",
                        # バックスラッシュでエスケープした文字（コミット後の自動セキュリティレビュー）
                        'X=a\\"b terraform apply', "X=a\\ b terraform apply"):
            with self.subTest(command=command):
                self.assertEqual(decision(command, self.repo), "deny")

    def test_word_after_non_prefix_command_is_ignored(self):
        for command in ("echo rtk terraform apply", "echo AWS_PROFILE=dev terraform apply",
                        "echo proxy terraform apply"):
            with self.subTest(command=command):
                self.assertEqual(run_hook(command, self.repo), "")

    def test_tofu_is_treated_like_terraform(self):
        # OpenTofu は terraform と置き換えられる別実装で、遅れたブランチでの事故も同じ形で起きる
        for command in ("tofu apply", "tofu destroy", "rtk tofu apply"):
            with self.subTest(command=command):
                self.assertEqual(decision(command, self.repo), "deny")
        out = json.loads(run_hook("tofu plan", self.repo))
        self.assertIsNone(out["hookSpecificOutput"].get("permissionDecision"))


class TestUpToDateBranch(unittest.TestCase):
    """遅れていない場合は黙って通す。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = make_repo(cls._tmp.name, behind=0)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_apply_is_allowed(self):
        self.assertEqual(run_hook("terraform apply", self.repo), "")

    def test_destroy_is_allowed(self):
        self.assertEqual(run_hook("terraform destroy", self.repo), "")


class TestOutsideGitRepo(unittest.TestCase):
    """git 管理外では判定できないので通す (fail-open)。"""

    def test_apply_is_allowed(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(run_hook("terraform apply", plain), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
