#!/usr/bin/env python3
"""hooks/rtk-rewrite.py の振る舞いを検証する。

Claude Codeのworktree分離チェックは、rtkが書き換えた `rtk git ...` を拒否する
（anthropics/claude-code#99895）。このフックは、linked worktreeでgitを含むコマンドだけ
rtkの書き換えを省き、それ以外は `rtk hook claude` の結果をそのまま返す。

実行: python3 -m unittest tests.test_rtk_rewrite_hook
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

if __package__:
    from tests.git_fixture import git
else:
    from git_fixture import git

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "rtk-rewrite.py"
REWRITTEN = '{"hookSpecificOutput":{"updatedInput":{"command":"rtk x"}}}'

# 偽のrtk。呼ばれた引数と受け取った入力を記録し、決まった出力と終了コードを返す
FAKE_RTK = f"""#!/bin/sh
echo "$@" > "$RTK_LOG"
cat >> "$RTK_LOG"
printf '%s' '{REWRITTEN}'
exit "${{RTK_EXIT:-0}}"
"""


def make_repos(base):
    """通常のリポジトリ、そのlinked worktree、submoduleを持つリポジトリを作る。"""
    main = base / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    git(main, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "init")
    worktree = base / "wt"
    git(main, "worktree", "add", "-q", str(worktree), "-b", "feat")
    (worktree / "sub").mkdir()

    # submoduleの作業ツリーも .git がファイルになる。gitdirは .git/modules/ を指す
    parent = base / "parent"
    (parent / "lib").mkdir(parents=True)
    modules = parent / ".git" / "modules" / "lib"
    modules.mkdir(parents=True)
    (parent / "lib" / ".git").write_text(f"gitdir: {modules}\n", encoding="utf-8")
    return main, worktree, parent / "lib"


class RtkRewriteHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.main, self.worktree, self.submodule = make_repos(self.base)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        rtk = self.bin / "rtk"
        rtk.write_text(FAKE_RTK, encoding="utf-8")
        rtk.chmod(0o755)
        self.log = self.base / "rtk.log"

    def run_hook(self, command, cwd, path=None, rtk_exit=0, use_payload_cwd=True):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        if use_payload_cwd:
            payload["cwd"] = str(cwd)
        environment = {**os.environ, "PATH": path or f"{self.bin}:/usr/bin:/bin",
                       "RTK_LOG": str(self.log), "RTK_EXIT": str(rtk_exit)}
        return subprocess.run(["python3", str(HOOK)], input=json.dumps(payload), capture_output=True,
                              text=True, cwd=str(cwd), env=environment)

    def assert_skipped(self, result):
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        self.assertFalse(self.log.exists(), "rtkを呼んではいけない")

    def assert_delegated(self, result, payload_command):
        self.assertEqual((result.returncode, result.stdout), (0, REWRITTEN), result.stderr)
        log = self.log.read_text(encoding="utf-8")
        self.assertTrue(log.startswith("hook claude\n"), log)
        self.assertEqual(json.loads(log.split("\n", 1)[1])["tool_input"]["command"], payload_command)

    def test_git_in_linked_worktree_is_left_unrewritten(self):
        for command in ("git status", "cd x && git -C . log", "grep -n git README.md"):
            with self.subTest(command=command):
                self.assert_skipped(self.run_hook(command, self.worktree))

    def test_subdirectory_of_linked_worktree_is_detected(self):
        self.assert_skipped(self.run_hook("git status", self.worktree / "sub"))

    def test_process_cwd_is_used_when_payload_has_no_cwd(self):
        self.assert_skipped(self.run_hook("git status", self.worktree, use_payload_cwd=False))

    def test_non_git_command_in_linked_worktree_is_delegated(self):
        for command in ("ls -la", "gh pr list", "cat .gitignore", "legit run"):
            with self.subTest(command=command):
                self.log.unlink(missing_ok=True)
                self.assert_delegated(self.run_hook(command, self.worktree), command)

    def test_git_in_main_checkout_is_delegated(self):
        self.assert_delegated(self.run_hook("git status", self.main), "git status")

    def test_git_in_submodule_is_delegated(self):
        self.assert_delegated(self.run_hook("git status", self.submodule), "git status")

    def test_git_outside_any_repository_is_delegated(self):
        outside = self.base / "plain"
        outside.mkdir()
        self.assert_delegated(self.run_hook("git status", outside), "git status")

    def test_rtk_exit_code_is_passed_through(self):
        result = self.run_hook("ls", self.main, rtk_exit=3)
        self.assertEqual(result.returncode, 3)

    def test_missing_rtk_does_not_block(self):
        empty = self.base / "empty-bin"
        empty.mkdir()
        result = self.run_hook("ls", self.main, path=f"{empty}:/usr/bin:/bin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("hookSpecificOutput", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
