#!/usr/bin/env python3
"""skillのホスト別配布境界とCodex routing skillを検証する。"""
import json
import re
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "manifests" / "skills.json"
SKILLS_DIR = REPO_ROOT / "skills"
ROUTING_SKILL = SKILLS_DIR / "codex-cli-best-practice" / "SKILL.md"
HOST_KEYS = ("shared", "claude", "codex")


def managed_skill_directories(root):
    """リポジトリが配布するskill directoryを収集する。"""
    # syncedは外部同期が所有するコンテナであり、manifestの配布単位ではない。
    return {
        path.name for path in root.iterdir()
        if path.is_dir() and path.name != "synced"
    }


def assert_complete_classification(classified, actual):
    """未分類と消失を同じ集合比較で検出する。"""
    if classified != actual:
        raise AssertionError(f"skill分類が不完全: classified={classified}, actual={actual}")


def parse_frontmatter(text):
    """外部YAML依存なしで単純なname/description frontmatterを読む。"""
    if not text.startswith("---\n"):
        raise AssertionError("YAML frontmatterが先頭にない")
    try:
        raw, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise AssertionError("YAML frontmatterが閉じていない") from exc

    fields = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise AssertionError(f"不正なfrontmatter行: {line!r}")
        if key.strip() in fields:
            raise AssertionError(f"frontmatterキーが重複: {key.strip()!r}")
        fields[key.strip()] = value.strip()
    return fields, body


class TestSkillManifest(unittest.TestCase):
    """全skill directoryが重複なく1つの配布先へ分類されるか。"""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.skill_dirs = managed_skill_directories(SKILLS_DIR)

    def test_schema_version_is_one(self):
        self.assertEqual(self.manifest["schemaVersion"], 1)

    def test_manifest_keys_are_exact(self):
        self.assertEqual(
            set(self.manifest), {"schemaVersion", "shared", "claude", "codex"}
        )

    def test_host_entries_have_no_duplicates(self):
        entries = [entry for key in HOST_KEYS for entry in self.manifest[key]]
        self.assertEqual(len(entries), len(set(entries)))

    def test_host_entries_are_pairwise_disjoint(self):
        groups = {key: set(self.manifest[key]) for key in HOST_KEYS}
        for index, left in enumerate(HOST_KEYS):
            for right in HOST_KEYS[index + 1:]:
                with self.subTest(left=left, right=right):
                    self.assertTrue(groups[left].isdisjoint(groups[right]))

    def test_union_exactly_matches_skill_directories(self):
        classified = set().union(*(self.manifest[key] for key in HOST_KEYS))
        assert_complete_classification(classified, self.skill_dirs)

    def test_unclassified_directory_fails_the_same_invariant(self):
        classified = set().union(*(self.manifest[key] for key in HOST_KEYS))
        with self.assertRaises(AssertionError):
            assert_complete_classification(
                classified, self.skill_dirs | {"unclassified-skill"}
            )

    def test_external_sync_container_is_excluded_but_unclassified_skill_is_detected(self):
        """外部同期コンテナを配布せず、通常skillの分類漏れは検出する。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("learning-mode", "synced", "unclassified-skill"):
                (root / name).mkdir()
            actual = managed_skill_directories(root)
            self.assertEqual(actual, {"learning-mode", "unclassified-skill"})
            with self.assertRaises(AssertionError):
                assert_complete_classification({"learning-mode"}, actual)

    def test_host_specific_entries_are_fixed(self):
        self.assertEqual(self.manifest["claude"], ["claude-code-best-practice", "work-principles"])
        self.assertEqual(self.manifest["codex"], ["codex-cli-best-practice"])

    def test_shared_entries_are_sorted(self):
        """件数が増えても、sharedの並び順を保つ。完全性は集合比較で検査する。"""
        shared = self.manifest["shared"]
        self.assertEqual(shared, sorted(shared))


class TestCodexRoutingSkill(unittest.TestCase):
    """Codex設定調査の根拠順と対象領域を固定する。"""

    @classmethod
    def setUpClass(cls):
        cls.text = ROUTING_SKILL.read_text(encoding="utf-8")
        cls.frontmatter, cls.body = parse_frontmatter(cls.text)

    def test_frontmatter_has_valid_name_and_description(self):
        self.assertEqual(set(self.frontmatter), {"name", "description"})
        self.assertEqual(self.frontmatter["name"], "codex-cli-best-practice")
        self.assertRegex(self.frontmatter["name"], r"^[a-z0-9-]{1,64}$")
        self.assertTrue(self.frontmatter["description"].startswith("Use when"))
        self.assertTrue(self.body.strip())

    def test_explicitly_covers_codex_configuration_surfaces(self):
        for topic in (
            "AGENTS.md",
            "skills",
            "agents",
            "hooks",
            "plugins",
            "MCP",
            "rules",
            "config.toml",
            "proving-absence",
        ):
            with self.subTest(topic=topic):
                self.assertIn(topic, self.text)

    def test_evidence_order_is_official_local_pinned_submodule(self):
        markers = (
            "OpenAI公式ドキュメント",
            "ローカルにインストールされたCLIのヘルプと実測",
            "固定したcodex-cli-best-practice submodule",
        )
        positions = [self.body.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

    def test_pinned_submodule_is_supplementary_only(self):
        self.assertIn("補助資料", self.body)
        self.assertIn("上書きしてはならない", self.body)


class TestExternalSkillSubmodule(unittest.TestCase):
    """外部のyomiyasuをcommit固定のsubmoduleとして共有配布しているか。"""

    def test_yomiyasu_is_declared_submodule_listed_as_shared(self):
        gitmodules = (REPO_ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertIn("path = skills/yomiyasu", gitmodules)
        self.assertIn("url = https://github.com/nanaism/yomiyasu.git", gitmodules)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertIn("yomiyasu", manifest["shared"])
        self.assertTrue((SKILLS_DIR / "yomiyasu" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
