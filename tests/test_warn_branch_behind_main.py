#!/usr/bin/env python3
"""hooks/warn-branch-behind-main.sh の振る舞いを検証する。

フックの契約 (stdin に JSON、stdout に PreToolUse の判定 JSON) をそのまま叩く。

このフックは git の操作対象を**プロセスの cwd** から決める (payload の cwd を見ない)
ため、テストでも subprocess の cwd を切り替えて実行する。

実行: python3 tests/test_warn_branch_behind_main.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "warn-branch-behind-main.sh"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


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
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(origin)], check=True)

    work = base / "work"
    # 空のベアリポジトリの clone は警告を出すが、この時点では正常な状態
    subprocess.run(["git", "clone", "-q", str(origin), str(work)],
                   check=True, capture_output=True, text=True)
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
        subprocess.run(["git", "clone", "-q", str(origin), str(other)],
                       check=True, capture_output=True, text=True)
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
