#!/usr/bin/env python3
"""bin/persona が、personas/ の版を rules/persona.md へ書き写して切り替えることを検証する。

実行: python3 -m unittest tests.test_persona_switch
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "persona"

CASUAL = "# casual\n\nタメ口で話す。\n"
POLITE = "# polite\n\n丁寧語で話す。\n"


class PersonaSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / "repository"
        (self.repo / "bin").mkdir(parents=True)
        (self.repo / "personas").mkdir()
        (self.repo / "rules").mkdir()
        shutil.copy2(SCRIPT, self.repo / "bin" / "persona")
        (self.repo / "personas" / "casual.md").write_text(CASUAL, encoding="utf-8")
        (self.repo / "personas" / "polite.md").write_text(POLITE, encoding="utf-8")
        self.active = self.repo / "rules" / "persona.md"

    def run_persona(self, *args, script=None):
        return subprocess.run(
            [str(script or self.repo / "bin" / "persona"), *args],
            capture_output=True, text=True, check=False,
        )

    def test_switch_copies_the_chosen_persona(self):
        result = self.run_persona("polite")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.active.read_text(encoding="utf-8"), POLITE)
        # シンボリックリンクにすると、プロジェクト外を指すruleをClaude Codeが読まない
        self.assertFalse(self.active.is_symlink())

    def test_switch_replaces_an_unedited_persona(self):
        self.active.write_text(CASUAL, encoding="utf-8")
        result = self.run_persona("polite")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.active.read_text(encoding="utf-8"), POLITE)

    def test_switch_leaves_no_temporary_file_in_rules(self):
        self.run_persona("polite")
        self.assertEqual(sorted(p.name for p in (self.repo / "rules").iterdir()), ["persona.md"])

    def test_without_arguments_shows_the_current_persona(self):
        self.active.write_text(POLITE, encoding="utf-8")
        result = self.run_persona()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("polite", result.stdout)
        self.assertIn("casual", result.stdout)  # 候補も見せる

    def test_without_arguments_fails_when_no_persona_is_active(self):
        result = self.run_persona()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rules/persona.md", result.stderr)

    def test_unknown_name_fails_without_change(self):
        self.active.write_text(CASUAL, encoding="utf-8")
        result = self.run_persona("tsundere")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("casual", result.stderr)
        self.assertEqual(self.active.read_text(encoding="utf-8"), CASUAL)

    def test_name_with_path_is_rejected(self):
        (self.base / "outside.md").write_text("外のファイル\n", encoding="utf-8")
        result = self.run_persona("../../outside")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.active.exists())

    def test_refuses_to_overwrite_a_hand_edited_persona(self):
        edited = CASUAL + "\n手で足した行\n"
        self.active.write_text(edited, encoding="utf-8")
        result = self.run_persona("polite")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("personas/", result.stderr)
        self.assertEqual(self.active.read_text(encoding="utf-8"), edited)

    def test_ensure_creates_the_default_when_missing(self):
        result = self.run_persona("--ensure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.active.read_text(encoding="utf-8"), CASUAL)

    def test_ensure_keeps_an_existing_persona(self):
        edited = POLITE + "\n手で足した行\n"
        self.active.write_text(edited, encoding="utf-8")
        result = self.run_persona("--ensure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.active.read_text(encoding="utf-8"), edited)

    def test_works_through_a_symlinked_bin_directory(self):
        # ~/.claude/bin と ~/.codex/bin はリポジトリの bin/ へのシンボリックリンク
        linked_bin = self.base / "home" / ".claude" / "bin"
        linked_bin.parent.mkdir(parents=True)
        linked_bin.symlink_to(self.repo / "bin")
        result = self.run_persona("polite", script=linked_bin / "persona")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.active.read_text(encoding="utf-8"), POLITE)


class RepositoryPersonaTests(unittest.TestCase):
    """リポジトリに置く版と、追跡しない生成物の境界。"""

    def test_both_personas_exist(self):
        for name in ("casual", "polite"):
            with self.subTest(name=name):
                self.assertTrue((REPO_ROOT / "personas" / f"{name}.md").is_file())

    def test_active_persona_is_not_tracked(self):
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "rules/persona.md"],
            check=False,
        )
        self.assertEqual(result.returncode, 0, "rules/persona.md が .gitignore で無視されていない")


if __name__ == "__main__":
    unittest.main()
