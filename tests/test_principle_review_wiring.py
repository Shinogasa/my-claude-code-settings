#!/usr/bin/env python3
"""原則レビューのフックの、settings.json.template への配線を検証する。

実行: python3 -m unittest tests.test_principle_review_wiring
"""
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMAND = "python3 ~/.claude/hooks/principle-review.py"


class WiringTests(unittest.TestCase):
    def test_registered_on_bash_pre_tool_use(self):
        settings = json.loads((REPO_ROOT / "settings.json.template").read_text(encoding="utf-8"))
        bash = [entry for entry in settings["hooks"]["PreToolUse"] if entry["matcher"] == "Bash"]
        hooks = [hook for entry in bash for hook in entry["hooks"]]
        self.assertIn(COMMAND, [hook["command"] for hook in hooks])
        # gitを最大3回×10秒呼ぶので、guardと同じ30秒を確保する
        self.assertEqual([hook["timeout"] for hook in hooks if hook["command"] == COMMAND], [30])


if __name__ == "__main__":
    unittest.main()
