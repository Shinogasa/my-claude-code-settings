#!/usr/bin/env python3
"""bin/detect-parallel-sessions の振る舞いを検証する。

このコマンドはプロセスの cwd を基準に判定するため、テストでも subprocess の
cwd を切り替えて実行する。実プロセスの列挙は環境変数
DETECT_PARALLEL_SESSIONS_FIXTURE で差し替える（pgrep/lsof に依存させない）。

実行: python3 tests/test_detect_parallel_sessions.py
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

if __package__:
    from tests.git_fixture import git
else:
    from git_fixture import git

REPO_ROOT = Path(__file__).resolve().parent.parent
DETECT = REPO_ROOT / "bin" / "detect-parallel-sessions"


def make_repo(base, name):
    """コミットを1つ持つリポジトリを作って返す。"""
    repo = Path(base) / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("init\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def run_detect(cwd, sessions, self_pid="0"):
    """sessions: [(pid, cwd), ...] を列挙結果として注入して実行し、JSON を返す。"""
    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
        for pid, session_cwd in sessions:
            fh.write(f"{pid}\t{session_cwd}\n")
        fixture = fh.name
    try:
        env = dict(os.environ)
        env["DETECT_PARALLEL_SESSIONS_FIXTURE"] = fixture
        result = subprocess.run(
            ["bash", str(DETECT), "--self-pid", str(self_pid)],
            capture_output=True, text=True, cwd=str(cwd), env=env,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout or "[]")
    finally:
        os.unlink(fixture)


class TestCollisionDetection(unittest.TestCase):
    """同一リポジトリ・同一作業ディレクトリのセッションだけを衝突とみなす。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = make_repo(cls._tmp.name, "repo")
        cls.other = make_repo(cls._tmp.name, "other")
        cls.worktree = Path(cls._tmp.name) / "wt"
        git(cls.repo, "worktree", "add", "-q", "--detach", str(cls.worktree), "HEAD")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_same_cwd_session_is_detected(self):
        found = run_detect(self.repo, [("111", str(self.repo))], self_pid="999")
        self.assertEqual([s["pid"] for s in found], [111])

    def test_own_pid_is_excluded(self):
        found = run_detect(self.repo, [("111", str(self.repo))], self_pid="111")
        self.assertEqual(found, [])

    def test_separated_worktree_is_not_detected(self):
        # common-dir は一致するが作業ディレクトリが違う = 分離済み
        found = run_detect(self.repo, [("111", str(self.worktree))], self_pid="999")
        self.assertEqual(found, [])

    def test_other_repository_is_not_leaked(self):
        # 無関係なプロジェクトの絶対パスを出力に含めない
        found = run_detect(self.repo, [("111", str(self.other))], self_pid="999")
        self.assertEqual(found, [])

    def test_mixed_sessions_return_only_colliding(self):
        found = run_detect(self.repo, [
            ("111", str(self.other)),
            ("222", str(self.repo)),
            ("333", str(self.worktree)),
        ], self_pid="999")
        self.assertEqual([s["pid"] for s in found], [222])
        self.assertEqual(found[0]["cwd"], str(Path(self.repo).resolve()))

    def test_no_sessions_returns_empty_array(self):
        self.assertEqual(run_detect(self.repo, [], self_pid="999"), [])

    def test_nonexistent_cwd_is_skipped(self):
        found = run_detect(self.repo, [("111", "/no/such/dir")], self_pid="999")
        self.assertEqual(found, [])


# 検出できなかったときの終了コード。「いない」(0 と []) と区別する。
# SessionStart フックは 0 以外で黙って抜けるので、フック側は fail-open のまま。
EXIT_UNDETECTABLE = 2


def run_undetectable(cwd, env):
    result = subprocess.run(
        ["bash", str(DETECT), "--self-pid", "999"],
        capture_output=True, text=True, cwd=str(cwd), env=env, timeout=10,
    )
    return result


class TestOutsideGitRepo(unittest.TestCase):
    """git 管理外では判定できないので、「いない」とは区別して返す。"""

    def test_reports_undetectable(self):
        with tempfile.TemporaryDirectory() as plain:
            env = dict(os.environ)
            env["DETECT_PARALLEL_SESSIONS_FIXTURE"] = os.devnull
            result = run_undetectable(plain, env)
            self.assertEqual(result.returncode, EXIT_UNDETECTABLE, result.stderr)
            # 標準出力に [] を出すと、出力だけを読む呼び出し元が「いない」と誤読する
            self.assertEqual(result.stdout, "")
            self.assertIn("検出できなかった", result.stderr)


