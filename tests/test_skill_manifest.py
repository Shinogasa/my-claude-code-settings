#!/usr/bin/env python3
"""skillのホスト別配布境界とCodex routing skillを検証する。"""
import json
import os
import re
import subprocess
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
    # submodule内を指すsymlinkは、未初期化で先が無くても配布単位として数える。
    return {
        path.name for path in root.iterdir()
        if (path.is_dir() or path.is_symlink()) and path.name != "synced"
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

    def test_dangling_skill_symlink_is_counted(self):
        """submoduleが未初期化でも、symlinkのskillを分類の対象に含める。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "learning-mode").mkdir()
            (root / "ext-skill").symlink_to("../missing-submodule/ext-skill")
            self.assertEqual(managed_skill_directories(root), {"learning-mode", "ext-skill"})

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
        self.assertIn("path = vendor/yomiyasu", gitmodules)
        self.assertIn("url = https://github.com/nanaism/yomiyasu.git", gitmodules)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertIn("yomiyasu", manifest["shared"])
        # v2でスキル本体が入れ子に移ったので、submoduleは skills/ の外に置き、本体をsymlinkで配る（ADR 0038）
        link = SKILLS_DIR / "yomiyasu"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), "../vendor/yomiyasu/skills/yomiyasu")
        self.assertTrue((link / "SKILL.md").is_file())


AWS_SUBMODULE = "agent-toolkit-for-aws"
AWS_SKILLS = (
    "aws-billing-and-cost-management", "aws-compute", "aws-containers", "aws-database",
    "aws-iam", "aws-networking", "aws-observability", "aws-security", "aws-serverless",
    "aws-storage", "aws-well-architected-review", "signing-in-to-aws",
)


def declared_submodule_paths(root=REPO_ROOT):
    text = (root / ".gitmodules").read_text(encoding="utf-8")
    return re.findall(r"^\s*path\s*=\s*(\S+)\s*$", text, flags=re.MULTILINE)


def unresolved_skill_links(skills_dir, root=REPO_ROOT):
    """初期化済みsubmoduleを指すのに、SKILL.mdへ解決できないskill symlinkの名前を返す。"""
    declared = declared_submodule_paths(root)
    base = os.path.relpath(skills_dir, root)
    unresolved = set()
    for link in skills_dir.iterdir():
        if not link.is_symlink():
            continue
        relative = os.path.normpath(os.path.join(base, os.readlink(link)))
        owners = [path for path in declared if relative.startswith(path + "/")]
        # 未初期化のsubmoduleは、新しい端末と同じ状態なので検査しない
        if owners and not (root / owners[0] / ".git").exists():
            continue
        if not (link / "SKILL.md").is_file():
            unresolved.add(link.name)
    return unresolved


class TestAwsSkillSubmodule(unittest.TestCase):
    """AWSスキルを上流submodule内へのsymlinkとして共有配布しているか。"""

    def test_submodule_is_declared(self):
        gitmodules = (REPO_ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertIn(f"path = {AWS_SUBMODULE}", gitmodules)
        self.assertIn("url = https://github.com/aws/agent-toolkit-for-aws.git", gitmodules)

    def test_selected_skills_are_relative_links_listed_as_shared(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for name in AWS_SKILLS:
            with self.subTest(name=name):
                link = SKILLS_DIR / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(
                    os.readlink(link), f"../{AWS_SUBMODULE}/skills/core-skills/{name}"
                )
                self.assertIn(name, manifest["shared"])

    def test_every_skill_symlink_points_into_declared_submodule(self):
        declared = declared_submodule_paths()
        for link in SKILLS_DIR.iterdir():
            if not link.is_symlink():
                continue
            with self.subTest(link=link.name):
                target = os.readlink(link)
                self.assertFalse(os.path.isabs(target))
                relative = os.path.normpath(os.path.join("skills", target))
                self.assertTrue(
                    any(relative == path or relative.startswith(path + "/") for path in declared),
                    relative,
                )

    def test_unresolved_links_cover_every_symlink_not_only_aws(self):
        """AWS_SKILLSに無いsymlinkでも、初期化済みsubmoduleで先を失えば検出する。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".gitmodules").write_text(
                '[submodule "ext"]\n\tpath = ext\n[submodule "uninit"]\n\tpath = uninit\n',
                encoding="utf-8",
            )
            (root / "ext" / "good").mkdir(parents=True)
            (root / "ext" / "good" / "SKILL.md").write_text("x\n", encoding="utf-8")
            (root / "ext" / ".git").write_text("gitdir: x\n", encoding="utf-8")
            skills = root / "skills"
            skills.mkdir()
            (skills / "good").symlink_to("../ext/good")
            (skills / "renamed").symlink_to("../ext/old-name")
            (skills / "not-yet").symlink_to("../uninit/skill")
            self.assertEqual(unresolved_skill_links(skills, root), {"renamed"})

    def test_links_resolve_to_skills_when_submodule_is_initialized(self):
        """上流で名前やパスが変わったら、ここで気づく。AWS_SKILLSに無いsymlinkも対象にする。"""
        self.assertEqual(unresolved_skill_links(SKILLS_DIR), set())


MATT_SUBMODULE = "mattpocock-skills"
MATT_SKILLS = {
    # grillingは推奨回答を外すためフォークした（ADR 0057）。TestGrillingForkで検査する
    # handoffは置き場所を変えるためフォークした（ADR 0054）。TestHandoffForkで検査する
    # retroは最初にwriting-for-agentsを呼ぶので、一緒に配る
    "retro": "skills/engineering/retro",
    "writing-for-agents": "skills/productivity/writing-for-agents",
}


