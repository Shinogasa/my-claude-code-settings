#!/usr/bin/env python3
"""hooks/detect-parallel-sessions.sh の振る舞いを検証する。

フックの契約 (stdin に JSON、stdout に SessionStart の JSON) をそのまま叩く。
検出コマンドと対象外リポジトリのパスは環境変数で差し替え、
実際のプロセス状態や ~/.claude の構成に依存させない。

実行: python3 tests/test_detect_parallel_sessions_hook.py
"""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "detect-parallel-sessions.sh"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def make_repo(base, name):
    repo = Path(base) / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("init\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def make_fake_detect(base, name, payload):
    """固定の JSON を返す検出コマンドを作って返す。"""
    path = Path(base) / name
    path.write_text(f"#!/bin/bash\ncat <<'EOF'\n{payload}\nEOF\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def run_hook(cwd, detect_cmd, exclude_path):
    payload = {"hook_event_name": "SessionStart", "source": "startup"}
    env = dict(os.environ)
    env["PARALLEL_SESSIONS_DETECT_CMD"] = str(detect_cmd)
    env["PARALLEL_SESSIONS_EXCLUDE_PATH"] = str(exclude_path)
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, cwd=str(cwd), env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestHook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = make_repo(cls._tmp.name, "repo")
        cls.settings_repo = make_repo(cls._tmp.name, "settings")
        cls.found = make_fake_detect(
            cls._tmp.name, "detect-found",
            '[{"pid":111,"cwd":"%s"}]' % cls.repo,
        )
        cls.none = make_fake_detect(cls._tmp.name, "detect-none", "[]")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_emits_context_when_collision_found(self):
        out = run_hook(self.repo, self.found, self.settings_repo)
        parsed = json.loads(out)
        self.assertEqual(
            parsed["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("additionalContext", parsed["hookSpecificOutput"])

    def test_context_tells_how_to_separate(self):
        out = run_hook(self.repo, self.found, self.settings_repo)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("worktree", ctx)
        self.assertIn("111", ctx)

    def test_silent_when_no_collision(self):
        self.assertEqual(run_hook(self.repo, self.none, self.settings_repo), "")

    def test_silent_in_excluded_repository(self):
        # 対象外リポジトリ (~/.claude/rules の実体) では検出ありでも黙る
        self.assertEqual(run_hook(self.settings_repo, self.found, self.settings_repo), "")

    def test_silent_outside_git_repo(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(run_hook(plain, self.found, self.settings_repo), "")

    def test_silent_when_detect_command_missing(self):
        missing = Path(self._tmp.name) / "no-such-command"
        self.assertEqual(run_hook(self.repo, missing, self.settings_repo), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