class TestMissingTools(unittest.TestCase):
    """必要な道具が欠けたら、「いない」とは区別して返す。

    差し込み口を使わず、既定の列挙経路 (pgrep + lsof) を通したうえで
    1つだけを PATH から隠す。
    """

    TOOLS = ("bash", "git", "jq", "ps", "basename", "pgrep", "lsof",
             "grep", "cut", "cat", "tr")

    def run_without(self, hidden):
        with tempfile.TemporaryDirectory() as base:
            repo = make_repo(base, "repo")
            bindir = Path(base) / "bin"
            bindir.mkdir()
            for tool in self.TOOLS:
                found = shutil.which(tool)
                if found and tool != hidden:
                    (bindir / tool).symlink_to(found)
            env = dict(os.environ)
            env["PATH"] = str(bindir)
            env.pop("DETECT_PARALLEL_SESSIONS_FIXTURE", None)
            return run_undetectable(repo, env)

    def test_each_missing_tool_is_reported(self):
        for hidden in ("lsof", "pgrep", "jq", "git"):
            with self.subTest(hidden=hidden):
                self.assertIsNotNone(shutil.which(hidden), f"{hidden} が無い環境ではこの検査は測定にならない")
                result = self.run_without(hidden)
                self.assertEqual(result.returncode, EXIT_UNDETECTABLE, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn(hidden, result.stderr)

    def test_all_tools_present_is_not_reported(self):
        # 隠す道具が無ければ検出は成功する。上の検査が PATH の作り方のせいで落ちていないことの対照
        result = self.run_without(None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsInstance(json.loads(result.stdout), list)


class TestMalformedArguments(unittest.TestCase):
    """不正な引数でもハングせず fail-open で終わる。

    値の無い --self-pid は、引数を1つずつ落とす実装でなければ無限ループになる。
    """

    def _run(self, *args):
        with tempfile.TemporaryDirectory() as base:
            repo = make_repo(base, "repo")
            env = dict(os.environ)
            env["DETECT_PARALLEL_SESSIONS_FIXTURE"] = os.devnull
            return subprocess.run(
                ["bash", str(DETECT), *args],
                capture_output=True, text=True, cwd=str(repo), env=env,
                timeout=10,
            )

    def test_self_pid_without_value_terminates(self):
        result = self._run("--self-pid")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout or "[]"), [])

    def test_no_arguments_terminates(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_argument_is_ignored(self):
        result = self._run("--unknown", "--self-pid", "999")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout or "[]"), [])


class TestProductionSelfExclusion(unittest.TestCase):
    """--self-pid を渡さない本番経路で、自分自身が除外されることを確認する。

    フックは検出コマンドを引数なしで呼ぶため、この経路が本番で通る唯一の経路。
    テストプロセスの pid は bash スクリプトから見て祖先にあたるので、
    祖先集合による除外が効いていれば必ず空配列になる。
    """

    def test_own_process_tree_is_excluded(self):
        with tempfile.TemporaryDirectory() as base:
            repo = make_repo(base, "repo")
            fixture = Path(base) / "fixture.tsv"
            fixture.write_text(f"{os.getpid()}\t{repo}\n")
            env = dict(os.environ)
            env["DETECT_PARALLEL_SESSIONS_FIXTURE"] = str(fixture)
            result = subprocess.run(
                ["bash", str(DETECT)],          # --self-pid を渡さない
                capture_output=True, text=True, cwd=str(repo), env=env,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout or "[]"), [])

    def test_direct_parent_is_excluded_when_ps_is_unavailable(self):
        with tempfile.TemporaryDirectory() as base:
            repo = make_repo(base, "repo")
            fixture = Path(base) / "fixture.tsv"
            fixture.write_text(f"{os.getpid()}\t{repo}\n")

            bindir = Path(base) / "bin"
            bindir.mkdir()
            ps = bindir / "ps"
            ps.write_text("#!/bin/sh\nexit 1\n")
            ps.chmod(0o755)

            env = dict(os.environ)
            env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
            env["DETECT_PARALLEL_SESSIONS_FIXTURE"] = str(fixture)
            result = subprocess.run(
                ["bash", str(DETECT)],
                capture_output=True, text=True, cwd=str(repo), env=env,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout or "[]"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