class TestMattPocockSkillSubmodule(unittest.TestCase):
    """mattpocock/skillsの公式版を上流submodule内へのsymlinkとして共有配布しているか。"""

    def test_submodule_is_declared(self):
        gitmodules = (REPO_ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertIn(f"path = {MATT_SUBMODULE}", gitmodules)
        self.assertIn("url = https://github.com/mattpocock/skills.git", gitmodules)

    def test_selected_skills_are_relative_links_listed_as_shared(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for name, upstream in MATT_SKILLS.items():
            with self.subTest(name=name):
                link = SKILLS_DIR / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), f"../{MATT_SUBMODULE}/{upstream}")
                self.assertIn(name, manifest["shared"])

    def test_grill_me_is_not_distributed(self):
        """上流のgrill-meは「grillingを呼ぶ」だけの入口。/grillingで足りるので配らない。"""
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        link = SKILLS_DIR / "grill-me"
        self.assertFalse(link.is_symlink() or link.exists())
        for host in HOST_KEYS:
            self.assertNotIn("grill-me", manifest[host])


# フォークの元にした上流のファイルの blob ハッシュ（mattpocock-skills 4ae2317）
GRILLING_UPSTREAM_BLOBS = {
    "skills/productivity/grilling/SKILL.md": "d2f09a18e6a6c65c55f1271ba08dfeaf06f0bed3",
    "skills/productivity/grilling/agents/openai.yaml": "ddbdb96139c0c1dfe6bca698f39d0465674b8a39",
}


class TestGrillingFork(unittest.TestCase):
    """grillingは上流をフォークし、推奨回答を先に出さない（ADR 0057）。"""

    def setUp(self):
        self.skill_dir = SKILLS_DIR / "grilling"
        self.skill_md = self.skill_dir / "SKILL.md"

    def test_is_own_directory_listed_as_shared(self):
        # symlinkのままだと、submoduleを更新したときに推奨回答の指示が上流の版へ戻る
        self.assertFalse(self.skill_dir.is_symlink())
        self.assertTrue(self.skill_md.is_file())
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertIn("grilling", manifest["shared"])

    def test_keeps_upstream_frontmatter_and_codex_metadata(self):
        text = self.skill_md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: grilling\n"))
        openai = (self.skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "Grilling"', openai)

    def test_asks_without_recommended_answer(self):
        # 推奨を先に出すと、ユーザーは承認だけを返しやすい（2026-11-19 の観測で defer の発生源だった）
        text = self.skill_md.read_text(encoding="utf-8")
        self.assertNotIn("➡️", text)
        self.assertNotIn("recommended answer", text)
        self.assertNotIn('"yes" accepts', text)

    def test_gives_own_view_after_user_answers(self):
        text = self.skill_md.read_text(encoding="utf-8")
        self.assertIn("after the user answers", text)

    def test_upstream_unchanged_since_fork(self):
        # フォークには上流の更新が自動で入らない。submoduleを進めて上流が変わったら、ここで落とす。
        # 差分を読んで取り込んだら、下のハッシュを新しい上流の値に更新する
        for upstream_path, expected in GRILLING_UPSTREAM_BLOBS.items():
            with self.subTest(path=upstream_path):
                result = subprocess.run(
                    ["git", "-C", MATT_SUBMODULE, "rev-parse", f"HEAD:{upstream_path}"],
                    cwd=REPO_ROOT, capture_output=True, text=True,
                )
                # 確かめられないときも、通さずに落とす
                self.assertEqual(result.returncode, 0, f"上流を読めなかった: {result.stderr.strip()}")
                self.assertEqual(
                    result.stdout.strip(), expected,
                    f"上流の {upstream_path} がフォークの元（4ae2317）から変わった。"
                    "差分を読んで skills/grilling に取り込み、ハッシュを更新する（ADR 0057）",
                )


class TestHandoffFork(unittest.TestCase):
    """handoffは上流をフォークし、引き継ぎ資料を作業repoのgit対象外の場所に置く（ADR 0054）。"""

    def setUp(self):
        self.skill_dir = SKILLS_DIR / "handoff"
        self.skill_md = self.skill_dir / "SKILL.md"

    def test_is_own_directory_listed_as_shared(self):
        # symlinkのままだと、submoduleを更新したときに置き場所の指示が上流の版へ戻る
        self.assertFalse(self.skill_dir.is_symlink())
        self.assertTrue(self.skill_md.is_file())
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertIn("handoff", manifest["shared"])

    def test_keeps_upstream_frontmatter_and_codex_metadata(self):
        text = self.skill_md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: handoff\n"))
        self.assertIn("disable-model-invocation: true", text)
        openai = (self.skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("allow_implicit_invocation: false", openai)

    def test_saves_into_ignored_tasks_handoff_of_working_repo(self):
        text = self.skill_md.read_text(encoding="utf-8")
        # ホストの一時ディレクトリはdevcontainerから見えず、再起動でも消える
        self.assertNotIn("$TMPDIR", text)
        self.assertNotIn("/tmp", text)
        self.assertIn("tasks/handoff/", text)
        self.assertIn("git check-ignore", text)

    def test_offers_to_exclude_once_when_not_ignored(self):
        # 毎回置き場所を聞かれないよう、了承を得て info/exclude に足す（ADR 0051 の worktree と同じ形）
        text = self.skill_md.read_text(encoding="utf-8")
        self.assertIn("git rev-parse --git-path info/exclude", text)
        self.assertIn("/tasks/handoff/", text)

    def test_this_repository_ignores_tasks_handoff(self):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "tasks/handoff/example.md"],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
