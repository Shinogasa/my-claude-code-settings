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
SECURITY_REVIEWER_SOURCE = REPO_ROOT / "agents" / "security-reviewer.md"
SECURITY_POLICY = REPO_ROOT / "rules" / "security-review-policy.md"

_spec = importlib.util.spec_from_file_location("codex_agents", GENERATOR)
codex_agents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(codex_agents)

# Codex が必須とするフィールド (→ https://developers.openai.com/codex/subagents)
REQUIRED_FIELDS = ("name", "description", "developer_instructions")
VALID_SANDBOX = {"read-only", "workspace-write"}
VALID_REASONING_EFFORTS = {"low", "medium", "high", "max"}
EXPECTED_PROFILES = {
    "build-error-resolver": ("gpt-5.6-luna", "low"),
    "code-architect": ("gpt-5.6-luna", "high"),
    "code-explorer": ("gpt-5.6-luna", "medium"),
    "code-simplifier": ("gpt-5.6-luna", "medium"),
    "planner": ("gpt-5.6-sol", "high"),
    "refactor-cleaner": ("gpt-5.6-luna", "high"),
    "security-reviewer": ("gpt-5.6-terra", "high"),
    "silent-failure-hunter": ("gpt-5.6-luna", "high"),
}
EXPECTED_SECURITY_BOUNDARIES = {
    "authentication",
    "authorization",
    "user input",
    "API endpoints",
    "file uploads",
    "secrets",
    "payments",
    "raw SQL",
    "cryptography",
    "external integrations",
    "permissions",
    "deployment settings",
}


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
        known = {profile[0] for profile in codex_agents.CODEX_AGENT_PROFILES.values()}
        for name, data in self.agents.items():
            if "model" in data:
                with self.subTest(agent=name):
                    self.assertIn(data["model"], known)

    def test_every_agent_has_an_explicit_model_reasoning_pair(self):
        self.assertEqual(set(self.agents), set(EXPECTED_PROFILES))
        for name, data in self.agents.items():
            with self.subTest(agent=name):
                self.assertEqual(
                    (data.get("model"), data.get("model_reasoning_effort")),
                    EXPECTED_PROFILES[name],
                )
                self.assertIn(data["model_reasoning_effort"], VALID_REASONING_EFFORTS)

    def test_every_agent_fails_closed_on_invalid_cross_model_handoff(self):
        for name, data in self.agents.items():
            with self.subTest(agent=name):
                instructions = data["developer_instructions"]
                self.assertIn("validate-codex-handoff.py validate", instructions)
                self.assertIn("最初の操作", instructions)
                self.assertIn("全文を読む", instructions)
                self.assertIn("INPUT_DIGEST", instructions)
                self.assertIn("validate-codex-handoff.py read", instructions)
                self.assertIn("--expected-input-digest", instructions)
                self.assertIn("pathから直接読まない", instructions)
                self.assertIn("NEEDS_CONTEXT", instructions)
                self.assertIn(data["model"], instructions)
                self.assertIn(data["model_reasoning_effort"], instructions)


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

    def test_security_reviewer_uses_official_semantic_review_profile(self):
        path = codex_agents.OUTPUT_DIR / "security-reviewer.toml"
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            (data["model"], data["model_reasoning_effort"]),
            ("gpt-5.6-terra", "high"),
        )
        self.assertEqual(data["sandbox_mode"], "read-only")


class TestSecurityReviewerContract(unittest.TestCase):
    """security-reviewerがpolicyの発火境界とread-only契約を守るか。"""

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.body = codex_agents.parse_frontmatter(
            SECURITY_REVIEWER_SOURCE.read_text(encoding="utf-8")
        )
        cls.policy = SECURITY_POLICY.read_text(encoding="utf-8")

    def test_description_covers_every_policy_security_boundary(self):
        section = self.policy.split("## security boundary", 1)[1].split("\n## ", 1)[0]
        policy_boundaries = {
            line.removeprefix("- ").split("（", 1)[0].strip()
            for line in section.splitlines()
            if line.startswith("- ")
        }
        self.assertEqual(policy_boundaries, EXPECTED_SECURITY_BOUNDARIES)
        for boundary in policy_boundaries:
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, self.meta["description"])
        self.assertNotIn("before major releases", self.body)

    def test_claude_agent_is_read_only_by_tools_and_permission_mode(self):
        tools = set(codex_agents.parse_tools(self.meta["tools"]))
        self.assertEqual(tools, {"Read", "Grep", "Glob"})
        self.assertTrue({"Write", "Edit", "Bash"}.isdisjoint(tools))
        self.assertEqual(self.meta.get("permissionMode"), "plan")

    def test_reviewer_does_not_run_deterministic_checks(self):
        self.assertNotIn("npm audit", self.body)
        self.assertNotIn("npx", self.body)
        self.assertNotRegex(self.body, r"\bRun\b")
        self.assertIn("Do not run commands", self.body)
        self.assertIn(
            "deterministic check results provided by the parent",
            self.body,
        )

    def test_output_contract_requires_findings_and_confidence(self):
        self.assertIn("## Output Contract", self.body)
        self.assertIn("`Severity: Critical|High|Medium|Low`", self.body)
        self.assertIn("`Confidence: sufficient`", self.body)
        self.assertIn("`Confidence: insufficient`", self.body)
        self.assertIn("List each missing piece of evidence", self.body)
        self.assertIn("Do not conclude that there are no issues", self.body)

    def test_escalation_contract_matches_policy(self):
        for trigger in ("Critical findings", "`Confidence: insufficient`"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, self.policy)
        self.assertIn(
            "If any Critical finding exists or `Confidence: insufficient`, "
            "do not spawn a stronger model.",
            self.body,
        )
        self.assertIn("`Human confirmation required: yes`", self.body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
