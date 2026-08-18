#!/usr/bin/env python3
"""codex/agents/*.toml が agents/*.md と一致していることを検証する。

Markdown と TOML は形式が違うためリンクで共有できず、生成物を commit している。
生成物を commit する構成の失敗モードは「片方だけ更新して静かに乖離する」ことなので、
再生成した結果と一致するかを検査する。

実行: python3 tests/test_codex_agents.py
"""
import importlib.util
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "bin" / "generate-codex-agents.py"

_spec = importlib.util.spec_from_file_location("codex_agents", GENERATOR)
codex_agents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(codex_agents)

# Codex が必須とするフィールド (→ https://developers.openai.com/codex/subagents)
REQUIRED_FIELDS = ("name", "description", "developer_instructions")
VALID_SANDBOX = {"read-only", "workspace-write"}


class TestGeneratedFilesAreCurrent(unittest.TestCase):
    """commit 済みの TOML が、今の Markdown から再生成した結果と一致するか。"""

    def test_no_drift(self):
        for path, expected in codex_agents.generate().items():
            with self.subTest(agent=path.stem):
                self.assertTrue(path.exists(), f"{path.name} が生成されていない")
                self.assertEqual(
                    path.read_text(encoding="utf-8"), expected,
                    f"{path.name} が古い。python3 bin/generate-codex-agents.py を実行すること")

    def test_no_orphan_toml(self):
        # 元の Markdown が消えたのに TOML が残ると、存在しないエージェントを配ることになる
        generated = {p.name for p in codex_agents.generate()}
        on_disk = {p.name for p in codex_agents.OUTPUT_DIR.glob("*.toml")}
        self.assertEqual(on_disk - generated, set())


class TestSchema(unittest.TestCase):
    """生成物が Codex のスキーマを満たすか。"""

    def setUp(self):
        self.agents = {
            p.stem: tomllib.loads(p.read_text(encoding="utf-8"))
            for p in codex_agents.OUTPUT_DIR.glob("*.toml")
        }
        self.assertTrue(self.agents, "TOML が1件も無い")

    def test_required_fields_present(self):
        for name, data in self.agents.items():
            for field in REQUIRED_FIELDS:
                with self.subTest(agent=name, field=field):
                    self.assertIn(field, data)
                    self.assertTrue(data[field].strip())

    def test_sandbox_mode_is_valid(self):
        for name, data in self.agents.items():
            with self.subTest(agent=name):
                self.assertIn(data.get("sandbox_mode"), VALID_SANDBOX)

    def test_model_is_a_known_generation(self):
        # Codex にモデルの別名は無いため、世代名を直接書いている。
        # 表に無い値が混ざると spawn 時に落ちる。
        known = set(codex_agents.MODEL_MAP.values())
        for name, data in self.agents.items():
            if "model" in data:
                with self.subTest(agent=name):
                    self.assertIn(data["model"], known)


class TestPermissionMapping(unittest.TestCase):
    """ツール一覧 → sandbox_mode の写像が権限を広げていないか。

    Codex にはツール単位の制限が無く2値でしか表現できない。粗い写像なので、
    「読み取り専用のつもりが書き込み可になっている」方向の誤りだけは潰す。
    """

    def test_read_only_agents_stay_read_only(self):
        for source in sorted(codex_agents.SOURCE_DIR.glob("*.md")):
            meta, _ = codex_agents.parse_frontmatter(source.read_text(encoding="utf-8"))
            tools = set(codex_agents.parse_tools(meta.get("tools", "")))
            if codex_agents.WRITE_TOOLS & tools:
                continue
            path = codex_agents.OUTPUT_DIR / f"{meta['name']}.toml"
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            with self.subTest(agent=meta["name"]):
                self.assertEqual(data["sandbox_mode"], "read-only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
