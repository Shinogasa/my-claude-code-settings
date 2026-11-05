#!/usr/bin/env python3
"""statusline.js の表示を検証する（worktree 内の元リポジトリ名、200k 警告を出さないこと）。

入力 JSON の形は、実際のセッションで採取した値に合わせている（2026-11-05）。
- worktree のディレクトリで直接起動: workspace.git_worktree だけがあり、worktree は null
- --worktree / EnterWorktree: workspace.git_worktree と worktree.* の両方がある
- worktree の外: どちらも無い（worktree は null）

git の呼び出しは PATH 先頭の shim で記録し、worktree の外で git を余計に呼んでいないかを数える。

実行: python3 tests/test_statusline.py
"""
import json
import os
import re
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
STATUSLINE = REPO_ROOT / "statusline.js"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def make_repo(base, name):
    """コミットを1つ持つリポジトリを作って返す。"""
    repo = Path(base) / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "f.txt").write_text("init\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


class StatuslineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="statusline-test-"))
        self.repo = make_repo(self.tmp, "origin_repo")
        self.worktree = self.repo / ".claude" / "worktrees" / "wt-name"
        git(self.repo, "worktree", "add", "-q", "-b", "wt-branch", str(self.worktree))
        self.outside = self.tmp / "not_a_repo"
        self.outside.mkdir()

        # git の呼び出しを記録する shim
        self.shim_dir = self.tmp / "shim"
        self.shim_dir.mkdir()
        self.git_log = self.tmp / "git-calls.log"
        real_git = shutil.which("git")
        shim = self.shim_dir / "git"
        shim.write_text(
            "#!/bin/sh\n"
            f'echo "$*" >> "{self.git_log}"\n'
            f'exec "{real_git}" "$@"\n'
        )
        shim.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_statusline(self, data):
        """statusline.js に JSON を流し、色を除いた1行目と git の呼び出し一覧を返す。"""
        if self.git_log.exists():
            self.git_log.unlink()
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_") and not key.startswith("ANTHROPIC_")
        }
        environment.update({
            "PATH": f"{self.shim_dir}{os.pathsep}{environment.get('PATH', '')}",
            "HOME": str(self.tmp),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            # 並列実行の負荷で既定の500msを超え、git の情報が消えて揺れるのを防ぐ
            "STATUSLINE_GIT_TIMEOUT_MS": "10000",
        })
        result = subprocess.run(
            ["node", str(STATUSLINE)], input=json.dumps(data), env=environment,
            capture_output=True, text=True, timeout=10, check=True,
        )
        lines = [ANSI.sub("", line) for line in result.stdout.splitlines()]
        self.lines = lines
        calls = self.git_log.read_text().splitlines() if self.git_log.exists() else []
        return lines[0], calls

    def workspace(self, directory, **extra):
        return {"current_dir": str(directory), "project_dir": str(directory), **extra}

    def test_worktreeで直接起動したときは元リポジトリ名とworktree名を出す(self):
        line, _ = self.run_statusline({
            "cwd": str(self.worktree),
            "workspace": self.workspace(self.worktree, git_worktree="wt-name"),
            "worktree": None,
        })
        self.assertIn("📁 origin_repo ", line)
        self.assertIn("🌲 wt-name", line)
        self.assertIn("⎇ wt-branch", line)

    def test_EnterWorktreeのときも元リポジトリ名とworktree名を出す(self):
        line, _ = self.run_statusline({
            "cwd": str(self.worktree),
            "workspace": self.workspace(self.worktree, git_worktree="wt-name"),
            "worktree": {
                "name": "wt-name",
                "path": str(self.worktree),
                "branch": "wt-branch",
                "original_cwd": str(self.repo),
                "original_branch": "main",
            },
        })
        self.assertIn("📁 origin_repo ", line)
        self.assertIn("🌲 wt-name", line)

    def test_worktreeの外では今の表示のままでgitを余計に呼ばない(self):
        line, calls = self.run_statusline({
            "cwd": str(self.repo),
            "workspace": self.workspace(self.repo),
            "worktree": None,
        })
        self.assertIn("📁 origin_repo ", line)
        self.assertNotIn("🌲", line)
        self.assertEqual(
            [call.split()[0] for call in calls], ["branch", "status"],
            f"worktree の外で想定外の git 呼び出し: {calls}",
        )

    def test_gitが失敗したらcurrent_dirのbasenameに戻る(self):
        line, _ = self.run_statusline({
            "cwd": str(self.outside),
            "workspace": self.workspace(self.outside, git_worktree="wt-name"),
            "worktree": None,
        })
        self.assertIn("📁 not_a_repo ", line)

    def test_workspaceもworktreeも無くても落ちない(self):
        line, _ = self.run_statusline({"cwd": str(self.outside)})
        self.assertIn("📁 not_a_repo", line)
        self.assertNotIn("🌲", line)

    def test_200kを超えても警告を出さない(self):
        # 1Mコンテキストのモデルでは200k超えが常態で、料金も変わらないため表示しない
        self.run_statusline({
            "cwd": str(self.outside),
            "context_window": {"used_percentage": 25},
            "exceeds_200k_tokens": True,
        })
        self.assertIn("25%", self.lines[1])
        self.assertNotIn("200k", self.lines[1])


if __name__ == "__main__":
    unittest.main()
