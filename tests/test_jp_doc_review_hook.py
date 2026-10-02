#!/usr/bin/env python3
"""hooks/jp-doc-review.py の振る舞いを、合成した入力で検証する。

合成した入力でのテストは、実機で動く証拠にならない。実機の入力は
docs/research/2026-10-02-claude-code-hook-payloads.md に記録している。

実行: python3 -m unittest tests.test_jp_doc_review_hook
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "jp-doc-review.py"
JP_LONG = "日本語の文書をレビューするためのテスト用の文です。" * 6
JP_HALF = "日本語の文書を少しずつ書き足すためのテスト用の文です。" * 2


def agent_call(subagent_type):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Agent",
         "input": {"subagent_type": subagent_type, "description": "d", "prompt": "p"}}]}}


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.state = self.base / "state"
        self.skill = self.base / "yomiyasu" / "SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text("---\nname: yomiyasu\n---\n", encoding="utf-8")
        self.repo = self.base / "repo"
        (self.repo / ".git").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, event, payload, raw=None):
        env = {**os.environ, "JP_DOC_REVIEW_STATE_DIR": str(self.state),
               "JP_DOC_REVIEW_YOMIYASU_SKILL": str(self.skill)}
        env.pop("FORCE_COLOR", None)
        result = subprocess.run(
            [sys.executable, str(HOOK), event],
            input=raw if raw is not None else json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, env=env,
        )
        output = json.loads(result.stdout) if result.stdout.strip() else {}
        return result.returncode, output, result.stderr

    def write_file(self, relative, text, root=None):
        path = (root or self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def post(self, path, text, tool="Write", session="s1", **extra):
        key = "content" if tool == "Write" else "new_string"
        payload = {"session_id": session, "cwd": str(self.repo), "tool_name": tool,
                   "tool_input": {"file_path": str(path), key: text}, **extra}
        return self.run_hook("post-tool-use", payload)

    def stop(self, active=False, transcript=None, session="s1"):
        payload = {"session_id": session, "stop_hook_active": active}
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        return self.run_hook("stop", payload)

    def records(self, session="s1"):
        path = self.state / f"{session}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class RecordTests(HookCase):
    def test_records_japanese_markdown_without_output(self):
        path = self.write_file("docs/a.md", JP_LONG)
        code, output, _ = self.post(path, JP_LONG)
        self.assertEqual((code, output), (0, {}))
        # JP_LONG の日本語の文字数は144（句点「。」は数えない）
        self.assertEqual(self.records(), [{"path": str(path), "jp_chars": 144}])

    def test_counts_only_japanese_characters(self):
        path = self.write_file("a.md", "x")
        self.post(path, "abc 日本語です。 def")
        self.assertEqual(self.records()[0]["jp_chars"], 5)

    def test_text_without_kana_is_not_recorded(self):
        path = self.write_file("a.md", "x")
        self.post(path, "中文文档没有假名" * 20)
        self.assertEqual(self.records(), [])

    def test_ignores_non_target_suffix_and_lockfiles(self):
        for relative in ("a.py", "package-lock.json", "pnpm-lock.yaml"):
            self.post(self.write_file(relative, "x"), JP_LONG)
        self.assertEqual(self.records(), [])

    def test_ignores_excluded_directories_inside_repository(self):
        for relative in ("node_modules/p/README.md", "vendor/a.md", "dist/a.md", "build/a.md"):
            self.post(self.write_file(relative, "x"), JP_LONG)
        self.assertEqual(self.records(), [])

    def test_excluded_names_above_repository_root_do_not_matter(self):
        repo = self.base / "build" / "project"
        (repo / ".git").mkdir(parents=True)
        path = self.write_file("a.md", "x", root=repo)
        self.post(path, JP_LONG)
        self.assertEqual(len(self.records()), 1)

    def test_ignores_files_inside_submodule(self):
        sub = self.repo / "skills" / "ext"
        sub.mkdir(parents=True)
        (sub / ".git").write_text("gitdir: ../../.git/modules/skills/ext\n", encoding="utf-8")
        self.post(self.write_file("skills/ext/README.md", "x"), JP_LONG)
        self.assertEqual(self.records(), [])

    def test_records_files_inside_worktree(self):
        worktree = self.base / "wt"
        worktree.mkdir()
        (worktree / ".git").write_text(f"gitdir: {self.repo}/.git/worktrees/wt\n", encoding="utf-8")
        self.post(self.write_file("a.md", "x", root=worktree), JP_LONG)
        self.assertEqual(len(self.records()), 1)

    def test_ignores_reviewer_writes(self):
        self.post(self.write_file("a.md", "x"), JP_LONG, agent_type="jp-doc-reviewer")
        self.assertEqual(self.records(), [])

    def test_ignores_drafts_directory(self):
        draft = self.state / "drafts" / "s1-abc.md"
        draft.parent.mkdir(parents=True)
        draft.write_text("x", encoding="utf-8")
        self.post(draft, JP_LONG)
        self.assertEqual(self.records(), [])

    def test_symlinked_path_is_recorded_as_real_path(self):
        real = self.write_file("rules/a.md", "x")
        alias_dir = self.base / "alias"
        alias_dir.symlink_to(self.repo / "rules")
        self.post(alias_dir / "a.md", JP_HALF)
        self.post(real, JP_HALF, tool="Edit")
        self.assertEqual({record["path"] for record in self.records()}, {str(real)})

    def test_relative_path_is_resolved_against_cwd(self):
        path = self.write_file("a.md", "x")
        payload = {"session_id": "s1", "cwd": str(self.repo), "tool_name": "Write",
                   "tool_input": {"file_path": "a.md", "content": JP_LONG}}
        self.run_hook("post-tool-use", payload)
        self.assertEqual(self.records()[0]["path"], str(path))

    def test_unsafe_session_id_stays_inside_state_directory(self):
        self.post(self.write_file("a.md", "x"), JP_LONG, session="../../escape")
        written = list(self.state.rglob("*.jsonl"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].parent, self.state)


class StopTests(HookCase):
    def transcript(self, *entries):
        path = self.base / "transcript.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path

    def test_blocks_and_lists_files_over_threshold(self):
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        code, output, _ = self.stop(transcript=self.transcript({"type": "user", "message": {"content": "x"}}))
        self.assertEqual(code, 0)
        self.assertEqual(output["decision"], "block")
        self.assertIn(str(path), output["reason"])
        self.assertIn("jp-doc-reviewer", output["reason"])

    def test_does_not_block_below_threshold(self):
        self.post(self.write_file("a.md", JP_HALF), JP_HALF)
        self.assertEqual(self.stop()[1], {})

    def test_small_edits_accumulate_across_turns(self):
        path = self.write_file("a.md", JP_HALF)
        self.post(path, JP_HALF)
        self.assertEqual(self.stop()[1], {})
        self.post(path, JP_HALF, tool="Edit")
        self.assertEqual(self.stop()[1]["decision"], "block")

    def test_deleted_file_is_not_reviewed(self):
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        path.unlink()
        self.assertEqual(self.stop()[1], {})

    def test_file_without_kana_now_is_not_reviewed(self):
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        path.write_text("rewritten in english", encoding="utf-8")
        self.assertEqual(self.stop()[1], {})

    def test_missing_yomiyasu_is_reported_once_without_blocking(self):
        self.skill.unlink()
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        first = self.stop()[1]
        self.assertNotIn("decision", first)
        self.assertIn("yomiyasu", first["systemMessage"])
        self.assertEqual(self.stop()[1], {})

    def test_second_stop_clears_and_warns_when_reviewer_was_not_invoked(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.assertEqual(self.stop(transcript=transcript)[1]["decision"], "block")
        code, output, _ = self.stop(active=True, transcript=transcript)
        self.assertEqual(code, 0)
        self.assertNotIn("decision", output)
        self.assertIn("jp-doc-reviewer", output["systemMessage"])
        self.assertEqual(self.records(), [])
        self.assertEqual(self.stop(transcript=transcript)[1], {})

    def test_second_stop_is_quiet_when_reviewer_was_invoked(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.stop(transcript=transcript)
        self.transcript(agent_call("jp-doc-reviewer"))
        self.assertEqual(self.stop(active=True, transcript=transcript)[1], {})

    def test_reviewer_call_before_dispatch_does_not_count(self):
        transcript = self.transcript(agent_call("jp-doc-reviewer"))
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.stop(transcript=transcript)
        self.assertIn("systemMessage", self.stop(active=True, transcript=transcript)[1])

    def test_active_stop_without_our_dispatch_is_silent(self):
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.assertEqual(self.stop(active=True)[1], {})
        self.assertEqual(len(self.records()), 1)

    def test_unreadable_transcript_on_second_stop_is_reported(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.stop(transcript=transcript)
        transcript.unlink()
        output = self.stop(active=True, transcript=transcript)[1]
        self.assertIn("確認できなかった", output["systemMessage"])

    def test_broken_log_lines_are_counted_in_message(self):
        self.state.mkdir(parents=True)
        (self.state / "s1.jsonl").write_text("{broken\n", encoding="utf-8")
        self.assertIn("1件", self.stop()[1]["systemMessage"])

    def test_old_state_files_are_removed(self):
        self.state.mkdir(parents=True)
        old = self.state / "old-session.jsonl"
        old.write_text("", encoding="utf-8")
        eight_days_ago = time.time() - 8 * 86400
        os.utime(old, (eight_days_ago, eight_days_ago))
        self.stop()
        self.assertFalse(old.exists())


class ConfluenceTests(HookCase):
    TOOL = "mcp__atlassian-http__createConfluencePage"

    def pre(self, body, title="", tool=None, **tool_input):
        payload = {"session_id": "s1", "tool_name": tool or self.TOOL,
                   "tool_input": {"cloudId": "c", "spaceId": "1", "title": title, "body": body, **tool_input}}
        return self.run_hook("pre-tool-use", payload)

    def test_short_japanese_passes(self):
        self.assertEqual(self.pre("短い本文です。"), (0, {}, ""))

    def test_first_post_is_denied_with_draft(self):
        code, output, _ = self.pre(f"<p>{JP_LONG}</p>", contentFormat="html")
        decision = output["hookSpecificOutput"]
        self.assertEqual((code, decision["permissionDecision"]), (0, "deny"))
        drafts = list((self.state / "drafts").iterdir())
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].suffix, ".html")
        self.assertEqual(drafts[0].read_text(encoding="utf-8"), f"<p>{JP_LONG}</p>")
        self.assertIn(str(drafts[0]), decision["permissionDecisionReason"])

    def test_draft_suffix_follows_content_format(self):
        self.pre(JP_LONG, contentFormat="markdown", pageId="1")
        self.pre(JP_LONG + "。", contentFormat="adf", pageId="2")
        self.pre(JP_LONG + "、", pageId="3")
        suffixes = sorted(path.suffix for path in (self.state / "drafts").iterdir())
        self.assertEqual(suffixes, [".html", ".json", ".md"])

    def test_title_counts_toward_threshold(self):
        self.assertEqual(self.pre("本文。", title=JP_LONG)[1]["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_second_post_passes_and_warns_when_unchanged(self):
        self.pre(JP_LONG, pageId="9")
        code, output, _ = self.pre(JP_LONG, pageId="9")
        self.assertEqual(code, 0)
        self.assertNotIn("hookSpecificOutput", output)
        self.assertIn("レビューを通らない", output["systemMessage"])

    def test_second_post_with_reviewed_body_is_silent(self):
        self.pre(JP_LONG, pageId="9")
        self.assertEqual(self.pre(JP_LONG.replace("テスト用", "確認用"), pageId="9")[1], {})

    def test_targets_are_tracked_separately(self):
        self.pre(JP_LONG, pageId="1")
        denied = self.pre(JP_LONG, pageId="2")[1]
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_after_passing_the_same_target_is_checked_again(self):
        self.pre(JP_LONG, pageId="1")
        self.pre(JP_LONG + "。", pageId="1")
        self.assertEqual(self.pre(JP_LONG + "、", pageId="1")[1]["hookSpecificOutput"]["permissionDecision"], "deny")


class ErrorTests(HookCase):
    def test_invalid_json_fails_loudly_without_blocking(self):
        code, output, stderr = self.run_hook("post-tool-use", None, raw="{broken")
        self.assertEqual((code, output), (1, {}))
        self.assertIn("jp-doc-review post-tool-use", stderr)

    def test_missing_session_id_fails_loudly(self):
        path = self.write_file("a.md", "x")
        code, _, stderr = self.run_hook("post-tool-use", {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": JP_LONG}})
        self.assertEqual(code, 1)
        self.assertIn("session_id", stderr)

    def test_unknown_event_fails(self):
        code, _, stderr = self.run_hook("unknown", {})
        self.assertEqual(code, 1)
        self.assertIn("使い方", stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
