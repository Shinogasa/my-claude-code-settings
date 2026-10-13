#!/usr/bin/env python3
"""hooks/jp-doc-lint.py（jp-doc-reviewerが使うyomiyasuリンターのラッパー）を検証する。

本物のリンターはsubmodule（skills/yomiyasu）のものを使う。リンターが失敗する場面だけ偽物に差し替える。

実行: python3 -m unittest tests.test_jp_doc_lint
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "hooks" / "jp-doc-lint.py"
REAL_SKILL = REPO_ROOT / "skills" / "yomiyasu" / "SKILL.md"
# yomiyasuのSlop語彙「手触り」を含む文。Markdownでは警告が出る
SLOP_SENTENCE = "この設計には独特の手触りがあり、使っていて楽しい。"
CANNOT_CHECK = "検査できなかった"


class WrapperCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.skill = REAL_SKILL

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.base / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_wrapper(self, *args):
        env = {**os.environ, "JP_DOC_REVIEW_YOMIYASU_SKILL": str(self.skill)}
        return subprocess.run([sys.executable, str(WRAPPER), *map(str, args)],
                              capture_output=True, text=True, env=env, timeout=30)

    def fake_linter(self, body):
        """scripts/yomiyasu_lint.py に偽物を置き、そのSKILL.mdを指す。"""
        script = self.base / "fake" / "scripts" / "yomiyasu_lint.py"
        script.parent.mkdir(parents=True)
        script.write_text(body, encoding="utf-8")
        self.skill = self.base / "fake" / "SKILL.md"
        self.skill.write_text("", encoding="utf-8")


class HtmlTests(WrapperCase):
    def test_html_paragraph_is_checked_as_text(self):
        draft = self.write("d.html", f"<p>{SLOP_SENTENCE}</p>\n")
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("手触り", result.stdout)

    def test_single_line_html_is_split_into_blocks(self):
        # 10/13の下書きは1行のHTMLだった。ブロックごとに行を分けて、文の数え方を崩さない
        draft = self.write("d.html", f"<h1>見出し</h1><p>{SLOP_SENTENCE}</p><ul><li>項目です。</li></ul>")
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("手触り", result.stdout)

    def test_script_and_style_are_not_text(self):
        draft = self.write("d.html", f"<style>p{{color:red}}</style><script>var a='手触り';</script><p>普通の文です。</p>")
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("手触り", result.stdout)

    def test_html_without_text_cannot_be_checked(self):
        draft = self.write("d.html", '<ac:structured-macro ac:name="toc"/>\n')
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)


class MarkdownTests(WrapperCase):
    def test_markdown_is_checked_as_is(self):
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE + "\n"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("手触り", result.stdout)

    def test_markdown_made_only_of_tags_cannot_be_checked(self):
        # リンターは < で始まる行を外す。形式を問わず、0文字は「問題なし」にしない
        result = self.run_wrapper(self.write("a.md", f"<p>{SLOP_SENTENCE}</p>\n"))
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)


class FailureTests(WrapperCase):
    def test_linter_failure_cannot_be_checked(self):
        self.fake_linter("import sys\nsys.exit(3)\n")
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE))
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)

    def test_unexpected_linter_output_cannot_be_checked(self):
        self.fake_linter("print('not json')\n")
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE))
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)

    def test_missing_linter_cannot_be_checked(self):
        self.skill = self.base / "nowhere" / "SKILL.md"
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE))
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)

    def test_missing_file_cannot_be_checked(self):
        result = self.run_wrapper(self.base / "missing.md")
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)

    def test_wrong_number_of_arguments_is_usage_error(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
