#!/usr/bin/env python3
"""hooks/jp-doc-review.py の振る舞いを、合成した入力で検証する。

合成した入力でのテストは、実機で動く証拠にならない。実機の入力は
docs/research/2026-10-02-claude-code-hook-payloads.md に記録している。

実行: python3 -m unittest tests.test_jp_doc_review_hook
"""
import json
import os
import shutil
import stat
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
        # テストのファイルは一時ディレクトリの下に作るので、除外する置き場を差し替える
        self.claude_home = self.base / "claude-home"
        self.temp_root = self.base / "tmp"
        self.env_overrides = {"JP_DOC_REVIEW_CLAUDE_HOME": str(self.claude_home),
                              "JP_DOC_REVIEW_TEMP_DIRS": str(self.temp_root)}

    def tearDown(self):
        self.tmp.cleanup()

    def hook_env(self):
        env = {**os.environ, "JP_DOC_REVIEW_STATE_DIR": str(self.state),
               "JP_DOC_REVIEW_YOMIYASU_SKILL": str(self.skill),
               "JP_DOC_REVIEW_AGENT_DEF": str(self.agent_def), **self.env_overrides}
        env.pop("FORCE_COLOR", None)
        return {name: value for name, value in env.items() if value is not None}

    def run_hook(self, event, payload, raw=None):
        # 権限を確かめるテストが実行環境のumaskに左右されないよう、よくある022にそろえる
        result = subprocess.run(
            [sys.executable, str(HOOK), event],
            input=raw if raw is not None else json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, env=self.hook_env(), preexec_fn=lambda: os.umask(0o022),
        )
        output = json.loads(result.stdout) if result.stdout.strip() else {}
        return result.returncode, output, result.stderr

    def run_parallel(self, event, payloads):
        """同じイベントを並行して動かし、(終了コード, 出力, 標準エラー) の一覧を返す。"""
        processes = [
            subprocess.Popen([sys.executable, str(HOOK), event], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=self.hook_env())
            for _ in payloads
        ]
        for process, payload in zip(processes, payloads):
            process.stdin.write(json.dumps(payload, ensure_ascii=False))
            process.stdin.close()
        results = []
        for process in processes:
            stdout, stderr = process.stdout.read(), process.stderr.read()
            process.wait()
            process.stdout.close()
            process.stderr.close()
            results.append((process.returncode, json.loads(stdout) if stdout.strip() else {}, stderr))
        return results

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

    def test_ignores_disposable_work_files(self):
        for relative in ("tasks/todo.md", ".superpowers/sdd/x/brief.md", "docs/.superpowers/a.md"):
            self.post(self.write_file(relative, "x"), JP_LONG)
        self.assertEqual(self.records(), [])

    def test_other_todo_and_tasks_files_are_recorded(self):
        for relative in ("tasks/backlog.md", "docs/todo.md"):
            self.post(self.write_file(relative, "x"), JP_LONG)
        self.assertEqual(len(self.records()), 2)

    def test_ignores_files_under_claude_home(self):
        self.post(self.write_file("projects/p/memory/MEMORY.md", "x", root=self.claude_home), JP_LONG)
        self.post(self.write_file("plans/plan.md", "x", root=self.claude_home), JP_LONG)
        self.assertEqual(self.records(), [])

    def test_managed_file_linked_from_claude_home_is_recorded_as_repository_file(self):
        real = self.write_file("rules/a.md", "x")
        self.claude_home.mkdir()
        (self.claude_home / "rules").symlink_to(self.repo / "rules")
        self.post(self.claude_home / "rules" / "a.md", JP_LONG)
        self.assertEqual(self.records(), [{"path": str(real), "jp_chars": 144}])

    def test_ignores_files_under_temporary_directories(self):
        scratch = self.temp_root / "scratch"
        (scratch / ".git").mkdir(parents=True)
        self.post(self.write_file("a.md", "x", root=scratch), JP_LONG)
        self.assertEqual(self.records(), [])

    def test_default_temporary_directory_follows_tmpdir(self):
        system_tmp = self.base / "system-tmp"
        self.env_overrides = {**self.env_overrides, "JP_DOC_REVIEW_TEMP_DIRS": None, "TMPDIR": str(system_tmp)}
        scratch = system_tmp / "scratch"
        (scratch / ".git").mkdir(parents=True)
        path = self.write_file("a.md", "x", root=scratch)
        self.post(path, JP_LONG)
        # /tmp の下で動く環境では repo 側も除外されるので、scratch の除外だけを確かめる
        self.assertNotIn(str(path), [record["path"] for record in self.records()])

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

    def test_commit_reason_asks_for_absolute_paths_in_the_request(self):
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        reason = self.commit()[1]["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("対象のパスを絶対パスでそのまま書く", reason)

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


class ReviewerBashTests(HookCase):
    """jp-doc-reviewer が使える Bash は、yomiyasu のリンターだけ。"""

    def lint_path(self, nested=False):
        base = self.skill.parent / "skills" / "yomiyasu" if nested else self.skill.parent
        return base / "scripts" / "yomiyasu_lint.py"

    def bash(self, command):
        payload = {"session_id": "s1", "tool_name": "Bash", "agent_type": "jp-doc-reviewer",
                   "tool_input": {"command": command}}
        return self.run_hook("pre-tool-use-reviewer-bash", payload)

    def assertAllowed(self, command):
        self.assertEqual(self.bash(command), (0, {}, ""), command)

    def assertDenied(self, command):
        result = self.bash(command)
        self.assertEqual((result[0], decision_of(result)), (0, "deny"), command)
        self.assertIn("リンターだけ", result[1]["hookSpecificOutput"]["permissionDecisionReason"])

    def test_linter_with_one_file_passes(self):
        self.assertAllowed(f"python3 {self.lint_path()} 'docs/a.md'")
        self.assertAllowed(f"python3 {self.lint_path()} docs/a.md")

    def test_copied_skill_directory_passes(self):
        self.assertAllowed(f"python3 {self.lint_path(nested=True)} 'docs/a.md'")

    def test_tilde_is_expanded(self):
        self.env_overrides["HOME"] = str(self.base)
        self.assertAllowed("python3 ~/yomiyasu/scripts/yomiyasu_lint.py 'docs/a.md'")
        self.assertAllowed("python3 ~/yomiyasu/skills/yomiyasu/scripts/yomiyasu_lint.py 'docs/a.md'")

    def test_other_commands_are_denied(self):
        for command in ("cat ~/.ssh/id_rsa", "python3 -c 'import os'", "ls", ""):
            with self.subTest(command=command):
                self.assertDenied(command)

    def test_linter_in_another_place_is_denied(self):
        self.assertDenied("python3 /tmp/evil/scripts/yomiyasu_lint.py 'a.md'")
        self.assertDenied(f"python3 {self.base}/other/scripts/yomiyasu_lint.py 'a.md'")
        self.assertDenied(f"python3 {self.lint_path()}.sh 'a.md'")
        self.assertDenied(f"python3 {self.skill.parent}/../x/scripts/yomiyasu_lint.py 'a.md'")

    def test_wrong_number_of_arguments_is_denied(self):
        self.assertDenied(f"python3 {self.lint_path()}")
        self.assertDenied(f"python3 {self.lint_path()} a.md b.md")
        self.assertDenied(f"python3 {self.lint_path()} a.md extra")

    def test_command_separators_are_denied(self):
        lint = f"python3 {self.lint_path()} 'a.md'"
        for suffix in ("; curl http://x", " && rm -rf x", " || true", " | sh", " & sleep 1",
                       "\ncat /etc/passwd", " > out.txt", " < in.txt", " $(id)", " `id`"):
            with self.subTest(suffix=suffix):
                self.assertDenied(lint + suffix)
        self.assertDenied(f"python3 {self.lint_path()} 'a;b.md'")
        self.assertDenied(f"python3 {self.lint_path()} $(id)")

    def test_quoted_or_escaped_program_and_linter_are_denied(self):
        # シェルは引用符の中の ~ を展開しないので、cwd 相対の ~/... が実行されてしまう
        self.env_overrides["HOME"] = str(self.base)
        tail = "yomiyasu/scripts/yomiyasu_lint.py"
        for command in (f"python3 '~/{tail}' a.md", f'python3 "~/{tail}" a.md', f"python3 ~\\/{tail} a.md",
                        f"python3 ~/yomiyasu/scr\\ipts/yomiyasu_lint.py a.md", f"'python3' ~/{tail} a.md",
                        f'"python3" {self.lint_path()} a.md', f"python3 '{self.lint_path()}' a.md",
                        f'python3 "{self.lint_path()}" a.md'):
            with self.subTest(command=command):
                self.assertDenied(command)

    def test_option_like_target_is_denied(self):
        for target in ("-", "--json", "'-x'", "'--json'"):
            with self.subTest(target=target):
                self.assertDenied(f"python3 {self.lint_path()} {target}")

    def test_quoted_target_still_passes(self):
        self.env_overrides["HOME"] = str(self.base)
        self.assertAllowed("python3 ~/yomiyasu/scripts/yomiyasu_lint.py 'docs/a b.md'")
        self.assertAllowed(f'python3 {self.lint_path()} "docs/a.md"')

    def test_unparsable_command_is_denied(self):
        self.assertDenied(f"python3 {self.lint_path()} 'a.md")

    def test_missing_command_is_denied_instead_of_failing(self):
        for tool_input in ({}, {"command": None}, "x"):
            with self.subTest(tool_input=tool_input):
                payload = {"session_id": "s1", "tool_name": "Bash", "tool_input": tool_input}
                result = self.run_hook("pre-tool-use-reviewer-bash", payload)
                self.assertEqual((result[0], decision_of(result)), (0, "deny"))


class ReviewerAllowTests(HookCase):
    """jp-doc-reviewer への依頼文に書かれたファイルを、Editの許可リストへ記録する。"""

    def agent(self, prompt, subagent_type="jp-doc-reviewer", session="s1", **extra):
        payload = {"session_id": session, "cwd": str(self.repo), "tool_name": "Agent",
                   "tool_input": {"subagent_type": subagent_type, "description": "d", "prompt": prompt}, **extra}
        return self.run_hook("pre-tool-use-agent", payload)

    def allowed(self, session="s1"):
        path = self.state / f"{session}.reviewer-allow.json"
        return json.loads(path.read_text(encoding="utf-8"))["paths"] if path.exists() else None

    def test_path_in_backticks_is_recorded(self):
        doc = self.write_file("docs/a.md", "x")
        self.assertEqual(self.agent(f"次を直して。\n- `{doc}`"), (0, {}, ""))
        self.assertEqual(self.allowed(), [os.path.realpath(doc)])

    def test_path_between_japanese_characters_is_recorded(self):
        self.write_file("docs/a.md", "x")
        self.agent("docs/a.mdを直して")
        self.assertEqual(self.allowed(), [os.path.realpath(self.repo / "docs/a.md")])

    def test_tilde_and_relative_paths_are_expanded(self):
        home = self.base / "home"
        (home / "notes").mkdir(parents=True)
        (home / "notes" / "n.md").write_text("x", encoding="utf-8")
        self.write_file("docs/r.md", "x")
        self.env_overrides["HOME"] = str(home)
        self.agent("~/notes/n.md と docs/r.md")
        self.assertEqual(sorted(self.allowed()), sorted(os.path.realpath(path) for path in
                                                        (home / "notes" / "n.md", self.repo / "docs" / "r.md")))

    def test_trailing_punctuation_is_dropped(self):
        self.write_file("docs/a.md", "x")
        self.agent("対象は docs/a.md, docs/a.md. docs/a.md:")
        self.assertEqual(self.allowed(), [os.path.realpath(self.repo / "docs/a.md")])

    def test_missing_files_directories_and_words_without_slash_are_not_recorded(self):
        self.write_file("docs/a.md", "x")
        code, output, _ = self.agent("docs/missing.md と docs と a.md と /etc/ と docs/")
        self.assertEqual(code, 0)
        self.assertIsNone(self.allowed())
        self.assertIn("依頼文にパスが無い", output["systemMessage"])

    def test_symlink_is_recorded_as_real_path(self):
        target = self.write_file("docs/real.md", "x")
        (self.repo / "link.md").symlink_to(target)
        self.agent("./link.md")
        self.assertEqual(self.allowed(), [os.path.realpath(target)])

    def test_other_subagent_types_are_not_recorded(self):
        self.write_file("docs/a.md", "x")
        self.assertEqual(self.agent("docs/a.md", subagent_type="Explore"), (0, {}, ""))
        self.assertIsNone(self.allowed())

    def test_calls_from_a_subagent_are_not_recorded(self):
        self.write_file("docs/a.md", "x")
        self.assertEqual(self.agent("docs/a.md", agent_type="jp-doc-reviewer"), (0, {}, ""))
        self.assertIsNone(self.allowed())

    def test_second_call_adds_to_the_first(self):
        first, second = self.write_file("docs/a.md", "x"), self.write_file("docs/b.md", "x")
        self.agent("docs/a.md")
        self.agent("docs/b.md")
        self.assertEqual(sorted(self.allowed()), sorted(os.path.realpath(path) for path in (first, second)))

    def test_allow_list_is_private_and_removed_when_old(self):
        self.write_file("docs/a.md", "x")
        self.agent("docs/a.md")
        path = self.state / "s1.reviewer-allow.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        os.utime(path, (time.time() - 8 * 86400,) * 2)
        self.commit(session="other")
        self.assertFalse(path.exists())


class ReviewerEditTests(HookCase):
    """jp-doc-reviewer の Edit は、依頼文に書かれたファイルだけ。制限の仕組みそのものは書き換えさせない。"""

    def allow(self, *paths, session="s1"):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / f"{session}.reviewer-allow.json").write_text(
            json.dumps({"paths": [os.path.realpath(path) for path in paths]}), encoding="utf-8")

    def edit(self, file_path, session="s1"):
        payload = {"session_id": session, "tool_name": "Edit", "agent_type": "jp-doc-reviewer", "cwd": str(self.repo),
                   "tool_input": {"file_path": file_path, "old_string": "a", "new_string": "b"}}
        return self.run_hook("pre-tool-use-reviewer-edit", payload)

    def assertAllowed(self, file_path):
        self.assertEqual(self.edit(file_path), (0, {}, ""), file_path)

    def assertDenied(self, file_path):
        result = self.edit(file_path)
        self.assertEqual((result[0], decision_of(result)), (0, "deny"), file_path)
        self.assertIn("依頼文に書かれたファイルだけを直せる", result[1]["hookSpecificOutput"]["permissionDecisionReason"])

    def test_requested_file_passes(self):
        doc = self.write_file("docs/a.md", "x")
        self.allow(doc)
        self.assertAllowed(str(doc))
        self.assertAllowed("docs/a.md")

    def test_unrequested_markdown_is_denied(self):
        self.allow(self.write_file("docs/a.md", "x"))
        self.assertDenied(str(self.write_file("docs/other.md", "x")))
        self.assertDenied(str(self.repo / ".claude" / "settings.json"))

    def test_other_sessions_allow_list_does_not_count(self):
        doc = self.write_file("docs/a.md", "x")
        self.allow(doc, session="other")
        self.assertDenied(str(doc))

    def test_symlink_to_requested_file_passes(self):
        doc = self.write_file("docs/a.md", "x")
        (self.repo / "link.md").symlink_to(doc)
        self.allow(doc)
        self.assertAllowed(str(self.repo / "link.md"))

    def test_protected_files_are_denied_even_when_listed(self):
        self.claude_home.mkdir(parents=True)
        for name in ("settings.json", "settings.local.json", "settings.personal.json"):
            (self.claude_home / name).write_text("{}", encoding="utf-8")
        scripts = self.skill.parent / "scripts"
        scripts.mkdir()
        (scripts / "yomiyasu_lint.py").write_text("", encoding="utf-8")
        protected = [self.skill, scripts / "yomiyasu_lint.py", HOOK, HOOK.parent / "hook_support.py", self.agent_def,
                     *(self.claude_home / name for name in ("settings.json", "settings.local.json", "settings.personal.json"))]
        self.allow(*protected)
        for path in protected:
            with self.subTest(path=str(path)):
                self.assertDenied(str(path))

    def test_symlink_to_protected_file_is_denied_even_when_listed(self):
        link = self.repo / "link.md"
        link.symlink_to(self.skill)
        self.allow(link)
        self.assertDenied(str(link))

    def test_missing_or_broken_allow_list_denies(self):
        doc = self.write_file("docs/a.md", "x")
        self.assertDenied(str(doc))
        self.state.mkdir(parents=True)
        for content in ("{broken", "[]", '{"paths": "x"}', '{"paths": [1]}', '{}'):
            with self.subTest(content=content):
                (self.state / "s1.reviewer-allow.json").write_text(content, encoding="utf-8")
                self.assertDenied(str(doc))

    def test_missing_or_non_string_file_path_is_denied(self):
        self.allow(self.write_file("docs/a.md", "x"))
        for tool_input in ({}, {"file_path": 5}, {"file_path": None}, {"file_path": ""}, "x"):
            with self.subTest(tool_input=tool_input):
                payload = {"session_id": "s1", "tool_name": "Edit", "tool_input": tool_input}
                result = self.run_hook("pre-tool-use-reviewer-edit", payload)
                self.assertEqual((result[0], decision_of(result)), (0, "deny"))


