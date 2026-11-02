#!/usr/bin/env python3
"""hooks/guard-confluence-markdown.py の振る舞いと、settings.json.template への配線を検証する。

既存の Confluence ページを Markdown で全文置き換えすると、マクロ（info パネル、目次、折りたたみ）が
失われるので API が 422 で拒否する。送る前に止め、HTML で送り直す手順を理由に書く。

フックの契約（stdin に JSON、stdout に hookSpecificOutput）をそのまま叩く。

実行: python3 -m unittest tests.test_guard_confluence_markdown
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "hooks" / "guard-confluence-markdown.py"
SETTINGS = json.loads((REPO_ROOT / "settings.json.template").read_text(encoding="utf-8"))
CODEX_HOOKS = (REPO_ROOT / "codex" / "hooks.json").read_text(encoding="utf-8")
UPDATE = "mcp__atlassian-http__updateConfluencePage"
MATCHER = "mcp__.*__updateConfluencePage"
CONVERTER = "~/.claude/bin/md-to-confluence-html.py"


def run_raw(stdin):
    result = subprocess.run([sys.executable, str(GUARD)], input=stdin, capture_output=True, text=True)
    output = json.loads(result.stdout) if result.stdout.strip() else {}
    return result, output


def run_hook(tool_name, tool_input):
    return run_raw(json.dumps({"tool_name": tool_name, "tool_input": tool_input}))


def decision_of(output):
    return output.get("hookSpecificOutput", {}).get("permissionDecision")


def reason_of(output):
    return output.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


class GuardConfluenceMarkdownTests(unittest.TestCase):
    def update_input(self, **fields):
        return {"cloudId": "c", "pageId": "123", "body": "# 見出し\n\n本文", **fields}

    def test_markdown_update_is_denied(self):
        result, output = run_hook(UPDATE, self.update_input(contentFormat="markdown"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(decision_of(output), "deny", output)

    def test_reason_explains_how_to_resend_as_html(self):
        _, output = run_hook(UPDATE, self.update_input(contentFormat="markdown"))
        reason = reason_of(output)
        for marker in ("contentFormat: html", "getConfluencePage", "getContentFormatGuide", CONVERTER):
            with self.subTest(marker=marker):
                self.assertIn(marker, reason)

    def test_reason_asks_to_finish_japanese_review_before_converting(self):
        # jp-doc-review と並列に動くので、レビュー後の下書きを変換する順番を理由で指示する
        _, output = run_hook(UPDATE, self.update_input(contentFormat="markdown"))
        reason = reason_of(output)
        self.assertIn("jp-doc-review", reason)
        self.assertIn("レビュー後の下書き", reason)

    def test_format_is_compared_case_insensitively(self):
        _, output = run_hook(UPDATE, self.update_input(contentFormat=" Markdown "))
        self.assertEqual(decision_of(output), "deny", output)

    def test_other_server_prefix_is_denied(self):
        _, output = run_hook("mcp__atlassian__updateConfluencePage", self.update_input(contentFormat="markdown"))
        self.assertEqual(decision_of(output), "deny", output)

    def test_html_adf_and_default_format_pass(self):
        for fields in ({"contentFormat": "html"}, {"contentFormat": "adf"}, {}):
            with self.subTest(fields=fields):
                result, output = run_hook(UPDATE, self.update_input(**fields))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, {})

    def test_create_page_with_markdown_passes(self):
        # 新規作成には失う既存マクロが無い
        _, output = run_hook("mcp__atlassian-http__createConfluencePage",
                             {"cloudId": "c", "spaceId": "1", "body": "# x", "contentFormat": "markdown"})
        self.assertEqual(output, {})

    def test_unreadable_input_asks(self):
        # 検査できなかったときは通さず、ユーザーに確かめる（終了コード1では止まらず送られる）
        for stdin in ("not json", json.dumps({"tool_name": UPDATE, "tool_input": "markdown"})):
            with self.subTest(stdin=stdin):
                result, output = run_raw(stdin)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(decision_of(output), "ask", output)


def guarded(script):
    path = f"~/.claude/hooks/{script}"
    return (f"if [ -f {path} ]; then python3 {path}; else echo '{{\"systemMessage\":\"フック（{path}）が"
            "見つからないので検査しなかった。設定リポジトリのブランチを切り替えたなら bash setup.sh --claude を実行する\"}'; fi")


class GuardConfluenceMarkdownWiringTests(unittest.TestCase):
    def groups(self):
        return [g for g in SETTINGS["hooks"]["PreToolUse"] if g.get("matcher") == MATCHER]

    def test_registered_as_its_own_pre_tool_use_group(self):
        [group] = self.groups()
        self.assertEqual([h["command"] for h in group["hooks"]], [guarded("guard-confluence-markdown.py")])
        self.assertEqual([h["timeout"] for h in group["hooks"]], [10])

    def test_matcher_catches_only_page_updates(self):
        pattern = re.compile(f"^(?:{MATCHER})$")
        self.assertTrue(pattern.match(UPDATE))
        for name in ("createConfluencePage", "getConfluencePage", "updateConfluencePageX"):
            with self.subTest(name=name):
                self.assertFalse(pattern.match(f"mcp__atlassian-http__{name}"))

    def test_not_registered_for_codex(self):
        self.assertNotIn("guard-confluence-markdown", CODEX_HOOKS)


if __name__ == "__main__":
    unittest.main()
