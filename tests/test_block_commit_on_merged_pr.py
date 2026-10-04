#!/usr/bin/env python3
"""hooks/block-commit-on-merged-pr.py の振る舞いを、スタブの gh と実際の git リポジトリで検証する。

実行: python3 -m unittest tests.test_block_commit_on_merged_pr
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "block-commit-on-merged-pr.py"
GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class MergedPrHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid",
                 "commit", "-q", "--allow-empty", "-m", "init")
        self.git("switch", "-q", "-c", "feature")
        # スタブの gh。GH_STUB_OUTPUT を返し、GH_STUB_EXIT で終了する。呼ばれた引数を記録する
        self.bindir = self.base / "bin"
        self.bindir.mkdir()
        self.calls = self.base / "gh-calls.log"
        stub = self.bindir / "gh"
        stub.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$GH_STUB_LOG"\n'
            'printf "%s" "${GH_STUB_OUTPUT:-[]}"\nexit "${GH_STUB_EXIT:-0}"\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True,
                       env={**os.environ, **GIT_ISOLATION})

    def run_hook(self, command, prs=None, gh_exit=0, cwd=None, with_gh=True):
        env = {**os.environ, **GIT_ISOLATION, "GH_STUB_LOG": str(self.calls), "GH_STUB_EXIT": str(gh_exit)}
        env["PATH"] = f"{self.bindir}{os.pathsep}{env['PATH']}" if with_gh else "/usr/bin:/bin"
        if prs is not None:
            env["GH_STUB_OUTPUT"] = json.dumps(prs)
        payload = {"session_id": "s1", "cwd": str(cwd or self.repo), "tool_name": "Bash",
                   "tool_input": {"command": command, "description": "d"}}
        result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                                capture_output=True, text=True, env=env)
        output = json.loads(result.stdout) if result.stdout.strip() else {}
        return result.returncode, output

    def decision(self, output):
        return output.get("hookSpecificOutput", {}).get("permissionDecision")

    def gh_called(self):
        return self.calls.exists() and self.calls.read_text(encoding="utf-8").strip() != ""

    def test_commit_on_branch_with_only_merged_pr_is_blocked(self):
        code, output = self.run_hook("git commit -m x", prs=[
            {"number": 12, "state": "MERGED", "url": "https://example.invalid/pull/12"}])
        self.assertEqual(code, 0)
        self.assertEqual(self.decision(output), "deny")
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("#12", reason)
        self.assertIn("feature", reason)

    def test_commit_with_open_pr_passes(self):
        code, output = self.run_hook("git commit -m x", prs=[
            {"number": 12, "state": "MERGED", "url": "u"}, {"number": 13, "state": "OPEN", "url": "u"}])
        self.assertEqual((code, output), (0, {}))

    def test_commit_without_pr_passes(self):
        self.assertEqual(self.run_hook("git commit -m x", prs=[]), (0, {}))

    def test_closed_unmerged_pr_warns_without_blocking(self):
        code, output = self.run_hook("git commit -m x", prs=[{"number": 7, "state": "CLOSED", "url": "u"}])
        self.assertEqual(code, 0)
        self.assertIsNone(self.decision(output))
        self.assertIn("#7", output.get("systemMessage", ""))

    def test_lookup_failure_warns_without_blocking(self):
        code, output = self.run_hook("git commit -m x", prs=[], gh_exit=1)
        self.assertEqual(code, 0)
        self.assertIsNone(self.decision(output))
        self.assertIn("確かめられなかった", output.get("systemMessage", ""))

    def test_missing_gh_warns_without_blocking(self):
        code, output = self.run_hook("git commit -m x", with_gh=False)
        self.assertEqual(code, 0)
        self.assertIsNone(self.decision(output))
        self.assertIn("確かめられなかった", output.get("systemMessage", ""))

    def test_other_commands_do_not_query(self):
        for command in ("git status", 'echo "git commit"', "git log --grep commit"):
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(command, prs=[{"number": 1, "state": "MERGED", "url": "u"}]), (0, {}))
        self.assertFalse(self.gh_called())

    def test_commit_after_separator_or_prefix_is_checked(self):
        merged = [{"number": 3, "state": "MERGED", "url": "u"}]
        for command in ("git add . && git commit -m x", "GIT_EDITOR=true git commit", "git -c a=b commit -m x"):
            with self.subTest(command=command):
                self.assertEqual(self.decision(self.run_hook(command, prs=merged)[1]), "deny")

    def test_default_branch_and_detached_head_are_not_queried(self):
        self.git("switch", "-q", "main")
        self.assertEqual(self.run_hook("git commit -m x", prs=[{"number": 1, "state": "MERGED", "url": "u"}]), (0, {}))
        self.git("switch", "-q", "--detach")
        self.assertEqual(self.run_hook("git commit -m x", prs=[{"number": 1, "state": "MERGED", "url": "u"}]), (0, {}))
        self.assertFalse(self.gh_called())

    def test_outside_git_repository_passes(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.assertEqual(self.run_hook("git commit -m x", cwd=outside), (0, {}))

    def test_queries_the_current_branch(self):
        self.run_hook("git commit -m x", prs=[])
        self.assertIn("--head feature", self.calls.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