class ReviewerFailClosedTests(HookCase):
    """reviewer-edit と reviewer-bash は、入力の不備や判定中の例外をすべて deny にする。"""

    EVENTS = ("pre-tool-use-reviewer-edit", "pre-tool-use-reviewer-bash")

    def assertDeniedWith(self, event, payload=None, raw=None):
        result = self.run_hook(event, payload, raw=raw)
        self.assertEqual((result[0], decision_of(result)), (0, "deny"), (event, payload, raw, result[2]))

    def test_missing_session_id_is_denied(self):
        doc = self.write_file("docs/a.md", "x")
        self.assertDeniedWith("pre-tool-use-reviewer-edit", {"tool_name": "Edit", "tool_input": {"file_path": str(doc)}})
        self.assertDeniedWith("pre-tool-use-reviewer-edit", {"session_id": 5, "tool_input": {"file_path": str(doc)}})

    def test_nul_in_input_is_denied(self):
        self.assertDeniedWith("pre-tool-use-reviewer-edit",
                              {"session_id": "s1", "tool_input": {"file_path": "docs/a\u0000.md"}})
        self.assertDeniedWith("pre-tool-use-reviewer-bash",
                              {"session_id": "s1", "tool_input": {"command": "python3 \u0000 a.md"}})

    def test_broken_stdin_is_denied(self):
        for event in self.EVENTS:
            for raw in ("", "{broken", "[]", "null"):
                with self.subTest(event=event, raw=raw):
                    self.assertDeniedWith(event, raw=raw)

    def test_unusable_state_directory_is_denied(self):
        doc = self.write_file("docs/a.md", "x")
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text("file, not directory", encoding="utf-8")
        self.assertDeniedWith("pre-tool-use-reviewer-edit", {"session_id": "s1", "tool_input": {"file_path": str(doc)}})


