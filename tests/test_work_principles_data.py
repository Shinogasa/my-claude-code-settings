#!/usr/bin/env python3
"""skills/work-principles/principles.json（生成物）の形を検証する。正本の無い環境でも走る。

実行: python3 -m unittest tests.test_work_principles_data
"""
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "skills" / "work-principles" / "principles.json"
REQUIRED = {"id", "principle", "scenes", "checkpoints", "not_applicable", "source_url", "theme"}
ALLOWED = REQUIRED | {"review_question"}
CHECKPOINTS = {"spec", "plan", "advice"}


class PrinciplesDataTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(DATA.read_text(encoding="utf-8"))

    def test_generated_note_is_present(self):
        self.assertIn("直接編集しない", self.data["_generated"])

    def test_principles_have_only_public_fields(self):
        for item in self.data["principles"]:
            with self.subTest(item["id"]):
                self.assertTrue(REQUIRED <= set(item), set(item))
                self.assertTrue(set(item) <= ALLOWED, set(item) - ALLOWED)

    def test_review_question_exists_for_spec_and_plan(self):
        for item in self.data["principles"]:
            with self.subTest(item["id"]):
                self.assertTrue(set(item["checkpoints"]) <= CHECKPOINTS)
                if {"spec", "plan"} & set(item["checkpoints"]):
                    self.assertTrue(item.get("review_question"))

    def test_ids_are_unique_sorted_and_indexed_by_themes(self):
        ids = [item["id"] for item in self.data["principles"]]
        self.assertEqual(ids, sorted(set(ids)))
        themed = {pid for theme in self.data["themes"] for pid in theme["ids"]}
        self.assertEqual(themed, set(ids))
        for pid in ids:
            self.assertRegex(pid, r"^P\d{2}[a-z]$")

    def test_source_is_a_youtube_url(self):
        for item in self.data["principles"]:
            self.assertRegex(item["source_url"], r"^https://youtu\.be/[A-Za-z0-9_-]{11}\?t=\d+$")


if __name__ == "__main__":
    unittest.main()
