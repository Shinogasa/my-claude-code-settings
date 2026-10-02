#!/usr/bin/env python3
"""hooks/jp-doc-review.py の振る舞いを、合成した入力で検証する。

合成した入力でのテストは、実機で動く証拠にならない。実機の入力は
docs/research/2026-10-02-claude-code-hook-payloads.md に記録している。

実行: python3 -m unittest tests.test_jp_doc_review_hook
"""
import json
import os
import shutil
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


def agent_call(subagent_type, name="Agent"):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": name,
         "input": {"subagent_type": subagent_type, "description": "d", "prompt": "p"}}]}}


def decision_of(result):
    """run_hook の結果から permissionDecision を取り出す。無ければ None。"""
    return result[1].get("hookSpecificOutput", {}).get("permissionDecision")


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.state = self.base / "state"
        self.skill = self.base / "yomiyasu" / "SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text("---\nname: yomiyasu\n---\n", encoding="utf-8")
        self.agent_def = self.base / "agents" / "jp-doc-reviewer.md"
        self.agent_def.parent.mkdir(parents=True)
        self.agent_def.write_text("---\nname: jp-doc-reviewer\n---\n", encoding="utf-8")
        self.repo = self.base / "repo"
        (self.repo / ".git").mkdir(parents=True)
        self.transcript_path = self.base / "transcript.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, event, payload, raw=None):
        env = {**os.environ, "JP_DOC_REVIEW_STATE_DIR": str(self.state),
               "JP_DOC_REVIEW_YOMIYASU_SKILL": str(self.skill),
               "JP_DOC_REVIEW_AGENT_DEF": str(self.agent_def)}
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

    def transcript(self, *entries):
        """会話記録に行を追記して、そのパスを返す。"""
        with self.transcript_path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return self.transcript_path

    def commit(self, command="git commit -m x", cwd=None, session="s1", transcript=None, **extra):
        payload = {"session_id": session, "cwd": str(cwd or self.repo), "tool_name": "Bash",
                   "tool_input": {"command": command, "description": "d"}, **extra}
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        return self.run_hook("pre-tool-use-bash", payload)

    def records(self, session="s1"):
        path = self.state / f"{session}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def dispatched(self, session="s1"):
        return self.state / f"{session}.dispatched.json"

    def make_repo(self, relative):
        root = self.base / relative
        (root / ".git").mkdir(parents=True)
        return root


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


