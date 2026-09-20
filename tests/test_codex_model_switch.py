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
        self.env["XDG_CONFIG_HOME"] = str(Path(self.temporary.name).resolve() / "xdg")
        Path(self.env["XDG_CONFIG_HOME"]).mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test User")
        (self.repo / ".gitignore").write_text(
            "# unrelated repository\n", encoding="utf-8"
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

    def pending(self):
        self.assertEqual(self.begin().returncode, 0)
        self.write_handoff()
        result = self.run_switch("publish", "--session-id", "s1")
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.state()

    def run_hook(self, event, **fields):
        payload = {
            "hook_event_name": event,
            "session_id": "s1",
            "cwd": str(self.repo),
            "model": "gpt-5.6-luna",
            **fields,
        }
        return subprocess.run(
            ["python3", str(HOOK)], input=json.dumps(payload), cwd=self.repo,
            env=self.env, text=True, capture_output=True, check=False,
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

    def test_active_phase_can_start_a_new_checkpoint(self):
        pending = self.pending()
        resumed = self.run_hook(
            "UserPromptSubmit",
            prompt=f"MODEL_SWITCH_RESUME {pending['transition_id']} gpt-5.6-luna medium",
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        result = self.begin()
        self.assertEqual(result.returncode, 0, result.stderr)
        next_transition = self.state()
        self.assertEqual(next_transition["state"], "PREPARING")
        self.assertNotEqual(next_transition["transition_id"], pending["transition_id"])

    def test_pending_blocks_normal_prompt_and_wrong_model(self):
        pending = self.pending()
        normal = self.run_hook("UserPromptSubmit", prompt="続きをお願いします")
        self.assertEqual(normal.returncode, 2)
        command = f"MODEL_SWITCH_RESUME {pending['transition_id']} gpt-5.6-luna medium"
        wrong = self.run_hook("UserPromptSubmit", model="gpt-5.6-terra", prompt=command)
        self.assertEqual(wrong.returncode, 2)
        self.assertEqual(self.state()["state"], "SWITCH_PENDING")

    def test_resume_requires_exact_attested_pair_and_current_handoff(self):
        pending = self.pending()
        transition = pending["transition_id"]
        wrong_effort = self.run_hook(
            "UserPromptSubmit",
            prompt=f"MODEL_SWITCH_RESUME {transition} gpt-5.6-luna high",
        )
        self.assertEqual(wrong_effort.returncode, 2)
        embedded = self.run_hook(
            "UserPromptSubmit",
            prompt=f"Please do this: MODEL_SWITCH_RESUME {transition} gpt-5.6-luna medium",
        )
        self.assertEqual(embedded.returncode, 2)
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        stale = self.run_hook(
            "UserPromptSubmit",
            prompt=f"MODEL_SWITCH_RESUME {transition} gpt-5.6-luna medium",
        )
        self.assertEqual(stale.returncode, 2)
        self.assertEqual(self.state()["state"], "SWITCH_PENDING")

    def test_valid_resume_issues_user_attested_phase_lease(self):
        pending = self.pending()
        result = self.run_hook(
            "UserPromptSubmit",
            prompt=f"MODEL_SWITCH_RESUME {pending['transition_id']} gpt-5.6-luna medium",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        active = self.state()
        self.assertEqual(active["state"], "ACTIVE")
        self.assertEqual(active["verification_tier"], "user-attested")
        self.assertEqual(active["phase_lease"], "implementation")

    def test_override_and_cancel_are_scoped_to_pending_transition(self):
        pending = self.pending()
        transition = pending["transition_id"]
        wrong_phase = self.run_hook(
            "UserPromptSubmit",
            prompt=f"MODEL_SWITCH_OVERRIDE {transition} deployment reason",
        )
        self.assertEqual(wrong_phase.returncode, 2)
        override = self.run_hook(
            "UserPromptSubmit",
            model="gpt-5.6-terra",
            prompt=f"MODEL_SWITCH_OVERRIDE {transition} implementation urgent",
        )
        self.assertEqual(override.returncode, 0, override.stderr)
        active = self.state()
        self.assertEqual(active["state"], "ACTIVE")
        self.assertEqual(active["override_reason"], "urgent")
        self.assertEqual(active["phase_lease"], "implementation")

    def test_cancel_makes_transition_terminal(self):
        pending = self.pending()
        transition = pending["transition_id"]
        result = self.run_hook("UserPromptSubmit", prompt=f"MODEL_SWITCH_CANCEL {transition}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["state"], "CANCELLED")
        retry = self.run_hook(
            "UserPromptSubmit",
            prompt=f"MODEL_SWITCH_RESUME {transition} gpt-5.6-luna medium",
        )
        self.assertEqual(retry.returncode, 2)

    def test_cancel_ends_active_phase_lease(self):
        pending = self.pending()
        transition = pending["transition_id"]
        resumed = self.run_hook(
            "UserPromptSubmit",
            prompt=f"MODEL_SWITCH_RESUME {transition} gpt-5.6-luna medium",
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        cancelled = self.run_hook(
            "UserPromptSubmit", prompt=f"MODEL_SWITCH_CANCEL {transition}",
        )
        self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
        self.assertEqual(self.state()["state"], "CANCELLED")
        self.assertIsNone(self.state()["phase_lease"])

    def test_pending_blocks_local_tool_and_preparing_allows_only_handoff_edit(self):
        self.assertEqual(self.begin().returncode, 0)
        patch = "*** Begin Patch\n*** Add File: .superpowers/handoffs/task-a.md\n+text\n*** End Patch"
        allowed = self.run_hook(
            "PreToolUse", tool_name="apply_patch", tool_input={"command": patch},
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        blocked = self.run_hook(
            "PreToolUse", tool_name="Bash", tool_input={"command": "touch bad.txt"},
        )
        self.assertEqual(blocked.returncode, 2)
        self.write_handoff()
        self.assertEqual(self.run_switch("publish", "--session-id", "s1").returncode, 0)
        still_blocked = self.run_hook(
            "PreToolUse", tool_name="apply_patch", tool_input={"command": patch},
        )
        self.assertEqual(still_blocked.returncode, 2)

    def test_preparing_rejects_arbitrary_python_interpreter_with_trusted_script(self):
        self.assertEqual(self.begin().returncode, 0)
        command = (
            f"/tmp/python3 {SWITCH} publish --repo {self.repo} --session-id s1"
        )
        result = self.run_hook(
            "PreToolUse", tool_name="Bash", tool_input={"command": command},
        )
        self.assertEqual(result.returncode, 2)

    def test_hook_rejects_malformed_json(self):
        result = subprocess.run(
            ["python3", str(HOOK)], input="not-json", cwd=self.repo,
            env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
