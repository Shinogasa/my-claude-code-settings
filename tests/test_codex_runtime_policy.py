#!/usr/bin/env python3
"""Codex runtime enforcement の契約を検証する。"""
import json
import os
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "inject-superpowers.sh"
HOOKS_CONFIG = REPO_ROOT / "codex" / "hooks.json"
SECURITY_POLICY = REPO_ROOT / "rules" / "security-review-policy.md"
EXPECTED_CONTEXT = (
    "Before responding, read and follow superpowers:using-superpowers "
    "from the enabled Codex plugin."
)
SESSION_SOURCES = ("startup", "resume", "clear", "compact")
INVALID_JSON_DIAGNOSTIC = "inject-superpowers: invalid JSON\n"


def run_hook(payload: str) -> subprocess.CompletedProcess:
    """hookへ文字列payloadを渡し、結果を返す。"""
    return subprocess.run(
        [str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


class TestSuperpowersSessionStartHook(unittest.TestCase):
    """SessionStart hook の入出力契約。"""

    def test_emits_plain_text_context_for_every_session_source(self):
        self.assertTrue(
            os.access(HOOK, os.X_OK),
            "Codexのcommand配線から直接起動するため、hookには実行権限が必要",
        )
        for source in SESSION_SOURCES:
            with self.subTest(source=source):
                payload = json.dumps(
                    {"hook_event_name": "SessionStart", "source": source}
                )
                result = run_hook(payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, EXPECTED_CONTEXT + "\n")
                self.assertEqual(result.stderr, "")

    def test_rejects_invalid_json_with_diagnostic(self):
        result = run_hook("not-json")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, INVALID_JSON_DIAGNOSTIC)
        self.assertNotIn("Traceback", result.stderr)

    def test_rejects_malformed_session_start_sources_with_stable_diagnostics(self):
        cases = (
            (
                "missing source",
                {"hook_event_name": "SessionStart"},
                "inject-superpowers: missing SessionStart source\n",
            ),
            (
                "unsupported source",
                {"hook_event_name": "SessionStart", "source": "other"},
                "inject-superpowers: unsupported SessionStart source\n",
            ),
            (
                "non-object JSON",
                [],
                "inject-superpowers: expected JSON object\n",
            ),
            (
                "non-string source",
                {"hook_event_name": "SessionStart", "source": []},
                "inject-superpowers: SessionStart source must be a string\n",
            ),
        )
        for name, payload, diagnostic in cases:
            with self.subTest(case=name):
                result = run_hook(json.dumps(payload))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, diagnostic)
                self.assertNotIn("Traceback", result.stderr)

    def test_rejects_non_session_start_payload_with_diagnostic(self):
        payload = json.dumps(
            {"hook_event_name": "UserPromptSubmit", "source": "startup"}
        )
        result = run_hook(payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr,
            "inject-superpowers: expected SessionStart payload\n",
        )
        self.assertNotIn("Traceback", result.stderr)


class TestCodexSessionStartWiring(unittest.TestCase):
    """Codex hooks.json のSessionStart配線契約。"""

    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))
        cls.raw = HOOKS_CONFIG.read_text(encoding="utf-8")

    def test_superpowers_hook_shares_the_parallel_detection_matcher_group(self):
        groups = self.config["hooks"]["SessionStart"]
        matching = [
            group
            for group in groups
            if any(
                "detect-parallel-sessions.sh" in hook.get("command", "")
                for hook in group.get("hooks", [])
            )
        ]
        self.assertEqual(len(matching), 1)
        group = matching[0]
        self.assertEqual(group.get("matcher"), "startup|resume|clear|compact")
        commands = [hook.get("command") for hook in group.get("hooks", [])]
        self.assertIn('"$HOME/.codex/hooks/inject-superpowers.sh"', commands)

    def test_session_start_handlers_are_synchronous(self):
        for group in self.config["hooks"]["SessionStart"]:
            for hook in group.get("hooks", []):
                with self.subTest(command=hook.get("command")):
                    self.assertIsNot(hook.get("async"), True)

    def test_does_not_use_claude_specific_async_rewake(self):
        self.assertNotIn("asyncRewake", self.raw)


class TestSecurityReviewPolicy(unittest.TestCase):
    """意味レビューをセキュリティ境界だけへ限定するルール契約。"""

    @classmethod
    def setUpClass(cls):
        cls.text = SECURITY_POLICY.read_text(encoding="utf-8")

    def test_has_no_paths_frontmatter(self):
        self.assertFalse(self.text.startswith("---\n"))

    def test_defines_every_security_boundary(self):
        for boundary in (
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
        ):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, self.text)

    def test_limits_llm_review_and_requires_human_escalation(self):
        self.assertIn(
            "上記の security boundary に一致する変更だけ、完了前に `security-reviewer` による\n"
            "意味レビューを必須とする。",
            self.text,
        )
        self.assertIn(
            "ordinary changes では自動LLM security reviewを起動してはいけない。",
            self.text,
        )
        self.assertIn(
            "`security-reviewer` が Critical findings または `Confidence: insufficient` を報告した場合は、\n"
            "結果を人間へ提示して確認を得る。強いモデルを使う追加レビューは、人間の確認前に\n"
            "自動でspawnしてはいけない。",
            self.text,
        )
        self.assertIn(
            "`security-reviewer` は軽量モデルによる意味レビューであり、静的解析、テスト、secret scan、\n"
            "依存関係監査などの決定的検査を置き換えない。",
            self.text,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
