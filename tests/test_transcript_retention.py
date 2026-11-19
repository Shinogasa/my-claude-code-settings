#!/usr/bin/env python3
"""セッションログの保持期間（cleanupPeriodDays）を検証する。

既定の30日では、職務経歴書や振り返りの材料になる過去のセッションが黙って消える。
1年残し、年1回の棚卸しで見返す（ADR 0055）。

実行: python3 -m unittest tests.test_transcript_retention
"""
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((REPO_ROOT / "settings.json.template").read_text(encoding="utf-8"))


class TranscriptRetentionTests(unittest.TestCase):
    def test_keeps_transcripts_for_one_year(self):
        self.assertEqual(SETTINGS.get("cleanupPeriodDays"), 365)


if __name__ == "__main__":
    unittest.main()