class EarlyCleanupTests(HookCase):
    def make_old_files(self):
        self.state.mkdir(parents=True)
        (self.state / "drafts").mkdir()
        old_state, old_draft = self.state / "old.jsonl", self.state / "drafts" / "old-1.html"
        for path in (old_state, old_draft):
            path.write_text("", encoding="utf-8")
            os.utime(path, (time.time() - 8 * 86400,) * 2)
        return old_state, old_draft

    def stamp(self):
        return self.state / ".last-cleanup"

    def test_post_tool_use_removes_old_files(self):
        old_state, old_draft = self.make_old_files()
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.assertFalse(old_state.exists() or old_draft.exists())

    def test_confluence_post_removes_old_files(self):
        old_state, old_draft = self.make_old_files()
        payload = {"session_id": "s1", "tool_name": "mcp__x__createConfluencePage",
                   "tool_input": {"body": "短い", "title": ""}}
        self.run_hook("pre-tool-use-confluence", payload)
        self.assertFalse(old_state.exists() or old_draft.exists())

    def test_scan_runs_at_most_once_per_hour(self):
        old_state, _ = self.make_old_files()
        self.stamp().write_text("", encoding="utf-8")
        self.commit()
        self.assertTrue(old_state.exists())
        os.utime(self.stamp(), (time.time() - 2 * 3600,) * 2)
        self.commit()
        self.assertFalse(old_state.exists())
        self.assertLess(time.time() - self.stamp().stat().st_mtime, 3600)


