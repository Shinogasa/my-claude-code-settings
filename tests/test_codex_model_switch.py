#!/usr/bin/env python3
"""親セッションの切替状態を実Git repoと実validatorで検証する。"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SWITCH = ROOT / "bin" / "codex-model-switch.py"
VALIDATOR = ROOT / "bin" / "validate-codex-handoff.py"
HOOK = ROOT / "hooks" / "codex-model-switch-hook.py"


class ModelSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve() / "repo"
        self.repo.mkdir()
        self.env = os.environ.copy()
        self.env["GIT_CONFIG_GLOBAL"] = os.devnull
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test User")
        (self.repo / ".gitignore").write_text(
            ".superpowers/model-switch/\n", encoding="utf-8"
        )
        (self.repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self.git("add", ".gitignore", "tracked.txt")
        self.git("commit", "-m", "initial")
        self.handoff = self.repo / ".superpowers" / "handoffs" / "task-a.md"
        self.handoff.parent.mkdir(parents=True)

    def git(self, *arguments):
        return subprocess.run(
            ["git", *arguments], cwd=self.repo, env=self.env,
            text=True, capture_output=True, check=True,
        )

    def run_switch(self, command, *arguments):
        return subprocess.run(
            ["python3", str(SWITCH), command, "--repo", str(self.repo), *arguments],
            cwd=self.repo, env=self.env, text=True, capture_output=True,
            check=False,
        )

    def state(self, session="s1"):
        result = self.run_switch("status", "--session-id", session)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def begin(self, session="s1"):
        return self.run_switch(
            "begin", "--session-id", session, "--task-id", "task-a",
            "--current-phase", "design", "--next-phase", "implementation",
            "--model", "gpt-5.6-luna", "--effort", "medium",
            "--handoff", ".superpowers/handoffs/task-a.md",
        )

    def write_handoff(self, *, task="task-a", model="gpt-5.6-luna", effort="medium"):
        result = subprocess.run(
            ["python3", str(VALIDATOR), "state", "--repo", str(self.repo)],
            cwd=self.repo, env=self.env, text=True, capture_output=True, check=True,
        )
        state = json.loads(result.stdout)
        self.handoff.write_text(
            f"""---
handoff_schema: 1
task_id: {task}
branch: {state['branch']}
head: {state['head']}
worktree_fingerprint: {state['worktree_fingerprint']}
target_model: {model}
target_reasoning_effort: {effort}
requirements_path: none
requirements_sha256: none
review_package_path: none
review_package_sha256: none
---
# Test handoff

## 目的と対象外
切替を検証する。

## Git状態
一時repoの状態。

## 確定済み設計判断と根拠
schema 1を維持する。

## 対象ファイルと作業所有範囲
tracked.txt。

## 受入条件と検証コマンド
unittestを実行する。

## 制約
providerを変えない。

## 未解決事項
なし。

## 実行モデル
指定ペアを使う。

## 返却レポート契約
結果を返す。
""", encoding="utf-8",
        )

    def test_begin_and_publish_valid_handoff(self):
        result = self.begin()
        self.assertEqual(result.returncode, 0, result.stderr)
        preparing = self.state()
        self.assertEqual(preparing["state"], "PREPARING")
        self.assertEqual(preparing["target_model"], "gpt-5.6-luna")
        self.assertTrue(preparing["transition_id"])
        self.assertIsNone(self.state("s2"))

        self.write_handoff()
        result = self.run_switch("publish", "--session-id", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        pending = self.state()
        self.assertEqual(pending["state"], "SWITCH_PENDING")
        self.assertEqual(len(pending["input_digest"]), 64)
        self.assertEqual(pending["transition_id"], preparing["transition_id"])

    def test_publish_rejects_wrong_task_or_pair(self):
        self.assertEqual(self.begin().returncode, 0)
        self.write_handoff(task="other-task")
        result = self.run_switch("publish", "--session-id", "s1")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.state()["state"], "PREPARING")

    def test_second_begin_cannot_replace_pending_transition(self):
        self.assertEqual(self.begin().returncode, 0)
        result = self.begin()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.state()["state"], "PREPARING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
