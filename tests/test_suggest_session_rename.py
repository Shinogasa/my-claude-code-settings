#!/usr/bin/env python3
"""hooks/suggest-session-rename.py を検証する。

実行: python3 -m unittest tests.test_suggest_session_rename
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "suggest-session-rename.py"


def run_hook(raw_input):
    result = subprocess.run([sys.executable, str(HOOK)], input=raw_input,
                            text=True, capture_output=True, check=False)
    return result


def bash(command, **extra):
    return json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                       "tool_input": {"command": command}, **extra})


class SuggestSessionRenameTests(unittest.TestCase):
    def assert_nudged(self, raw_input):
        result = run_hook(raw_input)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PostToolUse")
        self.assertIn("/rename", specific["additionalContext"])

    def assert_silent(self, raw_input):
        result = run_hook(raw_input)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_nudges_after_branch_creating_commands(self):
        for command in [
            "git switch -c feat/x",
            "git switch -C feat/x",
            "git switch --create feat/x",
            "git checkout -b feat/x",
            "git checkout -B feat/x origin/main",
            "git worktree add .claude/worktrees/x -b feat/x",
            "git -C /repo switch -c feat/x",
            "git pull --ff-only && git switch -c feat/x",
        ]:
            with self.subTest(command=command):
                self.assert_nudged(bash(command))

    def test_nudges_after_enter_worktree(self):
        self.assert_nudged(json.dumps({"hook_event_name": "PostToolUse", "tool_name": "EnterWorktree",
                                       "tool_input": {"name": "x"}}))

    def test_silent_for_commands_that_do_not_create_a_branch(self):
        for command in [
            "git switch main",
            "git checkout main",
            "git branch -c old new",
            "git worktree list",
            "echo 'git switch -c は使わない'",
        ]:
            with self.subTest(command=command):
                self.assert_silent(bash(command))

    def test_silent_inside_subagent(self):
        self.assert_silent(bash("git switch -c feat/x", agent_id="abc", agent_type="general-purpose"))

    def test_silent_on_broken_input(self):
        for raw in ["", "not json", "[]", json.dumps({"tool_name": "Bash", "tool_input": "x"})]:
            with self.subTest(raw=raw):
                self.assert_silent(raw)


if __name__ == "__main__":
    unittest.main()