class ConfluenceTests(HookCase):
    TOOL = "mcp__atlassian-http__createConfluencePage"

    def pre(self, body, title="", tool=None, transcript=None, **tool_input):
        payload = {"session_id": "s1", "tool_name": tool or self.TOOL,
                   "tool_input": {"cloudId": "c", "spaceId": "1", "title": title, "body": body, **tool_input}}
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        return self.run_hook("pre-tool-use-confluence", payload)

    REVIEWED = JP_LONG.replace("テスト用", "確認用")

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
        self.assertIn("このセッションで書いた箇所だけ", decision["permissionDecisionReason"])

    def test_first_post_records_body_hash_and_transcript_size(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.pre(JP_LONG, pageId="9", transcript=transcript)
        state = json.loads((self.state / "s1.confluence.json").read_text(encoding="utf-8"))
        self.assertEqual(list(state), [f"{self.TOOL}:pageId:9"])
        entry = state[f"{self.TOOL}:pageId:9"]
        self.assertEqual(entry["transcript_offset"], transcript.stat().st_size)
        self.assertEqual(len(entry["digest"]), 64)

    def test_confluence_reason_asks_for_absolute_paths_in_the_request(self):
        reason = self.pre(JP_LONG, pageId="9")[1]["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("対象のパスを絶対パスでそのまま書く", reason)

    def test_draft_suffix_follows_content_format(self):
        self.pre(JP_LONG, contentFormat="markdown", pageId="1")
        self.pre(JP_LONG + "。", contentFormat="adf", pageId="2")
        self.pre(JP_LONG + "、", pageId="3")
        suffixes = sorted(path.suffix for path in (self.state / "drafts").iterdir())
        self.assertEqual(suffixes, [".html", ".json", ".md"])

    def test_threshold_boundary(self):
        self.assertEqual(self.pre("あ" * 99, pageId="1"), (0, {}, ""))
        self.assertEqual(decision_of(self.pre("あ" * 100, pageId="2")), "deny")

    def test_target_key_prefers_page_id_then_parent_comment_then_title(self):
        # 2回目に同じ投稿先とみなされれば通り、別の投稿先とみなされれば止められる
        self.pre(JP_LONG, pageId="p", parentCommentId="c1", title="t1")
        self.assertIsNone(decision_of(self.pre(self.REVIEWED, pageId="p", parentCommentId="c2", title="t2")))
        self.pre(JP_LONG, parentCommentId="c", title="t1")
        self.assertIsNone(decision_of(self.pre(self.REVIEWED, parentCommentId="c", title="t2")))
        self.assertEqual(decision_of(self.pre(JP_LONG, pageId="other", parentCommentId="c", title="t1")), "deny")
        self.pre(JP_LONG, title="t")
        self.assertIsNone(decision_of(self.pre(self.REVIEWED, title="t")))

    def test_title_counts_toward_threshold(self):
        self.assertEqual(self.pre("本文。", title=JP_LONG)[1]["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_second_post_removes_the_draft_of_the_first(self):
        self.pre(JP_LONG, pageId="9")
        self.assertEqual(len(list((self.state / "drafts").iterdir())), 1)
        self.pre(self.REVIEWED, pageId="9")
        self.assertEqual(list((self.state / "drafts").iterdir()), [])

    def test_second_post_keeps_drafts_of_other_targets(self):
        self.pre(JP_LONG, pageId="1")
        self.pre(JP_LONG + "。", pageId="2")
        self.pre(self.REVIEWED, pageId="1")
        self.assertEqual(len(list((self.state / "drafts").iterdir())), 1)

    def test_second_post_ignores_draft_path_outside_drafts_directory(self):
        outside = self.base / "outside.md"
        outside.write_text("x", encoding="utf-8")
        self.state.mkdir(parents=True)
        target = f"{self.TOOL}:pageId:9"
        (self.state / "s1.confluence.json").write_text(json.dumps(
            {target: {"digest": "0" * 64, "transcript_offset": 0, "draft": str(outside)}}), encoding="utf-8")
        self.pre(self.REVIEWED, pageId="9")
        self.assertTrue(outside.exists())

    def test_second_post_passes_and_warns_when_unchanged(self):
        self.pre(JP_LONG, pageId="9")
        code, output, _ = self.pre(JP_LONG, pageId="9")
        self.assertEqual(code, 0)
        self.assertNotIn("hookSpecificOutput", output)
        self.assertIn("レビューを通らない", output["systemMessage"])

    def test_second_post_with_reviewed_body_is_silent(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.pre(JP_LONG, pageId="9", transcript=transcript)
        self.transcript(agent_call("jp-doc-reviewer"))
        self.assertEqual(self.pre(self.REVIEWED, pageId="9", transcript=transcript), (0, {}, ""))

    def test_second_post_warns_when_reviewer_was_not_invoked(self):
        transcript = self.transcript(agent_call("jp-doc-reviewer"))
        self.pre(JP_LONG, pageId="9", transcript=transcript)
        code, output, _ = self.pre(self.REVIEWED, pageId="9", transcript=transcript)
        self.assertEqual(code, 0)
        self.assertNotIn("hookSpecificOutput", output)
        self.assertIn("jp-doc-reviewerが起動されない", output["systemMessage"])

    def test_second_post_reports_when_transcript_cannot_be_checked(self):
        self.pre(JP_LONG, pageId="9")
        output = self.pre(self.REVIEWED, pageId="9", transcript=self.transcript(agent_call("jp-doc-reviewer")))[1]
        self.assertIn("確認できなかった", output["systemMessage"])

    def test_targets_are_tracked_separately(self):
        self.pre(JP_LONG, pageId="1")
        denied = self.pre(JP_LONG, pageId="2")[1]
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_after_passing_the_same_target_is_checked_again(self):
        self.pre(JP_LONG, pageId="1")
        self.pre(JP_LONG + "。", pageId="1")
        self.assertEqual(self.pre(JP_LONG + "、", pageId="1")[1]["hookSpecificOutput"]["permissionDecision"], "deny")


class StateFileTests(HookCase):
    CONFLUENCE_TOOL = "mcp__atlassian-http__createConfluencePage"

    def confluence_payload(self, page_id, session="s1"):
        return {"session_id": session, "tool_name": self.CONFLUENCE_TOOL,
                "tool_input": {"title": "", "body": JP_LONG, "pageId": page_id}}

    def test_state_is_private(self):
        self.state.mkdir(mode=0o755)
        os.chmod(self.state, 0o755)
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.assertEqual(decision_of(self.commit()), "deny")
        self.run_hook("pre-tool-use-confluence", self.confluence_payload("1"))
        self.skill.unlink()
        self.post(self.write_file("b.md", JP_LONG), JP_LONG, session="s2")
        self.assertIn("systemMessage", self.commit(session="s2")[1])
        names = {path.name for path in self.state.iterdir()}
        for expected in ("s1.jsonl", "s1.dispatched.json", "s1.confluence.json", "s2.flags.json"):
            with self.subTest(expected=expected):
                self.assertIn(expected, names)
        for directory in (self.state, self.state / "drafts"):
            with self.subTest(directory=directory.name):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        files = [path for path in self.state.rglob("*") if path.is_file()]
        self.assertTrue(any(path.parent.name == "drafts" for path in files))
        for path in files:
            with self.subTest(file=path.name):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_parallel_first_posts_are_all_denied_and_recorded(self):
        for round_number in range(5):
            with self.subTest(round=round_number):
                shutil.rmtree(self.state, ignore_errors=True)
                page_ids = [f"{round_number}-{index}" for index in range(6)]
                results = self.run_parallel("pre-tool-use-confluence",
                                            [self.confluence_payload(page_id) for page_id in page_ids])
                for code, output, stderr in results:
                    self.assertEqual(code, 0, stderr)
                    self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
                state = json.loads((self.state / "s1.confluence.json").read_text(encoding="utf-8"))
                self.assertEqual(len(state), len(page_ids))

    def test_writes_in_parallel_with_second_commit_are_kept(self):
        for round_number in range(3):
            with self.subTest(round=round_number):
                shutil.rmtree(self.state, ignore_errors=True)
                self.post(self.write_file("a.md", JP_LONG), JP_LONG)
                self.assertEqual(decision_of(self.commit()), "deny")
                paths = [self.write_file(f"r{round_number}-{index}.md", JP_HALF) for index in range(6)]
                commit_payload = {"session_id": "s1", "cwd": str(self.repo), "tool_name": "Bash",
                                  "tool_input": {"command": "git commit -m x"}}
                processes = [
                    subprocess.Popen([sys.executable, str(HOOK), "pre-tool-use-bash"], stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                     env=self.hook_env()),
                ]
                processes[0].stdin.write(json.dumps(commit_payload))
                processes[0].stdin.close()
                results = self.run_parallel("post-tool-use", [
                    {"session_id": "s1", "cwd": str(self.repo), "tool_name": "Write",
                     "tool_input": {"file_path": str(path), "content": JP_HALF}} for path in paths])
                processes[0].wait()
                processes[0].stderr.close()
                self.assertTrue(all(code == 0 for code, _, _ in results), results)
                self.assertEqual({record["path"] for record in self.records()}, {str(path) for path in paths})


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
