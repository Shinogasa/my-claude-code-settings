#!/usr/bin/env python3
"""hooks/code-learning-check.py を検証する。

実行: python3 -m unittest tests.test_code_learning_check
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "code-learning-check.py"
LINE = "コード学習: テストの識別力のレビュー → 出題（Review）"


def prompt(text="go"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def call(name, **tool_input):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]}}


def say(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


class CodeLearningCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.profile = self.base / "CLAUDE.md"
        self.profile.write_text("## ユーザープロファイル\n\n- 重点学習中: Go（初学者）。学習モードの上限が変わる\n",
                                encoding="utf-8")
        self.transcript = self.base / "t.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, entries, **payload):
        self.transcript.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
                                   encoding="utf-8")
        env = dict(os.environ, CODE_LEARNING_PROFILE=str(self.profile))
        result = subprocess.run(
            [sys.executable, str(HOOK), "stop"],
            input=json.dumps({"transcript_path": str(self.transcript), **payload}),
            text=True, capture_output=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_blocks_when_focus_file_was_read_without_judgment_line(self):
        output = self.run_hook([prompt(), call("Read", file_path="/repo/pkg/series.go"), say("426行目を消しても通る")])
        self.assertEqual(output.get("decision"), "block")
        self.assertIn("コード学習: <能力と対象> → <状態>（<根拠>）", output["reason"])

    def test_blocks_when_go_test_was_run_through_bash(self):
        output = self.run_hook([prompt(), call("Bash", command="go test ./pkg/... -count=1"), say("通った")])
        self.assertEqual(output.get("decision"), "block")

    def test_blocks_explanation_that_cites_focus_code_without_tools(self):
        # 2026-11-12: ツールを使わず、前のターンで読んだGoのコードを記憶から説明したターンが素通りした
        entries = [prompt("2これ詳しく"), call("Read", file_path="/skills/code-learning/SKILL.md"),
                   say("`integration_series_test.go:29` は、426行目を消しても通るはずだよ")]
        self.assertEqual(self.run_hook(entries).get("decision"), "block")

    def test_passes_when_judgment_line_is_written(self):
        for state in ("出題（Review）", "継続中（理由の回答）", "見送り（上限）", "候補なし（読んだのは定数だけ）", "OFF（学習なし）"):
            with self.subTest(state=state):
                entries = [prompt(), call("Read", file_path="/repo/a.go"), say(f"所見の前に\n`コード学習: 何か → {state}`\n本文")]
                self.assertEqual(self.run_hook(entries), {})

    def test_line_without_reason_or_unknown_state_does_not_count(self):
        for line in ("コード学習: 何か → 候補なし", "コード学習: 何か → たぶん（不明）"):
            with self.subTest(line=line):
                entries = [prompt(), call("Read", file_path="/repo/a.go"), say(line)]
                self.assertEqual(self.run_hook(entries).get("decision"), "block")

    def test_line_from_an_earlier_turn_does_not_count(self):
        entries = [prompt("前"), say(LINE), prompt("次"), call("Read", file_path="/repo/a.go"), say("説明")]
        self.assertEqual(self.run_hook(entries).get("decision"), "block")

    def test_ignores_turns_that_do_not_touch_focus_code(self):
        entries = [prompt(), call("Read", file_path="/repo/README.md"), call("Bash", command="cargo test"), say("ok")]
        self.assertEqual(self.run_hook(entries), {})

    def test_does_not_block_twice(self):
        entries = [prompt(), call("Read", file_path="/repo/a.go"), say("説明")]
        output = self.run_hook(entries, stop_hook_active=True)
        self.assertNotIn("decision", output)
        self.assertIn("判定の一行が無いまま", output.get("systemMessage", ""))

    def test_no_declaration_means_no_check(self):
        self.profile.write_text("## ユーザープロファイル\n\n- ミドルエンジニア\n", encoding="utf-8")
        entries = [prompt(), call("Read", file_path="/repo/a.go"), say("説明")]
        self.assertEqual(self.run_hook(entries), {})

    def test_unknown_declared_language_is_reported_not_silently_passed(self):
        self.profile.write_text("- 重点学習中: Haskell（初学者）\n", encoding="utf-8")
        entries = [prompt(), call("Read", file_path="/repo/a.hs"), say("説明")]
        output = self.run_hook(entries)
        self.assertNotIn("decision", output)
        self.assertIn("Haskell", output.get("systemMessage", ""))

    def test_unreadable_transcript_is_reported(self):
        env = dict(os.environ, CODE_LEARNING_PROFILE=str(self.profile))
        result = subprocess.run(
            [sys.executable, str(HOOK), "stop"],
            input=json.dumps({"transcript_path": str(self.base / "missing.jsonl")}),
            text=True, capture_output=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("確認していない", json.loads(result.stdout)["systemMessage"])

    def test_registered_as_stop_hook_in_settings_template(self):
        template = json.loads((REPO_ROOT / "settings.json.template").read_text(encoding="utf-8"))
        commands = [hook["command"] for group in template["hooks"]["Stop"] for hook in group["hooks"]]
        self.assertTrue(any("code-learning-check.py stop" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
