#!/usr/bin/env python3
"""hooks/principle-review.py の振る舞いを、合成した入力と一時リポジトリで検証する。

実行: python3 -m unittest tests.test_principle_review_hook
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    from tests.git_fixture import git
except ImportError:
    from git_fixture import git

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "principle-review.py"
_spec = importlib.util.spec_from_file_location("principle_review", HOOK)
principle_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(principle_review)


class ClassifyTests(unittest.TestCase):
    def test_spec_and_plan_locations(self):
        self.assertEqual(principle_review.classify("docs/superpowers/specs/a.md"), "spec")
        self.assertEqual(principle_review.classify("docs/specs/a.md"), "spec")
        self.assertEqual(principle_review.classify("docs/adr/0001-x.md"), "spec")
        self.assertEqual(principle_review.classify("docs/superpowers/plans/a.md"), "plan")
        self.assertEqual(principle_review.classify("docs/plans/a.md"), "plan")

    def test_other_files_are_not_targets(self):
        for path in ("docs/adr/README.md", "docs/specs/a.txt", "src/docs/specs/a.md", "README.md"):
            with self.subTest(path):
                self.assertIsNone(principle_review.classify(path))

    def test_uses_all_flag(self):
        f = principle_review.uses_all_flag
        self.assertTrue(f(["git", "commit", "-a", "-m", "x"]))
        self.assertTrue(f(["git", "commit", "-am", "x"]))
        self.assertTrue(f(["git", "commit", "--all"]))
        self.assertFalse(f(["git", "commit", "-m", "-a"]))
        self.assertFalse(f(["git", "commit", "-m", "add all"]))


def decision_of(output):
    return output.get("hookSpecificOutput", {}).get("permissionDecision")


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "work")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@example.invalid")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "init")
        self.data = self.base / "principles.json"
        self.data.write_text('{"principles": []}', encoding="utf-8")
        self.transcript_path = self.base / "transcript.jsonl"
        self.transcript_path.write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, command, session="s1", cwd=None, raw=None):
        payload = {"session_id": session, "cwd": str(cwd or self.repo), "transcript_path": str(self.transcript_path),
                   "tool_name": "Bash", "tool_input": {"command": command}}
        env = {**os.environ, "PRINCIPLE_REVIEW_STATE_DIR": str(self.base / "state"),
               "PRINCIPLE_REVIEW_DATA": str(self.data)}
        result = subprocess.run([sys.executable, str(HOOK)], input=raw if raw is not None else json.dumps(payload),
                                capture_output=True, text=True, env=env)
        output = json.loads(result.stdout) if result.stdout.strip() else {}
        return result.returncode, output

    def stage(self, relative, text="本文", repo=None):
        path = (repo or self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(repo or self.repo, "add", relative)
        return path


class BlockOnceTests(HookCase):
    def test_non_commit_passes_silently(self):
        self.stage("docs/specs/a.md")
        self.assertEqual(self.run_hook("git status"), (0, {}))

    def test_commit_without_targets_passes_silently(self):
        self.stage("src/a.py")
        self.assertEqual(self.run_hook("git commit -m x"), (0, {}))

    def test_spec_commit_is_denied_once_with_reviewer_instruction(self):
        path = self.stage("docs/superpowers/specs/a.md")
        code, output = self.run_hook("git commit -m x")
        self.assertEqual((code, decision_of(output)), (0, "deny"))
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("principle-reviewer", reason)
        self.assertIn(f"spec: {path}", reason)
        self.assertIn("要約せず", reason)
        self.assertIsNone(decision_of(self.run_hook("git commit -m x")[1]))

    def test_edited_after_review_is_not_denied_again(self):
        self.stage("docs/specs/a.md", "一版")
        self.run_hook("git commit -m x")
        self.stage("docs/specs/a.md", "二版")
        self.assertIsNone(decision_of(self.run_hook("git commit -m x")[1]))

    def test_new_plan_in_same_session_is_denied(self):
        self.stage("docs/specs/a.md")
        self.run_hook("git commit -m x")
        git(self.repo, "commit", "-q", "-m", "spec")
        self.stage("docs/superpowers/plans/a.md")
        self.assertEqual(decision_of(self.run_hook("git commit -m x")[1]), "deny")

    def test_other_session_is_denied_again(self):
        self.stage("docs/specs/a.md")
        self.run_hook("git commit -m x", session="s1")
        self.assertEqual(decision_of(self.run_hook("git commit -m x", session="s2")[1]), "deny")

    def test_deleted_target_only_passes(self):
        self.stage("docs/adr/0001-x.md")
        git(self.repo, "commit", "-q", "-m", "adr")
        git(self.repo, "rm", "-q", "docs/adr/0001-x.md")
        self.assertEqual(self.run_hook("git commit -m x"), (0, {}))

    def test_japanese_and_space_in_filename(self):
        path = self.stage("docs/specs/仕事の 原則.md")
        output = self.run_hook("git commit -m x")[1]
        self.assertEqual(decision_of(output), "deny")
        self.assertIn(f"spec: {path}", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_unstaged_change_counts_only_with_all_flag(self):
        self.stage("docs/specs/a.md")
        git(self.repo, "commit", "-q", "-m", "spec")
        (self.repo / "docs/specs/a.md").write_text("変更", encoding="utf-8")
        self.assertEqual(self.run_hook("git commit -m x"), (0, {}))
        self.assertEqual(decision_of(self.run_hook("git commit -am x")[1]), "deny")


class TargetRepositoryTests(HookCase):
    def setUp(self):
        super().setUp()
        self.other = self.base / "other"
        self.other.mkdir()
        git(self.other, "init", "-q", "-b", "work")
        git(self.other, "config", "user.name", "t")
        git(self.other, "config", "user.email", "t@example.invalid")
        git(self.other, "commit", "-q", "--allow-empty", "-m", "init")

    def test_git_dash_c_targets_the_other_repository(self):
        path = self.stage("docs/specs/a.md", repo=self.other)
        code, output = self.run_hook(f"git -C {self.other} commit -m x")
        self.assertEqual(decision_of(output), "deny")
        self.assertIn(str(path), output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_cd_and_commit_targets_the_other_repository(self):
        self.stage("docs/specs/a.md", repo=self.other)
        self.assertEqual(decision_of(self.run_hook(f"cd {self.other} && git commit -m x")[1]), "deny")

    def test_outside_any_repository_passes(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.assertEqual(self.run_hook("git commit -m x", cwd=outside), (0, {}))


class StateResilienceTests(HookCase):
    def write_session_state(self, text, session="s1"):
        state = self.base / "state"
        state.mkdir(exist_ok=True)
        (state / f"{session}.json").write_text(text, encoding="utf-8")

    def test_corrupt_json_state_is_denied_first(self):
        self.stage("docs/specs/a.md")
        self.write_session_state("{broken")
        self.assertEqual(decision_of(self.run_hook("git commit -m x")[1]), "deny")

    def test_non_dict_state_is_denied_first(self):
        self.stage("docs/specs/a.md")
        self.write_session_state("[]")
        self.assertEqual(decision_of(self.run_hook("git commit -m x")[1]), "deny")

    def test_unexpected_exception_exits_zero_with_message(self):
        payload = json.dumps({"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "git commit -m x"}})
        code, output = self.run_hook("", raw=payload)
        self.assertEqual(code, 0)
        self.assertIn("検査できなかった", json.dumps(output, ensure_ascii=False))

    def test_cleanup_keeps_the_lock_in_use(self):
        self.stage("docs/specs/a.md")
        self.run_hook("git commit -m x")
        old = time.time() - 8 * 86400
        for name in ("s1.lock", "s1.json"):
            os.utime(self.base / "state" / name, (old, old))
        self.run_hook("git commit -m x")
        self.assertTrue((self.base / "state" / "s1.lock").exists())


def agent_call(subagent_type):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Agent", "input": {"subagent_type": subagent_type, "prompt": "p"}}]}}


class FailureAndFollowUpTests(HookCase):
    def append_transcript(self, *entries):
        with self.transcript_path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def test_missing_principles_data_denies_once_then_passes_with_message(self):
        self.data.unlink()
        self.stage("docs/specs/a.md")
        first = self.run_hook("git commit -m x")[1]
        self.assertEqual(decision_of(first), "deny")
        self.assertIn("原則集を読めない", first["hookSpecificOutput"]["permissionDecisionReason"])
        second = self.run_hook("git commit -m x")[1]
        self.assertIsNone(decision_of(second))
        self.assertIn("原則集を読めない", second["systemMessage"])

    def test_missing_session_id_passes_with_message(self):
        self.stage("docs/specs/a.md")
        payload = {"cwd": str(self.repo), "tool_input": {"command": "git commit -m x"}}
        code, output = self.run_hook("", raw=json.dumps(payload))
        self.assertIsNone(decision_of(output))
        self.assertIn("検査できなかった", output["systemMessage"])

    def test_unreadable_input_passes_with_message(self):
        code, output = self.run_hook("", raw="{not json")
        self.assertEqual(code, 0)
        self.assertIn("検査できなかった", output["systemMessage"])

    def test_second_commit_warns_when_reviewer_was_not_started(self):
        self.stage("docs/specs/a.md")
        self.run_hook("git commit -m x")
        self.append_transcript(agent_call("jp-doc-reviewer"))
        output = self.run_hook("git commit -m x")[1]
        self.assertIsNone(decision_of(output))
        self.assertIn("principle-reviewer が起動していない", output["systemMessage"])

    def test_second_commit_is_quiet_when_reviewer_was_started(self):
        self.stage("docs/specs/a.md")
        self.run_hook("git commit -m x")
        self.append_transcript(agent_call("principle-reviewer"))
        self.assertEqual(self.run_hook("git commit -m x"), (0, {}))

    def test_warning_is_shown_only_once_per_file(self):
        self.stage("docs/specs/a.md")
        self.run_hook("git commit -m x")
        self.run_hook("git commit -m x")
        self.assertEqual(self.run_hook("git commit -m x"), (0, {}))
