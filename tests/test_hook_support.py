#!/usr/bin/env python3
"""hooks/hook_support.py の会話記録の読み取りと出力の組み立てを検証する。

実行: python3 -m unittest tests.test_hook_support
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))

import hook_support  # noqa: E402

COMPACT = {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"}


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_result():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}


def call(name, **tool_input):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]}}


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *entries, raw_lines=()):
        with self.path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            for line in raw_lines:
                handle.write(line + "\n")

    def test_skips_broken_lines_and_reads_the_rest(self):
        self.write(prompt("a"), raw_lines=["{broken"])
        self.assertEqual(hook_support.read_entries(str(self.path)), [prompt("a")])

    def test_line_separator_inside_json_does_not_split_the_line(self):
        self.write(prompt("前 後"))
        self.assertEqual(hook_support.read_entries(str(self.path)), [prompt("前 後")])

    def test_raises_when_no_line_can_be_read(self):
        self.write(raw_lines=["not json", "{also broken"])
        with self.assertRaises(hook_support.TranscriptError):
            hook_support.read_entries(str(self.path))

    def test_raises_when_path_is_missing(self):
        with self.assertRaises(hook_support.TranscriptError):
            hook_support.read_entries(None)
        with self.assertRaises(hook_support.TranscriptError):
            hook_support.read_entries(str(self.path))

    def test_reads_only_after_offset(self):
        self.write(prompt("before"))
        offset = self.path.stat().st_size
        self.write(prompt("after"))
        self.assertEqual(hook_support.read_entries(str(self.path), offset), [prompt("after")])

    def test_empty_slice_after_offset_is_not_an_error(self):
        self.write(prompt("only"))
        self.assertEqual(hook_support.read_entries(str(self.path), self.path.stat().st_size), [])

    def test_after_last_compact(self):
        entries = [prompt("old"), COMPACT, prompt("mid"), COMPACT, prompt("new")]
        self.assertEqual(hook_support.after_last_compact(entries), [prompt("new")])
        self.assertEqual(hook_support.after_last_compact([prompt("x")]), [prompt("x")])

    def test_human_prompt_excludes_tool_results_and_meta(self):
        self.assertTrue(hook_support.is_human_prompt(prompt("hi")))
        self.assertTrue(hook_support.is_human_prompt(
            {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}))
        self.assertFalse(hook_support.is_human_prompt(tool_result()))
        self.assertFalse(hook_support.is_human_prompt({**prompt("x"), "isMeta": True}))
        self.assertFalse(hook_support.is_human_prompt(call("Read", file_path="/a")))

    def test_since_last_prompt(self):
        entries = [prompt("1"), call("Skill", skill="x"), prompt("2"), call("Read", file_path="/a"), tool_result()]
        self.assertEqual(hook_support.since_last_prompt(entries), entries[3:])

    def test_tool_uses_in_order(self):
        entries = [call("Skill", skill="yomiyasu"), prompt("x"), call("Read", file_path="/a")]
        self.assertEqual(hook_support.tool_uses(entries),
                         [("Skill", {"skill": "yomiyasu"}), ("Read", {"file_path": "/a"})])


class OutputTests(unittest.TestCase):
    def test_emit_prints_json_and_skips_empty(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            hook_support.emit({})
            hook_support.emit({"systemMessage": "日本語"})
        self.assertEqual(buffer.getvalue().strip(), json.dumps({"systemMessage": "日本語"}, ensure_ascii=False))

    def test_with_messages_joins_lines(self):
        self.assertEqual(hook_support.with_messages({}, []), {})
        self.assertEqual(hook_support.with_messages({"decision": "block"}, ["a", "b"]),
                         {"decision": "block", "systemMessage": "a\nb"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