class CommitTests(HookCase):
    def reset_state(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def test_non_commit_commands_are_ignored(self):
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        for command in ("git status", "echo 'git commit'", "git log | grep commit",
                        "git commit-tree abc", "git -C . log", "gitx commit"):
            with self.subTest(command=command):
                self.assertEqual(self.commit(command), (0, {}, ""))
        self.assertFalse(self.dispatched().exists())
        self.assertEqual(len(self.records()), 1)

    def test_detects_commit_inside_compound_commands(self):
        path = self.write_file("a.md", JP_LONG)
        commands = (
            "git commit -m x",
            "GIT_AUTHOR_NAME=a LANG=C git commit -m x",
            "git add a.md && git commit -m x",
            "git status; git commit -m x",
            "false || git commit -m x",
            "git diff | cat\ngit commit -m x",
            "git -c user.name=a --no-pager commit -m x",
            "git --git-dir=.git commit -m x",
            "/usr/bin/git commit -m x",
            # 本文の二重引用符が対にならず、shlexでは最後まで分けられない形
            "git commit -m \"$(cat <<'EOF'\nfix: \"a\nEOF\n)\"",
        )
        for command in commands:
            with self.subTest(command=command):
                self.reset_state()
                self.post(path, JP_LONG)
                self.assertEqual(decision_of(self.commit(command)), "deny")

    def test_dash_c_selects_repository_relative_to_cwd(self):
        other = self.make_repo("other")
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.assertEqual(self.commit("git -C ../other commit -m x"), (0, {}, ""))
        self.assertEqual(decision_of(self.commit("git -C ../repo commit -m x", cwd=other)), "deny")

    def test_records_outside_the_repository_are_not_counted(self):
        other = self.make_repo("other")
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.assertEqual(self.commit(cwd=other), (0, {}, ""))
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(decision_of(self.commit()), "deny")

    def test_records_in_nested_repository_belong_to_it(self):
        nested = self.repo / ".claude" / "worktrees" / "wt"
        nested.mkdir(parents=True)
        (nested / ".git").write_text(f"gitdir: {self.repo}/.git/worktrees/wt\n", encoding="utf-8")
        self.post(self.write_file("a.md", JP_LONG, root=nested), JP_LONG)
        self.assertEqual(self.commit(), (0, {}, ""))
        self.assertEqual(decision_of(self.commit(cwd=nested)), "deny")

    def test_threshold_boundary(self):
        short = self.write_file("short.md", "あ" * 99)
        self.post(short, "あ" * 99)
        self.assertEqual(self.commit(), (0, {}, ""))
        exact = self.write_file("exact.md", "あ" * 100)
        self.post(exact, "あ" * 100, session="s2")
        self.assertEqual(decision_of(self.commit(session="s2")), "deny")

    def test_small_writes_accumulate_until_commit(self):
        path = self.write_file("a.md", JP_HALF)
        self.post(path, JP_HALF)
        self.assertEqual(self.commit(), (0, {}, ""))
        self.post(path, JP_HALF, tool="Edit")
        self.assertEqual(decision_of(self.commit()), "deny")

    def test_deleted_file_is_not_reviewed(self):
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        path.unlink()
        self.assertEqual(self.commit(), (0, {}, ""))

    def test_file_without_kana_now_is_not_reviewed(self):
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        path.write_text("rewritten in english", encoding="utf-8")
        self.assertEqual(self.commit(), (0, {}, ""))

    def test_missing_yomiyasu_or_reviewer_is_reported_once_without_blocking(self):
        for missing in (self.skill, self.agent_def):
            with self.subTest(missing=missing.name):
                self.reset_state()
                saved = missing.read_text(encoding="utf-8")
                missing.unlink()
                try:
                    self.post(self.write_file("a.md", JP_LONG), JP_LONG)
                    code, output, _ = self.commit()
                    self.assertEqual(code, 0)
                    self.assertNotIn("hookSpecificOutput", output)
                    self.assertIn("レビューを省略", output["systemMessage"])
                    self.assertEqual(self.commit(), (0, {}, ""))
                finally:
                    missing.write_text(saved, encoding="utf-8")

    def test_commit_inside_subagent_warns_without_blocking(self):
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        code, output, _ = self.commit(agent_id="a1", agent_type="general-purpose")
        self.assertEqual(code, 0)
        self.assertNotIn("hookSpecificOutput", output)
        self.assertIn("a.md", output["systemMessage"])
        self.assertIn("レビューしない", output["systemMessage"])
        self.assertFalse(self.dispatched().exists())
        self.assertEqual(len(self.records()), 1)

    def test_first_commit_is_denied_with_paths_and_instructions(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        code, output, _ = self.commit(transcript=transcript)
        self.assertEqual(code, 0)
        decision = output["hookSpecificOutput"]
        self.assertEqual((decision["hookEventName"], decision["permissionDecision"]), ("PreToolUse", "deny"))
        reason = decision["permissionDecisionReason"]
        for marker in (str(path), "jp-doc-reviewer", "このセッションで書いた箇所", "その範囲だけ",
                       "git add", "もう一度", "ユーザーに伝え"):
            with self.subTest(marker=marker):
                self.assertIn(marker, reason)
        dispatched = json.loads(self.dispatched().read_text(encoding="utf-8"))
        self.assertEqual(dispatched, {"paths": [str(path)], "record_lines": 1,
                                      "transcript_offset": transcript.stat().st_size})

    def test_second_commit_passes_and_keeps_writes_after_dispatch(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        other = self.make_repo("other")
        elsewhere = self.write_file("b.md", JP_LONG, root=other)
        self.post(elsewhere, JP_LONG)
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        self.assertEqual(decision_of(self.commit(transcript=transcript)), "deny")
        self.post(path, JP_HALF, tool="Edit")
        self.transcript(agent_call("jp-doc-reviewer"))
        self.assertEqual(self.commit(transcript=transcript), (0, {}, ""))
        self.assertEqual(self.records(), [{"path": str(elsewhere), "jp_chars": 144},
                                          {"path": str(path), "jp_chars": 52}])
        self.assertFalse(self.dispatched().exists())

    def test_task_tool_counts_as_reviewer_invocation(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.commit(transcript=transcript)
        self.transcript(agent_call("jp-doc-reviewer", name="Task"))
        self.assertEqual(self.commit(transcript=transcript), (0, {}, ""))

    def test_second_commit_warns_when_reviewer_was_not_invoked(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.commit(transcript=transcript)
        code, output, _ = self.commit(transcript=transcript)
        self.assertEqual(code, 0)
        self.assertNotIn("hookSpecificOutput", output)
        self.assertIn("jp-doc-reviewerが起動されない", output["systemMessage"])
        self.assertIn("a.md", output["systemMessage"])
        self.assertEqual(self.records(), [])

    def test_reviewer_call_before_dispatch_does_not_count(self):
        transcript = self.transcript(agent_call("jp-doc-reviewer"))
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.commit(transcript=transcript)
        self.assertIn("起動されない", self.commit(transcript=transcript)[1]["systemMessage"])

    def test_unreadable_transcript_on_second_commit_is_reported(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.commit(transcript=transcript)
        transcript.unlink()
        self.assertIn("確認できなかった", self.commit(transcript=transcript)[1]["systemMessage"])

    def test_unknown_transcript_size_at_dispatch_is_reported(self):
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.assertEqual(decision_of(self.commit()), "deny")
        self.transcript(agent_call("jp-doc-reviewer"))
        output = self.commit(transcript=self.transcript_path)[1]
        self.assertIn("確認できなかった", output["systemMessage"])

    def test_writes_after_second_commit_are_checked_again(self):
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.commit()
        self.commit()
        self.post(self.write_file("b.md", JP_LONG), JP_LONG)
        self.assertEqual(decision_of(self.commit()), "deny")

    def test_broken_log_lines_are_counted_in_message(self):
        self.state.mkdir(parents=True)
        (self.state / "s1.jsonl").write_text("{broken\n", encoding="utf-8")
        self.assertIn("1件", self.commit()[1]["systemMessage"])

    def test_old_state_files_are_removed_on_commit(self):
        self.state.mkdir(parents=True)
        old = self.state / "old-session.jsonl"
        old.write_text("", encoding="utf-8")
        eight_days_ago = time.time() - 8 * 86400
        os.utime(old, (eight_days_ago, eight_days_ago))
        self.commit()
        self.assertFalse(old.exists())

    def test_bash_input_without_command_fails_loudly(self):
        payload = {"session_id": "s1", "cwd": str(self.repo), "tool_name": "Bash", "tool_input": {}}
        code, output, stderr = self.run_hook("pre-tool-use-bash", payload)
        self.assertEqual((code, output), (1, {}))
        self.assertIn("command", stderr)

    def test_stop_event_is_no_longer_handled(self):
        code, _, stderr = self.run_hook("stop", {"session_id": "s1", "stop_hook_active": False})
        self.assertEqual(code, 1)
        self.assertIn("使い方", stderr)


class ConfluenceTests(HookCase):
    TOOL = "mcp__atlassian-http__createConfluencePage"

    def pre(self, body, title="", tool=None, **tool_input):
        payload = {"session_id": "s1", "tool_name": tool or self.TOOL,
                   "tool_input": {"cloudId": "c", "spaceId": "1", "title": title, "body": body, **tool_input}}
        return self.run_hook("pre-tool-use-confluence", payload)

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

    def test_changed_write_or_edit_input_fails_loudly(self):
        path = str(self.write_file("a.md", "x"))
        broken_inputs = (
            ("Write", {"file_path": path}),
            ("Edit", {"file_path": path, "old_string": "x"}),
            ("Write", {"path": path, "content": JP_LONG}),
            ("Edit", {"file_path": 1, "new_string": JP_LONG}),
            ("Write", {"file_path": path, "content": None}),
            ("Write", "not a dict"),
        )
        for tool, tool_input in broken_inputs:
            with self.subTest(tool=tool, tool_input=tool_input):
                payload = {"session_id": "s1", "cwd": str(self.repo), "tool_name": tool, "tool_input": tool_input}
                code, output, stderr = self.run_hook("post-tool-use", payload)
                self.assertEqual((code, output), (1, {}))
                self.assertIn("入力の形", stderr)
        self.assertEqual(self.records(), [])

    def test_edit_with_empty_new_string_is_valid(self):
        path = self.write_file("a.md", "x")
        self.assertEqual(self.post(path, "", tool="Edit"), (0, {}, ""))

    def test_other_tools_are_ignored(self):
        payload = {"session_id": "s1", "cwd": str(self.repo), "tool_name": "NotebookEdit", "tool_input": {}}
        self.assertEqual(self.run_hook("post-tool-use", payload), (0, {}, ""))

    def test_empty_stdin_fails_loudly(self):
        for event in ("post-tool-use", "pre-tool-use-bash", "pre-tool-use-confluence"):
            with self.subTest(event=event):
                code, output, stderr = self.run_hook(event, None, raw="")
                self.assertEqual((code, output), (1, {}))
                self.assertIn("入力が空", stderr)

    def test_missing_session_id_fails_even_for_non_target_file(self):
        path = self.write_file("a.py", "x")
        payload = {"tool_name": "Write", "cwd": str(self.repo), "tool_input": {"file_path": str(path), "content": "x"}}
        code, _, stderr = self.run_hook("post-tool-use", payload)
        self.assertEqual(code, 1)
        self.assertIn("session_id", stderr)

    def test_unknown_event_fails(self):
        code, _, stderr = self.run_hook("unknown", {})
        self.assertEqual(code, 1)
        self.assertIn("使い方", stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
