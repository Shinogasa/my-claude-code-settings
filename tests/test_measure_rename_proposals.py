#!/usr/bin/env python3
"""bin/measure-rename-proposals.py を検証する。

実行: python3 -m unittest tests.test_measure_rename_proposals
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "measure-rename-proposals.py"


def call(name, at, **tool_input):
    return {"type": "assistant", "timestamp": at,
            "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]}}


def say(text, at):
    return {"type": "assistant", "timestamp": at, "message": {"content": [{"type": "text", "text": text}]}}


class MeasureRenameProposalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "proj").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, name, entries):
        path = self.root / "proj" / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")

    def run_script(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_counts_sessions_and_proposals_per_month(self):
        self.session("a", [call("Bash", "2026-11-02T00:00:00Z", command="git switch -c feat/a"),
                           say("`/rename 作業 (feat/a)` を提案するね", "2026-11-02T00:01:00Z")])
        self.session("b", [call("EnterWorktree", "2026-11-03T00:00:00Z", name="b")])
        self.session("c", [call("Bash", "2026-10-20T00:00:00Z", command="git checkout -b fix/c")])
        self.session("d", [call("Bash", "2026-11-04T00:00:00Z", command="git switch main"),
                           say("/rename の話", "2026-11-04T00:01:00Z")])
        output = self.run_script()
        self.assertIn("2026-10 1 0", output)
        self.assertIn("2026-11 2 1", output)
        self.assertIn("読めなかったファイル 0", output)

    def test_rename_before_branch_creation_is_not_counted(self):
        self.session("a", [say("/rename の話", "2026-11-02T00:00:00Z"),
                           call("Bash", "2026-11-02T00:01:00Z", command="git switch -c feat/a")])
        self.assertIn("2026-11 1 0", self.run_script())

    def test_fails_loudly_when_root_has_no_transcripts(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)],
                                text=True, capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("会話記録", result.stderr)


if __name__ == "__main__":
    unittest.main()
